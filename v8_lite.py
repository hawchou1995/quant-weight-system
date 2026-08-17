# -*- coding: utf-8 -*-
"""
v8-lite 个人投资者版：15 万资金 + 自选池内轮动 + 整手/价格硬约束
- 池子：用户 20 只监控池（20 股票，2026-08-17 去 ETF）
- TopN 自适应：N = max(5, ceil(池子数*0.32))，25 只 → 8 席
- 硬约束：单只一手(100股)*价格 ≤ 预算(资金/TopN) 才可买，买不起自动跳过（现金保留）
- 移动止损 10% + MA200 择时 + 42 日轮动 + 佣金万2.5 + 印花税
- 目标：回撤 ≤25% / 夏普 ≥1 / 年化 ≥14%
"""
import os
import sys, json, time, math, csv
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v8_selector as V

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
CASH0 = 500_000.0

STOCKS = ['300502','300308','600498','601138','002463','002384','600183','300476','603986',
          '002185','605358','603228','603339','000636','605189','600403','002879','600162','000759','002474']
ETFS = []   # 2026-08-17 用户决策：去 ETF

def to_key(c):
    return ('sh' if c.startswith(('6', '9', '5')) else 'sz') + c


def build_pool(verbose=True):
    """构建 20 只自选池（v8 四因子统一打分，2026-08-17 去 ETF）"""
    pool = {}
    miss = []
    for c in STOCKS + ETFS:
        k = to_key(c)
        try:
            df = pd.read_csv(BASE / 'data_full' / f'{k}.csv', dtype={'date': str})
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').reset_index(drop=True)
            if len(df) < 400:
                miss.append((c, '长度不足'))
                continue
            if df['close'].pct_change().abs().max() > 0.25:
                miss.append((c, '跳变'))
                continue
            df = V.compute_factors_full(df).set_index('date')
            pool[k] = df
        except Exception as e:
            miss.append((c, str(e)[:30]))
    if verbose:
        print(f"自选池: {len(pool)}/25 只可用", flush=True)
        if miss:
            print(f"  不可用: {miss}", flush=True)
    return pool


def run_lite(pool, top_n=8, hold_days=42, use_timing=True, stop_loss=0.10, slippage_bps=0,
             min_price=1.0, cash0=CASH0, verbose=False):
    """池内轮动 + 整手约束 + 价格过滤"""
    idx = V.load_index(200).set_index("date")
    in_market_map = idx["in_market"].to_dict()
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    rebal_days = set(all_days[::hold_days])
    cash = cash0
    holdings, entry_price, entry_date = {}, {}, {}
    peak_price = {}
    equity_curve, trades = [], []
    pending_sell, pending_buy = set(), []
    last_close = {}

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_timing else True

        # 移动止损
        if holdings:
            for code in list(holdings.keys()):
                ddf = pool.get(code)
                if ddf is None or day not in ddf.index:
                    continue
                px = ddf.loc[day, "close"]
                if pd.isna(px) or px <= 0:
                    continue
                if code not in peak_price or px > peak_price[code]:
                    peak_price[code] = px
                if stop_loss and px <= peak_price[code] * (1 - stop_loss):
                    pending_sell.add(code)

        # 执行挂单（当日 open 成交，与主体系口径一致）
        if pending_sell or pending_buy:
            open_px = {}
            for code in list(pending_sell) + [c for c, _ in pending_buy]:
                ddf = pool.get(code)
                if ddf is not None and day in ddf.index:
                    open_px[code] = ddf.loc[day, "open"]
            for code in list(pending_sell):
                if code not in holdings:
                    continue
                px = open_px.get(code)
                if px is None or pd.isna(px) or px <= 0:
                    continue
                px = px * (1 - slippage_bps / 10000)   # 卖出滑点
                sh = holdings.pop(code)
                peak_price.pop(code, None)
                tax = sh * px * V.SELL_TAX
                proceeds = sh * px * (1 - V.COMMISSION) - tax
                pnl = proceeds - sh * entry_price[code] * (1 + V.COMMISSION)
                trades.append({"entry_date": str(entry_date[code].date()), "exit_date": dstr,
                               "side": "long", "size": sh, "entry_price": round(entry_price[code], 4),
                               "exit_price": round(px, 4), "pnl": round(pnl, 2),
                               "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                               "holding_bars": (day - entry_date[code]).days,
                               "symbol": code, "symbol_name": code, "display_symbol": code})
                cash += proceeds
            if pending_buy:
                # 动态等权目标（随组合市值增长，受现金约束）——修复固定 budget 现金堆积 bug
                port_value = cash
                for code, sh in holdings.items():
                    if last_close.get(code):
                        port_value += sh * last_close[code]
                budget = port_value / len(pending_buy[:top_n]) if pending_buy else port_value / top_n
                for code, _score in pending_buy:
                    if code in holdings:
                        continue
                    px = open_px.get(code)
                    if px is None or pd.isna(px) or px <= 0:
                        continue
                    px = px * (1 + slippage_bps / 10000)   # 买入滑点
                    # 整手买入：动态等权目标金额 + 现金自然约束
                    lot = 100
                    n_lots = int(budget / (px * lot * (1 + V.COMMISSION)))
                    if n_lots < 1:
                        continue
                    target_shares = n_lots * lot
                    cost = target_shares * px * (1 + V.COMMISSION)
                    # 若现金不足买满预算，按可买整手数
                    if cost > cash:
                        n_lots = int(cash / (px * lot * (1 + V.COMMISSION)))
                        target_shares = n_lots * lot
                        cost = target_shares * px * (1 + V.COMMISSION)
                    if target_shares > 0 and cost <= cash:
                        cash -= cost
                        holdings[code] = target_shares
                        entry_price[code] = px
                        entry_date[code] = day
                        peak_price[code] = px
            pending_sell = set()
            pending_buy = []

        # 再平衡：池内打分排序
        if day in rebal_days and di < len(all_days) - 1:
            if not in_market:
                pending_sell = set(holdings.keys())
                pending_buy = []
            else:
                candidates = {}
                for code, ddf in pool.items():
                    if day not in ddf.index:
                        continue
                    r = ddf.loc[day]
                    if pd.isna(r["close"]) or r["close"] <= 0 or pd.isna(r["mom_12_1"]):
                        continue
                    if pd.isna(r["amt20"]) or r["amt20"] < 5e6:
                        continue
                    if r["close"] < min_price:
                        continue
                    candidates[code] = V.score_row(r)
                if candidates:
                    ranked = sorted(candidates.items(), key=lambda kv: -kv[1])[:top_n]
                    keep = {c for c, _ in ranked}
                    pending_sell = {c for c in holdings if c not in keep}
                    pending_buy = ranked
                else:
                    pending_sell = set(holdings.keys())
                    pending_buy = []

        port_value = cash
        for code, sh in holdings.items():
            ddf = pool.get(code)
            px = None
            if ddf is not None and day in ddf.index:
                px = ddf.loc[day, "close"]
                if not pd.isna(px) and px > 0:
                    last_close[code] = px
                else:
                    px = last_close.get(code)
            else:
                px = last_close.get(code)
            if px:
                port_value += sh * px
        equity_curve.append({"date": dstr, "value": round(port_value, 2)})

    if holdings:
        last_day = all_days[-1]
        for code, sh in holdings.items():
            ddf = pool.get(code)
            px = None
            if ddf is not None and last_day in ddf.index:
                px = ddf.loc[last_day, "close"]
                if pd.isna(px) or px <= 0:
                    px = None
            if px is None:
                px = last_close.get(code)
            if px is None or px <= 0:
                continue
            tax = sh * px * V.SELL_TAX
            proceeds = sh * px * (1 - V.COMMISSION) - tax
            pnl = proceeds - sh * entry_price[code] * (1 + V.COMMISSION)
            trades.append({"entry_date": str(entry_date[code].date()), "exit_date": str(last_day.date()),
                           "side": "long", "size": sh, "entry_price": round(entry_price[code], 4),
                           "exit_price": round(px, 4), "pnl": round(pnl, 2),
                           "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                           "holding_bars": (last_day - entry_date[code]).days,
                           "symbol": code, "symbol_name": code, "display_symbol": code})
            cash += proceeds
        holdings = {}
    return pd.DataFrame(equity_curve), trades


if __name__ == "__main__":
    pool = build_pool()
    results = {}
    for tn in [4, 5, 6, 8, 10]:
        t0 = time.time()
        eq, tr = run_lite(pool, top_n=tn, hold_days=42, use_timing=True, stop_loss=0.10)
        s = V.summary(eq, tr)
        flag = "✅达标" if (s.get("max_drawdown_pct") or -99) > -25 and (s.get("sharpe") or 0) >= 1.0 and (s.get("annual_return_pct") or 0) >= 14 else ""
        print(f"[Lite Top{tn}] {time.time()-t0:.0f}s | 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% | "
              f"回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']} {flag}", flush=True)
        results[f"Lite_Top{tn}"] = s
    json.dump(results, open("v8_lite_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n=== v8-lite 个人版矩阵（15万/池内轮动/整手约束）===")
    print(f"{'实验':<12} {'收益':>10} {'年化':>8} {'回撤':>8} {'夏普':>7} {'胜率':>7}")
    for k, v in results.items():
        flag = "✅" if (v.get("max_drawdown_pct") or -99) > -25 and (v.get("sharpe") or 0) >= 1.0 and (v.get("annual_return_pct") or 0) >= 14 else ""
        print(f"{k:<12} {v['total_return_pct']:>9.1f}% {v['annual_return_pct']:>7.1f}% {v['max_drawdown_pct']:>7.1f}% {v['sharpe']:>7.3f} {v['win_rate_pct']:>6.1f}% {flag}")