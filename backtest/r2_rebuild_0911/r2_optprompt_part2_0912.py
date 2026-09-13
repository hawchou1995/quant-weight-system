# -*- coding: utf-8 -*-
"""优化版提示词回测 · Part2：敏感性网格 + 安慰剂500 + 失败声明（2026-09-12）
================================================================
导入 part1 的预计算矩阵（r2_optprompt_0912.py 作为模块执行到矩阵就绪），
敏感性：REV{15,20,25,30} × STOP{8,10,12} × HOLD{60,90,120} = 36 臂；
安慰剂：同事件数随机入场（OK_M 池内均匀），同退出规则，500 seeds，要求 real > p95。
失败声明：超额 t<2 或安慰剂 p>0.05 → 明确写"未通过证伪"。
"""
import importlib.util
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
R2 = BASE / "backtest" / "r2_rebuild_0911"

spec = importlib.util.spec_from_file_location(
    "opt1", r2 := str(R2 / "r2_optprompt_0912.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)   # 执行到矩阵就绪（__main__ 之外的顶层代码含 part1 打印，但不执行主臂）

run = M.run
GATE20 = M.GATE20
score20 = M.build_score(GATE20)
STKJ = M.STKJ
stock = M.stock
ROW = M.ROW
OK_M = M.OK_M
ND = M.ND
ALL_DAYS = M.ALL_DAYS
ALL_D64 = M.ALL_D64
OUT = R2 / "optprompt_0912.json"

t0 = time.time()
out = json.load(open(R2 / "optprompt_0912_part1.json", encoding="utf-8")) \
    if (R2 / "optprompt_0912_part1.json").exists() else {}

# ---------- 敏感性网格（36 臂） ----------
print("== 敏感性网格 ==", flush=True)
grid = []
for rev in (15, 20, 25, 30):
    g = M.build_gate(rev)
    sc = M.build_score(g)
    for stop in (0.08, 0.10, 0.12):
        for mh in (60, 90, 120):
            r = run(g, sc, stop=stop, maxhold=mh, cost_rt=0.0116)
            rec = {"rev": rev, "stop": int(stop * 100), "maxhold": mh, **{k: v for k, v in r.items() if k not in ("eq", "trades")}}
            grid.append(rec)
            print(f"  rev{rev}/stop{int(stop*100)}/h{mh}: {rec['total_pct']}% 夏普{rec['sharpe']} "
                  f"{rec['n_trades']}笔", flush=True)
out["grid"] = grid
pos_n = sum(1 for g in grid if g["total_pct"] > 0)
print(f"[grid] 正收益臂 {pos_n}/36", flush=True)
json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ---------- 安慰剂 500 seeds（同事件数随机入场，同退出规则） ----------
print("== 安慰剂 500 seeds ==", flush=True)
real = json.load(open(R2 / "optprompt_0912_part1.json", encoding="utf-8"))["main_cost"]
n_events = real["n_trades"]
half = 0.0116 / 2
stop = 0.10
maxhold = 120

# 事件池：OK_M 全体 (j, 全局日)（均匀撒点池）
pool_di, pool_j = np.where(OK_M)   # np.where → (行=日, 列=股)
rng = np.random.default_rng(20260912)


def event_return(j, di):
    """同退出规则的独立事件收益（open+1 入，stop/maxhold/ma120x3 出）"""
    s = stock[STKJ[j]]
    k = ROW[j][di]
    if k < 0 or k + 1 >= len(s["o"]):
        return np.nan
    ep = s["o"][k + 1]
    if not np.isfinite(ep) or ep <= 0 or k == 0:
        return np.nan
    if s["o"][k + 1] >= s["c"][k] * M.LIMIT_UP:
        return np.nan   # 开盘涨停不可买
    for b in range(1, maxhold + 1):
        kk = k + b
        if kk >= len(s["c"]):
            break
        c = s["c"][kk]
        if np.isfinite(c) and c <= ep * (1 - stop):
            kk2 = min(kk + 1, len(s["o"]) - 1)
            return (s["o"][kk2] * (1 - half) / (ep * (1 + half)) - 1) * 100
        if s["below3"][kk]:
            kk2 = min(kk + 1, len(s["o"]) - 1)
            return (s["o"][kk2] * (1 - half) / (ep * (1 + half)) - 1) * 100
    kk2 = min(k + maxhold + 1, len(s["o"]) - 1)
    return (s["o"][kk2] * (1 - half) / (ep * (1 + half)) - 1) * 100


# 真实策略的复利链（与安慰剂同函数形式）
real_trades = json.load(open(R2 / "optprompt_0912_part1.json", encoding="utf-8"))
# part1 未存 trades → 重跑一次主臂拿明细
res_main = run(GATE20, score20, stop=stop, maxhold=maxhold, cost_rt=0.0116)
real_rets = sorted([t["ret_pct"] for t in res_main["trades"]], key=lambda x: x)
real_total = res_main["total_pct"]

pl = []
for seed in range(500):
    idxs = rng.choice(len(pool_j), size=n_events, replace=False)
    rets = []
    for i in idxs:
        r = event_return(int(pool_j[i]), int(pool_di[i]))
        if np.isfinite(r):
            rets.append(r)
    if not rets:
        pl.append(0.0)
        continue
    rets = sorted(rets, key=lambda x: x)
    v = 1.0
    for rr in rets:            # 等权 1/5 序列复利（与真实链同形）
        v *= 1 + rr / 100 / 5
    pl.append((v - 1) * 100)
    if (seed + 1) % 100 == 0:
        print(f"  seed {seed+1}/500", flush=True)
pl = np.array(pl)
placebo = {"n_events": n_events, "real_total_pct": real_total,
           "placebo_mean_pct": round(float(pl.mean()), 2),
           "placebo_max_pct": round(float(pl.max()), 2),
           "placebo_p95_pct": round(float(np.percentile(pl, 95)), 2),
           "p": round(float((pl >= real_total).mean()), 3), "n_seeds": 500}
out["placebo"] = placebo
print(f"[placebo] real {real_total}% vs mean {placebo['placebo_mean_pct']}% max {placebo['placebo_max_pct']}% → p={placebo['p']}", flush=True)

# ---------- 失败声明 ----------
ex_t = out.get("excess", {}).get("hs300", {}).get("t", 0)
fail = (abs(ex_t) < 2) or (placebo["p"] > 0.05)
out["verdict"] = ("PASS" if not fail else
                  "FAIL - 未通过证伪，不具正期望（超额 t<2 或安慰剂不显著）")
json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"[verdict] {out['verdict']}", flush=True)
print(f"[done] {time.time()-t0:.0f}s", flush=True)
