# -*- coding: utf-8 -*-
"""资金容量曲线：两轨在各现金档（3.4w/6.8w/17w/100w）下的表现（offsets 0..9 子集，相位中位）"""
import numpy as np, pandas as pd, json, time, sys
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:5.1f}s]", *a, flush=True)
_full = open("dual_track_combined_0915.py", encoding="utf-8").read()
exec(_full.split("# ---- 任务3b")[0])          # 头部 + 轨A 引擎（内部已 exec unify 前缀）
exec("# ---- 轨B 引擎" + _full.split("# ---- 轨B 引擎")[1].split("# ---- 任务4")[0])
log("两引擎就绪")

LEVELS = [34000.0, 68000.0, 170000.0, 1_000_000.0]
res = {"trackA_cand4": {}, "trackB_pct40": {}}
for cash0 in LEVELS:
    for tag, fn in [("trackA_cand4", lambda o, c=cash0: run_A(o, use_gate=True, exit_pct40=True, cash0=c)),
                    ("trackB_pct40", lambda o, c=cash0: run_B_eq(o, cash0=c))]:
        shs, anns = [], []
        for o in range(10):
            s = stats(fn(o)); shs.append(s["sharpe"]); anns.append(s["ann"])
        res[tag][f"{int(cash0)}"] = dict(sharpe=float(np.median(shs)), ann=float(np.median(anns)))
        log(f"{tag:13s} cash={int(cash0):>9,} | phmed(0..9) S={np.median(shs):.3f} | ann {np.median(anns)*100:+.2f}%")
json.dump(res, open("capacity_curve_0915.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved capacity_curve_0915.json")
