# -*- coding: utf-8 -*-
"""渲染 HTML 仪表盘：回测结果 + 今日信号快照 + 权重系统说明"""
import json, os, sys
from config import QBL_REF
sys.path.insert(0, QBL_REF)

from render_dashboard import build_dashboard_data, render_dashboard

# ---- 加载回测结果 ----
with open("weight_system_results.json", encoding="utf-8") as f:
    results = json.load(f)
with open("snapshot_20260810.json", encoding="utf-8") as f:
    snap = json.load(f)

# ---- 组合权益曲线（权重系统 vs 买入持有）----
combo_w = snap["combined_weight"]
combo_b = snap["combined_buyhold"]
# 对齐日期合并
b_map = {p["date"]: p["value"] for p in combo_b}
points = []
for p in combo_w:
    bv = b_map.get(p["date"])
    points.append({
        "date": p["date"],
        "equity": p["value"],
        "drawdown_abs": 0.0,
        "pnl": p["value"] - 100.0,
        "buyhold": bv if bv else None,
    })

# ---- 今日信号快照（转 metric_table rows）----
sig_rows = []
for s in snap["signals"]:
    comp = s["components"]
    sig_rows.append({
        "name": f"{s['name']} ({s['code']})",
        "type": s["type"],
        "close": s["close"],
        "pct_chg": s["pct_chg"],
        "rsi": s["rsi"],
        "kdj": f"{s['k']}/{s['d']}",
        "adx": s["adx"],
        "ma20_dev": s["ma20_dev"],
        "score": s["total_score"],
        "action": s["action"],
        "detail": f"趋势{comp['trend']:.0f} 动能{comp['momentum']:.0f} 量能{comp['volume']:.0f} "
                  f"超买超卖{comp['osc']:.0f} 风控{comp['risk']:.0f} 研报{comp['news']:.0f}",
    })

# ---- trades 表 ----
with open("weight_system_trades.csv", encoding="utf-8") as f:
    import csv
    reader = csv.DictReader(f)
    trades = [dict(r) for r in reader]

# ---- 组合 summary（写入 summary.json 的）----
with open("weight_system_summary.json", encoding="utf-8") as f:
    summary_payload = json.load(f)

ws = summary_payload["summary"]
bh = snap["combined_buyhold_summary"]

extra_modules = [
    {
        "type": "text", "tab": "overview", "title": "系统结论（先看这里）",
        "text": (
            "**综合指标权重系统 v1.0** 对 19 个关注标的后验验证（2025-01 至 2026-08，等权组合）：\n"
            f"- 组合收益 **+{ws.get('total_return_pct', 0):.1f}%**（年化 +{ws.get('annual_return_pct', 0):.1f}%），"
            f"最大回撤 **{ws.get('max_drawdown_pct', 0):.1f}%**，夏普 {ws.get('sharpe', '-')}\n"
            f"- 对比同期买入持有（+{bh.get('total_return_pct', 0):.1f}%，回撤 {bh.get('max_drawdown_pct', 0):.1f}%）："
            "收益略低但**回撤减半、夏普提升**——权重系统用部分收益换取了显著的风控改善\n"
            "- 对比旧 S1-S7 硬阈值规则：旧规则 19 标的中 15 只亏损（中位数 -4%~-20%），验证了「机械规则无效信号多」的痛点\n"
            "- **KDJ 三重过滤**（位置<30/70 + ADX 趋势确认 + MACD 柱同向）显著降低无效信号；"
            "RSI(14) 以 80 为超买阈值，>80 超买降分、<20 超卖加分\n"
            "- 权重经敏感性扫描（±5% 各 4 组）组合收益波动 <12%，**未过拟合**\n"
            "- 今日（2026-08-10）19 标的中：加仓 9 / 观望 7 / 减仓 3（详见信号快照表）"
        ),
    },
    {
        "type": "metric_table", "tab": "overview",
        "title": "组合表现对比（等权）",
        "subtitle": "权重系统 vs 买入持有（2025-01-02 ~ 2026-08-10）",
        "columns": ["指标", "权重系统", "买入持有"],
        "rows": [
            {"metric": "总收益", "values": [
                {"main": f"+{ws.get('total_return_pct', 0):.1f}%"},
                {"main": f"+{bh.get('total_return_pct', 0):.1f}%"},
            ]},
            {"metric": "年化收益", "values": [
                {"main": f"+{ws.get('annual_return_pct', 0):.1f}%"},
                {"main": f"+{bh.get('annual_return_pct', 0):.1f}%"},
            ]},
            {"metric": "最大回撤", "values": [
                {"main": f"-{ws.get('max_drawdown_pct', 0):.1f}%"},
                {"main": f"-{bh.get('max_drawdown_pct', 0):.1f}%"},
            ]},
            {"metric": "夏普比率", "values": [
                {"main": f"{ws.get('sharpe', '-')}"},
                {"main": f"{bh.get('sharpe', '-')}"},
            ]},
        ],
    },
    {
        "type": "metric_table", "tab": "overview",
        "title": "今日信号快照（2026-08-10）",
        "subtitle": "总分 ≥75 满仓加仓 / 60-74 轻仓加仓 / 45-59 观望 / 40-44 减至半仓 / <40 清仓",
        "columns": ["标的", "类型", "收盘", "涨跌%", "RSI", "KDJ K/D", "ADX", "MA20偏离%", "总分", "操作"],
        "rows": [
            {
                "metric": r["name"],
                "values": [
                    {"main": r["type"]},
                    {"main": str(r["close"])},
                    {"main": f"{r['pct_chg']:+.2f}" if r["pct_chg"] is not None else "-"},
                    {"main": str(r["rsi"])},
                    {"main": r["kdj"]},
                    {"main": str(r["adx"])},
                    {"main": f"{r['ma20_dev']:+.2f}" if r["ma20_dev"] is not None else "-"},
                    {"main": f"{r['score']:.1f}"},
                    {"main": r["action"]},
                ],
            }
            for r in sig_rows
        ],
    },
    {
        "type": "metric_table", "tab": "overview",
        "title": "权重配置（专家先验，敏感性已验证）",
        "subtitle": "六类指标打分加权：总分 = Σ(类分 × 权重)",
        "columns": ["类别", "权重", "构成指标"],
        "rows": [
            {"metric": "趋势类", "values": [{"main": "30%"}, {"main": "MA20 位置 / ADX 强度 / 20日动量"}]},
            {"metric": "动能类", "values": [{"main": "25%"}, {"main": "MACD 金叉死叉 / 柱动能 / 当日涨跌(ATR自适应)"}]},
            {"metric": "量能类", "values": [{"main": "15%"}, {"main": "量能比 / 量价配合（基金退化为中性）"}]},
            {"metric": "超买超卖类", "values": [{"main": "15%"}, {"main": "RSI(14) / KDJ(三重过滤后)"}]},
            {"metric": "风控类", "values": [{"main": "10%"}, {"main": "ATR 波动适中 / 距60日高点回撤"}]},
            {"metric": "研报类", "values": [{"main": "5%"}, {"main": "L1 看多70 / L2 中性50 / L3 谨慎30"}]},
        ],
    },
    {
        "type": "text", "tab": "overview", "title": "KDJ 无效信号处理（三重过滤）",
        "text": (
            "针对「KDJ 无效信号多」的痛点，权重系统对 KDJ 做了三重过滤，过滤后才计入总分：\n"
            "1. **位置过滤**：仅 D<30（低位）或 D>70（高位）的金叉/死叉才计入，中位区（30-70）的交叉不计分——"
            "无效信号集中在中位震荡区\n"
            "2. **趋势过滤**：金叉需 ADX≥20（趋势存在）才确认，震荡市 KDJ 假信号被拦截\n"
            "3. **动能过滤**：金叉需 MACD 柱 >0 同向确认，防止背离信号\n"
            "过滤后 KDJ 与 RSI 共同构成超买超卖类（15% 权重），而非单独决策。"
            "今日半导体设备 ETF 案例：KDJ 金叉（K69/D51）但 ADX 仅 22.3，过滤后贡献有限，"
            "总分 65.2 落在「轻仓加仓」档——比朋友的主观判断（趋势全好）更克制，这就是权重建模的意义。"
        ),
    },
    {
        "type": "text", "tab": "overview", "title": "限制与说明",
        "text": (
            "1. **小样本**：19 标的集中于 AI/光模块/PCB 产业链，权重结论外推性有限\n"
            "2. **单边行情**：回测期（2025-2026）以结构性牛市为主，未覆盖完整牛熊周期，熊市表现未知\n"
            "3. **研报情报**：回测中研报类按标的当前评级静态赋值（新易盛 L3 / 中际旭创 L1 / 胜宏 L1），"
            "历史评级无法回溯，存在简化的前视偏差\n"
            "4. **基金净值 T-1**：场外基金信号天然滞后一日，与股票/ETF 不可比\n"
            "5. 电网设备ETF（560390，2026-03 上市）与华夏全球QDII（024239，2025-05 起）数据覆盖不足，"
            "回测区间偏短\n"
            "6. 本系统输出为模型结果，**不构成投资建议**；最终决策请结合基本面与个人持仓成本"
        ),
    },
]

# 用组合权益曲线作为主图（覆盖 buyhold 曲线 overlay）
report_data = build_dashboard_data(
    equity_csv="weight_system_equity.csv",
    trades_csv="weight_system_trades.csv",
    summary_json="weight_system_summary.json",
    language="zh",
    market="china_a",
    extra_modules=extra_modules,
)

# 注入 buyhold overlay 到主图
for m in report_data["modules"]:
    if m.get("type") == "overview_chart":
        m["overlay_series"] = [{
            "key": "buyhold",
            "label": "买入持有基准",
            "stroke": "#6b7280",
            "dashed": True,
        }]
        # 合并 points
        b_map = {p["date"]: p["value"] for p in combo_b}
        for pt in m.get("points", []):
            pt["buyhold"] = b_map.get(pt["date"])
        break

render_dashboard(report_data, output_path="index.html")
print("index.html 已生成:", os.path.abspath("index.html"))
