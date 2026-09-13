# -*- coding: utf-8 -*-
"""E0 参数穷举 C 段：极值权重向量的相位终审。
top1=[0,0.1,0,0.9,0]（A1口径 off0 1502.6%）8 相位 vs Dirichlet 120 向量×4 相位的相位中位分布。"""
import json
import time

import numpy as np

import r2_e0opt_0912 as E

R2 = E.R2
t0 = time.time()
out = json.load(open(R2 / "e0simplex_0912.json", encoding="utf-8"))
KW_A1 = dict(ma_p=40, stop_pct=None, maxhold=90)

# ---- 1. 等权与 top1 的 8 相位 ----
for tag, w in (("equal", None), ("top1", [0.0, 0.1, 0.0, 0.9, 0.0])):
    tots = []
    for off in (0, 5, 10, 15, 20, 25, 30, 35):
        E._RW_OVERRIDE = w
        r = E.run(f"C_{tag}_{off}", npos=5, shape="eq", offset=off, **KW_A1)
        tots.append(r["total_pct"])
    E._RW_OVERRIDE = None
    print(f"[{tag} 8相位] off0 {tots[0]:.1f}% | 中位 {np.median(tots):.1f}% | 区间 [{min(tots):.1f}, {max(tots):.1f}]", flush=True)
    out[f"C_phase_{tag}"] = {"tots": tots, "median": round(float(np.median(tots)), 2)}

# ---- 2. Dirichlet 120 向量 × 4 相位 → 相位中位分布 ----
rng = np.random.default_rng(512)
meds = []
for it in range(120):
    w = rng.dirichlet(np.ones(5))
    ph = []
    for off in (0, 7, 13, 20):
        E._RW_OVERRIDE = w
        r = E.run(f"CD{it}_{off}", npos=5, shape="eq", offset=off, **KW_A1)
        ph.append(r["total_pct"])
    E._RW_OVERRIDE = None
    meds.append(float(np.median(ph)))
meds = np.array(meds)
p_top1 = float((meds >= out["C_phase_top1"]["median"]).mean())
p_eq = float((meds >= out["C_phase_equal"]["median"]).mean())
out["C_dirichlet_phase_median"] = {"n": 120, "median_of_medians": round(float(np.median(meds)), 2),
                                   "p95": round(float(np.quantile(meds, 0.95)), 2),
                                   "max": round(float(meds.max()), 2),
                                   "p_top1_ge": round(p_top1, 4), "p_equal_ge": round(p_eq, 4)}
print(f"[Dirichlet 120×4 相位中位] 中位 {np.median(meds):.1f}% p95 {np.quantile(meds,0.95):.1f}% "
      f"max {meds.max():.1f}% | top1 相位中位 {out['C_phase_top1']['median']}% → p={p_top1:.4f} | "
      f"等权相位中位 {out['C_phase_equal']['median']}% → p={p_eq:.4f}", flush=True)

json.dump(out, open(R2 / "e0simplex_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
