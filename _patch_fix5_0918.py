# -*- coding: utf-8 -*-
"""看板修复包（2026-09-18 用户 11 项之 5/1/2/3/9）。

#5 真因（我上轮漏了）：用户看的「中长线选股池」= 卫星目标持仓表，其表头写死
    `"<th>评分 = 总分 + 子项</th>"`、单元格把 score_txt 与 parts 塞进同一个 <td>。
    我上轮改的是 system_block 模板里的另一张表 → 线上仍有 1 处未拆，验证属假通过。
#1/#2 真因：`ui_components.py:163` 的 `.topbar`（品牌栏，sticky）与我加的 `.sidenav`（横 tab）
    是两条栏 → 合并为一条 `position:fixed` 的固定顶栏。
#3 真因：ECharts 默认 tooltip backgroundColor = 'rgba(50,50,50,.7)'（近黑）→ 按主题色显式指定。
#9 徽章加 HH:MM:SS 实时时钟（每秒刷新，顺带重算开市状态）。
"""
import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
BD = BASE / "build_dual_system.py"
UI = BASE / "ui_components.py"
KX = BASE / "kxmm_card.py"
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
print("⑤ 卫星目标持仓表：评分总分 / 子项评分 真拆分")
print("=" * 74)
patch(BD, [(
    '        head = ("<th>代码</th><th>名称</th><th>行业</th><th>收盘</th><th>一手约</th><th>计划金额</th>"\n'
    '                "<th>评分 = 总分 + 子项</th><th>操作</th><th>涨跌幅</th><th>近1年</th>")',
    '        head = ("<th>代码</th><th>名称</th><th>行业</th><th>收盘</th><th>一手约</th><th>计划金额</th>"\n'
    '                "<th>评分总分</th><th>子项评分</th><th>操作</th><th>涨跌幅</th><th>近1年</th>")',
    "head-split",
), (
    '                f\'<td title="{r.get("detail", "")}"><b>{r.get("score_txt", "—")}</b>\'\n'
    '                f\'<div style="font-size:10.5px;color:#94a3b8;line-height:1.35;white-space:normal;'
    'max-width:190px">{r.get("parts", "")}</div></td>\'',
    '                f\'<td title="{r.get("detail", "")}"><b>{r.get("score_txt", "—")}</b></td>\'\n'
    '                f\'<td><div style="font-size:10.5px;color:#94a3b8;line-height:1.35;'
    'white-space:normal;max-width:190px" title="{r.get("detail", "")}">{r.get("parts", "")}</div></td>\'',
    "cell-split",
)], "⑤")

print()
print("=" * 74)
print("① 两条栏合并为一条（sidenav 移进 .topbar）")
print("=" * 74)
patch(UI, [(
    '<div class="topbar">\n'
    '  <div class="logo" onclick="location.hash=\'#overview\'"><span class="dot"></span>量化权重监控</div>\n'
    '  <div class="spacer"></div>',
    '<div class="topbar">\n'
    '  <div class="logo" onclick="location.hash=\'#overview\'"><span class="dot"></span>量化权重监控</div>\n'
    '  <div class="sidenav" id="sidenav"></div>\n'
    '  <div class="spacer"></div>',
    "move-sidenav",
), (
    '</div>\n<div class="sidenav" id="sidenav"></div>\n"""',
    '</div>\n"""',
    "drop-outer-sidenav",
)], "①")

print()
print("=" * 74)
print("② 顶栏固定（position:fixed）+ 单栏布局")
print("=" * 74)
patch(UI, [(
    ".topbar{position:sticky;top:0;z-index:900;background:var(--nav-bg);border-bottom:1px solid var(--border);\n"
    "  box-shadow:var(--shadow);display:flex;align-items:center;gap:14px;padding:10px 22px;flex-wrap:wrap}",
    "/* 单条固定顶栏（2026-09-18 用户 #1/#2：原先品牌栏+横 tab 两条栏 → 合并；且必须 fixed 不随滚动走） */\n"
    ".topbar{position:fixed;top:0;left:0;right:0;z-index:900;height:56px;background:#1b2130;\n"
    "  border-bottom:1px solid rgba(255,255,255,.08);display:flex;align-items:center;\n"
    "  gap:10px;padding:0 16px;flex-wrap:nowrap}\n"
    "body{padding-top:56px}\n"
    ".topbar .logo{color:#fff}\n"
    ".topbar .tb-btn{background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.16);color:#fff}\n"
    ".topbar .tb-btn:hover{background:rgba(255,255,255,.18)}\n"
    ".topbar .community{background:rgba(255,255,255,.10);color:#fff}",
    "topbar-fixed",
), (
    "/* 顶部横导航（2026-09-18 · 用户决策「顶部横 tab」）：深色通栏 + 扁平 tab，仿 gushi 语言 */\n"
    ".sidenav{position:sticky;top:0;left:0;right:0;width:auto;height:54px;"
    "background:#1b2130;border-right:none;\n  border-bottom:1px solid var(--border);"
    "display:flex;flex-direction:row;align-items:center;gap:2px;\n"
    "  padding:0 16px;z-index:850;overflow:visible}",
    "/* 横 tab 组（已并入 .topbar，2026-09-18）：透明内联，不再是独立一栏 */\n"
    ".sidenav{position:static;flex:1;min-width:0;display:flex;flex-direction:row;\n"
    "  align-items:center;gap:2px;overflow-x:auto;overflow-y:visible;padding:0;background:transparent}",
    "sidenav-inline",
)], "②")

print()
print("=" * 74)
print("③ 热力图 tooltip 去黑框（按主题色）")
print("=" * 74)
patch(KX, [(
    "    charts.heat.setOption({\n      tooltip:{\n        formatter:function(p){",
    "    var _cs=getComputedStyle(document.documentElement);\n"
    "    var _cardC=(_cs.getPropertyValue('--card')||'#fff').trim();\n"
    "    var _bordC=(_cs.getPropertyValue('--border')||'#e5e7eb').trim();\n"
    "    var _textC=(_cs.getPropertyValue('--text')||'#111827').trim();\n"
    "    charts.heat.setOption({\n"
    "      tooltip:{\n"
    "        backgroundColor:_cardC, borderColor:_bordC, borderWidth:1,\n"
    "        textStyle:{color:_textC, fontSize:12},\n"
    "        extraCssText:'box-shadow:0 8px 26px rgba(0,0,0,.14);border-radius:10px;"
    "padding:10px 12px;line-height:1.6',\n"
    "        formatter:function(p){",
    "tooltip-theme",
)], "③")

print()
print("=" * 74)
print("⑨ 徽章加实时时钟（每秒刷新 + 重算开市状态）")
print("=" * 74)
patch(UI, [(
    "  return '<span class=\"mkt-badge '+cls+'\" title=\"交易日 '+((s.tradeDay)||'—')"
    "+' · 本地时钟判定\"><span class=\"d\"></span>'+txt+'</span>';\n}",
    "  return '<span class=\"mkt-badge '+cls+'\" title=\"交易日 '+((s.tradeDay)||'—')"
    "+' · 本地时钟判定\"><span class=\"d\"></span>'+txt\n"
    "    +'<span class=\"clk\" style=\"font-variant-numeric:tabular-nums;opacity:.85\">'\n"
    "    +p(now.getHours())+':'+p(now.getMinutes())+':'+p(now.getSeconds())+'</span></span>';\n"
    "}\n"
    "function tickClock(){var b=document.querySelector('.mkt-badge');if(!b)return;\n"
    "  var h=mktBadgeHtml();var t=document.createElement('div');t.innerHTML=h;var nb=t.firstChild;\n"
    "  b.className=nb.className;b.innerHTML=nb.innerHTML;b.title=nb.title;}\n"
    "setInterval(tickClock,1000);",
    "clock",
)], "⑨")

print()
print("=" * 74)
print("编译校验")
print("=" * 74)
for p in (BD, UI, KX):
    try:
        ast.parse(p.read_text(encoding="utf-8"))
        print(f"  [ok] {p.name}")
    except SyntaxError as e:
        OK = False
        print(f"  [FAIL] {p.name}: line {e.lineno} {e.msg}")
print()
print("总结论：" + ("✅ 落地" if OK else "❌ 存在 FAIL"))
sys.exit(0 if OK else 1)
