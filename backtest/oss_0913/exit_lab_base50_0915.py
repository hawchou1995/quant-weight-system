# -*- coding: utf-8 -*-
"""补跑：两轨 BASE@50bp（验收门同档对比）"""
import numpy as np, pandas as pd, json, time, math
from pathlib import Path
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

# 轨A：satellite_opt 前缀（含 run_ln）
exec(open(OUT / "satellite_opt_0913.py", encoding="utf-8").read().split("# ---- 复现基线")[0])
shs, anns = [], []
for off in range(30):
    m = run_ln("turn", 20, 30, off, slip=0.005)
    shs.append(m["sharpe"]); anns.append(m["ann"])
resA = dict(phmed=float(np.median(shs)), phmin=float(min(shs)), ann_med=float(np.median(anns)))
log(f"轨A BASE@50bp | phmed S={resA['phmed']:.3f} (min {resA['phmin']:.2f}) ann_med {resA['ann_med']*100:+.2f}%")

# 轨B：fib_combo 全文件（含 run_engine；其自带臂会重跑 ~13s）
exec(open(OUT / "fib_combo_0914.py", encoding="utf-8").read())
shs, anns = [], []
for off in range(20):
    m = run_engine(S.COMP_SUPER, 20, offset=off, slip=0.005)
    shs.append(m["sharpe"]); anns.append(m["ann"])
resB = dict(phmed=float(np.median(shs)), phmin=float(min(shs)), ann_med=float(np.median(anns)))
log(f"轨B BASE@50bp | phmed S={resB['phmed']:.3f} (min {resB['phmin']:.2f}) ann_med {resB['ann_med']*100:+.2f}%")

json.dump(dict(trackA_base_50bp=resA, trackB_base_50bp=resB),
          open(OUT / "exit_lab_base50_0915.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved exit_lab_base50_0915.json")
