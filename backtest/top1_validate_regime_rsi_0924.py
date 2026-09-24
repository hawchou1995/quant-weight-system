# -*- coding: utf-8 -*-
"""
Top1 敏感度 · A：分域判定标准网格（6 变体） + RSI 出场阈值网格（熊×牛×弱） + RSI 周期微检
基线：K>=2 共振 + θ=20 + 单边0.575% ；出场=RSI域出场(兜底5)；组合级 K=5·3种子
"""
import os, sys, time, json
from collections import defaultdict
import numpy as np, pandas as pd

T0 = time.time()
def log(m): print(f"[{time.time()-T0:7.1f}s] {m}", flush=True)
BASE = r'D:\Documents\Workbuddy\股票基金\quant-weight-system'
BK = os.path.join(BASE, 'backtest'); OUT = os.path.join(BK, 'jiandi_top_grid_0924_out')
sys.path.insert(0, BK)
BS = pd.Timestamp('2016-06-01'); W_LO, W_HI = pd.Timestamp('2016-06-01'), pd.Timestamp('2026-09-23')
SEEDS3 = [20260921, 20260922, 20260923]
import jiandi_signal_0906 as JG

idx = pd.read_csv(os.path.join(BASE, 'index_000300.csv'))
idx['date'] = pd.to_datetime(idx['date']); idx = idx.sort_values('date').reset_index(drop=True)
for maw in (20, 60, 120, 250):
    idx[f'ma{maw}'] = idx['close'].rolling(maw, min_periods=1).mean()
CAL = [d for d in idx['date'] if W_LO <= d <= W_HI]

def build_regime(bear_ma, bull_ma=20, two_state=False):
    is_bear = (idx['close'] < idx[f'ma{bear_ma}']).to_numpy()
    if two_state:
        state = np.where(is_bear, 0, 1)
    else:
        bull = (~is_bear) & (idx['close'] > idx[f'ma{bull_ma}']).to_numpy()
        state = np.where(is_bear, 0, np.where(bull, 1, 2))
    prev_map = {}; prev = None
    for k, dt in enumerate(idx['date']):
        prev_map[dt] = prev if prev is not None else 0
        prev = int(state[k])
    return (lambda dt: prev_map.get(pd.Timestamp(dt))), prev_map

VARIANTS = {
    'V1 ma60_3(生产标准)': dict(bear_ma=60, bull_ma=20, two_state=False),
    'V2 ma20_3': dict(bear_ma=20, bull_ma=60, two_state=False),
    'V3 ma120_3': dict(bear_ma=120, bull_ma=20, two_state=False),
    'V4 ma250_3': dict(bear_ma=250, bull_ma=20, two_state=False),
    'V5 ma60_2(两态)': dict(bear_ma=60, bull_ma=20, two_state=True),
    'V6 ma250_2(两态)': dict(bear_ma=250, bull_ma=20, two_state=True),
}
THR3 = {0: 55, 1: 75, 2: 80}

def rsiN(c, n):
    delta = c.diff(); gain = delta.clip(lower=0).rolling(n, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(n, min_periods=1).mean()
    return (100 - 100 / (1 + gain / loss.replace(0, np.nan))).to_numpy()

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
            DA[code] = dict(o=o, h=h, l=l, c=c, dates=dates, rsi=rsiN(df['close'], 14),
                            pos={d: k for k, d in enumerate(dates)})
        events.append((sd, code, B, sell))
evsB = [e for e in events if res_daily[e[0]] >= 20]
log(f"事件 {len(events)} / 基线 {len(evsB)}")

def win_ok(code, B, sell):
    da = DA[code]; oo = da['o'][B:sell + 1]; cc = da['c'][B:sell + 1]
    return bool(np.isfinite(oo).all() and np.isfinite(cc).all() and (oo > 0).all() and (cc > 0).all())

def arm_rsi(evs, cap, reg_fn, thr_map, rsi_key='rsi'):
    out = []
    for (sd, code, B, sell0) in evs:
        da = DA[code]; rsi = da[rsi_key]; dts = da['dates']; n = len(dts)
        sell = min(B + cap, n - 1)
        for d in range(B, min(B + cap, n)):
            st = reg_fn(dts[d]); thr = thr_map.get(st if st is not None else 0, 55)
            if np.isfinite(rsi[d]) and rsi[d] >= thr:
                sell = min(d + 1, B + cap); break
        if sell <= B or sell >= n: continue
        if not win_ok(code, B, sell): continue
        out.append((sd, code, B, sell))
    return out

def sim(trades, K, seed, rt, cal):
    by_day = defaultdict(list)
    for tr in trades: by_day[tr[1]].append(tr)
    positions = []; rng = np.random.default_rng(seed)
    nv = 1.0; rets = []
    for d in cal:
        ret = 0.0; still = []
        for p in positions:
            if p['exit'] == d:
                da = DA[p['code']]; k = da['pos'].get(d)
                if k is None or k == 0: continue
                ret += p['w'] * (float(da['o'][k]) / float(da['c'][k - 1]) - 1 - rt)
            else:
                still.append(p)
        positions = still
        cands = by_day.get(d, [])
        free = K - len(positions)
        if cands and free > 0:
            pick = cands if len(cands) <= free else [cands[j] for j in sorted(rng.choice(len(cands), size=free, replace=False))]
            for tr in pick: positions.append(dict(code=tr[0], entry=tr[1], exit=tr[2], w=1.0 / K))
        for p in positions:
            da = DA[p['code']]; k = da['pos'].get(d)
            if k is None or k == 0: continue
            if p.get('entry') == d:
                ret += p['w'] * (float(da['c'][k]) / float(da['o'][k]) - 1)
            else:
                ret += p['w'] * (float(da['c'][k]) / float(da['c'][k - 1]) - 1)
        nv *= (1 + ret); rets.append(ret)
    s = pd.Series(rets, index=pd.DatetimeIndex(cal))
    nvv = (1 + s).cumprod(); span = (s.index[-1] - s.index[0]).days / 365.25
    return dict(cagr=round(float((nvv.iloc[-1]) ** (1 / max(span, 1e-9)) - 1) * 100, 2),
                sharpe=round(float(s.mean() / s.std() * np.sqrt(252)) if s.std() > 0 else 0.0, 3),
                mdd=round(float((nvv / nvv.cummax() - 1).min()) * 100, 2)), s

def to_trades(evs):
    return [(c, DA[c]['dates'][B], DA[c]['dates'][s]) for _sd, c, B, s in evs]

def sim_multi(evs, K, rt, seeds=SEEDS3):
    rr = []
    for sd_ in seeds:
        r, _ = sim(to_trades(evs), K, sd_, rt, CAL)
        rr.append(r)
    return {k: round(float(np.mean([x[k] for x in rr])), 3) for k in ('cagr', 'sharpe', 'mdd')}

# ============ 1) 分域判定标准网格 ============
log("1) 分域判定标准网格 ...")
reg_rows = []
for name, cfg in VARIANTS.items():
    reg_fn, _ = build_regime(**cfg)
    thr = dict(THR3) if not cfg['two_state'] else {0: 55, 1: 75}
    # 域分布
    dist = defaultdict(int)
    for e in evsB: dist[reg_fn(e[0])] += 1
    armA2 = arm_rsi(evsB, 5, reg_fn, thr)
    gate = [e for e in evsB if reg_fn(e[0]) == 0]
    row = dict(variant=name, dist={str(k): v for k, v in sorted(dist.items())},
               armA2_n=len(armA2), gate_n=len(gate))
    row['armA2_sim_020'] = sim_multi(armA2, 5, 0.002)
    row['armA2_sim_115'] = sim_multi(armA2, 5, 0.0115)
    row['gate_sim_020'] = sim_multi(gate, 5, 0.002)
    reg_rows.append(row)
    log(f"  {name}: dist={row['dist']} A2@{row['armA2_sim_020']} / 1.15%{row['armA2_sim_115']} | gate@{row['gate_sim_020']}")
RES = dict(generated_at=time.strftime('%Y-%m-%d %H:%M:%S'), section='A_regime_and_rsi_grids')
RES['regime_variants'] = reg_rows
RES['baseline_no_timing'] = dict(sim_020=sim_multi(evsB, 5, 0.002), sim_115=sim_multi(evsB, 5, 0.0115))
log(f"  baseline(无择时): {RES['baseline_no_timing']}")

# ============ 2) RSI 出场阈值网格（V1 生产分域） ============
log("2) RSI 阈值网格（熊×强牛×弱牛，兜底5, K=5, rt0.2%, seed1） ...")
reg_fn1, _ = build_regime(60, 20, False)
bear_list = [45, 50, 55, 60, 65]
o_bull = [65, 70, 75, 80]
o_weak = [65, 70, 75, 80]
grid = []
for b in bear_list:
    for u in o_bull:
        for w in o_weak:
            thr = {0: b, 1: u, 2: w}
            arm = arm_rsi(evsB, 5, reg_fn1, thr)
            if len(arm) < 100: continue
            r, s = sim(to_trades(arm), 5, 20260921, 0.002, CAL)
            rr = np.array([DA[c]['o'][s2] / DA[c]['o'][B] - 1 for _sd, c, B, s2 in arm])
            grid.append(dict(bear=b, bull=u, weak=w, n=len(arm),
                             mean=round(float(rr.mean()) * 100, 3), wr=round(float((rr > 0).mean()) * 100, 2),
                             cagr=r['cagr'], sharpe=r['sharpe'], mdd=r['mdd']))
log(f"  网格 {len(grid)} 格")
top = sorted(grid, key=lambda x: -x['sharpe'])[:8]
log("  top8(sharpe): " + json.dumps(top, ensure_ascii=False))
# top6 精修：rt 1.15% + 3 种子
refined = []
for g in sorted(grid, key=lambda x: -x['sharpe'])[:6]:
    thr = {0: g['bear'], 1: g['bull'], 2: g['weak']}
    arm = arm_rsi(evsB, 5, reg_fn1, thr)
    rr = sim_multi(arm, 5, 0.002); rr2 = sim_multi(arm, 5, 0.0115)
    refined.append(dict(thr=thr, n=len(arm), sim_020=rr, sim_115=rr2))
    log(f"  refine {thr}: {rr} / {rr2}")
RES['rsi_grid_top8_seed1'] = top
RES['rsi_grid_refined'] = refined

# 固定阈值网格（不分域）
fixg = []
for t in (45, 50, 55, 60, 65, 70, 75, 80):
    arm = arm_rsi(evsB, 5, reg_fn1, {0: t, 1: t, 2: t})
    rr = sim_multi(arm, 5, 0.002); rr2 = sim_multi(arm, 5, 0.0115)
    fixg.append(dict(thr=t, n=len(arm), sim_020=rr, sim_115=rr2))
    log(f"  fixed {t}: {rr} / {rr2}")
RES['rsi_fixed_grid'] = fixg

# ============ 3) RSI 周期微检（6/9/14/21） ============
log("3) RSI 周期微检 ...")
per_rows = []
uniq_codes = sorted(set(e[1] for e in evsB))
import pandas as _pd
for p in (6, 9, 21):
    for code in uniq_codes:
        DA[code]['rsi_p'] = rsiN(cache[code]['close'], p)
    for label, thr in (('域 55/75/80', {0: 55, 1: 75, 2: 80}), ('固定55', {0: 55, 1: 55, 2: 55})):
        arm = arm_rsi(evsB, 5, reg_fn1, thr, rsi_key='rsi_p')
        rr = sim_multi(arm, 5, 0.002)
        per_rows.append(dict(rsi_period=p, thr=label, n=len(arm), sim_020=rr))
        log(f"  RSI{p} {label}: {rr}")
RES['rsi_period_check'] = per_rows

with open(os.path.join(OUT, 'top1_validate_regime_rsi_0924.json'), 'w', encoding='utf-8') as fh:
    json.dump(RES, fh, ensure_ascii=False, indent=1, default=str)
log("SAVED top1_validate_regime_rsi_0924.json"); log("DONE")
