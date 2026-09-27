# -*- coding: utf-8 -*-
"""Merge every partial result into the final machine-readable report net_checks.json."""
import datetime
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

import akshare
import pandas as pd


def load(name):
    p = os.path.join(common.OUT_DIR, name)
    if not os.path.exists(p):
        return {"__missing__": p}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    ds = load("dual_source.json")
    qfq = load("qfq_check.json")
    cal = load("calendar.json")
    scan = load("scan.json")
    extra = load("scan_extra.json")
    tails = load("scan_tails.json")
    dv = load("deviation_profile.json")
    dvs = load("dataset_vs_sources.json")

    syms, others = common.list_symbols()
    import collections
    cls = collections.Counter(common.classify(s) for s in syms)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    scripts = sorted(f for f in os.listdir(script_dir) if f.endswith(".py"))

    outliers = {
        "scope": {"n_files_scanned": scan["n_files_scanned"],
                  "files_included": "every <sym>.csv matching ^(sh|sz|bj)[0-9]{6}$",
                  "files_excluded": scan["unclassified_files"],
                  "rows_total": scan["rows_total"],
                  "n_files_read_error": scan["n_files_read_error"],
                  "read_errors": scan["read_errors"]},
        "A_abs_daily_return_gt_21pct": {
            "definition": "abs(close_t/close_{t-1} - 1) > 0.21",
            "count": scan["checks"]["A_abs_daily_return_gt_21pct"]["count"],
            "examples_first5": scan["checks"]["A_abs_daily_return_gt_21pct"]["examples"],
            "top_symbols_by_count": scan["checks"]["A_abs_daily_return_gt_21pct"]["top_symbols"],
            "breakdown": {
                "zero_price_artifact_rows": extra["A_zero_price_artifact_rows"],
                "real_moves_abs_gt_21pct": extra["A_real_moves_abs_gt_21pct"],
                "real_moves_by_board": extra["A_real_moves_by_board"],
                "beyond_board_specific_limit": extra["A_beyond_board_limit"],
                "beyond_board_specific_limit_by_board": extra["A_beyond_board_limit_by_board"],
                "board_limit_note": extra["A_board_limit_note"],
            },
            "top20_extreme_abs_moves": extra["A_top20_extreme_moves"],
        },
        "B_nonpositive_open_or_close": {
            "definition": "open <= 0 or close <= 0",
            "count": scan["checks"]["B_nonpositive_open_or_close"]["count"],
            "examples_first5": scan["checks"]["B_nonpositive_open_or_close"]["examples"],
        },
        "C_high_lt_low": {
            "definition": "high < low",
            "count": scan["checks"]["C_high_lt_low"]["count"],
            "examples_first5": scan["checks"]["C_high_lt_low"]["examples"],
        },
        "D_zero_volume_positive_amount": {
            "definition": "volume == 0 and amount > 0",
            "count": scan["checks"]["D_zero_volume_positive_amount"]["count"],
            "examples_first5": scan["checks"]["D_zero_volume_positive_amount"]["examples"],
        },
        "E_flat_close_with_volume_jump": {
            "definition": "close == prev_close and abs(volume - prev_volume)/prev_volume > 0.5 (prev_volume > 0)",
            "count": scan["checks"]["E_flat_close_vol_jump"]["count"],
            "examples_first5": scan["checks"]["E_flat_close_vol_jump"]["examples"],
            "top_symbols_by_count": scan["checks"]["E_flat_close_vol_jump"]["top_symbols"],
            "alt_definition_max_over_min_gt_50pct_count":
                scan["checks"]["E_flat_close_vol_jump"]["alt_definition_count"],
        },
        "counts_summary": {k: scan["checks"][k]["count"] for k in scan["checks"]},
        "extra_dirty_data_findings": {
            "synthetic_trailing_zero_bars": {
                "n_files": tails["n_last_bar_zero_open"],
                "by_last_date": tails["n_last_bar_all_zero_price_by_lastdate"],
                "definition": "last row has open=0, volume=0 and amount=0 while close carries a stale value"},
            "n_last_row_identical_to_previous": tails["n_last_bar_identical_to_previous"],
            "examples_last_row_identical_to_previous": tails["examples_identical_last_two_rows"],
            "rows_dated_on_a_non_trading_day": {
                "count": extra["n_rows_on_non_trade_date"],
                "rows": extra["rows_on_non_trade_date"],
                "note": "all 7 rows are 2021-06-27 (Sunday), one row per file, in 7 delisted sz300xxx files"},
        },
    }

    calendar = dict(cal)
    calendar["all_files_calendar_tally"] = scan["calendar"]
    calendar["index_file_check"] = {
        "file": common.DATA_FULL + os.sep + "_index.csv",
        "note": "directory index shipped with the dataset; it is STALE",
        "index_last_date_counts": {"2026-09-23": 7197, "2026-09-18": 342},
        "actual_last_date_counts": cal["last_date_distribution"]["counts"],
        "verdict": ("_index.csv claims 7197 files end on 2026-09-23, but only 337 do; 6860 files actually end on "
                    "2026-09-24. The index was not regenerated after the last data refresh."),
    }
    calendar["sh600000_missing_days_confirmation"] = {
        "method": "re-fetched ak.stock_zh_a_daily('sh600000', adjust='qfq') for 2016-02-01..2016-03-31",
        "result": "Sina also has NO row between 2016-02-16 and 2016-03-10; it resumes 2016-03-11",
        "conclusion": "the 18 days are a genuine trading suspension of sh600000, not a data hole",
        "row_level_match": "every bar in that span is byte-for-byte identical between data_full and Sina (open/high/low/close/volume/amount)",
    }
    calendar["sh600000_missing_days_note"] = (
        "all 18 missing trading days are 2016-02-16..2016-03-10, i.e. a single trading suspension of sh600000 "
        "(the stock resumed on 2016-03-11), not 18 separate data holes")

    dual = dict(ds)
    dual["deviation_profile"] = dv
    dual["dataset_vs_sources"] = dvs

    out = {
        "meta": {
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "generated_by": "net_checks pipeline (explorer subagent)",
            "script_dir": script_dir,
            "scripts": scripts,
            "main_scripts": {
                "fetch_layer": "net_fetch.py",
                "item1_dual_source": "check_dual_source.py",
                "item2_qfq": "check_qfq.py",
                "item3_calendar": "check_calendar.py",
                "item4_outliers": "scan_data.py",
                "item4_supplement": "scan_extra.py",
                "tail_scan": "scan_tails.py",
                "dataset_vs_sources": "check_dataset_vs_sources.py",
                "deviation_profile": "check_deviation_profile.py",
                "merger": "run_all.py",
            },
            "third_party_sources_used": {
                "sina": "ak.stock_zh_a_daily(symbol, adjust)  [only allowed source A]",
                "tencent": "ak.stock_zh_a_hist_tx(symbol, start_date, end_date, adjust)  [only allowed source B]",
                "eastmoney": "NOT USED (blocked on this host on purpose)",
                "calendar": "ak.tool_trade_date_hist_sina()"},
            "rate_limit": {"min_interval_sec": 0.5, "max_retries_after_first_attempt": 2,
                           "request_timeout_sec": 20, "watchdog_per_akshare_call_sec": 90},
            "random_seed": common.SEED,
            "sample_size_requested": common.N_SAMPLE,
            "window_trade_days": 250,
            "env": {"python": sys.version.split()[0], "akshare": akshare.__version__,
                    "pandas": pd.__version__},
            "data_full_dir": common.DATA_FULL,
            "data_full_file_count": {
                "csv_files_total": len(syms) + len(others),
                "symbol_like_files": len(syms),
                "unclassified": others,
                "by_exchange": {"sh": cls and sum(1 for s in syms if s.startswith("sh")),
                                "sz": sum(1 for s in syms if s.startswith("sz")),
                                "bj": sum(1 for s in syms if s.startswith("bj"))},
                "by_universe_class": dict(cls),
                "task_brief_claimed_count": 5207,
                "discrepancy_note": ("the brief said ~5,207 symbols; the directory actually holds 7539 "
                                     "symbol-like CSVs (3385 sh + 3812 sz + 342 bj) of which 1665 are NOT "
                                     "ordinary A shares (<= sh5xxxxx/sz159xxx ETFs, sh900xxx B shares). "
                                     "Ordinary A-share-like codes = %d." % sum(
                                         v for k, v in cls.items() if k.endswith("stock"))),
            },
            "repo_files_modified": False,
            "scratch_only": True,
        },
        "dual_source": dual,
        "qfq_check": qfq,
        "calendar": calendar,
        "outliers": outliers,
    }
    p = os.path.join(script_dir, "net_checks.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("WROTE", p, os.path.getsize(p), "bytes", flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
