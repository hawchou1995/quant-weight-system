# -*- coding: utf-8 -*-
"""
Top1 联合敏感度：牛熊分域判定标准 x RSI 出场阈值调整（θ30 主口径 + θ20 对照 · K=5 · 兜底5 · 3种子 · 双成本）
上游：§11 两张单因子网格（θ20 口径）+ §11D 复格（θ30 冻结候选）。本脚本 = 联合网格（含交互观测）。
输出：jiandi_top_grid_0924_out/top1_validate_joint_sensitivity_0924.json
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
CAP = 5; K = 5
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
    return (lambda dt: prev_map.get(pd.Timestamp(dt)))

VARIANTS = {
    'V1 ma60_3(生产)': dict(bear_ma=60, bull_ma=20, two_state=False),
    'V2 ma20_3': dict(bear_ma=20, bull_ma=60, two_state=False),
    'V3 ma120_3': dict(bear_ma=120, bull_ma=20, two_state=False),
    'V4 ma250_3': dict(bear_ma=250, bull_ma=20, two_state=False),
    'V5 ma60_2': dict(bear_ma=60, bull_ma=20, two_state=True),
    'V6 ma250_2': dict(bear_ma=250, bull_ma=20, two_state=True),
}
RHOS = {
    'P0 域55/75/80(生产)': {0: 55, 1: 75, 2: 80},
    'P1 域55/65/65(A6)': {0: 55, 1: 65, 2: 65},
    'P2 域60/65/65': {0: 60, 1: 65, 2: 65},
    'P3 域55/70/70': {0: 55, 1: 70, 2: 70},
    'P4 固定55(A5)': {0: 55, 1: 55, 2: 55},
}
def thr_for(cfg, rho):
    return {0: rho[0], 1: rho[1]} if cfg['two_state'] else {0: rho[0], 1: rho[1], 2: rho[2]}

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
        sell = B + CAP
        if sell >= n or bad[B:sell + 1].any(): continue
        if code not in DA:
            DA[code] = dict(o=o, h=h, l=l, c=c, dates=dates, rsi=rsiN(df['close'], 14),
                            pos={d: k for k, d in enumerate(dates)})
        events.append((sd, code, B, sell))
log(f"事件池 {len(events)}")
EVS = {t: [e for e in events if res_daily[e[0]] >= t] for t in (20, 30)}
log(f"θ20 {len(EVS[20])} / θ30 {len(EVS[30])}")

def win_ok(code, B, sell):
    da = DA[code]; oo = da['o'][B:sell + 1]; cc = da['c'][B:sell + 1]
    return bool(np.isfinite(oo).all() and np.isfinite(cc).all() and (oo > 0).all() and (cc > 0).all())

def arm_rsi(evs, reg_fn, thr_map):
    out = []
    for (sd, code, B, sell0) in evs:
        da = DA[code]; rsi = da['rsi']; dts = da['dates']; n = len(dts)
        sell = min(B + CAP, n - 1)
        for d in range(B, min(B + CAP, n)):
            st = reg_fn(dts[d]); thr = thr_map.get(st if st is not None else 0, 55)
            if np.isfinite(rsi[d]) and rsi[d] >= thr:
                sell = min(d + 1, B + CAP); break
        if sell <= B or sell >= n: continue
        if not win_ok(code, B, sell): continue
        out.append((sd, code, B, sell))
    return out

def sim(trades, KK, seed, rt, cal, want_series=False):
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
        free = KK - len(positions)
        if cands and free > 0:
            pick = cands if len(cands) <= free else [cands[j] for j in sorted(rng.choice(len(cands), size=free, replace=False))]
            for tr in pick: positions.append(dict(code=tr[0], entry=tr[1], exit=tr[2], w=1.0 / KK))
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

def sim_multi(evs, rt):
    tr = to_trades(evs); rr = [sim(tr, K, sd_, rt, CAL) for sd_ in SEEDS3]
    return {k: round(float(np.mean([x[k] for x in rr])), 3) for k in ('cagr', 'sharpe', 'mdd')}

RES = dict(generated_at=time.strftime('%Y-%m-%d %H:%M:%S'), K=K, cap=CAP, seeds=SEEDS3,
           note='分域判定标准 x RSI 阈值 联合敏感度（θ30 主口径 + θ20 对照；含交互观测）')
CELLS = {}
for TH in (30, 20):
    log(f"== 联合网格 θ{TH}：6 分域标准 x 5 RSI 配置 = 30 格 ==")
    cells = []
    for vn, cfg in VARIANTS.items():
        reg_fn = build_regime(**cfg)
        dist = defaultdict(int)
        for e in EVS[TH]: dist[reg_fn(e[0])] += 1
        for pn, rho in RHOS.items():
            thr = thr_for(cfg, rho)
            arm = arm_rsi(EVS[TH], reg_fn, thr)
            rr = np.array([DA[c]['o'][s2] / DA[c]['o'][B] - 1 for _sd, c, B, s2 in arm])
            cell = dict(regime=vn, rho=pn, thr=thr, n=len(arm),
                        ev_mean=round(float(rr.mean()) * 100, 3), ev_wr=round(float((rr > 0).mean()) * 100, 2),
                        sim_020=sim_multi(arm, 0.002), sim_115=sim_multi(arm, 0.0115),
                        ev_regime_dist={str(k): v for k, v in sorted(dist.items())})
            cells.append(cell)
            log(f"  {vn} | {pn}: n={cell['n']} ev={cell['ev_mean']}% | 0.2%{cell['sim_020']} | 1.15%{cell['sim_115']}")
    CELLS[TH] = cells
    log(f"θ{TH} baseline(纯持5日): {dict(n=len(EVS[TH]), sim_020=sim_multi(EVS[TH], 0.002), sim_115=sim_multi(EVS[TH], 0.0115))}")
RES['grid'] = {str(k): v for k, v in CELLS.items()}
RES['baseline_no_timing'] = {str(t): dict(n=len(EVS[t]), sim_020=sim_multi(EVS[t], 0.002), sim_115=sim_multi(EVS[t], 0.0115)) for t in (20, 30)}

reg_fn1 = build_regime(**VARIANTS['V1 ma60_3(生产)'])
conc = {}
for (th, pn) in ((30, 'P1 域55/65/65(A6)'), (30, 'P4 固定55(A5)'), (30, 'P0 域55/75/80(生产)'), (20, 'P1 域55/65/65(A6)')):
    arm = arm_rsi(EVS[th], reg_fn1, RHOS[pn])
    _, s_ = sim(to_trades(arm), K, 20260921, 0.0115, CAL, want_series=True)
    tot = float(s_.sum())
    conc[f'θ{th}|{pn}'] = dict(n=len(arm), top10_share=round(float(s_.nlargest(10).sum()) / tot * 100, 1) if tot > 0 else None)
    log(f"  conc θ{th} {pn}: {conc[f'θ{th}|{pn}']}")
RES['concentration_115'] = conc

summary = {}
for th in (30, 20):
    cells = CELLS[th]
    by_rho = {}
    for pn in RHOS:
        sh = [c['sim_115']['sharpe'] for c in cells if c['rho'] == pn]
        best = sorted([c for c in cells if c['rho'] == pn], key=lambda x: -x['sim_115']['sharpe'])[0]
        by_rho[pn] = dict(range_sharpe_115=round(max(sh) - min(sh), 3), best_regime=best['regime'],
                          best_cagr=best['sim_115']['cagr'], best_sharpe=best['sim_115']['sharpe'])
    by_reg = {}
    for vn in VARIANTS:
        sh = [c['sim_115']['sharpe'] for c in cells if c['regime'] == vn]
        best = sorted([c for c in cells if c['regime'] == vn], key=lambda x: -x['sim_115']['sharpe'])[0]
        by_reg[vn] = dict(range_sharpe_115=round(max(sh) - min(sh), 3), best_rho=best['rho'],
                          best_cagr=best['sim_115']['cagr'], best_sharpe=best['sim_115']['sharpe'])
    bc = sorted(cells, key=lambda x: -x['sim_115']['sharpe'])[0]
    summary[f'theta{th}'] = dict(by_rho=by_rho, by_regime=by_reg,
                                 best_cell_115=dict(regime=bc['regime'], rho=bc['rho'], cagr=bc['sim_115']['cagr'], sharpe=bc['sim_115']['sharpe'], mdd=bc['sim_115']['mdd']))
    log(f"θ{th} best@1.15%: {summary[f'theta{th}']['best_cell_115']}")
RES['summary'] = summary
with open(os.path.join(OUT, 'top1_validate_joint_sensitivity_0924.json'), 'w', encoding='utf-8') as fh:
    json.dump(RES, fh, ensure_ascii=False, indent=1, default=str)
log("SAVED top1_validate_joint_sensitivity_0924.json"); log("DONE")