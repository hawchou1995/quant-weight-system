# -*- coding: utf-8 -*-
"""中长线滑点敏感性扫描（v5.11.8）
============================================
中长线换手低（年 30-70 笔），滑点影响应显著小于短线（132 笔/年）。
引擎：v9_auto（全量池月轮动）/ v8_lite（固定池42日轮动）/ etf_opt_v3（ETF月频）
扫描 slip {0, 10, 20, 30} bps
"""
import os
import sys, json, time
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import v9_auto as A
import v8_lite as L
import etf_opt_v3 as E3
import etf_opt_v2 as E2
import v8_selector as V

t0 = time.time()
print("加载池…", flush=True)
# v9: A.pool_all（v9_auto 加载时自动）；v8: L.build_pool()；ETF: E3 池
print("v9 池:", len(A.pool_all), flush=True)
lite_pool = L.build_pool(verbose=False)
etf_pool = E2.build_pool_with_factors()
print(f"池就绪（{time.time()-t0:.0f}s）：v8 {len(lite_pool)} / ETF {len(etf_pool) if etf_pool is not None else 0}", flush=True)

res = {}

# ---- v9 全量池（生产参数：T3/MA150，分层口径用一体 all）----
print("\n=== v9_auto 全量池（T3/m25/s65/SL5.5/MA150）===", flush=True)
res["v9"] = {}
for slip in (0, 10, 20, 30):
    eq, tr = A.run_auto(top_n=3, mom_min=0.25, score_min=65, stop_loss=0.055,
                        dynamic=True, rsi_max=85, ma_window=150, slippage_bps=slip)
    s = V.summary(eq, tr)
    res["v9"][slip] = s
    print(f"  slip {slip:>2d}bps: 收益 {s['total_return_pct']:>7.1f}% | 回撤 {s['max_drawdown_pct']:>6.2f}% | "
          f"夏普 {s['sharpe']:.3f} | {s['total_trades']} 笔", flush=True)

# ---- v8 固定池（T4/H42/MA200 择时）----
print("\n=== v8_lite 固定池（T4/H42/MA200）===", flush=True)
res["v8"] = {}
for slip in (0, 10, 20, 30):
    eq, tr = L.run_lite(lite_pool, top_n=4, hold_days=42, use_timing=True, stop_loss=0.10, slippage_bps=slip)
    s = V.summary(eq, tr)
    res["v8"][slip] = s
    print(f"  slip {slip:>2d}bps: 收益 {s['total_return_pct']:>7.1f}% | 回撤 {s['max_drawdown_pct']:>6.2f}% | "
          f"夏普 {s['sharpe']:.3f} | {s['total_trades']} 笔", flush=True)

# ---- ETF 中长线（月频 H21/Top5/MA5/冷冻5/MA150，v3 最优）----
if etf_pool is not None:
    print("\n=== ETF 中长线 v3（H21/T5/mom20/MA5/冷冻5/MA150）===", flush=True)
    res["etf"] = {}
    for code, ddf in etf_pool.items():
        ddf["ma5"] = ddf["close"].rolling(5).mean()
    for slip in (0, 10, 20, 30):
        eq, tr = E3.run_etf_v3(etf_pool, mom_type="mom20", top_n=5, hold_days=21, freeze=5,
                               ma5_exit=True, ma_win=150, slippage_bps=slip)
        s = V.summary(eq, tr)
        res["etf"][slip] = s
        print(f"  slip {slip:>2d}bps: 收益 {s['total_return_pct']:>7.1f}% | 回撤 {s['max_drawdown_pct']:>6.2f}% | "
              f"夏普 {s['sharpe']:.3f} | {s['total_trades']} 笔", flush=True)

json.dump({k: {str(s): {kk: float(vv) for kk, vv in v.items()} for s, v in d.items()} for k, d in res.items()},
          open(BASE / "slip_ml_sensitivity.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n✅ slip_ml_sensitivity.json 已保存（{time.time()-t0:.0f}s）")