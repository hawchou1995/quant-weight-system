# -*- coding: utf-8 -*-
"""oss_0913 批4b: 超集组合 — A4D 6 因子 + 战法原子 14 因子合并挖掘
预注册申报: 新臂 = 两族合并去冗余(|ρ|>0.6)后 icir 加权 composite,
口径与 A4D 完全一致(300万池/N20/F20/sc1000 MA20 半仓 + 高波半区), 20 相位全扫。
目的: 回答"战法原子因子对 A4D 是否有增量"。
"""
import numpy as np, pandas as pd, pickle, json, os, math, time

def _oss_base():
    """仓库根解析（2026-09-24 云端可移植；本机解析恒等）。exec 注入场景可能无 __file__ → 自 cwd 向上找 index_000300.csv 标记回退。"""
    _c = []
    if "__file__" in globals():
        _c.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    _p = os.getcwd()
    for _ in range(6):
        _c.append(_p)
        _q = os.path.dirname(_p)
        if _q == _p:
            break
        _p = _q
    for _d in _c:
        if _d and os.path.isfile(os.path.join(_d, "index_000300.csv")) and os.path.isdir(os.path.join(_d, "backtest", "oss_0913")):
            return _d
    return _c[0]
BASE = _oss_base()
OUT = os.path.join(BASE, "backtest", "oss_0913")
FL = os.path.join(BASE, "backtest", "factorlab_0913")
CASH0 = 170_000.0
COMM, TAX, SLIP, SLIP_STRESS, MIN_COMM = 0.00025, 0.0005, 0.0020, 0.0050, 5.0
WARMUP = 150; F = 20
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

with open(os.path.join(OUT, "oss_panel_0913.pkl"), "rb") as fh:
    P = pickle.load(fh)
with open(os.path.join(FL, "panel_0913.pkl"), "rb") as fh:
    FP = pickle.load(fh)
cal = P["cal"]; codes = P["codes"]; st = P["st_mask"]
ND, NC = P["close"].shape
E = P["ext"]; FD = FP["factors"]
O = P["open"].astype(np.float64); H = P["high"].astype(np.float64)
L = P["low"].astype(np.float64); C = P["close"].astype(np.float64)
V = P["vol"].astype(np.float64); AMT = P["amt"].astype(np.float64)
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
ALL = dict(AF)
for k in ["amount20", "size_rev", "amp20", "ret60", "bp", "size_ep"]:
    ALL[k] = FD[k].astype(np.float64)
# 生产口径: 不含行业因子（行业因子相位不稳已证, 见 super_combo_withind_0913.json）
log("candidates:", len(ALL))

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

EV = {}
for k, mat in ALL.items():
    ic, icir = rank_ic(mat)
    EV[k] = (ic, icir)
log("IC table done")
sign = {k: (1.0 if EV[k][0] >= 0 else -1.0) for k in ALL}

sample = np.arange(WARMUP, ND, 3)
Zs = {}
for k, mat in ALL.items():
    a = (mat * sign[k])[sample]
    a = np.where(np.isfinite(a) & ELIG3[sample], a, np.nan)
    mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
    Zs[k] = np.clip((a - mu) / (sd + 1e-12), -8, 8)
order = sorted(ALL, key=lambda k: -abs(EV[k][0]))
picked, dropped = [], {}
for k in order:
    ok = True
    for p in picked:
        m = np.isfinite(Zs[k]) & np.isfinite(Zs[p])
        r = np.corrcoef(Zs[k][m], Zs[p][m])[0, 1] if m.sum() > 500 else 0.0
        if abs(r) > 0.6:
            dropped[k] = f"{r:+.2f}~{p}"; ok = False; break
    if ok: picked.append(k)
log("picked:", picked)
log("dropped:", list(dropped.items()))
W = {}
for k in picked:
    W[k] = max(abs(EV[k][1]), 0.01)
sW = sum(W.values()); W = {k: v / sW for k, v in W.items()}
log("weights:", {k: round(v, 3) for k, v in W.items()})

def composite():
    num = np.zeros((ND, NC)); den = np.zeros((ND, NC))
    for k in picked:
        a = np.where(ELIG3, ALL[k] * sign[k], np.nan)
        mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
        z = np.clip((a - mu) / (sd + 1e-12), -3, 3)
        ok = np.isfinite(z)
        num += np.where(ok, z * W[k], 0.0); den += np.where(ok, W[k], 0.0)
    return np.where(den > 0.4, num / np.maximum(den, 1e-9), np.nan)

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
                proceeds = amt - fee
                cash += proceeds
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
    yr = {int(yv): float(eq[eq.index.year == yv].iloc[-1] / eq[eq.index.year == yv].iloc[0] - 1)
          for yv in sorted(set(eq.index.year))}
    return dict(total=float(eq.iloc[-1] / eq.iloc[0] - 1), ann=float(ann), sharpe=float(sharpe),
                mdd=float(dd), n_trades=len(closed),
                win=float(np.mean([t[3] > 0 for t in closed])) if closed else np.nan, by_year=yr, equity=eq)

comp = composite()
results = []
for N in [20, 30]:
    shs, anns, offs = [], [], []
    for off in range(F):
        m = run_engine(comp, N, offset=off)
        shs.append(m["sharpe"]); anns.append(m["ann"]); offs.append(m)
    med_sh, med_ann = float(np.median(shs)), float(np.median(anns))
    o0 = offs[0]
    results.append(dict(N=N, off0=dict(ann=o0["ann"], sharpe=o0["sharpe"], mdd=o0["mdd"], win=o0["win"],
        n_trades=o0["n_trades"], by_year=o0["by_year"]), phmed_sharpe=med_sh, phmed_ann=med_ann, phmin=float(np.min(shs))))
    log(f"SUPER N={N} | off0 ann {o0['ann']*100:+.2f}% S={o0['sharpe']:+.2f} mdd={o0['mdd']*100:.1f}% | phmed S={med_sh:.3f} ann={med_ann*100:+.2f}% phmin={min(shs):.3f}")

best = max(results, key=lambda r: r["phmed_sharpe"])
N_b = best["N"]
m0 = run_engine(comp, N_b, offset=0)
m50 = run_engine(comp, N_b, offset=0, slip=SLIP_STRESS)
m100 = run_engine(comp, N_b, offset=0, cash0=1_000_000.0)
log(f"best N={N_b} | slip50 {m50['ann']*100:+.2f}% S={m50['sharpe']:.2f} | 100w {m100['ann']*100:+.2f}% S={m100['sharpe']:.2f}")

rng = np.random.default_rng(53)
reb_days = [di for di in range(WARMUP, ND) if (di - WARMUP) % F == 0 and di + 1 < ND]
reb_set = set(reb_days); elig_days = {di: np.flatnonzero(ELIG3[di]) for di in reb_days}
def gate_open_at(di):
    return bool(np.isfinite(ma20sc[di]) and sc1000[di] > ma20sc[di])
seeds_sh = []
for s_i in range(500):
    shares_h = {}; cash = CASH0; eq_prev = CASH0; eq_path = []
    for di in range(WARMUP, ND):
        px_open = O[di]; px_prev = close_ff[di - 1]
        if (di - 1) in reb_set:
            Neff = N_b if gate_open_at(di - 1) else max(2, N_b // 2)
            for j, sh in shares_h.items():
                if np.isfinite(px_open[j]):
                    px = px_open[j] * (1 - SLIP); amt = px * sh
                    cash += amt - max(amt * COMM, MIN_COMM) - amt * TAX
            shares_h = {}
            cand = elig_days[di - 1]
            if gate_open_at(di - 1) and len(cand) >= Neff:
                picks = rng.choice(cand, size=Neff, replace=False)
                budget = eq_prev / N_b
                for j in picks:
                    if not np.isfinite(px_open[j]) or px_open[j] >= px_prev[j] * 1.098 or px_open[j] <= 0.01: continue
                    lots = math.floor(min(budget, cash) / (px_open[j] * (1 + SLIP) * 100.0))
                    if lots < 1: continue
                    px = px_open[j] * (1 + SLIP); amt = px * lots * 100.0
                    fee = max(amt * COMM, MIN_COMM)
                    if amt + fee > cash: continue
                    cash -= amt + fee; shares_h[int(j)] = lots * 100.0
        eq_prev = cash + sum(sh * close_ff[di][j] for j, sh in shares_h.items())
        eq_path.append(eq_prev)
    eqs = pd.Series(eq_path).ffill().dropna(); rr = eqs.pct_change().dropna()
    seeds_sh.append(float(rr.mean() / (rr.std() + 1e-12) * np.sqrt(244)))
p_val = float(np.mean(np.array(seeds_sh) >= m0["sharpe"]))
log(f"SUPER off0 S={m0['sharpe']:.3f} vs placebo med={np.median(seeds_sh):.3f} p={p_val:.3f}")

out = dict(meta=dict(candidates=list(ALL), picked=picked, dropped=dict(list(dropped.items())[:14]),
                     weights=W, sign={k: sign[k] for k in picked}, n_trials=2 * F + 500,
                     note="A4D 6 factors + 14 atomic factors merged, redundant removal |rho|>0.6"),
           results=results, best=dict(best, slip50=dict(ann=m50["ann"], sharpe=m50["sharpe"], mdd=m50["mdd"]),
                     cash100=dict(ann=m100["ann"], sharpe=m100["sharpe"]),
                     placebo_p=p_val, placebo_med=float(np.median(seeds_sh))))
with open(os.path.join(OUT, "super_combo_0913.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1, default=float)
m0["equity"].to_csv(os.path.join(OUT, "super_champion_equity_0913.csv"))
log("saved super_combo_0913.json DONE")
