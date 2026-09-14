# -*- coding: utf-8 -*-
"""oss_0913 批3: wtfibought 四策略 A 股日线移植 + 事件回测
源: /Tools/wtfibought-src wiib-quant/strategy/{fibo,turtle,sqzmom,smc}/*.java
移植申报（时间尺度映射 crypto→A股日线，全部如实申报为"形态逻辑移植"）:
  TURTLE: 4H 90/15 通道 → 日线 90/15 通道; 触价入场; 止损 2×ATR20; 无固定TP(反向通道退出)
  FIBO:   15m ZigZag 腿+0.66 回撤 → 20 日区间上半+0.66 回撤位挂限价; 止损=区间低-0.1ATR; TP=区间高
  SQZMOM: 4H BB/KC 挤压 → 日线 20 周期 σ(close)<SMA(TR) 连续≥6 根释放 + 动量>0 做多; SL 1.5ATR; TP 2R
  SMC:    4H 偏向/1H FVG → 60 日偏向(close>SMA60) + 3bar FVG 缺口回补(折扣区过滤); SL=缺口沿-0.1ATR; TP=20日高
口径: 2021 起 / 主板 3209 / 成本 20bp 滑点+税费 / 17 万整手 / 限价单与止损止盈按日内触及价成交(跳空按开盘)
网格: 4 策略 × N{5,10} × 持有上限 H{10,20,40} = 24 臂
"""
import numpy as np, pandas as pd, pickle, json, os, math, time
from scipy import stats

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
O = P["open"].astype(np.float64); H = P["high"].astype(np.float64)
L = P["low"].astype(np.float64); C = P["close"].astype(np.float64)
V = P["vol"].astype(np.float64); AMT = P["amt"].astype(np.float64)
ATR = E["atr14"].astype(np.float64)
close_ff = pd.DataFrame(C).ffill().to_numpy()
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
hist_n = np.cumsum(np.isfinite(O), axis=0)
ELIG = (np.isfinite(O) & np.isfinite(C) & (amt20 >= AMT_FLOOR)
        & (~st[None, :]) & (hist_n >= MIN_HIST) & (C > PRICE_FLOOR))
log("elig/day:", int(ELIG[WARMUP:].sum(axis=1).mean()))

# ---------- 指标矩阵 ----------
up90 = pd.DataFrame(H).rolling(90, min_periods=60).max().shift(1).to_numpy()   # 入场通道(排除当前)
dn15 = pd.DataFrame(L).rolling(15, min_periods=10).min().shift(1).to_numpy()   # 退出通道
hi20 = pd.DataFrame(H).rolling(20, min_periods=15).max().to_numpy()
lo20 = pd.DataFrame(L).rolling(20, min_periods=15).min().to_numpy()
hi20x = pd.DataFrame(H).rolling(20, min_periods=15).max().shift(1).to_numpy()
lo20x = pd.DataFrame(L).rolling(20, min_periods=15).min().shift(1).to_numpy()
sma20 = pd.DataFrame(close_ff).rolling(20, min_periods=20).mean().to_numpy()
sma60 = pd.DataFrame(close_ff).rolling(60, min_periods=60).mean().to_numpy()
sig20 = pd.DataFrame(close_ff).rolling(20, min_periods=20).std(ddof=0).to_numpy()
Cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
with np.errstate(all="ignore"):
    TR = np.maximum.reduce([H - L, np.abs(H - Cprev), np.abs(L - Cprev)])
tr20 = pd.DataFrame(TR).rolling(20, min_periods=20).mean().to_numpy()   # SMA(TR,20) 与 KC 同源
log("indicator matrices done")

# ---------- 入场事件生成 ----------
def gen_turtle():
    """触价突破: high[T] >= up90[T-1] 且 前收盘在通道下方(突破首日)"""
    px_th = up90  # 通道价 (T-1 时刻可得)
    trig = (H >= px_th) & (Cprev < px_th) & ELIG & np.isfinite(ATR) & (px_th > 0)
    ents = []
    ii, jj = np.where(trig[WARMUP:])
    for k in range(len(ii)):
        di = int(ii[k]) + WARMUP; j = int(jj[k])
        entry_px = max(px_th[di, j], O[di, j])  # 触价或跳空开盘
        if not np.isfinite(entry_px): continue
        ents.append((di, j, "touch", float(entry_px), float(entry_px - 2.0 * ATR[di, j]), np.nan))
    return ents

def gen_fibo():
    """20日区间上半 + 0.66 回撤挂限价; SL=区间低-0.1ATR; TP=区间高"""
    mid = (hi20x + lo20x) / 2
    upper = (C > mid) & (C < hi20x * 0.998)  # 上行腿中(未创新高)
    pull = hi20x - 0.66 * (hi20x - lo20x)   # 0.66 回撤位
    trig = upper & ELIG & np.isfinite(ATR) & np.isfinite(pull) & (pull > lo20x) & (pull < C)
    ents = []
    ii, jj = np.where(trig[WARMUP:])
    for k in range(len(ii)):
        di = int(ii[k]) + WARMUP; j = int(jj[k])
        lo_v = float(lo20x[di, j]); hi_v = float(hi20x[di, j])
        pv = float(pull[di, j]); slv = float(lo_v - 0.1 * ATR[di, j])
        if not (np.isfinite(pv) and np.isfinite(slv) and pv > 0.01 and slv > 0.01 and slv < pv): continue
        ents.append((di, j, "limit3", pv, slv, float(hi_v)))
    return ents

def gen_sqz():
    """挤压(σ20<TR20)连续≥6根后释放 + 动量>0"""
    on = (sig20 < tr20) & np.isfinite(sig20) & np.isfinite(tr20)
    # 连续计数
    cnt = np.zeros_like(sig20, dtype=np.int32)
    for i in range(1, ND):
        cnt[i] = np.where(on[i], cnt[i - 1] + 1, 0)
    prev_on = np.vstack([np.zeros((1, NC), np.int32), cnt[:-1]])
    rel = (~on) & (prev_on >= 6)  # 释放日
    mom = C - sma20
    trig = rel & (mom > 0) & ELIG & np.isfinite(ATR)
    ents = []
    ii, jj = np.where(trig[WARMUP:])
    for k in range(len(ii)):
        di = int(ii[k]) + WARMUP; j = int(jj[k])
        sl = float(C[di, j] - 1.5 * ATR[di, j]); risk = C[di, j] - sl
        ents.append((di, j, "market", np.nan, sl, float(C[di, j] + 2.0 * risk)))
    return ents

def gen_smc():
    """60日偏向 + 3bar 多头 FVG(折扣区) 回补"""
    bias_up = (C > sma60) & (sma60 > np.vstack([np.full((1, NC), np.nan), sma60[:-1]]))
    gap_up = L > np.vstack([np.full((2, NC), np.nan), H[:-2]])   # low[i] > high[i-2]
    gap_lo = np.vstack([np.full((2, NC), np.nan), H[:-2]])       # 缺口下沿 = high[i-2]
    gap_hi = L
    mid_gap = (gap_lo + gap_hi) / 2
    rng_mid = (hi20x + lo20x) / 2
    disc = mid_gap < rng_mid                                        # 折扣区过滤
    trig = gap_up & disc & bias_up & ELIG & np.isfinite(ATR)
    ents = []
    ii, jj = np.where(trig[WARMUP:])
    for k in range(len(ii)):
        di = int(ii[k]) + WARMUP; j = int(jj[k])
        mg = float(mid_gap[di, j]); slv = float(gap_lo[di, j] - 0.1 * ATR[di, j]); tpv = float(hi20x[di, j])
        if not (np.isfinite(mg) and np.isfinite(slv) and np.isfinite(tpv) and mg > 0.01 and slv > 0.01 and slv < mg): continue
        ents.append((di, j, "limit2", mg, slv, tpv))
    return ents

GEN = {"turtle": gen_turtle, "fibo": gen_fibo, "sqz": gen_sqz, "smc": gen_smc}

# ---------- 事件回测引擎 ----------
def run_events(ents, N, Hmax, slip=SLIP, cash0=CASH0, use_channel_exit=False):
    by_day = {}
    for e in ents: by_day.setdefault(e[0], []).append(e)
    shares = np.zeros(NC); cost_basis = np.zeros(NC)
    pend = {}      # j -> (kind, limit_px, sl, tp, expire_di, signaled_di)
    cash = cash0; eq_curve = np.full(ND, np.nan); trades = []
    entry_di = np.full(NC, -1); sl_arr = np.full(NC, np.nan); tp_arr = np.full(NC, np.nan)
    eq_prev_known = cash0
    def mark(di):
        nz = np.flatnonzero(shares)
        return cash if len(nz) == 0 else cash + float(np.dot(shares[nz], close_ff[di][nz]))
    def do_sell(j, di, px):
        nonlocal cash
        amt = px * shares[j]
        fee = max(amt * COMM, MIN_COMM) + amt * TAX
        proceeds = amt - fee
        cash += proceeds
        ret = proceeds / cost_basis[j] - 1 if cost_basis[j] > 0 else np.nan
        trades.append((entry_di[j], di, proceeds - cost_basis[j], ret))
        shares[j] = 0.0; cost_basis[j] = 0.0; entry_di[j] = -1; sl_arr[j] = np.nan; tp_arr[j] = np.nan
    def do_buy(j, di, px):
        nonlocal cash
        if not (np.isfinite(px) and px > 0.01): return False
        budget = eq_prev_known / N
        if not np.isfinite(budget): return False
        lots = math.floor(min(budget, cash) / (px * (1 + slip) * 100.0))
        if lots < 1: return False
        p = px * (1 + slip); amt = p * lots * 100.0
        fee = max(amt * COMM, MIN_COMM)
        if amt + fee > cash: return False
        cash -= amt + fee; shares[j] = lots * 100.0
        cost_basis[j] = amt + fee; entry_di[j] = di
        return True
    for di in range(WARMUP, ND):
        op = O[di]; lo = L[di]; hi = H[di]
        n_hold = int((shares > 0).sum())
        # ---- 1) 持仓盘中止损/止盈 (跳空按开盘) ----
        for j in np.flatnonzero(shares > 0):
            j = int(j)
            if not np.isfinite(op[j]): continue
            sl = sl_arr[j]; tp = tp_arr[j]
            if np.isfinite(sl) and lo[j] <= sl:
                px = min(sl, op[j]) if op[j] < sl else sl
                do_sell(j, di, px * (1 - slip)); n_hold -= 1; continue
            if np.isfinite(tp) and hi[j] >= tp:
                px = max(tp, op[j]) if op[j] > tp else tp
                do_sell(j, di, px * (1 - slip)); n_hold -= 1; continue
        # ---- 2) 通道退出 (TURTLE: close[T-1] < dn15) ----
        if use_channel_exit:
            for j in np.flatnonzero(shares > 0):
                j = int(j)
                ch = dn15[di - 1, j] if di > 0 else np.nan
                if np.isfinite(ch) and close_ff[di - 1, j] < ch and np.isfinite(op[j]):
                    do_sell(j, di, op[j] * (1 - slip)); n_hold -= 1
        # ---- 3) 超时平仓 (持有 ≥ Hmax 收盘触发 → 当日开盘已过, 用 T+1: 简化当日收盘价) ----
        for j in np.flatnonzero(shares > 0):
            j = int(j)
            if di - entry_di[j] >= Hmax and np.isfinite(close_ff[di, j]):
                do_sell(j, di, close_ff[di, j] * (1 - slip)); n_hold -= 1
        # ---- 4) 限价单执行 (挂单期内: open≤limit → open 成交; 否则 low≤limit → limit 成交) ----
        for j in list(pend.keys()):
            kind, lim, sl, tp, exp_di, sig_di = pend[j]
            if shares[j] > 0: del pend[j]; continue
            if di > exp_di: del pend[j]; continue
            if not np.isfinite(op[j]): continue
            if op[j] <= lim:
                if do_buy(j, di, op[j] * 1.0):
                    sl_arr[j] = sl; tp_arr[j] = tp; del pend[j]; n_hold += 1
            elif lo[j] <= lim:
                if do_buy(j, di, lim):
                    sl_arr[j] = sl; tp_arr[j] = tp; del pend[j]; n_hold += 1
        # ---- 5) 新信号处理 (T 收盘 → T+1 起生效) ----
        if di in by_day:
            sig = by_day[di]
            for (sdi, j, kind, lim, sl, tp) in sig:
                if kind == "market":
                    if n_hold < N and shares[j] == 0 and np.isfinite(O[min(di + 1, ND - 1), j]) and di + 1 < ND:
                        px = O[di + 1, j]
                        if np.isfinite(px) and not (px >= close_ff[di, j] * 1.098):
                            if do_buy(j, di + 1, px):
                                sl_arr[j] = sl; tp_arr[j] = tp; n_hold += 1
                elif kind == "touch":
                    # 触价单: 当日(信号次日)已经在 T+1 开盘执行——用开盘价近似(申报)
                    if n_hold < N and shares[j] == 0 and di + 1 < ND and np.isfinite(O[di + 1, j]):
                        px = O[di + 1, j]
                        if np.isfinite(px) and not (px >= close_ff[di, j] * 1.098):
                            if do_buy(j, di + 1, px):
                                sl_arr[j] = sl; tp_arr[j] = tp; n_hold += 1
                else:  # limitN
                    timeout = 3 if kind == "limit3" else 2
                    if j not in pend and shares[j] == 0 and n_hold < N:
                        pend[j] = (kind, lim, sl, tp, min(di + timeout, ND - 1), di)
        eq_prev_known = mark(di); eq_curve[di] = eq_prev_known
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

# ---------- 生成 + 网格 ----------
ENTS = {}
for nm, fn in GEN.items():
    ents = fn()
    ENTS[nm] = ents
    sig_days = len(set(e[0] for e in ents))
    log(f"gen {nm}: {len(ents)} events on {sig_days} days")

results = []
for nm, ents in ENTS.items():
    if not ents: continue
    for N in [5, 10]:
        for Hmax in [10, 20, 40]:
            m = run_events(ents, N, Hmax, use_channel_exit=(nm == "turtle"))
            results.append(dict(strategy=nm, N=N, H=Hmax, off0=dict(
                total=m["total"], ann=m["ann"], sharpe=m["sharpe"], mdd=m["mdd"],
                win=m["win"], n_trades=m["n_trades"], by_year=m["by_year"])))
            log(f"{nm:8s} N={N:2d} H={Hmax:2d} | ann {m['ann']*100:+7.2f}% S={m['sharpe']:+.2f} mdd={m['mdd']*100:5.1f}% trades={m['n_trades']:4d} win={m['win']*100 if np.isfinite(m['win']) else float('nan'):.0f}%")

results.sort(key=lambda r: -r["off0"]["sharpe"])
log("=== TOP by Sharpe ===")
for r in results[:8]:
    e = r["off0"]
    yy = " ".join(f"{y}:{v:+.2f}" for y, v in e["by_year"].items())
    log(f"{r['strategy']:8s} N={r['N']:2d} H={r['H']:2d} S={e['sharpe']:+.2f} ann={e['ann']*100:+.2f}% mdd={e['mdd']*100:.1f}% | {yy}")

out = dict(meta=dict(n_arms=len(results), window="2021-01-04~2026-09-11", pool="mainboard 3209",
                     cost=dict(comm=COMM, tax=TAX, slip=SLIP, min_comm=MIN_COMM),
                     mapping="crypto 5m/15m/1h/4h → A-share daily (declared approximation)",
                     events={k: len(v) for k, v in ENTS.items()}),
           results=results)
with open(os.path.join(OUT, "wtfibought_bt_0913.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1, default=float)
log("saved wtfibought_bt_0913.json DONE")
