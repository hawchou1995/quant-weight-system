# -*- coding: utf-8 -*-
"""更新记忆：#10 皮肤层上线 + 两条新陷阱。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
MEM = Path(r"C:/Users/Admin/.zcode/cli/memories/projects/project-9022da3c47c5e5bd/memory")

# ---------- 1) 看板项目记忆：新增 R-dash-0918d 段 + 收敛剩余待做 ----------
p = MEM / "project-kxmm-dashboard.md"
s = p.read_text(encoding="utf-8")

old_tail = "**剩余待做**：**#10 整体 UI 推翻重做**（建议**结构定型后再刷皮肤，返工最少**）；**#4b** 树图盘中实时；**`system_block` 表的五个子项（趋势/动量/量能/超买/风控）仍是「子项评分」单列**——应同样拆列（数据侧 `d[\"comp\"]` 本就是分开的字典，只改渲染）；**子章节下拉仍收起**（`.sn-sub{display:none}`，hover 下拉待补）。"
new_tail = "**剩余待做**：**#4b** 树图盘中实时；图表语义色是否也降饱和（待拍板，见下段「边界」）。~~#10 整体 UI 推翻重做~~ / ~~system_block 五子项拆列~~（`62e5ade` 已拆）/ ~~子章节下拉收起~~（本轮改 hover 下拉）均已闭环。"
assert s.count(old_tail) == 1, "剩余待做段未命中"
s = s.replace(old_tail, new_tail, 1)

SEC = """
## ★★ R-dash-0918d #10 第二步：扁平控制台皮肤（2026-09-18 晚已上线）

**依据**：用户「整体 UI 风格 AI 味太浓」→ 按**已实测**的参考基线（gushi 选股系统：深色单栏 / 细边框白卡 / 小圆角 / 单一强调色 / 纯文字 tab / 无渐变无重阴影）重做皮肤层。**结构先落、皮肤后刷**（上一轮的顺序决策生效，返工最少）。

**已上线**：main `6705f48`（皮肤）+ `10359c6`（JS 验证脚本）；gh-pages `22a4384`；changelog v5.13.6。
- **令牌**：`--r:6px / --r-sm:4px`、**`--warn`**（浅 #b45309 / 深 #fbbf24 —— 琥珀正文对比度 2.2:1 → 5.9:1）、`--mono`；**中性色对齐参考站**（`--text` #111827→#1f2329 等 6 项）
- **密度/层级**：正文 13px、卡片内边距 22→16、卡间距 22→12、顶栏 56→52px；卡标题 18→15px/600、分节 14.5→13.5px、KPI 值 22→20px；表格 12.5px
- **数字**：表格与 KPI 值 `tabular-nums`（数值单元格实测 **100%** 覆盖）+ 数值列右对齐 + `--mono` 栈
- **去渐变**：激活 tab / 社区按钮 / logo 方块 / 雷达条 / 累计总览卡 / 热力树图切换 → 纯色（**CSS 用法计数归零**）
- **配色收敛 32 处内联色**：两红→`--up`、三绿→`--down`、三琥珀→`--warn`；**清紫**（曲线序列色 紫→琥珀/石板）
- **去 emoji = 构建期统一净化**（关键设计，见 [[project-engineering-traps]]）：产物含 **1666** 个 emoji，其中 ~90% 来自**数据层**（pool JSON / 复盘 md / 验证 JSON）→ 逐行改源码不可行，改为 `build_dual_system.py` 落盘前统一净化；判定列 4 处「整格是 emoji」改 ✓/✕
- **导航子章节 hover 下拉**（原 `.sn-sub{display:none}` 收起）：JS 把每个 tab 包进 `.sn-grp` 定位容器 + CSS hover 显形；移除点击折叠旧实现。**实测 156×209 / 6 子项 / 移开自动收起**
- 页脚版本 v5.12.0 → v5.13.6（前三轮 changelog 已到 v5.13.5，页脚漏跟）

**验收证据（一律渲染态，不看纸面）**：静态 9 项 + 渲染态 12 项（真实 Chrome 计算样式：卡圆角 6px / 正文 13px / 表格 tabular-nums / 徽章 4px / 下拉 hover display:flex）+ **JS 异常 0**（39 卡 / 1351 行 / 5 canvas / 5 nav 组）+ 线上 8 项（CDN 刷新后 md5 `d3ac29341efe` 与本地一致）全 PASS；浅/深色双态截图 `D:/Tools/ui10c_auto_light.png`、`ui10c_auto_dark.png`。

**边界（未做，留用户决策）**：**图表语义色不动** —— 恐贪仪表盘彩虹弧 / 热力图红绿 / ECharts 序列色属数据可视化语义色，且恐贪弧为源站（kxmm.online）复刻口径；要一起降饱和须单独一轮并接受「偏离源站复刻」。

**复现**：`$PY _patch_ui10a_0918.py && $PY _patch_ui10b_0918.py && $PY _patch_ui10c_0918.py && $PY build_dual_system.py && $PY _verify_ui10b_0918.py && $PY _verify_ui10_js_0918.py && $PY build_log_pages.py && $PY _deploy_fundline_0911.py`
"""
s = s.replace("\n关联 [[project-quant-system-state]]", SEC + "\n关联 [[project-quant-system-state]]", 1)
assert "R-dash-0918d" in s
p.write_text(s, encoding="utf-8")
print("project-kxmm-dashboard.md 已更新")

# ---------- 2) 陷阱库 ----------
p2 = MEM / "project-engineering-traps.md"
s2 = p2.read_text(encoding="utf-8")
line0 = s2.split("\n", 1)[0]
TRAP = """
> 2026-09-18 晚新增（#10 皮肤层轮 · 两条）：
> - **★★ 展示层的 emoji 有 90% 不在源码里，在数据层 —— 「逐行改源码」是错的解法**（#10 实锤）：用户要「去 AI 味」时我先盘点源码（build_dual_system 203 行含 emoji），但**渲染产物**实测有 **1666** 个（✅458/⚠341/🔴117/🟢107/⚪49…），差额来自 `pool JSON / review md / 验证 JSON` 等**每日链重写的数据文件**。**正解=在最终 HTML 落盘前做一次统一净化**（`build_dual_system.py` 里 `out.write_text` 之前，正则 class 覆盖 1F100-1F1FF / 1F300-1FAFF / 2600-27BF / 2B00-2BFF / 23E9-23FF / FE0F），一次覆盖源码+数据层，且不会被日链刷回。**判据：净化必须用「负向先行断言排除保留符号」**——`(?![✓✔✕✗])[emoji-class]`，否则会把**判定列用的 ✓✕ 一起吃掉**变成空单元格（2600-27BF 区间同时含 ✔✕✗ 与 ✅⚠⛔⚡）。**另：整格内容就是 emoji 的单元格（过闸/复验标记）必须改源码为 ✓/✕**，净化后留空 = 静默丢信息。
> - **★ CDP 抽查页面必须核对页面身份；`page_ws()` 可能取到别的标签页**（#10 实锤，差点误报）：同一次验证里我先 `G.page_ws()` 建连、导航并收集异常，再调一次 `page_ws()` 做功能抽查 —— 第二次拿到的是**另一个 target**，抽查回 `cards:0 / rows:0 / canvas:0`，看起来像"皮肤把页面搞崩了"。真因是连错标签页（Log.enable 还把 `i.gushi.in/api.php 403` 的**历史缓冲**混进来当报错）。**规则：①同一次验证全程复用同一个 ws；②抽查结果里带 `document.title` 自证身份；③`Log.enable` 会回放缓冲日志 → 报错清单要按 URL 过滤，只认本页的。**
"""
s2 = s2.replace(line0, line0 + "\n" + TRAP, 1)
p2.write_text(s2, encoding="utf-8")
print("project-engineering-traps.md 已更新（+2 条）")

# ---------- 3) MEMORY.md 索引行 ----------
p3 = MEM / "MEMORY.md"
s3 = p3.read_text(encoding="utf-8")
old = "剩余=#10 UI 推翻重做 / #4b 树图盘中实时 / system_block 五子项拆列**"
new = "**★★ #10 已闭环（皮肤层，`6705f48`/gh-pages `22a4384`/changelog v5.13.6）：扁平控制台令牌（--r:6px/--warn/--mono、中性色对齐 gushi）+ 密度 13px + tabular-nums 数字等宽 + 去渐变 + 32 处内联色收敛 + 清紫 + **构建期统一净化 1666 个 emoji（90% 来自数据层）** + 导航 hover 下拉 + JS 异常 0 全绿；边界=图表语义色未动**；剩余=#4b 树图盘中实时**"
if s3.count(old) == 1:
    s3 = s3.replace(old, new, 1)
    p3.write_text(s3, encoding="utf-8")
    print("MEMORY.md 索引行已更新")
else:
    print(f"WARN MEMORY.md 锚点命中 {s3.count(old)} 次，未改（原句：{old[:40]}）")
