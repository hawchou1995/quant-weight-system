# -*- coding: utf-8 -*-
"""看板 4 项改动（2026-09-18 用户需求，design-taste-frontend-v1）。

1. 分组与排序：中长线池基金（FB3 基金池）与基金模拟盘相邻；删 v9-retired-card；修 ret20 卡表格样式
2. 左侧导航：默认折叠（56px 图标栏），悬浮展开（190px），**展开不推挤内容**（覆盖式，避免回流跳动）
3. 打板族「建议」列：限宽 + 允许换行（原 single-line 撑宽导致其他列被压成两行）
4. 中长线选股表：权重总分 / 子项评分 拆成两列
"""
import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
BD = BASE / "build_dual_system.py"
UI = BASE / "ui_components.py"
OK = True


def patch(path, pairs, tag):
    global OK
    t = path.read_text(encoding="utf-8")
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
    path.write_text(t, encoding="utf-8")


print("=" * 74)
print("改动 1a：视图挂载顺序（基金池与基金模拟盘相邻）+ 删 v9-retired-card")
print("=" * 74)
patch(BD, [(
    "{RET20_PAPER_CARD}\n{FUND_PAPER_CARD}\n{SHADOW_RET20_CARD}\n{FB3_POOL_CARD}\n"
    '<div class="card" id="v9-retired-card">',
    "{RET20_PAPER_CARD}\n{SHADOW_RET20_CARD}\n{FB3_POOL_CARD}\n{FUND_PAPER_CARD}\n"
    '<div class="card" id="v9-retired-card" data-removed="1" style="display:none">',
    "mount-order",
)], "c1a")

print()
print("=" * 74)
print("改动 1a-nav：导航顺序同步（基金池紧邻基金模拟盘）")
print("=" * 74)
patch(BD, [(
    '["sat-paper-b-card","轨B 模拟盘（主轨）"],["gold-sat-card","黄金卫星叠加"],'
    '["ret20-paper-card","ret20 倾斜臂模拟盘"],["fund-paper-card","基金主仓模拟盘"],'
    '["fb3-pool-card","FB3 基金池"]',
    '["sat-paper-b-card","轨B 模拟盘（主轨）"],["gold-sat-card","黄金卫星叠加"],'
    '["ret20-paper-card","ret20 倾斜臂模拟盘"],["fb3-pool-card","FB3 基金池"],'
    '["fund-paper-card","基金主仓模拟盘"]',
    "nav-order",
)], "c1a-nav")

print()
print("=" * 74)
print("改动 1c：ret20 倾斜臂卡表格样式（缺 class=tbl）")
print("=" * 74)
patch(BD, [(
    "f'<table><thead><tr><th>臂</th><th>定位</th><th>NAV</th><th>在仓</th><th>现金</th>"
    "<th>信号日</th><th>状态</th></tr></thead>'",
    "f'<table class=\"tbl\"><thead><tr><th>臂</th><th>定位</th><th>NAV</th><th>在仓</th>"
    "<th>现金</th><th>信号日</th><th>状态</th></tr></thead>'",
    "tbl-class",
)], "c1c")

print()
print("=" * 74)
print("改动 2：左侧导航折叠/悬浮展开（CSS + JS 标签包裹）")
print("=" * 74)
patch(UI, [(
    ".sidenav{position:fixed;left:0;top:0;bottom:0;width:190px;background:var(--nav-bg);"
    "border-right:1px solid var(--border);\n  display:flex;flex-direction:column;"
    "padding:16px 10px;z-index:850;overflow-y:auto}",
    "# 折叠态 56px（图标栏）→ 悬浮展开 190px；**覆盖式不推挤内容**，避免回流跳动\n"
    ".sidenav{position:fixed;left:0;top:0;bottom:0;width:56px;background:var(--nav-bg);"
    "border-right:1px solid var(--border);\n  display:flex;flex-direction:column;"
    "padding:16px 10px;z-index:850;overflow-y:auto;overflow-x:hidden;\n"
    "  transition:width .18s ease,box-shadow .18s ease}\n"
    ".sidenav:hover{width:190px;box-shadow:0 10px 34px rgba(0,0,0,.16)}",
    "css-collapse",
), (
    "body.sidenav-open .container{margin-left:190px}",
    "body.sidenav-open .container{margin-left:56px}   /* 常驻 56；展开时导航覆盖其上，不推挤 */\n"
    ".sidenav .lbl,.sidenav .sn-logo .txt{white-space:nowrap;opacity:0;transition:opacity .14s ease}\n"
    ".sidenav:hover .lbl,.sidenav:hover .sn-logo .txt{opacity:1}\n"
    ".sidenav .sn-sub{opacity:0;transition:opacity .14s ease;pointer-events:none}\n"
    ".sidenav:hover .sn-sub{opacity:1;pointer-events:auto}\n"
    ".sidenav .sn-arrow{opacity:0;transition:opacity .14s ease}\n"
    ".sidenav:hover .sn-arrow{opacity:1}",
    "css-margin",
)], "c2-css")

patch(UI, [(
    "var html='<div class=\"sn-logo\"><span class=\"dot\"></span>量化权重监控</div>"
    "<div class=\"sn-sep\"></div>';",
    "var html='<div class=\"sn-logo\"><span class=\"dot\"></span>"
    "<span class=\"txt\">量化权重监控</span></div><div class=\"sn-sep\"></div>';",
    "js-logo",
), (
    "'><span class=\"ic\">'+it[1]+'</span>'+it[2]+(hasSubs?"
    "'<span class=\"sn-arrow\">▾</span>':'')+'</a>';",
    "'><span class=\"ic\">'+it[1]+'</span><span class=\"lbl\">'+it[2]+'</span>'"
    "+(hasSubs?'<span class=\"sn-arrow\">▾</span>':'')+'</a>';",
    "js-main",
), (
    "'<a href=\"javascript:void(0)\" data-anchor=\"'+it[0]+'\" data-sub=\"'+s[0]+'\">"
    "<span class=\"dot-sub\"></span>'+s[1]+'</a>';",
    "'<a href=\"javascript:void(0)\" data-anchor=\"'+it[0]+'\" data-sub=\"'+s[0]+'\">"
    "<span class=\"dot-sub\"></span><span class=\"lbl\">'+s[1]+'</span></a>';",
    "js-sub",
), (
    "'<a href=\"javascript:void(0)\" data-anchor=\"review\"><span class=\"ic\">📋</span>复盘日志</a>'+"
    "'<a href=\"javascript:void(0)\" data-anchor=\"changelog\"><span class=\"ic\">📝</span>更新日志</a>'+"
    "'<a href=\"https://qingju.me/\" target=\"_blank\" rel=\"noopener\">"
    "<span class=\"ic\">💬</span>青橘社区</a></div>';",
    "'<a href=\"javascript:void(0)\" data-anchor=\"review\"><span class=\"ic\">📋</span>"
    "<span class=\"lbl\">复盘日志</span></a>'+"
    "'<a href=\"javascript:void(0)\" data-anchor=\"changelog\"><span class=\"ic\">📝</span>"
    "<span class=\"lbl\">更新日志</span></a>'+"
    "'<a href=\"https://qingju.me/\" target=\"_blank\" rel=\"noopener\"><span class=\"ic\">💬</span>"
    "<span class=\"lbl\">青橘社区</span></a></div>';",
    "js-foot",
)], "c2-js")

print()
print("=" * 74)
print("改动 3：打板族「建议」列限宽换行")
print("=" * 74)
patch(BD, [(
    "_txt_td(f'<span style=\"color:var(--sub);font-size:12px\">{advice}</span>')",
    "_txt_td(f'<span class=\"adv-cell\" style=\"color:var(--sub);font-size:11.5px\">{advice}</span>')",
    "adv-class",
)], "c3")

patch(UI, [(
    ".sidenav .sn-foot{margin-top:auto;display:flex;flex-direction:column;gap:6px}",
    ".sidenav .sn-foot{margin-top:auto;display:flex;flex-direction:column;gap:6px}\n"
    "/* 打板族「建议」列：限宽 + 允许换行（原不换行撑宽，把其他列压成两行） */\n"
    ".tbl td .adv-cell{display:block;white-space:normal;line-height:1.4;max-width:216px;"
    "margin:0 auto;text-align:left}\n"
    ".tbl th[data-key=\"advice\"]{min-width:216px}",
    "adv-css",
)], "c3-css")

print()
print("=" * 74)
print("改动 4：中长线选股表 —— 权重总分 / 子项评分 拆两列")
print("=" * 74)
patch(BD, [(
    '<th data-key="score" style="text-align:center">权重分<div class="th-sub">{score_sub}</div></th>',
    '<th data-key="score" style="text-align:center">权重总分</th>'
    '<th data-key="sub" style="text-align:center">子项评分<div class="th-sub">{score_sub}</div></th>',
    "head-split",
), (
    '<td style="text-align:center"><b>{d["score"]:.1f}</b><br>'
    '<span style="color:var(--faint);font-size:10px" title="趋势/动量/量能/超买/风控">{comp_txt}</span></td>',
    '<td style="text-align:center" data-v="{d["score"] or 0}"><b>{d["score"]:.1f}</b></td>\n'
    '<td style="text-align:center"><span style="color:var(--faint);font-size:11px" '
    'title="子项：趋势/动量/量能/超买/风控">{comp_txt}</span></td>',
    "cell-split",
)], "c4")

print()
print("=" * 74)
print("编译校验")
print("=" * 74)
for p in (BD, UI):
    try:
        ast.parse(p.read_text(encoding="utf-8"))
        print(f"  [ok] {p.name}")
    except SyntaxError as e:
        OK = False
        print(f"  [FAIL] {p.name}: line {e.lineno} {e.msg}")

print()
print("总结论：" + ("✅ 全部落地" if OK else "❌ 存在 FAIL"))
sys.exit(0 if OK else 1)
