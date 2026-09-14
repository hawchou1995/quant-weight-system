# -*- coding: utf-8 -*-
"""oss_0913 批9b: turn 因子全池复验（val_em 池用 amount/fmv，extra 用 baostock turn；口径一致=换手率%）
臂: turn/N20/F30（本轮最优） + base/N10/F60（基线锚） 全相位
对比: val_em 池(0.529/0.713) vs 全池
"""
import numpy as np, pandas as pd, pickle, json, math, time
from pathlib import Path

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
CASH0 = 1_000_000.0
COMM, TAX, SLIP, MIN_COMM = 0.00025, 0.0005, 0.0020, 5.0
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

with open(OUT / "oss_panel_0913.pkl", "rb") as fh:
    P = pickle.load(fh)
cal = P["cal"]; codes0 = list(P["codes"])
ND = len(cal); di = {d: i for i, d in enumerate(cal)}
O0 = P["open"].astype(np.float64); C0 = P["close"].astype(np.float64)
A0 = P["amt"].astype(np.float64); F0 = P["fmv"].astype(np.float64)
V0 = P["vol"].astype(np.float64); H0 = P["high"].astype(np.float64); L0 = P["low"].astype(np.float64)
NC0 = len(codes0)

# extra 票: 数据
extra = []
for f in sorted((BASE / "data_full").glob("*.csv")):
    s = f.stem
    if s.startswith(("sh600", "sh601", "sh603", "sh605", "sz000", "sz001", "sz002", "sz003")):
        c = s[2:]
        if c not in set(codes0):
            extra.append((c, f))
NC = NC0 + len(extra)
Oe = np.full((ND, len(extra)), np.nan); Ce = np.full((ND, len(extra)), np.nan)
He = np.full((ND, len(extra)), np.nan); Le = np.full((ND, len(extra)), np.nan)
Ae = np.full((ND, len(extra)), np.nan)
for k, (c, f) in enumerate(extra):
    d = pd.read_csv(f, parse_dates=["date"])
    d["d"] = d["date"].dt.strftime("%Y-%m-%d")
    d = d[d["d"].isin(di)].drop_duplicates("d").set_index("d")
    idx = [di[x] for x in d.index]
    Oe[idx, k] = d["open"].to_numpy(); Ce[idx, k] = d["close"].to_numpy()
    He[idx, k] = d["high"].to_numpy(); Le[idx, k] = d["low"].to_numpy()
    Ae[idx, k] = d["amount"].to_numpy()
O = np.hstack([O0, Oe]); C = np.hstack([C0, Ce]); H = np.hstack([H0, He]); L = np.hstack([L0, Le])
AMT = np.hstack([A0, Ae]); FMV = np.hstack([F0, np.full((ND, len(extra)), np.nan)])
codes = codes0 + [c for c, _ in extra]
log("pool:", NC)

# turn 矩阵: val_em 池 = amount/fmv*100; extra = baostock turn 补齐
# 计算 val_em 池的日换手率(matrix) 需要 amount/fmv 逐日 -> 这里用 baostock 全量 turn 优先?
# 方案: val_em 池用 amount/fmv（回测验证过的口径）; extra 用 baostock turn_extra
TURN = np.full((ND, NC), np.nan)
with np.errstate(all="ignore"):
    TURN[:, :NC0] = np.where(FMV[:, :NC0] > 0, AMT[:, :NC0] / FMV[:, :NC0] * 100, np.nan)
te = pd.read_csv(BASE / "data_fundamental" / "baostock_val" / "turn_extra_0913.csv", dtype={"code": str})
log("turn_extra rows:", len(te), "codes:", te["code"].nunique())
for k, (c, _) in enumerate(extra):
    sub = te[te["code"] == c]
    if len(sub) == 0: continue
    sub = sub[sub["date"].isin(di)]
    idx = [di[x] for x in sub["date"]]
    vals = pd.to_numeric(sub["turn"], errors="coerce").to_numpy()
    TURN[idx, NC0 + k] = vals
cov = np.isfinite(TURN[:, NC0:]).mean()
log(f"extra turn coverage: {cov:.3f}")

close_ff = pd.DataFrame(C).ffill().to_numpy()
turn20 = pd.DataFrame(TURN).rolling(20, min_periods=15).mean().to_numpy()
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
Cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
with np.errstate(all="ignore"):
    TR = np.maximum.reduce([H - L, np.abs(H - Cprev), np.abs(L - Cprev)])
atr20 = pd.DataFrame(TR).rolling(20, min_periods=15).mean().to_numpy() / close_ff
hist_n = np.cumsum(np.isfinite(O), axis=0)
first_valid = np.argmax(np.isfinite(O), axis=0)
hist_n = hist_n + np.where((first_valid == 0)[None, :], 1000, 0)
_nh = pd.read_csv(BASE / "data_fundamental" / "name_hist.csv", dtype={"code": str}).sort_values("TRADE_DATE").groupby("code").tail(1)
_name = _nh.set_index("code")["SECURITY_NAME_ABBR"].astype(str)
TUI = set(_name[_name.str.contains("退")].index)
tui_mask = np.array([c in TUI for c in codes])
WARMUP = 25
ELIG = (np.isfinite(O) & np.isfinite(C) & np.isfinite(amt20) & (amt20 > 0)
        & (hist_n >= WARMUP) & (C >= 2.0) & (~tui_mask[None, :]))

def rk(M): return pd.DataFrame(np.where(ELIG, M, np.nan)).rank(axis=1, pct=True).to_numpy()
S_BASE = rk(amt20) + rk(atr20)
_rk_turn = rk(turn20)
# 缺 turn 的票（96 只深度退市无 baostock 数据, 覆盖率 63%）填中性分位 0.5（申报）
_rk_turn = np.where(np.isfinite(_rk_turn), _rk_turn, 0.5)
S_TURN = S_BASE + _rk_turn
TOPS = {}
for nm, S in [("base", S_BASE), ("turn", S_TURN)]:
    TOPS[nm] = np.argsort(np.where(ELIG & np.isfinite(S), S, np.inf), axis=1)[:, :25]

def run_ln(variant, N, F, offset):
    shares = np.zeros(NC); cost_basis = np.zeros(NC)
    cash = CASH0; eq_curve = np.full(ND, np.nan); trades = []
    entry_di = np.full(NC, -1); pend_buy = []; pend_sell = []
    eq_prev = cash; top = TOPS[variant]
    for d in range(WARMUP, ND):
        px_open = O[d]; px_prev = close_ff[d - 1]
        if pend_sell:
            keep = []
            for j in pend_sell:
                if not np.isfinite(px_open[j]) or px_open[j] <= px_prev[j] * 0.902:
                    keep.append(j); continue
                px = px_open[j] * (1 - SLIP); amt = px * shares[j]
                fee = max(amt * COMM, MIN_COMM) + amt * TAX
                cash += amt - fee
                ret = (amt - fee) / cost_basis[j] - 1 if cost_basis[j] > 0 else np.nan
                trades.append((entry_di[j], d, (amt - fee) - cost_basis[j], ret))
                shares[j] = 0.0; cost_basis[j] = 0.0; entry_di[j] = -1
            pend_sell = keep
        if pend_buy:
            for j in pend_buy:
                if shares[j] > 0 or not np.isfinite(px_open[j]) or px_open[j] <= 0.01: continue
                if px_open[j] >= px_prev[j] * 1.098: continue
                budget = eq_prev / N
                lots = math.floor(min(budget, cash) / (px_open[j] * (1 + SLIP) * 100.0))
                if lots < 1: continue
                px = px_open[j] * (1 + SLIP); amt = px * lots * 100.0
                fee = max(amt * COMM, MIN_COMM)
                if amt + fee > cash: continue
                cash -= amt + fee; shares[j] = lots * 100.0
                cost_basis[j] = amt + fee; entry_di[j] = d - 1
            pend_buy = []
        nz = np.flatnonzero(shares)
        eq_prev = cash if len(nz) == 0 else cash + float(np.dot(shares[nz], close_ff[d][nz]))
        eq_curve[d] = eq_prev
        if (d - WARMUP - offset) % F == 0 and d + 1 < ND:
            tgt = [int(j) for j in top[d][:N]]; tgtS = set(tgt)
            held = np.flatnonzero(shares > 0)
            for j in held:
                if int(j) not in tgtS: pend_sell.append(int(j))
            n_after = int(len([j for j in held if int(j) in tgtS]))
            pend_buy = [j for j in tgt if shares[j] == 0]
    eq = pd.Series(eq_curve[WARMUP:], index=pd.to_datetime(cal[WARMUP:])).ffill().dropna()
    ret = eq.pct_change().dropna(); yrs = len(eq) / 244.0
    ann = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    sharpe = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    closed = [t for t in trades if np.isfinite(t[3])]
    return dict(ann=float(ann), sharpe=float(sharpe), mdd=float(dd), n_trades=len(closed),
                win=float(np.mean([t[3] > 0 for t in closed])) if closed else np.nan)

results = {}
for nm, N, F in [("base", 10, 60), ("turn", 20, 30), ("base", 20, 30), ("turn", 10, 60)]:
    shs = []
    for off in range(F):
        m = run_ln(nm, N, F, off)
        shs.append(m["sharpe"])
        if off == 0:
            log(f"{nm}/N{N}/F{F} off0: ann {m['ann']*100:+.2f}% S={m['sharpe']:.3f} mdd={m['mdd']*100:.1f}% trades={m['n_trades']}")
    log(f"{nm}/N{N}/F{F} phmed S={np.median(shs):.3f} phmin={min(shs):.2f} phmax={max(shs):.2f}")
    results[f"{nm}_N{N}_F{F}"] = dict(phmed_sharpe=float(np.median(shs)), phmin=float(min(shs)), phmax=float(max(shs)))
m0b = run_ln("base", 10, 60, 0)
m0t = run_ln("turn", 20, 30, 0)
out = dict(meta=dict(pool="full 3469", extra_turn_coverage=float(cov), warmup=WARMUP, cash0=CASH0),
           base_N10_F60=dict(off0_ann=m0b["ann"], off0_sharpe=m0b["sharpe"], **results["base_N10_F60"]),
           turn_N20_F30=dict(off0_ann=m0t["ann"], off0_sharpe=m0t["sharpe"], **results["turn_N20_F30"]),
           val_em_pool_ref=dict(base_phmed=0.529, turn_phmed=0.750, note="前轮 val_em 池"))
# 影子轨初始清单: turn/N20/F30 最后一个调仓窗的目标（asof 最新日）
_di = ND - 1
_sc = S_TURN[_di]
_ok = np.where(ELIG[_di] & np.isfinite(_sc))[0]
_ok = sorted(_ok, key=lambda j: _sc[j])[:20]
shadow = [dict(code=codes[j], close=float(close_ff[_di, j]), score=float(_sc[j])) for j in _ok]
out["shadow_turn_top20"] = shadow
out["shadow_asof"] = str(cal[-1])
for s in shadow[:5]:
    log(f"shadow {s['code']} score={s['score']:.4f} close={s['close']:.2f}")
json.dump(out, open(OUT / "turn_recheck_0913.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved turn_recheck_0913.json DONE")
