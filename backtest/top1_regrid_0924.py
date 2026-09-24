# -*- coding: utf-8 -*-
"""
Top1 复格（批准项）：arms{baseline, A2域(55/75/80), A5固定55, A6域(55/65/65)} x K{5,10} x θ{20,25,30} x rt{0.2%,1.15%} x 3 seeds
引擎：修正版（入场日 c/o、中间 ctc、出场日 o/前收 - rt）
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
for maw in (20, 60): idx[f'ma{maw}'] = idx['close'].rolling(maw, min_periods=1).mean()
idx['is_bear'] = idx['close'] < idx['ma60']; idx['bull_ma20'] = idx['close'] > idx['ma20']
sp = {}; prev = None
for dt in sorted(idx['date']):
    sp[dt] = prev if prev is not None else 0
    row = idx.loc[idx['date'] == dt]
    prev = 0 if bool(row['is_bear'].iloc[0]) else (1 if bool(row['bull_ma20'].iloc[0]) else 2)
def reg(dt):
    v = sp.get(pd.Timestamp(dt))
    return 0 if v is None else v
CAL = [d for d in idx['date'] if W_LO <= d <= W_HI]

cache0 = pd.read_pickle(os.path.join(BASE, 'v8_factor_cache.pkl'))
cache = {c: df.sort_index() for c, df in cache0.items() if df is not None and JG.board_of(c) == 'main'}
SIG_KEYS = ('rushi', 'jihui', 'jiandi', 'kuaixian', 'laiLin', 'deng')
DA = {}; events = []; res_daily = defaultdict(int)
log("加载缓存 + 信号 ...")
for code, df in cache.items():
    if len(df) < 70: continue
    sm = JG.jiandi_signals(code, df)
    sig6 = np.stack([np.asarray(sm[k], bool) for k in SIG_KEYS], axis=1)
    cnt = sig6.sum(axis=1)
    if not (cnt >= 2).any(): continue
    o = df['open'].to_numpy(); h = df['high'].to_numpy(); l = df['low'].to_numpy(); c = df['close'].to_numpy()
    bad = (~np.isfinite(o)) | (~np.isfinite(c)) | (o <= 0) | (c <= 0)
    dates = df.index; n = len(df)
    def rsiN(cs, m):
        delta = cs.diff(); gain = delta.clip(lower=0).rolling(m, min_periods=1).mean()
        loss = (-delta.clip(upper=0)).rolling(m, min_periods=1).mean()
        return (100 - 100 / (1 + gain / loss.replace(0, np.nan))).to_numpy()
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
log(f"事件池 {len(events)}")

def win_ok(code, B, sell):
    da = DA[code]; oo = da['o'][B:sell + 1]; cc = da['c'][B:sell + 1]
    return bool(np.isfinite(oo).all() and np.isfinite(cc).all() and (oo > 0).all() and (cc > 0).all())

def arm_rsi(evs, cap, thr_map):
    out = []
    for (sd, code, B, sell0) in evs:
        da = DA[code]; rsi = da['rsi']; dts = da['dates']; n = len(dts)
        sell = min(B + cap, n - 1)
        for d in range(B, min(B + cap, n)):
            st = reg(dts[d]); thr = thr_map.get(st if st is not None else 0, 55)
            if np.isfinite(rsi[d]) and rsi[d] >= thr:
                sell = min(d + 1, B + cap); break
        if sell <= B or sell >= n: continue
        if not win_ok(code, B, sell): continue
        out.append((sd, code, B, sell))
    return out

def sim(trades, K, seed, rt, cal, want_series=False):
    by_day = defaultdict(list)
    for tr in trades: by_day[tr[1]].append(tr)
    positions = []; rng = np.random.default_rng(seed); nv = 1.0; rets = []
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
    r = dict(cagr=round(float((nvv.iloc[-1]) ** (1 / max(span, 1e-9)) - 1) * 100, 2),
             sharpe=round(float(s.mean() / s.std() * np.sqrt(252)) if s.std() > 0 else 0.0, 3),
             mdd=round(float((nvv / nvv.cummax() - 1).min()) * 100, 2))
    return (r, s) if want_series else r

def to_trades(evs):
    return [(c, DA[c]['dates'][B], DA[c]['dates'][s]) for _sd, c, B, s in evs]

ARMS = {
    'baseline(N=5)': None,
    'A2 域55/75/80': {0: 55, 1: 75, 2: 80},
    'A5 固定55': {0: 55, 1: 55, 2: 55},
    'A6 域55/65/65': {0: 55, 1: 65, 2: 65},
}
rows = []
for th in (20, 25, 30):
    evsθ = [e for e in events if res_daily[e[0]] >= th]
    for anm, thr in ARMS.items():
        arm = evsθ if thr is None else arm_rsi(evsθ, 5, thr)
        tr = to_trades(arm)
        for K in (5, 10):
            for rt, rtn in ((0.002, '0.20%'), (0.0115, '1.15%')):
                rr = [sim(tr, K, sd_, rt, CAL) for sd_ in SEEDS3]
                agg = {k: round(float(np.mean([x[k] for x in rr])), 3) for k in ('cagr', 'sharpe', 'mdd')}
                rows.append(dict(th=th, arm=anm, K=K, rt=rtn, n=len(arm), **agg))
                log(f"θ{th} {anm} K={K} rt={rtn}: cagr={agg['cagr']} sh={agg['sharpe']} mdd={agg['mdd']} (n={len(arm)})")
RES = dict(generated_at=time.strftime('%Y-%m-%d %H:%M:%S'), rows=rows)
best = sorted(rows, key=lambda x: (-(x['rt'] == '1.15%'), -x['sharpe']))[:1]
log("（排序中间结果，完整见 JSON）")
# 全表按 1.15% 档 sharpe 排序打印 top12
top115 = sorted([r for r in rows if r['rt'] == '1.15%'], key=lambda x: -x['sharpe'])[:12]
log("== 1.15% 成本档 top12 ==")
for r in top115:
    log("  " + json.dumps(r, ensure_ascii=False))
top020 = sorted([r for r in rows if r['rt'] == '0.20%'], key=lambda x: -x['sharpe'])[:12]
log("== 0.20% 成本档 top12 ==")
for r in top020:
    log("  " + json.dumps(r, ensure_ascii=False))
# 最高组合的集中度（1.15% 档最优）
b = top115[0]
evsθ = [e for e in events if res_daily[e[0]] >= b['th']]
thr = ARMS[b['arm']]
arm = evsθ if thr is None else arm_rsi(evsθ, 5, thr)
_, s_ = sim(to_trades(arm), b['K'], 20260921, 0.0115, CAL, want_series=True)
tot = float(s_.sum())
RES['best_115'] = b
RES['best_115_concentration'] = dict(top10_share=round(float(s_.nlargest(10).sum()) / tot * 100, 1) if tot > 0 else None)
log(f"best@1.15%: {b} | top10日占比={RES['best_115_concentration']}")
with open(os.path.join(OUT, 'top1_validate_regrid_0924.json'), 'w', encoding='utf-8') as fh:
    json.dump(RES, fh, ensure_ascii=False, indent=1, default=str)
log("SAVED top1_validate_regrid_0924.json"); log("DONE")
