# -*- coding: utf-8 -*-
"""
妖股/主力操盘指标族评估回测（多领域 × ≥3 标的）
================================================
来源：2026-08-12 剪藏 10 篇指标文（指标大家园×4 / 指标源码选集 / 精选指标公式大全×2 /
      丰过林梢波段雷达 / 大吉底信号 / 股董赢家中阳起爆）
共性可量化信号 → 3 个补丁候选（±10，对齐 v4 量价三件套口径）：

  C1 筹码因子   ：WINNER 近似 = close > 60日量加权成本 → 获利盘过半 +10（体系无筹码类，唯一新维度）
  C2 游资评分   ：8 项多因子模板（MA5>MA10 / MA20>MA60 / KDJ.J>K / DIF>DEA / MACD>0 /
                   V>MA60 / WINNER>50% / 涨幅>3%，每项10分）≥60 分共振 +10
  C3 低位放量启动：CROSS(C,MA55) + 前日涨幅≥3% + 量≥1.5×5日均量 + 低位门控(距60日高>15%) → +10

领域分组（5 领域 × 4-5 只，data/ 与 data_tmp/ 双源）：
  半导体/新能源/消费/金融/光模块PCB
执行：T日收盘信号 + T+1 开盘执行，target_cap 仓位模型，领域内等权组合
输出：indicator_eval_results.json + 控制台对比表
"""
import numpy as np
import pandas as pd
import json, os
from datetime import datetime

from weight_system_backtest import (
    INITIAL_CASH, COMMISSION, SELL_TAX, LOT,
    BACKTEST_START, BACKTEST_END,
    BUY_STRONG, BUY_WEAK, SELL_WEAK, SELL_STRONG,
    POSITION_MODEL, STEP_PCT, CAP_PCT,
    load_data, compute_indicators, compute_total_score, compute_summary,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DOMAINS = {
    "半导体":  ["688981", "603986", "002185", "605358"],
    "新能源":  ["300750", "002594", "300274", "600438", "601012"],
    "消费":    ["600519", "000858", "000651", "000333", "600887"],
    "金融":    ["601398", "601318", "600030", "600036", "601601"],
    "光模块PCB": ["300502", "300308", "002463", "300476", "600183"],
}


def load_any(code: str) -> pd.DataFrame:
    for sub in ("data", "data_tmp"):
        p = os.path.join(BASE_DIR, sub, f"{code}.csv")
        if os.path.exists(p):
            return load_data(code.replace("", "") if False else code) if False else _load(p)
    raise FileNotFoundError(code)


def _load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["date"] = df["date"].astype(str).str.replace(r"(\d{4})(\d{2})(\d{2})", r"\1-\2-\3", regex=True)
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    return df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 补丁指标（向量化，与主引擎 compute_indicators 衔接）
# ---------------------------------------------------------------------------
def compute_patch_indicators(d: pd.DataFrame) -> pd.DataFrame:
    x = d.copy()
    x["ma34"] = x["close"].rolling(34).mean()
    x["ma55"] = x["close"].rolling(55).mean()
    # C1 筹码近似：60 日量加权成本
    vol = x["volume"].fillna(0)
    x["vwap60"] = (x["close"] * vol).rolling(60).sum() / vol.rolling(60).sum().replace(0, np.nan)
    x["winner_ok"] = x["close"] > x["vwap60"]
    # C3 低位放量启动
    x["vol_ma5"] = x["volume"].rolling(5).mean()
    x["prev_chg"] = x["close"].pct_change(1) * 100
    x["high60"] = x["close"].rolling(60).max()
    x["dd60p"] = (x["close"] / x["high60"] - 1) * 100
    x["cross_ma55"] = (x["close"] > x["ma55"]) & (x["close"].shift(1) <= x["ma55"].shift(1))
    x["low_start"] = (
        x["cross_ma55"] & (x["prev_chg"].shift(1) >= 3.0)
        & (x["volume"] >= 1.5 * x["vol_ma5"])
        & (x["dd60p"] < -15.0)
    )
    # C2 游资评分（8 项模板）
    ma5, ma10, ma20, ma60 = x["ma5"], x["ma10"], x["ma20"], x["close"].rolling(60).mean()
    s = 0
    s = s + np.where(ma5 > ma10, 10, 0)
    s = s + np.where(ma20 > ma60, 10, 0)
    s = s + np.where(x["j"] > x["k"], 10, 0)
    s = s + np.where(x["dif"] > x["dea"], 10, 0)
    s = s + np.where(x["macd_hist"] > 0, 10, 0)
    s = s + np.where(x["volume"] > x["volume"].rolling(60).mean(), 10, 0)
    s = s + np.where(x["winner_ok"], 10, 0)
    s = s + np.where(x["pct_chg"] > 3.0, 10, 0)
    x["score8"] = s
    x["score8_ok"] = x["score8"] >= 60
    return x


# ---------------------------------------------------------------------------
# 回测（主引擎逻辑 + 补丁开关）
# ---------------------------------------------------------------------------
def run_backtest_patch(df, news_level, is_fund=False, use_c1=False, use_c2=False, use_c3=False):
    d = compute_patch_indicators(compute_indicators(df))
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
                    else:
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
                    else:
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
                        "exit_date": str(date.date()), "side": "long", "size": sell_size,
                        "entry_price": round(entry_price, 4), "exit_price": round(open_p, 4),
                        "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
                        "holding_bars": i - entry_bar if entry_bar >= 0 else 0, "symbol": "",
                    })
                    cash += proceeds
                    position -= sell_size
                    if position == 0:
                        entry_price = 0.0
                        entry_date = None
                        entry_bar = -1

        if in_eval and indicators_ready:
            _, comp, _conf = compute_total_score(row, news_level, is_fund=is_fund)
            total = comp["total"]
            # ---- 补丁（±10，对齐 v4 量价三件套）----
            if use_c1 and bool(row["winner_ok"]):
                total += 10
            if use_c2 and bool(row["score8_ok"]):
                total += 10
            if use_c3 and bool(row["low_start"]):
                total += 10
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
            if pending_action is not None:
                cur_dir = "buy" if pending_action[0] == "buy" else "sell"
                if last_dir is None:
                    last_dir = cur_dir
                elif cur_dir == last_dir:
                    pending_action = None
                else:
                    last_dir = cur_dir

        if in_eval:
            value = cash + position * close_p
            equity_curve.append({"date": str(date.date()), "value": round(value, 2)})

    if position > 0 and equity_curve:
        last = d.iloc[-1]
        price = last["close"]
        tax = position * price * SELL_TAX if not is_fund else 0.0
        proceeds = position * price * (1 - COMMISSION) - tax
        pnl = proceeds - position * entry_price * (1 + COMMISSION)
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


# ---------------------------------------------------------------------------
# 实验矩阵
# ---------------------------------------------------------------------------
EXPERIMENTS = [
    ("BASE",  dict(use_c1=False, use_c2=False, use_c3=False)),
    ("C1筹码", dict(use_c1=True)),
    ("C2游资", dict(use_c2=True)),
    ("C3启动", dict(use_c3=True)),
    ("C1+C2", dict(use_c1=True, use_c2=True)),
    ("ALL",   dict(use_c1=True, use_c2=True, use_c3=True)),
]


def run_domain(domain, codes, use_c1, use_c2, use_c3):
    combined_equity = {}
    all_trades = []
    for code in codes:
        df = load_any(code)
        typ = "基金" if code.startswith(("0", "1")) and len(code) == 6 and code[0] in "012" else "股票"
        is_fund = False
        eq, tr = run_backtest_patch(df, None, is_fund, use_c1=use_c1, use_c2=use_c2, use_c3=use_c3)
        norm = []
        if eq:
            base = eq[0]["value"]
            for p in eq:
                norm.append({"date": p["date"], "value": round(100 * p["value"] / base, 4)})
        all_trades.extend(tr)
        for p in norm:
            combined_equity.setdefault(p["date"], []).append(p["value"])
    combo = []
    for date in sorted(combined_equity.keys()):
        vals = combined_equity[date]
        combo.append({"date": date, "value": round(sum(vals) / len(vals), 4)})
    summary = compute_summary(combo, all_trades)
    days = max(len(combo) - 1, 1)
    wins = sum(1 for t in all_trades if t["pnl"] > 0)
    summary["win_rate_pct"] = round(wins / len(all_trades) * 100, 1) if all_trades else 0
    summary["total_trades"] = len(all_trades)
    return summary


def main():
    print("=" * 104)
    print("妖股/主力操盘指标族评估  |  窗口", BACKTEST_START, "~", BACKTEST_END,
          "|  5 领域 × 4-5 标的  |  补丁 ±10（v4 口径）")
    print("=" * 104)
    results = {}
    for dom, codes in DOMAINS.items():
        results[dom] = {}
        print(f"\n[{dom}] {len(codes)} 只: {','.join(codes)}")
        base_s = None
        for name, cfg in EXPERIMENTS:
            s = run_domain(dom, codes, cfg.get("use_c1", False), cfg.get("use_c2", False), cfg.get("use_c3", False))
            results[dom][name] = s
            if base_s is None:
                base_s = s
                delta = 0.0
            else:
                delta = s["total_return_pct"] - base_s["total_return_pct"]
            print(f"  {name:<8} 收益 {s['total_return_pct']:>8.2f}% | 回撤 {s['max_drawdown_pct']:>5.2f}% "
                  f"| 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']:>4.1f}% | 笔数 {s['total_trades']:>3} "
                  f"| Δ{s['total_return_pct'] - base_s['total_return_pct']:+.2f}pct")

    # 汇总表（全领域平均 Δ）
    print("\n" + "=" * 104)
    print(f"{'实验':<10}" + "".join(f"{d:>14}" for d in DOMAINS) + f"{'平均Δ':>10}")
    print("-" * 104)
    for name, _ in EXPERIMENTS:
        row = ""
        deltas = []
        for dom in DOMAINS:
            base = results[dom]["BASE"]["total_return_pct"]
            cur = results[dom][name]["total_return_pct"]
            d = cur - base
            deltas.append(d)
            row += f"{cur:>12.2f}%({d:+.1f})"
        print(f"{name:<10}{row}{sum(deltas)/len(deltas):>+9.2f}pct")

    out = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "window": {"start": BACKTEST_START, "end": BACKTEST_END},
        "method": "妖股/主力操盘指标族补丁评估：C1筹码(WINNER近似)/C2游资8项评分/C3低位放量启动，±10 补丁式",
        "domains": results,
    }
    with open("indicator_eval_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n已生成: indicator_eval_results.json")


if __name__ == "__main__":
    main()
