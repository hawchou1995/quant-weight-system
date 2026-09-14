# -*- coding: utf-8 -*-
"""A 族组合级测试（2 臂，预注册 §二）
臂1: COMP_FIB  = 3 因子(z_382/z_618/fib_hold_618) ICIR 加权独立组合（全相位）
臂2: COMP_16   = SUPER 13（冻结权重按比例）+ 3 fib（ICIR 权重）合并 → 对 13 因子基线增量
口径: N20/F20/sc1000 MA20 半仓+高波半区/300万池/20 相位全扫/slip50/100w（与 SUPER 完全同源）
"""
import sys, json, time, math
import numpy as np, pandas as pd
from pathlib import Path
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
sys.path.insert(0, str(OUT))
import oss_super_prod_0913 as S
CASH0 = 170_000.0
COMM, TAX, SLIP, SLIP_STRESS, MIN_COMM = 0.00025, 0.0005, 0.0020, 0.0050, 5.0
WARMUP, F, N = S.WARMUP, 20, 20
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

O, H, L, C = S.O, S.H, S.L, S.C
close_ff, ELIG3 = S.close_ff, S.ELIG_SUPER
ND, NC = close_ff.shape

def rm(mat, w, mp, how="min"):
    return (pd.DataFrame(mat).rolling(w, min_periods=mp).min() if how == "min"
            else pd.DataFrame(mat).rolling(w, min_periods=mp).max()).to_numpy()
hi120, lo120 = rm(H, 120, 80, "max"), rm(L, 120, 80)
rng120 = hi120 - lo120
f382 = lo120 + rng120 * 0.382
f618 = lo120 + rng120 * 0.618
with np.errstate(all="ignore"):
    z_382 = np.where(np.isfinite(f382), (close_ff >= f382).astype(float), np.nan)
    z_618 = np.where(np.isfinite(f618), (close_ff >= f618).astype(float), np.nan)
    below = (close_ff < f618) & np.isfinite(f618)
    was5 = pd.DataFrame(below).rolling(5, min_periods=1).max().to_numpy() > 0
    fib_hold = np.where(was5 & (close_ff >= f618) & np.isfinite(f618), 1.0,
               np.where(was5 & np.isfinite(f618), 0.0, np.nan))
FIB3 = dict(z_382=z_382, z_618=z_618, fib_hold_618=fib_hold)

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
    return float(v.mean()), float(v.mean() / (v.std() + 1e-12))

EV = {k: rank_ic(m) for k, m in FIB3.items()}
SIGN = {k: (1.0 if EV[k][0] >= 0 else -1.0) for k in FIB3}
WF = {k: max(abs(EV[k][1]), 0.01) for k in FIB3}
sF = sum(WF.values()); WF = {k: v / sF for k, v in WF.items()}
log("fib IC:", {k: round(v[0], 4) for k, v in EV.items()}, "| weights:", {k: round(v, 3) for k, v in WF.items()})

# SUPER 13 冻结权重（已复现偏差 0.00%，chip_addon 验证）
W13, SIGN13 = S.WEIGHTS, S.SIGN
log("13 因子权重和:", round(sum(W13.values()), 4))

def z_of(mat, sign):
    a = np.where(ELIG3, mat * sign, np.nan)
    mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
    return np.clip((a - mu) / (sd + 1e-12), -3, 3)

def composite(weight_map):
    num = np.zeros((ND, NC)); den = np.zeros((ND, NC))
    for k, w in weight_map.items():
        if k in FIB3:
            z = z_of(FIB3[k], SIGN[k])
        else:
            z = z_of(S.ALL[k], SIGN13[k])
        ok = np.isfinite(z)
        num += np.where(ok, z * w, 0.0); den += np.where(ok, w, 0.0)
    return np.where(den > 0.4 * sum(weight_map.values()), num / np.maximum(den, 1e-9), np.nan)

# 臂1: 纯 fib 组合（权重再归一）
COMP_FIB = composite(dict(WF))
# 臂2: 13 + 3fib 合并（13 权重按 (1-sF_target) 缩放的公平做法：13 保持冻结比例、fib 占 ICIR 应得份额）
# ICIR 归一法：把 13 冻结权重视为 ICIR/Σ13，则合并权重 = {13: w*(Σ13/(Σ13+sF_target))} —— 用 fib 权重份额 λ=0.15 折算
# 为避免猜 Σ13 原始和，采用显式公平份额：λ_fib = 0.15（3 个弱因子合计 15% 权重，13 因子保持相对比例 85%）
LAM = 0.15
W16 = {k: v * (1 - LAM) for k, v in W13.items()}
for k, v in WF.items(): W16[k] = v * LAM
COMP_16 = composite(W16)
log("COMP_16 权重和:", round(sum(W16.values()), 4), "| fib 份额:", LAM)

# ---- run_engine（与 chip_addon 同源）----
def etf_series(fn, col):
    df = pd.read_csv(BASE / "data_full" / fn, parse_dates=["date"])
    df["d"] = df["date"].dt.strftime("%Y-%m-%d")
    return df.drop_duplicates("d").set_index("d")[col].reindex([d for d in S.cal]).to_numpy()
sc1000 = etf_series("sh512100.csv", "close")
ma20sc = pd.Series(sc1000).rolling(20, min_periods=15).mean().to_numpy()
_ret1 = pd.DataFrame(close_ff).pct_change()
_v20f = (-_ret1.rolling(20, min_periods=15).std()).to_numpy()
volpct = pd.DataFrame(np.where(ELIG3, _v20f, np.nan)).rank(axis=1, pct=True).to_numpy()

def run_engine(comp, N, offset=0, cash0=CASH0, slip=SLIP, calm=True):
    shares = np.zeros(NC); cost_basis = np.zeros(NC)
    cash = cash0; eq_curve = np.full(ND, np.nan); trades = []
    entry_di = np.full(NC, -1); pend_buy = []; pend_sell = []
    eq_prev_known = cash0
    def mark(di):
        nz = np.flatnonzero(shares)
        return cash if len(nz) == 0 else cash + float(np.dot(shares[nz], close_ff[di][nz]))
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
                if shares[j] > 0 or not np.isfinite(px_open[j]) or not ELIG3[di - 1][j]: continue
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
        eq_prev_known = mark(di); eq_curve[di] = eq_prev_known
        if (di - WARMUP - offset) % F == 0 and di + 1 < ND:
            row = comp[di]
            ok = ELIG3[di] & np.isfinite(row)
            gate_open = bool(np.isfinite(ma20sc[di]) and sc1000[di] > ma20sc[di])
            if ok.sum() >= N:
                cand = np.flatnonzero(ok)
                if gate_open:
                    N_eff = N; sel = cand
                else:
                    N_eff = max(2, N // 2); sel = cand
                    if calm:
                        sub = cand[np.isfinite(volpct[di][cand]) & (volpct[di][cand] <= 0.5)]
                        if len(sub) >= N_eff: sel = sub
                ordj = sel[np.argsort(-row[sel])]
                topN = [int(j) for j in ordj[:N_eff]]; topS = set(topN)
                held = np.flatnonzero(shares > 0)
                for j in held:
                    if int(j) not in topS: pend_sell.append(int(j))
                n_after = int(len([j for j in held if int(j) in topS]))
                pend_buy = [j for j in topN if shares[j] == 0][:max(0, N_eff - n_after)]
    eq = pd.Series(eq_curve[WARMUP:], index=pd.to_datetime(S.cal[WARMUP:])).ffill().dropna()
    ret = eq.pct_change().dropna()
    yrs = len(eq) / 244.0
    ann = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    sharpe = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    closed = [t for t in trades if np.isfinite(t[3])]
    return dict(total=float(eq.iloc[-1] / eq.iloc[0] - 1), ann=float(ann), sharpe=float(sharpe),
                mdd=float(dd), n_trades=len(closed),
                win=float(np.mean([t[3] > 0 for t in closed])) if closed else np.nan, equity=eq)

res = {}
for name, comp in [("COMP_FIB", COMP_FIB), ("COMP_16", COMP_16), ("COMP_13_base", composite(dict(W13)))]:
    shs, anns = [], []
    o0 = None
    for off in range(F):
        m = run_engine(comp, N, offset=off)
        shs.append(m["sharpe"]); anns.append(m["ann"])
        if off == 0: o0 = m
    pm = float(np.median(shs))
    res[name] = dict(phmed=pm, phmin=float(min(shs)), phmax=float(max(shs)),
                     off0=dict(ann=o0["ann"], sharpe=o0["sharpe"], mdd=o0["mdd"], win=o0["win"], n_trades=o0["n_trades"]))
    log(f"{name:14s} phmed S={pm:.3f} (phmin {min(shs):.3f} / phmax {max(shs):.3f}) | off0 ann {o0['ann']*100:+.2f}% S={o0['sharpe']:.2f} mdd {o0['mdd']*100:.1f}%")

m50 = run_engine(COMP_16, N, offset=0, slip=SLIP_STRESS)
res["COMP_16"]["slip50"] = dict(ann=m50["ann"], sharpe=m50["sharpe"])
log(f"COMP_16 slip50: ann {m50['ann']*100:+.2f}% S={m50['sharpe']:.2f}")
d16 = res["COMP_16"]["phmed"] - res["COMP_13_base"]["phmed"]
log(f"增量: COMP_16 - COMP_13 = {d16:+.3f}（门槛 +0.10 → {'过' if d16 >= 0.10 else '不过'}）")
res["delta_16_vs_13"] = d16
json.dump(res, open(OUT / "fib_combo_0914.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved fib_combo_0914.json")
