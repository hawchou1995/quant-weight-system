# -*- coding: utf-8 -*-
"""m1_census_20260928.py — 由 M2 v2 证据生成 M1 清册 + 报告制表数据 (dump)
"""
import json
import pathlib
import sys
import time
from collections import Counter

OUT = pathlib.Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system\backtest\forum8_formulas_0928")
EV = OUT / "evidence_forum8_sweep_v3_20260928.json"
d = json.loads(EV.read_text(encoding="utf-8"))
rows = d["rows"]
by = {r["id"]: r for r in rows}

# ---------------- M1 清册 ----------------
census = dict(generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
              source="https://gushi.in/forum/8 （sort=comment + sort=post，各 13 页取并集）",
              fetch=dict(channel="Firecrawl stealth", topics=len(rows), requests=304, credits_est=304),
              prereg=d["prereg"], tiers=d["tier_counts"],
              topics=[dict(id=r["id"], title=r["title"], group=r.get("group"),
                           reply_cnt=r.get("reply_cnt"), url=r["url"],
                           n_blocks=r.get("n_blocks"), code_len=r.get("code_len"),
                           code_sha1=r.get("code_sha1"), tier=r["tier"],
                           verdict=r.get("verdict"), reason=r.get("reason"),
                           signal_name=r.get("signal_name"),
                           n_events=(r.get("event") or {}).get("n"))
                      for r in sorted(rows, key=lambda x: -int(x["id"]))])
(OUT / "census_forum8_20260928.json").write_text(json.dumps(census, ensure_ascii=False, indent=1),
                                                 encoding="utf-8")

# ---------------- dump（供书写报告） ----------------
L = []
A = [r for r in rows if r["tier"] == "①"]
A.sort(key=lambda r: -r["event"]["ci95_lo_gross_buy_pct"])
L.append("### ① 可回测选股公式（%d 条，按毛口径 CI 下界降序）" % len(A))
L.append("| id | 标题 | 信号名 | n | 毛超额% | CI下界% | t | 净超额% | 净CI下界% | 判定 |")
L.append("|---|---|---|---|---|---|---|---|---|---|")
for r in A:
    e = r["event"]
    L.append("| %s | %s | %s | %d | %+.4f | %+.4f | %.2f | %+.4f | %+.4f | %s |" % (
        r["id"], r["title"].replace("|", "/")[:40], (r.get("signal_name") or "")[:10], e["n"],
        e["exc_gross_buy_pct"], e["ci95_lo_gross_buy_pct"],
        e["t_stat_gross_buy"] if e.get("t_stat_gross_buy") else float("nan"),
        e["exc_mean_buy_pct"], e["ci95_lo_buy_pct"], r["verdict"]))
L.append("")
L.append("### ④ 无法编译原因（%d 条）" % d["tier_counts"]["④"])
for k, v in Counter(str(r.get("reason", ""))[:70] for r in rows if r["tier"] == "④").most_common(20):
    L.append("- %-70s %d" % (k, v))
L.append("")
L.append("### ③ 跳过原因（%d 条）" % d["tier_counts"]["③"])
for k, v in Counter(str(r.get("reason", ""))[:70] for r in rows if r["tier"] == "③").most_common():
    L.append("- %-70s %d" % (k, v))
L.append("")
L.append("### ② 画线只登记（%d 条）" % d["tier_counts"]["②"])
for k, v in Counter(str(r.get("reason", ""))[:70] for r in rows if r["tier"] == "②").most_common():
    L.append("- %-70s %d" % (k, v))
L.append("")
L.append("### 汇总")
L.append("- 面板 %s T=%s N=%s；成本 %.4f；min_n %d；alpha %s" % (
    d["panel"]["path"], d["panel"]["T"], d["panel"]["N"], d["cost"], d["min_n"], d["alpha"]))
L.append("- placebo: %s" % json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "rows"}
                                        for k, v in (d.get("placebo") or {}).items()},
                                       ensure_ascii=False))
txt = "\n".join(L)
(OUT / "_report_tables_20260928.md").write_text(txt, encoding="utf-8")
print(txt[:600])
print("...")
print("[wrote] census_forum8_20260928.json (%d B) + _report_tables_20260928.md (%d B)"
      % ((OUT / "census_forum8_20260928.json").stat().st_size, len(txt.encode("utf-8"))))
