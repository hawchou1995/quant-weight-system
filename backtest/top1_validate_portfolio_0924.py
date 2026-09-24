# -*- coding: utf-8 -*-
"""
Top1 验证 · 组合层（2026-09-24）：D槽位仿真 / 择时臂修正版 / G与qlch相关性+增量
引擎口径 = 生产同款（等权、w=1/K、入场日 c/o、中间收盘链、出场日 open/前收 或 close/前收 - 往返成本加法式）
"""
import os, sys, time, json
from collections import defaultdict
import numpy as np, pandas as pd

T0 = time.time()
def log(m): print(f"[{time.time()-T0:7.1f}s] {m}", flush=True)

BASE = r'D:\Documents\Workbuddy\股票基金\quant-weight-system'
BK = os.path.join(BASE, 'backtest')
OUT = os.path.join(BK, 'jiandi_top_grid_0924_out')
sys.path.insert(0, BK)
BS = pd.Timestamp('2016-06-01')
W_LO, W_HI = pd.Timestamp('2016-06-01'), pd.Timestamp('2026-09-23')
RSI_SELL = {0: 55, 1: 75, 2: 80}
SEEDS = [20260921, 20260922, 20260923, 20260924, 20260925]

import jiandi_signal_0906 as JG

# ---------- 分域 ----------
idx = pd.read_csv(os.path.join(BASE, 'index_000300.csv'))
idx['date'] = pd.to_datetime(idx['date']); idx = idx.sort_values('date').reset_index(drop=True)
for maw in (20, 60): idx[f'ma{maw}'] = idx['close'].rolling(maw, min_periods=1).mean()
idx['is_bear'] = idx['close'] < idx['ma60']; idx['bull_ma20'] = idx['close'] > idx['ma20']
state_prev = {}; prev = None
for dt in sorted(idx['date']):
    state_prev[dt] = prev if prev is not None else {'is_bear': True, 'bull_ma20': False}
    row = idx.loc[idx['date'] == dt]
    prev = {'is_bear': bool(row['is_bear'].iloc[0]), 'bull_ma20': bool(row['bull_ma20'].iloc[0])}
def regime_of(dt):
    s = state_prev.get(pd.Timestamp(dt))
    if s is None: return None
    return 0 if s['is_bear'] else (1 if s['bull_ma20'] else 2)
CAL_HS = [d for d in idx['date'] if W_LO <= d <= W_HI]
def rsi14(c):
    delta = c.diff(); gain = delta.clip(lower=0).rolling(14, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=1).mean()
    return (100 - 100 / (1 + gain / loss.replace(0, np.nan))).to_numpy()

# ---------- Top1 事件 + DA ----------
log("加载缓存 + 信号 ...")
cache0 = pd.read_pickle(os.path.join(BASE, 'v8_factor_cache.pkl'))
cache = {c: df.sort_index() for c, df in cache0.items() if df is not None and JG.board_of(c) == 'main'}
SIG_KEYS = ('rushi', 'jihui', 'jiandi', 'kuaixian', 'laiLin', 'deng')
DA = {}; events = []; res_daily = defaultdict(int)
for code, df in cache.items():
    if len(df) < 70: continue
    sm = JG.jiandi_signals(code, df)
    sig6 = np.stack([np.asarray(sm[k], bool) for k in SIG_KEYS], axis=1)
    cnt = sig6.sum(axis=1)
    if not (cnt >= 2).any(): continue
    o = df['open'].to_numpy(); h = df['high'].to_numpy(); l = df['low'].to_numpy(); c = df['close'].to_numpy()
    bad = (~np.isfinite(o)) | (~np.isfinite(c)) | (o <= 0) | (c <= 0)
    dates = df.index; n = len(df)
    for i in np.where(cnt >= 2)[0]:
        sd = dates[i]
        if sd < BS: continue
        res_daily[sd] += 1
        B = i + 1
        if B >= n or bad[B]: continue
        sell = B + 5
        if sell >= n or bad[B:sell + 1].any(): continue
        if code not in DA:
            DA[code] = dict(o=o, h=h, l=l, c=c, dates=dates, rsi=rsi14(df['close']),
                            pos={d: k for k, d in enumerate(dates)})
        events.append((sd, code, B, sell))
log(f"K2 事件 {len(events)}")
evsB = [e for e in events if res_daily[e[0]] >= 20]
log(f"基线（th>=20）事件 {len(evsB)}")

# ---------- 择时臂（修正版：加窗口价格守卫） ----------
def window_ok(code, B, sell):
    da = DA[code]; oo = da['o'][B:sell + 1]; cc = da['c'][B:sell + 1]
    return bool(np.isfinite(oo).all() and np.isfinite(cc).all() and (oo > 0).all() and (cc > 0).all())

def arm_rsi(evs, cap):
    out = []
    for (sd, code, B, sell0) in evs:
        da = DA[code]; rsi = da['rsi']; dts = da['dates']; n = len(dts)
        sell = min(B + cap, n - 1)
        for d in range(B, min(B + cap, n)):
            thr = RSI_SELL.get(regime_of(dts[d]), 55)
            if np.isfinite(rsi[d]) and rsi[d] >= thr:
                sell = min(d + 1, B + cap); break
        if sell <= B or sell >= n: continue
        if not window_ok(code, B, sell): continue
        out.append((sd, code, B, sell))
    return out

A1 = [e for e in evsB if regime_of(e[0]) == 0]
A2 = arm_rsi(evsB, 5)
A3 = arm_rsi(evsB, 20)
A5 = arm_rsi(evsB, 5)  # (与 A2 相同分域阈值；固定 55 档下一轮单独算)
def arm_rsi_fix(evs, cap, thr):
    out = []
    for (sd, code, B, sell0) in evs:
        da = DA[code]; rsi = da['rsi']; dts = da['dates']; n = len(dts)
        sell = min(B + cap, n - 1)
        for d in range(B, min(B + cap, n)):
            if np.isfinite(rsi[d]) and rsi[d] >= thr:
                sell = min(d + 1, B + cap); break
        if sell <= B or sell >= n: continue
        if not window_ok(code, B, sell): continue
        out.append((sd, code, B, sell))
    return out
A5 = arm_rsi_fix(evsB, 5, 55)

def netc(bo, so, c): return so * (1 - c) / (bo * (1 + c)) - 1
def stats(evs, cost=0.00575):
    if not evs: return dict(n=0)
    r = np.array([netc(float(DA[c]['o'][B]), float(DA[c]['o'][s]), cost) for _sd, c, B, s in evs])
    wins, losses = r[r > 0], r[r < 0]
    return dict(n=len(r), wr=round(float((r > 0).mean()) * 100, 2),
                med=round(float(np.median(r)) * 100, 3), mean=round(float(r.mean()) * 100, 3),
                pf=round(float(wins.mean() / abs(losses.mean())), 2) if len(wins) and len(losses) else None)
log(f"臂: A1={len(A1)} A2={len(A2)} A3={len(A3)} A5={len(A5)}")
log(f"  A2 stats {stats(A2)} / A3 {stats(A3)} / A5 {stats(A5)}")

# ---------- 组合仿真引擎 ----------
def sim(trades, da, K, seed, rt, exit_mode, cal):
    by_day = defaultdict(list)
    for tr in trades: by_day[tr[1]].append(tr)
    positions = []; rng = np.random.default_rng(seed)
    nav = 1.0; rets = []; navs = []; invested_sum = 0.0; n_traded = 0
    for d in cal:
        ret = 0.0; invested = 0.0; still = []
        for p in positions:
            if p['exit'] == d:
                dd_ = da[p['code']]; k = dd_['pos'].get(d)
                if k is None or k == 0: continue
                prev = dd_['c'][k - 1]
                px = dd_['o'][k] if exit_mode == 'open' else dd_['c'][k]
                ret += p['w'] * (float(px) / float(prev) - 1 - rt)
                invested += p['w']
            else:
                still.append(p)
        positions = still
        cands = by_day.get(d, [])
        free = K - len(positions)
        if cands and free > 0:
            pick = cands if len(cands) <= free else [cands[j] for j in sorted(rng.choice(len(cands), size=free, replace=False))]
            for tr in pick:
                positions.append(dict(code=tr[0], entry=tr[1], exit=tr[2], w=1.0 / K)); n_traded += 1
        for p in positions:
            dd_ = da[p['code']]; k = dd_['pos'].get(d)
            if k is None or k == 0: continue
            if p['entry'] == d:
                ret += p['w'] * (float(dd_['c'][k]) / float(dd_['o'][k]) - 1)
            else:
                ret += p['w'] * (float(dd_['c'][k]) / float(dd_['c'][k - 1]) - 1)
            invested += p['w']
        nav *= (1 + ret); rets.append(ret); navs.append(nav); invested_sum += invested
    s = pd.Series(rets, index=pd.DatetimeIndex(cal))
    nv = pd.Series(navs, index=pd.DatetimeIndex(cal))
    span = (s.index[-1] - s.index[0]).days / 365.25
    dd = float((nv / nv.cummax() - 1).min())
    sh = float(s.mean() / s.std() * np.sqrt(252)) if s.std() > 0 else 0.0
    return dict(total=round(float(nv.iloc[-1] - 1) * 100, 2),
                cagr=round(float((nv.iloc[-1]) ** (1 / max(span, 1e-9)) - 1) * 100, 2),
                maxdd=round(dd * 100, 2), sharpe=round(sh, 3),
                traded=n_traded, take_rate=round(n_traded / max(len(trades), 1) * 100, 2),
                invested_avg=round(invested_sum / max(len(cal), 1) * 100, 1)), s

def to_trades(evs):
    return [(code, DA[code]['dates'][B], DA[code]['dates'][sell]) for _sd, code, B, sell in evs]

# ---------- D. 组合仿真：基线 K×种子×成本 ----------
log("D. 组合仿真（基线）...")
port_rows = []
for rt, rtn in ((0.0115, 'rt1.15%'), (0.002, 'rt0.20%')):
    for K in (3, 5, 10):
        for seed in SEEDS:
            r, _s = sim(to_trades(evsB), DA, K, seed, rt, 'open', CAL_HS)
            port_rows.append(dict(cost=rtn, K=K, seed=seed, **r))
            log(f"  {rtn} K={K} seed={seed}: cagr={r['cagr']} sh={r['sharpe']} mdd={r['maxdd']} take={r['take_rate']}")
RES2 = dict(generated_at=time.strftime('%Y-%m-%d %H:%M:%S'), D_portfolio_baseline=port_rows)

# ---------- 择时臂组合仿真（K=5, rt0.20%, 3 seeds） ----------
log("择时臂组合仿真 ...")
arm_rows = []
for nm_, evs2 in (('baseline', evsB), ('A1 熊市门', A1), ('A2 RSI域出场5', A2), ('A3 RSI域出场20', A3), ('A5 RSI固定55出场5', A5)):
    rr = []
    for seed in SEEDS[:3]:
        r, _s = sim(to_trades(evs2), DA, 5, seed, 0.002, 'open', CAL_HS)
        rr.append(r)
    agg = {k: round(float(np.mean([x[k] for x in rr])), 3) for k in ('total', 'cagr', 'maxdd', 'sharpe', 'take_rate', 'invested_avg')}
    ev_st = stats(evs2)
    arm_rows.append(dict(arm=nm_, K=5, rt='0.20%', sim_seed_mean=agg, event_stats=ev_st))
    log(f"  {nm_}: sim {agg} | event {ev_st}")
RES2['F_arms_portfolio'] = arm_rows

# ---------- qlch 组合仿真（相关性用） ----------
log("qlch 生产口径重建 ...")
os.environ.setdefault('QLCH_VARIANT', 'B4')
import qlch_paper_20260921 as Q
Pq = Q.load_all(); Sq = Q.build_signals(Pq)
calq = [str(x) for x in Sq['cal']]; codesq = [str(x) for x in Sq['codes']]
Oq, Cq, validq = Sq['open'], Sq['close'], Sq['valid']
cand, gap = Sq['cand'], Sq['gap']
Tq = len(calq)
POSQ = {pd.Timestamp(d): k for k, d in enumerate(calq)}
DAq = {c: dict(o=Oq[:, j], c=Cq[:, j], pos=POSQ) for j, c in enumerate(codesq)}
trq = []
for t in range(1, Tq - 1):
    if calq[t] < '2016-06-01': continue
    if calq[t] > '2026-09-23': break
    row = cand[t - 1] & np.isfinite(gap[t]) & (gap[t] >= Q.GAP_LO) & (gap[t] <= Q.GAP_HI) & validq[t]
    for j in np.where(row)[0]:
        bo, so = float(Oq[t, j]), float(Cq[t + 1, j])
        if not (np.isfinite(bo) and np.isfinite(so)) or bo <= 0 or so <= 0: continue
        trq.append((codesq[j], pd.Timestamp(calq[t]), pd.Timestamp(calq[t + 1])))
log(f"qlch 成交 {len(trq)}")
CAL_Q = [pd.Timestamp(d) for d in calq if '2016-06-01' <= d <= '2026-09-23']
qlch_sims = []
for seed in SEEDS:
    r, s = sim(trq, DAq, 3, seed, 0.002, 'close', CAL_Q)
    qlch_sims.append(r)
    log(f"  qlch K=3 seed={seed}: cagr={r['cagr']} sh={r['sharpe']} mdd={r['maxdd']} take={r['take_rate']}")
q_agg = {k: round(float(np.mean([x[k] for x in qlch_sims])), 3) for k in ('total', 'cagr', 'maxdd', 'sharpe', 'take_rate', 'invested_avg')}
RES2['D_qlch_portfolio'] = dict(K=3, rt='0.20%', seed_mean=q_agg, per_seed=qlch_sims)

# ---------- G. 相关性 + 增量 ----------
log("G. 相关性 / 增量 ...")
_, sA = sim(to_trades(evsB), DA, 5, 20260921, 0.002, 'open', CAL_HS)
_, sQ = sim(trq, DAq, 3, 20260921, 0.002, 'close', CAL_Q)
u = sA.index.union(sQ.index)
A2_ = sA.reindex(u, fill_value=0.0); Q2_ = sQ.reindex(u, fill_value=0.0)
corr = float(A2_.corr(Q2_))
hs_ret = idx.set_index('date')['close'].pct_change().reindex(u, fill_value=0.0)
blend = 0.5 * (A2_ + Q2_)
def series_stats(s):
    nv = (1 + s).cumprod(); span = (s.index[-1] - s.index[0]).days / 365.25
    dd = float((nv / nv.cummax() - 1).min())
    sh = float(s.mean() / s.std() * np.sqrt(252)) if s.std() > 0 else 0.0
    return dict(total=round(float(nv.iloc[-1] - 1) * 100, 2),
                cagr=round(float((nv.iloc[-1]) ** (1 / max(span, 1e-9)) - 1) * 100, 2),
                maxdd=round(dd * 100, 2), sharpe=round(sh, 3))
RES2['G_corr'] = dict(
    corr_top1_qlch=round(corr, 3),
    corr_top1_hs300=round(float(A2_.corr(hs_ret)), 3),
    corr_qlch_hs300=round(float(Q2_.corr(hs_ret)), 3),
    top1=series_stats(A2_), qlch=series_stats(Q2_), blend_5050=series_stats(blend))
log(f"  corr(Top1,qlch)={corr:.3f} | blend: {RES2['G_corr']['blend_5050']}")

with open(os.path.join(OUT, 'top1_validate_portfolio_0924.json'), 'w', encoding='utf-8') as fh:
    json.dump(RES2, fh, ensure_ascii=False, indent=1, default=str)
log("SAVED top1_validate_portfolio_0924.json")
log("DONE")
