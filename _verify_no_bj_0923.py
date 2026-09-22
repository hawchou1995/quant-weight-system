# -*- coding: utf-8 -*-
"""北交所（bj*）审计 + 池产物 0 命中 + 硬闸 fail-loud 证明（R-no-bj-0923，只读）

用法: python _verify_no_bj_0923.py

三部分：
  ① 宇宙入口审计表：策略 × 是否过滤 bj × 依据文件:行号（行号实时定位，不写死）
  ② 6 个池产物扫描：bj 命中必须 = 0（用 no_bj 的判定，命中即本脚本非零退出）
  ③ fail-loud 证明：向 no_bj.assert_clean 注入一个 bj 码 → 必须 raise（证明构建期会中止）
另附「北交所」文案残留清单（git grep，逐处标注保留/移除理由见构建报告）。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import no_bj  # noqa: E402

FAILS = []


def A(name, ok, detail=""):
    print("  [%s] %s%s" % ("ok" if ok else "FAIL", name, (" ｜ " + str(detail)) if detail else ""))
    if not ok:
        FAILS.append(name)


def find(pattern, rel, flags=0):
    """在文件里找正则，返回 (行号, 该行去空白文本) 列表。"""
    p = BASE / rel
    if not p.exists():
        return []
    out = []
    for i, ln in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if re.search(pattern, ln, flags):
            out.append((i, ln.strip()[:120]))
    return out


# ════════════════════════════════════════════════════════════════════════
print("① 宇宙入口审计（策略 × 是否排除 bj × 依据）")
# (策略/脚本, 描述, 判据正则, 依据文件, 期望是否含过滤)
AUDIT = [
    ("build_short_pool.py（短线 股票池线）", "经 short_engine.load_stock_pool 取宇宙",
     r'code\.startswith\(\("bj", "sh5", "sz1", "sh9"\)\)', "short_engine.py", True),
    ("build_a5_pool.py（A5 打板）", "经 P.is_pool_code 取宇宙（P=a5_prod/paper_daban_a5.py）",
     r"if code\.startswith\('bj'\)", "a5_prod/paper_daban_a5.py", True),
    ("v9_auto.py（中长线普适版）", "经 v8_selector.load_pool 取宇宙",
     r'code\.startswith\(\("sh5", "sz1", "bj"\)\)', "v8_selector.py", True),
    ("build_enhanced_data.py（看板中长线数据）", "经 v8_selector.load_pool（V.load_pool）",
     r'code\.startswith\(\("sh5", "sz1", "bj"\)\)', "v8_selector.py", True),
    ("backtest/build_satellite_pool.py（双卫星）", "经 signal_satellite 宇宙（只取 sh60/sz00 + 基金缓存）",
     r'c\.startswith\("sh60"\) or c\.startswith\("sz00"\)', "backtest/signal_satellite_0913.py", True),
    ("backtest/qlch_paper_20260921.py（超跌低开低吸）", "宇宙来自 _tmp_0921_qlch_sig.npz（sh/sz 前缀）",
     r'c2j = \{c: j for j, c in enumerate\(P\["codes"\]\)\}', "backtest/qlch_paper_20260921.py", None),
    ("build_dual_system.py（看板渲染）", "_board_of6 8/4/92 号段已不产出板块文案",
     r'if c\.startswith\(\("8", "4", "92"\)\)', "build_dual_system.py", True),
    ("fund_nav_update.py（场外基金线）", "宇宙 = fund_nav_cache 基金代码（无 bj 概念）",
     r"codes\.update\(f\.stem for f in sorted\(CACHE\.glob", "fund_nav_update.py", None),
    ("etf_paper_0906.py（ETF 轮动线）", "宇宙 = ETF 代码（sh5/sz1，无 bj）",
     r'ETF\w*|sh5|sz1', "etf_paper_0906.py", None),
    ("khunter_paper_20260903.py（超卖伏击模拟盘）", "宇宙只取 sh60/sz00 且剔 688/689/30",
     r'code\.startswith\("sh60"\) or code\.startswith\("sz00"\)', "khunter_paper_20260903.py", True),
]
for name, desc, pat, rel, expect in AUDIT:
    hits = find(pat, rel)
    if expect is True:
        A("%s：宇宙侧排除 bj*" % name, bool(hits),
          "%s:%s" % (rel, hits[0][0]) if hits else "未找到判据（%s）" % rel)
    else:
        print("  [--] %s%s" % (name, (" ｜ 依据 %s:%s" % (rel, hits[0][0])) if hits else ""))
    print("       %s" % desc)

# 策略侧「北交所」返回分支必须已移除
for rel, fn in (("build_short_pool.py", "board_of"), ("build_a5_pool.py", "market_board"),
                ("build_dual_system.py", "_board_of6")):
    hits = [(i, t) for i, t in find(r'return "北交所"', rel)]
    A("%s 的 %s 已无「北交所」返回分支" % (rel, fn), not hits, hits[:2])


print("\n①b 硬闸已接线（5 个池产物在**写盘前**断言；命中即 raise 中止）")
WIRED = [("build_short_pool.py", "short_pool.json"),
         ("build_a5_pool.py", "a5_pool.js"),
         ("build_enhanced_data.py", "enhanced_data.js"),
         ("backtest/build_satellite_pool.py", "satellite_pool.json"),
         ("backtest/qlch_paper_20260921.py", "qlch_candidates.json")]
for rel, art in WIRED:
    p = BASE / rel
    txt = p.read_text(encoding="utf-8") if p.exists() else ""
    call = ("_assert_clean(" in txt) and ('"%s"' % art in txt)
    A("%s 写入 %s 前调用 no_bj.assert_clean" % (rel, art), call)

print("\n①c 北交所数据与开关语义保持不变（只做下游过滤）")
_bj = list((BASE / "data_full").glob("bj*.csv"))
A("data_full/bj*.csv 保留未删（342 个）", len(_bj) == 342, "实际 %d" % len(_bj))
_ud = (BASE / "update_daily.py").read_text(encoding="utf-8")
A("update_daily 仍含 --include-bj 覆盖开关（语义不变）",
  '"--include-bj" not in args' in _ud and "跳过北交所" in _ud)
# ════════════════════════════════════════════════════════════════════════
print("\n② 池产物扫描（bj 命中必须 = 0）")
ARTIFACTS = ["short_pool.json", "a5_pool.js", "backtest/satellite_pool.json",
             "backtest/qlch_candidates.json", "enhanced_data.js"]
for rel in ARTIFACTS:
    p = BASE / rel
    if not p.exists():
        A("%s 存在" % rel, False, "文件缺失")
        continue
    hits = no_bj.bj_hits(p)
    A("%s：北交所命中 0" % rel, not hits, "命中 %s" % hits[:5])
for rel in ("short_signals.js", "dual_system.html", "backtest/qlch_paper_state_b4_k3.json",
            "khunter_paper_state.json", "khunter_paper_state_c.json", "etf_paper_state.json"):
    p = BASE / rel
    if not p.exists():
        print("  [--] %s 不存在（跳过）" % rel)
        continue
    hits = no_bj.bj_hits(p)
    A("%s：北交所命中 0" % rel, not hits, "命中 %s" % hits[:5])

print("\n①d 基金 / ETF 线脚本（宇宙 = 基金代码 / 固定 ETF 列表，结构上不含 bj）")
LINE = [("fund_nav_update.py", "fund_nav_cache 基金代码（fund_top_pool.json Top N）"),
        ("build_fund_pool.py", "fund_nav_cache 基金代码"),
        ("etf_paper_0906.py", "固定 CORE ETF 列表（data_full/{code}.csv 仅按名单取价）"),
        ("etf_dashboard_snapshot.py", "etf_momentum_20d_0906.CORE（固定 ETF 列表）"),
        ("fetch_etf_qfq.py", "ETF 数据补齐（写 data_full，不产出池产物）"),
        ("etf_opt_v2.py", "研究脚本，不产出池产物（etf_opt_v3/opt_etf_fund/fund_opt_v2 同）")]
for rel, univ in LINE:
    txt = ((BASE / rel).read_text(encoding="utf-8") if (BASE / rel).exists() else "")
    wildcard = bool(re.search(r'data_full"\)\.glob\(|glob\.glob\([^)]*data_full', txt))
    A("%s 不按 data_full 通配取宇宙（无 bj 入口）" % rel, not wildcard, univ)

# ════════════════════════════════════════════════════════════════════════
print("\n③ 硬闸 fail-loud 证明（注入 bj 码 → 必须 raise）")
try:
    no_bj.assert_clean({"codes": ["sz000931", "bj920006"]}, "负对照·注入")
    A("注入 bj920006 → 构建期 raise", False, "未 raise（静默放行！）")
except RuntimeError as e:
    A("注入 bj920006 → 构建期 raise", "no_bj" in str(e), str(e)[:90])
try:
    no_bj.assert_clean({"codes": ["bj430047"]}, "负对照·注入前缀码")
    A("注入 bj430047（带前缀）→ raise", False, "未 raise")
except RuntimeError as e:
    A("注入 bj430047（带前缀）→ raise", True, str(e)[:70])
try:
    no_bj.assert_clean({"codes": ["sz000931", "920006"]}, "负对照·注入裸码")
    A("注入裸码 920006（北交所号段）→ raise", False, "未 raise")
except RuntimeError:
    A("注入裸码 920006（北交所号段）→ raise", True)
# 反例（不得误伤）：基金 880006 / 沪深标的
try:
    no_bj.assert_clean({"codes": ["sz000931", "880006", "sh600345", "sh518880"]}, "负对照·正常码")
    A("正常码（含基金 880006）→ 不误伤", True)
except RuntimeError as e:
    A("正常码（含基金 880006）→ 不误伤", False, str(e)[:80])

# ════════════════════════════════════════════════════════════════════════
print("\n④ 「北交所」残留清单（git grep -n，逐处理由见构建报告）")
try:
    out = subprocess.run(["git", "grep", "-n", "-I", "北交所"], cwd=BASE,
                         capture_output=True, text=True, encoding="utf-8").stdout
    lines = [x for x in out.splitlines() if x.strip()]
    keep = [x for x in lines if re.search(r"^(build_dual_system\.py|ui_components\.py|update_daily\.py|build_unified_industry\.py|fullpool_v6_|compile_full_summary|exp_engine|build_market_breadth|kxmm_card)", x)]
    print("  共 %d 处命中（git grep，含研究脚本/历史注释）" % len(lines))
    for x in keep:
        print("    %s" % x[:170])
except Exception as e:
    print("  git grep 不可用:", e)

print("\n===== 结果：%d 项失败 =====" % len(FAILS))
if FAILS:
    for f in FAILS:
        print("  FAIL", f)
sys.exit(1 if FAILS else 0)
