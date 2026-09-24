# -*- coding: utf-8 -*-
"""
见底共振 Top30 前向哨兵（R-jiandi-top30-0924）· 重放式
预注册：backtest/PRE-REGISTRATION_20260924_jiandi_top30_sentinel.md（V1-V4 冻结判据）
三臂：A1 基线(纯持5日) | A2 RSI固定55(主假设) | A3 RSI域55/65/65(次假设·对照)
组合：K=5 等权 · seed=20260921 · 双成本档(0.2%/1.15% 往返) · 分域=生产 MA60_3(T-1)
只可否决：V1/V2/V3 任一触发 -> status=REVIEW_TRIGGERED（不自动改参）；V4 仅诊断
用法：
  python jiandi_top30_sentinel_0924.py                       # 正式运行（写状态）
  python jiandi_top30_sentinel_0924.py --dry                 # 默认起点重放（不写状态）
  python jiandi_top30_sentinel_0924.py --start 2016-06-01 --dry               # 全历史重放校验
  python jiandi_top30_sentinel_0924.py --start 2016-06-01 --dry --seeds 20260921,20260922,20260923
状态：backtest/jiandi_top30_sentinel_state.json
"""
import argparse, os, sys, time, json
from collections import defaultdict
import numpy as np, pandas as pd

T0 = time.time()
def log(m): print(f"[{time.time()-T0:7.1f}s] {m}", flush=True)
BASE = r'D:\Documents\Workbuddy\股票基金\quant-weight-system'
BK = os.path.join(BASE, 'backtest')
STATE_PATH = os.path.join(BK, 'jiandi_top30_sentinel_state.json')
sys.path.insert(0, BK)
BS = pd.Timestamp('2016-06-01'); W_LO, W_HI = pd.Timestamp('2016-06-01'), pd.Timestamp('2026-09-23')
DEFAULT_SHADOW_START = '2026-09-24'
THETA = 30; K = 5; CAP = 5; DEFAULT_SEED = 20260921
V1_MIN_N = 300; V2_MDD = -30.2; V3_MIN_DAYS = 120; V3_CAGR = -10.0; V4_CONC = 60.0
import jiandi_signal_0906 as JG

ap = argparse.ArgumentParser()
ap.add_argument('--dry', action='store_true')
ap.add_argument('--start', default=None)
ap.add_argument('--seeds', default=str(DEFAULT_SEED))
a = ap.parse_args()
seeds = [int(x) for x in a.seeds.split(',') if x.strip() != '']
prev_state = None
if os.path.exists(STATE_PATH):
    with open(STATE_PATH, encoding='utf-8') as fh: prev_state = json.load(fh)
if a.start:
    if not a.dry:
        log("ERROR: --start 仅限与 --dry 同用（保护正式账本）"); sys.exit(2)
    win_start = pd.Timestamp(a.start)
elif prev_state and prev_state.get('shadow_start'):
    win_start = pd.Timestamp(prev_state['shadow_start'])
else:
    win_start = pd.Timestamp(DEFAULT_SHADOW_START)
log(f"哨兵运行 | win_start={win_start.date()} | seeds={seeds} | dry={a.dry}")

idx = pd.read_csv(os.path.join(BASE, 'index_000300.csv'))
idx['date'] = pd.to_datetime(idx['date']); idx = idx.sort_values('date').reset_index(drop=True)
for maw in (20, 60):
    idx[f'ma{maw}'] = idx['close'].rolling(maw, min_periods=1).mean()
CAL = [d for d in idx['date'] if W_LO <= d <= W_HI]
CAL_WIN = [d for d in CAL if d >= win_start]
last_data_date = CAL[-1]
log(f"数据截至 {last_data_date.date()} | 窗口交易日 {len(CAL_WIN)}")

def build_regime(bear_ma, bull_ma=20):
    is_bear = (idx['close'] < idx[f'ma{bear_ma}']).to_numpy()
    bull = (~is_bear) & (idx['close'] > idx[f'ma{bull_ma}']).to_numpy()
    state = np.where(is_bear, 0, np.where(bull, 1, 2))
    prev_map = {}; prev = None
    for k, dt in enumerate(idx['date']):
        prev_map[dt] = prev if prev is not None else 0
        prev = int(state[k])
    return (lambda dt: prev_map.get(pd.Timestamp(dt)))
reg_fn = build_regime(60, 20)

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
evsθ = [e for e in events if res_daily[e[0]] >= THETA]
log(f"事件池 {len(events)} / θ>=30 {len(evsθ)}")

def win_ok(code, B, sell):
    da = DA[code]; oo = da['o'][B:sell + 1]; cc = da['c'][B:sell + 1]
    return bool(np.isfinite(oo).all() and np.isfinite(cc).all() and (oo > 0).all() and (cc > 0).all())

def arm_rsi(evs, thr_map):
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

def sim(trades, seed, rt, cal, want_series=False):
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

def sim_multi(trades, rt):
    if len(CAL_WIN) < 2: return None
    rr = [sim(trades, sd_, rt, CAL_WIN) for sd_ in seeds]
    return {k: round(float(np.mean([x[k] for x in rr])), 3) for k in ('cagr', 'sharpe', 'mdd')}

def ev_metrics(arm):
    if not arm:
        return dict(n_done=0, mean_gross_pct=None, mean_net_pct_020=None, mean_net_pct_115=None, wr_pct=None, med_net_pct_020=None)
    rr = np.array([DA[c]['o'][s2] / DA[c]['o'][B] - 1 for _sd, c, B, s2 in arm])
    return dict(n_done=int(len(arm)),
                mean_gross_pct=round(float(rr.mean()) * 100, 3),
                mean_net_pct_020=round(float(rr.mean()) * 100 - 0.2, 3),
                mean_net_pct_115=round(float(rr.mean()) * 100 - 1.15, 3),
                wr_pct=round(float((rr > 0).mean()) * 100, 2),
                med_net_pct_020=round(float(np.median(rr)) * 100 - 0.2, 3))

evs_w = [e for e in evsθ if e[0] >= win_start]
trig_days_w = sorted({e[0] for e in evsθ if e[0] >= win_start})
trig_days_all = sorted({e[0] for e in evsθ})
span_yr = (CAL[-1] - CAL[0]).days / 365.25

ARMS = [('A1 基线(纯持5日)', None),
        ('A2 RSI固定55(主假设)', {0: 55, 1: 55, 2: 55}),
        ('A3 RSI域55/65/65(次假设)', {0: 55, 1: 65, 2: 65})]
arm_res = {}
for name, thr in ARMS:
    arm = evs_w if thr is None else arm_rsi(evs_w, thr)
    tr = to_trades(arm)
    m = ev_metrics(arm)
    s020 = sim_multi(tr, 0.002); s115 = sim_multi(tr, 0.0115)
    conc = None
    if len(CAL_WIN) >= 2 and tr:
        _, s_ = sim(tr, seeds[0], 0.0115, CAL_WIN, want_series=True)
        tot = float(s_.sum()); conc = round(float(s_.nlargest(10).sum()) / tot * 100, 1) if tot > 0 else None
    v1 = bool(m['n_done'] >= V1_MIN_N and m['mean_net_pct_020'] is not None and m['mean_net_pct_020'] <= 0)
    v2 = bool(s115 is not None and s115['mdd'] <= V2_MDD)
    v3 = bool(len(CAL_WIN) >= V3_MIN_DAYS and s115 is not None and s115['cagr'] <= V3_CAGR)
    v4e = bool(conc is not None and conc >= V4_CONC)
    arm_res[name] = dict(n_total=len(arm), **m, sim_020=s020, sim_115=s115, conc_115_top10=conc,
                         V1=dict(min_n=V1_MIN_N, tier='net@0.20%', metric=m['mean_net_pct_020'], triggered=v1),
                         V2=dict(thr=V2_MDD, metric=None if s115 is None else s115['mdd'], triggered=v2),
                         V3=dict(min_days=V3_MIN_DAYS, thr=V3_CAGR, metric=None if s115 is None else s115['cagr'], triggered=v3),
                         V4_diag=dict(thr=V4_CONC, metric=conc, elevated=v4e))
    log(f"  {name}: n_done={m['n_done']} mean_net020={m['mean_net_pct_020']} | 0.2%{s020} | 1.15%{s115} | conc={conc} | V1={v1} V2={v2} V3={v3} V4diag={v4e}")

any_trig = any(arm_res[n]['V1']['triggered'] or arm_res[n]['V2']['triggered'] or arm_res[n]['V3']['triggered'] for n, _ in ARMS)
judgement_ready = bool(len(CAL_WIN) >= V3_MIN_DAYS or any(arm_res[n]['n_done'] >= V1_MIN_N for n, _ in ARMS))
status = 'REVIEW_TRIGGERED' if any_trig else ('OK' if judgement_ready else 'COLLECTING')

state = dict(
    generated_at=time.strftime('%Y-%m-%d %H:%M:%S'),
    rule_version='R-jiandi-top30-0924/v1',
    status=status, judgement_ready=judgement_ready,
    shadow_start=str(win_start.date()), last_data_date=str(last_data_date.date()),
    window=dict(start=str(win_start.date()), end=str(last_data_date.date()), n_cal_days=len(CAL_WIN)),
    config=dict(theta=THETA, K=K, fallback_days=CAP, seed=seeds[0], seeds_used=seeds,
                cost_tiers=['0.20%', '1.15%'], regime='生产 MA60_3（T-1）'),
    frequency=dict(trigger_days_window=len(trig_days_w), events_total_window=len(evs_w),
                   backtest_reference=dict(trigger_days_all=len(trig_days_all), events_all=len(evsθ),
                                           span_years=round(span_yr, 2),
                                           trigger_days_per_year=round(len(trig_days_all) / span_yr, 1),
                                           events_per_year=round(len(evsθ) / span_yr, 0))),
    arms=arm_res,
    notes=['事件在 5 日窗口闭合且价格门控通过后才会出现（对齐回测构造）；窗口起点为空仓（不含跨窗口持仓）',
           'V1 用 net@0.20% 档（精确回测参照 net@0.20% = 4.27~4.35、net@1.15% = 3.32~3.40）；net@1.15% 同时记录于 mean_net_pct_115',
           'V2/V3 用 1.15% 保守档；V4 仅诊断不设门',
           '--start 重放仅限 --dry（防污染正式窗口）；重放校验见报告 §13'])
if not a.dry:
    hist = prev_state.get('history', []) if prev_state else []
    hist.append(dict(at=state['generated_at'], status=status, days=len(CAL_WIN),
                     per_arm={n: dict(n_done=arm_res[n]['n_done'], mean_net020=arm_res[n]['mean_net_pct_020']) for n, _ in ARMS}))
    state['history'] = hist[-500:]
    with open(STATE_PATH, 'w', encoding='utf-8') as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1, default=str)
    log(f"STATE SAVED {STATE_PATH}")
else:
    log("--dry：不写状态")
log("== 摘要 ==")
log(json.dumps(dict(status=status, window=state['window'], arms={n: dict(n_done=arm_res[n]['n_done'], sim_115=arm_res[n]['sim_115'], V1=arm_res[n]['V1']['triggered'], V2=arm_res[n]['V2']['triggered'], V3=arm_res[n]['V3']['triggered']) for n, _ in ARMS}), ensure_ascii=False))
log("DONE")