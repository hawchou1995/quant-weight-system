# -*- coding: utf-8 -*-
"""盘前强势策略验证的补充取证：
1) 复权口径核对：CSV 开盘价（不复权） vs 本机 K 线（疑似前复权）的比值是否与"复权锚点"一致。
2) 补一个对照臂 D：剔除"涨停续持"（卖出日收盘涨停）后的收益，用来对拍原帖自报的 +0.05%。
3) 逐日统计与 t 统计量（同日多票按等权组合聚合，避免 n 被放大）。
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gushi_panqian_t1_verify_20261013 import (  # noqa: E402
    board_rate, is_limit, load_picks, load_series, market_of,
)

DATA = Path(r"D:/Documents/Quant data/data_full")
EPS = 1e-6


def adjustment_probe(picks: list[dict]) -> dict:
    """同一只票在不同日期的 csv_open/local_open 比值是否恒定 → 判定复权口径。"""
    ratio_by_code: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for p in picks:
        s = load_series(p["code"])
        if p["day"] in s and s[p["day"]]["open"]:
            ratio_by_code[p["code"]].append((p["day"], p["csv_open"] / s[p["day"]]["open"]))
    rows = []
    for code, vals in ratio_by_code.items():
        if len(vals) < 2:
            continue
        rs = [r for _, r in vals]
        spread = max(rs) - min(rs)
        rows.append({"code": code, "n_days": len(vals), "ratio_min": min(rs), "ratio_max": max(rs),
                     "ratio_spread": spread, "first_day": vals[0][0], "last_day": vals[-1][0]})
    rows.sort(key=lambda r: -r["ratio_spread"])
    # 比值恒定(=复权因子)的票：spread 极小
    constant = [r for r in rows if r["ratio_spread"] < 0.002]
    drifted = [r for r in rows if r["ratio_spread"] >= 0.002]
    return {
        "codes_with_multiple_days": len(rows),
        "ratio_constant_within_0.2pct": len(constant),
        "ratio_drifting": len(drifted),
        "worst_drift_examples": rows[:8],
        "note": "比值恒定 = 同一套复权因子作用于全部日期（前复权 vs 不复权）；比值漂移 = 期间发生除权导致历史价被重算",
    }


def arm_d(picks: list[dict]) -> dict:
    """B 臂基础上再剔除"卖出日收盘涨停"（涨停续持）的样本。"""
    rows = []
    for p in picks:
        code, day = p["code"], p["day"]
        s = load_series(code)
        dates = sorted(s)
        if day not in dates or dates.index(day) == 0:
            rows.append({"status": "skip"})
            continue
        i = dates.index(day)
        bar = s[day]
        prev_close = s[dates[i - 1]]["close"]
        if is_limit(bar["open"], prev_close, code, up=True):
            rows.append({"status": "excluded_limitup_open"})
            continue
        j = i + 1
        if j >= len(dates):
            rows.append({"status": "no_sellable_day"})
            continue
        sell_day = dates[j]
        sell_bar = s[sell_day]
        sell_prev = s[dates[j - 1]]["close"]
        if is_limit(sell_bar["close"], sell_prev, code, up=True):
            rows.append({"status": "excluded_limitup_continuation"})
            continue
        rows.append({"status": "traded", "day": day, "ret": sell_bar["close"] / bar["open"] - 1.0})
    traded = [r for r in rows if r["status"] == "traded"]
    by_day = defaultdict(list)
    for r in traded:
        by_day[r["day"]].append(r["ret"])
    dm = [statistics.fmean(v) for v in by_day.values()]
    return {
        "arm": "D_topic1010_rules_excl_limitup_continuation",
        "picks": len(rows),
        "traded": len(traded),
        "excluded_limitup_open": sum(1 for r in rows if r["status"] == "excluded_limitup_open"),
        "excluded_limitup_continuation": sum(1 for r in rows if r["status"] == "excluded_limitup_continuation"),
        "mean_per_pick": statistics.fmean([r["ret"] for r in traded]) if traded else None,
        "win_rate_per_pick": (sum(1 for r in traded if r["ret"] > 0) / len(traded)) if traded else None,
        "trading_days": len(dm),
        "mean_per_day": statistics.fmean(dm) if dm else None,
        "t_stat_per_day": (statistics.fmean(dm) / (statistics.stdev(dm) / len(dm) ** 0.5))
                          if len(dm) > 1 and statistics.stdev(dm) > 0 else None,
    }


def main() -> int:
    csv_in = Path(sys.argv[1])
    out = Path(sys.argv[2])
    picks = load_picks(csv_in)
    print(f"picks {len(picks)}")

    adj = adjustment_probe(picks)
    print(json.dumps(adj, ensure_ascii=False, indent=2)[:1500])

    d = arm_d(picks)
    print(json.dumps(d, ensure_ascii=False, indent=2))

    doc = {"schema": "gushi-1010-panqian-supplement/v1", "captured_at": "2026-10-13",
           "adjustment_probe": adj, "armD": d}
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
