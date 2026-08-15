# -*- coding: utf-8 -*-
"""
赛马指数（60日均线 + OBV）情绪门禁验证实验
=========================================
来源：鳄鱼派投资档案 2026-08-12 NO.643（方法论重申：8/7、8/10、8/11 三次一致）
赛马 = 纯技术面筛选：头等马 = 站上60日均线 + OBV强势；黑马 = 60日线下但OBV强势
作者前提："市场情绪好的时候，技术分析胜率大得多" → 本实验验证其作为
【情绪门控】接入权重系统的增量价值：非赛马状态日抑制买入信号（防守保留）。

实验矩阵：
  BASE      无门禁（复现 v1.4 基线，sanity）
  G50       门禁：MA60占比≥50% 且 OBV强势占比≥50% 才开门（AND）
  G60       门禁：双占比阈值 60%（更严格）
  G60_OR    门禁：双占比任一 ≥60% 即开门（OR，宽松 sanity）
  INV60     反向门禁：赛马状态日反而抑制买入（反证 sanity，应明显变差）

口径：OBV 强势 = OBV > 自身20日均线（推荐口径A）
执行：T日收盘信号 + T+1 开盘执行（沿用主引擎）；门禁仅抑制 buy，sell 保留
输出：sailhorse_results.json + 控制台对比表
"""
import numpy as np
import pandas as pd
import json
from datetime import datetime

from weight_system_backtest import (
    UNIVERSE, INITIAL_CASH, COMMISSION, SELL_TAX, LOT,
    BACKTEST_START, BACKTEST_END,
    BUY_STRONG, BUY_WEAK, SELL_WEAK, SELL_STRONG,
    POSITION_MODEL, STEP_PCT, CAP_PCT,
    USE_DEADBAND, DEADBAND_LO, DEADBAND_HI, USE_REVERSAL_ONLY,
    load_data, compute_indicators, compute_total_score, compute_summary,
)

# ---------------------------------------------------------------------------
# 1. 赛马指标与市场状态
# ---------------------------------------------------------------------------
def compute_sailhorse(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["ma60"] = d["close"].rolling(60).mean()
    sign = np.sign(d["close"].diff()).fillna(0)          # 涨+1 / 跌-1 / 平0
    d["obv"] = (sign * d["volume"].fillna(0)).cumsum()   # 标准 OBV
    d["obv_ma20"] = d["obv"].rolling(20).mean()
    d["above_ma60"] = d["close"] > d["ma60"]
    d["obv_strong"] = d["obv"] > d["obv_ma20"]           # 口径A：OBV 站上自身20日线
    return d


def build_market_state(threshold: float = 0.5, logic: str = "AND"):
    """逐日统计全池 above_ma60 / obv_strong 占比 → {date_str: bool}"""
    frames = []
    for code, name, typ, market, news_level in UNIVERSE:
        d = compute_sailhorse(load_data(code))
        frames.append(d[["date", "above_ma60", "obv_strong"]])
    all_d = pd.concat(frames)
    daily = all_d.groupby("date").agg(
        ma60_share=("above_ma60", "mean"),
        obv_share=("obv_strong", "mean"),
        n=("above_ma60", "size"),
    )
    if logic == "AND":
        daily["state"] = (daily["ma60_share"] >= threshold) & (daily["obv_share"] >= threshold)
    else:
        daily["state"] = (daily["ma60_share"] >= threshold) | (daily["obv_share"] >= threshold)
    # key 统一为 "YYYY-MM-DD" 字符串（groupby index 为 Timestamp，与回测内 str(date.date()) 对齐）
    return {str(k.date()): bool(v) for k, v in daily["state"].items()}


# ---------------------------------------------------------------------------
# 2. 回测（复制主引擎 run_backtest，插入赛马门禁）
# ---------------------------------------------------------------------------
def run_backtest_gated(df, news_level, is_fund=False,
                       gate_mode="off", market_state=None):
    """gate_mode: off=基线 / gate=非赛马日抑制买入 / invert=反向(sanity)"""
    d = compute_indicators(df)
    cash = INITIAL_CASH
    position = 0
    entry_price = 0.0
    entry_date = None
    entry_bar = -1
    pending_action = None
    equity_curve = []
    trade_history = []
    last_dir = None

    for i in range(len(d)):
        row = d.iloc[i]
        date = row["date"]
        open_p, close_p = row["open"], row["close"]
        if pd.isna(close_p) or pd.isna(open_p):
            value = cash + position * close_p if not pd.isna(close_p) else cash + position * (entry_price or 0)
            equity_curve.append({"date": str(date.date()), "value": round(value, 2)})
            continue
        in_eval = date >= pd.Timestamp(BACKTEST_START)
        indicators_ready = not pd.isna(row["ma20"]) and not pd.isna(row["rsi"])

        # ---- 1. 执行昨日待执行动作（T+1 开盘）----
        if pending_action is not None and in_eval:
            action, amount = pending_action
            pending_action = None
            if action == "buy":
                if POSITION_MODEL == "target":
                    target_value = amount * INITIAL_CASH
                    target_shares = int(target_value / (open_p * (1 + COMMISSION)))
                    target_shares = (target_shares // LOT) * LOT
                    add_size = target_shares - position
                    if add_size > 0:
                        cost = add_size * open_p * (1 + COMMISSION)
                        if cost <= cash:
                            cash -= cost
                            if position == 0:
                                entry_price = open_p
                                entry_date = date
                                entry_bar = i
                            position += add_size
                else:
                    if POSITION_MODEL == "incremental":
                        total_assets = cash + position * open_p
                        add_value = total_assets * amount
                    else:  # target_cap
                        target_value = amount * INITIAL_CASH
                        cur_value = position * open_p
                        cap_value = max(0.0, target_value - cur_value)
                        add_value = min(cap_value, CAP_PCT * INITIAL_CASH)
                    add_shares = int(add_value / (open_p * (1 + COMMISSION)))
                    add_shares = (add_shares // LOT) * LOT
                    add_size = min(add_shares, int(cash / (open_p * (1 + COMMISSION))) // LOT * LOT)
                    if add_size > 0:
                        cost = add_size * open_p * (1 + COMMISSION)
                        if cost <= cash:
                            cash -= cost
                            if position == 0:
                                entry_price = open_p
                                entry_date = date
                                entry_bar = i
                            position += add_size
            elif action == "sell":
                if POSITION_MODEL == "target":
                    target_value = amount * INITIAL_CASH
                    target_shares = int(target_value / open_p)
                    target_shares = (target_shares // LOT) * LOT
                    sell_size = position - target_shares
                else:
                    if POSITION_MODEL == "incremental":
                        sell_value = position * open_p * amount
                    else:  # target_cap
                        target_value = amount * INITIAL_CASH
                        cur_value = position * open_p
                        cap_value = max(0.0, cur_value - target_value)
                        sell_value = min(cap_value, CAP_PCT * INITIAL_CASH)
                    sell_shares = int(sell_value / open_p)
                    sell_shares = (sell_shares // LOT) * LOT
                    sell_size = min(sell_shares, position)
                if sell_size > 0:
                    tax = sell_size * open_p * SELL_TAX if not is_fund else 0.0
                    proceeds = sell_size * open_p * (1 - COMMISSION) - tax
                    pnl = proceeds - sell_size * entry_price * (1 + COMMISSION)
                    pnl_pct = (open_p / entry_price - 1) * 100 if entry_price else 0
                    trade_history.append({
                        "entry_date": str(entry_date.date()) if entry_date else "",
                        "exit_date": str(date.date()),
                        "side": "long",
                        "size": sell_size,
                        "entry_price": round(entry_price, 4),
                        "exit_price": round(open_p, 4),
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "holding_bars": i - entry_bar if entry_bar >= 0 else 0,
                        "symbol": "",
                    })
                    cash += proceeds
                    position -= sell_size
                    if position == 0:
                        entry_price = 0.0
                        entry_date = None
                        entry_bar = -1

        # ---- 2. 生成今日信号（收盘后确认，明日执行）----
        if in_eval and indicators_ready:
            _, comp, _conf = compute_total_score(row, news_level, is_fund=is_fund)
            total = comp["total"]
            if POSITION_MODEL == "incremental":
                if total >= BUY_WEAK:
                    pending_action = ("buy", STEP_PCT)
                elif total < SELL_WEAK:
                    pending_action = ("sell", STEP_PCT)
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
            # ---- 赛马门禁（本实验新增）----
            if gate_mode != "off" and pending_action is not None and pending_action[0] == "buy":
                st = market_state.get(str(date.date())) if market_state else None
                if st is not None:
                    if gate_mode == "gate" and not st:
                        pending_action = None          # 非赛马日：抑制买入
                    elif gate_mode == "invert" and st:
                        pending_action = None          # 反向：赛马日反而抑制（sanity）
            # v1.3 死区/反转（保持与主引擎一致）
            if USE_DEADBAND and DEADBAND_LO <= total < DEADBAND_HI:
                pending_action = None
            if USE_REVERSAL_ONLY and pending_action is not None:
                cur_dir = "buy" if pending_action[0] == "buy" else "sell"
                if last_dir is None:
                    last_dir = cur_dir
                elif cur_dir == last_dir:
                    pending_action = None
                else:
                    last_dir = cur_dir

        # ---- 3. 记录权益（收盘市值）----
        if in_eval:
            value = cash + position * close_p
            equity_curve.append({"date": str(date.date()), "value": round(value, 2)})

    # ---- 期末强制平仓 ----
    if position > 0 and equity_curve:
        last = d.iloc[-1]
        price = last["close"]
        tax = position * price * SELL_TAX if not is_fund else 0.0
        proceeds = position * price * (1 - COMMISSION) - tax
        pnl = proceeds - position * entry_price * (1 + COMMISSION)
        pnl_pct = (price / entry_price - 1) * 100 if entry_price else 0
        trade_history.append({
            "entry_date": str(entry_date.date()) if entry_date else "",
            "exit_date": str(last["date"].date()),
            "side": "long",
            "size": position,
            "entry_price": round(entry_price, 4),
            "exit_price": round(price, 4),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "holding_bars": len(d) - 1 - entry_bar if entry_bar >= 0 else 0,
            "symbol": "",
        })
        cash += proceeds
        position = 0

    return equity_curve, trade_history


# ---------------------------------------------------------------------------
# 3. 实验矩阵
# ---------------------------------------------------------------------------
EXPERIMENTS = [
    ("BASE",   dict(gate_mode="off")),
    ("G50",    dict(gate_mode="gate", threshold=0.50, logic="AND")),
    ("G60",    dict(gate_mode="gate", threshold=0.60, logic="AND")),
    ("G60_OR", dict(gate_mode="gate", threshold=0.60, logic="OR")),
    ("INV60",  dict(gate_mode="invert", threshold=0.60, logic="AND")),
]


def run_experiment(gate_mode, threshold=None, logic=None):
    market_state = None
    if gate_mode != "off":
        market_state = build_market_state(threshold=threshold, logic=logic)
    combined_equity = {}
    all_trades = []
    gate_stats = {"open_days": 0, "closed_days": 0} if market_state else None
    for code, name, typ, market, news_level in UNIVERSE:
        df = load_data(code)
        is_fund = typ == "基金"
        eq, tr = run_backtest_gated(df, news_level, is_fund, gate_mode=gate_mode, market_state=market_state)
        norm = []
        if eq:
            base = eq[0]["value"]
            for p in eq:
                norm.append({"date": p["date"], "value": round(100 * p["value"] / base, 4)})
        for t in tr:
            t["symbol"] = code
            t["symbol_name"] = name
            t["display_symbol"] = f"{name} ({code})"
        all_trades.extend(tr)
        for p in norm:
            combined_equity.setdefault(p["date"], []).append(p["value"])
    if gate_stats is not None:
        for v in market_state.values():
            gate_stats["open_days" if v else "closed_days"] += 1
    combo = []
    for date in sorted(combined_equity.keys()):
        vals = combined_equity[date]
        combo.append({"date": date, "value": round(sum(vals) / len(vals), 4)})
    summary = compute_summary(combo, all_trades)
    # 组合口径胜率/换手（按 v4 报告口径：胜率=trades 盈利占比；换手=trades 数/交易日）
    days = max(len(combo) - 1, 1)
    wins = sum(1 for t in all_trades if t["pnl"] > 0)
    summary["win_rate_pct"] = round(wins / len(all_trades) * 100, 1) if all_trades else 0
    summary["total_trades"] = len(all_trades)
    summary["turnover"] = round(len(all_trades) / days * 100, 3)  # 笔/百交易日
    return {"summary": summary, "gate_stats": gate_stats, "combo_tail": combo[-1]["value"] if combo else None}


def main():
    print("=" * 100)
    print("赛马指数（60日均线 + OBV）情绪门禁验证  |  窗口", BACKTEST_START, "~", BACKTEST_END,
          "|  池", len(UNIVERSE), "只  |  仓位模型", POSITION_MODEL)
    print("=" * 100)
    results = {}
    for name, cfg in EXPERIMENTS:
        gate_mode = cfg["gate_mode"]
        label = name
        if gate_mode != "off":
            label += f" (阈{cfg['threshold']:.0%},{cfg['logic']})"
        r = run_experiment(gate_mode, cfg.get("threshold"), cfg.get("logic"))
        results[name] = r
        s = r["summary"]
        gs = r["gate_stats"]
        print(f"\n[{label}]")
        print(f"  总收益 {s['total_return_pct']:>8.2f}% | 年化 {s['annual_return_pct']:>7.2f}% "
              f"| 回撤 {s['max_drawdown_pct']:>5.2f}% | 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% "
              f"| 笔数 {s['total_trades']} | 换手 {s['turnover']}‰")
        if gs:
            print(f"  门禁统计: 开 {gs['open_days']} 日 / 关 {gs['closed_days']} 日 "
                  f"(开占比 {gs['open_days']/(gs['open_days']+gs['closed_days']):.1%})")

    # ---- 汇总对比 ----
    base = results["BASE"]["summary"]
    print("\n" + "=" * 100)
    print(f"{'实验':<10}{'总收益':>10}{'回撤':>8}{'夏普':>8}{'胜率':>8}{'笔数':>7}{'换手‰':>8}{'收益Δ':>9}")
    print("-" * 100)
    for name, r in results.items():
        s = r["summary"]
        delta = s["total_return_pct"] - base["total_return_pct"]
        print(f"{name:<10}{s['total_return_pct']:>9.2f}%{s['max_drawdown_pct']:>7.2f}%"
              f"{s['sharpe']:>8.3f}{s['win_rate_pct']:>7.1f}%{s['total_trades']:>7}"
              f"{s['turnover']:>8.3f}{delta:>+8.2f}pct")

    out = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "window": {"start": BACKTEST_START, "end": BACKTEST_END},
        "method": "赛马指数情绪门禁：MA60占比+OBV强势占比（OBV>OBV_MA20），非赛马日抑制买入、保留卖出",
        "experiments": results,
    }
    with open("sailhorse_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n已生成: sailhorse_results.json")


if __name__ == "__main__":
    main()
