# -*- coding: utf-8 -*-
"""#11 收尾：把「市场晴雨表」卡物理搬进市场晴雨视图（KXMM_EXTRA 注入点）。

边界（已逐行读准）：
  2085 行  <!-- 🌦 市场晴雨表 ... -->   ← 卡起点（含注释）
  2086 行  <div class="card" id="mkt-weather" ...>
  ...
  2104 行  </div>                        ← 卡终点
  2105 行  </div>                        ← view-overview 闭标签
  2106 行  <!-- 视图 A ... -->            ← 下一个视图

做法：
  ① 把 2085–2104 提取为 `_MKT_WEATHER_CARD = f'''...'''`（保留 {{ }} 转义——它在 page f-string 内
     是转义写法，移入独立 f-string 后运行时会正确还原为 { }）
  ② 删除 视图0 开标签..2105（整块视图移除）
  ③ 注入改为 _MKT_WEATHER_CARD + _CROWD_CARD（走既有 <!--KXMM_EXTRA--> 占位符）
  ④ 默认激活视图从 view-overview 移到 view-kxmm（否则删除后无视图激活 → 白屏）
  ⑤ nav 里指向 overview 的子项清理（回测参考/短线回测已在 #7 移入各池，属悬空项）
  ⑥ logo 点击目标 '#overview' → '#kxmm'
"""
import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
BD = BASE / "build_dual_system.py"
KX = BASE / "kxmm_card.py"
OK = True

t = BD.read_text(encoding="utf-8")
L = t.splitlines(keepends=True)


def fi(pred, start=0):
    for i in range(start, len(L)):
        if pred(L[i]):
            return i
    raise SystemExit("locate fail")


i_cmt = fi(lambda l: "市场晴雨表（niuone" in l)
i_v0 = fi(lambda l: l.lstrip().startswith("<!-- ============ 视图 0"))
i_card_end = fi(lambda l: l.strip() == "</div>" and L[fi(lambda x: 'id="mkt-weather"' in x) - 1].strip().startswith("<!--") - 0, 0)
# 卡终点：从 i_cmt 起找第一个 `</div>` 前面紧跟 `</style>` 的行
i_style = fi(lambda l: l.strip() == "</style>", i_cmt)
i_card_end = i_style + 1
assert L[i_card_end].strip() == "</div>", repr(L[i_card_end])
i_view_close = i_card_end + 1
assert L[i_view_close].strip() == "</div>", repr(L[i_view_close])
print(f"[info] 卡 {i_cmt+1}–{i_card_end+1} ｜ view0 开标签 {i_v0+1} ｜ view0 闭标签 {i_view_close+1}")

card_txt = "".join(L[i_cmt:i_card_end + 1])
assert 'id="mkt-weather"' in card_txt and len(card_txt) > 500
print(f"[info] 提取卡 HTML {len(card_txt)} 字节")

VAR = ("_MKT_WEATHER_CARD = f'''" + card_txt.rstrip("\n") + "\n'''\n\n\n")

# ① 定义变量（放在 def _mkt_status 之前）
anchor = "def _mkt_status():"
if "_MKT_WEATHER_CARD" in t:
    print("  [skip] 变量已定义")
else:
    if t.count(anchor) != 1:
        print(f"  [FAIL] 变量锚点 {t.count(anchor)}")
        OK = False
    else:
        t = t.replace(anchor, VAR + anchor, 1)
        print("  [ok]   _MKT_WEATHER_CARD 已定义")

# ② 删除整块 view-overview
L2 = (t.splitlines(keepends=True))
i_v0b = next(i for i, l in enumerate(L2) if l.lstrip().startswith("<!-- ============ 视图 0"))
i_cb = next(i for i, l in enumerate(L2) if "id=\"mkt-weather\"" in l)
i_se = next(i for i in range(i_cb, len(L2)) if L2[i].strip() == "</style>")
i_ce = i_se + 1
i_vc = i_ce + 1
assert L2[i_ce].strip() == "</div>" and L2[i_vc].strip() == "</div>", "边界核对失败"
t = "".join(L2[:i_v0b] + L2[i_vc + 1:])
print(f"  [ok]   已删除 view-overview 整块（行 {i_v0b+1}–{i_vc+1}）")

# ③ 注入两张卡
old_inj = '{KXMM_VIEW_HTML.replace("<!--KXMM_EXTRA-->", _CROWD_CARD)}'
new_inj = '{KXMM_VIEW_HTML.replace("<!--KXMM_EXTRA-->", _MKT_WEATHER_CARD + _CROWD_CARD)}'
if new_inj in t:
    print("  [skip] 注入（已含晴雨表）")
elif t.count(old_inj) == 1:
    t = t.replace(old_inj, new_inj, 1)
    print("  [ok]   注入 = 晴雨表 + 拥挤度")
else:
    print(f"  [FAIL] 注入锚点 {t.count(old_inj)}")
    OK = False

# ④ nav 子项清理（去掉指向已删视图的悬空项 + 补新增卡）
old_nav = ('["kxmm","📊","市场晴雨",[["kxmm-fg","恐贪指数"],["kxmm-heat","热力图"],'
           '["mkt-weather","市场晴雨表","overview"],["bt-all","回测参考","overview"],'
           '["bt-short","短线回测","overview"],["overview","总览统计","overview"]]]')
new_nav = ('["kxmm","📊","市场晴雨",[["kxmm-fg","恐贪指数"],["kxmm-heat","热力图"],'
           '["hm-card","热力树图"],["crowd-card","大盘拥挤度"],["mkt-weather","市场晴雨表"]]]')
if new_nav in t:
    print("  [skip] nav 子项")
elif t.count(old_nav) == 1:
    t = t.replace(old_nav, new_nav, 1)
    print("  [ok]   nav 子项已更新（5 项，全部指向 kxmm）")
else:
    print(f"  [FAIL] nav 锚点 {t.count(old_nav)}")
    OK = False

# ⑤ logo 点击目标
if "location.hash='#overview'" in t:
    t = t.replace("location.hash='#overview'", "location.hash='#kxmm'", 1)
    print("  [ok]   logo 点击 → #kxmm")
else:
    print("  [skip] logo（已改或无此项）")

# ⑥ VIEW_MAP 去掉 overview
old_map = "'overview':'view-overview',"
if old_map in t:
    t = t.replace(old_map, "", 1)
    print("  [ok]   VIEW_MAP 移除 overview")
else:
    print("  [skip] VIEW_MAP")

try:
    ast.parse(t)
    print("  [ok]   BD AST")
except SyntaxError as e:
    print(f"  [FAIL] BD AST line {e.lineno}: {e.msg}")
    OK = False
    sys.exit(1)
BD.write_text(t, encoding="utf-8")

# ⑦ kxmm 视图默认激活
k = KX.read_text(encoding="utf-8")
if '<div class="view active" id="view-kxmm">' in k:
    print("  [skip] kxmm 默认激活")
else:
    c = k.count('<div class="view" id="view-kxmm">')
    if c == 1:
        k = k.replace('<div class="view" id="view-kxmm">', '<div class="view active" id="view-kxmm">', 1)
        ast.parse(k)
        KX.write_text(k, encoding="utf-8")
        print("  [ok]   view-kxmm 改为默认激活")
    else:
        print(f"  [FAIL] kxmm 视图锚点 {c}")
        OK = False

print()
print("总结论：" + ("✅ 落地" if OK else "❌ FAIL"))
sys.exit(0 if OK else 1)
