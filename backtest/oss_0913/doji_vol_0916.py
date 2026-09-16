# -*- coding: utf-8 -*-
"""十字星 × 巨量 × 低位 —— 事件级终审实验（R-doji-vol-0916）

预注册（三份外部方案 + 本方推荐一致）：
  层级   Q1(b) 只做事件级快筛，不上组合级（ADR-0004 精神）
  十字星 S1 实体型 |C−O|/O ≤ 0.5% ｜ S2 影线型 (H−L)/O ≥ 2% ∧ (H−L)/O ≥ 2×|C−O|/O
  巨量   V90/V95 = 成交量对 120 日滚动分位 > 90% / > 95%
  低位   P10/P20/P30 = 收盘对 120 日滚动分位 < 10% / 20% / 30%
  臂账   2 × 2 × 3 = 12 臂 + 边际臂（单条件 / A∩B / A∩B∩C）
  门     超额 ≥ +0.30pp ∧ t(日聚类) ≥ 3 ∧ 分年度 ≥4/6 为正
硬约束：T+1 开盘买→T+5/T+20 收盘卖；成本往返 55bp（另报 115bp 保守档）；
        标签显式切片（trap#30 禁 vstack）；排 ST/退(PIT)/停牌/上市<120日/C<2；
        样本<100 判不可靠；同轮廓安慰剂 20 seeds；保留连续分位做剂量曲线；
        交互项增量 Edge_{A∩B∩C} − Edge_A − Edge_B − Edge_C。
"""
import json
import os
import pickle

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
OUT = os.path.join(HERE, "doji_vol_0916.json")
COST_RT, COST_CONS = 0.0055, 0.0115
HS = (5, 20)
W = 120

print("[1/5] 载入面板…", flush=True)
P = pickle.load(open(os.path.join(HERE, "oss_panel_0913.pkl"), "rb"))
cal = pd.to_datetime(P["cal"]); codes = np.asarray(P["codes"])
O, H, L, C, V = (P[k].astype(np.float64) for k in ("open", "high", "low", "close", "vol"))
ND, NC = C.shape
print(f"      {ND} 日 × {NC} 只（{cal[0].date()} ~ {cal[-1].date()}）", flush=True)

# ---- 逐日 ST/退（PIT）----
nh = pd.read_csv(f"{BASE}/data_fundamental/name_hist.csv", dtype={"code": str},
                 usecols=["code", "TRADE_DATE", "SECURITY_NAME_ABBR"])
nh["TRADE_DATE"] = pd.to_datetime(nh["TRADE_DATE"]).dt.normalize()
cm = {c[-6:]: i for i, c in enumerate(codes)}
nh = nh[nh["code"].isin(cm)].copy(); nh["ci"] = nh["code"].map(cm)
pv = (nh[nh["SECURITY_NAME_ABBR"].astype(str).str.contains("ST|退", na=False)]
      .pivot_table(index="TRADE_DATE", columns="ci", values="SECURITY_NAME_ABBR", aggfunc="last")
      .reindex(cal).ffill())
M = np.zeros((ND, NC), dtype=bool)
if len(pv):
    for c in pv.columns:
        M[:, int(c)] = pv[c].notna().values
print(f"      逐日 ST/退 掩码：命中 {M.sum():,} 格（{M.mean():.2%}）", flush=True)

# ---- 合格集 ----
valid = np.isfinite(O) & np.isfinite(C) & (C > 0) & np.isfinite(H) & np.isfinite(L)
ELIG = valid & ~M & (np.cumsum(valid, axis=0) >= W) & (C >= 2.0) & (V > 0)
print(f"      合格集日均 {ELIG[W:].sum(axis=1).mean():,.0f} 只", flush=True)

# ---- 形态 ----
body = np.abs(C - O) / np.where(O > 0, O, np.nan)
amp = (H - L) / np.where(O > 0, O, np.nan)
S1 = ELIG & (body <= 0.005)
S2 = ELIG & (amp >= 0.02) & (amp >= 2.0 * body)
print(f"      S1 实体型 {int(S1.sum()):,} ｜ S2 影线型 {int(S2.sum()):,}", flush=True)

# ---- 滚动分位（pandas 原生 rolling.rank，Cython 实现）----
print("[2/5] 120 日滚动分位…", flush=True)
rankW = pd.DataFrame(V).rolling(W, min_periods=100).rank(pct=True).to_numpy(dtype=np.float64)
posW = pd.DataFrame(C).rolling(W, min_periods=100).rank(pct=True).to_numpy(dtype=np.float64)
print("      done", flush=True)

# ---- 标签（显式切片）----
fwd, base_h = {}, {}
for h in HS:
    f = np.full((ND, NC), np.nan)
    if ND > h + 1:
        f[: ND - h - 1] = C[h + 1:] / O[1: ND - h] - 1.0
    fwd[h] = f
    m = np.where(ELIG & np.isfinite(f), f, np.nan)
    base_h[h] = np.nanmean(m, axis=1)

print("[3/5] 臂位…", flush=True)


def stats(mask, h):
    ev = mask & np.isfinite(fwd[h])
    idx = np.argwhere(ev)
    if len(idx) < 1:
        return dict(n=0)
    di, ci = idx[:, 0], idx[:, 1]
    r = fwd[h][di, ci]
    ex = r - base_h[h][di]
    s = pd.Series(ex, index=cal[di])
    dd = s.groupby(level=0).mean()
    t = float(dd.mean() / (dd.std(ddof=1) / np.sqrt(len(dd)))) if len(dd) > 2 else float("nan")
    byy = s.groupby(s.index.year).mean()
    return dict(n=int(len(r)), gross=float(r.mean()), net=float(r.mean() - COST_RT),
                net_cons=float(r.mean() - COST_CONS), excess=float(ex.mean()), t_day=t,
                win=float((r > 0).mean()), med=float(np.median(r)),
                by_year={str(k): float(v) for k, v in byy.items()},
                pos_years=int(sum(1 for v in byy.values if v > 0)), n_years=int(len(byy)),
                volpct_med=float(np.nanmedian(rankW[di, ci])), pospct_med=float(np.nanmedian(posW[di, ci])))


res = {"arms": {}, "marginal": {}, "dose": {}, "meta": dict(
    window=[str(cal[0].date()), str(cal[-1].date())], n_days=ND, n_codes=NC,
    cost_round=COST_RT, elig_med=float(np.median(ELIG[W:].sum(axis=1))),
    s1=int(S1.sum()), s2=int(S2.sum()))}

arm_defs = []
for sn, Sm in (("S1实体", S1), ("S2影线", S2)):
    for vn, vt in (("V90", 0.90), ("V95", 0.95)):
        for pn, pt in (("P10", 0.10), ("P20", 0.20), ("P30", 0.30)):
            arm_defs.append((f"{sn}+{vn}+{pn}", Sm & (rankW > vt) & (posW < pt)))

for name, mask in arm_defs:
    res["arms"][name] = {f"H{h}": stats(mask, h) for h in HS}
    a = res["arms"][name]["H5"]
    if a.get("n", 0) >= 100:
        print(f"  {name:18s} H5 n={a['n']:>7,} 超额 {a['excess']*100:+6.3f}pp t={a['t_day']:6.2f} "
              f"胜率 {a['win']:5.1%} 净 {a['net']*100:+.2f}% 分年正 {a['pos_years']}/{a['n_years']}", flush=True)

marg = {"A_十字星S1": S1, "A2_十字星S2": S2,
        "B_巨量V90": ELIG & (rankW > 0.90), "B2_巨量V95": ELIG & (rankW > 0.95),
        "C_低位P20": ELIG & (posW < 0.20),
        "AB_S1V90": S1 & (rankW > 0.90), "ABC_S1V90P20": S1 & (rankW > 0.90) & (posW < 0.20),
        "BASE_全池": ELIG.copy()}
for name, mask in marg.items():
    res["marginal"][name] = {f"H{h}": stats(mask, h) for h in HS}
print("  边际臂(H5 超额):", {k: f"{v['H5'].get('excess', np.nan)*100:+.3f}pp(n={v['H5'].get('n',0)})"
                            for k, v in res["marginal"].items()}, flush=True)

e = lambda k: res["marginal"][k]["H5"].get("excess", np.nan)
res["interaction"] = dict(
    A=e("A_十字星S1"), B=e("B_巨量V90"), C=e("C_低位P20"), AB=e("AB_S1V90"), ABC=e("ABC_S1V90P20"),
    delta_AB=e("AB_S1V90") - e("A_十字星S1") - e("B_巨量V90"),
    delta_ABC=e("ABC_S1V90P20") - e("A_十字星S1") - e("B_巨量V90") - e("C_低位P20"))
it = res["interaction"]
print(f"\n  交互分解(H5)：A {it['A']*100:+.3f} | B {it['B']*100:+.3f} | C {it['C']*100:+.3f} "
      f"| A∩B {it['AB']*100:+.3f} | A∩B∩C {it['ABC']*100:+.3f} pp", flush=True)
print(f"                Δ(A∩B)={it['delta_AB']*100:+.3f}pp  Δ(A∩B∩C)={it['delta_ABC']*100:+.3f}pp", flush=True)

print("\n[4/5] 剂量曲线（H5 超额）…", flush=True)
for sn, Sm in (("S1实体", S1), ("S2影线", S2)):
    for cn, A in (("vol分位", rankW), ("pos分位", posW)):
        row = {}
        for lo, hi in ((0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 0.95), (0.95, 0.99), (0.99, 1.01)):
            m = Sm & (A >= lo) & (A < hi) & np.isfinite(fwd[5])
            if m.sum() >= 100:
                di = np.argwhere(m)[:, 0]
                row[f"{lo:.2f}~{hi:.2f}"] = float(np.nanmean(fwd[5][m] - base_h[5][di]))
        res["dose"][f"{sn}_{cn}"] = row
        print(f"  {sn} × {cn}: " + "  ".join(f"{k}:{v*100:+.3f}" for k, v in row.items()), flush=True)

print("\n[5/5] 同轮廓安慰剂（20 seeds，H5）…", flush=True)
rng = np.random.default_rng(20260916)
real = res["arms"]["S1实体+V90+P20"]["H5"]
ph = []
elig_idx = [np.flatnonzero(ELIG[i]) for i in range(ND)]
n_day = np.array([int((S1 & (rankW > 0.90) & (posW < 0.20))[i].sum()) for i in range(ND)])
for seed in range(20):
    r2 = np.random.default_rng(seed)
    vals = []
    for i in np.flatnonzero(n_day > 0):
        cand = elig_idx[i]
        k = min(n_day[i], len(cand))
        pick = r2.choice(cand, size=k, replace=False)
        ok = np.isfinite(fwd[5][i, pick])
        if ok.any():
            vals.append(float(np.mean(fwd[5][i, pick][ok] - base_h[5][i])))
    ph.append(float(np.mean(vals)) if vals else np.nan)
ph = np.array([p for p in ph if np.isfinite(p)])
pval = float((ph >= real.get("excess", np.nan)).mean()) if len(ph) else np.nan
print(f"  real 超额 {real.get('excess', np.nan)*100:+.3f}pp | placebo 中位 {np.nanmedian(ph)*100:+.3f}pp "
      f"最大 {np.nanmax(ph)*100:+.3f}pp → p={pval:.3f}", flush=True)
res["placebo"] = dict(real=float(real.get("excess", np.nan)), med=float(np.nanmedian(ph)),
                      mx=float(np.nanmax(ph)), p=pval, seeds=int(len(ph)))

json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
print(f"\n[doji] 落盘 {OUT}")
