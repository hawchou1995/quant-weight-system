# -*- coding: utf-8 -*-
"""verify: mechanical cross-check of report numbers against evidence artifacts."""
import json, pathlib
D = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest/hengpan_fangliang_dikai_0925")
rep = (D.parent/"报告-横盘放量次日低开隔日卖-回测-20260925.md").read_text(encoding="utf-8").replace("\u2212","-").replace("\u2014","-")
L = lambda n: json.loads((D/n).read_text(encoding="utf-8"))
rules = L("evidence_rules.json"); scales = L("evidence_scaling.json")
buck = L("evidence_depth_buckets.json"); ev = L("evidence_eventstudy.json")
marg = L("evidence_marginal.json"); g11 = L("q11_exact_gates.json")
R2 = rules["R2 低开[-3%,-1%] 仅此"]; R4 = rules["R4 低开[-2%,-1%] 仅此"]; R6 = rules["R6 任意低开 仅此"]
checks = [
 ("R2 毛均 +0.4120",        R2["gross_mean"], 0.4120, "+0.4120%"),
 ("R2@20bp 年化 +12.44",    R2["scen"]["20bp"]["ann"], 12.44, "+12.44%"),
 ("R2@20bp 净中 -0.0920",   R2["scen"]["20bp"]["med"], -0.0920, "-0.0920%"),
 ("R2@20bp 夏普 0.50",      R2["scen"]["20bp"]["sharpe"], 0.50, "0.50"),
 ("R2@20bp 超额 +9.51",     R2["scen"]["20bp"]["exc"], 9.51, "+9.51pp"),
 ("R2@20bp MDD -49.10",     R2["scen"]["20bp"]["mdd"], -49.10, "-49.10%"),
 ("R2@10bp 年化 +26.77",    R2["scen"]["10bp"]["ann"], 26.77, "+26.77%"),
 ("R2@10bp 净中 +0.0080",   R2["scen"]["10bp"]["med"], 0.0080, "+0.0080%"),
 ("R2 t_exc 13.35",         R2["t_exc"], 13.35, "+13.35"),
 ("R2 盈亏平衡 41.2bp",     R2["breakeven_cost_bp"], 41.2, "41.2bp"),
 ("R4 毛均 +0.3919",        R4["gross_mean"], 0.3919, "+0.3919%"),
 ("R4@20bp 年化 +15.23",    R4["scen"]["20bp"]["ann"], 15.23, "+15.23%"),
 ("R4 t_exc 14.37",         R4["t_exc"], 14.37, "+14.37"),
 ("R6 毛均 +0.2103",        R6["gross_mean"], 0.2103, "+0.2103%"),
 ("R6 t_exc 15.75",         R6["t_exc"], 15.75, "+15.75"),
 ("R6 盈亏平衡 21.0bp",     R6["breakeven_cost_bp"], 21.0, "21.0bp"),
 ("K3depth 年化 -30.36",    scales["K=3 depth"]["ann"], -30.36, "-30.36%"),
 ("K3random 年化 -5.47",    scales["K=3 random"]["ann"], -5.47, "-5.47%"),
 ("K10random 年化 +11.71",  scales["K=10 random"]["ann"], 11.71, "+11.71%"),
 ("深度[-3,-2] 均 +0.4875", buck["pool_lowopen"][1]["mean"], 0.4875, "+0.4875%"),
 ("深度[-2,-1] 均 +0.3919", buck["pool_lowopen"][2]["mean"], 0.3919, "+0.3919%"),
 ("深度<=-3 均 +0.1317",    buck["pool_lowopen"][0]["mean"], 0.1317, "+0.1317%"),
 ("事件研究 低开+横盘+放量 +0.3313", ev["layers"]["L3_spk_lowopen"]["mean"], 0.2930, "+0.2930%"),
 ("A@20bp 净均 +0.0544",    g11["A_忠实base Pq0.30/K2.0|20bp"]["mean"], 0.0544, "+0.0544%"),
 ("A@20bp 净中 -0.1998",    g11["A_忠实base Pq0.30/K2.0|20bp"]["med"], -0.1998, "-0.1998%"),
 ("B@20bp 年化 +7.13",      g11["B_网格 Pq0.40/K1.5|20bp"]["ann"], 7.13, "+7.13%"),
 ("B@20bp 净中 -0.1998",    g11["B_网格 Pq0.40/K1.5|20bp"]["med"], -0.1998, "-0.1998%"),
]
bad=0
for name, actual, expect, needle in checks:
    ok_val = abs(float(actual)-float(expect)) < 1e-6
    ok_txt = needle in rep
    flag = "OK " if (ok_val and ok_txt) else "FAIL"
    if not (ok_val and ok_txt): bad+=1
    print("  %s %-34s json=%-10s 报告含%-12s" % (flag, name, actual, needle))
# 仅低开层 t_exc 从 marginal 表核对
m1 = [r for r in marg["layers"] if r["tag"].startswith("1 ")][0]
print("  %s 仅低开层 t_exc=%.2f (marginal) 报告含 +15.75=%s" % ("OK " if m1["t_exc"]==15.75 and "+15.75" in rep else "FAIL", m1["t_exc"], "+15.75" in rep))
print("\n%s  共 %d 项, 失败 %d 项" % ("ALL PASS" if bad==0 else "HAS FAILURES", len(checks), bad))
