# -*- coding: utf-8 -*-
"""
v10 固定池信号仓位管理：自己的标的 + 看指标独立加减仓（无排名、无换仓）
- 池：用户自选池 25 只（固定）
- 每只独立判定（v9 规则，6 项）：
    6/6 达标 → 加仓档（目标仓位 = 100/加仓数，上限 25%）
    4-5/6 达标 → 观望档（持有不加，保持现有仓位）
    ≤3/6 或 分<45 或 动量<0 → 减仓档（清仓）
- 每日：移动止损（峰值回撤 10%）+ MA200 择时（指数下清仓）
- 无 TopN：加仓档标的全部持有，不会因排名被踢
"""
import sys, time, math
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import v8_selector as V
import v8_lite as L

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")

STOCKS = L.STOCKS
ETFS = L.ETFS


def to_key(c):
    return ('sh' if c.startswith(('6', '9', '5')) else 'sz') + c


def rsi14(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def build_pool():
    pool = {}
    for c in STOCKS + ETFS:
        k = to_key(c)
        f = BASE / 'data_full' / f'{k}.csv'
        if not f.exists():
            continue
        try:
            df = pd.read_csv(f, dtype={'date': str})
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            if len(df) < 400 or df['close'].pct_change().abs().max() > 0.25:
                continue
            df = V.compute_factors_full(df)
            df['rsi'] = rsi14(df['close'])
            df['ma150'] = df['close'].rolling(150).mean()
            pool[k] = df.set_index('date')
        except Exception:
            continue
    return pool


def signal_grade(ddf, day, score_min=65, mom_min=0.25, rsi_max=85):
    """v9 六项规则判定，返回 (通过数, 分数, 档位)"""
    if day not in ddf.index:
        return 0, np.nan, '减仓'
    r = ddf.loc[day]
    px = r['close']
    if pd.isna(px) or px <= 0 or pd.isna(r['mom_12_1']):
        return 0, np.nan, '减仓'
    sc = V.score_row(r)
    checks = [
        r['mom_12_1'] >= mom_min,
        sc >= score_min,
        not pd.isna(r['ma150']) and px > r['ma150'],
        px >= 2.0,
        not pd.isna(r['amt20']) and r['amt20'] >= 5e6,
        not pd.isna(r['rsi']) and r['rsi'] < rsi_max,
    ]
    n = sum(checks)
    if n >= 6:
        tier = '加仓'
    elif sc < 45 or r['mom_12_1'] < 0 or (not pd.isna(r['rsi']) and r['rsi'] >= 88):
        tier = '减仓'
    elif n >= 4:
        tier = '观望'
    else:
        tier = '减仓'
    return n, sc, tier


def run_v10(pool, hold_days=21, stop_loss=0.10, cash0=500000, max_w=0.25,
            use_timing=True, verbose=False):
    idx = V.load_index(200).set_index('date')
    in_market_map = idx['in_market'].to_dict()
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    rebal_days = set(all_days[::hold_days])
    cash = cash0
    holdings, ep, ed, peak = {}, {}, {}, {}
    eq, trades = [], []
    last_close = {}
    tier_hist = {}

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

        # 再平衡日：每只独立信号判定 → 加减仓
        if day in rebal_days and di < len(all_days) - 1:
            if not in_market:
                # 大盘择时清仓
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
                # 逐只独立判定
                add_list, hold_list, cut_list = [], [], []
                for code, ddf in pool.items():
                    n_pass, sc, tier = signal_grade(ddf, day)
                    if tier == '加仓':
                        add_list.append((code, sc))
                    elif tier == '观望':
                        hold_list.append(code)
                    else:
                        cut_list.append(code)
                    tier_hist[code] = tier
                # 减仓档：清仓（独立信号，不看排名）
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
                # 加仓档：等权目标仓位（100/加仓数，上限 max_w）
                if add_list:
                    port_value = cash
                    for code, sh in holdings.items():
                        if last_close.get(code):
                            port_value += sh * last_close[code]
                    n = len(add_list)
                    target_w = min(1.0 / n, max_w)
                    budget = port_value * target_w
                    for code, sc in sorted(add_list, key=lambda kv: -kv[1]):
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
                    print(f'{dstr}: 加仓{len(add_list)} 观望{len(hold_list)} 减仓{len(cut_list)} 持仓{len(holdings)}', flush=True)

        # mark-to-market
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
    for sl in [0.08, 0.10, 0.12]:
        t0 = time.time()
        eq, tr = run_v10(pool, stop_loss=sl, verbose=False)
        s = V.summary(eq, tr)
        flag = '✅' if s['sharpe'] >= 1.0 and s['max_drawdown_pct'] > -30 and s['annual_return_pct'] >= 10 else ''
        print(f'v10 止损{sl}: {time.time()-t0:.0f}s | 收益 {s["total_return_pct"]}% | 年化 {s["annual_return_pct"]}% | 回撤 {s["max_drawdown_pct"]}% | 夏普 {s["sharpe"]} | 胜率 {s["win_rate_pct"]}% | 交易 {s["total_trades"]} {flag}', flush=True)
