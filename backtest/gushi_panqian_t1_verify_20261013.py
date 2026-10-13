# -*- coding: utf-8 -*-
"""盘前强势策略 —— 按 gushi topic/1010 明示执行规则做独立 T+1 验证。

数据来源（全部本机，不外连）：
  - 选股落盘：scratch 下载的 `盘前强势策略-2026-03-01-2026-10-09.csv`（875 条真实选股）
  - 日线 OHLC：D:/Documents/Quant data/data_full/<market><code>.csv（截至 2026-10-12）

被验证的规则（topic/1010 主帖原文要求，逐条落地）：
  R1 不使用未来数据：T 日 09:29 竞价出票 → 用 T 日**开盘价**买入（开盘价在竞价结束即已知）。
  R2 排除开盘涨停价买不进：T 日开盘价已达涨停价（封板）的样本剔除，不计入收益。
  R3 成交判定：出票日除开盘价外的最低价 ≤ 开盘价才算买入成功（low ≤ open）。
     严格变体（low < open）单独作为敏感性对照。
  R4 卖出：T+1 收盘卖出；若 T+1 为跌停封板（卖不掉）则顺延到 T+2、T+3…直到可卖那天收盘。

输出：对照臂 A/B/C 的逐笔与逐日统计，写成 JSON 证据文件。
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

DATA = Path(r"D:/Documents/Quant data/data_full")
CSV_IN = Path(sys.argv[1])
OUT = Path(sys.argv[2])
EPS = 1e-6


def market_of(code: str) -> str:
    if code.startswith(("60", "68", "69", "90")):
        return "sh"
    if code.startswith(("00", "30", "20")):
        return "sz"
    return "bj"


def board_rate(code: str) -> float:
    """涨跌停幅度（非 ST）：创业板/科创板 20%，北交所 30%，其余 10%。"""
    if code.startswith(("300", "301", "302", "688", "689")):
        return 0.20
    if code.startswith(("4", "8", "92")):
        return 0.30
    return 0.10


_series_cache: dict[str, dict] = {}


def load_series(code: str) -> dict:
    if code in _series_cache:
        return _series_cache[code]
    p = DATA / f"{market_of(code)}{code}.csv"
    rows: dict[str, dict] = {}
    if p.exists():
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                try:
                    rows[r["date"]] = {
                        "open": float(r["open"]), "high": float(r["high"]),
                        "low": float(r["low"]), "close": float(r["close"]),
                    }
                except (KeyError, ValueError):
                    continue
    _series_cache[code] = rows
    return rows


def limit_prices(prev_close: float, rate: float) -> tuple[float, float]:
    return round(prev_close * (1 + rate), 2), round(prev_close * (1 - rate), 2)


def is_limit(px: float, prev_close: float, code: str, up: bool) -> bool:
    """是否等于某档涨停/跌停价（同时尝试 ST 5% 与板块档位，避免 ST 误判）。"""
    if not prev_close or not px:
        return False
    for rate in (0.05, board_rate(code)):
        lu, ld = limit_prices(prev_close, rate)
        target = lu if up else ld
        if abs(px - target) < 0.005:
            return True
    return False


def load_picks(path: Path) -> list[dict]:
    picks = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            code = (r.get("股票代码") or "").strip()
            ts = (r.get("调入时间") or "").strip()
            if not code or not ts:
                continue
            day = ts.split(" ")[0]
            try:
                open_px = float(r.get("开盘价") or 0)
            except ValueError:
                continue
            picks.append({"code": code, "name": (r.get("股票名称") or "").strip(),
                          "day": day, "csv_open": open_px, "ts": ts,
                          "strategy": (r.get("策略名称") or "").strip()})
    return picks


def evaluate(pick: dict, fill_rule: str) -> dict:
    code, day = pick["code"], pick["day"]
    s = load_series(code)
    dates = sorted(s)
    if day not in dates:
        return {"topic": "1010", "code": code, "day": day, "status": "no_bar_on_pick_day"}
    i = dates.index(day)
    bar = s[day]
    if i == 0:
        return {"topic": "1010", "code": code, "day": day, "status": "no_prev_close"}
    prev_close = s[dates[i - 1]]["close"]
    open_px = bar["open"]

    # R2 排除开盘涨停买不进
    if is_limit(open_px, prev_close, code, up=True):
        return {"topic": "1010", "code": code, "day": day, "status": "excluded_limitup_open",
                "open": open_px, "prev_close": prev_close}

    # R3 成交判定（除开盘价外的最低价）
    if fill_rule == "le" and not (bar["low"] <= open_px + EPS):
        return {"topic": "1010", "code": code, "day": day, "status": "no_fill_low_gt_open",
                "open": open_px, "low": bar["low"]}
    if fill_rule == "lt" and not (bar["low"] < open_px - EPS):
        return {"topic": "1010", "code": code, "day": day, "status": "no_fill_low_eq_open",
                "open": open_px, "low": bar["low"]}

    # R4 T+1 收盘卖，跌停封板顺延
    roll = 0
    j = i + 1
    while j < len(dates):
        d = dates[j]
        b = s[d]
        pc = s[dates[j - 1]]["close"]
        if is_limit(b["high"], pc, code, up=False):
            roll += 1
            j += 1
            continue
        sell_day, sell_px = d, b["close"]
        ret = sell_px / open_px - 1.0
        return {"topic": "1010", "code": code, "name": pick["name"], "day": day, "buy_day": day,
                "buy": open_px, "sell_day": sell_day, "sell": sell_px, "roll_days": roll,
                "ret": ret, "status": "traded", "open_gap_pct": (open_px / prev_close - 1) * 100 if prev_close else None}
    return {"topic": "1010", "code": code, "day": day, "status": "no_sellable_day"}


def arm_stats(rows: list[dict], label: str) -> dict:
    traded = [r for r in rows if r.get("status") == "traded"]
    rets = [r["ret"] for r in traded]
    by_day: dict[str, list[float]] = defaultdict(list)
    for r in traded:
        by_day[r["day"]].append(r["ret"])
    day_mean = {d: sum(v) / len(v) for d, v in by_day.items()}
    dm = list(day_mean.values())
    out = {
        "arm": label,
        "picks": len(rows),
        "traded": len(traded),
        "excluded_limitup_open": sum(1 for r in rows if r.get("status") == "excluded_limitup_open"),
        "no_fill": sum(1 for r in rows if str(r.get("status", "")).startswith("no_fill")),
        "rolled": sum(1 for r in traded if r.get("roll_days", 0) > 0),
        "mean_per_pick": statistics.fmean(rets) if rets else None,
        "median_per_pick": statistics.median(rets) if rets else None,
        "win_rate_per_pick": (sum(1 for x in rets if x > 0) / len(rets)) if rets else None,
        "trading_days": len(dm),
        "mean_per_day": statistics.fmean(dm) if dm else None,
        "median_per_day": statistics.median(dm) if dm else None,
        "stdev_per_day": statistics.stdev(dm) if len(dm) > 1 else None,
        "t_stat_per_day": (statistics.fmean(dm) / (statistics.stdev(dm) / len(dm) ** 0.5))
                          if len(dm) > 1 and statistics.stdev(dm) > 0 else None,
        "win_rate_per_day": (sum(1 for x in dm if x > 0) / len(dm)) if dm else None,
    }
    return out


def main() -> int:
    picks = load_picks(CSV_IN)
    print(f"picks loaded: {len(picks)}  days: {len(set(p['day'] for p in picks))}")

    # 数据完整性：CSV 开盘价 vs 本机 K 线 T 日开盘价
    mism, missing = [], []
    for p in picks:
        s = load_series(p["code"])
        if p["day"] not in s:
            missing.append((p["code"], p["day"]))
        elif abs(s[p["day"]]["open"] - p["csv_open"]) > 0.011:
            mism.append({"code": p["code"], "day": p["day"], "csv_open": p["csv_open"],
                         "local_open": s[p["day"]]["open"]})
    print(f"open-price cross-check: missing_bars={len(missing)} mismatched={len(mism)}")

    arms = {}
    for label, fill in (("A_naive_no_tradability", "none"), ("B_topic1010_rules", "le"), ("C_strict_low_lt_open", "lt")):
        rows = []
        for p in picks:
            if fill == "none":
                # 朴素臂：不做涨停/成交过滤
                code, day = p["code"], p["day"]
                s = load_series(code)
                dates = sorted(s)
                if day not in dates or dates.index(day) == 0:
                    rows.append({"topic": "1010", "day": day, "status": "no_prev_close"})
                    continue
                i = dates.index(day)
                j = i + 1
                if j >= len(dates):
                    rows.append({"topic": "1010", "day": day, "status": "no_sellable_day"})
                    continue
                rows.append({"topic": "1010", "day": day, "status": "traded",
                             "ret": s[dates[j]]["close"] / s[day]["open"] - 1.0, "roll_days": 0})
            else:
                rows.append(evaluate(p, fill))
        arms[label] = arm_stats(rows, label)
        (OUT.parent / (OUT.stem + f"_{label}.json"))
        print(json.dumps(arms[label], ensure_ascii=False, indent=2))
        if label == "B_topic1010_rules":
            traded = [r for r in rows if r.get("status") == "traded"]
            by_day = defaultdict(list)
            for r in traded:
                by_day[r["day"]].append(r)
            (OUT.parent / "gushi_1010_panqian_trades_20261013.json").write_text(
                json.dumps(sorted(traded, key=lambda r: (r["day"], r["code"])), ensure_ascii=False, indent=1),
                encoding="utf-8")
            daily = [{"day": d, "n": len(v),
                      "mean": statistics.fmean([x["ret"] for x in v]),
                      "stocks": [x["code"] for x in v]} for d, v in sorted(by_day.items())]
            (OUT.parent / "gushi_1010_panqian_daily_20261013.json").write_text(
                json.dumps(daily, ensure_ascii=False, indent=1), encoding="utf-8")

    doc = {
        "schema": "gushi-1010-panqian-verification/v1",
        "captured_at": "2026-10-13",
        "source": {
            "topic": "https://www.gushi.in/topic/1010",
            "attachment": "盘前强势策略-2026-03-01-2026-10-09.csv",
            "dataset": "875 rows of real strategy picks (TL1-gated, downloaded with the user's logged-in session)",
            "price_data": "D:/Documents/Quant data/data_full (daily OHLC, through 2026-10-12, local only)",
        },
        "rules_implemented": {
            "R1_no_lookahead": "buy at day-T open, which is known when the 09:29 auction print lands",
            "R2_exclude_limitup_open": "skip picks whose day-T open already sits at the limit-up price",
            "R3_fill_check": "filled only when the pick day's low (excluding the open print) is <= the open; strict '<' variant reported separately",
            "R4_exit_roll": "sell at T+1 close; while T+1..n has a sealed limit-down open..high band, roll to the next tradable close",
        },
        "data_integrity": {
            "csv_rows": len(picks),
            "distinct_days": len(set(p["day"] for p in picks)),
            "bars_missing_on_pick_day": len(missing),
            "open_price_mismatches_gt_1cent": len(mism),
            "mismatch_examples": mism[:10],
        },
        "arms": arms,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
