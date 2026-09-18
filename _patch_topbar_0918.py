# -*- coding: utf-8 -*-
"""看板改版第一步 · 顶部横 tab（2026-09-18 用户 7 项决策之 1/2/4/6/7）。

纪律（吸取本会话教训）：
  · CSS/JS 字符串里**只能**用 /* */ 注释 —— 上次把 Python 的 # 写进 CSS，
    把紧随的 .sidenav 规则整条吞掉（实测 1905px）。
  · 字符串拼接不得跨行插注释（会截断隐式拼接）。
  · 每处替换先验锚点唯一性，再 AST 校验。
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
print("① CSS：左侧竖栏 → 顶部横栏（gushi 深色通栏 + 扁平 tab）")
print("=" * 74)
patch(UI, [(
    "/* 折叠态 56px（图标栏）→ 悬浮展开 190px；覆盖式不推挤内容，避免回流跳动 */\n"
    ".sidenav{position:fixed;left:0;top:0;bottom:0;width:56px;background:var(--nav-bg);"
    "border-right:1px solid var(--border);\n  display:flex;flex-direction:column;"
    "padding:16px 10px;z-index:850;overflow-y:auto;overflow-x:hidden;\n"
    "  transition:width .18s ease,box-shadow .18s ease}\n"
    ".sidenav:hover{width:190px;box-shadow:0 10px 34px rgba(0,0,0,.16)}",
    "/* 顶部横导航（2026-09-18 · 用户决策「顶部横 tab」）：深色通栏 + 扁平 tab，仿 gushi 语言 */\n"
    ".sidenav{position:sticky;top:0;left:0;right:0;width:auto;height:54px;"
    "background:#1b2130;border-right:none;\n  border-bottom:1px solid var(--border);"
    "display:flex;flex-direction:row;align-items:center;gap:2px;\n"
    "  padding:0 16px;z-index:850;overflow:visible}",
    "topbar-base",
), (
    ".sidenav .sn-logo{font-size:14px;font-weight:700;padding:2px 10px 14px;"
    "display:flex;align-items:center;gap:8px}",
    ".sidenav .sn-logo{font-size:14px;font-weight:700;padding:0 16px 0 0;margin-right:8px;"
    "display:flex;align-items:center;gap:8px;color:#fff;\n"
    "  border-right:1px solid rgba(255,255,255,.16);height:22px}",
    "logo",
), (
    ".sidenav .sn-sep{height:1px;background:var(--line);margin:8px 6px}",
    ".sidenav .sn-sep{width:1px;height:22px;background:rgba(255,255,255,.16);margin:0 6px;flex:none}",
    "sep",
), (
    ".sidenav a{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:10px;\n"
    "  color:var(--sub);text-decoration:none;font-size:13px;margin-bottom:2px;transition:all .15s}",
    ".sidenav a{display:inline-flex;align-items:center;gap:8px;padding:8px 14px;border-radius:9px;\n"
    "  color:rgba(255,255,255,.74);text-decoration:none;font-size:13px;"
    "transition:all .15s;white-space:nowrap}",
    "link",
), (
    ".sidenav a:hover{background:var(--card2);color:var(--text)}",
    ".sidenav a:hover{background:rgba(255,255,255,.10);color:#fff}",
    "hover",
), (
    ".sidenav a.active{background:linear-gradient(135deg,rgba(245,158,11,.15),"
    "rgba(239,68,68,.15));color:var(--accent);font-weight:600}",
    ".sidenav a.active{background:linear-gradient(135deg,#FF9A3D 0%,#F2701D 100%);"
    "color:#fff;font-weight:600}",
    "active",
), (
    ".sidenav .sn-sub{margin:0 0 8px 22px;display:flex;flex-direction:column;gap:2px}",
    "/* 子章节下拉暂收起（gushi 无子导航；内容一张不丢，只在视图内）。下一轮补 hover 下拉 */\n"
    ".sidenav .sn-sub{display:none;margin:0;flex-direction:row;gap:2px}",
    "sub-hide",
), (
    ".sidenav .sn-foot{margin-top:auto;display:flex;flex-direction:column;gap:6px}",
    ".sidenav .sn-foot{margin-top:0;margin-left:auto;display:flex;flex-direction:row;"
    "align-items:center;gap:8px}\n"
    "/* 开市/休市五态徽章（用户决策 4） */\n"
    ".mkt-badge{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;\n"
    "  padding:4px 11px;border-radius:20px;border:1px solid transparent;white-space:nowrap}\n"
    ".mkt-badge .d{width:7px;height:7px;border-radius:50%;background:currentColor;flex:none}\n"
    ".mkt-open{background:rgba(16,185,129,.16);color:#34d399;border-color:rgba(16,185,129,.35)}\n"
    ".mkt-mid{background:rgba(245,158,11,.16);color:#fbbf24;border-color:rgba(245,158,11,.35)}\n"
    ".mkt-rest{background:rgba(148,163,184,.16);color:#94a3b8;border-color:rgba(148,163,184,.3)}\n"
    ".mkt-pre{background:rgba(59,130,246,.16);color:#60a5fa;border-color:rgba(59,130,246,.35)}",
    "foot-badge-css",
), (
    "body.sidenav-open .container{margin-left:56px}   /* 常驻 56；展开时导航覆盖其上，不推挤 */\n"
    ".sidenav .lbl,.sidenav .sn-logo .txt{white-space:nowrap;opacity:0;transition:opacity .14s ease}\n"
    ".sidenav:hover .lbl,.sidenav:hover .sn-logo .txt{opacity:1}\n"
    ".sidenav .sn-sub{opacity:0;transition:opacity .14s ease;pointer-events:none}\n"
    ".sidenav:hover .sn-sub{opacity:1;pointer-events:auto}\n"
    ".sidenav .sn-arrow{opacity:0;transition:opacity .14s ease}\n"
    ".sidenav:hover .sn-arrow{opacity:1}",
    "/* 顶部横栏：内容不再被导航占位；标签常显（原折叠态的 opacity/transition 全部移除） */\n"
    "body.sidenav-open .container{margin-left:0;padding-top:22px}\n"
    ".sidenav .sn-arrow{display:none}",
    "container-full",
)], "①")

print()
print("=" * 74)
print("② JS：子项可指定目标视图；tab 支持外链")
print("=" * 74)
patch(UI, [(
    "    var subs=it[3];\n    var hasSubs=subs&&subs.length;\n"
    "    html+='<a href=\"javascript:void(0)\" data-anchor=\"'+it[0]+'\"'"
    "+(hasSubs?' data-toggle=\"1\"':'')+'><span class=\"ic\">'+it[1]+'</span>"
    "<span class=\"lbl\">'+it[2]+'</span>'+(hasSubs?'<span class=\"sn-arrow\">▾</span>':'')+'</a>';",
    "    var subs=it[3];\n    var hasSubs=subs&&subs.length;\n"
    "    var ext=it[4];\n"
    "    if(ext){\n"
    "      html+='<a href=\"'+ext+'\" target=\"_blank\" rel=\"noopener\"><span class=\"ic\">'"
    "+it[1]+'</span><span class=\"lbl\">'+it[2]+'</span></a>';\n"
    "    }else{\n"
    "      html+='<a href=\"javascript:void(0)\" data-anchor=\"'+it[0]+'\"'"
    "+(hasSubs?' data-toggle=\"1\"':'')+'><span class=\"ic\">'+it[1]+'</span>"
    "<span class=\"lbl\">'+it[2]+'</span>'+(hasSubs?'<span class=\"sn-arrow\">▾</span>':'')+'</a>';\n"
    "    }",
    "js-external",
), (
    "      subs.forEach(function(s){html+='<a href=\"javascript:void(0)\" data-anchor=\"'+it[0]"
    "+\" data-sub=\"'+s[0]+'\"><span class=\"dot-sub\"></span><span class=\"lbl\">'+s[1]"
    "+'</span></a>';});",
    "      subs.forEach(function(s){html+='<a href=\"javascript:void(0)\" data-anchor=\"'+it[0]"
    "+\" data-sub=\"'+s[0]+'\" data-view=\"'+(s[2]||it[0])+'\"><span class=\"dot-sub\"></span>"
    "<span class=\"lbl\">'+s[1]+'</span></a>';});",
    "js-subview",
), (
    "      var t=a.getAttribute('data-anchor');\n      var sub=a.getAttribute('data-sub');\n"
    "      // 视图切换模式：交给 switchView；否则滚动定位\n"
    "      if(window.switchView){window.switchView(t);}",
    "      var t=a.getAttribute('data-anchor');\n      var sub=a.getAttribute('data-sub');\n"
    "      var vw=a.getAttribute('data-view')||t;\n"
    "      // 视图切换模式：交给 switchView；否则滚动定位\n"
    "      if(window.switchView){window.switchView(vw);}",
    "js-switchview",
)], "②")

print()
print("=" * 74)
print("③ 徽章 JS：五态（休市/未开盘/开市中/午间休市/已收盘）")
print("=" * 74)
patch(UI, [(
    "function renderSidenav(){var nav=document.getElementById('sidenav');if(!nav)return;",
    "/* 开市/休市五态徽章（用户决策 4）：本地时钟 + 构建期判定的交易日 */\n"
    "function mktBadgeHtml(){\n"
    "  var s=window.MKT_STATUS||{};\n"
    "  var now=new Date();\n"
    "  var p=function(n){return (n<10?'0':'')+n;};\n"
    "  var today=now.getFullYear()+'-'+p(now.getMonth()+1)+'-'+p(now.getDate());\n"
    "  var hm=now.getHours()*100+now.getMinutes();\n"
    "  var cls='mkt-rest',txt='休市';\n"
    "  if(s.isTradingDay&&s.tradeDay===today){\n"
    "    if(hm<930){cls='mkt-pre';txt='未开盘';}\n"
    "    else if(hm<1130){cls='mkt-open';txt='开市中';}\n"
    "    else if(hm<1300){cls='mkt-mid';txt='午间休市';}\n"
    "    else if(hm<1500){cls='mkt-open';txt='开市中';}\n"
    "    else{cls='mkt-rest';txt='已收盘';}\n"
    "  }\n"
    "  return '<span class=\"mkt-badge '+cls+'\" title=\"交易日 '+((s.tradeDay)||'—')"
    "+' · 本地时钟判定\"><span class=\"d\"></span>'+txt+'</span>';\n"
    "}\n"
    "function renderSidenav(){var nav=document.getElementById('sidenav');if(!nav)return;",
    "badge-fn",
), (
    "  nav.innerHTML=html;\n  document.body.classList.add('sidenav-open');",
    "  nav.innerHTML=html;\n"
    "  var _ft=nav.querySelector('.sn-foot');\n"
    "  if(_ft)_ft.insertAdjacentHTML('afterbegin', mktBadgeHtml());\n"
    "  document.body.classList.add('sidenav-open');",
    "badge-mount",
)], "③")

print()
print("=" * 74)
print("④ 导航数据：5 个 4 字 tab（市场晴雨 → 三池 → 社区讨论）")
print("=" * 74)
patch(BD, [
    ('  ["overview","📊","监控总览",[["overview","总览统计"],["mkt-weather","市场晴雨表"],'
     '["bt-all","回测参考·中长线"],["bt-short","短线回测"]]],\n',
     '  ["kxmm","📊","市场晴雨",[["kxmm-fg","恐贪指数"],["kxmm-heat","热力图"],'
     '["mkt-weather","市场晴雨表","overview"],["bt-all","回测参考","overview"],'
     '["bt-short","短线回测","overview"],["overview","总览统计","overview"]]],\n',
     "tab-mkt"),
    ('  ["sys-auto","🛰️","三轨中长线",', '  ["sys-auto","🛰️","中长线池",', "tab-mid"),
    ('  ["short","⚡","全量池短线",', '  ["short","⚡","短线选股",', "tab-short"),
    ('  ["a5","🎯","打板族",', '  ["a5","🎯","打板专区",', "tab-a5"),
    ('  ["kxmm","😨","市场情绪",[["kxmm-fg","恐贪指数"],["kxmm-heat","热力图"]]],\n'
     '  ["comment","💬","评论区",[]]\n',
     '  ["qingju","💬","社区讨论",[],"https://qingju.me/"]\n',
     "tab-community"),
], "④")

print()
print("=" * 74)
print("⑤ 构建期注入 MKT_STATUS")
print("=" * 74)
patch(BD, [(
    "window.ENH.NAV_SWITCH = true;",
    "window.ENH.NAV_SWITCH = true;\n"
    "/* 开市/休市徽章数据（构建期注入）：tradeDay = index_000300 末行；isTradingDay = 末行是否今日 */\n"
    "window.MKT_STATUS = {json.dumps(_MKT_STATUS)};",
    "mkt-status-js",
), (
    "from kxmm_card import KXMM_CSS, KXMM_VIEW_HTML, KXMM_JS",
    "from kxmm_card import KXMM_CSS, KXMM_VIEW_HTML, KXMM_JS\n\n\n"
    "def _mkt_status():\n"
    "    \"\"\"开市/休市徽章（2026-09-18 用户决策 4）：构建期判定今日是否交易日。\n"
    "    tradeDay = index_000300.csv 末行（最近交易日）；isTradingDay = 该末行 == 今日。\n"
    "    盘中/休市时段由前端按本地时钟二次判定，不依赖外部接口。\"\"\"\n"
    "    from datetime import date as _d\n"
    "    _p = Path(__file__).resolve().parent / \"index_000300.csv\"\n"
    "    try:\n"
    "        _last = _p.read_text(encoding=\"utf-8\").strip().splitlines()[-1].split(\",\")[0][:10]\n"
    "    except Exception:\n"
    "        _last = \"\"\n"
    "    _today = _d.today().strftime(\"%Y-%m-%d\")\n"
    "    return {\"tradeDay\": _last, \"today\": _today, \"isTradingDay\": _last == _today}\n\n\n"
    "_MKT_STATUS = _mkt_status()",
    "mkt-status-py",
)], "⑤")

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
print("总结论：" + ("✅ 落地" if OK else "❌ 存在 FAIL（可 git checkout 回退）"))
sys.exit(0 if OK else 1)
