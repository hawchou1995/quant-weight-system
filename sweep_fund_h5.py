# -*- coding: utf-8 -*-
"""基金 H5 v3 补充穷举（基金净值型 5 日轮动是甜蜜点）"""
import sys, json, time
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
sys.path.insert(0, str(BASE))
import short_engine as S
import v8_selector as V

t0 = time.time()
pool = S.load_fund_pool(3000)
print(f"基金池 {len(pool)} 只 ({time.time()-t0:.0f}s)", flush=True)

grid = [(5, 5, 40), (5, 5, 50), (8, 5, 40), (8, 5, 50), (10, 5, 40),
        (5, 10, 40), (8, 10, 40), (5, 3, 40), (8, 3, 40), (10, 3, 40)]
res = {}
for i, (tn, h, sm) in enumerate(grid):
    for tp in (0.0, 0.12):
        key = f"T{tn}_H{h}_S{sm}_M1_TP{int(tp*100)}_SL0"
        eq, tr = S.run_short(pool, top_n=tn, hold_days=h, score_min=sm,
                             fund_mode=True, ma5_exit=True, take_profit=tp)
        s = V.summary(eq, tr)
        res[key] = s
        print(f"[{len(res)}/20] {key}: 收益 {s['total_return_pct']}% | 回撤 {s['max_drawdown_pct']}% | "
              f"夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']}", flush=True)
json.dump({k: {kk: float(vv) for kk, vv in v.items()} for k, v in res.items()},
          open(BASE / "mix_fund_h5_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
best = max(res.items(), key=lambda kv: kv[1]["sharpe"])
print("BEST:", best[0], best[1])
