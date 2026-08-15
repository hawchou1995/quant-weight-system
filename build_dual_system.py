# -*- coding: utf-8 -*-
"""标的监控看板（双体系）：今日监控信号优先（档位/变化/建议动作），回测 KPI 作参考。
顶部：标的报告下拉 + 明暗 + qingju.me；左侧：贴边导航；标的表：搜索/筛选/排序/权限切换；行点击监控详情。"""
import json
import math
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import sys
sys.path.insert(0, str(BASE))
from ui_components import THEME_CSS, NAV_HTML, COMMON_JS

js_src = (BASE / "enhanced_data.js").read_text(encoding="utf-8")
DATA = json.loads(js_src[len("window.ENH = "):-1])
details = DATA["details"]

# ---------------- 监控统计（今日信号分布） ----------------
tier_cnt = {"满仓加仓": 0, "轻仓加仓": 0, "观望": 0, "减至半仓": 0, "清仓": 0}
up_cnt = down_cnt = 0
for d in details.values():
    tier_cnt[d["tier"]] = tier_cnt.get(d["tier"], 0) + 1
    if d["tier"] in ("满仓加仓", "轻仓加仓"):
        up_cnt += 1
    elif d["tier"] in ("减至半仓", "清仓"):
        down_cnt += 1
n_total = len(details)

# ---------------- 标的监控表行 ----------------
def tier_pill(t):
    cls = {"满仓加仓": "pill-full", "轻仓加仓": "pill-add", "观望": "pill-watch", "减至半仓": "pill-cut", "清仓": "pill-clear"}.get(t, "pill-watch")
    return f'<span class="pill {cls}">{t}</span>'

def action_for(d):
    """监控建议动作"""
    if d["tier"] in ("满仓加仓",):
        return "持有至目标仓位"
    if d["tier"] == "轻仓加仓":
        return "可加至目标仓位"
    if d["tier"] == "观望":
        return "持有不加 / 观望"
    if d["tier"] == "减至半仓":
        return "减至半仓"
    return "清仓离场"

rows_html = ""
rank = 0
for c, d in sorted(details.items(), key=lambda kv: -kv[1]["score"]):
    rank += 1
    chg_cls = "up" if (d["chg"] or 0) > 0 else "down"
    ret_cls = "up" if (d["ret_1y"] or 0) > 0 else "down"
    chg_txt = f'{d["chg"]:+.2f}%' if d["chg"] is not None else "—"
    ret_txt = f'{d["ret_1y"]:+.0f}%' if d["ret_1y"] is not None else "—"
    chg_tier = ""
    if d["tier_prev"] and d["tier_prev"] != d["tier"]:
        up = d["tier"] in ("满仓加仓", "轻仓加仓")
        chg_tier = f'<span class="{"pill-chg-up" if up else "pill-chg-down"}">{d["tier_prev"]}→{d["tier"]}</span>'
    board_map = {"主板": "main", "创业板": "gem", "科创板": "star", "ETF": "etf"}
    board = d["board"]
    rows_html += f'''<tr data-search="{d["name"]} {d["code"]} {d["industry"]}" data-board="{board_map.get(board, board)}" data-tier="{d["tier"]}" onclick="openDetail('{c}')">
<td style="text-align:center">{rank}</td>
<td><b>{d["name"]}</b><br><span style="color:var(--faint);font-size:11px">{d["code"]} <span class="board-tag">{board}</span> <span class="board-tag">{d["industry"]}</span></span></td>
<td style="text-align:right" data-v="{d["px"]}">{d["px"]:.2f}</td>
<td style="text-align:right" class="{chg_cls}" data-v="{d["chg"] or 0}">{chg_txt}</td>
<td style="text-align:right" class="{ret_cls}" data-v="{d["ret_1y"] or 0}">{ret_txt}</td>
<td style="text-align:center"><b>{d["score"]:.1f}</b></td>
<td style="text-align:center">{tier_pill(d["tier"])}</td>
<td style="text-align:center">{chg_tier or '<span style="color:var(--faint)">—</span>'}</td>
<td style="text-align:center;font-size:12px;color:var(--sub)">{action_for(d)}</td></tr>'''

perm_btns = ''.join(
    f'<button data-perm="{p}" class="{"active" if p == "all" else ""}">{lbl}</button>'
    for p, lbl in [("all", "全部"), ("main", "主板·新开户"), ("gem", "+创业板"), ("star", "+科创板"), ("etf", "ETF")])

# 净值曲线改为 JS 运行时渲染（数据在 enhanced_data.js，容器占位 → HTML 大幅瘦身）
svg_curve = '<div id="curve-chart" style="background:var(--card);border-radius:12px;border:1px solid var(--border);padding:6px"></div>'

html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>标的监控看板（2026-08-14）</title>
<style>{THEME_CSS}</style></head><body>
{NAV_HTML}
<div class="container">

<div class="card" id="overview">
<h2>📊 标的监控总览 <span class="badge badge-auto">数据截至 2026-08-14 收盘</span></h2>
<div class="sub">今日信号：加仓区 {up_cnt} 只 ｜ 观望 {tier_cnt["观望"]} 只 ｜ 减/清仓区 {down_cnt} 只 ｜ 共监控 {n_total} 只 · 点击任意标的查看监控详情 · 信号仅供参考，执行与否由你决定</div>
<div class="kpis">
<div class="kpi"><div class="l">🟢 加仓区</div><div class="v" style="color:#dc2626">{up_cnt} 只</div><div class="s">满仓+轻仓加仓</div></div>
<div class="kpi"><div class="l">🟡 观望区</div><div class="v" style="color:#d97706">{tier_cnt["观望"]} 只</div><div class="s">持有不加</div></div>
<div class="kpi"><div class="l">🔴 减/清仓区</div><div class="v" style="color:#16a34a">{down_cnt} 只</div><div class="s">减半或清仓</div></div>
<div class="kpi"><div class="l">📈 档位升级</div><div class="v">{sum(1 for d in details.values() if d["tier_prev"] and d["tier_prev"] != d["tier"] and d["tier"] in ("满仓加仓", "轻仓加仓"))} 只</div><div class="s">对比上次再平衡</div></div>
<div class="kpi"><div class="l">📉 档位降级</div><div class="v">{sum(1 for d in details.values() if d["tier_prev"] and d["tier_prev"] != d["tier"] and d["tier"] in ("减至半仓", "清仓", "观望") and d["tier_prev"] in ("满仓加仓", "轻仓加仓"))} 只</div><div class="s">对比上次再平衡</div></div>
</div>
<div class="rule-box" style="margin-bottom:0"><b>监控口径</b>：权重分 = 动量35% + 趋势25% + Aroon20% + 量价20% ｜ 档位 = ≥75 满仓加仓 / ≥60 轻仓加仓 / ≥45 观望 / ≥30 减半 / &lt;30 清仓
<br><b>卖出闸门（每日）</b>：v9-auto 移动止损 4.5% + 沪深300破MA150 ｜ v8-lite 移动止损 10% + 破MA200 ｜ 任何闸门先触发先生效</div>
</div>

<div class="card" id="sys-auto">
<h2>🅰️ v9-auto 普适版 <span class="badge badge-auto">全市场自动池 · 无人工选池</span></h2>
<div class="sub">每月全市场绝对规则筛池 → Top3 等权 · 移动止损 4.5% · MA150 择时 · 动态门槛 · RSI&lt;85 · 自动补位</div>
<div class="kpis">
<div class="kpi"><div class="l">回测收益</div><div class="v" style="color:#f59e0b">+{DATA["systems"]["v9_auto"]["summary"]["total_return_pct"]:.1f}%</div><div class="s">参考：2016-01~2026-08</div></div>
<div class="kpi"><div class="l">年化</div><div class="v">{DATA["systems"]["v9_auto"]["summary"]["annual_return_pct"]:.1f}%</div><div class="s">50万中性资金</div></div>
<div class="kpi"><div class="l">最大回撤</div><div class="v" style="color:#ef4444">{DATA["systems"]["v9_auto"]["summary"]["max_drawdown_pct"]:.1f}%</div><div class="s">回测参考</div></div>
<div class="kpi"><div class="l">夏普</div><div class="v" style="color:#22c55e">{DATA["systems"]["v9_auto"]["summary"]["sharpe"]:.3f}</div><div class="s">回测参考</div></div>
</div>
<div class="rule-box" style="margin-bottom:0"><b>自动筛池规则（人人平等）</b>：绝对动量 ≥25% ｜ 四因子分 ≥65 ｜ 站上 MA150 ｜ 价格 ≥2 ｜ 成交额 ≥500万 ｜ RSI &lt;85
<br><b>权限档</b>：main=仅主板(新开户) 夏普2.49 ｜ gem=+创业板 2.44 ｜ star=+科创板 2.34 —— 标的表可切换查看</div>
</div>

<div class="card" id="sys-lite">
<h2>🅱️ v8-lite 个人版 <span class="badge badge-lite">固定自选池 25 只 · Top4 轮动</span></h2>
<div class="sub">自选池内四因子打分轮动 Top4 · 月轮动(21日) · 移动止损 10% · MA200 择时 · 动态等权</div>
<div class="kpis">
<div class="kpi"><div class="l">回测收益</div><div class="v" style="color:#3b82f6">+{DATA["systems"]["v8_lite"]["summary"]["total_return_pct"]:.1f}%</div><div class="s">参考：2016-01~2026-08</div></div>
<div class="kpi"><div class="l">年化</div><div class="v">{DATA["systems"]["v8_lite"]["summary"]["annual_return_pct"]:.1f}%</div><div class="s">50万中性资金</div></div>
<div class="kpi"><div class="l">最大回撤</div><div class="v" style="color:#ef4444">{DATA["systems"]["v8_lite"]["summary"]["max_drawdown_pct"]:.1f}%</div><div class="s">回测参考</div></div>
<div class="kpi"><div class="l">夏普</div><div class="v" style="color:#22c55e">{DATA["systems"]["v8_lite"]["summary"]["sharpe"]:.3f}</div><div class="s">回测参考</div></div>
</div>
<div class="rule-box" style="margin-bottom:0"><b>执行</b>：自选池 25 只打分 → 每期 Top4 等权 ｜ <b>风控</b>：移动止损 10% ｜ 沪深300 破 MA200 全撤</div>
</div>

<div class="card" id="table">
<h2>📋 标的监控表 <span class="badge badge-lite">34 只（自选池 24 + v9 自动池 Top10）</span></h2>
<div class="sub">点击行打开监控详情（K线/因子/交易史/建议）· 表头点击排序 · 权限切换模拟开户状态（信号层始终全量计算，向下兼容）</div>
<div class="toolbar">
<input type="text" id="tbl-q" placeholder="🔍 搜索名称 / 代码 / 行业…">
<div class="perm-group" data-perm-group="tbl">{perm_btns}</div>
<select id="tbl-tier">
<option value="all">全部档位</option><option>满仓加仓</option><option>轻仓加仓</option><option>观望</option><option>减至半仓</option><option>清仓</option>
</select>
<span class="count" id="tbl-count"></span>
</div>
<table class="tbl" id="tbl">
<thead><tr>
<th data-key="rank">排名</th><th data-key="name">标的 / 板块 / 行业</th><th data-key="px">现价</th>
<th data-key="chg">当日</th><th data-key="ret1y">近一年</th><th data-key="score">权重分</th>
<th data-key="tier">档位</th><th data-key="tierchg">档位变化</th><th data-key="action">建议动作</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
<div class="note">档位变化对比上次再平衡（07-23）· 建议动作 = 当前档位下的操作指引 · 回测净值曲线见上方体系卡片（作为历史参考，非实时监控）</div>
</div>

<div class="card" id="curve">
<h2>📈 回测净值参考（2016-2026）</h2>
<div class="sub">两体系 10 年回测曲线（归一化 100 起）——监控依据的历史表现背景</div>
{svg_curve}
</div>

</div>
<script src="enhanced_data.js"></script>
<script>
{COMMON_JS}
document.addEventListener('DOMContentLoaded',function(){{
  initTable('tbl', {{columns: {{rank:0, name:1, px:2, chg:3, ret1y:4, score:5, tier:6, tierchg:7, action:8}}}});
}});
</script>
</body></html>"""

out = BASE / "dual_system.html"
out.write_text(html, encoding="utf-8")
print(f"监控看板已生成: {out} ({out.stat().st_size/1024:.0f} KB)")
