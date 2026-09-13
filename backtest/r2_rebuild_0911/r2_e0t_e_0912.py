# -*- coding: utf-8 -*-
"""E0 T 族终审 E 段：LLV30 回撤修复（分散 N7/N10）+ 分年度/滑点 + LLV30 口径随机权重对照。"""
import json
import time

import numpy as np
import pandas as pd

import r2_e0opt_0912 as E

R2 = E.R2
t0 = time.time()
out = json.load(open(R2 / "e0t_0912.json", encoding="utf-8"))

for name, kw in (("E_LLV30_N7",  dict(exit_mode="llv", llv_p=30, npos=7)),
                 ("E_LLV30_N10", dict(exit_mode="llv", llv_p=30, npos=10)),
                 ("E_LLV30_N7_lin", dict(exit_mode="llv", llv_p=30, npos=7, shape="lin")),
                 ("E_LLV20_N7", dict(exit_mode="llv", llv_p=20, npos=7)),
                 ("E_LLV25", dict(exit_mode="llv", llv_p=25))):
    r = E.run(name, **kw)
    r.pop("eq", None)
    out[name] = r
    print(f"[{name}] {r['total_pct']}% | 年化 {r['ann_pct']}% | 回撤 {r['mdd_pct']}% | 夏普 {r['sharpe']} | "
          f"{r['n_trades']}笔 胜率{r['win_rate']}%", flush=True)

# 最优修复臂分年度 + 滑点
r0 = E.run("E_stats", exit_mode="llv", llv_p=30, npos=7)
eq = np.array(r0["eq"])
days = pd.DatetimeIndex(E.ALL_DAYS)
eqs = pd.Series(eq, index=days)
yearly = {str(y): round(float(g.iloc[-1] / g.iloc[0] - 1) * 100, 2) for y, g in eqs.groupby(eqs.index.year)}
out["E_yearly_LLV30N7"] = yearly
print(f"[LLV30+N7 分年度] {yearly}", flush=True)
for slip in (0.0030, 0.0040):
    E.SLIP = slip
    r = E.run(f"E_LLV30N7_s{int(slip*1e4)}", exit_mode="llv", llv_p=30, npos=7)
    r.pop("eq", None)
    out[f"E_LLV30N7_slip{int(slip*1e4)}"] = r
    print(f"[LLV30+N7 slip={int(slip*1e4)}bps] {r['total_pct']}% | 夏普 {r['sharpe']} | 回撤 {r['mdd_pct']}", flush=True)
E.SLIP = 0.0020

# LLV30 口径随机权重对照（N7 Dirichlet 300）
rng = np.random.default_rng(730)
plc = []
for it in range(300):
    E._RW_OVERRIDE = rng.dirichlet(np.ones(7))
    r = E.run(f"Eplc{it}", npos=7, shape="eq", exit_mode="llv", llv_p=30)
    plc.append((r["sharpe"], r["total_pct"]))
E._RW_OVERRIDE = None
plc = np.array(plc)
out["E_LLV30N7_randomw"] = {"n": 300, "sharpe_median": round(float(np.median(plc[:, 0])), 3),
                            "sharpe_p95": round(float(np.quantile(plc[:, 0], 0.95)), 3),
                            "total_median": round(float(np.median(plc[:, 1])), 2)}
print(f"[LLV30+N7 随机权重300] 夏普中位 {np.median(plc[:,0]):.3f} | 收益中位 {np.median(plc[:,1]):.1f}%", flush=True)

json.dump(out, open(R2 / "e0t_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
