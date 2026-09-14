# -*- coding: utf-8 -*-
"""打板优化轮 · 分年度 + 组合 + 组合NAV（预注册 R-daban-opt-0915 第二部分）
输入：daban_events_0915.csv（daban_opt_0915.py 产出）
输出：daban_opt2_0915.json
"""
import os, json
import numpy as np, pandas as pd
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
E = pd.read_csv(os.path.join(HERE, "daban_events_0915.csv"))
E['year'] = E.buy.str[:4]
print("事件", len(E))


def gates(s):
    g = [s['n'] >= 30, s['wr'] > 0.40, s['med'] > 0, s['mean'] > 0, s['ex'] is not None and s['ex'] > 0]
    return "".join("P" if x else "F" for x in g)


def cohort_stats(sub, col):
    f = sub[col].values
    return dict(n=len(f), mean=float(np.mean(f)), med=float(np.median(f)), wr=float((f > 0).mean()))


def yearly(sub, col):
    out = {}
    for y, g in sub.groupby('year'):
        if len(g) >= 10:
            f = g[col].values
            out[y] = dict(n=len(f), mean=round(float(np.mean(f)) * 100, 2), med=round(float(np.median(f)) * 100, 2),
                          wr=round(float((f > 0).mean()) * 100, 1))
    return out


def drop_year_check(sub, col):
    """剔除任一贡献年仍为正（均值）"""
    bad = []
    for y in sorted(sub.year.unique()):
        g = sub[sub.year != y]
        if len(g) >= 30 and np.mean(g[col].values) <= 0:
            bad.append(y)
    return bad


def nav_sim(sub, col, cap=5, w=0.2):
    byexit = defaultdict(list)
    for _, r in sub.iterrows():
        byexit[r['base_sell']].append(r[col])
    eq = 1.0; curve = []
    for d in sorted(byexit):
        for net in byexit[d]:
            eq *= (1 + w * net)
        curve.append((d, eq))
    if not curve:
        return None
    c = pd.Series([x[1] for x in curve], index=pd.to_datetime([x[0] for x in curve]))
    dd = float((c / c.cummax() - 1).min())
    return dict(total=float(c.iloc[-1] - 1), maxdd=dd, n=len(sub))


# 并发检查（若超 cap，NAV 仅作相对比较）
occ = defaultdict(int)
for _, r in E.iterrows():
    for d in pd.date_range(r['buy'], r['base_sell']):
        occ[d.strftime('%Y-%m-%d')] += 1
occ_v = pd.Series(occ)
print(f"并发持仓：max {occ_v.max()} / p95 {occ_v.quantile(0.95):.0f} / 均值(有持仓日) {occ_v.mean():.1f}")

q20_r20 = E.f_r20.quantile(0.2); q33_r20 = E.f_r20.quantile(1/3)
q80_adx = E.f_adx.quantile(0.8); q67_adx = E.f_adx.quantile(2/3)
q80_zt = E.s_zt.quantile(0.8)

COH = {
    "BASE": E,
    "R20L20": E[E.f_r20 <= q20_r20].copy(),
    "R20L33": E[E.f_r20 <= q33_r20].copy(),
    "ADXH67": E[E.f_adx >= q67_adx].copy(),
    "ADXH80": E[E.f_adx >= q80_adx].copy(),
    "COMBO_R20L33xADXH67": E[(E.f_r20 <= q33_r20) & (E.f_adx >= q67_adx)].copy(),
    "COMBO_R20L20xADXH80": E[(E.f_r20 <= q20_r20) & (E.f_adx >= q80_adx)].copy(),
    "COMBO_BASE_tp6": None,   # 占位：组合用 tp6 出场
    "SZT80": E[E.s_zt >= q80_zt].copy(),
    "COMBO+SZT80": E[(E.f_r20 <= q33_r20) & (E.f_adx >= q67_adx) & (E.s_zt >= q80_zt)].copy(),
}
col_of = {k: 'base_net' for k in COH}
col_of["COMBO_BASE_tp6"] = 'tp6_tp_t2'

res = {}
print("=== 队列统计（base_net 口径；COMBO_BASE_tp6 用 tp6 出场）===")
for k, sub in list(COH.items()):
    if k == "COMBO_BASE_tp6":
        sub = COH["COMBO_R20L33xADXH67"]
    if sub is None or len(sub) < 10:
        print(f"{k:24s} n<10 跳过"); continue
    col = col_of[k]
    s = cohort_stats(sub, col)
    yr = yearly(sub, col)
    bad = drop_year_check(sub, col)
    nav = nav_sim(sub, col)
    # 超额（对全事件均值）
    s['ex'] = s['mean'] - float(E.base_net.mean())
    s['yearly'] = yr
    s['drop_year_bad'] = bad
    s['nav'] = nav
    res[k] = s
    posyr = sum(1 for v in yr.values() if v['mean'] > 0)
    print(f"{k:24s} n={s['n']:4d} mean={s['mean']*100:+.2f}% med={s['med']*100:+.2f}% wr={s['wr']*100:.1f}% "
          f"ex={s['ex']*100:+.2f}% | 年正 {posyr}/{len(yr)} | 剔年劣化 {bad if bad else '无'} | "
          f"NAV {nav['total']*100:+.1f}% DD {nav['maxdd']*100:.1f}% | 闸 {gates(s)}")

# 2×2：r20 × adx
print()
print("=== 2×2（r20 低33 × adx 高67，base_net）===")
for r20lo in (True, False):
    row = []
    for adxhi in (True, False):
        m = ((E.f_r20 <= q33_r20) if r20lo else (E.f_r20 > q33_r20)) & ((E.f_adx >= q67_adx) if adxhi else (E.f_adx < q67_adx))
        sub = E[m]
        if len(sub) >= 10:
            row.append(f"n={len(sub):4d} mean={sub.base_net.mean()*100:+.2f}% med={sub.base_net.median()*100:+.2f}%")
        else:
            row.append(f"n={len(sub)}")
    print(f"r20{'低' if r20lo else '高'}33: adx高 {row[0]} | adx低 {row[1]}")

# 正交性
print()
print("=== 正交性（事件样本内 Spearman）===")
sub = E[['f_r20', 'f_adx', 'rp', 'f_amt20']].dropna()
print("rho(r20,adx)=", round(sub.f_r20.corr(sub.f_adx, method='spearman'), 3),
      "| rho(r20,rp)=", round(sub.f_r20.corr(sub.rp, method='spearman'), 3),
      "| rho(adx,rp)=", round(sub.f_adx.corr(sub.rp, method='spearman'), 3),
      "| rho(adx,amt20)=", round(sub.f_adx.corr(sub.f_amt20, method='spearman'), 3))
print("rp 分布: BASE 均值", round(E.rp.mean(), 3), "| R20L33 均值", round(E[E.f_r20 <= q33_r20].rp.mean(), 3),
      "| ADXH67 均值", round(E[E.f_adx >= q67_adx].rp.mean(), 3))

json.dump(res, open(os.path.join(HERE, "daban_opt2_0915.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1, default=float)
print("\nsaved daban_opt2_0915.json")
