# -*- coding: utf-8 -*-
"""
v8 ETF 回测独立脚本（自包含，生产版）
======================================
ETF 池：data_full sh5/sz1 开头，清洗除权跳变（单日 >25%）
参数：Top20 / H42 / 择时 / 止损15% / 波动<60% / 最低价 0.5 / 成交额 100 万
输出：v8_etf_equity.csv / v8_etf_trades.csv / v8_etf_summary.json
"""
import sys, json, time, csv
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
import v8_selector as V


def build_etf_pool():
    pool = {}
    for f in sorted((BASE / "data_full").glob("*.csv")):
        code = f.stem
        if not (code.startswith("sh5") or code.startswith("sz1")):
            continue
        try:
            df = pd.read_csv(f, dtype={"date": str})
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            if len(df) < 400:
                continue
            if df["close"].pct_change().abs().max() > 0.25:
                continue
            df = V.compute_factors_full(df).set_index("date")
            pool[code] = df
        except Exception:
            continue
    return pool


def run_etf(pool, top_n=20, hold_days=42, use_timing=True, stop_loss=0.15,
            min_price=0.5, max_vol=0.60, min_amt=1e6):
    """ETF 版主循环（自包含，mark-to-market 末日兜底）"""
    idx = V.load_index(200).set_index("date")
    in_market_map = idx["in_market"].to_dict()
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    rebal_days = set(all_days[::hold_days])
    cash = 1_000_000.0
    holdings, entry_price, entry_date = {}, {}, {}
    equity_curve, trades = [], []
    pending_sell, pending_buy = set(), []
    last_close = {}

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_timing else True
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
                               "side": "long", "size": sh, "entry_price": round(entry_price[code], 4),
                               "exit_price": round(px, 4), "pnl": round(pnl, 2),
                               "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                               "holding_bars": (day - entry_date[code]).days,
                               "symbol": code, "symbol_name": code, "display_symbol": code})
                cash += proceeds
            if pending_buy:
                port_value = cash
                for code, sh in holdings.items():
                    if last_close.get(code):
                        port_value += sh * last_close[code]
                per_target = port_value / top_n
                for code, _score in pending_buy:
                    if code in holdings:
                        continue
                    px = open_px.get(code)
                    if px is None or pd.isna(px) or px <= 0:
                        continue
                    target_shares = int(per_target / (px * (1 + V.COMMISSION)))
                    target_shares = (target_shares // V.LOT) * V.LOT
                    if target_shares > 0 and target_shares * px * (1 + V.COMMISSION) <= cash:
                        cash -= target_shares * px * (1 + V.COMMISSION)
                        holdings[code] = target_shares
                        entry_price[code] = px
                        entry_date[code] = day
            pending_sell = set()
            pending_buy = []
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
                    if pd.isna(r["amt20"]) or r["amt20"] < min_amt:
                        continue
                    if max_vol and not pd.isna(r["vol20"]) and r["vol20"] > max_vol:
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
    t0 = time.time()
    pool = build_etf_pool()
    print(f"ETF 池: {len(pool)} 只（清洗后）", flush=True)
    eq, trades = run_etf(pool)
    s = V.summary(eq, trades)
    print(f"ETF v8 Top20/H42: 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% "
          f"| 回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']} "
          f"({time.time()-t0:.0f}s)", flush=True)
    eq.to_csv(BASE / "v8_etf_equity.csv", index=False)
    with open(BASE / "v8_etf_trades.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        keys = ["entry_date", "exit_date", "side", "size", "entry_price", "exit_price",
                "pnl", "pnl_pct", "holding_bars", "symbol", "symbol_name", "display_symbol"]
        w.writerow(keys)
        for t in trades:
            w.writerow([t.get(k, "") for k in keys])
    with open(BASE / "v8_etf_summary.json", "w", encoding="utf-8") as f:
        json.dump({"meta": {"strategy_name": "v8 ETF 中长线看板（Top20/季度轮动）",
                            "symbol": "全量 ETF 截面选股 Top20", "start": V.START, "end": V.END,
                            "initial_cash": 1000000.0,
                            "window_start_value": float(eq["value"].iloc[0]),
                            "final_value": float(eq["value"].iloc[-1]), "market": "china_a"},
                   "summary": s}, f, ensure_ascii=False, indent=2)
    print("已输出 v8_etf_equity.csv / v8_etf_trades.csv / v8_etf_summary.json")
