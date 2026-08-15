# -*- coding: utf-8 -*-
"""v9-auto：绝对规则自动池 + 池内持仓（无人工选池的普适体系）"""
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import math
import v8_selector as V

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
pool_all = V.load_pool()


def get_ddf(auto_pool, code):
    ddf = auto_pool.get(code)
    if ddf is None:
        ddf = pool_all.get(code)
    return ddf


def run_auto(top_n=4, hold_days=21, pool_size=25, stop_loss=0.10, cash0=500000,
             mom_min=0.15, score_min=60, use_timing=True, sell_score=0,
             dynamic=False, rsi_max=None, ma_window=200, vol_target=None):
    idx = V.load_index(200).set_index('date')
    idx['idx_vol'] = idx['close'].pct_change().rolling(20).std() * math.sqrt(252)
    idx_vol = idx['idx_vol'].to_dict()
    idx['ma_t'] = idx['close'].rolling(ma_window).mean()
    in_market_map = {d: bool(pd.notna(r['ma_t']) and r['close'] > r['ma_t']) for d, r in idx.iterrows()}
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    rebal_days = set(all_days[::hold_days])
    cash = cash0
    holdings, ep, ed, peak = {}, {}, {}, {}
    eq, trades = [], []
    ps, pb = set(), []
    last_close = {}
    auto_pool = {}
    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_timing else True
        if holdings:
            for code in list(holdings.keys()):
                ddf = get_ddf(auto_pool, code)
                if ddf is None or day not in ddf.index: continue
                px = ddf.loc[day, 'close']
                if pd.isna(px) or px <= 0: continue
                if code not in peak or px > peak[code]: peak[code] = px
                if stop_loss and px <= peak[code] * (1 - stop_loss): ps.add(code)
        if ps or pb:
            open_px = {}
            for code in list(ps) + [c for c, _ in pb]:
                ddf = get_ddf(auto_pool, code)
                if ddf is not None and day in ddf.index: open_px[code] = ddf.loc[day, 'open']
            for code in list(ps):
                if code not in holdings: continue
                px = open_px.get(code)
                if px is None or pd.isna(px) or px <= 0: continue
                sh = holdings.pop(code); peak.pop(code, None)
                tax = sh * px * V.SELL_TAX
                proceeds = sh * px * (1 - V.COMMISSION) - tax
                pnl = proceeds - sh * ep[code] * (1 + V.COMMISSION)
                trades.append({'entry_date': str(ed[code].date()), 'exit_date': dstr, 'side': 'long', 'size': sh,
                               'entry_price': round(ep[code],4), 'exit_price': round(px,4), 'pnl': round(pnl,2),
                               'pnl_pct': round((px/ep[code]-1)*100,2), 'holding_bars': (day-ed[code]).days,
                               'symbol': code, 'symbol_name': code, 'display_symbol': code})
                cash += proceeds
            if pb:
                port_value = cash
                for code, sh in holdings.items():
                    if last_close.get(code): port_value += sh * last_close[code]
                scale = 1.0
                if vol_target:
                    v = idx_vol.get(day)
                    if v is not None and not pd.isna(v) and v > 0:
                        scale = max(0.3, min(1.0, vol_target / v))
                budget = port_value * scale / len(pb)
                for code, _sc in pb:
                    if code in holdings: continue
                    px = open_px.get(code)
                    if px is None or pd.isna(px) or px <= 0: continue
                    lot = 100
                    n_lots = int(budget / (px * lot * (1 + V.COMMISSION)))
                    if n_lots < 1: continue
                    target_shares = n_lots * lot
                    cost = target_shares * px * (1 + V.COMMISSION)
                    if cost > cash:
                        n_lots = int(cash / (px * lot * (1 + V.COMMISSION)))
                        target_shares = n_lots * lot
                        cost = target_shares * px * (1 + V.COMMISSION)
                    if target_shares > 0 and cost <= cash:
                        cash -= cost
                        holdings[code] = target_shares
                        ep[code] = px; ed[code] = day; peak[code] = px
            ps = set(); pb = []
        if day in rebal_days and di < len(all_days) - 1:
            if not in_market:
                ps = set(holdings.keys()); pb = []
            else:
                thresh_now = score_min
                if dynamic:
                    v_now = idx_vol.get(day)
                    if v_now is not None and not pd.isna(v_now):
                        thresh_now = max(55.0, min(75.0, score_min + (v_now - 0.20) * 200))
                cand = []
                for code, ddf in pool_all.items():
                    if day not in ddf.index: continue
                    r = ddf.loc[day]
                    if pd.isna(r['close']) or r['close'] <= 0 or pd.isna(r['mom_12_1']): continue
                    if r['close'] < 2.0: continue
                    if pd.isna(r['amt20']) or r['amt20'] < 5e6: continue
                    if r['mom_12_1'] < mom_min: continue
                    if pd.isna(r['ma200_pos']) or r['ma200_pos'] <= 0: continue
                    sc = V.score_row(r)
                    if sc < thresh_now: continue
                    if rsi_max and 'rsi' in ddf.columns and not pd.isna(ddf['rsi'].iloc[pos]) and ddf['rsi'].iloc[pos] > rsi_max:
                        continue
                    cand.append((code, sc))
                cand.sort(key=lambda kv: -kv[1])
                auto_pool = {c: pool_all[c] for c, _ in cand[:pool_size]}
                ranked = cand[:top_n]
                keep = {c for c, _ in ranked}
                ps = {c for c in holdings if c not in keep}
                if sell_score:
                    for code in list(holdings.keys()):
                        ddf = get_ddf(auto_pool, code)
                        if ddf is not None and day in ddf.index:
                            sc_now = V.score_row(ddf.loc[day])
                            if sc_now < sell_score:
                                ps.add(code)
                pb = ranked
        pv = cash
        for code, sh in holdings.items():
            ddf = get_ddf(auto_pool, code)
            px = None
            if ddf is not None and day in ddf.index:
                px = ddf.loc[day, 'close']
                if not pd.isna(px) and px > 0: last_close[code] = px
                else: px = last_close.get(code)
            else: px = last_close.get(code)
            if px: pv += sh * px
        eq.append({'date': dstr, 'value': round(pv, 2)})
    if holdings:
        last_day = all_days[-1]
        for code, sh in holdings.items():
            px = last_close.get(code)
            if px is None or px <= 0: continue
            tax = sh * px * V.SELL_TAX
            proceeds = sh * px * (1 - V.COMMISSION) - tax
            pnl = proceeds - sh * ep[code] * (1 + V.COMMISSION)
            trades.append({'entry_date': str(ed[code].date()), 'exit_date': str(last_day.date()), 'side': 'long', 'size': sh,
                           'entry_price': round(ep[code],4), 'exit_price': round(px,4), 'pnl': round(pnl,2),
                           'pnl_pct': round((px/ep[code]-1)*100,2), 'holding_bars': (last_day-ed[code]).days,
                           'symbol': code, 'symbol_name': code, 'display_symbol': code})
            cash += proceeds
        holdings = {}
    return pd.DataFrame(eq), trades


if __name__ == "__main__":
    # 邻域冲刺：T3_SL8 附近
    cases = [
        ('T3_m20_s60_SL8', dict(top_n=3, mom_min=0.20, score_min=60, stop_loss=0.08)),
        ('T3_m25_s60_SL8', dict(top_n=3, mom_min=0.25, score_min=60, stop_loss=0.08)),
        ('T3_m20_s65_SL8', dict(top_n=3, mom_min=0.20, score_min=65, stop_loss=0.08)),
        ('T3_m25_s65_SL7', dict(top_n=3, mom_min=0.25, score_min=65, stop_loss=0.07)),
        ('T3_m25_s65_SL9', dict(top_n=3, mom_min=0.25, score_min=65, stop_loss=0.09)),
        ('T2_m25_s65_SL8', dict(top_n=2, mom_min=0.25, score_min=65, stop_loss=0.08)),
        ('T3_m30_s65_SL8', dict(top_n=3, mom_min=0.30, score_min=65, stop_loss=0.08)),
    ]
    import json
    res = {}
    for label, kw in cases:
        t0 = time.time()
        eq, tr = run_auto(**kw)
        s = V.summary(eq, tr)
        flag = '✅' if s['sharpe'] >= 1.0 and s['max_drawdown_pct'] > -30 and s['annual_return_pct'] >= 10 else ''
        print(f'{label}: {time.time()-t0:.0f}s | 收益 {s["total_return_pct"]}% | 年化 {s["annual_return_pct"]}% | 回撤 {s["max_drawdown_pct"]}% | 夏普 {s["sharpe"]} | 胜率 {s["win_rate_pct"]}% | 交易 {s["total_trades"]} {flag}', flush=True)
        res[label] = s
    json.dump(res, open(BASE / 'v9_auto_results.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
