# -*- coding: utf-8 -*-
"""Fast tail inspection of every data_full CSV (reads only the last few KB of each file)
to quantify padding / synthetic trailing rows."""
import collections
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common


def tail_lines(path, window=6000, n=3):
    sz = os.path.getsize(path)
    with open(path, "rb") as f:
        f.seek(max(0, sz - window))
        blob = f.read()
    txt = blob.decode("utf-8", "replace")
    lines = [l for l in txt.splitlines() if l.strip()]
    return lines[-n:]


def nums(line):
    parts = line.split(",")
    if len(parts) < 7:
        return None
    try:
        return parts[0], [float(x) for x in parts[1:7]]
    except Exception:
        return None


def main():
    t0 = time.time()
    syms, _others = common.list_symbols()
    last_date_counts = collections.Counter()
    n_last_zero_bar = 0
    n_last_zero_volamt = 0
    n_last_zero_open = 0
    n_last0_dup_prev = 0
    zero_bar_by_lastdate = collections.Counter()
    examples = []
    for sym in syms:
        p = os.path.join(common.DATA_FULL, sym + ".csv")
        lines = tail_lines(p, 6000, 3)
        if not lines:
            continue
        r = nums(lines[-1])
        if r is None:
            continue
        d, v = r
        o, h, lo, c, vol, amt = v
        last_date_counts[d[:10]] += 1
        is_zero_bar = (o == 0 and vol == 0 and amt == 0)
        if is_zero_bar:
            n_last_zero_bar += 1
            zero_bar_by_lastdate[d[:10]] += 1
        if vol == 0 and amt == 0:
            n_last_zero_volamt += 1
        if o == 0:
            n_last_zero_open += 1
        if len(lines) >= 2:
            r2 = nums(lines[-2])
            if r2 is not None and r2[1] == v:
                n_last0_dup_prev += 1
                if len(examples) < 12:
                    examples.append({"sym": sym, "last_date": d[:10], "prev_date": r2[0][:10],
                                     "identical_ohlcv_amount": True})
    res = {
        "last_date_distribution": dict(sorted(last_date_counts.items(), key=lambda kv: -kv[1])),
        "n_files": sum(last_date_counts.values()),
        "n_last_bar_all_zero_price": n_last_zero_bar,
        "n_last_bar_all_zero_price_by_lastdate": dict(zero_bar_by_lastdate),
        "n_last_bar_zero_volume_and_amount": n_last_zero_volamt,
        "n_last_bar_zero_open": n_last_zero_open,
        "n_last_bar_identical_to_previous": n_last0_dup_prev,
        "examples_identical_last_two_rows": examples,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    print("WROTE", common.write_json("scan_tails.json", res), flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
