# -*- coding: utf-8 -*-
"""v1.1 仪表盘渲染：回测 + 两日快照变动记录 + 临时行业标的参考"""
import json, os, sys, csv

from config import QBL_REF
sys.path.insert(0, QBL_REF)
from render_dashboard import build_dashboard_data, render_dashboard

with open("snapshot_20260810_v2.json", encoding="utf-8") as f:
    snap = json.load(f)
with open("tmp_industry_validation.json", encoding="utf-8") as f:
    tmp_ind = json.load(f)
with open("weight_system_summary.json", encoding="utf-8") as f:
    summary_payload = json.load(f)

ws = summary_payload["summary"]

def share_of(s):
    """从 action_desc 提取建议份额（加多少/减多少），无则返回空"""
    desc = s.get("action_desc", "")
    # 提取括号内份额口径（如「单次最多调整 50% 仓位」）
    import re
    m = re.search(r"（(.+?)）", desc)
    if m:
        return m.group(1)
    return ""

# 今日信号表（含变动记录 + 置信度 + 数据溯源）
sig_rows = []
for s in snap["signals"]:
    comp = s["components"]
    conf = s.get("confidence", {})
    conf_txt = f"{conf.get('level', '-')}（覆盖率{conf.get('coverage', 0)*100:.0f}%）" if conf else "-"
    sig_rows.append({
        "metric": f"{s['name']} ({s['code']})",
        "values": [
            {"main": s["type"]},
            {"main": f"{s['total_score']:.1f}"},
            {"main": f"{s['action']} {share_of(s)}"},
            {"main": conf_txt},
            {"main": s["prev_action"]},
            {"main": s["change"]},
            {"main": str(s["rsi"])},
            {"main": f"{s['k']}/{s['d']}"},
            {"main": str(s["adx"])},
            {"main": f"{s['ma20_dev']:+.2f}" if s["ma20_dev"] is not None else "-"},
            {"main": f"趋势{comp['trend']:.0f} 动能{comp['momentum']:.0f} 量能{comp['volume']:.0f} 超买超卖{comp['osc']:.0f} 风控{comp['risk']:.0f} 研报{comp['news']:.0f}"},
        ],
    })

# 临时行业标的参考表
tmp_rows = []
for t in tmp_ind:
    tmp_rows.append({
        "metric": f"{t['name']} ({t['code']})",
        "values": [
            {"main": t["industry"]},
            {"main": f"{t['weight_ret']:+.1f}%"},
            {"main": f"{t['bh_ret']:+.1f}%"},
            {"main": f"{t['weight_dd']:.1f}%"},
            {"main": f"{t['bh_dd']:.1f}%"},
            {"main": f"{t['today_score']:.1f}"},
            {"main": t["today_action"]},
        ],
    })

extra_modules = [
    {
        "type": "text", "tab": "overview", "title": "v1.1 更新说明",
        "text": (
            "**本轮更新（2026-08-10 晚）**：\n"
            "1. **素材吸收**：新增 vault 素材（大财师兄 6 篇指标搭配文章 / 金智量化筹码指标 / 凡尘逸心 RSI·CCI / 观势起航盘面 / AI光通信概念科普）已完成信源评估与归类提炼（详见 vault [[research-量化权重素材吸收-20260810]]）\n"
            "2. **权重评估结论：维持 v1.0 配置**（趋势30/动能25/量能15/超买超卖15/风控10/研报5）——跨行业验证通过（12 只临时标的 9 只正收益，平均收益 19.1%≈持有 20.2%，回撤 27.3%<31.6%）；唯一补丁：S2 破位阈值加固定下限 -6%（防低波动阴跌股 ATR 自适应失效）\n"
            "3. **快照新增**：操作建议 + 前后变动记录（8-07 ➡️ 8-10）\n"
            "4. **半导设ETF 159516：观望➡️加仓（65.2 分轻仓）**——KDJ 金叉 + RSI 53 健康，验证了朋友方向判断"
        ),
    },
    {
        "type": "metric_table", "tab": "overview",
        "title": "今日信号快照（2026-08-10）· 含变动记录",
        "subtitle": "变动 = 8-07 建议 ➡️ 8-10 建议；≥75 满仓加仓 / 60-74 轻仓加仓 / 45-59 观望 / 40-44 减半仓 / <30 清仓",
        "columns": ["标的", "类型", "总分", "本次建议(份额)", "置信度", "上次建议", "变动", "RSI", "KDJ K/D", "ADX", "MA20偏离%", "打分明细"],
        "rows": sig_rows,
    },
    {
        "type": "metric_table", "tab": "overview",
        "title": "跨行业临时标的权重验证（参考，不纳入监控池）",
        "subtitle": "12 只非 AI 产业链标的验证权重普适性：9/12 正收益，平均收益 19.1% vs 持有 20.2%，回撤 27.3% vs 31.6%（2025-01~2026-08）",
        "columns": ["标的", "行业", "权重收益", "持有收益", "权重回撤", "持有回撤", "今日分", "今日建议"],
        "rows": tmp_rows,
    },
    {
        "type": "text", "tab": "overview", "title": "权重评估结论（维持现状）",
        "text": (
            "**结论：维持 v1.0 权重配置，不做重新分配。**\n\n"
            "评估过程：\n"
            "1. **新增素材信息价值盘点**：大财师兄系列（KDJ/RSI/布林+量能搭配、量价 7 形态、RSI 背离钝化）、金智量化（换手率+筹码密集度箱体突破）、凡尘逸心（RSI/CCI 科普）——核心增量均为**量价/超买超卖细节**，已被现有六类结构覆盖（量能类/超买超卖类）\n"
            "2. **跨行业验证**（12 只临时标的）：权重系统正收益 9/12，平均收益 19.1% ≈ 持有 20.2%，但回撤 27.3% < 31.6%——普适性通过，无行业系统性偏差\n"
            "3. **敏感性扫描**（v1.0 已做）：权重 ±5% 组合收益 208-220%，波动 <12%\n"
            "4. **阴跌补丁实验**：对趋势类加「阴跌惩罚」后，五粮液/茅台改善但比亚迪/隆基恶化（强势回调股误伤）→ 回退，仅保留 S2 固定下限\n\n"
            "**维持理由**：现有权重已反映素材信息价值；调整会牺牲可解释性与 19 标的已验证表现；素材增量信息（RSI 背离、筹码密集度）更适合作为 v2 候选增强而非权重重分配。"
        ),
    },
    {
        "type": "text", "tab": "overview", "title": "数据溯源与置信度（v1.2 方法论吸收）",
        "text": (
            "**来源等级制（A/B/C）**：A=官方一手（交易所/指数编制方/公司披露）；B=机构报告或转述；C=财经媒体/聚合。"
            "本系统数据源：股票/ETF 日线=腾讯自选股接口（A 级，前复权）；基金净值=通达信 setcode=33（A 级，T-1）；"
            "研报情报=vault L1-L3 人工分级（B 级）；技术指标=本地向量化计算（A 级）。"
            "每条信号均带 as-of 日期（见快照 JSON provenance 字段）。\n\n"
            "**置信度机械判定**：覆盖率=方向性有效类别数/6（基金量能、无情报研报不计方向）；"
            "方向一致率=高分（≥60）或低分（≤40）类占比。规则：覆盖率≥80% 且一致率≥75% → 高；覆盖率<60% → 低；其余 → 中。"
            "低置信度时操作建议仅作参考，优先补数据。\n\n"
            "**取数预算**：每个标的/指标最多尝试 2 个来源各 1 次，失败即标「数据不足」，禁止反复重试（配置见 config.py）。"
        ),
    },
    {
        "type": "text", "tab": "overview", "title": "限制与说明",
        "text": (
            "1. 临时行业标的仅作权重参考验证，**不修改关注标的池**；如需纳入正式监控需单独确认\n"
            "2. 五粮液/隆基绿能今日高分（87/78）是技术面修复的真实反映（站上 MA20、mom20 转正），非系统缺陷；但此类标的全年收益为负，说明「技术面修复 ≠ 中期反转」，建议结合基本面\n"
            "3. 变动记录为 8-07 与 8-10 两日对比，非回测历史信号\n"
            "4. 基金净值 T-1 口径导致基金建议天然滞后一日\n"
            "5. 本系统输出为模型结果，不构成投资建议"
        ),
    },
]

report_data = build_dashboard_data(
    equity_csv="weight_system_equity.csv",
    trades_csv="weight_system_trades.csv",
    summary_json="weight_system_summary.json",
    language="zh",
    market="china_a",
    extra_modules=extra_modules,
)

render_dashboard(report_data, output_path="index.html")
print("index.html v1.1 已生成")
