# -*- coding: utf-8 -*-
"""Item 1: dual-source (Sina vs Tencent) close-price cross-check on a random sample."""
import json
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import net_fetch

PCT_1 = 0.005   # 0.5%
PCT_2 = 0.05    # 5%


def main():
    t0 = time.time()
    syms, others = common.list_symbols()
    sample = common.sample_symbols(syms, common.N_SAMPLE, common.SEED)
    ws, we, win = common.window(250)
    s_start, s_end = ws.replace("-", ""), we.replace("-", "")
    print("sample=%d window=%s..%s (%d trade days)" % (len(sample), ws, we, len(win)), flush=True)

    per = []
    fails = []
    total_pairs = 0
    gt1 = 0
    gt2 = 0
    exact = 0
    maxdev_rows = []

    for i, sym in enumerate(sample, 1):
        sd, serr = net_fetch.sina(sym, "qfq", s_start, s_end)
        td, terr = net_fetch.tx(sym, "qfq", s_start, s_end)
        rec = {"sym": sym, "sina_rows": 0 if sd is None else len(sd),
               "tx_rows": 0 if td is None else len(td)}
        if sd is None or td is None:
            rec["status"] = "fetch_fail"
            rec["sina_error"] = serr
            rec["tx_error"] = terr
            fails.append(rec)
            per.append(rec)
            print("[%3d/%d] %s FETCH_FAIL sina=%s tx=%s" % (i, len(sample), sym,
                  "ok" if sd is not None else "FAIL", "ok" if td is not None else "FAIL"), flush=True)
            continue

        a = sd[(sd["date"] >= ws) & (sd["date"] <= we)][["date", "close"]]
        b = td[(td["date"] >= ws) & (td["date"] <= we)][["date", "close"]]
        sa = set(a["date"])
        sb = set(b["date"])
        only_sina = sorted(sa - sb)
        only_tx = sorted(sb - sa)
        m = a.merge(b, on="date", how="inner", suffixes=("_sina", "_tx"))
        m = m[pd.to_numeric(m["close_tx"], errors="coerce") > 0]
        if len(m) == 0:
            rec["status"] = "no_overlap"
            rec["only_sina_dates"] = only_sina
            rec["only_tx_dates"] = only_tx
            fails.append(rec)
            per.append(rec)
            print("[%3d/%d] %s NO_OVERLAP sina_only=%d tx_only=%d" % (i, len(sample), sym,
                  len(only_sina), len(only_tx)), flush=True)
            continue

        dev = (m["close_sina"] - m["close_tx"]).abs() / m["close_tx"]
        n1 = int((dev > PCT_1).sum())
        n2 = int((dev > PCT_2).sum())
        nex = int((dev == 0).sum())
        total_pairs += len(m)
        gt1 += n1
        gt2 += n2
        exact += nex
        j = int(dev.values.argmax())
        top = {"sym": sym, "max_rel_dev": float(dev.values[j]),
               "date": str(m["date"].values[j]),
               "close_sina": float(m["close_sina"].values[j]),
               "close_tx": float(m["close_tx"].values[j]),
               "pairs": int(len(m)), "pairs_gt_0.5pct": n1, "pairs_gt_5pct": n2,
               "mean_rel_dev": float(dev.mean()), "n_exact_equal": nex}
        maxdev_rows.append(top)
        rec.update({"status": "ok", "pairs": int(len(m)), "pairs_gt_0.5pct": n1,
                    "pairs_gt_5pct": n2, "max_rel_dev": float(dev.max()),
                    "max_rel_dev_date": str(m["date"].values[j]),
                    "mean_rel_dev": float(dev.mean()), "n_exact_equal": nex,
                    "sina_only_dates": len(only_sina), "tx_only_dates": len(only_tx),
                    "sina_first": str(a["date"].min()), "sina_last": str(a["date"].max()),
                    "tx_first": str(b["date"].min()), "tx_last": str(b["date"].max())})
        per.append(rec)
        print("[%3d/%d] %s pairs=%d gt0.5%%=%d gt5%%=%d max=%.4f%%" % (
            i, len(sample), sym, len(m), n1, n2, 100 * dev.max()), flush=True)

    ok = [r for r in per if r.get("status") == "ok"]
    for r in per:
        r["universe_class"] = common.classify(r["sym"])
    by_u = {}
    for cls in sorted({r["universe_class"] for r in per}):
        sub = [r for r in per if r["universe_class"] == cls]
        subok = [r for r in sub if r.get("status") == "ok"]
        tp = sum(r["pairs"] for r in subok)
        g1 = sum(r["pairs_gt_0.5pct"] for r in subok)
        g2 = sum(r["pairs_gt_5pct"] for r in subok)
        by_u[cls] = {
            "n_symbols_in_sample": len(sub),
            "n_symbols_compared": len(subok),
            "n_symbols_fetch_fail": sum(1 for r in sub if r.get("status") != "ok"),
            "total_pairs": tp,
            "pairs_gt_0.5pct": g1,
            "pairs_gt_0.5pct_ratio": (g1 / tp) if tp else None,
            "pairs_gt_5pct": g2,
            "pairs_gt_5pct_ratio": (g2 / tp) if tp else None,
        }
    st_ok = [r for r in ok if r["universe_class"].endswith("stock") and r["universe_class"] != "bj_stock"]
    st_tp = sum(r["pairs"] for r in st_ok)
    st_g1 = sum(r["pairs_gt_0.5pct"] for r in st_ok)
    st_g2 = sum(r["pairs_gt_5pct"] for r in st_ok)
    a_share_only = {
        "note": "subset of the same 120-symbol sample: sh600/601/603/605/688 + sz000/001/002/003/300/301/302 (excludes ETFs, B-shares, BJ)",
        "n_symbols_in_sample": sum(1 for r in per if r["universe_class"].endswith("stock") and r["universe_class"] != "bj_stock"),
        "n_symbols_compared": len(st_ok),
        "total_pairs": st_tp,
        "pairs_gt_0.5pct": st_g1,
        "pairs_gt_0.5pct_ratio": (st_g1 / st_tp) if st_tp else None,
        "pairs_gt_5pct": st_g2,
        "pairs_gt_5pct_ratio": (st_g2 / st_tp) if st_tp else None,
        "top10_max_deviation": sorted(
            [{"sym": r["sym"], "max_rel_dev": r["max_rel_dev"], "date": r["max_rel_dev_date"],
              "pairs": r["pairs"]} for r in st_ok], key=lambda x: -x["max_rel_dev"])[:10],
    }
    maxdev_rows.sort(key=lambda r: -r["max_rel_dev"])

    res = {
        "window": {"start": ws, "end": we, "trade_days": len(win),
                   "note": "last 250 official SSE trade dates <= today"},
        "sources": {"sina": "ak.stock_zh_a_daily(adjust='qfq')",
                    "tencent": "ak.stock_zh_a_hist_tx(adjust='qfq')"},
        "compare_field": "close",
        "deviation_definition": "abs(close_sina - close_tx) / close_tx",
        "n_symbols_sampled": len(sample),
        "n_symbols_compared": len(ok),
        "n_symbols_fetch_fail": len(fails),
        "fetch_fail": fails,
        "total_pairs": total_pairs,
        "pairs_gt_0.5pct": gt1,
        "pairs_gt_0.5pct_ratio": (gt1 / total_pairs) if total_pairs else None,
        "pairs_gt_5pct": gt2,
        "pairs_gt_5pct_ratio": (gt2 / total_pairs) if total_pairs else None,
        "pairs_exact_equal": exact,
        "pairs_exact_equal_ratio": (exact / total_pairs) if total_pairs else None,
        "mean_rel_dev_all_pairs": float(sum(r["mean_rel_dev"] * r["pairs"] for r in ok) / total_pairs) if total_pairs else None,
        "top10_max_deviation": maxdev_rows[:10],
        "by_universe": by_u,
        "a_share_only": a_share_only,
        "per_symbol": per,
        "fetch_stats": net_fetch.stats(),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    p = common.write_json("dual_source.json", res)
    print("WROTE", p, flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
