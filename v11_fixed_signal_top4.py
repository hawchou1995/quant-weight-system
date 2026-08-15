# -*- coding: utf-8 -*-
"""
v8-lite v9 信号版：固定池 25 只 + v9 六项信号档位 + Top4 容量截断
- 信号（v9 规则）：动量≥25% / 分≥65 / 站MA150 / 价≥2 / 额≥500万 / RSI<85
    - 6/6 达标 → 加仓档；4-5/6 → 观望档；≤3/6 或分<45 或动量负 → 减仓档
- 容量：加仓档按分数降序取 Top4 等权持有（动态等权）
- 减仓档 → 清仓（独立信号）；观望档 → 不持仓
- 风控：移动止损 + 大盘择时
"""
import sys, time, math
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import v8_selector as V
import v10_fixed_signal as V10


def build_pool():
    return V10.build_pool()


def run_v11(pool, hold_days=21, stop_loss=0.10, cash0=500000, top_n=4,
            use_timing=True, ma_window=200, verbose=False):
    idx = V.load_index(200).set_index('date')
    idx['ma_t'] = idx['close'].rolling(ma_window).mean()
    in_market_map = {d: bool(pd.notna(r['ma_t']) and r['close'] > r['ma_t']) for d, r in idx.iterrows()}
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    rebal_days = set(all_days[::hold_days])
    cash = cash0
    holdings, ep, ed, peak = {}, {}, {}, {}
    eq, trades = [], []
    last_close = {}

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_timing else True

        # 每日移动止损
        if holdings:
            for code in list(holdings.keys()):
                ddf = pool.get(code)
                if ddf is None or day not in ddf.index:
                    continue
                px = ddf.loc[day, 'close']
                if pd.isna(px) or px <= 0:
                    continue
                if code not in peak or px > peak[code]:
                    peak[code] = px
                if stop_loss and px <= peak[code] * (1 - stop_loss):
                    sh = holdings.pop(code)
                    peak.pop(code, None)
                    tax = sh * px * V.SELL_TAX
                    proceeds = sh * px * (1 - V.COMMISSION) - tax
                    pnl = proceeds - sh * ep[code] * (1 + V.COMMISSION)
                    trades.append({'entry_date': str(ed[code].date()), 'exit_date': dstr, 'side': 'long', 'size': sh,
                                   'entry_price': round(ep[code], 4), 'exit_price': round(px, 4), 'pnl': round(pnl, 2),
                                   'pnl_pct': round((px / ep[code] - 1) * 100, 2), 'holding_bars': (day - ed[code]).days,
                                   'symbol': code, 'symbol_name': code, 'display_symbol': code})
                    cash += proceeds

        # 再平衡日
        if day in rebal_days and di < len(all_days) - 1:
            if not in_market:
                for code, sh in list(holdings.items()):
                    px = last_close.get(code)
                    if px is None or px <= 0:
                        continue
                    tax = sh * px * V.SELL_TAX
                    proceeds = sh * px * (1 - V.COMMISSION) - tax
                    pnl = proceeds - sh * ep[code] * (1 + V.COMMISSION)
                    trades.append({'entry_date': str(ed[code].date()), 'exit_date': dstr, 'side': 'long', 'size': sh,
                                   'entry_price': round(ep[code], 4), 'exit_price': round(px, 4), 'pnl': round(pnl, 2),
                                   'pnl_pct': round((px / ep[code] - 1) * 100, 2), 'holding_bars': (day - ed[code]).days,
                                   'symbol': code, 'symbol_name': code, 'display_symbol': code})
                    cash += proceeds
                    holdings.pop(code)
                    peak.pop(code, None)
            else:
                # v9 六项信号档位
                add_list, cut_list = [], []
                for code, ddf in pool.items():
                    n_pass, sc, tier = V10.signal_grade(ddf, day)
                    if tier == '加仓':
                        add_list.append((code, sc))
                    elif tier == '减仓':
                        cut_list.append(code)
                # 减仓档：清仓（独立信号）
                for code in cut_list:
                    if code in holdings:
                        px = last_close.get(code)
                        if px is None or px <= 0:
                            continue
                        sh = holdings.pop(code)
                        peak.pop(code, None)
                        tax = sh * px * V.SELL_TAX
                        proceeds = sh * px * (1 - V.COMMISSION) - tax
                        pnl = proceeds - sh * ep[code] * (1 + V.COMMISSION)
                        trades.append({'entry_date': str(ed[code].date()), 'exit_date': dstr, 'side': 'long', 'size': sh,
                                       'entry_price': round(ep[code], 4), 'exit_price': round(px, 4), 'pnl': round(pnl, 2),
                                       'pnl_pct': round((px / ep[code] - 1) * 100, 2), 'holding_bars': (day - ed[code]).days,
                                       'symbol': code, 'symbol_name': code, 'display_symbol': code})
                        cash += proceeds
                # Top4 容量截断：加仓档按分数降序取前 top_n
                add_list.sort(key=lambda kv: -kv[1])
                keep = {c for c, _ in add_list[:top_n]}
                # 持仓中不在新 Top4 的（且非加仓档）→ 卖出
                for code in list(holdings.keys()):
                    if code not in keep:
                        px = last_close.get(code)
                        if px is None or px <= 0:
                            continue
                        sh = holdings.pop(code)
                        peak.pop(code, None)
                        tax = sh * px * V.SELL_TAX
                        proceeds = sh * px * (1 - V.COMMISSION) - tax
                        pnl = proceeds - sh * ep[code] * (1 + V.COMMISSION)
                        trades.append({'entry_date': str(ed[code].date()), 'exit_date': dstr, 'side': 'long', 'size': sh,
                                       'entry_price': round(ep[code], 4), 'exit_price': round(px, 4), 'pnl': round(pnl, 2),
                                       'pnl_pct': round((px / ep[code] - 1) * 100, 2), 'holding_bars': (day - ed[code]).days,
                                       'symbol': code, 'symbol_name': code, 'display_symbol': code})
                        cash += proceeds
                # 买入新 Top4（动态等权）
                if add_list:
                    port_value = cash
                    for code, sh in holdings.items():
                        if last_close.get(code):
                            port_value += sh * last_close[code]
                    budget = port_value / top_n
                    for code, sc in add_list[:top_n]:
                        if code in holdings:
                            continue
                        ddf = pool.get(code)
                        px = ddf.loc[day, 'close'] if day in ddf.index else None
                        if px is None or pd.isna(px) or px <= 0:
                            continue
                        lot = 100
                        n_lots = int(budget / (px * lot * (1 + V.COMMISSION)))
                        if n_lots < 1:
                            continue
                        target_shares = n_lots * lot
                        cost = target_shares * px * (1 + V.COMMISSION)
                        if cost > cash:
                            n_lots = int(cash / (px * lot * (1 + V.COMMISSION)))
                            target_shares = n_lots * lot
                            cost = target_shares * px * (1 + V.COMMISSION)
                        if target_shares > 0 and cost <= cash:
                            cash -= cost
                            holdings[code] = target_shares
                            ep[code] = px
                            ed[code] = day
                            peak[code] = px
                if verbose:
                    print(f'{dstr}: 加仓{len(add_list)} 减仓{len(cut_list)} 持仓{len(holdings)}', flush=True)

        pv = cash
        for code, sh in holdings.items():
            ddf = pool.get(code)
            px = None
            if ddf is not None and day in ddf.index:
                px = ddf.loc[day, 'close']
                if not pd.isna(px) and px > 0:
                    last_close[code] = px
                else:
                    px = last_close.get(code)
            else:
                px = last_close.get(code)
            if px:
                pv += sh * px
        eq.append({'date': dstr, 'value': round(pv, 2)})

    if holdings:
        last_day = all_days[-1]
        for code, sh in list(holdings.items()):
            px = last_close.get(code)
            if px is None or px <= 0:
                continue
            tax = sh * px * V.SELL_TAX
            proceeds = sh * px * (1 - V.COMMISSION) - tax
            pnl = proceeds - sh * ep[code] * (1 + V.COMMISSION)
            trades.append({'entry_date': str(ed[code].date()), 'exit_date': str(last_day.date()), 'side': 'long', 'size': sh,
                           'entry_price': round(ep[code], 4), 'exit_price': round(px, 4), 'pnl': round(pnl, 2),
                           'pnl_pct': round((px / ep[code] - 1) * 100, 2), 'holding_bars': (last_day - ed[code]).days,
                           'symbol': code, 'symbol_name': code, 'display_symbol': code})
            cash += proceeds
            holdings.pop(code)
    return pd.DataFrame(eq), trades


if __name__ == "__main__":
    pool = build_pool()
    print(f'固定池 {len(pool)}/25 只', flush=True)
    cases = [
        ('SL10_MA200', dict(stop_loss=0.10, ma_window=200)),
        ('SL10_MA150', dict(stop_loss=0.10, ma_window=150)),
        ('SL8_MA150', dict(stop_loss=0.08, ma_window=150)),
        ('SL12_MA200', dict(stop_loss=0.12, ma_window=200)),
        ('SL10_MA100', dict(stop_loss=0.10, ma_window=100)),
    ]
    import json
    res = {}
    for label, kw in cases:
        t0 = time.time()
        eq, tr = run_v11(pool, **kw)
        s = V.summary(eq, tr)
        flag = '✅' if s['sharpe'] >= 1.0 and s['max_drawdown_pct'] > -30 and s['annual_return_pct'] >= 10 else ''
        print(f'{label}: {time.time()-t0:.0f}s | 收益 {s["total_return_pct"]}% | 年化 {s["annual_return_pct"]}% | 回撤 {s["max_drawdown_pct"]}% | 夏普 {s["sharpe"]} | 胜率 {s["win_rate_pct"]}% | 交易 {s["total_trades"]} {flag}', flush=True)
        res[label] = s
    json.dump(res, open('v11_results.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
