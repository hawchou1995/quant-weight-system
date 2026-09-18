# -*- coding: utf-8 -*-
"""① 居中修复 ② system_block 子项按指标拆列（用户 2026-09-18）。

① 居中：`.container` **本来就有** `max-width:1560px;margin:0 auto`（ui_components.py:22）。
   是我上一轮加导航横栏时写的 `body.sidenav-open .container{margin-left:0;padding-top:22px}`
   把 `margin-left:auto` 覆盖成 0 → 容器在宽屏上左对齐、看起来没居中。
   顶栏 `position:fixed;left:0;right:0;padding:0 16px` 同理未限宽。

② 拆列：现有「权重总分 + 子项评分（单列斜杠串）」→ 每个子项一列。
   数据侧无需改源头：`comp` 本来就是分开的字典（trend/momentum/volume/osc/risk）。
   注意：单元格那行在 `rows += f'''...'''` 的**字面量**里，只能插入 `{变量}`，
   不能写 `+ "".join(...)`（与卫星表那种 cells 元组不同）。
"""
import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
UI, BD = BASE / "ui_components.py", BASE / "build_dual_system.py"
OK = True


def patch(path, pairs, tag):
    global OK
    t = path.read_text(encoding="utf-8")
    for old, new, name in pairs:
        if new in t and old not in t:
            print(f"  [skip] {tag}/{name}")
            continue
        c = t.count(old)
        if c != 1:
            print(f"  [FAIL] {tag}/{name}: 命中 {c}")
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
    path.write_text(t, encoding="utf-8")


print("=" * 74)
print("① 居中修复")
print("=" * 74)
patch(UI, [
    ("body.sidenav-open .container{margin-left:0;padding-top:22px}",
     "/* 2026-09-18 修：原先 margin-left:0 覆盖掉 .container 自身的 margin:0 auto → 宽屏左对齐 */\n"
     "body.sidenav-open .container{padding-top:22px}",
     "container-center"),
    (".topbar{position:fixed;top:0;left:0;right:0;z-index:900;height:56px;background:#1b2130;\n"
     "  border-bottom:1px solid rgba(255,255,255,.08);display:flex;align-items:center;\n"
     "  gap:10px;padding:0 16px;flex-wrap:nowrap}",
     ".topbar{position:fixed;top:0;left:0;right:0;z-index:900;height:56px;background:#1b2130;\n"
     "  border-bottom:1px solid rgba(255,255,255,.08);display:flex;align-items:center;\n"
     "  gap:10px;flex-wrap:nowrap;\n"
     "  /* 与 .container 同宽居中（1560 + 24 内边距），宽屏下顶栏内容不再贴左 */\n"
     "  padding:0 max(16px,calc((100vw - 1560px)/2))}",
     "topbar-center"),
], "①")

print()
print("=" * 74)
print("② system_block 子项按指标拆列")
print("=" * 74)
patch(BD, [
    ('def rows_html_for(items):\n'
     '    """模板式汇总表行：标的 | 板块 | 行业 | 现价 | 涨跌幅 | 近一年 | 权重分+六类构成 | '
     '超买分解 | 量能分解 | 置信度 | 档位 | 档位变化"""',
     'SCORE_SUB_MAP = {"趋势": "trend", "动量": "momentum", "量能": "volume",\n'
     '                 "超买": "osc", "风控": "risk"}          # 子项标签 → comp 字典键\n\n\n'
     'def rows_html_for(items, score_sub="趋势/动量/量能/超买/风控"):\n'
     '    """模板式汇总表行（2026-09-18：子项由单列斜杠串改为每个指标一列）"""',
     "sig"),
    ('        comp = d.get("comp", {})\n'
     '        comp_txt = f\'{comp.get("trend",0):.0f}/{comp.get("momentum",0):.0f}/'
     '{comp.get("volume",0):.0f}/{comp.get("osc",0):.0f}/{comp.get("risk",0):.0f}\'',
     '        comp = d.get("comp", {})\n'
     '        _labs = [x for x in str(score_sub).split("/") if x]\n'
     '        _sub_cells = "".join(\n'
     '            f\'<td class="num" style="text-align:center;font-size:12px">\'\n'
     '            f\'{comp.get(SCORE_SUB_MAP.get(_lb, _lb), 0):.0f}</td>\' for _lb in _labs)\n'
     '        comp_txt = "/".join(f\'{comp.get(SCORE_SUB_MAP.get(_lb, _lb), 0):.0f}\' for _lb in _labs)',
     "cells-prep"),
    ('<td style="text-align:center"><span style="color:var(--faint);font-size:11px" '
     'title="子项：趋势/动量/量能/超买/风控">{comp_txt}</span></td>',
     '{_sub_cells}',
     "cells-use"),
    ('<th data-key="score" style="text-align:center">权重总分</th>'
     '<th data-key="sub" style="text-align:center">子项评分<div class="th-sub">{score_sub}</div></th>',
     '<th data-key="score" style="text-align:center">权重总分</th>'
     '{_sub_th}',
     "head"),
    ('<tbody>{rows_html_for(items)}</tbody>',
     '<tbody>{rows_html_for(items, score_sub)}</tbody>',
     "call"),
], "②")

# _sub_th 需在 system_block 的 return f-string 之前定义
t = BD.read_text(encoding="utf-8")
anchor = '    tier_opts_html = "".join(f"<option>{t}</option>" for t in tier_opts)'
if "_sub_th = " in t:
    print("  [skip] _sub_th 已定义")
elif t.count(anchor) == 1:
    t = t.replace(anchor, anchor + "\n"
                  '    _sub_th = "".join(\n'
                  '        f\'<th data-key="sub{i}" style="text-align:center">{lb}</th>\'\n'
                  '        for i, lb in enumerate(x for x in str(score_sub).split("/") if x))', 1)
    ast.parse(t); BD.write_text(t, encoding="utf-8")
    print("  [ok]   _sub_th 已定义")
else:
    print(f"  [FAIL] _sub_th 锚点 {t.count(anchor)}")
    OK = False

print()
print("总结论：" + ("✅ 落地" if OK else "❌ FAIL"))
sys.exit(0 if OK else 1)
