# -*- coding: utf-8 -*-
"""r8: mechanical cross-check of the optimization report against evidence artifacts."""
import json, pathlib
D = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest/hengpan_fangliang_dikai_0925")
rep = (D.parent/"报告-横盘放量次日低开-优化方向研究-20260926.md").read_text(encoding="utf-8").replace("\u2212","-").replace("\u2014","-")
L = lambda n: json.loads((D/n).read_text(encoding="utf-8"))
rk=L("evidence_ranking.json"); op=L("evidence_optimization.json"); ar=L("evidence_artifact_test.json")
ex=L("evidence_execution.json"); lq=L("evidence_liquidity_ladder.json"); sv=L("evidence_survivorship.json")
C=[]
def ck(name, actual, expect, needle):
    okv = abs(float(actual)-float(expect)) < 1e-6; okt = needle in rep
    C.append((okv and okt, name, actual, needle))
# ranking scan
for key,val,nd in (("amt_lo",0.6469,"+0.6469%"),("random",0.3669,"+0.3669%"),("gap_deep",0.2656,"+0.2656%"),
                   ("volbr_lo",0.4887,"+0.4887%"),("ret20_lo",0.5168,"+0.5168%"),("volbr_hi",0.2612,"+0.2612%"),
                   ("amt_hi",0.1800,"+0.1800%"),("relgap_deep",0.1563,"+0.1563%")):
    ck("排序键 %s 毛均"%key, rk["K10_%s"%key]["ev"]["mean"], val, nd)
ck("amt_lo 年化 +69.92", rk["K10_amt_lo"]["port"]["ann"], 69.92, "+69.92%")
ck("gap_deep 年化 -20.58", rk["K10_gap_deep"]["port"]["ann"], -20.58, "-20.58%")
ck("random 年化 +11.42", rk["K10_random"]["port"]["ann"], 11.42, "+11.42%")
# optimization
ck("复合打分 毛均 +0.7957", op["cmp_composite"]["ev"]["mean"], 0.7957, "+0.7957%")
ck("复合打分 毛中 +0.7067", op["cmp_composite"]["ev"]["med"], 0.7067, "+0.7067%")
ck("复合打分 毛胜 58.43", op["cmp_composite"]["ev"]["wr"], 58.43, "58.43%")
ck("复合打分 t超额 14.22", op["cmp_composite"]["ev"]["t_exc"], 14.22, "+14.22")
ck("复合打分 年化 +106.69", op["cmp_composite"]["port"]["ann"], 106.69, "+106.69%")
ck("复合打分 MDD -48.86", op["cmp_composite"]["port"]["mdd"], -48.86, "-48.86%")
ck("复合打分 夏普 2.19", op["cmp_composite"]["port"]["sharpe"], 2.19, "2.19")
for k,v in (("K5",70.86),("K10",69.92),("K20",68.61),("K50",48.46),("K100",29.96)):
    ck("容量曲线 K=%s"%k, op["cap_%s"%k]["port"]["ann"], v, "+%.2f%%"%v)
for k,v in (("0bp",113.24),("20bp",69.92),("30bp",51.75),("40bp",35.57),("60bp",8.42)):
    ck("成本阶梯 %s"%k, op["cost_%s"%k]["ann"], v, "+%.2f%%"%v)
ck("ST原始 +69.92", op["ST_原始"]["port"]["ann"], 69.92, "+69.92%")
ck("ST剔期内代理 +71.72", op["ST_剔期内ST代理"]["port"]["ann"], 71.72, "+71.72%")
ck("择时门 无门 +69.92", op["gate_无门"]["ann"], 69.92, "+69.92%")
ck("择时门 >MA20 +26.71", op["gate_HS300>MA20"]["ann"], 26.71, "+26.71%")
ck("择时门 反向 +32.99", op["gate_HS300<MA60(反向)"]["ann"], 32.99, "+32.99%")
_ap50 = op["adv"]["p50"]; C.append(((round(_ap50/1e4)==2442) and ("2,442 万" in rep), "ADV p50 2,442万", _ap50, "2,442 万"))
# artifact
ck("入场日盘中 +0.7439", ar["legs"]["T1_intraday"], 0.7439, "+0.7439%")
ck("隔夜腿 +0.0478", ar["legs"]["T1c_T2c"], 0.0478, "+0.0478%")
ck("全程 +0.7958", ar["legs"]["full"], 0.7958, "+0.7958%")
ck("池 入场日盘中 +0.4257", ar["pool_legs"]["T1_intraday"], 0.4257, "+0.4257%")
ck("池 隔夜腿 -0.0128", ar["pool_legs"]["T1c_T2c"], -0.0128, "-0.0128%")
# execution
for lab,v,nd in (("① 理想: T+1 开盘价",106.94,"+106.94%"),("② 开盘+0.2% 滑价",63.84,"+63.84%"),
                 ("③ 开盘+0.5% 滑价",15.63,"+15.63%"),("④ 开盘+1.0% 滑价",-35.00,"-35.00%"),
                 ("⑤ 当日均价 (O+H+L+C)/4",12.49,"+12.49%"),("⑥ 错失开盘: T+1 收盘",-10.35,"-10.35%")):
    ck("成交情景 %s"%lab, ex["scenarios"][lab]["ann"], v, nd)
ck("二维 0|20bp", ex["grid"]["0|20bp_rt"]["ann"], 106.94, "+106.94%")
ck("二维 均价|40bp", ex["grid"]["均价|40bp_rt"]["ann"], -10.86, "-10.86%")
# liquidity ladder
ck("下限2000万 amt_lo +69.92", lq["2000万|amt_lo"]["port"]["ann"], 69.92, "+69.92%")
ck("下限3亿 amt_lo -9.64", lq["3亿|amt_lo"]["port"]["ann"], -9.64, "-9.64%")
ck("下限3亿 random -18.35", lq["3亿|random"]["port"]["ann"], -18.35, "-18.35%")
ck("下限1亿 random -8.73", lq["1亿|random"]["port"]["ann"], -8.73, "-8.73%")
# survivorship
ck("池内提前终止占比 0.144", sv["pool_dead_share_pct"], 0.144, "0.144%")
ck("选中活到样本末 +0.7935", sv["picks_live"]["mean"], 0.7935, "+0.7935%")
bad=[c for c in C if not c[0]]
for ok,name,act,nd in C:
    if not ok: print("  FAIL %-30s json=%-10s 报告含 %s" % (name, act, nd))
print("\n%s  共 %d 项, 失败 %d 项" % ("ALL PASS" if not bad else "HAS FAILURES", len(C), len(bad)))


