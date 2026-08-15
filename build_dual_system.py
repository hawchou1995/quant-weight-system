# -*- coding: utf-8 -*-
"""标的监控看板（双体系·模板风格）：监控总览 / 全量池中长线 / 固定池中长线 / 短线占位。
每视图 = KPI 卡 + 标的汇总表（模板列：分数构成/超买分解/量能分解/置信度/档位变化）
       + 紧跟其下的逐标的详情卡片（六角雷达图 + 六类分数 + 回测），v8/v9 池分开。
右上角「标的报告」= 按月分类的历史收盘监控快照（当前页内切换，不新开窗口）；
左侧导航无独立标的报告入口（同页处理）；左上角板块/行业/档位 select 筛选；
全量池自动池 = 股票按权限各10 + ETF10 + 基金10；回测参考统一放监控总览。"""
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
# 短线信号池（v5.10）：全市场最新交易日短线分 Top 池（股票反转10 + ETF动量10 + 基金动量10）
try:
    _sp_js = open(BASE / "short_pool.js", encoding="utf-8").read()
    SHORT_POOL = json.loads(_sp_js[len("window.SHORT_POOL = "):-1])
    _sp_items = []
    for _grp in ("股票", "ETF", "基金"):
        for _c in SHORT_POOL["tiers"].get(_grp, []):
            _d = SHORT_POOL["details"].get(_c)
            if _d:
                _row = dict(_d)
                _row["score"] = _d["short_score"]
                _row["tier"] = _d["short_tier"]
                _row["is_short"] = True
                _sp_items.append(_row)
    v9_short_items = _sp_items
    SHORT_POOL_ASOF = SHORT_POOL.get("as_of", "—")
except Exception as _e:
    print("short_pool 加载失败:", _e)
    v9_short_items = []
    SHORT_POOL_ASOF = "—"
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
# ETF/基金独立回测（v5.9：ETF 升级 v3 月频+MA5；基金维持混合版）
s_etf = json.load(open(BASE / "etf_v3_final_summary.json", encoding="utf-8"))["summary"]
ETF_TAG = json.load(open(BASE / "etf_v3_final_summary.json", encoding="utf-8"))["params"]
s_fund = json.load(open(BASE / "v8_fund_summary.json", encoding="utf-8"))["summary"]

def load_curve_norm(f):
    try:
        df = __import__("pandas").read_csv(BASE / f)
        v = df["value"].astype(float).values
        return [round(float(x), 2) for x in (v / v[0] * 100)]
    except Exception:
        return []

v_etf = load_curve_norm("etf_v3_final_equity.csv")
v_fund = load_curve_norm("v8_fund_equity.csv")
# 短线净值曲线（短线体系 v3 最优）
v_short_etf = load_curve_norm("short_v3_etf_equity.csv")
v_short_fund = load_curve_norm("short_v3_fund_equity.csv")
v_short_stock = load_curve_norm("short_v3_stock_equity.csv")
# 分层净值曲线（v5.9：中长线 v9split + 短线 shortsplit，按权限互斥）
_SPLIT_GROUPS = ["all", "main_only", "gem_only", "star_only"]
v9split_curves = {g: load_curve_norm(f"v9split_{g}_equity.csv") for g in _SPLIT_GROUPS}
shortsplit_curves = {g: load_curve_norm(f"shortsplit_{g}_equity.csv") for g in _SPLIT_GROUPS}
# 短线 v3 最优 summary（看板 KPI 卡读这里，不再用穷举中间结果）
ss_stock = json.load(open(BASE / "short_v3_stock_summary.json", encoding="utf-8"))["summary"]
ss_etf = json.load(open(BASE / "short_v3_etf_summary.json", encoding="utf-8"))["summary"]
ss_fund = json.load(open(BASE / "short_v3_fund_summary.json", encoding="utf-8"))["summary"]
ss_stock_tag = json.load(open(BASE / "short_v3_stock_summary.json", encoding="utf-8"))["params"]
ss_etf_tag = json.load(open(BASE / "short_v3_etf_summary.json", encoding="utf-8"))["params"]
ss_fund_tag = json.load(open(BASE / "short_v3_fund_summary.json", encoding="utf-8"))["params"]


# ---- v5.9 分层回测（股票按权限互斥：一体/主板/创业板/科创板）----
def _load_summary(f):
    try:
        d = json.load(open(BASE / f, encoding="utf-8"))
        return d.get("summary", {}), d.get("label", ""), d.get("params", "")
    except Exception:
        return {}, "", ""


_STK_GROUPS = [
    ("all", "股票一体 · 全A", "v9split_all", "shortsplit_all"),
    ("main", "纯主板", "v9split_main_only", "shortsplit_main_only"),
    ("gem", "纯创业板", "v9split_gem_only", "shortsplit_gem_only"),
    ("star", "纯科创板", "v9split_star_only", "shortsplit_star_only"),
]
# 中长线分层 summary
s_stk = {}
stk_tag = {}
for g, label, v9f, _sf in _STK_GROUPS:
    s, lbl, tag = _load_summary(v9f + "_summary.json")
    s_stk[g] = s
    stk_tag[g] = tag or label
# 短线分层 summary
ss_stk = {}
ss_stk_tag = {}
for g, label, _v9f, sf in _STK_GROUPS:
    s, lbl, tag = _load_summary(sf + "_summary.json")
    ss_stk[g] = s
    ss_stk_tag[g] = tag or label


def bt_card(cid, title, tag, s, curve_id, color="#f59e0b", sub="2016-01~2026-08"):
    """回测 KPI 卡（收益/年化/回撤·夏普 + 净值曲线容器）"""
    if not s:
        return f'<div class="bt-card" id="{cid}"><div class="bt-head"><b>{title}</b><span class="bt-tag">{tag}</span></div><div class="kpis"><div class="kpi"><div class="l">回测收益</div><div class="v">—</div><div class="s">回测中…</div></div></div><div class="bt-curve" id="{curve_id}"></div></div>'
    return f'''<div class="bt-card" id="{cid}">
<div class="bt-head"><b>{title}</b><span class="bt-tag">{tag}</span></div>
<div class="kpis">
<div class="kpi"><div class="l">回测收益</div><div class="v" style="color:{color}">+{s["total_return_pct"]:.1f}%</div><div class="s">{sub}</div></div>
<div class="kpi"><div class="l">年化</div><div class="v">{s["annual_return_pct"]:.1f}%</div><div class="s">胜率 {s.get("win_rate_pct",0):.0f}%</div></div>
<div class="kpi"><div class="l">最大回撤</div><div class="v" style="color:#ef4444">{s["max_drawdown_pct"]:.1f}%</div><div class="s">夏普 {s["sharpe"]:.2f} · {s.get("total_trades",0)} 笔</div></div>
</div>
<div class="bt-curve" id="{curve_id}"></div>
</div>'''


def bt_all_html():
    """中长线回测参考 6 卡（股票分层 4 + ETF + 基金）"""
    cards = "".join([
        bt_card("bt-stock-all", "📈 股票 一体（全A）", stk_tag["all"], s_stk["all"], "curve-chart-stock-all"),
        bt_card("bt-stock-main", "📈 股票 纯主板", stk_tag["main"], s_stk["main"], "curve-chart-stock-main"),
        bt_card("bt-stock-gem", "📈 股票 纯创业板", stk_tag["gem"], s_stk["gem"], "curve-chart-stock-gem"),
        bt_card("bt-stock-star", "📈 股票 纯科创板", stk_tag["star"], s_stk["star"], "curve-chart-stock-star"),
        bt_card("bt-etf", "🟠 ETF 池", ETF_TAG, s_etf, "curve-chart-etf"),
        bt_card("bt-fund", "🔵 基金池", "净值动量轮动", s_fund, "curve-chart-fund", color="#3b82f6"),
    ])
    return ('<div class="card" id="bt-all">\n'
            '<h2>📊 回测参考 <span class="badge badge-auto">中/长线 · 股票按权限分层</span></h2>\n'
            '<div class="sub">股票 = 绝对规则筛池 Top3 · 月轮动 · 按权限<b>互斥分层</b>（一体/纯主板/纯创业板/纯科创板，各池独立回测）｜ ETF = 动量轮动 ｜ 基金 = 净值动量轮动 —— 各池严格分开</div>\n'
            '<div class="bt-grid">' + cards + '</div>\n</div>')


def bt_short_html():
    """短线回测参考 6 卡（股票分层 4 + ETF + 基金）"""
    cards = "".join([
        bt_card("bt-short-stock-all", "📈 短线 股票 一体", ss_stk_tag["all"], ss_stk["all"], "curve-short-stock-all"),
        bt_card("bt-short-stock-main", "📈 短线 纯主板", ss_stk_tag["main"], ss_stk["main"], "curve-short-stock-main"),
        bt_card("bt-short-stock-gem", "📈 短线 纯创业板", ss_stk_tag["gem"], ss_stk["gem"], "curve-short-stock-gem"),
        bt_card("bt-short-stock-star", "📈 短线 纯科创板", ss_stk_tag["star"], ss_stk["star"], "curve-short-stock-star"),
        bt_card("bt-short-etf", "🟠 短线 ETF", ss_etf_tag, ss_etf, "curve-short-etf"),
        bt_card("bt-short-fund", "🔵 短线 基金", ss_fund_tag, ss_fund, "curve-short-fund", color="#3b82f6"),
    ])
    return ('<div class="card" id="bt-short">\n'
            '<h2>⚡ 短线回测参考 <span class="badge badge-auto">全量池短线 · 股票按权限分层</span></h2>\n'
            '<div class="sub">短线 = 动量30/量价25/通道25/波动20（A 股个股反转版）+ <b>MA5 生命线每日止损</b> + 强势市门控 · 股票按权限<b>互斥分层</b>（各池独立回测）｜ ETF/基金 = 动量短线 —— 与中长线独立，监控表「⚡ 全量池短线」视图对应此池</div>\n'
            '<div class="bt-grid">' + cards + '</div>\n</div>')
perm_stat = f'股票 {len(v8_main)} ｜ ETF {len(v8_etf)} ｜ 基金 {len(v8_fund)}'

def system_block(vid, sid, title, badge, sub, items, tbl_id, card_id, note, extra_stat=None, extra_card=""):
    """每个系统的完整区块：系统头（标题+说明）+ 操作统计条 + 汇总表 + 详情卡片
    回测参考统一放总览视图，这里只保留监控主体。extra_card=视图末尾追加卡片（如持仓跟踪）"""
    up, down = updown(items)
    t8 = tier_counts(items)
    stat_bar = (extra_stat if extra_stat else "") + f'''<div class="op-stats">
<span class="op op-add">🟢 加仓区 <b>{t8.get("满仓加仓",0)+t8.get("轻仓加仓",0)}</b> 只</span>
<span class="op op-watch">🟡 观望 <b>{t8.get("观望",0)}</b> 只</span>
<span class="op op-cut">🔴 减/清仓区 <b>{t8.get("减至半仓",0)+t8.get("清仓",0)}</b> 只</span>
</div>'''
    return f'''<div class="view" id="{vid}">
<div class="card" id="{sid}">
<h2>{title} <span class="view-badge {badge}">{sub}</span></h2>
{stat_bar}
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
<th data-key="rank" style="text-align:center">#</th><th data-key="name">标的</th><th data-key="board">板块</th><th data-key="industry">行业</th><th data-key="px" style="text-align:right">现价</th>
<th data-key="chg" style="text-align:right">涨跌幅</th><th data-key="ret1y" style="text-align:right">近一年</th><th data-key="score" style="text-align:center">权重分<div class="th-sub">趋势/动量/量能/超买/风控</div></th><th data-key="rsi" style="text-align:center">RSI</th><th data-key="vp" style="text-align:center">量能</th>
<th data-key="conf" style="text-align:center">置信度</th><th data-key="tier" style="text-align:center">档位</th><th data-key="tierchg" style="text-align:center">档位变化</th><th data-key="action" style="text-align:center">建议动作</th>
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
{extra_card}
</div>'''


WATCH_CARD = f'''<div class="card" id="watch-card">
<h2>🔎 我的持仓跟踪 <span class="badge badge-auto">与回测同口径</span></h2>
<div class="sub">卖出规则（与回测一致）：<b>收盘跌破 MA5 → 次日开盘卖出</b> ｜ 掉出信号池 → 下次轮动换出（约 10 个交易日）｜ 档位减半/清仓 → 按档位操作 · 数据截至 {SHORT_POOL_ASOF} · 每天收盘后跑 refresh_daily.py 刷新</div>
<div class="watch-bar">
<input type="text" id="watch-input" placeholder="持仓代码，逗号分隔，如：600641, 159502, 000742">
<button id="watch-save">💾 保存持仓</button>
<span class="count" id="watch-count"></span>
</div>
<div id="watch-table"></div>
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
/* 表头两行（权重分/构成第二行指标名） */
.th-sub{{font-size:10px;color:var(--faint);font-weight:400;margin-top:2px}}
/* 到顶/到底浮动按钮 */
.scroll-fab{{position:fixed;right:22px;bottom:22px;display:flex;flex-direction:column;gap:8px;z-index:950}}
.scroll-fab button{{width:40px;height:40px;border-radius:50%;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:16px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.15);font-family:inherit}}
.scroll-fab button:hover{{border-color:var(--accent);color:var(--accent)}}
/* ETF/基金回测参考 · 三池独立大卡 */
.bt-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}
.bt-card{{background:var(--card2);border:1px solid var(--border);border-radius:14px;padding:16px}}
.bt-card .bt-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;font-size:15px}}
.bt-card .bt-tag{{font-size:11px;color:var(--faint);background:var(--card);border:1px solid var(--border);border-radius:20px;padding:2px 10px}}
.bt-card .bt-curve{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:6px;margin-top:10px}}
/* 持仓跟踪 */
.watch-bar{{display:flex;gap:10px;align-items:center;margin-bottom:12px}}
.watch-bar input{{flex:1;background:var(--card2);border:1px solid var(--border);color:var(--text);border-radius:10px;padding:8px 12px;font-size:13px;font-family:inherit}}
.watch-bar button{{background:var(--accent);border:none;color:#fff;border-radius:10px;padding:8px 16px;font-size:13px;cursor:pointer;font-family:inherit}}
.watch-bar .count{{color:var(--faint);font-size:12px}}
#watch-table .up{{color:#22c55e}} #watch-table .down{{color:#ef4444}} #watch-table .warn{{color:#f59e0b}}
.bt-short{{background:var(--card2);border:1px dashed var(--border);border-radius:14px;padding:22px;text-align:center;margin-top:16px}}
.bt-short h3{{margin:0 0 8px;color:var(--sub);font-size:15px}}
.bt-short .sub{{color:var(--faint);font-size:12px;line-height:1.8}}
/* 大卡片折叠 */
.card{{transition:box-shadow .15s}}
.card .card-h{{display:flex;align-items:center;gap:10px;cursor:pointer;user-select:none}}
.card .card-h:hover{{color:var(--accent)}}
.card .fold-arrow{{margin-left:auto;font-size:12px;color:var(--faint);flex:0 0 auto}}
.card .card-body{{margin-top:12px}}
.card.collapsed .card-body{{display:none}}
.card.collapsed .fold-arrow{{transform:rotate(-90deg);display:inline-block}}
/* 操作统计条（各系统视图） */
.op-stats{{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}}
.op{{font-size:13px;padding:6px 14px;border-radius:20px;background:var(--card2);border:1px solid var(--border)}}
.op b{{font-size:15px}}
.op-add{{color:var(--up)}}
.op-watch{{color:#d97706}}
.op-cut{{color:var(--down)}}
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
<div class="sub">左侧导航切换：🅰️ 全量池中/长线（全市场自动池·股票分层+ETF+基金） / 🅱️ 固定池中/长线（用户固定池） / ⚡ 短线（占位） · 右上角「标的报告」按月查看历史收盘快照 · 信号仅供参考</div>
<div class="kpis">
<div class="kpi"><div class="l">🟢 加仓区</div><div class="v" style="color:#dc2626">{sum(1 for d in all_items if d["tier"] in ("满仓加仓","轻仓加仓"))} 只</div><div class="s">满仓+轻仓加仓</div></div>
<div class="kpi"><div class="l">🟡 观望区</div><div class="v" style="color:#d97706">{sum(1 for d in all_items if d["tier"]=="观望")} 只</div><div class="s">持有不加</div></div>
<div class="kpi"><div class="l">🔴 减/清仓区</div><div class="v" style="color:#16a34a">{sum(1 for d in all_items if d["tier"] in ("减至半仓","清仓"))} 只</div><div class="s">减半或清仓</div></div>
<div class="kpi"><div class="l">共监控</div><div class="v">{len(all_items)} 只</div><div class="s">全量池 {len(v9_items)} 行 + 固定池 {len(v8_items)} 只</div></div>
</div>
<div class="rule-box" style="margin-bottom:0"><b>监控口径</b>：权重分 = 动量35% + 趋势25% + Aroon20% + 量价20% ｜ 档位 = ≥75 满仓加仓 / ≥60 轻仓加仓 / ≥45 观望 / ≥30 减半 / &lt;30 清仓
<br><b>卖出闸门（每日）</b>：全量池 移动止损 4.5% + 沪深300破MA150 ｜ 固定池 移动止损 10% + 破MA200 ｜ 任何闸门先触发先生效
<br><b>历史快照</b>：右上角「标的报告」按月分类，点击当前页切换查看（不新开窗口）</div>
</div>
{bt_all_html()}
{bt_short_html()}
</div>
<!-- ============ 视图 A：全量池中/长线 ============ -->
{system_block(
  "view-auto", "sys-auto",
  "🅰️ 全量池中/长线", "auto", "全市场自动池 · 股票分层+ETF+基金 ｜ 全市场绝对规则筛池 Top3 等权 · 月轮动 · 移动止损4.5% · MA150择时 ｜ 回测参考见「监控总览」",
  v9_items, "tbl-v9", "card-tbl-v9",
  "档位变化对比上次再平衡（07-23）· 建议动作 = 当前档位下的操作指引 · 回测参考在监控总览视图")}

<!-- ============ 视图 B：固定池中/长线 ============ -->
{system_block(
  "view-lite", "sys-lite",
  "🅱️ 固定池中/长线", "lite", f"用户固定池 · 股票+ETF+基金 ｜ 四因子打分 Top4 · 月轮动21日 · 移动止损10% · MA200择时 ｜ 池构成：{perm_stat} ｜ 回测参考见「监控总览」",
  v8_items, "tbl-v8", "card-tbl-v8",
  "档位变化对比上次再平衡（07-23）· 建议动作 = 当前档位下的操作指引 · 回测参考在监控总览视图")}

<!-- ============ 视图 C：全量池短线（与中长线同结构：统计条+表格+雷达卡） ============ -->
{system_block(
  "view-short", "sys-short",
  "⚡ 全量池短线", "auto", f"全市场短线信号 Top 池（数据截至 {SHORT_POOL_ASOF}）：股票=反转信号 Top10（剔ST）｜ ETF=动量 Top10 ｜ 基金=动量 Top10 · 短线分 = 动量30/量价25/通道25/波动20 · 回测参考见「监控总览」",
  v9_short_items, "tbl-short", "card-tbl-short",
  "短线分 = 动量30 + 量价25 + 通道25 + 波动20（A 股个股反转版）· 档位与中长线同口径 · 回测参考在监控总览视图",
  extra_card=WATCH_CARD)}

<!-- ============ 历史快照视图（右上角标的报告切换） ============ -->
<div class="view" id="view-snapshot">
<div class="card" id="snap-holder">
<h2>📅 历史收盘监控快照</h2>
<div class="sub" id="snap-title"></div>
<div id="snap-content"></div>
</div>
</div>

</div>
<!-- 到顶/到底浮动按钮 -->
<div class="scroll-fab">
<button title="回到顶部" onclick="window.scrollTo({{top:0,behavior:'smooth'}})">↑</button>
<button title="滚到底部" onclick="window.scrollTo({{top:document.body.scrollHeight,behavior:'smooth'}})">↓</button>
</div>
<script src="enhanced_data.js"></script>
<script src="short_signals.js"></script>
<script src="monitor/snapshots_index.js"></script>
<script>
/* 三视图导航（覆盖默认 4 项） */
window.ENH.nav = [["overview","📊","监控总览"],["sys-auto","🅰️","全量池中/长线"],["sys-lite","🅱️","固定池中/长线"],["short","⚡","全量池短线"]];
/* 视图切换模式：滚动不更新导航高亮（COMMON_JS renderSidenav 检测此标志） */
window.ENH.NAV_SWITCH = true;
/* 三池回测净值（股票/ETF/基金，监控总览展示） */
window.ENH.sub_curves = {{
  stock: {json.dumps(DATA["systems"]["v9_auto"]["equity"])},
  etf: {json.dumps(v_etf)},
  fund: {json.dumps(v_fund)},
  short_etf: {json.dumps(v_short_etf)},
  short_fund: {json.dumps(v_short_fund)},
  short_stock: {json.dumps(v_short_stock)},
  stk_all: {json.dumps(v9split_curves["all"])}, stk_main: {json.dumps(v9split_curves["main_only"])},
  stk_gem: {json.dumps(v9split_curves["gem_only"])}, stk_star: {json.dumps(v9split_curves["star_only"])},
  sstk_all: {json.dumps(shortsplit_curves["all"])}, sstk_main: {json.dumps(shortsplit_curves["main_only"])},
  sstk_gem: {json.dumps(shortsplit_curves["gem_only"])}, sstk_star: {json.dumps(shortsplit_curves["star_only"])},
}};
/* 渲染 ETF/基金回测净值曲线（各自容器、各自对数坐标轴） */
function renderOneCurve(elId, vals, color, label, totalPct){{
  var el=document.getElementById(elId);if(!el)return;
  var n=vals.length,W=1400,H=240,PAD_L=70,PAD_R=20,PAD_T=22,PAD_B=28;
  var x=function(i){{return PAD_L+(W-PAD_L-PAD_R)*i/Math.max(1,n-1);}};
  var lo=Math.max(50,Math.min.apply(null,vals)*0.9), hi=Math.max(200,Math.max.apply(null,vals));
  var lmin=Math.log(lo),lmax=Math.log(hi);
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
  for(var i=0;i<vals.length;i+=3){{pts+=x(i).toFixed(1)+','+y(vals[i]).toFixed(1)+' ';}}
  el.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto">'+g+
    '<polyline points="'+pts+'" fill="none" stroke="'+color+'" stroke-width="2"/>'+
    '<text x="'+(PAD_L+10)+'" y="'+(PAD_T+16)+'" font-size="13" fill="'+color+'">'+label+' → +'+totalPct+'%</text>'+
    '<text x="'+(W-PAD_R-6)+'" y="'+(PAD_T+8)+'" font-size="11" fill="#9ca3af" text-anchor="end">对数坐标 · 净值(100起)</text></svg>';
}}
function renderSubCurve(){{
  var C=window.ENH.sub_curves;if(!C)return;
  renderOneCurve('curve-chart-stock-all', C.stk_all, '#f59e0b', '股票 一体', '+'+{round(s_stk["all"].get("total_return_pct") or 0):.0f});
  renderOneCurve('curve-chart-stock-main', C.stk_main, '#ea580c', '纯主板', '+'+{round(s_stk["main"].get("total_return_pct") or 0):.0f});
  renderOneCurve('curve-chart-stock-gem', C.stk_gem, '#22c55e', '纯创业板', '+'+{round(s_stk["gem"].get("total_return_pct") or 0):.0f});
  renderOneCurve('curve-chart-stock-star', C.stk_star, '#8b5cf6', '纯科创板', '+'+{round(s_stk["star"].get("total_return_pct") or 0):.0f});
  renderOneCurve('curve-chart-etf', C.etf, '#ea580c', 'ETF 池', '+'+{s_etf["total_return_pct"]:.0f});
  renderOneCurve('curve-chart-fund', C.fund, '#3b82f6', '基金池', '+'+{s_fund["total_return_pct"]:.0f});
  renderOneCurve('curve-short-stock-all', C.sstk_all, '#f59e0b', '短线 股票 一体', '+'+{round(ss_stk["all"].get("total_return_pct") or 0):.0f});
  renderOneCurve('curve-short-stock-main', C.sstk_main, '#ea580c', '短线 纯主板', '+'+{round(ss_stk["main"].get("total_return_pct") or 0):.0f});
  renderOneCurve('curve-short-stock-gem', C.sstk_gem, '#22c55e', '短线 纯创业板', '+'+{round(ss_stk["gem"].get("total_return_pct") or 0):.0f});
  renderOneCurve('curve-short-stock-star', C.sstk_star, '#8b5cf6', '短线 纯科创板', '+'+{round(ss_stk["star"].get("total_return_pct") or 0):.0f});
  renderOneCurve('curve-short-etf', C.short_etf, '#ea580c', 'ETF 短线', '+'+{ss_etf["total_return_pct"]:.0f});
  renderOneCurve('curve-short-fund', C.short_fund, '#3b82f6', '基金短线', '+'+{ss_fund["total_return_pct"]:.0f});
}}
/* 视图切换（hash 驱动：切换时更新 location.hash，加载/前进后退时按 hash 定位） */
var VIEW_MAP={{'overview':'view-overview','sys-auto':'view-auto','sys-lite':'view-lite','short':'view-short','snapshot':'view-snapshot'}};
function switchView(key){{
  var v=VIEW_MAP[key];if(!v)return;
  document.querySelectorAll('.view').forEach(function(x){{x.classList.remove('active');}});
  document.getElementById(v).classList.add('active');
  window.scrollTo(0,0);
  if(location.hash!=='#'+key)try{{history.replaceState(null,'','#'+key)}}catch(e){{}}
}}
function applyHash(){{
  var k=(location.hash||'').replace('#','');
  if(VIEW_MAP[k])switchView(k);
}}
window.addEventListener('hashchange',applyHash);
/* 右上角标的报告：按月分类历史快照（当前页内切换） */
function renderReportMenu(){{
  var m=document.getElementById('report-menu');if(!m)return;
  if(!window.SNAPSHOTS){{m.innerHTML='<div class="head">暂无历史快照</div>';return;}}
  var h='<div class="head">历史收盘监控快照（'+window.SNAPSHOTS.snapshots.length+' 份）</div>';
  h+='<a class="snap-item" style="font-weight:600;color:var(--accent)" href="history_reports.html">📚 历史报告总览（独立页）</a>';
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
  applyHash();   // 按 URL hash 定位视图（历史页跳转 dual_system.html#sys-auto 直接显示普适版）
  renderSubCurve();   // ETF/基金回测净值曲线
  renderReportMenu();
  /* 持仓跟踪：localStorage 存代码 → 查 SHORT_SIGNALS 渲染状态（卖出规则与回测一致） */
  function renderWatch(){{
    var box=document.getElementById('watch-table');if(!box)return;
    var codes=(localStorage.getItem('short_watchlist')||'').split(',').map(function(s){{return s.trim();}}).filter(Boolean);
    var S=window.SHORT_SIGNALS;if(!S){{box.innerHTML='<div class="sub">信号数据未加载（缺 short_signals.js）</div>';return;}}
    var topSet={{}};
    if(window.SHORT_POOL){{Object.keys(window.SHORT_POOL.tiers||{{}}).forEach(function(g){{(window.SHORT_POOL.tiers[g]||[]).forEach(function(c){{topSet[c]=1;}});}});}}
    var cnt=document.getElementById('watch-count');
    if(cnt)cnt.textContent='跟踪 '+codes.length+' 只';
    if(!codes.length){{box.innerHTML='<div class="sub" style="color:var(--faint)">未设置持仓 —— 在上方输入代码并保存，每天刷新后这里显示每只持仓的减仓/清仓信号</div>';return;}}
    var h='<table class="tbl"><thead><tr><th>代码</th><th>名称</th><th>类型</th><th style="text-align:right">现价</th><th style="text-align:right">涨跌</th><th style="text-align:center">短线分</th><th style="text-align:center">档位</th><th style="text-align:center">MA5</th><th style="text-align:center">建议动作</th></tr></thead><tbody>';
    codes.forEach(function(code){{
      var rec=null,grp='';
      ['stock','etf','fund'].forEach(function(g){{if(S[g]&&S[g][code]){{rec=S[g][code];grp=g;}}}});
      if(!rec){{h+='<tr><td>'+code+'</td><td colspan="8" style="color:var(--faint)">未找到该代码（检查输入 / 代码不在监控范围）</td></tr>';return;}}
      var act,actCls;
      if(rec.ma5_above===false){{act='⚠️ 次日卖出（破MA5）';actCls='down';}}
      else if(rec.tier==='清仓'){{act='🔴 清仓';actCls='down';}}
      else if(rec.tier==='减至半仓'){{act='🔴 减至半仓';actCls='down';}}
      else if(!topSet[code]){{act='🔄 下次轮动换出';actCls='warn';}}
      else if(rec.tier==='轻仓加仓'||rec.tier==='满仓加仓'){{act='✅ 继续持有';actCls='up';}}
      else {{act='🟡 观望（不补不加）';actCls='warn';}}
      var gName=grp==='stock'?'股票':(grp==='etf'?'ETF':'基金');
      h+='<tr><td>'+code+'</td><td>'+rec.name+'</td><td>'+gName+'</td><td style="text-align:right">'+rec.px+'</td><td style="text-align:right" class="'+(rec.chg>0?'up':'down')+'">'+(rec.chg>0?'+':'')+rec.chg+'%</td><td style="text-align:center">'+rec.score+'</td><td style="text-align:center">'+rec.tier+'</td><td style="text-align:center">'+(rec.ma5_above?'✅ 上方':'⚠️ 下方')+'</td><td style="text-align:center" class="'+actCls+'">'+act+'</td></tr>';
    }});
    h+='</tbody></table>';
    box.innerHTML=h;
  }}
  var ws=document.getElementById('watch-save');
  if(ws){{ws.addEventListener('click',function(){{localStorage.setItem('short_watchlist',document.getElementById('watch-input').value);renderWatch();}});}}
  var wi=document.getElementById('watch-input');
  if(wi)wi.addEventListener('keydown',function(e){{if(e.key==='Enter'&&ws)ws.click();}});
  renderWatch();
  /* 大卡片折叠：所有 .card 的标题可点击折叠/展开（.stock-card 小卡不受影响） */
  document.querySelectorAll('.card').forEach(function(card){{
    var h2=null;
    for(var i=0;i<card.children.length;i++){{if(card.children[i].tagName==='H2'){{h2=card.children[i];break;}}}}
    if(!h2)return;
    var body=document.createElement('div');body.className='card-body';
    var nodes=[];
    var nxt=h2.nextSibling;
    while(nxt){{nodes.push(nxt);nxt=nxt.nextSibling;}}
    nodes.forEach(function(n){{body.appendChild(n);}});
    var hb=document.createElement('div');hb.className='card-h';
    var arrow=document.createElement('span');arrow.className='fold-arrow';arrow.textContent='▼';
    h2.parentNode.insertBefore(hb,h2);
    hb.appendChild(h2);hb.appendChild(arrow);
    card.insertBefore(body,hb.nextSibling);
    hb.addEventListener('click',function(){{card.classList.toggle('collapsed');}});
  }});
  document.querySelectorAll('#sidenav a[data-anchor]').forEach(function(a){{
    a.addEventListener('click',function(e){{
      e.preventDefault();switchView(a.getAttribute('data-anchor'));
      document.querySelectorAll('#sidenav a[data-anchor]').forEach(function(x){{x.classList.toggle('active',x===a);}});}});
  }});
  initTable('tbl-v9', {{columns: {{rank:0, name:1, board:2, industry:3, px:4, chg:5, ret1y:6, score:7, rsi:8, vp:9, conf:10, tier:11, tierchg:12, action:13}}}});
  initTable('tbl-v8', {{columns: {{rank:0, name:1, board:2, industry:3, px:4, chg:5, ret1y:6, score:7, rsi:8, vp:9, conf:10, tier:11, tierchg:12, action:13}}}});
  initTable('tbl-short', {{columns: {{rank:0, name:1, board:2, industry:3, px:4, chg:5, ret1y:6, score:7, rsi:8, vp:9, conf:10, tier:11, tierchg:12, action:13}}}});
  /* 统一联动：搜索 + 板块/行业/档位筛选 → 表格行 + 详情卡片同步；排序后卡片重排 */
  ['tbl-v9','tbl-v8','tbl-short'].forEach(function(id){{
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
