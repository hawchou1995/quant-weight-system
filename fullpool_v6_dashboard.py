# -*- coding: utf-8 -*-
"""全量池 v6 基线 → HTML 仪表盘（中文）"""
import json
import sys
from pathlib import Path

QBL = Path(r"C:/Users/XAUTHUB/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/quant-backtest-lab/reference")
sys.path.insert(0, str(QBL))

from render_dashboard import build_dashboard_data, render_dashboard

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")

# 载入对照数据（全仓等权买入持有净值，供 overlay）
import glob
import numpy as np
import pandas as pd

daily = {}
for f in glob.glob(str(BASE / "data_full" / "*.csv")):
    code = Path(f).stem
    try:
        df = pd.read_csv(f, dtype={"date": str})
        df = df[df["date"] >= "2016-01-04"]
        if len(df) < 250:
            continue
        base0 = df["close"].iloc[0]
        if not base0 or base0 <= 0:
            continue
        nav = df["close"] / base0 * 100
        for d, v in zip(df["date"], nav):
            daily.setdefault(d, []).append(v)
    except Exception:
        pass
bh_points = [{"date": d, "value": round(float(np.mean(v)), 4)}
             for d, v in sorted(daily.items())]

extra = [
    {"type": "text", "tab": "overview", "title": "核心结论",
     "text": (
         "- **全量池基线（6870 只等权，2016-01 ~ 2026-08，10.6 年）：总收益 +37.1%，年化 3.1%，最大回撤 40.0%，夏普 0.27，胜率 51.0%，234,170 笔交易**\n"
         "- **跑输全仓等权买入持有**：全市场等权持有同期 +63.6%（年化 4.8%）——权重系统在全量池上无超额收益\n"
         "- **与 100 池基线（+303%）对比**：v6 在精选 100 池上的高收益来自样本池构建（领域精选+强中弱分层），而非信号本身；全量池才是真实水平\n"
         "- **引擎 buyhold 口径缺陷**：target_cap 仓位模型下单次加仓上限 50%，buyhold 分支只触发一次 → 实际为半仓持有（单标的均值 +23.1% 被低估）；对照用全仓等权买入持有 +63.6%"
     )},
    {"type": "text", "tab": "overview", "title": "关键实现细节",
     "text": (
         "- 数据：data_full 全量池 7420 只（沪深 A 股 + 北交所 + ETF + 退市股），2016-01-04 起；不足 1 年数据自动跳过 → 6870 只参与\n"
         "- 信号：收盘后确认 → 次日开盘执行（无未来函数）；A 股 T+1 + 100 股整手\n"
         "- 仓位：target_cap 目标仓位制（≥75 分满仓 / 60-74 半仓 / <30 清仓），单次调整上限 50%\n"
         "- 费率：佣金万 2.5 双边 + 印花税千 0.5（ETF 免印花税）\n"
         "- 退市股 open≤0 行视为停牌（价格保护）；组合为各标的归一化净值等权平均"
     )},
    {"type": "text", "tab": "overview", "title": "已知偏差与限制",
     "text": (
         "- **幸存者偏差已基本消除**：池内包含 250 只退市股（乐视/暴风/康美等），但 2016 年前退市的老股（PT/ST 远古标的）免费源无数据，未纳入\n"
         "- **ETF 与股票同权**：等权组合中 1600+ ETF 与 5000+ 股票权重相同，ETF 收益特征会稀释股票信号\n"
         "- 日线无法还原盘中顺序；未建模冲击成本/涨跌停不可成交\n"
         "- 北交所标的数据起点多为 2021+（挂牌晚），其归一化净值从各自起点开始，等权平均对早期年份有轻微低估\n"
         "- 全量池 234,170 笔交易中大量为低价股/退市股的高频小仓位调仓，换手成本显著"
     )},
    {"type": "text", "tab": "overview", "title": "下一步建议",
     "text": (
         "- 修复引擎 buyhold 为全仓口径后重跑对照，量化超额收益的精确值\n"
         "- 按市值/行业分层回测，定位权重系统在哪些子域仍有效\n"
         "- 加涨跌停不可成交约束（全量池中涨停买入/跌停卖出现象常见）\n"
         "- 考虑 ETF 与股票分池或按权重调整，消除类型稀释"
     )},
]

# ---- 降采样：23.4 万笔交易按日期均匀抽样 ≤ 8000 笔（性能红线）----
import csv

def _load_trades(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for k in ("size", "entry_price", "exit_price", "pnl", "pnl_pct"):
                if row.get(k):
                    try:
                        row[k] = float(row[k])
                    except (TypeError, ValueError):
                        pass
            if row.get("holding_bars"):
                try:
                    row["holding_bars"] = int(float(row["holding_bars"]))
                except (TypeError, ValueError):
                    pass
            rows.append(row)
    return rows

trades = _load_trades(BASE / "fullpool_v6_trades.csv")
print(f"交易总数: {len(trades)}")
if len(trades) > 2000:
    def _sort_key(t):
        return (t.get("exit_date") or t.get("entry_date") or "")
    trades_sorted = sorted(trades, key=_sort_key)
    n = len(trades_sorted)
    step = n / 2000
    sampled = [trades_sorted[int(i * step)] for i in range(2000)]
    by_pnl = sorted(trades, key=lambda t: float(t.get("pnl") or 0))
    sampled.extend(by_pnl[:50])
    sampled.extend(by_pnl[-50:])
    seen = set()
    uniq = []
    for t in sampled:
        key = (t.get("symbol"), t.get("entry_date"), t.get("exit_date"), t.get("pnl"))
        if key not in seen:
            seen.add(key)
            uniq.append(t)
    trades = uniq
    print(f"交易降采样: {n} → {len(trades)} 笔")

report_data = build_dashboard_data(
    equity_csv=str(BASE / "fullpool_v6_equity.csv"),
    trades_csv=None,
    summary_json=str(BASE / "fullpool_v6_summary.json"),
    trade_history=trades,
    language="zh",
    market="china_a",
    extra_modules=extra,
)

# 注入 overlay 对照线（全仓等权买入持有）
for m in report_data["modules"]:
    if m.get("type") == "overview_chart":
        m["overlay_series"] = [
            {"name": "全仓等权买入持有", "stroke": "#9e9e9e", "points": bh_points},
        ]

out = render_dashboard(report_data, output_path=str(BASE / "index.html"),
                       template_path=str(QBL / "dashboard_template.html"))
print(f"已生成: {out}")
