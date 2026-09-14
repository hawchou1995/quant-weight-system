# -*- coding: utf-8 -*-
"""最强版真实夏普：轨A v2+pct40（统一窗口 2021-04~）@1M/@17k；轨B SUPER+pct40 @51k"""
import numpy as np, pandas as pd, json, time, math, sys
from pathlib import Path
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OSS = BASE / "backtest" / "oss_0913"
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:5.1f}s]", *a, flush=True)
W0 = pd.Timestamp("2021-04-01")

# ---------- 轨A（turn+gate+pct40） ----------
src = open(OSS / "satellite_opt_0913.py", encoding="utf-8").read()
exec(src.split("# ---- 复现基线")[0])
RK = {k: rk_pct(m) for k, m in [("amt", amt20), ("atr", atr20), ("turn", turn20)]}
S = np.zeros((ND, NC))
for k in RK: S += np.where(np.isfinite(RK[k]), RK[k], np.nan)
ORD = np.argsort(np.where(ELIG & np.isfinite(S), S, np.inf), axis=1)
SPCT = pd.DataFrame(np.where(ELIG & np.isfinite(S), S, np.nan)).rank(axis=1, pct=True).to_numpy()

def run_A(offset=0, pct40=True, slip=0.0020, cash0=1_000_000.0):
    shares = np.zeros(NC); cost_basis = np.zeros(NC); cash = cash0
    eq_curve = np.full(ND, np.nan); entry_di = np.full(NC, -1)
    pend_buy = []; pend_sell = []; eq_prev = cash0
    for di in range(WARMUP, ND):
        px_open = O[di]; px_prev = close_ff[di - 1]
        if pend_sell:
            keep = []
            for j in pend_sell:
                if not np.isfinite(px_open[j]) or px_open[j] <= px_prev[j] * 0.902: keep.append(j); continue
                px = px_open[j] * (1 - slip); amt = px * shares[j]
                fee = max(amt * COMM, MIN_COMM) + amt * TAX
                cash += amt - fee; shares[j] = 0.0; cost_basis[j] = 0.0; entry_di[j] = -1
            pend_sell = keep
        if pend_buy:
            held_n = int((shares > 0).sum())
            slots = 20 if gate_open[di - 1] else 10
            for j in pend_buy:
                if held_n >= slots: break
                if shares[j] > 0 or not np.isfinite(px_open[j]) or px_open[j] <= 0.01: continue
                if px_open[j] >= px_prev[j] * 1.098: continue
                lots = math.floor(min(eq_prev / 20, cash) / (px_open[j] * (1 + slip) * 100.0))
                if lots < 1: continue
                px = px_open[j] * (1 + slip); amt = px * lots * 100.0
                fee = max(amt * COMM, MIN_COMM)
                if amt + fee > cash: continue
                cash -= amt + fee; shares[j] = lots * 100.0; cost_basis[j] = amt + fee; entry_di[j] = di - 1
                held_n += 1
            pend_buy = []
        nz = np.flatnonzero(shares)
        eq_prev = cash if len(nz) == 0 else cash + float(np.dot(shares[nz], close_ff[di][nz]))
        eq_curve[di] = eq_prev
        if pct40:
            for j in np.flatnonzero(shares > 0):
                jj = int(j)
                if np.isfinite(SPCT[di, jj]) and SPCT[di, jj] > 0.40 and jj not in pend_sell:
                    pend_sell.append(jj)
        if (di - WARMUP - offset) % 30 == 0 and di + 1 < ND:
            tgt = [int(j) for j in ORD[di][:20]]; tgtS = set(tgt)
            held = np.flatnonzero(shares > 0)
            for j in held:
                if int(j) not in tgtS and int(j) not in pend_sell: pend_sell.append(int(j))
            pend_buy = [j for j in tgt if shares[j] == 0]
    return pd.Series(eq_curve, index=pd.to_datetime(cal)).ffill().dropna()

def m(eq):
    e = eq[eq.index >= W0]; r = e.pct_change().dropna(); yrs = len(e) / 244.0
    return dict(ann=round(float((e.iloc[-1]/e.iloc[0])**(1/yrs)-1)*100, 2),
                mdd=round(float((e/e.cummax()-1).min())*100, 2),
                sharpe=round(float(r.mean()/r.std()*np.sqrt(244)), 3))

log("轨A v2+pct40 @1M（统一窗口，30 相位）...")
shs = [m(run_A(o))["sharpe"] for o in range(30)]
o0 = m(run_A(0))
log(f"  @1M phmed={np.median(shs):.3f} (min {min(shs):.2f}/max {max(shs):.2f}) | off0 S={o0['sharpe']}/ann {o0['ann']}%/mdd {o0['mdd']}%")
shs17 = [m(run_A(o, cash0=17000.0))["sharpe"] for o in range(30)]
o017 = m(run_A(0, cash0=17000.0))
log(f"  @17k phmed={np.median(shs17):.3f} (min {min(shs17):.2f}/max {max(shs17):.2f}) | off0 S={o017['sharpe']}/ann {o017['ann']}%")
res = dict(A_pct40_1M=dict(phmed=round(float(np.median(shs)), 3), off0=o0),
           A_pct40_17k=dict(phmed=round(float(np.median(shs17)), 3), off0=o017))

# ---------- 轨B（SUPER+pct40）@51k ----------
_full = open(OSS / "dual_track_combined_0915.py", encoding="utf-8").read()
exec("# ---- 轨B 引擎" + _full.split("# ---- 轨B 引擎")[1].split("# ---- 任务4")[0])
shsb, o0b = [], None
for o in range(20):
    eq = run_B_eq(o, cash0=51000.0)
    r = m(eq); shsb.append(r["sharpe"])
    if o == 0: o0b = r
log(f"轨B pct40 @51k | phmed={np.median(shsb):.3f} (min {min(shsb):.2f}/max {max(shsb):.2f}) | off0 S={o0b['sharpe']}/ann {o0b['ann']}%/mdd {o0b['mdd']}%")
res["B_pct40_51k"] = dict(phmed=round(float(np.median(shsb)), 3), off0=o0b)
json.dump(res, open(OSS / "strongest_sharpe_0915.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved strongest_sharpe_0915.json")
