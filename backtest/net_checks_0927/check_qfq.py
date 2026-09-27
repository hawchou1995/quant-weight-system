# -*- coding: utf-8 -*-
"""Item 2: qfq / non-adjusted (raw) consistency check.

For 10 symbols drawn from the 120-symbol sample we pull BOTH adjust variants from
BOTH allowed sources and check:
  (1) is the LATEST bar close identical between adjust="" and adjust="qfq"?
      (theory: the qfq series is anchored on the most recent bar, so they must match)
  (2) over the historical overlap, how often is raw_close < qfq_close
      (the direction the task asks about) and, for completeness, qfq_close < raw_close
"""
import json
import os
import random
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import net_fetch

N_PICK = 10


def main():
    t0 = time.time()
    ds = json.load(open(os.path.join(common.OUT_DIR, "dual_source.json"), encoding="utf-8"))
    ok_syms = sorted(r["sym"] for r in ds["per_symbol"] if r.get("status") == "ok")
    rng = random.Random(common.SEED + 1)
    pick = sorted(rng.sample(ok_syms, min(N_PICK, len(ok_syms))))
    ws, we, _win = common.window(250)
    hist_start = "20160101"      # data_full starts 2016-01-04
    hist_end = we.replace("-", "")
    print("picked:", pick, flush=True)

    per = []
    for i, sym in enumerate(pick, 1):
        rec = {"sym": sym}
        for src, fn in (("sina", net_fetch.sina), ("tx", net_fetch.tx)):
            if src == "sina":
                raw, rerr = fn(sym, "", "19900101", "21000118")
                qfq, qerr = fn(sym, "qfq", "19900101", "21000118")
            else:
                raw, rerr = fn(sym, "", hist_start, hist_end)
                qfq, qerr = fn(sym, "qfq", hist_start, hist_end)
            if raw is None or qfq is None:
                rec[src] = {"status": "fetch_fail",
                            "raw_error": rerr, "qfq_error": qerr}
                continue
            rl = raw.iloc[-1]
            ql = qfq.iloc[-1]
            same = bool(abs(float(rl["close"]) - float(ql["close"])) < 1e-9)
            eq = bool(str(rl["date"]) == str(ql["date"]))
            m = raw[["date", "close"]].merge(qfq[["date", "close"]], on="date",
                                             suffixes=("_raw", "_qfq"))
            m = m[m["close_qfq"] > 0]
            rel = (m["close_qfq"] - m["close_raw"]).abs() / m["close_qfq"]
            raw_lt = int((m["close_raw"] < m["close_qfq"] - 1e-9).sum())
            qfq_lt = int((m["close_qfq"] < m["close_raw"] - 1e-9).sum())
            equal = int((m["close_raw"] == m["close_qfq"]).sum())
            e_raw = m[m["close_raw"] < m["close_qfq"] - 1e-9]
            rec[src] = {
                "status": "ok",
                "raw_rows": int(len(raw)), "qfq_rows": int(len(qfq)),
                "raw_last_date": str(rl["date"]), "qfq_last_date": str(ql["date"]),
                "same_last_date": eq,
                "raw_last_close": float(rl["close"]), "qfq_last_close": float(ql["close"]),
                "latest_close_equal": same,
                "latest_abs_diff": float(abs(float(rl["close"]) - float(ql["close"]))),
                "overlap_days": int(len(m)),
                "days_raw_lt_qfq": raw_lt,
                "days_qfq_lt_raw": qfq_lt,
                "days_equal": equal,
                "max_abs_rel_diff": float(rel.max()) if len(m) else None,
                "examples_raw_lt_qfq": [
                    {"date": str(r["date"]), "raw_close": float(r["close_raw"]),
                     "qfq_close": float(r["close_qfq"])}
                    for _, r in e_raw.head(3).iterrows()],
            }
        per.append(rec)
        print("[%2d/%d] %s sina_latest_eq=%s tx_latest_eq=%s" % (
            i, len(pick), sym,
            rec.get("sina", {}).get("latest_close_equal"),
            rec.get("tx", {}).get("latest_close_equal")), flush=True)

    res = {
        "history_window": {"start": hist_start, "end": hist_end,
                           "note": "data_full coverage start; sina is fetched full-history and sliced"},
        "n_stocks": len(pick),
        "picked_symbols": pick,
        "latest_price_consistent": {
            src: {
                "n_checked": sum(1 for r in per if r.get(src, {}).get("status") == "ok"),
                "n_latest_equal": sum(1 for r in per if r.get(src, {}).get("latest_close_equal") is True),
                "ratio_latest_equal": (
                    sum(1 for r in per if r.get(src, {}).get("latest_close_equal") is True)
                    / max(1, sum(1 for r in per if r.get(src, {}).get("status") == "ok"))),
                "n_latest_not_equal": sum(1 for r in per if r.get(src, {}).get("latest_close_equal") is False),
            } for src in ("sina", "tx")},
        "history_raw_vs_qfq": {
            src: {
                "overlap_days_total": sum(r.get(src, {}).get("overlap_days", 0) for r in per),
                "days_raw_lt_qfq": sum(r.get(src, {}).get("days_raw_lt_qfq", 0) for r in per),
                "days_qfq_lt_raw": sum(r.get(src, {}).get("days_qfq_lt_raw", 0) for r in per),
                "days_equal": sum(r.get(src, {}).get("days_equal", 0) for r in per),
                "n_stocks_with_raw_lt_qfq": sum(1 for r in per if r.get(src, {}).get("days_raw_lt_qfq", 0) > 0),
            } for src in ("sina", "tx")},
        "per_symbol": per,
        "fetch_stats": net_fetch.stats(),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    print("WROTE", common.write_json("qfq_check.json", res), flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
