# -*- coding: utf-8 -*-
"""#6 三池子池分节（2026-09-18 用户需求）。

用户原话：「三个选股池把不同的子池也分开，选股结果置顶展示，不然可读性比较差」
做法：加轻量分节标题（`.pool-sec`，无 emoji，仅一条下划线 + 主标题 + 副标注），
把「选股结果 / 模拟盘 / 回测数据 / 选股指标逻辑」四类在三个池里显式分开；
中长线池的股票线与基金线各成一组（选股结果与模拟盘各自成节）。

不移动任何内容（顺序已在 #7 调好），只加分隔——**零结构风险**。
"""
import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
P = BASE / "build_dual_system.py"
OK = True

CSS = '''
/* 子池分节标题（R-poolsec-0918 · 用户需求 #6） */
.pool-sec{display:flex;align-items:baseline;gap:10px;margin:26px 2px 10px;padding-bottom:8px;
  border-bottom:1px solid var(--border)}
.pool-sec b{font-size:14.5px;font-weight:700;color:var(--text)}
.pool-sec span{font-size:12px;color:var(--faint)}
'''


def sec(label, sub):
    return f'<div class="pool-sec"><b>{label}</b><span>{sub}</span></div>\n'


PATCHES = [
    ("view-auto", "{SAT_CARD}", sec("选股结果", "股票线 · SUPER 卫星")),
    ("view-auto", "{SAT_PAPER_B_CARD}", sec("模拟盘", "股票线 · 轨B + 黄金 + ret20 臂")),
    ("view-auto", "{FB3_POOL_CARD}", sec("选股结果", "基金线 · FB3-H20")),
    ("view-auto", "{FUND_PAPER_CARD}", sec("模拟盘", "基金线 · FB3 主仓")),
    ("view-auto", "{bt_all_html()}", sec("回测数据", "中长线三轨")),
    ("view-short", "{KH_HITS_CARD}", sec("选股结果", "股票线 · KHunter 命中策略")),
    ("view-short", "{KH_PAPER_CARD}", sec("模拟盘", "股票线 · KHunter / ETF")),
    ("view-short", "{bt_short_html()}", sec("回测数据", "短线池")),
    ("view-a5", '<div class="card" id="a5-watchlist">', sec("选股结果", "双池滤网 v1.3 · 观察清单")),
    ("view-a5", '<div class="card" id="a5-positions">', sec("模拟盘", "双池 v1.3 · 持仓与净值")),
    ("view-a5", "{bt_a5_html()}", sec("回测数据", "打板双池")),
]


def main():
    global OK
    t = P.read_text(encoding="utf-8")

    if "pool-sec" not in t:
        marker = "/* 逐标的详情卡片（模板风格 · 等高适配） */"
        if t.count(marker) == 1:
            t = t.replace(marker, CSS.strip() + "\n" + marker, 1)
            print("  [ok]   CSS 已插入")
        else:
            print(f"  [FAIL] CSS 锚点命中 {t.count(marker)}")
            OK = False
    else:
        print("  [skip] CSS")

    for tag, anchor, blk in PATCHES:
        if blk + anchor in t:
            print(f"  [skip] {tag} / {blk[24:40]}")
            continue
        c = t.count(anchor)
        if c != 1:
            print(f"  [FAIL] {tag}: 锚点 {anchor[:28]} 命中 {c}")
            OK = False
            continue
        t = t.replace(anchor, blk + anchor, 1)
        print(f"  [ok]   {tag} ← {blk[21:38]}…")

    # view-short 首节：视图开标签之后
    a = "SHORT_VIEW_HTML = f'''<div class=\"view\" id=\"view-short\">\n"
    blk = sec("选股结果", "股票线 · 全量池短线")
    if blk + "{" not in t[t.index(a):t.index(a) + 200] if a in t else False:
        pass
    if a in t and blk + "{system_block(" in t:
        print("  [skip] view-short 首节")
    elif t.count(a) == 1:
        t = t.replace(a, a + blk, 1)
        print("  [ok]   view-short 首节")

    try:
        ast.parse(t)
        print("  [ok]   AST")
    except SyntaxError as e:
        print(f"  [FAIL] AST line {e.lineno}: {e.msg}")
        OK = False
        return 1
    P.write_text(t, encoding="utf-8")
    print()
    print("总结论：" + ("✅ 落地" if OK else "❌ FAIL"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
