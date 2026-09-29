# -*- coding: utf-8 -*-
"""errata_e19_attrib.py — 查清「Δ+6.13pp」到底是谁造成的
三臂对拍（同一面板、同一 sim_portfolio、2018+ 窗口 start='2018-01-01'）：
  A) v1.5 原样            : (~STP) & (~STNOW) & (C>=3) & BPSA>=3
  B) 只去 STNOW (v1.6)    : (~STP)              & (C>=3) & BPSA>=3      ← E-19
  C) 去 STNOW + 去 BPSA    : (~STP)              & (C>=3)              ← 未来函数核查脚本当时的探针（误）
预期：C ≈ +69.99%（复现那份报告的数字）⇒ 证明 +6.13pp 的真因是 BPSA 滤网，不是 STNOW。
"""
import importlib.util
import json
import os
import pathlib
import re
import sys

D = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(D))
import x2_sens as X  # noqa: E402

cache = D / ".x3cache"     # 【2026-09-29 修】改用与 x2_sens 同一个面板缓存（scratch 目录已清空）
OUT = D / "oos_run.py"

# 【勘误 E-22 · 2026-09-29 修】原锚点是旧 FILT 文本（已随 E-19/E-22 改写）⇒ 改为
# 「从 m = (~STP… 到 return m」整段匹配，对 FILT 内部改写免疫。
OLD = re.compile(
    r"        m = \(~STP\[t\]\) & \(C\[t\] >= 3\.0\).*?\n        return m\n",
    re.S)
NEW_C = ("        m = (~STP[t]) & (C[t] >= 3.0)          # 探针 C：去 STNOW + 去 BPSA\n"
         "        return m")
probe = D / "_tmp_probeC_oos_run.py"   # 必须与 oos_run.py 同目录：脚本用 parents[2] 定位仓库根

src = OUT.read_text(encoding="utf-8")
hits = OLD.findall(src)
assert len(hits) == 1, "anchor x%d" % len(hits)
probe.write_text(OLD.sub(NEW_C, src, count=1), encoding="utf-8")
print("[probe] wrote %s" % probe.name)

X.OOS = OUT
mod = X.load_mod()
cal, syms, F, done = X.get_panel(mod, cache)
print("[panel] T=%d N=%d" % (len(cal), len(syms)))

KEEP = ("ann", "mdd", "sharpe", "n_trades", "mean_per_trade", "win_rate")
res = {}


def snap(recs, P, tag):
    m = X.sim_portfolio(recs, cal, syms, F, int(P["K"]), int(P["KSLOT"]),
                        float(P["COST_SIDE"]), start="2018-01-01")
    res[tag] = dict(n=len(recs), **{k: m[k] for k in KEEP})


# A) v1.5 原样
recs, P = X.run_variant(mod, cache, cal, F, done, "attr_A_v15",
                        {"STNOW_LIVE_ONLY": False, "STP_CNT": 0})   # v1.5 = 全量剔现名 + 无 A
snap(recs, P, "A_v15")
# B) v1.6（只去 STNOW）
recs, P = X.run_variant(mod, cache, cal, F, done, "attr_B_v16", None)
snap(recs, P, "B_v16")
# C) 去 STNOW + 去 BPSA（复现当时探针）
spec = importlib.util.spec_from_file_location("oos_run_probeC", probe)
mp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mp)
mp.STATE_F = cache / "_v_attr_C_state.json"
mp.TRADES_F = cache / "_v_attr_C_trades.jsonl"
mp.REPORT_F = cache / "_v_attr_C_report.json"
for p in (mp.STATE_F, mp.TRADES_F, mp.REPORT_F):
    if p.exists():
        p.unlink()
P0 = dict(X.BASE_P)
mp.P.clear()
mp.P.update(P0)
mp.build = lambda _c, _s: (F, done)
mp.main()
recsC = [json.loads(x) for x in mp.TRADES_F.read_text(encoding="utf-8").splitlines() if x.strip()]
snap(recsC, P0, "C_nostnow_noBPSA")

print("\n%-20s %8s %8s %8s %8s %9s %8s" % ("臂", "年化%", "MDD%", "夏普", "笔数", "单笔均%", "胜率%"))
for k, v in res.items():
    print("%-20s %+8.2f %8.2f %8.2f %8d %9.4f %8.2f"
          % (k, v["ann"], v["mdd"], v["sharpe"], v["n_trades"], v["mean_per_trade"], v["win_rate"]))
base = res["A_v15"]["ann"]
print("\n未来函数核查报告称「去掉 STNOW → 2018+ 年化 +69.99%（Δ+6.13pp）」")
print("  E-19（只去 STNOW）实测 2018+ = %+.2f%%（Δ %+.2fpp）" % (res["B_v16"]["ann"], res["B_v16"]["ann"] - base))
print("  探针 C（同时去 BPSA）       = %+.2f%%（Δ %+.2fpp）" % (res["C_nostnow_noBPSA"]["ann"],
                                                              res["C_nostnow_noBPSA"]["ann"] - base))
(D / "evidence_errata_e19_attrib.json").write_text(
    json.dumps({"purpose": "查清未来函数核查报告里 +6.13pp 的真因（STNOW vs BPSA 滤网）",
                "window": "2018-01-01 起", "sim": "x2_sens.sim_portfolio(order=entry_first)",
                "arms": res,
                "verdict": "见 report 与 E-19a"}, ensure_ascii=False, indent=1), encoding="utf-8")
print("[wrote] evidence_errata_e19_attrib.json")
