# -*- coding: utf-8 -*-
"""S2c 交叠容量评估（R-structure-S2c-0915）：去重后持仓数 + 整手可执行性。

问题：12 相位交叠 = 12 × Top20 = 240 个持仓位次，但相位间选股高度重叠 → 实际去重持仓数未知。
方法：对每个交易日，取 12 个相位各自"最近一次调仓选出的 Top20"，做并集 → U(d)。
      再做资金校验：单标的可用金额 = 配额 / U，需 ≥ 100股 × 现价（整手）+ 最低佣金 5 元。
口径：只读，不改任何生产文件。
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OSS = os.path.join(HERE, "oss_0913")
os.chdir(OSS)
TRACK = sys.argv[1] if len(sys.argv) > 1 else "trackA"
OUT = os.path.join(HERE, f"value_s2c_{TRACK}_0915.json")

CAP_A, CAP_B = 17000.0, 51000.0       # 生产配额（satellite_paper meta: cash_a/cash_b）


def union_counts(sel_by_phase, dates, phases_offsets, rebal):
    """sel_by_phase[k][di] = 该相位在 di 调仓时选中的列索引集合；返回每个交易日的并集大小。"""
    U = np.zeros(len(dates), dtype=int)
    last = {k: None for k in range(len(phases_offsets))}
    plan = {k: set(range(off, len(dates), rebal)) for k, off in enumerate(phases_offsets)}
    for di in range(len(dates)):
        for k in range(len(phases_offsets)):
            if di in plan[k]:
                last[k] = sel_by_phase[k].get(di)
        s = set()
        for k in range(len(phases_offsets)):
            if last[k]:
                s |= last[k]
        U[di] = len(s)
    return U


t0 = time.time()
if TRACK == "trackA":
    SRC = os.path.join(OSS, "satellite_opt_0913.py")
    src = open(SRC, encoding="utf-8").read()
    g = {"__file__": os.path.abspath(SRC), "__name__": "__s2cA__"}
    exec(compile(src, SRC, "exec"), g)
    ORDER, ELIG = g["ORDER"], g["ELIG"]
    cal = g["cal"]; codes = g["codes"]
    F, N_TOP, GATE = 30, 20, True
    print(f"[s2c] 轨A 引擎就绪 {time.time()-t0:.0f}s（F={F} Top{N_TOP} 闸门={GATE}）", flush=True)

    class _O:  # ORDER 的薄包装：把「argsort 索引」转成「按 ELIG 过滤后取前 N」
        def __init__(self, order, elig, n):
            self.order, self.elig, self.n = order, elig, n
        def __getitem__(self, di):
            r = self.order[di]
            ok = [int(ci) for ci in r[:self.n * 3] if self.elig[di, int(ci)]]
            return np.array(ok[:self.n])
    base_order = _O(ORDER["turn"], ELIG, N_TOP)
else:
    SRC = os.path.join(OSS, "oss_super_combo_0913.py")
    src = open(SRC, encoding="utf-8").read()
    head = src.split("comp = composite()")[0]
    g = {"__file__": os.path.abspath(SRC), "__name__": "__s2cB__"}
    exec(compile(head, SRC, "exec"), g)
    comp, F = g["composite"](), g["F"]
    ELIG3 = g["ELIG3"]; cal = g["cal"]; codes = g["codes"]
    ND = comp.shape[0]
    print(f"[s2c] 轨B 引擎就绪 {time.time()-t0:.0f}s（F={F}）", flush=True)
    print(f"  ELIG3 类型={type(ELIG3).__name__} shape/len={getattr(ELIG3,'shape',None) or len(ELIG3)}", flush=True)
    arr = comp if isinstance(comp, np.ndarray) else comp.values
    if isinstance(ELIG3, pd.DataFrame):
        E = ELIG3.values
    else:
        E = np.asarray(ELIG3)
    # ELIG3 可能是稀疏的 (N,2) 索引对
    if E.ndim == 2 and E.shape[1] == 2 and E.shape[0] != arr.shape[0]:
        Emat = np.zeros(arr.shape, dtype=bool)
        Emat[E[:, 0].astype(int), E[:, 1].astype(int)] = True
        E = Emat
    base_order = np.argsort(np.where(E & np.isfinite(arr), arr, np.inf), axis=1)
    N_TOP = 20

offsets = [int(round(k * F / 12)) for k in range(12)]
sel = {}
for k, off in enumerate(offsets):
    d = {}
    for di in range(off, len(cal), F):
        row = np.asarray(base_order[di])
        d[di] = set(int(x) for x in row[:N_TOP])
    sel[k] = d
U = union_counts(sel, cal, offsets, F)
valid = U > 0
Uv = U[valid]
print(f"\n  名义持仓位次 = 12 × {N_TOP} = {12*N_TOP}")
print(f"  去重后实际持仓数 U：中位 {int(np.median(Uv))}｜P90 {int(np.quantile(Uv,0.9))}｜最大 {int(Uv.max())}")
print(f"  重叠度 = 1 − U/(12×{N_TOP}) = {1-np.median(Uv)/(12*N_TOP):.1%}")

# 资金校验
res = dict(track=TRACK, F=F, N_TOP=N_TOP, union_med=int(np.median(Uv)),
           union_p90=int(np.quantile(Uv, 0.9)), union_max=int(Uv.max()),
           nominal=12 * N_TOP)
print("\n  整手可执行性（单标的可用额 = 配额 / U；需 ≥ 100股×价 + 最低佣金5元）")
for tag, cap in [("轨A 17k", CAP_A), ("轨B 51k", CAP_B)]:
    for Uq, name in [(int(np.median(Uv)), "U中位"), (int(np.quantile(Uv, 0.9)), "U-P90")]:
        per = cap / Uq
        maxpx = (per - 5.0) / 100.0
        ok = maxpx >= 3.0
        print(f"    {tag} × {name}({Uq})：每只 {per:8.0f} 元 → 可买 100 股的最高股价 {maxpx:6.2f} 元 "
              f"{'✅ 可行(≥3元)' if ok else '❌ 不可行(<3元)'}")
        res[f"{tag}_{name}"] = dict(U=Uq, per_pos=float(per), max_price=float(maxpx), feasible=bool(ok))

json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n[s2c] 落盘 {OUT}")
