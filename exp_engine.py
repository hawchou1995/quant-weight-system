# -*- coding: utf-8 -*-
"""
v6 实验引擎（子样本版）：候选指标注入 + 权重/门槛参数化 + buyhold 修复 + 涨跌停约束
====================================================================================
复用 weight_system_backtest 的指标与打分函数，run_backtest 参数化：
- extra_penalties: {列名: 扣分} 每命中扣分（逃顶信号等）
- extra_bonuses:   {列名: 加分}（Aroon/MFI 正向）
- overrides:       覆盖层强制减仓（1 信号→25% 目标仓 等）
- thresholds:      四门槛覆盖
- weights_override: 六维权重覆盖
- fix_buyhold:     True 时 buyhold 全仓（绕过 target_cap 50% 上限）
- limit_rule:      True 时涨跌停不可成交（涨停不可买/跌停不可卖）
"""
import os, sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import weight_system_backtest as W

# 与 fullpool_v6_backtest 保持一致的评估窗口（2016-01-04 起，10.6 年）
W.BACKTEST_START = "2016-01-04"
W.BACKTEST_END = "2026-08-14"

# ---------------- 指标扩展：候选列 ----------------
def add_candidate_indicators(d: pd.DataFrame, use_escape: bool = True,
                             use_aroon: bool = True, use_mfi: bool = True) -> pd.DataFrame:
    """注入候选指标列：逃顶3信号 + Aroon + MFI（基于 8/14 设计文档定义）"""
    # 逃顶 3 子信号（明规智投 6 大顶部信号中 OHLCV 可量化子集）
    if use_escape:
        # vol_ratio 已存在
        d["ret5"] = d["close"] / d["close"].shift(5) * 100 - 100
        d["vol_ratio2"] = d["volume"] / d["volume"].rolling(5).mean().replace(0, np.nan)
        # esc_stall 放量滞涨：量比≥2 且 5日涨幅≤2%（且 >-8% 排除下跌段）
        d["esc_stall"] = ((d["vol_ratio2"] >= 2) & (d["ret5"] <= 2) & (d["ret5"] > -8)).astype(int)
        # esc_break 破位加速：收盘<MA60 且量比≥1.5 且 60日回撤>15%
        d["ma60"] = d["close"].rolling(60).mean()
        d["dd60b"] = (d["close"] / d["close"].rolling(60).max() - 1) * 100
        d["esc_break"] = ((d["close"] < d["ma60"]) & (d["vol_ratio2"] >= 1.5)
                          & (d["dd60b"] < -15)).astype(int)
        # esc_volpeak 天量见顶：20日量新高 且 量比≥2
        d["vol_high20"] = (d["volume"] >= d["volume"].rolling(20).max().shift(1)).astype(int)
        d["esc_volpeak"] = (d["vol_high20"] & (d["vol_ratio2"] >= 2)).astype(int)
        # 累计逃顶信号数（用于 overrides 模式）
        d["esc_count"] = d["esc_stall"] + d["esc_break"] + d["esc_volpeak"]
    # Aroon(25)：上升/下降强度
    if use_aroon:
        period = 25
        high_roll = d["high"].rolling(period + 1)
        low_roll = d["low"].rolling(period + 1)
        high_idx = d["high"].rolling(period + 1).apply(lambda x: np.argmax(x), raw=True)
        low_idx = d["low"].rolling(period + 1).apply(lambda x: np.argmin(x), raw=True)
        d["aroon_up"] = (100 * (period - high_idx) / period).fillna(50)
        d["aroon_down"] = (100 * (period - low_idx) / period).fillna(50)
        d["aroon_osc"] = d["aroon_up"] - d["aroon_down"]
    # MFI(14)：量价加权 RSI
    if use_mfi:
        tp = (d["high"] + d["low"] + d["close"]) / 3
        mf = tp * d["volume"].fillna(0)
        pos_mf = mf.where(tp > tp.shift(1), 0.0).rolling(14).sum()
        neg_mf = mf.where(tp < tp.shift(1), 0.0).rolling(14).sum()
        mfr = pos_mf / neg_mf.replace(0, np.nan)
        d["mfi"] = (100 - 100 / (1 + mfr)).fillna(50)
    return d


def compute_total_score_w(row, news_level, is_fund=False, weights_override=None):
    """六维打分 + 可覆盖权重（原版 compute_total_score 硬编码全局 WEIGHTS）"""
    st = W.score_trend(row)
    sm = W.score_momentum(row)
    sv = W.score_volume(row, is_fund=is_fund)
    so = W.score_osc(row)
    sr = W.score_risk(row)
    sn = W.score_news(row, news_level)
    w = weights_override or W.WEIGHTS
    total = (
        st * w["trend"] + sm * w["momentum"] + sv * w["volume"]
        + so * w["osc"] + sr * w["risk"] + sn * w["news"]
    )
    comp = {"trend": st, "momentum": sm, "volume": sv, "osc": so, "risk": sr, "news": sn, "total": total}
    conf = W.compute_confidence(comp, is_fund=is_fund)
    return _clamp(total), comp, conf


# ---------------- 参数化 run_backtest ----------------
def run_backtest(df, news_level=None, is_fund=False, strategy="weight",
                 extra_penalties=None, extra_bonuses=None,
                 thresholds=None, weights_override=None,
                 use_escape=False, use_aroon=False, use_mfi=False,
                 fix_buyhold=False, limit_rule=False,
                 sig_lowopen=None, sig_triple_pump=None, sig_highvol=None):
    """参数化回测；返回 (equity_curve, trade_history)
    sig_lowopen:    低开清仓阈值（如 0.03 = 低开 3% 次日开盘清仓）
    sig_triple_pump: 三拉兑现 (拉升阈值, 兑现后仓位比例) 如 (0.05, 0.5)
    sig_highvol:    高位巨量清仓 (高位距60日高点阈值, 量比阈值) 如 (0.03, 2.0)
    """
    # 应用参数覆盖（不修改全局）
    BUY_STRONG = thresholds.get("buy_strong", W.BUY_STRONG) if thresholds else W.BUY_STRONG
    BUY_WEAK = thresholds.get("buy_weak", W.BUY_WEAK) if thresholds else W.BUY_WEAK
    SELL_WEAK = thresholds.get("sell_weak", W.SELL_WEAK) if thresholds else W.SELL_WEAK
    SELL_STRONG = thresholds.get("sell_strong", W.SELL_STRONG) if thresholds else W.SELL_STRONG

    d = W.compute_indicators(df)
    d = add_candidate_indicators(d, use_escape=use_escape, use_aroon=use_aroon, use_mfi=use_mfi)
    if sig_highvol and "dd60b" not in d.columns:
        d["dd60b"] = (d["close"] / d["close"].rolling(60).max() - 1) * 100

    cash = W.INITIAL_CASH
    position = 0
    entry_price = 0.0
    entry_date = None
    entry_bar = -1
    pending_action = None
    pending_override = None  # ("sell_full"/"sell_half") 无条件信号强制动作
    equity_curve = []
    trade_history = []
    target_pct = 0.0
    last_dir = None
    prev_close = None  # 涨跌停判断用
    pump_count = 0      # 三拉兑现：累计大拉升次数
    pump_done = False   # 是否已兑现过

    def do_sell(row, i, date, open_p, ratio):
        """通用卖出执行（ratio: 1.0 全清 / 0.5 减半）"""
        nonlocal cash, position, entry_price, entry_date, entry_bar, pump_done
        if position <= 0:
            return
        sell_size = int(position * ratio)
        sell_size = (sell_size // W.LOT) * W.LOT
        if sell_size <= 0:
            return
        tax = sell_size * open_p * W.SELL_TAX if not is_fund else 0.0
        proceeds = sell_size * open_p * (1 - W.COMMISSION) - tax
        pnl = proceeds - sell_size * entry_price * (1 + W.COMMISSION)
        pnl_pct = (open_p / entry_price - 1) * 100 if entry_price else 0
        trade_history.append({
            "entry_date": str(entry_date.date()) if entry_date else "",
            "exit_date": str(date.date()), "side": "long", "size": sell_size,
            "entry_price": round(entry_price, 4), "exit_price": round(open_p, 4),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
            "holding_bars": i - entry_bar if entry_bar >= 0 else 0, "symbol": "",
        })
        cash += proceeds
        position -= sell_size
        if position == 0:
            entry_price = 0.0; entry_date = None; entry_bar = -1
        if ratio < 1.0:
            pump_done = True

    for i in range(len(d)):
        row = d.iloc[i]
        date = row["date"]
        open_p, close_p = row["open"], row["close"]
        if pd.isna(close_p) or pd.isna(open_p):
            value = cash + position * close_p if not pd.isna(close_p) else cash + position * (entry_price or 0)
            equity_curve.append({"date": str(date.date()), "value": round(value, 2)})
            prev_close = close_p
            continue
        in_eval = date >= pd.Timestamp(W.BACKTEST_START)
        indicators_ready = not pd.isna(row["ma20"]) and not pd.isna(row["rsi"])

        # 涨跌停判断（涨停不可买/跌停不可卖）：主板 ±10%，创业板/科创板 ±20%，北交所 ±30%
        if prev_close and not pd.isna(prev_close) and prev_close > 0:
            if is_fund:
                limit_pct = 0.10
            elif str(code_of(d))[0:1] in ("3", "4", "8"):  # 深创业板/北交所近似
                limit_pct = 0.30 if str(code_of(d)).startswith(("4", "8")) else 0.20
            else:
                limit_pct = 0.10
            limit_up = prev_close * (1 + limit_pct) * 0.999  # 涨停价（留 0.1% 容差）
            limit_down = prev_close * (1 - limit_pct) * 1.001
        else:
            limit_up = limit_down = None

        # ---- 0. 无条件信号检查（优先于常规信号执行）----
        if in_eval and position > 0:
            # S1 低开清仓：开盘低开超阈值 → 开盘清仓
            if sig_lowopen and prev_close and not pd.isna(prev_close) and prev_close > 0:
                if open_p < prev_close * (1 - sig_lowopen):
                    do_sell(row, i, date, open_p, 1.0)
            # S2 三拉兑现：单日涨幅 ≥ 阈值 累计 3 次 → 减仓至 hold_ratio（兑现 1-hold_ratio）
            if sig_triple_pump and position > 0 and not pump_done:
                pump_th, hold_ratio = sig_triple_pump
                if prev_close and not pd.isna(prev_close) and prev_close > 0:
                    day_ret = (close_p / prev_close - 1)
                    if day_ret >= pump_th:
                        pump_count += 1
                        if pump_count >= 3 and position > 0:
                            do_sell(row, i, date, open_p, 1.0 - hold_ratio)
            # S3 高位巨量清仓：距60日高点 < 阈值 且 量比 ≥ 阈值 → 次日开盘清仓
            if sig_highvol and position > 0:
                high_dist_th, vol_th = sig_highvol
                if not pd.isna(row.get("dd60b", np.nan)) and not pd.isna(row.get("vol_ratio", np.nan)):
                    if row["dd60b"] > -high_dist_th * 100 and row["vol_ratio"] >= vol_th:
                        pending_override = "sell_full"
            if pending_override == "sell_full" and position > 0:
                do_sell(row, i, date, open_p, 1.0)
                pending_override = None

        # ---- 1. 执行昨日待执行动作 ----
        if pending_action is not None and in_eval:
            action, amount = pending_action
            pending_action = None
            if action == "buy":
                # 涨停不可买
                if limit_rule and limit_up is not None and open_p >= limit_up:
                    pass
                else:
                    if W.POSITION_MODEL == "target":
                        target_value = amount * W.INITIAL_CASH
                        target_shares = int(target_value / (open_p * (1 + W.COMMISSION)))
                        target_shares = (target_shares // W.LOT) * W.LOT
                        add_size = target_shares - position
                        if add_size > 0:
                            cost = add_size * open_p * (1 + W.COMMISSION)
                            if cost <= cash:
                                cash -= cost
                                if position == 0:
                                    entry_price = open_p; entry_date = date; entry_bar = i
                                position += add_size
                    else:
                        if W.POSITION_MODEL == "incremental":
                            total_assets = cash + position * open_p
                            add_value = total_assets * amount
                        else:
                            target_value = amount * W.INITIAL_CASH
                            cur_value = position * open_p
                            cap_value = max(0.0, target_value - cur_value)
                            # buyhold 修复：strategy=bh 且 fix_buyhold 时绕过 CAP 上限
                            if fix_buyhold and strategy == "bh":
                                add_value = cap_value
                            else:
                                add_value = min(cap_value, W.CAP_PCT * W.INITIAL_CASH)
                        add_shares = int(add_value / (open_p * (1 + W.COMMISSION)))
                        add_shares = (add_shares // W.LOT) * W.LOT
                        add_size = min(add_shares, int(cash / (open_p * (1 + W.COMMISSION))) // W.LOT * W.LOT)
                        if add_size > 0:
                            cost = add_size * open_p * (1 + W.COMMISSION)
                            if cost <= cash:
                                cash -= cost
                                if position == 0:
                                    entry_price = open_p; entry_date = date; entry_bar = i
                                position += add_size
            elif action == "sell":
                # 跌停不可卖
                if limit_rule and limit_down is not None and open_p <= limit_down:
                    pass
                else:
                    if W.POSITION_MODEL == "target":
                        target_value = amount * W.INITIAL_CASH
                        target_shares = int(target_value / open_p)
                        target_shares = (target_shares // W.LOT) * W.LOT
                        sell_size = position - target_shares
                    else:
                        if W.POSITION_MODEL == "incremental":
                            sell_value = position * open_p * amount
                        else:
                            target_value = amount * W.INITIAL_CASH
                            cur_value = position * open_p
                            cap_value = max(0.0, cur_value - target_value)
                            sell_value = min(cap_value, W.CAP_PCT * W.INITIAL_CASH)
                        sell_shares = int(sell_value / open_p)
                        sell_shares = (sell_shares // W.LOT) * W.LOT
                        sell_size = min(sell_shares, position)
                    if sell_size > 0:
                        tax = sell_size * open_p * W.SELL_TAX if not is_fund else 0.0
                        proceeds = sell_size * open_p * (1 - W.COMMISSION) - tax
                        pnl = proceeds - sell_size * entry_price * (1 + W.COMMISSION)
                        pnl_pct = (open_p / entry_price - 1) * 100 if entry_price else 0
                        trade_history.append({
                            "entry_date": str(entry_date.date()) if entry_date else "",
                            "exit_date": str(date.date()), "side": "long", "size": sell_size,
                            "entry_price": round(entry_price, 4), "exit_price": round(open_p, 4),
                            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
                            "holding_bars": i - entry_bar if entry_bar >= 0 else 0, "symbol": "",
                        })
                        cash += proceeds
                        position -= sell_size
                        if position == 0:
                            entry_price = 0.0; entry_date = None; entry_bar = -1

        # ---- 2. 生成今日信号 ----
        if in_eval and indicators_ready:
            if strategy == "weight":
                _, comp, _conf = compute_total_score_w(row, news_level, is_fund=is_fund,
                                                       weights_override=weights_override)
                total = comp["total"]
                # 候选注入：逃顶信号扣分 / Aroon / MFI 加减分
                if extra_penalties:
                    for col, pen in extra_penalties.items():
                        if not pd.isna(row.get(col, np.nan)) and row[col] > 0:
                            total -= pen
                if extra_bonuses:
                    for col, bonus in extra_bonuses.items():
                        v = row.get(col, np.nan)
                        if pd.isna(v):
                            continue
                        if col == "aroon_osc":
                            if v >= 50: total += bonus
                            elif v <= -50: total -= bonus
                        elif col == "mfi":
                            if v >= 80: total -= bonus       # 超买减分
                            elif v <= 20: total += bonus     # 超卖加分
                        elif v > 0:
                            total += bonus
                total = _clamp(total)

                if W.POSITION_MODEL == "incremental":
                    if total >= BUY_WEAK:
                        pending_action = ("buy", W.STEP_PCT)
                    elif total < SELL_WEAK:
                        pending_action = ("sell", W.STEP_PCT)
                    else:
                        pending_action = None
                else:
                    if total >= BUY_STRONG:
                        pending_action = ("buy", 1.0)
                    elif total >= BUY_WEAK:
                        pending_action = ("buy", 0.5)
                    elif total < SELL_STRONG:
                        pending_action = ("sell", 0.0)
                    elif total < SELL_WEAK:
                        pending_action = ("sell", 0.5)
                    else:
                        pending_action = None
            elif strategy == "s1s7":
                sig = W.old_s1s7_signal(row, is_fund=is_fund)
                if sig == 1: pending_action = ("buy", 1.0)
                elif sig == -1: pending_action = ("sell", 0.0)
                else: pending_action = None
            else:  # buy-and-hold
                if position == 0:
                    pending_action = ("buy", 1.0)
                else:
                    pending_action = None

        # ---- 3. 记录权益 ----
        if in_eval:
            value = cash + position * close_p
            equity_curve.append({"date": str(date.date()), "value": round(value, 2)})
        prev_close = close_p

    # 期末强制平仓
    if position > 0 and equity_curve:
        last = d.iloc[-1]
        price = last["close"]
        tax = position * price * W.SELL_TAX if not is_fund else 0.0
        proceeds = position * price * (1 - W.COMMISSION) - tax
        pnl = proceeds - position * entry_price * (1 + W.COMMISSION)
        pnl_pct = (price / entry_price - 1) * 100 if entry_price else 0
        trade_history.append({
            "entry_date": str(entry_date.date()) if entry_date else "",
            "exit_date": str(last["date"].date()), "side": "long", "size": position,
            "entry_price": round(entry_price, 4), "exit_price": round(price, 4),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
            "holding_bars": len(d) - 1 - entry_bar if entry_bar >= 0 else 0, "symbol": "",
        })
        cash += proceeds
        position = 0

    return equity_curve, trade_history


# 用模块级变量记录当前 code（涨跌停判断用）
_code_holder = {"code": "000000"}
def code_of(d):
    return _code_holder["code"]

def _clamp(x):
    return max(0.0, min(100.0, float(x)))


# ---------------- 组合跑批 ----------------
def run_pool(codes, data_dir, name, weights_override=None, thresholds=None,
             extra_penalties=None, extra_bonuses=None,
             use_escape=False, use_aroon=False, use_mfi=False,
             fix_buyhold=False, limit_rule=False, only_weight=True,
             sig_lowopen=None, sig_triple_pump=None, sig_highvol=None):
    """跑一个标的池，返回 (combo_summary, per_symbol, combined_equity)"""
    from collections import defaultdict
    combined_equity = defaultdict(list)
    all_trades = []
    results = {}
    for code in codes:
        _code_holder["code"] = code
        f = os.path.join(data_dir, f"{code}.csv")
        if not os.path.exists(f):
            continue
        try:
            df = pd.read_csv(f)
            df["date"] = df["date"].astype(str).str.replace(r"(\d{4})(\d{2})(\d{2})", r"\1-\2-\3", regex=True)
            df["date"] = pd.to_datetime(df["date"])
            for c in ["open", "high", "low", "close"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
            if len(df) < 250:
                continue
            is_fund = code.startswith(("sh5", "sz1"))
            eq_w, tr_w = run_backtest(df, None, is_fund=is_fund, strategy="weight",
                                      extra_penalties=extra_penalties, extra_bonuses=extra_bonuses,
                                      thresholds=thresholds, weights_override=weights_override,
                                      use_escape=use_escape, use_aroon=use_aroon, use_mfi=use_mfi,
                                      fix_buyhold=fix_buyhold, limit_rule=limit_rule,
                                      sig_lowopen=sig_lowopen, sig_triple_pump=sig_triple_pump,
                                      sig_highvol=sig_highvol)
            if not eq_w:
                continue
            sum_w = W.compute_summary(eq_w, tr_w)
            base = eq_w[0]["value"]
            norm = [{"date": p["date"], "value": round(100 * p["value"] / base, 4)} for p in eq_w]
            for t in tr_w:
                t["symbol"] = code
            all_trades.extend(tr_w)
            results[code] = sum_w
            for p in norm:
                combined_equity[p["date"]].append(p["value"])
        except Exception as e:
            results[code] = {"error": str(e)[:80]}
    combo = [{"date": dt, "value": round(sum(v) / len(v), 4)}
             for dt, v in sorted(combined_equity.items())]
    cs = W.compute_summary(combo, all_trades) if combo else {}
    return cs, results, combo


if __name__ == "__main__":
    # 快速冒烟测试
    subs = (BASE / "subsample_1000.txt").read_text(encoding="utf-8").splitlines()
    df = pd.read_csv(BASE / "data_full" / f"{subs[0]}.csv")
    df["date"] = pd.to_datetime(df["date"])
    eq, tr = run_backtest(df, None, is_fund=False, strategy="weight")
    print(f"冒烟测试: {subs[0]} equity={len(eq)} trades={len(tr)}")
