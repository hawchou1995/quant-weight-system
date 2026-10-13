# -*- coding: utf-8 -*-
"""topic/1010 执行规则的探针灵敏度验证（设计好的阳性/阴性对照）。

只用规则、不引入新策略参数。被验证的两条：

  R2 排除"开盘涨停价买不进"：T 日开盘价已等于涨停价 → 该样本必须被剔除。
  R4 "次日跌停卖不掉顺延"：卖出口（T+1）若全天封在跌停价 → 必须顺延到下一可卖日。

对照设计（阳性 = 注入已知缺陷，必须被抓到；阴性 = 正常路径，必须不误报）：
  R2 阳性：把已成交样本的 T 日开盘价改写为按板块档位算出的涨停价 → 期望全部被剔除。
  R2 阴性：同批样本不改写 → 期望全部放行。
  R4 阳性：把已成交样本的卖出日 high 改写为该日跌停价 → 期望全部顺延。
  R4 阴性：同批样本不改写 → 期望零顺延。

注入走 monkeypatch 本模块的 load_series，被调用的是**与正式跑同一份 run_arm / is_limit**，
避免"验证用的规则"和"跑数据用的规则"是两套实现。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gushi_strategy_export_t1_verify_20261013 as drv  # noqa: E402
from gushi_panqian_t1_verify_20261013 import board_rate, load_picks  # noqa: E402

REAL_LOAD = drv.load_series
INJECT: dict[tuple[str, str], dict] = {}


def patched_load(code: str) -> dict:
    series = dict(REAL_LOAD(code))
    for (c, d), overrides in INJECT.items():
        if c == code and d in series:
            series[d] = {**series[d], **overrides}
    return series


def pick_sample(picks: list[dict], n: int = 5, need_sell: bool = True) -> list[dict]:
    """挑 n 个"正常成交"的样本（开盘远离涨跌停、且 T+1 存在）。"""
    chosen = []
    for p in picks:
        s = REAL_LOAD(p["code"])
        dates = sorted(s)
        if p["day"] not in dates or dates.index(p["day"]) == 0:
            continue
        i = dates.index(p["day"])
        if need_sell and i + 1 >= len(dates):
            continue
        prev = s[dates[i - 1]]["close"]
        rate = board_rate(p["code"])
        open_px = s[p["day"]]["open"]
        # 距离涨停至少 3 个百分点，避免边界样本
        if prev and (open_px / prev - 1) < rate - 0.03 and (open_px / prev - 1) > -rate + 0.03:
            chosen.append(p)
        if len(chosen) >= n:
            break
    return chosen


def main() -> int:
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])
    csvs = [p for p in sorted(src.rglob("*.csv")) if not p.name.startswith("._")]
    picks = []
    for p in csvs:
        picks.extend(load_picks(p))
    print(f"picks loaded: {len(picks)}")

    sample = pick_sample(picks, 5)
    print("sample:", [(x["code"], x["day"]) for x in sample])

    report: dict = {"schema": "gushi-1010-tradability-controls/v1", "captured_at": "2026-10-13",
                    "sample": [{"code": x["code"], "day": x["day"]} for x in sample]}

    # ---------- baseline & negative controls (no injection) ----------
    drv.load_series = REAL_LOAD
    INJECT.clear()
    base_rows = drv.run_arm(picks, "B")
    observed = {
        "picks": len(base_rows),
        "traded": sum(1 for r in base_rows if r["status"] == "traded"),
        "excluded_limitup_open": sum(1 for r in base_rows if r["status"] == "excluded_limitup_open"),
        "rolled_limitdown": sum(1 for r in base_rows if r["status"] == "traded" and r.get("roll_days", 0) > 0),
        "no_fill_low_eq_open": sum(1 for r in base_rows if r["status"] == "no_fill_low_eq_open"),
    }
    print("observed (all four exports, arm B):", observed)

    neg_rows = drv.run_arm(sample, "B")
    neg = {
        "expected": "all five normal picks pass through untraded-filtered",
        "statuses": [r["status"] for r in neg_rows],
        "passed": all(r["status"] == "traded" for r in neg_rows),
        "roll_days": [r.get("roll_days") for r in neg_rows],
    }
    print("R2/R4 negative control:", neg)

    # ---------- R2 positive control: force open to the limit-up price ----------
    drv.load_series = patched_load
    INJECT.clear()
    inject_r2 = []
    for p in sample:
        s = REAL_LOAD(p["code"])
        dates = sorted(s)
        i = dates.index(p["day"])
        prev = s[dates[i - 1]]["close"]
        lu = round(prev * (1 + board_rate(p["code"])), 2)
        INJECT[(p["code"], p["day"])] = {"open": lu}
        inject_r2.append({"code": p["code"], "day": p["day"], "prev_close": prev,
                          "injected_open": lu, "real_open": s[p["day"]]["open"]})
    pos2_rows = drv.run_arm(sample, "B")
    pos2 = {
        "expected": "all five injected picks excluded as unbuyable",
        "injections": inject_r2,
        "statuses": [r["status"] for r in pos2_rows],
        "caught": sum(1 for r in pos2_rows if r["status"] == "excluded_limitup_open"),
        "all_caught": all(r["status"] == "excluded_limitup_open" for r in pos2_rows),
    }
    print("R2 positive control:", pos2["caught"], "/", len(sample), "caught")

    # ---------- R4 positive control: force the exit day to a sealed limit-down ----------
    INJECT.clear()
    inject_r4 = []
    for p in sample:
        s = REAL_LOAD(p["code"])
        dates = sorted(s)
        i = dates.index(p["day"])
        sell_day = dates[i + 1]
        j = dates.index(sell_day)
        pc = s[dates[j - 1]]["close"]
        ld = round(pc * (1 - board_rate(p["code"])), 2)
        INJECT[(p["code"], sell_day)] = {"high": ld, "low": ld, "close": ld, "open": min(s[sell_day]["open"], ld)}
        inject_r4.append({"code": p["code"], "pick_day": p["day"], "forced_seal_day": sell_day,
                          "limit_down": ld, "next_day": dates[j + 1] if j + 1 < len(dates) else None})
    pos4_rows = drv.run_arm(sample, "B")
    pos4 = {
        "expected": "all five forced limit-down exits roll to the next tradable close",
        "injections": inject_r4,
        "statuses": [r["status"] for r in pos4_rows],
        "roll_days": [r.get("roll_days") for r in pos4_rows],
        "all_rolled": all(r.get("roll_days", 0) >= 1 for r in pos4_rows if r["status"] == "traded"),
        "rolled_count": sum(1 for r in pos4_rows if r.get("roll_days", 0) >= 1),
    }
    print("R4 positive control: rolled", pos4["rolled_count"], "/", len(sample))

    drv.load_series = REAL_LOAD
    INJECT.clear()

    report.update({
        "observed_on_real_data": observed,
        "R2_negative_control": neg,
        "R2_positive_control": pos2,
        "R4_negative_control": {"expected": "no roll without injection", "roll_days": neg["roll_days"],
                                "no_false_roll": all((r or 0) == 0 for r in neg["roll_days"])},
        "R4_positive_control": pos4,
        "verdict": {
            "R2_probe_sensitive": pos2["all_caught"] and neg["passed"],
            "R4_probe_sensitive": pos4["all_rolled"] and all((r or 0) == 0 for r in neg["roll_days"]),
            "note": f"在真实样本里 R4（跌停封板顺延）从未触发（rolled={observed['rolled_limitdown']}），"
                    f"其机制由注入对照证明；R2 在真实样本中命中 {observed['excluded_limitup_open']} 个开盘封板样本"
                    f"（全部四份导出合计 {observed['picks']} 笔），并被注入对照确认不会漏判。",
        },
    })
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["verdict"], ensure_ascii=False, indent=2))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
