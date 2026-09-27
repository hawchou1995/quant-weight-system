# -*- coding: utf-8 -*-
"""Item 3: trade-calendar alignment for data_full\\sh600000.csv plus the
dataset-wide 'last date' distribution."""
import json
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

TARGET = "sh600000"


def main():
    t0 = time.time()
    cal = common.calendar()
    calset = set(cal.strftime("%Y-%m-%d"))
    p = os.path.join(common.DATA_FULL, TARGET + ".csv")
    df = pd.read_csv(p, dtype={"date": str})
    d = sorted(set(df["date"].astype(str).str.slice(0, 10)))
    ds = pd.to_datetime(pd.Series(d))
    dmin, dmax = d[0], d[-1]
    not_trade = [x for x in d if x not in calset]
    in_range = cal[(cal >= pd.Timestamp(dmin)) & (cal <= pd.Timestamp(dmax))]
    missing = [x.strftime("%Y-%m-%d") for x in in_range if x.strftime("%Y-%m-%d") not in set(d)]
    # weekend check
    wk = {x: pd.Timestamp(x).day_name() for x in not_trade[:10]}

    scan = json.load(open(os.path.join(common.OUT_DIR, "scan.json"), encoding="utf-8"))
    tails = json.load(open(os.path.join(common.OUT_DIR, "scan_tails.json"), encoding="utf-8"))

    res = {
        "symbol": TARGET,
        "akshare_calendar": {"source": "ak.tool_trade_date_hist_sina()",
                            "first": cal[0].strftime("%Y-%m-%d"),
                            "last": cal[-1].strftime("%Y-%m-%d"), "n_dates": int(len(cal))},
        "data_full": {"file": p, "rows": int(len(df)),
                      "first_date": dmin, "last_date": dmax, "n_distinct_dates": len(d),
                      "n_duplicate_dates": int(len(df) - len(d))},
        "dates_in_data_not_trading": {"count": len(not_trade),
                                      "examples": [{"date": x, "weekday": wk.get(x)} for x in not_trade[:5]]},
        "trading_dates_missing_from_data": {
            "count": len(missing),
            "expected_trading_days_in_range": int(len(in_range)),
            "coverage_ratio": (len(in_range) - len(missing)) / len(in_range) if len(in_range) else None,
            "examples": missing[:10],
            "last_10_missing": missing[-10:]},
        "last_date_distribution": {
            "note": "last row date per file, all 7539 data_full CSVs",
            "counts": scan["last_date_distribution"],
            "mode": scan["last_date_mode"],
            "overall_max": scan["max_date_overall"],
            "n_distinct_last_dates": len(scan["last_date_distribution"]),
            "by_universe_class": {},
        },
        "synthetic_tail_rows": {
            "file": os.path.join(common.OUT_DIR, "scan_tails.json"),
            "n_last_bar_zero_open": tails["n_last_bar_zero_open"],
            "n_last_bar_zero_volume_and_amount": tails["n_last_bar_zero_volume_and_amount"],
            "n_last_bar_identical_to_previous": tails["n_last_bar_identical_to_previous"],
            "zero_bar_by_last_date": tails["n_last_bar_all_zero_price_by_lastdate"],
        },
        "all_files_calendar_tally": scan["calendar"],
        "elapsed_sec": round(time.time() - t0, 1),
    }
    # breakdown of the last-date distribution by universe class
    syms, _o = common.list_symbols()
    per_sym_last = {}
    for sym in syms:
        per_sym_last[sym] = None
    import collections
    dist = collections.Counter()
    for sym in syms:
        try:
            with open(os.path.join(common.DATA_FULL, sym + ".csv"), "rb") as f:
                sz = os.path.getsize(os.path.join(common.DATA_FULL, sym + ".csv"))
                f.seek(max(0, sz - 6000))
                blob = f.read().decode("utf-8", "replace").splitlines()
            last = [l for l in blob if l.strip()][-1].split(",")[0][:10]
        except Exception:
            last = "?"
        dist[(common.classify(sym), last)] += 1
    agg = collections.defaultdict(dict)
    for (cls, last), n in dist.items():
        agg[cls][last] = n
    res["last_date_distribution"]["by_universe_class"] = {k: dict(v) for k, v in agg.items()}
    print("WROTE", common.write_json("calendar.json", res), flush=True)
    print(json.dumps({k: v for k, v in res.items() if k != "all_files_calendar_tally"},
                     ensure_ascii=False, indent=1, default=str), flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
