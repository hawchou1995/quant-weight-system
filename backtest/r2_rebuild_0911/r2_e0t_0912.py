# -*- coding: utf-8 -*-
"""E0 T 族：新语料提取方向回测（《股票交易精髓》ML-N 阶梯跟踪止损 / 均线上移；t-trading 维加斯 EMA 过滤）。
LLV 阶梯退出 = 与 MA 平滑退出不同族的宽/紧双侧交叉验证（检验"宽松退出 better"是结构还是相位运气）。
默认参数复刻校验：BASE 复刻 + LLV20 应≈紧于 MA20。"""
import json
import time

import numpy as np

import r2_e0opt_0912 as E

R2 = E.R2
t0 = time.time()
out = {}

# 复刻校验
r = E.run("BASE复刻")
r.pop("eq", None)
out["BASE复刻"] = r
print(f"[BASE复刻] {r['total_pct']}% (期望 121.05)", flush=True)


def arm(name, **kw):
    r = E.run(name, **kw)
    r.pop("eq", None)
    out[name] = r
    print(f"[{name}] {r['total_pct']}% | 年化 {r['ann_pct']}% | 回撤 {r['mdd_pct']}% | 夏普 {r['sharpe']} | "
          f"{r['n_trades']}笔 胜率{r['win_rate']}% | {r['reasons']}", flush=True)
    return r


# ---- T1: ML-N 阶梯跟踪止损（近 N 日最低收盘）----
for n in (10, 13, 15, 20, 30, 40, 60):
    arm(f"T1_LLV{n}", exit_mode="llv", llv_p=n)

# ---- T2: 均线上移跟踪止损（书中 3-5% 建议）----
for sh in (0.03, 0.05):
    arm(f"T2_MA20x{1+sh:.2f}", ma_shift=sh)

# ---- T3: 维加斯 EMA 过滤（中层趋势 / 外层牛熊）----
arm("T3_ema144多头排列", ema_filter=144)
arm("T3_ema576牛熊", ema_filter=576)

json.dump(out, open(R2 / "e0t_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ---- 相位审计：off0 最优 T 臂 + LLV 宽档代表 ----
cands = sorted([(v["total_pct"], k) for k, v in out.items()
                if k.startswith("T") and v["n_trades"] >= 60], reverse=True)[:3]
print("--- top3 T 臂相位审计 ---", flush=True)
for tot, k in cands:
    kw = {}
    if "LLV" in k:
        kw = dict(exit_mode="llv", llv_p=int(k.split("LLV")[1].replace("破位", "")))
    elif "MA20x" in k:
        kw = dict(ma_shift=0.03 if "1.03" in k else 0.05)
    elif "ema144" in k:
        kw = dict(ema_filter=144)
    elif "ema576" in k:
        kw = dict(ema_filter=576)
    tots = []
    for off in (0, 7, 13, 20, 27, 33):
        r = E.run(f"TPH_{k}_{off}", offset=off, **kw)
        tots.append(r["total_pct"])
    med = float(np.median(tots))
    out[f"_phase_{k}"] = {"off0": tot, "tots": tots, "median": round(med, 2), "min": min(tots), "max": max(tots)}
    print(f"[相位 {k}] off0 {tot:.1f}% | 中位 {med:.1f}% | 区间 [{min(tots):.1f}, {max(tots):.1f}]", flush=True)

json.dump(out, open(R2 / "e0t_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
