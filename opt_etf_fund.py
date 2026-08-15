# -*- coding: utf-8 -*-
"""ETF/基金池优化实验：对齐股票池风控强度，扫描参数找更优组合。
ETF：TopN × 轮动周期 × 止损 × 择时窗口
基金：TopN × 轮动周期 × 净值止损 × 择时窗口"""
import sys, json, time
from pathlib import Path
import pandas as pd
import numpy as np

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
sys.path.insert(0, str(BASE))
import v8_selector as V

# ---------- ETF 优化 ----------
def build_etf_pool_fast():
    """复用 v8_etf_run 的池（避免重复构建）"""
    import v8_etf_run as E
    return E.build_etf_pool()

def run_etf_params(pool, top_n, hold_days, stop_loss, ma_win, min_price=0.5, max_vol=0.60, min_amt=1e6):
    """ETF 参数化回测（复制原版 v8_etf_run 逻辑，仅 ma_win 可调）"""
    idx = V.load_index(ma_win).set_index("date")
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
        in_market = in_market_map.get(day, False)
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
    # 期末强制平仓（末日兜底，与 summary 口径一致）
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
    eq = pd.DataFrame(equity_curve)
    return eq, trades

def etf_opt():
    pool = build_etf_pool_fast()
    print(f"ETF 池 {len(pool)} 只", flush=True)
    cases = [
        ("baseline_T20_H42_SL15_MA200", dict(top_n=20, hold_days=42, stop_loss=0.15, ma_win=200)),
        ("T10_H126_SL10_MA150",         dict(top_n=10, hold_days=126, stop_loss=0.10, ma_win=150)),
        ("T10_H126_SL08_MA150",         dict(top_n=10, hold_days=126, stop_loss=0.08, ma_win=150)),
        ("T10_H126_SL10_MA120",         dict(top_n=10, hold_days=126, stop_loss=0.10, ma_win=120)),
        ("T12_H126_SL10_MA150",         dict(top_n=12, hold_days=126, stop_loss=0.10, ma_win=150)),
        ("T10_H168_SL10_MA150",         dict(top_n=10, hold_days=168, stop_loss=0.10, ma_win=150)),
        ("T10_H126_SL12_MA150",         dict(top_n=10, hold_days=126, stop_loss=0.12, ma_win=150)),
        ("T8_H126_SL10_MA150",          dict(top_n=8, hold_days=126, stop_loss=0.10, ma_win=150)),
        ("T10_H126_SL10_MA180",         dict(top_n=10, hold_days=126, stop_loss=0.10, ma_win=180)),
        ("T15_H126_SL12_MA150",         dict(top_n=15, hold_days=126, stop_loss=0.12, ma_win=150)),
    ]
    res = {}
    for label, kw in cases:
        t0 = time.time()
        eq, tr = run_etf_params(pool, **kw)
        s = V.summary(eq, tr)
        res[label] = s
        print(f"{label}: 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% | 回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 交易 {s['total_trades']} ({time.time()-t0:.0f}s)", flush=True)
    json.dump(res, open(BASE / "etf_opt_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return res

if __name__ == "__main__":
    r = etf_opt()
    best = max(r.items(), key=lambda kv: kv[1]["sharpe"])
    print("BEST:", best[0], best[1])

# ---------- 基金优化 ----------
def fund_opt():
    """基金参数扫描（复用 v8_fund_v5 逻辑：净值动量 TopN + MA 择时 + 净值止损）"""
    import v8_fund_v5 as F
    # v8_fund_v5 已有 run_case；直接扫描关键参数
    cases = [
        ("F_base_ma100", dict(top_n=10, hold_days=126, ma_window=100)),
        ("F_ma100_ns15", dict(top_n=10, hold_days=126, ma_window=100, nav_stop=0.15)),
        ("F_ma100_ns20", dict(top_n=10, hold_days=126, ma_window=100, nav_stop=0.20)),
        ("F_ma120_ns15", dict(top_n=10, hold_days=126, ma_window=120, nav_stop=0.15)),
        ("F_ma100_t8",   dict(top_n=8, hold_days=126, ma_window=100, nav_stop=0.15)),
        ("F_ma100_t15",  dict(top_n=15, hold_days=126, ma_window=100, nav_stop=0.15)),
        ("F_ma80_ns15",  dict(top_n=10, hold_days=126, ma_window=80, nav_stop=0.15)),
        ("F_ma100_ns15_h84", dict(top_n=10, hold_days=84, ma_window=100, nav_stop=0.15)),
    ]
    import json as _j
    res = {}
    for label, kw in cases:
        try:
            eq, tr = F.run_fund_v5(**kw)
            s = V.summary(eq, tr)
            res[label] = s
            print(f"{label}: 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% | 回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 交易 {s['total_trades']}", flush=True)
        except Exception as e:
            print(label, "ERR", str(e)[:80], flush=True)
    _j.dump(res, open(BASE / "fund_opt_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return res

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "fund":
        r = fund_opt()
        best = max(r.items(), key=lambda kv: kv[1]["sharpe"])
        print("BEST:", best[0], best[1])
