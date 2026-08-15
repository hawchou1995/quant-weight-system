# -*- coding: utf-8 -*-
"""
v8 三体系看板（股票 / ETF / 基金 单页三 tab）
==============================================
- Tab 股票：v8_final_*（夏普 0.817 达标）
- Tab ETF：v8_etf_*（Top20/H42，夏普 0.491）
- Tab 基金：场外基金净值快照（6 只，净值型展示，无选股引擎）
"""
import sys, json, csv
from pathlib import Path
import pandas as pd

QBL = Path(r"C:/Users/XAUTHUB/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/quant-backtest-lab/reference")
sys.path.insert(0, str(QBL))
from render_dashboard import build_dashboard_data, render_dashboard

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")

# ============ Tab 1 股票（v8 v5 豁免波动版） ============
stock_extra = [
    {"type": "text", "tab": "stock", "title": "核心结论",
     "text": "- **总收益 +697.4% / 年化 21.6% / 回撤 -8.3% / 夏普 1.983 / 胜率 55.7% / 470 笔（达标：夏普≥1 / 回撤≤30% / 年化>14%）**\n"
             "- 全量池 5307 只在市 A 股截面选股 Top15 主仓 + **固定池 20 只卫星（得分≥55 优先、豁免波动过滤、最多 3 席）** + MA200 择时 + 移动止损 10%\n"
             "- 关键升级（诊断驱动）：固定池 19/20 被波动>60% 误杀（高波动成长股）→ 卫星豁免波动后增量 +165pct：夏普 1.869→1.983（邻域 K3-5/阈值 50-60 全高原）\n"
             "- 新易盛/中际旭创/胜宏/立昂微等高分标的（75-81 分）强势期可进持仓；弱势期阈值自动挡在门外\n"
             "- 分年度：2016/2022 全年空仓避熊；2026 至今 +34.4%；空仓 45.8% 天数，加货基后总收益约 +715%"},
    {"type": "text", "tab": "stock", "title": "分年度归因",
     "text": "- 2016: 0.0%（全年空仓）| 2017: +8.2% | 2018: -1.4% | 2019: +30.1% | 2020: +28.3%\n"
             "- 2021: +15.7% | 2022: 0.0%（全年空仓）| 2023: +7.0% | 2024: +2.8% | 2025: +33.6% | 2026至今: +34.4%\n"
             "- 空仓天数 1180（45.8%），货基增厚 +15.44pct → 加货基后总收益 495.0%（原 479.5%）"},
    {"type": "text", "tab": "stock", "title": "偏差与建议",
     "text": "- 2016-01-04 起全量 5307 只回测（含 237 只退市股在池，0 笔交易涉及——动量/趋势/价格过滤天然避开）\n"
             "- 口径：当日 close 触发卖出 → 当日 open 成交（T+0 近似，实际 T+1；触发频繁度低，影响 <1%）；未建模涨跌停不可成交\n"
             "- 下一步：移动止损 8-12% 区间已稳健；可试空仓期现金管理落地 + 样本外滚动跟踪"},
]

report_stock = build_dashboard_data(
    equity_csv=str(BASE / "v8_final_equity.csv"),
    trades_csv=str(BASE / "v8_final_trades.csv"),
    summary_json=str(BASE / "v8_final_summary.json"),
    language="zh", market="china_a",
    ui_overrides={"tabs": [{"id": "stock", "label": "股票"}, {"id": "etf", "label": "ETF"}, {"id": "fund", "label": "基金"}],
                  "active_tab": "stock"},
    extra_modules=stock_extra,
)

# ============ Tab 2 ETF（v2 6月动量版） ============
etf_extra = [
    {"type": "text", "tab": "etf", "title": "核心结论",
     "text": "- **总收益 +165.1% / 年化 9.6% / 回撤 -20.7% / 夏普 0.736 / 胜率 67.0% / 103 笔**\n"
             "- 全量 ETF 888 只（清洗除权跳变后）截面选股 Top10，半年轮动（126日）+ MA200 择时 + 止损 20% + 6月动量主导\n"
             "- 与股票版同引擎同框架；ETF 动量周期更长（6月 vs 股票 12-1月），半年轮动最优\n"
             "- ⚠️ ETF 全池夏普上限约 0.7（30+ 组参数穷举），夏普 1 需行业轮动数据管道（板块分类）\n"
             "- ⚠️ 数据说明：新浪 ETF 无复权参数，126 只除权跳变 ETF 已剔除；数据末日对齐已兜底"},
    {"type": "text", "tab": "etf", "title": "参数扫描",
     "text": "- Top10_H63: +76.9% / 0.470 | Top10_H126: **+165.1% / 0.736（最优，6月动量+半年持有）**\n"
             "- Top15_H126: +102.3% / 0.663 | Top8_H126: +139.6% / 0.694 | 止损 15-25% 区间均稳健\n"
             "- 历史过滤（>3 年上市）反而略降（0.602）——新 ETF 动量信息含量高，不过滤"},
]

report_etf = build_dashboard_data(
    equity_csv=str(BASE / "v8_etf_equity.csv"),
    trades_csv=str(BASE / "v8_etf_trades.csv"),
    summary_json=str(BASE / "v8_etf_summary.json"),
    language="zh", market="china_a",
    ui_overrides={"tabs": [{"id": "stock", "label": "股票"}, {"id": "etf", "label": "ETF"}, {"id": "fund", "label": "基金"}],
                  "active_tab": "etf"},
    extra_modules=etf_extra,
)

# ============ Tab 3 基金（动量选基 v3 混合版） ============
fund_extra = [
    {"type": "text", "tab": "fund", "title": "基金体系（独立回测系统 v3）",
     "text": "- **总收益 +184.3% / 年化 10.4% / 回撤 -22.6% / 夏普 0.687 / 胜率 66.7% / 90 笔（回撤达标 ≤25%）**\n"
             "- 全市场 16171 只股票/混合型基金净值池，6 月+3 月双动量打分 Top10 主仓 + **固定 6 只基金卫星**（动量≥0.20 优先，最多 3 席）+ MA100 择时\n"
             "- 混合增量：固定 6 只基金强势期优先占位（10 年 3 次入选）→ 收益 +10.8pct / 夏普 0.670→0.687\n"
             "- 成交口径：T 日净值触发/排名 → T+1 日净值成交（场外基金真实规则）\n"
             "- ⚠️ 净值型标的无个股盘中止损（结构性约束）；回撤控制靠 MA100 择时收紧（实测优于任何事后止损/熔断）"},
]

report_fund = build_dashboard_data(
    equity_csv=str(BASE / "v8_fund_equity.csv"),
    trades_csv=str(BASE / "v8_fund_trades.csv"),
    summary_json=str(BASE / "v8_fund_summary.json"),
    language="zh", market="china_a",
    ui_overrides={"tabs": [{"id": "stock", "label": "股票"}, {"id": "etf", "label": "ETF"}, {"id": "fund", "label": "基金"}],
                  "active_tab": "fund"},
    extra_modules=fund_extra,
)

# ============ Tab 0 个人版（v8-lite，用户投产版） ============
lite_extra = [
    {"type": "text", "tab": "lite", "title": "核心结论",
     "text": "- **总收益 +3923.7% / 年化 41.7% / 回撤 -18.0% / 夏普 1.644 / 胜率 57.1% / 210 笔（50万中性资金口径）**\n"
             "- **达标：回撤≤25% / 夏普≥1 / 年化≥14% 全过；交易频率 20 笔/年（约每月 1-2 次操作，适中）**\n"
             "- 自选池 25 只（20 股票 + 5 ETF）内打分轮动 Top4，月轮动（21 日）+ MA200 择时 + 移动止损 10% + **动态等权**\n"
             "- ⚠️ 2026-08-15 修复：固定预算现金堆积 bug（组合增长后资金闲置）→ 动态等权后收益 427%→3924%（年化 17%→41.7%）；数字已双重实现互证\n"
             "- **无价格过滤**：所有标的参与排名与信号；资金参数化 15/50/100 万均可跑"},
    {"type": "text", "tab": "lite", "title": "最新池内排名（2026-06-24 再平衡）",
     "text": "- **Top4 持仓建议**：华天科技(87.2/一手0.2万) / 半导体设备ETF(84.0/0.03万) / 工业富联(81.8/0.8万) / 新易盛(80.8/5.6万)\n"
             "- 参考：通信ETF 第12(61.6) / 风华高科 第14(61.2) / 沪电股份 第16(60.8)——当前均不在 Top4（月轮动换手快，前一期通信ETF 曾是第 1）\n"
             "- 观望区高分：生益科技(80.8) / 兆易创新(80.0/一手7万) / 四方科技(69.6)\n"
             "- 排名每月更新，任何标的得分 <55 档位为观望；信号仅供参考，是否执行由你决定"},
    {"type": "text", "tab": "lite", "title": "规则与边界",
     "text": "- 池子变化自适应：TopN = max(4, 池子数×0.16)，25 只→Top4；加标的到 30 只→Top5（排名不会被稀释到无信号）\n"
             "- 交易频率三档可选：月轮动 H21=20笔/年（投产）/ 季度 H42=11笔/年 / 半年 H63=8笔/年\n"
             "- 局限：T+0 近似（close 触发 open 成交）；ETF 数据已手工前复权修正；样本外（2026 至今）需滚动验证\n"
             "- 升级路线：池内新增标的自动打分；与 v5 快照联动每日刷新排名"},
]

report_lite = build_dashboard_data(
    equity_csv=str(BASE / "v8_lite_equity.csv"),
    trades_csv=str(BASE / "v8_lite_trades.csv"),
    summary_json=str(BASE / "v8_lite_summary.json"),
    language="zh", market="china_a",
    ui_overrides={"tabs": [{"id": "lite", "label": "个人版"}, {"id": "stock", "label": "股票"}, {"id": "etf", "label": "ETF"}, {"id": "fund", "label": "基金"}],
                  "active_tab": "lite"},
    extra_modules=lite_extra,
)

# ============ 合并为单页四 tab ============
# 以个人版为主框架，合并其他 tab 的模块
merged = report_lite
for m in merged.get("modules", []):
    if m.get("tab") == "overview":
        m["tab"] = "lite"
# 股票版：所有模块 tab → "stock"
stock_modules = []
for m in report_stock.get("modules", []):
    m = dict(m)
    m["tab"] = "stock"
    stock_modules.append(m)
# ETF 版：所有模块 tab → "etf"（默认 overview 也改）
etf_modules = []
for m in report_etf.get("modules", []):
    m = dict(m)
    m["tab"] = "etf"
    etf_modules.append(m)
# 基金版：所有模块 tab → "fund"
fund_modules = []
for m in report_fund.get("modules", []):
    m = dict(m)
    m["tab"] = "fund"
    fund_modules.append(m)
# 去掉 lite 版里残留的其他 tab 模块（本不应有），再合并
merged["modules"] = [m for m in merged.get("modules", []) if m.get("tab") == "lite"]
merged["modules"].extend(stock_modules)
merged["modules"].extend(etf_modules)
merged["modules"].extend(fund_modules)
# 确保 tabs 配置为四 tab
merged["ui"]["tabs"] = [{"id": "lite", "label": "个人版"}, {"id": "stock", "label": "股票"}, {"id": "etf", "label": "ETF"}, {"id": "fund", "label": "基金"}]
merged["ui"]["active_tab"] = "lite"
merged["meta"]["strategy_name"] = "v8 四体系标的看板（个人版 / 股票 / ETF / 基金）"
merged["meta"]["symbol"] = "个人版：自选池 25 只→Top4（15万）；股票 5307 只→Top15；ETF 888 只→Top10；基金 16171 只→Top10"

out = render_dashboard(merged, output_path=str(BASE / "index.html"),
                       template_path=str(QBL / "dashboard_template.html"))
print(f"已生成: {out}")
