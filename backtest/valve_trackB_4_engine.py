# -*- coding: utf-8 -*-
"""valve_trackB 第4步(附加): 引擎级验证 —— 把阀当作"剔除+补位"直接接进 SUPER 13 引擎，
看净值口径的年化/夏普/回撤怎么变。这是事件级之外的裁决性证据。

口径: 与轨B完全一致(N20/F20/sc1000 MA20 半仓/offset0/20bp)，唯一改动:
      在调仓日 di，把被阀剔除的 (标的,日期) 的 composite 置为 NaN
      -> 引擎自然跳过该票并补入下一名 (补位票无分时数据, 视为通过; 这一点偏乐观, 报告已注明)
"""
import numpy as np, pandas as pd, pickle, json, os, math, time

BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
BT = os.path.join(BASE, "backtest")
OSS = os.path.join(BASE, "backtest", "oss_0913")
FL = os.path.join(BASE, "backtest", "factorlab_0913")
CASH0 = 170_000.0; COMM, TAX, SLIP, MIN_COMM = 0.00025, 0.0005, 0.0020, 5.0
WARMUP = 150; F = 20
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

CFG = json.load(open(os.path.join(OSS, "super_combo_0913.json"), encoding="utf-8"))
PICKED = list(CFG["meta"]["picked"]); W = {k: float(v) for k, v in CFG["meta"]["weights"].items()}
SIGN = {k: float(v) for k, v in CFG["meta"]["sign"].items()}

with open(os.path.join(OSS, "oss_panel_0913.pkl"), "rb") as fh: P = pickle.load(fh)
with open(os.path.join(FL, "panel_0913.pkl"), "rb") as fh: FP = pickle.load(fh)
cal = P["cal"]; codes = P["codes"]; st = P["st_mask"]; ND, NC = P["close"].shape
E = P["ext"]; FD = FP["factors"]
O = P["open"].astype(np.float64); H = P["high"].astype(np.float64)
L = P["low"].astype(np.float64); C = P["close"].astype(np.float64)
V = P["vol"].astype(np.float64); AMT = P["amt"].astype(np.float64)
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
with np.errstate(all="ignore"):
    AF = {"neg_j": -E["kdj_j"].astype(np.float64), "shrink": -(v5 / v20),
          "neg_dbbi": -np.abs(E["dist_bbi"].astype(np.float64)),
          "wy_ratio": (E["z_white"].astype(np.float64) / E["z_yellow"].astype(np.float64) - 1) * 100,
          "neg_sspace": -((close_ff / lo20 - 1) * 100),
          "pspace": (hi20 / close_ff - 1) * 100, "dd120": (close_ff / hi120 - 1) * 100,
          "sqz_ratio": -(sig20 / tr20)}
ALL = dict(AF)
for k in ["amount20", "size_rev", "amp20", "bp", "size_ep"]: ALL[k] = FD[k].astype(np.float64)
ELIG3 = (np.isfinite(O) & np.isfinite(C) & (amt20 >= 3e6) & (~st[None, :]) & (hist_n >= WARMUP) & (C > 2.0))

def composite():
    num = np.zeros((ND, NC)); den = np.zeros((ND, NC))
    for k in PICKED:
        a = np.where(ELIG3, ALL[k] * SIGN[k], np.nan)
        mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
        z = np.clip((a - mu) / (sd + 1e-12), -3, 3); ok = np.isfinite(z)
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
                if not np.isfinite(px_open[j]) or px_open[j] <= px_prev[j] * 0.902: keep.append(j); continue
                px = px_open[j] * (1 - slip); amt = px * shares[j]
                fee = max(amt * COMM, MIN_COMM) + amt * TAX; proceeds = amt - fee
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
            row = comp[di]; ok = ELIG3[di] & np.isfinite(row)
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
                    if int(j) not in topS: pend_sell.append(int(j))
                n_after = int(len([j for j in held if int(j) in topS]))
                pend_buy = [j for j in topN if shares[j] == 0][:max(0, N_eff - n_after)]
    eq = pd.Series(eq_curve[WARMUP:], index=pd.to_datetime(cal[WARMUP:])).ffill().dropna()
    ret = eq.pct_change().dropna(); yrs = len(eq) / 244.0
    ann = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    sharpe = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    closed = [t for t in trades if np.isfinite(t[3])]
    yr = {int(y): float(eq[eq.index.year == y].iloc[-1] / eq[eq.index.year == y].iloc[0] - 1)
          for y in sorted(set(eq.index.year))}
    return dict(ann=float(ann), sharpe=float(sharpe), mdd=float(dd),
                win=float(np.mean([t[3] > 0 for t in closed])), n_trades=len(closed), by_year=yr)

# ---- 阀 -> 每个调仓日的"剔除"掩码 ----
V = pd.read_csv(os.path.join(BT, "valve_trackB_lists_valved.csv"), dtype={"code": str})
code2j = {str(c): j for j, c in enumerate(P["codes"])}
d2i = {str(d): i for i, d in enumerate(P["cal"])}
comp0 = composite()

def apply_valve(comp, valve, mode="reject"):
    """把 (code,date) 被阀剔除的格置 NaN；mode='reject' 用 flag==0 剔除。"""
    cm = comp.copy()
    sub = V[V["has_minute"] == 1]
    hit = 0
    for rec in sub.itertuples():
        di = d2i.get(str(rec.date)); j = code2j.get(str(rec.code))
        if di is None or j is None: continue
        if getattr(rec, valve) == (0 if mode == "reject" else 1):
            cm[di][j] = np.nan; hit += 1
    return cm, hit

base = run_engine(comp0, 20, offset=0)
print("=" * 78)
print(f"基准(不设阀) ann={base['ann']*100:.3f}% S={base['sharpe']:.4f} mdd={base['mdd']*100:.2f}% "
      f"win={base['win']*100:.2f}% n={base['n_trades']}")
print("=" * 78)
print(f"{'阀':<10}{'剔除格数':>8}{'年化%':>9}{'Δann pp':>9}{'夏普':>8}{'ΔS':>8}{'回撤%':>9}{'胜率%':>8}{'笔数':>7}")
res = {"base": base}
for v in ["V1_强", "V2_不弱", "V3_反向", "V4_排带"]:
    cm, hit = apply_valve(comp0, v)
    m = run_engine(cm, 20, offset=0)
    res[v] = dict(hit=hit, **m)
    print(f"{v:<10}{hit:>8}{m['ann']*100:>9.3f}{(m['ann']-base['ann'])*100:>+9.3f}"
          f"{m['sharpe']:>8.4f}{m['sharpe']-base['sharpe']:>+8.4f}{m['mdd']*100:>9.2f}"
          f"{m['win']*100:>8.2f}{m['n_trades']:>7}")
json.dump(res, open(os.path.join(BT, "valve_trackB_engine.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1, default=float)
log("saved valve_trackB_engine.json")
