# -*- coding: utf-8 -*-
"""单轨独享本金的资金敏感度（R-capsens-0915）。

背景（用户 2026-09-15 澄清）：实盘**只买一套**（轨A 或轨B），两轨并行 = 30 只 = "开超市"；
      两套模拟盘应**分开展示**，配额**可独立**。
故本脚本回答：**每条轨单独跑、在不同本金下的真实表现曲线**（整手约束随本金非线性生效）。

用法：python value_capsens_0915.py trackA|trackB
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OSS = os.path.join(HERE, "oss_0913")
os.chdir(OSS)
TRACK = sys.argv[1] if len(sys.argv) > 1 else "trackA"
OUT = os.path.join(HERE, f"value_capsens_{TRACK}_0915.json")
CAPS = [17000.0, 34000.0, 51000.0, 68000.0, 102000.0, 170000.0]

t0 = time.time()
if TRACK == "trackA":
    SRC = os.path.join(OSS, "satellite_opt_0913.py")
    src = open(SRC, encoding="utf-8").read()
    g = {"__file__": os.path.abspath(SRC), "__name__": "__capA"}
    exec(compile(src, SRC, "exec"), g)
    fn = lambda c0, off: g["run_ln"]("turn", 20, 30, off, use_gate=True, cash0=c0)
    N, F, name = 20, 30, "轨A（三低 turn + Top20 + 闸门）"
else:
    SRC = os.path.join(OSS, "oss_super_combo_0913.py")
    src = open(SRC, encoding="utf-8").read()
    g = {"__file__": os.path.abspath(SRC), "__name__": "__capB"}
    exec(compile(src.split("comp = composite()")[0], SRC, "exec"), g)
    comp = g["composite"]()
    fn = lambda c0, off: g["run_engine"](comp, 20, offset=off, cash0=c0)
    N, F, name = 20, g["F"], "轨B（SUPER 13 因子 + Top20）"
print(f"[capsens] {name} 引擎就绪 {time.time()-t0:.0f}s", flush=True)

print("=" * 100)
print(f"单轨独享本金 · 资金敏感度 — {name}（{N} 只 / F={F} / 9 相位中位）")
print("=" * 100)
print(f"{'本金':>9s} {'每只预算':>9s} {'年化':>8s} {'夏普':>7s} {'回撤':>8s} {'成交笔数':>8s} {'备注':>14s}")
res = {}
for c0 in CAPS:
    rs = [fn(c0, int(round(p * F / 9))) for p in range(9)]
    ann = float(np.median([r["ann"] for r in rs]))
    sh = float(np.median([r["sharpe"] for r in rs]))
    md = float(np.median([r["mdd"] for r in rs]))
    tr = int(np.median([r["n_trades"] for r in rs]))
    res[str(int(c0))] = dict(budget_per=c0 / N, ann=ann, sharpe=sh, mdd=md, trades=tr)
    note = "（当前配额）" if c0 == 17000 else ("（模拟盘总额）" if c0 == 68000 else "")
    print(f"{c0:>9.0f} {c0/N:>9.0f} {ann:>7.2%} {sh:>7.3f} {md:>7.2%} {tr:>8d} {note:>14s}", flush=True)

lo, hi = res["17000"], res["170000"]
print(f"\n  资金弹性：1.7万 → 17万：Δ年化 {hi['ann']-lo['ann']:+.2%}  Δ夏普 {hi['sharpe']-lo['sharpe']:+.3f}")
json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"  [capsens] 落盘 {OUT}")
