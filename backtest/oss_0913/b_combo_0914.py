# -*- coding: utf-8 -*-
"""B 族组合级（臂1: 13+3B 合并增量）+ turn 家族头对头（turn20 vs turn_avoid → 轨A 第三因子选型）"""
import sys, json, time, math
import numpy as np, pandas as pd
from pathlib import Path
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
sys.path.insert(0, str(OUT))
import oss_super_prod_0913 as S
exec(open(OUT / "fib_combo_0914.py").read())  # 复用全部定义（含 run_engine）；会顺带重跑 fib 臂（~10s）
V, AMT = S.V, S.AMT
FMV = S.P["fmv"].astype(np.float64)
# ↑ 上面 exec 段包含 FIB3 计算与 composite()/run_engine 定义（已在本文件后续直接可用）
# ---------- B 因子 ----------
def rollx(mat, w, mp, how="mean"):
    r = pd.DataFrame(mat).rolling(w, min_periods=mp)
    return (r.mean() if how == "mean" else r.max()).to_numpy()
hi60p = pd.DataFrame(H).rolling(60, min_periods=40).max().shift(1).to_numpy()
v20 = rollx(V, 20, 15); v5 = rollx(V, 5, 5); v5max = pd.DataFrame(V).rolling(5, min_periods=2).max().to_numpy()
TURNd = np.where(FMV > 0, AMT / FMV, np.nan)
with np.errstate(all="ignore"):
    bk = (close_ff > hi60p) & np.isfinite(hi60p)
    bk5 = pd.DataFrame(bk).rolling(5, min_periods=1).max().to_numpy() > 0
    shrink = np.isfinite(v5max) & (V <= 0.7 * v5max)
    hold = close_ff >= hi60p
    B1 = np.where(bk5 & np.isfinite(hi60p), (shrink & hold).astype(float), np.nan)
    B3 = np.where(np.isfinite(TURNd), (TURNd < 0.10).astype(float), np.nan)
    A20 = rollx(AMT, 20, 15)
    rk = pd.DataFrame(np.where(ELIG3, A20, np.nan)).rank(axis=1, pct=True).to_numpy()
    rk_prev = np.vstack([np.full((20, NC), np.nan), rk[:-20]])
    B4 = rk - rk_prev
    T0 = np.where(np.isfinite(TURNd), TURNd, 0.0)
    turn20 = pd.DataFrame(T0).rolling(20, min_periods=15).mean().to_numpy()

BF3 = dict(break_retest=B1, turn_avoid=B3, amount_rank_chg=B4)

# ---------- turn 家族头对头 ----------
EVt20 = rank_ic(turn20)
EVtav = rank_ic(B3)
# 合成：两者 ICIR 加权（同向：低换手好）
sgn20, sgna = (1.0 if EVt20[0] >= 0 else -1.0), (1.0 if EVtav[0] >= 0 else -1.0)
w20, wa = max(abs(EVt20[1]), 0.01), max(abs(EVtav[1]), 0.01)
Tmix = np.where(np.isfinite(turn20) & np.isfinite(B3),
                (sgn20 * turn20 * w20 + sgna * B3 * wa) / (w20 + wa), np.nan)
EVmix = rank_ic(Tmix)
log(f"turn 家族: turn20 IC={EVt20[0]:+.4f}/ICIR={EVt20[1]:+.3f} | turn_avoid IC={EVtav[0]:+.4f}/ICIR={EVtav[1]:+.3f} | mix IC={EVmix[0]:+.4f}/ICIR={EVmix[1]:+.3f}")

# ---------- 臂: 13 + 3B(15%) 合并 ----------
LAM = 0.15
W19 = {k: v * (1 - LAM) for k, v in S.WEIGHTS.items()}
EVB = {k: rank_ic(m) for k, m in BF3.items()}
WBraw = {k: max(abs(EVB[k][1]), 0.01) for k in BF3}
sB = sum(WBraw.values())
for k in BF3: W19[k] = WBraw[k] / sB * LAM
SIGNB = {k: (1.0 if EVB[k][0] >= 0 else -1.0) for k in BF3}

def z_of2(mat, sign):
    a = np.where(ELIG3, mat * sign, np.nan)
    mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
    return np.clip((a - mu) / (sd + 1e-12), -3, 3)

def composite2(wmap):
    num = np.zeros((ND, NC)); den = np.zeros((ND, NC))
    for k, w in wmap.items():
        z = z_of2(BF3[k], SIGNB[k]) if k in BF3 else z_of2(S.ALL[k], S.SIGN[k])
        ok = np.isfinite(z)
        num += np.where(ok, z * w, 0.0); den += np.where(ok, w, 0.0)
    return np.where(den > 0.4 * sum(wmap.values()), num / np.maximum(den, 1e-9), np.nan)

COMP_19 = composite2(W19)
COMP_13 = composite2(dict(S.WEIGHTS))
res = {}
for name, comp in [("COMP_19", COMP_19), ("COMP_13_base", COMP_13)]:
    shs = []
    o0 = None
    for off in range(F):
        m = run_engine(comp, N, offset=off)
        shs.append(m["sharpe"])
        if off == 0: o0 = m
    pm = float(np.median(shs))
    res[name] = dict(phmed=pm, phmin=float(min(shs)), phmax=float(max(shs)),
                     off0=dict(ann=o0["ann"], sharpe=o0["sharpe"], mdd=o0["mdd"], win=o0["win"], n_trades=o0["n_trades"]))
    log(f"{name:14s} phmed S={pm:.3f} (phmin {min(shs):.3f}/phmax {max(shs):.3f}) | off0 ann {o0['ann']*100:+.2f}% S={o0['sharpe']:.2f}")
m50 = run_engine(COMP_19, N, offset=0, slip=SLIP_STRESS)
res["COMP_19"]["slip50"] = dict(ann=m50["ann"], sharpe=m50["sharpe"])
d = res["COMP_19"]["phmed"] - res["COMP_13_base"]["phmed"]
res["delta_19_vs_13"] = d
res["turn_family"] = dict(turn20=dict(ic=EVt20[0], icir=EVt20[1]), turn_avoid=dict(ic=EVtav[0], icir=EVtav[1]),
                          mix=dict(ic=EVmix[0], icir=EVmix[1]))
log(f"增量 COMP_19 - COMP_13 = {d:+.3f}（门槛 +0.10 → {'过' if d >= 0.10 else '不过'}）| slip50 S={m50['sharpe']:.2f}")
json.dump(res, open(OUT / "b_combo_0914.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved b_combo_0914.json")
