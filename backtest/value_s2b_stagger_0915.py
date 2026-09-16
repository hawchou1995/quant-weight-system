# -*- coding: utf-8 -*-
"""S2b 交叠迁移测试（R-structure-S2b-0915）：把「12 相位交叠」测到在产轨A/轨B。

动机：S1 证明主导结构变量是**交叠相位数 P**（P=1→P≥6 提升 +0.05~+0.16，且与调仓周期 F 无关），
      而 S2 只在 P=1 下扫过 F。故**真正该测的是交叠本身能否迁移**。

做法：对同一配置取 12 个不同 offset 的子组合（覆盖整个调仓周期），各自归一后等权合成 = 交叠组合；
      对照组 = 同样的 12 个 offset 的**单相位中位**。
纪律：只测不改；轨A 的 equity 用运行时源码注入补齐（不修改上游文件）。
用法：python value_s2b_stagger_0915.py trackA|trackB
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
OUT = os.path.join(HERE, f"value_s2b_{TRACK}_0915.json")


def _stat(eq, tag):
    eq = eq.dropna()
    rr = eq.pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    tot = eq.iloc[-1] / eq.iloc[0] - 1
    return dict(tag=tag, ann=float((1 + tot) ** (1 / yrs) - 1), sharpe=float(rr.mean() / rr.std() * np.sqrt(252)),
                mdd=float(((eq / eq.cummax()) - 1).min()))


def stag_run(runner, offsets, tag):
    subs, singles = [], []
    for k, o in enumerate(offsets):
        r = runner(o)
        eq = r["equity"]
        subs.append(eq / eq.iloc[0])
        s = _stat(eq, f"off{o}")
        s["off"] = o
        singles.append(s)
    S = pd.concat(subs, axis=1).ffill().dropna()
    st = S.mean(axis=1)
    a = _stat(st, "交叠合成")
    b = dict(sharpe=float(np.median([x["sharpe"] for x in singles])),
             ann=float(np.median([x["ann"] for x in singles])),
             mdd=float(np.median([x["mdd"] for x in singles])),
             smin=float(np.min([x["sharpe"] for x in singles])),
             smax=float(np.max([x["sharpe"] for x in singles])))
    print(f"  {tag}")
    print(f"    单相位（{len(singles)} 档中位）: 夏普 {b['sharpe']:.3f}（{b['smin']:.3f}~{b['smax']:.3f}）"
          f"  年化 {b['ann']:7.2%}  回撤 {b['mdd']:8.2%}")
    print(f"    12 相位交叠合成        : 夏普 {a['sharpe']:.3f}  年化 {a['ann']:7.2%}  回撤 {a['mdd']:8.2%}")
    print(f"    → Δ夏普 {a['sharpe']-b['sharpe']:+.3f}  Δ年化 {a['ann']-b['ann']:+.2%}  "
          f"Δ回撤 {a['mdd']-b['mdd']:+.2%}", flush=True)
    return dict(staggered=a, single=b, singles=singles)


res = {}
if TRACK == "trackA":
    SRC = os.path.join(OSS, "satellite_opt_0913.py")
    src = open(SRC, encoding="utf-8").read()
    old = ("win=float(np.mean([t[3] > 0 for t in closed])) if closed else np.nan, by_year=yr)")
    new = ("win=float(np.mean([t[3] > 0 for t in closed])) if closed else np.nan, by_year=yr, equity=eq)")
    assert src.count(old) == 1, f"注入锚点命中 {src.count(old)} 次"
    g = {"__file__": os.path.abspath(SRC), "__name__": "__s2bA__"}
    exec(compile(src.replace(old, new), SRC, "exec"), g)
    run_ln, F = g["run_ln"], 30
    print(f"[s2b] 轨A 引擎就绪（F={F}，equity 已注入）", flush=True)
    res["trackA"] = stag_run(lambda o: run_ln("turn", 20, F, o, use_gate=True),
                             [int(round(k * F / 12)) for k in range(12)], "轨A（三低 turn + Top20 + 闸门，F=30）")
else:
    SRC = os.path.join(OSS, "oss_super_combo_0913.py")
    src = open(SRC, encoding="utf-8").read()
    head = src.split("comp = composite()")[0]
    g = {"__file__": os.path.abspath(SRC), "__name__": "__s2bB__"}
    exec(compile(head, SRC, "exec"), g)
    for need in ("run_engine", "composite", "F"):
        assert need in g, f"缺少 {need}"
    comp, F = g["composite"](), g["F"]
    print(f"[s2b] 轨B 引擎就绪（F={F}）", flush=True)
    res["trackB"] = stag_run(lambda o: g["run_engine"](comp, 20, offset=o),
                             [int(round(k * F / 12)) for k in range(12)], f"轨B（SUPER 13 因子 + Top20，F={F}）")

json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n[s2b] 落盘 {OUT}")
