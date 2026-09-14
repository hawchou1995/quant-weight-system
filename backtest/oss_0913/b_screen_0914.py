# -*- coding: utf-8 -*-
"""B 族（全库未测 4 候选）IC/相关性快筛 —— PRE-REGISTRATION_20260914 §三
B1 break_retest: 60日新高突破后 5 日内缩量回踩不破前高（真突破）
B2 vol_ratio_15: 5日均量/20日均量 ≥1.5（量能放大）
B3 turn_avoid:   日换手率 <10%（规避高换手）
B4 amount_chg:   20日成交额分位 - 20日前分位（资金关注度变化）
"""
import sys, json, time
import numpy as np, pandas as pd
from pathlib import Path
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
sys.path.insert(0, str(OUT))
import oss_super_prod_0913 as S
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

O, H, L, C, V, AMT = S.O, S.H, S.L, S.C, S.V, S.AMT
FMV = S.P["fmv"].astype(np.float64)
close_ff, ELIG3 = S.close_ff, S.ELIG_SUPER
WARMUP = S.WARMUP
ND, NC = close_ff.shape

def rollx(mat, w, mp, how="mean"):
    r = pd.DataFrame(mat).rolling(w, min_periods=mp)
    return (r.mean() if how == "mean" else r.max()).to_numpy()

hi60p = pd.DataFrame(H).rolling(60, min_periods=40).max().shift(1).to_numpy()
v20 = rollx(V, 20, 15); v5 = rollx(V, 5, 5)
v5max = pd.DataFrame(V).rolling(5, min_periods=2).max().to_numpy()
TURNd = np.where(FMV > 0, AMT / FMV, np.nan)

with np.errstate(all="ignore"):
    bk = (close_ff > hi60p) & np.isfinite(hi60p)
    bk5 = pd.DataFrame(bk).rolling(5, min_periods=1).max().to_numpy() > 0
    shrink = np.isfinite(v5max) & (V <= 0.7 * v5max)
    hold = close_ff >= hi60p
    B1 = np.where(bk5 & np.isfinite(hi60p), (shrink & hold).astype(float), np.nan)

    vr = v5 / (v20 + 1e-12)
    B2 = np.where(np.isfinite(vr) & (v20 > 0), (vr >= 1.5).astype(float), np.nan)

    B3 = np.where(np.isfinite(TURNd), (TURNd < 0.10).astype(float), np.nan)

    A20 = rollx(AMT, 20, 15)
    rk = pd.DataFrame(np.where(ELIG3, A20, np.nan)).rank(axis=1, pct=True).to_numpy()
    rk_prev = np.vstack([np.full((20, NC), np.nan), rk[:-20]])
    B4 = rk - rk_prev

BF = dict(break_retest=B1, vol_ratio_15=B2, turn_avoid=B3, amount_rank_chg=B4)

fwdH = np.full((ND, NC), np.nan)
fwdH[:ND-1-20] = O[21:] / O[1:ND-20] - 1
def rank_ic(mat):
    a = np.where(ELIG3 & np.isfinite(mat), mat, np.nan)
    r = pd.DataFrame(a).rank(axis=1).to_numpy()
    zy = pd.DataFrame(np.where(ELIG3 & np.isfinite(fwdH), fwdH, np.nan)).rank(axis=1).to_numpy()
    zf = r - np.nanmean(r, axis=1, keepdims=True); zz = zy - np.nanmean(zy, axis=1, keepdims=True)
    zf = zf / (np.nanstd(zf, axis=1, keepdims=True) + 1e-12); zz = zz / (np.nanstd(zz, axis=1, keepdims=True) + 1e-12)
    both = np.isfinite(zf) & np.isfinite(zz)
    n = both.sum(axis=1)
    ic = np.where(n > 50, np.nansum(np.where(both, zf * zz, 0), axis=1) / np.maximum(n, 1), np.nan)
    v = ic[np.isfinite(ic)]
    return float(v.mean()), float(v.mean() / (v.std() + 1e-12)), float((v > 0).mean())

T0 = np.where(np.isfinite(TURNd), TURNd, 0.0)
W60 = pd.DataFrame(T0).rolling(60, min_periods=40).sum().to_numpy()
VC60 = pd.DataFrame(close_ff * T0).rolling(60, min_periods=40).sum().to_numpy()
VW60 = VC60 / (W60 + 1e-12)
extra = dict(turn20=pd.DataFrame(T0).rolling(20, min_periods=15).mean().to_numpy(),
             cost_bias_rev=np.where(W60 > 0, -(close_ff / (VW60 + 1e-12) - 1), np.nan))
REFS = {**{k: S.ALL[k] for k in S.PICKED}, **extra}

res = {}
log("B 族 IC 表:")
for k, m in BF.items():
    ic, icir, posr = rank_ic(m)
    cov = float(np.isfinite(np.where(ELIG3, m, np.nan)).sum() / max(1, ELIG3.sum()))
    res[k] = dict(ic=ic, icir=icir, pos_rate=posr, coverage=cov)
    log(f"  {k:18s} IC={ic:+.4f} ICIR={icir:+.3f} 正IC占比={posr:.0%} 覆盖={cov:.0%}")

sample = np.arange(WARMUP, ND, 3)
def zmat(mat, ic=0.0):
    s = 1.0 if ic >= 0 else -1.0
    a = (mat * s)[sample]
    a = np.where(np.isfinite(a) & ELIG3[sample], a, np.nan)
    mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
    return np.clip((a - mu) / (sd + 1e-12), -8, 8)
log("相关性:")
for k, m in BF.items():
    ZN = zmat(m, res[k]["ic"])
    worst = []
    for rk, rm in REFS.items():
        Zk = zmat(rm)
        mm = np.isfinite(ZN) & np.isfinite(Zk)
        if mm.sum() < 500: continue
        worst.append((rk, float(np.corrcoef(ZN[mm], Zk[mm])[0, 1])))
    worst.sort(key=lambda x: -abs(x[1]))
    mx = abs(worst[0][1]) if worst else 0.0
    res[k]["rho_max"] = mx; res[k]["rho_top3"] = worst[:3]
    res[k]["pass"] = (abs(res[k]["ic"]) >= 0.02) and (mx < 0.6)
    log(f"  {k:18s} ρmax={mx:.3f} ({worst[0][0]}) → {'进组合级' if res[k]['pass'] else '筛除'}")

json.dump(res, open(OUT / "b_screen_0914.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
n = sum(1 for v in res.values() if v.get("pass"))
log(f"结论: {n}/4 进入组合级 | saved b_screen_0914.json")
