# -*- coding: utf-8 -*-
"""
个人资金约束版回测（17 万本金）：
- 本金 170,000 元；每笔目标金额与槽位可配（默认 2 槽 × 6 万；另测 3 槽 × 5.6 万 / 2 槽 × 8.5 万 / 日限 1 笔）
- 真实费率：佣金 万0.86（每笔最低 5 元，买卖双边）+ 印花税卖出 0.05% + 过户费 0.001%（双边）
- 100 股整手撮合；买入/卖出价 = 开盘价；当天先卖出（回笼现金）再买入
- 选股规则：R1 抽签（200 个随机种子 → 结果分布）；R2 共振分项数优先（并列按代码序）
- 三臂：A1 基线（纯持 5 日）/ A2 固定 55 / A3 域 55/65/65（与预注册一致）；分域 = 生产 60 日线标准（前一日收盘）
输出：jiandi_top_grid_0924_out/top1_personal_170k_0924.json
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
CAPITAL = 170000.0
COMM_RATE = 0.000086; COMM_MIN = 5.0; STAMP_RATE = 0.0005; TRANSFER_RATE = 0.00001
THETA = 30; HOLD = 5; NSEED = 200
import jiandi_signal_0906 as JG

idx = pd.read_csv(os.path.join(BASE, 'index_000300.csv'))
idx['date'] = pd.to_datetime(idx['date']); idx = idx.sort_values('date').reset_index(drop=True)
for maw in (20, 60): idx[f'ma{maw}'] = idx['close'].rolling(maw, min_periods=1).mean()
CAL = [d for d in idx['date'] if W_LO <= d <= W_HI]

def build_regime(bear_ma=60, bull_ma=20):
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
    o = df['open'].to_numpy(); c = df['close'].to_numpy()
    bad = (~np.isfinite(o)) | (~np.isfinite(c)) | (o <= 0) | (c <= 0)
    dates = df.index; n = len(df)
    for i in np.where(cnt >= 2)[0]:
        sd = dates[i]
        if sd < BS: continue
        res_daily[sd] += 1
        B = i + 1
        if B >= n or bad[B]: continue
        sell = B + HOLD
        if sell >= n or bad[B:sell + 1].any(): continue
        if code not in DA:
            DA[code] = dict(o=o, c=c, dates=dates, rsi=rsiN(df['close'], 14),
                            pos={d: k for k, d in enumerate(dates)})
        events.append((sd, code, B, sell, int(cnt[i])))
evsT = [e for e in events if res_daily[e[0]] >= THETA]
log(f"事件池 {len(events)} / 共振家数>={THETA} {len(evsT)}")

def win_ok(code, B, sell):
    da = DA[code]; oo = da['o'][B:sell + 1]; cc = da['c'][B:sell + 1]
    return bool(np.isfinite(oo).all() and np.isfinite(cc).all() and (oo > 0).all() and (cc > 0).all())

def arm_rsi(evs, thr_map):
    out = []
    for (sd, code, B, sell0, cn) in evs:
        da = DA[code]; rsi = da['rsi']; dts = da['dates']; n = len(dts)
        sell = min(B + HOLD, n - 1)
        for d in range(B, min(B + HOLD, n)):
            st = reg_fn(dts[d]); thr = thr_map.get(st if st is not None else 0, 55)
            if np.isfinite(rsi[d]) and rsi[d] >= thr:
                sell = min(d + 1, B + HOLD); break
        if sell <= B or sell >= n: continue
        if not win_ok(code, B, sell): continue
        out.append((sd, code, B, sell, cn))
    return out

ARMS = {'A1 基线(纯持5日)': None, 'A2 固定55': {0: 55, 1: 55, 2: 55}, 'A3 域55/65/65': {0: 55, 1: 65, 2: 65}}
ARM_EVS = {}; ARM_BYENTRY = {}; ARM_BYENTRY_SORTED = {}
for anm, thr in ARMS.items():
    evs = evsT if thr is None else arm_rsi(evsT, thr)
    ARM_EVS[anm] = evs
    be = defaultdict(list)
    for (sd, code, B, sell, cn) in evs:
        be[DA[code]['dates'][B]].append((code, B, sell, cn))
    ARM_BYENTRY[anm] = be
    ARM_BYENTRY_SORTED[anm] = {d: sorted(v, key=lambda x: (-x[3], x[0])) for d, v in be.items()}
    log(f"  {anm}: n={len(evs)}")

def fee_buy(amt):
    return max(amt * COMM_RATE, COMM_MIN) + amt * TRANSFER_RATE
def fee_sell(amt):
    return max(amt * COMM_RATE, COMM_MIN) + amt * TRANSFER_RATE + amt * STAMP_RATE

FEE_TABLE = {}
for amt in (30000, 50000, 60000, 85000):
    b = fee_buy(amt); s = fee_sell(amt)
    FEE_TABLE[amt] = dict(buy=round(b, 2), sell=round(s, 2), roundtrip=round(b + s, 2),
                          rate_pct=round((b + s) / amt * 100, 4))
    log(f"  费率示例 {amt}: 买{b:.2f} 卖{s:.2f} 合计{b + s:.2f} = {(b + s) / amt * 100:.4f}%")

def run_sim(anm, slots, notional, max_new, rule, seed=0):
    rng = np.random.default_rng(seed)
    by_entry = ARM_BYENTRY[anm] if rule == 'random' else ARM_BYENTRY_SORTED[anm]
    cash = CAPITAL; positions = []; equity = []; util = []; trades = []
    for d in CAL:
        if not positions and d not in by_entry:
            equity.append(cash); util.append(0.0); continue
        still = []
        for p in positions:
            if DA[p['code']]['dates'][p['sell']] == d:
                px = float(DA[p['code']]['o'][p['sell']])
                amt = p['shares'] * px; fs = fee_sell(amt)
                cash += amt - fs
                cb = p['shares'] * p['entry_px'] + p['buy_fee']
                net = amt - fs - cb
                trades.append(dict(code=p['code'], entry=str(DA[p['code']]['dates'][p['B']].date()),
                                   exit=str(d.date()), ret_pct=round(net / cb * 100, 3), pnl=round(net, 2)))
            else:
                still.append(p)
        positions = still
        cands = by_entry.get(d)
        if cands:
            free = slots - len(positions)
            if free > 0:
                n_pick = min(len(cands), free, max_new)
                if rule == 'random':
                    jj = sorted(rng.choice(len(cands), n_pick, replace=False)) if n_pick < len(cands) else list(range(n_pick))
                    picks = [cands[j] for j in jj]
                else:
                    picks = cands[:n_pick]
                for (code, B, sell, cn) in picks:
                    if len(positions) >= slots: break
                    px = float(DA[code]['o'][B])
                    budget = min(notional, cash * 0.995)
                    shares = int(budget // (px * 100)) * 100
                    if shares <= 0: continue
                    amt = shares * px; bf = fee_buy(amt)
                    if amt + bf > cash: continue
                    cash -= amt + bf
                    positions.append(dict(code=code, shares=shares, B=B, sell=sell, entry_px=px, buy_fee=bf))
        mv = 0.0; cost = 0.0
        for p in positions:
            k = DA[p['code']]['pos'].get(d)
            if k is None: k = p['B']
            mv += p['shares'] * float(DA[p['code']]['c'][k])
            cost += p['shares'] * p['entry_px']
        equity.append(cash + mv); util.append(cost / max(cash + mv, 1e-9))
    eq = np.array(equity, dtype=float)
    span = (CAL[-1] - CAL[0]).days / 365.25
    mdd = float((eq / np.maximum.accumulate(eq) - 1).min())
    tr = pd.DataFrame(trades)
    by_year = {}
    s_eq = pd.Series(eq, index=pd.DatetimeIndex(CAL))
    last = CAPITAL
    for ts, v in s_eq.resample('YE').last().items():
        by_year[str(ts.year)] = round(float(v / last - 1) * 100, 1)
        last = float(v)
    res = dict(total_ret_pct=round(float(eq[-1] / CAPITAL - 1) * 100, 2),
               annual_pct=round(float((eq[-1] / CAPITAL) ** (1 / max(span, 1e-9)) - 1) * 100, 2),
               mdd_pct=round(mdd * 100, 2),
               pnl_yuan=round(float(eq[-1] - CAPITAL), 0),
               equity_end=round(float(eq[-1]), 0),
               trades=int(len(tr)),
               trades_per_year=round(len(tr) / span, 1),
               avg_trade_ret_pct=round(float(tr['ret_pct'].mean()), 3) if len(tr) else None,
               win_pct=round(float((tr['ret_pct'] > 0).mean()) * 100, 2) if len(tr) else None,
               worst_trade_pct=round(float(tr['ret_pct'].min()), 2) if len(tr) else None,
               best_trade_pct=round(float(tr['ret_pct'].max()), 2) if len(tr) else None,
               avg_util_pct=round(float(np.mean(util)) * 100, 1),
               by_year=by_year)
    return res, tr

CONFIGS = [
    dict(name='2槽x6万·日限2', slots=2, notional=60000, max_new=2),
    dict(name='2槽x6万·日限1', slots=2, notional=60000, max_new=1),
    dict(name='3槽x5.6万·日限2', slots=3, notional=56000, max_new=2),
    dict(name='2槽x8.5万·日限2', slots=2, notional=85000, max_new=2),
]
ARM_NAMES = ['A2 固定55', 'A3 域55/65/65', 'A1 基线(纯持5日)']
EV_REF = {}
for anm in ARM_NAMES:
    evs = ARM_EVS[anm]
    rr = np.array([DA[c]['o'][s2] / DA[c]['o'][B] - 1 for _sd, c, B, s2, cn in evs])
    EV_REF[anm] = dict(n=int(len(evs)), mean_gross_pct=round(float(rr.mean()) * 100, 3),
                       wr_pct=round(float((rr > 0).mean()) * 100, 2))

RESULTS = {}
for anm in ARM_NAMES:
    for cfg in CONFIGS:
        key = anm + ' | ' + cfg['name']
        rr = [run_sim(anm, cfg['slots'], cfg['notional'], cfg['max_new'], 'random', s)[0] for s in range(NSEED)]
        agg = {}
        for k in ('annual_pct', 'mdd_pct', 'trades', 'trades_per_year', 'avg_trade_ret_pct', 'win_pct', 'pnl_yuan', 'equity_end', 'avg_util_pct'):
            vals = [x[k] for x in rr]
            agg[k] = dict(median=round(float(np.median(vals)), 3),
                          p5=round(float(np.percentile(vals, 5)), 3),
                          p95=round(float(np.percentile(vals, 95)), 3))
        rc, trc = run_sim(anm, cfg['slots'], cfg['notional'], cfg['max_new'], 'cnt')
        RESULTS[key] = dict(random_dist=agg, cnt_rule=rc)
        log(f"  {key} | 随机中位 年化={agg['annual_pct']['median']}% [{agg['annual_pct']['p5']}~{agg['annual_pct']['p95']}] 回撤中位={agg['mdd_pct']['median']}% 年笔数={agg['trades_per_year']['median']} 单笔={agg['avg_trade_ret_pct']['median']}% 期末={agg['equity_end']['median']}元 | 共振数优先 年化={rc['annual_pct']}% 回撤={rc['mdd_pct']}% 笔数={rc['trades']} 单笔={rc['avg_trade_ret_pct']}% 期末={rc['equity_end']}元")

RES = dict(generated_at=time.strftime('%Y-%m-%d %H:%M:%S'), capital=CAPITAL,
           fee_model=dict(comm_rate=COMM_RATE, comm_min=COMM_MIN, stamp_rate=STAMP_RATE,
                          transfer_rate=TRANSFER_RATE, note='印花税仅卖出；过户费双边；佣金双边底5元'),
           fee_table=FEE_TABLE, configs=CONFIGS, event_ref=EV_REF, results=RESULTS,
           note='个人资金约束版：逐元记账+整手撮合；选股 R1=随机(200种子分布) R2=共振分项数优先（并列按代码序）')
with open(os.path.join(OUT, 'top1_personal_170k_0924.json'), 'w', encoding='utf-8') as fh:
    json.dump(RES, fh, ensure_ascii=False, indent=1, default=str)
log("SAVED top1_personal_170k_0924.json"); log("DONE")