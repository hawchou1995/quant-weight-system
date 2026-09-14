# -*- coding: utf-8 -*-
"""打板优化轮 · 优化后配置的完整回测表现（R-daban-opt-0915 第三部分）
- 组合 × TP 矩阵（事件级，含成本）
- 5 槽位组合模拟（启用现行风控规则：单日进场≤5、每笔 1/5 仓、并发占用计槽）
  说明：出场时点用各事件基准卖出日近似（tp 变体的实际出场 ≤ 基准出场，占用差 0-1 日）
输出：daban_opt3_0915.json + 控制台表
"""
import os, json
import numpy as np, pandas as pd
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
E = pd.read_csv(os.path.join(HERE, "daban_events_0915.csv"))
E['year'] = E.buy.str[:4]
q33r, q67a = E.f_r20.quantile(1/3), E.f_adx.quantile(2/3)
q20r, q80a = E.f_r20.quantile(0.2), E.f_adx.quantile(0.8)

COH = {
    "BASE(现行)": E,
    "R20L33": E[E.f_r20 <= q33r],
    "ADXH67": E[E.f_adx >= q67a],
    "COMBO(33×67)": E[(E.f_r20 <= q33r) & (E.f_adx >= q67a)],
    "COMBO_TIGHT(20×80)": E[(E.f_r20 <= q20r) & (E.f_adx >= q80a)],
}
TP_COLS = ["base_net"] + [f"tp{t}_{f}" for t in (4, 5, 6, 7, 8, 9, 10, 12) for f in ("tp_t2", "tp_t1")]


def est(sub, col):
    f = sub[col].values
    return dict(n=len(f), mean=float(np.mean(f)), med=float(np.median(f)), wr=float((f > 0).mean()))


print("=== 组合 × TP 矩阵（单笔，含成本；每格 mean/med）===")
grid = {}
hdr = "队列               " + "".join(f"{c.replace('base_net','base').replace('_tp_t2','t2').replace('_tp_t1','t1'):>16s}" for c in TP_COLS)
print(hdr)
for k, sub in COH.items():
    row = []
    grid[k] = {}
    for c in TP_COLS:
        s = est(sub, c)
        grid[k][c] = s
        row.append(f"{s['mean']*100:+.2f}/{s['med']*100:+.2f}")
    print(f"{k:18s} " + "".join(f"{x:>16s}" for x in row))


def nav_sim(sub, col, cap=5, w=0.2, start_eq=1.0):
    """5 槽位：进场按买入日排序，占用=买入→基准卖出日；满槽跳过；退出日实现"""
    sub = sub.sort_values(['buy'])
    open_slots = []          # (exit_date, net)
    eq = start_eq
    curve = []
    skipped = 0
    events = []
    for _, r in sub.iterrows():
        b, x, net = r['buy'], r['base_sell'], r[col]
        # 释放已到期
        open_slots = [(xd, nt) for (xd, nt) in open_slots if xd >= b]
        if len(open_slots) >= cap:
            skipped += 1
            continue
        open_slots.append((x, net))
        events.append((x, net))
    byexit = defaultdict(list)
    for x, net in events:
        byexit[x].append(net)
    for d in sorted(byexit):
        for net in byexit[d]:
            eq *= (1 + w * net)
        curve.append((d, eq))
    c = pd.Series([v for _, v in curve], index=pd.to_datetime([d for d, _ in curve]))
    dd = float((c / c.cummax() - 1).min())
    yrs = (pd.Timestamp(curve[-1][0]) - pd.Timestamp(sub.buy.min())).days / 365.25 if curve else np.nan
    cagr = float(eq ** (1 / yrs) - 1) if yrs and yrs > 1 else np.nan
    return dict(total=float(eq - 1), cagr=cagr, maxdd=dd, n_taken=len(events), n_skipped=skipped, years=float(yrs))


print("\n=== 5 槽位组合模拟（含成本；每笔 1/5 仓；满槽跳过）===")
res = {}
PICK = [("BASE(现行)", "BASE(现行)", "base_net"),
        ("COMBO(33×67)", "COMBO(33×67)", "base_net"),
        ("COMBO_TIGHT(20×80)", "COMBO_TIGHT(20×80)", "base_net"),
        ("COMBO(33×67)+tp6t2", "COMBO(33×67)", "tp6_tp_t2"),
        ("COMBO(33×67)+tp5t1", "COMBO(33×67)", "tp5_tp_t1"),
        ("COMBO_TIGHT+tp5t1", "COMBO_TIGHT(20×80)", "tp5_tp_t1"),
        ("R20L33", "R20L33", "base_net"),
        ("ADXH67", "ADXH67", "base_net")]
for label, coh, col in PICK:
    sub = COH[coh]
    v = nav_sim(sub, col)
    v['es'] = est(sub, col)
    res[f"{label}|{col}"] = v
    print(f"{label:22s}[{col:11s}] 笔数 {v['n_taken']:4d}(+跳 {v['n_skipped']:3d}) 单笔 {v['es']['mean']*100:+.2f}%/{v['es']['med']*100:+.2f}% "
          f"wr {v['es']['wr']*100:.1f}% | 组合 {v['total']*100:+.1f}% 年化 {v['cagr']*100:+.2f}% 回撤 {v['maxdd']*100:.1f}%")

print("\n=== 差窗口（2024-05 后，现行盘所在 regime）===")
E2 = E[E.buy >= "2024-05-01"]
for k in ("BASE(现行)", "R20L33", "ADXH67", "COMBO(33×67)"):
    sub = E2[E2.index.isin(COH[k].index)] if k != "BASE(现行)" else E2
    s = est(sub, "base_net")
    print(f"{k:18s} n={s['n']:4d} 单笔 {s['mean']*100:+.2f}%/{s['med']*100:+.2f}% wr {s['wr']*100:.1f}%")

print("\n=== COMBO(33×67) 分年度（单笔 mean/med, n）===")
for y, g in COH["COMBO(33×67)"].groupby('year'):
    if len(g) >= 5:
        print(f"  {y}: n={len(g):3d} mean {g.base_net.mean()*100:+.2f}% med {g.base_net.median()*100:+.2f}% wr {(g.base_net>0).mean()*100:.0f}%")

json.dump({"grid": grid, "nav": res}, open(os.path.join(HERE, "daban_opt3_0915.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1, default=float)
print("\nsaved daban_opt3_0915.json")
