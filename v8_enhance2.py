# -*- coding: utf-8 -*-
"""
v8 增强网格 v2：修正择时（单 MA200）+ 个股止损 + 低波/流动性过滤 + 因子合成
目标：夏普 ≥0.8、回撤 ≤30%
"""
import sys, json, time, math
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import v8_selector as V

# 单 MA200 择时版 run（去掉 fast 双均线），加个股止损
def run_v8_single_timing(top_n=20, w_mom=0.35, w_trend=0.25, w_aroon=0.20, w_vp=0.20,
                         use_timing=True, min_amt=5e6, max_vol=None, hold_days=42,
                         pool=None, stop_loss=None, min_price=2.0, max_price=None,
                         min_mom=None):
    idx = V.load_index(200).set_index("date")
    in_market_map = idx["in_market"].to_dict()
    data = pool
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    rebal_days = set(all_days[::hold_days])

    cash = 1_000_000.0
    holdings, entry_price, entry_date = {}, {}, {}
    equity_curve, trades = [], []
    pending_sell, pending_buy = set(), []
    last_close = {}
    peak = 1_000_000.0

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_timing else True

        # 个股止损（每日检查：跌破成本价 × (1-stop_loss) → 次日开盘卖）
        if stop_loss and holdings:
            for code in list(holdings.keys()):
                ddf = data.get(code)
                if ddf is None or day not in ddf.index:
                    continue
                px = ddf.loc[day, "close"]
                if not pd.isna(px) and px <= entry_price[code] * (1 - stop_loss):
                    pending_sell.add(code)

        # 执行 T-1 挂单
        if pending_sell or pending_buy:
            open_px = {}
            for code in list(pending_sell) + [c for c, _ in pending_buy]:
                ddf = data.get(code)
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
                trades.append({
                    "entry_date": str(entry_date[code].date()), "exit_date": dstr,
                    "side": "long", "size": sh,
                    "entry_price": round(entry_price[code], 4), "exit_price": round(px, 4),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                    "holding_bars": (day - entry_date[code]).days,
                    "symbol": code, "symbol_name": code, "display_symbol": code,
                })
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

        # 再平衡日：计算排名
        if day in rebal_days and di < len(all_days) - 1:
            port_value_now = cash
            for code, sh in holdings.items():
                ddf = data.get(code)
                if ddf is not None and day in ddf.index:
                    px = ddf.loc[day, "close"]
                    if not pd.isna(px):
                        port_value_now += sh * px
            if port_value_now > peak:
                peak = port_value_now
            if not in_market:
                pending_sell = set(holdings.keys())
                pending_buy = []
            else:
                candidates = {}
                for code, ddf in data.items():
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
                    if max_price and r["close"] > max_price:
                        continue
                    if min_mom and (pd.isna(r["mom_12_1"]) or r["mom_12_1"] < min_mom):
                        continue
                    candidates[code] = V.score_row(r, w_mom, w_trend, w_aroon, w_vp)
                if candidates:
                    ranked = sorted(candidates.items(), key=lambda kv: -kv[1])[:top_n]
                    keep = {c for c, _ in ranked}
                    pending_sell = {c for c in holdings if c not in keep}
                    pending_buy = ranked
                else:
                    pending_sell = set(holdings.keys())
                    pending_buy = []

        # mark-to-market（当日无数据用最近收盘价兜底，避免数据末日错位）
        port_value = cash
        for code, sh in holdings.items():
            ddf = data.get(code)
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
            ddf = data.get(code)
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
            trades.append({
                "entry_date": str(entry_date[code].date()), "exit_date": str(last_day.date()),
                "side": "long", "size": sh,
                "entry_price": round(entry_price[code], 4), "exit_price": round(px, 4),
                "pnl": round(pnl, 2),
                "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                "holding_bars": (last_day - entry_date[code]).days,
                "symbol": code, "symbol_name": code, "display_symbol": code,
            })
            cash += proceeds
        holdings = {}
    return pd.DataFrame(equity_curve), trades


if __name__ == "__main__":
    pool = V.load_pool()
def run_case(label, **kw):
    t0 = time.time()
    eq, trades = run_v8_single_timing(pool=pool, **kw)
    s = V.summary(eq, trades)
    s["seconds"] = round(time.time() - t0, 0)
    s["label"] = label
    print(f"[{label}] {s['seconds']}s | 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% "
          f"| 回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']}", flush=True)
    return s

results = {}
BASE_KW = dict(top_n=20, hold_days=42, use_timing=True)

# 复现网格 T20_H42（单 MA200 应为 131% 量级）
results["F0_复现T20H42"] = run_case("F0_复现T20H42", **BASE_KW)

# 个股止损扫描
for sl in [0.15, 0.20, 0.25]:
    results[f"F1_止损{int(sl*100)}%"] = run_case(f"F1_止损{int(sl*100)}%", **BASE_KW, stop_loss=sl)

# 价格过滤（避低价股）
results["F2_价格≥2"] = run_case("F2_价格≥2", **BASE_KW, min_price=2.0)
results["F3_价格5-100"] = run_case("F3_价格5-100", **BASE_KW, min_price=5.0, max_price=100.0)

# 动量门槛（只买 mom_12_1 > 0 的）
results["F4_动量>0"] = run_case("F4_动量>0", **{**BASE_KW, "min_mom": 0.0})

# 波动上限（剔除高波动）
results["F5_波动<60%"] = run_case("F5_波动<60%", **BASE_KW, max_vol=0.60)
results["F6_波动<40%"] = run_case("F6_波动<40%", **BASE_KW, max_vol=0.40)

# 组合：止损20% + 价格≥2 + 动量>0 + 波动<60%
results["F7_组合风控"] = run_case("F7_组合风控", **BASE_KW, stop_loss=0.20, min_price=2.0,
    min_mom=0.0, max_vol=0.60)

with open("v8_enhance2_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\n===== v2 增强汇总（按夏普排序）=====")
for k, v in sorted(results.items(), key=lambda kv: -(kv[1].get("sharpe") or 0)):
    ok = "✅达标" if (v.get("sharpe") or 0) >= 0.8 and (v.get("max_drawdown_pct") or -99) > -30 else ""
    print(f"{k:<16} 收益 {v.get('total_return_pct')}% | 年化 {v.get('annual_return_pct')}% | 回撤 {v.get('max_drawdown_pct')}% | 夏普 {v.get('sharpe')} | 交易 {v.get('total_trades')} {ok}")
