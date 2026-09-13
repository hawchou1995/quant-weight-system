# -*- coding: utf-8 -*-
"""E0 优化第二波：rebal 邻域加密（30/50/60/80）+ P40 × 动量/N/F 交互组合臂。
复用 r2_e0opt_0912 引擎（import 触发模块级加载一次）。
"""
import json
import time

import r2_e0opt_0912 as E

R2 = E.R2
t0 = time.time()

ARMS2 = [
    ("R30",       dict(npos=5, shape="eq", rebal=30)),
    ("R50",       dict(npos=5, shape="eq", rebal=50)),
    ("R60",       dict(npos=5, shape="eq", rebal=60)),
    ("R80",       dict(npos=5, shape="eq", rebal=80)),
    ("C1=P40+动量",   dict(npos=5, shape="eq", rebal=40, wfactor="mom")),
    ("C2=P40+N3",     dict(npos=3, shape="eq", rebal=40)),
    ("C3=P40+N7",     dict(npos=7, shape="eq", rebal=40)),
    ("C4=P40+N10",    dict(npos=10, shape="eq", rebal=40)),
    ("C5=P40+动量+N10", dict(npos=10, shape="eq", rebal=40, wfactor="mom")),
    ("C6=P40+F2排序",  dict(npos=5, shape="eq", rebal=40, fib_entry="sort382")),
    ("C7=P40+F2+动量", dict(npos=5, shape="eq", rebal=40, fib_entry="sort382", wfactor="mom")),
    ("C8=R60+动量",   dict(npos=5, shape="eq", rebal=60, wfactor="mom")),
]

if __name__ == "__main__":
    out = json.load(open(R2 / "e0opt_0912.json", encoding="utf-8"))
    for name, kw in ARMS2:
        r = E.run(name, **kw)
        r.pop("eq", None)
        out[name] = r
        print(f"[{name}] {r['total_pct']}% | 年化 {r['ann_pct']}% | 回撤 {r['mdd_pct']}% | "
              f"夏普 {r['sharpe']} | {r['n_trades']}笔 胜率{r['win_rate']}% 盈亏比{r['payoff']} | {r['reasons']}", flush=True)
        json.dump(out, open(R2 / "e0opt_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
