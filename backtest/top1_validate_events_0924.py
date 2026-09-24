# -*- coding: utf-8 -*-
"""
Top1 验证 · 事件层（2026-09-24）：A阈值邻域 / B集中度与留一 / C涨跌停可成交性 / E牛熊分域 / F择时臂
基线：K>=2 共振 + θ=当日共振家数>=20 + N=5（B+5 开盘卖）+ 单边0.575%
口径：分域/RSI = 生产 KHunter 同款（熊=HS300<MA60；强牛=非熊且>MA20；弱牛=其余；RSI(14) 简单平均；卖出阈值 熊55/牛75/弱牛80）
输出：jiandi_top_grid_0924_out/top1_validate_events_0924.json
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
YEARS_SPAN = 10.31
COST = 0.00575
RSI_SELL = {0: 55, 1: 75, 2: 80}

import jiandi_signal_0906 as JG

# ---------- 分域（严格 T-1，KHunter 同款） ----------
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
idx_open = idx.set_index('date')['open']

def rsi14(c):
    delta = c.diff(); gain = delta.clip(lower=0).rolling(14, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=1).mean()
    return (100 - 100 / (1 + gain / loss.replace(0, np.nan))).to_numpy()

# ---------- 单次遍历：信号 / 事件 / DA ----------
log("加载缓存 ...")
cache0 = pd.read_pickle(os.path.join(BASE, 'v8_factor_cache.pkl'))
cache = {c: df.sort_index() for c, df in cache0.items() if df is not None and JG.board_of(c) == 'main'}
SIG_KEYS = ('rushi', 'jihui', 'jiandi', 'kuaixian', 'laiLin', 'deng')
DA = {}
events = {2: [], 3: []}
res_daily = defaultdict(int)
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
            DA[code] = dict(dates=dates, o=o, h=h, l=l, c=c,
                            rsi=rsi14(df['close']), idx={d: k for k, d in enumerate(dates)})
        if cnt[i] >= 2: events[2].append((sd, code, B, sell))
        if cnt[i] >= 3: events[3].append((sd, code, B, sell))
log(f"事件池 K2={len(events[2])} K3={len(events[3])}")

def netc(bo, so, c): return so * (1 - c) / (bo * (1 + c)) - 1
def ev_ret(e, cost=COST):
    sd, code, B, sell = e; da = DA[code]
    return float(netc(da['o'][B], da['o'][sell], cost))
def ev_exb(e):
    sd, code, B, sell = e; da = DA[code]
    b0 = idx_open.get(da['dates'][B]); b1 = idx_open.get(da['dates'][sell])
    if b0 is None or b1 is None or b0 <= 0: return np.nan
    return ev_ret(e) - (float(b1) / float(b0) - 1)
def stats(evs, cost=COST):
    if not evs: return dict(n=0)
    r = np.array([ev_ret(e, cost) for e in evs]); exb = np.array([ev_exb(e) for e in evs])
    wins, losses = r[r > 0], r[r < 0]
    return dict(n=len(r), wr=round(float((r > 0).mean()) * 100, 2), med=round(float(np.median(r)) * 100, 3),
                mean=round(float(r.mean()) * 100, 3), ex_b=round(float(np.nanmean(exb)) * 100, 3),
                pf=round(float(wins.mean() / abs(losses.mean())), 2) if len(wins) and len(losses) else None)
def nav_event(evs, cost=COST, want_series=False):
    daily = defaultdict(list)
    for (sd, code, B, sell) in evs:
        da = DA[code]; o = da['o']; c = da['c']; dts = da['dates']
        daily[dts[B]].append(c[B] / o[B] - 1 - cost)
        for k in range(B + 1, sell): daily[dts[k]].append(c[k] / c[k - 1] - 1)
        daily[dts[sell]].append(o[sell] / c[sell - 1] - 1 - cost)
    if not daily: return None
    s = pd.Series({d: float(np.mean(v)) for d, v in daily.items()}).sort_index()
    full = pd.date_range(s.index[0], s.index[-1], freq='B'); s = s.reindex(full, fill_value=0.0)
    nav = (1 + s).cumprod(); span = (nav.index[-1] - nav.index[0]).days / 365.25
    dd = float((nav / nav.cummax() - 1).min()); sh = float(s.mean() / s.std() * np.sqrt(252)) if s.std() > 0 else 0.0
    out = dict(total=round(float(nav.iloc[-1] - 1) * 100, 2),
               cagr=round(float((nav.iloc[-1]) ** (1 / max(span, 1e-9)) - 1) * 100, 2),
               maxdd=round(dd * 100, 2), sharpe=round(sh, 3))
    return (out, s) if want_series else out

RES = dict(generated_at=time.strftime('%Y-%m-%d %H:%M:%S'), window=['2016-06-01', '2026-09-23'])

# ================= A. 阈值邻域 =================
log("A. 阈值邻域 ...")
sweep = []
for K in (2, 3):
    for th in (10, 15, 20, 25, 30):
        evs = [e for e in events[K] if res_daily[e[0]] >= th]
        if len(evs) < 30:
            sweep.append(dict(K=K, th=th, n=len(evs), note='n<30')); continue
        row = dict(K=K, th=th, n=len(evs), days=len(set(e[0] for e in evs)),
                   events_per_year=round(len(evs) / YEARS_SPAN, 1))
        row.update(stats(evs)); row['nav'] = nav_event(evs)
        sweep.append(row)
        log(f"  K>={K} th>={th}: {row}")
RES['A_sweep'] = sweep

# ================= 基线（K2 th20） =================
evsB = [e for e in events[2] if res_daily[e[0]] >= 20]
base_nav, base_s = nav_event(evsB, want_series=True)
RES['base'] = dict(K=2, th=20, stats=stats(evsB), nav=base_nav)
log(f"基线: {RES['base']}")

# ================= B. 集中度 + 留一 =================
log("B. 集中度 / 留一年 ...")
byd = defaultdict(float)
for d, v in base_s.items(): byd[pd.Timestamp(d).year] += float(np.log1p(v))
tot_log = sum(byd.values())
s18 = base_s[base_s.index.year == 2018]
top_days = [[str(d)[:10], round(float(v), 4)] for d, v in base_s.nlargest(10).items()]
RES['B_concentration'] = dict(
    by_year_log={str(y): round(v, 4) for y, v in sorted(byd.items())}, total_log=round(tot_log, 4),
    top10_days=top_days, top10_share_pct=round(sum(v for _, v in top_days) / tot_log * 100, 1),
    y2018_top5=[[str(d)[:10], round(float(v), 4)] for d, v in s18.nlargest(5).items()],
    y2018_top5_share_pct=round(float(s18.nlargest(5).sum()) / float(s18.sum()) * 100, 1))
loo = []
for y in range(2017, 2027):
    ex = [e for e in evsB if pd.Timestamp(e[0]).year != y]
    nv = nav_event(ex)
    loo.append(dict(year=y, **nv))
    log(f"  leave-{y}: {nv}")
RES['B_loo'] = loo

# ================= C. 涨跌停可成交性 =================
log("C. 涨跌停可成交性 ...")
ok_buy, bad_buy = [], []
for e in evsB:
    sd, code, B, sell = e; da = DA[code]
    o, h, l, c = da['o'], da['h'], da['l'], da['c']
    pc = c[B - 1] if B >= 1 else np.nan
    onew_up = (h[B] == l[B] == o[B] == c[B]) and np.isfinite(pc) and pc > 0 and (c[B] / pc - 1) >= 0.095
    (bad_buy if onew_up else ok_buy).append(e)
adj = []; moved_cnt = defaultdict(int); stuck = 0
for e in evsB:
    sd, code, B, sell0 = e; da = DA[code]
    o, h, l, c, dts = da['o'], da['h'], da['l'], da['c'], da['dates']
    d = sell0; moved = 0
    while d < len(dts):
        pc = c[d - 1]
        fillable = (np.isfinite(o[d]) and o[d] > 0 and np.isfinite(pc) and pc > 0
                    and not ((h[d] == l[d] == o[d] == c[d]) and (c[d] / pc - 1) <= -0.095))
        if fillable: break
        d += 1; moved += 1
        if moved > 10: break
    if d >= len(dts) or moved > 10:
        stuck += 1; d = sell0
    moved_cnt[moved] += 1
    adj.append((sd, code, B, d))
RES['C_fill'] = dict(
    n_base=len(evsB), n_buy_unfillable=len(bad_buy),
    stats_base=stats(evsB), stats_after_buyfilter=stats(ok_buy), stats_after_both=stats(adj),
    nav_after_both=nav_event(adj),
    n_sell_deferred=int(sum(v for k, v in moved_cnt.items() if k > 0)), n_stuck=stuck,
    defer_hist={str(k): v for k, v in sorted(moved_cnt.items())},
    unfillable_buy_samples=[[str(e[0])[:10], e[1]] for e in bad_buy[:10]])
log(f"  C: {RES['C_fill']}")

# ================= E. 牛熊分域 =================
log("E. 牛熊分域 ...")
REG_NM = {0: 'bear', 1: 'bull', 2: 'weak'}
reg_rows = []
for rg in (0, 1, 2):
    evs2 = [e for e in evsB if regime_of(e[0]) == rg]
    row = dict(regime=REG_NM[rg], days=len(set(e[0] for e in evs2)))
    row.update(stats(evs2))
    row['nav'] = nav_event(evs2) if len(evs2) >= 30 else None
    reg_rows.append(row)
    log(f"  {REG_NM[rg]}: n={row['n']} mean={row.get('mean')} nav={row['nav']}")
RES['E_regime'] = reg_rows

# ================= F. 择时臂 =================
log("F. 择时臂 ...")
def rsi_arm(evs, cap=5, use_regime=True, fix_thr=55):
    out = []
    for (sd, code, B, sell0) in evs:
        da = DA[code]; rsi = da['rsi']; dts = da['dates']; n = len(dts)
        sell = min(B + cap, n - 1)
        for d in range(B, B + cap):
            if d >= n: break
            thr = (RSI_SELL.get(regime_of(dts[d]), 55) if use_regime else fix_thr)
            if np.isfinite(rsi[d]) and rsi[d] >= thr:
                sell = min(d + 1, B + cap); break
        if sell <= B or sell >= n: continue
        out.append((sd, code, B, sell))
    return out

arms = []
A1 = [e for e in evsB if regime_of(e[0]) == 0]
A2 = rsi_arm(evsB, cap=5, use_regime=True)
A3 = rsi_arm(evsB, cap=20, use_regime=True)
A4 = rsi_arm(A1, cap=5, use_regime=True)
A5 = rsi_arm(evsB, cap=5, use_regime=False, fix_thr=55)
for nm_, evs2 in (('A1 熊市门(仅熊域)', A1), ('A2 RSI分域出场(兜底5)', A2),
                  ('A3 RSI分域出场(兜底20)', A3), ('A4 熊市门+RSI出场5', A4), ('A5 RSI固定55出场(兜底5)', A5)):
    row = dict(arm=nm_, n=len(evs2), avg_hold=round(float(np.mean([e[3] - e[2] for e in evs2])), 2) if evs2 else None)
    row.update(stats(evs2))
    row['nav'] = nav_event(evs2)
    arms.append(row)
    log(f"  {nm_}: n={row['n']} mean={row.get('mean')} hold={row['avg_hold']} nav={row['nav']}")
RES['F_arms'] = arms

with open(os.path.join(OUT, 'top1_validate_events_0924.json'), 'w', encoding='utf-8') as fh:
    json.dump(RES, fh, ensure_ascii=False, indent=1, default=str)
log("SAVED top1_validate_events_0924.json")
log("DONE")
