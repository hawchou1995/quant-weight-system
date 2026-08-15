# -*- coding: utf-8 -*-
"""
v8 夏普冲刺矩阵 v2（目标：夏普 ≥1.0，回撤 <30%，年化 >14%）
=============================================================
自包含引擎（复制 run_v8_single_timing + 新增 vol_target 波动率目标仓位）
升级点：
1. vol_target：目标年化波动，仓位 = vol_target / 指数 20 日波动（0.3~1.0 缩放）
2. rsi_overbought 过滤：rsi14 > 阈值剔除
3. 动量增强：mom12_1 门槛提高
4. TopN 收缩 + 止损收窄
"""
import sys, json, time, math, csv
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import v8_selector as V


def add_rsi(pool, period=14):
    for code, df in pool.items():
        if "rsi14" in df.columns:
            continue
        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi14"] = (100 - 100 / (1 + rs)).fillna(50)
    return pool


def run_v8x(pool, top_n=25, hold_days=42, use_timing=True, stop_loss=0.20,
            min_price=2.0, max_vol=0.60, min_amt=5e6,
            vol_target=None, rsi_max=None, min_mom=None):
    idx = V.load_index(200).set_index("date")
    idx["vol20"] = idx["close"].pct_change().rolling(20).std() * math.sqrt(252)
    in_market_map = idx["in_market"].to_dict()
    vol_map = idx["vol20"].to_dict()
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
                # 波动率目标仓位
                scale = 1.0
                if vol_target:
                    cur_vol = vol_map.get(day)
                    if cur_vol and not pd.isna(cur_vol) and cur_vol > 0:
                        scale = max(0.3, min(1.0, vol_target / cur_vol))
                per_target = port_value * scale / top_n
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
                    if rsi_max is not None and "rsi14" in ddf.columns and not pd.isna(r["rsi14"]) and r["rsi14"] > rsi_max:
                        continue
                    if min_mom is not None and r["mom_12_1"] < min_mom:
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
    pool = add_rsi(V.load_pool())
    print(f"池: {len(pool)} 只\n")

    def run_case(label, **kw):
        t0 = time.time()
        eq, trades = run_v8x(pool=pool, **kw)
        s = V.summary(eq, trades)
        s["seconds"] = round(time.time() - t0, 0)
        s["label"] = label
        flag = "✅达标" if (s.get("sharpe") or 0) >= 1.0 and (s.get("max_drawdown_pct") or -99) > -30 else ""
        print(f"[{label}] {s['seconds']}s | 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% "
              f"| 回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']} {flag}", flush=True)
        return s

    results = {}
    B = dict(hold_days=42, use_timing=True, stop_loss=0.20, min_price=2.0, max_vol=0.60)

    # 基线复现
    results["S0_基线Top25"] = run_case("S0_基线Top25", top_n=25, **B)

    # 波动率目标仓位
    for vt in [0.10, 0.12, 0.15, 0.18]:
        results[f"S1_vol目标{int(vt*100)}%"] = run_case(f"S1_vol目标{int(vt*100)}%", top_n=25, **B, vol_target=vt)

    # RSI 过热过滤
    for rm in [70, 75, 80]:
        results[f"S2_RSI<{rm}"] = run_case(f"S2_RSI<{rm}", top_n=25, **B, rsi_max=rm)

    # 动量门槛
    for mm in [0.05, 0.10, 0.15]:
        results[f"S3_动量>{mm}"] = run_case(f"S3_动量>{mm}", top_n=25, **B, min_mom=mm)

    # TopN 收缩 + 止损收窄
    for tn, sl in [(10, 0.15), (15, 0.15), (10, 0.20), (15, 0.20)]:
        results[f"S4_Top{tn}_止损{int(sl*100)}"] = run_case(f"S4_Top{tn}_止损{int(sl*100)}", top_n=tn, **{**B, "stop_loss": sl})

    # 组合：vol目标12% + RSI<80 + Top15 止损15%
    results["S5_组合A"] = run_case("S5_组合A", top_n=15, **{**B, "stop_loss": 0.15, "vol_target": 0.12, "rsi_max": 80})
    # 组合：vol目标12% + RSI<80 + Top15 止损20%
    results["S6_组合B"] = run_case("S6_组合B", top_n=15, **{**B, "stop_loss": 0.20, "vol_target": 0.12, "rsi_max": 80})
    # 组合：vol目标10% + 动量>0.05 + Top15
    results["S7_组合C"] = run_case("S7_组合C", top_n=15, **{**B, "stop_loss": 0.15, "vol_target": 0.10, "min_mom": 0.05})

    with open("v8_sprint2_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n===== 冲刺矩阵汇总（按夏普排序）=====")
    for k, v in sorted(results.items(), key=lambda kv: -(kv[1].get("sharpe") or 0)):
        flag = "✅达标" if (v.get("sharpe") or 0) >= 1.0 and (v.get("max_drawdown_pct") or -99) > -30 else ""
        print(f"{k:<20} 收益 {v.get('total_return_pct')}% | 年化 {v.get('annual_return_pct')}% | 回撤 {v.get('max_drawdown_pct')}% | 夏普 {v.get('sharpe')} {flag}")
