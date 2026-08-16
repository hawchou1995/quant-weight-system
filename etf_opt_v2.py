# -*- coding: utf-8 -*-
"""ETF 中长线 v2 优化（参考：知乎动量轮动体系）
================================================================
新因子：RSRS 动量（高低价 OLS 斜率 Z-Score）/ 斜率动量（价格-时间回归）
新机制：冷冻期（卖出后 N 天不买回）/ 动量阈值空仓（全负空仓）
网格：动量类型 × 调仓周期 × TopN × 冷冻 × 空仓阈值
"""
import os
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import v8_selector as V
import v8_etf_run as E


def rsrs_series(hi, lo, n=20, m=5):
    """RSRS：高低价 OLS 斜率（cov/var 向量化）→ 最近 m 日 Z-Score"""
    b = hi.rolling(n).cov(lo) / lo.rolling(n).var().replace(0, np.nan)
    z = (b - b.rolling(m).mean()) / b.rolling(m).std().replace(0, np.nan)
    return z


def slope_series(px, n=20):
    """斜率动量：价格对时间线性回归斜率（最近 n 日）"""
    def _slope(x):
        if len(x) < 2 or np.std(x) == 0:
            return 0.0
        t = np.arange(len(x))
        return np.polyfit(t, x, 1)[0]
    return px.rolling(n).apply(_slope, raw=True)


def build_pool_with_factors():
    """ETF 池 + 三动量因子（mom20 简单 / rsrs / slope）"""
    pool = E.build_etf_pool()
    for code, ddf in pool.items():
        hi = ddf["high"]; lo = ddf["low"]; c = ddf["close"]
        ddf["mom20"] = c / c.shift(20) - 1
        ddf["rsrs"] = rsrs_series(hi, lo)
        ddf["slope"] = slope_series(c, 20)
        ddf["mom60"] = c / c.shift(60) - 1
    return pool


def run_etf_v2(pool, mom_type="mom20", top_n=8, hold_days=63, stop_loss=0.10,
               freeze=0, mom_thresh=0.0, use_timing=True, ma_win=150,
               cash0=1_000_000, min_amt=1e6, min_px=0.5, max_vol=0.60):
    """ETF 中长线 v2：动量排名轮动 + 冷冻期 + 动量阈值空仓 + MA 择时"""
    idx = V.load_index(ma_win).set_index("date")
    in_market_map = idx["in_market"].to_dict()
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    rebal_days = set(all_days[::hold_days])
    cash = cash0
    holdings, entry_price, entry_date = {}, {}, {}
    last_sell_day = {}            # 冷冻期：code -> 最后卖出日
    equity_curve, trades = [], []
    pending_sell, pending_buy = set(), []
    last_close = {}

    def frozen(code, day):
        return last_sell_day.get(code, None) is not None and (day - last_sell_day[code]).days < freeze

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_timing else True
        # 止损
        if stop_loss and holdings:
            for code in list(holdings.keys()):
                ddf = pool.get(code)
                if ddf is None or day not in ddf.index:
                    continue
                px = ddf.loc[day, "close"]
                if not pd.isna(px) and px <= entry_price[code] * (1 - stop_loss):
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
                    sh = int(per_target / (px * (1 + V.COMMISSION)))
                    if sh > 0 and sh * px * (1 + V.COMMISSION) <= cash:
                        cash -= sh * px * (1 + V.COMMISSION)
                        holdings[code] = sh
                        entry_price[code] = px
                        entry_date[code] = day
            pending_sell, pending_buy = set(), []
        # 调仓
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
                    if pd.isna(r["close"]) or r["close"] <= 0 or pd.isna(r.get(mom_type, np.nan)):
                        continue
                    if pd.isna(r["amt20"]) or r["amt20"] < min_amt:
                        continue
                    if max_vol and not pd.isna(r["vol20"]) and r["vol20"] > max_vol:
                        continue
                    if r["close"] < min_px:
                        continue
                    m = r[mom_type]
                    # 动量阈值空仓：全部动量 < thresh → 空仓
                    if mom_thresh is not None and m < mom_thresh:
                        continue
                    candidates[code] = m
                if candidates:
                    ranked = sorted(candidates.items(), key=lambda kv: -kv[1])[:top_n]
                    keep = {c for c, _ in ranked}
                    pending_sell = {c for c in holdings if c not in keep}
                    pending_buy = ranked
                else:
                    pending_sell = set(holdings.keys())
                    pending_buy = []
        # mark-to-market
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
    # 期末平仓
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
    pool = build_pool_with_factors()
    print(f"ETF 池 {len(pool)} 只 + 三动量因子 ({time.time()-t0:.0f}s)", flush=True)
    # 粗扫：动量类型 × 调仓 × TopN × 冷冻 × 空仓
    grid = []
    for mt in ["mom20", "rsrs", "slope"]:
        for hd in [42, 63, 126]:
            for tn in [5, 8]:
                for fz in [0, 5]:
                    for th in [None, 0.0]:
                        grid.append((mt, hd, tn, fz, th))
    print(f"网格 {len(grid)} 组", flush=True)
    res = {}
    out_file = BASE / "etf_v2_results.json"
    for i, (mt, hd, tn, fz, th) in enumerate(grid):
        try:
            eq, tr = run_etf_v2(pool, mom_type=mt, top_n=tn, hold_days=hd, freeze=fz, mom_thresh=th)
            s = V.summary(eq, tr)
            key = f"{mt}_H{hd}_T{tn}_F{fz}_TH{('off' if th is None else '0')}"
            res[key] = s
            print(f"[{i+1}/{len(grid)}] {key}: 收益 {s['total_return_pct']}% | 回撤 {s['max_drawdown_pct']}% | "
                  f"夏普 {s['sharpe']} | 卡玛 {s['annual_return_pct']/max(0.01,abs(s['max_drawdown_pct'])):.2f} | "
                  f"交易 {s['total_trades']}", flush=True)
            json.dump({k: {kk: float(vv) for kk, vv in v.items()} for k, v in res.items()},
                      open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[{i+1}] {grid[i]} ERR: {e}", flush=True)
    best = max(res.items(), key=lambda kv: kv[1]["sharpe"]) if res else (None, {})
    print(f"\nBEST sharpe: {best[0]} {best[1]}")
    by_calmar = max(res.items(), key=lambda kv: kv[1]["annual_return_pct"] / max(0.01, abs(kv[1]["max_drawdown_pct"])))
    print(f"BEST calmar: {by_calmar[0]} {by_calmar[1]}")