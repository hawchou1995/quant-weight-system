# -*- coding: utf-8 -*-
"""
固定标的池回测：v8 v3 引擎（TopN/季度轮动/MA200择时/移动止损10%）应用到用户快照池
池来源：Obsidian data-标的快照-20260814.md（30 只 = 20 股票 + 5 ETF + 6 基金）
对比：全量池 v3 基线
注意：固定池存在上市时间偏置（部分标的 2016 后上市）——披露项
"""
import os
import sys, json, time, math, csv
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v8_selector as V
import v8_winrate as W

BASE = Path(os.path.dirname(os.path.abspath(__file__)))

STOCKS = ['600498','002463','600183',
          '002185','605358','603228','603339','000636','605189','600403','002879','600162','000759',
          '002820','002971','603629']   # 2026-08-18 用户调整固定池（去 002384/603986/601138 等）
ETFS = []   # 2026-08-17 用户决策：ETF 表现不佳，全池去 ETF，后续不考虑投资
FUNDS = ['008254','018036','002891','024239']   # 2026-08-17 去 014002/020900

def to_key(c):
    return ('sh' if c.startswith(('6', '9')) else 'sz') + c

# ---------- 1. 股票固定池 ----------
stock_pool = {to_key(c): W.pool[to_key(c)] for c in STOCKS}
print(f"股票固定池: {len(stock_pool)} 只", flush=True)

def run_stock(label, pool, **kw):
    t0 = time.time()
    eq, tr = W.run_v8w(pool=pool, **kw)
    s = V.summary(eq, tr)
    print(f"[{label}] {time.time()-t0:.0f}s | 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% | "
          f"回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']}", flush=True)
    return s

results = {}
B = dict(hold_days=42, use_timing=True, stop_loss=0.10, stop_mode='trailing', min_price=2.0, max_vol=0.60)
results['股票_固定池_Top15'] = run_stock('股票_固定池_Top15', stock_pool, top_n=15, **B)
results['股票_固定池_Top10'] = run_stock('股票_固定池_Top10', stock_pool, top_n=10, **B)
results['股票_固定池_全持20'] = run_stock('股票_固定池_全持20', stock_pool, top_n=20, **B)

# ---------- 2. ETF 固定池（2026-08-17 用户决策移除，ETF 表现不佳不考虑投资） ----------
# 原 ETF 回测分支已移除；若未来恢复，见 git 历史 v8_fixed_pool.py

# ---------- 3. 基金固定池（4 只，全持 + MA100 择时 + T+1） ----------
CACHE = BASE / 'fund_nav_cache'
navs = {}
for code in FUNDS:
    f = CACHE / f"{code}.csv"
    if not f.exists():
        print(f"基金 {code}: 无缓存", flush=True)
        continue
    df = pd.read_csv(f, dtype={'净值日期': str})
    s = pd.Series(pd.to_numeric(df['单位净值'], errors='coerce').values,
                  index=pd.to_datetime(df['净值日期'])).dropna()
    if len(s) >= 250:
        navs[code] = s
print(f"基金固定池: {len(navs)} 只", flush=True)

idx = V.load_index(200).set_index('date')
idx = idx[~idx.index.duplicated(keep='last')].sort_index()
idx['ma100'] = idx['close'].rolling(100).mean()
in_market = {}
for d, r in idx.iterrows():
    in_market[d] = bool(pd.notna(r['ma100']) and r['close'] > r['ma100'])

START, END = '2016-01-04', '2026-08-14'
all_days = sorted(set().union(*[set(s.index) for s in navs.values()]))
all_days = [d for d in all_days if START <= str(d.date()) <= END]
rebal = set(all_days[::126])
cash = 1_000_000.0
holdings, ep, ed = {}, {}, {}
eq, trades = [], []
ps, pb = set(), []
ln = {}
for di, day in enumerate(all_days):
    dstr = str(day.date())
    im = in_market.get(day, False)
    if ps or pb:
        for code in list(ps):
            if code not in holdings:
                continue
            px = navs[code].get(day) or ln.get(code)
            if px is None:
                continue
            sh = holdings.pop(code)
            pnl = sh * (px - ep[code])
            trades.append({'entry_date': str(ed[code].date()), 'exit_date': dstr, 'side': 'long', 'size': sh,
                           'entry_price': round(ep[code],4), 'exit_price': round(px,4), 'pnl': round(pnl,2),
                           'pnl_pct': round((px/ep[code]-1)*100,2), 'holding_bars': (day-ed[code]).days,
                           'symbol': code, 'symbol_name': code, 'display_symbol': code})
            cash += sh * px
        if pb:
            pv = cash
            for code, sh in holdings.items():
                if ln.get(code):
                    pv += sh * ln[code]
            per = pv / len(pb)
            for code in pb:
                if code in holdings:
                    continue
                px = navs[code].get(day) or ln.get(code)
                if px is None:
                    continue
                sh = int(per / px)
                if sh > 0 and sh * px <= cash:
                    cash -= sh * px
                    holdings[code] = sh
                    ep[code] = px
                    ed[code] = day
        ps = set()
        pb = []
    if day in rebal and di < len(all_days) - 1:
        if not im:
            ps = set(holdings.keys())
            pb = []
        else:
            pb = list(navs.keys())
            ps = set()
    pv = cash
    for code, sh in holdings.items():
        px = navs[code].get(day)
        if px is not None and px > 0:
            pv += sh * px
            ln[code] = px
        elif ln.get(code):
            pv += sh * ln[code]
    eq.append({'date': dstr, 'value': round(pv, 2)})
if holdings:
    last_day = all_days[-1]
    for code, sh in holdings.items():
        px = navs[code].get(last_day) or ln.get(code)
        if px is None:
            continue
        pnl = sh * (px - ep[code])
        trades.append({'entry_date': str(ed[code].date()), 'exit_date': str(last_day.date()), 'side': 'long', 'size': sh,
                       'entry_price': round(ep[code],4), 'exit_price': round(px,4), 'pnl': round(pnl,2),
                       'pnl_pct': round((px/ep[code]-1)*100,2), 'holding_bars': (last_day-ed[code]).days,
                       'symbol': code, 'symbol_name': code, 'display_symbol': code})
        cash += sh * px
    holdings = {}
eqdf = pd.DataFrame(eq)
v = pd.to_numeric(eqdf['value']).values
total = (v[-1]/v[0]-1)*100
days = (pd.to_datetime(eqdf['date'].iloc[-1]) - pd.to_datetime(eqdf['date'].iloc[0])).days
yrs = days / 365.25
annual = ((v[-1]/v[0])**(1/yrs)-1)*100
ret = pd.Series(v).pct_change().dropna()
sharpe = ret.mean()/ret.std()*math.sqrt(252) if len(ret) > 5 and ret.std() > 0 else 0
dd = (v/np.maximum.accumulate(v)-1)*100
win = sum(1 for t in trades if t.get('pnl',0) > 0)/len(trades)*100 if trades else 0
results['基金_固定池_全持_MA100'] = {
    'total_return_pct': round(total,2), 'annual_return_pct': round(annual,2),
    'max_drawdown_pct': round(dd.min(),2), 'sharpe': round(sharpe,3),
    'win_rate_pct': round(win,1), 'total_trades': len(trades)}
print(f"[基金_固定池_全持_MA100] 收益 {total:.2f}% | 年化 {annual:.2f}% | 回撤 {dd.min():.2f}% | 夏普 {sharpe:.3f} | 胜率 {win:.1f}% | 交易 {len(trades)}", flush=True)

json.dump(results, open('v8_fixed_pool_results.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print("\n=== 固定池 vs 全量池基线 ===")
print(f"{'实验':<22} {'收益':>10} {'回撤':>8} {'夏普':>7} {'胜率':>7}")
print(f"{'全量池v3(参考)':<22} {479.54:>9.1f}% {-7.08:>7.1f}% {1.799:>7.3f} {55.3:>6.1f}%")
for k, v in results.items():
    print(f"{k:<22} {v['total_return_pct']:>9.1f}% {v['max_drawdown_pct']:>7.1f}% {v['sharpe']:>7.3f} {v['win_rate_pct']:>6.1f}%")