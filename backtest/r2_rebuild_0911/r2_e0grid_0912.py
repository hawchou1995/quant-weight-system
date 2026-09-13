# -*- coding: utf-8 -*-
"""E0 参数穷举 A 段：复刻验证 + 单维扫描（MA/止损/期限/池/门槛）+ MA×止损×期限交叉网格。
基线口径（默认参数）= E0：MA20/−8%/60日/池10/amt 5e6/等权5/20日轮动。"""
import json
import time

import numpy as np

import r2_e0opt_0912 as E

R2 = E.R2
t0 = time.time()
out = {}


def arm(name, **kw):
    r = E.run(name, **kw)
    r.pop("eq", None)
    out[name] = r
    print(f"[{name}] {r['total_pct']}% | 年化 {r['ann_pct']}% | 回撤 {r['mdd_pct']}% | 夏普 {r['sharpe']} | "
          f"{r['n_trades']}笔 胜率{r['win_rate']}%", flush=True)
    return r


# ---- 0. 复刻验证 ----
base = arm("BASE复刻")

# ---- 1. M 族：退出均线周期（用户点名 MA22）----
for p in E.MA_PERIODS:
    if p != 20:
        arm(f"M_MA{p}", ma_p=p)

# ---- 2. S 族：硬止损深度 ----
for s_ in (0.05, 0.10, 0.12, 0.15, None):
    arm(f"S_stop{s_ if s_ is not None else 'none'}", stop_pct=s_)

# ---- 3. H 族：满仓期限 ----
for h_ in (30, 40, 90, 120, None):
    arm(f"H_hold{h_ if h_ is not None else 'none'}", maxhold=h_)

# ---- 4. L 族：池大小与流动性门槛 ----
for pn in (5, 20, 50):
    arm(f"L_pool{pn}", pool_n=pn)
for th in (2e6, 1e7, 2e7):
    arm(f"L_amt{int(th/1e6)}M", amt_th=th)

json.dump(out, open(R2 / "e0grid_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"--- 单维完成 {time.time()-t0:.0f}s，进入交叉网格 ---", flush=True)

# ---- 5. 交叉网格 MA×stop×hold（7×5×4=140 臂，含默认 20/0.08/60）----
MAS = (10, 15, 20, 22, 25, 30, 40)
STOPS = (0.05, 0.08, 0.10, 0.15, None)
HOLDS = (30, 60, 90, None)
for p in MAS:
    for s_ in STOPS:
        for h_ in HOLDS:
            key = f"G_MA{p}_s{s_ if s_ is not None else 'x'}_h{h_ if h_ is not None else 'x'}"
            if key == "G_MA20_s0.08_h60":
                continue  # = BASE复刻
            r = E.run(key, ma_p=p, stop_pct=s_, maxhold=h_)
            r.pop("eq", None)
            out[key] = r
json.dump(out, open(R2 / "e0grid_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ---- 6. 网格 top15（按夏普，要求 n_trades≥80 保证非退化）----
cands = [(v["sharpe"], k) for k, v in out.items() if k.startswith("G_") and v["n_trades"] >= 80]
cands.sort(reverse=True)
print("--- 网格 top15（夏普，n>=80）---", flush=True)
for sh, k in cands[:15]:
    v = out[k]
    print(f"{k}: {v['total_pct']}% | 夏普 {v['sharpe']} | 回撤 {v['mdd_pct']}%", flush=True)
out["_grid_top15"] = [k for _, k in cands[:15]]
json.dump(out, open(R2 / "e0grid_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"总耗时 {time.time()-t0:.0f}s | 总臂位 {len(out)-1}", flush=True)
