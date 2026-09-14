# -*- coding: utf-8 -*-
"""oss_0913 批7: 冷门低波 data_full 全池复验（上轮报告承诺的下一步）
池: data_full 全部主板 (sh600/601/603/605 + sz000/001/002/003), 补齐 val_em 缺失票(冷门尾部/退市)
臂: base/N10/F60（基线锚） + turn/N20/F30（本轮最优） 全相位
口径: 100 万 / T+1 开盘 / 20bp / 排"退"（名称表 + 末期无行情双保险）
"""
import numpy as np, pandas as pd, pickle, json, os, math, time
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
ci0 = {c: i for i, c in enumerate(codes0)}
ND = len(cal)
di = {d: i for i, d in enumerate(cal)}
O0 = P["open"].astype(np.float64); C0 = P["close"].astype(np.float64); A0 = P["amt"].astype(np.float64)

# ---- 补齐 data_full 缺失主板票 ----
extra = []
for f in sorted((BASE / "data_full").glob("*.csv")):
    s = f.stem  # sh600xxx
    if not (s.startswith(("sh600", "sh601", "sh603", "sh605", "sz000", "sz001", "sz002", "sz003"))):
        continue
    c = s[2:]
    if c not in ci0:
        extra.append((c, f))
log("extra files:", len(extra))

Oe = np.full((ND, len(extra)), np.nan); Ce = np.full((ND, len(extra)), np.nan); Ae = np.full((ND, len(extra)), np.nan)
for k, (c, f) in enumerate(extra):
    d = pd.read_csv(f, parse_dates=["date"])
    d["d"] = d["date"].dt.strftime("%Y-%m-%d")
    d = d[d["d"].isin(di)].drop_duplicates("d").set_index("d")
    idx = [di[x] for x in d.index]
    Oe[idx, k] = d["open"].to_numpy(); Ce[idx, k] = d["close"].to_numpy(); Ae[idx, k] = d["amount"].to_numpy()
    if k % 100 == 0: log("loaded", k)
O = np.hstack([O0, Oe]); C = np.hstack([C0, Ce]); AMT = np.hstack([A0, Ae])
codes = codes0 + [c for c, _ in extra]
NC = len(codes)
log("full pool:", NC, "cols (extra", len(extra), ")")

# fmv: 缺失票用 NaN（turn20 对这些票不可用 -> 兜底用 amt 排名分位替代? 用 NaN 并在 score 里跳过）
FMV0 = P["fmv"].astype(np.float64)
FMVe = np.full((ND, len(extra)), np.nan)
FMV = np.hstack([FMV0, FMVe])

close_ff = pd.DataFrame(C).ffill().to_numpy()
Cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
with np.errstate(all="ignore"):
    TR = np.maximum.reduce([C - Cprev, np.abs(C - Cprev), np.abs(C - Cprev)])  # 缺 H/L -> 用 C 近似（申报）
# 注意: extra 票只有 O/C/A, 无 H/L -> TR 用 |C-Cprev| 近似（对 atr20 偏低估计, 申报）
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
atr20_e = pd.DataFrame(np.abs(C - Cprev)).rolling(20, min_periods=15).mean().to_numpy() / close_ff
ret60 = close_ff / pd.DataFrame(close_ff).shift(60).to_numpy() - 1

# 名称"退"排除
_nh = pd.read_csv(BASE / "data_fundamental" / "name_hist.csv", dtype={"code": str}).sort_values("TRADE_DATE").groupby("code").tail(1)
_name = _nh.set_index("code")["SECURITY_NAME_ABBR"].astype(str)
TUI_SET = set(_name[_name.str.contains("退")].index)
tui_mask = np.array([c in TUI_SET for c in codes])

WARMUP = 25
first_valid = np.argmax(np.isfinite(O), axis=0)
hist_n = np.cumsum(np.isfinite(O), axis=0)
hist_n = hist_n + np.where((first_valid == 0)[None, :], 1000, 0)
ELIG = (np.isfinite(O) & np.isfinite(C) & np.isfinite(amt20) & (amt20 > 0)
        & (hist_n >= WARMUP) & (C >= 2.0) & (~tui_mask[None, :]))

def rk(M): return pd.DataFrame(np.where(ELIG, M, np.nan)).rank(axis=1, pct=True).to_numpy()
S_BASE = rk(amt20) + rk(atr20_e)
S_TURN = S_BASE  # 缺 fmv -> turn 不可算, 用 base 近似 + 申报（或换 amp 近似）
# 保守: 全池复验两条臂 = base（严格可比） + turn20（仅 val_em 子集有 fmv -> 不完整） -> 只报 base
TOP = {}
for nm, S in [("base", S_BASE)]:
    ORDER = np.argsort(np.where(ELIG & np.isfinite(S), S, np.inf), axis=1)
    TOP[nm] = ORDER[:, :25]

def run_ln(variant, N, F, offset):
    shares = np.zeros(NC); cost_basis = np.zeros(NC)
    cash = CASH0; eq_curve = np.full(ND, np.nan); trades = []
    entry_di = np.full(NC, -1); pend_buy = []; pend_sell = []
    eq_prev = cash
    top = TOP[variant]
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
    ret = eq.pct_change().dropna()
    yrs = len(eq) / 244.0
    ann = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    sharpe = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    closed = [t for t in trades if np.isfinite(t[3])]
    return dict(ann=float(ann), sharpe=float(sharpe), mdd=float(dd), n_trades=len(closed),
                win=float(np.mean([t[3] > 0 for t in closed])) if closed else np.nan)

log("=== 全池复验: base/N10/F60 全相位 ===")
shs = []
for off in range(60):
    m = run_ln("base", 10, 60, off)
    shs.append(m["sharpe"])
    if off == 0: log(f"  off0: ann {m['ann']*100:+.2f}% S={m['sharpe']:.3f} mdd={m['mdd']*100:.1f}% trades={m['n_trades']} win={m['win']*100:.0f}%")
log(f"  phmed S={np.median(shs):.3f} phmin={min(shs):.2f} phmax={max(shs):.2f}")
m_o = run_ln("base", 10, 60, 0)
res = dict(pool="data_full full mainboard", n_cols=NC, n_extra=len(extra),
           arm="base/N10/F60", off0=dict(ann=m_o["ann"], sharpe=m_o["sharpe"], mdd=m_o["mdd"],
           n_trades=m_o["n_trades"], win=m_o["win"]),
           phmed_sharpe=float(np.median(shs)), phmin=float(min(shs)), phmax=float(max(shs)),
           note="extra 票无 H/L -> ATR 用 |C-Cprev| 近似（atr20 偏低, 申报）；turn 因子因缺 fmv 未测")
json.dump(res, open(OUT / "satellite_fullpool_0913.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved satellite_fullpool_0913.json")
log(f"对比: val_em 池 base/N10/F60 off0 S=0.713（前轮）| 全池 off0 S={m_o['sharpe']:.3f}")
