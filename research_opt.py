# -*- coding: utf-8 -*-
"""文章启发优化穷举（v5.11.10 研究稿）——股票短线池
============================================
对照文章2（小止盈高胜率）/ 文章8（天量剔除），全部含 20bps 滑点：
基准：T10/H10/S55 反转+MA5
变体：小止盈（TP2-5%/SL3-5%）× 持有期 5/10 + 天量剔除 20 日
"""
import sys, json, time
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
sys.path.insert(0, str(BASE))
import short_engine as S
import v8_selector as V

t0 = time.time()
pool = S.load_stock_pool()
print(f"股票池 {len(pool)} 只 ({time.time()-t0:.0f}s)", flush=True)

GRID = [
    ("基准 H10/S55/MA5",           dict(top_n=10, hold_days=10, score_min=55, reversal=True, ma5_exit=True)),
    ("文2小止盈 TP3%/SL5% H10",     dict(top_n=10, hold_days=10, score_min=55, reversal=True, ma5_exit=True, take_profit=0.03, stop_loss=0.05)),
    ("文2小止盈 TP2%/SL5% H5",      dict(top_n=10, hold_days=5,  score_min=55, reversal=True, ma5_exit=True, take_profit=0.02, stop_loss=0.05)),
    ("文2小止盈 TP3%/SL5% H5",      dict(top_n=10, hold_days=5,  score_min=55, reversal=True, ma5_exit=True, take_profit=0.03, stop_loss=0.05)),
    ("文2小止盈 TP5%/SL7% H10",     dict(top_n=10, hold_days=10, score_min=55, reversal=True, ma5_exit=True, take_profit=0.05, stop_loss=0.07)),
    ("文8天量剔除20日 H10",         dict(top_n=10, hold_days=10, score_min=55, reversal=True, ma5_exit=True, sky_vol_filter=20)),
    ("组合 TP3%+天量剔除 H10",      dict(top_n=10, hold_days=10, score_min=55, reversal=True, ma5_exit=True, take_profit=0.03, stop_loss=0.05, sky_vol_filter=20)),
    ("组合 TP2%/SL5% H5+天量剔除",  dict(top_n=10, hold_days=5,  score_min=55, reversal=True, ma5_exit=True, take_profit=0.02, stop_loss=0.05, sky_vol_filter=20)),
]

res = {}
for label, kw in GRID:
    t1 = time.time()
    eq, tr = S.run_short(pool, slippage_bps=20, **kw)
    s = V.summary(eq, tr)
    res[label] = s
    print(f"{label}: 收益 {s['total_return_pct']:>7.1f}% | 回撤 {s['max_drawdown_pct']:>6.2f}% | "
          f"夏普 {s['sharpe']:.3f} | 胜率 {s['win_rate_pct']:.1f}% | {s['total_trades']} 笔 ({time.time()-t1:.0f}s)", flush=True)

json.dump({k: {kk: float(vv) for kk, vv in v.items()} for k, v in res.items()},
          open(BASE / "research_opt_grid.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n✅ research_opt_grid.json 已保存（{time.time()-t0:.0f}s）")
