# -*- coding: utf-8 -*-
"""
增强矩阵 v3：全部按推荐回测
E1 动态卫星池：卫星候选 = 用户 20 只 ∪ 每期全市场得分 Top10
E4 卫星波动豁免：卫星池标的跳过 vol20>60% 过滤（诊断发现 19/20 被波动卡住）
E5 联动阈值：阈值随沪深300 20日波动率调整（低波 50 / 中波 55 / 高波 65）
ETF 混合：全量 ETF Top10 + 固定 5 只 ETF 卫星
基金混合：全市场动量 Top10 + 固定 6 只基金卫星
"""
import os
import sys, json, time, math, csv
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v8_selector as V
import v8_mixed as M
import v8_winrate as W

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
pool = M.pool
FIXED_OK = M.FIXED_OK


def run_mixed2(pool=None, top_n=15, hold_days=42, use_timing=True, stop_loss=0.10,
               stop_mode="trailing", fixed_slots=0, fixed_thresh=55,
               vol_exempt=False, dynamic_top=0, adaptive=False,
               min_price=2.0, max_vol=0.60, min_amt=5e6):
    """扩展 run_mixed：vol_exempt=卫星豁免波动过滤; dynamic_top=动态卫星数量; adaptive=阈值联动"""
    if pool is None:
        pool = globals().get("pool", M.pool)
    idx = V.load_index(200).set_index("date")
    idx["vol20_idx"] = idx["close"].pct_change().rolling(20).std() * math.sqrt(252)
    in_market_map = idx["in_market"].to_dict()
    idx_vol = idx["vol20_idx"].to_dict()
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    rebal_days = set(all_days[::hold_days])
    cash = 1_000_000.0
    holdings, entry_price, entry_date = {}, {}, {}
    peak_price = {}
    equity_curve, trades = [], []
    pending_sell, pending_buy = set(), []
    last_close = {}
    dyn_sat = set()   # 动态卫星（上期全市场 TopN）

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_timing else True

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
                if stop_loss:
                    base = peak_price[code] if stop_mode == "trailing" else entry_price[code]
                    if px <= base * (1 - stop_loss):
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
                        peak_price[code] = px
            pending_sell = set()
            pending_buy = []

        if day in rebal_days and di < len(all_days) - 1:
            if not in_market:
                pending_sell = set(holdings.keys())
                pending_buy = []
            else:
                thresh = fixed_thresh
                if adaptive:
                    v = idx_vol.get(day)
                    if v is not None and not pd.isna(v):
                        thresh = 50 if v < 0.15 else (65 if v > 0.30 else 55)
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
                        # 卫星池豁免：用户池 + 动态卫星 跳过波动过滤
                        if not (vol_exempt and (code in FIXED_OK or code in dyn_sat)):
                            continue
                    if r["close"] < min_price:
                        continue
                    candidates[code] = V.score_row(r)
                if candidates:
                    if fixed_slots > 0:
                        sat_candidates = set(FIXED_OK) | dyn_sat if dynamic_top else set(FIXED_OK)
                        fixed_ok = sorted([(c, s) for c, s in candidates.items() if c in sat_candidates and s >= thresh],
                                          key=lambda kv: -kv[1])[:fixed_slots]
                        others = sorted([(c, s) for c, s in candidates.items() if c not in sat_candidates or s < thresh],
                                        key=lambda kv: -kv[1])
                        ranked = fixed_ok + others[:top_n - len(fixed_ok)]
                    else:
                        ranked = sorted(candidates.items(), key=lambda kv: -kv[1])[:top_n]
                    keep = {c for c, _ in ranked}
                    pending_sell = {c for c in holdings if c not in keep}
                    pending_buy = ranked
                    # 更新动态卫星（下期生效：本期全市场 TopN 进卫星候选）
                    if dynamic_top > 0:
                        dyn_sat = {c for c, _ in sorted(candidates.items(), key=lambda kv: -kv[1])[:dynamic_top]}
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


def run_case(label, fn, **kw):
    t0 = time.time()
    eq, tr = fn(**kw)
    s = V.summary(eq, tr)
    print(f"[{label}] {time.time()-t0:.0f}s | 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% | "
          f"回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']}", flush=True)
    return s


if __name__ == "__main__":
    results = {}
    B = dict(top_n=15, hold_days=42, use_timing=True, stop_loss=0.10, stop_mode="trailing",
             min_price=2.0, max_vol=0.60)
    # v4 基线（TH55_K5）
    results["V4_基线"] = run_case("V4_基线", M.run_mixed, **B, fixed_slots=5, fixed_thresh=55)
    # E1 动态卫星池（用户池 ∪ 全市场 Top10）
    results["E1_动态卫星Top10"] = run_case("E1_动态卫星Top10", run_mixed2, **B,
                                          fixed_slots=5, fixed_thresh=55, dynamic_top=10)
    # E4 卫星波动豁免（slots 5/8）
    results["E4_豁免波动_K5"] = run_case("E4_豁免波动_K5", run_mixed2, **B,
                                        fixed_slots=5, fixed_thresh=55, vol_exempt=True)
    results["E4_豁免波动_K8"] = run_case("E4_豁免波动_K8", run_mixed2, **B,
                                        fixed_slots=8, fixed_thresh=55, vol_exempt=True)
    # E5 联动阈值（低波50/中55/高65）
    results["E5_联动阈值"] = run_case("E5_联动阈值", run_mixed2, **B,
                                     fixed_slots=5, fixed_thresh=55, adaptive=True)
    # 组合：豁免波动 + 动态卫星
    results["E6_豁免+动态"] = run_case("E6_豁免+动态", run_mixed2, **B,
                                      fixed_slots=5, fixed_thresh=55, vol_exempt=True, dynamic_top=10)
    json.dump(results, open("v8_enhance3_results.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n=== 增强矩阵 ===")
    print(f"{'实验':<16} {'收益':>10} {'回撤':>8} {'夏普':>7} {'胜率':>7}")
    for k, v in results.items():
        print(f"{k:<16} {v['total_return_pct']:>9.1f}% {v['max_drawdown_pct']:>7.1f}% {v['sharpe']:>7.3f} {v['win_rate_pct']:>6.1f}%")