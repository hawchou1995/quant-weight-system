# -*- coding: utf-8 -*-
"""定位差异：冻结 combo 脚本 vs 我的复现/生产模块 —— 逐层对比
层1: 13 因子数组（冻结 ALL vs prod S.ALL）
层2: composite（冻结 composite() vs prod COMP_SUPER）
层3: 引擎（同一 comp 过冻结 run_engine vs 我的 run_engine）
"""
import numpy as np, pandas as pd, time, sys
BASE_DIR = r"D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest/oss_0913"
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

# ---- 冻结脚本前缀（定义 ALL/picked/W/sign/ELIG3/composite/run_engine）----
src = open(BASE_DIR + "/oss_super_combo_0913.py", encoding="utf-8").read()
exec(src.split("comp = composite()")[0])
log("冻结定义载入 | picked", len(picked))
FROZEN_ALL = dict(ALL); FROZEN_PICKED = list(picked); FROZEN_W = dict(W)
frozen_composite = composite
frozen_run = run_engine

# ---- prod 模块 ----
sys.path.insert(0, BASE_DIR)
import oss_super_prod_0913 as S
log("prod 模块载入")

# 层1: 因子数组对比
log("== 层1: 因子数组 ==")
bad = []
for k in FROZEN_PICKED:
    a, b = FROZEN_ALL[k], S.ALL[k]
    if a.shape != b.shape: bad.append((k, 'shape', a.shape, b.shape)); continue
    m = np.isfinite(a) & np.isfinite(b)
    d = np.nanmax(np.abs(a[m] - b[m])) if m.sum() else np.nan
    mismatch = int((~np.isfinite(a) & np.isfinite(b)).sum() + (np.isfinite(a) & ~np.isfinite(b)).sum())
    if (np.isfinite(d) and d > 1e-9) or mismatch > 0:
        bad.append((k, 'diff', round(float(d), 6), 'nan_mismatch', mismatch))
log("层1 差异因子:", bad if bad else "无（13 因子数组完全一致）")

# 层2: composite 对比
log("== 层2: composite ==")
C1 = frozen_composite()
C2 = S.COMP_SUPER
m = np.isfinite(C1) & np.isfinite(C2)
d = np.nanmax(np.abs(C1[m] - C2[m])) if m.sum() else np.nan
n1 = int(np.isfinite(C1).sum()); n2 = int(np.isfinite(C2).sum())
disagree = int((np.isfinite(C1) != np.isfinite(C2)).sum())
log(f"冻结 composite: 有效 {n1} | prod COMP_SUPER: 有效 {n2} | 有限性不一致 {disagree} | 数值 max|diff| {d:.6g}")
if np.isfinite(d) and d > 1e-9:
    # 找出首个不一致日期
    rowmax = np.nanmax(np.abs(C1 - C2), axis=1)
    i = int(np.nanargmax(rowmax))
    log(f"最大差出现在 {cal[i]}（{rowmax[i]:.4f}）")

# 层3: 引擎对比（同一 comp 两种引擎, N=20 offset=0）
log("== 层3: 引擎 ==")
m1 = frozen_run(C1, 20, offset=0)
log(f"冻结引擎(冻结comp): ann {m1['ann']*100:+.2f}% S={m1['sharpe']:.3f}")
m2 = frozen_run(C2, 20, offset=0)
log(f"冻结引擎(prod comp): ann {m2['ann']*100:+.2f}% S={m2['sharpe']:.3f}  ← 若此条≈22.87% 则 composite 无差，问题在别处")
