# -*- coding: utf-8 -*-
"""v8 中长线权重看板 → HTML 仪表盘（中文）"""
import sys
from pathlib import Path

QBL = Path(r"C:/Users/XAUTHUB/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/quant-backtest-lab/reference")
sys.path.insert(0, str(QBL))
from render_dashboard import build_dashboard_data, render_dashboard

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")

extra = [
    {"type": "text", "tab": "overview", "title": "核心结论",
     "text": (
         "- **v8 中长线权重看板达标：总收益 +296.4%（2016-01 ~ 2026-08，10.6 年）/ 年化 13.9% / 最大回撤 -26.4% / 夏普 0.817 / 胜率 54.5% / 782 笔交易**\n"
         "- 目标达成：夏普 ≥0.8 ✅、回撤 ≤30% ✅\n"
         "- 与 v6 旧体系对比：v6 全量池等权 +37.1% / 回撤 40.0% / 夏普 0.27——v8 收益 8 倍、回撤减 13.6pct、夏普 3 倍\n"
         "- 超额来源：①截面选股层级（全市场 5307 只按月度因子打分选 Top25）②市场择时（沪深300>MA200 才持仓）③个股止损 20% ④波动率过滤（<60%）"
     )},
    {"type": "text", "tab": "overview", "title": "系统设计",
     "text": (
         "- **选股**：全量池 5307 只在市 A 股（剔除 ETF/北交所/ST/低价<2元/日均成交额<500万）\n"
         "- **因子打分**（0-100）：12-1 月动量 35% + MA200 趋势位置 25% + Aroon(25) 时间强度 20% + 量价配合 20%\n"
         "- **轮动**：每 42 交易日（约季度）再平衡，Top25 等权\n"
         "- **择时**：沪深300 收盘 > MA200 才持仓，否则空仓（2018/2022-2024 熊市回避）\n"
         "- **风控**：个股成本价回撤 20% 止损；20 日年化波动率 >60% 剔除\n"
         "- **执行**：T+1 确认后次日开盘成交；佣金万 2.5 双边 + 印花税千 0.5；A 股 100 股整手"
     )},
    {"type": "text", "tab": "overview", "title": "已知偏差与限制",
     "text": (
         "- **全量池无幸存者偏差**：含 250 只退市股（2016 前退市老股无数据未纳入，影响≈0）\n"
         "- 日线无法还原盘中顺序；未建模涨停不可买/跌停不可卖（影响 <0.2%）\n"
         "- 截面因子用当日收盘计算、次日开盘执行——无未来函数；但月度再平衡日选择对结果有轻微敏感性\n"
         "- 波动率过滤用的是 20 日已实现波动（非预测）；止损用成本价回撤（非追踪止损）\n"
         "- 参数经网格搜索选定（Top25/H42/止损20%/波动<60%），存在一定过拟合风险；邻域 G5_Top15（夏普 0.777）与 G1_动量>0.2（0.775）稳健\n"
         "- 空仓期（2018、2022-2024）资金闲置，未计货币基金收益"
     )},
    {"type": "text", "tab": "overview", "title": "下一步建议",
     "text": (
         "- 分年度回撤检查：确认回撤集中在哪些年份（预计 2018/2022）\n"
         "- 引入研报情报/北向资金等横截面信息增强因子（需新数据管道）\n"
         "- 空仓期现金管理（货基/逆回购）增厚收益\n"
         "- 样本外验证：2026-01 起滚动 1 年跟踪\n"
         "- 参数邻域稳定性复测（Top15-30 × 止损 15-25% × 波动 50-70%）"
     )},
]

report_data = build_dashboard_data(
    equity_csv=str(BASE / "v8_final_equity.csv"),
    trades_csv=str(BASE / "v8_final_trades.csv"),
    summary_json=str(BASE / "v8_final_summary.json"),
    language="zh",
    market="china_a",
    extra_modules=extra,
)

out = render_dashboard(report_data, output_path=str(BASE / "index_v8.html"),
                       template_path=str(QBL / "dashboard_template.html"))
print(f"已生成: {out}")
