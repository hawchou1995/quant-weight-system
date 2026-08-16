# -*- coding: utf-8 -*-
"""短线 v3：动量截面轮动 + MA5生命线/止盈/止损 每日风控（v1 高收益 + v2 好风控混合）
====================================================================================
"""
import os
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import short_engine as S
import v8_selector as V

def sweep(asset, limit=0, fi=0, ti=0):
    t0 = time.time()
    if asset == "stock":
        pool = S.load_stock_pool()
    elif asset == "etf":
        pool = S.load_etf_pool()
    else:
        pool = S.load_fund_pool(limit or None)
    print(f"{asset} 池 {len(pool)} 只 加载 {time.time()-t0:.0f}s", flush=True)

    # v3 网格：轮动参数 × 风控参数
    grid = []
    for top_n in [8, 10]:
        for hold in [10, 20]:
            for smin in [50, 60]:
                for ma5 in [True]:
                    for tp in [0.0, 0.12]:
                        for sl in [0.0, 0.08]:
                            grid.append((top_n, hold, smin, ma5, tp, sl))
    print(f"网格 {len(grid)} 组", flush=True)
    if ti > 0:
        grid = grid[fi:ti]
    res = {}
    out_file = BASE / f"mix_{asset}_results.json"
    for i, (top_n, hold, smin, ma5, tp, sl) in enumerate(grid):
        try:
            eq, tr = S.run_short(pool, top_n=top_n, hold_days=hold, score_min=smin,
                                 fund_mode=(asset == "fund"), reversal=(asset == "stock"),
                                 ma5_exit=ma5, take_profit=tp, stop_loss=sl)
            s = V.summary(eq, tr)
            key = f"T{top_n}_H{hold}_S{smin}_M{int(ma5)}_TP{int(tp*100)}_SL{int(sl*100)}"
            res[key] = s
            print(f"[{i+1}/{len(grid)}] {key}: 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% | "
                  f"回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 交易 {s['total_trades']}", flush=True)
            json.dump({k: {kk: float(vv) for kk, vv in v.items()} for k, v in res.items()},
                      open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[{i+1}] {grid[i]} ERR: {e}", flush=True)
    best = max(res.items(), key=lambda kv: kv[1]["sharpe"]) if res else (None, {})
    print(f"\nBEST {asset}: {best[0]} {best[1]}")
    json.dump({k: {kk: float(vv) for kk, vv in v.items()} for k, v in res.items()},
              open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return res

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="etf", choices=["stock", "etf", "fund"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--from", type=int, default=0, dest="fi")
    ap.add_argument("--to", type=int, default=0, dest="ti")
    args = ap.parse_args()
    sweep(args.asset, args.limit, args.fi, args.ti)