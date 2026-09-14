# -*- coding: utf-8 -*-
"""oss_0913 批2: niuone 七战法策略级回测（每日候选 → T+1 开盘轮动）
口径: 2021-01-04 起 / T 收盘信号 → T+1 开盘成交 / 主板 3209 池（val_em 口径）
      成本: 佣金 2.5bp + 卖税 5bp + 滑点 20bp / 17 万整手+最低佣 5 元
      退出（简化申报）: 持有 H 日到期 或 收盘 < BBI×0.97 → T+1 开盘卖
      买入: actionable 候选（score≥threshold ∧ 无 hard blockers）按 decision_score 降序
网格: 7 战法 × N{5,10} × H{5,10,20} = 42 臂 + 等权全候选合并臂
"""
import numpy as np, pandas as pd, pickle, json, os, math, time, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oss_niuone_lib_0913 import STRATEGIES, prefilter

BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
OUT = os.path.join(BASE, "backtest", "oss_0913")
CASH0 = 170_000.0
COMM, TAX, SLIP, MIN_COMM = 0.00025, 0.0005, 0.0020, 5.0
AMT_FLOOR = 5e7; PRICE_FLOOR = 2.0; MIN_HIST = 150
WARMUP = 150
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

with open(os.path.join(OUT, "oss_panel_0913.pkl"), "rb") as fh:
    P = pickle.load(fh)
cal = P["cal"]; codes = P["codes"]; st = P["st_mask"]
ND, NC = P["close"].shape
E = P["ext"]
M = {"open": P["open"].astype(np.float64), "high": P["high"].astype(np.float64),
     "low": P["low"].astype(np.float64), "close": P["close"].astype(np.float64),
     "vol": P["vol"].astype(np.float64), "amt": P["amt"].astype(np.float64),
     "fmv": P["fmv"].astype(np.float64)}
for k, v in E.items():
    M[k] = v.astype(np.float64)
close_ff = pd.DataFrame(M["close"]).ffill().to_numpy()
amt20 = pd.DataFrame(M["amt"]).rolling(20, min_periods=15).mean().to_numpy()
hist_n = np.cumsum(np.isfinite(M["open"]), axis=0)
coreb = np.array([c[:3] in ("600", "601", "603", "605", "000", "001", "002") for c in codes])
ELIG = (np.isfinite(M["open"]) & np.isfinite(M["close"]) & (amt20 >= AMT_FLOOR)
        & (~st[None, :]) & (hist_n >= MIN_HIST) & (M["close"] > PRICE_FLOOR))
log("panel loaded; elig/day:", int(ELIG[WARMUP:].sum(axis=1).mean()))

# ---------- 扫描: 每日 actionable 候选 ----------
CAND = {}
for strat, cfg in STRATEGIES.items():
    fn = cfg["fn"]; n_ev = 0
    cands = {}
    for di in range(WARMUP, ND):
        pf = prefilter(M, di, strat) & ELIG[di]
        js = np.flatnonzero(pf)
        if len(js) == 0: continue
        day = []
        for j in js:
            r = fn(M, di, int(j), bool(coreb[j])) if strat == "li_daxiao" else fn(M, di, int(j))
            if r is None: continue
            n_ev += 1
            if r["score"] >= r["threshold"] and not r["blockers"]:
                day.append((int(j), r["score"] + r["priority"] / 100.0))
        if day:
            day.sort(key=lambda x: -x[1])
            cands[di] = day
    CAND[strat] = cands
    n_days = len(cands); n_sig = sum(len(v) for v in cands.values())
    log(f"scan {strat}: {n_ev} evals, {n_days} signal days, {n_sig} actionable sigs, avg/day={n_sig/max(1,n_days):.1f}")

# ---------- 回测引擎 (每日轮动) ----------
def run_daily(cands, N, H, slip=SLIP, cash0=CASH0, use_bbi_stop=True):
    shares = np.zeros(NC); cost_basis = np.zeros(NC)
    cash = cash0; eq_curve = np.full(ND, np.nan); trades = []
    entry_di = np.full(NC, -1); pend_buy = []; pend_sell = []
    eq_prev_known = cash0
    def mark(di):
        nz = np.flatnonzero(shares)
        return cash if len(nz) == 0 else cash + float(np.dot(shares[nz], close_ff[di][nz]))
    for di in range(WARMUP, ND):
        px_open = M["open"][di]; px_prev = close_ff[di - 1]
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
                if shares[j] > 0 or not np.isfinite(px_open[j]) or not ELIG[di - 1][j]: continue
                if px_open[j] >= px_prev[j] * 1.098: continue
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
        # ---- 收盘信号 ----
        held = np.flatnonzero(shares > 0)
        # 1) 退出检查
        for j in held:
            j = int(j)
            expired = (di - entry_di[j]) >= H
            bbi_brk = use_bbi_stop and np.isfinite(M["bbi"][di, j]) and M["close"][di, j] < M["bbi"][di, j] * 0.97
            if expired or bbi_brk:
                if j not in pend_sell: pend_sell.append(j)
        # 2) 买入填充
        slots = N - len(held) + len([j for j in pend_sell if shares[j] > 0])
        if slots > 0 and di in cands:
            held_set = set(int(j) for j in held)
            pend_set = set(pend_sell)
            picks = [j for j, ds in cands[di] if j not in held_set and j not in pend_set][:slots]
            pend_buy = picks
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

# ---------- 网格 ----------
results = []
for strat in STRATEGIES:
    cands = CAND[strat]
    if not cands:
        log(f"{strat}: NO SIGNALS, skip"); continue
    for N in [5, 10]:
        for H in [5, 10, 20]:
            m = run_daily(cands, N, H)
            results.append(dict(strategy=strat, N=N, H=H, off0=dict(
                total=m["total"], ann=m["ann"], sharpe=m["sharpe"], mdd=m["mdd"],
                win=m["win"], n_trades=m["n_trades"], by_year=m["by_year"])))
            log(f"{strat:16s} N={N:2d} H={H:2d} | ann {m['ann']*100:+7.2f}% S={m['sharpe']:+.2f} mdd={m['mdd']*100:5.1f}% trades={m['n_trades']:4d} win={m['win']*100 if m['win']==m['win'] else float('nan'):.0f}%")

# 合并臂: 全战法候选合并 (decision_score 跨策略排序)
merged = {}
for strat, cands in CAND.items():
    for di, lst in cands.items():
        merged.setdefault(di, []).extend(lst)
for di in merged:
    merged[di].sort(key=lambda x: -x[1])
m = run_daily(merged, 10, 10)
results.append(dict(strategy="ALL_MERGED", N=10, H=10, off0=dict(
    total=m["total"], ann=m["ann"], sharpe=m["sharpe"], mdd=m["mdd"],
    win=m["win"], n_trades=m["n_trades"], by_year=m["by_year"])))
log(f"{'ALL_MERGED':16s} N=10 H=10 | ann {m['ann']*100:+7.2f}% S={m['sharpe']:+.2f} mdd={m['mdd']*100:5.1f}% trades={m['n_trades']}")

# 排序输出
results.sort(key=lambda r: -r["off0"]["sharpe"])
log("=== TOP 10 by Sharpe ===")
for r in results[:10]:
    e = r["off0"]
    yy = " ".join(f"{y}:{v:+.2f}" for y, v in e["by_year"].items())
    log(f"{r['strategy']:16s} N={r['N']:2d} H={r['H']:2d} S={e['sharpe']:+.2f} ann={e['ann']*100:+.2f}% mdd={e['mdd']*100:.1f}% | {yy}")

out = dict(meta=dict(n_arms=len(results), window="2021-01-04~2026-09-11", pool="mainboard 3209",
                     cost=dict(comm=COMM, tax=TAX, slip=SLIP, min_comm=MIN_COMM),
                     exit_rule="H-day expiry OR close<BBI*0.97 (simplified, declared)",
                     candidates={s: sum(len(v) for v in c.values()) for s, c in CAND.items()}),
           results=results)
with open(os.path.join(OUT, "niuone_bt_0913.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1, default=float)
log("saved niuone_bt_0913.json DONE")
