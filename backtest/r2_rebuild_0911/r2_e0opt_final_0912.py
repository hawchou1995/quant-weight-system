# -*- coding: utf-8 -*-
"""R20 域内收尾：动量加权交互臂 + 随机权重安慰剂（池固定 Top10，Dirichlet 权重 500 次）。"""
import json
import time

import numpy as np

import r2_e0opt_0912 as E

R2 = E.R2
t0 = time.time()
out = {}

ARMS3 = [
    ("M7=R20动量N7",    dict(npos=7, shape="eq", wfactor="mom")),
    ("M10=R20动量N10",  dict(npos=10, shape="eq", wfactor="mom")),
    ("MF=R20动量+F2",   dict(npos=5, shape="eq", wfactor="mom", fib_entry="sort382")),
    ("Moff3",           dict(npos=5, shape="eq", wfactor="mom", offset=3)),
    ("Moff10",          dict(npos=5, shape="eq", wfactor="mom", offset=10)),
    ("Moff13",          dict(npos=5, shape="eq", wfactor="mom", offset=13)),
]
for name, kw in ARMS3:
    r = E.run(name, **kw)
    r.pop("eq", None)
    out[name] = r
    print(f"[{name}] {r['total_pct']}% | 年化 {r['ann_pct']}% | 回撤 {r['mdd_pct']}% | 夏普 {r['sharpe']} | "
          f"{r['n_trades']}笔 胜率{r['win_rate']}%", flush=True)

# ---- 随机权重安慰剂：Top10 池固定（等权选择逻辑不变），权重 Dirichlet(1) 500 次 ----
rng = np.random.default_rng(20260912)
NT = 500
plc_sharpe, plc_total = [], []
t0p = time.time()
for it in range(NT):
    w = rng.dirichlet(np.ones(5))
    # 把随机权重注入槽位形状：rank_weights 只认预设形状 → 直接传等权再在 run 外改？
    # 简化：monkey-patch rank_weights 不便；此处以 "shape=eq" 跑 run 后重新按 w 加权代价太高。
    # 直接调 E.run 内部不可行 → 改为调用 run(shape=eq) 等权作为池复现，权重随机化通过
    # 预生成 5 槽权重向量写入模块级覆盖：
    E._RW_OVERRIDE = w  # run() 内 rank_weights 之前检查
    r = E.run(f"plc{it}", npos=5, shape="eq")
    plc_sharpe.append(r["sharpe"])
    plc_total.append(r["total_pct"])
    if (it + 1) % 100 == 0:
        print(f"  placebo {it+1}/{NT} ({time.time()-t0p:.0f}s)", flush=True)

plc_sharpe = np.array(plc_sharpe); plc_total = np.array(plc_total)
mom_arm = out["W5动量加权"] if "W5动量加权" in out else json.load(open(R2 / "e0opt_0912.json", encoding="utf-8"))["W5动量加权"]
p_sharpe = float((plc_sharpe >= mom_arm["sharpe"]).mean())
p_total = float((plc_total >= mom_arm["total_pct"]).mean())
out["_placebo_randomweight"] = {
    "n": NT, "sharpe_median": round(float(np.median(plc_sharpe)), 3),
    "sharpe_p95": round(float(np.quantile(plc_sharpe, 0.95)), 3),
    "total_median": round(float(np.median(plc_total)), 2),
    "p_sharpe_mom_ge": p_sharpe, "p_total_mom_ge": p_total,
    "target_sharpe": mom_arm["sharpe"], "target_total": mom_arm["total_pct"],
}
print(f"[安慰剂-随机权重 {NT}] 夏普中位 {np.median(plc_sharpe):.3f} p95 {np.quantile(plc_sharpe,0.95):.3f} | "
      f"总收益中位 {np.median(plc_total):.1f}% | 动量加权 target 夏普{mom_arm['sharpe']} p={p_sharpe:.4f} "
      f"总收益{mom_arm['total_pct']}% p={p_total:.4f}", flush=True)

json.dump(out, open(R2 / "e0opt_final_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
