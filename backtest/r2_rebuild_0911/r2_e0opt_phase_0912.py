# -*- coding: utf-8 -*-
"""相位稳定性审计：rebal 相位平移扫描，检验 R40 是否跨相位稳健（vs R20 对照）。"""
import json
import time

import numpy as np

import r2_e0opt_0912 as E

R2 = E.R2
t0 = time.time()
out = {}

# R40 全相位 8 个 + R20 对照相位 8 个 + R30/R50/R60 抽查 4 个相位
PLAN = (
    [("R40", 40, o) for o in (0, 5, 10, 15, 20, 25, 30, 35)]
    + [("R20", 20, o) for o in (0, 3, 7, 10, 13, 16)]
    + [("R30", 30, o) for o in (0, 7, 15, 22)]
    + [("R50", 50, o) for o in (0, 12, 25, 37)]
    + [("R60", 60, o) for o in (0, 15, 30, 45)]
)

for name, rebal, off in PLAN:
    arm = f"PH{name}_off{off}"
    r = E.run(arm, npos=5, shape="eq", rebal=rebal, offset=off)
    r.pop("eq", None)
    out[arm] = r
    print(f"[{arm}] {r['total_pct']}% | 年化 {r['ann_pct']}% | 回撤 {r['mdd_pct']}% | 夏普 {r['sharpe']} | "
          f"{r['n_trades']}笔 胜率{r['win_rate']}%", flush=True)

for k in ("R20", "R30", "R40", "R50", "R60"):
    tots = [v["total_pct"] for n, v in out.items() if n.startswith(f"PH{k}_off")]
    shrp = [v["sharpe"] for n, v in out.items() if n.startswith(f"PH{k}_off")]
    dds = [v["mdd_pct"] for n, v in out.items() if n.startswith(f"PH{k}_off")]
    print(f"[相位汇总 {k}] 总收益: 中位 {np.median(tots):.1f}% 区间 [{min(tots):.1f}, {max(tots):.1f}] | "
          f"夏普中位 {np.median(shrp):.3f} | 回撤中位 {np.median(dds):.1f}%", flush=True)

json.dump(out, open(R2 / "e0opt_phase_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
