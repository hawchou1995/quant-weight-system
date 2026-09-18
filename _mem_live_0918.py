# -*- coding: utf-8 -*-
"""记忆更新：R-live-0918（盘中实时数据层）+ 三条新陷阱 + 数据源口径。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
MEM = Path(r"C:/Users/Admin/.zcode/cli/memories/projects/project-9022da3c47c5e5bd/memory")

# ---------- 1) 看板项目记忆 ----------
p = MEM / "project-kxmm-dashboard.md"
s = p.read_text(encoding="utf-8")
SEC = """
## ★★ R-live-0918 盘中实时数据层（2026-09-18 晚已上线）

**用户需求**：#4b 树图盘中实时 + 选股池涨跌幅等数据盘中更新（同日第二轮）。

**架构决定：纯浏览器端**（新模块 `intraday_live.py` → 构建期注入 `{INTRADAY_JS}`）。对比原 `update_intraday_dashboard.py`（9:30/14:30 拉快照 → patch js → **重建整页 + 一个 gh-pages 提交**）：浏览器直连零部署、本机关机也生效。**代价**：只有打开页面时才有实时数据（这正是"盘中实时"的语义）。

**通道实测（决定性数字，真实 Chrome 双 Origin：file:// 与线上 https）**
- 东财 `push2delay`：`ulist.np` ACAO `*`、**800 码单请求 26ms**（1000 码 URL 过长失败）；`clist` **单页硬上限 100 行**（pz 传多大都只回 100）→ **全市场 5560 只 = 56 次请求、共 1.1 秒**
- 腾讯 `qt.gtimg.cn`：ACAO `*`、**对 Referer 无要求**（curl 900 码可过、**浏览器 900 码被拒**、500 码可用）→ 兜底通道；字段位置见 [[reference-quant-env-paths]]
- ⚠️ `push2.eastmoney.com` / `82.push2` 本机 curl 全 RemoteDisconnected，**只有 push2delay 稳**；页面里 `INTRADAY.cfg.HOSTS` 留了三主机轮换

**① 选股池涨跌幅/现价 overlay**：425 目标格 → **390 格改写 / 35 格正确跳过**（本机实测）
- 只补**价格类**：现价/收盘、涨跌幅（当日涨跌/涨幅）。评分/档位/RSI/近一年/MACD/KDJ 日线派生 → 一律不碰
- 口径可见化：表头「实时」小标签 + 卡片「实时 HH:MM:SS」徽章 + 单元格琥珀下划线 + `title` 全文
- **防串码双重校验**：行代码（`data-code` 优先）+ 行情返回名称比对（归一空白/全角空格/**XD·XR·DR·N·C·ST 前缀**）→ 实测拦下 **7 处「场外基金代码与 A 股同号」**（002496 前海开源量化优选C vs 辉丰股份 等）、修掉 3 处除权前缀误拦
- **组合估值表整表跳过**（表头含 浮盈/盈亏/权重/净值/市值）：只把价格换实时会让行内自相矛盾
- 自动跳过：场外基金 28 格、停牌股（601059）

**② 树图盘中实时（#4b）**：全市场快照 → `window.HM_APPLY`（`kxmm_card.py` 内新增导出）就地改值 + 复用 `render()` 重绘，**面积档跟随当前选择**；实测 **5560 只 662ms**；**只在「市场晴雨」可见时刷新**（否则省 56 次请求），切到该页自动补刷；徽章/说明行显示「实时快照 · 更新于 HH:MM:SS（全市场 5560 只）」

**③ 调度/开关/联动**：选股池 60s、树图 180s、探测 60s；`visibilityState=hidden` 暂停；非交易时段退避 15 分钟；左下角「实时」药丸=总开关（localStorage `quant_live_v1`）+ 上证涨跌 + 市况文案；**顶栏开市徽章与实时探测联动**（`mktBadgeHtml` 读 `INTRADAY.state.live`）—— 否则上一交易日构建的页面在新交易日一直显示"休市"

**验证**：合成注入（守卫反向测试：错名 0 改写）+ 真实端到端 + **JS 异常 0 / console.error 0**；线上 gh-pages 实测 **695ms 刷新 334 格** + 树图全市场；截图 `D:/Tools/ui10_live_{sat,kxmm,short}.png`

**未做/待拍板**：原服务端盘中脚本 `update_intraday_dashboard.py` 未退役（不冲突，客户端层总以更新值覆盖）；**#4b 完成** → 看板需求清单里只剩「图表语义色是否降饱和」待拍板。

**复现**：`$PY build_dual_system.py && $PY _verify_live_0918.py && $PY _deploy_fundline_0911.py`
"""
s = s.replace("\n关联 [[project-quant-system-state]]", SEC + "\n关联 [[project-quant-system-state]]", 1)
assert "R-live-0918" in s
s = s.replace("**剩余待做**：**#4b** 树图盘中实时；", "**剩余待做**：~~#4b 树图盘中实时~~（R-live-0918 已闭环）；", 1)
p.write_text(s, encoding="utf-8")
print("project-kxmm-dashboard.md 已更新")

# ---------- 2) 陷阱库 ----------
p2 = MEM / "project-engineering-traps.md"
s2 = p2.read_text(encoding="utf-8")
line0 = s2.split("\n", 1)[0]
TRAP = """
> 2026-09-18 深夜新增（R-live-0918 盘中实时层 · 三条）：
> - **★★「诊断脚本自己复制了一份判据」= 改完源码数字不变，看出假象**（本轮差点误判）：修完守卫后发现诊断输出与修改前**逐位一致**（28/1/12/3），一度以为修复无效。真因=**诊断脚本把被测逻辑抄了一份**（自己写 `t.name.slice(0,2)!==d.name.slice(0,2)`），改的是页面源码、量的是脚本副本。**规则：诊断必须走真实路径（调真实函数）并用可观测痕迹判定**——本轮改为「调 `applyQuotes` 后数 DOM 里没有 `.live-cell` 的目标」，立刻暴露出 3 处除权前缀误拦与真冲突混杂。同族：`_verify_*` 里别重写被测逻辑。
> - **★ 浏览器端批量上限 ≠ curl 上限，必须分通道实测**（本轮铁证）：腾讯 `qt.gtimg.cn` **curl 900 码 OK（449KB）**，**同一 URL 在浏览器里 900 码 `TypeError: Failed to fetch`、500 码 OK**；东财 clist **pz 传 1000/500/200 都只回 100 行**（单页硬上限），`push2.eastmoney.com`/`82.push2` 在 curl 层直接 RemoteDisconnected，只有 `push2delay` 稳。**规则：做"页面里直连外部接口"的方案前，先跑"梯度实测"表（n=100/300/500/800/900 × 双 Origin），别用 curl 结论推浏览器。**
> - **★ 名称比对式防串码：名字的取法决定守卫有效性**（本轮两次修正）：① **取错列**（卫星表第 0 列是代码列 → 守卫拿到空名而**静默放行一切**）② **首列是序号**（kh-hits 表 → 名称="6"，与行情名比对必然不符 → **41 个目标被误拦**）③ **除权前缀**（行情名 `XD新化股` vs 页面名 `新化股份`）④ `data-search` 空格分隔（"七 匹 狼 002029 …" → 首词="七"）。**正解：名称候选要求「≥2 个中文/字母」（滤掉纯数字序号）、两侧都归一（去空白/全角空格/XD·XR·DR·N·C·ST 前缀）、data-search 先切掉 6 位代码再取。** 验收要正反两侧都测（错名必须 0 改写 + 正确名必须改写）。
"""
s2 = s2.replace(line0, line0 + "\n" + TRAP, 1)
p2.write_text(s2, encoding="utf-8")
print("project-engineering-traps.md 已更新（+3 条）")

# ---------- 3) 数据源记忆 ----------
p3 = MEM / "reference-quant-env-paths.md"
s3 = p3.read_text(encoding="utf-8")
ADD = """
**★ 行情快照通道实测总表（R-live-0918，2026-09-18，浏览器端 + curl 双口径）**
- **东财 `push2delay.eastmoney.com`**（唯一稳定主机；`push2` / `82.push2` 在 curl 层 RemoteDisconnected）：
  · `api/qt/ulist.np/get?fltt=2&invt=2&fields=f2,f3,f6,f12,f14,f20,f21&secids=1.600519,0.000001…`
    → 返回 `{f2:现价, f3:涨跌幅%, f6:成交额(元), f14:名称, f20:总市值(元), f21:流通市值(元)}`，ACAO `*`
    · **800 码/请求可用（26ms）**，1000 码 URL 过长失败；secid 前缀 6/5/9→`1.`、其余→`0.`
  · `api/qt/clist/get?pn=N&pz=100&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f3,f6,f12,f14,f20,f21`
    · **单页硬上限 100 行**（pz 无效）→ 全市场 5560 只 = 56 页；浏览器里串行 1.1s、并发 5 约 0.7s
- **腾讯 `qt.gtimg.cn/q=sh600519,sz000001,…`**：GBK 文本，ACAO `*`，**对 Referer 无要求**；
  · **curl 900 码 OK / 浏览器 500 码 OK、900 码 Failed to fetch** → 页面里按 400~500 分片
  · 字段位置（`~` 分隔，实测）：`0`=v_sh600519=" `1`=名称 `2`=代码 `3`=现价 `4`=昨收 `5`=今开 `6`=量(手)
    `30`=时间戳 YYYYMMDDHHMMSS `31`=涨跌额 `32`=涨跌幅% `33`=最高 `37`=成交额(万) `38`=换手% `44`=总市值(亿) `45`=流通市值(亿)
  · 用途：**指数+时间戳探测**（sh000001/sh000300 → 判断是否盘中）、东财失败时的兜底
- 页面实现：`intraday_live.py`（`INTRADAY` 全局，cfg.HOSTS 三主机轮换 + EM_CHUNK 800 / TX_CHUNK 400）
"""
s3 = s3.rstrip() + "\n\n" + ADD
p3.write_text(s3, encoding="utf-8")
print("reference-quant-env-paths.md 已追加行情通道总表")

# ---------- 4) MEMORY.md 索引 ----------
p4 = MEM / "MEMORY.md"
s4 = p4.read_text(encoding="utf-8")
old = "；剩余=#4b 树图盘中实时**"
new = ("；**★ R-live-0918 盘中实时数据层已上线（`f2e7fef`/gh-pages `294e2b9`/changelog v5.13.7）：纯浏览器端直连行情源"
       "（东财 push2delay ulist 800 码 26ms / clist 全市场 56 请求 1.1s；腾讯 500 码兜底、双 Origin 实测）→ "
       "选股池涨跌幅·现价 overlay（425 格→390 改写，只补价格类字段；防串码双重校验拦下 7 处基金/A股同号冲突）+ "
       "热力树图盘中实时（#4b 闭环，5560 只 662ms，`window.HM_APPLY`）+ 流量闸门（树图仅晴雨页可见时刷）+ "
       "左下药丸总开关 + 开市徽章与实时探测联动；JS 异常 0**；剩余=图表语义色是否降饱和待拍板**")
if s4.count(old) == 1:
    s4 = s4.replace(old, new, 1)
    p4.write_text(s4, encoding="utf-8")
    print("MEMORY.md 索引行已更新")
else:
    print(f"WARN MEMORY.md 锚点命中 {s4.count(old)}，未改")
