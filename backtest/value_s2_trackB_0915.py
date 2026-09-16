# -*- coding: utf-8 -*-
"""S2 迁移测试 · 轨B（SUPER 13 因子）：扫调仓周期 F。

口径：exec `oss_super_combo_0913.py` 到已验证安全的锚点 `comp = composite()`（run_engine 定义在锚点之前），
      取得 run_engine + composite，然后**覆盖模块常量 F** 重跑（F 在 run_engine 内是全局查表）。
纪律：只测不改（生产 F=20 不动）。
"""
import json
import os
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OSS = os.path.join(HERE, "oss_0913")
SRC = os.path.join(OSS, "oss_super_combo_0913.py")
OUT = os.path.join(HERE, "value_s2_trackB_0915.json")

os.chdir(OSS)
t0 = time.time()
src = open(SRC, encoding="utf-8").read()
anchor = "comp = composite()"
assert anchor in src, "锚点未命中"
head = src.split(anchor)[0]
g = {"__file__": os.path.abspath(SRC), "__name__": "__s2b__"}
exec(compile(head, SRC, "exec"), g)
for need in ("run_engine", "composite", "F", "ELIG3", "WARMUP"):
    assert need in g, f"缺少 {need}"
print(f"[s2b] 引擎就绪 {time.time()-t0:.0f}s｜生产 F={g['F']}", flush=True)

comp = g["composite"]()
N_TOP = 20
res = {}
print("=" * 100)
print("S2 轨B 迁移测试 · SUPER 13 因子 / Top20 · 扫调仓周期 F")
print("=" * 100)
print(f"{'F':>6s} {'年化中位':>10s} {'夏普中位':>10s} {'相位区间':>16s} {'回撤中位':>10s} {'off0年化':>10s} {'off0夏普':>9s}")
for F in (20, 60, 125):
    g["F"] = F
    sh, an, dd, r0 = [], [], [], None
    for p in range(9):
        off = int(round(p * F / 9))
        r = g["run_engine"](comp, N_TOP, offset=off)
        sh.append(r["sharpe"]); an.append(r["ann"]); dd.append(r["mdd"])
        if p == 0:
            r0 = r
    rec = dict(F=F, ann_med=float(np.median(an)), sharpe_med=float(np.median(sh)),
               sharpe_min=float(np.min(sh)), sharpe_max=float(np.max(sh)),
               mdd_med=float(np.median(dd)), off0_ann=float(r0["ann"]),
               off0_sharpe=float(r0["sharpe"]), off0_mdd=float(r0["mdd"]),
               off0_trades=int(r0.get("n_trades", 0)))
    res[str(F)] = rec
    tag = "（现产）" if F == 20 else ""
    print(f"{F:>6d} {rec['ann_med']:>9.2%} {rec['sharpe_med']:>10.3f} "
          f"{rec['sharpe_min']:>7.2f}~{rec['sharpe_max']:<6.2f} {rec['mdd_med']:>9.2%} "
          f"{rec['off0_ann']:>9.2%} {rec['off0_sharpe']:>9.3f} {tag}", flush=True)

base = res["20"]
best = max(res.values(), key=lambda r: r["sharpe_med"])
print("\n" + "=" * 100)
print(f"裁决：现产 F=20 phmed {base['sharpe_med']:.3f}（年化 {base['ann_med']:.2%}）")
print(f"      最优 F={best['F']} phmed {best['sharpe_med']:.3f}（年化 {best['ann_med']:.2%}）"
      f"  → Δ夏普 {best['sharpe_med']-base['sharpe_med']:+.3f}  Δ年化 {best['ann_med']-base['ann_med']:+.2%}")
print("=" * 100)
json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"[s2b] 落盘 {OUT}")
