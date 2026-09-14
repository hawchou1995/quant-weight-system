# -*- coding: utf-8 -*-
"""出场研究 R-exit-0915 · 轨A/轨B 因子化出场 10 臂（预注册 §二）
轨A: variant=turn, N20/F30；轨B: SUPER 13 因子 composite（oss_super_prod），N20 月频(F=20)
出场形 E1 top2n / E2 pct40 / E3 amp2x / E4 hs15 / E5 ma20；出场后留现金至下一调仓。
"""
import sys, json, time, math
import numpy as np, pandas as pd
from pathlib import Path
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
sys.path.insert(0, str(OUT))
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

# ---------- 轨A 侧：复用 satellite_opt 前缀 ----------
src = open(OUT / "satellite_opt_0913.py", encoding="utf-8").read()
exec(src.split("# ---- 复现基线")[0])
log("轨A harness ok | elig/day:", float(ELIG[WARMUP:].sum(axis=1).mean()))

# 动态出场矩阵（轨A）
SPCT = pd.DataFrame(np.where(ELIG, SCORE["turn"], np.nan)).rank(axis=1, pct=True).to_numpy()   # 升序分位(低=好)
IN2N = np.zeros((ND, NC), dtype=bool)
for di in range(ND):
    IN2N[di, ORDER["turn"][di][:40]] = True
ATRP = atr20 / np.where(close_ff > 0, close_ff, np.nan)
ATRMED = pd.DataFrame(ATRP).rolling(60, min_periods=40).median().to_numpy()
AMP2X = np.isfinite(ATRP) & np.isfinite(ATRMED) & (ATRP > 2 * ATRMED)
MA20 = pd.DataFrame(close_ff).rolling(20, min_periods=15).mean().to_numpy()
MA20_BRK = np.isfinite(MA20) & (close_ff < MA20)
log("轨A exit matrices ok")

def run_exit(variant, N, F, offset, exit_mode=None, cash0=CASH0, slip=SLIP):
    shares = np.zeros(NC); cost_basis = np.zeros(NC)
    cash = cash0; eq_curve = np.full(ND, np.nan); trades = []
    entry_di = np.full(NC, -1)
    pend_buy = []; pend_sell = []
    eq_prev = cash0; n_exit = 0
    top = TOP[variant]
    for di in range(WARMUP, ND):
        px_open = O[di]; px_prev = close_ff[di - 1]
        if pend_sell:
            keep = []
            for j in pend_sell:
                if not np.isfinite(px_open[j]) or px_open[j] <= px_prev[j] * 0.902:
                    keep.append(j); continue
                px = px_open[j] * (1 - slip); amt = px * shares[j]
                fee = max(amt * COMM, MIN_COMM) + amt * TAX
                cash += amt - fee
                ret = (amt - fee) / cost_basis[j] - 1 if cost_basis[j] > 0 else np.nan
                trades.append((entry_di[j], di, (amt - fee) - cost_basis[j], ret))
                shares[j] = 0.0; cost_basis[j] = 0.0; entry_di[j] = -1
            pend_sell = keep
        if pend_buy:
            held_n = int((shares > 0).sum())
            for j in pend_buy:
                if held_n >= N: break
                if shares[j] > 0 or not np.isfinite(px_open[j]) or px_open[j] <= 0.01: continue
                if px_open[j] >= px_prev[j] * 1.098: continue
                budget = eq_prev / N
                lots = math.floor(min(budget, cash) / (px_open[j] * (1 + slip) * 100.0))
                if lots < 1: continue
                px = px_open[j] * (1 + slip); amt = px * lots * 100.0
                fee = max(amt * COMM, MIN_COMM)
                if amt + fee > cash: continue
                cash -= amt + fee; shares[j] = lots * 100.0
                cost_basis[j] = amt + fee; entry_di[j] = di - 1
                held_n += 1
            pend_buy = []
        # mark
        nz = np.flatnonzero(shares)
        eq_prev = cash if len(nz) == 0 else cash + float(np.dot(shares[nz], close_ff[di][nz]))
        eq_curve[di] = eq_prev
        # ---- 动态出场（T 收盘判定 → 次日开盘卖）----
        if exit_mode:
            held = np.flatnonzero(shares > 0)
            for j in held:
                jj = int(j)
                trig = False
                if exit_mode == "top2n":   trig = not IN2N[di, jj]
                elif exit_mode == "pct40": trig = np.isfinite(SPCT[di, jj]) and SPCT[di, jj] > 0.40
                elif exit_mode == "amp2x": trig = AMP2X[di, jj]
                elif exit_mode == "ma20":  trig = MA20_BRK[di, jj]
                elif exit_mode == "hs15":
                    if cost_basis[jj] > 0 and np.isfinite(close_ff[di, jj]):
                        trig = (close_ff[di, jj] / (cost_basis[jj] / shares[jj]) - 1) <= -0.15
                if trig and jj not in pend_sell:
                    pend_sell.append(jj); n_exit += 1
        # 调仓
        if (di - WARMUP - offset) % F == 0 and di + 1 < ND:
            tgt = [int(j) for j in top[di][:N]]
            tgtS = set(tgt)
            held = np.flatnonzero(shares > 0)
            for j in held:
                if int(j) not in tgtS and int(j) not in pend_sell: pend_sell.append(int(j))
            n_after = int(len([j for j in held if int(j) in tgtS]))
            pend_buy = [j for j in tgt if shares[j] == 0]
    eq = pd.Series(eq_curve[WARMUP:], index=pd.to_datetime(cal[WARMUP:])).ffill().dropna()
    ret = eq.pct_change().dropna()
    yrs = len(eq) / 244.0
    ann = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    sharpe = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    closed = [t for t in trades if np.isfinite(t[3])]
    return dict(ann=float(ann), sharpe=float(sharpe), mdd=float(dd), n_trades=len(closed), n_exit=n_exit,
                win=float(np.mean([t[3] > 0 for t in closed])) if closed else np.nan)

res = {"track_a": {}, "track_b": {}}
# ---- 轨A：variant turn N20 F30 全 30 相位 ----
for mode in [None, "top2n", "pct40", "amp2x", "hs15", "ma20"]:
    shs, anns, mdd = [], [], []
    for off in range(30):
        m = run_exit("turn", 20, 30, off, exit_mode=mode)
        shs.append(m["sharpe"]); anns.append(m["ann"]); mdd.append(m["mdd"])
        if off == 0: o0 = m
    key = mode or "BASE"
    res["track_a"][key] = dict(phmed=float(np.median(shs)), phmin=float(min(shs)), phmax=float(max(shs)),
                               phmed_ann=float(np.median(anns)), off0=o0)
    log(f"轨A {key:7s} | phmed S={np.median(shs):.3f} (min {min(shs):.2f}/max {max(shs):.2f}) ann_med {np.median(anns)*100:+.2f}% | off0 S={o0['sharpe']:.2f} ann {o0['ann']*100:+.2f}% mdd {o0['mdd']*100:.1f}% exit={o0['n_exit']}")
b = res["track_a"]["BASE"]["phmed"]
for k, v in res["track_a"].items():
    if k != "BASE": log(f"   Δ {k}: {v['phmed']-b:+.3f}（门 +0.10 → {'过' if v['phmed']-b>=0.10 else '不过'}）")

json.dump(res, open(OUT / "exit_lab_trackA_0915.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved exit_lab_trackA_0915.json")
