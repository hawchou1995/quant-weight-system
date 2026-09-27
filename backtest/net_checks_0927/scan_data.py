# -*- coding: utf-8 -*-
"""Item 4 (+ data used by item 3): full scan of every data_full CSV.

Checks
  A abs(close/prev_close - 1) > 0.21
  B close <= 0 or open <= 0
  C high < low
  D volume == 0 and amount > 0
  E close == prev_close and |vol - prev_vol| / prev_vol > 0.5   (prev_vol > 0)
Also collects the per-file max date distribution and a calendar sanity tally.
"""
import collections
import json
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

MAX_PCT = 0.21
VOL_DIFF = 0.5
EXAMPLES = 5
MAX_EXAMPLES = 200     # keep a few hundred so top-symbol stats remain possible


def blank(name, desc):
    return {"name": name, "definition": desc, "count": 0, "examples": []}


def main():
    t0 = time.time()
    syms, others = common.list_symbols()
    cal = set(common.calendar().strftime("%Y-%m-%d"))
    checks = {
        "A_abs_daily_return_gt_21pct": blank("A", "abs(close_t - close_{t-1})/close_{t-1} > 0.21"),
        "B_nonpositive_open_or_close": blank("B", "open <= 0 or close <= 0"),
        "C_high_lt_low": blank("C", "high < low"),
        "D_zero_volume_positive_amount": blank("D", "volume == 0 and amount > 0"),
        "E_flat_close_vol_jump": blank("E", "close == prev_close and |vol - prev_vol|/prev_vol > 0.5 (prev_vol > 0)"),
    }
    checkE_alt = blank("E-alt", "close == prev_close and max(vol,prev_vol)/min(vol,prev_vol) - 1 > 0.5 (both > 0)")
    top_syms_a = collections.Counter()
    top_syms_e = collections.Counter()
    last_date_counts = collections.Counter()
    rows_total = 0
    nondate_rows = 0
    nondate_counter = collections.Counter()
    read_errors = []
    files_with_bad_date = 0
    per_file_rows = {}

    for i, sym in enumerate(syms, 1):
        p = os.path.join(common.DATA_FULL, sym + ".csv")
        try:
            df = pd.read_csv(p, dtype={"date": str})
        except Exception as exc:  # noqa: BLE001
            read_errors.append({"sym": sym, "error": "%s: %s" % (type(exc).__name__, str(exc)[:200])})
            continue
        need = ["date", "open", "high", "low", "close", "volume", "amount"]
        if not all(c in df.columns for c in need):
            read_errors.append({"sym": sym, "error": "missing columns: %s" % list(df.columns)})
            continue
        for c in need[1:]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["date"] = df["date"].astype(str).str.slice(0, 10)
        df = df.dropna(subset=["close"])
        if len(df) == 0:
            read_errors.append({"sym": sym, "error": "no numeric rows"})
            continue
        rows_total += len(df)
        per_file_rows[sym] = len(df)
        last_date_counts[df["date"].iloc[-1]] += 1

        bad_dates = df.loc[~df["date"].isin(cal), "date"]
        if len(bad_dates):
            nondate_rows += len(bad_dates)
            files_with_bad_date += 1
            for d in bad_dates.head(3):
                nondate_counter[d] += 1

        prev_close = df["close"].shift(1)
        prev_vol = df["volume"].shift(1)
        ret = (df["close"] - prev_close) / prev_close
        mask_a = prev_close.notna() & (prev_close != 0) & (ret.abs() > MAX_PCT)
        mask_b = (df["open"] <= 0) | (df["close"] <= 0)
        mask_c = df["high"] < df["low"]
        mask_d = (df["volume"] == 0) & (df["amount"] > 0)
        mask_e = (df["close"] == prev_close) & (prev_vol > 0) & ((df["volume"] - prev_vol).abs() / prev_vol > VOL_DIFF)
        mask_e_alt = ((df["close"] == prev_close) & (df["volume"] > 0) & (prev_vol > 0)
                      & ((df[["volume"]].join(prev_vol.rename("pv"), how="left")).max(axis=1)
                         / (df[["volume"]].join(prev_vol.rename("pv"), how="left")).min(axis=1) - 1 > VOL_DIFF))

        nA = int(mask_a.sum())
        if nA:
            checks["A_abs_daily_return_gt_21pct"]["count"] += nA
            top_syms_a[sym] += nA
            for idx in df.index[mask_a][:max(0, MAX_EXAMPLES - len(checks["A_abs_daily_return_gt_21pct"]["examples"]))]:
                checks["A_abs_daily_return_gt_21pct"]["examples"].append(
                    {"sym": sym, "date": df.at[idx, "date"], "pct": round(float(ret.at[idx]), 6),
                     "close": float(df.at[idx, "close"]), "prev_close": float(prev_close.at[idx])})
        for key, mask in (("B_nonpositive_open_or_close", mask_b), ("C_high_lt_low", mask_c),
                          ("D_zero_volume_positive_amount", mask_d)):
            n = int(mask.sum())
            if n:
                checks[key]["count"] += n
                for idx in df.index[mask][:max(0, EXAMPLES - len(checks[key]["examples"]))]:
                    checks[key]["examples"].append(
                        {"sym": sym, "date": df.at[idx, "date"],
                         "open": float(df.at[idx, "open"]), "high": float(df.at[idx, "high"]),
                         "low": float(df.at[idx, "low"]), "close": float(df.at[idx, "close"]),
                         "volume": float(df.at[idx, "volume"]), "amount": float(df.at[idx, "amount"])})
        nE = int(mask_e.sum())
        if nE:
            checks["E_flat_close_vol_jump"]["count"] += nE
            top_syms_e[sym] += nE
            for idx in df.index[mask_e][:max(0, EXAMPLES - len(checks["E_flat_close_vol_jump"]["examples"]))]:
                checks["E_flat_close_vol_jump"]["examples"].append(
                    {"sym": sym, "date": df.at[idx, "date"], "close": float(df.at[idx, "close"]),
                     "prev_volume": float(prev_vol.at[idx]), "volume": float(df.at[idx, "volume"]),
                     "rel_vol_diff": round(float(abs(df.at[idx, "volume"] - prev_vol.at[idx]) / prev_vol.at[idx]), 6)})
        checkE_alt["count"] += int(mask_e_alt.sum())
        if i % 1000 == 0:
            print("scanned %d/%d" % (i, len(syms)), flush=True)

    for k in checks:
        checks[k]["examples"] = checks[k]["examples"][:EXAMPLES]
    checks["E_flat_close_vol_jump"]["alt_definition_count"] = checkE_alt["count"]
    checks["A_abs_daily_return_gt_21pct"]["top_symbols"] = top_syms_a.most_common(10)
    checks["E_flat_close_vol_jump"]["top_symbols"] = top_syms_e.most_common(10)

    res = {
        "n_files_scanned": len(syms),
        "n_files_unclassified_excluded": len(others),
        "unclassified_files": others,
        "n_files_read_error": len(read_errors),
        "read_errors": read_errors[:20],
        "rows_total": rows_total,
        "checks": checks,
        "last_date_distribution": dict(sorted(last_date_counts.items(), key=lambda kv: -kv[1])),
        "last_date_mode": last_date_counts.most_common(1)[0] if last_date_counts else None,
        "max_date_overall": max(last_date_counts) if last_date_counts else None,
        "min_last_date": min(last_date_counts) if last_date_counts else None,
        "calendar": {
            "rows_total_all_files": rows_total,
            "rows_on_non_trade_date": nondate_rows,
            "n_files_with_non_trade_date": files_with_bad_date,
            "top_non_trade_dates": nondate_counter.most_common(20),
        },
        "elapsed_sec": round(time.time() - t0, 1),
    }
    print("WROTE", common.write_json("scan.json", res), flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
