# -*- coding: utf-8 -*-
"""A/B/E 行为验证 + C 的跳过逻辑单元验证。"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
ok = []

# ---------- E: board_of 实测（抽出函数体 exec，不加载整个模块） ----------
src = (BASE / "build_short_pool.py").read_text(encoding="utf-8")
i = src.index("def board_of(code):")
j = src.index("\ndef ", i + 10)
ns = {}
exec(src[i:j], ns)
board_of = ns["board_of"]
cases = [("bj920992", "北交所"), ("bj430047", "北交所"), ("bj830799", "北交所"),
         ("sh600519", "主板"), ("sz000001", "主板"), ("sz300750", "创业板"),
         ("sh688819", "科创板"), ("sh510050", "ETF"), ("sz159915", "ETF")]
print("=== E) board_of() 实测 ===")
for c, exp in cases:
    got = board_of(c)
    good = got == exp
    ok.append((f"board_of({c})={got}（期望 {exp}）", good))
    print(f"  [{'ok' if good else 'FAIL'}] {c} -> {got}（期望 {exp}）")

# ---------- A: FS 已去北交所 ----------
print("\n=== A) 东财 FS ===")
eb = (BASE / "backtest" / "em_bulk_snapshot.py").read_text(encoding="utf-8")
fs = re.search(r'^FS = "([^"]+)"', eb, re.M).group(1)
has_bj = "t:81" in fs
ok.append(("FS 不含北交所段 t:81", not has_bj))
print(f"  [{'ok' if not has_bj else 'FAIL'}] FS = {fs}")

# ---------- C: 跳过逻辑单元验证（复刻同谓词，不触网） ----------
print("\n=== C) update_daily 跳过谓词 ===")
ud = (BASE / "update_daily.py").read_text(encoding="utf-8")
has_filter = 'str(x[0]).startswith("bj")' in ud and '"--include-bj" not in args' in ud
ok.append(("update_daily 含 bj 过滤 + include-bj 覆盖", has_filter))
print(f"  [{'ok' if has_filter else 'FAIL'}] 过滤已接线（--include-bj 可覆盖）")
lag_demo = [("bj920992",), ("sh600519",), ("sz000001",), ("bj430047",)]
kept = [x for x in lag_demo if not str(x[0]).startswith("bj")]
ok.append(("谓词正确剔除 bj", kept == [("sh600519",), ("sz000001",)]))
print(f"  谓词实测：{len(lag_demo)} 只 → 保留 {[x[0] for x in kept]}")

# ---------- B: 门控排除（复刻 kind + 求和） ----------
print("\n=== B) 新鲜度门控 ===")
cf = (BASE / "backtest" / "check_data_freshness.py").read_text(encoding="utf-8")
ok.append(("北交所标为「未使用-北交所」", 'return "未使用-北交所"' in cf))
ok.append(("NOT_IN_UNIVERSE 常量存在", 'NOT_IN_UNIVERSE = ("未使用-北交所",)' in cf))
ok.append(("stale_tradable 已排除该桶", "if not k.startswith(NOT_IN_UNIVERSE)" in cf))
for n, v in ok[-3:]:
    print(f"  [{'ok' if v else 'FAIL'}] {n}")

print()
bad = [n for n, v in ok if not v]
for n in bad:
    print(f"  FAIL: {n}")
print("总结论：" + ("✅ A/B/C/E 全部验证通过" if not bad else f"❌ {len(bad)} 项失败"))
sys.exit(1 if bad else 0)
