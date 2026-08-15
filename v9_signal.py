# -*- coding: utf-8 -*-
"""
v9 普适信号体系：绝对打分 + 动态系数（不选 TopN，任何股票达标即持有）
- 每只股票独立四因子打分（动量35%/趋势25%/Aroon20%/量价20%），与排名无关
- 动态买入门槛：buy_thresh = 60 + (沪深300 20日波动率 - 20%) × 200，clip [45,75]
- 沪深300 < MA200 → 空仓（门禁）
- 月检（21 日）全池评估：score ≥ 门槛 → 持有/买入；score < 卖出门槛(45) → 卖出
- 每日：移动止损（峰值回撤10%）+ 大盘破位清仓
- 资金：达标等权（当前市值/达标数），单票≤10%，动态等权（无固定预算）
- 回测：全量池 5307 只，2016-2026
目标：夏普≥1 / 回撤≤30% / 年化≥10%
"""
import sys, json, time, math
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import v8_selector as V

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")


def load_pool():
    return V.load_pool()


def score_series(ddf):
    """向量化四因子打分（整列）"""
    s = np.zeros(len(ddf))
    if "mom_12_1" in ddf.columns:
        m = ddf["mom_12_1"].values
        s += 35 * np.clip(m / 0.20, 0, 1)
    if "ma200_pos" in ddf.columns:
        t = ddf["ma200_pos"].values
        s += 25 * np.clip(t / 0.30, 0, 1)
    if "aroon_osc" in ddf.columns:
        a = np.clip(ddf["aroon_osc"].values, -100, 100)
        s += 20 * ((a + 100) / 200)
    if "vp_confirm" in ddf.columns:
        s += 20 * ddf["vp_confirm"].values.astype(float)
    return s


def run_v9(pool, hold_days=21, buy_base=60, sell_thresh=45, dynamic=True,
           stop_loss=0.10, cash0=500_000.0, max_w=0.10, min_price=2.0, min_amt=5e6,
           max_holdings=30, mom_min=0.25, new_high_dist=0.85, verbose=False):
    idx = V.load_index(200).set_index("date")
    idx["vol20_idx"] = idx["close"].pct_change().rolling(20).std() * math.sqrt(252)
    in_market_map = idx["in_market"].to_dict()
    idx_vol = idx["vol20_idx"].to_dict()
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    rebal_days = set(all_days[::hold_days])

    # 预计算每只标的的 score 序列 + close 序列 + open 序列
    scores = {}   # code -> np.array (aligned to ddf.index)
    closes = {}
    opens = {}
    ddates = {}
    t0 = time.time()
    for code, ddf in pool.items():
        scores[code] = score_series(ddf)
        closes[code] = ddf["close"].values
        opens[code] = ddf["open"].values if "open" in ddf.columns else ddf["close"].values
        ddates[code] = ddf.index
    if verbose:
        print(f"预计算 {len(pool)} 只 ({time.time()-t0:.0f}s)", flush=True)

    cash = cash0
    holdings = {}       # code -> shares
    entry_price = {}
    entry_date = {}
    peak_price = {}
    equity_curve = []
    trades = []
    last_close = {}
    n_rebal_evals = 0

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False)
        vol = idx_vol.get(day)

        # ---- 每日：移动止损（当日 close 触发 → 当日 close 成交，T+0 近似口径）----
        if stop_loss and holdings:
            for code in list(holdings.keys()):
                dd = ddates.get(code)
                if dd is None or day not in dd:
                    continue
                pos = dd.get_loc(day)
                px = closes[code][pos]
                if np.isnan(px) or px <= 0:
                    continue
                if code not in peak_price or px > peak_price[code]:
                    peak_price[code] = px
                if px <= peak_price[code] * (1 - stop_loss):
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

        # ---- 执行挂单（T-1 信号，当日开盘成交近似：用当日收盘代替——与既有口径一致）----
        # 简化实现：信号日收盘判断 → 次日开盘执行 = 用 next day 的 open
        # 为保持与主体系一致（close 触发 open 成交同日近似），此处用当日 open 执行前一日信号

        # 持仓市值
        port_value = cash
        for code, sh in holdings.items():
            dd = ddates.get(code)
            px = None
            if dd is not None and day in dd:
                pos = dd.get_loc(day)
                c = closes[code][pos]
                if not np.isnan(c) and c > 0:
                    last_close[code] = c
                    px = c
                else:
                    px = last_close.get(code)
            else:
                px = last_close.get(code)
            if px:
                port_value += sh * px

        # ---- 再平衡日：全池评估 ----
        if day in rebal_days and di < len(all_days) - 1:
            n_rebal_evals += 1
            if not in_market:
                # 清仓
                for code, sh in list(holdings.items()):
                    px = last_close.get(code)
                    if px is None or px <= 0:
                        continue
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
                    holdings.pop(code)
                    peak_price.pop(code, None)
                if verbose:
                    print(f"  {dstr} 空仓清仓", flush=True)
            else:
                # 动态门槛
                if dynamic and vol is not None and not np.isnan(vol):
                    thresh = buy_base + (vol - 0.20) * 200
                    thresh = max(45.0, min(75.0, thresh))
                else:
                    thresh = buy_base
                # 全池打分（再平衡日）
                buy_list = []
                for code, dd in ddates.items():
                    if day not in dd:
                        continue
                    pos = dd.get_loc(day)
                    sc = scores[code][pos]
                    px = closes[code][pos]
                    if np.isnan(sc) or np.isnan(px) or px <= 0:
                        continue
                    # v9.2 绝对质量门槛（人人平等，只有真正强的股票达标）
                    r = pool[code].iloc[pos]
                    if px < min_price:
                        continue
                    if pd.isna(r["amt20"]) or r["amt20"] < min_amt:
                        continue
                    if pd.isna(r["mom_12_1"]) or r["mom_12_1"] < mom_min:
                        continue
                    # 接近 52 周新高（趋势确认）
                    if "high252" in ddf.columns:
                        h252 = ddf["high252"].iloc[pos]
                        if np.isnan(h252) or px < h252 * new_high_dist:
                            continue
                    # 动量加速：3 月动量不弱于 12-1 月动量（新动量>旧动量）
                    if "mom_3m" in ddf.columns:
                        m3 = ddf["mom_3m"].iloc[pos]
                        if not np.isnan(m3) and m3 < r["mom_12_1"]:
                            continue
                    if sc >= thresh:
                        buy_list.append((code, sc, px))
                    elif code in holdings and sc < sell_thresh:
                        # 卖出（收盘判断，次日执行——此处同日 close 成交近似）
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
                        peak_price.pop(code, None)
                # 买入达标：分数加权仓位（权重∝score，达标即持有不砍单）+ 容量上限
                if buy_list:
                    slots = max_holdings - len(holdings)
                    if slots > 0:
                        bl = sorted(buy_list, key=lambda kv: -kv[1])[:slots]
                        # 分数加权：w_i ∝ (score - thresh + 10)，归一化
                        ws = np.array([max(5.0, sc - thresh + 10) for _, sc, _ in bl], dtype=float)
                        ws = ws / ws.sum()
                        for (code, sc, px), w in zip(bl, ws):
                            if code in holdings:
                                continue
                            if px <= 0:
                                continue
                            budget = port_value * min(w, max_w)
                            lot = 100
                            n_lots = int(budget / (px * lot * (1 + V.COMMISSION)))
                            if n_lots < 1:
                                continue
                            target_shares = n_lots * lot
                            cost = target_shares * px * (1 + V.COMMISSION)
                            if cost > cash:
                                n_lots = int(cash / (px * lot * (1 + V.COMMISSION)))
                                target_shares = n_lots * lot
                                cost = target_shares * px * (1 + V.COMMISSION)
                            if target_shares > 0 and cost <= cash:
                                cash -= cost
                                holdings[code] = target_shares
                                entry_price[code] = px
                                entry_date[code] = day
                                peak_price[code] = px
                        if verbose:
                            print(f"  {dstr} 门槛{thresh:.0f} 达标{len(buy_list)}只 买入{len(bl)} 持仓{len(holdings)}只", flush=True)

        # ---- 移动止损执行（前一日触发，今日开盘近似用今日 close）----
        # 简化：止损在每日检查时立即以当日 close 成交（口径披露）

        equity_curve.append({"date": dstr, "value": round(port_value, 2)})

    # 期末平仓
    if holdings:
        last_day = all_days[-1]
        for code, sh in list(holdings.items()):
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
            holdings.pop(code)
    return pd.DataFrame(equity_curve), trades


if __name__ == "__main__":
    pool = load_pool()
    print(f"全量池 {len(pool)} 只", flush=True)
    t0 = time.time()
    eq, tr = run_v9(pool, verbose=True)
    s = V.summary(eq, tr)
    print(f"\n[v9 基线] {time.time()-t0:.0f}s | 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% | "
          f"回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']}", flush=True)
