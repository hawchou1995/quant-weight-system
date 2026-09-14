# -*- coding: utf-8 -*-
"""R-exit-0915 · 轨B（SUPER 13 因子）出场 6 臂 + 轨A 胜者 50bp 压力档"""
import sys, json, time, math
import numpy as np, pandas as pd
from pathlib import Path
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
sys.path.insert(0, str(OUT))
import oss_super_prod_0913 as S
CASH0, COMM, TAX, MIN_COMM = 170_000.0, 0.00025, 0.0005, 5.0
SLIP, SLIP50 = 0.0020, 0.0050
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

O, H, L, C = S.O, S.H, S.L, S.C
close_ff, ELIG = S.close_ff, S.ELIG_SUPER
COMP = S.COMP_SUPER
cal, WARMUP = S.cal, S.WARMUP
ND, NC = close_ff.shape
N, F = 20, 20   # 轨B 月频 rebal=20

# ---- 出场矩阵 ----
SPCT = pd.DataFrame(np.where(ELIG & np.isfinite(COMP), COMP, np.nan)).rank(axis=1, pct=True).to_numpy()
ORDERB = np.argsort(np.where(ELIG & np.isfinite(COMP), -COMP, -np.inf), axis=1)   # 高分在前
IN2N = np.zeros((ND, NC), dtype=bool)
for di in range(ND): IN2N[di, ORDERB[di][:40]] = True
cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
with np.errstate(all="ignore"):
    TR = np.maximum.reduce([H - L, np.abs(H - cprev), np.abs(L - cprev)])
    ATRP = pd.DataFrame(TR).rolling(20, min_periods=15).mean().to_numpy() / np.where(close_ff > 0, close_ff, np.nan)
ATRMED = pd.DataFrame(ATRP).rolling(60, min_periods=40).median().to_numpy()
AMP2X = np.isfinite(ATRP) & np.isfinite(ATRMED) & (ATRP > 2 * ATRMED)
MA20 = pd.DataFrame(close_ff).rolling(20, min_periods=15).mean().to_numpy()
MA20_BRK = np.isfinite(MA20) & (close_ff < MA20)
log("轨B matrices ok")

def etf_series(fn, col):
    df = pd.read_csv(BASE / "data_full" / fn, parse_dates=["date"])
    df["d"] = df["date"].dt.strftime("%Y-%m-%d")
    return df.drop_duplicates("d").set_index("d")[col].reindex([d for d in cal]).to_numpy()
sc1000 = etf_series("sh512100.csv", "close")
ma20sc = pd.Series(sc1000).rolling(20, min_periods=15).mean().to_numpy()
_ret1 = pd.DataFrame(close_ff).pct_change()
_v20f = (-_ret1.rolling(20, min_periods=15).std()).to_numpy()
volpct = pd.DataFrame(np.where(ELIG, _v20f, np.nan)).rank(axis=1, pct=True).to_numpy()

def run_exit(exit_mode=None, N=N, F=F, offset=0, cash0=CASH0, slip=SLIP, calm=True):
    shares = np.zeros(NC); cost_basis = np.zeros(NC)
    cash = cash0; eq_curve = np.full(ND, np.nan); trades = []
    entry_di = np.full(NC, -1); pend_buy = []; pend_sell = []
    eq_prev_known = cash0; n_exit = 0
    for di in range(WARMUP, ND):
        px_open = O[di]; px_prev = close_ff[di - 1]
        if pend_sell:
            keep = []
            for j in pend_sell:
                if not np.isfinite(px_open[j]) or px_open[j] <= px_prev[j] * 0.902: keep.append(j); continue
                px = px_open[j] * (1 - slip); amt = px * shares[j]
                fee = max(amt * COMM, MIN_COMM) + amt * TAX
                proceeds = amt - fee; cash += proceeds
                ret = proceeds / cost_basis[j] - 1 if cost_basis[j] > 0 else np.nan
                trades.append((entry_di[j], di, proceeds - cost_basis[j], ret))
                shares[j] = 0.0; cost_basis[j] = 0.0; entry_di[j] = -1
            pend_sell = keep
        if pend_buy:
            for j in pend_buy:
                if shares[j] > 0 or not np.isfinite(px_open[j]) or not ELIG[di - 1][j]: continue
                if px_open[j] >= px_prev[j] * 1.098 or px_open[j] <= 0.01: continue
                budget = eq_prev_known / N
                lots = math.floor(min(budget, cash) / (px_open[j] * (1 + slip) * 100.0))
                if lots < 1: continue
                px = px_open[j] * (1 + slip); amt = px * lots * 100.0
                fee = max(amt * COMM, MIN_COMM)
                if amt + fee > cash: continue
                cash -= amt + fee; shares[j] = lots * 100.0
                cost_basis[j] = amt + fee; entry_di[j] = di - 1
            pend_buy = []
        nz = np.flatnonzero(shares)
        eq_prev_known = cash if len(nz) == 0 else cash + float(np.dot(shares[nz], close_ff[di][nz]))
        eq_curve[di] = eq_prev_known
        # ---- 动态出场（T 收盘 → T+1 开盘）----
        if exit_mode:
            for j in np.flatnonzero(shares > 0):
                jj = int(j); trig = False
                if exit_mode == "top2n":   trig = not IN2N[di, jj]
                elif exit_mode == "pct40": trig = np.isfinite(SPCT[di, jj]) and SPCT[di, jj] <= 0.60   # 跌出前40%（低分侧）
                elif exit_mode == "amp2x": trig = AMP2X[di, jj]
                elif exit_mode == "ma20":  trig = MA20_BRK[di, jj]
                elif exit_mode == "hs15":
                    if cost_basis[jj] > 0 and np.isfinite(close_ff[di, jj]):
                        trig = (close_ff[di, jj] / (cost_basis[jj] / shares[jj]) - 1) <= -0.15
                if trig and jj not in pend_sell:
                    pend_sell.append(jj); n_exit += 1
        # 调仓（月频）
        if (di - WARMUP - offset) % F == 0 and di + 1 < ND:
            row = COMP[di]
            ok = ELIG[di] & np.isfinite(row)
            gate_open = bool(np.isfinite(ma20sc[di]) and sc1000[di] > ma20sc[di])
            if ok.sum() >= N:
                cand = np.flatnonzero(ok)
                if gate_open: N_eff = N; sel = cand
                else:
                    N_eff = max(2, N // 2); sel = cand
                    if calm:
                        sub = cand[np.isfinite(volpct[di][cand]) & (volpct[di][cand] <= 0.5)]
                        if len(sub) >= N_eff: sel = sub
                ordj = sel[np.argsort(-row[sel])]
                topN = [int(j) for j in ordj[:N_eff]]; topS = set(topN)
                held = np.flatnonzero(shares > 0)
                for j in held:
                    if int(j) not in topS and int(j) not in pend_sell: pend_sell.append(int(j))
                n_after = int(len([j for j in held if int(j) in topS]))
                pend_buy = [j for j in topN if shares[j] == 0][:max(0, N_eff - n_after)]
    eq = pd.Series(eq_curve[WARMUP:], index=pd.to_datetime(cal[WARMUP:])).ffill().dropna()
    ret = eq.pct_change().dropna()
    yrs = len(eq) / 244.0
    ann = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    sharpe = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    closed = [t for t in trades if np.isfinite(t[3])]
    return dict(ann=float(ann), sharpe=float(sharpe), mdd=float(dd), n_trades=len(closed), n_exit=n_exit)

res = {}
for mode in [None, "top2n", "pct40", "amp2x", "hs15", "ma20"]:
    shs, anns = [], []
    for off in range(F):
        m = run_exit(exit_mode=mode, offset=off)
        shs.append(m["sharpe"]); anns.append(m["ann"])
        if off == 0: o0 = m
    key = mode or "BASE"
    res[key] = dict(phmed=float(np.median(shs)), phmin=float(min(shs)), phmax=float(max(shs)),
                    phmed_ann=float(np.median(anns)), off0=o0)
    log(f"轨B {key:7s} | phmed S={np.median(shs):.3f} (min {min(shs):.2f}/max {max(shs):.2f}) | off0 S={o0['sharpe']:.2f} ann {o0['ann']*100:+.2f}% mdd {o0['mdd']*100:.1f}% exit={o0['n_exit']}")
b = res["BASE"]["phmed"]
winners = []
for k, v in res.items():
    if k != "BASE":
        d = v["phmed"] - b
        if d >= 0.10: winners.append(k)
        log(f"   Δ {k}: {d:+.3f}（门 +0.10 → {'过' if d >= 0.10 else '不过'}）")

# ---- 压力档：轨B 胜者（或全部）+ 轨A 胜者 ----
for k in (winners or ["pct40"]):
    m50 = run_exit(exit_mode=k, offset=0, slip=SLIP50)
    res[k]["slip50"] = dict(ann=m50["ann"], sharpe=m50["sharpe"], mdd=m50["mdd"])
    log(f"轨B {k} slip50: ann {m50['ann']*100:+.2f}% S={m50['sharpe']:.2f}")

# 轨A 胜者压力档（复用 exit_lab_trackA 的 harness）
srcA = open(OUT / "satellite_opt_0913.py", encoding="utf-8").read()
exec(srcA.split("# ---- 复现基线")[0])
SPCT_A = pd.DataFrame(np.where(ELIG, SCORE["turn"], np.nan)).rank(axis=1, pct=True).to_numpy()
IN2N_A = np.zeros((ND, NC), dtype=bool)
for di in range(ND): IN2N_A[di, ORDER["turn"][di][:40]] = True
def runA(exit_mode, slip):
    shares = np.zeros(NC); cost_basis = np.zeros(NC)
    cash = CASH0; eq_curve = np.full(ND, np.nan); pend_sell = []; pend_buy = []
    eq_prev = CASH0; entry_di = np.full(NC, -1)
    top = TOP["turn"]
    for di in range(WARMUP, ND):
        px_open = O[di]; px_prev = close_ff[di - 1]
        if pend_sell:
            keep = []
            for j in pend_sell:
                if not np.isfinite(px_open[j]) or px_open[j] <= px_prev[j] * 0.902: keep.append(j); continue
                px = px_open[j] * (1 - slip); amt = px * shares[j]
                fee = max(amt * COMM, MIN_COMM) + amt * TAX
                cash += amt - fee
                shares[j] = 0.0; cost_basis[j] = 0.0; entry_di[j] = -1
            pend_sell = keep
        if pend_buy:
            held_n = int((shares > 0).sum())
            for j in pend_buy:
                if held_n >= 20: break
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
        if exit_mode:
            for j in np.flatnonzero(shares > 0):
                jj = int(j)
                trig = (not IN2N_A[di, jj]) if exit_mode == "top2n" else (np.isfinite(SPCT_A[di, jj]) and SPCT_A[di, jj] > 0.40)
                if trig and jj not in pend_sell: pend_sell.append(jj)
        if (di - WARMUP) % 30 == 0 and di + 1 < ND:
            tgt = [int(j) for j in top[di][:20]]; tgtS = set(tgt)
            held = np.flatnonzero(shares > 0)
            for j in held:
                if int(j) not in tgtS and int(j) not in pend_sell: pend_sell.append(int(j))
            pend_buy = [j for j in tgt if shares[j] == 0]
    eq = pd.Series(eq_curve[WARMUP:], index=pd.to_datetime(cal[WARMUP:])).ffill().dropna()
    ret = eq.pct_change().dropna()
    yrs = len(eq) / 244.0
    ann = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    return dict(ann=float(ann), sharpe=float(ret.mean() / ret.std() * np.sqrt(244)) if ret.std() > 0 else np.nan)

for k in ["pct40", "top2n"]:
    m50 = runA(k, SLIP50)
    res.setdefault("trackA_" + k, {})["slip50"] = dict(ann=m50["ann"], sharpe=m50["sharpe"])
    log(f"轨A {k} slip50: ann {m50['ann']*100:+.2f}% S={m50['sharpe']:.2f}")

json.dump(res, open(OUT / "exit_lab_trackB_0915.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved exit_lab_trackB_0915.json")
