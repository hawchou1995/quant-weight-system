# -*- coding: utf-8 -*-
"""基金池规模对照回测（2026-09-16 预注册口径）
=============================================================
背景：基金信号池原为「按代码升序取缓存前 N 个文件」的任意截断——
      生产 3000（已修为 2000，与回测同池）/ 回测 2000 / 缓存全库 19,359（净值≥400行 14,707）。
问题：池扩到「字面全量」是否更好？（用户要求「确保三个系统都是全量池跑的数据」）

口径：FB3-H20 牛熊（牛 Top10/S30/w(40,0,30,30)、熊 Top3/S45/w(25,0,30,45)，allow_bear_buy=True），
      相位 offsets 0/4/8/12/16（hold=20，ADR-0006），slip 5bp 主档 + 50bp 稳健档，2021 起（引擎内 START）。
用法：python backtest/fund_pool_size_0916.py --pool 2000        # 单档
      python backtest/fund_pool_size_0916.py --pool 0           # 0 = 全库（load_fund_pool(None)）
产物：backtest/fund_pool_size_0916.json（按 pool 累积）
"""
import argparse
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import numpy as np
import short_engine as S
import v8_selector as V

OUT = BASE / "backtest" / "fund_pool_size_0916.json"
FUND_BULL = dict(top_n=10, hold_days=20, score_min=30, reversal=False, min_amt=0,
                 weights=(40, 0, 30, 30), mask=(1, 1, 1, 1))
FUND_BEAR = dict(top_n=3, hold_days=20, score_min=45, reversal=False, min_amt=0,
                 weights=(25, 0, 30, 45), mask=(1, 1, 1, 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=int, required=True, help="池规模；0=全库（None）")
    ap.add_argument("--phases", default="0,4,8,12,16")
    a = ap.parse_args()

    lim = None if a.pool == 0 else a.pool
    t0 = time.time()
    pool = S.load_fund_pool(lim)
    n_pool = len(pool)
    print(f"[pool={a.pool}] 实际载入 {n_pool} 只（{time.time()-t0:.0f}s）", flush=True)

    def run(slip, off):
        eq, tr = S.run_short_regime(pool, bull_cfg=dict(FUND_BULL), bear_cfg=dict(FUND_BEAR),
                                    allow_bear_buy=True, fund_mode=True, slippage_bps=slip, offset=off)
        return V.summary(eq, tr)

    rows = []
    for off in [int(x) for x in a.phases.split(",")]:
        t1 = time.time()
        s = run(5, off)
        rows.append({"offset": off, "total": s["total_return_pct"], "sharpe": s["sharpe"],
                     "mdd": s["max_drawdown_pct"], "trades": s["total_trades"], "annual": s.get("annual_return_pct")})
        print(f"  off={off:<3} 收益 {s['total_return_pct']:>9.1f}%  年化 {s.get('annual_return_pct', 0):>5.1f}%  "
              f"夏普 {s['sharpe']:>5.3f}  回撤 {s['max_drawdown_pct']:>6.1f}%  笔数 {s['total_trades']:>5}  ({time.time()-t1:.0f}s)", flush=True)
    sh = [r["sharpe"] for r in rows]
    res = {"pool_arg": a.pool, "loaded": n_pool,
           "sharpe_med": float(np.median(sh)), "total_med": float(np.median([r["total"] for r in rows])),
           "sharpe_min": float(min(sh)), "sharpe_max": float(max(sh)), "phases": rows}
    s50 = run(50, 0)
    res["slip50_off0"] = {"total": s50["total_return_pct"], "sharpe": s50["sharpe"], "mdd": s50["max_drawdown_pct"]}
    print(f"  → 相位中位：收益 {res['total_med']:.1f}% / 夏普 {res['sharpe_med']:.3f} [{res['sharpe_min']:.3f},{res['sharpe_max']:.3f}]"
          f" | slip50 off0 夏普 {s50['sharpe']:.3f}", flush=True)

    out = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"prereg": {
        "strategy": "FB3-H20", "phases": [0, 4, 8, 12, 16], "slip_main_bps": 5, "slip_robust_bps": 50,
        "basis": "2021 起；生产与回测同池校验", "date": "2026-09-16"}}
    out[f"pool_{a.pool}"] = res
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[done] {time.time()-t0:.0f}s → {OUT.name}")


if __name__ == "__main__":
    main()
