# 量化权重系统（Quant Weight System）v4

A 股个人研究工具：**六类加权打分 + 回测引擎 + 每日信号快照 + HTML 仪表盘**。个人参考，不构成投资建议。

## 版本历程

| 版本 | 内容 | 组合回测（27 池 × 9 领域，2024-01 起） |
|---|---|---|
| v2 | 六类基础打分 + 市场状态门禁 + A3 量价位置区分 | +130.75% / 回撤 14.64% |
| v3 | **布林带 %B 位置分**（采纳）；均线三线/共振补丁/牛熊系数（回测否决） | +138.63% / 回撤 13.91% / 胜率 89.4% / 换手 0.845% |
| **v4** | **量价三件套补丁式**：地量见底/天量见顶 + 纯量价背离 + RSI背离（量能验证） | **+141.54% / 回撤 13.84% / 胜率 91.6% / 换手 0.787%（四项全优）** |

v4 关键发现：量价背离是 20 日极值低频事件，信号稀疏高价值——换手率不升反降，与 v3 共振补丁（高频抖动、换手翻倍判负）本质不同。

## 目录结构

```
monitor/          生产监控系统（每日信号 + 看板）
  monitor.py         主流程：指标 → 六类打分 → 档位 → 信号变化 → 报告/看板数据
  weight_score.py    v4 权重打分核心（开关可回退）
  render_dashboard.py  看板 HTML（含超买/量能分解列 + 导出 PNG/PDF）
  render_report_html.py 每日报告 HTML
  build_web.py      历史归档 + history.html
  信号规则.md        档位/阈值/市场状态规则
backtest/         回测引擎（v3/v4 候选矩阵）
  weight_system_backtest_v3.py
  weight_system_backtest_v4.py   9 实验矩阵（量价三件套选型）
  update_ref_metrics_v4.py       更新 ref_metrics.json（27 池重跑）
  weight_system_v4_results.json  9 实验明细
  权重系统v4改造报告_20260812.md
docs/             文档
index.html        看板快照（最新构建产物）
legacy/           v2 时代历史代码（可回溯）
watchlist.example.json  标的池模板（脱敏；个人 watchlist.json 不入库）
```

## 快速开始

```bash
# 1. 准备标的池（复制模板并编辑）
cp watchlist.example.json monitor/watchlist.json

# 2. 拉取行情（tdx-connector，每标的日K线 ≥60 根带 h/l）写入 raw_kline/YYYY-MM-DD.json

# 3. 生成信号 + 报告 + 看板
python monitor/monitor.py
python monitor/render_report_html.py
python monitor/render_dashboard.py   # 产出 dist/index.html

# 4. 回测（可选，验证候选）
python backtest/weight_system_backtest_v4.py
python backtest/update_ref_metrics_v4.py
```

数据依赖：通达信 K 线（tdx-connector）拉取、研报情报.json（个人维护，L1-L4 分级，不入库）。

## 六类权重与档位

- 权重：趋势 30% / 动能 25% / 量能 15% / 超买超卖 15% / 风控 10% / 研报 5%
- 档位：满仓加仓 ≥75 / 轻仓加仓 60-74 / 观望 45-59 / 减至半仓 30-44 / 清仓 <30（市场状态三档调节门槛）
- v3 增量：超买超卖类 = RSI(45) + KDJ过滤(30) + 布林位置(25)
- v4 增量：量能类 = 量比 + A3量价配合 + 地量天量(±15) + 纯量价背离(±10)；超买超卖类 += RSI背离(±10，缩量/放量加权)

## 免责声明

本仓库为个人研究工具，基于历史数据回测选型，不代表未来表现。仅供个人参考，不构成任何投资建议；最终投资决策由使用者自行判断并承担全部盈亏责任。
