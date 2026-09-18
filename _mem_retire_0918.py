# -*- coding: utf-8 -*-
"""记忆更新：旧盘中链退役（R-retire-intraday-0918）。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
MEM = Path(r"C:/Users/Admin/.zcode/cli/memories/projects/project-9022da3c47c5e5bd/memory")

p = MEM / "project-kxmm-dashboard.md"
s = p.read_text(encoding="utf-8")
SEC = """
## ★ R-retire-intraday-0918 旧盘中链退役（2026-09-18 深夜）

用户拍板「退役」。**先摸清引用面再删**（这步最关键，避免删脚本留坏任务）：
- Windows 计划任务无相关项（`Get-ScheduledTask` 全量列表无 quant/intraday 相关）→ 该链是**手动跑**的
- `daily_refresh.py` 无引用；`intraday_quotes_*.json` 仅被该脚本消费；`行情监控/` + `monitor/`（读 `raw_kline`）是**独立子系统**，不动

**删除**：`update_intraday_dashboard.py`（9:30/14:30 patch js → 重建整页 → 部署）、`build_intraday_0821.py`、`_build_intraday_quotes_0819.py`、`intraday_quotes_*.json` ×9（git rm，历史可回溯）；未跟踪的 11 份快照 + `_tmp_0909_quotes.py` 先备份到 `D:/Tools/_retired_intraday_0918/` 再删（可回退）
**替代**：客户端实时层（R-live-0918）；`build_a5_pool.py` 的 `intraday` 字段保留（数据驱动，无人设置恒 False，注释已同步）
**changelog v5.13.8**，页脚同步。

**覆盖率实测结论（用户问「每个标的都会实时更新吗」）**——不全会，实测逐表清单：
| 表 | 可刷行 | 已改写格 | 判定 |
|---|---|---|---|
| 全量池短线跟踪 | 223 | 382 | 实时 |
| 今日涨停全景 | 95 | 95 | 实时 |
| KHunter 命中策略 | 78 | 156 | 实时 |
| 卫星目标持仓（track_b） | 20 | 40 | 实时 |
| 观察清单 / 回避清单 | 3 / 1 | 3 / 1 | 实时 |
| 短线股票池（system_block 18 列） | **今日 0 行** | — | 机制覆盖：合成行注入实测 `1257.12→1111.11`、`-0.78%→+5.55%`、th 打「实时」标签 ✓ |
| 短线基金池 / 基金主仓模拟盘 | 0 | — | 场外基金（净值 T-1，无盘中行情） |
| 各模拟盘持仓表 | 0 | — | 估值表（含浮盈/权重/净值列）整表跳过 |
| KPI/净值卡、RSI/MACD/KDJ/近一年列 | — | — | 日线派生或构建期算好，非价格类 |

合计目标格 **423**、带「实时」徽章卡片 **6** 张。

**退役当轮踩到并修掉的坑（值得隔几天回看）**：
1. **估值表规则误伤短线股票池**：关键词 `权重` 命中了表头「权重**总分**」（评分，不是持仓权重）→ 整表被跳过（正是用户要的那张表）。正解=按语义收紧：含 浮盈/盈亏/市值/净值 一律跳过；含「权重」**且无涨跌幅列**才跳过。**这类"关键词匹配中文业务词"的坑要靠覆盖率实测才暴露**。
2. **诊断脚本第二次复制判据**（同族坑重犯）：覆盖脚本自己写了一遍"估值表"关键词规则 → 改完源码读数不变。已把 `targets()` 收敛成单一出口 `scan()` 并暴露 `INTRADAY.__scan()`，诊断只读它。
3. **验证时序**：首屏实时层在拉 56 个请求时输入事件排队，hover 判定会抖动（1 秒等待不够）→ 验证脚本改为"等 `state.lastTree` 就绪 + 2.5 秒等待"。**这是测试工具的问题，不是产品问题**（判定必须能区分这两者，否则会误修生产代码）。
"""
s = s.replace("\n关联 [[project-quant-system-state]]", SEC + "\n关联 [[project-quant-system-state]]", 1)
assert "R-retire-intraday-0918" in s
p.write_text(s, encoding="utf-8")
print("project-kxmm-dashboard.md 已追加退役段 + 覆盖率结论")

p2 = MEM / "MEMORY.md"
s2 = p2.read_text(encoding="utf-8")
old = "；剩余=图表语义色是否降饱和待拍板**"
new = ("；**★ 旧盘中链已退役（R-retire-intraday-0918，`git rm` 4 脚本 + 20 份快照，gh-pages `294e2b9`）："
       "先摸引用面（无计划任务/日链无引用/monitor 是独立子系统）再删；覆盖率实测=可刷行 423 / 徽章 6 张，"
       "不全覆盖（场外基金·模拟盘估值表·日线派生列不刷）；退役轮修掉「权重总分被当估值列」误伤短线池 + 诊断脚本复制判据**；"
       "剩余=图表语义色是否降饱和待拍板**")
if s2.count(old) == 1:
    s2 = s2.replace(old, new, 1)
    p2.write_text(s2, encoding="utf-8")
    print("MEMORY.md 索引已更新")
else:
    print(f"WARN MEMORY.md 锚点命中 {s2.count(old)}，未改")

p3 = MEM / "project-engineering-traps.md"
s3 = p3.read_text(encoding="utf-8")
line0 = s3.split("\n", 1)[0]
TRAP = """
> 2026-09-18 深夜续（退役轮 · 一条，与上一批同族）：
> - **★「关键词匹配中文业务词」必须做覆盖率实测才算完**（本条差点漏网）：为"组合估值表不补价"写了黑名单 `/浮盈|盈亏|权重|净值|市值/`，结果**命中了短线股票池表头「权重总分」**（评分，不是持仓权重）→ **整表被静默跳过**，而它恰好是用户点名要实时的表。若只看"守卫测试通过/JS 无异常"就交付，这张表会永远不更新且没人知道。**正解=按语义收紧（含浮盈/盈亏/市值/净值 → 跳过；含权重但**无涨跌幅列**才跳过）+ 覆盖率脚本逐表打印"可刷行/已改写格/跳过原因"**。同族：[[#177 阈值处样本塌缩]]（只跑分位口径看不出绝对阈值无样本）——**"没报错"与"覆盖到了"是两件事，必须用覆盖率清单证明**。
"""
s3 = s3.replace(line0, line0 + "\n" + TRAP, 1)
p3.write_text(s3, encoding="utf-8")
print("project-engineering-traps.md 已追加（+1 条）")
