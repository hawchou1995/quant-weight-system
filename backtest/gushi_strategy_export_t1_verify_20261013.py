# -*- coding: utf-8 -*-
"""gushi topic/1010 四个策略导出数据的统一 T+1 验证。

输入：目录下 4 份 CSV（T+1闪电 / 晨星量化 / 盘前强势量化 / 竞价多头策略），
      均由 topic/1010、topic/1009 的 TL1 附件解压得到，字段同构：
      策略名称,股票名称,股票代码,开盘价,最新价,开盘涨幅,实体涨幅,调入时间

四个对照臂（同一份选股、同一份本地日线）：
  A 朴素：所有样本按 T 日开盘买入、T+1 收盘卖出（不做任何可成交性处理）
  B 帖内规则：剔除开盘涨停买不进 + 成交判定 low ≤ open
  C 严格成交：剔除开盘涨停 + 要求 low < open（除开盘价外出现过更低报价）
  D 帖内规则 + 剔除"涨停续持"（卖出日收盘涨停）

同时给出逐日等权组合口径的均值/中位/t 统计量。
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
    is_limit, load_picks, load_series,
)

EPS = 1e-6


def run_arm(picks: list[dict], mode: str) -> list[dict]:
    rows = []
    for p in picks:
        code, day = p["code"], p["day"]
        s = load_series(code)
        dates = sorted(s)
        if day not in dates or dates.index(day) == 0:
            rows.append({"status": "no_bar"}); continue
        i = dates.index(day)
        bar = s[day]
        prev_close = s[dates[i - 1]]["close"]
        if mode != "A" and is_limit(bar["open"], prev_close, code, up=True):
            rows.append({"status": "excluded_limitup_open"}); continue
        if mode == "C" and not (bar["low"] < bar["open"] - EPS):
            rows.append({"status": "no_fill_low_eq_open"}); continue
        j = i + 1
        if mode == "A":
            if j >= len(dates):
                rows.append({"status": "no_sellable_day"}); continue
            sell_day = dates[j]; sell_px = s[sell_day]["close"]
        else:
            roll = 0
            while j < len(dates):
                d = dates[j]; b = s[d]; pc = s[dates[j - 1]]["close"]
                if is_limit(b["high"], pc, code, up=False):
                    roll += 1; j += 1; continue
                sell_day, sell_px = d, b["close"]
                break
            else:
                rows.append({"status": "no_sellable_day"}); continue
            if mode == "D" and is_limit(s[sell_day]["close"], s[dates[dates.index(sell_day) - 1]]["close"], code, up=True):
                rows.append({"status": "excluded_limitup_continuation"}); continue
            rows.append({"status": "traded", "day": day, "code": code, "ret": sell_px / bar["open"] - 1.0,
                         "roll_days": roll})
            continue
        rows.append({"status": "traded", "day": day, "code": code, "ret": sell_px / bar["open"] - 1.0, "roll_days": 0})
    return rows


def stats(rows: list[dict], label: str) -> dict:
    traded = [r for r in rows if r["status"] == "traded"]
    rets = [r["ret"] for r in traded]
    by_day = defaultdict(list)
    for r in traded:
        by_day[r["day"]].append(r["ret"])
    dm = [statistics.fmean(v) for v in by_day.values()]
    sd = statistics.stdev(dm) if len(dm) > 1 else None
    return {
        "arm": label,
        "picks": len(rows),
        "traded": len(traded),
        "excluded_limitup_open": sum(1 for r in rows if r["status"] == "excluded_limitup_open"),
        "excluded_limitup_continuation": sum(1 for r in rows if r["status"] == "excluded_limitup_continuation"),
        "no_fill": sum(1 for r in rows if r["status"] == "no_fill_low_eq_open"),
        "rolled_limitdown": sum(1 for r in traded if r.get("roll_days", 0) > 0),
        "mean_per_pick_pct": round(statistics.fmean(rets) * 100, 4) if rets else None,
        "median_per_pick_pct": round(statistics.median(rets) * 100, 4) if rets else None,
        "win_rate_per_pick_pct": round(sum(1 for x in rets if x > 0) / len(rets) * 100, 2) if rets else None,
        "days": len(dm),
        "mean_per_day_pct": round(statistics.fmean(dm) * 100, 4) if dm else None,
        "median_per_day_pct": round(statistics.median(dm) * 100, 4) if dm else None,
        "t_stat_per_day": round(statistics.fmean(dm) / (sd / len(dm) ** 0.5), 3) if sd else None,
        "win_rate_per_day_pct": round(sum(1 for x in dm if x > 0) / len(dm) * 100, 2) if dm else None,
    }


def main() -> int:
    src_dir = Path(sys.argv[1])
    out = Path(sys.argv[2])
    label_map = {
        "T+1闪电": ("T+1闪电", "1010"),
        "晨星量化": ("晨星量化", "1010"),
        "盘前强势量化": ("盘前强势量化", "1010"),
        "竞价多头策略": ("竞价多头策略", "1009"),
    }
    result = {}
    all_rows_by_arm: dict[str, list[dict]] = defaultdict(list)
    # 文件名可能因 zip 编码而乱码 —— 一律按内容里的“策略名称”列识别
    candidates = [p for p in sorted(src_dir.rglob("*.csv"))
                  if not p.name.startswith("._") and "__MACOSX" not in str(p)]
    seen: set[str] = set()
    for p in candidates:
        try:
            with open(p, "r", encoding="utf-8-sig", errors="replace") as f:
                head: list[str] = []
                for line in f:
                    if line.strip():
                        head.append(line)
                    if len(head) == 2:
                        break
            first = next(csv.DictReader(head)) if len(head) == 2 else None
        except Exception as e:
            print("SKIP", p.name, e); continue
        if not first:
            continue
        strategy = (first.get("策略名称") or "").strip()
        if strategy not in label_map:
            print("SKIP (unknown strategy)", p.name, repr(strategy)); continue
        label, topic = label_map[strategy]
        if label in seen:
            print("SKIP (duplicate label)", p.name); continue
        seen.add(label)
        picks = load_picks(p)
        days = len(set(x["day"] for x in picks))
        print(f"--- {label} ({topic}) rows={len(picks)} days={days} from {p.name}")
        entry = {"topic": topic, "source_file": p.name, "rows": len(picks),
                 "distinct_days": days, "arms": {}}
        for mode, name in (("A", "A_naive"), ("B", "B_topic_rules"), ("C", "C_strict_fill"), ("D", "D_rules_excl_limitup_continuation")):
            rows = run_arm(picks, mode)
            st = stats(rows, name)
            entry["arms"][name] = st
            for r in rows:
                if r["status"] == "traded":
                    all_rows_by_arm[name].append(r)
            print("     ", name, {k: st[k] for k in ("traded", "excluded_limitup_open", "excluded_limitup_continuation",
                                                      "no_fill", "rolled_limitdown", "mean_per_day_pct", "t_stat_per_day")})
        result[label] = entry

    pooled = {}
    for name, rows in all_rows_by_arm.items():
        pooled[name] = stats(rows, name + "_pooled_all")
        print("POOLED", name, {k: pooled[name][k] for k in ("traded", "mean_per_pick_pct", "mean_per_day_pct", "t_stat_per_day")})

    doc = {
        "schema": "gushi-strategy-export-t1-verification/v1",
        "captured_at": "2026-10-13",
        "provenance": {
            "community_topics": ["https://www.gushi.in/topic/1010", "https://www.gushi.in/topic/1009"],
            "access": "TL1 attachments downloaded through the owner's authenticated browser session (his explicit authorization)",
            "file_origin_note": "the zip archives carry __MACOSX metadata showing the export URL "
                                "https://i.gushi.in/strategy_export.php?strategy_id=..&start_date=2026-03-01&end_date=2026-10-09&format=csv "
                                "-> the CSVs are platform exports attached to the community posts, not community-authored text",
            "price_data": "D:/Documents/Quant data/data_full (front-adjusted daily OHLC, through 2026-10-12, local read-only)",
            "adjustment_note": "local series is 前复权 while the exports are 不复权; verified by a constant 1.400/1.405 ratio "
                              "(10送4) for codes 301165/300394/300857 on pre-event dates and an exact 1.000 ratio after the event",
        },
        "rules": {
            "entry": "buy at the pick day's official open (the export already lists it; the 09:27-09:29 timestamps are after the 09:25 opening print)",
            "R2": "exclude picks whose entry-day open already sits at the limit-up price",
            "R3": "fill requires the entry-day low to be at or below the open (strict variant: strictly below)",
            "R4": "exit at T+1 close, rolling to the next tradable close while the day is sealed limit-down",
        },
        "per_strategy": result,
        "pooled_all_strategies": pooled,
    }
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
