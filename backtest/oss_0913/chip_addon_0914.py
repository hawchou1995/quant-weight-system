# -*- coding: utf-8 -*-
"""chip_addon_0914: 筹码因子 cost_bias_rev 对 SUPER 13 因子的增量测试
预注册: 若与 picked 13 因子 |rho|<0.6 → 14 因子 ICIR 复合全相位评估 vs 13 因子基线;
        若任一 |rho|>=0.6 → 判定同族冗余, 不做组合级测试, 直接出结论。
口径与 SUPER 生产完全一致: N20 / F20 / sc1000 MA20 半仓 + 高波半区 / 300万池 / 20 相位全扫。
"""
import numpy as np, pandas as pd, pickle, json, os, math, time
BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
OUT = os.path.join(BASE, "backtest", "oss_0913")
FL = os.path.join(BASE, "backtest", "factorlab_0913")
CASH0 = 170_000.0
COMM, TAX, SLIP, SLIP_STRESS, MIN_COMM = 0.00025, 0.0005, 0.0020, 0.0050, 5.0
WARMUP = 150; F = 20; N = 20
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

with open(os.path.join(OUT, "oss_panel_0913.pkl"), "rb") as fh: P = pickle.load(fh)
with open(os.path.join(FL, "panel_0913.pkl"), "rb") as fh: FP = pickle.load(fh)
cal = P["cal"]; codes = P["codes"]; st = P["st_mask"]
ND, NC = P["close"].shape
E = P["ext"]; FD = FP["factors"]
O = P["open"].astype(np.float64); H = P["high"].astype(np.float64)
L = P["low"].astype(np.float64); C = P["close"].astype(np.float64)
V = P["vol"].astype(np.float64); AMT = P["amt"].astype(np.float64)
FMV = P["fmv"].astype(np.float64)
ATR = E["atr14"].astype(np.float64); J = E["kdj_j"].astype(np.float64)
ZW = E["z_white"].astype(np.float64); ZY = E["z_yellow"].astype(np.float64)
close_ff = pd.DataFrame(C).ffill().to_numpy()
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
hist_n = np.cumsum(np.isfinite(O), axis=0)
lo20 = pd.DataFrame(L).rolling(20, min_periods=15).min().to_numpy()
hi20 = pd.DataFrame(H).rolling(20, min_periods=15).max().to_numpy()
hi120 = pd.DataFrame(H).rolling(120, min_periods=80).max().to_numpy()
sig20 = pd.DataFrame(close_ff).rolling(20, min_periods=20).std(ddof=0).to_numpy()
Cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
with np.errstate(all="ignore"):
    TR = np.maximum.reduce([H - L, np.abs(H - Cprev), np.abs(L - Cprev)])
    tr20 = pd.DataFrame(TR).rolling(20, min_periods=20).mean().to_numpy()
    v5 = pd.DataFrame(V).rolling(5, min_periods=5).mean().to_numpy()
    v20 = pd.DataFrame(V).rolling(20, min_periods=20).mean().to_numpy()
    up90 = pd.DataFrame(H).rolling(90, min_periods=60).max().shift(1).to_numpy()

with np.errstate(all="ignore"):
    AF = {
        "neg_j": -J, "shrink": -(v5 / v20),
        "low_lift": (lo20 / pd.DataFrame(L).rolling(60, min_periods=40).min().to_numpy() - 1) * 100,
        "neg_dbbi": -np.abs(E["dist_bbi"].astype(np.float64)),
        "neg_dyel": -np.abs(E["dist_yellow"].astype(np.float64)),
        "wy_ratio": (ZW / ZY - 1) * 100,
        "neg_sspace": -((close_ff / lo20 - 1) * 100),
        "pspace": (hi20 / close_ff - 1) * 100,
        "dd120": (close_ff / hi120 - 1) * 100,
        "slope_bbi": (E["bbi"].astype(np.float64) / pd.DataFrame(E["bbi"].astype(np.float64)).shift(3).to_numpy() - 1) * 100,
        "sqz_ratio": -(sig20 / tr20),
        "neg_atrp": -(ATR / close_ff) * 100,
        "brk90": (close_ff / up90 - 1) * 100,
        "neg_vr": -(v5 / v20),
    }
    # ==== 筹码因子(ima 语料提炼) ====
    TURN = np.where(FMV > 0, AMT / FMV, np.nan)
    TURN0 = np.where(np.isfinite(TURN), TURN, 0.0)
    W60 = pd.DataFrame(TURN0).rolling(60, min_periods=40).sum().to_numpy()
    VC60 = pd.DataFrame(close_ff * TURN0).rolling(60, min_periods=40).sum().to_numpy()
    VW60 = VC60 / (W60 + 1e-12)
    cost_bias_rev = np.where((W60 > 0), -(close_ff / (VW60 + 1e-12) - 1), np.nan)
ALL = dict(AF)
for k in ["amount20", "size_rev", "amp20", "ret60", "bp", "size_ep"]:
    ALL[k] = FD[k].astype(np.float64)
ALL["cost_bias_rev"] = cost_bias_rev

ELIG3 = (np.isfinite(O) & np.isfinite(C) & (amt20 >= 3e6) & (~st[None, :]) & (hist_n >= WARMUP) & (C > 2.0))
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

# ---- 冻结的 13 因子口径 ----
META = json.load(open(os.path.join(OUT, "super_combo_0913.json"), encoding="utf-8"))["meta"]
PICKED = META["picked"]; WFRZ = META["weights"]; SIGN13 = META["sign"]
log("frozen picked:", PICKED)

# ---- 1. 全因子 IC 表 ----
EV = {}
for k, mat in ALL.items():
    ic, icir = rank_ic(mat)
    EV[k] = (ic, icir)
log("IC done. cost_bias_rev IC=%.4f ICIR=%.3f" % EV["cost_bias_rev"])

# ---- 2. 相关性(cost_bias_rev vs 13 因子 + 全候选), z 域, 与 combo 同法 ----
sample = np.arange(WARMUP, ND, 3)
def zmat(k):
    s = 1.0 if EV[k][0] >= 0 else -1.0
    a = (ALL[k] * s)[sample]
    a = np.where(np.isfinite(a) & ELIG3[sample], a, np.nan)
    mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
    return np.clip((a - mu) / (sd + 1e-12), -8, 8)
ZN = zmat("cost_bias_rev")
rho = {}
for k in PICKED:
    Zk = zmat(k)
    m = np.isfinite(ZN) & np.isfinite(Zk)
    rho[k] = float(np.corrcoef(ZN[m], Zk[m])[0, 1]) if m.sum() > 500 else 0.0
log("rho vs 13:")
for k, r in sorted(rho.items(), key=lambda x: -abs(x[1])):
    flag = "  <== OVER 0.6" if abs(r) >= 0.6 else ""
    log(f"    {k:14s} {r:+.3f}{flag}")
maxabs = max(abs(v) for v in rho.values()) if rho else 0.0
log(f"max |rho| = {maxabs:.3f}  -> {'REDUNDANT(同族, 不做组合级)' if maxabs >= 0.6 else 'PASS(进入组合级测试)'}")

# ---- 3. run_engine (与 combo 完全同源) ----
def etf_series(fn, col):
    df = pd.read_csv(os.path.join(BASE, "data_full", fn), parse_dates=["date"])
    df["d"] = df["date"].dt.strftime("%Y-%m-%d")
    return df.drop_duplicates("d").set_index("d")[col].reindex([d for d in cal]).to_numpy()
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
                if not np.isfinite(px_open[j]) or px_open[j] <= px_prev[j] * 0.902:
                    keep.append(j); continue
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
    eq = pd.Series(eq_curve[WARMUP:], index=pd.to_datetime(cal[WARMUP:])).ffill().dropna()
    ret = eq.pct_change().dropna()
    yrs = len(eq) / 244.0
    ann = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    sharpe = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    closed = [t for t in trades if np.isfinite(t[3])]
    return dict(total=float(eq.iloc[-1] / eq.iloc[0] - 1), ann=float(ann), sharpe=float(sharpe),
                mdd=float(dd), n_trades=len(closed),
                win=float(np.mean([t[3] > 0 for t in closed])) if closed else np.nan, equity=eq)

def make_comp(keys, Ws):
    def f():
        num = np.zeros((ND, NC)); den = np.zeros((ND, NC))
        for k in keys:
            a = np.where(ELIG3, ALL[k] * SIGN[k], np.nan)
            mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
            z = np.clip((a - mu) / (sd + 1e-12), -3, 3)
            ok = np.isfinite(z)
            num += np.where(ok, z * Ws[k], 0.0); den += np.where(ok, Ws[k], 0.0)
        return np.where(den > 0.4 * sum(Ws.values()), num / np.maximum(den, 1e-9), np.nan)
    return f()

# ---- 4. 13 因子基线复算(自建权重, 用于验证复现) ----
W13r = {k: max(abs(EV[k][1]), 0.01) for k in PICKED}
s13 = sum(W13r.values()); W13r = {k: v / s13 for k, v in W13r.items()}
dev = max(abs(W13r[k] - WFRZ[k]) / max(WFRZ[k], 1e-9) for k in PICKED)
log(f"weight replication max rel dev vs frozen: {dev*100:.2f}%")
SIGN = {k: (1.0 if EV[k][0] >= 0 else -1.0) for k in ALL}
comp13 = make_comp(PICKED, W13r)

# ---- 5. 若相关性通过 → 14 因子 ----
res = dict(rho=rho, max_abs_rho=maxabs, ic_costbias=list(EV["cost_bias_rev"]), weight_dev_pct=dev*100)
phase13, phase14 = [], []
o0_13 = o0_14 = None
if maxabs < 0.6:
    PICK14 = PICKED + ["cost_bias_rev"]
    W14r = {k: max(abs(EV[k][1]), 0.01) for k in PICK14}
    s14 = sum(W14r.values()); W14r = {k: v / s14 for k, v in W14r.items()}
    log("cost_bias_rev weight in 14: %.4f" % W14r["cost_bias_rev"])
    comp14 = make_comp(PICK14, W14r)
    # 持仓重合度(off0 语义: 每 F 日 top20 overlap)
    ov = []
    for di in range(WARMUP, ND, F):
        if di + 1 >= ND: break
        ok = ELIG3[di] & np.isfinite(comp13[di]) & np.isfinite(comp14[di])
        if ok.sum() < N: continue
        cand = np.flatnonzero(ok)
        t13 = set(cand[np.argsort(-comp13[di][cand])[:N]].tolist())
        t14 = set(cand[np.argsort(-comp14[di][cand])[:N]].tolist())
        ov.append(len(t13 & t14) / N)
    log(f"top20 overlap med={np.median(ov):.3f} mean={np.mean(ov):.3f} n={len(ov)}")
    res["overlap"] = dict(med=float(np.median(ov)), mean=float(np.mean(ov)))
    for off in range(F):
        m13 = run_engine(comp13, N, offset=off); phase13.append(m13["sharpe"])
        m14 = run_engine(comp14, N, offset=off); phase14.append(m14["sharpe"])
        if off == 0: o0_13, o0_14 = m13, m14
    pm13, pm14 = float(np.median(phase13)), float(np.median(phase14))
    log(f"PHMED 13F: S={pm13:.3f} (min {min(phase13):.3f}) | 14F: S={pm14:.3f} (min {min(phase14):.3f})")
    log(f"off0 13F: ann {o0_13['ann']*100:+.2f}% S={o0_13['sharpe']:.2f} mdd {o0_13['mdd']*100:.1f}% | "
        f"14F: ann {o0_14['ann']*100:+.2f}% S={o0_14['sharpe']:.2f} mdd {o0_14['mdd']*100:.1f}%")
    m50_14 = run_engine(comp14, N, offset=0, slip=SLIP_STRESS)
    m100_14 = run_engine(comp14, N, offset=0, cash0=1_000_000.0)
    log(f"14F slip50 off0: ann {m50_14['ann']*100:+.2f}% S={m50_14['sharpe']:.2f} | 100w: ann {m100_14['ann']*100:+.2f}% S={m100_14['sharpe']:.2f}")
    res.update(dict(
        phmed13=pm13, phmed14=pm14, phmin13=float(min(phase13)), phmin14=float(min(phase14)),
        off0_13=dict(ann=o0_13["ann"], sharpe=o0_13["sharpe"], mdd=o0_13["mdd"], win=o0_13["win"], n_trades=o0_13["n_trades"]),
        off0_14=dict(ann=o0_14["ann"], sharpe=o0_14["sharpe"], mdd=o0_14["mdd"], win=o0_14["win"], n_trades=o0_14["n_trades"]),
        slip50_14=dict(ann=m50_14["ann"], sharpe=m50_14["sharpe"]),
        cash100_14=dict(ann=m100_14["ann"], sharpe=m100_14["sharpe"]),
        weight_14=W14r, phase_sharpe_13=phase13, phase_sharpe_14=phase14))
    o0_14["equity"].to_csv(os.path.join(OUT, "chip14_equity_0914.csv"))
else:
    log("SKIP 组合级测试 (同族冗余)")

with open(os.path.join(OUT, "chip_addon_0914.json"), "w", encoding="utf-8") as fh:
    json.dump(res, fh, ensure_ascii=False, indent=1, default=float)
log("saved chip_addon_0914.json DONE")
