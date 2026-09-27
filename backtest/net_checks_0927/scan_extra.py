# -*- coding: utf-8 -*-
"""Supplementary pass: split check-A (>21% day move) by cause / board, and locate
the rows whose date is not an official trade date."""
import collections
import json
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common


def main():
    t0 = time.time()
    syms, _others = common.list_symbols()
    cal = set(common.calendar().strftime("%Y-%m-%d"))
    # board-specific daily limits
    LIMIT = {"sh_stock": 21.0, "sz_stock": 21.0, "bj_stock": 31.0}
    zero_artifact = 0
    real_moves = 0
    beyond_limit = 0
    by_board = collections.Counter()
    beyond_by_board = collections.Counter()
    extreme = []
    nondate = []
    maxret = 0.0
    for i, sym in enumerate(syms, 1):
        p = os.path.join(common.DATA_FULL, sym + ".csv")
        try:
            df = pd.read_csv(p, usecols=["date", "close"], dtype={"date": str})
        except Exception:
            continue
        if "close" not in df.columns or "date" not in df.columns:
            continue
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["date"] = df["date"].astype(str).str.slice(0, 10)
        df = df.dropna(subset=["close"])
        if len(df) == 0:
            continue
        pc = df["close"].shift(1)
        ret = (df["close"] - pc) / pc
        m = pc.notna() & (pc != 0) & (ret.abs() > 0.21)
        if not m.any():
            pass
        else:
            cls = common.classify(sym)
            z = 0
            for idx in df.index[m]:
                if df.at[idx, "close"] == 0 or pc.at[idx] == 0:
                    z += 1
                else:
                    by_board[cls] += 1
                    lim = LIMIT.get(cls, 21.0)
                    if abs(ret.at[idx]) * 100 > lim:
                        beyond_by_board[cls] += 1
                        beyond_limit += 1
            zero_artifact += z
            real_moves += int(m.sum()) - z
            for idx in df.index[m]:
                r = abs(float(ret.at[idx]))
                if r > maxret:
                    maxret = r
                extreme.append((r, sym, df.at[idx, "date"], float(df.at[idx, "close"]), float(pc.at[idx])))
        bad = df.index[~df["date"].isin(cal)]
        for idx in bad:
            nondate.append((sym, df.at[idx, "date"]))
        if i % 1500 == 0:
            print("passed %d/%d" % (i, len(syms)), flush=True)
    extreme.sort(reverse=True)
    res = {
        "A_total_raw": zero_artifact + real_moves,
        "A_zero_price_artifact_rows": zero_artifact,
        "A_real_moves_abs_gt_21pct": real_moves,
        "A_real_moves_by_board": dict(by_board),
        "A_beyond_board_limit": beyond_limit,
        "A_beyond_board_limit_by_board": dict(beyond_by_board),
        "A_board_limit_note": "SSE/SZSE main+ChiNext+STAR use 20% (21% used as the >21% screen); BSE (bj) uses 30%; first day of a new listing has no limit",
        "A_top20_extreme_moves": [
            {"abs_pct": round(r, 6), "sym": s, "date": d, "close": c, "prev_close": pc}
            for r, s, d, c, pc in extreme[:20]],
        "n_rows_on_non_trade_date": len(nondate),
        "rows_on_non_trade_date": [{"sym": s, "date": d} for s, d in nondate[:30]],
        "elapsed_sec": round(time.time() - t0, 1),
    }
    print("WROTE", common.write_json("scan_extra.json", res), flush=True)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
