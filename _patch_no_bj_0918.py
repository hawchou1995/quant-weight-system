# -*- coding: utf-8 -*-
"""北交所清理 A/B/C/E（用户 2026-09-18 批准）。

背景：核实结论——**没有任何策略用到北交所**（引擎宇宙 oss_panel 3209 票全主板、短池宇宙 5890 票
零北交所、track_a/b/c 与 A5 产物零北交所）。北交所只存在于原始归档 data_full（342 个 bj*.csv），
无下游消费者，却带来三份成本：update_daily 每次多拉 342 只、东财通道含北交所段、新鲜度分母多 342。

批准项：
  A  东财批量通道去掉北交所段（em_bulk_snapshot.py 的 FS）
  B  新鲜度分型把北交所标为「未使用」且**不计入门控 stale_tradable**（保留可观测性）
  C  update_daily 跳过 bj*（不再重拉；data_full 文件保留，故可逆）——--include-bj 可覆盖
  E  board_of() 补「北交所」分支（防雷：原 fallthrough 到「基金」，会把 bj 当基金打分）
  ✗ D 删 data_full/bj*.csv —— **不做**（不可逆；不占运行时间，只占磁盘）
"""
import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OK = True


def patch(rel, pairs, tag):
    global OK
    p = BASE / rel
    t = p.read_text(encoding="utf-8")
    for old, new, name in pairs:
        if new in t and old not in t:
            print(f"  [skip] {tag}/{name}（已打过）")
            continue
        c = t.count(old)
        if c != 1:
            print(f"  [FAIL] {tag}/{name}：锚点命中 {c} 次（期望 1）")
            OK = False
            continue
        t = t.replace(old, new, 1)
        print(f"  [ok]   {tag}/{name}")
    try:
        ast.parse(t)
    except SyntaxError as e:
        print(f"  [FAIL] {tag} AST：line {e.lineno} {e.msg}")
        OK = False
        return
    p.write_text(t, encoding="utf-8")


print("=" * 74)
print("A) 东财批量通道去掉北交所段")
print("=" * 74)
patch("backtest/em_bulk_snapshot.py", [(
    'FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"',
    '# 2026-09-18 用户拍板：**不做北交所** → FS 去掉 `m:0+t:81+s:2048`（342 只）\n'
    'FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"',
    "fs-no-bj",
)], "A")

print()
print("=" * 74)
print("B) 新鲜度：北交所标「未使用」且不计入门控")
print("=" * 74)
patch("backtest/check_data_freshness.py", [(
    '    if m == "bj":\n        return "A股-北交所"',
    '    if m == "bj":\n'
    '        # 2026-09-18 用户拍板：不做北交所 → 标为「未使用」（**不计入门控分母**，但保留可观测性）\n'
    '        return "未使用-北交所"',
    "kind-bj",
), (
    '    stale_tradable = sum(v["stale"] - v["delisted"] for v in by_kind.values())',
    '    # 门控只数「我们真的用到的宇宙」：北交所已判定不做（引擎/短池宇宙均不含），排除分母\n'
    '    stale_tradable = sum(v["stale"] - v["delisted"] for k, v in by_kind.items()\n'
    '                         if not k.startswith(NOT_IN_UNIVERSE))',
    "gate-exclude",
), (
    'def is_stock(k: str) -> bool:',
    'NOT_IN_UNIVERSE = ("未使用-北交所",)   # 不做北交所（2026-09-18 拍板）：不计入任何门控/口径统计\n\n\n'
    'def is_stock(k: str) -> bool:',
    "const",
)], "B")

print()
print("=" * 74)
print("C) update_daily 跳过 bj*（不再重拉）")
print("=" * 74)
patch("update_daily.py", [(
    "    lag = scan_lag(target_date)\n",
    "    lag = scan_lag(target_date)\n"
    "    # 2026-09-18 用户拍板：**不做北交所** → 不再重拉（data_full/bj*.csv 保留不删，故可逆；\n"
    "    # 需要临时拉回用 --include-bj）。北交所无任何下游消费者（引擎宇宙/短池宇宙均不含）。\n"
    "    if \"--include-bj\" not in args:\n"
    "        _bj = [x for x in lag if str(x[0]).startswith(\"bj\")]\n"
    "        if _bj:\n"
    "            lag = [x for x in lag if not str(x[0]).startswith(\"bj\")]\n"
    "            print(f\"  跳过北交所 {len(_bj)} 只（不做北交所；--include-bj 可覆盖）\", flush=True)\n",
    "skip-bj",
)], "C")

print()
print("=" * 74)
print("E) board_of() 补北交所分支（防雷）")
print("=" * 74)
patch("build_short_pool.py", [(
    '    if code.startswith(("sh5", "sz1")):\n        return "ETF"\n    return "基金"',
    '    if code.startswith(("sh5", "sz1")):\n        return "ETF"\n'
    '    if code.startswith("bj"):          # 2026-09-18 补：原先 fallthrough 到「基金」\n'
    '        return "北交所"                 # 会把 bj 当基金套用基金口径打分（防雷）\n'
    '    return "基金"',
    "board-bj",
)], "E")

print()
print("=" * 74)
print("编译校验")
print("=" * 74)
for rel in ("backtest/em_bulk_snapshot.py", "backtest/check_data_freshness.py",
            "update_daily.py", "build_short_pool.py"):
    try:
        ast.parse((BASE / rel).read_text(encoding="utf-8"))
        print(f"  [ok] {rel}")
    except SyntaxError as e:
        OK = False
        print(f"  [FAIL] {rel}: line {e.lineno} {e.msg}")
print()
print("总结论：" + ("✅ 全部落地" if OK else "❌ 存在 FAIL"))
sys.exit(0 if OK else 1)
