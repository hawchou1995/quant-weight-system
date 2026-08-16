# -*- coding: utf-8 -*-
"""滑点/冲击成本敏感性扫描（v5.11.6）
============================================
三池最优参数在不同滑点下的收益衰减——给出实盘预期区间：
- 股票：T10/H10/S50 反转+MA5（回测 +632.7%）
- ETF：T10/H10/S50 动量+MA5+TP12（+239.2%）
- 基金：T5/H5/S40 无MA5（+273.4%）

滑点口径：每边 bps（买入价上浮 + 卖出价下浮）；基金=T+1 净值申赎费口径（30bps 常见）
"""
import os
import sys, json, time
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import short_engine as S
import v8_selector as V

t0 = time.time()
print("加载池…", flush=True)
stock_pool = S.load_stock_pool()
etf_pool = S.load_etf_pool()
fund_pool = S.load_fund_pool(3000)
print(f"池就绪（{time.time()-t0:.0f}s）：股票 {len(stock_pool)} / ETF {len(etf_pool)} / 基金 {len(fund_pool)}", flush=True)

CONFIGS = [
    ("股票", stock_pool, dict(top_n=10, hold_days=10, score_min=50, reversal=True, ma5_exit=True)),
    ("ETF", etf_pool, dict(top_n=10, hold_days=10, score_min=50, ma5_exit=True, take_profit=0.12)),
    ("基金", fund_pool, dict(top_n=5, hold_days=5, score_min=40, fund_mode=True)),
]
SLIPS = {"股票": [0, 5, 10, 20, 30, 50], "ETF": [0, 5, 10, 20, 30, 50], "基金": [0, 10, 20, 30, 40, 50]}

res = {}
for name, pool, kw in CONFIGS:
    print(f"\n=== {name} 滑点扫描 ===", flush=True)
    res[name] = {}
    for slip in SLIPS[name]:
        eq, tr = S.run_short(pool, slippage_bps=slip, **kw)
        s = V.summary(eq, tr)
        res[name][slip] = s
        print(f"  slip {slip:>2d}bps: 收益 {s['total_return_pct']:>7.1f}% | 回撤 {s['max_drawdown_pct']:>6.2f}% | "
              f"夏普 {s['sharpe']:.3f} | 胜率 {s['win_rate_pct']:.1f}% | {s['total_trades']} 笔", flush=True)

json.dump({k: {str(s): {kk: float(vv) for kk, vv in v.items()} for s, v in d.items()} for k, d in res.items()},
          open(BASE / "slip_sensitivity.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n✅ slip_sensitivity.json 已保存（{time.time()-t0:.0f}s）")