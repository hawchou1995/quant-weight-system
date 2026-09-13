# -*- coding: utf-8 -*-
"""E0 小资金口径（17 万本金）：整手约束 + 最低佣金 5 元下的 N 扫描与 N3 弱化诊断。
S 族：N ∈ {3,4,5,7,10} × LLV ∈ {20,30}（comm_min=5）+ 佣金影响对照。
P 族：N3 十相位配对 vs N7。X 族：N3 1001 单纯形 + Dirichlet 300（形状能否救回 N3）。"""
import json
import time

import numpy as np

import r2_e0opt_0912 as E

R2 = E.R2
CASH = 170_000.0
t0 = time.time()
out = {"_meta": {"cash": CASH, "comm_min": 5.0, "round_lot": 100}}


def arm(name, **kw):
    r = E.run(name, **{**kw, "comm_min": 5.0})
    r.pop("eq", None)
    out[name] = r
    print(f"[{name}] {r['total_pct']}% | 年化 {r['ann_pct']}% | 回撤 {r['mdd_pct']}% | 夏普 {r['sharpe']} | "
          f"{r['n_trades']}笔 胜率{r['win_rate']}% 盈亏比{r['payoff']}", flush=True)
    return r


# 复刻校验：comm_min=0 + CASH0=100万 应=历史口径
r = E.run("复刻校验", exit_mode="llv", llv_p=30, npos=10)
out["复刻校验_100万comm0"] = {k: v for k, v in r.items() if k != "eq"}
print(f"[复刻校验 LLV30N10/100万/无最低佣] {r['total_pct']}% (期望 270.05)", flush=True)

# ---- S 族：17 万本金 N×LLV 扫描 ----
for n in (3, 4, 5, 7, 10):
    for lv in (20, 30):
        arm(f"S_N{n}_LLV{lv}", npos=n, exit_mode="llv", llv_p=lv)

# 佣金影响对照（N10 现金最紧张档）
r = E.run("S_N10_LLV30_comm0", npos=10, exit_mode="llv", llv_p=30, comm_min=0.0)
r.pop("eq", None)
out["S_N10_LLV30_comm0"] = r
print(f"[对照 N10/LLV30 无最低佣] {r['total_pct']}% vs 含最低佣 {out['S_N10_LLV30']['total_pct']}%", flush=True)

json.dump(out, open(R2 / "e0small_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"--- S 族完成 {time.time()-t0:.0f}s ---", flush=True)

# ---- P 族：N3 十相位配对 vs N7（LLV30 口径）----
OFFS = (0, 2, 4, 6, 8, 10, 12, 14, 16, 18)


def scan(kw, tag):
    return [E.run(f"P_{tag}_{o}", offset=o, comm_min=5.0, **kw)["total_pct"] for o in OFFS]


ph_n3 = scan(dict(npos=3, exit_mode="llv", llv_p=30), "n3")
ph_n5 = scan(dict(npos=5, exit_mode="llv", llv_p=30), "n5")
ph_n7 = scan(dict(npos=7, exit_mode="llv", llv_p=30), "n7")
d37 = np.array(ph_n3) - np.array(ph_n7)
res = {"offs": list(OFFS), "n3": ph_n3, "n5": ph_n5, "n7": ph_n7,
       "n3_med": round(float(np.median(ph_n3)), 1), "n5_med": round(float(np.median(ph_n5)), 1),
       "n7_med": round(float(np.median(ph_n7)), 1),
       "diff_n3n7_med": round(float(np.median(d37)), 1), "diff_n3n7_pos": round(float((d37 > 0).mean()), 2)}
print(f"[十相位 N3 ] 中位 {np.median(ph_n3):.1f}% 区间 [{min(ph_n3):.0f},{max(ph_n3):.0f}]", flush=True)
print(f"[十相位 N5 ] 中位 {np.median(ph_n5):.1f}%", flush=True)
print(f"[十相位 N7 ] 中位 {np.median(ph_n7):.1f}%", flush=True)
print(f"[配对 N3-N7] 差中位 {np.median(d37):.1f}pp | N3 胜率 {(d37>0).mean():.2f}", flush=True)
out["_P_phase"] = res
json.dump(out, open(R2 / "e0small_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ---- X 族：N3 1001 单纯形 + Dirichlet 300（权重形状能否救回 N3）----
from itertools import combinations
VECS = []
for combo in combinations(range(14), 4):
    v = [combo[0], combo[1] - combo[0] - 1, combo[2] - combo[1] - 1, combo[3] - combo[2] - 1, 13 - combo[3]]
    VECS.append([x / 10 for x in v])
tot3, shp3 = [], []
for i, w in enumerate(VECS):
    E._RW_OVERRIDE = w
    r = E.run(f"X{i}", npos=3, shape="eq", exit_mode="llv", llv_p=30, comm_min=5.0)
    tot3.append(r["total_pct"]); shp3.append(r["sharpe"])
E._RW_OVERRIDE = None
tot3 = np.array(tot3); shp3 = np.array(shp3)
eq_rank = float((tot3 < out["S_N3_LLV30"]["total_pct"]).mean())
rng = np.random.default_rng(33)
plc = []
for it in range(300):
    E._RW_OVERRIDE = rng.dirichlet(np.ones(3))
    r = E.run(f"XD{it}", npos=3, shape="eq", exit_mode="llv", llv_p=30, comm_min=5.0)
    plc.append((r["sharpe"], r["total_pct"]))
E._RW_OVERRIDE = None
plc = np.array(plc)
out["_X_simplex_N3"] = {"n": 1001, "equal_rank": round(eq_rank, 3), "median": round(float(np.median(tot3)), 1),
                        "p95": round(float(np.quantile(tot3, 0.95)), 1), "max": round(float(tot3.max()), 1),
                        "best_vec": VECS[int(np.argmax(tot3))],
                        "dirichlet_med_sharpe": round(float(np.median(plc[:, 0])), 3),
                        "dirichlet_med_total": round(float(np.median(plc[:, 1])), 1)}
print(f"[X N3单纯形1001] 等权分位 {eq_rank:.3f} | 中位 {np.median(tot3):.1f}% p95 {np.quantile(tot3,0.95):.1f}% "
      f"max {tot3.max():.1f}% vec={VECS[int(np.argmax(tot3))]} | Dirichlet中位 {np.median(plc[:,1]):.1f}%", flush=True)
out["_meta"]["n_trials"] = 14 + 30 + 1001 + 300
json.dump(out, open(R2 / "e0small_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
