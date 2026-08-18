# -*- coding: utf-8 -*-
"""
混合方案回测：全量池 Top15 主仓 + 固定池（用户 20 只监控池）达标优先入选
- fixed_slots: 固定池最多占用名额（0=纯全量池，15=固定池达标全优先）
- fixed_thresh: 固定池标的入选分数阈值
其余参数与 v3 一致（Top15/季度轮动/MA200择时/移动止损10%）
"""
import os
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v8_selector as V
import v8_winrate as W

pool = W.pool
FIXED = {'600498', '601138', '002463', '002384', '600183',
         '603986', '002185', '605358', '603228', '603339', '000636', '605189',
         '600403', '002879', '600162', '000759', '002820', '002971', '603629'}
def to_key(c):
    return ('sh' if c.startswith(('6', '9')) else 'sz') + c
FIXED_KEYS = {to_key(c) for c in FIXED}
# 固定池在缓存中的子集
FIXED_OK = {k for k in FIXED_KEYS if k in pool}
print(f"固定池标的: {len(FIXED_KEYS)} 只, 缓存可用 {len(FIXED_OK)} 只", flush=True)


def run_mixed(top_n=15, hold_days=42, use_timing=True, stop_loss=0.10,
              stop_mode="trailing", fixed_slots=0, fixed_thresh=60,
              min_price=2.0, max_vol=0.60, min_amt=5e6):
    idx = V.load_index(200).set_index("date")
    in_market_map = idx["in_market"].to_dict()
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    rebal_days = set(all_days[::hold_days])
    cash = 1_000_000.0
    holdings, entry_price, entry_date = {}, {}, {}
    peak_price = {}
    equity_curve, trades = [], []
    pending_sell, pending_buy = set(), []
    last_close = {}

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_timing else True

        if (stop_loss or True) and holdings:
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
                    if fixed_slots > 0:
                        # 固定池达标标的优先（分数 >= 阈值），最多占 fixed_slots 个
                        fixed_ok = sorted([(c, s) for c, s in candidates.items() if c in FIXED_OK and s >= fixed_thresh],
                                          key=lambda kv: -kv[1])[:fixed_slots]
                        others = sorted([(c, s) for c, s in candidates.items() if c not in FIXED_OK or s < fixed_thresh],
                                        key=lambda kv: -kv[1])
                        ranked = fixed_ok + others[:top_n - len(fixed_ok)]
                    else:
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
    eq, tr = run_mixed(**kw)
    s = V.summary(eq, tr)
    # 统计固定池标的成交占比
    fixed_trades = sum(1 for t in tr if t["symbol"] in FIXED_OK)
    print(f"[{label}] {time.time()-t0:.0f}s | 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% | "
          f"回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | "
          f"交易 {s['total_trades']} | 固定池成交 {fixed_trades} 笔 ({fixed_trades/len(tr)*100:.0f}%)", flush=True)
    return s


if __name__ == "__main__":
    B = dict(top_n=15, hold_days=42, use_timing=True, stop_loss=0.10,
             stop_mode="trailing", min_price=2.0, max_vol=0.60)
    results = {}
    results["M0_纯全量对照"] = run_case("M0_纯全量对照", **B)
    # 混合：固定池名额 3/5/8，阈值 60/55
    results["M1_固定3_阈值60"] = run_case("M1_固定3_阈值60", **{**B, "fixed_slots": 3, "fixed_thresh": 60})
    results["M2_固定5_阈值60"] = run_case("M2_固定5_阈值60", **{**B, "fixed_slots": 5, "fixed_thresh": 60})
    results["M3_固定8_阈值60"] = run_case("M3_固定8_阈值60", **{**B, "fixed_slots": 8, "fixed_thresh": 60})
    results["M4_固定5_阈值55"] = run_case("M4_固定5_阈值55", **{**B, "fixed_slots": 5, "fixed_thresh": 55})
    results["M5_固定15_阈值60"] = run_case("M5_固定15_阈值60", **{**B, "fixed_slots": 15, "fixed_thresh": 60})
    json.dump(results, open("v8_mixed_results.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n=== 混合方案对比 ===")
    print(f"{'实验':<18} {'收益':>10} {'回撤':>8} {'夏普':>7} {'胜率':>7}")
    for k, v in results.items():
        print(f"{k:<18} {v['total_return_pct']:>9.1f}% {v['max_drawdown_pct']:>7.1f}% {v['sharpe']:>7.3f} {v['win_rate_pct']:>6.1f}%")