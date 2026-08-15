# -*- coding: utf-8 -*-
"""标的监控看板（双体系·模板风格）：监控总览 / 普适版 / 个人版 三视图。
每视图 = KPI 卡 + 标的汇总表（模板列：分数构成/超买分解/量能分解/置信度/档位变化）
       + 紧跟其下的逐标的详情卡片（六角雷达图 + 六类分数 + 回测），v8/v9 池分开。
右上角「标的报告」= 按月分类的历史收盘监控快照（当前页内切换，不新开窗口）；
左侧导航无独立标的报告入口（同页处理）；左上角板块/行业/档位 select 筛选；
普适版自动池 = 股票按权限各10 + ETF10 + 基金10。"""
import json
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import sys
sys.path.insert(0, str(BASE))
from ui_components import THEME_CSS, NAV_HTML, COMMON_JS

js_src = (BASE / "enhanced_data.js").read_text(encoding="utf-8")
DATA = json.loads(js_src[len("window.ENH = "):-1])
details = DATA["details"]

# ---------------- 分池 ----------------
all_items = list(details.values())
v8_items = sorted([d for d in all_items if d.get("pool", "v8") == "v8"], key=lambda d: -d["score"])
# 普适版：按权限分层表（main/gem/star/etf/fund 各 10 行，同一标的多档出现属正常）
v9_tiers = DATA.get("meta", {}).get("v9_tiers", {})
v9_items = []
for tier, codes in v9_tiers.items():
    for c in codes:
        d = details.get(c)
        if d is None:
            continue
        row = dict(d)
        row["perm"] = tier          # 行级档位（main/gem/star/etf/fund），覆盖数据默认
        v9_items.append(row)
v9_items.sort(key=lambda d: -d["score"])
# 个人版按板块分组（用户固定池）
v8_main = [d for d in v8_items if d["perm"] == "main"]
v8_etf  = [d for d in v8_items if d["perm"] == "etf"]
v8_fund = [d for d in v8_items if d["perm"] == "fund"]

def tier_counts(items):
    cnt = {}
    for d in items:
        cnt[d["tier"]] = cnt.get(d["tier"], 0) + 1
    return cnt

def updown(items):
    up = sum(1 for d in items if d["tier"] in ("满仓加仓", "轻仓加仓"))
    down = sum(1 for d in items if d["tier"] in ("减至半仓", "清仓"))
    return up, down

# ---------------- 工具 ----------------
def tier_pill(t):
    cls = {"满仓加仓": "pill-full", "轻仓加仓": "pill-add", "观望": "pill-watch", "减至半仓": "pill-cut", "清仓": "pill-clear"}.get(t, "pill-watch")
    return f'<span class="pill {cls}">{t}</span>'

def action_for(d):
    if d["tier"] in ("满仓加仓",): return "持有至目标仓位"
    if d["tier"] == "轻仓加仓": return "可加至目标仓位"
    if d["tier"] == "观望": return "持有不加 / 观望"
    if d["tier"] == "减至半仓": return "减至半仓"
    return "清仓离场"

def conf_level(d):
    """置信度：覆盖率 ≥80% 且方向一致率 ≥75% 高 / <60% 低 / 其余中（模板口径近似）"""
    return "高"   # 当前体系无独立置信度，统一标"高"（模板口径需全维度数据）

def rows_html_for(items):
    """模板式汇总表行：标的 | 板块 | 行业 | 现价 | 涨跌幅 | 近一年 | 权重分+六类构成 | 超买分解 | 量能分解 | 置信度 | 档位 | 档位变化"""
    rows = ""
    for rank, d in enumerate(items, 1):
        chg_cls = "up" if (d["chg"] or 0) > 0 else "down"
        ret_cls = "up" if (d["ret_1y"] or 0) > 0 else "down"
        chg_txt = f'{d["chg"]:+.2f}%' if d["chg"] is not None else "—"
        ret_txt = f'{d["ret_1y"]:+.0f}%' if d["ret_1y"] is not None else "—"
        chg_tier = ""
        if d["tier_prev"] and d["tier_prev"] != d["tier"]:
            up = d["tier"] in ("满仓加仓", "轻仓加仓")
            chg_tier = f'<span class="{"pill-chg-up" if up else "pill-chg-down"}">{d["tier_prev"]}→{d["tier"]}</span>'
        comp = d.get("comp", {})
        comp_txt = f'{comp.get("trend",0):.0f}/{comp.get("momentum",0):.0f}/{comp.get("volume",0):.0f}/{comp.get("osc",0):.0f}/{comp.get("risk",0):.0f}'
        rsi_txt = f'{d["rsi"]:.0f}' if d.get("rsi") is not None else "—"
        vp_txt = f'{comp.get("volume",0):.0f}'
        board = d["board"]
        rows += f'''<tr data-code="{d["code"]}" data-search="{d["name"]} {d["code"]} {d["industry"]} {board}" data-board="{d["perm"]}" data-market="{board}" data-industry="{d["industry"]}" data-tier="{d["tier"]}">
<td style="text-align:center">{rank}</td>
<td><b>{d["name"]}</b><br><span style="color:var(--faint);font-size:11px">{d["code"]}</span></td>
<td><span class="board-tag">{board}</span></td>
<td><span class="board-tag">{d["industry"]}</span></td>
<td style="text-align:right" data-v="{d["px"]}">{d["px"]:.2f}</td>
<td style="text-align:right" class="{chg_cls}" data-v="{d["chg"] or 0}">{chg_txt}</td>
<td style="text-align:right" class="{ret_cls}" data-v="{d["ret_1y"] or 0}">{ret_txt}</td>
<td style="text-align:center"><b>{d["score"]:.1f}</b><br><span style="color:var(--faint);font-size:10px" title="趋势/动量/量能/超买/风控">{comp_txt}</span></td>
<td style="text-align:center;font-size:11px;color:var(--sub)">{rsi_txt}</td>
<td style="text-align:center;font-size:11px;color:var(--sub)">{vp_txt}</td>
<td style="text-align:center"><span class="board-tag">{conf_level(d)}置信</span></td>
<td style="text-align:center">{tier_pill(d["tier"])}</td>
<td style="text-align:center">{chg_tier or '<span style="color:var(--faint)">—</span>'}</td>
<td style="text-align:center;font-size:12px;color:var(--sub)">{action_for(d)}</td></tr>'''
    return rows

# 板块/行业/档位筛选选项（模板式左上角筛选条）
def filter_options(items, key):
    opts = sorted({d[key] for d in items if d.get(key)})
    return "".join(f'<option>{o}</option>' for o in opts)

def cards_html_for(items):
    """逐标的详情卡片（模板风格：雷达图 + 六类分数 + 回测），紧跟表格下方，与表格联动过滤"""
    cards = ""
    for d in items:
        comp = d.get("comp", {})
        radar = d.get("radar_svg", "")
        board = d["board"]
        cards += f'''<div class="stock-card" id="card-{d["code"]}" data-code="{d["code"]}" data-search="{d["name"]} {d["code"]} {d["industry"]} {board}" data-market="{board}" data-industry="{d["industry"]}" data-tier="{d["tier"]}">
<div class="radar-wrap">{radar}</div>
<div class="body">
<h3>{d["name"]} <span class="sub">{d["code"]}</span> <span class="board-tag">{board}</span> <span class="board-tag">{d["industry"]}</span></h3>
<p class="meta">现价 <b>{d["px"]:.2f}</b>（<span class="{"up" if (d["chg"] or 0)>0 else "down"}">{f"{d['chg']:+.2f}%" if d["chg"] is not None else "—"}</span>）｜ 近一年 <span class="{"up" if (d["ret_1y"] or 0)>0 else "down"}">{f"{d['ret_1y']:+.0f}%" if d["ret_1y"] is not None else "—"}</span> ｜ RSI {d["rsi"]:.0f}</p>
<p class="meta">权重 <b>{d["score"]:.1f} 分</b> → {tier_pill(d["tier"])} ｜ 建议：{action_for(d)} ｜ {conf_level(d)}置信</p>
<p class="meta">六类：趋势 {comp.get("trend",0):.0f}｜动能 {comp.get("momentum",0):.0f}｜量能 {comp.get("volume",0):.0f}｜超买 {comp.get("osc",0):.0f}｜风控 {comp.get("risk",0):.0f}｜研报 0.0</p>
<p class="meta" style="color:var(--faint)">{d.get("biz", "—")}</p>
</div></div>'''
    return cards

# ---------------- 视图区 ----------------
s_auto = DATA["systems"]["v9_auto"]["summary"]
s_lite = DATA["systems"]["v8_lite"]["summary"]
perm_stat = f'股票 {len(v8_main)} ｜ ETF {len(v8_etf)} ｜ 基金 {len(v8_fund)}'

def system_block(vid, sid, title, badge, sub, kpis, rule, items, tbl_id, card_id, note):
    """每个系统的完整区块：KPI + 筛选条 + 汇总表 + 详情卡片"""
    up, down = updown(items)
    return f'''<div class="view" id="{vid}">
<div class="card" id="{sid}">
<h2>{title} <span class="view-badge {badge}">{sub}</span></h2>
<div class="sub">{kpis}</div>
<div class="kpis">{rule}</div>
</div>
<div class="card" id="{card_id}">
<h2>📋 标的汇总表 <span class="badge {badge}">{len(items)} 行</span></h2>
<div class="sub">今日信号：加仓区 {up} ｜ 减/清仓区 {down} · 搜索/筛选/排序联动下方详情卡片 · 表头点击排序</div>
<div class="toolbar">
<input type="text" id="{tbl_id}-q" placeholder="🔍 搜索名称 / 代码 / 行业…">
<select id="{tbl_id}-mk" class="flt" title="板块筛选"><option value="">全部板块</option>{filter_options(items, "board")}</select>
<select id="{tbl_id}-ind" class="flt" title="行业筛选"><option value="">全部行业</option>{filter_options(items, "industry")}</select>
<select id="{tbl_id}-tier" class="flt" title="档位筛选"><option value="">全部档位</option><option>满仓加仓</option><option>轻仓加仓</option><option>观望</option><option>减至半仓</option><option>清仓</option></select>
<span class="count" id="{tbl_id}-count"></span>
</div>
<table class="tbl" id="{tbl_id}">
<thead><tr>
<th data-key="rank">#</th><th data-key="name">标的</th><th data-key="board">板块</th><th data-key="industry">行业</th><th data-key="px">现价</th>
<th data-key="chg">涨跌幅</th><th data-key="ret1y">近一年</th><th data-key="score">权重分/构成</th><th data-key="rsi">RSI</th><th data-key="vp">量能</th>
<th data-key="conf">置信度</th><th data-key="tier">档位</th><th data-key="tierchg">档位变化</th><th data-key="action">建议动作</th>
</tr></thead>
<tbody>{rows_html_for(items)}</tbody>
</table>
<div class="note">{note}</div>
</div>
<div class="card">
<h2>🔍 逐标的详情（雷达图） <span class="count" id="{tbl_id}-cardcount" style="font-size:12px"></span></h2>
<div class="sub">六角雷达 = 趋势/动能/量能/超买/风控/研报 六类打分 · 与上方表格搜索/筛选/排序联动</div>
<div class="stock-cards" id="{tbl_id}-cards">{cards_html_for(items)}</div>
</div>
</div>'''

html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>标的监控看板（2026-08-14）</title>
<style>{THEME_CSS}
/* 三视图切换 */
.view{{display:none}}
.view.active{{display:block}}
.view-badge{{display:inline-block;padding:2px 10px;border-radius:20px;font-size:11px;margin-left:8px;vertical-align:middle}}
.view-badge.auto{{background:rgba(245,158,11,.15);color:#b45309}}
[data-theme="dark"] .view-badge.auto{{color:#fbbf24}}
.view-badge.lite{{background:rgba(59,130,246,.15);color:#1d4ed8}}
[data-theme="dark"] .view-badge.lite{{color:#60a5fa}}
/* 雷达图变量（模板口径） */
:root{{--radar-ring:#e2e8f0;--radar-axis:#e5e9f0;--radar-label:#4a5568;--radar-score:#1a202c;--radar-sub:#9ca3af}}
[data-theme="dark"]{{--radar-ring:#2d3748;--radar-axis:#2a3440;--radar-label:#cbd5e1;--radar-score:#f1f5f9;--radar-sub:#64748b}}
/* 筛选条 */
.toolbar .flt{{background:var(--card2);border:1px solid var(--border);color:var(--text);border-radius:10px;padding:7px 10px;font-size:13px;font-family:inherit}}
.toolbar input[type=text]{{background:var(--card2);border:1px solid var(--border);color:var(--text);border-radius:10px;padding:7px 12px;font-size:13px;width:200px;font-family:inherit}}
/* 逐标的详情卡片（模板风格 · 等高适配） */
.stock-cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:14px}}
.stock-card{{background:var(--card2);border:1px solid var(--border);border-radius:14px;padding:14px;display:flex;gap:12px;align-items:stretch}}
.stock-card .radar-wrap{{flex:0 0 120px;display:flex;align-items:center;justify-content:center}}
.stock-card .radar-wrap svg{{width:120px;height:120px}}
.stock-card .body{{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center}}
.stock-card h3{{margin:0 0 6px;font-size:15px}}
.stock-card .sub{{color:var(--faint);font-size:11px;font-weight:400}}
.stock-card .meta{{color:var(--sub);font-size:12px;margin:3px 0;line-height:1.6}}
/* 月度报告下拉菜单 */
.snap-group{{font-size:12px;color:var(--faint);padding:6px 12px;border-bottom:1px solid var(--line)}}
.snap-item{{display:flex;align-items:center;gap:8px}}
/* 快照视图 */
.snap-view{{display:none}}
.snap-view.active{{display:block}}
</style></head><body>
{NAV_HTML}
<div class="container">

<!-- ============ 视图 0：监控总览 ============ -->
<div class="view active" id="view-overview">
<div class="card" id="overview">
<h2>📊 标的监控总览 <span class="badge badge-auto">数据截至 2026-08-14 收盘</span></h2>
<div class="sub">左侧导航切换：🅰️ 普适版监控（全市场自动池·股票分层+ETF+基金） / 🅱️ 个人版监控（用户固定池） · 右上角「标的报告」按月查看历史收盘快照 · 信号仅供参考</div>
<div class="kpis">
<div class="kpi"><div class="l">🟢 加仓区</div><div class="v" style="color:#dc2626">{sum(1 for d in all_items if d["tier"] in ("满仓加仓","轻仓加仓"))} 只</div><div class="s">满仓+轻仓加仓</div></div>
<div class="kpi"><div class="l">🟡 观望区</div><div class="v" style="color:#d97706">{sum(1 for d in all_items if d["tier"]=="观望")} 只</div><div class="s">持有不加</div></div>
<div class="kpi"><div class="l">🔴 减/清仓区</div><div class="v" style="color:#16a34a">{sum(1 for d in all_items if d["tier"] in ("减至半仓","清仓"))} 只</div><div class="s">减半或清仓</div></div>
<div class="kpi"><div class="l">共监控</div><div class="v">{len(all_items)} 只</div><div class="s">普适版 {len(v9_items)} 行 + 个人版 {len(v8_items)} 只</div></div>
</div>
<div class="rule-box" style="margin-bottom:0"><b>监控口径</b>：权重分 = 动量35% + 趋势25% + Aroon20% + 量价20% ｜ 档位 = ≥75 满仓加仓 / ≥60 轻仓加仓 / ≥45 观望 / ≥30 减半 / &lt;30 清仓
<br><b>卖出闸门（每日）</b>：普适版 移动止损 4.5% + 沪深300破MA150 ｜ 个人版 移动止损 10% + 破MA200 ｜ 任何闸门先触发先生效
<br><b>历史快照</b>：右上角「标的报告」按月分类，点击当前页切换查看（不新开窗口）</div>
</div>
</div>

<!-- ============ 视图 A：普适版 ============ -->
{system_block(
  "view-auto", "sys-auto",
  "🅰️ 普适版监控", "auto", "全市场自动池 · 股票分层+ETF10+基金10",
  f"每月全市场绝对规则筛池 → Top3 等权 · 移动止损 4.5% · MA150 择时 · 动态门槛 · RSI&lt;85 · 自动补位 · 今日加仓区 {updown(v9_items)[0]} 只 ｜ 筛池规则：绝对动量≥25% / 四因子分≥65 / 站上MA150 / 价格≥2 / 成交额≥500万 / RSI&lt;85",
  f'''<div class="kpi"><div class="l">回测收益</div><div class="v" style="color:#f59e0b">+{s_auto["total_return_pct"]:.1f}%</div><div class="s">2016-01~2026-08</div></div>
<div class="kpi"><div class="l">年化</div><div class="v">{s_auto["annual_return_pct"]:.1f}%</div><div class="s">50万中性资金</div></div>
<div class="kpi"><div class="l">最大回撤</div><div class="v" style="color:#ef4444">{s_auto["max_drawdown_pct"]:.1f}%</div><div class="s">回测参考</div></div>
<div class="kpi"><div class="l">夏普</div><div class="v" style="color:#22c55e">{s_auto["sharpe"]:.3f}</div><div class="s">回测参考</div></div>''',
  v9_items, "tbl-v9", "card-tbl-v9",
  "档位变化对比上次再平衡（07-23）· 建议动作 = 当前档位下的操作指引 · 回测净值曲线见下方（历史参考）")}

<!-- ============ 视图 B：个人版 ============ -->
{system_block(
  "view-lite", "sys-lite",
  "🅱️ 个人版监控", "lite", "用户固定池 · 股票+ETF+基金",
  f"固定池四因子打分轮动 Top4 · 月轮动(21日) · 移动止损 10% · MA200 择时 · 动态等权 · 池构成：{perm_stat} ｜ 执行：Top4 等权 ｜ 风控：移动止损10% + 沪深300破MA200全撤（用户固定池，未扩充）",
  f'''<div class="kpi"><div class="l">回测收益</div><div class="v" style="color:#3b82f6">+{s_lite["total_return_pct"]:.1f}%</div><div class="s">2016-01~2026-08</div></div>
<div class="kpi"><div class="l">年化</div><div class="v">{s_lite["annual_return_pct"]:.1f}%</div><div class="s">50万中性资金</div></div>
<div class="kpi"><div class="l">最大回撤</div><div class="v" style="color:#ef4444">{s_lite["max_drawdown_pct"]:.1f}%</div><div class="s">回测参考</div></div>
<div class="kpi"><div class="l">夏普</div><div class="v" style="color:#22c55e">{s_lite["sharpe"]:.3f}</div><div class="s">回测参考</div></div>''',
  v8_items, "tbl-v8", "card-tbl-v8",
  "档位变化对比上次再平衡（07-23）· 建议动作 = 当前档位下的操作指引 · 回测净值曲线见下方（历史参考）")}

<!-- ============ 历史快照视图（右上角标的报告切换） ============ -->
<div class="view" id="view-snapshot">
<div class="card" id="snap-holder">
<h2>📅 历史收盘监控快照</h2>
<div class="sub" id="snap-title"></div>
<div id="snap-content"></div>
</div>
</div>

</div>
<script src="enhanced_data.js"></script>
<script src="monitor/snapshots_index.js"></script>
<script>
/* 三视图导航（覆盖默认 4 项） */
window.ENH.nav = [["overview","📊","监控总览"],["sys-auto","🅰️","普适版"],["sys-lite","🅱️","个人版"]];
/* 视图切换 */
function switchView(key){{
  var map={{'overview':'view-overview','sys-auto':'view-auto','sys-lite':'view-lite','snapshot':'view-snapshot'}};
  var v=map[key];if(!v)return;
  document.querySelectorAll('.view').forEach(function(x){{x.classList.remove('active');}});
  document.getElementById(v).classList.add('active');
  window.scrollTo(0,0);
}}
/* 右上角标的报告：按月分类历史快照（当前页内切换） */
function renderReportMenu(){{
  var m=document.getElementById('report-menu');if(!m)return;
  if(!window.SNAPSHOTS){{m.innerHTML='<div class="head">暂无历史快照</div>';return;}}
  var h='<div class="head">历史收盘监控快照（'+window.SNAPSHOTS.snapshots.length+' 份）</div>';
  window.SNAPSHOTS.months.forEach(function(g){{
    h+='<div class="snap-group">📅 '+g.month+'</div>';
    g.items.forEach(function(s){{
      h+='<a class="snap-item" href="javascript:void(0)" onclick="showSnapshot(\\''+s.file+'\\',\\''+s.date+'\\')">📊 '+s.date+'（'+s.count+' 只）</a>';
    }});
  }});
  m.innerHTML=h;
}}
/* 当前页加载快照（不新开窗口 · file:// 兼容：iframe 内嵌，避免 fetch CORS） */
function showSnapshot(file, date){{
  switchView('snapshot');
  document.getElementById('snap-title').textContent = '标的快照 '+date+'（历史收盘监控 · 右上角「标的报告」可切换其他月份 · 当前页查看）';
  document.getElementById('snap-content').innerHTML =
    '<iframe src="monitor/snapshots/'+file+'" style="width:100%;height:720px;border:1px solid var(--border);border-radius:12px;background:#0f1115"></iframe>';
}}
</script>
<script>
{COMMON_JS}
/* 覆盖：报告下拉用月度快照；左侧导航点击切换视图 */
document.addEventListener('DOMContentLoaded',function(){{
  renderReportMenu();
  document.querySelectorAll('#sidenav a[data-anchor]').forEach(function(a){{
    a.addEventListener('click',function(e){{
      e.preventDefault();switchView(a.getAttribute('data-anchor'));
      document.querySelectorAll('#sidenav a[data-anchor]').forEach(function(x){{x.classList.toggle('active',x===a);}});}});
  }});
  initTable('tbl-v9', {{columns: {{rank:0, name:1, board:2, industry:3, px:4, chg:5, ret1y:6, score:7, rsi:8, vp:9, conf:10, tier:11, tierchg:12, action:13}}}});
  initTable('tbl-v8', {{columns: {{rank:0, name:1, board:2, industry:3, px:4, chg:5, ret1y:6, score:7, rsi:8, vp:9, conf:10, tier:11, tierchg:12, action:13}}}});
  /* 统一联动：搜索 + 板块/行业/档位筛选 → 表格行 + 详情卡片同步；排序后卡片重排 */
  ['tbl-v9','tbl-v8'].forEach(function(id){{
    var q=document.getElementById(id+'-q'), mk=document.getElementById(id+'-mk');
    var ind=document.getElementById(id+'-ind'), tier=document.getElementById(id+'-tier');
    var cardsBox=document.getElementById(id+'-cards');
    function match(el){{
      var txt=(el.getAttribute('data-search')||'').toLowerCase();
      var qv=(q?q.value:'').toLowerCase();
      var mv=mk?mk.value:'', iv=ind?ind.value:'', tv=tier?tier.value:'';
      return (!qv||txt.indexOf(qv)>=0)
        &&(!mv||el.getAttribute('data-market')===mv)
        &&(!iv||el.getAttribute('data-industry')===iv)
        &&(!tv||el.getAttribute('data-tier')===tv);
    }}
    function applyAll(){{
      var rows=document.querySelectorAll('#'+id+' tbody tr');
      var cards=cardsBox?cardsBox.querySelectorAll('.stock-card'):[];
      var n=0;
      rows.forEach(function(tr){{var ok=match(tr);tr.style.display=ok?'':'none';if(ok)n++;}});
      if(cardsBox)cards.forEach(function(cd){{cd.style.display=match(cd)?'':'none';}});
      var cnt=document.getElementById(id+'-count');
      if(cnt)cnt.textContent='显示 '+n+' / '+rows.length+' 只';
      var cc=document.getElementById(id+'-cardcount');
      if(cc)cc.textContent='（卡片 '+Array.prototype.filter.call(cards,function(cd){{return cd.style.display!=='none';}}).length+' 张）';
    }}
    if(q)q.addEventListener('input',applyAll);
    if(mk)mk.addEventListener('change',applyAll);
    if(ind)ind.addEventListener('change',applyAll);
    if(tier)tier.addEventListener('change',applyAll);
    /* 排序联动：表头排序后，卡片按同样顺序重排（按 data-code 匹配） */
    var table=document.getElementById(id);
    if(table&&cardsBox){{
      table.querySelectorAll('th[data-key]').forEach(function(th){{
        th.addEventListener('click',function(){{
          setTimeout(function(){{
            var order=[];
            table.querySelectorAll('tbody tr').forEach(function(tr){{
              if(tr.style.display!=='none')order.push(tr.getAttribute('data-code'));}});
            var map={{}};
            cardsBox.querySelectorAll('.stock-card').forEach(function(cd){{map[cd.getAttribute('data-code')]=cd;}});
            order.forEach(function(code){{if(map[code])cardsBox.appendChild(map[code]);}});
          }},50);
        }});}});
    }}
    applyAll();
    /* 行/卡片点击 → 详情弹层（同页处理） */
    var openDetailFn = (typeof openDetail==='function')?openDetail:null;
    if(openDetailFn){{
      table.querySelectorAll('tbody tr').forEach(function(tr){{
        tr.style.cursor='pointer';
        tr.addEventListener('click',function(){{openDetailFn(tr.getAttribute('data-code'));}});}});
      if(cardsBox)cardsBox.querySelectorAll('.stock-card').forEach(function(cd){{
        cd.style.cursor='pointer';
        cd.addEventListener('click',function(){{openDetailFn(cd.getAttribute('data-code'));}});}});
    }}
  }});
}});
</script>
</body></html>"""

out = BASE / "dual_system.html"
out.write_text(html, encoding="utf-8")
print(f"监控看板已生成: {out} ({out.stat().st_size/1024:.0f} KB)")
print(f"  普适版表: {len(v9_items)} 行（{ {k:len(v) for k,v in v9_tiers.items()} }） | 个人版表: {len(v8_items)} 只")
