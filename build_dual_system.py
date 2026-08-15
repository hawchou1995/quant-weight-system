# -*- coding: utf-8 -*-
"""标的监控看板（双体系·三视图）：监控总览 / 普适版监控 / 个人版监控。
左侧导航点击切换独立视图（不再一页堆叠）；每视图含 KPI + 监控表 + 独立回测曲线；
个人版 = 用户固定池（20股+5ETF+6基金）不动；普适版自动池按权限分层（main主板10/gem+创业板10/star全A10）；
标题去版本号（普适版/个人版）；曲线独立坐标轴（根治纵坐标挤成皱纹）。"""
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

# ---------------- 分池 ----------------
all_items = list(details.values())
v8_items = sorted([d for d in all_items if d.get("pool", "v8") == "v8"], key=lambda d: -d["score"])
# 普适版：按权限分层表（main 10 + gem 10 + star 10 = 30 行，同一标的多档出现属正常，
# 权限过滤时每档恰好 10 只）；details 数据每只一份（600183 等重叠标的取个人版数据）
v9_tiers = DATA.get("meta", {}).get("v9_tiers", {})
v9_items = []
for tier, codes in v9_tiers.items():
    for c in codes:
        d = details.get(c)
        if d is None:
            continue
        row = dict(d)
        row["perm"] = tier          # 行级档位（main/gem/star），覆盖数据默认
        v9_items.append(row)
v9_items.sort(key=lambda d: -d["score"])
# 个人版按板块分组（用户固定池：股票+ETF+基金）
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

# ---------------- 行渲染 ----------------
def tier_pill(t):
    cls = {"满仓加仓": "pill-full", "轻仓加仓": "pill-add", "观望": "pill-watch", "减至半仓": "pill-cut", "清仓": "pill-clear"}.get(t, "pill-watch")
    return f'<span class="pill {cls}">{t}</span>'

def action_for(d):
    if d["tier"] in ("满仓加仓",): return "持有至目标仓位"
    if d["tier"] == "轻仓加仓": return "可加至目标仓位"
    if d["tier"] == "观望": return "持有不加 / 观望"
    if d["tier"] == "减至半仓": return "减至半仓"
    return "清仓离场"

def rows_html_for(items):
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
        board = d["board"]
        rows += f'''<tr data-search="{d["name"]} {d["code"]} {d["industry"]}" data-board="{d["perm"]}" data-tier="{d["tier"]}" onclick="openDetail('{d["code"]}')">
<td style="text-align:center">{rank}</td>
<td><b>{d["name"]}</b><br><span style="color:var(--faint);font-size:11px">{d["code"]} <span class="board-tag">{board}</span> <span class="board-tag">{d["industry"]}</span></span></td>
<td style="text-align:right" data-v="{d["px"]}">{d["px"]:.2f}</td>
<td style="text-align:right" class="{chg_cls}" data-v="{d["chg"] or 0}">{chg_txt}</td>
<td style="text-align:right" class="{ret_cls}" data-v="{d["ret_1y"] or 0}">{ret_txt}</td>
<td style="text-align:center"><b>{d["score"]:.1f}</b></td>
<td style="text-align:center">{tier_pill(d["tier"])}</td>
<td style="text-align:center">{chg_tier or '<span style="color:var(--faint)">—</span>'}</td>
<td style="text-align:center;font-size:12px;color:var(--sub)">{action_for(d)}</td></tr>'''
    return rows

perm_btns = ''.join(
    f'<button data-perm="{p}" class="{"active" if p == "all" else ""}">{lbl}</button>'
    for p, lbl in [("all", "全部"), ("main", "主板·新开户"), ("gem", "+创业板"), ("star", "+科创板"), ("etf", "ETF"), ("fund", "基金")])

tier_opts = '<option value="all">全部档位</option><option>满仓加仓</option><option>轻仓加仓</option><option>观望</option><option>减至半仓</option><option>清仓</option>'

def table_card(card_id, tbl_id, title, badge, sub, items, note):
    up, down = updown(items)
    return f'''<div class="card" id="{card_id}">
<h2>{title} <span class="badge {badge}">{len(items)} 只</span></h2>
<div class="sub">{sub} · 今日信号：加仓区 {up} ｜ 减/清仓区 {down} · 点击行打开监控详情 · 表头点击排序 · 权限切换模拟开户状态</div>
<div class="toolbar">
<input type="text" id="{tbl_id}-q" placeholder="🔍 搜索名称 / 代码 / 行业…">
<div class="perm-group" data-perm-group="{tbl_id}">{perm_btns}</div>
<select id="{tbl_id}-tier">{tier_opts}</select>
<span class="count" id="{tbl_id}-count"></span>
</div>
<table class="tbl" id="{tbl_id}">
<thead><tr>
<th data-key="rank">排名</th><th data-key="name">标的 / 板块 / 行业</th><th data-key="px">现价</th>
<th data-key="chg">当日</th><th data-key="ret1y">近一年</th><th data-key="score">权重分</th>
<th data-key="tier">档位</th><th data-key="tierchg">档位变化</th><th data-key="action">建议动作</th>
</tr></thead>
<tbody>{rows_html_for(items)}</tbody>
</table>
<div class="note">{note}</div>
</div>'''

# 独立曲线容器（每系统一个，JS 单独渲染）
svg_curve_auto = '<div id="curve-chart-auto" style="background:var(--card);border-radius:12px;border:1px solid var(--border);padding:6px"></div>'
svg_curve_lite = '<div id="curve-chart-lite" style="background:var(--card);border-radius:12px;border:1px solid var(--border);padding:6px"></div>'

s_auto = DATA["systems"]["v9_auto"]["summary"]
s_lite = DATA["systems"]["v8_lite"]["summary"]

t9 = tier_counts(v9_items)
t8 = tier_counts(v8_items)
up9, down9 = updown(v9_items)
up8, down8 = updown(v8_items)

# 权限分层概览（个人版）
perm_stat = f'''股票 {len(v8_main)} ｜ ETF {len(v8_etf)} ｜ 基金 {len(v8_fund)}'''

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
</style></head><body>
{NAV_HTML}
<div class="container">

<!-- ============ 视图 0：监控总览 ============ -->
<div class="view active" id="view-overview">
<div class="card" id="overview">
<h2>📊 标的监控总览 <span class="badge badge-auto">数据截至 2026-08-14 收盘</span></h2>
<div class="sub">左侧导航切换：🅰️ 普适版监控（全市场自动池·权限分层各10只） / 🅱️ 个人版监控（用户固定池·股票+ETF+基金） · 信号仅供参考，执行与否由你决定</div>
<div class="kpis">
<div class="kpi"><div class="l">🟢 加仓区</div><div class="v" style="color:#dc2626">{sum(1 for d in all_items if d["tier"] in ("满仓加仓","轻仓加仓"))} 只</div><div class="s">满仓+轻仓加仓</div></div>
<div class="kpi"><div class="l">🟡 观望区</div><div class="v" style="color:#d97706">{sum(1 for d in all_items if d["tier"]=="观望")} 只</div><div class="s">持有不加</div></div>
<div class="kpi"><div class="l">🔴 减/清仓区</div><div class="v" style="color:#16a34a">{sum(1 for d in all_items if d["tier"] in ("减至半仓","清仓"))} 只</div><div class="s">减半或清仓</div></div>
<div class="kpi"><div class="l">共监控</div><div class="v">{len(all_items)} 只</div><div class="s">普适版 {len(v9_items)} + 个人版 {len(v8_items)}</div></div>
</div>
<div class="rule-box" style="margin-bottom:0"><b>监控口径</b>：权重分 = 动量35% + 趋势25% + Aroon20% + 量价20% ｜ 档位 = ≥75 满仓加仓 / ≥60 轻仓加仓 / ≥45 观望 / ≥30 减半 / &lt;30 清仓
<br><b>卖出闸门（每日）</b>：普适版 移动止损 4.5% + 沪深300破MA150 ｜ 个人版 移动止损 10% + 破MA200 ｜ 任何闸门先触发先生效</div>
</div>
</div>

<!-- ============ 视图 A：普适版监控 ============ -->
<div class="view" id="view-auto">
<div class="card" id="sys-auto">
<h2>🅰️ 普适版监控 <span class="view-badge auto">全市场自动池 · 权限分层各 10 只</span></h2>
<div class="sub">每月全市场绝对规则筛池 → Top3 等权 · 移动止损 4.5% · MA150 择时 · 动态门槛 · RSI&lt;85 · 自动补位</div>
<div class="kpis">
<div class="kpi"><div class="l">回测收益</div><div class="v" style="color:#f59e0b">+{s_auto["total_return_pct"]:.1f}%</div><div class="s">参考：2016-01~2026-08</div></div>
<div class="kpi"><div class="l">年化</div><div class="v">{s_auto["annual_return_pct"]:.1f}%</div><div class="s">50万中性资金</div></div>
<div class="kpi"><div class="l">最大回撤</div><div class="v" style="color:#ef4444">{s_auto["max_drawdown_pct"]:.1f}%</div><div class="s">回测参考</div></div>
<div class="kpi"><div class="l">夏普</div><div class="v" style="color:#22c55e">{s_auto["sharpe"]:.3f}</div><div class="s">回测参考</div></div>
</div>
<div class="rule-box" style="margin-bottom:0"><b>自动筛池规则（人人平等）</b>：绝对动量 ≥25% ｜ 四因子分 ≥65 ｜ 站上 MA150 ｜ 价格 ≥2 ｜ 成交额 ≥500万 ｜ RSI &lt;85
<br><b>权限档</b>：main=仅主板(新开户) 夏普2.49 ｜ gem=+创业板 2.44 ｜ star=+科创板 2.34 —— 下表按权限切换查看</div>
</div>
{table_card("card-tbl-v9", "tbl-v9", "📋 普适版监控表", "badge-auto",
            "全市场自动筛池 · 按权限分层（main 主板10 / gem +创业板10 / star 全A10 = 30 行），同一标的多档出现属正常", v9_items,
            "档位变化对比上次再平衡（07-23）· 建议动作 = 当前档位下的操作指引 · 回测净值曲线见下方（历史参考）")}
<div class="card" id="curve-auto">
<h2>📈 回测净值参考（普适版 · 2016-2026）</h2>
<div class="sub">全市场自动池 Top3 十年回测曲线（归一化 100 起）——监控依据的历史表现背景</div>
{svg_curve_auto}
</div>
</div>

<!-- ============ 视图 B：个人版监控 ============ -->
<div class="view" id="view-lite">
<div class="card" id="sys-lite">
<h2>🅱️ 个人版监控 <span class="view-badge lite">用户固定池 · 股票+ETF+基金</span></h2>
<div class="sub">固定池四因子打分轮动 Top4 · 月轮动(21日) · 移动止损 10% · MA200 择时 · 动态等权 · 池构成：{perm_stat}</div>
<div class="kpis">
<div class="kpi"><div class="l">回测收益</div><div class="v" style="color:#3b82f6">+{s_lite["total_return_pct"]:.1f}%</div><div class="s">参考：2016-01~2026-08</div></div>
<div class="kpi"><div class="l">年化</div><div class="v">{s_lite["annual_return_pct"]:.1f}%</div><div class="s">50万中性资金</div></div>
<div class="kpi"><div class="l">最大回撤</div><div class="v" style="color:#ef4444">{s_lite["max_drawdown_pct"]:.1f}%</div><div class="s">回测参考</div></div>
<div class="kpi"><div class="l">夏普</div><div class="v" style="color:#22c55e">{s_lite["sharpe"]:.3f}</div><div class="s">回测参考</div></div>
</div>
<div class="rule-box" style="margin-bottom:0"><b>执行</b>：用户固定池 {len(v8_items)} 只打分 → 每期 Top4 等权 ｜ <b>风控</b>：移动止损 10% ｜ 沪深300 破 MA200 全撤 ｜ <b>池构成</b>：股票 {len(v8_main)} + ETF {len(v8_etf)} + 基金 {len(v8_fund)}（用户固定池，未扩充）</div>
</div>
{table_card("card-tbl-v8", "tbl-v8", "📋 个人版监控表", "badge-lite",
            f"用户固定池 {len(v8_items)} 只（股票 {len(v8_main)} + ETF {len(v8_etf)} + 基金 {len(v8_fund)}）", v8_items,
            "档位变化对比上次再平衡（07-23）· 建议动作 = 当前档位下的操作指引 · 回测净值曲线见下方（历史参考）")}
<div class="card" id="curve-lite">
<h2>📈 回测净值参考（个人版 · 2016-2026）</h2>
<div class="sub">自选池内 Top4 轮动十年回测曲线（归一化 100 起）——监控依据的历史表现背景</div>
{svg_curve_lite}
</div>
</div>

</div>
<script src="enhanced_data.js"></script>
<script>
/* 三视图导航（覆盖默认 4 项） */
window.ENH.nav = [["overview","📊","监控总览"],["sys-auto","🅰️","普适版"],["sys-lite","🅱️","个人版"]];
/* 视图切换：导航点击显示对应 view，隐藏其他 */
function switchView(key){{
  var map={{'overview':'view-overview','sys-auto':'view-auto','sys-lite':'view-lite'}};
  var v=map[key];if(!v)return;
  document.querySelectorAll('.view').forEach(function(x){{x.classList.remove('active');}});
  document.getElementById(v).classList.add('active');
  window.scrollTo(0,0);
}}
</script>
<script>
{COMMON_JS}
/* 重写导航点击：切换视图而非滚动 */
document.addEventListener('DOMContentLoaded',function(){{
  document.querySelectorAll('#sidenav a[data-anchor]').forEach(function(a){{
    a.addEventListener('click',function(e){{
      e.preventDefault();switchView(a.getAttribute('data-anchor'));
      document.querySelectorAll('#sidenav a[data-anchor]').forEach(function(x){{x.classList.toggle('active',x===a);}});}});
  }});
  initTable('tbl-v9', {{columns: {{rank:0, name:1, px:2, chg:3, ret1y:4, score:5, tier:6, tierchg:7, action:8}}}});
  initTable('tbl-v8', {{columns: {{rank:0, name:1, px:2, chg:3, ret1y:4, score:5, tier:6, tierchg:7, action:8}}}});
}});
/* 独立曲线渲染：每系统单独坐标轴，根治"皱纹" */
function renderCurveAuto(){{
  var el=document.getElementById('curve-chart-auto');if(!el)return;
  var S=window.ENH.systems;if(!S)return;
  var va=S.v9_auto.equity;
  var n=va.length,W=1400,H=300,PAD_L=70,PAD_R=20,PAD_T=26,PAD_B=34;
  var x=function(i){{return PAD_L+(W-PAD_L-PAD_R)*i/Math.max(1,n-1);}};
  var lo=Math.max(50,Math.min.apply(null,va)*0.9), hi=Math.max(200,Math.max.apply(null,va));
  var lmin=Math.log(lo), lmax=Math.log(hi);
  var y=function(v){{return PAD_T+(H-PAD_T-PAD_B)*(1-(Math.log(v)-lmin)/(lmax-lmin));}};
  function tickLabel(v){{if(v>=1000)return (v/1000).toFixed(0)+'k';return String(v);}}
  var g='';
  for(var t=100;t<=hi*1.02;t*=2){{if(t<lo*0.95)continue;
    g+='<line x1="'+PAD_L+'" y1="'+y(t)+'" x2="'+(W-PAD_R)+'" y2="'+y(t)+'" stroke="rgba(128,128,128,.15)"/>';
    g+='<text x="'+(PAD_L-8)+'" y="'+(y(t)+4)+'" font-size="12" fill="#9ca3af" text-anchor="end">'+tickLabel(t)+'</text>';}}
  var prevYr=null;
  for(var i=0;i<n;i++){{var yr=2016+Math.floor(i/252);
    if(yr!==prevYr){{g+='<text x="'+x(i)+'" y="'+(H-PAD_B+18)+'" font-size="13" fill="#9ca3af" text-anchor="middle">'+yr+'</text>';prevYr=yr;}}}}
  var pts='';
  for(var i=0;i<va.length;i+=3){{pts+=x(i).toFixed(1)+','+y(va[i]).toFixed(1)+' ';}}
  el.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto">'+g+
    '<polyline points="'+pts+'" fill="none" stroke="#f59e0b" stroke-width="2.5"/>'+
    '<text x="'+(PAD_L+10)+'" y="'+(PAD_T+18)+'" font-size="13" fill="#f59e0b">普适版 → +'+S.v9_auto.summary.total_return_pct+'%</text>'+
    '<text x="'+(W-PAD_R-6)+'" y="'+(PAD_T+8)+'" font-size="11" fill="#9ca3af" text-anchor="end">对数坐标 · 净值(100起)</text></svg>';
}}
function renderCurveLite(){{
  var el=document.getElementById('curve-chart-lite');if(!el)return;
  var S=window.ENH.systems;if(!S)return;
  var vl=S.v8_lite.equity;
  var n=vl.length,W=1400,H=300,PAD_L=70,PAD_R=20,PAD_T=26,PAD_B=34;
  var x=function(i){{return PAD_L+(W-PAD_L-PAD_R)*i/Math.max(1,n-1);}};
  var lo=Math.max(50,Math.min.apply(null,vl)*0.9), hi=Math.max(200,Math.max.apply(null,vl));
  var lmin=Math.log(lo), lmax=Math.log(hi);
  var y=function(v){{return PAD_T+(H-PAD_T-PAD_B)*(1-(Math.log(v)-lmin)/(lmax-lmin));}};
  function tickLabel(v){{if(v>=1000)return (v/1000).toFixed(1)+'k';return String(v);}}
  var g='';
  for(var t=100;t<=hi*1.02;t*=2){{if(t<lo*0.95)continue;
    g+='<line x1="'+PAD_L+'" y1="'+y(t)+'" x2="'+(W-PAD_R)+'" y2="'+y(t)+'" stroke="rgba(128,128,128,.15)"/>';
    g+='<text x="'+(PAD_L-8)+'" y="'+(y(t)+4)+'" font-size="12" fill="#9ca3af" text-anchor="end">'+tickLabel(t)+'</text>';}}
  var prevYr=null;
  for(var i=0;i<n;i++){{var yr=2016+Math.floor(i/252);
    if(yr!==prevYr){{g+='<text x="'+x(i)+'" y="'+(H-PAD_B+18)+'" font-size="13" fill="#9ca3af" text-anchor="middle">'+yr+'</text>';prevYr=yr;}}}}
  var pts='';
  for(var i=0;i<vl.length;i+=3){{pts+=x(i).toFixed(1)+','+y(vl[i]).toFixed(1)+' ';}}
  el.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto">'+g+
    '<polyline points="'+pts+'" fill="none" stroke="#3b82f6" stroke-width="2"/>'+
    '<text x="'+(PAD_L+10)+'" y="'+(PAD_T+18)+'" font-size="13" fill="#3b82f6">个人版 → +'+S.v8_lite.summary.total_return_pct+'%</text>'+
    '<text x="'+(W-PAD_R-6)+'" y="'+(PAD_T+8)+'" font-size="11" fill="#9ca3af" text-anchor="end">对数坐标 · 净值(100起)</text></svg>';
}}
document.addEventListener('DOMContentLoaded',function(){{
  renderCurveAuto();renderCurveLite();
}});
</script>
</body></html>"""

out = BASE / "dual_system.html"
out.write_text(html, encoding="utf-8")
print(f"监控看板已生成: {out} ({out.stat().st_size/1024:.0f} KB)")
print(f"  普适版表: {len(v9_items)} 只 | 个人版表: {len(v8_items)} 只（股票{len(v8_main)}/ETF{len(v8_etf)}/基金{len(v8_fund)}）")
