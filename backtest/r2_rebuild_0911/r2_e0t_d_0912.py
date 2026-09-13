# -*- coding: utf-8 -*-
"""E0 T 族终审 D 段：LLV30/40 vs MA20 基线的 12 相位配对检验 + 组合臂 + 分年度/滑点。"""
import json
import time

import numpy as np
import pandas as pd

import r2_e0opt_0912 as E

R2 = E.R2
t0 = time.time()
out = json.load(open(R2 / "e0t_0912.json", encoding="utf-8"))
OFFS = tuple(range(0, 40, 3))  # 12 相位（rebal=20 时 offset 0..19 有效，取 0,3,...,18 + 20..39 映射回模20）

# rebal=20 → offset 应取模 20；12 个不同相位用 0..19 中均匀 12 个
OFFS = (0, 2, 4, 6, 8, 10, 12, 14, 16, 18)  # 10 相位全覆盖（mod 20）

def phase_scan(kw, tag):
    tots = []
    for off in OFFS:
        r = E.run(f"D_{tag}_{off}", offset=off, **kw)
        tots.append(r["total_pct"])
    return tots

base_kw = dict()                       # MA20/−8%/60
llv30_kw = dict(exit_mode="llv", llv_p=30)
llv40_kw = dict(exit_mode="llv", llv_p=40)

ph_base = phase_scan(base_kw, "base")
ph_l30 = phase_scan(llv30_kw, "llv30")
ph_l40 = phase_scan(llv40_kw, "llv40")
diff30 = np.array(ph_l30) - np.array(ph_base)
diff40 = np.array(ph_l40) - np.array(ph_base)
res = {
    "offs": list(OFFS), "base": ph_base, "llv30": ph_l30, "llv40": ph_l40,
    "llv30_median": round(float(np.median(ph_l30)), 2), "base_median": round(float(np.median(ph_base)), 2),
    "llv40_median": round(float(np.median(ph_l40)), 2),
    "diff30_median": round(float(np.median(diff30)), 2), "diff30_pos_ratio": round(float((diff30 > 0).mean()), 3),
    "diff40_median": round(float(np.median(diff40)), 2), "diff40_pos_ratio": round(float((diff40 > 0).mean()), 3),
}
print(f"[12相位 base ] {ph_base} 中位 {np.median(ph_base):.1f}%", flush=True)
print(f"[12相位 llv30] {ph_l30} 中位 {np.median(ph_l30):.1f}%", flush=True)
print(f"[12相位 llv40] {ph_l40} 中位 {np.median(ph_l40):.1f}%", flush=True)
print(f"[配对差 llv30-base] 中位 {np.median(diff30):.1f}pp | 正差比例 {(diff30>0).mean():.2f} | 差值 {diff30.round(1)}", flush=True)
print(f"[配对差 llv40-base] 中位 {np.median(diff40):.1f}pp | 正差比例 {(diff40>0).mean():.2f}", flush=True)

# 组合臂：LLV30 + 5% 硬止损（回撤修复尝试）+ LLV20 折中档
for name, kw in (("D_LLV30_stop5", dict(exit_mode="llv", llv_p=30, stop_pct=0.05)),
                 ("D_LLV20_stop5", dict(exit_mode="llv", llv_p=20, stop_pct=0.05)),
                 ("D_LLV25", dict(exit_mode="llv", llv_p=25))):
    r = E.run(name, **kw)
    r.pop("eq", None)
    out[name] = r
    print(f"[{name}] {r['total_pct']}% | 夏普 {r['sharpe']} | 回撤 {r['mdd_pct']}", flush=True)

# 最优组合臂相位
r0 = E.run("D_LLV30stop5_stats", exit_mode="llv", llv_p=30, stop_pct=0.05)
eq = np.array(r0["eq"])
days = pd.DatetimeIndex(E.ALL_DAYS)
eqs = pd.Series(eq, index=days)
yearly = {str(y): round(float(g.iloc[-1] / g.iloc[0] - 1) * 100, 2) for y, g in eqs.groupby(eqs.index.year)}
out["D_yearly_LLV30stop5"] = yearly
print(f"[LLV30+stop5 分年度] {yearly}", flush=True)
E.SLIP = 0.0030
r = E.run("D_LLV30stop5_s30", exit_mode="llv", llv_p=30, stop_pct=0.05)
r.pop("eq", None)
out["D_LLV30stop5_slip30"] = r
print(f"[LLV30+stop5 slip30] {r['total_pct']}% | 夏普 {r['sharpe']} | 回撤 {r['mdd_pct']}", flush=True)
E.SLIP = 0.0020

out["_D_phase"] = res
json.dump(out, open(R2 / "e0t_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
