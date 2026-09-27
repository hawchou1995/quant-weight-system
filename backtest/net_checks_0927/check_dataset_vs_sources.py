# -*- coding: utf-8 -*-
"""Extra: does data_full follow Sina or Tencent, and is it current?
Re-uses the cached 120-symbol dual-source responses (no new network traffic)."""
import json
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import net_fetch


def main():
    t0 = time.time()
    ds = json.load(open(os.path.join(common.OUT_DIR, "dual_source.json"), encoding="utf-8"))
    ws, we = ds["window"]["start"], ds["window"]["end"]
    s_start, s_end = ws.replace("-", ""), we.replace("-", "")
    res = {"window": {"start": ws, "end": we}, "sources": {}, "per_symbol": []}
    acc = {s: {"symbols": 0, "pairs": 0, "exact": 0, "gt05": 0, "gt5": 0,
               "ds_missing_dates": 0, "ds_extra_dates": 0, "ds_stale_last": 0,
               "last_date_same": 0} for s in ("sina", "tx")}
    for r in ds["per_symbol"]:
        sym = r["sym"]
        p = os.path.join(common.DATA_FULL, sym + ".csv")
        try:
            df = pd.read_csv(p, dtype={"date": str})
        except Exception:
            continue
        df["date"] = df["date"].astype(str).str.slice(0, 10)
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        d = df[(df["date"] >= ws) & (df["date"] <= we)][["date", "close"]].dropna()
        rec = {"sym": sym, "source_last": {}}
        for src in ("sina", "tx"):
            if src == "sina":
                sd, serr = net_fetch.sina(sym, "qfq", s_start, s_end)
            else:
                sd, serr = net_fetch.tx(sym, "qfq", s_start, s_end)
            if sd is None:
                rec["source_last"][src] = None
                continue
            s = sd[(sd["date"] >= ws) & (sd["date"] <= we)][["date", "close"]]
            rec["source_last"][src] = str(s["date"].max()) if len(s) else None
            m = d.merge(s, on="date", how="inner", suffixes=("_ds", "_src"))
            m = m[m["close_src"] > 0]
            a = acc[src]
            a["symbols"] += 1
            a["pairs"] += len(m)
            if len(m):
                dev = (m["close_ds"] - m["close_src"]).abs() / m["close_src"]
                a["exact"] += int((dev == 0).sum())
                a["gt05"] += int((dev > 0.005).sum())
                a["gt5"] += int((dev > 0.05).sum())
            a["ds_missing_dates"] += len(set(s["date"]) - set(d["date"]))
            a["ds_extra_dates"] += len(set(d["date"]) - set(s["date"]))
            if len(s) and len(d):
                if str(s["date"].max()) == str(d["date"].max()):
                    a["last_date_same"] += 1
                elif str(d["date"].max()) < str(s["date"].max()):
                    a["ds_stale_last"] += 1
        rec["ds_last"] = str(d["date"].max()) if len(d) else None
        res["per_symbol"].append(rec)
    for src, a in acc.items():
        res["sources"][src] = dict(a, exact_ratio=(a["exact"] / a["pairs"]) if a["pairs"] else None,
                                   gt05_ratio=(a["gt05"] / a["pairs"]) if a["pairs"] else None,
                                   gt5_ratio=(a["gt5"] / a["pairs"]) if a["pairs"] else None)
    print("WROTE", common.write_json("dataset_vs_sources.json", res), flush=True)
    print(json.dumps(res["sources"], ensure_ascii=False, indent=1), flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
