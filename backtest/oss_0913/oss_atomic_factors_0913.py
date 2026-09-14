# -*- coding: utf-8 -*-
"""oss_0913 批4: 战法原子因子拆解 + IC体检 + 去冗余 + 组合挖掘
从 11 个策略（niuone 7 + wtfibought 4）的公式中共拆出 14 个战法特有原子因子：
  neg_j       -J (KDJ低位, B1/super_b1核心)
  shrink      5日均量/前10日均量 取负 (缩量回调)
  low_lift    lo20/lo60-1 (N型低点抬高)
  neg_dbbi    -|距BBI%| (牛绳/BBI约束)
  neg_dyel    -|距黄线%|
  wy_ratio    白线/黄线-1 (牛绳多头)
  neg_sspace  -(close/lo20-1) (止损空间小)
  pspace      hi20/close-1 (上方压力空间)
  dd120       120日回撤% (低位区深度)
  slope_bbi   BBI 3日斜率
  sqz_ratio   -σ20/TR20 (挤压度)
  neg_atrp    -ATR/close (低波)
  brk90       close/通道90-1 (通道位置)
  neg_vr      -5日/20日量比
流程: H20 Rank IC 体检 → |ρ|>0.6 去冗余 → ICIR 权重 composite → 复用地板网格回测(5000万/300万) → 与 A4D 对比
口径: 2021 起 / 主板 3209 / T+1 开盘 / 成本 20bp / 17 万整手
"""
import numpy as np, pandas as pd, pickle, json, os, math, time
from scipy import stats

BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
OUT = os.path.join(BASE, "backtest", "oss_0913")
CASH0 = 170_000.0
COMM, TAX, SLIP, SLIP_STRESS, MIN_COMM = 0.00025, 0.0005, 0.0020, 0.0050, 5.0
WARMUP = 150; F = 20
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

with open(os.path.join(OUT, "oss_panel_0913.pkl"), "rb") as fh:
    P = pickle.load(fh)
cal = P["cal"]; codes = P["codes"]; st = P["st_mask"]
ND, NC = P["close"].shape
E = P["ext"]
O = P["open"].astype(np.float64); H = P["high"].astype(np.float64)
L = P["low"].astype(np.float64); C = P["close"].astype(np.float64)
V = P["vol"].astype(np.float64); AMT = P["amt"].astype(np.float64)
ATR = E["atr14"].astype(np.float64); BBI = E["bbi"].astype(np.float64)
J = E["kdj_j"].astype(np.float64); ZW = E["z_white"].astype(np.float64)
ZY = E["z_yellow"].astype(np.float64)
close_ff = pd.DataFrame(C).ffill().to_numpy()
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
hist_n = np.cumsum(np.isfinite(O), axis=0)
lo20 = pd.DataFrame(L).rolling(20, min_periods=15).min().to_numpy()
lo60 = pd.DataFrame(L).rolling(60, min_periods=40).min().to_numpy()
hi20 = pd.DataFrame(H).rolling(20, min_periods=15).max().to_numpy()
hi120 = pd.DataFrame(H).rolling(120, min_periods=80).max().to_numpy()
sig20 = pd.DataFrame(close_ff).rolling(20, min_periods=20).std(ddof=0).to_numpy()
Cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
with np.errstate(all="ignore"):
    TR = np.maximum.reduce([H - L, np.abs(H - Cprev), np.abs(L - Cprev)])
tr20 = pd.DataFrame(TR).rolling(20, min_periods=20).mean().to_numpy()
up90 = pd.DataFrame(H).rolling(90, min_periods=60).max().shift(1).to_numpy()
v5 = pd.DataFrame(V).rolling(5, min_periods=5).mean().to_numpy()
v20 = pd.DataFrame(V).rolling(20, min_periods=20).mean().to_numpy()
bbi_s3 = (BBI / pd.DataFrame(BBI).shift(3).to_numpy() - 1) * 100
log("matrices ready")

with np.errstate(all="ignore"):
    AF = {
        "neg_j": -J,
        "shrink": -(v5 / v20),
        "low_lift": (lo20 / lo60 - 1) * 100,
        "neg_dbbi": -np.abs(E["dist_bbi"].astype(np.float64)),
        "neg_dyel": -np.abs(E["dist_yellow"].astype(np.float64)),
        "wy_ratio": (ZW / ZY - 1) * 100,
        "neg_sspace": -((close_ff / lo20 - 1) * 100),
        "pspace": (hi20 / close_ff - 1) * 100,
        "dd120": (close_ff / hi120 - 1) * 100,
        "slope_bbi": bbi_s3,
        "sqz_ratio": -(sig20 / tr20),
        "neg_atrp": -(ATR / close_ff) * 100,
        "brk90": (close_ff / up90 - 1) * 100,
        "neg_vr": -(v5 / v20),
    }
log("atomic factors:", len(AF))

ELIG5 = (np.isfinite(O) & np.isfinite(C) & (amt20 >= 5e7) & (~st[None, :]) & (hist_n >= WARMUP) & (C > 2.0))
ELIG3 = (np.isfinite(O) & np.isfinite(C) & (amt20 >= 3e6) & (~st[None, :]) & (hist_n >= WARMUP) & (C > 2.0))
fwdH = np.full((ND, NC), np.nan)
Hh = 20
fwdH[:ND-1-Hh] = O[1+Hh:] / O[1:ND-Hh] - 1

def rank_ic(mat, mask):
    a = np.where(mask & np.isfinite(mat), mat, np.nan)
    r = pd.DataFrame(a).rank(axis=1).to_numpy()
    zy = np.where(mask & np.isfinite(fwdH), pd.DataFrame(np.where(mask & np.isfinite(fwdH), fwdH, np.nan)).rank(axis=1).to_numpy(), np.nan)
    zf = r - np.nanmean(r, axis=1, keepdims=True); zz = zy - np.nanmean(zy, axis=1, keepdims=True)
    zf = zf / (np.nanstd(zf, axis=1, keepdims=True) + 1e-12); zz = zz / (np.nanstd(zz, axis=1, keepdims=True) + 1e-12)
    both = np.isfinite(zf) & np.isfinite(zz)
    n = both.sum(axis=1)
    ic = np.where(n > 50, np.nansum(np.where(both, zf * zz, 0), axis=1) / np.maximum(n, 1), np.nan)
    v = ic[np.isfinite(ic)]
    return (float(v.mean()), float(v.mean() / (v.std() + 1e-12)), len(v), ic)

log("=== IC 体检 (H20, 5000万地板) ===")
EV = {}
for k, mat in AF.items():
    ic, icir, nd, ic_ts = rank_ic(mat, ELIG5)
    EV[k] = dict(ic=ic, icir=icir, n=nd)
    log(f"{k:12s} IC={ic:+.4f} ICIR={icir:+.2f} n={nd}")

# ---------- 去冗余 (|rho|>0.6) ----------
sign = {k: (1.0 if EV[k]["ic"] >= 0 else -1.0) for k in AF}
sample = np.arange(WARMUP, ND, 3)
Zs = {}
for k, mat in AF.items():
    a = (mat * sign[k])[sample]
    ok = np.isfinite(a) & ELIG5[sample]
    a = np.where(ok, a, np.nan)
    mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
    Zs[k] = np.clip((a - mu) / (sd + 1e-12), -8, 8)
order = sorted(AF, key=lambda k: -abs(EV[k]["ic"]))
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

# ---------- composite (icir 权重, eligibility 内 z) ----------
ICIR_W = {k: max(abs(EV[k]["icir"]), 0.01) for k in picked}
s = sum(ICIR_W.values()); W = {k: ICIR_W[k] / s for k in picked}
log("weights:", {k: round(v, 3) for k, v in W.items()})

def composite(elig):
    num = np.zeros((ND, NC)); den = np.zeros((ND, NC))
    for k in picked:
        a = np.where(elig, AF[k] * sign[k], np.nan)
        mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
        z = np.clip((a - mu) / (sd + 1e-12), -3, 3)
        ok = np.isfinite(z)
        num += np.where(ok, z * W[k], 0.0); den += np.where(ok, W[k], 0.0)
    return np.where(den > 0.4, num / np.maximum(den, 1e-9), np.nan)

# ---------- 引擎 (对齐 A4D/r6b) ----------
sc1000 = None
def etf_series(fn, col):
    df = pd.read_csv(os.path.join(BASE, "data_full", fn), parse_dates=["date"])
    df["d"] = df["date"].dt.strftime("%Y-%m-%d")
    return df.drop_duplicates("d").set_index("d")[col].reindex([d for d in cal]).to_numpy()
sc1000 = etf_series("sh512100.csv", "close")
ma20sc = pd.Series(sc1000).rolling(20, min_periods=15).mean().to_numpy()
# 与 A4D 引擎完全一致: vol20 因子 = -std (rank 低 = 高波); calm 取 rank<=0.5 (高波半区)
_ret1 = pd.DataFrame(close_ff).pct_change()
_v20f = (-_ret1.rolling(20, min_periods=15).std()).to_numpy()
volpct = pd.DataFrame(np.where(ELIG5, _v20f, np.nan)).rank(axis=1, pct=True).to_numpy()

def run_engine(comp, elig, N, offset=0, cash0=CASH0, slip=SLIP, calm=True):
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
                if shares[j] > 0 or not np.isfinite(px_open[j]) or not elig[di - 1][j]: continue
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
            ok = elig[di] & np.isfinite(row)
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

results = []
for poolname, elig in [("5000万", ELIG5), ("300万", ELIG3)]:
    comp = composite(elig)
    for N in [20, 30]:
        shs, anns, offs = [], [], []
        for off in range(F):
            m = run_engine(comp, elig, N, offset=off)
            shs.append(m["sharpe"]); anns.append(m["ann"]); offs.append(m)
        med_sh, med_ann = float(np.median(shs)), float(np.median(anns))
        o0 = offs[0]
        results.append(dict(pool=poolname, N=N, off0=dict(ann=o0["ann"], sharpe=o0["sharpe"], mdd=o0["mdd"],
            win=o0["win"], n_trades=o0["n_trades"], by_year=o0["by_year"]),
            phmed_sharpe=med_sh, phmed_ann=med_ann, phmin=float(np.min(shs))))
        log(f"pool={poolname} N={N} | off0 ann {o0['ann']*100:+.2f}% S={o0['sharpe']:+.2f} mdd={o0['mdd']*100:.1f}% | phmed S={med_sh:.3f} ann={med_ann*100:+.2f}%")

# 冠军加压 + 安慰剂
best = max(results, key=lambda r: r["phmed_sharpe"])
elig_b = ELIG5 if best["pool"] == "5000万" else ELIG3
comp_b = composite(elig_b)
N_b = best["N"]
m0 = run_engine(comp_b, elig_b, N_b, offset=0)
m50 = run_engine(comp_b, elig_b, N_b, offset=0, slip=SLIP_STRESS)
m100 = run_engine(comp_b, elig_b, N_b, offset=0, cash0=1_000_000.0)
log(f"best pool={best['pool']} N={N_b} | slip50 {m50['ann']*100:+.2f}% S={m50['sharpe']:.2f} | 100w {m100['ann']*100:+.2f}% S={m100['sharpe']:.2f}")
rng = np.random.default_rng(53)
reb_days = [di for di in range(WARMUP, ND) if (di - WARMUP) % F == 0 and di + 1 < ND]
reb_set = set(reb_days); elig_days = {di: np.flatnonzero(elig_b[di]) for di in reb_days}
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
log(f"best off0 S={m0['sharpe']:.3f} vs placebo med={np.median(seeds_sh):.3f} p={p_val:.3f}")

out = dict(meta=dict(atomic=list(AF), picked=picked, dropped=dict(list(dropped.items())[:12]),
                     weights=W, eval_table={k: EV[k] for k in AF},
                     n_trials=4 * F + 500),
           results=results, best=dict(best, slip50=dict(ann=m50["ann"], sharpe=m50["sharpe"], mdd=m50["mdd"]),
                     cash100=dict(ann=m100["ann"], sharpe=m100["sharpe"]),
                     placebo_p=p_val, placebo_med=float(np.median(seeds_sh))))
with open(os.path.join(OUT, "atomic_factors_0913.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1, default=float)
m0["equity"].to_csv(os.path.join(OUT, "atomic_champion_equity_0913.csv"))
log("saved atomic_factors_0913.json DONE")
