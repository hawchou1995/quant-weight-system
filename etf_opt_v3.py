# -*- coding: utf-8 -*-
"""ETF 中长线 v3 补扫：动量轮动 + MA5 每日止损（v3 短线验证的杀手锏）+ 月频/季频
================================================================================
"""
import os
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import v8_selector as V
import etf_opt_v2 as E2   # 复用 rsrs/slope/pool/run_etf_v2


def run_etf_v3(pool, mom_type="mom20", top_n=5, hold_days=63, stop_loss=0.10, slippage_bps=0,
               freeze=0, mom_thresh=0.0, ma5_exit=True, use_timing=True, ma_win=150,
               cash0=1_000_000, min_amt=1e6, min_px=0.5, max_vol=0.60):
    """ETF 中长线 v3 = v2 逻辑 + MA5 生命线每日止损"""
    idx = V.load_index(ma_win).set_index("date")
    in_market_map = idx["in_market"].to_dict()
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    rebal_days = set(all_days[::hold_days])
    cash = cash0
    holdings, entry_price, entry_date = {}, {}, {}
    last_sell_day = {}
    equity_curve, trades = [], []
    pending_sell, pending_buy = set(), []
    last_close = {}

    def frozen(code, day):
        return last_sell_day.get(code, None) is not None and (day - last_sell_day[code]).days < freeze

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_timing else True
        # 每日风控：止损 + MA5 生命线
        if holdings:
            for code in list(holdings.keys()):
                ddf = pool.get(code)
                if ddf is None or day not in ddf.index:
                    continue
                r = ddf.loc[day]
                px = r["close"]
                if pd.isna(px) or px <= 0:
                    continue
                if stop_loss and px <= entry_price[code] * (1 - stop_loss):
                    pending_sell.add(code); continue
                if ma5_exit and not pd.isna(r.get("ma5", np.nan)) and px < r["ma5"]:
                    pending_sell.add(code)
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
                tax = sh * px * V.SELL_TAX
                proceeds = sh * px * (1 - V.COMMISSION) - tax
                pnl = proceeds - sh * entry_price[code] * (1 + V.COMMISSION)
                trades.append({"entry_date": str(entry_date[code].date()), "exit_date": dstr,
                               "pnl": round(pnl, 2), "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                               "holding_bars": (day - entry_date[code]).days, "symbol": code})
                cash += proceeds
                last_sell_day[code] = day
            if pending_buy:
                port_value = cash
                for code, sh in holdings.items():
                    if last_close.get(code):
                        port_value += sh * last_close[code]
                per_target = port_value / top_n
                for code, _sc in pending_buy:
                    if code in holdings or frozen(code, day):
                        continue
                    px = open_px.get(code)
                    if px is None or pd.isna(px) or px <= 0:
                        continue
                    px = px * (1 + slippage_bps / 10000)   # 买入滑点
                    sh = int(per_target / (px * (1 + V.COMMISSION)))
                    if sh > 0 and sh * px * (1 + V.COMMISSION) <= cash:
                        cash -= sh * px * (1 + V.COMMISSION)
                        holdings[code] = sh
                        entry_price[code] = px
                        entry_date[code] = day
            pending_sell, pending_buy = set(), []
        if day in rebal_days and di < len(all_days) - 1:
            if not in_market:
                pending_sell = set(holdings.keys()); pending_buy = []
            else:
                candidates = {}
                for code, ddf in pool.items():
                    if day not in ddf.index:
                        continue
                    r = ddf.loc[day]
                    if pd.isna(r["close"]) or r["close"] <= 0 or pd.isna(r.get(mom_type, np.nan)):
                        continue
                    if pd.isna(r["amt20"]) or r["amt20"] < min_amt:
                        continue
                    if max_vol and not pd.isna(r["vol20"]) and r["vol20"] > max_vol:
                        continue
                    if r["close"] < min_px:
                        continue
                    m = r[mom_type]
                    if mom_thresh is not None and m < mom_thresh:
                        continue
                    candidates[code] = m
                if candidates:
                    ranked = sorted(candidates.items(), key=lambda kv: -kv[1])[:top_n]
                    keep = {c for c, _ in ranked}
                    pending_sell = {c for c in holdings if c not in keep}
                    pending_buy = ranked
                else:
                    pending_sell = set(holdings.keys()); pending_buy = []
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
            px = last_close.get(code)
            if px is None or px <= 0:
                continue
            tax = sh * px * V.SELL_TAX
            proceeds = sh * px * (1 - V.COMMISSION) - tax
            pnl = proceeds - sh * entry_price[code] * (1 + V.COMMISSION)
            trades.append({"entry_date": str(entry_date[code].date()), "exit_date": str(last_day.date()),
                           "pnl": round(pnl, 2), "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                           "holding_bars": (last_day - entry_date[code]).days, "symbol": code})
    return pd.DataFrame(equity_curve), trades


if __name__ == "__main__":
    t0 = time.time()
    pool = E2.build_pool_with_factors()
    # 给池加 ma5（run_etf_v3 需要）
    for code, ddf in pool.items():
        ddf["ma5"] = ddf["close"].rolling(5).mean()
    print(f"ETF 池 {len(pool)} 只 + ma5 ({time.time()-t0:.0f}s)", flush=True)
    # 补扫：月频/季频 × Top3/5 × MA5开关 × 空仓阈值
    grid = []
    for hd in [21, 42, 63, 126]:
        for tn in [3, 5]:
            for m5 in [True]:
                for th in [None, 0.0]:
                    grid.append((hd, tn, m5, th))
    print(f"网格 {len(grid)} 组", flush=True)
    res = {}
    out_file = BASE / "etf_v3_results.json"
    for i, (hd, tn, m5, th) in enumerate(grid):
        try:
            eq, tr = run_etf_v3(pool, top_n=tn, hold_days=hd, freeze=5, mom_thresh=th, ma5_exit=m5)
            s = V.summary(eq, tr)
            key = f"H{hd}_T{tn}_M{int(m5)}_TH{('off' if th is None else '0')}_F5"
            res[key] = s
            print(f"[{i+1}/{len(grid)}] {key}: 收益 {s['total_return_pct']}% | 回撤 {s['max_drawdown_pct']}% | "
                  f"夏普 {s['sharpe']} | 交易 {s['total_trades']} ({time.time()-t0:.0f}s)", flush=True)
            json.dump({k: {kk: float(vv) for kk, vv in v.items()} for k, v in res.items()},
                      open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[{i+1}] {grid[i]} ERR: {e}", flush=True)
    best = max(res.items(), key=lambda kv: kv[1]["sharpe"]) if res else (None, {})
    print(f"\nBEST {best[0]} {best[1]}")