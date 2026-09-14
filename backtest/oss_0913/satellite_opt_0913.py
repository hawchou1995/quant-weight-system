# -*- coding: utf-8 -*-
"""oss_0913 批6: 冷门低波卫星优化（预注册 40 臂）
基线: ln_amt20+atr20 双低 Top10 / 60 交易日 → phmed 复现目标 127.4%/16.2%/S 1.238
预注册臂:
  因子变体 4: base / +ret60(低吸) / +turn20(低换手) / +amp20(低振幅)   [每日截面 rank 和]
  TopN {5,10,20} × 调仓 F {30,60,90} × 全相位 → 36 臂
  闸门臂 4: 各变体 × N10 × F60 + sc1000_ma20 半仓
口径: 2021-04 起(180 bar 预热) / 全主板(排"退"留ST) / T 收盘信号→T+1 开盘 / 17 万整手 / 20bp 滑点 / 最低佣 5 元
"""
import numpy as np, pandas as pd, pickle, json, os, math, time
from pathlib import Path

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
CASH0 = 1_000_000.0  # 对齐 track_a 基线口径（净值曲线 2021-01-04=100万）
COMM, TAX, SLIP, MIN_COMM = 0.00025, 0.0005, 0.0020, 5.0
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

with open(OUT / "oss_panel_0913.pkl", "rb") as fh:
    P = pickle.load(fh)
cal = P["cal"]; codes = P["codes"]; st = P["st_mask"]
ND, NC = P["close"].shape
E = P["ext"]
O = P["open"].astype(np.float64); H = P["high"].astype(np.float64)
L = P["low"].astype(np.float64); C = P["close"].astype(np.float64)
AMT = P["amt"].astype(np.float64); FMV = P["fmv"].astype(np.float64)
close_ff = pd.DataFrame(C).ffill().to_numpy()
Cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
with np.errstate(all="ignore"):
    TR = np.maximum.reduce([H - L, np.abs(H - Cprev), np.abs(L - Cprev)])
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
atr20 = pd.DataFrame(TR).rolling(20, min_periods=15).mean().to_numpy() / close_ff
ret60 = (close_ff / pd.DataFrame(close_ff).shift(60).to_numpy() - 1)
turn20 = pd.DataFrame(np.where(FMV > 0, AMT / FMV, np.nan)).rolling(20, min_periods=15).mean().to_numpy()
amp_mat = (E["amp"].astype(np.float64))
amp20 = pd.DataFrame(amp_mat).rolling(20, min_periods=15).mean().to_numpy()
hist_n = np.cumsum(np.isfinite(O), axis=0)
# 名称"退"过滤（与 track_a 口径一致：排退留ST）
_nh = pd.read_csv(BASE / "data_fundamental" / "name_hist.csv", dtype={"code": str}).sort_values("TRADE_DATE").groupby("code").tail(1)
_name = _nh.set_index("code")["SECURITY_NAME_ABBR"].astype(str)
TUI_SET = set(_name[_name.str.contains("退")].index)
tui_mask = np.array([c in TUI_SET for c in codes])

WARMUP = 25
# hist_n 全历史近似: 面板首日(2021-01-04)即存在的股票视为历史充足(2021 前上市), 面板内新上市者用面板内 bar 数
first_valid = np.argmax(np.isfinite(O), axis=0)
hist_n = hist_n + np.where((first_valid == 0)[None, :], 1000, 0)
ELIG = (np.isfinite(O) & np.isfinite(C) & np.isfinite(amt20) & (amt20 > 0)
        & (hist_n >= WARMUP) & (C >= 2.0) & (~tui_mask[None, :]))
log("elig/day:", int(ELIG[WARMUP:].sum(axis=1).mean()))

# ---- 每日截面 rank (0-1, 小者优先) ----
def rk_pct(M):
    return pd.DataFrame(np.where(ELIG, M, np.nan)).rank(axis=1, pct=True).to_numpy()
RK = {"amt": rk_pct(amt20), "atr": rk_pct(atr20), "ret": rk_pct(ret60), "turn": rk_pct(turn20), "amp": rk_pct(amp20)}
VARIANTS = {
    "base": ["amt", "atr"],
    "ret60": ["amt", "atr", "ret"],
    "turn": ["amt", "atr", "turn"],
    "amp": ["amt", "atr", "amp"],
}
SCORE = {}
for v, ks in VARIANTS.items():
    s = np.zeros((ND, NC))
    for k in ks: s += np.where(np.isfinite(RK[k]), RK[k], np.nan)
    SCORE[v] = s
log("scores built")
# 每日排序（一次计算, 所有臂复用）: 返回每日升序索引（分数低者优先）
ORDER = {}
for v in VARIANTS:
    s = SCORE[v]
    ORDER[v] = np.argsort(np.where(ELIG & np.isfinite(s), s, np.inf), axis=1)
log("orders built")
# 预取 Top20 每日候选（按 score 升序, 分数相同不影响）
TOP = {v: ORDER[v][:, :25] for v in VARIANTS}

# sc1000 闸门
def etf_series(fn, col):
    df = pd.read_csv(BASE / "data_full" / fn, parse_dates=["date"])
    df["d"] = df["date"].dt.strftime("%Y-%m-%d")
    return df.drop_duplicates("d").set_index("d")[col].reindex([d for d in cal]).to_numpy()
sc1000 = etf_series("sh512100.csv", "close")
ma20sc = pd.Series(sc1000).rolling(20, min_periods=15).mean().to_numpy()
gate_open = np.isfinite(ma20sc) & (sc1000 > ma20sc)

def run_ln(variant, N, F, offset, use_gate=False, cash0=CASH0, slip=SLIP):
    shares = np.zeros(NC); cost_basis = np.zeros(NC)
    cash = cash0; eq_curve = np.full(ND, np.nan); trades = []
    entry_di = np.full(NC, -1)
    pend_buy = []; pend_sell = []
    eq_prev = cash0
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
            slots = N if not use_gate else (N if gate_open[di - 1] else max(2, N // 2))
            for j in pend_buy:
                if held_n >= slots: break
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
        # 调仓信号
        if (di - WARMUP - offset) % F == 0 and di + 1 < ND:
            tgt = [int(j) for j in top[di][:N]]
            tgtS = set(tgt)
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
    yr = {int(yv): float(eq[eq.index.year == yv].iloc[-1] / eq[eq.index.year == yv].iloc[0] - 1)
          for yv in sorted(set(eq.index.year))}
    return dict(total=float(eq.iloc[-1] / eq.iloc[0] - 1), ann=float(ann), sharpe=float(sharpe),
                mdd=float(dd), n_trades=len(closed),
                win=float(np.mean([t[3] > 0 for t in closed])) if closed else np.nan, by_year=yr)

# ---- 复现基线: base / N10 / F60 / offset0 ----
m0 = run_ln("base", 10, 60, 0)
log(f"BASELINE repro: ann {m0['ann']*100:+.2f}% S={m0['sharpe']:.3f} mdd={m0['mdd']*100:.1f}% trades={m0['n_trades']} (target: 16.18%/1.238/107)")

results = []
for v in VARIANTS:
    for N in [5, 10, 20]:
        for F in [30, 60, 90]:
            shs, anns, offs = [], [], []
            for off in range(F):
                m = run_ln(v, N, F, off)
                shs.append(m["sharpe"]); anns.append(m["ann"]); offs.append(m)
            med_sh, med_ann = float(np.median(shs)), float(np.median(anns))
            o0 = offs[0] if F > 0 else None
            results.append(dict(variant=v, N=N, F=F, gated=False,
                                off0_sharpe=o0["sharpe"], off0_ann=o0["ann"], off0_mdd=o0["mdd"],
                                phmed_sharpe=med_sh, phmed_ann=med_ann, phmin=float(np.min(shs)),
                                phmax=float(np.max(shs))))
            log(f"{v:6s} N={N:2d} F={F:2d} | off0 S={o0['sharpe']:+.3f} ann={o0['ann']*100:+6.2f}% | phmed S={med_sh:.3f} ann={med_ann*100:+6.2f}% phmin={min(shs):.2f}")

# 闸门臂: 各变体 N10 F60 + gate
for v in VARIANTS:
    shs, anns = [], []
    for off in range(60):
        m = run_ln(v, 10, 60, off, use_gate=True)
        shs.append(m["sharpe"]); anns.append(m["ann"])
    med_sh, med_ann = float(np.median(shs)), float(np.median(anns))
    results.append(dict(variant=v, N=10, F=60, gated=True, off0_sharpe=None, off0_ann=None, off0_mdd=None,
                        phmed_sharpe=med_sh, phmed_ann=med_ann, phmin=float(np.min(shs)), phmax=float(np.max(shs))))
    log(f"{v:6s} N=10 F=60 GATED | phmed S={med_sh:.3f} ann={med_ann*100:+6.2f}% phmin={min(shs):.2f}")

results.sort(key=lambda r: -r["phmed_sharpe"])
log("=== TOP 8 (phmed Sharpe) ===")
for r in results[:8]:
    log(f"{r['variant']:6s} N={r['N']:2d} F={r['F']:2d} gated={r['gated']} | phmed S={r['phmed_sharpe']:.3f} ann={r['phmed_ann']*100:+.2f}% phmin={r['phmin']:.2f}")

base_r = [r for r in results if r["variant"] == "base" and r["N"] == 10 and r["F"] == 60 and not r["gated"]][0]
log(f"baseline arm: phmed S={base_r['phmed_sharpe']:.3f} ann={base_r['phmed_ann']*100:+.2f}% (基线 phmed 对比)")

out = dict(meta=dict(window="2021-04~2026-09-11", warmup=180, n_arms=len(results),
                     cost=dict(comm=COMM, tax=TAX, slip=SLIP, min_comm=MIN_COMM),
                     variants={k: v for k, v in VARIANTS.items()},
                     baseline_repro=dict(ann=m0["ann"], sharpe=m0["sharpe"], mdd=m0["mdd"], n_trades=m0["n_trades"]),
                     target_note="track_a 基线 127.45%/16.18%/S1.238/107笔"),
           results=results)
with open(OUT / "satellite_opt_0913.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1, default=float)
log("saved satellite_opt_0913.json DONE")
