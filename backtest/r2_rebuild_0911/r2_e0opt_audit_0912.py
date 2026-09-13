# -*- coding: utf-8 -*-
"""收尾审计：E0 滑点敏感性(30/40bps) + 分年度分解 + M7(N7) 随机权重安慰剂 500。"""
import json
import time

import numpy as np
import pandas as pd

import r2_e0opt_0912 as E

R2 = E.R2
out = {}

# ---- 1. 滑点敏感性（E0 基线口径 rebal20 N5 等权）----
for slip in (0.0030, 0.0040):
    E.SLIP = slip
    r = E.run(f"E0滑点{int(slip*1e4)}bps", npos=5, shape="eq")
    r.pop("eq", None)
    out[f"E0_slip{int(slip*1e4)}"] = r
    print(f"[E0 slip={int(slip*1e4)}bps] {r['total_pct']}% | 年化 {r['ann_pct']}% | 回撤 {r['mdd_pct']}% | "
          f"夏普 {r['sharpe']}", flush=True)
E.SLIP = 0.0020
r0 = E.run("E0_base_for_yearly", npos=5, shape="eq")
eq = np.array(r0["eq"])
out["E0_slip20"] = {k: v for k, v in r0.items() if k != "eq"}

# ---- 2. 分年度 ----
days = pd.DatetimeIndex(E.ALL_DAYS)
eqs = pd.Series(eq, index=days)
yearly = {}
for y, g in eqs.groupby(eqs.index.year):
    yearly[str(y)] = round(float(g.iloc[-1] / g.iloc[0] - 1) * 100, 2)
out["E0_yearly_pct"] = yearly
print(f"[E0 分年度] {yearly}", flush=True)

# ---- 3. M7 随机权重安慰剂（N7 Dirichlet 500 次）----
rng = np.random.default_rng(912)
plc = []
t0p = time.time()
for it in range(500):
    E._RW_OVERRIDE = rng.dirichlet(np.ones(7))
    r = E.run(f"plc7_{it}", npos=7, shape="eq")
    plc.append((r["sharpe"], r["total_pct"]))
E._RW_OVERRIDE = None
plc = np.array(plc)
m7 = out_m7 = json.load(open(R2 / "e0opt_final_0912.json", encoding="utf-8"))["M7=R20动量N7"]
out["M7_placebo"] = {
    "n": 500, "sharpe_median": round(float(np.median(plc[:, 0])), 3),
    "sharpe_p95": round(float(np.quantile(plc[:, 0], 0.95)), 3),
    "total_median": round(float(np.median(plc[:, 1])), 2),
    "p_sharpe": float((plc[:, 0] >= m7["sharpe"]).mean()),
    "p_total": float((plc[:, 1] >= m7["total_pct"]).mean()),
}
print(f"[M7安慰剂N7x500] 夏普中位 {np.median(plc[:,0]):.3f} p95 {np.quantile(plc[:,0],0.95):.3f} | "
      f"收益中位 {np.median(plc[:,1]):.1f}% | M7 target {m7['sharpe']}/{m7['total_pct']}% → "
      f"p_sharpe={out['M7_placebo']['p_sharpe']:.4f} p_total={out['M7_placebo']['p_total']:.4f}", flush=True)

json.dump(out, open(R2 / "e0opt_audit_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"总耗时 {time.time()-t0p:.0f}s", flush=True)
