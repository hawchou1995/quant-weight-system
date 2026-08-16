# -*- coding: utf-8 -*-
"""基金中长线 v2 优化（参考：动量阈值空仓 + 调仓周期网格）
================================================================
机制：净值动量 TopN 轮动 + 全部净值动量 < thresh → 空仓（熊市不硬扛）
+ MA 择时 + T+1 成交（场外基金真实规则）
"""
import os
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import v8_selector as V
import v8_fund_v5 as F   # 复用 navs / all_days_all / build_market_map / idx


def fund_nav_momentum(s, n=20):
    """净值动量：n 日累计收益"""
    return s / s.shift(n) - 1


def run_fund_thresh(top_n=10, hold_days=126, ma_window=100, mom_n=20,
                    mom_thresh=None, cash0=1_000_000.0):
    """基金轮动 + 动量阈值空仓（全部净值动量 < mom_thresh 时空仓）+ MA 择时，T+1 成交"""
    in_market_map = F.build_market_map(ma_window)
    rebal = set(F.all_days_all[::hold_days])
    cash = cash0
    holdings, entry_price, entry_date = {}, {}, {}
    equity_curve, trades = [], []
    pending_sell, pending_buy = set(), []
    last_nav = {}
    mom_cache = {}   # code -> 动量序列（复用）

    def momentum(code, day):
        if code not in mom_cache:
            mom_cache[code] = F.navs[code].pct_change(mom_n)
        s = mom_cache[code]
        if day in s.index:
            v = s.loc[day]
            return float(v) if not pd.isna(v) else None
        return None

    for di, day in enumerate(F.all_days_all):
        dstr = str(day.date())
        im = in_market_map.get(day, False)
        # 执行挂单（T+1 净值成交）
        if pending_sell or pending_buy:
            px_map = {}
            for code in list(pending_sell) + [c for c, _ in pending_buy]:
                s = F.navs.get(code)
                if s is not None and day in s.index:
                    px_map[code] = float(s.loc[day])
            for code in list(pending_sell):
                if code not in holdings:
                    continue
                px = px_map.get(code)
                if px is None or px <= 0:
                    continue
                sh = holdings.pop(code)
                proceeds = sh * px * (1 - V.COMMISSION)
                pnl = proceeds - sh * entry_price[code] * (1 + V.COMMISSION)
                trades.append({"entry_date": str(entry_date[code].date()), "exit_date": dstr,
                               "pnl": round(pnl, 2), "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                               "holding_bars": (day - entry_date[code]).days, "symbol": code})
                cash += proceeds
            if pending_buy:
                port_value = cash
                for code, sh in holdings.items():
                    if last_nav.get(code):
                        port_value += sh * last_nav[code]
                per_target = port_value / top_n
                for code, _m in pending_buy:
                    if code in holdings:
                        continue
                    px = px_map.get(code)
                    if px is None or px <= 0:
                        continue
                    sh = int(per_target / (px * (1 + V.COMMISSION)))
                    sh = (sh // 100) * 100
                    if sh > 0 and sh * px * (1 + V.COMMISSION) <= cash:
                        cash -= sh * px * (1 + V.COMMISSION)
                        holdings[code] = sh
                        entry_price[code] = px
                        entry_date[code] = day
            pending_sell, pending_buy = set(), []
        # 调仓
        if day in rebal and di < len(F.all_days_all) - 1:
            if not im:
                pending_sell = set(holdings.keys()); pending_buy = []
            else:
                scores = {}
                for code in F.navs:
                    m = momentum(code, day)
                    if m is None:
                        continue
                    if mom_thresh is not None and m < mom_thresh:
                        continue
                    scores[code] = m
                if scores:
                    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:top_n]
                    keep = {c for c, _ in ranked}
                    pending_sell = {c for c in holdings if c not in keep}
                    pending_buy = ranked
                else:
                    pending_sell = set(holdings.keys()); pending_buy = []
        # mark-to-market
        port_value = cash
        for code, sh in holdings.items():
            s = F.navs.get(code)
            px = None
            if s is not None and day in s.index:
                px = float(s.loc[day])
                last_nav[code] = px
            else:
                px = last_nav.get(code)
            if px:
                port_value += sh * px
        equity_curve.append({"date": dstr, "value": round(port_value, 2)})
    if holdings:
        last_day = F.all_days_all[-1]
        for code, sh in holdings.items():
            px = last_nav.get(code)
            if px is None or px <= 0:
                continue
            proceeds = sh * px * (1 - V.COMMISSION)
            pnl = proceeds - sh * entry_price[code] * (1 + V.COMMISSION)
            trades.append({"entry_date": str(entry_date[code].date()), "exit_date": str(last_day.date()),
                           "pnl": round(pnl, 2), "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                           "holding_bars": (last_day - entry_date[code]).days, "symbol": code})
    return pd.DataFrame(equity_curve), trades


if __name__ == "__main__":
    # 基线复现（MA100 当前生产参数）
    t0 = time.time()
    eq, tr = run_fund_thresh(top_n=10, hold_days=126, ma_window=100)
    s = V.summary(eq, tr)
    print(f"基线(MA100/T10/H126): 收益 {s['total_return_pct']}% | 回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} "
          f"({time.time()-t0:.0f}s)", flush=True)
    # 网格：调仓 × TopN × 空仓阈值 × 动量周期
    grid = []
    for hd in [42, 63, 126]:
        for tn in [5, 8, 10]:
            for th in [None, 0.0, 0.05]:
                for mn in [20, 60]:
                    grid.append((hd, tn, th, mn))
    print(f"网格 {len(grid)} 组", flush=True)
    res = {}
    out_file = BASE / "fund_v2_results.json"
    for i, (hd, tn, th, mn) in enumerate(grid):
        try:
            eq, tr = run_fund_thresh(top_n=tn, hold_days=hd, mom_n=mn, mom_thresh=th)
            s = V.summary(eq, tr)
            key = f"H{hd}_T{tn}_TH{('off' if th is None else str(th))}_M{mn}"
            res[key] = s
            print(f"[{i+1}/{len(grid)}] {key}: 收益 {s['total_return_pct']}% | 回撤 {s['max_drawdown_pct']}% | "
                  f"夏普 {s['sharpe']} | 交易 {s['total_trades']} ({time.time()-t0:.0f}s)", flush=True)
            json.dump({k: {kk: float(vv) for kk, vv in v.items()} for k, v in res.items()},
                      open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[{i+1}] {grid[i]} ERR: {e}", flush=True)
    best = max(res.items(), key=lambda kv: kv[1]["sharpe"]) if res else (None, {})
    print(f"\nBEST {best[0]} {best[1]}")