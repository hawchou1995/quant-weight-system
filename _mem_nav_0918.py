# -*- coding: utf-8 -*-
"""记忆：① 饱和度拍板不改（关闭待办）② 新陷阱「非法伪类让整条 CSS 规则失效」。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
MEM = Path(r"C:/Users/Admin/.zcode/cli/memories/projects/project-9022da3c47c5e5bd/memory")

# ① 看板项目记忆：关闭「图表语义色」待办 + 记顶栏修复
p = MEM / "project-kxmm-dashboard.md"
s = p.read_text(encoding="utf-8")
old = "**未做/待拍板**：原服务端盘中脚本 `update_intraday_dashboard.py` 未退役（不冲突，客户端层总以更新值覆盖）；**#4b 完成** → 看板需求清单里只剩「图表语义色是否降饱和」待拍板。"
new = ("**未做/待拍板**：均已于 2026-09-18 深夜收口 —— ① 旧盘中链已退役（R-retire-intraday-0918）"
       "② **图表语义色：用户拍板「饱和度不改」**（恐贪彩虹弧 / 热力图红绿 / ECharts 序列色维持现状，该项关闭）"
       "③ 顶栏空图标占位已修（v5.13.9，见下）。")
assert s.count(old) == 1, f"锚点命中 {s.count(old)}"
s = s.replace(old, new, 1)

SEC = """
### v5.13.9 顶栏空图标占位修复（2026-09-18 深夜）
用户报「顶栏五个标签有 emoji 占位，不协调」。**根因**：#10 去 emoji 时我写的隐藏规则是
`.sidenav a .ic:empty,.sidenav a .ic:blank{display:none}` —— **`:blank` 不是 Chrome 实现的伪类，
逗号选择器列表里有一个非法项 → 整条规则被浏览器丢弃** ⇒ `:empty` 从未生效，空 `<span class="ic">` 一直占 20px（渲染态：display=block / 宽 20px / tab 宽 104px）。
**修法**：CSS 删 `:blank` 只留 `:empty`；JS 加 `_ic()`，图标为空时干脆不渲染 span（治本）。
**验证**：五个 tab 宽度 76/76/76/76/76px（极差 0）、导航内 `.ic`=0、hover 下拉正常、**全站 CSS 选择器扫描无其他非法项**。
"""
s = s.replace("\n关联 [[project-quant-system-state]]", SEC + "\n关联 [[project-quant-system-state]]", 1)
p.write_text(s, encoding="utf-8")
print("project-kxmm-dashboard.md：待办收口 + v5.13.9 段")

# ② 陷阱库
p2 = MEM / "project-engineering-traps.md"
s2 = p2.read_text(encoding="utf-8")
line0 = s2.split("\n", 1)[0]
TRAP = """
> 2026-09-18 深夜新增（v5.13.9 · 一条 CSS 语义坑）：
> - **★★ 逗号选择器列表里有一个"未知伪类"，整条规则会被浏览器丢弃**（实测踩中）：为隐藏去 emoji 后的空图标位写了 `.sidenav a .ic:empty,.sidenav a .ic:blank{display:none}` —— `:blank` 从未被 Chrome 实现（提案级），**CSS 规范要求选择器列表中出现无法解析的选择器时整条规则无效** ⇒ `:empty` 那条也一起失效，页面里空 `.ic` 仍然 `display:block; width:20px`，五个 tab 各留一个 20px 空占位（用户一眼看出"不协调"）。**诊断口径：不要靠"我写了这条规则"判断生效，要读渲染态计算样式**（`getComputedStyle(el).display`）；**通用兜底：给页面加"选择器合法性扫描"**——逐条 `document.querySelector(sel)` 试解析，抛错即非法（本轮扫全站只此一处）。**正解写法：一条规则一个伪类，宁多写几行**。
"""
s2 = s2.replace(line0, line0 + "\n" + TRAP, 1)
p2.write_text(s2, encoding="utf-8")
print("project-engineering-traps.md：+1 条")

# ③ MEMORY.md 索引：去掉"剩余=图表语义色"，写入关闭状态
p3 = MEM / "MEMORY.md"
s3 = p3.read_text(encoding="utf-8")
old3 = "；剩余=图表语义色是否降饱和待拍板**"
new3 = ("；**★ 收口（0918 深夜）：图表语义色「饱和度不改」用户拍板关闭；顶栏空图标占位已修（v5.13.9 根因=`：blank` 非法伪类致整条 CSS 规则被丢弃，5 tab 现 76px 极差 0）**"
        "；看板需求清单全部清零**")
if s3.count(old3) == 1:
    s3 = s3.replace(old3, new3, 1)
    p3.write_text(s3, encoding="utf-8")
    print("MEMORY.md 索引已更新")
else:
    print(f"WARN MEMORY.md 锚点命中 {s3.count(old3)}，未改")
