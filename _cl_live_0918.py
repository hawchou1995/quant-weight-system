# -*- coding: utf-8 -*-
"""changelog v5.13.7 置顶 + 页脚版本升级。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
R = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")

ENTRY = """## v5.13.7 - 2026-09-18（盘中实时数据层：#4b 热力树图盘中实时 + 选股池涨跌幅盘中更新）

**做法**：纯浏览器端实时层（新模块 `intraday_live.py` → 构建期注入 `{INTRADAY_JS}`）。页面打开后由浏览器直连行情源，**不依赖本机常开、不需要盘中定时重建/部署**（对比原 `update_intraday_dashboard.py` 路线：每次刷新要重建整页 + 一个 gh-pages 提交）。

**通道实测（真实 Chrome，file:// 与线上 https 双 Origin 都过）**
- 东财 `push2delay`：`ulist.np` 返回 `Access-Control-Allow-Origin: *`，800 码单请求 26ms；`clist` 单页硬上限 100 行 → **全市场 5560 只 56 次请求共 1.1 秒**
- 腾讯 `qt.gtimg.cn`：ACAO `*`、对 Referer 无要求；浏览器端 500 码/请求可用（900 码被拒）→ 作兜底通道

**选股池涨跌幅 / 现价盘中更新**
- 覆盖：中长线池卫星表（收盘·涨跌幅）、短线选股股票池、打板专区（观察清单 / 持仓 / 今日涨停全景）、ETF 动量表；实测 **425 个目标格 → 390 格成功改写、35 格正确跳过**
- 口径纪律：**只补价格类字段**（现价/收盘、涨跌幅/当日涨跌/涨幅）。评分、档位、RSI、近一年、MACD、KDJ 是日线派生（上一交易日收盘口径），一律不碰；页面上以**表头「实时」小标签 + 卡片「实时 HH:MM:SS」徽章**区分口径
- **防串码双重校验**：行代码（`data-code` 优先）+ 行情返回名称比对（归一空白/全角空格/XD·XR·DR·N·C·ST 前缀）。实测正确拦下 **7 处「场外基金代码与 A 股同号」冲突**（如 002496 前海开源量化优选C vs 辉丰股份），并修掉 3 处除权前缀误拦（XD新化股 / XD成都银 / 页面名 XD益民集）
- 自动跳过：场外基金 28 格（净值 T-1，无盘中行情）、停牌股（601059 信达证券停牌）

**热力树图盘中实时（#4b）**
- 全市场快照（涨跌幅 / 成交额 / 总市值 / 流通市值）→ `window.HM_APPLY` 就地改值并复用渲染函数重绘，**面积档跟随当前选择**（总市值 / 成交额 / 流通市值）
- 实测：全市场 5560 只 **662ms** 完成刷新；卡片徽章与说明行显示「实时快照 · 更新于 HH:MM:SS（全市场 5560 只）」
- 流量闸门：树图**只在「市场晴雨」视图可见时**刷新（否则省下 56 次请求）；切到该页时自动补刷

**调度与开关**：选股池 60s / 树图 180s / 行情探测 60s；页面隐藏时暂停；非交易时段自动退避 15 分钟；左下角「实时」药丸=总开关（点击开/关，localStorage 记忆），并显示上证涨跌与市况（`盘中 HH:MM:SS` / `非交易时段 · 数据 09-18 16:14`）
**开市徽章联动**：行情源时间戳证明"今天在交易"时，顶栏徽章以实时探测为准 —— 否则上一交易日构建的页面在新交易日会一直显示"休市"

**验证**：合成报价注入（含防串码守卫反向测试：错名 0 改写）+ 真实端到端刷新 + JS 异常捕获 = **0 未捕获异常 / 0 console.error**；截图目视确认（卫星表实时格 / 树图徽章 / 左下药丸）
**并存说明**：原服务端盘中脚本 `update_intraday_dashboard.py`（9:30/14:30 重建+部署）未退役，两者不冲突 —— 客户端层总以更新值覆盖；是否退役待拍板

"""

p = R / "changelog.md"
s = p.read_text(encoding="utf-8")
assert not s.startswith("## v5.13.7"), "已存在同版本"
p.write_text(ENTRY + s, encoding="utf-8")
print("changelog.md: v5.13.7 已置顶")

p2 = R / "build_dual_system.py"
s2 = p2.read_text(encoding="utf-8")
old = "· 版本 v5.13.6（+扁平控制台皮肤） · "
new = "· 版本 v5.13.7（+盘中实时数据层） · "
assert s2.count(old) == 1, f"页脚锚点命中 {s2.count(old)}"
p2.write_text(s2.replace(old, new, 1), encoding="utf-8")
print("build_dual_system.py: 页脚版本 → v5.13.7")
