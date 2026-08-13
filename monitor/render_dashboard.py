# -*- coding: utf-8 -*-
"""
看板渲染：dashboard_data.json + charts/*.png → dist/index.html（单页自包含）
功能：KPI 卡片（组合胜率/收益/回撤）+ 走势图 + 汇总表（搜索/板块筛选/行业筛选/排序）+ 逐标的卡片
"""
import json, os, base64, math

BASE = os.path.dirname(os.path.abspath(__file__))
DIST = r"D:/Documents/Workbuddy/股票基金/dist"
DASH = os.path.join(BASE, "dashboard_data.json")
CHARTS = os.path.join(BASE, "charts")

d = json.load(open(DASH, encoding="utf-8"))
items = d["items"]
combo = d.get("combined", {})
W = d.get("weights", {})
CW = d.get("combined_window", "2016-01起·100池")

# ---- 收益概述 21 项指标（参考量化看板参数结构）----
METRICS_DEF = [
    ("strategy_return_pct", "策略收益", "pct"),
    ("strategy_annual_pct", "策略年化收益", "pct"),
    ("excess_return_pct", "超额收益", "pct"),
    ("benchmark_return_pct", "基准收益", "pct"),
    ("alpha", "阿尔法 α", "dec3"),
    ("beta", "贝塔 β", "dec3"),
    ("sharpe", "夏普比率", "dec3"),
    ("win_rate", "胜率", "dec3"),
    ("profit_loss_ratio", "盈亏比", "dec3"),
    ("max_drawdown_pct", "最大回撤", "pct_neg"),
    ("sortino", "索提诺比率", "dec3"),
    ("daily_excess_pct", "日均超额收益", "pct4"),
    ("excess_max_drawdown_pct", "超额收益最大回撤", "pct_neg"),
    ("excess_sharpe", "超额收益夏普比率", "dec3"),
    ("daily_win_rate", "日胜率", "dec3"),
    ("win_count", "盈利次数", "int"),
    ("loss_count", "亏损次数", "int"),
    ("information_ratio", "信息比率", "dec3"),
    ("strategy_volatility", "策略波动率", "dec3"),
    ("benchmark_volatility", "基准波动率", "dec3"),
    ("max_drawdown_range", "最大回撤区间", "range"),
]

def _fmt_metric(key, fmt):
    v = combo.get(key)
    if v is None:
        return "—"
    if fmt == "pct":
        return f"{v:+.2f}%"
    if fmt == "pct_neg":
        return f"{v:.2f}%"
    if fmt == "pct4":
        return f"{v:.4f}%"
    if fmt == "dec3":
        return f"{v:.3f}"
    if fmt == "int":
        return f"{int(v)}"
    return str(v)

METRICS_HTML = "\n".join(
    f'<div class="m"><span class="ml">{label}</span><span class="mv">{_fmt_metric(k, fmt)}</span></div>'
    for k, label, fmt in METRICS_DEF
)


# ---- 浅色主题六角雷达图（逐标的卡片内嵌）----
def svg_radar_light(item, size=104):
    cx = cy = size / 2
    R = size * 0.36
    cats = ["trend", "momentum", "volume", "osc", "risk", "news"]
    labels = ["趋势", "动能", "量能", "超买", "风控", "研报"]
    comp = item.get("comp", {})
    score = item.get("score", 50)
    angles = [math.radians(i * 60 - 90) for i in range(6)]  # 顶部起点

    def pt(r, ang):
        return (cx + r * math.cos(ang), cy + r * math.sin(ang))

    parts = []
    for ring in [0.25, 0.5, 0.75, 1.0]:
        pts = " ".join(f"{pt(R*ring, a)[0]:.1f},{pt(R*ring, a)[1]:.1f}" for a in angles)
        stroke = "#e2e8f0" if ring < 1.0 else "#cbd5e0"
        parts.append(f'<polygon points="{pts}" fill="none" stroke="{stroke}" stroke-width="1"/>')
    for a in angles:
        x0, y0 = pt(0, a); x1, y1 = pt(R, a)
        parts.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="#e5e9f0" stroke-width="1"/>')
    vals = [comp.get(c, 50) for c in cats]
    if abs(comp.get("news", 0) or 0) <= 5:
        vals[5] = 50 + comp["news"] * 20
    spts = " ".join(f"{pt(R*max(3,min(100,vals[i]))/100, angles[i])[0]:.1f},{pt(R*max(3,min(100,vals[i]))/100, angles[i])[1]:.1f}" for i in range(6))
    if score >= 75: fill, stroke = "rgba(220,38,38,0.18)", "#dc2626"
    elif score >= 60: fill, stroke = "rgba(234,88,12,0.16)", "#ea580c"
    elif score >= 45: fill, stroke = "rgba(202,138,4,0.16)", "#ca8a04"
    elif score >= 30: fill, stroke = "rgba(22,163,74,0.16)", "#16a34a"
    else: fill, stroke = "rgba(2,132,199,0.16)", "#0284c7"
    parts.append(f'<polygon points="{spts}" fill="{fill}" stroke="{stroke}" stroke-width="2" stroke-linejoin="round"/>')
    for i in range(6):
        xr, yr = pt(R * max(3, min(100, vals[i])) / 100, angles[i])
        parts.append(f'<circle cx="{xr:.1f}" cy="{yr:.1f}" r="2.5" fill="{stroke}"/>')
        lx, ly = pt(R * 1.22, angles[i])
        anchor = "middle"
        if abs(math.cos(angles[i])) > 0.7:
            anchor = "start" if lx > cx else "end"
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" fill="#4a5568" font-size="8" text-anchor="{anchor}" font-weight="600">{labels[i]}</text>')
    parts.append(f'<text x="{cx:.1f}" y="{cy+1:.1f}" fill="#1a202c" font-size="20" font-weight="800" text-anchor="middle">{score:.1f}</text>')
    parts.append(f'<text x="{cx:.1f}" y="{cy+13:.1f}" fill="#9ca3af" font-size="7" text-anchor="middle">总分</text>')
    return f'<svg viewBox="0 0 {size} {size}" style="width:{size}px;height:{size}px;flex:0 0 auto">{chr(10).join(parts)}</svg>'

# 给每个 item 预生成雷达图 SVG
for _it in items:
    _it["radar_svg"] = svg_radar_light(_it)

def b64(p):
    with open(p, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()

img_combo = b64(os.path.join(CHARTS, "chart_combo_equity.png"))
# ECharts 趋势数据（交互式走势图）
trend_path = os.path.join(CHARTS, "trend_data.json")
if os.path.exists(trend_path):
    trend = json.load(open(trend_path, encoding="utf-8"))
    TREND_JSON = json.dumps(trend, ensure_ascii=False).replace("</", "<\\/")
else:
    TREND_JSON = "null"

DATA_JSON = json.dumps(d, ensure_ascii=False).replace("</", "<\\/")

html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>关注标的权重看板 {d['date']}</title>
<style>
body {{ font-family: "Microsoft YaHei", sans-serif; margin: 0; background: #f7f8fa; color: #222; }}
.wrap {{ max-width: 1180px; margin: 0 auto; padding: 20px 16px 40px; }}
h1 {{ font-size: 22px; margin: 4px 0 2px; }}
.note {{ color: #666; font-size: 13px; background: #eef2f7; padding: 8px 12px; border-radius: 6px; margin: 8px 0 16px; }}
.kpis {{ display: grid; grid-template-columns: repeat(11, minmax(0, 1fr)); gap: 6px 18px; margin: 10px 0 14px; padding: 10px 14px; background: #fff; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
@media (max-width: 900px) {{ .kpis {{ grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); }} }}
.m {{ display: flex; flex-direction: column; gap: 1px; padding: 2px 0; }}
.m .ml {{ font-size: 11px; color: #8892a0; white-space: nowrap; }}
.m .mv {{ font-size: 15px; font-weight: 700; color: #1a202c; font-variant-numeric: tabular-nums; }}
.up {{ color: #d92d20; }} .down {{ color: #0f9d58; }} .flat {{ color: #666; }}
.charts img {{ width: 100%; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.08); margin: 8px 0; background:#fff; }}
h2 {{ font-size: 17px; margin: 26px 0 10px; border-left: 4px solid #2b6cb0; padding-left: 8px; }}
.tools {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 10px 0; }}
.tools input, .tools select {{ padding: 7px 10px; border: 1px solid #d5dbe3; border-radius: 6px; font-size: 13px; }}
.tools input {{ flex: 1; min-width: 200px; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.08); font-size: 13px; }}
th, td {{ border: 1px solid #e2e8f0; padding: 7px 8px; text-align: center; }}
th {{ background: #f1f5f9; cursor: pointer; user-select: none; white-space: nowrap; }}
th:hover {{ background: #e2e8f0; }}
.sig {{ display: inline-block; padding: 2px 9px; border-radius: 12px; color: #fff; font-size: 12px; white-space: nowrap; }}
.sig.buy {{ background: #d92d20; }} .sig.sell {{ background: #0f9d58; }} .sig.hold {{ background: #8a94a6; }}
.bdg {{ display: inline-block; padding: 1px 7px; border-radius: 4px; font-size: 11px; margin: 1px; white-space: nowrap; }}
.bdg.res-ok {{ background: #e8f5ec; color: #0f9d58; border: 1px solid #0f9d58; }}
.bdg.flat {{ background: #eef1f4; color: #6b7280; }}
.bdg.res-warn {{ background: #fef6e7; color: #b45309; border: 1px solid #b45309; }}
.bdg.mk {{ background: #edf2fa; color: #2b6cb0; }}
.bdg.ind {{ background: #f3eefb; color: #7c3aed; }}
.bdg.chg {{ background: #fef6e7; color: #b45309; border: 1px solid #b45309; }}
.bdg.boll {{ background: #e6f4ff; color: #0b6bcb; border: 1px solid #0b6bcb; }}
.bdg.evol {{ background: #fff3e0; color: #b45309; border: 1px solid #b45309; }}
.bdg.pdiv {{ background: #fdeaea; color: #c0392b; border: 1px solid #c0392b; }}
.bdg.rdiv {{ background: #f3e8fd; color: #7c3aed; border: 1px solid #7c3aed; }}
.sub {{ color: #8892a0; font-size: 11px; font-weight: normal; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 12px; margin-top: 12px; }}
.card {{ background: #fff; border-radius: 10px; padding: 12px 14px; box-shadow: 0 1px 3px rgba(0,0,0,.08); display: flex; gap: 12px; align-items: flex-start; }}
.card .body {{ flex: 1 1 auto; min-width: 0; }}
.card h3 {{ margin: 0 0 6px; font-size: 15px; }}
.card .meta {{ margin: 3px 0; font-size: 12px; color: #555; }}
.risk {{ background: #fef6e7; border: 1px solid #f0d9a8; border-radius: 8px; padding: 12px 16px; font-size: 13px; color: #6b4f1d; margin-top: 26px; }}
.empty {{ padding: 30px; text-align: center; color: #8892a0; }}
.header-row {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin: 4px 0 2px; }}
.header-row h1 {{ margin: 0; }}
.topbar {{ display: flex; gap: 8px; align-items: center; }}
.topbar a.hist {{ display: inline-block; padding: 6px 12px; border-radius: 20px; background: #fff; color: #4a5568; font-size: 12.5px; text-decoration: none; box-shadow: 0 1px 4px rgba(0,0,0,.10); border: 1px solid #e2e8f0; transition: all .15s; }}
.topbar a.hist:hover {{ background: #fff; color: #2b6cb0; border-color: #2b6cb0; }}
.topbar a.community {{ display: inline-block; padding: 7px 14px; border-radius: 20px; background: linear-gradient(135deg, #FF9A3D 0%, #F2701D 100%); color: #fff; font-size: 13px; font-weight: 600; text-decoration: none; box-shadow: 0 2px 8px rgba(242,112,29,.35); transition: all .15s; }}
.topbar a.community:hover {{ transform: translateY(-1px); box-shadow: 0 4px 14px rgba(242,112,29,.45); }}
@media (max-width: 720px) {{ .topbar a.community {{ font-size: 12px; padding: 6px 10px; }} .topbar a.hist {{ display: none; }} }}
</style></head><body>
<div class="wrap">
<div class="header-row">
<h1>📊 关注标的权重看板（{d['date']}）</h1>
<div class="topbar">
  <a class="hist" href="history.html" title="历史监控报告归档">📚 历史报告</a>
  <a class="community" href="https://qingju.me/" target="_blank" rel="noopener" title="青橘社区 · 西理工人的论坛">💬 青橘社区 · 加标的 / 自由讨论 →</a>
</div>
</div>
<p class="note">{d['note']}｜权重系统 v6（2026-08-13 样本池重建）：六类打分（趋势30/动能25/量能15/超买超卖15/风控10/研报5；超买超卖类含布林带位置分，量能类含量价三件套）→ 满仓加仓≥75（按资产配置加到目标仓位，非全部资金投入）/ 轻仓加仓60-74 / 观望45-59 / 减至半仓30-44 / 清仓&lt;30；稳健加减仓 = 目标制 + 单次上限50%；研报对称打分（无研报0/看多+1/看空-1.5）；<b>恐贪指数 FG（沪深300 5维滚动分位 W=250）：{'🎯 FG ' + ('%.1f' % d.get('fg')) + '（恐惧区·逆向机会，动态门槛 ' + ('%.1f' % (d['items'][0].get('fg_info',{}).get('bw_eff',62))) + '/' + ('%.1f' % (d['items'][0].get('fg_info',{}).get('ss_eff',30))) + '）' if d.get('fg') is not None and d.get('fg') < 45 else ('⚖️ FG ' + ('%.1f' % d.get('fg')) + '（中性）' if d.get('fg') is not None and d.get('fg') <= 55 else ('🚀 FG ' + ('%.1f' % d.get('fg')) + '（贪婪区）' if d.get('fg') is not None else 'FG 不可用'))}</b>；组合回测口径 {CW}（v6 重建：27 池口径已作废，100 池基线 +303.37%/回撤 26.52%/夏普 0.85/年化 14.1%，2016-01 起 10.5 年全窗口，含 10 退市标的）</p>

<h2>收益概述 <span class="sub" style="font-size:12px;font-weight:normal">v6 100 池 · 2016-01 ~ 2026-08 · 含 10 退市</span></h2>
<div class="kpis">
{METRICS_HTML}
</div>

<h2>组合净值走势（拖动下方滑块自由选择时间段）</h2>
<div class="charts">
  <div id="trendChart" style="width:100%;height:360px;background:#fff;border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,.08);margin:8px 0;"></div>
</div>

<h2>权重系统指标公示</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px;margin:10px 0">
  <div class="kpi" style="box-shadow:0 1px 3px rgba(0,0,0,.08)">
    <div class="l" style="font-weight:700;color:#2b6cb0;margin-bottom:6px">六类打分权重</div>
    <div class="l">总分 = 趋势<b>30%</b> + 动能<b>25%</b> + 量能<b>15%</b> + 超买超卖<b>15%</b> + 风控<b>10%</b> + 研报<b>5%</b></div>
    <div class="l" style="margin-top:6px">趋势=MA20位置/ADX(14)/20日动量 ｜ 动能=MACD(12,26,9)/当日涨跌(ATR自适应)/MACD柱<br>量能=量比(5日)/量价配合(A3位置区分)/量价三件套(v4:地量天量+量价背离+RSI背离) ｜ 超买超卖=RSI(14)/KDJ三重过滤/布林带位置分(v3)<br>风控=ATR%适中/60日回撤 ｜ 研报=对称贡献分（看多+1.0/谨慎-1.0/看空-1.5/无0，v6）</div>
  </div>
  <div class="kpi" style="box-shadow:0 1px 3px rgba(0,0,0,.08)">
    <div class="l" style="font-weight:700;color:#2b6cb0;margin-bottom:6px">操作档位与市场门禁</div>
    <div class="l">≥75 满仓加仓 ｜ 60-74 轻仓加仓 ｜ 45-59 观望 ｜ 30-44 减至半仓 ｜ &lt;30 清仓</div>
    <div class="l" style="margin-top:6px;color:#b45309"><b>仓位说明</b>：满仓/半仓 = <b>该标的的目标仓位占比</b>（初始资金按你分配给该策略的资产池计），<b>不是把全部可投资金投入</b>——实际投入请按自身资产配置换算。</div>
    <div class="l" style="margin-top:6px">市场门禁（沪深300 vs MA20）：<b>强势</b> 58/28 ｜ <b>正常</b> 62/30 ｜ <b>防御</b> 65/35<br>仓位模型：target_cap（目标制+单次上限50%）；T日收盘信号→T+1开盘执行；A股T+1、100股整手</div>
  </div>
  <div class="kpi" style="box-shadow:0 1px 3px rgba(0,0,0,.08)">
    <div class="l" style="font-weight:700;color:#2b6cb0;margin-bottom:6px">置信度机械判定</div>
    <div class="l">高 = 覆盖率≥80% 且方向一致率≥75% ｜ 低 = 覆盖率&lt;60% ｜ 其余为中</div>
    <div class="l" style="margin-top:6px">方向性类别 = 剔除退化项（基金无量能/无研报）后的六类；方向一致 = 该类别≥60 或 ≤40 分</div>
  </div>
</div>
<p style="font-size:12px;color:#8892a0;margin:0 0 8px">指标全解（每个档位可手算复核）见知识库《权重系统指标全解_20260811》｜ 素材纪律：权重经 ±5% 敏感性扫描 + 37 只验证池维持 v1.0；v3（2026-08-12）布林带位置分；v4（2026-08-12）量价三件套补丁式；v5（2026-08-12）恐贪指数 FG 动态门槛（恐惧机会）；<b style="color:#c53030">v6（2026-08-13）样本池重建为 100 池（9 领域 × 10 + 10 退市）消除幸存者偏差——27 池口径（+141.54%）已作废；2016-01 起全量回测：100 池基线 +303.37%/回撤 26.52%/夏普 0.85/胜率 82.0%/年化 14.1%（退市 10 只均值 -88.4% 已计入）；FG 恐惧机会 +304.92% 微优（胜率 84.2%/换手 0.489% 占优）；FG 第7维收益最高但回撤恶化 6.1pct 否决</b></p>

<h2>标的汇总（{len(items)} 只）</h2>
<div class="tools">
  <input id="q" placeholder="🔍 搜索名称 / 代码…" oninput="render()">
  <select id="fMk" onchange="render()"><option value="">全部板块</option></select>
  <select id="fInd" onchange="render()"><option value="">全部行业</option></select>
  <select id="fAct" onchange="render()"><option value="">全部档位</option></select>
  <button onclick="exportPNG()" style="margin-left:8px;padding:4px 12px;border:1px solid #2b6cb0;background:#fff;color:#2b6cb0;border-radius:4px;cursor:pointer;font-size:12px">📷 导出PNG</button>
  <button onclick="exportXLSX()" style="margin-left:6px;padding:4px 12px;border:1px solid #2b6cb0;background:#2b6cb0;color:#fff;border-radius:4px;cursor:pointer;font-size:12px">📊 导出XLSX</button>
</div>
<table id="tbl"><thead><tr>
<th data-k="name">标的</th><th data-k="market">板块</th><th data-k="industry">行业</th>
<th data-k="close">现价</th><th data-k="pct_chg">涨跌幅</th><th data-k="year_return">近一年</th>
<th data-k="score">权重分</th><th>分数构成<br><span class="sub">趋/动/量/超/风/研</span></th><th>超买分解<br><span class="sub">RSI/KDJ/布林</span></th><th>量能分解<br><span class="sub">量比/地量天量/背离</span></th><th data-k="conf">置信度</th><th data-k="action">操作档位</th><th data-k="changed">档位变化</th>
</tr></thead><tbody id="tb"></tbody></table>
<p id="cnt" style="font-size:12px;color:#8892a0;margin:6px 0 0"></p>

<h2>逐标的详情</h2>
<div class="cards" id="cards"></div>

<div class="risk">⚠️ 本看板由自动化规则生成，仅供个人参考，<b>不构成任何投资建议</b>。组合回测指标基于 2024-01~2026-08 历史数据（27 标的 × 9 领域等权，target_cap 单次上限50%，市场门禁启用），不代表未来表现。最终投资决策由您自行判断，并承担全部盈亏责任。投资有风险，决策需谨慎。</div>
</div>

<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"></script>
<script>
const D = {DATA_JSON};
const TREND = {TREND_JSON};
const ITEMS = D.items;
const fmt = (v, d=2, sign=true) => v === null || v === undefined ? "—" : (sign && v > 0 ? "+" : "") + v.toFixed(d) + "%";
const actCls = {{"满仓加仓":"buy","轻仓加仓":"buy","观望":"hold","减至半仓":"sell","清仓":"sell"}};
const confCls = {{"高":"res-ok","中":"flat","低":"res-warn"}};
const mkOpt = (sel, key, label) => {{
  const set = new Set(ITEMS.map(i => i[key]).filter(Boolean));
  [...set].sort().forEach(v => {{ const o = document.createElement("option"); o.value = v; o.textContent = v; sel.appendChild(o); }});
}};
mkOpt(document.getElementById("fMk"), "market", "板块");
mkOpt(document.getElementById("fInd"), "industry", "行业");
mkOpt(document.getElementById("fAct"), "action", "档位");
let sortK = "score", sortAsc = false;
document.querySelectorAll("th[data-k]").forEach(th => th.onclick = () => {{
  const k = th.dataset.k; if (sortK === k) sortAsc = !sortAsc; else {{ sortK = k; sortAsc = k !== "name"; }}
  document.querySelectorAll("th[data-k]").forEach(h => h.textContent = h.textContent.replace(/[▲▼]$/, ""));
  th.textContent += sortAsc ? " ▲" : " ▼";
  render();
}});
function filtered() {{
  const q = document.getElementById("q").value.trim().toLowerCase();
  const mk = document.getElementById("fMk").value, ind = document.getElementById("fInd").value, act = document.getElementById("fAct").value;
  return ITEMS.filter(i =>
    (!q || i.name.toLowerCase().includes(q) || i.code.includes(q)) &&
    (!mk || i.market === mk) && (!ind || i.industry === ind) && (!act || i.action === act));
}}
function render() {{
  let rows = filtered();
  rows.sort((a, b) => {{
    const va = a[sortK], vb = b[sortK];
    if (typeof va === "number" && typeof vb === "number") return sortAsc ? va - vb : vb - va;
    return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
  }});
  document.getElementById("tb").innerHTML = rows.map(i => {{
    const pc = i.pct_chg, pcCls = pc > 0 ? "up" : pc < 0 ? "down" : "flat";
    const chg = i.changed ? `<span class="bdg chg">${{i.prev_action||"—"}}→${{i.action}}</span>` : (i.prev_action ? i.action : "—");
    return `<tr>
      <td><b>${{i.name}}${{i.risk_note ? " ⚠" : ""}}</b><br><span class="sub">${{i.code}}</span></td>
      <td><span class="bdg mk">${{i.market}}</span></td>
      <td><span class="bdg ind">${{i.industry||"—"}}</span></td>
      <td>${{i.close.toFixed(2)}}</td>
      <td class="${{pcCls}}">${{fmt(pc)}}</td>
      <td class="${{i.year_return >= 0 ? "up" : "down"}}">${{fmt(i.year_return)}}</td>
      <td><b>${{i.score.toFixed(1)}}</b></td>
      <td style="font-size:11px;color:#555" title="趋势/动能/量能/超买超卖(含布林v3)/风控/研报(对称贡献分)">${{i.comp.trend.toFixed(0)}}/${{i.comp.momentum.toFixed(0)}}/${{i.comp.volume.toFixed(0)}}/${{i.comp.osc.toFixed(0)}}/${{i.comp.risk.toFixed(0)}}/<span class="${{i.comp.news<0?"down":"up"}}">${{i.comp.news>0?"+":""}}${{i.comp.news.toFixed(1)}}</span></td>
      <td style="font-size:11px;color:#555" title="${{i.osc_detail ? '超买超卖子分：RSI ' + i.osc_detail.rsi + ' 分 / KDJ ' + i.osc_detail.kdj + ' 分 / 布林位置 ' + i.osc_detail.boll + ' 分（%B=' + (i.osc_detail.boll_pct != null ? i.osc_detail.boll_pct : '—') + '，v3 新增）' + (i.osc_detail.rsi_div ? '；⚠ ' + i.osc_detail.rsi_div : '') : 'v2 模式无布林分'}}">${{i.osc_detail ? '<div>' + i.osc_detail.rsi.toFixed(0) + '/' + i.osc_detail.kdj.toFixed(0) + '/' + i.osc_detail.boll.toFixed(0) + '</div><div style="margin-top:2px">' + (i.osc_detail.boll_pct != null ? '<span class="bdg boll">B'+ (i.osc_detail.boll_pct*100).toFixed(0) + '%</span>' : '') + (i.osc_detail.rsi_div ? '<span class="bdg rdiv">' + i.osc_detail.rsi_div + '</span>' : '') + '</div>' : '—'}}</td>
      <td style="font-size:11px;color:#555" title="${{i.vol_detail ? '量能子分：量比 ' + i.vol_detail.vr + ' → ' + i.vol_detail.vr_score + ' 分 / 量价配合 ' + i.vol_detail.pv_score + ' 分' + (i.vol_detail.extreme ? '；' + i.vol_detail.extreme : '') + (i.vol_detail.pdv ? '；' + i.vol_detail.pdv : '') + '（v4 量价三件套）' : '—'}}">${{i.vol_detail ? '<div>' + (i.vol_detail.vr != null ? '量比' + i.vol_detail.vr.toFixed(1) : '—') + '</div><div style="margin-top:2px">' + (i.vol_detail.extreme ? '<span class="bdg evol">' + i.vol_detail.extreme + '</span>' : '') + (i.vol_detail.pdv ? '<span class="bdg pdiv">' + i.vol_detail.pdv + '</span>' : '') + '</div>' : '—'}}</td>
      <td><span class="bdg ${{confCls[i.conf.level]}}">${{i.conf.level}}置信</span></td>
      <td><span class="sig ${{actCls[i.action]}}">${{i.action}}</span></td>
      <td>${{chg}}</td></tr>`;
  }}).join("");
  document.getElementById("cnt").textContent = `显示 ${{rows.length}} / ${{ITEMS.length}} 只`;
  const c = i => {{
    const bt = i.bt || {{}};
    return `<div class="card">${{i.radar_svg || ""}}<div class="body"><h3>${{i.name}} <span class="sub">${{i.code}}</span></h3>
      <p class="meta">板块：${{i.market}} ｜ 行业：${{i.industry||"—"}} ｜ 现价 ${{i.close.toFixed(2)}}（<span class="${{i.pct_chg>0?"up":"down"}}">${{fmt(i.pct_chg)}}</span>）｜ 近一年 <span class="${{i.year_return>=0?"up":"down"}}">${{fmt(i.year_return)}}</span></p>
      <p class="meta">权重 <b>${{i.score.toFixed(1)}} 分</b> → <span class="sig ${{actCls[i.action]}}">${{i.action}}</span> <span class="bdg ${{confCls[i.conf.level]}}">${{i.conf.level}}置信</span>${{i.news ? ` ｜ 研报：${{i.news}}` : ""}}</p>
      <p class="meta">六类：趋势 ${{i.comp.trend.toFixed(0)}}｜动能 ${{i.comp.momentum.toFixed(0)}}｜量能 ${{i.comp.volume.toFixed(0)}}${{i.vol_detail && (i.vol_detail.extreme || i.vol_detail.pdv) ? `⚠${{i.vol_detail.extreme || i.vol_detail.pdv}}` : ""}}｜超买超卖 ${{i.comp.osc.toFixed(0)}}${{i.osc_detail && i.osc_detail.rsi_div ? `⚠${{i.osc_detail.rsi_div}}` : ""}}｜风控 ${{i.comp.risk.toFixed(0)}}｜研报 <span class="${{i.comp.news<0?"down":"up"}}">${{i.comp.news>0?"+":""}}${{i.comp.news.toFixed(1)}}</span></p>
      <p class="meta">回测(${{i.bt_window||"2016-01起"}})：收益 <b>${{bt.total_return_pct != null ? bt.total_return_pct.toFixed(1)+"%" : "—"}}</b>（持有 ${{i.buyhold_return != null ? i.buyhold_return.toFixed(1)+"%" : "—"}}）｜回撤 ${{bt.max_drawdown_pct != null ? bt.max_drawdown_pct.toFixed(1)+"%" : "—"}}</p>
      ${{i.risk_note ? `<p class="meta" style="color:#b45309">⚠ 事件：${{i.risk_note}}</p>` : ""}}</div></div>`;
  }};
  document.getElementById("cards").innerHTML = rows.map(c).join("");
}}
render();
// ---- 组合净值交互式走势图（ECharts · v6 2016 起全量 + 时间段筛选）----
if (TREND && TREND.combo && window.echarts) {{
  const chart = echarts.init(document.getElementById("trendChart"));
  const mk = (arr, color, nm) => ({{
    name: nm, type: "line", showSymbol: false, smooth: true, color,
    data: (arr || []).map(p => [p.date, p.value]),
  }});
  chart.setOption({{
    tooltip: {{ trigger: "axis", confine: true }},
    legend: {{ data: ["权重系统 100池", "沪深300"], top: 4 }},
    grid: {{ left: 46, right: 14, top: 34, bottom: 40 }},
    xAxis: {{ type: "time" }},
    yAxis: {{ type: "value", scale: true, axisLabel: {{ formatter: v => v.toFixed(0) }} }},
    dataZoom: [
      {{ type: "inside" }},
      {{ type: "slider", height: 20, bottom: 8, startValue: TREND.combo[0].date, endValue: TREND.combo[TREND.combo.length-1].date }},
    ],
    series: [
      mk(TREND.combo, "#d92d20", "权重系统 100池"),
      mk(TREND.hs300, "#f5a623", "沪深300"),
    ],
  }});
  window.addEventListener("resize", () => chart.resize());
}}
// ---- 导出 PNG / XLSX（分享用）----
const EXPORT_DATE = "{d['date']}";
function exportPNG() {{
  const el = document.getElementById("tbl");
  html2canvas(el, {{ backgroundColor: "#fff", scale: 2, useCORS: true }}).then(canvas => {{
    const a = document.createElement("a");
    a.download = `权重看板_${{EXPORT_DATE}}.png`;
    a.href = canvas.toDataURL("image/png");
    a.click();
  }});
}}
function exportXLSX() {{
  const rows = filtered();  // 导出当前筛选结果
  const fmtPct = v => (v === null || v === undefined) ? "—" : (v > 0 ? "+" : "") + v.toFixed(2) + "%";
  const data = rows.map(i => {{
    const od = i.osc_detail || {{}}, vd = i.vol_detail || {{}};
    return {{
      "名称": i.name, "代码": i.code, "板块": i.market, "行业": i.industry || "—",
      "现价": i.close, "涨跌幅": fmtPct(i.pct_chg), "近一年": fmtPct(i.year_return),
      "权重分": i.score, "趋势": i.comp.trend, "动能": i.comp.momentum, "量能": i.comp.volume,
      "超买超卖": i.comp.osc, "风控": i.comp.risk, "研报": i.comp.news,
      "RSI/KDJ/布林": od.rsi + "/" + od.kdj + "/" + od.boll,
      "布林%B": od.boll_pct != null ? (od.boll_pct * 100).toFixed(1) + "%" : "—",
      "RSI背离": od.rsi_div || "—",
      "量比": vd.vr != null ? vd.vr : "—", "量价信号": [vd.extreme, vd.pdv].filter(Boolean).join(" / ") || "—",
      "置信度": i.conf.level, "操作档位": i.action,
    }};
  }});
  const ws = XLSX.utils.json_to_sheet(data);
  ws["!cols"] = Object.keys(data[0] || {{}}).map(() => ({{ wch: 12 }}));
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, "权重看板");
  XLSX.writeFile(wb, `权重看板_${{EXPORT_DATE}}.xlsx`);
}}
</script>
</body></html>"""

os.makedirs(DIST, exist_ok=True)
out = os.path.join(DIST, "index.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print("written:", out, len(html), "bytes")
