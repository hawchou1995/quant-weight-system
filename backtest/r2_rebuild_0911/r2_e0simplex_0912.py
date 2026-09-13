# -*- coding: utf-8 -*-
"""E0 参数穷举 B2 段：权重向量全穷举。
B2a 基线口径：5 槽权重单纯形网格 1001（步长 10%）逐格跑 + 等权分位。
B2b A1 口径（MA40/无stop/90）：单纯形 1001 + Dirichlet 800 + top10 向量 4 相位审计。"""
import json
import time
from itertools import combinations

import numpy as np

import r2_e0opt_0912 as E

R2 = E.R2
t0 = time.time()
out = {"_meta": {"n_trials": 0}}

# 5 个非负整数和为 10 的全部组合 = C(14,4) = 1001 个权重向量（步长 10%）
VECS = []
for combo in combinations(range(14), 4):  # 星与杠：10 个球 4 根杠，位置 0..13
    v = [combo[0], combo[1] - combo[0] - 1, combo[2] - combo[1] - 1, combo[3] - combo[2] - 1, 13 - combo[3]]
    VECS.append([x / 10 for x in v])
assert len(VECS) == 1001 and all(abs(sum(v) - 1) < 1e-9 for v in VECS)


def simplex_run(kw, tag):
    res = []
    for i, w in enumerate(VECS):
        E._RW_OVERRIDE = w
        r = E.run(f"{tag}{i}", **kw)
        res.append((r["total_pct"], r["sharpe"], r["mdd_pct"], i, w))
    E._RW_OVERRIDE = None
    return res


# ---- B2a 基线口径单纯形 1001 ----
t0a = time.time()
res_base = simplex_run(dict(npos=5, shape="eq"), "SXb")
tot = np.array([x[0] for x in res_base]); shp = np.array([x[1] for x in res_base])
eq_rank_t = float((tot < 121.05).mean())   # 等权在单纯形中的收益分位
best_i = int(np.argmax(tot))
out["B2a_simplex_baseline"] = {
    "n": len(res_base), "equal_weight_total": 121.05, "equal_weight_pct_rank": round(eq_rank_t, 3),
    "best_total": round(float(tot.max()), 2), "best_vec": res_base[best_i][4],
    "median_total": round(float(np.median(tot)), 2), "p95_total": round(float(np.quantile(tot, 0.95)), 2),
    "median_sharpe": round(float(np.median(shp)), 3), "p95_sharpe": round(float(np.quantile(shp, 0.95)), 3),
}
print(f"[B2a 基线单纯形 1001] 等权 121.05% 位于分位 {eq_rank_t:.3f} | 最优 {tot.max():.1f}% "
      f"vec={res_base[best_i][4]} | 中位 {np.median(tot):.1f}% p95 {np.quantile(tot,0.95):.1f}% | "
      f"夏普中位 {np.median(shp):.3f} p95 {np.quantile(shp,0.95):.3f} ({time.time()-t0a:.0f}s)", flush=True)
json.dump(out, open(R2 / "e0simplex_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ---- B2b A1 口径（MA40/无stop/90）单纯形 1001 + Dirichlet 800 ----
KW_A1 = dict(ma_p=40, stop_pct=None, maxhold=90)
t0b = time.time()
res_a1 = simplex_run(dict(npos=5, shape="eq", **KW_A1), "SXa")
tot2 = np.array([x[0] for x in res_a1]); shp2 = np.array([x[1] for x in res_a1])
best2 = int(np.argmax(tot2))
out["B2b_simplex_A1"] = {
    "n": len(res_a1), "equal_weight_total": 338.06,
    "equal_weight_pct_rank": round(float((tot2 < 338.06).mean()), 3),
    "best_total": round(float(tot2.max()), 2), "best_vec": res_a1[best2][4],
    "median_total": round(float(np.median(tot2)), 2), "p95_total": round(float(np.quantile(tot2, 0.95)), 2),
    "median_sharpe": round(float(np.median(shp2)), 3), "p95_sharpe": round(float(np.quantile(shp2, 0.95)), 3),
}
print(f"[B2b A1单纯形 1001] 等权 338.06% 分位 {(tot2<338.06).mean():.3f} | 最优 {tot2.max():.1f}% "
      f"vec={res_a1[best2][4]} | 中位 {np.median(tot2):.1f}% p95 {np.quantile(tot2,0.95):.1f}% "
      f"({time.time()-t0b:.0f}s)", flush=True)

rng = np.random.default_rng(40912)
plc_t, plc_s = [], []
for it in range(800):
    E._RW_OVERRIDE = rng.dirichlet(np.ones(5))
    r = E.run(f"DRC{it}", npos=5, shape="eq", **KW_A1)
    plc_t.append(r["total_pct"]); plc_s.append(r["sharpe"])
E._RW_OVERRIDE = None
plc_t = np.array(plc_t); plc_s = np.array(plc_s)
out["B2b_dirichlet_A1"] = {"n": 800, "median_total": round(float(np.median(plc_t)), 2),
                           "p95_total": round(float(np.quantile(plc_t, 0.95)), 2),
                           "median_sharpe": round(float(np.median(plc_s)), 3),
                           "p95_sharpe": round(float(np.quantile(plc_s, 0.95)), 3),
                           "equal_weight_p_total": round(float((plc_t >= 338.06).mean()), 4)}
print(f"[B2b A1 Dirichlet 800] 中位 {np.median(plc_t):.1f}% p95 {np.quantile(plc_t,0.95):.1f}% | "
      f"等权 338.06% 的 p={(plc_t>=338.06).mean():.4f}", flush=True)

# ---- top10 A1 向量相位审计（4 相位中位）----
order = np.argsort(-tot2)[:10]
top_phase = []
for idx in order:
    w = res_a1[idx][4]
    E._RW_OVERRIDE = w
    meds = []
    for off in (0, 7, 13, 20):
        r = E.run(f"PHS{idx}_{off}", npos=5, shape="eq", offset=off, **KW_A1)
        meds.append(r["total_pct"])
    E._RW_OVERRIDE = None
    top_phase.append({"vec": w, "off0": round(float(tot2[idx]), 2), "phase_median": round(float(np.median(meds)), 2)})
    print(f"[A1 top vec {res_a1[idx][4]}] off0 {tot2[idx]:.1f}% | 相位中位 {np.median(meds):.1f}%", flush=True)
out["B2b_top_phase"] = top_phase
out["_meta"]["n_trials"] = 1001 + 1001 + 800 + 40
json.dump(out, open(R2 / "e0simplex_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
