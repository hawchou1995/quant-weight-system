# -*- coding: utf-8 -*-
"""修正 changelog v5.13.6 条目（首版经 bash 双引号，反引号被 shell 吞掉）。"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
p = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system/changelog.md")
s = p.read_text(encoding="utf-8")

ENTRY = """## v5.13.6 - 2026-09-18（#10 整体 UI 推翻重做：扁平控制台皮肤）

**背景**：用户反馈「整体 UI 风格 AI 味太浓」→ 按已实测的参考基线（gushi 选股系统：深色单栏 + 细边框白卡 + 小圆角 + 单一强调色 + 纯文字 tab）重做皮肤层。

**皮肤层改动（渲染态实测值，非纸面参数）**
- 圆角收敛：卡片 16→6px、徽章/药丸 20→4px、弹层 16→8px（令牌化 `--r/--r-sm`，内联 14 处）
- 去渐变：顶栏激活 tab / 社区按钮 / logo 方块 / 雷达条 / 累计总览卡 / 热力树图切换 —— 全站 `linear-gradient` 计数 = 0
- 密度提升：卡片内边距 22→16px、卡间距 22→12px、正文 13px、表格 12.5px、顶栏 56→52px
- 字号层级：卡片标题 18→15px/600、分节标题 14.5→13.5px/600、KPI 值 22→20px
- 数字等宽：全站表格与 KPI 数值启用 `tabular-nums`（实测数值单元格覆盖 100%），数值列右对齐
- 配色收敛：新增 `--warn` 令牌（浅底 #b45309，正文对比度 2.2:1 → 5.9:1）；32 处内联色收敛（两种红→`--up`、三种绿→`--down`、三种琥珀→`--warn`）；清掉紫色；中性色基线对齐参考站 #1F2329
- 去 emoji：**构建期统一净化**（源字符串 + 数据层一起覆盖，实测清除 1666 个）；保留 ✓✕ 判定符号与 ↑↓→ / ①②③ 排版符号；页面可见文字 emoji 实测 = 0
- 导航：子章节由「收起不显示」改为 **hover 下拉**（实测 156×209、6 个子项、移开自动收起），移除点击折叠的旧实现

**验证**：静态 9 项 + 渲染态 12 项全 PASS（真实 Chrome 计算样式：卡片圆角 6px / 正文 13px / 表格 tabular-nums / 徽章 4px / 下拉 hover 显形）；div 平衡终局深度 0；浅色/深色双态截图确认。

"""

m = re.search(r"## v5\.13\.6[\s\S]*?(?=## v5\.13\.)", s)
assert m, "未找到 v5.13.6 段落"
s = s[:m.start()] + ENTRY + s[m.start():][len(m.group(0)):]
# 结构自检
assert s.startswith("## v5.13.6"), "置顶失败"
assert s.count("## v5.13.6") == 1, "版本重复"
assert "\\" not in ENTRY.split("背景")[0], "残留转义"
p.write_text(s, encoding="utf-8")
print("已修正 v5.13.6 条目")
print("\n".join(s.split("\n")[:10]))
