# -*- coding: utf-8 -*-
"""
v8 胜率优化实验：参数不动（Top15/H42/MA200择时/波动<60%），只改卖出规则
- stop_mode: "cost"(基线,成本价回撤) | "trailing"(移动止损,持仓最高价回撤)
- take_profit: 盈利 X% 全部了结
目标：胜率↑ 且 收益≥360.82% 且 夏普≥1.166（严格帕累托，用户约束）
口径：与 v8_sprint2 一致（当日 close 触发 → 当日 open 成交，T+0 近似）
"""
import sys, json, time, math, os
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v8_selector as V
import v8_sprint2 as S

pool = S.add_rsi(V.load_pool())
print(f"股票池: {len(pool)} 只（缓存）", flush=True)


def run_v8w(pool, top_n=15, hold_days=42, use_timing=True, stop_loss=0.12,
            stop_mode="cost", take_profit=None,
            min_price=2.0, max_vol=0.60, min_amt=5e6):
    idx = V.load_index(200).set_index("date")
    in_market_map = idx["in_market"].to_dict()
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    rebal_days = set(all_days[::hold_days])
    cash = 1_000_000.0
    holdings, entry_price, entry_date = {}, {}, {}
    peak_price = {}          # trailing 用：持仓期间最高价
    equity_curve, trades = [], []
    pending_sell, pending_buy = set(), []
    last_close = {}

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_timing else True

        # ---- 卖出信号（当日 close 判断，当日 open 成交，与基线口径一致）----
        if (stop_loss or take_profit) and holdings:
            for code in list(holdings.keys()):
                ddf = pool.get(code)
                if ddf is None or day not in ddf.index:
                    continue
                px = ddf.loc[day, "close"]
                if pd.isna(px) or px <= 0:
                    continue
                # 更新峰值（trailing）
                if code not in peak_price or px > peak_price[code]:
                    peak_price[code] = px
                if stop_loss:
                    base = peak_price[code] if stop_mode == "trailing" else entry_price[code]
                    if px <= base * (1 - stop_loss):
                        pending_sell.add(code)
                        continue
                if take_profit and px >= entry_price[code] * (1 + take_profit):
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


def run_case(label, **kw):
    t0 = time.time()
    eq, trades = run_v8w(pool=pool, **kw)
    s = V.summary(eq, trades)
    win = s.get("win_rate_pct", 0)
    ret = s.get("total_return_pct", 0)
    shp = s.get("sharpe", 0)
    dd = s.get("max_drawdown_pct", -99)
    pareto = "✅帕累托" if (win >= 51.0 and ret >= 360.82 and shp >= 1.166) else (
        "🟡收益或夏普降" if (win > 51.0 and ret < 360.82) else "")
    print(f"[{label}] {time.time()-t0:.0f}s | 收益 {ret}% | 年化 {s.get('annual_return_pct')}% | "
          f"回撤 {dd}% | 夏普 {shp} | 胜率 {win}% | 交易 {s.get('total_trades')} {pareto}", flush=True)
    return s


if __name__ == "__main__":
    BASE = dict(top_n=15, hold_days=42, use_timing=True, stop_loss=0.12,
                min_price=2.0, max_vol=0.60)
    results = {}
    # 基线确认（成本价止损 12%，应与 1.166 一致）
    results["W0_基线cost12"] = run_case("W0_基线cost12", **BASE)
    # A 组：trailing 移动止损（峰值回撤 10/12/15）
    for sl in [0.10, 0.12, 0.15]:
        results[f"W1_trailing{int(sl*100)}"] = run_case(f"W1_trailing{int(sl*100)}",
                                                        **{**BASE, "stop_mode": "trailing", "stop_loss": sl})
    # B 组：高阈值止盈（成本价止损不动，+25/30/40/50 了结）
    for tp in [0.25, 0.30, 0.40, 0.50]:
        results[f"W2_tp{int(tp*100)}"] = run_case(f"W2_tp{int(tp*100)}",
                                                  **{**BASE, "take_profit": tp})
    # C 组：trailing12 + 止盈40 组合
    results["W3_trail12_tp40"] = run_case("W3_trail12_tp40",
                                          **{**BASE, "stop_mode": "trailing", "take_profit": 0.40})
    json.dump(results, open("v8_winrate_results.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n=== 汇总（按胜率排序）===")
    for k, v in sorted(results.items(), key=lambda kv: -kv[1].get("win_rate_pct", 0)):
        pareto = "✅" if (v.get("win_rate_pct", 0) >= 51.0 and v.get("total_return_pct", 0) >= 360.82
                          and v.get("sharpe", 0) >= 1.166) else ""
        print(f"{k:<18} 收益 {v.get('total_return_pct')}% | 回撤 {v.get('max_drawdown_pct')}% | "
              f"夏普 {v.get('sharpe')} | 胜率 {v.get('win_rate_pct')}% {pareto}")
