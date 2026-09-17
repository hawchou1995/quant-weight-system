# -*- coding: utf-8 -*-
"""补丁：build_dual_system.py 接入「市场情绪（kxmm）」视图卡（R-kxmm-0917）
7 处插入，全部带锚点断言（防锚点未命中的静默无效）。
"""
from pathlib import Path

F = Path(__file__).resolve().parent / "build_dual_system.py"
src = F.read_text(encoding="utf-8")
orig = src
hits = []


def sub_once(old, new, tag):
    global src
    n = src.count(old)
    assert n == 1, f"[{tag}] 锚点命中 {n} 次（须为 1）"
    src = src.replace(old, new, 1)
    hits.append(tag)


# ① import
sub_once(
    "from ui_components import THEME_CSS, NAV_HTML, COMMON_JS",
    "from ui_components import THEME_CSS, NAV_HTML, COMMON_JS\nfrom kxmm_card import KXMM_CSS, KXMM_VIEW_HTML, KXMM_JS",
    "import")

# ② CSS 注入（紧随主题 CSS）
sub_once("<style>{THEME_CSS}", "<style>{THEME_CSS}{KXMM_CSS}", "css")

# ③ 数据脚本引入
sub_once('<script src="market_weather.js"></script>',
         '<script src="market_weather.js"></script>\n<script src="echarts.min.js"></script>\n<script src="kxmm_data.js"></script>',
         "scripts")

# ④ 导航组（插在「评论区」之前）
sub_once('  ["comment","💬","评论区",[]]\n];',
         '  ["kxmm","😨","市场情绪",[["kxmm-fg","恐贪指数"],["kxmm-heat","热力图"]]],\n  ["comment","💬","评论区",[]]\n];',
         "nav")

# ⑤ VIEW_MAP
sub_once("'comment':'view-comment'}};", "'comment':'view-comment','kxmm':'view-kxmm'}};", "viewmap")

# ⑥ 视图容器（插在打板族视图之后）
sub_once("{a5_view_html()}", "{a5_view_html()}\n\n{KXMM_VIEW_HTML}", "view")

# ⑦ 渲染 JS（插在 </body></html> 之前）
sub_once('</body></html>"""', '<script>{KXMM_JS}</script>\n</body></html>"""', "js")

F.write_text(src, encoding="utf-8")
assert src != orig
print("✅ 补丁完成：", " | ".join(hits))
for tag in hits:
    pass
print(f"   文件大小 {len(orig)} → {len(src)} 字节（+{len(src)-len(orig)}）")
