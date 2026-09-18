# -*- coding: utf-8 -*-
"""顶栏空图标占位修复收口：changelog v5.13.9 + 页脚版本 + 记录「饱和度不改」拍板。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
R = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")

ENTRY = """## v5.13.9 - 2026-09-18（顶栏五个标签的空图标占位修复）

**现象**（用户报「顶栏五个标签有 emoji 占位，不协调」）：五 tab 左侧各留着一个 20px 空位，文字偏右、五个标签看着不匀。

**根因**：#10 皮肤层去 emoji 时，我加的隐藏规则写成
`.sidenav a .ic:empty,.sidenav a .ic:blank{display:none}` —— **`:blank` 不是 Chrome 实现的伪类，逗号选择器列表里只要有一个非法项，整条规则会被浏览器丢弃** ⇒ `:empty` 那条从未生效，空图标位一直占位（渲染态实测：`.ic` 计算 display=block、宽 20px，tab 宽 104px）。

**修法（双保险）**
- CSS：删掉 `:blank`，只留 `.sidenav a .ic:empty{display:none}`
- JS：`renderSidenav` 增加 `_ic()` —— 图标为空时**根本不渲染** `<span class="ic">`（治本，不依赖 `:empty` 语义）

**验证（渲染态）**：五个 tab 宽度 **76 / 76 / 76 / 76 / 76px（极差 0）**、导航内 `.ic` 数量 = 0、hover 下拉正常（6 子项）；另做**全站 CSS 选择器合法性扫描**（逐条 `querySelector` 试解析）—— 无其他非法选择器（`:blank` 是唯一一处）。

**同批记录（用户拍板）**：图表语义色（恐贪仪表盘彩虹弧 / 热力图红绿 / ECharts 序列色）**维持现状，不降饱和** —— 该项关闭，不再列入待办。

"""
p = R / "changelog.md"
s = p.read_text(encoding="utf-8")
assert not s.startswith("## v5.13.9"), "已存在同版本"
p.write_text(ENTRY + s, encoding="utf-8")
print("changelog.md: v5.13.9 已置顶")

p2 = R / "build_dual_system.py"
s2 = p2.read_text(encoding="utf-8")
old = "· 版本 v5.13.8（+盘中实时·旧盘中链已退役） · "
new = "· 版本 v5.13.9（+盘中实时·顶栏占位修复） · "
assert s2.count(old) == 1, f"页脚锚点命中 {s2.count(old)}"
p2.write_text(s2.replace(old, new, 1), encoding="utf-8")
print("页脚版本 → v5.13.9")
