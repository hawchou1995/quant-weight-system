# -*- coding: utf-8 -*-
"""S2 迁移测试（R-structure-S2-0915）：把「低换手」结构测到在产轨A/轨B。

问题：结构分解（value_structure_0915）显示随机基线上「年度 vs 月度」贡献 +0.297 夏普，
      但那是**价值因子池**。三轨用**价量因子**（短周期衰减）→ 低换手能否迁移未知。
      既有反例：FB3-H20 拉长到 40/60 已衰减。
做法：在轨A 真实引擎（satellite_opt_0913.run_ln，生产配置 turn+N20+闸门）上扫调仓周期 F。
纪律：**只测不改**（生产参数 REBAL_LN=30 不动）。
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OSS = os.path.join(HERE, "oss_0913")
F_SCRIPT = os.path.join(OSS, "satellite_opt_0913.py")
OUT = os.path.join(HERE, "value_s2_trackA_0915.json")

os.chdir(OSS)                      # 上游脚本用相对路径读 data_*
t0 = time.time()
src = open(F_SCRIPT, encoding="utf-8").read()
g = {"__file__": os.path.abspath(F_SCRIPT), "__name__": "__s2__"}
exec(compile(src, F_SCRIPT, "exec"), g)
run_ln = g["run_ln"]
print(f"[s2] 引擎就绪 {time.time()-t0:.0f}s", flush=True)

VAR, N_TOP, GATE = "turn", 20, True     # 生产轨A：三低 turn + Top20 + 闸门
res = {}
print("=" * 100)
print("S2 轨A 迁移测试 · 生产配置 turn/N20/闸门 · 扫调仓周期 F（单位：交易日）")
print("=" * 100)
print(f"{'F':>6s} {'年化中位':>10s} {'夏普中位':>10s} {'相位区间':>16s} {'回撤中位':>10s} {'off0年化':>10s}")
for F in (30, 60, 125, 250):
    sh, an, dd, r0 = [], [], [], None
    for p in range(9):
        off = int(round(p * F / 9))
        r = run_ln(VAR, N_TOP, F, off, use_gate=GATE)
        sh.append(r["sharpe"]); an.append(r["ann"]); dd.append(r["mdd"])
        if p == 0:
            r0 = r
    rec = dict(F=F, ann_med=float(np.median(an)), sharpe_med=float(np.median(sh)),
               sharpe_min=float(np.min(sh)), sharpe_max=float(np.max(sh)),
               mdd_med=float(np.median(dd)), off0_ann=float(r0["ann"]),
               off0_sharpe=float(r0["sharpe"]), off0_mdd=float(r0["mdd"]),
               off0_trades=int(r0.get("n_trades", r0.get("trades", 0))))
    res[str(F)] = rec
    tag = "（现产）" if F == 30 else ""
    print(f"{F:>6d} {rec['ann_med']:>9.2%} {rec['sharpe_med']:>10.3f} "
          f"{rec['sharpe_min']:>7.2f}~{rec['sharpe_max']:<6.2f} {rec['mdd_med']:>9.2%} "
          f"{rec['off0_ann']:>9.2%} {tag}", flush=True)

base = res["30"]
best = max(res.values(), key=lambda r: r["sharpe_med"])
print("\n" + "=" * 100)
print(f"裁决：现产 F=30 phmed {base['sharpe_med']:.3f}（年化 {base['ann_med']:.2%}）")
print(f"      最优 F={best['F']} phmed {best['sharpe_med']:.3f}（年化 {best['ann_med']:.2%}）"
      f"  → Δ夏普 {best['sharpe_med']-base['sharpe_med']:+.3f}  Δ年化 {best['ann_med']-base['ann_med']:+.2%}")
print("=" * 100)
json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"[s2] 落盘 {OUT}")
