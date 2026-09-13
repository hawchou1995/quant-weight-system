# -*- coding: utf-8 -*-
"""E0 参数穷举 B1 段：top 网格臂相位审计 + MA 邻域加密 + 最优臂分年度/滑点。"""
import json
import time

import numpy as np
import pandas as pd

import r2_e0opt_0912 as E

R2 = E.R2
t0 = time.time()
out = json.load(open(R2 / "e0grid_0912.json", encoding="utf-8"))

TOPS = [
    ("A1=MA40+无stop+90",  dict(ma_p=40, stop_pct=None, maxhold=90)),
    ("A2=MA40+s15+90",     dict(ma_p=40, stop_pct=0.15, maxhold=90)),
    ("A3=MA40+s08+90",     dict(ma_p=40, stop_pct=0.08, maxhold=90)),
    ("A4=MA40+无stop+无限", dict(ma_p=40, stop_pct=None, maxhold=None)),
    ("A5=MA30+无stop+90",  dict(ma_p=30, stop_pct=None, maxhold=90)),
    ("A6=MA30+s08+60(基线MA改)", dict(ma_p=30, stop_pct=0.08, maxhold=60)),
]

# ---- 1. 相位审计：每臂 6 相位（已跑过则跳过）----
phase_med = out.get("_phase_audit", {})
if not phase_med:
    for name, kw in TOPS:
        tots, shrps, dds = [], [], []
        for off in (0, 7, 13, 20, 27, 33):
            r = E.run(f"PH_{name}_off{off}", offset=off, **kw)
            tots.append(r["total_pct"]); shrps.append(r["sharpe"]); dds.append(r["mdd_pct"])
        phase_med[name] = {"off0_total": tots[0], "phase_median_total": float(np.median(tots)),
                           "phase_min": min(tots), "phase_max": max(tots),
                           "phase_median_sharpe": float(np.median(shrps)), "phase_median_dd": float(np.median(dds))}
        print(f"[相位 {name}] off0 {tots[0]:.1f}% | 相位中位 {np.median(tots):.1f}% | "
              f"区间 [{min(tots):.1f}, {max(tots):.1f}] | 相位夏普中位 {np.median(shrps):.3f} | "
              f"相位回撤中位 {np.median(dds):.1f}%", flush=True)
    out["_phase_audit"] = phase_med
else:
    for name, kw in TOPS:
        print(f"[相位缓存 {name}] {phase_med[name]}", flush=True)

# ---- 2. MA 邻域加密（35/45）+ 基线对照（全部 h90+无stop 口径）----
for p in (35, 45):
    r = E.run(f"MA{p}_sx_h90", ma_p=p, stop_pct=None, maxhold=90)
    r.pop("eq", None)
    out[f"MA{p}_sx_h90"] = r
    print(f"[MA{p}+90+无stop] {r['total_pct']}% | 夏普 {r['sharpe']} | 回撤 {r['mdd_pct']}%", flush=True)

# ---- 3. 最优臂分年度 + 滑点敏感性 ----
r0 = E.run("A1_eq_forstats", ma_p=40, stop_pct=None, maxhold=90)
eq = np.array(r0["eq"])
days = pd.DatetimeIndex(E.ALL_DAYS)
eqs = pd.Series(eq, index=days)
yearly = {str(y): round(float(g.iloc[-1] / g.iloc[0] - 1) * 100, 2) for y, g in eqs.groupby(eqs.index.year)}
out["A1_yearly_pct"] = yearly
print(f"[A1 分年度] {yearly}", flush=True)
for slip in (0.0030, 0.0040):
    E.SLIP = slip
    r = E.run(f"A1_slip{int(slip*1e4)}", ma_p=40, stop_pct=None, maxhold=90)
    r.pop("eq", None)
    out[f"A1_slip{int(slip*1e4)}"] = r
    print(f"[A1 slip={int(slip*1e4)}bps] {r['total_pct']}% | 夏普 {r['sharpe']} | 回撤 {r['mdd_pct']}%", flush=True)
E.SLIP = 0.0020

json.dump(out, open(R2 / "e0grid_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
