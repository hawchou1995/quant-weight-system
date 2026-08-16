# -*- coding: utf-8 -*-
"""滑点稳健参数扫描（v5.11.7）：找含滑点下更优的参数组合
============================================
网格：hold_days {5,10,15,20} × score_min {50,55,60} × slip {0,20}（股票/ETF）
基金：hold_days {5,10} × slip {5(C类),30(A类申赎费)}，score_min {40,50}
目标：滑点 20bps 下收益/夏普最高，或相对 0 滑点衰减最小
"""
import sys, json, time
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
sys.path.insert(0, str(BASE))
import short_engine as S
import v8_selector as V

t0 = time.time()
print("加载池…", flush=True)
stock_pool = S.load_stock_pool()
etf_pool = S.load_etf_pool()
fund_pool = S.load_fund_pool(3000)
print(f"池就绪（{time.time()-t0:.0f}s）", flush=True)

def run(name, pool, grid, kw_base):
    res = {}
    print(f"\n=== {name} ===", flush=True)
    for (h, sm, slip, extra) in grid:
        kw = dict(kw_base, hold_days=h, score_min=sm, slippage_bps=slip)
        kw.update(extra or {})
        eq, tr = S.run_short(pool, **kw)
        s = V.summary(eq, tr)
        key = f"H{h}_S{sm}_slip{slip}"
        res[key] = s
        print(f"  {key}: 收益 {s['total_return_pct']:>7.1f}% | 回撤 {s['max_drawdown_pct']:>6.2f}% | "
              f"夏普 {s['sharpe']:.3f} | 胜率 {s['win_rate_pct']:.1f}% | {s['total_trades']} 笔", flush=True)
    return res

grid_stock = [(h, sm, slip, None)
              for h in (5, 10, 15, 20) for sm in (50, 55, 60) for slip in (0, 20)]
grid_etf = [(h, sm, slip, None)
            for h in (10, 15, 20) for sm in (50, 55) for slip in (0, 20)]
grid_fund = [(5, 40, 5, None), (5, 40, 30, None), (10, 40, 5, None), (10, 40, 30, None),
             (5, 50, 5, None), (10, 50, 5, None)]

res = {
    "股票": run("股票", stock_pool, grid_stock, dict(top_n=10, reversal=True, ma5_exit=True)),
    "ETF": run("ETF", etf_pool, grid_etf, dict(top_n=10, ma5_exit=True, take_profit=0.12)),
    "基金": run("基金", fund_pool, grid_fund, dict(top_n=5, fund_mode=True)),
}
json.dump({k: {kk: {x: float(y) for x, y in vv.items()} for kk, vv in v.items()} for k, v in res.items()},
          open(BASE / "slip_opt_grid.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n✅ slip_opt_grid.json 已保存（{time.time()-t0:.0f}s）")
