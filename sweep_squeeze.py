# -*- coding: utf-8 -*-
"""短线 v2：布林收窄事件驱动穷举（蜗牛量化策略 + BigQuant 铁律）
================================================================
事件：20日布林带宽 当日/5日前/11日前 ≤ bw_th + mid 上行 + 放量(量比) + 顺MA2
卖出：止盈 / 止损 / 最多持有 max_hold / MA5 生命线 / 市况转弱全撤
网格：top_n × max_hold × take_profit × stop_loss × bw_th
"""
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
sys.path.insert(0, str(BASE))
import short_engine as S
import v8_selector as V

def sweep(asset, limit=0):
    t0 = time.time()
    if asset == "stock":
        pool = S.load_stock_pool()
        vol_ratio, min_amt = 1.2, 2e6
    elif asset == "etf":
        pool = S.load_etf_pool()
        vol_ratio, min_amt = 1.2, 1e6
    else:
        pool = S.load_fund_pool(limit or None)
        vol_ratio, min_amt = None, 0
    print(f"{asset} 池 {len(pool)} 只 加载 {time.time()-t0:.0f}s", flush=True)

    # 粗扫网格（54 组 × 2 带宽阈值 = 108 组）
    grid = []
    for bw_th in [0.02, 0.03]:
        for top_n in [3, 5]:
            for max_hold in [3, 5, 10]:
                for tp in [0.08, 0.12, 0.15]:
                    for sl in [0.05, 0.08, 0.10]:
                        grid.append((bw_th, top_n, max_hold, tp, sl))
    print(f"网格 {len(grid)} 组", flush=True)

    # 事件索引（按 bw_th 缓存）
    events_cache = {}
    res = {}
    out_file = BASE / f"squeeze_{asset}_results.json"
    for i, (bw_th, top_n, max_hold, tp, sl) in enumerate(grid):
        try:
            if bw_th not in events_cache:
                events_cache[bw_th] = S.build_squeeze_events(
                    pool, bw_th=bw_th, vol_ratio=vol_ratio, min_amt=min_amt)
                print(f"  bw_th={bw_th} 事件 {sum(len(v) for v in events_cache[bw_th].values())} 个 "
                      f"({time.time()-t0:.0f}s)", flush=True)
            eq, tr = S.run_squeeze(pool, events_cache[bw_th], top_n=top_n, max_hold=max_hold,
                                   take_profit=tp, stop_loss=sl, fund_mode=(asset == "fund"))
            s = V.summary(eq, tr)
            key = f"B{bw_th*100:.0f}_T{top_n}_H{max_hold}_TP{int(tp*100)}_SL{int(sl*100)}"
            res[key] = s
            print(f"[{i+1}/{len(grid)}] {key}: 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% | "
                  f"回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 交易 {s['total_trades']}", flush=True)
            json.dump({k: {kk: float(vv) for kk, vv in v.items()} for k, v in res.items()},
                      open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[{i+1}] {key if 'key' in dir() else grid[i]} ERR: {e}", flush=True)
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
    args = ap.parse_args()
    sweep(args.asset, args.limit)
