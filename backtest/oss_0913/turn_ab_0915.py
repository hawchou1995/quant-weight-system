# -*- coding: utf-8 -*-
"""轨A turn 第三因子选型 A/B（预注册 §五 turn 切换材料）
臂：base / turn(连续turn20) / avoid(二值 turn20>=10% 坏标记) / badfrac(近20日换手>=10%天数占比)
口径：与 satellite_opt_0913 完全同源（WARMUP=25 / 全池 / N20/F30 / 30 相位 / 100万 / 20bp）
前置：exec satellite_opt_0913.py 前缀（到"# ---- 复现基线"之前的全部定义）
"""
import sys, json, time
import numpy as np, pandas as pd
from pathlib import Path
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

src = open(OUT / "satellite_opt_0913.py", encoding="utf-8").read()
exec(src.split("# ---- 复现基线")[0])   # 拿到 P/cal/ELIG/rk_pct/RK/SCORE/ORDER/TOP/run_ln 等
log("harness loaded | elig/day:", float(ELIG[WARMUP:].sum(axis=1).mean()))

# ---- 新增 turn 家族变体 ----
TURNd = np.where(FMV > 0, AMT / FMV, np.nan)
bad_hi = np.where(np.isfinite(TURNd), (TURNd >= 0.10).astype(float), np.nan)          # 当日高换手(坏)标记
badfrac = pd.DataFrame(bad_hi).rolling(20, min_periods=10).mean().to_numpy()            # 近20日高换手天数占比
RK["avoid"] = rk_pct(bad_hi)      # 二值：坏标记 rank（0 -> 最小 rank -> 优先）
RK["badfrac"] = rk_pct(badfrac)   # 持续度：占比低者优先
VARIANTS["avoid"] = ["amt", "atr", "avoid"]
VARIANTS["badfrac"] = ["amt", "atr", "badfrac"]
SCORE, ORDER, TOP = {}, {}, {}
for v, ks in VARIANTS.items():
    s = np.zeros((ND, NC))
    for k in ks: s += np.where(np.isfinite(RK[k]), RK[k], np.nan)
    SCORE[v] = s
for v in VARIANTS:
    ORDER[v] = np.argsort(np.where(ELIG & np.isfinite(SCORE[v]), SCORE[v], np.inf), axis=1)
    TOP[v] = ORDER[v][:, :25]
log("variants:", list(VARIANTS.keys()))

# ---- 臂：N20/F30 全 30 相位（4 变体）+ 对照 turn N10/F60 ----
res = {}
for v in ["base", "turn", "avoid", "badfrac"]:
    shs, anns = [], []
    o0 = None
    for off in range(30):
        m = run_ln(v, 20, 30, off)
        shs.append(m["sharpe"]); anns.append(m["ann"])
        if off == 0: o0 = m
    res[v] = dict(N=20, F=30, phmed=float(np.median(shs)), phmin=float(min(shs)), phmax=float(max(shs)),
                  phmed_ann=float(np.median(anns)), n_neg=sum(1 for s in shs if s <= 0),
                  off0=dict(ann=o0["ann"], sharpe=o0["sharpe"], mdd=o0["mdd"], n_trades=o0["n_trades"], win=o0["win"]))
    log(f"{v:8s} N20/F30 | phmed S={res[v]['phmed']:.3f} (min {res[v]['phmin']:.2f}/max {res[v]['phmax']:.2f}, 负相位 {res[v]['n_neg']}) | off0 ann {o0['ann']*100:+.2f}% S={o0['sharpe']:.2f} mdd {o0['mdd']*100:.1f}%")

# 冠军对照：turn N10/F60（satellite_opt 最优先前臂之一）
shs = []
for off in range(60):
    shs.append(run_ln("turn", 10, 60, off)["sharpe"])
res["turn_N10_F60"] = dict(phmed=float(np.median(shs)), phmin=float(min(shs)), phmax=float(max(shs)))
log(f"turn N10/F60 对照 | phmed S={res['turn_N10_F60']['phmed']:.3f} (min {res['turn_N10_F60']['phmin']:.2f})")

best = max(["turn", "avoid", "badfrac"], key=lambda v: res[v]["phmed"])
log(f"A/B 结论: 第三因子最优形式 = {best}（phmed {res[best]['phmed']:.3f} vs 连续turn20 {res['turn']['phmed']:.3f}）")
json.dump(res, open(OUT / "turn_ab_0915.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved turn_ab_0915.json")
