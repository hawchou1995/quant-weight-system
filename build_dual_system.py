# -*- coding: utf-8 -*-
"""dual_system.html 全功能版：顶部导航(历史报告/明暗/qingju.me) + 左侧导航 +
双体系 KPI/曲线 + 标的表(搜索/筛选/排序/权限切换) + 逐标的详情弹层"""
import json
import math
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import sys
sys.path.insert(0, str(BASE))
from ui_components import THEME_CSS, NAV_HTML, COMMON_JS

# 数据（从 enhanced_data.js 提取 JSON 部分避免二次解析）
js_src = (BASE / "enhanced_data.js").read_text(encoding="utf-8")
DATA = json.loads(js_src[len("window.ENH = "):-1])

# ---------------- 净值曲线 SVG（归一化对比） ----------------
d_auto = DATA["systems"]["v9_auto"]["equity"]
d_lite = DATA["systems"]["v8_lite"]["equity"]
n = len(d_auto)
W, H = 1400, 360
PAD_L, PAD_R, PAD_T, PAD_B = 70, 20, 30, 40
x = lambda i: PAD_L + (W - PAD_L - PAD_R) * i / max(1, n - 1)
all_v = d_auto + d_lite
vmax = max(200, math.ceil(max(all_v) / 100) * 100)
vmin = 50
y = lambda v: PAD_T + (H - PAD_T - PAD_B) * (1 - (v - vmin) / (vmax - vmin))

grid = ""
for yy in range(vmin, vmax + 1, 50):
    grid += f'<line x1="{PAD_L}" y1="{y(yy):.1f}" x2="{W-PAD_R}" y2="{y(yy):.1f}" stroke="rgba(128,128,128,.15)"/>'
    grid += f'<text x="{PAD_L-8}" y="{y(yy)+4:.1f}" font-size="12" fill="#9ca3af" text-anchor="end">{yy}</text>'
year_labels = {}
prev_yr = None
for i, (va, vl) in enumerate(zip(d_auto, d_lite)):
    yr = 2016 + i // 252
    if yr != prev_yr:
        year_labels[yr] = i
        prev_yr = yr
for yr, i in year_labels.items():
    grid += f'<text x="{x(i):.1f}" y="{H-PAD_B+20}" font-size="13" fill="#9ca3af" text-anchor="middle">{yr}</text>'
    grid += f'<line x1="{x(i):.1f}" y1="{PAD_T}" x2="{x(i):.1f}" y2="{H-PAD_B}" stroke="rgba(128,128,128,.08)"/>'

def poly(vals, color, width):
    pts = " ".join(f"{x(i):.1f},{y(vals[i]):.1f}" for i in range(0, n, 3))
    return f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}"/>'

svg_curve = f'''<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;background:var(--card);border-radius:12px;border:1px solid var(--border)">
{grid}
{poly(d_lite, "#3b82f6", 2)}
{poly(d_auto, "#f59e0b", 2.5)}
<text x="{PAD_L+10}" y="{PAD_T+20}" font-size="13" fill="#3b82f6">v8-lite 个人版（自选池 Top4）→ +3923.7%</text>
<text x="{PAD_L+10}" y="{PAD_T+40}" font-size="13" fill="#f59e0b">v9-auto 普适版（全市场自动池 Top3）→ +839.6%</text>
</svg>'''

# ---------------- 标的表行（34 只） ----------------
def tier_pill(t):
    cls = {"满仓加仓": "pill-full", "轻仓加仓": "pill-add", "观望": "pill-watch", "减至半仓": "pill-cut", "清仓": "pill-clear"}.get(t, "pill-watch")
    return f'<span class="pill {cls}">{t}</span>'

rows_html = ""
rank = 0
for c, d in sorted(DATA["details"].items(), key=lambda kv: -kv[1]["score"]):
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
<td style="text-align:center">{chg_tier or '<span style="color:var(--faint)">—</span>'}</td></tr>'''

# 权限按钮组（表格 id 关联）
perm_btns = ''.join(
    f'<button data-perm="{p}" class="{"active" if p == "all" else ""}">{lbl}</button>'
    for p, lbl in [("all", "全部"), ("main", "主板·新开户"), ("gem", "+创业板"), ("star", "+科创板"), ("etf", "ETF")])

html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>量化权重双体系看板</title>
<style>{THEME_CSS}</style></head><body>
{NAV_HTML}
<div class="container">

<div class="card" id="overview">
<h2>📊 量化权重双体系看板 <span class="badge badge-auto">数据截至 2026-08-14 收盘</span></h2>
<div class="sub">全量池 5307 只 · 2016-01 ~ 2026-08 · 点击任意标的查看详情 · 本页完全离线可用（内联 SVG / 本地数据）</div>
{svg_curve}
</div>

<div class="card" id="sys-auto">
<h2>🅰️ v9-auto 普适版 <span class="badge badge-auto">全市场自动池 · 无人工选池</span></h2>
<div class="sub">每月全市场绝对规则筛池 → Top3 等权 · 移动止损 4.5% · MA150 择时 · 动态门槛 · RSI&lt;85 · 自动补位</div>
<div class="kpis">
<div class="kpi"><div class="l">策略收益</div><div class="v" style="color:#f59e0b">+{DATA["systems"]["v9_auto"]["summary"]["total_return_pct"]:.1f}%</div><div class="s">2016-01~2026-08</div></div>
<div class="kpi"><div class="l">年化收益</div><div class="v">{DATA["systems"]["v9_auto"]["summary"]["annual_return_pct"]:.1f}%</div><div class="s">50万中性资金</div></div>
<div class="kpi"><div class="l">最大回撤</div><div class="v" style="color:#ef4444">{DATA["systems"]["v9_auto"]["summary"]["max_drawdown_pct"]:.1f}%</div><div class="s">达标 ≤30%</div></div>
<div class="kpi"><div class="l">夏普比率</div><div class="v" style="color:#22c55e">{DATA["systems"]["v9_auto"]["summary"]["sharpe"]:.3f}</div><div class="s">达标 ≥1</div></div>
<div class="kpi"><div class="l">胜率</div><div class="v">{DATA["systems"]["v9_auto"]["summary"]["win_rate_pct"]:.1f}%</div><div class="s">{DATA["systems"]["v9_auto"]["summary"]["total_trades"]} 笔</div></div>
</div>
<div class="rule-box"><b>自动筛池规则（人人平等）</b>：绝对动量 ≥25% ｜ 四因子分 ≥65 ｜ 站上 MA150 ｜ 价格 ≥2 ｜ 成交额 ≥500万 ｜ RSI &lt;85
<br><b>风控</b>：移动止损 4.5%（峰值回撤）｜ 沪深300 破 MA150 全撤 ｜ 买不起自动补位
<br><b>权限档</b>：main=仅主板(新开户) 夏普2.49 ｜ gem=+创业板 2.44 ｜ star=+科创板 2.34 —— 下方标的表可切换查看</div>
</div>

<div class="card" id="sys-lite">
<h2>🅱️ v8-lite 个人版 <span class="badge badge-lite">固定自选池 25 只 · Top4 轮动</span></h2>
<div class="sub">自选池内四因子打分轮动 Top4 · 月轮动(21日) · 移动止损 10% · MA200 择时 · 动态等权</div>
<div class="kpis">
<div class="kpi"><div class="l">策略收益</div><div class="v" style="color:#3b82f6">+{DATA["systems"]["v8_lite"]["summary"]["total_return_pct"]:.1f}%</div><div class="s">2016-01~2026-08</div></div>
<div class="kpi"><div class="l">年化收益</div><div class="v">{DATA["systems"]["v8_lite"]["summary"]["annual_return_pct"]:.1f}%</div><div class="s">50万中性资金</div></div>
<div class="kpi"><div class="l">最大回撤</div><div class="v" style="color:#ef4444">{DATA["systems"]["v8_lite"]["summary"]["max_drawdown_pct"]:.1f}%</div><div class="s">达标 ≤25%</div></div>
<div class="kpi"><div class="l">夏普比率</div><div class="v" style="color:#22c55e">{DATA["systems"]["v8_lite"]["summary"]["sharpe"]:.3f}</div><div class="s">达标 ≥1</div></div>
<div class="kpi"><div class="l">胜率</div><div class="v">{DATA["systems"]["v8_lite"]["summary"]["win_rate_pct"]:.1f}%</div><div class="s">{DATA["systems"]["v8_lite"]["summary"]["total_trades"]} 笔</div></div>
</div>
<div class="rule-box"><b>执行</b>：自选池 25 只打分 → 每期 Top4 等权（动态等权）｜ <b>信号档位</b>：满仓加仓≥75 / 轻仓加仓≥60 / 观望≥45 / 减半≥30 / 清仓&lt;30
<br><b>风控</b>：移动止损 10% ｜ 沪深300 破 MA200 全撤 ｜ 整手约束</div>
</div>

<div class="card" id="table">
<h2>📋 标的汇总表 <span class="badge badge-lite">34 只（自选池 24 + v9 自动池 Top10）</span></h2>
<div class="sub">点击行打开逐标的详情 · 表头点击排序 · 权限切换模拟开户状态（向下兼容：所有标的始终参与信号计算）</div>
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
<th data-key="tier">档位</th><th data-key="tierchg">档位变化</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
<div class="note">权重分 = 动量35% + 趋势25% + Aroon20% + 量价20%（08-14 收盘）· 档位变化对比上次再平衡（07-23）· ETF 不参与权限切换（场内可买）</div>
</div>

</div>
<script src="enhanced_data.js"></script>
<script>
{COMMON_JS}
document.addEventListener('DOMContentLoaded',function(){{
  initTable('tbl', {{columns: {{rank:0, name:1, px:2, chg:3, ret1y:4, score:5, tier:6, tierchg:7}}}});
}});
</script>
</body></html>"""

out = BASE / "dual_system.html"
out.write_text(html, encoding="utf-8")
print(f"已生成: {out} ({out.stat().st_size/1024:.0f} KB)")
