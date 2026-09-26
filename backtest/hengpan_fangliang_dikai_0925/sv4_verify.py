# -*- coding: utf-8 -*-
"""sv4: mechanical cross-check of §12/§13 against artifacts."""
import json, hashlib, pathlib
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
D = R/"backtest/hengpan_fangliang_dikai_0925"
pre = (R/"backtest/PRE-REGISTRATION_20260926_hengpan_dikai_oos.md").read_text(encoding="utf-8").replace("\u2212","-")
rep = (R/"backtest/报告-横盘放量次日低开-优化方向研究-20260926.md").read_text(encoding="utf-8").replace("\u2212","-")
L = lambda p: json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
sv = L(D/"evidence_survivorship_fix.json"); meta = L(R/"backtest/_delisted_universe/delisted_meta.json")
ros = L(D/"evidence_delisted_roster.json"); oos = L(D/"oos_report.json"); ost = L(D/"oos_state.json")
C=[]
def ck(name, actual, expect, needle, where):
    txt = rep if where=="rep" else pre
    ok = abs(float(actual)-float(expect)) < 1e-6 and (needle in txt)
    C.append((ok,name,actual,needle,where))
ck("仅现存 年化 +143.06", sv["仅现存(5207)"]["ann"], 143.06, "+143.06%", "rep")
ck("仅现存 净均 +0.8153", sv["仅现存(5207)"]["mean"], 0.8153, "+0.8153%", "rep")
ck("扩展 年化 +127.91", sv["扩展(5207+250退市)"]["ann"], 127.91, "+127.91%", "rep")
ck("扩展 净均 +0.7845", sv["扩展(5207+250退市)"]["mean"], 0.7845, "+0.7845%", "rep")
ck("扩展 净中位 +0.6047", sv["扩展(5207+250退市)"]["med"], 0.6047, "+0.6047%", "rep")
ck("扩展 净胜率 56.11", sv["扩展(5207+250退市)"]["wr"], 56.11, "56.11%", "rep")
ck("退市股笔数 3384", sv["扩展(5207+250退市)"]["n_dead"], 3384, "3,384", "rep")
ck("退市股净均 +0.4993", sv["扩展(5207+250退市)"]["dead_mean"], 0.4993, "+0.4993%", "rep")
ck("退市股占比 13.90", round(3384/24346*100,2), 13.90, "13.90%", "rep")
ck("退市名录 253", len(ros), 253, "**253 只**", "rep")
ck("退市行情行数 474444", meta["n_rows"], 474444, "474,444", "rep")
ck("退市行情 0 失败", meta["fails"], 0, "253/253 成功，0 失败", "rep")
sha = hashlib.sha256((D/"oos_run.py").read_bytes()).hexdigest()
ck("脚本哈希一致", 1 if sha==oos["frozen_script_sha256"]==ost["frozen_script_sha256"] else 0, 1, "53040b9c9c225a1d572273fe5024775d824c93320eb260dee9dd9ce1dc29a6fe", "pre")
ck("shadow_start", 1 if oos["shadow_start"]=="2026-09-25" else 0, 1, "2026-09-25", "pre")
ck("OOS 当前样本数 0", oos["acceptance"]["n"], 0, "尚未开始", "rep")
bad=[c for c in C if not c[0]]
for ok,name,act,nd,w in C:
    if not ok: print("  FAIL %-26s json=%-12s 缺 %s in %s" % (name, act, nd, w))
print("\n%s  共 %d 项, 失败 %d 项" % ("ALL PASS" if not bad else "HAS FAILURES", len(C), len(bad)))
