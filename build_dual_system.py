# -*- coding: utf-8 -*-
"""标的监控看板（模板风格）：监控总览 / 全量池中长线 / 短线。
每视图 = KPI 卡 + 标的汇总表（模板列：分数构成/超买分解/量能分解/置信度/档位变化）
       + 紧跟其下的逐标的详情卡片（六角雷达图 + 六类分数 + 回测）。
左侧导航切换视图；左上角板块/行业/档位 select 筛选；
全量池自动池 = 股票按权限各10 + 基金10；回测参考统一放监控总览。
2026-08-21：固定池彻底去除（用户清仓全部自买股票），仅保留全量池+短线两体系。"""
import os
import json, re
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, str(BASE))
import v8_selector as V
sys.path.insert(0, str(BASE))
from ui_components import THEME_CSS, NAV_HTML, COMMON_JS

js_src = (BASE / "enhanced_data.js").read_text(encoding="utf-8")
DATA = json.loads(js_src[len("window.ENH = "):-1])
details = DATA["details"]
import datetime as _dt
build_ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")

# ---------------- 分池 ----------------
all_items = list(details.values())
# 2026-08-21 用户清仓全部自买股票 → 固定池彻底去除（MAIN_CODES=[]），v8_items 恒为空（保留变量兼容）
v8_items = sorted([d for d in all_items if d.get("pool", "v8") == "v8"], key=lambda d: -d["score"])
track_v9_len = len(DATA.get("track_v9", {}) or {})   # 中长线跟踪池规模（固定池已去除，仅全量池自动跟踪）
# 普适版：按权限分层表（main/gem/star/fund 各 10 行，同一标的多档出现属正常；2026-08-17 去 etf 层）
v9_tiers = DATA.get("meta", {}).get("v9_tiers", {})
v9_items = []
for tier, codes in v9_tiers.items():
    for c in codes:
        d = details.get(c)
        if d is None:
            continue
        row = dict(d)
        row["perm"] = tier          # 行级档位（main/gem/star/fund），覆盖数据默认
        v9_items.append(row)
v9_items.sort(key=lambda d: -d["score"])
# 短线信号池（v5.10）：全市场最新交易日短线分 Top 池（股票反转按权限各10【主板/创业板/科创板】 + 基金动量10；2026-08-17 去 ETF）
try:
    _sp_js = open(BASE / "short_pool.js", encoding="utf-8").read()
    SHORT_POOL = json.loads(_sp_js[len("window.SHORT_POOL = "):-1])
    _sp_items = []
    for _grp in ("主板", "创业板", "科创板", "基金"):
        for _c in SHORT_POOL["tiers"].get(_grp, []):
            _d = SHORT_POOL["details"].get(_c)
            if _d:
                _row = dict(_d)
                _row["score"] = _d["short_score"]
                _row["tier"] = _d["short_tier"]
                _row["is_short"] = True
                _sp_items.append(_row)
    v9_short_items = _sp_items
    # 2026-09-02 点2改造：主信号 top4 置顶 + 行级标签（主信号/候选·仅参考）
    _sel_meta = SHORT_POOL.get("sel_meta") or {}
    _top4_set = set(_sel_meta.get("top4", []))
    v9_short_items.sort(key=lambda d: (d.get("code") not in _top4_set, -d["score"]))
    # 2026-09-03 用户需求：短线池股票/基金分板块展示（基金 board=「基金」，股票=主板/创业板/科创板）
    v9_short_stock = [d for d in v9_short_items if d.get("board") != "基金"]
    v9_short_fund = [d for d in v9_short_items if d.get("board") == "基金"]
    SHORT_POOL_NOTE = _sel_meta.get("note", "")
    # 2026-09-02 KHunter 今日统计徽章（主信号/信号观察/卖出数——0 只主信号时前端仍有迹可循）
    # ⚠ 2026-09-03 双版本部署：A55 主卖出 + C50 参考卖出 并行展示（ver 字段来自 sel_meta.khunter）
    _kh_meta = (_sel_meta.get("khunter") or {})
    _kh_ver = _kh_meta.get("ver") or {}
    _kh_note = ""
    if _kh_meta.get("sig"):
        _kh_str = (f'{_kh_meta.get("buy_n", 0)} 只主信号 · {_kh_meta.get("watch_n", 0)} 只观察 · '
                   f'卖出 A{_kh_ver.get("sell_a", 55)} {len(_kh_meta.get("sell", []))}/C{_kh_ver.get("sell_c", 50)} {len(_kh_meta.get("sell_c", []))}')
    else:
        _kh_str = "信号层未启用"
    SHORT_KHUNTER_BADGE = (f'<span class="badge" style="background:rgba(37,99,235,.14);color:#60a5fa;" '
                           f'title="KHunter 15 策略命中 + 信号日 RSI&lt;分域阈值 + 收盘≥低价过滤(仅熊市) + 牛熊分域 = 主信号（事件独立，有信号即买）；'
                           f'信号观察 = 已命中但未触发；卖出 = 标准版分域（熊 RSI&gt;{_kh_ver.get("sell_a", 55)} / 牛 RSI&gt;{_kh_ver.get("sell_a_bull", 75)} / 弱牛 RSI&gt;{_kh_ver.get("sell_a_weak", 80)}）主信号 / 激进版 RSI&gt;{_kh_ver.get("sell_c", 50)} 参考（2026-09-03 牛熊分域 HYBRIDv2 + 09-04 弱牛域 OSL32：total 68.5%→80.0% 回撤不变）">'
                           f'KHunter 今日: {_kh_str}</span>')
    SHORT_POOL_ASOF = SHORT_POOL.get("as_of", "—")
    _mg = SHORT_POOL.get("market_gate") or {}
    _bear60 = bool(_mg.get("bear60"))
    # 2026-09-03 牛熊分域投产（HYBRIDv2 定稿）+ 2026-09-04 弱牛域专项投产：三态 regime 全开仓
    #   🐻 熊市(<MA60, osl35+low3+ob55) / 🌞 牛市(>MA20, osl30+无low+ob75) / 🌙 弱牛回调(MA20下/MA60上, osl32+无low+ob80)
    if _bear60:
        _kh_regime_txt, _kh_regime_color = "🐻 熊市（MA60 下 · osl35+low3+ob55 · 可买入）", "#1f8a4c"
    elif _mg.get("open"):
        _kh_regime_txt, _kh_regime_color = "🌞 牛市（MA20 上 · osl30+无low+ob75 · 可买入）", "#1f8a4c"
    else:
        _kh_regime_txt, _kh_regime_color = "🌙 弱牛回调（MA20 下/MA60 上 · osl32+无low+ob80 · 可买入）", "#b45309"
    SHORT_KHUNTER_BEAR = (f'<span class="badge badge-auto" style="background:{_kh_regime_color};color:#fff">'
                          f'KHunter 牛熊分域：{_kh_regime_txt}'
                          f'</span>')
    if _mg.get("open"):
        SHORT_POOL_GATE = f'<span class="badge badge-auto" style="background:#1f8a4c;color:#fff">市况门控 ✅ 开（{_mg.get("idx_close")} &gt; MA20 {_mg.get("idx_ma20")}）</span>'
    else:
        # 2026-08-20 用户决策：门控改为「仅提醒」——股票池分≥50 照常入池展示（供参考），不做买入指令
        # 2026-09-02 豁免：KHunter 主信号不受 MA20 门控（回测全窗口证据）→ 2026-09-03 牛熊分域接管（熊市全开/牛市>MA20 开）→ 2026-09-04 弱牛域投产三态全开
        SHORT_POOL_GATE = f'<span class="badge badge-auto" style="background:#d97706;color:#fff">市况门控 ⚠ 关 · 仅提醒（沪深300 {_mg.get("idx_close")} &lt; MA20 {_mg.get("idx_ma20")}；KHunter 由牛熊分域裁决，其余仅参考）</span>'
    SHORT_POOL_INTRADAY = SHORT_POOL.get("intraday_note") or ""
    SHORT_POOL_ASOF_MIN = SHORT_POOL.get("intraday_ts") or "15:00"
    # 运行时精简池数据（tiers/track 供「全量池短线跟踪」渲染；HTML 不加载 short_pool.js）
    SHORT_POOL_SLIM = json.dumps(
        {k: SHORT_POOL.get(k) for k in ("as_of", "fund_as_of", "tiers", "track", "track_pending_short", "market_gate", "sel_meta")},
        ensure_ascii=False)
except Exception as _e:
    print("short_pool 加载失败:", _e)
    v9_short_items = []
    v9_short_stock = []
    v9_short_fund = []
    SHORT_POOL_ASOF = "—"
    SHORT_POOL_INTRADAY = ""
    SHORT_POOL_ASOF_MIN = "15:00"
    SHORT_POOL_SLIM = '{}'
    SHORT_POOL_GATE = ''
    SHORT_POOL_NOTE = ''
    SHORT_KHUNTER_BEAR = ''
# A5_tp8t2 打板实验系统（第三个系统，2026-08-28 接入；数据由 build_a5_pool.py 生成）
try:
    _a5_js = open(BASE / "a5_pool.js", encoding="utf-8").read()
    A5 = json.loads(_a5_js[len("window.A5_POOL = "):-1])
    A5_ASOF = A5.get("as_of", "—")
    A5_GATE = A5.get("gate", {})
    A5_STATS = A5.get("stats", {})
except Exception as _e:
    print("a5_pool 加载失败:", _e)
    A5 = {"watchlist": [], "avoid": [], "positions": [], "closed": [], "stats": {},
          "gate": {"verdict": "数据未生成（先运行 build_a5_pool.py）"}, "bench": {},
          "backtest": {}, "equity": []}
    A5_ASOF = "—"
    A5_GATE = {}
    A5_STATS = {}
# 2026-08-21 固定池已去除，v8_main/v8_etf/v8_fund 不再使用

# 中长线 MA200 市况门控徽章（2026-08-19：与回测口径 use_timing=True/MA200 一致；沪深300<MA200 → 熊市保护，不回补新仓）
try:
    _idx_lt = V.load_index(200)
    _lt_close = float(_idx_lt["close"].iloc[-1]); _lt_ma = float(_idx_lt["ma"].iloc[-1])
    if _lt_close > _lt_ma:
        LT_GATE_BADGE = f'<span class="badge badge-auto" style="background:#1f8a4c;color:#fff">市况门控 ✅ 开（沪深300 {_lt_close:.0f} &gt; MA200 {_lt_ma:.0f}）</span>'
    else:
        # 2026-08-20 用户决策：门控改为「仅提醒」——权重分达标照常入池供参考，非买入指令
        LT_GATE_BADGE = f'<span class="badge badge-auto" style="background:#d97706;color:#fff">市况门控 ⚠ 关 · 仅提醒（沪深300 {_lt_close:.0f} &lt; MA200 {_lt_ma:.0f}，权重分达标照常展示，仅供参考）</span>'
except Exception as _e:
    print("MA200 门控徽章计算失败:", _e)
    LT_GATE_BADGE = ''

def tier_counts(items):
    cnt = {}
    for d in items:
        cnt[d["tier"]] = cnt.get(d["tier"], 0) + 1
    return cnt

def updown(items, add=("满仓加仓", "轻仓加仓"), cut=("减至半仓", "清仓")):
    up = sum(1 for d in items if d["tier"] in add)
    down = sum(1 for d in items if d["tier"] in cut)
    return up, down

# ---------------- 工具 ----------------
TIER_W = {"满仓加仓": 5, "强买入": 5, "动量强": 5, "轻仓加仓": 4, "买入": 4, "观望": 3, "动量中": 3,
          "减至半仓": 2, "动量弱": 2, "清仓": 1, "动量极弱": 1, "不买": 0}

def tier_pill(t):
    cls = {"满仓加仓": "pill-full", "强买入": "pill-full", "动量强": "pill-full", "轻仓加仓": "pill-add", "买入": "pill-add",
           "观望": "pill-watch", "动量中": "pill-watch", "减至半仓": "pill-cut", "动量弱": "pill-cut",
           "清仓": "pill-clear", "动量极弱": "pill-clear", "不买": "pill-watch"}.get(t, "pill-watch")
    return f'<span class="pill {cls}">{t}</span>'

def action_for(d):
    if d["tier"] == "动量强": return "动量强（池内优选）"
    if d["tier"] == "动量中": return "动量中（持有观察）"
    if d["tier"] == "动量弱": return "动量弱（关注轮出）"
    if d["tier"] == "动量极弱": return "动量极弱（或轮出）"
    if d["tier"] in ("满仓加仓",): return "持有至目标仓位"
    if d["tier"] == "轻仓加仓": return "可加至目标仓位"
    if d["tier"] == "观望": return "持有不加 / 观望"
    if d["tier"] == "减至半仓": return "减至半仓"
    if d["tier"] == "强买入": return "买入（强信号）"
    if d["tier"] == "买入": return "买入"
    if d["tier"] == "不买": return "不买入"
    return "清仓离场"

def conf_level(d):
    """置信度：覆盖率 ≥80% 且方向一致率 ≥75% 高 / <60% 低 / 其余中（模板口径近似）"""
    return "高"   # 当前体系无独立置信度，统一标"高"（模板口径需全维度数据）

def _bare(code):
    """六位代码统一（2026-09-05 用户需求：所有标的显示六位代码，去 sh/sz 前缀）"""
    c = str(code or "")
    return c[-6:] if len(c) > 6 else c


def _board_cell(v, ind=None):
    """市场板块徽章（统一标准：主板/创业板/科创板/北交所）；行业放入悬浮提示"""
    if not v or v == "—":
        return '<span style="color:var(--faint)">—</span>'
    cls = {"主板": "board-sh", "创业板": "board-cy", "科创板": "board-kc", "北交所": "board-bj"}.get(v, "")
    tip = f' title="行业：{ind}"' if ind else ""
    return f'<span class="board-tag {cls}"{tip}>{v}</span>'


def _perm_cell(code):
    """交易权限徽章（2026-09-05 用户需求：区分权限=开通门槛）：
    主板无门槛 / 创业板 2年+10万 / 科创板 2年+50万 / 北交所 2年+50万"""
    c = _bare(code)
    if c.startswith("688"):
        return '<span class="board-tag board-kc" title="科创板：需 2 年交易经验 + 50 万资产">2年+50万</span>'
    if c.startswith("30"):
        return '<span class="board-tag board-cy" title="创业板：需 2 年交易经验 + 10 万资产">2年+10万</span>'
    if c.startswith(("8", "4", "92")):
        return '<span class="board-tag board-bj" title="北交所：需 2 年交易经验 + 50 万资产">2年+50万</span>'
    return '<span class="board-tag board-sh" title="主板/ETF/基金：无开通门槛">无门槛</span>'


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
        # 开盘跳空高开规避（2026-08-17 用户需求）：盘中 patch 写入 gap（开盘 vs 昨收），>3% 不追高，
        # 可等盘中回落至 3% 以内再考虑买入
        gap_badge = ""
        if d.get("gap") is not None and d["gap"] > 3:
            gap_badge = (f'<span class="badge" style="background:rgba(239,68,68,.15);color:#f87171;" '
                         f'title="开盘跳空高开 {d["gap"]:.1f}%（vs 昨收），反转空间被开盘吃掉，不追高；可等盘中回落至 3% 以内再考虑买入">'
                         f'⚠ 高开{d["gap"]:.1f}% 规避（回落&lt;3%可买）</span>')
        # 2026-08-20 用户决策：市况门控改为「仅提醒」——门控关闭时入池股票标「仅提醒·非买入」，
        # 仅供参考（不追高）；与 8/19 跟踪池安全口径（不开新仓·仅跟踪）区分开（两者都非买入指令）
        gate_tag = ""
        if d.get("gate_closed"):
            gate_tag = ('<span class="badge" style="background:rgba(217,119,6,.18);color:#fbbf24;" '
                        f'title="市况门控关闭：权重分≥50 照常入池仅供参考，非买入指令；不追高，持仓走跟踪池等卖出信号">仅提醒·非买入</span>')
        # 2026-09-02 用户拍板：主信号=KHunter 主板信号（+RSI<35）；旧战法候选已全量删除（弃用）
        pick_tag = ""
        if d.get("pick") == "top4":
            pick_tag = ('<span class="badge" style="background:rgba(37,99,235,.16);color:#60a5fa;" '
                        f'title="KHunter 主信号：15 策略命中 + 信号日 RSI&lt;35 超卖（主板限定，事件独立，有信号即买）">'
                        f'🎯 KHunter 主信号</span>')
        rows += f'''<tr data-code="{d["code"]}" data-search="{d["name"]} {_bare(d["code"])} {d["industry"]} {board}" data-board="{d["perm"]}" data-market="{board}" data-industry="{d["industry"]}" data-tier="{d["tier"]}" data-pick="{d.get("pick") or ""}">
<td style="text-align:center">{rank}</td>
<td><b>{d["name"]}</b>{pick_tag}<br><span style="color:var(--faint);font-size:11px">{_bare(d["code"])}</span></td>
<td>{_board_cell(board, d.get("industry"))}</td>
<td>{_perm_cell(d["code"])}</td>
<td><span class="board-tag">{d["industry"]}</span></td>
<td style="text-align:right" data-v="{d["px"]}">{d["px"]:.2f}</td>
<td style="text-align:right" class="{chg_cls}" data-v="{d["chg"] or 0}">{chg_txt}</td>
<td style="text-align:right" class="{ret_cls}" data-v="{d["ret_1y"] or 0}">{ret_txt}</td>
<td style="text-align:center"><b>{d["score"]:.1f}</b><br><span style="color:var(--faint);font-size:10px" title="趋势/动量/量能/超买/风控">{comp_txt}</span></td>
<td style="text-align:center;font-size:11px;color:var(--sub)">{rsi_txt}</td>
<td style="text-align:center;font-size:11px;color:var(--sub)">{vp_txt}</td>
<td style="text-align:center" data-v="100"><span class="board-tag">{conf_level(d)}置信</span></td>
<td style="text-align:center" data-v="{TIER_W.get(d["tier"], 0)}">{tier_pill(d["tier"])}</td>
<td style="text-align:center" data-v="{1 if chg_tier else 0}">{chg_tier or '<span style="color:var(--faint)">—</span>'}</td>
<td style="text-align:center;font-size:12px;color:var(--sub)">{gap_badge if gap_badge else gate_tag if gate_tag else action_for(d)}</td></tr>'''
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
        # 年线(MA200)位置（2026-08-18 口径对照）：池档位(收盘决策)偏空的长期依据；监控摘要的分数=20日短期强度
        ma200_txt = ""
        _dev = d.get("ma200_dev")
        if _dev is not None:
            if _dev < 0:
                ma200_txt = (f'<span style="color:#60a5fa" title="收盘口径：现价在 MA200(年线) 下方 '
                             f'{abs(_dev):.1f}%，长期结构偏空，池档位大概率偏弱（监控分仅为短期强度）">'
                             f'年线下方 {abs(_dev):.1f}%</span>')
            else:
                ma200_txt = (f'<span style="color:var(--faint)" title="现价在 MA200(年线) 上方">'
                             f'年线上方 {_dev:+.1f}%</span>')
        cards += f'''<div class="stock-card" id="card-{d["code"]}" data-code="{d["code"]}" data-search="{d["name"]} {d["code"]} {d["industry"]} {board}" data-market="{board}" data-industry="{d["industry"]}" data-tier="{d["tier"]}" data-pick="{d.get("pick") or ""}">
<div class="radar-wrap">{radar}</div>
<div class="body">
<h3>{d["name"]} <span class="sub">{d["code"]}</span> <span class="board-tag">{board}</span> <span class="board-tag">{d["industry"]}</span>{"🎯 KHunter 主信号" if d.get("pick")=="top4" else ("候选·仅观察" if d.get("pick")=="cand" else "")}</h3>
<p class="meta">现价 <b>{d["px"]:.2f}</b>（<span class="{"up" if (d["chg"] or 0)>0 else "down"}">{f"{d['chg']:+.2f}%" if d["chg"] is not None else "—"}</span>）｜ 近一年 <span class="{"up" if (d["ret_1y"] or 0)>0 else "down"}">{f"{d['ret_1y']:+.0f}%" if d["ret_1y"] is not None else "—"}</span> ｜ RSI {d["rsi"]:.0f}</p>
<p class="meta">权重 <b>{d["score"]:.1f} 分</b> → {tier_pill(d["tier"])} ｜ 建议：{action_for(d)} ｜ {ma200_txt}</p>
<p class="meta">六类：趋势 {comp.get("trend",0):.0f}｜动能 {comp.get("momentum",0):.0f}｜量能 {comp.get("volume",0):.0f}｜超买 {comp.get("osc",0):.0f}｜风控 {comp.get("risk",0):.0f}｜研报 0.0</p>
<p class="meta" style="color:var(--faint)">{d.get("biz", "—")}</p>
</div></div>'''
    return cards

# ---------------- 视图区 ----------------
s_auto = DATA["systems"]["v9_auto"]["summary"]
s_lite = DATA["systems"]["v8_lite"]["summary"]
# 基金独立回测（v5.11.9 主显含滑点：基金 slip30 申赎费，fallback 0 滑点；2026-08-17 去 ETF）
def _ml(f, b):
    try:
        d = json.load(open(BASE / f, encoding="utf-8"))
        return d.get("summary", {}), d.get("params", b)
    except Exception:
        return {}, b

s_fund, _ftag = _ml("v8_fund_summary.json", "Top10主仓+6卫星 · MA100")
FUND_TAG = _ftag + " · 申赎费敏感度：30bps≈-10%（90笔/10年半年轮动，影响小）"

def load_curve_norm(f):
    try:
        df = __import__("pandas").read_csv(BASE / f)
        v = df["value"].astype(float).values
        return [round(float(x), 2) for x in (v / v[0] * 100)]
    except Exception:
        return []

v_fund = load_curve_norm("v8_fund_equity.csv")
# 短线净值曲线（短线体系 v3 最优；2026-08-17 去 ETF）
v_short_fund = load_curve_norm("short_v3_fund_slip20_equity.csv")
v_short_stock = load_curve_norm("short_v3_stock_slip20_equity.csv")
# 分层净值曲线（v5.11.15 优先 A80_M78 版，fallback v5.9 旧版；短线 shortsplit 保持）
_SPLIT_GROUPS = ["all", "main_only", "gem_only", "star_only"]
v9split_curves = {}
for g in _SPLIT_GROUPS:
    v = load_curve_norm(f"v9split_{g}_a80_equity.csv")          # v5.11.15 A80_M78
    if not v:
        v = load_curve_norm(f"v9split_{g}_slip20_equity.csv")
    v9split_curves[g] = v if v else load_curve_norm(f"v9split_{g}_equity.csv")
shortsplit_curves = {g: load_curve_norm(f"shortsplit_{g}_equity.csv") for g in _SPLIT_GROUPS}
# 短线 v3 最优 summary（v5.11.7 起主显含滑点口径 slip20，fallback 0 滑点理想口径）
def _ss(asset):
    f = BASE / f"short_v3_{asset}_slip20_summary.json"
    if f.exists():
        return json.load(open(f, encoding="utf-8"))
    return json.load(open(BASE / f"short_v3_{asset}_summary.json", encoding="utf-8"))

_ss_s, _ss_f = _ss("stock"), _ss("fund")
ss_stock = _ss_s["summary"]
ss_fund = _ss_f["summary"]
ss_stock_tag = _ss_s["params"] + f" · 含{_ss_s.get('slippage_bps', 0)}bps滑点"
ss_fund_tag = _ss_f["params"] + f" · 含{_ss_f.get('slippage_bps', 0)}bps滑点"


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
# 中长线分层 summary（v5.11.15 A80_M78 主显：Aroon强趋势过滤版，fallback 旧 slip20/0 滑点类）
s_stk = {}
stk_tag = {}
for g, label, v9f, _sf in _STK_GROUPS:
    s, lbl, tag = _load_summary(v9f + "_a80_summary.json")       # v5.11.15 A80_M78
    is_a80 = bool(s)
    if not s:
        s, lbl, tag = _load_summary(v9f + "_slip20_summary.json")  # fallback 旧
    if not s:
        s, lbl, tag = _load_summary(v9f + "_summary.json")
    s_stk[g] = s
    if is_a80:
        stk_tag[g] = (tag or label) + " · Aroon强趋势过滤(A80_M78)"
    else:
        stk_tag[g] = (tag or label) + (" · 含20bps滑点" if "滑点" not in (tag or "") else "")
# 短线分层 summary（8/31 审计：旧 shortsplit_* 含未来函数作废；修正引擎无分层口径）
# 2026-09-02 晚修复：旧战法（反转打分）已全量弃用 → 分层「已下架」占位卡下线，
# 改接生产主信号 = KHunter 15 信号 + RSI<35 择时 的全窗口回测（主板限定 · S1B_BOARD=main）
# 2026-09-03 生产切换（用户拍板「直接切换，两版部署」）：主源 = 9 格网格 khunter_three_ver_opt_20260903.csv
#   A_x3（ob55+low3）= 生产主卖出配置；C_x3（ob50+low3）= 并行参考配置；B_x3（30%止损）已否决
#   旧源 fusion_s1b_bear_main_allwindow.csv（ob75/osl35）仅作文件缺失回退
def _load_kh_prod():
    """读生产双版本回测（9 格网格 CSV），返回 (A_dict, C_dict|None) 或 (None, None)"""
    import pandas as pd
    f = BASE / "backtest" / "khunter_timing_out" / "khunter_three_ver_opt_20260903.csv"
    if not f.exists():
        return None, None
    try:
        df = pd.read_csv(f)
    except Exception:
        return None, None
    def _pick(tag):
        row = df[df["cfg"] == tag]
        if row.empty:
            return None
        r = row.iloc[0]
        def _g(c):
            v = r[c]
            return float(v) if pd.notna(v) else None
        return {"n": int(r["n"]), "wr": float(r["wr"]), "med": float(r["med"]),
                "mean": float(r["mean"]), "ex_m": float(r["ex_m"]),
                "sharpe": float(r["sharpe_trade"]), "pf": float(r["pf"]), "hold": float(r["hold"]),
                "pool_ann": _g("pool_ann"), "pool_mdd": _g("pool_mdd"),
                "pool_sharpe": _g("pool_sharpe"), "pool_final": _g("pool_final"),
                "y2023": _g("y2023"), "y2024": _g("y2024")}
    return _pick("A_x3"), _pick("C_x3")

def _load_kh_bt():
    """回退源：KHunter 全窗口回测（旧 ob75/osl35/gate none/breadth 0）"""
    import pandas as pd
    f = BASE / "backtest" / "khunter_timing_out" / "fusion_s1b_bear_main_allwindow.csv"
    if not f.exists():
        return None
    try:
        df = pd.read_csv(f)
        row = df[(df["ob"] == 75) & (df["oversold"] == 35) & (df["gate"] == "none") & (df["breadth"] == 0.0)]
        if row.empty:
            return None
        r = row.iloc[0]
        return {
            "n": int(r["n"]), "wr": float(r["wr"]), "med": float(r["med"]),
            "mean": float(r["mean"]), "ex_m": float(r["ex_m"]), "ex_b": float(r["ex_b"]),
            "ann": float(r["ann"]), "sharpe": float(r["sharpe"]), "pf": float(r["pf"]),
            "hold": float(r["hold"]),
            "h1_n": int(r["h1_n"]), "h1_wr": float(r["h1_wr"]), "h1_med": float(r["h1_med"]), "h1_ex": float(r["h1_ex"]),
            "h2_n": int(r["h2_n"]), "h2_wr": float(r["h2_wr"]), "h2_med": float(r["h2_med"]), "h2_ex": float(r["h2_ex"]),
        }
    except Exception:
        return None

_KH_A, _KH_C = _load_kh_prod()
_KH_LEGACY = _KH_A is None
if _KH_A is None:
    _KH_A = _load_kh_bt()
KH_BT = _KH_A
KH_BT_C = _KH_C

ss_stk = {}
ss_stk_tag = {}
for g, label, _v9f, _sf in _STK_GROUPS:
    if g == "all":
        # 一体=旧战法修正版口径（-41.67%）：如实标注「旧战法已弃用」
        ss_stk[g] = json.loads(json.dumps(ss_stock))
        ss_stk_tag[g] = ss_stock_tag + " · 旧战法已弃用(8/31审计)"
    elif g == "main":
        # 纯主板：生产主信号 = KHunter（2026-09-03 起 标准版(主卖出) ob55+低价3元；用户唯一可买主板）
        ss_stk[g] = KH_BT if KH_BT else {}
        ss_stk_tag[g] = ("KHunter 标准版主卖出 RSI>55 · 全窗口对比口径（生产=HYBRIDv2 卡）" if not _KH_LEGACY
                         else ("KHunter 主信号 · 全窗口(牛熊) · 无门控" if KH_BT else f"{label} · 暂无回测"))
    else:
        # 创业板/科创板：用户仅主板可买，KHunter 仅主板回测 → 明确说明卡
        ss_stk[g] = {}
        ss_stk_tag[g] = f"{label} · 用户仅主板可买 · KHunter 未回测"
# 激进版参考卡（9 格网格存在时）
ss_stk["main_c"] = KH_BT_C if KH_BT_C else {}
ss_stk_tag["main_c"] = "KHunter 激进版参考卖出 RSI>50 · 全窗口对比口径（生产=HYBRIDv2 卡）" if KH_BT_C else ""


def bt_card(cid, title, tag, s, curve_id, color="#f59e0b", sub="2016-01~2026-08"):
    """回测 KPI 卡（收益/年化/回撤·夏普 + 净值曲线容器）"""
    if not s:
        return f'<div class="bt-card" id="{cid}"><div class="bt-head"><b>{title}</b><span class="bt-tag">{tag}</span></div><div class="kpis"><div class="kpi"><div class="l">回测收益</div><div class="v">—</div><div class="s">回测中…</div></div></div><div class="bt-curve" id="{curve_id}"></div></div>'
    return f'''<div class="bt-card" id="{cid}">
<div class="bt-head"><b>{title}</b><span class="bt-tag">{tag}</span></div>
<div class="kpis">
<div class="kpi"><div class="l">回测收益</div><div class="v" style="color:{color}">{s["total_return_pct"]:+.1f}%</div><div class="s">{sub}</div></div>
<div class="kpi"><div class="l">年化</div><div class="v">{s["annual_return_pct"]:.1f}%</div><div class="s">胜率 {s.get("win_rate_pct",0):.0f}%</div></div>
<div class="kpi"><div class="l">最大回撤</div><div class="v" style="color:#ef4444">{s["max_drawdown_pct"]:.1f}%</div><div class="s">夏普 {s["sharpe"]:.2f} · {s.get("total_trades",0)} 笔</div></div>
</div>
<div class="bt-curve" id="{curve_id}"></div>
</div>'''


def bt_all_html():
    """中长线回测参考 5 卡（股票分层 4 + 基金；2026-08-17 去 ETF）"""
    cards = "".join([
        bt_card("bt-stock-all", "📈 股票 一体（全A）", stk_tag["all"], s_stk["all"], "curve-chart-stock-all"),
        bt_card("bt-stock-main", "📈 股票 纯主板", stk_tag["main"], s_stk["main"], "curve-chart-stock-main"),
        bt_card("bt-stock-gem", "📈 股票 纯创业板", stk_tag["gem"], s_stk["gem"], "curve-chart-stock-gem"),
        bt_card("bt-stock-star", "📈 股票 纯科创板", stk_tag["star"], s_stk["star"], "curve-chart-stock-star"),
        bt_card("bt-fund", "🔵 基金池", FUND_TAG, s_fund, "curve-chart-fund", color="#3b82f6"),
    ])
    return ('<div class="card" id="bt-all">\n'
            '<h2>📊 回测参考 <span class="badge badge-auto">中/长线 · 股票按权限分层</span></h2>\n'
            '<div class="sub">股票 = 绝对规则筛池 Top3 · 月轮动 · 按权限<b>互斥分层</b>（一体/纯主板/纯创业板/纯科创板，各池独立回测）｜ 基金 = 净值动量轮动 —— 各池严格分开（2026-08-17 去 ETF）</div>\n'
            '<div class="sub" style="color:var(--sub)">💧 <b>滑点敏感性</b>（每边，sweep_ml_slip.py 扫描）：中长线换手低、影响显著小于短线 —— 股票 20bps 收益 -23%（夏普 1.58→1.43）、30bps -31% ｜ 历史固定池（已去除）20bps -13%、30bps -18% —— 实盘 10-20bps 区间内中长线策略稳健</div>\n'
            '<div class="sub" style="color:#d97706">🐻 <b>9/1 牛熊独立权重验证（修正引擎 T+1 · regime=沪深300&gt;MA200 同口径）</b>：生产口径 A（牛开熊清 + 固定权重 0.35/0.25/0.20/0.20）收益 +28.3%/夏普 0.229/回撤 -27.15% 仍最优；牛攻熊守双权重 B/C/D/E 变体（熊市开仓）全面恶化（-25.9%~-65.0%）→ <b>中长期维持「牛开熊清」，熊市开仓不可行</b>（与短线基金相反：基金熊市防守开仓 +398pp 因选到避险型基金）</div>\n'
            '<div class="bt-grid">' + cards + '</div>\n</div>')


def bt_short_html():
    """短线回测参考 5+1 卡
    2026-09-02 晚修复：旧战法弃用 → 纯主板卡改接 KHunter 主信号回测（全窗口无门控 · 四闸 PASS）；
    一体卡=旧战法修正版 -41.67%（标注弃用）；创业板/科创板=用户不可买，明确说明卡
    2026-09-03 生产切换：纯主板卡= 标准版 ob55+低价3元（主卖出）+ 激进版 ob50（参考卖出）双卡（资金池口径含回撤）；
    B 版(30%止损)已否决不入卡"""
    def _card(cid, title, tag, s, curve_id, color="#f59e0b"):
        if not s:
            # 说明卡（创业板/科创板未回测等）
            return (f'<div class="bt-card" id="{cid}" style="border-color:rgba(120,113,108,.3)">'
                    f'<div class="bt-head"><b>{title}</b><span class="bt-tag">{tag}</span></div>'
                    f'<div class="kpis"><div class="kpi"><div class="l">回测收益</div>'
                    f'<div class="v" style="color:var(--faint)">未回测</div>'
                    f'<div class="s">用户仅可买主板；KHunter 主信号仅按主板回测</div></div>'
                    f'<div class="kpi"><div class="l">说明</div><div class="v" style="font-size:15px;color:var(--faint)">—</div>'
                    f'<div class="s">主板卡以 KHunter 全窗口回测为准</div></div></div></div>')
        # KHunter 卡是自定义结构（dict 字段与 summary 不同），单独渲染
        if "ex_m" in s:
            _pool = s.get("pool_mdd") is not None
            if _pool:
                _kpi3 = (f'<div class="kpi"><div class="l">资金池(N5) 回撤</div>'
                         f'<div class="v" style="color:#ef4444">{s["pool_mdd"]:.1f}%</div>'
                         f'<div class="s">资金池(N5) 年化 {s["pool_ann"]:+.2f}% · 夏普 {s["pool_sharpe"]:.2f}</div></div>')
                _kpi2s = f'2024 灾年 {s["y2024"]:+.2f}%' if s.get("y2024") is not None else f'均值 {s["mean"]:+.2f}%'
            else:
                _kpi3 = (f'<div class="kpi"><div class="l">超额(中位基准)</div>'
                         f'<div class="v" style="color:var(--up)">{s["ex_m"]:+.2f}%</div>'
                         f'<div class="s">夏普 {s["sharpe"]:.2f} · PF {s["pf"]:.2f} · 持有 {s["hold"]:.0f} 天</div></div>')
                _kpi2s = f'均值 {s["mean"]:+.2f}%'
            return (f'<div class="bt-card" id="{cid}">'
                    f'<div class="bt-head"><b>{title}</b><span class="bt-tag">{tag}</span></div>'
                    f'<div class="kpis">'
                    f'<div class="kpi"><div class="l">交易口径 中位</div><div class="v" style="color:var(--up)">{s["med"]:+.1f}%</div><div class="s">n={s["n"]} · 均值 {s["mean"]:+.2f}%</div></div>'
                    f'<div class="kpi"><div class="l">胜率</div><div class="v">{s["wr"]:.1f}%</div><div class="s">{_kpi2s}</div></div>'
                    f'{_kpi3}'
                    f'</div></div>')
        return bt_card(cid, title, tag, s, curve_id, color=color)
    _c_cards = (f'{_card("bt-short-stock-main-c", "📈 短线 纯主板 · 激进版(OB50 参考)", ss_stk_tag["main_c"], ss_stk["main_c"], "curve-short-stock-main-c", color="#7c3aed")}'
                if KH_BT_C else "")
    # 🌟 HYBRIDv2 牛熊分域总卡（生产口径 · 组合化资金 · Phase 10 · 2026-09-03 投产终局 · 09-04 弱牛域投产）
    _hybrid_card = ('''<div class="bt-card" id="bt-short-stock-hybrid" style="border-color:rgba(37,99,235,.5)">
<div class="bt-head"><b>🌟 生产口径：牛熊分域 HYBRIDv2 总卡</b><span class="bt-tag">组合化资金 · 正在用的就是它</span></div>
<div class="kpis">
<div class="kpi"><div class="l">组合总收益</div><div class="v" style="color:var(--up)">+68.5%</div><div class="s">n=296 · 胜率 61.2% · 弱牛域未开</div></div>
<div class="kpi"><div class="l">弱牛域开(OSL32)</div><div class="v" style="color:var(--up)">+80.0%</div><div class="s">回测 2026-09-04 定稿 · n=313 · 夏普 0.435</div></div>
<div class="kpi"><div class="l">最大回撤</div><div class="v" style="color:#ef4444">-22.45%</div><div class="s">夏普 0.397 → 0.435 · 均值 +1.90%/笔</div></div>
<div class="kpi"><div class="l">牛(>MA20)</div><div class="v" style="color:var(--up)">med +3.20%</div><div class="s">n=39 · wr 61.5% · 独立过闸</div></div>
</div>
<div class="kpis">
<div class="kpi"><div class="l">熊(&lt;MA60)</div><div class="v" style="color:var(--up)">med +2.41%</div><div class="s">n=257 → 254 · wr 61.1%</div></div>
<div class="kpi"><div class="l">弱牛回调(MA20下/MA60上)</div><div class="v" style="color:var(--up)">med +2.95%</div><div class="s">n=28 · wr 57.1% · 近四闸(n&lt;30) · 2026-09-04 投产</div></div>
</div></div>''')
    cards = "".join([
        _card("bt-short-stock-all", "📈 短线 股票 一体", ss_stk_tag["all"], ss_stk["all"], "curve-short-stock-all"),
        _card("bt-short-stock-main", "📈 短线 纯主板 · 标准版(主卖出 RSI>55)", ss_stk_tag["main"], ss_stk["main"], "curve-short-stock-main", color="#ea580c"),
        _c_cards,
        _hybrid_card,
        _card("bt-short-stock-gem", "📈 短线 纯创业板", ss_stk_tag["gem"], ss_stk["gem"], "curve-short-stock-gem"),
        _card("bt-short-stock-star", "📈 短线 纯科创板", ss_stk_tag["star"], ss_stk["star"], "curve-short-stock-star"),
        bt_card("bt-short-fund", "🔵 短线 基金", ss_fund_tag, ss_fund, "curve-short-fund", color="#3b82f6"),
    ])
    return ('<div class="card" id="bt-short">\n'
            '<h2>⚡ 短线回测参考 <span class="badge badge-auto">生产主信号=KHunter · 修正引擎 T+1 · 2026-09-03 牛熊分域(HYBRIDv2) + 09-04 弱牛域</span></h2>\n'
            '''<div class="sub">📊 <b>短线「在用什么」= 牛熊分域(进场) + 标准版/激进版(卖出线)，外加 H6 动量强弱切换(打分)</b>——三个独立维度，别混：
① <b>牛熊分域（HYBRIDv2 买入框架 + 09-04 弱牛域）</b>：🐻 熊市(沪深300&lt;MA60)：KHunter 信号+RSI&lt;35+收盘≥3元 → 可买；🌞 牛市(&gt;MA20)：信号+RSI&lt;30+无低价 → 可买；🌙 弱牛回调(MA20 下/MA60 上)：<b>RSI&lt;32+无低价 → 可买</b>（2026-09-04 专项投产，回测总收益 68.49%→79.96%）。
② <b>标准版/激进版（卖出参考线）</b>：标准版=主执行（熊市 RSI&gt;55 / 牛市 RSI&gt;75 / 弱牛 RSI&gt;80）；激进版=参考（RSI&gt;50 更早止盈）。<b>两版买入规则完全相同</b>，只有卖出线不同。
③ <b>H6 三态（短线打分权重）</b>：沪深300 20d 动量&gt;2% = 强牛（进攻权重+关动量 mask+S50 门槛）／≤2% 且&gt;MA20 = 弱牛（防守权重+全 mask+S55）／不满足 = 熊市清仓。这个决定「入选池怎么打分」，与开仓/卖出无关。<b>模拟盘标准/激进前向对决后定稿</b></div>\n'''
            '<div class="sub" style="color:var(--sub)">💧 <b>回撤就看一张卡</b>：正在用的 = <b>生产口径 HYBRIDv2 卡（回撤 -22.45%）</b>——牛熊分域入场 + 标准版卖出，组合化资金计算。标准版/激进版两张卡是<b>全窗口单笔口径</b>（n=408，回撤 19.90%/19.45%），用于两版对比（买相同、卖不同），<b>不是</b>生产真实回撤。买卖均为 T 日收盘确认 → T+1 开盘执行；回撤=资金池固定 5 仓等权 NAV。<b>旧战法（反转打分）已弃用</b>（-41.67% 仅对照）</div>\n'
            '<div class="sub" style="color:#7c3aed">🧪 <b>9/1 熊市三策略吸收验证（用户框架规则化 · 修正引擎 T+1）</b>：S1 超跌反弹单笔 +0.48%/胜率 52.6% 但<b>几何均值 -1.73%</b>、S3 右侧追涨单笔 +2.79%/胜率 69.2% 但<b>组合复利 -92.9%</b>、S2 抗跌强势负期望 —— <b>三策略全部 FAIL 组合级四闸</b>。结论：<b>熊市入场过滤救不了逆势，唯一可行=熊市空仓/极端轻仓</b>（例外：KHunter 主信号自身承担风险过滤，熊市开仓全窗口实测过闸）</div>\n'
            '<div class="bt-grid">' + cards + '</div>\n</div>')
perm_stat = ''   # 2026-08-21 固定池已去除

def bt_a5_html():
    """打板族过闸档位回测参考卡（2026-09-04 精简：只显示生产在用最优配置）
    口径：BASE 生产档（rel_pos≤0.5 + amt≥5e7 + room≥0.20）= 9/1 融合网格 260 配置 牛熊独立四闸唯一全维通过
        2026-09-04 放宽扫描 14 配置证实其为唯一全维最优（权威数据 daban_loosen_sweep_20260904.csv）"""
    c1 = f'''<div class="bt-card" id="bt-a5-all">
<div class="bt-head"><b>✅ 生产在用配置（G3_M3 过闸族）</b><span class="bt-tag">唯一四闸 · 全维最优 · 不改</span></div>
<div class="kpis">
<div class="kpi"><div class="l">四闸</div><div class="v" style="color:var(--up)">✅ 通过</div><div class="s">n=358 · wr 51.1% · 2021+ 制度一致区间</div></div>
<div class="kpi"><div class="l">交易中位</div><div class="v" style="color:var(--up)">+0.13%</div><div class="s">均值 +0.69% · 2024 灾年 +0.9%</div></div>
<div class="kpi"><div class="l">累计 / 回撤</div><div class="v">+26.2%</div><div class="s">mdd -15.8% · 放宽 14 配置中最小</div></div>
<div class="kpi"><div class="l">牛 / 熊</div><div class="v">+0.28% / +0.07%</div><div class="s">n=102 / 256 · 牛熊中位均正</div></div>
</div></div>'''
    return (f'<div class="card" id="bt-a5">\n'
            f'<h2>🏆 打板族（生产配置） <span class="badge badge-auto">G3_M3 过闸族 · 9/4 放宽扫描证实全维最优</span></h2>\n'
            f'<div class="sub">生产预筛 = <b>rel_pos≤0.5 + 成交额≥5000万 + 距60日高点≥20%（ROOM_MIN=0.20）</b> + 首板次日低开 gap∈[-5%,-2%] + 止盈 8%/2 天。牛熊独立四闸（n≥30 + wr≥40% + 均值&gt;0 + 中位&gt;0）通过，为 9/1 融合网格唯一牛熊双过闸族</div>\n'
            f'<div class="sub" style="color:#059669">✅ <b>9/4 放宽扫描 14 配置确认最优</b>：放宽 rel_pos(0.6/0.7/0.8/1.0) 中位全转负、降 amt(3e7/2e7/1e7) 过闸但劣化、降 room(0.10/0.00) 四闸灭 —— <b>生产参数维持不变</b>（回测期望，模拟盘验证门通过前不改权重）</div>\n'
            f'<div class="bt-grid">{c1}</div>\n</div>')


def _a5_tbl_full(tbl_id, head_keys, rows, empty="（无）"):
    """A5 交互式表格（2026-08-28 用户需求：与 v9/短线池共用同一交互标准）——
    搜索 + 板块/行业筛选 + 表头点击排序（initTable）。rows = [(data_attrs, td_html_list), ...]"""
    if not rows:
        return f'<div class="sub" style="color:var(--faint)">{empty}</div>'
    boards = sorted({r[0].get("data-market") for r in rows if r[0].get("data-market")})
    inds = sorted({r[0].get("data-industry") for r in rows if r[0].get("data-industry")})
    opt = lambda xs: "".join(f"<option>{x}</option>" for x in xs)
    toolbar = (f'<div class="toolbar">'
               f'<input type="text" id="{tbl_id}-q" placeholder="🔍 搜索名称 / 代码 / 板块 / 行业…">'
               f'<select id="{tbl_id}-mk" class="flt" title="板块筛选"><option value="">全部板块</option>{opt(boards)}</select>'
               f'<select id="{tbl_id}-ind" class="flt" title="行业筛选"><option value="">全部行业</option>{opt(inds)}</select>'
               f'<span class="count" id="{tbl_id}-count"></span></div>')
    head = "".join(f'<th data-key="{k}">{h}</th>' for k, h in head_keys)
    body = "".join(
        "<tr" + "".join(f' {k}="{v}"' for k, v in attrs.items()) + ">" + "".join(cells) + "</tr>"
        for attrs, cells in rows)
    return toolbar + f'<table class="tbl" id="{tbl_id}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def a5_view_html():
    """第三个系统视图：🎯 打板实验（A5_tp8t2 模拟盘 + A2_tp3 回避清单）"""
    st = A5_STATS
    gate = A5_GATE
    bench = A5.get("bench", {})
    wl = A5.get("watchlist", [])
    av = A5.get("avoid", [])
    pos = A5.get("positions", [])
    closed = A5.get("closed", [])
    eq = A5.get("equity", [])
    intraday = A5.get("intraday", False)

    # 验证统计 KPI
    kpis = []
    kpis.append(f'<div class="kpi"><div class="l">已平仓信号</div><div class="v">{st.get("n", 0)}<span style="font-size:13px;color:var(--faint)">/30</span></div><div class="s">触发验证门判定</div></div>')
    wr = st.get("win_rate")
    kpis.append(f'<div class="kpi"><div class="l">模拟盘胜率</div><div class="v">{f"{wr:.1f}%" if wr is not None else "—"}</div><div class="s">回测基准 {bench.get("win_rate", "—")}%</div></div>')
    mn = st.get("mean_net")
    kpis.append(f'<div class="kpi"><div class="l">均值净收益</div><div class="v" style="color:{("var(--up)" if (mn or 0) >= 0 else "var(--down)")}">{f"{mn:+.2f}%" if mn is not None else "—"}</div><div class="s">基准 {bench.get("mean_net", "—"):+.2f}% · 闸 &gt;-0.5%</div></div>')
    tp = st.get("tp_ratio")
    kpis.append(f'<div class="kpi"><div class="l">止盈出场占比</div><div class="v">{f"{tp:.1f}%" if tp is not None else "—"}</div><div class="s">基准 {bench.get("tp_ratio", "—")}% · 闸 [12,32]%</div></div>')
    kpis.append(f'<div class="kpi"><div class="l">模拟盘净值</div><div class="v">{st.get("nav", 1.0):.4f}</div><div class="s">已平仓复利</div></div>')

    # 验证门三闸
    gwr, gmn, gtp = gate.get("wr", {}), gate.get("mn", {}), gate.get("tp", {})
    def _gate_pill(g, label, base):
        if g.get("status") == "waiting":
            return f'<span class="op op-watch">⏳ {label} {g.get("note", "")}</span>'
        flag = "✅" if g.get("status") == "PASS" else "⛔"
        cls = "op-add" if g.get("status") == "PASS" else "op-cut"
        return f'<span class="op {cls}">{flag} {label} {g.get("note", "")}</span>'
    gate_bar = ('<div class="op-stats">' +
                _gate_pill(gwr, "胜率", bench.get("win_rate")) +
                _gate_pill(gmn, "均值净", bench.get("mean_net")) +
                _gate_pill(gtp, "止盈占比", bench.get("tp_ratio")) +
                f'<span class="op" style="color:var(--sub)">{gate.get("verdict", "")}</span>' +
                '</div>')

    # 指标单元格（chg 当日涨跌幅 / ret_1y 近一年 / rsi / vr 量比 / ma5_dev）
    def _chg_cell(v):
        if v is None:
            return '<span style="color:var(--faint)">—</span>'
        cls = "up" if v > 0 else ("down" if v < 0 else "")
        return f'<span class="{cls}">{v:+.2f}%</span>'
    def _pct_cell(v, sig=1):
        if v is None:
            return '<span style="color:var(--faint)">—</span>'
        cls = "up" if v > 0 else ("down" if v < 0 else "")
        return f'<span class="{cls}">{v:+.{sig}f}%</span>'
    def _num_cell(v, sig=1):
        if v is None:
            return '<span style="color:var(--faint)">—</span>'
        return f'{v:.{sig}f}'
    def _num_td(v, sig=1):
        """数值单元格（data-v 供排序）"""
        if v is None:
            return '<td data-v="-99999">—</td>'
        return f'<td data-v="{v}">{v:.{sig}f}</td>'
    def _chg_td(v):
        if v is None:
            return '<td data-v="-99999">—</td>'
        cls = "up" if v > 0 else ("down" if v < 0 else "")
        return f'<td class="{cls}" data-v="{v}">{v:+.2f}%</td>'
    def _pct_td(v, sig=1):
        if v is None:
            return '<td data-v="-99999">—</td>'
        cls = "up" if v > 0 else ("down" if v < 0 else "")
        return f'<td class="{cls}" data-v="{v}">{v:+.{sig}f}%</td>'
    def _txt_td(v):
        return f'<td>{v if v is not None else "—"}</td>'
    def _row(attrs, cells):
        return (attrs, cells)

    # 观察清单（板块列与 v9 同标准：主板/创业板/科创板；行业进 data-search + 悬浮提示）
    def _gate_cell(w, with_val=True):
        """过闸族标注：F3 空间因子（首板日距前60日收盘高点≥20%，百分比单位）+ rel_pos≤0.5（G3_M3 唯一牛熊双过闸）"""
        dh = w.get("dist_high") if w.get("dist_high") is not None else w.get("dist_high60")
        rp = w.get("rel_pos")
        ok = (dh is not None and dh >= 20) and (rp is None or rp <= 0.5)
        if ok:
            inner = f'<span class="board-tag board-sh" title="G3_M3 过闸族：F3空间≥20% + 低位rel≤0.5">✅</span>'
            return f'<td>{inner} {dh:.0f}%</td>' if with_val else f'<td>{inner}</td>'
        return _txt_td("—")
    wl_rows = [_row(
        {"data-code": w["code"], "data-search": f'{w["name"]} {_bare(w["code"])} {w.get("ind", "")} {w.get("board", "")}',
         "data-market": w.get("board", ""), "data-industry": w.get("ind", "")},
        [_txt_td(_bare(w["code"])), _txt_td(f'<b>{w["name"]}</b>'), _txt_td(_board_cell(w.get("board"), w.get("ind"))),
         _txt_td(_perm_cell(w["code"])), _txt_td(w.get("ind", "—")),
         _txt_td(w["sb_date"]), _num_td(w.get("rel_pos"), 2), _txt_td(f'{w.get("amt", 0)/1e4:.0f}'),
         _gate_cell(w), _chg_td(w.get("chg")), _pct_td(w.get("ret_1y"), 1),
         _num_td(w.get("rsi"), 1), _num_td(w.get("vr"), 2), _pct_td(w.get("ma5_dev"), 1)])
        for w in sorted(wl, key=lambda x: -x.get("amt", 0))]
    # 回避清单
    av_rows = [_row(
        {"data-code": a["code"], "data-search": f'{a["name"]} {_bare(a["code"])} {a.get("ind", "")} {a.get("board", "")}',
         "data-market": a.get("board", ""), "data-industry": a.get("ind", "")},
        [_txt_td(_bare(a["code"])), _txt_td(f'<b>{a["name"]}</b>'), _txt_td(_board_cell(a.get("board"), a.get("ind"))),
         _txt_td(_perm_cell(a["code"])), _txt_td(a.get("ind", "—")),
         _txt_td(a["sb_date"]), _pct_td(a.get("gap")*100, 2), _num_td(a.get("rel_pos"), 2),
         _txt_td(f'{a.get("amt", 0)/1e4:.0f}'), _chg_td(a.get("chg")), _pct_td(a.get("ret_1y"), 1),
         _num_td(a.get("rsi"), 1), _num_td(a.get("vr"), 2), _pct_td(a.get("ma5_dev"), 1)])
        for a in sorted(av, key=lambda x: -x.get("amt", 0))]
    # 持仓（板块列与观察/回避清单对齐）
    pos_rows = [_row(
        {"data-code": p["code"], "data-search": f'{p["name"]} {_bare(p["code"])} {p.get("ind", "")} {p.get("board", "")}',
         "data-market": p.get("board", ""), "data-industry": p.get("ind", "")},
        [_txt_td(_bare(p["code"])), _txt_td(f'<b>{p["name"]}</b>'), _txt_td(_board_cell(p.get("board"), p.get("ind"))),
         _txt_td(_perm_cell(p["code"])), _txt_td(p.get("ind", "—")),
         _txt_td(p["entry_date"]), _num_td(p["entry_px"], 2), _pct_td(p.get("gap")*100, 2),
         _txt_td(f'T+{p.get("exit_stage", 1)}'), _chg_td(p.get("chg")), _pct_td(p.get("ret_1y"), 1),
         _num_td(p.get("rsi"), 1), _num_td(p.get("vr"), 2), _pct_td(p.get("ma5_dev"), 1)])
        for p in sorted(pos, key=lambda x: x.get("entry_date", ""))]
    # 已平仓（出场原因中文化）
    REASON_CN = {"tp": "止盈", "ts": "收盘卖", "force": "强平"}
    closed_rows = [_row(
        {"data-code": p["code"], "data-search": f'{p["name"]} {_bare(p["code"])} {p.get("ind", "")} {p.get("board", "")}',
         "data-market": p.get("board", ""), "data-industry": p.get("ind", "")},
        [_txt_td(_bare(p["code"])), _txt_td(f'<b>{p["name"]}</b>'), _txt_td(_board_cell(p.get("board"), p.get("ind"))),
         _txt_td(_perm_cell(p["code"])), _txt_td(p.get("ind", "—")),
         _txt_td(p["entry_date"]), _txt_td(p["exit_date"]), _num_td(p["entry_px"], 2), _num_td(p["exit_px"], 2),
         _txt_td(REASON_CN.get(p["exit_reason"], p["exit_reason"] or "—")),
         _pct_td(p.get("net_ret", 0)*100, 2), _chg_td(p.get("chg")), _pct_td(p.get("ret_1y"), 1),
         _num_td(p.get("rsi"), 1), _num_td(p.get("vr"), 2)])
        for p in closed]
    # 净值曲线（模拟盘点数少，线性折线）
    curve_html = ""
    if len(eq) >= 2:
        pts = " ".join(f"{i},{v['nav']}" for i, v in enumerate(eq))
        curve_html = (f'<svg viewBox="0 0 600 120" style="width:100%;max-width:700px;margin-top:10px">'
                      f'<polyline points="{pts}" fill="none" stroke="#f59e0b" stroke-width="2"/>'
                      f'<text x="8" y="16" font-size="12" fill="#9ca3af">模拟盘净值 {st.get("nav", 1.0):.4f}（{len(eq)} 个交易点）</text></svg>')
    elif eq:
        curve_html = f'<div class="sub" style="color:var(--faint)">净值曲线待积累（当前 {len(eq)} 个点）· 首个平仓后开始绘制</div>'

    # 数据截至徽章（盘中 patch 后显示盘中实时）
    if intraday:
        idate = A5.get("intraday_date") or A5_ASOF
        its = A5.get("intraday_ts") or ""
        asof_badge = (f'<span class="view-badge auto" '
                      f'title="行情截至 {idate} {its} · 清单（观察/回避/持仓）为 {A5_ASOF} 收盘口径">'
                      f'数据截至 {idate} {its} · 盘中实时（清单为 {A5_ASOF} 收盘口径）</span>')
    else:
        asof_badge = f'<span class="view-badge auto" title="收盘数据">数据截至 {A5_ASOF} 15:00 · 收盘</span>'

    # 今日涨停全景（2026-09-05 用户需求：≥9.5%/封板一览 + A5 命中标记，纯观察）
    zp = A5.get("zt_panorama", {})
    zp_date = zp.get("date") or A5_ASOF
    zp_stocks = zp.get("stocks", [])
    zp_hits = [s for s in zp_stocks if s.get("hit")]
    zp_rows = []
    for s in sorted(zp_stocks, key=lambda x: (-x.get("hit", False), -x.get("pct", 0))):
        hit = s.get("hit", False)
        sealed = s.get("sealed", False)
        yz = s.get("yz", False)
        fb = s.get("first_board", False)
        if hit:
            tag = '<span class="badge" style="background:rgba(5,150,105,.18);color:#34d399">✅ A5命中</span>'
        elif sealed:
            tag = '<span class="badge" style="background:rgba(217,119,6,.15);color:#fbbf24">封板</span>'
        else:
            tag = '<span class="badge" style="background:rgba(107,114,128,.15);color:#9ca3af">未封</span>'
        st = []
        if yz:
            st.append('<span class="badge" style="background:rgba(239,68,68,.14);color:#f87171">一字</span>')
        elif fb:
            st.append('<span class="badge" style="background:rgba(37,99,235,.14);color:#60a5fa">首板</span>')
        elif sealed:
            st.append('<span class="badge" style="background:rgba(37,99,235,.14);color:#60a5fa">连板</span>')
        st_html = "".join(st) or '<span style="color:var(--faint)">—</span>'
        # 档位/建议（2026-09-05 用户需求：命中标签之外给操作建议）
        tier = s.get("tier", "不追")
        advice = s.get("advice", "")
        if hit:
            tier_badge = f'<span class="badge" style="background:rgba(5,150,105,.18);color:#34d399">观察</span>'
        else:
            tier_badge = f'<span class="badge" style="background:rgba(107,114,128,.15);color:#9ca3af">不追</span>'
        zp_rows.append(_row(
            {"data-code": s["code"], "data-search": f'{s["name"]} {_bare(s["code"])} {s.get("ind", "")} {s.get("board", "")}',
             "data-market": s.get("board", ""), "data-industry": s.get("ind", "")},
            [_txt_td(_bare(s["code"])), _txt_td(f'<b>{s["name"]}</b>'), _txt_td(_board_cell(s.get("board"), s.get("ind"))),
             _txt_td(_perm_cell(s["code"])), _txt_td(s.get("ind", "—")), _chg_td(s.get("pct")), _txt_td(st_html),
             _txt_td(f'{s.get("amt", 0)/1e8:.2f}'), _num_td(s.get("rel_pos"), 2),
             _pct_td(s.get("dist_high"), 1), _txt_td(tag), _txt_td(tier_badge),
             _txt_td(f'<span style="color:var(--sub);font-size:12px">{advice}</span>')]))
    zp_html = f'''<div class="card" id="a5-zt" style="border-color:rgba(5,150,105,.35)">
<h2>🔥 今日涨停全景 <span class="badge badge-auto">{len(zp_stocks)} 只 · 命中 {len(zp_hits)} 只</span></h2>
<div class="sub">收盘涨幅 ≥9.5% 或封板标的（{zp_date} 收盘口径）· <b>✅ A5命中</b> = 首板 + 非一字 + rel_pos≤0.5 + F3空间≥20% + 成交额≥5000万（G3_M3 过闸族，明日低开 2-5% 则入场）· 纯观察，不构成交易信号</div>
{_a5_tbl_full("a5-zt", [("code","代码"),("name","名称"),("board","板块"),("perm","权限"),("ind","行业"),("pct","涨幅"),("status","状态"),("amt","成交额(亿)"),("relpos","相对位置"),("dist","空间%"),("hit","命中"),("tier","档位"),("advice","建议")], zp_rows, "（今日无 ≥9.5% 标的）")}
</div>'''
    return f'''<div class="view" id="view-a5">
<div class="card" id="sys-a5">
<div class="sys-head">
<div class="sys-head-top">
<h2>🎯 打板族（过闸档位） <span class="view-badge auto">G3_M3 · 过闸档位 · 模拟盘观察</span></h2>
{asof_badge}
</div>
<div class="sys-head-tags">
<span class="badge badge-auto" style="background:#059669;color:#fff">✅ 过闸打板族（G3_M3 牛熊双过）· 模拟盘观察中</span>
<span class="badge badge-auto">信号 = 首板次日低开 2-5% + 相对位置≤0.5 + 成交额≥5000万（生产预筛口径）</span>
<span class="badge badge-auto">出场 = 止盈+T+2（+8% 止盈 / T+2 兜底）</span>
</div>
<div class="sys-head-note"><b>定位</b>：9/3 生产档位敏感性确认 <b>G3_M3（低位+空间≥20%）牛熊双过闸</b>（牛 n=78 wr51.3% +2.52% / 熊 n=104 wr55.8% +0.27%）；裸 rel_pos 不过闸；<b>生产预筛已接入 G3_M3 过闸族</b>（阶段1 = 首板 + rel_pos≤0.5 + <b>F3 空间因子 dist_high≥20%（ROOM_MIN=0.20）</b> + 成交额≥5000万 → 仅过闸族入观察清单）。模拟盘观察 30 信号/3 个月，通过前不改生产权重；G6 组 n&lt;30 禁止投产</div>
</div>
<div class="kpis">{''.join(kpis)}</div>
{gate_bar}
</div>
{zp_html}
<div class="card" id="a5-watchlist">
<h2>📋 观察清单 <span class="badge badge-auto">{len(wl)} 只</span></h2>
<div class="sub">今日首板 · 明日低开 2-5% 则入场（与回测口径一致）· 当日涨跌幅为实时数据（早盘/尾盘/收盘更新），近一年/RSI/量比/MA5偏离为收盘口径</div>
{_a5_tbl_full("a5-wl", [("code","代码"),("name","名称"),("board","板块"),("perm","权限"),("ind","行业"),("sbdate","首板日"),("relpos","相对位置"),("amt","成交额(万)"),("gate","过闸"),("chg","当日涨跌"),("ret1y","近一年"),("rsi","RSI"),("vr","量比"),("ma5dev","MA5偏离")], wl_rows, "（无观察标的）")}
</div>
<div class="card" id="a5-avoid" style="border-color:rgba(217,119,6,.35)">
<h2>⚠ A2_tp3 回避清单 <span class="badge badge-auto">{len(av)} 只 · 负期望警示</span></h2>
<div class="sub">今日满足 A2_tp3 信号（首板次日低开 2-6% + 相对位置≤0.7 + 成交额≥5000万）· 回测胜率 63.1% 但单笔均值 -1.39%（盈亏比 0.29）→ <b>信号出现时回避或减仓，不追高</b></div>
{_a5_tbl_full("a5-av", [("code","代码"),("name","名称"),("board","板块"),("perm","权限"),("ind","行业"),("sbdate","首板日"),("gap","今日低开"),("relpos","相对位置"),("amt","成交额(万)"),("chg","当日涨跌"),("ret1y","近一年"),("rsi","RSI"),("vr","量比"),("ma5dev","MA5偏离")], av_rows, "（无）")}
</div>
<div class="card" id="a5-positions">
<h2>💼 模拟盘持仓 <span class="badge badge-auto">{len(pos)} 只</span></h2>
<div class="sub">入场 = 开盘价低开确认 · 出场 T+1/T+2 冲高≥入场×1.08 止盈，否则收盘卖；涨停顺延/强平</div>
{_a5_tbl_full("a5-pos", [("code","代码"),("name","名称"),("board","板块"),("perm","权限"),("ind","行业"),("entrydate","入场日"),("entrypx","入场价"),("gap","低开"),("stage","出场阶段"),("chg","当日涨跌"),("ret1y","近一年"),("rsi","RSI"),("vr","量比"),("ma5dev","MA5偏离")], pos_rows, "（无持仓）")}
</div>
<div class="card" id="a5-closed">
<h2>📜 已平仓（累计） <span class="badge badge-auto">{len(closed)} 笔</span></h2>
<div class="sub">模拟盘逐笔净收益（含成本买 0.525%/卖 0.625%）· 累计 ≥30 笔触发验证门判定</div>
{_a5_tbl_full("a5-cl", [("code","代码"),("name","名称"),("board","板块"),("perm","权限"),("ind","行业"),("entrydate","入场日"),("exitdate","出场日"),("entrypx","入场价"),("exitpx","出场价"),("reason","原因"),("netret","净收益"),("chg","当日涨跌"),("ret1y","近一年"),("rsi","RSI"),("vr","量比")], closed_rows, "（尚无平仓记录）")}
</div>
<div class="card" id="a5-curve">
<h2>📈 模拟盘净值曲线 <span class="badge badge-auto">已平仓复利</span></h2>
<div class="sub">回测组合复利 -72.2% 警示：边缘太薄（σ≈5%/日），净值曲线难看属正常，验证的是边缘是否存在而非盈利</div>
{curve_html}
</div>
</div>'''

def system_block(vid, sid, title, badge, sub, items, tbl_id, card_id, note, extra_stat=None, extra_card="", score_sub="趋势/动量/量能/超买/风控", as_of=None, intraday_note=None, as_of_min=None, tier_opts=None, tier_add=None, tier_watch=None, tier_cut=None, head_tags=None, head_note="", inline=False):
    """每个系统的完整区块：系统头（标题+说明）+ 操作统计条 + 汇总表 + 详情卡片
    回测参考统一放总览视图，这里只保留监控主体。extra_card=视图末尾追加卡片（如持仓跟踪）
    as_of / intraday_note / as_of_min：三池数据更新时间徽章（2026-08-17 升级：精确到分钟，
    盘中=patch 时刻 HH:MM，收盘=15:00）
    head_tags：标题下方的标签行（徽章 HTML 列表，门控徽章放第一位）；head_note：标签行下说明文字
    （2026-08-21：标题与更新时间一左一右，指标/门控标签独立一行，不再堆进 h2）
    tier_opts/tier_add/tier_watch/tier_cut：档位筛选与统计条口径（短线池=强买入/买入/不买，
    与中长线池不同，2026-08-17 修复）
    inline=True：不包 .view 外壳（2026-09-03 短线股票/基金分板块：同视图内叠两个系统块）"""
    tier_opts = tier_opts or ["满仓加仓", "轻仓加仓", "观望", "减至半仓", "清仓"]
    tier_add = tier_add or ("满仓加仓", "轻仓加仓")
    tier_watch = tier_watch or ("观望",)
    tier_cut = tier_cut or ("减至半仓", "清仓")
    up, down = updown(items, tier_add, tier_cut)
    t8 = tier_counts(items)
    asof_html = ""
    if as_of:
        _tag = "盘中实时" if intraday_note else "收盘"
        _ts = as_of_min or ("15:00" if not intraday_note else "")
        _ts_html = f" {_ts}" if _ts else ""
        asof_html = f'<span class="view-badge auto" title="{intraday_note or "收盘数据"}">数据截至 {as_of}{_ts_html} · {_tag}</span>'
    stat_bar = (extra_stat if extra_stat else "") + f'''<div class="op-stats">
<span class="op op-add">🟢 加仓区 <b>{sum(t8.get(t,0) for t in tier_add)}</b> 只</span>
<span class="op op-watch">🟡 观望 <b>{sum(t8.get(t,0) for t in tier_watch)}</b> 只</span>
<span class="op op-cut">🔴 减/清仓区 <b>{sum(t8.get(t,0) for t in tier_cut)}</b> 只</span>
</div>'''
    tier_opts_html = "".join(f"<option>{t}</option>" for t in tier_opts)
    _tags_html = "".join(head_tags) if head_tags else ""
    _head_extra = ""
    if _tags_html:
        _head_extra += f'<div class="sys-head-tags">{_tags_html}</div>'
    if head_note:
        _head_extra += f'<div class="sys-head-note">{head_note}</div>'
    _body = f'''<div class="card" id="{sid}">
<div class="sys-head">
<div class="sys-head-top">
<h2>{title} <span class="view-badge {badge}">{sub}</span></h2>
{asof_html}
</div>
{_head_extra}
</div>
{stat_bar}
</div>
<div class="card" id="{card_id}">
<h2>📋 标的汇总表 <span class="badge {badge}">{len(items)} 行</span></h2>
<div class="sub">今日信号：加仓区 {up} ｜ 减/清仓区 {down} · 搜索/筛选/排序联动下方详情卡片 · 表头点击排序</div>
<div class="toolbar">
<input type="text" id="{tbl_id}-q" placeholder="🔍 搜索名称 / 代码 / 行业…">
<select id="{tbl_id}-mk" class="flt" title="板块筛选"><option value="">全部板块</option>{filter_options(items, "board")}</select>
<select id="{tbl_id}-ind" class="flt" title="行业筛选"><option value="">全部行业</option>{filter_options(items, "industry")}</select>
<select id="{tbl_id}-tier" class="flt" title="档位筛选"><option value="">全部档位</option>{tier_opts_html}</select>
<span class="count" id="{tbl_id}-count"></span>
<button id="{tbl_id}-buyonly" class="flt" title="只看买入候选（剔除减半/清仓）" style="cursor:pointer;padding:7px 12px">🔍 只看可买信号</button>
</div>
<table class="tbl" id="{tbl_id}">
<thead><tr>
<th data-key="rank" style="text-align:center">#</th><th data-key="name">标的</th><th data-key="board">板块</th><th data-key="perm">权限</th><th data-key="industry">行业</th><th data-key="px" style="text-align:right">现价</th>
<th data-key="chg" style="text-align:right">涨跌幅</th><th data-key="ret1y" style="text-align:right">近一年</th><th data-key="score" style="text-align:center">权重分<div class="th-sub">{score_sub}</div></th><th data-key="rsi" style="text-align:center">RSI</th><th data-key="vp" style="text-align:center">量能</th>
<th data-key="conf" style="text-align:center">置信度</th><th data-key="tier" style="text-align:center">档位</th><th data-key="tierchg" style="text-align:center">档位变化</th><th data-key="action" style="text-align:center">建议动作</th>
</tr></thead>
<tbody>{rows_html_for(items)}</tbody>
</table>
<div class="note">{note}</div>
</div>
<div class="card" id="{card_id}-detail">
<h2>🔍 逐标的详情（雷达图） <span class="count" id="{tbl_id}-cardcount" style="font-size:12px"></span></h2>
<div class="sub">六角雷达 = 趋势/动能/量能/超买/风控/研报 六类打分 · 与上方表格搜索/筛选/排序联动</div>
<div class="stock-cards" id="{tbl_id}-cards">{cards_html_for(items)}</div>
</div>
{extra_card}'''
    if inline:
        return _body
    return f'''<div class="view" id="{vid}">
{_body}
</div>'''


WATCH_CARD = f'''<div class="card" id="watch-card">
<h2>📌 全量池短线跟踪 <span class="badge badge-auto">自动 · 保留 30 天</span></h2>
<div class="sub">上方短线表<b>可买入标的（强买入/买入）</b>上榜次日收盘确认后自动加入跟踪，30 天自动移除（<b>2026-08-18 起新上榜先入「待确认」隔日入池</b>，隔离当日收盘信号）· 卖出规则（与回测一致）：<b>收盘跌破 MA5 → 次日开盘卖出</b> ｜ 掉出信号池 → 下次轮动换出 ｜ 档位减半/清仓 → 按档位操作 · 每次重新上榜刷新【入池/跟踪/出池】时间 · 数据截至 {SHORT_POOL_ASOF}（基金净值 T-1：{SHORT_POOL.get("fund_as_of", "—")}）</div>
<div id="watch-pending"></div>
<div id="watch-gate"></div>
<div class="toolbar" id="watch-bar">
<input type="text" id="watch-q" name="watch-q" placeholder="🔍 搜索代码 / 名称…" autocomplete="off" spellcheck="false" aria-label="搜索跟踪标的（代码或名称）">
<select id="watch-f-type" class="flt" title="类型/权限筛选" aria-label="按类型或权限筛选"><option value="">全部类型</option></select>
<select id="watch-f-inpool" class="flt" title="在池状态筛选" aria-label="按在池状态筛选"><option value="">全部状态</option><option value="1">在池</option><option value="0">已掉出（待轮动换出）</option></select>
<select id="watch-f-tier" class="flt" title="档位筛选" aria-label="按档位筛选"><option value="">全部档位</option></select>
<select id="watch-sort" class="flt" title="排序方式" aria-label="排序方式"><option value="entry">加入时间 ↓</option><option value="chg">涨跌 ↓</option><option value="score">短线分 ↓</option><option value="name">名称 ↑</option><option value="left">剩余天数 ↑</option></select>
<span class="count" id="watch-count"></span>
</div>
<div id="watch-table"></div>
</div>'''

# 全量池中/长线年跟踪池（2026-08-17 用户需求：上榜跟踪 1 年，再上榜 +1 年；track_v9 由 build_enhanced_data.py 维护）
WATCH_V9_CARD = f'''<div class="card" id="watch-v9-card">
<h2>📌 全量池中/长线跟踪 <span class="badge badge-auto">上榜跟踪 1 年 · 再上榜 +1 年</span> </h2>
<div class="sub">上方全量池表<b>上榜标的</b>（v9_tiers：main/gem/star/fund）上榜次日收盘确认后自动加入跟踪，持续 1 年（365 天）；<b>2026-08-18 起新上榜先入「待确认」隔日入池</b>（隔离当日收盘信号）；每次重新上榜刷新【入池/跟踪/出池】时间 · 数据截至 {DATA["meta"].get("as_of", "—")}（收盘）</div>
<div id="watch-v9-pending"></div>
<div class="toolbar" id="watch-v9-bar">
<input type="text" id="watch-v9-q" name="watch-v9-q" placeholder="🔍 搜索代码 / 名称…" autocomplete="off" spellcheck="false" aria-label="搜索跟踪标的（代码或名称）">
<select id="watch-v9-f-pool" class="flt" title="板块筛选" aria-label="按板块筛选"><option value="">全部板块</option></select>
<select id="watch-v9-f-status" class="flt" title="状态筛选" aria-label="按状态筛选"><option value="">全部状态</option><option value="1">在池</option><option value="0">已掉出池（观察）</option></select>
<select id="watch-v9-f-tier" class="flt" title="档位筛选" aria-label="按档位筛选"><option value="">全部档位</option></select>
<select id="watch-v9-sort" class="flt" title="排序方式" aria-label="排序方式"><option value="entry">加入时间 ↓</option><option value="chg">涨跌 ↓</option><option value="score">权重分 ↓</option><option value="name">名称 ↑</option><option value="left">剩余天数 ↑</option></select>
<span class="count" id="watch-v9-count"></span>
</div>
<div id="watch-v9-table"></div>
</div>'''

# ---- 复盘日志 + 更新日志（v5.11.1 内嵌视图：与各池同形态，导航内切换）----
def md_to_html(md):
    """轻量 markdown → HTML（标题/表格/列表/粗体/代码/引用），复用主题 .tbl 样式，全部走 CSS 变量"""
    def inline(s):
        # 先转义 & < >（防内容里的 <details> 等破坏 HTML 结构），再包粗体/代码标签
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        return s
    lines = md.splitlines()
    out, i, n = [], 0, len(lines)
    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1; continue
        if ln.startswith("|"):
            tbl = []
            while i < n and lines[i].startswith("|"):
                tbl.append(lines[i]); i += 1
            if len(tbl) >= 2:
                hdr = [c.strip() for c in tbl[0].strip("|").split("|")]
                body = [[c.strip() for c in r.strip("|").split("|")] for r in tbl[2:]]
                out.append('<table class="tbl"><thead><tr>' + "".join(f"<th>{inline(h)}</th>" for h in hdr) + "</tr></thead><tbody>")
                for r in body:
                    out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
                out.append("</tbody></table>")
            continue
        if ln.startswith(("#### ", "### ", "## ", "# ")):
            out.append(f"<h3>{inline(ln.split(' ', 1)[1])}</h3>"); i += 1; continue
        if ln.startswith("- "):
            items = []
            while i < n and lines[i].startswith("- "):
                items.append(f"<li>{inline(lines[i][2:])}</li>"); i += 1
            out.append("<ul>" + "".join(items) + "</ul>"); continue
        if ln.startswith("> "):
            q = []
            while i < n and lines[i].startswith("> "):
                q.append(inline(lines[i][2:])); i += 1
            out.append("<blockquote>" + "<br>".join(q) + "</blockquote>"); continue
        out.append(f"<p>{inline(ln)}</p>"); i += 1
    return '<div class="rev-md">' + "\n".join(out) + "</div>"


REVIEW_LIST_HTML = ""
_rf = BASE / "review" / "review_index.json"
_ridx = json.loads(_rf.read_text(encoding="utf-8")) if _rf.exists() else {"reviews": []}
# 2026-08-18 晚：按日期降序（最新在前），最新一篇默认展开
_rev_sorted = sorted(_ridx.get("reviews", []), key=lambda r: r.get("date", ""), reverse=True)
_seen_rf = set()
for _i, _r in enumerate(_rev_sorted):
    _f = BASE / "review" / _r["file"]
    if not _f.exists() or _r["file"] in _seen_rf:
        continue
    _seen_rf.add(_r["file"])
    _flag = "🔴" if _r.get("defects", 0) > 0 else "✅"
    _open = " open" if _i == 0 else ""          # 最新一篇默认展开，其余折叠
    REVIEW_LIST_HTML += (f'<details class="rev-item"{_open}>'
                         f'<summary><span class="rev-flag">{_flag}</span><b>{_r["date"]}</b>'
                         f'<span class="rev-meta">信号 {_r["sig"]} · {_r["n"]} 只 · 胜率 {_r.get("win_rate", 0)}% · 缺陷 {_r.get("defects", 0)} 项</span></summary>'
                         f'<div class="rev-body">{md_to_html(_f.read_text(encoding="utf-8"))}</div></details>\n')
if not REVIEW_LIST_HTML:
    REVIEW_LIST_HTML = '<div class="sub" style="color:var(--faint)">暂无复盘记录 —— 每天收盘后运行 <code>python refresh_daily.py</code> 自动生成</div>'

# A5 打板实验复盘区块（2026-08-28 接入 view-review 顶部；数据来自 review/a5_review.json）
A5_REVIEW_BLOCK = ""
_a5rev_f = BASE / "review" / "a5_review.json"
if _a5rev_f.exists():
    _ar = json.loads(_a5rev_f.read_text(encoding="utf-8"))
    _ars = _ar.get("stats", {})
    _arg = _ar.get("gate", {})
    _wr = _ars.get("win_rate")
    _mn = _ars.get("mean_net")
    _tp = _ars.get("tp_ratio")
    _a5kpi = (
        f'<div class="kpi"><div class="l">已平仓</div><div class="v">{_ars.get("n", 0)}/30</div><div class="s">触发判定阈值</div></div>'
        f'<div class="kpi"><div class="l">胜率</div><div class="v">{f"{_wr:.1f}%" if _wr is not None else "—"}</div><div class="s">基准 46.1% · 闸 [35,55]%</div></div>'
        f'<div class="kpi"><div class="l">均值净</div><div class="v" style="color:{("var(--up)" if (_mn or 0) >= 0 else "var(--down)")}">{f"{_mn:+.2f}%" if _mn is not None else "—"}</div><div class="s">基准 -0.17% · 闸 &gt;-0.5%</div></div>'
        f'<div class="kpi"><div class="l">止盈占比</div><div class="v">{f"{_tp:.1f}%" if _tp is not None else "—"}</div><div class="s">基准 21.5% · 闸 [12,32]%</div></div>'
        f'<div class="kpi"><div class="l">净值</div><div class="v">{_ars.get("nav", 1.0):.4f}</div><div class="s">已平仓复利</div></div>'
    )
    _flag = "✅" if _arg.get("verdict", "").startswith("✅") else ("⏳" if _arg.get("verdict", "").startswith("信号不足") else "⛔")
    A5_REVIEW_BLOCK = (f'<h2>🎯 打板族（过闸档位）模拟盘验证 <span class="badge badge-auto">生产预筛口径 · 非实盘指令</span></h2>'
                       f'<div class="sub">逐笔模拟盘跟踪（net_ret 含成本）· 验证门参考 = G3_M3 过闸（牛 +2.52% / 熊 +0.27%）· 30 信号或 3 个月触发判定 · 详细见「🎯 打板族」视图</div>'
                       f'<div class="kpis" style="margin-bottom:10px">{_a5kpi}</div>'
                       f'<div class="op-stats"><span class="op" style="color:var(--sub)">{_flag} 判定：{_arg.get("verdict", "—")}</span>'
                       f'<span class="op" style="color:var(--faint)">观察清单 {_ar.get("n_watch", 0)} · 回避清单 {_ar.get("n_avoid", 0)} · 持仓 {_ar.get("n_pos", 0)} · 更新 {_ar.get("updated", "—")}</span></div>')
else:
    A5_REVIEW_BLOCK = '<div class="sub" style="color:var(--faint)">A5 模拟盘复盘未生成 —— 先运行 <code>python build_a5_pool.py && python build_a5_review.py</code></div>'

# 累计总览独立卡片（2026-08-18 晚：内嵌视图顶部只显示一份，data 来自 cumulative.json）
_rev_cum = ""
_cum_f = BASE / "review" / "cumulative.json"
if _cum_f.exists():
    _cdata = json.loads(_cum_f.read_text(encoding="utf-8"))
    if _cdata.get("pools"):
        _CBENCH = {
            "全量池中/长线": 48.1,
            "短线·主板": 46.8, "短线·创业板": 48.1, "短线·科创板": 57.8, "短线·基金": 55.5,
        }
        _crows = []
        _CT = {"n": 0, "buy": 0, "wins": 0, "losses": 0, "flat": 0, "sum_pct": 0.0}
        for _cn, _ca in _cdata["pools"].items():
            _cwr = (_ca["wins"] / _ca["buy"] * 100) if _ca.get("buy") else 0
            _cavg = (_ca["sum_pct"] / _ca["buy"]) if _ca.get("buy") else 0
            _bench = _CBENCH.get(_cn)
            _bench_s = f"{_bench:.1f}%" if _bench is not None else "—"
            _diff = f"（{(_cwr-_bench):+0.1f}pct）" if _bench is not None and _ca.get("buy") else ""
            _crows.append(f"<tr><td>{_cn}</td><td>{_ca['n']}</td><td>{_ca['buy']}</td><td>{_ca['wins']}</td>"
                          f"<td>{_ca['losses']}</td><td>{_ca['flat']}</td><td>{_cwr:.0f}%</td>"
                          f"<td>{_bench_s} {_diff}</td><td>{_cavg:+.2f}%</td></tr>")
            for _k in _CT:
                _CT[_k] += _ca[_k]
        if _CT["buy"]:
            _crows.append(f"<tr class='rev-cum-total'><td>合计</td><td>{_CT['n']}</td><td>{_CT['buy']}</td><td>{_CT['wins']}</td>"
                          f"<td>{_CT['losses']}</td><td>{_CT['flat']}</td><td>{_CT['wins']/_CT['buy']*100:.0f}%</td>"
                          f"<td>—</td><td>{_CT['sum_pct']/_CT['buy']:+.2f}%</td></tr>")
        _rev_cum = (f'<div class="rev-cum"><div class="rev-cum-title">📈 累计总览'
                    f'<span class="rev-cum-badge">自 {_cdata.get("since","—")} · {_cdata.get("count",0)} 篇</span></div>'
                    f'<div class="rev-cum-sub">三池累计信号标的（防重累加；短线·基金 T+1 净值未出计持平）· 回测基准 = 2016 起回测胜率</div>'
                    f'<table class="tbl"><thead><tr><th>池</th><th>累计标的</th><th>累计买入</th><th>🟢吃到</th>'
                    f'<th>🔴被套</th><th>⚪持平</th><th>累计胜率</th><th>回测基准</th><th>累计均收</th></tr></thead>'
                    f'<tbody>{"".join(_crows)}</tbody></table></div>')

CHANGELOG_HTML = ""
_cf = BASE / "changelog.md"
if _cf.exists():
    _ct = _cf.read_text(encoding="utf-8")
    _cards = []
    _seen_ver = set()
    for _i, _seg in enumerate(re.split(r"\n## ", "\n" + _ct)[1:]):
        _title = _seg.splitlines()[0].strip()
        _body = "\n".join(_seg.splitlines()[1:]).strip()
        _m = re.match(r"(v[\d.]+)\s*-\s*([\d-]+)", _title)
        _ver = _m.group(1) if _m else _title
        if _ver in _seen_ver:
            continue                        # 同版本号只渲染第一个，防 changelog 重复段
        _seen_ver.add(_ver)
        _date = _m.group(2) if _m else ""
        _open = " open" if _i == 0 else ""       # 最新版本默认展开，其余折叠
        _cards.append(f'<details class="rel-item"{_open}>'
                      f'<summary><span class="rel-ver">{_ver}</span><span class="rel-date">{_date}</span></summary>'
                      f'<div class="rel-body">{md_to_html(_body)}</div></details>')
    CHANGELOG_HTML = "\n".join(_cards)

# ════ 视图 C 内容：短线 股票池 / 基金池 分板块（2026-09-03 用户需求）════
# 股票池含 标准/激进 双版本（入场同信号，标准版 A55 主卖出 + 激进版 C50 参考标注）；基金池=场外基金动量；
# 跟踪池统一放底部（股票+基金同一 watch 卡，类型筛选），不做 标准/激进 双跟踪池（买入同一、卖出判定归模拟盘双轨）
SHORT_VIEW_HTML = f'''<div class="view" id="view-short">
{system_block(
  "view-short-stk", "sys-short-stk",
  "⚡ 短线 · 股票池", "auto", "主板 KHunter 主信号 · A55 主卖出 / C50 参考 · 低价≥3元",
  v9_short_stock, "tbl-short-stk", "card-short-stk",
  "信号池 = 回测买入清单：KHunter 15 策略信号 + 信号日 RSI&lt;35 超卖 + 收盘≥3元（主板限定·事件独立·有信号即买）· 卖出 = <b>逐股独立</b>：持仓股自身 RSI 确认日 &gt; 标准版阈值（熊 55/牛 75） → T+1 开盘卖（RSI&gt;50 为激进版参考线，标注但<i>不执行</i>，标准/激进判定归模拟盘双轨）· 档位 = 短线买入口径（强买入/买入）· 下方「📌 全量池短线跟踪」自动跟踪可买入标的（保留 30 天）· <b>开盘跳空高开 &gt;3% 的标的标注「⚠ 高开规避」：不追高，可等盘中回落至 3% 以内再考虑买入（9:30 盘中起生效）</b>",
  extra_card="", score_sub="动量/量价/通道/波动",
  head_tags=[SHORT_POOL_GATE, SHORT_KHUNTER_BEAR, SHORT_KHUNTER_BADGE,
             '<span class="badge badge-auto">股票 = KHunter 15 策略信号 + RSI&lt;35 超卖 + 熊市MA60（主板限定 · 弃用旧战法）</span>',
             '<span class="badge badge-auto">KHunter 信号密集期每日可能有几只，稀疏期 0 只属正常（事件驱动）</span>'],
  head_note=f"<b>🎯 KHunter 主信号（蓝标）= 主板 15 策略信号命中 + 信号日 RSI&lt;35 超卖 + 收盘≥3元 + 熊市(沪深300&lt;MA60)</b>（2026-09-03 生产切换 v5.14.0：B1 熊市限定——38 组牛市扫描 0 过门后收紧；<b>标准版</b> 卖出 RSI&gt;55 主执行 / <b>激进版</b> RSI&gt;50 参考展示；入场两版相同）· 回测：标准版+低价（熊市限定）n=408 资金池(N5)年化 5.54%/回撤 19.90%/夏普 0.372，激进版+低价 4.98%/19.45%/0.352（每笔口径激进版更锐：81.4%/1.430）；牛市子集 4 方向×38 组 0 过门→不开新仓，牛市收益由基金动量池承担· <b>旧战法（反转分）已全量弃用</b>（主板 -35.65% / 全市场 -41.67% 均负期望，不再展示）· 市况门控仅提醒：沪深300 &gt; MA20 才开新仓；KHunter 买入由独立 <b>MA60 熊市门控</b>裁决（非熊→不开新仓仅观察/卖出）· 卖出逐股独立走「全量池短线跟踪」· 回测参考见「监控总览」",
  as_of=SHORT_POOL_ASOF, intraday_note=SHORT_POOL_INTRADAY,
  as_of_min=SHORT_POOL.get("intraday_ts") or SHORT_POOL_ASOF_MIN,
  tier_opts=["强买入", "买入", "不买"], tier_add=("强买入", "买入"), tier_watch=("不买",), tier_cut=(), inline=True)}
{system_block(
  "view-short-fund", "sys-short-fund",
  "🔵 短线 · 基金池", "auto", "场外基金动量（分≥50 才入池）",
  v9_short_fund, "tbl-short-fund", "card-short-fund",
  "基金池 = 场外基金动量选股（与股票完全独立，资产类别不同）· 现价 = T-1 净值（场外基金净值次日公布）· 基金买入按短线分（≥50）· 与股票池分开展示（2026-09-03 起）",
  extra_card="", score_sub="动量/趋势",
  head_tags=['<span class="badge badge-auto">🔵 场外基金动量（分≥50）</span>',
             '<span class="badge badge-auto">现价 = T-1 净值 · 次日公布</span>'],
  head_note="基金池与股票池（KHunter 主板信号）完全独立：基金=净值动量轮动，股票=KHunter 事件信号；档位口径同为短线买入口径（强买入/买入）",
  as_of=SHORT_POOL.get("fund_as_of", SHORT_POOL_ASOF), intraday_note="",
  as_of_min="20:00",
  tier_opts=["强买入", "买入", "不买"], tier_add=("强买入", "买入"), tier_watch=("不买",), tier_cut=(), inline=True)}
{WATCH_CARD}
</div>'''

html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2016%2016'%3E%3Crect%20width='16'%20height='16'%20rx='3'%20fill='%232563eb'/%3E%3Cpath%20d='M3%2012V8h2v4zM6%2012V4h2v8zM9%2012V6h2v6zM12%2012V2h2v10z'%20fill='%23fff'/%3E%3C/svg%3E">
<title>标的监控看板（数据截至 {DATA["meta"].get("as_of", "—")} · 构建 {build_ts}）</title>
<style>{THEME_CSS}
/* 三视图切换 */
.view{{display:none}}
.view.active{{display:block}}
.view-badge{{display:inline-block;padding:2px 10px;border-radius:20px;font-size:11px;margin-left:8px;vertical-align:middle}}
.view-badge.auto{{background:rgba(245,158,11,.15);color:#b45309}}
[data-theme="dark"] .view-badge.auto{{color:#fbbf24}}
.view-badge.lite{{background:rgba(59,130,246,.15);color:#1d4ed8}}
[data-theme="dark"] .view-badge.lite{{color:#60a5fa}}
/* 系统头部排版（2026-08-21）：标题+更新时间一左一右，标签按内容分行，门控最前 */
.sys-head{{display:flex;flex-direction:column;gap:10px}}
.sys-head-top{{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px}}
.sys-head-top h2{{margin:0;display:flex;align-items:center;flex-wrap:wrap;gap:4px}}
.sys-head-top .view-badge{{margin-left:0}}
.sys-head-tags{{display:flex;flex-wrap:wrap;gap:6px;align-items:center}}
.sys-head-tags .badge{{margin-left:0}}
.sys-head-note{{color:var(--faint);font-size:12px;line-height:1.7}}
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
/* 基金回测参考 · 三池独立大卡（2026-08-17 去 ETF） */
.bt-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}
.bt-card{{background:var(--card2);border:1px solid var(--border);border-radius:14px;padding:16px}}
.bt-card .bt-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;font-size:15px}}
.bt-card .bt-tag{{font-size:11px;color:var(--faint);background:var(--card);border:1px solid var(--border);border-radius:20px;padding:2px 10px}}
.bt-card .bt-curve{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:6px;margin-top:10px}}
/* 日志视图（内嵌，主题变量驱动） */
.rev-item,.rel-item{{background:var(--card2);border:1px solid var(--border);border-radius:12px;margin-bottom:10px;overflow:hidden}}
.rev-item summary,.rel-item summary{{display:flex;align-items:center;gap:10px;padding:12px 16px;cursor:pointer;font-size:13px;color:var(--text);list-style:none;flex-wrap:wrap;user-select:none}}
.rev-item summary::-webkit-details-marker,.rel-item summary::-webkit-details-marker{{display:none}}
.rev-item summary::before,.rel-item summary::before{{content:'▸';color:var(--faint);transition:transform .15s;font-size:12px}}
.rev-item[open] summary::before,.rel-item[open] summary::before{{transform:rotate(90deg)}}
.rev-item[open] summary,.rel-item[open] summary{{border-bottom:1px solid var(--line)}}
.rev-item summary:hover,.rel-item summary:hover{{border-color:var(--accent)}}
.rev-flag{{font-size:13px}}
.rev-meta{{color:var(--faint);font-size:12px}}
.rev-body{{padding:14px 16px}}
/* 累计总览独立卡片（2026-08-18 晚：内嵌视图顶部仅一份） */
.rev-cum{{background:linear-gradient(135deg,var(--card2),var(--card));border:1px solid var(--border);border-radius:14px;padding:16px 18px;margin-bottom:14px}}
.rev-cum-title{{font-size:16px;font-weight:700;color:var(--accent);display:flex;align-items:center;gap:10px;margin-bottom:6px}}
.rev-cum-badge{{font-size:11px;color:var(--faint);background:var(--card);border:1px solid var(--border);border-radius:20px;padding:2px 10px;font-weight:400}}
.rev-cum-sub{{color:var(--faint);font-size:12px;margin-bottom:8px}}
.rev-cum .tbl th{{background:var(--card2)}}
.rev-cum .tbl tbody tr.rev-cum-total td{{font-weight:700;background:var(--card2)}}
.rel-ver{{font-weight:700;font-size:15px;color:var(--accent);letter-spacing:.5px}}
.rel-date{{color:var(--faint);font-size:12px;background:var(--card);border:1px solid var(--border);padding:2px 10px;border-radius:20px}}
.rel-body{{color:var(--text);font-size:13px;line-height:1.75}}
.rel-body ul{{margin:6px 0 6px 18px;padding:0}}
.rel-body li{{margin:4px 0}}
.rel-body b{{color:var(--text)}}
.rev-md h3{{font-size:15px;margin:16px 0 8px;color:var(--text)}}
.rev-md h4{{font-size:14px;margin:12px 0 6px;color:var(--text)}}
.rev-md p{{margin:6px 0;color:var(--text)}}
.rev-md blockquote{{background:var(--card2);border-left:3px solid var(--accent);padding:8px 12px;margin:8px 0;border-radius:0 8px 8px 0;color:var(--sub)}}
/* 持仓跟踪 */
#watch-table .up{{color:#22c55e}} #watch-table .down{{color:#ef4444}} #watch-table .warn{{color:#f59e0b}}
#watch-v9-table .up{{color:#22c55e}} #watch-v9-table .down{{color:#ef4444}} #watch-v9-table .warn{{color:#f59e0b}}
#watch-table td,#watch-v9-table td{{font-variant-numeric:tabular-nums}}
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
</style></head><body>
{NAV_HTML}
<div class="container">

<!-- ============ 视图 0：监控总览 ============ -->
<div class="view active" id="view-overview">
<div class="card" id="overview">
<h2>📊 标的监控总览 <span class="badge badge-auto">数据截至 {DATA["meta"].get("as_of", "—")}{"（盘中实时）" if DATA["meta"].get("intraday") else " 收盘"}</span></h2>
<div class="sub">左侧导航切换：🅰️ 全量池中/长线（全市场自动池·股票分层+基金） / ⚡ 短线 / 🎯 打板族（过闸档位·模拟盘观察） · 信号仅供参考</div>
<div class="kpis">
<div class="kpi"><div class="l">🟢 加仓区</div><div class="v" style="color:#dc2626">{sum(1 for d in all_items if d["tier"] in ("满仓加仓","轻仓加仓"))} 只</div><div class="s">满仓+轻仓加仓</div></div>
<div class="kpi"><div class="l">🟡 观望区</div><div class="v" style="color:#d97706">{sum(1 for d in all_items if d["tier"]=="观望")} 只</div><div class="s">持有不加</div></div>
<div class="kpi"><div class="l">🔴 减/清仓区</div><div class="v" style="color:#16a34a">{sum(1 for d in all_items if d["tier"] in ("减至半仓","清仓"))} 只</div><div class="s">减半或清仓</div></div>
<div class="kpi"><div class="l">共监控</div><div class="v">{len(all_items)} 只</div><div class="s">全量池 {len(v9_items)} 行</div></div>
</div>
<div class="rule-box" style="margin-bottom:0"><b>监控口径</b>：权重分 = 动量35% + 趋势25% + Aroon20% + 量价20% ｜ 档位 = ≥75 满仓加仓 / ≥60 轻仓加仓 / ≥45 观望 / ≥30 减半 / &lt;30 清仓
<br><b>卖出闸门（每日）</b>：全量池 移动止损 4.5% + 沪深300破MA150 ｜ 任何闸门先触发先生效</div>
</div>
<!-- 🌦 市场晴雨表（niuone 口径 · 30s 实时 · 纯展示非信号） -->
<div class="card" id="mkt-weather" style="margin-top:14px">
<h2>🌦 市场晴雨表 <span class="badge badge-auto" id="mw-badge">—</span></h2>
<div class="sub">全市场情绪广度 = 红/绿盘家数 + 涨停/跌停/炸板 + 量能（照抄 niuone 口径 · 腾讯行情批量接口精算）· 交易时段每 30s 实时更新，收盘后定格静态精算 · <b>仅客观展示，不构成任何交易信号</b></div>
<div id="mw-summary" class="mw-summary">等待数据…</div>
<div id="mw-idx" class="mw-idx"></div>
<div id="mw-chart" class="mw-chart"></div>
<style>
.mw-summary{{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;padding:6px 0 10px;font-size:13px}}
.mw-big{{font-size:16px;font-weight:700;margin-right:4px}}
.mw-item{{white-space:nowrap}}
.mw-note{{color:var(--faint);font-size:11px;margin-left:auto}}
.mw-idx{{display:flex;flex-wrap:wrap;gap:6px 14px;padding:6px 0 8px;border-top:1px dashed var(--border,#e2e8f0)}}
.mw-idx-item{{font-size:12px;white-space:nowrap}}
.mw-idx-item .n{{color:var(--sub)}}
.mw-idx-item .p{{font-weight:600;margin:0 4px;font-variant-numeric:tabular-nums}}
.mw-chart{{border-top:1px dashed var(--border,#e2e8f0);padding-top:10px}}
</style>
</div>
{bt_all_html()}
{bt_short_html()}
{bt_a5_html()}
</div>
<!-- ============ 视图 A：全量池中/长线 ============ -->
{system_block(
  "view-auto", "sys-auto",
  "🅰️ 全量池中/长线", "auto", "全市场自动池 · 股票分层+基金",
  v9_items, "tbl-v9", "card-tbl-v9",
  "档位变化对比上次再平衡（07-23）· 建议动作 = 当前档位下的操作指引 · 回测参考在监控总览视图",
  extra_card=WATCH_V9_CARD,
  head_tags=[LT_GATE_BADGE,
             '<span class="badge badge-auto">评分 = Aroon强趋势过滤(A80_M78)</span>',
             '<span class="badge badge-auto">筛池 = 全市场绝对规则 Top3 等权 · 月轮动</span>',
             '<span class="badge badge-auto">风控 = 移动止损4.5% · MA200择时</span>'],
  head_note="回测参考见「监控总览」视图",
  as_of=DATA["meta"].get("as_of", "—"), intraday_note=DATA["meta"].get("intraday"),
  as_of_min=DATA["meta"].get("intraday_ts") or DATA["meta"].get("as_of_min"))}

<!-- ============ 视图 C：全量池短线（2026-09-03 起 股票池 / 基金池 分板块展示） ============ -->
{SHORT_VIEW_HTML}

<!-- ============ 视图 D：打板族（过闸档位 · 第三个系统，G3_M3 过闸 + 生产预筛模拟盘） ============ -->
{a5_view_html()}

<!-- ============ 视图 E：复盘日志（内嵌，与各池同形态） ============ -->
<div class="view" id="view-review">
{_rev_cum}
<div class="card" id="a5-review-block" style="border-color:rgba(245,158,11,.35)">
<h2>🎯 打板族（过闸档位）模拟盘验证 <span class="badge badge-auto">生产预筛口径 · 非实盘指令</span></h2>
<div class="sub">逐笔模拟盘跟踪（net_ret 含成本）· 验证门参考 = G3_M3 过闸（牛 +2.52% / 熊 +0.27%）· 30 信号或 3 个月触发判定 · 详细见「🎯 打板族」视图</div>
{A5_REVIEW_BLOCK}
</div>
<div class="card">
<h2>📋 复盘日志 <span class="badge badge-auto">{len(_rev_sorted)} 篇</span></h2>
<div class="sub">每个交易日复盘：信号标的哪些吃到 / 哪些被套 / 是否符合系统设计（对比回测基准）· 发现设计缺陷 → 启动系统更新并登记于「📝 更新日志」· 点击日期展开/折叠当日复盘详情（日期降序，最新在前）</div>
{REVIEW_LIST_HTML}
</div>
</div>

<!-- ============ 视图 F：更新日志（内嵌，GitHub release 风格） ============ -->
<div class="view" id="view-changelog">
<div class="card">
<h2>📝 更新日志 <span class="badge badge-auto">GitHub Release 风格</span></h2>
<div class="sub">版本 / 日期 / 更新内容 —— 复盘发现系统设计缺陷 → 启动量化系统更新 → 在此登记</div>
{CHANGELOG_HTML}
</div>
</div>

<!-- ============ 视图 G：评论区（Artalk） ============ -->
<div class="view" id="view-comment">
<div class="card">
<h2>💬 评论区 <span class="badge badge-auto">Artalk</span></h2>
<div class="sub">对本看板/策略的看法、问题、交流都欢迎 · 评论数据由 Artalk 后端（PostgreSQL）存储</div>
<div id="comment-area">
  <div id="Comments"></div>
  <div id="comment-loading">💬 评论加载中…<span class="comment-loading-sub">（首次打开可能需要 30-60 秒，后端为 Render 免费层，闲置后休眠唤醒）</span></div>
</div>
<style>
#comment-loading{{display:none;flex-direction:column;align-items:center;gap:6px;padding:36px 12px;color:var(--faint,#888);font-size:14px;border:1px dashed var(--line,#ddd);border-radius:12px;margin-top:12px}}
#comment-loading .comment-loading-sub{{font-size:12px;opacity:.75}}
</style>
</div>
</div>

</div>
<div class="sub" style="text-align:center;color:var(--faint);font-size:11px;padding:8px 0 4px">看板构建于 {build_ts} · 版本 v5.12.0（+🌦市场晴雨表） · 数据截至 {DATA["meta"].get("as_of", "—")} · 若页面与预期不符请 Ctrl+F5 强制刷新</div>
<!-- 到顶/到底浮动按钮 -->
<div class="scroll-fab">
<button title="回到顶部" onclick="window.scrollTo({{top:0,behavior:'smooth'}})">↑</button>
<button title="滚到底部" onclick="window.scrollTo({{top:document.body.scrollHeight,behavior:'smooth'}})">↓</button>
</div>
<script src="enhanced_data.js"></script>
<script src="short_signals.js"></script>
<script src="a5_pool.js"></script>
<script src="market_breadth.js"></script>
<script src="market_weather.js"></script>
<link rel="stylesheet" href="https://unpkg.com/artalk@2/dist/Artalk.css">
<script src="https://unpkg.com/artalk@2/dist/Artalk.js"></script>
<script>window.SHORT_POOL = {SHORT_POOL_SLIM};</script>
<script>
/* 三视图导航（覆盖默认 4 项） */
window.ENH.nav = [
  ["overview","📊","监控总览",[["overview","总览统计"],["mkt-weather","市场晴雨表"],["bt-all","回测参考·中长线"],["bt-short","短线回测"]]],
  ["sys-auto","🅰️","全量池中/长线",[["card-tbl-v9","标的汇总表"],["card-tbl-v9-detail","逐标的详情"],["watch-v9-card","中长线跟踪"]]],
  ["short","⚡","全量池短线",[["card-short-stk","📋 股票池 汇总表"],["card-short-stk-detail","🔍 股票池 逐标的详情"],["card-short-fund","📋 基金池 汇总表"],["card-short-fund-detail","🔍 基金池 逐标的详情"],["watch-card","📌 短线跟踪"]]],
  ["a5","🎯","打板族",[["a5-watchlist","观察清单"],["a5-avoid","回避清单"],["a5-positions","持仓"],["a5-closed","已平仓"],["a5-curve","净值曲线"]]],
  ["comment","💬","评论区",[]]
];
/* 视图切换模式：滚动不更新导航高亮（COMMON_JS renderSidenav 检测此标志） */
window.ENH.NAV_SWITCH = true;
/* 三池回测净值（股票/基金，监控总览展示；2026-08-17 去 ETF） */
window.ENH.sub_curves = {{
  stock: {json.dumps(DATA["systems"]["v9_auto"]["equity"])},
  fund: {json.dumps(v_fund)},
  short_fund: {json.dumps(v_short_fund)},
  short_stock: {json.dumps(v_short_stock)},
  stk_all: {json.dumps(v9split_curves["all"])}, stk_main: {json.dumps(v9split_curves["main_only"])},
  stk_gem: {json.dumps(v9split_curves["gem_only"])}, stk_star: {json.dumps(v9split_curves["star_only"])},
  sstk_all: {json.dumps(shortsplit_curves["all"])}, sstk_main: {json.dumps(shortsplit_curves["main_only"])},
  sstk_gem: {json.dumps(shortsplit_curves["gem_only"])}, sstk_star: {json.dumps(shortsplit_curves["star_only"])},
}};
/* 渲染 基金回测净值曲线（各自容器、各自对数坐标轴） */
function renderOneCurve(elId, vals, color, label, totalPct){{
  var el=document.getElementById(elId);if(!el)return;
  if(!vals||!vals.length){{ /* 未回测/无修正口径：画占位文字 */
    el.innerHTML='<svg viewBox="0 0 1400 240" style="width:100%;height:auto"><text x="700" y="120" font-size="15" fill="#9ca3af" text-anchor="middle">未回测 · 用户仅可买主板（KHunter 主信号按主板回测，见卡片 KPI）</text></svg>';
    return;
  }}
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
  renderOneCurve('curve-chart-fund', C.fund, '#3b82f6', '基金池', '+'+{s_fund["total_return_pct"]:.0f});
  renderOneCurve('curve-short-stock-all', C.short_stock, '#f59e0b', '短线 股票 一体', '{(ss_stk["all"].get("total_return_pct") or 0):+.0f}');
  renderOneCurve('curve-short-stock-main', [], '#ea580c', '短线 纯主板（KHunter）', '无净值曲线');
  renderOneCurve('curve-short-stock-gem', [], '#22c55e', '短线 纯创业板', '未回测');
  renderOneCurve('curve-short-stock-star', [], '#8b5cf6', '短线 纯科创板', '未回测');
  renderOneCurve('curve-short-fund', C.short_fund, '#3b82f6', '基金短线', '{ss_fund["total_return_pct"]:+.0f}');
}}
/* 视图切换（hash 驱动：切换时更新 location.hash，加载/前进后退时按 hash 定位） */
var VIEW_MAP={{'overview':'view-overview','sys-auto':'view-auto','short':'view-short','a5':'view-a5','review':'view-review','changelog':'view-changelog','comment':'view-comment'}};
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
/* Artalk 评论（PostgreSQL 后端；server 占位，部署后替换为 Artalk 服务直链如 https://xxx.hf.space） */
var _sw0=switchView;
function initComment(){{
  if(window.__artalkInit)return;
  var el=document.getElementById('Comments');if(!el)return;
  window.__artalkInit=true;
  if(typeof Artalk!=='undefined'){{
    Artalk.init({{
      el: '#Comments',
      server: 'https://artalk-8iqt.onrender.com',   // ⚠ Artalk 后端（Render 免费层，2026-08-19 上线）
      site: '量化权重监控',
      pageKey: 'quant-weight-system',
      pageTitle: document.title,
      locale: 'zh-CN',
    }});
  }}
}}
/* 评论加载占位：Artalk 冷启动期间（后台 conf 请求等待）#Comments 为空，
   MutationObserver 监测渲染完成后隐藏"加载中"提示 */
function watchCommentLoading(){{
  var el=document.getElementById('Comments');
  var ld=document.getElementById('comment-loading');
  if(!el||!ld)return;
  var upd=function(){{
    var children=el.childElementCount>0 && el.querySelector('.atk-main-editor,.atk-list,textarea,.atk-name');
    ld.style.display=(children)?'none':'flex';
  }};
  upd();
  new MutationObserver(upd).observe(el,{{childList:true,subtree:true,attributes:false}});
}}
switchView=function(key){{
  _sw0(key);
  if(key==='comment'){{initComment();watchCommentLoading();}}
}};
</script>
<script>
{COMMON_JS}
/* 覆盖：左侧导航点击切换视图 */
document.addEventListener('DOMContentLoaded',function(){{
  applyHash();   // 按 URL hash 定位视图（历史页跳转 dual_system.html#sys-auto 直接显示普适版）
  renderSubCurve();   // 基金回测净值曲线
  /* 全量池短线跟踪：自动跟踪池（SHORT_POOL.track，可买入标的 30 天）+ 可选手动补充（localStorage） */
  /* 2026-09-05 用户需求：交易权限徽章（主板无门槛/创业板 2年+10万/科创板 2年+50万/北交所 2年+50万） */
  function permOf(code){{
    code=String(code||'');if(code.length>6)code=code.slice(-6);
    if(code.indexOf('688')===0)return '<span class="board-tag board-kc" title="科创板：需 2 年交易经验 + 50 万资产">2年+50万</span>';
    if(code.indexOf('30')===0)return '<span class="board-tag board-cy" title="创业板：需 2 年交易经验 + 10 万资产">2年+10万</span>';
    if(code.indexOf('8')===0||code.indexOf('4')===0||code.indexOf('92')===0)return '<span class="board-tag board-bj" title="北交所：需 2 年交易经验 + 50 万资产">2年+50万</span>';
    return '<span class="board-tag board-sh" title="主板/ETF/基金：无开通门槛">无门槛</span>';
  }}
  function boardCell(v){{
    var cls={{'主板':'board-sh','创业板':'board-cy','科创板':'board-kc','北交所':'board-bj'}}[v]||'';
    return v?'<span class="board-tag '+cls+'">'+v+'</span>':'—';
  }}
  function fillTierOptions(selId,tiers){{
    var sel=document.getElementById(selId);if(!sel)return;
    var cur=sel.value;
    var seen={{}};var opts=[];
    tiers.forEach(function(t){{if(t&&!seen[t]){{seen[t]=1;opts.push(t);}}}});
    var html='<option value="">全部档位</option>'+opts.map(function(t){{return '<option value="'+t+'">'+t+'</option>';}}).join('');
    if(sel.innerHTML!==html){{sel.innerHTML=html;if(cur)sel.value=cur;}}
  }}
  function renderWatch(){{
    var box=document.getElementById('watch-table');if(!box)return;
    var S=window.SHORT_SIGNALS;if(!S){{box.innerHTML='<div class="sub">信号数据未加载（缺 short_signals.js）</div>';return;}}
    var track=(window.SHORT_POOL&&window.SHORT_POOL.track)?window.SHORT_POOL.track:{{}};
    // 2026-08-19 市况门控口径统一：门控关闭时跟踪池档位已改写「不开新仓·仅跟踪」，顶部横幅提示
    var _mg=(window.SHORT_POOL&&window.SHORT_POOL.market_gate)||{{}};
    var _gateOpen=_mg.open;
    var _gateBox=document.getElementById('watch-gate');
    if(_gateBox){{
      if(_gateOpen===false){{
        _gateBox.innerHTML='<div class="sub" style="margin-bottom:6px;color:#d97706">⚠ 市况门控关闭（沪深300 '+( _mg.idx_close!=null?_mg.idx_close:'—')+' < MA20 '+( _mg.idx_ma20!=null?_mg.idx_ma20:'—')+'）—— 已入池跟踪标的仅跟踪卖出信号，「不开新仓·仅跟踪」（安全口径，非买入）</div>';
      }}else{{_gateBox.innerHTML='';}}
    }}
    // 待确认（pending）：当日新上榜、下个收盘确认后入正式池（2026-08-18 用户需求，与中长线一致）
    var pnd=(window.SHORT_POOL&&window.SHORT_POOL.track_pending_short)?window.SHORT_POOL.track_pending_short:{{}};
    var pendBox=document.getElementById('watch-pending');
    var pkeys=Object.keys(pnd);
    if(pendBox){{
      if(pkeys.length){{
        var ph='<div class="sub" style="margin-bottom:6px;color:#d97706">⏳ 待确认 '+pkeys.length+' 只 —— 上榜后下一收盘确认在池再入池（隔离当日信号）</div><table class="tbl"><tbody>';
        pkeys.forEach(function(c){{
          var p=pnd[c]||{{}};var last=p.last||{{}};
          var nm=last.name||c;
          var pt=(last.score!==undefined&&last.score!==null)?last.score:'—';
          var pt2=last.tier||'—';
          ph+='<tr><td>'+c+'</td><td>'+nm+'</td><td style="text-align:center">'+(last.pool||p.pool||'')+'</td><td style="text-align:center">'+(p.entry_candidate||'—')+'</td><td style="text-align:right">'+pt+'</td><td style="text-align:center">'+pt2+'</td></tr>';
        }});
        ph+='</tbody></table>';
        pendBox.innerHTML=ph;
      }} else {{pendBox.innerHTML='';}}
    }}
    var now=new Date();var base=[];
    Object.keys(track).forEach(function(code){{
      var t=track[code]||{{}};var entry=t.entry?new Date(String(t.entry).replace(/-/g,'/')):null;
      var age=entry?Math.floor((now-entry)/86400000):0;
      if(age>=30)return;   // 30 天过期（前端兜底，与服务端一致）
      base.push({{code:code,entry:t.entry||'—',exit:t.exit||'—',age:age,type:t.type||'',pool:t.pool||''}});
    }});
    var bar=document.getElementById('watch-bar');
    var topSet={{}};
    if(window.SHORT_POOL){{Object.keys(window.SHORT_POOL.tiers||{{}}).forEach(function(g){{(window.SHORT_POOL.tiers[g]||[]).forEach(function(c){{topSet[c]=1;}});}});}}
    // 解析信号数据（名称/涨跌/分/档位），未找到代码的单独标记
    var rows=[];
    base.forEach(function(r){{
      var code=r.code,rec=null,grp='';
      if(r.type==='stock'||r.type==='fund'){{if(S[r.type]&&S[r.type][code]){{rec=S[r.type][code];grp=r.type;}}}}
      if(!rec&&S.stock&&S.stock[code]){{rec=S.stock[code];grp='stock';}}
      if(!rec&&S.fund&&S.fund[code]){{rec=S.fund[code];grp='fund';}}
      if(!rec){{rows.push({{code:code,entry:r.entry,exit:r.exit||'—',age:r.age,grp:grp,typeName:r.pool||'股票',rec:null,inPool:0}});return;}}
      var act,actCls,tierDisp=rec.tier;
      // 2026-09-04 新增（grill Q1-2/Q2-1）：标准版/激进版 双档位判定
      // 标准版档位/动作沿用现有语义；激进版=KHunter RSI>50 参考卖出（c_sell，与标准版独立）
      var kh=rec.khunter||{{}};
      var tierC='—',actC='—',actCCls='';
      if(kh.c_sell){{tierC='激进:卖出';actC='🔴 激进版·卖出';actCCls='down';}}
      else if(kh.sell){{tierC='激进:卖出';actC='🔴 激进版·卖出';actCCls='down';}}
      else if(kh.buy){{tierC='激进:持有';actC='🟢 激进版·持有/跟踪';actCCls='up';}}
      else if(kh.c_sell===false||kh.sell===false){{tierC='激进:持有';actC='🟢 激进版·持有/跟踪';actCCls='up';}}
      // 2026-08-27 修复：停牌股（suspended）——持仓股停牌期间仍需跟踪卖出信号，显示「停牌·复牌后跟踪」
      if(rec.suspended){{act='⏸ 停牌·复牌后跟踪';actCls='warn';tierDisp='停牌';}}
      // 2026-08-26 修复：破MA5（收盘价<MA5）为硬性退出规则，档位同步改写「破MA5·卖出」，避免与建议动作「次日卖出」展示冲突
      else if(rec.ma5_above===false){{act='⚠️ 次日卖出（破MA5）';actCls='down';tierDisp='破MA5·卖出';}}
      else if(rec.tier==='清仓'){{act='🔴 清仓';actCls='down';}}
      else if(rec.tier==='减至半仓'){{act='🔴 减至半仓';actCls='down';}}
      // 2026-09-04 修复（grill Q1）：KHunter 主信号买入档必须显示为买入信号（原落进「观望」兜底）
      else if(rec.tier==='强买入'){{act='🟢 强买入信号（KHunter）';actCls='up';}}
      else if(rec.tier==='买入'){{act='🟢 买入信号（KHunter）';actCls='up';}}
      else if(!topSet[code]){{act='🔄 下次轮动换出';actCls='warn';}}
      else if(rec.tier==='轻仓加仓'||rec.tier==='满仓加仓'){{act='✅ 继续持有';actCls='up';}}
      else {{act='🟡 观望（不补不加）';actCls='warn';}}
      var typeName=(grp==='fund'||r.type==='fund')?'基金':(r.pool||'股票');   // 2026-08-18 用户需求：股票类型按权限细分（主板/创业板/科创板）
      rows.push({{code:code,entry:r.entry,exit:r.exit||'—',age:r.age,grp:grp,typeName:typeName,pool:r.pool,rec:rec,act:act,actCls:actCls,inPool:topSet[code]?1:0,tierDisp:tierDisp,tierC:tierC,actC:actC,actCCls:actCCls}});
    }});
    if(bar){{bar.style.display=rows.length?'':'none';}}
    if(!rows.length){{box.innerHTML='<div class="sub" style="color:var(--faint)">暂无跟踪 —— 短线表出现可买入标的（强买入/买入）后自动加入，保留 30 天</div>';return;}}
    // 读筛选/排序（uncontrolled，每次渲染读取 DOM）
    var q=(document.getElementById('watch-q').value||'').trim().toLowerCase();
    var ftype=document.getElementById('watch-f-type').value;
    var fpool=document.getElementById('watch-f-inpool').value;
    var ftier=document.getElementById('watch-f-tier').value;
    var sortKey=document.getElementById('watch-sort').value||'entry';
    fillTierOptions('watch-f-tier', rows.map(function(r){{return r.tierDisp||null;}}));
    var seenType={{}};var typeOpts=[];
    rows.forEach(function(r){{if(r.typeName&&!seenType[r.typeName]){{seenType[r.typeName]=1;typeOpts.push(r.typeName);}}}});
    var tsel=document.getElementById('watch-f-type');
    if(tsel){{var tcur=tsel.value;
      var th='<option value="">全部类型</option>'+typeOpts.map(function(t){{return '<option value="'+t+'">'+t+'</option>';}}).join('');
      if(tsel.innerHTML!==th){{tsel.innerHTML=th;if(tcur)tsel.value=tcur;}}}}
    var filtered=rows.filter(function(r){{
      if(!r.rec)return false;
      if(q&&!(r.code.toLowerCase().indexOf(q)>=0||(r.rec.name||'').toLowerCase().indexOf(q)>=0))return false;
      if(ftype&&r.typeName!==ftype)return false;
      if(fpool!==''&&String(r.inPool)!==fpool)return false;
      if(ftier&&(r.tierDisp||'')!==ftier)return false;
      return true;
    }});
    filtered.sort(function(a,b){{
      if(sortKey==='name'){{return (a.rec.name||'').localeCompare(b.rec.name||'');}}
      if(sortKey==='chg'){{return (b.rec.chg||-999)-(a.rec.chg||-999);}}
      if(sortKey==='score'){{return (b.rec.score||-999)-(a.rec.score||-999);}}
      if(sortKey==='left'){{return a.age-b.age;}}
      var da=a.entry&&a.entry!=='—'?new Date(String(a.entry).replace(/-/g,'/')):null;
      var db=b.entry&&b.entry!=='—'?new Date(String(b.entry).replace(/-/g,'/')):null;
      if(!da&&!db)return 0;if(!da)return 1;if(!db)return -1;return db-da;
    }});
    var cnt=document.getElementById('watch-count');
    if(cnt)cnt.textContent='筛选 '+filtered.length+' / 共 '+rows.length+' 只';
    if(!filtered.length){{box.innerHTML='<div class="sub" style="color:var(--faint)">无匹配标的 —— 调整搜索/筛选条件后重试</div>';return;}}
    var h='<div class="sub" style="margin-bottom:6px;color:var(--sub)">🧭 版本说明：<b>标准版</b>=生产主信号（熊市卖出 RSI&gt;55 / 牛市卖出 RSI&gt;75）；<b>激进版</b>=参考线（RSI&gt;50 卖出，更早止盈高周转）—— 双版本并行对决；卖出为独立信号，不含买入含义</div>'
          +'<table class="tbl"><thead><tr><th>代码</th><th>名称</th><th>类型</th><th>权限</th><th>行业</th><th style="text-align:center">入池日期</th><th style="text-align:center">出池日期</th><th style="text-align:center">已跟踪</th><th style="text-align:right">现价</th><th style="text-align:right">涨跌</th><th style="text-align:center">短线分</th><th style="text-align:center">档位(标准版)</th><th style="text-align:center">建议(标准版)</th><th style="text-align:center">档位(激进版)</th><th style="text-align:center">建议(激进版)</th><th style="text-align:center">MA5</th></tr></thead><tbody>';
    filtered.forEach(function(r){{
      var rec=r.rec;
      var ageS=r.age===null?'—':(r.age+' 天 / 剩 '+(30-r.age)+' 天');
      // 2026-08-27 修复：停牌股显示「⏸ 停牌」徽章，涨跌/MA5 置「—」（旧数据不误导）
      var susp=rec.suspended;
      var nameDisp=rec.name+(susp?' <span class="badge badge-warn" style="background:var(--warn-bg,#fef3c7);color:#92400e;font-size:11px;padding:1px 6px;border-radius:8px;margin-left:4px">⏸ 停牌</span>':'');
      var chgDisp=susp?'停牌':((rec.chg>0?'+':'')+rec.chg+'%');
      var chgCls=susp?'':(rec.chg>0?'up':'down');
      var ma5Disp=susp?'—':(rec.ma5_above?'✅ 上方':'⚠️ 下方');
      // 2026-09-05 用户需求：跟踪池统一格式（权限/行业列）
      var ind=(window.SHORT_POOL&&window.SHORT_POOL.details&&window.SHORT_POOL.details[r.code])?(window.SHORT_POOL.details[r.code].industry||'—'):'—';
      // 2026-09-04（grill Q2-1）：标准/激进双列（激进列对非 KHunter 标的显示 —）
      var tierCDisp=r.tierC||'—'; var actCDisp=r.actC||'—'; var actCCls=r.actCCls||'';
      h+='<tr><td>'+r.code+'</td><td>'+nameDisp+'</td><td>'+r.typeName+'</td><td>'+permOf(r.code)+'</td><td>'+ind+'</td><td style="text-align:center">'+r.entry+'</td><td style="text-align:center">'+(r.exit||'—')+'</td><td style="text-align:center">'+ageS+'</td><td style="text-align:right">'+rec.px+'</td><td style="text-align:right" class="'+chgCls+'">'+chgDisp+'</td><td style="text-align:center">'+rec.score+'</td><td style="text-align:center">'+r.tierDisp+'</td><td style="text-align:center" class="'+r.actCls+'">'+r.act+'</td><td style="text-align:center">'+tierCDisp+'</td><td style="text-align:center" class="'+actCCls+'">'+actCDisp+'</td><td style="text-align:center">'+ma5Disp+'</td></tr>';
    }});
    h+='</tbody></table>';
    box.innerHTML=h;
  }}
  // 2026-08-17 用户决策：移除手动补充功能，顺带清理旧 localStorage 残留（含用户误加的"金安国纪"条目）
  try{{localStorage.removeItem('short_watchlist');}}catch(_e){{}}
  ['watch-q','watch-f-type','watch-f-inpool','watch-f-tier','watch-sort'].forEach(function(id){{
    var el=document.getElementById(id);if(!el)return;
    el.addEventListener(id==='watch-q'?'input':'change',renderWatch);
  }});
  renderWatch();
  /* 全量池中/长线年跟踪池（2026-08-17 用户需求：上榜 1 年，再上榜 +1 年；数据由 build_enhanced_data.py 维护） */
  function renderV9Watch(){{
    var box=document.getElementById('watch-v9-table');if(!box)return;
    var E=window.ENH;if(!E||!E.track_v9){{box.innerHTML='<div class="sub">暂无跟踪数据</div>';return;}}
    var track=E.track_v9||{{}};
    var inPool={{}};
    var t9=E.meta&&E.meta.v9_tiers?E.meta.v9_tiers:{{}};
    Object.keys(t9).forEach(function(g){{(t9[g]||[]).forEach(function(c){{inPool[c]=1;}});}});
    var now=new Date();var rows=[];
    // 待确认（pending）：今日/前几日上榜、下个收盘确认后入正式池
    var pendBox=document.getElementById('watch-v9-pending');
    var pnd=E.track_pending_v9||{{}};
    var pkeys=Object.keys(pnd);
    if(pendBox){{
      if(pkeys.length){{
        var ph='<div class="sub" style="margin-bottom:6px;color:#d97706">⏳ 待确认 '+pkeys.length+' 只 —— 上榜后下一收盘确认在榜再入池（隔离当日信号）</div><table class="tbl"><tbody>';
        pkeys.forEach(function(c){{
          var p=pnd[c]||{{}};var last=p.last||{{}};var nm=last.name||(E.details&&E.details[c]&&E.details[c].name)||c;
          ph+='<tr><td>'+c+'</td><td>'+nm+'</td><td style="text-align:center">'+p.pool+'</td><td style="text-align:center">'+(p.entry_candidate||'—')+'</td><td style="text-align:right">'+(last.px!==undefined&&last.px!==null?last.px.toFixed(2):'—')+'</td><td style="text-align:center">'+(last.tier||'—')+'</td></tr>';
        }});
        ph+='</tbody></table>';
        pendBox.innerHTML=ph;
      }} else {{pendBox.innerHTML='';}}
    }}
    Object.keys(track).forEach(function(code){{
      var t=track[code]||{{}};var entry=t.entry?new Date(String(t.entry).replace(/-/g,'/')):null;
      var age=entry?Math.floor((now-entry)/86400000):0;
      var live=E.details&&E.details[code];
      var rec=live||t.last||{{}};
      // 2026-08-18：track 条目自带 name（掉出池标的不在 details）；名称兜底 t.name，避免显示 —/代码
      if(!rec.name){{rec.name=t.name||code;}}
      var chg=(rec.chg!==undefined&&rec.chg!==null)?rec.chg:null;
      var score=(rec.score!==undefined&&rec.score!==null)?rec.score:null;
      rows.push({{code:code,entry:t.entry||'—',exit:t.exit||'—',age:age,pool:t.pool||'—',rec:rec,chg:chg,score:score,inPool:inPool[code]?1:0}});
    }});
    var bar=document.getElementById('watch-v9-bar');
    if(bar){{bar.style.display=rows.length?'':'none';}}
    if(!rows.length){{box.innerHTML='<div class="sub" style="color:var(--faint)">暂无跟踪 —— 全量池中/长线上榜标的自动加入，保留 1 年</div>';return;}}
    // 板块选项动态重建（保留当前选择）
    var pools=[];var seenPool={{}};
    rows.forEach(function(r){{if(r.pool&&r.pool!=='—'&&!seenPool[r.pool]){{seenPool[r.pool]=1;pools.push(r.pool);}}}});
    var psel=document.getElementById('watch-v9-f-pool');
    if(psel){{var pcur=psel.value;
      var ph='<option value="">全部板块</option>'+pools.map(function(p){{return '<option value="'+p+'">'+p+'</option>';}}).join('');
      if(psel.innerHTML!==ph){{psel.innerHTML=ph;if(pcur)psel.value=pcur;}}}}
    fillTierOptions('watch-v9-f-tier', rows.map(function(r){{return r.rec.tier||null;}}));
    // 读筛选/排序（uncontrolled）
    var q=(document.getElementById('watch-v9-q').value||'').trim().toLowerCase();
    var fpool=document.getElementById('watch-v9-f-pool').value;
    var fstatus=document.getElementById('watch-v9-f-status').value;
    var ftier=document.getElementById('watch-v9-f-tier').value;
    var sortKey=document.getElementById('watch-v9-sort').value||'entry';
    var filtered=rows.filter(function(r){{
      var nm=r.rec.name||'';
      if(q&&!(r.code.toLowerCase().indexOf(q)>=0||nm.toLowerCase().indexOf(q)>=0))return false;
      if(fpool&&r.pool!==fpool)return false;
      if(fstatus!==''&&String(r.inPool)!==fstatus)return false;
      if(ftier&&(r.rec.tier||'')!==ftier)return false;
      return true;
    }});
    filtered.sort(function(a,b){{
      if(sortKey==='name'){{return (a.rec.name||'').localeCompare(b.rec.name||'');}}
      if(sortKey==='chg'){{var ac=a.chg===null?-999:a.chg,bc=b.chg===null?-999:b.chg;return bc-ac;}}
      if(sortKey==='score'){{var as=a.score===null?-999:a.score,bs=b.score===null?-999:b.score;return bs-as;}}
      if(sortKey==='left'){{return a.age-b.age;}}
      var da=a.entry!=='—'?new Date(String(a.entry).replace(/-/g,'/')):null;
      var db=b.entry!=='—'?new Date(String(b.entry).replace(/-/g,'/')):null;
      if(!da)return 1;if(!db)return -1;return db-da;
    }});
    var cnt=document.getElementById('watch-v9-count');
    if(cnt)cnt.textContent='筛选 '+filtered.length+' / 共 '+rows.length+' 只';
    if(!filtered.length){{box.innerHTML='<div class="sub" style="color:var(--faint)">无匹配标的 —— 调整搜索/筛选条件后重试</div>';return;}}
    var h='<table class="tbl"><thead><tr><th>代码</th><th>名称</th><th>板块</th><th>权限</th><th>行业</th><th style="text-align:center">入池日期</th><th style="text-align:center">出池日期</th><th style="text-align:center">已跟踪</th><th style="text-align:right">现价</th><th style="text-align:right">涨跌</th><th style="text-align:center">权重分</th><th style="text-align:center">档位</th><th style="text-align:center">状态</th></tr></thead><tbody>';
    filtered.forEach(function(r){{
      var rec=r.rec;var px=(rec.px!==undefined&&rec.px!==null)?rec.px:null;
      var ageS=r.age+' 天 / 剩 '+(365-r.age)+' 天';
      var exitT=r.exit||'—';
      var status=r.inPool?'<span style="color:#dc2626;font-weight:600">在池</span>':'<span style="color:var(--faint)">已掉出池（观察）</span>';
      // 2026-09-05 用户需求：跟踪池统一格式（权限/行业列）
      var ind=(E.details&&E.details[r.code])?(E.details[r.code].industry||'—'):'—';
      h+='<tr><td>'+r.code+'</td><td>'+(rec.name||'—')+'</td><td>'+boardCell(r.pool)+'</td><td>'+permOf(r.code)+'</td><td>'+ind+'</td><td style="text-align:center">'+r.entry+'</td><td style="text-align:center">'+exitT+'</td><td style="text-align:center">'+ageS+'</td>'+
         '<td style="text-align:right">'+(px===null?'—':px.toFixed(2))+'</td>'+
         '<td style="text-align:right" class="'+(r.chg===null?'':(r.chg>0?'up':'down'))+'">'+(r.chg===null?'—':(r.chg>0?'+':'')+r.chg.toFixed(2)+'%')+'</td>'+
         '<td style="text-align:center">'+(r.score===null?'—':r.score.toFixed(1))+'</td>'+
         '<td style="text-align:center">'+(rec.tier||'—')+'</td><td style="text-align:center">'+status+'</td></tr>';
    }});
    h+='</tbody></table>';
    box.innerHTML=h;
  }}
  ['watch-v9-q','watch-v9-f-pool','watch-v9-f-status','watch-v9-f-tier','watch-v9-sort'].forEach(function(id){{
    var el=document.getElementById(id);if(!el)return;
    el.addEventListener(id==='watch-v9-q'?'input':'change',renderV9Watch);
  }});
  renderV9Watch();
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
      e.preventDefault();var t=a.getAttribute('data-anchor');switchView(t);
      document.querySelectorAll('#sidenav a[data-anchor]').forEach(function(x){{x.classList.toggle('active',x===a);}});
      // 子项点击时父主项保持高亮（2026-08-17）
      if(a.getAttribute('data-sub')&&a.parentNode&&a.parentNode.classList.contains('sn-sub')){{
        var pm=document.querySelector('#sidenav a[data-anchor="'+t+'"]:not([data-sub])');
        if(pm)pm.classList.add('active');}}}});}});
  initTable('tbl-v9', {{columns: {{rank:0, name:1, board:2, industry:3, px:4, chg:5, ret1y:6, score:7, rsi:8, vp:9, conf:10, tier:11, tierchg:12, action:13}}}});
  initTable('tbl-short-stk', {{columns: {{rank:0, name:1, board:2, industry:3, px:4, chg:5, ret1y:6, score:7, rsi:8, vp:9, conf:10, tier:11, tierchg:12, action:13}}}});
  initTable('tbl-short-fund', {{columns: {{rank:0, name:1, board:2, industry:3, px:4, chg:5, ret1y:6, score:7, rsi:8, vp:9, conf:10, tier:11, tierchg:12, action:13}}}});
  /* A5 打板实验四表：与 v9/短线池同标准——表头排序 + 搜索 + 板块/行业筛选（2026-08-28） */
  initTable('a5-wl', {{columns: {{code:0, name:1, board:2, sbdate:3, relpos:4, amt:5, chg:6, ret1y:7, rsi:8, vr:9, ma5dev:10}}}});
  initTable('a5-av', {{columns: {{code:0, name:1, board:2, sbdate:3, gap:4, relpos:5, amt:6, chg:7, ret1y:8, rsi:9, vr:10, ma5dev:11}}}});
  initTable('a5-pos', {{columns: {{code:0, name:1, board:2, entrydate:3, entrypx:4, gap:5, stage:6, chg:7, ret1y:8, rsi:9, vr:10, ma5dev:11}}}});
  initTable('a5-cl', {{columns: {{code:0, name:1, board:2, entrydate:3, exitdate:4, entrypx:5, exitpx:6, reason:7, netret:8, chg:9, ret1y:10, rsi:11, vr:12}}}});
  ['a5-wl','a5-av','a5-pos','a5-cl'].forEach(function(id){{
    var q=document.getElementById(id+'-q'), mk=document.getElementById(id+'-mk'), ind=document.getElementById(id+'-ind');
    function applyA5(){{
      var rows=document.querySelectorAll('#'+id+' tbody tr');var n=0;
      rows.forEach(function(tr){{
        var txt=(tr.getAttribute('data-search')||'').toLowerCase();
        var qv=(q?q.value:'').toLowerCase(), mv=mk?mk.value:'', iv=ind?ind.value:'';
        var ok=(!qv||txt.indexOf(qv)>=0)&&(!mv||tr.getAttribute('data-market')===mv)&&(!iv||tr.getAttribute('data-industry')===iv);
        tr.style.display=ok?'':'none';if(ok)n++;
      }});
      var cnt=document.getElementById(id+'-count');
      if(cnt)cnt.textContent='显示 '+n+' / '+rows.length+' 只';
    }}
    if(q)q.addEventListener('input',applyA5);
    if(mk)mk.addEventListener('change',applyA5);
    if(ind)ind.addEventListener('change',applyA5);
  }});
  /* 统一联动：搜索 + 板块/行业/档位筛选 → 表格行 + 详情卡片同步；排序后卡片重排 */
  ['tbl-v9','tbl-short-stk','tbl-short-fund'].forEach(function(id){{
    var q=document.getElementById(id+'-q'), mk=document.getElementById(id+'-mk');
    var ind=document.getElementById(id+'-ind'), tier=document.getElementById(id+'-tier');
    var buyonly=document.getElementById(id+'-buyonly');
    var cardsBox=document.getElementById(id+'-cards');
    var buyOnlyOn=false;
    function match(el){{
      var txt=(el.getAttribute('data-search')||'').toLowerCase();
      var qv=(q?q.value:'').toLowerCase();
      var mv=mk?mk.value:'', iv=ind?ind.value:'', tv=tier?tier.value:'';
      var t2=el.getAttribute('data-tier');
      return (!qv||txt.indexOf(qv)>=0)
        &&(!mv||el.getAttribute('data-market')===mv)
        &&(!iv||el.getAttribute('data-industry')===iv)
        &&(!tv||t2===tv)
        &&(!buyOnlyOn||(t2!=='减至半仓'&&t2!=='清仓'));
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
    if(buyonly)buyonly.addEventListener('click',function(){{
      buyOnlyOn=!buyOnlyOn;
      buyonly.style.borderColor=buyOnlyOn?'var(--accent)':'';
      buyonly.style.color=buyOnlyOn?'var(--accent)':'';
      applyAll();
    }});
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

# --- 防御性 HTML 校验（2026-09-04 新增：防未转义尖括号破坏 DOM）---
import re as _re
# 先剔除 <script>...</script> 块（块内 JS 比较符 < 合法，不参与 HTML 文本校验）
_text_only = _re.sub(r'<script\b[^>]*>.*?</script\s*>', '', html, flags=_re.S)
_bad = []
for _m in _re.finditer(r'<(?![a-zA-Z/!]|!DOCTYPE|!--)([^>\n]{0,40})', _text_only):
    _seg = _m.group(0)
    # HTML 文本中 < 后跟字母/数字但非标签开头（如 <MA60) → 未转义风险）
    _after = _text_only[_m.start()+1:_m.start()+12]
    if _after and _after[0].isalnum() and not _re.match(r'^[a-zA-Z][a-zA-Z0-9-]*[\s/>]', _after):
        _bad.append(f"@{_m.start()}: {_seg!r}")
if _bad:
    print(f"⚠ 警告：检测到 {len(_bad)} 处疑似未转义 '<'（可能破坏 HTML 结构）：")
    for _b in _bad[:10]:
        print(f"  {_b}")
else:
    print("✅ HTML 转义校验通过：无未转义 '<'（已豁免 <script> 块内 JS 比较符）")
# 终局 div 平衡粗校验
_dep = 0
for _m in _re.finditer(r'<div\b[^>]*>|</div\s*>', html):
    _dep += -1 if _m.group(0).startswith('</') else 1
    if _dep < 0:
        print("⚠ div 深度变负（嵌套错位）！")
        break
print(f"✅ div 平衡校验: 终局深度 {_dep}")
print(f"  普适版表: {len(v9_items)} 行（{ {k:len(v) for k,v in v9_tiers.items()} }） | 中长线跟踪池: {track_v9_len} 只")