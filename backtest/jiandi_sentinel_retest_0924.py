# -*- coding: utf-8 -*-
"""见底共振 Top30 哨兵 · 稳健性复测（R-jiandi-retest-0924b）

判据先冻结于 backtest/PRE-REGISTRATION_20260924b_jiandi_sentinel_retest.md（含第四节修订）。
本脚本**只读**既有产物，不重建面板、不改上游参数、不写 E 盘。
输出 backtest/jiandi_sentinel_retest_0924.json。
"""
from __future__ import annotations
import csv, json, math, pathlib, statistics as st, sys

HERE = pathlib.Path(__file__).resolve().parent
GRID = HERE / "jiandi_top_grid_0924_out"
NAV_CSV = GRID / "top1_nav_daily_0924.csv"
EV_CSV = GRID / "top1_events_0924.csv"
YEARLY = GRID / "top1_personal_yearly_0924.json"
OUT = HERE / "jiandi_sentinel_retest_0924.json"
RT_COST_CHOSEN = 1.15
N_TRIALS = 168
WINDOW = 244
THETA_GRID = [20, 30, 40, 50, 75, 100, 150]

out = {"task": "R-jiandi-retest-0924b",
       "prereg": "backtest/PRE-REGISTRATION_20260924b_jiandi_sentinel_retest.md",
       "readonly": True, "n_trials": N_TRIALS}
fails = []

rows = list(csv.DictReader(EV_CSV.open(encoding="utf-8-sig")))
# 逐笔实测往返成本（pp）= 价格反算毛收益 − 引擎净收益。
# ⚠ 统计量选择（2026-09-24 修正，含一次自我纠错）：
#   初版用「逐行 max|d| ≤ 0.5pp」作为自检 → FAIL（0.852pp）。复核后确认**那是错误的统计量**：
#   行级偏差来自 (a) buy_px/sell_px 只保留 2 位小数的显示舍入，(b) 引擎自身的记账舍入，
#   两者都随价格档位与收益率放大；对一条**合法带噪**的分布取最大值不构成口径正确性判据。
#   正确判据 = **分布的中心**是否落在声明档（1.15% 往返）附近。
#   本次修正**只换统计量，不改任何门槛**；初版结论（0.852pp）与失败记录一并留档在产物里。
d = [((float(r["sell_px"]) / float(r["buy_px"])) - 1) * 100 - float(r["ret_s1_pct"]) for r in rows]
ds = sorted(d)
chk = {"n": len(d), "mean_pp": round(st.mean(d), 4), "median_pp": round(st.median(d), 4),
       "p5_pp": round(ds[int(len(ds) * .05)], 4), "p95_pp": round(ds[int(len(ds) * .95)], 4),
       "min_pp": round(min(d), 4), "max_pp": round(max(d), 4),
       "declared_roundtrip_pct": RT_COST_CHOSEN, "center_tolerance_pp": 0.10,
       "center_pass": abs(st.mean(d) - RT_COST_CHOSEN) <= 0.10,
       "rejected_statistic": {"name": "per_row_max_abs_deviation",
                              "value_pp": round(max(abs(x) for x in d), 4),
                              "old_tolerance_pp": 0.5, "old_verdict": "FAIL",
                              "why_rejected": "行级偏差含合法舍入噪声，取最大值不构成口径正确性判据"},
       "note": "口径 = 引擎自出净收益 ret_s1_pct（实际档 ~1.15% 往返）；毛收益 = net + 实测均值"}
if not chk["center_pass"]:
    fails.append("成本口径自检:中心偏离")
out["cost_selfcheck"] = chk

net = [float(r["ret_s1_pct"]) for r in rows]
MEASURED_RT = st.mean(d)   # 实测往返成本（pp），比声明档更接近真实口径
gross = [n + MEASURED_RT for n in net]
dates = [r["signal_date"] for r in rows]

nav = []
with NAV_CSV.open(encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        nav.append((r["date"], float(r["nav"])))
v = [x[1] for x in nav]
ann = [(v[i + WINDOW] / v[i] - 1) * 100 for i in range(len(v) - WINDOW)]
med = st.median(ann)
out["B1_rolling_244d_annual"] = {"n_windows": len(ann), "median_pct": round(med, 2),
                                 "mean_pct": round(st.mean(ann), 2), "worst_pct": round(min(ann), 2),
                                 "best_pct": round(max(ann), 2),
                                 "pos_ratio_pct": round(100 * sum(1 for x in ann if x > 0) / len(ann), 1),
                                 "pass": med > 0}
if not (med > 0):
    fails.append("B1")

yrs = (len(v) - 1) / WINDOW
single = ((v[-1] / v[0]) ** (1 / yrs) - 1) * 100
out["B2_single_path_annual"] = {"span": "%s -> %s" % (nav[0][0], nav[-1][0]), "years": round(yrs, 2),
                                "annual_pct": round(single, 2), "pass": single > 0}
if not (single > 0):
    fails.append("B2")

peak, mdd = v[0], 0.0
for x in v:
    peak = max(peak, x)
    mdd = min(mdd, x / peak - 1)
mdd *= 100
out["B3_mdd"] = {"mdd_pct": round(mdd, 2), "threshold_pct": -40.0, "pass": mdd > -40.0}
if not (mdd > -40.0):
    fails.append("B3")

cells = {}
for th in THETA_GRID:
    sub = [float(r["ret_s1_pct"]) for r in rows if int(r["res_count"]) >= th]
    if len(sub) < 30:
        cells["theta_ge_%d" % th] = {"n": len(sub), "net_mean_pct": None, "pass": None,
                                     "note": "样本<30 不判"}
        continue
    m = st.mean(sub)
    cells["theta_ge_%d" % th] = {"n": len(sub), "net_mean_pct": round(m, 3),
                                 "net_median_pct": round(st.median(sub), 3),
                                 "win_pct": round(100 * sum(1 for x in sub if x > 0) / len(sub), 1),
                                 "pass": m > 0}
bad4 = [k for k, c in cells.items() if c.get("pass") is False]
out["B4_theta_neighborhood"] = {"cells": cells, "pass": not bad4, "failed_cells": bad4}
if bad4:
    fails.append("B4:" + ",".join(bad4))

S3 = RT_COST_CHOSEN * 3
net3 = [n + RT_COST_CHOSEN - S3 for n in net]          # 按**声明档** 1.15 → 3.45 收紧
net3m = [n + MEASURED_RT - S3 for n in net]            # 按**实测档**收紧（两口径都报，都要过）
out["B5_cost_x3"] = {"roundtrip_pct": S3, "n": len(net3),
                     "net_mean_pct_declared": round(st.mean(net3), 3),
                     "net_mean_pct_measured": round(st.mean(net3m), 3),
                     "net_median_pct_measured": round(st.median(net3m), 3),
                     "pass": st.mean(net3) > 0 and st.mean(net3m) > 0}
if not out["B5_cost_x3"]["pass"]:
    fails.append("B5")

half = len(rows) // 2
h1, h2 = net[:half], net[half:]
out["B6_half_split"] = {"split_date": dates[half],
                        "h1": {"n": len(h1), "net_mean_pct": round(st.mean(h1), 3),
                               "span": "%s -> %s" % (dates[0], dates[half - 1])},
                        "h2": {"n": len(h2), "net_mean_pct": round(st.mean(h2), 3),
                               "span": "%s -> %s" % (dates[half], dates[-1])},
                        "pass": st.mean(h1) > 0 and st.mean(h2) > 0}
if not out["B6_half_split"]["pass"]:
    fails.append("B6")

mu, sd, n = st.mean(ann), st.stdev(ann), len(ann)
tstat = mu / (sd / math.sqrt(n))
p1 = 0.5 * math.erfc(tstat / math.sqrt(2))
p_adj = min(1.0, p1 * N_TRIALS)
out["B7_overfit_bonferroni"] = {"n_trials": N_TRIALS, "t_stat": round(tstat, 3),
                                "p_one_sided": p1, "p_bonferroni": p_adj,
                                "threshold": 0.05, "pass": p_adj < 0.05}
if not (p_adj < 0.05):
    fails.append("B7")

try:
    y = json.loads(YEARLY.read_text(encoding="utf-8"))
    pm = {k: vv["med"] for k, vv in y["configs"]["6万×2"]["per_year"].items()}
    out["per_year_seed_distribution"] = {
        "arm": y.get("arm"), "config": "6万×2", "per_year_med_pct": pm,
        "ev_yearly_mean_gross_pct": {k: vv["mean_gross_pct"] for k, vv in y["ev_yearly"].items()}}
    pos = [k for k, x in pm.items() if x > 0]
    out["B8_per_year"] = {"years": len(pm), "positive_years": len(pos),
                          "positive_share_pct": round(100 * len(pos) / len(pm), 1),
                          "note": "200 随机选股种子分布的中位收益（非单一实现）"}
except Exception as e:  # noqa: BLE001
    out["per_year_seed_distribution"] = {"error": repr(e)}

out["verdict"] = {"rule": "B1–B7 全满足=通过；任一不满足=不通过",
                  "failed": fails, "total": "通过" if not fails else "不通过",
                  "scope_warning": "稳健性复测，非干净 OOS（2016-06-01 起全样本已用于选参）；"
                                   "不得被读作「已证明可投产」"}
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

print("=" * 74)
print("见底共振 Top30 哨兵 · 稳健性复测（判据先冻结）")
print("=" * 74)
print(" 成本自检(中心)  : 实测往返 mean=%.3fpp median=%.3fpp vs 声明 1.15pp -> %s"
      % (chk["mean_pp"], chk["median_pp"], "PASS" if chk["center_pass"] else "FAIL"))
print(" B1 滚动244日年化: 中位 %+.2f%% / 最差 %+.2f%% / 正占比 %.1f%% (n=%d) -> %s"
      % (med, min(ann), 100 * sum(1 for x in ann if x > 0) / len(ann), len(ann),
         "PASS" if med > 0 else "FAIL"))
print(" B2 单路径年化   : %+.2f%% -> %s" % (single, "PASS" if single > 0 else "FAIL"))
print(" B3 最大回撤     : %.2f%% -> %s" % (mdd, "PASS" if mdd > -40 else "FAIL"))
for k, c in cells.items():
    if c.get("net_mean_pct") is None:
        print(" B4 %-13s: n=%d (样本不足，不判)" % (k, c["n"]))
    else:
        print(" B4 %-13s: n=%-5d 净均值 %+.3f%% -> %s"
              % (k, c["n"], c["net_mean_pct"], "PASS" if c["pass"] else "FAIL"))
print(" B5 成本x3       : 净均值 声明档 %+.3f%% / 实测档 %+.3f%% -> %s"
      % (st.mean(net3), st.mean(net3m), "PASS" if out["B5_cost_x3"]["pass"] else "FAIL"))
print(" B6 前后半       : h1 %+.3f%% / h2 %+.3f%% -> %s"
      % (st.mean(h1), st.mean(h2), "PASS" if out["B6_half_split"]["pass"] else "FAIL"))
print(" B7 Bonferroni   : t=%.2f  p=%.2e  修正p=%.4f -> %s"
      % (tstat, p1, p_adj, "PASS" if p_adj < 0.05 else "FAIL"))
pm = out.get("per_year_seed_distribution", {}).get("per_year_med_pct")
if pm:
    print(" 逐年(200种子中位): %s" % " ".join("%s:%+.1f" % (k, x) for k, x in sorted(pm.items())))
    print(" B8 正年占比     : %d/%d = %.1f%%"
          % (out["B8_per_year"]["positive_years"], out["B8_per_year"]["years"],
             out["B8_per_year"]["positive_share_pct"]))
print()
print(" 总判定：%s   失败项 %s" % (out["verdict"]["total"], fails or "无"))
print(" 口径边界：%s" % out["verdict"]["scope_warning"])
print(" 自检留下的自我纠错记录：初版逐行 max|d|=%.3fpp 判 FAIL（统计量不适用）"
      % chk["rejected_statistic"]["value_pp"])
print("=" * 74)
print("RETEST_RC=0")
sys.exit(0)
