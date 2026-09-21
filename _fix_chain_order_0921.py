# -*- coding: utf-8 -*-
"""2026-09-21 用户批准的修复 ①链序 ②复权候选（gushi 授权同日批准，但受余额限制，见报告）。

① 链序缺陷（2026-09-21 收盘链实测）：`index_000300.csv` 的当日行由 `ensure_index_row`
   写入，而它排在 fullpool_guard / em_bulk / heatmap **之后** → 这三个步骤在链启动时
   读到的末行是**上一交易日**，导致：
     · check_data_freshness 判「交易日 = 09-18」→ 得出「陈旧 14」的错误新鲜结论
     · fullpool_guard 误判「全量池新鲜，无需补数」
     · em_bulk 的口径校验拿本地 09-18 对东财 09-21 → 不一致率爆表 → rc=2 拒写
       （**拒写行为正确**：口径硬门；错的是输入基准日）
   → 全池没补到 09-21 → 涨停全景只有 14 只、短线池显示旧数据。
   修法：把 `HS300 索引行 ensure_index_row` 提到「数据更新」之后（它是交易日判定步，
   本来就该在依赖"当日"概念的步骤之前）。

② 复权基准检测把 2400s 预算全烧在北交所（2026-09-21 实测）：`scan_rebase_candidates`
   用 `sorted(OUT_DIR.glob("*.csv"))`，`bj*` 排最前；北交所文件自 09-18 起不再更新
   （末行停在 09-18）→ **永远都是候选**，每个上限 90s → 沪深候选一个都轮不到。
   修法：候选扫描同样跳过 bj（与 update_daily 的滞后清单同一口径）。

③ gushi：用户批准「没会员就帮我开，仅限开市日」。`--renew` 机制已在采集器内
   （每日 1 次上限 + 余额不足不扣分 + 非 vip 不落盘），且该步骤位于所有 STEPS 之后
   → 天然只有开市日才会执行。**本次不改代码**；实际阻塞是积分余额（09-18 时为 23 < 30）。
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
            print(f"  [FAIL] {tag}/{name}：命中 {c} 次")
            OK = False
            continue
        t = t.replace(old, new, 1)
        print(f"  [ok]   {tag}/{name}")
    try:
        ast.parse(t)
    except SyntaxError as e:
        print(f"  [FAIL] {tag} AST line {e.lineno}: {e.msg}")
        OK = False
        return
    p.write_text(t, encoding="utf-8")


print("=" * 74)
print("① 链序：ensure_index_row 提到数据更新之后")
print("=" * 74)
patch("daily_refresh.py", [
    # 摘出原条目（连注释）
    ("    # HS300 指数行维护 + 交易日闸门（R-gate-0917）：exit 3 = 今日行情不可得（非交易日/未就绪）→ 主链跳过后续\n"
     "    (\"HS300 索引行 ensure_index_row\", [\"backtest/ensure_index_row.py\"], False),\n",
     "",
     "摘出"),
    # 插到数据更新之后
    ("    (\"数据更新 update_daily\", [\"update_daily.py\"], \"--skip-data\" in sys.argv),\n",
     "    (\"数据更新 update_daily\", [\"update_daily.py\"], \"--skip-data\" in sys.argv),\n"
     "    # HS300 指数行维护 + 交易日闸门（R-gate-0917）：exit 3 = 今日行情不可得（非交易日/未就绪）→ 主链跳过后续\n"
     "    # 2026-09-21 修：**必须紧跟在数据更新之后**——它是唯一写入 index_000300 当日行的步骤，\n"
     "    # 而 fullpool_guard / em_bulk / heatmap 都靠该文件末行判定「今日」。原先排在它们之后\n"
     "    # → 三步拿到上一交易日做基准：freshness 误报新鲜、guard 漏补、em_bulk 口径校验拒写(rc=2)。\n"
     "    (\"HS300 索引行 ensure_index_row\", [\"backtest/ensure_index_row.py\"], False),\n",
     "插入"),
], "①")

print()
print("=" * 74)
print("② 复权候选跳过北交所")
print("=" * 74)
patch("update_daily.py", [
    ("    for f in sorted(OUT_DIR.glob(\"*.csv\")):\n"
     "        if f.stat().st_size < 100:\n"
     "            continue\n",
     "    for f in sorted(OUT_DIR.glob(\"*.csv\")):\n"
     "        if f.stem.startswith(\"bj\"):\n"
     "            continue   # 2026-09-21：不做北交所（与滞后清单同口径；否则每日候选首位全被 bj* 占满）\n"
     "        if f.stat().st_size < 100:\n"
     "            continue\n",
     "skip-bj"),
], "②")

print()
print("编译 + 顺序校验")
try:
    ast.parse((BASE / "daily_refresh.py").read_text(encoding="utf-8"))
    ast.parse((BASE / "update_daily.py").read_text(encoding="utf-8"))
    print("  [ok]   AST")
except SyntaxError as e:
    print(f"  [FAIL] AST: {e}")
    OK = False

src = (BASE / "daily_refresh.py").read_text(encoding="utf-8")
order = [m.group(1) for m in __import__("re").finditer(r'\("([^"]+)",', src)]
for want, where in [("数据更新 update_daily", 0), ("HS300 索引行 ensure_index_row", 1),
                    ("全量池守卫 fullpool_guard[软]", 2), ("东财批量补齐 em_bulk[软]", 3)]:
    got = order.index(want) if want in order else -1
    ok = got == where
    print(f"  [{'ok' if ok else 'FAIL'}] 步骤序 {where}: {want}（实际 {got}）")
    if not ok:
        OK = False
print()
print("总结论：" + ("✅ 落地" if OK else "❌ FAIL"))
sys.exit(0 if OK else 1)
