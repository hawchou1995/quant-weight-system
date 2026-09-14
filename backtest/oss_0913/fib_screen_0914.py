# -*- coding: utf-8 -*-
"""A 族（黄金分割 6 因子）IC/相关性快筛 —— 预注册 PRE-REGISTRATION_20260914_fib_三线.md §二
规则：rank IC 过 0.02 且 |ρ|<0.6（vs SUPER picked 13 + turn + cost_bias_rev）才进组合级。
预期自检：A1 retrace_depth 应与 dd120/neg_sspace 高度共线（几何同构）——若不然说明实现有偏。
"""
import sys, json, time
import numpy as np, pandas as pd
from pathlib import Path
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
sys.path.insert(0, str(OUT))
import oss_super_prod_0913 as S   # ALL(20因子)/PICKED/ELIG_SUPER/P 等
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

O, H, L, C = S.O, S.H, S.L, S.C
AMT, FMV = S.AMT, S.P["fmv"].astype(np.float64)
close_ff = S.close_ff
ELIG3 = S.ELIG_SUPER
WARMUP = S.WARMUP
ND, NC = close_ff.shape

def roll_min(mat, w, mp):
    return pd.DataFrame(mat).rolling(w, min_periods=mp).min().to_numpy()
def roll_max(mat, w, mp):
    return pd.DataFrame(mat).rolling(w, min_periods=mp).max().to_numpy()

hi60, lo60 = roll_max(H, 60, 40), roll_min(L, 60, 40)
hi120, lo120 = roll_max(H, 120, 80), roll_min(L, 120, 80)
hi250, lo250 = roll_max(H, 250, 170), roll_min(L, 250, 170)

with np.errstate(all="ignore"):
    rng120 = hi120 - lo120
    fib = {Lv: lo120 + rng120 * Lv for Lv in (0.236, 0.382, 0.5, 0.618, 0.809)}
    A1 = (hi120 - close_ff) / (rng120 + 1e-12)
    dists = np.stack([np.abs(close_ff - fib[Lv]) / (close_ff + 1e-12) for Lv in (0.236, 0.382, 0.5, 0.618, 0.809)])
    A2 = -np.nanmin(dists, axis=0)
    A2 = np.where(np.isfinite(rng120) & (rng120 > 0), A2, np.nan)
    A3 = np.where(np.isfinite(fib[0.382]), (close_ff >= fib[0.382]).astype(float), np.nan)
    A4 = np.where(np.isfinite(fib[0.618]), (close_ff >= fib[0.618]).astype(float), np.nan)
    # A5 近5日曾破 0.618 且当前收回
    below = (close_ff < fib[0.618]) & np.isfinite(fib[0.618])
    was_below5 = pd.DataFrame(below).rolling(5, min_periods=1).max().to_numpy() > 0
    A5 = np.where(was_below5 & (close_ff >= fib[0.618]) & np.isfinite(fib[0.618]), 1.0,
         np.where(was_below5 & np.isfinite(fib[0.618]), 0.0, np.nan))
    # A6 三窗口 0.618 上方一致计数
    f60 = lo60 + (hi60 - lo60) * 0.618
    f250 = lo250 + (hi250 - lo250) * 0.618
    cnt = ((close_ff >= fb).astype(float) for fb in (f60, fib[0.618], f250))
    A6 = np.sum(list(cnt), axis=0)
    A6 = np.where(np.isfinite(f60) & np.isfinite(fib[0.618]) & np.isfinite(f250), A6, np.nan)

FIB = dict(retrace_depth=A1, fib_prox=A2, z_382=A3, z_618=A4, fib_hold_618=A5, fib_scale_agree=A6)

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

# 对照因子：SUPER picked 13 + turn20 + cost_bias_rev
TURN = np.where(FMV > 0, AMT / FMV, np.nan)
T0 = np.where(np.isfinite(TURN), TURN, 0.0)
W60 = pd.DataFrame(T0).rolling(60, min_periods=40).sum().to_numpy()
VC60 = pd.DataFrame(close_ff * T0).rolling(60, min_periods=40).sum().to_numpy()
VW60 = VC60 / (W60 + 1e-12)
extra = dict(turn20=pd.DataFrame(T0).rolling(20, min_periods=15).mean().to_numpy(),
             cost_bias_rev=np.where(W60 > 0, -(close_ff / (VW60 + 1e-12) - 1), np.nan))
REFS = {**{k: S.ALL[k] for k in S.PICKED}, **extra}

log("IC 表（A 族 6 因子）:")
res = {}
for k, m in FIB.items():
    ic, icir, posr = rank_ic(m)
    res[k] = dict(ic=ic, icir=icir, pos_rate=posr)
    verdict = "PASS" if (abs(ic) >= 0.02) else "IC<0.02"
    log(f"  {k:18s} IC={ic:+.4f} ICIR={icir:+.3f} 正IC占比={posr:.0%}  {verdict}")

# 相关性（z 域，与 combo 同法）
sample = np.arange(WARMUP, ND, 3)
def zmat(mat):
    ic, *_ = rank_ic(mat)
    s = 1.0 if ic >= 0 else -1.0
    a = (mat * s)[sample]
    a = np.where(np.isfinite(a) & ELIG3[sample], a, np.nan)
    mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
    return np.clip((a - mu) / (sd + 1e-12), -8, 8)
log("相关性（vs picked13 + turn20 + cost_bias_rev）:")
for k, m in FIB.items():
    ZN = zmat(m)
    worst = []
    for rk, rm in REFS.items():
        Zk = zmat(rm)
        mm = np.isfinite(ZN) & np.isfinite(Zk)
        if mm.sum() < 500: continue
        r = float(np.corrcoef(ZN[mm], Zk[mm])[0, 1])
        worst.append((rk, r))
    worst.sort(key=lambda x: -abs(x[1]))
    top = ", ".join(f"{n}{r:+.3f}" for n, r in worst[:3])
    mx = abs(worst[0][1]) if worst else 0.0
    res[k]["rho_max"] = mx
    res[k]["rho_top3"] = worst[:3]
    res[k]["pass"] = (abs(res[k]["ic"]) >= 0.02) and (mx < 0.6)
    log(f"  {k:18s} ρmax={mx:.3f} | {top}  → {'进组合级' if res[k]['pass'] else '筛除'}")

json.dump(res, open(OUT / "fib_screen_0914.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved fib_screen_0914.json")
n_pass = sum(1 for v in res.values() if v.get("pass"))
log(f"结论: {n_pass}/6 进入组合级")
