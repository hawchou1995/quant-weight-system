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
from kxmm_card import KXMM_CSS, KXMM_VIEW_HTML, KXMM_JS
from ui_subtab import SUBNAV_CSS, SUBNAV_JS, subnav, subview, ASSET_HINT
from intraday_live import INTRADAY_JS, QLCH_JS


def _crowding():
    """大盘拥挤度（代理口径 · 2026-09-18 用户需求 #11）。

    三成分全部来自已有产物（不新建数据依赖）：
      量能分位 45% — 沪深300 成交量 20 日分位（index_000300.csv volume 列）
      趋势乖离 35% — 沪深300 收盘相对 MA20 乖离，±5% 映射 0~100
      情绪温度 20% — kxmm 恐贪指数（kxmm_data.js fear_greed.base.num）
    定位：风险提示，不是买卖信号。
    """
    import csv as _csv
    out = {"score": None, "vol_pct": None, "bias": None, "fg": None, "n": 0}
    try:
        rows = []
        with open(BASE / "index_000300.csv", encoding="utf-8") as fh:
            for r in _csv.DictReader(fh):
                rows.append(r)
        rows = [r for r in rows if r.get("close")][-40:]
        out["n"] = len(rows)
        if len(rows) >= 25:
            vols = [float(r["volume"]) for r in rows[-20:]]
            hist = [float(r["volume"]) for r in rows]
            cur = vols[-1]
            out["vol_pct"] = round(sum(1 for v in hist if v <= cur) / len(hist) * 100, 1)
            closes = [float(r["close"]) for r in rows]
            ma20 = sum(closes[-20:]) / 20
            bias = (closes[-1] / ma20 - 1) * 100
            out["bias"] = round(bias, 2)
            out["bias_pct"] = round(max(0.0, min(100.0, (bias + 5) / 10 * 100)), 1)
    except Exception:
        pass
    try:
        _t = (BASE / "kxmm_data.js").read_text(encoding="utf-8")
        _j = json.loads(_t[_t.find("{"):_t.rfind("}") + 1])
        _fg = (_j.get("fear_greed") or {}).get("base") or {}
        out["fg"] = _fg.get("num")
        out["fg_txt"] = _fg.get("status_str")
    except Exception:
        pass
    try:
        if out["vol_pct"] is not None and out["bias_pct"] is not None:
            fg = out["fg"] if isinstance(out["fg"], (int, float)) else 50
            out["score"] = round(out["vol_pct"] * 0.45 + out["bias_pct"] * 0.35 + fg * 0.20, 1)
    except Exception:
        pass
    return out


_CROWD = _crowding()


def _crowd_card():
    """拥挤度卡 HTML（注入市场晴雨视图）。数据缺失时降级显示，不抛错。"""
    c = _CROWD
    if c.get("score") is None:
        return ('<div class="card" id="crowd-card"><h2>大盘拥挤度 <span class="badge badge-auto">数据不足</span></h2>'
                '<div class="sub">需要 ≥25 个交易日的 index_000300 记录；当前样本 '
                + str(c.get("n", 0)) + ' 条。</div></div>')
    s = c["score"]
    if s >= 80:
        lab, col, hint = "极度拥挤", "var(--up)", "量能与情绪同时亢奋，历史上此区间后波动放大"
    elif s >= 65:
        lab, col, hint = "偏拥挤", "var(--warn)", "成交活跃度高，注意追高风险"
    elif s >= 40:
        lab, col, hint = "中性", "#3b82f6", "量能与估值偏离均处常态区间"
    elif s >= 25:
        lab, col, hint = "偏冷清", "var(--down)", "量能萎缩，留意流动性"
    else:
        lab, col, hint = "极度冷清", "var(--down)", "成交与情绪双低，历史上多为底部区域特征"
    return (
        '<div class="card" id="crowd-card">'
        '<h2>大盘拥挤度 <span class="badge badge-auto" style="background:' + col + '22;color:' + col + '">'
        + lab + '</span></h2>'
        '<div class="sub">代理口径（非买卖信号）：<b>量能分位</b> 45%（沪深300 成交量 20 日分位）+ '
        '<b>趋势乖离</b> 35%（收盘 vs MA20，±5% 映射）+ <b>情绪温度</b> 20%（恐贪指数）</div>'
        '<div class="kpis">'
        '<div class="kpi"><div class="l">拥挤度</div><div class="v" style="color:' + col + '">'
        + f'{s:.1f}' + '</div><div class="s">0~100 · 越高越拥挤</div></div>'
        '<div class="kpi"><div class="l">量能分位</div><div class="v">' + f'{c["vol_pct"]:.1f}' + '</div>'
        '<div class="s">沪深300 成交量 20 日分位</div></div>'
        '<div class="kpi"><div class="l">趋势乖离</div><div class="v">' + f'{c["bias"]:+.2f}%' + '</div>'
        '<div class="s">收盘 vs MA20</div></div>'
        '<div class="kpi"><div class="l">情绪温度</div><div class="v">' + str(c.get("fg") if c.get("fg") is not None else "—")
        + '</div><div class="s">恐贪指数 · ' + str(c.get("fg_txt") or "—") + '</div></div>'
        '</div>'
        '<div class="sub" style="color:var(--faint)">' + hint + ' · 样本 ' + str(c["n"]) + ' 个交易日'
        '（index_000300）｜ 仅客观展示，不构成交易信号</div>'
        '</div>'
    )


_CROWD_CARD = _crowd_card()


_MKT_WEATHER_CARD = f'''<!-- 🌦 市场晴雨表（niuone 口径 · 30s 实时 · 纯展示非信号） -->
<div class="card" id="mkt-weather" style="margin-top:14px">
<h2>🌦 市场晴雨表 <span class="badge badge-auto" id="mw-badge">—</span></h2>
<div class="sub">全市场情绪广度 = 红/绿盘家数 + 涨停/跌停/炸板 + 量能（照抄 niuone 口径 · 腾讯行情批量接口精算）· 交易时段每 30s 实时更新，收盘后定格静态精算 · <b>仅客观展示，不构成任何交易信号</b></div>
<div id="mw-summary" class="mw-summary">等待数据…</div>
<div id="mw-idx" class="mw-idx"></div>
<div id="mw-jiandi" class="mw-summary" style="border-top:1px dashed var(--border,#e2e8f0);padding-top:8px;margin-top:8px;font-size:12px;color:var(--sub)"><span>🕐 见底信号·市场级恐慌观察（advisory-only）…</span></div>
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
'''


def _mkt_status():
    """开市/休市徽章（2026-09-18 用户决策 4）：构建期判定今日是否交易日。
    tradeDay = index_000300.csv 末行（最近交易日）；isTradingDay = 该末行 == 今日。
    盘中/休市时段由前端按本地时钟二次判定，不依赖外部接口。"""
    from datetime import date as _d
    _p = Path(__file__).resolve().parent / "index_000300.csv"
    try:
        _last = _p.read_text(encoding="utf-8").strip().splitlines()[-1].split(",")[0][:10]
    except Exception:
        _last = ""
    _today = _d.today().strftime("%Y-%m-%d")
    return {"tradeDay": _last, "today": _today, "isTradingDay": _last == _today}


_MKT_STATUS = _mkt_status()

js_src = (BASE / "enhanced_data.js").read_text(encoding="utf-8")
DATA = json.loads(js_src[len("window.ENH = "):].rstrip().rstrip(";"))
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
    SHORT_POOL = json.loads(_sp_js[len("window.SHORT_POOL = "):].rstrip().rstrip(";"))
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
    # 2026-09-02 超卖伏击今日统计徽章（主信号/信号观察/卖出数——0 只主信号时前端仍有迹可循）
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
                           f'title="15 个超卖形态策略命中 + 信号日 RSI&lt;分域阈值 + 收盘≥低价过滤(仅熊市) + 牛熊分域 = 主信号（事件独立，有信号即买）；'
                           f'信号观察 = 已命中但未触发；卖出 = 标准版分域（熊 RSI&gt;{_kh_ver.get("sell_a", 55)} / 牛 RSI&gt;{_kh_ver.get("sell_a_bull", 75)} / 弱牛 RSI&gt;{_kh_ver.get("sell_a_weak", 80)}）主信号 / 激进版 RSI&gt;{_kh_ver.get("sell_c", 50)} 参考（2026-09-03 牛熊分域 HYBRIDv2 + 09-04 弱牛域 OSL32：total 68.5%→80.0% 回撤不变）">'
                           f'超卖伏击今日: {_kh_str}</span>')
    SHORT_POOL_ASOF = SHORT_POOL.get("as_of", "—")
    _mg = SHORT_POOL.get("market_gate") or {}
    _bear60 = bool(_mg.get("bear60"))
    # 2026-09-07 牛熊分域 MA250 投产（Phase 11 定稿 · 用户拍板方案 2）+ 09-04 弱牛域 + 22:45 ob59 升级：
    #   🐻 熊市(<MA250, osl35+low3+ob59) / 🌞 牛市(>MA20, osl32+无low+ob75) / 🌙 弱牛回调(MA20下/MA250上, osl32+无low+ob80)
    if _bear60:
        _kh_regime_txt, _kh_regime_color = "🐻 熊市（MA250 下 · osl35+low3+ob59 · 可买入）", "var(--down)"
    elif _mg.get("open"):
        _kh_regime_txt, _kh_regime_color = "🌞 牛市（MA20 上 · osl32+无low+ob75 · 可买入）", "var(--down)"
    else:
        _kh_regime_txt, _kh_regime_color = "🌙 弱牛回调（MA20 下/MA250 上 · osl32+无low+ob80 · 可买入）", "#b45309"
    SHORT_KHUNTER_BEAR = (f'<span class="badge badge-auto" style="background:{_kh_regime_color};color:#fff">'
                          f'超卖伏击牛熊分域：{_kh_regime_txt}'
                          f'</span>')
    if _mg.get("open"):
        SHORT_POOL_GATE = f'<span class="badge badge-auto" style="background:#1f8a4c;color:#fff">市况门控 ✅ 开（{_mg.get("idx_close")} &gt; MA20 {_mg.get("idx_ma20")}）</span>'
    else:
        # 2026-08-20 用户决策：门控改为「仅提醒」——股票池分≥50 照常入池展示（供参考），不做买入指令
        # 2026-09-02 豁免：超卖伏击主信号不受 MA20 门控（回测全窗口证据）→ 2026-09-03 牛熊分域接管（熊市全开/牛市>MA20 开）→ 2026-09-04 弱牛域投产三态全开
        SHORT_POOL_GATE = f'<span class="badge badge-auto" style="background:#d97706;color:#fff">市况门控 ⚠ 关 · 仅提醒（沪深300 {_mg.get("idx_close")} &lt; MA20 {_mg.get("idx_ma20")}；超卖伏击由牛熊分域裁决，其余仅参考）</span>'
    SHORT_POOL_INTRADAY = SHORT_POOL.get("intraday_note") or ""
    SHORT_POOL_ASOF_MIN = SHORT_POOL.get("intraday_ts") or "15:00"
    # 跟踪池清洗（R-dash-track-0922 · 用户 2026-09-22：「很多还是旧版本已退休策略的标的，都删掉」）
    # 依据：现行超卖伏击为**主板限定**，pool ∈ {创业板, 科创板} 的标的不可能被它选中 → 属退休策略残留
    _TR_DROP_POOLS = ("创业板", "科创板")
    _tr_raw = SHORT_POOL.get("track", {}) or {}
    _tp_raw = SHORT_POOL.get("track_pending_short", {}) or {}
    _tr_keep = {k: v for k, v in _tr_raw.items()
                if str((v or {}).get("pool", "")) not in _TR_DROP_POOLS}
    _tp_keep = {k: v for k, v in _tp_raw.items()
                if str((v or {}).get("pool", "")) not in _TR_DROP_POOLS}
    TRACK_PRUNED = {"raw": len(_tr_raw), "keep": len(_tr_keep),
                    "drop": len(_tr_raw) - len(_tr_keep),
                    "pend_raw": len(_tp_raw), "pend_keep": len(_tp_keep)}
    # 运行时精简池数据（tiers/track 供「短线跟踪池」渲染；HTML 不加载 short_pool.js）
    SHORT_POOL_SLIM = json.dumps(
        {"as_of": SHORT_POOL.get("as_of"), "fund_as_of": SHORT_POOL.get("fund_as_of"),
         "tiers": SHORT_POOL.get("tiers"), "track": _tr_keep,
         "track_pending_short": _tp_keep, "market_gate": SHORT_POOL.get("market_gate"),
         "sel_meta": SHORT_POOL.get("sel_meta")},
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
    SHORT_POOL = {}

def _sat_paper_card(path, tk, title):
    """单轨模拟盘卡（2026-09-15 拆分为三低对照/多因子主仓两张，各自独立账户与基数）。"""
    tag = tk[-1]
    try:
        d = json.load(open(path, encoding="utf-8"))
        m = d.get("meta", {})
        nh = d.get("nav_history", [])
        pos = d.get("positions", {}) or {}
        basis = float(m.get("basis") or m.get("initial_cash") or 1)
        last = nh[-1] if nh else {}
        nav = float(last.get(tk) or basis)
        ret = (nav / basis - 1) * 100
        status = "运行中" if nh else "待建仓"
        dt = last.get("date") if nh else ((d.get("events") or [{}])[-1].get("date", "—"))
        ev = ((d.get("events") or [{}])[-1].get("event", ""))
        role = m.get("role", "")
        return (f'<div class="card" id="sat-paper-{tag}-card">'
                f'<h2>{title} <span class="badge badge-auto">{m.get("rebased","2026-09-15")[:10]} 重设 · 基数 {basis:,.0f} · {role}</span></h2>'
                f'<div class="kpis">'
                f'<div class="kpi"><div class="l">模拟净值</div><div class="v">{nav:,.0f}</div><div class="s">期初 {basis:,.0f}</div></div>'
                f'<div class="kpi"><div class="l">累计收益</div><div class="v" style="color:{ "var(--down)" if ret >= 0 else "var(--up)" }">{ret:+.2f}%</div><div class="s">含成本口径</div></div>'
                f'<div class="kpi"><div class="l">持仓标的</div><div class="v">{len(pos)}</div><div class="s">{"零实盘资金·仅对照" if tag == "a" else "实盘主轨"}</div></div>'
                f'<div class="kpi"><div class="l">状态</div><div class="v">{status}</div><div class="s">{dt}</div></div>'
                f'</div>'
                f'<div class="sub">记账口径：信号日次一交易日开盘价×1.002（20bp 滑点）+ 佣金 2.5bp（最低 5 元）· 全自动，无需回填成交'
                + (' · <b>pct40 因子化出场已启用（跌出前 40% 分位 → T+1 开盘卖）</b>' if tag == "b" else ' · 对照轨不执行 pct40（保持纯定期轮动基线）') + '</div>'
                f'<div class="sub" style="color:var(--faint)">{ev}</div>'
                f'</div>')
    except Exception as _e:
        return (f'<div class="card" id="sat-paper-{tag}-card"><h2>{title}</h2>'
                f'<div class="sub">账户文件未生成（{_e}）</div></div>')


SAT_PAPER_B_CARD = _sat_paper_card(BASE / "backtest" / "satellite_paper_b.json", "track_b",
                                   "🧪 多因子主仓 模拟盘（13 因子打分 Top20 · 月频）")
# 三低对照模拟盘卡已于 2026-09-16 随三低对照 退休一并移除（用户指令：看板不留三低对照 内容）

# 基金主仓（基金主仓 FB3-H20）模拟盘卡（2026-09-14 用户指出「中长线基金没有模拟盘」后补齐）
_fp_f = BASE / "backtest" / "fund_paper.json"
try:
    _fp = json.load(open(_fp_f, encoding="utf-8"))
    _fm = _fp.get("meta", {})
    _fnh = _fp.get("nav_history", [])
    _finit = float(_fm.get("initial_cash", 102000) or 102000)
    _flast = _fnh[-1] if _fnh else {}
    _fnav = float(_flast.get("nav") or _finit) / _finit
    _fret = (_fnav - 1) * 100
    _fpos = len(_fp.get("positions", {}))
    try:
        _ftarget = len((json.load(open(BASE / "short_pool.json", encoding="utf-8")).get("tiers", {}).get("基金")) or [])
    except Exception:
        _ftarget = "—"
    FUND_PAPER_CARD = (f'<div class="card" id="fund-paper-card">'
                       f'<h2>🧪 基金主仓（基金动量 · 持 20 日） <span class="badge badge-auto">10.2 万（17万×60%）· 持仓 20 交易日</span></h2>'
                       f'<div class="kpis">'
                       f'<div class="kpi"><div class="l">模拟净值</div><div class="v">{_fnav:.4f}</div><div class="s">期初 1.0</div></div>'
                       f'<div class="kpi"><div class="l">累计收益</div><div class="v" style="color:{'#10b981' if _fret >= 0 else '#ef4444'}">{_fret:+.2f}%</div><div class="s">C类份额 5bp/边</div></div>'
                       f'<div class="kpi"><div class="l">持仓 / 目标</div><div class="v">{_fpos} / {_ftarget}</div><div class="s">牛 Top10 / 熊 Top3</div></div>'
                       f'<div class="kpi"><div class="l">状态</div><div class="v">{"运行中" if _fnh else "待建仓"}</div><div class="s">{(_flast.get("date") if _fnh else _fp.get("events", [{}])[-1].get("date", "—"))}</div></div>'
                       f'</div>'
                       f'<div class="sub">成交口径：信号净值日（fund_as_of）之后第一个净值日按净值成交（基金净值 T+1 公布，当日未出则自动等下一交易日——不用信号日自身净值，避免前视）</div>'
                       f'<div class="sub" style="color:var(--faint)">{(_fp.get("events", [{}])[-1].get("event", ""))}</div>'
                       f'</div>')
except Exception as _e3:
    FUND_PAPER_CARD = (f'<div class="card" id="fund-paper-card"><h2>🧪 基金主仓模拟盘</h2>'
                       f'<div class="sub">fund_paper.json 未生成（{_e3}）</div></div>')

# 动量增强对照臂卡（2026-09-17 建：用户拍板 ③纸面跟踪；#2 λ0.2 主候选 / #4 λ0.3 陪跑）
# 数据源：backtest/shadow_ret20/{ledger.csv, daily_metrics.jsonl}（daily_refresh 对照臂软步骤产出）
def _shadow_ret20_card():
    import pandas as _pd, json as _js
    try:
        _sb = BASE / "backtest" / "shadow_ret20"
        led = _pd.read_csv(_sb / "ledger.csv")
        _ln = (_sb / "daily_metrics.jsonl").read_text(encoding="utf-8").strip().splitlines()
        met = _js.loads(_ln[-1]) if _ln else {}
        start = str(led["date"].iloc[0]); days = len(led)
        last = led.iloc[-1]

        def _nv(k, pre="nav_"):
            try:
                v = float(last[pre + k])
                return v if v == v else None
            except Exception:
                return None

        nb, n2, n3 = _nv("base"), _nv("l02"), _nv("l03")
        b50, s50 = _nv("base", "nav50_"), _nv("l02", "nav50_")
        d2 = (n2 / nb - 1) * 100 if (nb and n2) else 0.0
        d3 = (n3 / nb - 1) * 100 if (nb and n3) else 0.0
        d50 = (s50 / b50 - 1) * 100 if (b50 and s50) else 0.0
        ov = (met.get("overlap") or {}).get("l02_vs_base")
        _col = lambda v: "var(--down)" if (v or 0) >= 0 else "var(--up)"
        f_n2 = f"{n2:.4f}" if n2 else "—"
        f_nb = f"{nb:.4f}" if nb else "—"
        f_n3 = f"{n3:.4f}" if n3 else "—"
        return (f'<div class="card" id="shadow-ret20-card">'
                f'<h2>🧪 对照臂 · 动量增强（#2 λ0.2 主 / #4 λ0.3 陪跑） <span class="badge badge-auto">纸面跟踪 · 生产 composite 未动</span></h2>'
                f'<div class="kpis">'
                f'<div class="kpi"><div class="l">λ0.2 归一净值</div><div class="v">{f_n2}</div><div class="s">vs BASE <b style="color:{_col(d2)}">{d2:+.2f}%</b></div></div>'
                f'<div class="kpi"><div class="l">BASE 归一净值</div><div class="v">{f_nb}</div><div class="s">生产口径基准臂</div></div>'
                f'<div class="kpi"><div class="l">λ0.3 归一净值</div><div class="v">{f_n3}</div><div class="s">vs BASE <b style="color:{_col(d3)}">{d3:+.2f}%</b></div></div>'
                f'<div class="kpi"><div class="l">跟踪进度</div><div class="v">{days} 日</div><div class="s">起点 {start} · TopN 重合 {ov if ov is not None else "—"}</div></div>'
                f'</div>'
                f'<div class="sub">机制：(z(comp)+λ·z(ret20))/(1+λ)，把生产复合分隐含的反转倾斜压回一点（corr(z_ret,z_comp)=−0.602）· 20bp 基准档（50bp 压力档 L02−BASE {d50:+.2f}%）· T+1 开盘执行</div>'
                f'<div class="sub" style="color:var(--faint)">验收（用户定）：≥1-3 个月前瞻 · 月度多数为正 · 相对回撤不失控；首检 10 月中。数据 backtest/shadow_ret20/，每日链内刷新</div>'
                f'</div>')
    except Exception as _e:
        return (f'<div class="card" id="shadow-ret20-card"><h2>🧪 对照臂 · 动量增强</h2>'
                f'<div class="sub">数据未生成（{_e}）→ 运行 backtest/shadow_ret20.py</div></div>')

SHADOW_RET20_CARD = _shadow_ret20_card()

# 黄金对冲卡（R-gold-sat-0917 · 2026-09-17 用户拍板投产）
# 数据源：backtest/gold_sat_paper.json（daily_refresh「黄金卫星模拟盘」软步骤产出）
def _gold_sat_card():
    import json as _js
    try:
        _g = _js.loads((BASE / "backtest" / "gold_sat_paper.json").read_text(encoding="utf-8"))
        _m = _g.get("meta", {})
        _nh = _g.get("nav_history", [])
        _notional = float(_m.get("notional") or 6800.0)
        _last = _nh[-1] if _nh else {}
        _nav = float(_last.get("nav") or _notional)
        _ret = (_nav / _notional - 1) * 100
        _share = float(_last.get("share") or 0.0) * 100
        _lots = int(sum(float(p.get("shares", 0)) for p in (_g.get("positions") or {}).values()) // 100)
        _stat = "运行中" if _nh else "待建仓"
        _cold = "var(--down)" if _ret >= 0 else "var(--up)"
        _flags = "；".join(_m.get("hard_flags") or [])
        return (f'<div class="card" id="gold-sat-card">'
                f'<h2>🥇 黄金对冲（卫星层 10% · sh518880 买入持有） <span class="badge badge-auto">2026-09-17 投产 · 只做卫星层</span></h2>'
                f'<div class="kpis">'
                f'<div class="kpi"><div class="l">黄金袖净值</div><div class="v">{_nav / _notional:.4f}</div><div class="s">名义 {_notional:.0f} · {_lots} 手</div></div>'
                f'<div class="kpi"><div class="l">累计收益</div><div class="v" style="color:{_cold}">{_ret:+.2f}%</div><div class="s">B&H · 无卖出</div></div>'
                f'<div class="kpi"><div class="l">实际占比</div><div class="v">{_share:.1f}%</div><div class="s">目标 10% · 永不回补</div></div>'
                f'<div class="kpi"><div class="l">状态</div><div class="v">{_stat}</div><div class="s">信号 {_m.get("signal_date", "—")} → T+1 开盘</div></div>'
                f'</div>'
                f'<div class="sub">叠加式 <code>r_sat=(1−w)·r_B+w·r_gold</code>，w=10%，<b>替换</b>多因子主仓的 10%（卫星总敞口仍 68000，不超配）· 黄金腿 = 518880 买入持有、永不卖出 · 卫星层 ΔS(w10) = <b>+0.104</b>（采纳门 +0.02）· 分半 h1/h2 双正</div>'
                f'<div class="sub" style="color:var(--warn)">⚠ 硬伤申报：{_flags}</div>'
                f'<div class="sub" style="color:var(--faint)">账本 backtest/gold_sat_paper.json；黄金腿已镜像进多因子主仓账户（卫星 mark 逐只取价自动计入净值）。每日链内刷新。</div>'
                f'</div>')
    except Exception as _e:
        return (f'<div class="card" id="gold-sat-card"><h2>🥇 黄金对冲</h2>'
                f'<div class="sub">gold_sat_paper.json 未生成（{_e}）→ 运行 backtest/gold_sat_paper.py</div></div>')

GOLD_SAT_CARD = _gold_sat_card()


# 动量增强模拟盘卡（R-ret20-paper-0917 · 2026-09-17 用户拍板 #2/#4「投产并加模拟盘」）
# 数据源：backtest/ret20_paper_l02.json / ret20_paper_l03.json（daily_refresh「动量增强模拟盘」软步骤产出）
#        + backtest/shadow_ret20/daily_metrics.jsonl（臂 NAV 与 TopN 重合度）
def _ret20_paper_card():
    import json as _js
    _arms = [("l02", "λ0.2", "#2 · 对照臂主候选"), ("l03", "λ0.3", "#4 · 对照臂陪跑")]
    try:
        _rows, _nav, _ovl = [], {}, {}
        for _a, _lab, _tagd in _arms:
            _p = BASE / "backtest" / f"ret20_paper_{_a}.json"
            _d = _js.loads(_p.read_text(encoding="utf-8"))
            _nh = _d.get("nav_history") or []
            _bs = float(_d["meta"].get("basis") or 68000.0)
            _nv = float(((_nh[-1] if _nh else {}) or {}).get("nav") or _bs)
            _nav[_a] = _nv / _bs
            _rows.append((_a, _lab, _tagd, _nv / _bs, len(_d.get("positions") or {}),
                          float(_d.get("cash") or 0.0), _d["meta"].get("signal_date", "—"),
                          "运行中" if _nh else "待建仓"))
        try:
            _m = (BASE / "backtest" / "shadow_ret20" / "daily_metrics.jsonl").read_text(encoding="utf-8")
            _last = _js.loads(_m.strip().splitlines()[-1])
            _ovl = _last.get("overlap") or {}
            _nav["base"] = float((_last.get("nav") or {}).get("base") or 1.0)
        except Exception:
            pass
        _tr = "".join(
            f'<tr><td><b>{_lab}</b></td><td>{_tagd}</td><td>{_nv:.4f}</td><td>{_pn} 只</td>'
            f'<td>{_cs:.0f}</td><td>{_sg}</td><td>{_stt}</td></tr>'
            for _a, _lab, _tagd, _nv, _pn, _cs, _sg, _stt in _rows)
        _otxt = (f"λ0.2 与 BASE 重合 <b>{float(_ovl.get('l02_vs_base', 0)):.3f}</b> · "
                 f"λ0.3 与 BASE <b>{float(_ovl.get('l03_vs_base', 0)):.3f}</b> · "
                 f"λ0.2/λ0.3 互重合 <b>{float(_ovl.get('l02_vs_l03', 0)):.3f}</b>"
                 f"｜BASE 臂 NAV {_nav.get('base', 1.0):.4f}（同窗影子）") if _ovl else "影子 metrics 未就绪"
        return (f'<div class="card" id="ret20-paper-card">'
                f'<h2>📐 动量增强模拟盘（λ0.2 / λ0.3） <span class="badge badge-auto">2026-09-17 投产 · 生产 composite 未改</span></h2>'
                f'<div class="sub">形态：<code>l02=(z(comp)+0.2·z(ret20))/1.2</code>、<code>l03=(z(comp)+0.3·z(ret20))/1.3</code>'
                f'，冻结引擎 BASE 原样 = 生产口径 · 两臂各 <b>68,000 同额纯对照</b>（零实盘资金申领，不与多因子主仓抢配额）</div>'
                f'<table class="tbl"><thead><tr><th>臂</th><th>定位</th><th>NAV</th><th>在仓</th><th>现金</th><th>信号日</th><th>状态</th></tr></thead>'
                f'<tbody>{_tr}</tbody></table>'
                f'<div class="sub">{_otxt}</div>'
                f'<div class="sub" style="color:var(--warn)">⚠ 样本外记录 = 0 天（研究侧读数 λ0.2 off0 +25.08%/S1.411/50bp 19.25；'
                f'λ0.3 +24.36%/S1.376/50bp 18.67；安慰剂 p 均 0.05）→ 毕业首检 <b>2026-10-15</b>：'
                f'① NAV ≥ BASE 臂 ② 月度多数为正 ③ 相对回撤 ≤ BASE+5pp</div>'
                f'<div class="sub" style="color:var(--faint)">账本 backtest/ret20_paper_l02.json / ret20_paper_l03.json；'
                f'信号源 backtest/shadow_ret20/state.json。每日链内刷新。</div></div>')
    except Exception as _e:
        return (f'<div class="card" id="ret20-paper-card"><h2>📐 动量增强模拟盘</h2>'
                f'<div class="sub">ret20_paper_l02/l03.json 未生成（{_e}）→ 运行 backtest/ret20_paper.py</div></div>')


RET20_PAPER_CARD = _ret20_paper_card()



# 2026-09-05 用户需求：短线命中策略一览 + 跟踪池行业列 —— 全市场板块/行业紧凑映射（内联 window.STOCK_META）
# 数据源：short_signals.js 全量股票代码 + stock_industry.json（申万一级，7511 只全市场覆盖）
try:
    _ind_map = json.loads(open(BASE / "stock_industry.json", encoding="utf-8").read())["map"]
except Exception:
    _ind_map = {}
def _board_of6(c):
    """6 位代码 → 板块。2026-09-23（R-no-bj-0923）：北交所分支已移除 —— 北交所不在任何
    池宇宙（引擎/短池/A5/qlch 均硬排除 bj*），8/4/92 号段返回「—」（不再渲染「北交所」标签）。"""
    if c.startswith(("688", "689")):
        return "科创板"
    if c.startswith("30"):
        return "创业板"
    if c.startswith(("8", "4", "92")):
        return "—"                    # 非交易宇宙（原北交所号段）：显式未知，不产出板块文案
    return "主板"
STOCK_META = {}
try:
    _sig_js = open(BASE / "short_signals.js", encoding="utf-8").read()
    _sig_data = json.loads(_sig_js[len("window.SHORT_SIGNALS = "):].rstrip().rstrip(";"))
    for _c in _sig_data.get("stock", {}):
        STOCK_META[_c] = [_board_of6(_c), _ind_map.get(_c, "—")]
    # 基金（短线跟踪池含基金行）：short_pool.json details 自带行业
    for _c, _d in SHORT_POOL.get("details", {}).items():
        STOCK_META[_c] = [_d.get("board", "基金"), _d.get("industry", "—")]
    # 跟踪池基金补全：track/pending 中未覆盖的基金代码 → 按基金名识别主题（industry_pool.fund_industry）
    import industry_pool as _IP
    for _c in set(SHORT_POOL.get("track", {})) | set(SHORT_POOL.get("track_pending_short", {})):
        if _c in STOCK_META:
            continue
        _fname = (_sig_data.get("fund", {}).get(_c) or {}).get("name", "")
        STOCK_META[_c] = ["基金", _IP.fund_industry(_fname)]
except Exception as _e:
    print("stock_meta 构建失败:", _e)
STOCK_META_JS = json.dumps(STOCK_META, ensure_ascii=False, separators=(",", ":"))
# A5_tp8t2 打板实验系统（第三个系统，2026-08-28 接入；数据由 build_a5_pool.py 生成）
try:
    _a5_js = open(BASE / "a5_pool.js", encoding="utf-8").read()
    A5 = json.loads(_a5_js[len("window.A5_POOL = "):].rstrip().rstrip(";"))
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

# 选池再平衡倒计时徽章（2026-09-08 Q1C 用户拍板）：
# 语义 = 月度再平衡（21 交易日），未到期维持现榜 → 让用户一眼看懂「为何榜单标的还是上次选的那批」。
# 数据源 = enhanced_data.js meta.pool_rebalance（由 build_enhanced_data.py 的
# V.pool_rebalance_state() 状态机写入，与选池共用同一真相源，不重复计算）。
POOL_REBAL_BADGE = ""
POOL_REBAL_NOTE = ""
try:
    _pr = (DATA.get("meta", {}) or {}).get("pool_rebalance") or {}
    if _pr:
        _ls = _pr.get("last_select", "—")
        _dtn = int(_pr.get("days_to_next") or 0)
        _ds = int(_pr.get("days_since") or 0)
        _every = int(_pr.get("every") or 21)
        if _pr.get("due"):
            POOL_REBAL_BADGE = (f'<span class="badge badge-auto" style="background:#1f8a4c;color:#fff" '
                                f'title="距上次选池已满 {_every} 个交易日 → 本次已触发换榜">'
                                f'🔄 选池已到期 · 本次换榜</span>')
            POOL_REBAL_NOTE = f"榜单为最新交易日（{_pr.get('select_day','—')}）重新选出的 Top10。"
        else:
            POOL_REBAL_BADGE = (f'<span class="badge badge-auto" '
                                f'title="月度再平衡：距上次选池 {_ds} 个交易日，满 {_every} 个交易日才换榜；'
                                f'未到期维持现榜（中长线持有定位，避免跑一次管道就整体换血）">'
                                f'🗓 距下次再平衡 {_dtn} 个交易日</span>')
            POOL_REBAL_NOTE = (f"榜单为 {_ls} 选出的 Top10（月度再平衡，未到期维持现榜）；"
                               f"距下次再平衡 {_dtn} 个交易日 · 标的一旦权重分跌破入池门槛会打「⚠ 低于入池门槛」软标记，"
                               f"但<b>不自动剔除</b>（中长线持有定位）。")
except Exception as _e:
    print("选池再平衡徽章计算失败:", _e)

# 布林带宽观察指标（2026-09-08 Q2C：大财师兄 9/8「布林线定位置」——带宽收窄=选方向、张开=方向已出；
# 仅做看板观察，不参与任何门控/信号。口径：沪深300 日线 BOLL(20,2)，带宽=(上轨-下轨)/中轨，
# 与 60 日均带宽比较判收窄/张开）
# ⚠ 2026-09-08 修复：本模块未导入 pandas（原写法 name 'pd' is not defined 静默失败），改标准库实现
try:
    import statistics as _stat
    _idx_lines = []
    with open(BASE / "index_000300.csv", encoding="utf-8") as _f:
        for _ln in _f:
            _ln = _ln.strip()
            if not _ln or _ln.startswith("date"):
                continue
            _p = _ln.split(",")
            if len(_p) >= 5:
                try:
                    _idx_lines.append(float(_p[4]))  # close
                except ValueError:
                    pass
    _bw_series = []
    for _i in range(20, len(_idx_lines) + 1):
        _win = _idx_lines[_i - 20:_i]
        _m = _stat.fmean(_win)
        if _m == 0:
            continue
        _s = _stat.pstdev(_win)
        _bw_series.append(4 * _s / _m)
    if len(_bw_series) >= 61:
        _bw_now = _bw_series[-1]
        _bw_avg60 = _stat.fmean(_bw_series[-60:])
        _bw_pct = _bw_now / _bw_avg60 - 1 if _bw_avg60 else 0.0
        if _bw_pct < -0.15:
            _bw_state, _bw_color = "收窄·选方向", "var(--warn)"
        elif _bw_pct > 0.15:
            _bw_state, _bw_color = "张开·方向已出", "var(--up)"
        else:
            _bw_state, _bw_color = "中性", "#6b7280"
        BB_BW_KPI = f'<div class="kpi"><div class="l">📐 沪深300 布林带宽</div><div class="v" style="color:{_bw_color}">{_bw_state}</div><div class="s">带宽 {_bw_now*100:.1f}% vs 60日均 {_bw_avg60*100:.1f}%（{_bw_pct*100:+.0f}%）· 观察非信号</div></div>'
    else:
        BB_BW_KPI = ''
except Exception as _e:
    print("布林带宽 KPI 计算失败:", _e)
    BB_BW_KPI = ''

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
    """市场板块徽章（统一标准：主板/创业板/科创板；行业放入悬浮提示）。
    四档 class 映射**保留**（含 board-bj，按批准口径沿用四档体系）——但北交所已不在任何池宇宙，
    实际渲染只会出现 主板 / 创业板 / 科创板（R-no-bj-0923）。"""
    if not v or v == "—":
        return '<span style="color:var(--faint)">—</span>'
    cls = {"主板": "board-sh", "创业板": "board-cy", "科创板": "board-kc", "北交所": "board-bj"}.get(v, "")
    tip = f' title="行业：{ind}"' if ind else ""
    return f'<span class="board-tag {cls}"{tip}>{v}</span>'


SCORE_SUB_MAP = {"趋势": "trend", "动量": "momentum", "量能": "volume",
                 "超买": "osc", "风控": "risk"}          # 子项标签 → comp 字典键


def rows_html_for(items, score_sub="趋势/动量/量能/超买/风控"):
    """模板式汇总表行（2026-09-18：子项由单列斜杠串改为每个指标一列）"""
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
        _labs = [x for x in str(score_sub).split("/") if x]
        _sub_cells = "".join(
            f'<td class="num" style="text-align:center;font-size:12px">'
            f'{comp.get(SCORE_SUB_MAP.get(_lb, _lb), 0):.0f}</td>' for _lb in _labs)
        comp_txt = "/".join(f'{comp.get(SCORE_SUB_MAP.get(_lb, _lb), 0):.0f}' for _lb in _labs)
        rsi_txt = f'{d["rsi"]:.0f}' if d.get("rsi") is not None else "—"
        vp_txt = f'{comp.get("volume",0):.0f}'
        board = d["board"]
        # 开盘跳空高开规避（2026-08-17 用户需求）：盘中 patch 写入 gap（开盘 vs 昨收），>3% 不追高，
        # 可等盘中回落至 3% 以内再考虑买入
        gap_badge = ""
        if d.get("gap") is not None and d["gap"] > 3:
            gap_badge = (f'<span class="badge" style="background:rgba(239,68,68,.15);color:var(--up);" '
                         f'title="开盘跳空高开 {d["gap"]:.1f}%（vs 昨收），反转空间被开盘吃掉，不追高；可等盘中回落至 3% 以内再考虑买入">'
                         f'⚠ 高开{d["gap"]:.1f}% 规避（回落&lt;3%可买）</span>')
        # 2026-08-20 用户决策：市况门控改为「仅提醒」——门控关闭时入池股票标「仅提醒·非买入」，
        # 仅供参考（不追高）；与 8/19 跟踪池安全口径（不开新仓·仅跟踪）区分开（两者都非买入指令）
        gate_tag = ""
        if d.get("gate_closed"):
            gate_tag = ('<span class="badge" style="background:rgba(217,119,6,.18);color:#fbbf24;" '
                        f'title="市况门控关闭：权重分≥50 照常入池仅供参考，非买入指令；不追高，持仓走跟踪池等卖出信号">仅提醒·非买入</span>')
        # 2026-09-08 Q2B 用户拍板：低于入池门槛软标记 —— 解释「为何不达标的标的还在池里」。
        # 语义 = 纯提示，**不改变交易语义**：榜是上次再平衡日选的（月度换榜），权重分随行情回落属正常；
        # 清仓走 score<50 的 exit_signal 路径（跟踪池），与入池门槛无关。
        below_tag = ""
        if d.get("below_entry"):
            _emin = d.get("entry_min") or 65
            below_tag = (f'<span class="badge" style="background:rgba(148,163,184,.18);color:var(--faint);" '
                         f'title="权重分 {d["score"]:.1f} 已跌破入池门槛 {_emin} 分：本标的为上次再平衡日（'
                         f'{DATA.get("meta",{}).get("pool_rebalance",{}).get("last_select","—")}）的达标标的，'
                         f'权重分随行情回落属正常；软标记仅提示，不改变交易语义（买入看档位/择时，'
                         f'清仓看 score&lt;50 的跟踪池信号）">⚠ 低于入池门槛 {_emin}</span>')
        # 2026-09-02 用户拍板：主信号=超卖伏击 主板信号（+RSI<35）；旧战法候选已全量删除（弃用）
        pick_tag = ""
        if d.get("pick") == "top4":
            pick_tag = ('<span class="badge" style="background:rgba(37,99,235,.16);color:#60a5fa;" '
                        f'title="超卖伏击主信号：15 策略命中 + 信号日 RSI&lt;35 超卖（主板限定，事件独立，有信号即买）">'
                        f'🎯 超卖伏击主信号</span>')
        rows += f'''<tr data-code="{d["code"]}" data-search="{d["name"]} {_bare(d["code"])} {d["industry"]} {board}" data-board="{d["perm"]}" data-market="{board}" data-industry="{d["industry"]}" data-tier="{d["tier"]}" data-pick="{d.get("pick") or ""}">
<td style="text-align:center">{rank}</td>
<td><b>{d["name"]}</b>{pick_tag}{below_tag}<br><span style="color:var(--faint);font-size:11px">{_bare(d["code"])}</span></td>
<td>{_board_cell(board, d.get("industry"))}</td>
<td><span class="board-tag">{d["industry"]}</span></td>
<td style="text-align:right" data-v="{d["px"]}">{d["px"]:.2f}</td>
<td style="text-align:right" class="{chg_cls}" data-v="{d["chg"] or 0}">{chg_txt}</td>
<td style="text-align:right" class="{ret_cls}" data-v="{d["ret_1y"] or 0}">{ret_txt}</td>
<td style="text-align:center" data-v="{d["score"] or 0}"><b>{d["score"]:.1f}</b></td>
{_sub_cells}
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
<h3>{d["name"]} <span class="sub">{d["code"]}</span> <span class="board-tag">{board}</span> <span class="board-tag">{d["industry"]}</span>{"🎯 超卖伏击主信号" if d.get("pick")=="top4" else ("候选·仅观察" if d.get("pick")=="cand" else "")}</h3>
<p class="meta">现价 <b>{d["px"]:.2f}</b>（<span class="{"up" if (d["chg"] or 0)>0 else "down"}">{f"{d['chg']:+.2f}%" if d["chg"] is not None else "—"}</span>）｜ 近一年 <span class="{"up" if (d["ret_1y"] or 0)>0 else "down"}">{f"{d['ret_1y']:+.0f}%" if d["ret_1y"] is not None else "—"}</span> ｜ RSI {d["rsi"]:.0f}</p>
<p class="meta">权重 <b>{d["score"]:.1f} 分</b> → {tier_pill(d["tier"])} ｜ 建议：{action_for(d)} ｜ {ma200_txt}</p>
{f'<p class="meta" style="color:var(--faint)">⚠ 低于入池门槛 {d.get("entry_min") or 65} 分（软标记 · 不改变交易语义）</p>' if d.get("below_entry") else ""}
<p class="meta">六类：趋势 {comp.get("trend",0):.0f}｜动能 {comp.get("momentum",0):.0f}｜量能 {comp.get("volume",0):.0f}｜超买 {comp.get("osc",0):.0f}｜风控 {comp.get("risk",0):.0f}｜研报 0.0</p>
<p class="meta" style="color:var(--faint)">{d.get("biz", "—")}</p>
</div>
</div>'''
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

# ⚠ 2026-09-13 用户拍板：中长线基金卡切换 FB3-H20 2000 池口径（v8 混合版 +184.3%/10.3% 退役）。
#    优先读 FB3-H20 含滑点主显口径（short_v3_fund_slip20_summary.json），曲线同步切 short_v3_fund_slip20_equity.csv。
s_fund, _ftag = _ml("short_v3_fund_slip20_summary.json", "FB3-H20 牛熊 regime · 2000 池")
if not s_fund:
    s_fund, _ftag = _ml("v8_fund_summary.json", "Top10主仓+6卫星 · MA100")
    FUND_TAG = _ftag + " · 申赎费敏感度：30bps≈-10%（90笔/10年半年轮动，影响小）"
else:
    FUND_TAG = _ftag + "（2000 池 · 含5bps滑点） · v8 混合版（+184.3%/年化10.3%）已退役，历史见更新日志 v5.11.9/v5.13.3"

def load_curve_norm(f):
    try:
        df = __import__("pandas").read_csv(BASE / f)
        v = df["value"].astype(float).values
        return [round(float(x), 2) for x in (v / v[0] * 100)]
    except Exception:
        return []

v_fund = load_curve_norm("short_v3_fund_slip20_equity.csv")  # 2026-09-13 切 FB3-H20 2000 池曲线（原 v8_fund_equity.csv 退役）
# 双卫星数据源（2026-09-13 三轨拍板）
s_ln = {}          # 三低对照 已于 2026-09-16 退休：摘要/曲线/标签全部移除

_sup = json.load(open(BASE / "backtest" / "oss_0913" / "super_combo_0913.json", encoding="utf-8")) if (BASE / "backtest" / "oss_0913" / "super_combo_0913.json").exists() else {}
if _sup:
    _o = _sup["best"]["off0"]
    s_super = {"total_return_pct": None, "annual_return_pct": round(_o["ann"] * 100, 2),
             "max_drawdown_pct": round(_o["mdd"] * 100, 2), "sharpe": round(_o["sharpe"], 3),
             "total_trades": _o.get("n_trades"), "win_rate_pct": round(_o.get("win", 0) * 100, 1)}
else:
    s_super = {}
SUPER_TAG = "SUPER 13因子(A4D6+战法原子7)+中证1000<MA20半仓且高波半区 · Top20 · 月频（主板含退市 · 2021起）"
SUPER_TAG += " · 相位中位1.151 · off0 年化22.87% · 安慰剂500 p=0.000 · slip50档S1.00 · 100万对照S1.30（2026-09-13 替换 A4D）"
def load_curve_idx(f):
    try:
        df = __import__("pandas").read_csv(BASE / f, index_col=0)
        v = df.iloc[:, 0].astype(float).values
        return [round(float(x), 2) for x in (v / v[0] * 100)]
    except Exception:
        return []
v_super = load_curve_idx("backtest/oss_0913/super_champion_equity_0913.csv")
if s_super and v_super:
    s_super["total_return_pct"] = round(v_super[-1] - 100, 2)
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
        # 2026-09-08 修复：summary 的 params 已含 "Aroon强趋势过滤(A80_M78)"，
        # 旧代码无脑追加导致标签重复（"…(A80_M78) · Aroon强趋势过滤(A80_M78)"）
        _base_tag = (tag or label)
        stk_tag[g] = _base_tag if "A80_M78" in _base_tag else (_base_tag + " · Aroon强趋势过滤(A80_M78)")
    else:
        stk_tag[g] = (tag or label) + (" · 含20bps滑点" if "滑点" not in (tag or "") else "")
# 短线分层 summary（8/31 审计：旧 shortsplit_* 含未来函数作废；修正引擎无分层口径）
# 2026-09-02 晚修复：旧战法（反转打分）已全量弃用 → 分层「已下架」占位卡下线，
# 改接生产主信号 = 超卖伏击 15 信号 + RSI<35 择时 的全窗口回测（主板限定 · S1B_BOARD=main）
# 2026-09-03 生产切换（用户拍板「直接切换，两版部署」）：主源 = 9 格网格 khunter_three_ver_opt_20260903.csv
#   A_x3（ob55+low3）= 旧生产主卖出配置（已升级）；C_x3（ob50+low3）= 并行参考配置；B_x3（30%止损）已否决
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
    """回退源：超卖伏击 全窗口回测（旧 ob75/osl35/gate none/breadth 0）"""
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
        # 纯主板：生产主信号 = 超卖伏击（2026-09-07 起 标准版(主卖出) ob59+低价3元；用户唯一可买主板）
        ss_stk[g] = KH_BT if KH_BT else {}
        ss_stk_tag[g] = ("超卖伏击 标准版主卖出 RSI>59 · 全窗口对比口径（生产=MA250 分域卡）" if not _KH_LEGACY
                         else ("超卖伏击主信号 · 全窗口(牛熊) · 无门控" if KH_BT else f"{label} · 暂无回测"))
    else:
        # 创业板/科创板：用户仅主板可买，超卖伏击 仅主板回测 → 明确说明卡
        ss_stk[g] = {}
        ss_stk_tag[g] = f"{label} · 用户仅主板可买 · 超卖伏击 未回测"
# 激进版参考卡（9 格网格存在时）
ss_stk["main_c"] = KH_BT_C if KH_BT_C else {}
ss_stk_tag["main_c"] = "超卖伏击 激进版参考卖出 RSI>50 · 全窗口对比口径（生产=MA250 卡）" if KH_BT_C else ""


def bt_card(cid, title, tag, s, curve_id, color="var(--warn)", sub="2016-01~2026-08"):
    """回测 KPI 卡（收益/年化/回撤·夏普 + 净值曲线容器）"""
    if not s:
        return f'<div class="bt-card" id="{cid}"><div class="bt-head"><b>{title}</b><span class="bt-tag">{tag}</span></div><div class="kpis"><div class="kpi"><div class="l">回测收益</div><div class="v">—</div><div class="s">回测中…</div></div></div><div class="bt-curve" id="{curve_id}"></div></div>'
    return f'''<div class="bt-card" id="{cid}">
<div class="bt-head"><b>{title}</b><span class="bt-tag">{tag}</span></div>
<div class="kpis">
<div class="kpi"><div class="l">回测收益</div><div class="v" style="color:{color}">{s["total_return_pct"]:+.1f}%</div><div class="s">{sub}</div></div>
<div class="kpi"><div class="l">年化</div><div class="v">{s["annual_return_pct"]:.1f}%</div><div class="s">胜率 {s.get("win_rate_pct",0):.0f}%</div></div>
<div class="kpi"><div class="l">最大回撤</div><div class="v" style="color:var(--up)">{s["max_drawdown_pct"]:.1f}%</div><div class="s">夏普 {s["sharpe"]:.2f} · {s.get("total_trades",0)} 笔</div></div>
</div>
<div class="bt-curve" id="{curve_id}"></div>
</div>'''


def bt_all_html():
    """中长线回测参考 5 卡（股票分层 4 + 基金；2026-08-17 去 ETF）"""
    cards = "".join([
        bt_card("bt-fund", "🥇 主仓 FB3-H20 基金线", FUND_TAG, s_fund, "curve-chart-fund", color="#3b82f6"),
        bt_card("bt-super", "🥉 卫星·SUPER", SUPER_TAG, s_super, "curve-chart-super", color="var(--warn)"),
    ])
    _ret = ('<div class="sub" style="color:var(--up)">⛔ <b>v9 股票分层战法（一体/主板/创业板/科创板四卡）已于 2026-09-13 退役</b>'
            '——十重证伪确认负期望（ADR-0006/0007），历史曲线与明细见更新日志 v5.9~v5.11.15 与 backtest/ 报告存档。</div>')
    return ('<div class="card" id="bt-all">\n'
            '<h2>📊 回测参考 <span class="badge badge-auto">中/长线 · 股票按权限分层</span></h2>\n'
            f'<div class="sub"><b>双轨 60/0/40（2026-09-16 起：卫星单轨化）</b>：主仓 = 基金 NAV 动量牛熊 regime（牛市 Top10/熊市 Top3）｜ 卫星 = 主板量价因子选股（全审计过闸）｜ 信号：<code>backtest/signal_satellite_0913.py</code> · <span style="color:var(--warn);font-weight:600">看板构建 {__import__("datetime").datetime.now():%Y-%m-%d %H:%M}</span></div>\n'
            '<div class="sub" style="color:var(--sub)">💧 <b>滑点敏感性</b>（每边，sweep_ml_slip.py 扫描）：中长线换手低、影响显著小于短线 —— 股票 20bps 收益 -23%（夏普 1.58→1.43）、30bps -31% ｜ 历史固定池（已去除）20bps -13%、30bps -18% —— 实盘 10-20bps 区间内中长线策略稳健</div>\n'
            '<div class="sub" style="color:var(--warn)">🐻 <b>9/1 牛熊独立权重验证（修正引擎 T+1 · regime=沪深300&gt;MA200 同口径）</b>：生产口径 A（牛开熊清 + 固定权重 0.35/0.25/0.20/0.20）收益 +28.3%/夏普 0.229/回撤 -27.15% 仍最优；牛攻熊守双权重 B/C/D/E 变体（熊市开仓）全面恶化（-25.9%~-65.0%）→ <b>中长期维持「牛开熊清」，熊市开仓不可行</b>（与短线基金相反：基金熊市防守开仓 +398pp 因选到避险型基金）</div>\n'
            '<div class="sub" style="margin-top:10px;padding:8px 10px;background:rgba(59,130,246,.08);border-left:3px solid #3b82f6;border-radius:4px">'
            '<b>🎯 双轨配置（2026-09-16 · 60/0/40）</b>｜'
            '<b>① 主仓 FB3-H20</b>（60%）：基金 NAV 动量牛熊 regime，牛市 Top10/熊市 Top3 · 2000 池回测 +733.4%/年化 21.95%/回撤 -27.0%/夏普 1.316｜'
            '<b>② SUPER 卫星</b>（40% · 2026-09-16 卫星单轨化）：13 因子（A4D 6 + Z哥战法原子 7：牛绳/止损空间/距BBI 等）Top20 月频 + 中证1000&lt;MA20 半仓且高波半区 · 回测 off0 年化 22.87%/<b>相位中位 1.151</b>/回撤 -22.0% · 安慰剂 500 p=0.000 · 50bp 压力档 S 1.00 · 100 万对照 S 1.30｜'
            '信号：<code>backtest/signal_satellite_0913.py</code>（每日收盘跑 → T+1 开盘清单，卫星与主仓信号均已交付）· '
            '⚠ 风险披露：双轨均为 2021 起回测口径，2021-2026 为结构性分化窗口</div>\n'
            '<div class="bt-grid">' + cards + '</div>\n' + _ret + '\n</div>')


def bt_short_html():
    """短线回测参考 5+1 卡
    2026-09-02 晚修复：旧战法弃用 → 纯主板卡改接 超卖伏击主信号回测（全窗口无门控 · 四闸 PASS）；
    一体卡=旧战法修正版 -41.67%（标注弃用）；创业板/科创板=用户不可买，明确说明卡
    2026-09-03 生产切换：纯主板卡= 标准版 ob55+低价3元（主卖出）+ 激进版 ob50（参考卖出）双卡（资金池口径含回撤）；
    2026-09-07 MA250 分域投产（ob58→ob59 升级）：生产=MA250 分域卡（熊 MA250 下 osl35+low3+ob59 / 牛 MA20 上 osl32+ob75）；
    B 版(30%止损)已否决不入卡"""
    def _card(cid, title, tag, s, curve_id, color="var(--warn)"):
        if not s:
            # 说明卡（创业板/科创板未回测等）
            return (f'<div class="bt-card" id="{cid}" style="border-color:rgba(120,113,108,.3)">'
                    f'<div class="bt-head"><b>{title}</b><span class="bt-tag">{tag}</span></div>'
                    f'<div class="kpis"><div class="kpi"><div class="l">回测收益</div>'
                    f'<div class="v" style="color:var(--faint)">未回测</div>'
                    f'<div class="s">用户仅可买主板；超卖伏击主信号仅按主板回测</div></div>'
                    f'<div class="kpi"><div class="l">说明</div><div class="v" style="font-size:15px;color:var(--faint)">—</div>'
                    f'<div class="s">主板卡以 超卖伏击 全窗口回测为准</div></div></div></div>')
        # 超卖伏击 卡是自定义结构（dict 字段与 summary 不同），单独渲染
        if "ex_m" in s:
            _pool = s.get("pool_mdd") is not None
            if _pool:
                _kpi3 = (f'<div class="kpi"><div class="l">资金池(N5) 回撤</div>'
                         f'<div class="v" style="color:var(--up)">{s["pool_mdd"]:.1f}%</div>'
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
    _c_cards = (f'{_card("bt-short-stock-main-c", "📈 短线 纯主板 · 激进版(OB50 参考)", ss_stk_tag["main_c"], ss_stk["main_c"], "curve-short-stock-main-c", color="#64748b")}'
                if KH_BT_C else "")
    # 🌟 MA250 牛熊分域总卡（生产口径 · 组合化资金 · Phase 11 · 2026-09-07 投产 · ob59 最终版）
    _hybrid_card = ('''<div class="bt-card" id="bt-short-stock-hybrid" style="border-color:rgba(37,99,235,.5)">
<div class="bt-head"><b>🌟 生产口径：牛熊分域 MA250 总卡（ob59）</b><span class="bt-tag">组合化资金 · 正在用的就是它</span></div>
<div class="kpis">
<div class="kpi"><div class="l">组合总收益</div><div class="v" style="color:var(--up)">+119.4%</div><div class="s">n=266 · 胜率 62.4% · ob59 定稿</div></div>
<div class="kpi"><div class="l">最大回撤</div><div class="v" style="color:var(--up)">-20.91%</div><div class="s">夏普 0.648 · 均值 +3.08%/笔 · 满窗验证</div></div>
<div class="kpi"><div class="l">牛(>MA20)</div><div class="v" style="color:var(--up)">med +4.67%</div><div class="s">n=65 · wr 62% · 独立过闸</div></div>
<div class="kpi"><div class="l">熊(&lt;MA250)</div><div class="v" style="color:var(--up)">med +2.78%</div><div class="s">n=201 · wr 62% · 独立过闸</div></div>
</div>
<div class="kpis">
<div class="kpi"><div class="l">前后半双过</div><div class="v" style="color:var(--up)">med +2.93/+2.92</div><div class="s">h1/h2 · 11 年 8 正 3 负</div></div>
<div class="kpi"><div class="l">弱牛回调(MA20下/MA250上)</div><div class="v" style="color:var(--up)">med +2.95%</div><div class="s">n=28 · wr 57.1% · 近四闸(n&lt;30) · 2026-09-04 投产</div></div>
</div></div>''')
    cards = "".join([
        _card("bt-short-stock-all", "📈 短线 股票 一体", ss_stk_tag["all"], ss_stk["all"], "curve-short-stock-all"),
        _card("bt-short-stock-main", "📈 短线 纯主板 · 标准版(主卖出 RSI>59)", ss_stk_tag["main"], ss_stk["main"], "curve-short-stock-main", color="var(--warn)"),
        _c_cards,
        _hybrid_card,
        _card("bt-short-stock-gem", "📈 短线 纯创业板", ss_stk_tag["gem"], ss_stk["gem"], "curve-short-stock-gem"),
        _card("bt-short-stock-star", "📈 短线 纯科创板", ss_stk_tag["star"], ss_stk["star"], "curve-short-stock-star"),
        bt_card("bt-short-fund", "🔵 短线 基金", ss_fund_tag, ss_fund, "curve-short-fund", color="#3b82f6"),
    ])
    return ('<div class="card" id="bt-short">\n'
            '<h2>⚡ 短线回测参考 <span class="badge badge-auto">生产主信号=超卖伏击 · 修正引擎 T+1 · 2026-09-07 牛熊分域(MA250) + 09-04 弱牛域</span></h2>\n'
            '''<div class="sub">📊 <b>短线「在用什么」= 牛熊分域(进场) + 标准版/激进版(卖出线)，外加 H6 动量强弱切换(打分)</b>——三个独立维度，别混：
① <b>牛熊分域（MA250 买入框架 + 09-04 弱牛域）</b>：🐻 熊市(沪深300&lt;MA250)：超卖伏击信号+RSI&lt;35+收盘≥3元 → 可买；🌞 牛市(&gt;MA20)：信号+RSI&lt;32+无低价 → 可买；🌙 弱牛回调(MA20 下/MA250 上)：<b>RSI&lt;32+无低价 → 可买</b>（2026-09-04 专项投产，2026-09-07 MA250 定稿总收益 +119.4%）。
② <b>标准版/激进版（卖出参考线）</b>：标准版=主执行（熊市 RSI&gt;59 / 牛市 RSI&gt;75 / 弱牛 RSI&gt;80）；激进版=参考（RSI&gt;50 更早止盈）。<b>两版买入规则完全相同</b>，只有卖出线不同。
③ <b>H6 三态（短线打分权重）</b>：沪深300 20d 动量&gt;2% = 强牛（进攻权重+关动量 mask+S50 门槛）／≤2% 且&gt;MA20 = 弱牛（防守权重+全 mask+S55）／不满足 = 熊市清仓。这个决定「入选池怎么打分」，与开仓/卖出无关。<b>模拟盘标准/激进前向对决后定稿</b></div>\n'''
            '<div class="sub" style="color:var(--sub)">💧 <b>回撤就看一张卡</b>：正在用的 = <b>生产口径 MA250 卡（回撤 -20.91%）</b>——牛熊分域入场 + 标准版 ob59 卖出，组合化资金计算。标准版/激进版两张卡是<b>全窗口单笔口径</b>（n=266，2026-09-07 ob59 定稿），用于两版对比（买相同、卖不同），<b>不是</b>生产真实回撤。买卖均为 T 日收盘确认 → T+1 开盘执行；回撤=资金池固定 5 仓等权 NAV。<b>旧战法（反转打分）已弃用</b>（-41.67% 仅对照）</div>\n'
            '<div class="sub" style="color:#7c3aed">🧪 <b>9/1 熊市三策略吸收验证（用户框架规则化 · 修正引擎 T+1）</b>：S1 超跌反弹单笔 +0.48%/胜率 52.6% 但<b>几何均值 -1.73%</b>、S3 右侧追涨单笔 +2.79%/胜率 69.2% 但<b>组合复利 -92.9%</b>、S2 抗跌强势负期望 —— <b>三策略全部 FAIL 组合级四闸</b>。结论：<b>熊市入场过滤救不了逆势，唯一可行=熊市空仓/极端轻仓</b>（例外：超卖伏击主信号自身承担风险过滤，熊市开仓全窗口实测过闸）</div>\n'
            '<div class="bt-grid">' + cards + '</div>\n</div>')
perm_stat = ''   # 2026-08-21 固定池已去除

def bt_a5_html():
    """首板低吸回测参考卡（v1.3 · 2026-09-15 双池独立滤网上线）
    口径：线上基底（rel_pos≤0.5 + amt≥5e7 + room≥0.20）上叠加双池——池A 超跌 ret20≤-7.31% / 池B 趋势 ADX14≥27.9
    数据：R-daban-opt-0915（真实 amount + 严格 rel_pos 修正口径，2016-2026，含成本）"""
    c1 = f'''<div class="bt-card" id="bt-a5-all">
<div class="bt-head"><b>🆕 v1.3 双池独立滤网（2026-09-15 上线）</b><span class="bt-tag">各自独立 · 不做共振交集</span></div>
<div class="kpis">
<div class="kpi"><div class="l">池A 超跌 ret20≤-7.31%</div><div class="v" style="color:var(--up)">+1.37%/笔</div><div class="s">n=282 · 胜率 58.2% · 10/10 年正</div></div>
<div class="kpi"><div class="l">池B 趋势 ADX≥27.9</div><div class="v" style="color:var(--up)">+1.19%/笔</div><div class="s">n=255 · 胜率 54.9% · 8/10 年正</div></div>
<div class="kpi"><div class="l">并集（验证门基准）</div><div class="v" style="color:var(--up)">+1.19%/笔</div><div class="s">n=396 · 胜率 56.1% · ≈38.6 笔/年</div></div>
<div class="kpi"><div class="l">对照：旧口径基底</div><div class="v">+0.57%/笔</div><div class="s">n=692 · 胜率 50.6%（v1 归档 11 笔 -1.71%）</div></div>
</div></div>'''
    return (f'<div class="card" id="bt-a5">\n'
            f'<h2>🏆 首板低吸（生产配置） <span class="badge badge-auto">v1.3 双池独立滤网 · 2026-09-15 上线</span></h2>\n'
            f'<div class="sub">生产预筛 = <b>rel_pos≤0.5 + 成交额≥5000万 + 距60日高点≥20%（ROOM_MIN=0.20）</b> + <b>双池至少命中其一（池A 超跌 ret20≤-7.31% / 池B 趋势 ADX14≥27.9，各自独立成池）</b> + 首板次日低开 gap∈[-5%,-2%] + 止盈 8%/2 天</div>\n'
            f'<div class="sub" style="color:#059669">✅ <b>R-daban-opt-0915 实测（修正口径：真实 amount + 严格 rel_pos）</b>：线上基底 692 笔 +0.57% → 双池并集 396 笔 +1.19%（池A 单独最强 10/10 年正）；差窗口 2024-05 后 并集 +0.35% vs 基底 -0.40%。<b>验证门基准随口径切换为并集（56.1%/+1.19%/tp25.0%），新口径独立计数</b></div>\n'
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
    _v1n = st.get("v1_n", 0)
    _v1s = f' · v1 归档 {_v1n} 笔' if _v1n else ''
    kpis.append(f'<div class="kpi"><div class="l">已平仓信号（新口径）</div><div class="v">{st.get("n", 0)}<span style="font-size:13px;color:var(--faint)">/30</span></div><div class="s">触发验证门判定{_v1s}</div></div>')
    wr = st.get("win_rate")
    kpis.append(f'<div class="kpi"><div class="l">模拟盘胜率</div><div class="v">{f"{wr:.1f}%" if wr is not None else "—"}</div><div class="s">回测基准 {bench.get("win_rate", "—")}%</div></div>')
    mn = st.get("mean_net")
    kpis.append(f'<div class="kpi"><div class="l">均值净收益</div><div class="v" style="color:{("var(--up)" if (mn or 0) >= 0 else "var(--down)")}">{f"{mn:+.2f}%" if mn is not None else "—"}</div><div class="s">基准 {bench.get("mean_net", "—"):+.2f}% · 闸 &gt;+0.5%</div></div>')
    tp = st.get("tp_ratio")
    kpis.append(f'<div class="kpi"><div class="l">止盈出场占比</div><div class="v">{f"{tp:.1f}%" if tp is not None else "—"}</div><div class="s">基准 {bench.get("tp_ratio", "—")}% · 闸 [15,35]%</div></div>')
    kpis.append(f'<div class="kpi"><div class="l">模拟盘净值</div><div class="v">{st.get("nav", 1.0):.4f}</div><div class="s">已平仓复利</div></div>')

    # 验证门三闸
    gwr, gmn, gtp = gate.get("wr", {}), gate.get("mn", {}), gate.get("tp", {})
    def _gate_pill(g, label, base):
        if g.get("status") == "waiting":
            return f'<span class="op op-watch">⏳ {label} {g.get("note", "")}</span>'
        flag = "✓" if g.get("status") == "PASS" else "✕"
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
    def _name_code(name, code, extra=""):
        """标的名称+代码同格（2026-09-06 用户需求：对齐中长线标的池 tbl-v9 格式）——
        粗体名称 + 可选标签，换行 + 淡色小号代码"""
        return _txt_td(f'<b>{name}</b>{extra}<br><span style="color:var(--faint);font-size:11px">{_bare(code)}</span>')
    def _buyhit_td(c):
        """明日买点（R-qlch-buyhint-0922）：今收 × [0.95, 0.98]，跳空 −5%~−2% 才买。
        与「超跌低开低吸」同口径（打板信号本就是首板次日低开 2-5%，GAP_LO/HI 完全相同）。"""
        if not isinstance(c, (int, float)) or c <= 0:
            return '<td>—</td>'
        return ('<td><span class="badge badge-auto">● 跳空 −5%%~−2%% 才买</span>'
                '<div style="margin-top:3px;font-variant-numeric:tabular-nums">%.3f ~ %.3f</div></td>'
                % (round(c * 0.95, 3), round(c * 0.98, 3)))

    def _row(attrs, cells):
        return (attrs, cells)

    # 观察清单（板块列与 v9 同标准：主板/创业板/科创板；行业进 data-search + 悬浮提示）
    def _gate_cell(w, with_val=True):
        """生产预筛标注：F3 空间因子（首板日距前60日收盘高点≥20%）+ rel_pos≤0.5（v1.3 起为双池滤网的前置条件）"""
        dh = w.get("dist_high") if w.get("dist_high") is not None else w.get("dist_high60")
        rp = w.get("rel_pos")
        ok = (dh is not None and dh >= 20) and (rp is None or rp <= 0.5)
        if ok:
            inner = f'<span class="board-tag board-sh" title="生产预筛：F3空间≥20% + 低位rel≤0.5（池A/池B 为附加滤网）">✓</span>'
            return f'<td>{inner} {dh:.0f}%</td>' if with_val else f'<td>{inner}</td>'
        return _txt_td("—")
    wl_rows = [_row(
        {"data-code": w["code"], "data-search": f'{w["name"]} {_bare(w["code"])} {w.get("ind", "")} {w.get("board", "")}',
         "data-market": w.get("board", ""), "data-industry": w.get("ind", "")},
        [_name_code(w["name"], w["code"]), _txt_td(_board_cell(w.get("board"), w.get("ind"))),
         _txt_td(w.get("ind", "—")),
         _txt_td(w["sb_date"]), _txt_td("/".join(w.get("pools", [])) or "—"), _num_td(w.get("rel_pos"), 2), _txt_td(f'{w.get("amt", 0)/1e4:.0f}'),
         _gate_cell(w), _chg_td(w.get("chg")), _pct_td(w.get("ret_1y"), 1),
         _num_td(w.get("rsi"), 1), _num_td(w.get("vr"), 2), _pct_td(w.get("ma5_dev"), 1),
         _buyhit_td(w.get("last_close"))])
        for w in sorted(wl, key=lambda x: -x.get("amt", 0))]
    # 回避清单
    av_rows = [_row(
        {"data-code": a["code"], "data-search": f'{a["name"]} {_bare(a["code"])} {a.get("ind", "")} {a.get("board", "")}',
         "data-market": a.get("board", ""), "data-industry": a.get("ind", "")},
        [_name_code(a["name"], a["code"]), _txt_td(_board_cell(a.get("board"), a.get("ind"))),
         _txt_td(a.get("ind", "—")),
         _txt_td(a["sb_date"]), _pct_td(a.get("gap")*100, 2), _num_td(a.get("rel_pos"), 2),
         _txt_td(f'{a.get("amt", 0)/1e4:.0f}'), _chg_td(a.get("chg")), _pct_td(a.get("ret_1y"), 1),
         _num_td(a.get("rsi"), 1), _num_td(a.get("vr"), 2), _pct_td(a.get("ma5_dev"), 1)])
        for a in sorted(av, key=lambda x: -x.get("amt", 0))]
    # 持仓（板块列与观察/回避清单对齐）
    pos_rows = [_row(
        {"data-code": p["code"], "data-search": f'{p["name"]} {_bare(p["code"])} {p.get("ind", "")} {p.get("board", "")}',
         "data-market": p.get("board", ""), "data-industry": p.get("ind", "")},
        [_name_code(p["name"], p["code"]), _txt_td(_board_cell(p.get("board"), p.get("ind"))),
         _txt_td(p.get("ind", "—")),
         _txt_td(p["entry_date"]), _num_td(p["entry_px"], 2), _pct_td(p.get("gap")*100, 2),
         _txt_td("/".join(p.get("pools", [])) or "v1"), _txt_td(f'T+{p.get("exit_stage", 1)}'), _chg_td(p.get("chg")), _pct_td(p.get("ret_1y"), 1),
         _num_td(p.get("rsi"), 1), _num_td(p.get("vr"), 2), _pct_td(p.get("ma5_dev"), 1)])
        for p in sorted(pos, key=lambda x: x.get("entry_date", ""))]
    # 已平仓（出场原因中文化）
    REASON_CN = {"tp": "止盈", "ts": "收盘卖", "force": "强平"}
    closed_new = [p for p in closed if p.get("pools")]     # v1.3：看板只列新口径；v1 归档见复盘日志/state
    closed_rows = [_row(
        {"data-code": p["code"], "data-search": f'{p["name"]} {_bare(p["code"])} {p.get("ind", "")} {p.get("board", "")}',
         "data-market": p.get("board", ""), "data-industry": p.get("ind", "")},
        [_name_code(p["name"], p["code"]), _txt_td(_board_cell(p.get("board"), p.get("ind"))),
         _txt_td(p.get("ind", "—")),
         _txt_td(p["entry_date"]), _txt_td(p["exit_date"]), _num_td(p["entry_px"], 2), _num_td(p["exit_px"], 2),
         _txt_td(REASON_CN.get(p["exit_reason"], p["exit_reason"] or "—")),
         _txt_td("/".join(p.get("pools", [])) or "v1"),
         _pct_td(p.get("net_ret", 0)*100, 2), _chg_td(p.get("chg")), _pct_td(p.get("ret_1y"), 1),
         _num_td(p.get("rsi"), 1), _num_td(p.get("vr"), 2)])
        for p in closed_new]
    # 净值曲线（模拟盘点数少，线性折线）
    curve_html = ""
    if len(eq) >= 2:
        pts = " ".join(f"{i},{v['nav']}" for i, v in enumerate(eq))
        curve_html = (f'<svg viewBox="0 0 600 120" style="width:100%;max-width:700px;margin-top:10px">'
                      f'<polyline points="{pts}" fill="none" stroke="var(--warn)" stroke-width="2"/>'
                      f'<text x="8" y="16" font-size="12" fill="var(--faint)">模拟盘净值 {st.get("nav", 1.0):.4f}（{len(eq)} 个交易点）</text></svg>')
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
            tag = '<span class="badge" style="background:rgba(5,150,105,.18);color:var(--down)">✅ 双池命中</span>'
        elif sealed:
            tag = '<span class="badge" style="background:rgba(217,119,6,.15);color:#fbbf24">封板</span>'
        else:
            tag = '<span class="badge" style="background:rgba(107,114,128,.15);color:#9ca3af">未封</span>'
        st = []
        if yz:
            st.append('<span class="badge" style="background:rgba(239,68,68,.14);color:var(--up)">一字</span>')
        elif fb:
            st.append('<span class="badge" style="background:rgba(37,99,235,.14);color:#60a5fa">首板</span>')
        elif sealed:
            st.append('<span class="badge" style="background:rgba(37,99,235,.14);color:#60a5fa">连板</span>')
        st_html = "".join(st) or '<span style="color:var(--faint)">—</span>'

        # v1.3 双池标签（2026-09-15 用户需求：双池直接上全景卡）
        _pools = s.get("pools", []) or []
        _pt = []
        if "R20" in _pools:
            _pt.append('<span class="badge" style="background:rgba(5,150,105,.18);color:var(--down)" '
                       f'title="池A 超跌：r20 {s.get("r20")}%（需 ≤-7.31%）">A·超跌</span>')
        if "ADX" in _pools:
            _pt.append('<span class="badge" style="background:rgba(37,99,235,.16);color:#60a5fa" '
                       f'title="池B 趋势：ADX {s.get("adx")}（需 ≥27.9）">B·趋势</span>')
        _pool_html = "".join(_pt) or '<span style="color:var(--faint)">—</span>'

        # 档位/建议（2026-09-05 用户需求：命中标签之外给操作建议）
        tier = s.get("tier", "不追")
        advice = s.get("advice", "")
        if hit:
            tier_badge = f'<span class="badge" style="background:rgba(5,150,105,.18);color:var(--down)">观察</span>'
        else:
            tier_badge = f'<span class="badge" style="background:rgba(107,114,128,.15);color:#9ca3af">不追</span>'
        zp_rows.append(_row(
            {"data-code": s["code"], "data-search": f'{s["name"]} {_bare(s["code"])} {s.get("ind", "")} {s.get("board", "")}',
             "data-market": s.get("board", ""), "data-industry": s.get("ind", "")},
            [_name_code(s["name"], s["code"]), _txt_td(_board_cell(s.get("board"), s.get("ind"))),
             _txt_td(s.get("ind", "—")), _chg_td(s.get("pct")), _txt_td(st_html),
             _txt_td(f'{s.get("amt", 0)/1e8:.2f}'), _num_td(s.get("rel_pos"), 2),
             _pct_td(s.get("dist_high"), 1), _txt_td(_pool_html), _txt_td(tag), _txt_td(tier_badge),
             _txt_td(f'<span class="adv-cell" style="color:var(--sub);font-size:11.5px">{advice}</span>'),
             _buyhit_td(s.get("close"))]))
    zp_html = f'''<div class="card" id="a5-zt" style="border-color:rgba(5,150,105,.35)">
<h2>🔥 今日涨停全景 <span class="badge badge-auto">{len(zp_stocks)} 只 · 双池命中 {len(zp_hits)} 只（池A {sum(1 for x in zp_hits if "R20" in (x.get("pools") or []))} · 池B {sum(1 for x in zp_hits if "ADX" in (x.get("pools") or []))}）</span></h2>
<div class="sub">收盘涨幅 ≥9.5% 或封板标的（{zp_date} 收盘口径）· <b>✅ 双池命中</b> = 首板 + 非一字 + rel_pos≤0.5 + F3空间≥20% + 成交额≥5000万 + <b>池A 超跌（ret20≤-7.31%）/ 池B 趋势（ADX14≥27.9）至少命中其一</b>（v1.3 双池独立）· 滤网池列：A·超跌 / B·趋势（悬浮可见实测值）· <b>明日买点</b> = 今收 × [0.95, 0.98]（首板次日低开 2-5% 才买，与「超跌低开低吸」同口径）· 纯观察，不构成交易信号</div>
{_a5_tbl_full("a5-zt", [("name","标的"),("board","板块"),("ind","行业"),("pct","涨幅"),("status","状态"),("amt","成交额(亿)"),("relpos","相对位置"),("dist","空间%"),("pools","滤网池"),("hit","命中"),("tier","档位"),("advice","建议"),("buy","明日买点")], zp_rows, "（今日无 ≥9.5% 标的）")}
</div>'''
    return f'''<div class="view" id="view-a5">
<div class="card" id="sys-a5">
<div class="sys-head">
<div class="sys-head-top">
<h2>🎯 首板低吸（双池滤网 v1.3） <span class="view-badge auto">池A 超跌 / 池B 趋势 · 模拟盘观察</span></h2>
{asof_badge}
</div>
<div class="sys-head-tags">
<span class="badge badge-auto" style="background:#059669;color:#fff">✅ v1.3 双池独立滤网（2026-09-15 上线）· 模拟盘观察中</span>
<span class="badge badge-auto">信号 = 首板次日低开 2-5% + rel_pos≤0.5 + 成交额≥5000万 + <b>双池至少命中其一（池A 超跌 / 池B 趋势）</b></span>
<span class="badge badge-auto">出场 = 止盈+T+2（+8% 止盈 / T+2 兜底）</span>
</div>
<div class="sys-head-note"><b>定位</b>：<b>v1.3 双池独立滤网（2026-09-15 用户拍板替换生产口径）</b>——在生产预筛（首板 + rel_pos≤0.5 + F3 空间≥20% + 成交额≥5000万）之上叠加 <b>池A 超跌（ret20≤-7.31%）</b> 与 <b>池B 趋势（ADX14≥27.9）</b>，<b>两因子各自独立成池、不做共振交集</b>（回测：并集 396 笔 +1.19%/笔、胜率 56.1%、≈38.6 笔/年；池A 10/10 年正）。模拟盘验证门基准随口径切换、新口径独立计数（v1 旧口径 11 笔归档）；通过前不改实盘权重</div>
</div>
<div class="kpis">{''.join(kpis)}</div>
{gate_bar}
</div>
{zp_html}
{subnav("a5", [("a5-watch", "观察清单"), ("a5-avoid", "回避清单"), ("a5-pos", "持仓"),
               ("a5-closed", "已平仓"), ("a5-curve", "净值曲线")], default_key="a5-watch")}
<div class="subview" id="sv-a5-watch">
<div class="pool-sec"><b>观察清单</b><span>今日首板 · 明日低开 2-5% 则入场</span></div>
<div class="card" id="a5-watchlist">
<h2>📋 观察清单 <span class="badge badge-auto">{len(wl)} 只</span></h2>
<div class="sub">今日首板 · 双池至少命中其一（池A 超跌 / 池B 趋势）· 明日低开 2-5% 则入场 · 当日涨跌幅为实时数据，近一年/RSI/量比/MA5偏离为收盘口径</div>
{_a5_tbl_full("a5-wl", [("name","标的"),("board","板块"),("ind","行业"),("sbdate","首板日"),("pools","滤网池"),("relpos","相对位置"),("amt","成交额(万)"),("gate","过闸"),("chg","涨跌幅"),("ret1y","近一年"),("rsi","RSI"),("vr","量比"),("ma5dev","MA5偏离"),("buy","明日买点")], wl_rows, "（无观察标的）")}
</div>
</div>
<div class="subview" id="sv-a5-avoid">
<div class="pool-sec"><b>回避清单</b><span>负期望警示 · 只提示不拦单</span></div>
<div class="card" id="a5-avoid" style="border-left:3px solid rgba(217,119,6,.55)">
<h2>⚠ A2_tp3 回避清单 <span class="badge badge-auto">{len(av)} 只 · 负期望警示</span></h2>
<div class="sub">今日满足 A2_tp3 信号（首板次日低开 2-6% + 相对位置≤0.7 + 成交额≥5000万）· 回测胜率 63.1% 但单笔均值 -1.39%（盈亏比 0.29）→ <b>信号出现时回避或减仓，不追高</b></div>
{_a5_tbl_full("a5-av", [("name","标的"),("board","板块"),("ind","行业"),("sbdate","首板日"),("gap","今日低开"),("relpos","相对位置"),("amt","成交额(万)"),("chg","涨跌幅"),("ret1y","近一年"),("rsi","RSI"),("vr","量比"),("ma5dev","MA5偏离")], av_rows, "（无）")}
</div>
<div class="pool-sec"><b>模拟盘</b><span>双池 v1.3 · 持仓与净值</span></div>
</div>
<div class="subview" id="sv-a5-pos">
<div class="pool-sec"><b>持仓</b><span>模拟盘在仓 · 止盈 +8% / T+2 兜底</span></div>
<div class="card" id="a5-positions">
<h2>💼 模拟盘持仓 <span class="badge badge-auto">{len(pos)} 只</span></h2>
<div class="sub">入场 = 开盘价低开确认 · 出场 T+1/T+2 冲高≥入场×1.08 止盈，否则收盘卖；涨停顺延/强平</div>
{_a5_tbl_full("a5-pos", [("name","标的"),("board","板块"),("ind","行业"),("entrydate","入场日"),("entrypx","入场价"),("gap","低开"),("pools","滤网池"),("stage","出场阶段"),("chg","涨跌幅"),("ret1y","近一年"),("rsi","RSI"),("vr","量比"),("ma5dev","MA5偏离")], pos_rows, "（无持仓）")}
</div>
</div>
<div class="subview" id="sv-a5-closed">
<div class="pool-sec"><b>已平仓</b><span>逐笔净收益 · 累计 ≥30 笔触发验证门</span></div>
<div class="card" id="a5-closed">
<h2>📜 已平仓（新口径） <span class="badge badge-auto">{len(closed_new)} 笔 · v1 归档 {len(closed) - len(closed_new)} 笔</span></h2>
<div class="sub">模拟盘逐笔净收益（含成本买 0.525%/卖 0.625%）· 累计 ≥30 笔触发验证门判定 · <b>v1 旧口径 11 笔（均值 −1.71%）已归档</b>（完整记录见复盘日志与 paper_state.json，不再逐笔展示）</div>
{_a5_tbl_full("a5-cl", [("name","标的"),("board","板块"),("ind","行业"),("entrydate","入场日"),("exitdate","出场日"),("entrypx","入场价"),("exitpx","出场价"),("reason","原因"),("pools","滤网池"),("netret","净收益"),("chg","涨跌幅"),("ret1y","近一年"),("rsi","RSI"),("vr","量比")], closed_rows, "（新口径尚无平仓记录——2026-09-15 起计）")}
</div>
</div>
<div class="subview" id="sv-a5-curve">
<div class="pool-sec"><b>净值曲线</b><span>已平仓复利 · 验证边缘是否存在</span></div>
<div class="card" id="a5-curve">
<h2>📈 模拟盘净值曲线 <span class="badge badge-auto">已平仓复利</span></h2>
<div class="sub">回测（v1.3 修正口径）：线上基底 5 槽位组合 +18.9%/回撤 −35.4%；双池并集 +39.7%/回撤 −8.7%（近似模拟）。净值曲线验证的是边缘是否存在而非盈利，小仓位实验形态</div>
{curve_html}
<div class="pool-sec"><b>回测数据</b><span>打板双池</span></div>
{bt_a5_html()}
</div>
</div>
{ASSET_HINT}
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
        _tag = "盘中实时" if intraday_note else "现价"
        _ts = as_of_min or ("15:00" if not intraday_note else "")
        _ts_html = f" {_ts}" if _ts else ""
        asof_html = f'<span class="view-badge auto" title="{intraday_note or "收盘数据"}">数据截至 {as_of}{_ts_html} · {_tag}</span>'
    stat_bar = (extra_stat if extra_stat else "") + f'''<div class="op-stats">
<span class="op op-add">🟢 加仓区 <b>{sum(t8.get(t,0) for t in tier_add)}</b> 只</span>
<span class="op op-watch">🟡 观望 <b>{sum(t8.get(t,0) for t in tier_watch)}</b> 只</span>
<span class="op op-cut">🔴 减/清仓区 <b>{sum(t8.get(t,0) for t in tier_cut)}</b> 只</span>
</div>'''
    tier_opts_html = "".join(f"<option>{t}</option>" for t in tier_opts)
    # 子项列（2026-09-18）：按 score_sub 的 '/' 拆成每指标一列（股票 5 项 / 基金 2 项）
    _sub_th = "".join(
        f'<th data-key="sub{i}" style="text-align:center">{lb}</th>'
        for i, lb in enumerate([x for x in str(score_sub).split("/") if x]))
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
<th data-key="rank" style="text-align:center">#</th><th data-key="name">标的</th><th data-key="board">板块</th><th data-key="industry">行业</th><th data-key="px" style="text-align:right">现价</th>
<th data-key="chg" style="text-align:right">涨跌幅</th><th data-key="ret1y" style="text-align:right">近一年</th><th data-key="score" style="text-align:center">权重总分</th>{_sub_th}<th data-key="rsi" style="text-align:center">RSI</th><th data-key="vp" style="text-align:center">量能</th>
<th data-key="conf" style="text-align:center">置信度</th><th data-key="tier" style="text-align:center">档位</th><th data-key="tierchg" style="text-align:center">档位变化</th><th data-key="action" style="text-align:center">建议动作</th>
</tr></thead>
<tbody>{rows_html_for(items, score_sub)}</tbody>
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


# ════════════════════════════════════════════════════════════════════
# 跟踪池卡（R-track-sep-0923 · 2026-09-23 用户批准「跟踪池按策略独立」）
# 原「页面级共享卡」→ 参数化渲染函数：短线 5 个子视图**各挂一张**，只显示本策略标的。
#   key         子视图键（st-stk/st-qlch/st-kh/st-etf/st-fund）→ 唯一 DOM id 后缀
#   title       策略名 → 卡标题「👁 跟踪池 · <title>」
#   source_kind 'short' = 浏览器端渲染（window.SHORT_POOL.track，带搜索/筛选/排序）
#               其它   = 构建期渲染（Python **只读**该策略自己的账本/状态文件）
#   cols        [(表头, 行字典键, 对齐)]；'short' 走 JS 自带表头（传 None）
# 数据源一律「策略自有」：跨策略文件不上卡（静态断言见 _verify_qlch_live.py）。
# ════════════════════════════════════════════════════════════════════
WATCH_NAMES = {}
try:
    WATCH_NAMES = json.loads((BASE / "data_full_names.json").read_text(encoding="utf-8"))
except Exception as _e:
    print("跟踪池名称表加载失败:", _e)

# 各策略状态文件搜索序（根目录 → dist/ → backtest/）——写作期的路径漂移不静默失败
WATCH_STATE_DIRS = ("", "dist", "backtest")
WATCH_NAMES_MISSING = ["code（6 位基金代码）", "name（基金名称）", "signal_date（入选信号日）",
                       "entry_date（建仓净值日）", "entry_px（建仓单位净值）", "shares（份额）",
                       "last_nav（最新净值，用于浮动盈亏）", "exit_rule / exit_date（出场：跌破 MA/掉出基金池 Top-N）",
                       "nav_history（账户净值序列）"]


def _watch_state_path(name):
    for _d in WATCH_STATE_DIRS:
        p = (BASE / _d / name) if _d else (BASE / name)
        if p.exists():
            return p
    return None


def _watch_load(name):
    p = _watch_state_path(name)
    if not p:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _w_tgt(code, name=None):
    """标的列（与看板其它表同格式：上行名称加粗 / 下行 6 位码）"""
    c6 = _bare(code)
    return ('<b>%s</b><br><span style="color:var(--sub);font-size:var(--fs-xs);'
            'font-variant-numeric:tabular-nums">%s</span>'
            % (name or WATCH_NAMES.get(code, "") or c6, c6))


def _w_board(code):
    """板块列（四档徽章）。⚠ ETF/场外基金不是「主板」——按资产类型标注，避免误导（不编造板块）。"""
    c = str(code or "")
    if c.startswith(("sh5", "sz1")):
        return _board_cell("ETF")
    if not c.startswith(("sh6", "sz0", "sz3")):
        return _board_cell("—")
    return _board_cell(_board_of6(_bare(c)))


def _w_num(v, nd=3):
    return "—" if not isinstance(v, (int, float)) else (("%%.%df" % nd) % v)


def _w_pct(v, nd=2):
    return "—" if not isinstance(v, (int, float)) else ("%+.*f%%" % (nd, v * 100))


def _w_rows_qlch():
    """超跌低开低吸：六臂账本（backtest/qlch_paper_state*.json）的 positions + trades。
    列：标的 / 板块 / 轨 / 状态 / 入场日 / 入场价 / 出场日 / 净收益。"""
    out = []
    for _key, _label, _fn, _tag in QLCH_TRACKS:
        d = _watch_load(_fn)
        if not d:
            continue
        arm = _label.split("（")[0]
        for p in (d.get("positions") or []):
            c = p.get("code", "")
            out.append((p.get("entry_date") or "", {
                "code": c, "name": p.get("name") or WATCH_NAMES.get(c, ""),
                "tgt": _w_tgt(c, p.get("name")), "board": _w_board(c), "arm": arm,
                "state": '<span class="up">持仓中</span>',
                "d0": p.get("entry_date") or "—", "px": _w_num(p.get("entry_px")),
                "d1": "—", "ret": "—"}))
        for t in (d.get("trades") or []):
            c = t.get("code", "")
            if not c:
                continue
            out.append(((t.get("exit_date") or t.get("entry_date") or ""), {
                "code": c, "name": t.get("name") or WATCH_NAMES.get(c, ""),
                "tgt": _w_tgt(c, t.get("name")), "board": _w_board(c), "arm": arm,
                "state": '<span class="sub">已成交</span>',
                "d0": t.get("entry_date") or "—", "px": _w_num(t.get("entry_px")),
                "d1": t.get("exit_date") or "—", "ret": _w_pct(t.get("net_ret"))}))
    out.sort(key=lambda x: x[0], reverse=True)
    return [r for _d, r in out], []


def _w_rows_kh():
    """超卖伏击：A 轨（标准 · khunter_paper_state.json）+ C 轨（激进 · khunter_paper_state_c.json）
    的 positions / pending / trades（**只读**账本，不写）。
    列：标的 / 板块 / 轨 / 状态 / 日期 / 价格 / 最新价 / 持有。"""
    out = []
    for fn, arm in (("khunter_paper_state.json", "标准 A"),
                    ("khunter_paper_state_c.json", "激进 C")):
        d = _watch_load(fn)
        if not d:
            continue
        _nh = d.get("nav_history") or []
        _last_d = _nh[-1].get("date", "") if _nh else ""
        pend_sell = set(d.get("pending_sells") or [])
        for p in (d.get("positions") or []):
            c = p.get("code", "")
            st = ('<span class="warn">待卖出 · T+1 开盘</span>' if c in pend_sell
                  else '<span class="up">持仓中</span>')
            out.append((p.get("entry_date") or "", {
                "code": c, "name": WATCH_NAMES.get(c, ""), "tgt": _w_tgt(c),
                "board": _w_board(c), "arm": arm, "state": st,
                "d": p.get("entry_date") or "—", "px": _w_num(p.get("entry_px")),
                "last": _w_num(p.get("last_close")),
                "hold": "%s d" % p.get("hold_days", "—")}))
        for c in (d.get("pending_buys") or []):
            out.append((_last_d, {
                "code": c, "name": WATCH_NAMES.get(c, ""), "tgt": _w_tgt(c),
                "board": _w_board(c), "arm": arm,
                "state": '<span class="warn">待买入 · T+1 开盘</span>',
                "d": _last_d or "—", "px": "—", "last": "—", "hold": "—"}))
        for t in (d.get("trades") or []):
            c = t.get("code", "")
            if not c:
                continue
            _is_buy = str(t.get("side", "")).lower() == "buy"
            out.append((t.get("date") or "", {
                "code": c, "name": WATCH_NAMES.get(c, ""), "tgt": _w_tgt(c),
                "board": _w_board(c), "arm": arm,
                "state": ('<span class="up">已买入</span>' if _is_buy
                          else '<span class="down">已卖出</span>'),
                "d": t.get("date") or "—", "px": _w_num(t.get("px")),
                "last": "—", "hold": "—"}))
    out.sort(key=lambda x: x[0], reverse=True)
    return [r for _d, r in out], []


def _w_rows_etf():
    """ETF 动量轮动：etf_paper_state.json 的 positions / pending / trades（**只读**）。
    列：标的 / 板块 / 状态 / 日期 / 入场价 / 最新价 / 权重。"""
    d = _watch_load("etf_paper_state.json")
    if not d:
        return [], []
    out = []
    for p in (d.get("positions") or []):
        c = p.get("code", "")
        out.append((p.get("entry_date") or "", {
            "code": c, "name": WATCH_NAMES.get(c, ""), "tgt": _w_tgt(c),
            "board": _w_board(c), "state": '<span class="up">持仓中</span>',
            "d": p.get("entry_date") or "—", "px": _w_num(p.get("entry_px")),
            "last": _w_num(p.get("last_close")),
            "w": _w_pct(p.get("weight"), 2)}))
    _pend = d.get("pending")
    if isinstance(_pend, dict):
        for c, w in _pend.items():
            out.append(("", {"code": c, "name": WATCH_NAMES.get(c, ""), "tgt": _w_tgt(c),
                             "board": _w_board(c),
                             "state": '<span class="warn">待调仓 · T+1 开盘</span>',
                             "d": "—", "px": "—", "last": "—", "w": _w_pct(w, 2)}))
    for t in (d.get("trades") or []):
        _to = t.get("to") or {}
        _lab = {"init": "建仓目标", "rebal": "调仓目标"}.get(str(t.get("type")), "调仓目标")
        for c, w in (_to.items() if isinstance(_to, dict) else []):
            out.append((t.get("date") or "", {
                "code": c, "name": WATCH_NAMES.get(c, ""), "tgt": _w_tgt(c),
                "board": _w_board(c), "state": '<span class="sub">%s</span>' % _lab,
                "d": t.get("date") or "—", "px": "—", "last": "—", "w": _w_pct(w, 2)}))
    out.sort(key=lambda x: x[0], reverse=True)
    return [r for _d, r in out], []


def _w_rows_fund():
    """短线基金池（场外基金动量）：**本策略目前没有独立 paper/持仓状态**（已查全仓）——
      · backtest/fund_paper.json  = 中线 FB3-H20 基金主仓（轨C），已在「中长线池 · 基金主仓」渲染，
        与短线基金池不是同一策略 → 不上本卡（否则违反「仅本策略标的」）。
      · short_pool.json.track     = 短线跟踪池条目（含 type=fund），非账本、无入场价/份额字段。
    2026-09-23（R-track-fund-0923）更新：用户批准「基金池改显示短线跟踪的基金行」→ 该卡改用
    source_kind="short_fund"（浏览器端读 SHORT_POOL.track 并过滤 type=fund），本函数保留备用、
    不再被 watch_card 调用（缺字段清单见 WATCH_NAMES_MISSING）。"""
    return [], WATCH_NAMES_MISSING


WATCH_STATIC = {"qlch": _w_rows_qlch, "kh": _w_rows_kh, "etf": _w_rows_etf, "fund": _w_rows_fund}
WATCH_COLS = {
    "qlch": [("标的", "tgt", ""), ("板块", "board", ""), ("轨", "arm", ""), ("状态", "state", ""),
             ("入场日", "d0", "center"), ("入场价", "px", "right"), ("出场日", "d1", "center"),
             ("净收益", "ret", "right")],
    "kh": [("标的", "tgt", ""), ("板块", "board", ""), ("轨", "arm", ""), ("状态", "state", ""),
           ("日期", "d", "center"), ("价格", "px", "right"), ("最新价", "last", "right"),
           ("持有", "hold", "center")],
    "etf": [("标的", "tgt", ""), ("板块", "board", ""), ("状态", "state", ""),
            ("日期", "d", "center"), ("入场价", "px", "right"), ("最新价", "last", "right"),
            ("权重", "w", "right")],
    "fund": [],
}


def watch_card(key, title, source_kind="short", cols=None, note="", empty_msg=None, badge="自动"):
    """一张「策略自有」跟踪池卡。id 一律带 key 后缀（页面级共享卡已删除）。"""
    _cid = "watch-card-%s" % key
    L = ['<div class="card" id="%s">' % _cid,
         '<h2>👁 跟踪池 · %s <span class="badge badge-auto">%s</span></h2>' % (title, badge),
         '<div class="sub"><b>仅本策略标的</b> · %s</div>' % note]
    if source_kind in ("short", "short_fund"):  # R-track-fund-0923：基金池复用短线跟踪源，按 type=fund 过滤
        _s = ('<input type="text" id="watch-q-%(k)s" name="watch-q-%(k)s" placeholder="🔍 搜索代码 / 名称…" '
              'autocomplete="off" spellcheck="false" aria-label="搜索跟踪标的（代码或名称）">'
              '<select id="watch-f-type-%(k)s" class="flt" title="类型筛选" aria-label="按类型筛选">'
              '<option value="">全部类型</option></select>'
              '<select id="watch-f-inpool-%(k)s" class="flt" title="在池状态筛选" aria-label="按在池状态筛选">'
              '<option value="">全部状态</option><option value="1">在池</option>'
              '<option value="0">已掉出（待轮动换出）</option></select>'
              '<select id="watch-f-tier-%(k)s" class="flt" title="档位筛选" aria-label="按档位筛选">'
              '<option value="">全部档位</option></select>'
              '<select id="watch-sort-%(k)s" class="flt" title="排序方式" aria-label="排序方式">'
              '<option value="entry">加入时间 ↓</option><option value="chg">涨跌 ↓</option>'
              '<option value="score">短线分 ↓</option><option value="name">名称 ↑</option>'
              '<option value="left">剩余天数 ↑</option></select>'
              '<span class="count" id="watch-count-%(k)s"></span>' % {"k": key})
        L.append('<div id="watch-pending-%s"></div><div id="watch-gate-%s"></div>'
                 '<div class="toolbar" id="watch-bar-%s">%s</div>'
                 '<div id="watch-table-%s" class="watch-tbl"></div>'
                 % (key, key, key, _s, key))
        L.append('</div>')
        return "".join(L)
    rows, missing = WATCH_STATIC[source_kind]()
    _cols = cols if cols is not None else WATCH_COLS.get(source_kind, [])
    if rows and _cols:
        L.append('<div class="tbl-wrap"><table class="tbl watch-tbl" id="tbl-watch-%s">'
                 '<thead><tr>' % key)
        for h, _k, _al in _cols:
            L.append('<th%s>%s</th>' % (' style="text-align:%s"' % _al if _al else '', h))
        L.append('</tr></thead><tbody>')
        for r in rows:
            L.append('<tr data-code="%s" data-search="%s">'
                     % (r.get("code", ""),
                        " ".join([str(r.get("name") or ""), _bare(r.get("code", ""))]).strip()))
            for _h, k2, _al in _cols:
                L.append('<td%s>%s</td>' % (' style="text-align:%s"' % _al if _al else '',
                                            r.get(k2, "—")))
            L.append('</tr>')
        L.append('</tbody></table></div>')
        L.append('<div class="sub" style="margin-top:6px;color:var(--faint)">共 <b>%d</b> 行'
                 '（持仓 + 已成交 / 待执行），按日期降序 · 只读本策略账本，不写回</div>' % len(rows))
    elif missing:
        L.append('<div class="sub" style="color:var(--warn)">%s</div>'
                 % (empty_msg or "暂无跟踪数据（本策略尚无独立 paper/持仓状态）"))
        L.append('<div class="sub">缺字段清单（补齐后才能上卡）：<b>%s</b></div>'
                 % "、".join(missing))
    else:
        L.append('<div class="sub" style="color:var(--faint)">%s</div>'
                 % (empty_msg or "暂无成交"))
    L.append('</div>')
    return "".join(L)

# ════════════════════════════════════════════════════════════════════
# ETF 动量轮动（冻结模型）卡片 —— 2026-09-06 用户需求：ETF 选股加进看板
# 数据源：etf_dashboard_snapshot.py 生成的 dist/etf_dashboard_snapshot.json
# 冻结配置 = 20日动量/前2等权/绝对动量保护/12%目标波动率缩放/月末调仓/T+1开盘
# ════════════════════════════════════════════════════════════════════
ETF_SNAP = {}
_etf_snap_f = (BASE / "dist" / "etf_dashboard_snapshot.json")
if _etf_snap_f.exists():
    try:
        ETF_SNAP = json.loads(_etf_snap_f.read_text(encoding="utf-8"))
    except Exception as _e:
        print("ETF 快照加载失败:", _e)
        ETF_SNAP = {}

def _etf_paper_card():
    """ETF 动量轮动（冻结模型）卡片：信号状态 + 模拟盘持仓 + 回测证据"""
    if not ETF_SNAP:
        return ('<div class="card" id="card-etf-paper">'
                '<h2>📈 ETF 动量轮动（冻结模型） <span class="badge badge-auto">待数据</span></h2>'
                '<div class="sub">先运行 <code>python etf_dashboard_snapshot.py</code> 生成快照</div></div>')
    _sig = ETF_SNAP.get("sig", {})
    _bt = ETF_SNAP.get("bt", {})
    _pp = ETF_SNAP.get("paper", {})
    _as_of = _sig.get("as_of", "—")
    _sig_date = _sig.get("sig_date", "—")
    _top1 = _sig.get("top1"); _top2 = _sig.get("top2")
    _scale = _sig.get("scale")
    _empty = _sig.get("empty")
    _note = _sig.get("note", "")

    # 名称查表 + 板块映射（2026-09-06 用户需求：区分板块 → 宽基股票/商品/债券）
    _names = {"sh510300": "沪深300ETF", "sh510500": "中证500ETF", "sh510050": "上证50ETF",
              "sz159915": "创业板ETF", "sh518880": "黄金ETF", "sh511260": "国债ETF"}
    _sects = {"sh510300": "宽基股票", "sh510500": "宽基股票", "sh510050": "宽基股票",
              "sz159915": "宽基股票", "sh518880": "商品", "sh511260": "债券"}

    def _nm_cell(_c, extra=""):
        """名称+代码同格（2026-09-06 对齐全站标准：粗体名称 + 换行淡色六位代码）"""
        _nm = _names.get(_c, _c)
        return f'<td><b>{_nm}</b>{extra}<br><span style="color:var(--faint);font-size:11px">{_bare(_c)}</span></td>'

    # 信号行（6 只 ETF 的 20 日动量排序，动静标注）
    _rows = []
    for i, r in enumerate(_sig.get("rank", [])):
        _c = r.get("code")
        _mom = r.get("mom", 0)
        _cls = "up" if _mom >= 0 else "down"
        _tag = ""
        if _c == _top1: _tag = " 🏆 Top1"
        elif _c == _top2: _tag = " 🥈 Top2"
        _w = _sig.get("weights", {}).get(_c)
        _wtxt = f"{_w*100:.1f}%" if _w else ("—" if _empty else "—")
        _rows.append(f"<tr><td>#{i+1}</td>{_nm_cell(_c, _tag)}"
                     f"<td style='text-align:center'>{_sects.get(_c, '—')}</td>"
                     f"<td class='{'up' if _mom>=0 else 'down'}'>{_mom:+.2f}%</td>"
                     f"<td>{_wtxt}</td></tr>")

    # 模拟盘持仓行
    _prows = []
    for p in _pp.get("positions", []):
        _px = p.get("last_close") or p.get("entry_px") or 0
        _prows.append(f"<tr>{_nm_cell(p.get('code'))}"
                      f"<td style='text-align:center'>{_sects.get(p.get('code'), '—')}</td>"
                      f"<td>{p.get('shares')} 份</td><td>{_px:.3f}</td>"
                      f"<td>{p.get('weight', 0):.1f}%</td></tr>")

    _nav = _pp.get("nav")
    _cum = _pp.get("cum")
    _pchg = _pp.get("px_chg")
    _pdate = _pp.get("last_date", "—")
    _pos_cnt = len(_pp.get("positions", []))
    _pend = _pp.get("pending")
    _pend_txt = f"挂单：{_pend.get('signal_date')}→{_pend.get('exec_date')}（{_pend.get('scale')}）" if _pend else "无挂单（下个信号日 9/30 月末）"

    # 回测证据 KPI
    _bt_kpi = (
        f'<div class="kpi"><div class="l">年化</div><div class="v" style="color:var(--up)">{_bt.get("annual", 0):.1f}%</div><div class="s">2017+</div></div>'
        f'<div class="kpi"><div class="l">最大回撤</div><div class="v" style="color:var(--down)">{_bt.get("max_dd", 0):.1f}%</div><div class="s">基线 -28.8%</div></div>'
        f'<div class="kpi"><div class="l">夏普</div><div class="v">{_bt.get("sharpe", 0):.2f}</div><div class="s">基线 0.60</div></div>'
        f'<div class="kpi"><div class="l">胜率</div><div class="v">{_bt.get("wr", 0):.1f}%</div><div class="s">月频</div></div>'
        f'<div class="kpi"><div class="l">正年</div><div class="v">{_bt.get("pos_years", 0)}/10</div><div class="s">2017-2026</div></div>'
        f'<div class="kpi"><div class="l">2021+段</div><div class="v" style="color:var(--up)">{_bt.get("seg_annual", 0):.1f}%</div><div class="s">回撤 {_bt.get("seg_max_dd", 0):.1f}%</div></div>'
    )

    return f'''<div class="card" id="card-etf-paper">
<div class="card-h"><h2>📈 ETF 动量轮动（冻结模型） <span class="badge badge-auto">自动 · 2026-09-06 定稿</span></h2><span class="fold-arrow">▾</span></div>
<div class="body" style="padding:0 16px 16px">
<div class="sub"><b>冻结配置</b>：core 6 只（沪深300/中证500/上证50/创业板/黄金/国债）· 20 日动量 · 绝对动量保护（Top1&lt;0 空仓）· 前 2 等权 · 目标波动率 <b>12%</b>（20 日窗口·clamp 25%~100%）· 月末最后交易日信号 → 次日开盘执行 · 成本 0.1% · <b>6/6 过验收门</b>（回撤 -19.1% vs 基线 -28.8% · 年化 12.2% · 夏普 1.01 · 9/10 正年 · 2021+ 段独立验证同样改善）· <b>仅供研究，不构成投资建议</b></div>
<div class="kpis" style="margin:10px 0">{_bt_kpi}</div>
<div class="op-stats">
<span class="op op-add">📊 信号状态：<b>{'🏆 ' + _names.get(_top1,'') + ' + ' + _names.get(_top2,'') if _top1 and _top2 else (('⛔ 空仓（绝对动量保护）') if _empty else '信号未定')}</b></span>
<span class="op">缩放 <b>{f'{_scale*100:.0f}%' if _scale is not None and _scale > 0 else '（空仓）'}</b> · 信号日 {_sig_date}</span>
<span class="op" style="color:var(--faint)">{_note}</span>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:12px">
<div>
<div class="etf-sec">🎯 当前信号（20 日动量排名，数据截至 {_as_of}）</div>
<table class="tbl"><thead><tr><th>#</th><th>标的</th><th style="text-align:center">板块</th><th style="text-align:right">20日动量</th><th style="text-align:right">目标权重</th></tr></thead>
<tbody>{"".join(_rows)}</tbody></table>
</div>
<div>
<div class="etf-sec">💼 模拟盘持仓 <span class="badge badge-auto">¥100,000 起点 · 9/3 初始化 @ {_pdate}</span></div>
<table class="tbl"><thead><tr><th>标的</th><th style="text-align:center">板块</th><th>份额</th><th style="text-align:right">最新价</th><th style="text-align:right">权重</th></tr></thead>
<tbody>{"".join(_prows)}</tbody></table>
<div class="sub" style="margin-top:8px">NAV ¥{_nav:,.0f}（{_cum:+.2f}% 累计 · 当日 {_pchg:+.2f}%）· 现金 ¥{_pp.get('cash', 0):,.0f} · {_pend_txt} · 下次调仓信号 9/30 月末（T+1 执行）</div>
</div>
</div>
<div class="sub" style="margin-top:10px;color:var(--faint)">模拟盘 = 前向验证《公众号 ETF 动量轮动策略》冻结模型（目标 12%）在真实时间线上的复现；与股票池（超卖伏击）/基金池（场外动量）完全独立 · 回测细节见「📝 更新日志」2026-09-06 · 数据生成：python etf_dashboard_snapshot.py</div>
</div></div>'''

# 让前端可用（未来扩展：实时刷新）
ETF_SNAP_JS = json.dumps(ETF_SNAP, ensure_ascii=False, separators=(",", ":"))
ETF_PAPER_CARD = _etf_paper_card()

# ════════════════════════════════════════════════════════════════════
# 超卖伏击模拟盘（A/C 双轨）卡片 —— 2026-09-06 用户需求：模拟盘接看板
# 数据源：khunter_paper_snapshot.py 生成的 dist/khunter_paper_snapshot.json
# 模拟口径与 khunter_paper_20260903.py 生产一致（分域 RSI/低价/主板/5仓×2万）
# ════════════════════════════════════════════════════════════════════
KH_SNAP = {}
_kh_snap_f = (BASE / "dist" / "khunter_paper_snapshot.json")
if _kh_snap_f.exists():
    try:
        KH_SNAP = json.loads(_kh_snap_f.read_text(encoding="utf-8"))
    except Exception as _e:
        print("超卖伏击 快照加载失败:", _e)
        KH_SNAP = {}

def _kh_paper_card():
    """超卖伏击 优化配置模拟盘卡片：A/C 双轨状态 + 持仓明细 + 回测证据"""
    if not KH_SNAP:
        return ('<div class="card" id="card-kh-paper">'
                '<h2>🐺 超卖伏击 模拟盘 <span class="badge badge-auto">待数据</span></h2>'
                '<div class="sub">先运行 <code>python khunter_paper_snapshot.py</code> 生成快照</div></div>')
    _cfg = KH_SNAP.get("config", {})
    _trk = KH_SNAP.get("tracks", {})
    _bt = KH_SNAP.get("bt", {})
    _tA = _trk.get("A", {})
    _tC = _trk.get("C", {})

    def _track_sec(_t, _title):
        """单个轨道的 KPI + 持仓表"""
        _pos = _t.get("positions", [])
        _nav = _t.get("nav")
        _cum = _t.get("cum")
        _chg = _t.get("px_chg")
        _pdate = _t.get("last_date", "—")
        _n_pos = len(_pos)
        _rows = []
        for p in _pos:
            _pl = p.get("pl_pct")
            _pl_cls = "up" if (_pl or 0) >= 0 else "down"
            _rows.append(
                f"<tr><td><b>{p.get('name','—')}</b><br>"
                f"<span style='color:var(--faint);font-size:11px'>{_bare(p.get('code',''))}</span></td>"
                f"<td>{p.get('shares')} 股</td>"
                f"<td style='text-align:right'>{p.get('entry_px'):.3f}</td>"
                f"<td style='text-align:right'>{p.get('last_close') or 0:.3f}</td>"
                f"<td class='{_pl_cls}' style='text-align:right'>{_pl:+.2f}%</td>"
                f"<td style='text-align:center'>{p.get('hold_days',0)}d</td></tr>")
        _kpi = (
            f'<div class="kpi"><div class="l">NAV</div><div class="v">¥{_nav:,.0f}</div>'
            f'<div class="s">{_pdate}</div></div>'
            f'<div class="kpi"><div class="l">累计</div>'
            f'<div class="v" style="color:{"var(--up)" if (_cum or 0) >= 0 else "var(--down)"}">{_cum:+.2f}%</div>'
            f'<div class="s">初始 ¥100,000</div></div>'
            f'<div class="kpi"><div class="l">当日</div>'
            f'<div class="v" style="color:{"var(--up)" if (_chg or 0) >= 0 else "var(--down)"}">{_chg:+.3f}%</div>'
            f'<div class="s">9/2 起</div></div>'
            f'<div class="kpi"><div class="l">仓位</div>'
            f'<div class="v">{_n_pos}/5</div>'
            f'<div class="s">每仓 ¥20,000</div></div>'
        )
        _pos_txt = '<div class="sub" style="margin-top:6px">无持仓（空仓等待信号）</div>' if not _rows else (
            '<table class="tbl"><thead><tr>'
            '<th>标的</th><th>份额</th><th style="text-align:right">入场价</th>'
            '<th style="text-align:right">最新价</th><th style="text-align:right">浮盈</th>'
            '<th style="text-align:center">持有</th>'
            '</tr></thead><tbody>' + "".join(_rows) + '</tbody></table>'
            f'<div class="sub" style="margin-top:6px">现金 ¥{_t.get("cash", 0):,.0f} · 交易 {_t.get("n_trades", 0)} 笔'
            f'{(" · 持有上限提醒: " + ", ".join(_t.get("hold_over_codes", []))) if _t.get("hold_over_codes") else ""}</div>'
        )
        return f'<div><div class="kpis" style="margin:6px 0">{_kpi}</div>{_pos_txt}</div>'

    _bt_rows = ""
    if _bt.get("rows"):
        _arr = sorted(_bt["rows"], key=lambda r: -r.get("mean", -99))
        # 策略英文名 → 中文名（映射自 backtest/khunter_all_strategies_backtest.py SIGNALS）
        _bt_names = {"golden_cross_not_green": "金叉不绿", "golden_triangle": "金三角",
                     "immortal_guidance": "不死鸟", "limit_up_pullback": "涨停回调",
                     "limit_up_sideways": "涨停横盘", "morning_star": "晨星",
                     "multi_golden_cross": "多金叉", "multi_party_cannon": "多方炮",
                     "resistance_breakout": "阻力突破", "strategy_2560": "2560战法",
                     "strong_wash": "强洗反转", "trend_acceleration": "趋势加速",
                     "trend_resonance": "趋势共振", "trend_start": "启动拐点",
                     "w_bottom": "W底"}
        _bt_rows = "<tr><td colspan='4'>—</td></tr>" if not _arr else "".join(
            f'<tr><td>{_bt_names.get(r.get("strategy",""), r.get("strategy",""))}</td>'
            f'<td style="text-align:center">{r.get("hold")}d</td>'
            f'<td style="text-align:right">{r.get("mean", 0):+.2f}%</td>'
            f'<td style="text-align:right">{r.get("win_rate", 0):.1f}%</td></tr>' for r in _arr[:10])

    return f'''<div class="card" id="card-kh-paper">
<div class="card-h"><h2>🐺 超卖伏击模拟盘（标准 / 激进） <span class="badge badge-auto">自动 · 前向验证</span></h2><span class="fold-arrow">▾</span></div>
<div class="body" style="padding:0 16px 16px">
<div class="sub" style="margin-top:8px"><b>模拟什么</b>：超卖伏击 优化配置（2026-09-07 MA250 定稿）在<b>真实时间线前向验证</b>——入场=15 策略信号命中 + 分域 RSI（熊&lt;35/牛&lt;32/弱牛&lt;32）+ 熊市判定(沪深300&lt;MA250) + 主板 + 收盘≥3元 + 20日均额≥3000万；出场=分域 RSI（熊&gt;59/牛&gt;75/弱牛&gt;80）T+1 开盘执行 + 25 交易日持有上限；仓位=5仓×¥20,000 · 成本 0.575% × 2 边。</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:14px">
{_track_sec(_tA, "🅰️ A 轨（标准版 · 出场 RSI&gt;59）")}
{_track_sec(_tC, "🆑 C 轨（激进版 · 出场 RSI&gt;50）")}
</div>
<div class="etf-sec" style="margin-top:14px">📊 15 策略基础信号回测（各策略最优持有期 · 事件口径） <span class="badge badge-auto">未过滤 · 负值=原始信号期望</span></div>
<table class="tbl"><thead><tr><th>策略</th><th style="text-align:center">持有</th><th style="text-align:right">均值</th><th style="text-align:right">胜率</th></tr></thead><tbody>{_bt_rows}</tbody></table>
<div class="sub" style="margin-top:6px;color:var(--faint)">⚠ 上方为 15 策略<b>原始信号</b>（无过滤）事件口径：均值普遍为负（胜率~40% 但右尾不足）——<b>不含</b>分域 RSI 过滤，<b>不是</b>投产组合；投产组合 = 15 策略信号 + 熊市分域 RSI&lt;35 超卖 + 低价≥3元 + 主板（见「超卖伏击 · 命中策略」与监控总览回测）。</div>
<div class="sub" style="margin-top:8px;color:var(--faint)">模拟盘 = 前向验证 超卖伏击 优化配置在生产上的现实信号频率与损耗；与 ETF 模拟盘（动量轮动）/基金池完全独立 · 数据生成：python khunter_paper_snapshot.py</div>
</div></div>'''

# 让前端可用
KH_SNAP_JS = json.dumps(KH_SNAP, ensure_ascii=False, separators=(",", ":"))
KH_PAPER_CARD = _kh_paper_card()

# 全量池中/长线年跟踪池（2026-08-17 用户需求：上榜跟踪 1 年，再上榜 +1 年；track_v9 由 build_enhanced_data.py 维护）
# 双卫星目标持仓卡（2026-09-13：三轨拍板后并入 sys-auto 视图；数据由 backtest/build_satellite_pool.py 生成）
try:
    _sat = json.load(open(BASE / "backtest" / "satellite_pool.json", encoding="utf-8"))

    def _fnum(v, nd=2):
        if v is None:
            return "—"
        try:
            return f"{float(v):,.{nd}f}"
        except Exception:
            return str(v)

    def _sat_rows(track):
        tr = _sat[track]
        _is_fund = (track == "track_c")

        def _fp(v):
            if v is None:
                return "—"
            col = "var(--up)" if v > 0 else ("var(--down)" if v < 0 else "var(--faint)")
            return f'<span style="color:{col}">{v:+.2f}%</span>'

        def _row(r):
            _kv = {k: v for k, v in (r.get("parts_kv") or [])}
            cells = (
                f'<tr><td><code>{r["code"]}</code></td><td>{r.get("name", "")}</td><td>{r.get("industry", "—")}</td>'
                f'<td class="num">{_fnum(r.get("close"))}</td>'
                f'<td class="num">{_fnum(r.get("lot"), 0)} 元</td><td class="num">{_fnum(r.get("amount"), 0)} 元</td>'
                f'<td title="{r.get("detail", "")}"><b>{r.get("score_txt", "—")}</b></td>'
                )
            cells = cells + "".join(
                f'<td class="num" style="text-align:center;font-size:12px">{_kv.get(lbl, "—")}</td>'
                for lbl in _subs)
            cells = cells + (
                f'<td>{r.get("action", "—")}{" ⚠涨停勿追" if r.get("limit_guard") else ""}</td>'
                f'<td class="num">{_fp(r.get("chg"))}</td><td class="num">{_fp(r.get("ret_1y"))}</td>')
            if _is_fund:
                return cells + "</tr>"
            rsi, macd, jv = r.get("rsi14"), r.get("macd_hist"), r.get("kdj_j")
            mc = "var(--up)" if (macd is not None and macd > 0) else ("var(--down)" if macd is not None else "var(--faint)")
            jc = "var(--up)" if (jv is not None and jv > 80) else ("#3b82f6" if (jv is not None and jv < 20) else "inherit")
            rsi_s = "—" if rsi is None else f"{rsi:.1f}"
            macd_s = "—" if macd is None else f"{macd:.3f}"
            jv_s = "—" if jv is None else f"{jv:.1f}"
            return (cells
                    + f'<td class="num">{rsi_s}</td>'
                    + f'<td class="num" style="color:{mc}">{macd_s}</td>'
                    + f'<td class="num" style="color:{jc}">{jv_s}</td>'
                    + "</tr>")

        # 子项列名须在 _row 被调用前确定（_row 内部引用 _subs，否则 free variable 报错）
        _subs = [k for k, _v in ((tr["rows"][0].get("parts_kv") or []) if tr.get("rows") else [])]
        _sub_th = "".join(
            f'<th style="text-align:center;font-weight:500">{lbl}</th>' for lbl in _subs)
        tds = "".join(_row(r) for r in tr["rows"])
        head = ("<th>代码</th><th>名称</th><th>行业</th><th>收盘</th><th>一手约</th><th>计划金额</th>"
                "<th>评分总分</th>" + _sub_th +
                "<th>操作</th><th>涨跌幅</th><th>近1年</th>")
        if not _is_fund:
            head += "<th>RSI14</th><th>MACD柱</th><th>KDJ-J</th>"
        bt = tr["bt"]
        nr = tr.get("next_rebal_in_days")
        cal_note = f" · 距下次调仓约 {nr} 交易日" if nr is not None else f" · {tr.get('next_rebal', '')}"
        return (f'<div class="sub" style="margin:6px 0"><b>{tr["name"]}</b> · {tr.get("ranking", "")}</div>'
                f'<div class="sub" style="margin:6px 0">调仓：{tr["rebal"]}{cal_note}'
                f'｜回测 +{bt["total"]}%/年化 +{bt["ann"]}%/回撤 {bt["mdd"]}%/夏普 {bt["sharpe"]}</div>'
                f'<div class="sub" style="color:var(--faint)">{bt["note"]}</div>'
                f'<div class="toolbar" id="sat-bar-{track}"><input type="text" class="sat-q" data-t="{track}" placeholder="🔍 搜索代码…" autocomplete="off"><select class="sat-sort" data-t="{track}"><option value="idx">清单序</option><option value="code">代码 ↑</option><option value="lot">一手成本 ↑</option></select><span class="count sat-count" data-t="{track}"></span></div>'
                f'<div class="tbl-wrap"><table class="tbl sat-tbl" data-t="{track}"><thead><tr>{head}</tr></thead><tbody>{tds}</tbody></table></div>')

    SAT_CARD = (f'<div class="card" id="sat-card">\n'
                f'<h2>🛰️ 卫星目标持仓 <span class="badge badge-auto">双轨 60/0/40 · 数据截至 {_sat["asof"]}（收盘）</span></h2>\n'
                f'<div class="sub">信号生成：<code>backtest/signal_satellite_0913.py</code>（每日收盘跑 → T+1 开盘清单）· 资金占比：<b>卫星 100% 多因子主仓</b>｜双轨口径 FB3-H20 主仓 60%· 目标持仓为<b>下次调仓的完整清单</b>（非增量）· 评分列悬浮可见拆解 · 操作列=相对模拟盘当前持仓</div>\n'
                f'{_sat_rows("track_b")}\n</div>')
except Exception as _e:
    SAT_CARD = (f'<div class="card" id="sat-card"><h2>🛰️ 双卫星目标持仓</h2>'
                f'<div class="sub">satellite_pool.json 未生成 —— 先运行 <code>python backtest/build_satellite_pool.py</code>（{_e}）</div></div>')

_sp_j = json.load(open(BASE / "short_pool.json", encoding="utf-8"))
_fund_tier = _sp_j.get("tiers", {}).get("基金", []) or _sp_j.get("tiers", {}).get("fund", [])
_mg = _sp_j.get("market_gate", {})
_held_c = set()
try:
    _hst = json.load(open(BASE / "backtest" / "holdings_satellite.json", encoding="utf-8"))
    _held_c = set((_hst.get("track_c", {}) or {}).get("holdings", {}).keys())
except Exception:
    pass
_n_f = max(1, len(_fund_tier))
# 基金主仓行级指标（2026-09-14 新增列）：取 satellite_pool.json track_c 行（NAV 口径算 RSI/MACD/KDJ）
try:
    _sat_c = {r["code"]: r for r in json.load(open(BASE / "backtest" / "satellite_pool.json", encoding="utf-8")).get("track_c", {}).get("rows", [])}
except Exception:
    _sat_c = {}


def _fpct(v):
    if v is None:
        return "—"
    col = "var(--up)" if v > 0 else ("var(--down)" if v < 0 else "var(--faint)")
    return f'<span style="color:{col}">{v:+.2f}%</span>'


_fund_rows = ""
for _c in _fund_tier:
    _d = _sp_j.get("details", {}).get(_c, {})
    _act = "持有" if _c in _held_c else "申购"
    _r = _sat_c.get(_c, {})
    _rsi, _macd, _jv = _r.get("rsi14"), _r.get("macd_hist"), _r.get("kdj_j")
    _mc = "var(--up)" if (_macd is not None and _macd > 0) else ("var(--down)" if _macd is not None else "var(--faint)")
    _jc = "var(--up)" if (_jv is not None and _jv > 80) else ("#3b82f6" if (_jv is not None and _jv < 20) else "inherit")
    _fund_rows += (f'<tr><td><code>{_c}</code></td><td>{_d.get("name", "")}</td>'
                   f'<td class="num">{_d.get("score", "—")}</td>'
                   f'<td class="num">{_fpct(_r.get("chg"))}</td><td class="num">{_fpct(_r.get("ret_1y"))}</td>'
                   f'<td class="num">{"—" if _rsi is None else f"{_rsi:.1f}"}</td>'
                   f'<td class="num" style="color:{_mc}">{"—" if _macd is None else f"{_macd:.3f}"}</td>'
                   f'<td class="num" style="color:{_jc}">{"—" if _jv is None else f"{_jv:.1f}"}</td>'
                   f'<td class="num">{100/_n_f:.1f}%</td><td>{_act}</td></tr>')
_gate_txt = ("🟢 开（股票可买）" if _mg.get("open") else "🟠 关（仅拦股票池；基金轨不受影响——熊市 FB3 照常买入，转 Top3 低波防守仓）") + f' · 沪深300 {_mg.get("idx_close", "—")} vs MA20 {_mg.get("idx_ma20", "—")}'
FB3_POOL_CARD = (f'<div class="card" id="fb3-pool-card">'
                 f'<h2>🥇 主仓 FB3-H20 基金池 <span class="badge badge-auto">当前 regime 持仓 · 数据截至 {_sp_j.get("as_of", "—")}</span></h2>'
                 f'<div class="sub">排序=基金动量分降序 · 市况门控 {_gate_txt} · 60% 资金 · 牛市 Top10 动量 / 熊市 Top3 低波（C 类份额，T+1 净值申赎）· 操作=相对模拟盘当前持仓</div>'
                 f'<div class="sub" style="color:var(--warn)">⚠ 实盘清单已按份额去重（同一基金 A/C/E 类只留一只，优先 C 类）——回测口径未去重，故实盘预期与回测数字存在系统性差异</div>'
                 f'<div class="sub" style="color:var(--faint)">行业集中度约束（同行业≤N，N∈{{1,2,3}}）已于 2026-09-14 预注册实测：三轨均未过「相位中位夏普≥对照 + 50bp 档不劣化 + 配对显著」闸 → 不采纳（报告 backtest/报告-行业集中度约束三轨实测_20260914.md）</div>'
                 f'<div class="tbl-wrap"><table class="tbl"><thead><tr><th>代码</th><th>名称</th><th>动量分</th><th>涨跌幅</th><th>近1年</th><th>RSI14</th><th>MACD柱</th><th>KDJ-J</th><th>权重</th><th>操作</th></tr></thead><tbody>{_fund_rows or "<tr><td colspan=10>空（门控关闭；基金轨熊市照买 Top3）</td></tr>"}</tbody></table></div>'
                 f'<div class="sub" style="color:var(--faint)">指标口径：基金为 NAV 净值序列口径（RSI14/MACD(12,26,9)柱/KDJ(9,3,3)-J），与股票轨同算法；数据源 <code>fund_nav_cache</code></div></div>')

WATCH_V9_CARD = ('<div class="card" id="watch-v9-card"><h2>📌 历史跟踪池（已退役）</h2>'
                 '<div class="sub" style="color:var(--up)">⛔ v9 跟踪池展示已于 2026-09-13 移除（战法退役，十重证伪）。数据文件保留于 enhanced_data.js 供回溯。</div></div>')

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
    _flag = "✕" if _r.get("defects", 0) > 0 else "✓"
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
    _arb = _ar.get("bench", {}) or {}
    _bwr = _arb.get("win_rate", 56.1); _bmn = _arb.get("mean_net", 1.19); _btp = _arb.get("tp_ratio", 25.0)
    _v1n_ = _ars.get("v1_n", 0)
    _a5kpi = (
        f'<div class="kpi"><div class="l">已平仓（新口径）</div><div class="v">{_ars.get("n", 0)}/30</div><div class="s">触发判定阈值' + (f' · v1 归档 {_v1n_} 笔' if _v1n_ else '') + '</div></div>'
        f'<div class="kpi"><div class="l">胜率</div><div class="v">{f"{_wr:.1f}%" if _wr is not None else "—"}</div><div class="s">基准 {_bwr:.1f}% · 闸 [46,66]%</div></div>'
        f'<div class="kpi"><div class="l">均值净</div><div class="v" style="color:{("var(--up)" if (_mn or 0) >= 0 else "var(--down)")}">{f"{_mn:+.2f}%" if _mn is not None else "—"}</div><div class="s">基准 +{_bmn:.2f}% · 闸 &gt;+0.5%</div></div>'
        f'<div class="kpi"><div class="l">止盈占比</div><div class="v">{f"{_tp:.1f}%" if _tp is not None else "—"}</div><div class="s">基准 {_btp:.1f}% · 闸 [15,35]%</div></div>'
        f'<div class="kpi"><div class="l">净值</div><div class="v">{_ars.get("nav", 1.0):.4f}</div><div class="s">全部已平仓复利（含 v1 归档）</div></div>'
    )
    _flag = "✓" if _arg.get("verdict", "").startswith("✅") else ("…" if _arg.get("verdict", "").startswith("信号不足") else "✕")
    A5_REVIEW_BLOCK = (f'<h2>🎯 首板低吸（双池滤网 v1.3）模拟盘验证 <span class="badge badge-auto">池A 超跌 / 池B 趋势 · 非实盘指令</span></h2>'
                       f'<div class="sub">逐笔模拟盘跟踪（net_ret 含成本）· 验证门基准 = 双池并集（胜率 56.1% / 均值 +1.19% / tp 25.0%）· 新口径独立计数（v1 旧口径 11 笔归档）· 详细见「🎯 首板低吸」视图</div>'
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
            "短线·主板": 46.8, "短线·创业板": 48.1, "短线·科创板": 57.8, "短线·基金": 65.2,  # 2026-09-11 FB3-H20 投产：55.5（T5/H10/S40 退役）→ 65.2
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
# 股票池含 标准/激进 双版本（入场同信号，标准版 A59 主卖出 + 激进版 C50 参考标注）；基金池=场外基金动量；
# 跟踪池统一放底部（股票+基金同一 watch 卡，类型筛选），不做 标准/激进 双跟踪池（买入同一、卖出判定归模拟盘双轨）
# 2026-09-05 用户需求：新增「超卖伏击命中策略一览」卡（命中 15 策略全展示，按 RSI 升序，档位/建议区分）
KH_HITS_CARD = f'''<div class="card" id="card-kh-hits">
<h2>🎯 超卖伏击 命中策略一览 <span class="badge badge-auto">自动 · 按 RSI 升序</span></h2>
<div class="sub">全量池短线股票中<b>命中 15 个超卖形态策略</b>的标的（含未达买入阈值者，事件驱动）· 按当前 RSI 升序（超卖优先）· 档位/建议 = 牛熊分域裁决，<b>标准版（A59 主卖出）</b>与<b>激进版（C50 参考线）</b>分四列独立展示：<b>买入</b> = RSI 低于分域阈值（熊&lt;35 / 牛&lt;32 / 弱牛&lt;32）· <b>卖出</b> = 标准版 RSI&gt;59/75/80、激进版 RSI&gt;50 · 命中但未达阈值 = 观望（仅观察，不构成操作）· 数据截至 {SHORT_POOL_ASOF}</div>
<div class="toolbar" id="kh-hits-bar">
<input type="text" id="kh-hits-q" placeholder="🔍 搜索代码 / 名称 / 策略…" autocomplete="off" spellcheck="false">
<select id="kh-hits-f-tier" class="flt" title="标准版档位筛选"><option value="">全部档位</option><option>买入</option><option>卖出</option><option>观望</option></select>
<select id="kh-hits-f-board" class="flt" title="板块筛选"><option value="">全部板块</option><option>主板</option><option>创业板</option><option>科创板</option></select>
<span class="count" id="kh-hits-count"></span>
</div>
<table class="tbl" id="kh-hits-table">
<thead><tr>
<th style="text-align:center">#</th><th>标的</th><th>板块</th><th>行业</th>
<th style="text-align:right">现价</th><th style="text-align:right">涨跌</th>
<th style="text-align:center">RSI 今</th><th style="text-align:center">RSI T-1</th><th style="text-align:center">分域</th>
<th>命中策略</th>
<th style="text-align:center">档位(标准)</th><th style="text-align:center">建议(标准)</th>
<th style="text-align:center">档位(激进)</th><th style="text-align:center">建议(激进)</th>
</tr></thead>
<tbody></tbody>
</table>
</div>'''

# ================= 超跌低开低吸 卡片（R-qlch-dash-0921n） =================
QLCH_TRACKS = [
    ("B4_K3",    "超跌低开低吸（B4+K3 · 全池）",      "qlch_paper_state_b4_k3.json",    "★ 本次投产"),
    ("B4_K3_MB", "超跌低开低吸（B4+K3 · 真主板）",    "qlch_paper_state_b4_k3_mb.json", "对照轨·封存集头对头"),
    ("C1",       "旧基线（绝对滤网 · 全池 · 无上限）", "qlch_paper_state.json",          "对照"),
    ("B4_K3_G60", "候选·MA60 门（封存集采集）",       "qlch_paper_state_b4_k3_gate60.json", "🟡 候选 · 不改生产"),
    ("B4_K3_CB",  "候选·综合分排序（封存集采集）",     "qlch_paper_state_b4_k3_combo.json",  "🟡 候选 · 不改生产"),
    ("B4",       "B4 无上限（全池）",                  "qlch_paper_state_b4.json",       "⚠ 收益依赖分配约定"),
]


def qlch_card():
    import json as _j
    B = BASE / "backtest"
    # ---- 三列参数（2026-09-22 用户需求）：单一来源 = qlch 生产脚本，**不硬编码** ----
    _QP = B / "qlch_paper_20260921.py"
    _mm = re.search(r"TP_PCT,\s*SL_PCT,\s*MAXHOLD\s*=\s*([\d.]+),\s*(-?[\d.]+),\s*(\d+)",
                    _QP.read_text(encoding="utf-8")) if _QP.exists() else None
    TP, SL, MH = ((float(_mm.group(1)), float(_mm.group(2)), int(_mm.group(3)))
                  if _mm else (0.15, -0.20, 20))
    _PARAM_OK = bool(_mm)
    # 交易日历（纯文本读 index_000300.csv；本文件未导入 pandas）—— 用于「轮动点」精确日期
    try:
        _cal = [ln.split(",")[0] for ln in
                (BASE / "index_000300.csv").read_text(encoding="utf-8").strip().splitlines()[1:]
                if ln[:4].isdigit()]
    except Exception:
        _cal = []

    def _rot(ed):
        """轮动点 = 入场日 + MH 个交易日；日历不足则退回参数口径。"""
        if not _cal or not ed or ed not in _cal:
            return "≤ %d 个交易日" % MH
        j = _cal.index(ed) + MH
        return _cal[j] if j < len(_cal) else "≤ %d 个交易日（未到期）" % MH

    cand = {}
    fp = B / "qlch_candidates.json"
    if fp.exists():
        try:
            cand = _j.load(open(fp, encoding="utf-8"))
        except Exception:
            cand = {}
    bt = {}
    # 2026-09-22 R-qlch-t1exit-0922：原 qlch_bt_summary.json 是 T+0 违法口径（★198 复发），
    # 改读 T+1 合规复测产物；旧文件保留作历史对照但不再上卡。
    fp2 = B / "qlch_bt_t1exit_0922.json"
    if not fp2.exists():
        fp2 = B / "qlch_bt_summary.json"
    if fp2.exists():
        try:
            bt = _j.load(open(fp2, encoding="utf-8"))
        except Exception:
            bt = {}
    L = []
    L.append('<div class="card" id="qlch-card">')
    L.append('<h2>🏷 超跌低开低吸 <span class="view-badge auto">'
             '短期反转 + 跳空低吸 + 熊市择时 + 分位滤网 · 影子盘 · T+1 合规</span></h2>')
    if bt.get("void"):
        L.append('<div class="subhint" style="border-left:3px solid var(--warn);'
                 'background:rgba(255,180,60,.08);padding:8px 10px;margin-top:8px;line-height:1.75">%s</div>'
                 % bt["void"])
    L.append('<div class="etf-sec" style="margin-top:6px">📌 策略定义</div>')
    L.append('<div style="font-size:12.5px;color:var(--sub);line-height:1.85">'
             'T 收盘判定：<b>超跌</b> ret20(T-1) ≤ −7.31% ＋ <b>熊市门</b> 沪深300(T) &lt; MA20<span style="color:var(--faint)">（R-qlch-gate-rank-t1-0922 合法口径重跑：<b>MA60 夏普 2.936</b> vs 现状 MA20 2.539 / MA200 1.376 / MA250 1.314 / 无门 0.420 → <b>MA60 登记候选，生产仍用 MA20</b>；MA200 硬门不过（0.5% 档 −0.010%）；<span style="color:var(--warn)">旧违法口径数字已作废</span>）<br><span style="color:var(--sub)">组合臂 MA60×综合分（R-qlch-combo-0922）：夏普 <b>3.284</b> 全场最高（自助法显著优于 C1/C2），但回撤 −21.36% vs 现状 −18.38% <b>劣化 2.99pp</b> → <b>按预注册 §五 组合否决</b>，两候选各自保留，零生产变更。</span></span> ＋ '
             '<b>真主板</b> ＋ 非ST ＋ 量比 ≥1.2 ＋ <b>市值/换手横截面分位带</b>（市值 [.20,.70] / 换手 [.40,.80]）<br>'
             'T+1 开盘执行：<b>开盘跳空 gap ∈ [−5%,−2%]</b> 才买，成交价 = T+1 开盘；'
             '<b>单票权重 = min(1/n, 1/3)</b>，未用资金持国债ETF；'
             '<b>出场 = 止盈 +15% ／ 止损 −20% ／ 上限 20 日（T+1 合规，次日才可卖）</b>。'
             '<span style="color:var(--warn)">⚠ 上市板块剔除科创板（688，20% 涨跌幅）</span></div>')

    L.append('<div class="etf-sec" style="margin-top:14px">🎯 选股结果 · 今日收盘候选'
             '（等次日开盘 gap 判定后入场）</div>')
    ck = cand.get("by_track", {}).get("B4_K3", {})
    if ck:
        rows = ck.get("codes", [])
        # ---- 明日买点（R-qlch-buyhint-0922）：今收 × [0.95, 0.98]；名额来自在产影子盘 ----
        _K3F = B / "qlch_paper_state_b4_k3.json"
        _npos = 0
        try:
            if _K3F.exists():
                _npos = len(_j.load(open(_K3F, encoding="utf-8")).get("positions", []))
        except Exception:
            _npos = 0
        _SELK = 3
        _room = max(_SELK - _npos, 0)

        def _band(c):
            if not isinstance(c, (int, float)) or c <= 0:
                return None, None
            return round(c * 0.95, 3), round(c * 0.98, 3)

        def _buy_td(c):
            lo, hi = _band(c)
            if lo is None:
                return '<td>—</td>'
            _op = ' style="opacity:.45"' if _room <= 0 else ''
            return ('<td%s><span class="badge badge-auto">● 跳空 −5%%~−2%% 才买</span>'
                    '<div style="margin-top:3px;font-variant-numeric:tabular-nums">%.3f ~ %.3f</div></td>'
                    % (_op, lo, hi))

        L.append('<div class="sub">截至 <b>%s</b> 收盘 · %s · n = <b>%d</b> 只 · '
                 '明日买点 = <b>今收 × [0.95, 0.98]</b>（跳空 −5%%~−2%% 才买，成交价 = 明日开盘）· '
                 '当前持仓 <b>%d</b> 只 → 明日可建新仓 <b>%d</b> 只%s<br>'
                 '<b>这不是买入名单</b>：单票上限 K=%d，候选多于空位时<b>随机抽</b>；'
                 '<b># 列是按超跌深度降序的展示排序，不是买入优先级</b>'
                 '（若要按深度取 TopK，须另立预注册）。</div>'
                 % (ck.get("as_of", "—"), ck.get("pool", ""), ck.get("n", 0),
                    _npos, _room,
                    '　<span style="color:var(--warn)">已持满 → 明日不建新仓，下表仅作观察</span>' if _room <= 0 else '',
                    _SELK))
        if rows:
            # 2026-09-22 用户反馈（截图）：芯片云不可读 → 改标准表格
            # 2026-09-22 用户：表格太简单、指标没体现、排名没体现 → 补 7 个信号驱动指标 + 排名列
            def _pct(v, nd=2):
                return "—" if v is None else ("%+.*f%%" % (nd, v * 100))

            def _row_attrs(r):
                """行属性（R-qlch-live-0923 / R-qlch-pxcol-0923）：与看板其它表同格式的
                data-code / data-search。盘中层靠它认行：**data-code 保留带前缀原值**（盘中层
                剥 sh/sz/bj 后取 6 位）；data-search 首词必须是名称（名称守卫按「去掉 6 位数字
                及其后」取名），末段补板块供前端搜索。"""
                _c = r.get("code", "")
                return ' data-code="%s" data-search="%s"' % (
                    _c, " ".join([str(r.get("name", "")), _bare(_c),
                                  str(_board_of6(_bare(_c))), str(r.get("ind") or "")]).strip())

            # 列序（15 列 = 原 14 − 代码/名称合并 1 + 板块 1 + 现价 1）：# / 标的 / 板块 / 行业 / 现价 / 涨跌幅 / …
            L.append('<table class="tbl" id="tbl-qlch-cand" style="width:100%;font-size:12px;margin-top:8px">'
                     '<thead><tr>'
                     '<th data-key="rank">#</th><th data-key="name">标的</th><th data-key="board">板块</th>'
                     '<th data-key="ind">行业</th>'
                     '<th data-key="px" style="text-align:right">现价</th>'
                     '<th data-key="chg" style="text-align:right">涨跌幅</th>'
                     '<th data-key="r20" title="信号核心：T-1 的 20 日收益，越负越超跌，门槛 ≤ −7.31%">超跌深度</th>'
                     '<th data-key="vr" title="量比：当日成交额 / 5 日均量，门槛 ≥1.2">量比</th>'
                     '<th data-key="turn" title="换手率（amount/流通市值），横截面分位带 [.40,.80]">换手</th>'
                     '<th data-key="pm" title="流通市值横截面分位，分位带 [.20,.70]">市值分位</th>'
                     '<th data-key="pt" title="换手率横截面分位，分位带 [.40,.80]">换手分位</th>'
                     '<th data-key="buy" title="明日开盘跳空落在 [今收×0.95, 今收×0.98] 才买——这是条件不是承诺；名单按 K=3 随机抽">明日买点</th>'
                     '<th data-key="tp" title="策略止盈点：买入价 ×(1+TP)，TP 从 qlch 生产脚本解析；价格按明日买点区间折算">止盈点 +15%</th>'
                     '<th data-key="sl" title="策略止损点：买入价 ×(1+SL)，SL 从 qlch 生产脚本解析；价格按明日买点区间折算">止损点 −20%</th>'
                     '<th data-key="rot" title="轮动点：最长持有 MAXHOLD 个交易日，到期轮动（未触发止盈/止损时）">轮动点 20 交易日</th>'
                     '</tr></thead><tbody>')
            def _tpsl(c):
                _lo, _hi = _band(c)
                if _lo is None:
                    return '<td>—</td><td>—</td><td>—</td>'
                return ('<td style="font-variant-numeric:tabular-nums;color:var(--up)">'
                        '%.3f ~ %.3f</td>'
                        '<td style="font-variant-numeric:tabular-nums;color:var(--down)">'
                        '%.3f ~ %.3f</td>'
                        '<td style="color:var(--sub)">≤ %d 个交易日</td>'
                        % (_lo * (1 + TP), _hi * (1 + TP), _lo * (1 + SL), _hi * (1 + SL), MH))

            for r in rows:
                _c6 = _bare(r.get("code", ""))          # 6 位码：标的列下行 + 板块判定（data-code 仍为带前缀原值）
                _board = _board_of6(_c6)
                _cl = r.get("close")
                _chg = r.get("chg"); _r20 = r.get("r20")
                _cs = "—" if _chg is None else "%+.2f%%" % (_chg * 100)
                _col = ("var(--up)" if (_chg is not None and _chg > 0)
                        else ("var(--down)" if _chg is not None else "var(--faint)"))
                # 超跌深度：越负越深，用颜色强调深度
                _r20s = "—" if _r20 is None else "%+.2f%%" % (_r20 * 100)
                _r20col = ("var(--down)" if (_r20 is not None and _r20 <= -0.15)
                           else ("var(--warn)" if _r20 is not None else "var(--faint)"))
                # 现价（R-qlch-pxcol-0923）：构建期填今收，无则「—」；盘中层按列头文本「现价」定位并改写
                _pxs = "—" if _cl is None else "%.2f" % _cl
                L.append(('<tr%s>'
                          '<td data-v="%s">%s</td>'
                          '<td><b>%s</b><br><span style="color:var(--sub);font-size:var(--fs-xs);'
                          'font-variant-numeric:tabular-nums">%s</span></td>'
                          '<td>%s</td><td style="color:var(--sub)">%s</td>'
                          '<td data-key="px" data-v="%s" style="text-align:right;'
                          'font-variant-numeric:tabular-nums">%s</td>'
                          '<td data-v="%s" style="color:%s">%s</td>'
                          '<td data-v="%s" style="color:%s"><b>%s</b></td>'
                          '<td data-v="%s">%s</td><td data-v="%s">%s</td>'
                          '<td data-v="%s">%s</td><td data-v="%s">%s</td>'
                          % (_row_attrs(r), r.get("rank", ""), r.get("rank", ""),
                             r.get("name", ""), _c6,
                             _board_cell(_board, r.get("ind")), r.get("ind", "") or "—",
                             "" if _cl is None else _cl, _pxs,
                             "" if _chg is None else _chg, _col, _cs,
                             "" if _r20 is None else _r20, _r20col, _r20s,
                             r.get("vr") or "", "—" if r.get("vr") is None else "%.2f" % r["vr"],
                             r.get("turn") or "", _pct(r.get("turn")),
                             r.get("pm") or "", "—" if r.get("pm") is None else "%.2f" % r["pm"],
                             r.get("pt") or "", "—" if r.get("pt") is None else "%.2f" % r["pt"])
                         ) + _buy_td(r.get("close")) + _tpsl(r.get("close")) + '</tr>')
            L.append('</tbody></table>')
    else:
        L.append('<div style="font-size:12.5px;color:var(--faint)">候选数据未生成'
                 '（日链第 30 步之后写入 backtest/qlch_candidates.json）</div>')

    L.append('<div class="etf-sec" style="margin-top:14px">💼 模拟盘（对照臂，'
             '<b>不申领实盘资金</b> · 毕业门见预注册）</div>')
    L.append('<table class="tbl" id="tbl-qlch-paper" style="width:100%;font-size:12.5px">'
             '<thead><tr><th>轨</th><th>净值</th>'
             '<th title="盘中估算值，非记账值；记账以收盘链写入为准">盘中净值（估算）</th>'
             '<th>已成交</th><th>最近信号日</th><th>状态</th></tr></thead><tbody>')
    anyrow = False
    for key, label, fn, tag in QLCH_TRACKS:
        f = B / fn
        if not f.exists():
            continue
        try:
            d = _j.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        anyrow = True
        eq = d.get("equity", [])
        nav = eq[-1]["nav"] if eq else 1.0
        lastd = eq[-1]["date"] if eq else "—"
        # 盘中净值（R-qlch-live-0923）：构建期只放账本净值 + 「—」占位；真实估算由浏览器端按
        # nav_prev × (1 + Σ w×(现价/入场价−1−成本)) 算（数据来自 window.QLCH.accounts）。
        L.append('<tr data-track="%s"><td>%s</td><td><b>%.4f</b></td>'
                 '<td class="qlch-nav-live" title="盘中估算值，非记账值；记账以收盘链写入为准">%.4f <span class="qlch-nav-tip">—</span></td>'
                 '<td>%d 笔</td><td>%s</td>'
                 '<td style="color:var(--sub)">%s</td></tr>'
                 % (key, label, nav, nav, len(d.get("trades", [])), lastd, tag))
    if not anyrow:
        L.append('<tr><td colspan="6" style="color:var(--faint)">尚未初始化</td></tr>')
    L.append('</tbody></table>')

    L.append('<div class="etf-sec" style="margin-top:14px">👁 跟踪池（超跌低开低吸 · 已成交 / 待判定）</div>')
    alltr = []
    for key, label, fn, tag in QLCH_TRACKS:
        f = B / fn
        if not f.exists():
            continue
        try:
            d = _j.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for t in d.get("trades", []):
            if t.get("code"):
                alltr.append((t.get("exit_date") or t.get("entry_date") or "", t.get("code", ""),
                              t.get("name", ""), label.split("（")[0], t.get("gap"), t.get("net_ret"),
                              t.get("entry_px"), t.get("entry_date")))
    alltr.sort(key=lambda x: x[0], reverse=True)
    if alltr:
        L.append('<table class="tbl" id="tbl-qlch-track" style="width:100%;font-size:12.5px">'
                 '<thead><tr><th>日期</th><th>代码</th><th>名称</th><th>轨</th><th>gap</th><th>净收益</th>'
                 '<th title="策略止盈点：买入价 ×(1+TP)，TP 从 qlch 生产脚本解析">止盈点 +15%</th>'
                 '<th title="策略止损点：买入价 ×(1+SL)">止损点 −20%</th>'
                 '<th title="轮动点：入场日 + MAXHOLD 个交易日（未触发止盈/止损时到期轮动）">轮动点</th>'
                 '</tr></thead><tbody>')
        for d0, c0, n0, lab, gp, nr, epx, ed in alltr[:30]:
            gs = "%+.2f%%" % (gp * 100) if isinstance(gp, (int, float)) else "—"
            ns = "%+.2f%%" % (nr * 100) if isinstance(nr, (int, float)) else "—"
            col = "var(--up)" if isinstance(nr, (int, float)) and nr > 0 else "var(--down)"
            _tp = ("%.3f" % (epx * (1 + TP))) if isinstance(epx, (int, float)) and epx else "—"
            _sl = ("%.3f" % (epx * (1 + SL))) if isinstance(epx, (int, float)) and epx else "—"
            L.append('<tr><td>%s</td><td>%s</td><td>%s</td><td style="color:var(--sub)">%s</td>'
                     '<td>%s</td><td style="color:%s"><b>%s</b></td>'
                     '<td style="font-variant-numeric:tabular-nums;color:var(--up)">%s</td>'
                     '<td style="font-variant-numeric:tabular-nums;color:var(--down)">%s</td>'
                     '<td style="color:var(--sub)">%s</td></tr>'
                     % (d0, c0, n0, lab, gs, col, ns, _tp, _sl, _rot(ed)))
        L.append('</tbody></table>')
    else:
        L.append('<div style="font-size:12.5px;color:var(--faint)">暂无成交（2026-09-22 起进入封存集采集期）</div>')

    L.append('<div class="etf-sec" style="margin-top:14px">📊 回测数据（%s）</div>'
             % bt.get("cost", "往返20bp"))
    arms = bt.get("arms", [])
    if arms:
        L.append('<table class="tbl" style="width:100%;font-size:12px">'
                 '<thead><tr><th>臂</th><th>池</th><th>单票上限</th><th>笔数</th>'
                 '<th title="训练窗 2016-2021（2016/2017 无成交，分母含两年 → 另给 cagr_4y 按有成交年份）">年化</th><th>夏普</th><th>回撤</th><th>胜率</th><th>50bp 年化</th>'
                 '<th title="2022-01-04 起，仅参照不用于选型；2026-09-23 由绝对净值口径修正为窗口内年化（R-qlch-cagrval-0923）">验证窗年化（修正）</th></tr></thead><tbody>')
        for a in arms:
            mp = ("1/%d" % a["maxpos"]) if a.get("maxpos") else "无"
            col = "var(--up)" if a.get("cagr", 0) > 0 else "var(--down)"
            L.append('<tr><td>%s</td><td>%s</td><td>%s</td><td>%d</td>'
                     '<td style="color:%s"><b>%+.2f%%</b></td><td>%.3f</td><td>%.2f%%</td><td>%.1f%%</td>'
                     '<td>%+.2f%%</td><td>%s</td></tr>'
                     % (("⚠ " if a.get("legal") is False else "") + a.get("name", ""),
                        a.get("pool", ""), mp, a.get("n", 0), col,
                        a.get("cagr", 0), a.get("sharpe", 0), a.get("mdd", 0), a.get("wr", 0),
                        a.get("cagr50", 0),
                        ("—" if a.get("cagr_val_fix") is None else
                          ("<b>%+.2f%%</b>" % a["cagr_val_fix"]) +
                          ("" if a.get("cagr_val") is None else
                           "<span style=\"color:var(--faint);font-size:var(--fs-xs)\"> · 原 %+.2f%%</span>" % a["cagr_val"]))))
        L.append('</tbody></table>')
    kf = bt.get("key_facts", [])
    if kf:
        L.append('<ul style="font-size:12px;color:var(--sub);margin:9px 0 0 18px;line-height:1.8">')
        for x in kf:
            L.append('<li>%s</li>' % x)
        L.append('</ul>')
    L.append('<div style="font-size:11.5px;color:var(--faint);margin-top:9px">%s</div>'
             % bt.get("note", ""))
    if bt.get("recalib"):
        L.append('<div class="subhint" style="border-left:3px solid var(--warn);'
                 'background:rgba(255,180,60,.08);padding:8px 10px;margin-top:8px;'
                 'line-height:1.7;font-size:12px">⚠ <b>验证窗口径修正（%s）</b>：原「验证窗年化」按'
                 '<b>绝对净值水平</b>年化 → 2022+ 段被放大（起点净值≈2.04）；已改为<b>窗口内年化</b>。'
                 '★候选 E4：+22.10%% → <b>+5.06%%</b>（窗口累计 +26.04%%）；E1 +31.31%% → +9.33%%；'
                 'E2 +55.05%% → +21.51%%；E3 +11.13%% → +0.33%%。训练窗「年化」分母含 2016/2017 两个零成交年，'
                 '按有成交年份另给 cagr_4y（E4 12.63%% → 19.48%%）。复算：'
                 '<code>backtest/repro_qlch_cagrval_0923.py</code></div>'
                 % bt["recalib"].get("id", ""))
    L.append('</div>')
    return "".join(L)


# ── 5 张「策略自有」跟踪池卡的副标题（R-track-sep-0923：一卡一策略，只列本策略标的）──
WATCH_NOTE_STK = (
    '上方短线表<b>可买入标的（强买入/买入）</b>上榜次日收盘确认后自动加入跟踪，30 天自动移除'
    '（<b>2026-08-18 起新上榜先入「待确认」隔日入池</b>，隔离当日收盘信号）· 卖出规则（与回测一致）：'
    '<b>收盘跌破 MA5 → 次日开盘卖出</b> ｜ 掉出信号池 → 下次轮动换出 ｜ 档位减半/清仓 → 按档位操作 · '
    '每次重新上榜刷新【入池/跟踪/出池】时间 · 数据截至 %s（基金净值 T-1：%s）· '
    '数据源 <code>short_pool.json</code>（track / track_pending_short）'
    % (SHORT_POOL_ASOF, SHORT_POOL.get("fund_as_of", "—")))
WATCH_NOTE_QLCH = (
    '超跌低开低吸六臂账本（B4_K3 在产 + 5 对照臂）的<b>持仓 + 已成交</b>，只读 '
    '<code>backtest/qlch_paper_state*.json</code>（不写账本、不改收盘链）· '
    '出场口径：止盈 +15% ／ 止损 −20% ／ 上限 20 交易日')
WATCH_NOTE_KH = (
    '超卖伏击 A/C 双轨账本的<b>持仓 + 待买卖 + 已成交</b>，只读 '
    '<code>khunter_paper_state.json</code>（标准 A · 卖出 RSI&gt;59）与 '
    '<code>khunter_paper_state_c.json</code>（激进 C · 卖出 RSI&gt;50）')
WATCH_NOTE_ETF = (
    'ETF 动量轮动模拟盘的<b>持仓 + 建仓/调仓目标</b>，只读 <code>etf_paper_state.json</code> · '
    '冻结配置：20 日动量前 2 等权 / 绝对动量保护 / 12% 目标波动率 / 月末调仓')
WATCH_NOTE_FUND = (
    '短线基金池（场外基金动量 ≥50 入池）· 与股票池<b>同一跟踪口径</b>，'
    '本卡<b>只显示 <code>type=基金</code> 行</b>（股票行归「跟踪池 · 股票池」）· '
    '数据源 <code>short_pool.json</code>（track / track_pending_short）· '
    '行为变更 2026-09-23（R-track-fund-0923）：原先两池共用同一张表，现按类型分流；'
    '该策略本身没有独立 paper/持仓账本（<code>backtest/fund_paper.json</code> 属中线 FB3-H20 另一策略，不混用）')


SHORT_VIEW_HTML = f'''<div class="view" id="view-short">
{subnav("short", [("st-qlch", "超跌低开低吸"), ("st-kh", "超卖伏击"),
                    ("st-etf", "ETF轮动"), ("st-stk", "股票池"), ("st-fund", "基金池")],
        default_key="st-qlch")}
{subview("st-stk", "股票池", "全量池短线 · 主板信号 · 有信号即买", system_block(
  "view-short-stk", "sys-short-stk",
  "⚡ 短线 · 股票池", "auto", "主板 超卖伏击主信号 · A59 主卖出 / C50 参考 · 低价≥3元",
  v9_short_stock, "tbl-short-stk", "card-short-stk",
  "信号池 = 回测买入清单：15 个超卖形态策略信号 + 信号日 RSI&lt;35 超卖 + 收盘≥3元（主板限定·事件独立·有信号即买）· 卖出 = <b>逐股独立</b>：持仓股自身 RSI 确认日 &gt; 标准版阈值（熊 59/牛 75） → T+1 开盘卖（RSI&gt;50 为激进版参考线，标注但<i>不执行</i>，标准/激进判定归模拟盘双轨）· 档位 = 短线买入口径（强买入/买入）· 下方「👁 跟踪池 · 股票池」自动跟踪可买入标的（保留 30 天）· <b>开盘跳空高开 &gt;3% 的标的标注「⚠ 高开规避」：不追高，可等盘中回落至 3% 以内再考虑买入（9:30 盘中起生效）</b>",
  extra_card=watch_card("st-stk", "股票池", "short", note=WATCH_NOTE_STK), score_sub="动量/量价/通道/波动",
  head_tags=[SHORT_POOL_GATE, SHORT_KHUNTER_BEAR, SHORT_KHUNTER_BADGE,
             '<span class="badge badge-auto">股票 = 15 个超卖形态策略信号 + RSI&lt;35 超卖 + 熊市MA250（主板限定 · 弃用旧战法）</span>',
             '<span class="badge badge-auto">超卖伏击信号密集期每日可能有几只，稀疏期 0 只属正常（事件驱动）</span>'],
  head_note=f"<b>🎯 超卖伏击主信号（蓝标）= 主板 15 策略信号命中 + 信号日 RSI&lt;35 超卖 + 收盘≥3元 + 熊市(沪深300&lt;MA250)</b>（2026-09-07 牛熊线 MA250 投产 + ob59 升级：MA60→MA250 回测 total 68.49→75.06%、ob 55→58→59 组合 total 110.15→119.44%/夏普 0.621→0.648；<b>标准版</b> 卖出 RSI&gt;59 主执行 / <b>激进版</b> RSI&gt;50 参考展示；入场两版相同）· 回测：MA250_ob59_oslb32 n=266 资金池(N5)年化 7.96%/回撤 20.91%/夏普 0.648（满窗验证 105.77%/0.660 稳健）· 分年度 11 年 8 正 3 负（2023 -1.92/2026 -0.91 为小样本）· <b>旧战法（反转分）已全量弃用</b>（主板 -35.65% / 全市场 -41.67% 均负期望，不再展示）· 市况门控仅提醒：沪深300 &gt; MA20 才开新仓；超卖伏击买入由 <b>MA250 熊市门控</b>裁决（非熊→不开新仓仅观察/卖出，弱牛域 OSL32 开仓）· 卖出逐股独立走「👁 跟踪池 · 股票池」· 回测参考见「监控总览」",
  as_of=SHORT_POOL_ASOF, intraday_note=SHORT_POOL_INTRADAY,
  as_of_min=SHORT_POOL.get("intraday_ts") or SHORT_POOL_ASOF_MIN,
  tier_opts=["强买入", "买入", "不买"], tier_add=("强买入", "买入"), tier_watch=("不买",), tier_cut=(), inline=True))}
{subview("st-qlch", "超跌低开低吸", "短期反转 + 跳空低吸 + 熊市择时 · 次日出场",
         qlch_card() + watch_card("st-qlch", "超跌低开低吸", "qlch", note=WATCH_NOTE_QLCH))}
{subview("st-kh", "超卖伏击", "RSI 超卖 + 15 策略形态 · 标准/激进双轨",
         KH_HITS_CARD + KH_PAPER_CARD + watch_card("st-kh", "超卖伏击", "kh", note=WATCH_NOTE_KH))}
{subview("st-etf", "ETF轮动", "20 日动量排名 · 目标权重为策略输出",
         ETF_PAPER_CARD + watch_card("st-etf", "ETF轮动", "etf", note=WATCH_NOTE_ETF))}
{subview("st-fund", "基金池", "场外基金动量（分≥50 才入池）", system_block(
  "view-short-fund", "sys-short-fund",
  "🔵 短线 · 基金池", "auto", "场外基金动量（分≥50 才入池）",
  v9_short_fund, "tbl-short-fund", "card-short-fund",
  "基金池 = 场外基金动量选股（与股票完全独立，资产类别不同）· 现价 = T-1 净值（场外基金净值次日公布）· 基金买入按短线分（≥50）· 与股票池分开展示（2026-09-03 起）",
  extra_card=watch_card("st-fund", "基金池", "short_fund", note=WATCH_NOTE_FUND), score_sub="动量/趋势",
  head_tags=['<span class="badge badge-auto">🔵 场外基金动量（分≥50）</span>',
             '<span class="badge badge-auto">现价 = T-1 净值 · 次日公布</span>'],
  head_note="基金池与股票池（超卖伏击 主板信号）完全独立：基金=净值动量轮动，股票=超卖伏击 事件信号；档位口径同为短线买入口径（强买入/买入）",
  as_of=SHORT_POOL.get("fund_as_of", SHORT_POOL_ASOF), intraday_note="",
  as_of_min="20:00",
  tier_opts=["强买入", "买入", "不买"], tier_add=("强买入", "买入"), tier_watch=("不买",), tier_cut=(), inline=True))}
{ASSET_HINT}
<!-- 页面级「全量池短线跟踪」共享卡已于 2026-09-23（R-track-sep-0923）删除：改为 5 张「策略自有」跟踪池卡，
     分别挂在上方 5 个短线子视图内（id=watch-card-st-*），跨策略标的 0 混入。 -->
<div class="pool-sec"><b>回测数据</b><span>短线池</span></div>
{bt_short_html()}
</div>'''

def qlch_live_payload():
    """构建期把「盘中买点判定」需要的东西一次性内嵌成 window.QLCH（R-qlch-live-0923）。

    为什么在浏览器端判定（ADR-0009）：判定只读行情、只改 DOM —— 零落盘（不写任何 json / 不碰账本）、
    不占收盘链配额、复用已验证的盘中层（#4b）。本函数因此**只读**两个既有产物：
      · backtest/qlch_candidates.json   —— 候选（B4_K3 在产轨）与今收
      · backtest/qlch_paper_state*.json —— 六臂账本（nav 取 equity[-1]、持仓 entry_px/w）
    参数口径与 qlch_card() 同源：单一来源 = qlch 生产脚本 qlch_paper_20260921.py。
    """
    import json as _j
    B = BASE / "backtest"
    _QP = B / "qlch_paper_20260921.py"
    try:
        _src = _QP.read_text(encoding="utf-8") if _QP.exists() else ""
    except Exception:
        _src = ""

    def _g(pat, cast, dflt):
        _m = re.search(pat, _src) if _src else None
        try:
            return cast(_m.group(1)) if _m else dflt
        except Exception:
            return dflt

    # 允许跳空区间（低开达标带）：GAP_LO, GAP_HI = -0.05, -0.02
    GAP_LO = _g(r"GAP_LO\s*,\s*GAP_HI\s*=\s*(-?[\d.]+)", float, -0.05)
    GAP_HI = _g(r"GAP_LO\s*,\s*GAP_HI\s*=\s*-?[\d.]+\s*,\s*(-?[\d.]+)", float, -0.02)
    # 出场：TP_PCT, SL_PCT, MAXHOLD = 0.15, -0.20, 20
    TP = _g(r"TP_PCT,\s*SL_PCT,\s*MAXHOLD\s*=\s*([\d.]+)", float, 0.15)
    SL = _g(r"TP_PCT,\s*SL_PCT,\s*MAXHOLD\s*=\s*[\d.]+,\s*(-?[\d.]+)", float, -0.20)
    MH = _g(r"TP_PCT,\s*SL_PCT,\s*MAXHOLD\s*=\s*[\d.]+,\s*-?[\d.]+,\s*(\d+)", int, 20)
    # 往返成本：生产脚本 COST_RT = 0.002（往返 20bp，成本档见预注册，50bp 为压力档）。
    # 解析不到才退回 0.0015（该值**只**用于盘中估算的显示，不影响任何记账/回测数值）。
    COST_RT = _g(r"COST_RT\s*=\s*([\d.]+)", float, 0.0015)

    _cand = {}
    _fp = B / "qlch_candidates.json"
    if _fp.exists():
        try:
            _cand = _j.load(open(_fp, encoding="utf-8"))
        except Exception:
            _cand = {}
    _ck = (_cand.get("by_track") or {}).get("B4_K3", {})
    _crows = _ck.get("rows") or _ck.get("codes") or []

    def _band2(c):
        """与卡片 _band() 同口径：买点带 = 今收 × [0.95, 0.98]，三位小数。"""
        if not isinstance(c, (int, float)) or c <= 0:
            return None, None
        return round(c * 0.95, 3), round(c * 0.98, 3)

    _rows = []
    for _r in _crows:
        _lo, _hi = _band2(_r.get("close"))
        _it = {"rank": _r.get("rank"), "code": _bare(_r.get("code", "")), "name": _r.get("name", ""),
               "ind": _r.get("ind") or "", "close": _r.get("close"),
               "band_lo": _lo, "band_hi": _hi, "chg": _r.get("chg"), "r20": _r.get("r20")}
        if _lo is not None:      # 止盈/止损点按买点带区间预折算（命中不到就只放 band）
            _it["tp_lo"] = round(_lo * (1 + TP), 3); _it["tp_hi"] = round(_hi * (1 + TP), 3)
            _it["sl_lo"] = round(_lo * (1 + SL), 3); _it["sl_hi"] = round(_hi * (1 + SL), 3)
        _rows.append(_it)

    _acc = {}
    for _key, _label, _fn, _tag in QLCH_TRACKS:
        _f = B / _fn
        if not _f.exists():
            continue
        try:
            _d = _j.load(open(_f, encoding="utf-8"))
        except Exception:
            continue
        _eq = _d.get("equity", [])
        # nav_date = 账本 equity[-1].date：盘中净值判「当日是否已由收盘链记账」（修正 2，避免叠加两次）
        _acc[_key] = {"label": _label, "nav": (_eq[-1]["nav"] if _eq else 1.0),
                      "nav_date": (_eq[-1].get("date") if _eq else None),
                      "cash": _d.get("cash"),
                      "positions": [{"code": _bare(_p.get("code", "")), "name": _p.get("name", ""),
                                     "entry_px": _p.get("entry_px"), "w": _p.get("w"),
                                     "entry_date": _p.get("entry_date")}
                                    for _p in (_d.get("positions") or [])]}
    return {"as_of": _ck.get("as_of", ""), "n": _ck.get("n", len(_rows)), "pool": _ck.get("pool", ""),
            "gap_lo": GAP_LO, "gap_hi": GAP_HI, "tp": TP, "sl": SL, "max_hold": MH, "cost_rt": COST_RT,
            "cost_rt_src": ("%s:COST_RT" % _QP.name) if _src else "fallback 0.0015",
            "rows": _rows, "accounts": _acc}


QLCH_LIVE = qlch_live_payload()
QLCH_JSON = json.dumps(QLCH_LIVE, ensure_ascii=False, separators=(",", ":"))
print("  盘中买点数据: window.QLCH 候选 %d 行 / 六臂账本 %d 臂 / cost_rt=%s / gap=[%s, %s]"
      % (len(QLCH_LIVE["rows"]), len(QLCH_LIVE["accounts"]), QLCH_LIVE["cost_rt"],
         QLCH_LIVE["gap_lo"], QLCH_LIVE["gap_hi"]))
html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2016%2016'%3E%3Crect%20width='16'%20height='16'%20rx='3'%20fill='%232563eb'/%3E%3Cpath%20d='M3%2012V8h2v4zM6%2012V4h2v8zM9%2012V6h2v6zM12%2012V2h2v10z'%20fill='%23fff'/%3E%3C/svg%3E">
<title>标的监控看板（数据截至 {DATA["meta"].get("as_of", "—")} · 构建 {build_ts}）</title>
<style>{THEME_CSS}{KXMM_CSS}{SUBNAV_CSS}
/* 三视图切换 */
.view{{display:none}}
.view.active{{display:block}}
.view-badge{{display:inline-block;padding:1px 7px;border:1px solid transparent;border-radius:var(--r-sm);font-size:11px;background:var(--card2);color:var(--sub);margin-left:8px;vertical-align:middle}}
.view-badge.auto{{background:rgba(245,158,11,.12);color:var(--warn);border-color:rgba(245,158,11,.25)}}
[data-theme="dark"] .view-badge.auto{{color:#fbbf24}}
.view-badge.lite{{background:var(--card2);color:var(--sub);border-color:var(--border)}}
[data-theme="dark"] .view-badge.lite{{background:var(--card2);color:var(--sub);border-color:var(--border)}}
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
.toolbar .flt{{background:var(--card2);border:1px solid var(--border);color:var(--text);border-radius:var(--r);padding:6px 9px;font-size:12.5px;font-family:inherit}}
.toolbar input[type=text]{{background:var(--card2);border:1px solid var(--border);color:var(--text);border-radius:var(--r);padding:6px 11px;font-size:12.5px;width:200px;font-family:inherit}}
/* 表头两行（权重分/构成第二行指标名） */
.th-sub{{font-size:10px;color:var(--faint);font-weight:400;margin-top:2px}}
/* 到顶/到底浮动按钮 */
.scroll-fab{{position:fixed;right:22px;bottom:22px;display:flex;flex-direction:column;gap:8px;z-index:950}}
.scroll-fab button{{width:40px;height:40px;border-radius:50%;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:16px;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.15);font-family:inherit}}
.scroll-fab button:hover{{border-color:var(--accent);color:var(--accent)}}
/* 基金回测参考 · 三池独立大卡（2026-08-17 去 ETF） */
.bt-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}
.bt-card{{background:var(--card2);border:1px solid var(--border);border-radius:var(--r);padding:16px}}
.bt-card .bt-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;font-size:13.5px;font-weight:600}}
.bt-card .bt-tag{{font-size:11px;color:var(--faint);background:var(--card);border:1px solid var(--border);border-radius:var(--r-sm);padding:2px 10px}}
.bt-card .bt-curve{{background:var(--card);border:1px solid var(--border);border-radius:var(--r);padding:6px;margin-top:10px}}
/* 日志视图（内嵌，主题变量驱动） */
.rev-item,.rel-item{{background:var(--card2);border:1px solid var(--border);border-radius:var(--r);margin-bottom:10px;overflow:hidden}}
.rev-item summary,.rel-item summary{{display:flex;align-items:center;gap:10px;padding:10px 14px;cursor:pointer;font-size:12.5px;color:var(--text);list-style:none;flex-wrap:wrap;user-select:none}}
.rev-item summary::-webkit-details-marker,.rel-item summary::-webkit-details-marker{{display:none}}
.rev-item summary::before,.rel-item summary::before{{content:'▸';color:var(--faint);transition:transform .15s;font-size:12px}}
.rev-item[open] summary::before,.rel-item[open] summary::before{{transform:rotate(90deg)}}
.rev-item[open] summary,.rel-item[open] summary{{border-bottom:1px solid var(--line)}}
.rev-item summary:hover,.rel-item summary:hover{{border-color:var(--accent)}}
.rev-flag{{font-size:13px}}
.rev-meta{{color:var(--faint);font-size:12px}}
.rev-body{{padding:14px 16px}}
/* 累计总览独立卡片（2026-08-18 晚：内嵌视图顶部仅一份） */
.rev-cum{{background:var(--card2);border:1px solid var(--border);border-radius:var(--r);padding:14px 16px;margin-bottom:12px}}
.rev-cum-title{{font-size:14px;font-weight:600;color:var(--accent);display:flex;align-items:center;gap:8px;margin-bottom:6px}}
.rev-cum-badge{{font-size:11px;color:var(--faint);background:var(--card);border:1px solid var(--border);border-radius:var(--r-sm);padding:2px 10px;font-weight:400}}
.rev-cum-sub{{color:var(--faint);font-size:12px;margin-bottom:8px}}
.rev-cum .tbl th{{background:var(--card2)}}
.rev-cum .tbl tbody tr.rev-cum-total td{{font-weight:700;background:var(--card2)}}
.rel-ver{{font-weight:700;font-size:15px;color:var(--accent);letter-spacing:.5px}}
.rel-date{{color:var(--faint);font-size:11.5px;background:var(--card);border:1px solid var(--border);padding:1px 7px;border-radius:var(--r-sm)}}
.rel-body{{color:var(--text);font-size:13px;line-height:1.75}}
.rel-body ul{{margin:6px 0 6px 18px;padding:0}}
.rel-body li{{margin:4px 0}}
.rel-body b{{color:var(--text)}}
.rev-md h3{{font-size:15px;margin:16px 0 8px;color:var(--text)}}
.rev-md h4{{font-size:14px;margin:12px 0 6px;color:var(--text)}}
.rev-md p{{margin:6px 0;color:var(--text)}}
.rev-md blockquote{{background:var(--card2);border-left:3px solid var(--accent);padding:8px 12px;margin:8px 0;border-radius:0 8px 8px 0;color:var(--sub)}}
/* 持仓跟踪 */
/* 跟踪池表配色（R-track-sep-0923：id 带 key 后缀 → 改按 class 选择，5 张卡共用） */
.watch-tbl .up{{color:var(--down)}} .watch-tbl .down{{color:var(--up)}} .watch-tbl .warn{{color:var(--warn)}}
#watch-v9-table .up{{color:var(--down)}} #watch-v9-table .down{{color:var(--up)}} #watch-v9-table .warn{{color:var(--warn)}}
.watch-tbl td,#watch-v9-table td{{font-variant-numeric:tabular-nums}}
.bt-short{{background:var(--card2);border:1px dashed var(--border);border-radius:var(--r);padding:22px;text-align:center;margin-top:16px}}
.bt-short h3{{margin:0 0 6px;color:var(--sub);font-size:13.5px}}
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
.op{{font-size:13px;padding:6px 14px;border-radius:var(--r-sm);background:var(--card2);border:1px solid var(--border)}}
.op b{{font-size:13.5px}}
.op-add{{color:var(--up)}}
.op-watch{{color:var(--warn)}}
.op-cut{{color:var(--down)}}
/* 子池分节标题（R-poolsec-0918 · 用户需求 #6） */
.pool-sec{{display:flex;align-items:baseline;gap:10px;margin:20px 2px 8px;padding-bottom:7px;
  border-bottom:1px solid var(--border)}}
.pool-sec b{{font-size:13.5px;font-weight:600;color:var(--text)}}
.pool-sec span{{font-size:12px;color:var(--faint)}}
/* 逐标的详情卡片（模板风格 · 等高适配） */
.stock-cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:14px}}
.stock-card{{background:var(--card2);border:1px solid var(--border);border-radius:var(--r);padding:14px;display:flex;gap:12px;align-items:stretch}}
.stock-card .radar-wrap{{flex:0 0 120px;display:flex;align-items:center;justify-content:center}}
.stock-card .radar-wrap svg{{width:120px;height:120px}}
.stock-card .body{{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center}}
.stock-card h3{{margin:0 0 6px;font-size:14px}}
.stock-card .sub{{color:var(--faint);font-size:11px;font-weight:400}}
.stock-card .meta{{color:var(--sub);font-size:12px;margin:3px 0;line-height:1.6}}
/* ETF 动量轮动卡片（2026-09-06） */
.etf-code{{color:var(--faint);font-size:10px;margin-left:6px;font-family:var(--mono,monospace)}}
.etf-sec{{font-size:12.5px;font-weight:600;color:var(--accent);margin-bottom:6px}}
#card-etf-paper .tbl{{margin-bottom:0}}
#card-etf-paper .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}}
#card-kh-paper .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}}
</style></head><body>
{NAV_HTML}
<div class="container">

<!-- ============ 视图 A：三轨中长线（2026-09-13 起） ============ -->
<div class="view" id="view-auto">
<div class="card" id="sys-auto">
<div class="sys-head">
<div class="sys-head-top">
<h2>🛰️ 三轨中长线 <span class="view-badge auto">FB3-H20 主仓 + SUPER 卫星 · 资金 60/0/40</span></h2>
</div>
<div class="sys-head-tags">
<span class="badge badge-auto">v9 股票分层战法已退役（十重证伪 · ADR-0006/0007）</span>
<span class="badge badge-auto">三轨信号 = backtest/signal_satellite_0913.py · 每日收盘跑</span>
<span class="badge badge-auto">退出 = 定期换仓制（详见下方说明）</span>
</div>
</div>
</div>
{subnav("sys-auto", [("mf-main", "多因子主仓"), ("mf-gold", "黄金对冲"),
                       ("mf-mom", "动量增强"), ("mf-fund", "基金主仓"),
                       ("mf-ctr", "对照臂", None, True)])}
{subview("mf-main", "多因子主仓", "13 因子打分 Top20 · 月频调仓 · 单票上限见报告",
         SAT_CARD + SAT_PAPER_B_CARD)}
{subview("mf-gold", "黄金对冲", "10% 黄金 ETF · 买入持有 · 永不回补", GOLD_SAT_CARD)}
{subview("mf-mom", "动量增强", "20 日涨幅倾斜臂 · 纸面记录", RET20_PAPER_CARD)}
{subview("mf-fund", "基金主仓", "基金动量轮动 · 持 20 日 · 牛熊切换", FB3_POOL_CARD + FUND_PAPER_CARD)}
{subview("mf-ctr", "对照臂", "零资金对照 · 不占实盘资金 · 仅记录信号与幻影净值", SHADOW_RET20_CARD)}
{ASSET_HINT}
<div class="card" id="v9-retired-card" data-removed="1" style="display:none"><h2>🗂️ v9 全量池（已退役）</h2><div class="sub" style="color:var(--up)">⛔ v9 股票分层战法与 197 只跟踪池已于 2026-09-13 退役并移除展示——十重证伪确认负期望（ADR-0006/0007）。历史回测明细见「📝 更新日志」v5.9~v5.11.15 与 <code>backtest/</code> 报告存档。</div><div class="sub"><b>双轨退出规则</b>：① 主仓 FB3-H20 = 20 交易日月度轮动 + 牛熊 regime 切换（沪深300&lt;MA200 转 Top3 低波防守仓）——<b>无个股止盈止损</b>（基金 NAV 无涨跌停，止盈变体回测全部减值）；② SUPER = 月频调仓 + 中证1000&lt;MA20 组合半仓闸（且关闸期取高波半区）+ <b>pct40 因子化出场已启用（跌出前40%分位 → T+1 开盘卖，留现金至下一调仓）</b>。</div></div>
<div class="pool-sec"><b>回测数据</b><span>中长线三轨</span></div>
{bt_all_html()}
<div class="card" id="lt-rule"><h2>选股指标逻辑</h2>
<div class="rule-box" style="margin-bottom:0"><b>监控口径</b>：权重分 = 动量30% + 趋势35% + Aroon20% + 量价15%（2026-09-08 投产 V5）｜ 档位 = ≥75 满仓加仓 / ≥60 轻仓加仓 / ≥45 观望 / ≥30 减半 / &lt;30 清仓
<br><b>卖出闸门（每日）</b>：全量池 掉榜连续5日 或 权重分&lt;50 → 清仓信号（21交易日倒计时）｜ 市况门控 沪深300 vs MA200（仅提醒，非交易指令）</div>
</div>
</div>

<!-- ============ 视图 C：全量池短线（2026-09-03 起 股票池 / 基金池 分板块展示） ============ -->
{SHORT_VIEW_HTML}

<!-- ============ 视图 D：首板低吸（双池滤网 v1.3 · 第三个系统，池A 超跌/池B 趋势 + 生产预筛模拟盘） ============ -->
{a5_view_html()}

{KXMM_VIEW_HTML.replace("<!--KXMM_EXTRA-->", _MKT_WEATHER_CARD + _CROWD_CARD)}

<!-- ============ 视图 E：复盘日志（内嵌，与各池同形态） ============ -->
<div class="view" id="view-review">
{_rev_cum}
<div class="card" id="a5-review-block" style="border-color:rgba(245,158,11,.35)">
<h2>🎯 首板低吸（双池滤网 v1.3）模拟盘验证 <span class="badge badge-auto">池A 超跌 / 池B 趋势 · 非实盘指令</span></h2>
<div class="sub">逐笔模拟盘跟踪（net_ret 含成本）· 验证门基准 = 双池并集（胜率 56.1% / 均值 +1.19% / tp 25.0%）· 新口径独立计数（v1 旧口径 11 笔归档）· 详细见「🎯 首板低吸」视图</div>
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
#comment-loading{{display:none;flex-direction:column;align-items:center;gap:6px;padding:36px 12px;color:var(--faint,#888);font-size:14px;border:1px dashed var(--line,#ddd);border-radius:var(--r);margin-top:12px}}
#comment-loading .comment-loading-sub{{font-size:12px;opacity:.75}}
</style>
</div>
</div>

</div>
<div class="sub" style="text-align:center;color:var(--faint);font-size:11px;padding:8px 0 4px">看板构建于 {build_ts} · 版本 v5.13.9（+盘中实时·顶栏占位修复） · 数据截至 {DATA["meta"].get("as_of", "—")} · 若页面与预期不符请 Ctrl+F5 强制刷新</div>
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
<script src="echarts.min.js"></script>
<script src="kxmm_data.js"></script>
<script src="heatmap_data.js"></script>
<link rel="stylesheet" href="https://unpkg.com/artalk@2/dist/Artalk.css">
<script src="https://unpkg.com/artalk@2/dist/Artalk.js"></script>
<script>window.SHORT_POOL = {SHORT_POOL_SLIM};</script>
<script>window.ETF_SNAP = {ETF_SNAP_JS};</script>
<script>window.KH_SNAP = {KH_SNAP_JS};</script>
<script>window.STOCK_META = {STOCK_META_JS};</script>
<!-- 盘中买点判定数据（R-qlch-live-0923）：qlch 候选 + 策略参数 + 六臂账本净值，构建期一次性内嵌。
     只读快照：判定与盘中净值都在浏览器端算（ADR-0009），不落盘、不写账本、不改收盘链。 -->
<script>window.QLCH = {QLCH_JSON};</script>
<script>
/* 三视图导航（覆盖默认 4 项） */
window.ENH.nav = [
  ["kxmm","","市场晴雨",[["kxmm-fg","恐贪指数"],["kxmm-heat","热力图"],["hm-card","热力树图"],["crowd-card","大盘拥挤度"],["mkt-weather","市场晴雨表"]]],
  ["sys-auto","","中长线池",[["sat-card","卫星目标持仓"],["sat-paper-b-card","多因子主仓 模拟盘"],["gold-sat-card","黄金对冲"],["ret20-paper-card","动量增强模拟盘"],["fb3-pool-card","FB3 基金池"],["fund-paper-card","基金主仓模拟盘"]]],
  ["short","","短线选股",[["card-short-stk","股票池 汇总表"],["card-short-stk-detail","股票池 逐标的详情"],["qlch-card","🏷️ 超跌低开低吸"],["card-kh-hits","🏷️ 超卖伏击 · 命中策略"],["card-kh-paper","🏷️ 超卖伏击 · 模拟盘"],["card-etf-paper","ETF 动量轮动"],["card-short-fund","基金池 汇总表"],["card-short-fund-detail","基金池 逐标的详情"],["watch-card-st-qlch","👁 跟踪池 · 超跌低开低吸"],["watch-card-st-kh","👁 跟踪池 · 超卖伏击"],["watch-card-st-etf","👁 跟踪池 · ETF轮动"],["watch-card-st-stk","👁 跟踪池 · 股票池"],["watch-card-st-fund","👁 跟踪池 · 基金池"]]],
  ["a5","","打板专区",[["a5-watchlist","观察清单"],["a5-avoid","回避清单"],["a5-positions","持仓"],["a5-closed","已平仓"],["a5-curve","净值曲线"]]],
  ["qingju","","社区讨论",[],"https://qingju.me/"]
];
/* 视图切换模式：滚动不更新导航高亮（COMMON_JS renderSidenav 检测此标志） */
window.ENH.NAV_SWITCH = true;
/* 开市/休市徽章数据（构建期注入）：tradeDay = index_000300 末行；isTradingDay = 末行是否今日 */
window.MKT_STATUS = {json.dumps(_MKT_STATUS)};
/* 三池回测净值（股票/基金，监控总览展示；2026-08-17 去 ETF） */
window.ENH.sub_curves = {{
  stock: {json.dumps(DATA["systems"]["v9_auto"]["equity"])},
  fund: {json.dumps(v_fund)},
  super: {json.dumps(v_super)},
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
    el.innerHTML='<svg viewBox="0 0 1400 240" style="width:100%;height:auto"><text x="700" y="120" font-size="15" fill="var(--faint)" text-anchor="middle">未回测 · 用户仅可买主板（超卖伏击主信号按主板回测，见卡片 KPI）</text></svg>';
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
    g+='<text x="'+(PAD_L-8)+'" y="'+(y(t)+4)+'" font-size="12" fill="var(--faint)" text-anchor="end">'+tickLabel(t)+'</text>';}}
  var prevYr=null;
  for(var i=0;i<n;i++){{var yr=2016+Math.floor(i/252);
    if(yr!==prevYr){{g+='<text x="'+x(i)+'" y="'+(H-PAD_B+18)+'" font-size="13" fill="var(--faint)" text-anchor="middle">'+yr+'</text>';prevYr=yr;}}}}
  var pts='';
  for(var i=0;i<vals.length;i+=3){{pts+=x(i).toFixed(1)+','+y(vals[i]).toFixed(1)+' ';}}
  el.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto">'+g+
    '<polyline points="'+pts+'" fill="none" stroke="'+color+'" stroke-width="2"/>'+
    '<text x="'+(PAD_L+10)+'" y="'+(PAD_T+16)+'" font-size="13" fill="'+color+'">'+label+' → +'+totalPct+'%</text>'+
    '<text x="'+(W-PAD_R-6)+'" y="'+(PAD_T+8)+'" font-size="11" fill="var(--faint)" text-anchor="end">对数坐标 · 净值(100起)</text></svg>';
}}
function renderSubCurve(){{
  var C=window.ENH.sub_curves;if(!C)return;
  renderOneCurve('curve-chart-fund', C.fund, '#3b82f6', '主仓 FB3-H20（2000池）', '+'+{s_fund["total_return_pct"]:.0f});
  renderOneCurve('curve-chart-super', C.super, '#8b5cf6', '卫星·SUPER', '+'+{s_super.get("total_return_pct") or 0:.0f});
  renderOneCurve('curve-chart-stock-all', C.stk_all, '#94a3b8', '股票 一体（v9 已退役）', '+'+{round(s_stk["all"].get("total_return_pct") or 0):.0f});
  renderOneCurve('curve-short-stock-all', C.short_stock, '#f59e0b', '短线 股票 一体', '{(ss_stk["all"].get("total_return_pct") or 0):+.0f}');
  renderOneCurve('curve-short-stock-main', [], '#ea580c', '短线 纯主板（超卖伏击）', '无净值曲线');
  renderOneCurve('curve-short-stock-gem', [], '#22c55e', '短线 纯创业板', '未回测');
  renderOneCurve('curve-short-stock-star', [], '#8b5cf6', '短线 纯科创板', '未回测');
  renderOneCurve('curve-short-fund', C.short_fund, '#3b82f6', '基金短线', '{ss_fund["total_return_pct"]:+.0f}');
}}
/* 视图切换（hash 驱动：切换时更新 location.hash，加载/前进后退时按 hash 定位） */
var VIEW_MAP={{'sys-auto':'view-auto','short':'view-short','a5':'view-a5','review':'view-review','changelog':'view-changelog','comment':'view-comment','kxmm':'view-kxmm'}};
function switchView(key){{
  var v=VIEW_MAP[key];if(!v)return;
  document.querySelectorAll('.view').forEach(function(x){{x.classList.remove('active');}});
  document.getElementById(v).classList.add('active');
  window.scrollTo(0,0);
  if(location.hash!=='#'+key)try{{history.replaceState(null,'','#'+key)}}catch(e){{}}
}}
function initSatTables(){{  /* 双卫星表搜索/排序 */
  var tables=document.querySelectorAll('table.sat-tbl');if(!tables.length)return;
  Array.prototype.forEach.call(tables,function(tbl){{
    var t=tbl.getAttribute('data-t');
    var q=document.querySelector('.sat-q[data-t="'+t+'"]');
    var srt=document.querySelector('.sat-sort[data-t="'+t+'"]');
    var cnt=document.querySelector('.sat-count[data-t="'+t+'"]');
    function apply(){{
      var rows=Array.prototype.slice.call(tbl.querySelectorAll('tbody tr'));
      var qv=((q&&q.value)||'').trim().toLowerCase();
      rows.forEach(function(r){{r.style.display=(!qv||r.cells[0].textContent.toLowerCase().indexOf(qv)>=0)?'':'none';}});
      var tb=tbl.querySelector('tbody');
      if(srt&&srt.value==='code'){{rows.sort(function(a,b){{return a.cells[0].textContent.localeCompare(b.cells[0].textContent);}});rows.forEach(function(r){{tb.appendChild(r);}});}}
      if(srt&&srt.value==='lot'){{rows.sort(function(a,b){{return (parseFloat(a.cells[4].textContent.replace(/[^0-9.]/g,''))||0)-(parseFloat(b.cells[4].textContent.replace(/[^0-9.]/g,''))||0);}});rows.forEach(function(r){{tb.appendChild(r);}});}}
      var shown=rows.filter(function(r){{return r.style.display!=='none';}}).length;
      if(cnt)cnt.textContent=shown+' / '+rows.length+' 只';
    }}
    if(q)q.addEventListener('input',apply);
    if(srt)srt.addEventListener('change',apply);
    apply();
  }});
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
{SUBNAV_JS}
/* 覆盖：左侧导航点击切换视图 */
document.addEventListener('DOMContentLoaded',function(){{
  applyHash();   // 按 URL hash 定位视图（历史页跳转 dual_system.html#sys-auto 直接显示普适版）
  renderSubCurve();   // 基金回测净值曲线
  initSatTables();   // 双卫星表搜索/排序
  /* 2026-09-06 见底信号市场级恐慌观察指标（advisory-only）：读 SHORT_POOL.market_gate.jiandi_panic */
  function renderJiandiPanic(){{
    var box=document.getElementById('mw-jiandi');if(!box)return;
    var mg=(window.SHORT_POOL&&window.SHORT_POOL.market_gate)||{{}};
    var jp=mg.jiandi_panic||null;
    if(!jp){{box.innerHTML='<span>🕐 见底信号·市场级恐慌观察：暂无数据（jiandi_panic.json 未生成/未接入）</span>';return;}}
    var c=jp.counts||{{}};
    var lv=jp.level_name||'—';
    var lvColor={{'无恐慌':'#16a34a','轻微':'#d97706','市场级恐慌':'#dc2626','极恐慌':'#b91c1c'}}[lv]||'#16a34a';
    box.innerHTML='<span class="mw-item">🕐 见底信号(主板) 入市 <b>'+ (c.rushi!=null?c.rushi:'—') +'</b> / 机会 <b>'+ (c.jihui!=null?c.jihui:'—') +'</b> / 见底 <b>'+ (c.jiandi!=null?c.jiandi:'—') +'</b></span>'+
      '<span class="mw-item">恐慌级别 <b style="color:'+lvColor+'">'+lv+'</b>('+ (jp.panic_level!=null?jp.panic_level:'—') +')</span>'+
      '<span class="mw-item">日期 '+ (jp.date||'—') +'</span>'+
      '<span class="mw-note">advisory-only · 不参与门控 · 2026-09-06 投产（见底信号回测 alpha 观察）</span>';
  }}
  try{{renderJiandiPanic();}}catch(e){{console.warn('renderJiandiPanic',e);}}
  /* 全量池短线跟踪：自动跟踪池（SHORT_POOL.track，可买入标的 30 天）+ 可选手动补充（localStorage） */
  function boardCell(v){{
    var cls={{'主板':'board-sh','创业板':'board-cy','科创板':'board-kc','北交所':'board-bj'}}[v]||'';
    return v?'<span class="board-tag '+cls+'">'+v+'</span>':'—';
  }}
  /* 2026-09-05：板块/行业统一查找 —— 优先 window.STOCK_META（全市场紧凑映射，内联），回退 ENH.details（v9 池） */
  function stockMeta(code){{
    var m=window.STOCK_META||{{}};
    var e=m[code];
    if(e)return {{board:e[0]||'—',industry:e[1]||'—'}};
    var det=(window.ENH&&window.ENH.details&&window.ENH.details[code])||{{}};
    return {{board:det.board||'—',industry:det.industry||'—'}};
  }}
  function fillTierOptions(selId,tiers){{
    var sel=document.getElementById(selId);if(!sel)return;
    var cur=sel.value;
    var seen={{}};var opts=[];
    tiers.forEach(function(t){{if(t&&!seen[t]){{seen[t]=1;opts.push(t);}}}});
    var html='<option value="">全部档位</option>'+opts.map(function(t){{return '<option value="'+t+'">'+t+'</option>';}}).join('');
    if(sel.innerHTML!==html){{sel.innerHTML=html;if(cur)sel.value=cur;}}
  }}
  /* R-track-sep-0923：跟踪池按策略独立 —— 本函数改为**按子视图 key 参数化**渲染。
     目前只有 st-stk（股票池）走浏览器端渲染（SHORT_POOL.track）；其余 4 张卡由构建期 Python
     读各自策略账本渲染（见 watch_card()）。页面级共享卡已删除。 */
  var WATCH_KEYS=['st-stk','st-fund'];
  /* R-track-fund-0923：同一份 SHORT_POOL.track 按类型分流 —— 股票池只看 type!=fund，基金池只看 type=fund（待确认列表同规则） */
  function _isFundRow(o){{ var t=(o&&o.type)||(o&&o.last&&o.last.type)||''; if(t) return t==='fund';
    var pool=(o&&o.pool)||(o&&o.last&&o.last.pool)||''; return pool==='基金'; }}
  function _keepRowFor(k,o){{ return (k==='st-fund') ? _isFundRow(o) : !_isFundRow(o); }}
  function renderWatchFor(k){{
    var box=document.getElementById('watch-table-'+k);if(!box)return;
    var S=window.SHORT_SIGNALS;if(!S){{box.innerHTML='<div class="sub">信号数据未加载（缺 short_signals.js）</div>';return;}}
    var track=(window.SHORT_POOL&&window.SHORT_POOL.track)?window.SHORT_POOL.track:{{}};
    // 2026-08-19 市况门控口径统一：门控关闭时跟踪池档位已改写「不开新仓·仅跟踪」，顶部横幅提示
    var _mg=(window.SHORT_POOL&&window.SHORT_POOL.market_gate)||{{}};
    var _gateOpen=_mg.open;
    var _gateBox=document.getElementById('watch-gate-'+k);
    if(_gateBox){{
      if(_gateOpen===false){{
        _gateBox.innerHTML='<div class="sub" style="margin-bottom:6px;color:var(--warn)">⚠ 市况门控关闭（沪深300 '+( _mg.idx_close!=null?_mg.idx_close:'—')+' < MA20 '+( _mg.idx_ma20!=null?_mg.idx_ma20:'—')+'）—— 已入池跟踪标的仅跟踪卖出信号，「不开新仓·仅跟踪」（安全口径，非买入）</div>';
      }}else{{_gateBox.innerHTML='';}}
    }}
    // 待确认（pending）：当日新上榜、下个收盘确认后入正式池（2026-08-18 用户需求，与中长线一致）
    var pnd=(window.SHORT_POOL&&window.SHORT_POOL.track_pending_short)?window.SHORT_POOL.track_pending_short:{{}};
    var pendBox=document.getElementById('watch-pending-'+k);
    var pkeys=Object.keys(pnd);
    if(pendBox){{
      if(pkeys.length){{
        var ph='<div class="sub" style="margin-bottom:6px;color:var(--warn)">⏳ 待确认 '+pkeys.length+' 只 —— 上榜后下一收盘确认在池再入池（隔离当日信号）</div><table class="tbl"><tbody>';
        pkeys.forEach(function(c){{
          var p=pnd[c]||{{}};var last=p.last||{{}};if(!_keepRowFor(k,p))return;
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
      var t=track[code]||{{}};if(!_keepRowFor(k,t))return;
      var entry=t.entry?new Date(String(t.entry).replace(/-/g,'/')):null;
      var age=entry?Math.floor((now-entry)/86400000):0;
      if(age>=30)return;   // 30 天过期（前端兜底，与服务端一致）
      base.push({{code:code,entry:t.entry||'—',exit:t.exit||'—',age:age,type:t.type||'',pool:t.pool||''}});
    }});
    var bar=document.getElementById('watch-bar-'+k);
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
      // 标准版档位/动作沿用现有语义；激进版=超卖伏击 RSI>50 参考卖出（c_sell，与标准版独立）
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
      // 2026-09-04 修复（grill Q1）：超卖伏击主信号买入档必须显示为买入信号（原落进「观望」兜底）
      else if(rec.tier==='强买入'){{act='🟢 强买入信号（超卖伏击）';actCls='up';}}
      else if(rec.tier==='买入'){{act='🟢 买入信号（超卖伏击）';actCls='up';}}
      else if(!topSet[code]){{act='🔄 下次轮动换出';actCls='warn';}}
      else if(rec.tier==='轻仓加仓'||rec.tier==='满仓加仓'){{act='✅ 继续持有';actCls='up';}}
      else {{act='🟡 观望（不补不加）';actCls='warn';}}
      var typeName=(grp==='fund'||r.type==='fund')?'基金':(r.pool||'股票');   // 2026-08-18 用户需求：股票类型按权限细分（主板/创业板/科创板）
      rows.push({{code:code,entry:r.entry,exit:r.exit||'—',age:r.age,grp:grp,typeName:typeName,pool:r.pool,rec:rec,act:act,actCls:actCls,inPool:topSet[code]?1:0,tierDisp:tierDisp,tierC:tierC,actC:actC,actCCls:actCCls}});
    }});
    if(bar){{bar.style.display=rows.length?'':'none';}}
    if(!rows.length){{box.innerHTML='<div class="sub" style="color:var(--faint)">暂无跟踪 —— 短线表出现可买入标的（强买入/买入）后自动加入，保留 30 天</div>';return;}}
    // 读筛选/排序（uncontrolled，每次渲染读取 DOM）
    var q=(document.getElementById('watch-q-'+k).value||'').trim().toLowerCase();
    var ftype=document.getElementById('watch-f-type-'+k).value;
    var fpool=document.getElementById('watch-f-inpool-'+k).value;
    var ftier=document.getElementById('watch-f-tier-'+k).value;
    var sortKey=document.getElementById('watch-sort-'+k).value||'entry';
    fillTierOptions('watch-f-tier-'+k, rows.map(function(r){{return r.tierDisp||null;}}));
    var seenType={{}};var typeOpts=[];
    rows.forEach(function(r){{if(r.typeName&&!seenType[r.typeName]){{seenType[r.typeName]=1;typeOpts.push(r.typeName);}}}});
    var tsel=document.getElementById('watch-f-type-'+k);
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
    var cnt=document.getElementById('watch-count-'+k);
    if(cnt)cnt.textContent='筛选 '+filtered.length+' / 共 '+rows.length+' 只';
    if(!filtered.length){{box.innerHTML='<div class="sub" style="color:var(--faint)">无匹配标的 —— 调整搜索/筛选条件后重试</div>';return;}}
    var h='<div class="sub" style="margin-bottom:6px;color:var(--sub)">🧭 版本说明：<b>标准版</b>=生产主信号（熊市卖出 RSI&gt;59 / 牛市卖出 RSI&gt;75）；<b>激进版</b>=参考线（RSI&gt;50 卖出，更早止盈高周转）—— 双版本并行对决；卖出为独立信号，不含买入含义</div>'
          +'<table class="tbl"><thead><tr><th>标的</th><th>类型</th><th>行业</th><th style="text-align:center">入池日期</th><th style="text-align:center">出池日期</th><th style="text-align:center">已跟踪</th><th style="text-align:right">现价</th><th style="text-align:right">涨跌</th><th style="text-align:center">短线分</th><th style="text-align:center">档位(标准版)</th><th style="text-align:center">建议(标准版)</th><th style="text-align:center">档位(激进版)</th><th style="text-align:center">建议(激进版)</th><th style="text-align:center">MA5</th></tr></thead><tbody>';
    filtered.forEach(function(r){{
      var rec=r.rec;
      var ageS=r.age===null?'—':(r.age+' 天 / 剩 '+(30-r.age)+' 天');
      // 2026-08-27 修复：停牌股显示「⏸ 停牌」徽章，涨跌/MA5 置「—」（旧数据不误导）
      var susp=rec.suspended;
      var chgDisp=susp?'停牌':((rec.chg>0?'+':'')+rec.chg+'%');
      var chgCls=susp?'':(rec.chg>0?'up':'down');
      var ma5Disp=susp?'—':(rec.ma5_above?'✅ 上方':'⚠️ 下方');
      // 2026-09-05 用户需求：跟踪池统一格式（板块/行业列）
      // 2026-09-05 修复：SHORT_POOL_SLIM 不含 details → 走 stockMeta（STOCK_META 全市场映射，回退 ENH.details）
      var ind=stockMeta(r.code).industry;
      // 2026-09-04（grill Q2-1）：标准/激进双列（激进列对非 超卖伏击 标的显示 —）
      var tierCDisp=r.tierC||'—'; var actCDisp=r.actC||'—'; var actCCls=r.actCCls||'';
      h+='<tr><td><b>'+rec.name+'</b>'+(susp?' <span class="badge badge-warn" style="background:var(--warn-bg,#fef3c7);color:#92400e;font-size:11px;padding:1px 6px;border-radius:8px;margin-left:4px">⏸ 停牌</span>':'')+'<br><span style="color:var(--faint);font-size:11px">'+r.code+'</span></td><td>'+r.typeName+'</td><td>'+ind+'</td><td style="text-align:center">'+r.entry+'</td><td style="text-align:center">'+(r.exit||'—')+'</td><td style="text-align:center">'+ageS+'</td><td style="text-align:right">'+rec.px+'</td><td style="text-align:right" class="'+chgCls+'">'+chgDisp+'</td><td style="text-align:center">'+rec.score+'</td><td style="text-align:center">'+r.tierDisp+'</td><td style="text-align:center" class="'+r.actCls+'">'+r.act+'</td><td style="text-align:center">'+tierCDisp+'</td><td style="text-align:center" class="'+actCCls+'">'+actCDisp+'</td><td style="text-align:center">'+ma5Disp+'</td></tr>';
    }});
    h+='</tbody></table>';
    box.innerHTML=h;
  }}
  // 2026-08-17 用户决策：移除手动补充功能，顺带清理旧 localStorage 残留（含用户误加的"金安国纪"条目）
  try{{localStorage.removeItem('short_watchlist');}}catch(_e){{}}
  /* R-track-sep-0923：逐子视图绑定 + 首渲染（目前只有 st-stk 走 JS；其余 4 张为构建期渲染） */
  WATCH_KEYS.forEach(function(k){{
    ['watch-q-'+k,'watch-f-type-'+k,'watch-f-inpool-'+k,'watch-f-tier-'+k,'watch-sort-'+k].forEach(function(id){{
      var el=document.getElementById(id);if(!el)return;
      el.addEventListener(id.indexOf('watch-q-'+k)===0?'input':'change',function(){{renderWatchFor(k);}});
    }});
    renderWatchFor(k);
  }});
  /* 2026-09-05 用户需求：短线选股池命中策略一览 —— 命中 15 个超卖形态策略全展示，按 RSI 升序，档位/建议区分 */
  /* 2026-09-05 修复（用户反馈）：①表头被 innerHTML 整体替换删除 → 只替换 tbody；②分域问号 = 数据缺 regime → 兜底显示 —；
     ③标准版(A59)/激进版(C50) 混一列打架 → 拆四列独立展示 */
  var KH_STRAT_CN={{'trend_resonance':'趋势共振','trend_start':'趋势起点','immortal_guidance':'仙人指路','multi_golden_cross':'多金叉共振','limit_up_pullback':'涨停回马枪','strong_wash':'强势洗盘','golden_cross_not_green':'金叉不绿','morning_star':'启明星','strategy_2560':'2560战法','golden_triangle':'黄金三角','limit_up_sideways':'涨停横盘','multi_party_cannon':'多方炮','resistance_breakout':'突破压力','trend_acceleration':'趋势加速','w_bottom':'W底'}};
  var KH_REGIME_CN={{'bear':'🐻 熊市','bull':'🌞 牛市','weak_bull':'🌙 弱牛'}};
  /* 标准版（A59 主卖出）：buy→买入 / sell→卖出（note 为 A 版文案）/ 否则观望 */
  function khStd(kh){{
    if(kh.buy)return {{tier:'买入',act:'🟢 买入信号 · T+1 开盘买入',cls:'up'}};
    if(kh.sell)return {{tier:'卖出',act:kh.note||'🔴 卖出信号 · T+1 开盘卖',cls:'down'}};
    return {{tier:'观望',act:'🟡 未达买入/卖出阈值 · 仅观察',cls:'warn'}};
  }}
  /* 激进版（C50 参考线）：buy→买入 / c_sell→卖出 / 否则观望（与标准版独立，不打架） */
  function khAgg(kh){{
    if(kh.buy)return {{tier:'买入',act:'🟢 买入信号 · T+1 开盘买入',cls:'up'}};
    if(kh.c_sell)return {{tier:'卖出',act:'🔴 激进版参考卖出（RSI>50）· T+1 开盘卖',cls:'down'}};
    return {{tier:'观望',act:'🟡 未达买入/卖出阈值 · 仅观察',cls:'warn'}};
  }}
  function renderKhHits(){{
    var box=document.getElementById('kh-hits-table');if(!box)return;
    var tb=box.querySelector('tbody');if(!tb)return;
    var S=window.SHORT_SIGNALS;if(!S||!S.stock){{tb.innerHTML='<tr><td colspan="15" class="sub">信号数据未加载（缺 short_signals.js）</td></tr>';return;}}
    var rows=[];
    Object.keys(S.stock).forEach(function(code){{
      var rec=S.stock[code];var kh=rec.khunter||{{}};
      if(!kh.sig)return;
      var meta=stockMeta(code);
      var st=khStd(kh),ag=khAgg(kh);
      rows.push({{code:code,name:rec.name||code,board:meta.board,industry:meta.industry,px:rec.px,chg:rec.chg,
        rsi:kh.rsi_now,rsi1:kh.rsi_t1,regime:kh.regime||'—',hits:kh.hits||[],
        stTier:st.tier,stAct:st.act,stCls:st.cls,agTier:ag.tier,agAct:ag.act,agCls:ag.cls}});
    }});
    rows.sort(function(a,b){{return (a.rsi==null?999:a.rsi)-(b.rsi==null?999:b.rsi);}});   // RSI 升序
    var q=(document.getElementById('kh-hits-q').value||'').trim().toLowerCase();
    var ft=document.getElementById('kh-hits-f-tier').value;
    var fb=document.getElementById('kh-hits-f-board').value;
    var filtered=rows.filter(function(r){{
      if(q){{var txt=(r.code+' '+r.name+' '+r.hits.join(' ')+' '+r.industry).toLowerCase();if(txt.indexOf(q)<0)return false;}}
      if(ft&&r.stTier!==ft)return false;
      if(fb&&r.board!==fb)return false;
      return true;
    }});
    var cnt=document.getElementById('kh-hits-count');
    if(cnt)cnt.textContent='命中 '+rows.length+' 只 · 筛选 '+filtered.length+' 只';
    if(!filtered.length){{tb.innerHTML='<tr><td colspan="15" class="sub" style="color:var(--faint)">今日无命中 —— 超卖伏击信号稀疏期 0 只属正常（事件驱动）</td></tr>';return;}}
    var h='';
    filtered.forEach(function(r,i){{
      var strat=r.hits.map(function(s){{return KH_STRAT_CN[s]||s;}}).join('、');
      var chgCls=r.chg>0?'up':(r.chg<0?'down':'');
      var chgDisp=(r.chg==null)?'—':((r.chg>0?'+':'')+r.chg.toFixed(2)+'%');
      var pxDisp=(r.px==null)?'—':r.px.toFixed(2);
      var rsiDisp=(r.rsi==null)?'—':r.rsi.toFixed(1);
      var rsi1Disp=(r.rsi1==null)?'—':r.rsi1.toFixed(1);
      var regDisp=KH_REGIME_CN[r.regime]||r.regime;
      h+='<tr><td style="text-align:center">'+(i+1)+'</td><td><b>'+r.name+'</b><br><span style="color:var(--faint);font-size:11px">'+r.code+'</span></td><td>'+boardCell(r.board)+'</td><td>'+r.industry+'</td>'
        +'<td style="text-align:right">'+pxDisp+'</td><td style="text-align:right" class="'+chgCls+'">'+chgDisp+'</td>'
        +'<td style="text-align:center"><b>'+rsiDisp+'</b></td><td style="text-align:center">'+rsi1Disp+'</td><td style="text-align:center">'+regDisp+'</td>'
        +'<td>'+strat+'</td>'
        +'<td style="text-align:center">'+r.stTier+'</td><td style="text-align:center" class="'+r.stCls+'">'+r.stAct+'</td>'
        +'<td style="text-align:center">'+r.agTier+'</td><td style="text-align:center" class="'+r.agCls+'">'+r.agAct+'</td></tr>';
    }});
    tb.innerHTML=h;
  }}
  ['kh-hits-q','kh-hits-f-tier','kh-hits-f-board'].forEach(function(id){{
    var el=document.getElementById(id);if(!el)return;
    el.addEventListener(id==='kh-hits-q'?'input':'change',renderKhHits);
  }});
  renderKhHits();
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
        var ph='<div class="sub" style="margin-bottom:6px;color:var(--warn)">⏳ 待确认 '+pkeys.length+' 只 —— 上榜后下一收盘确认在榜再入池（隔离当日信号）</div><table class="tbl"><tbody>';
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
    var h='<table class="tbl"><thead><tr><th>标的</th><th>板块</th><th>行业</th><th style="text-align:center">入池日期</th><th style="text-align:center">出池日期</th><th style="text-align:center">已跟踪</th><th style="text-align:right">现价</th><th style="text-align:right">涨跌</th><th style="text-align:center">权重分</th><th style="text-align:center">档位</th><th style="text-align:center">状态</th></tr></thead><tbody>';
    filtered.forEach(function(r){{
      var rec=r.rec;var px=(rec.px!==undefined&&rec.px!==null)?rec.px:null;
      var ageS=r.age+' 天 / 剩 '+(365-r.age)+' 天';
      var exitT=r.exit||'—';
      var status=r.inPool?'<span style="color:var(--up);font-weight:600">在池</span>':'<span style="color:var(--faint)">已掉出池（观察）</span>';
      // 2026-09-05 用户需求：跟踪池统一格式（板块/行业列）
      var ind=(E.details&&E.details[r.code])?(E.details[r.code].industry||'—'):'—';
      h+='<tr><td><b>'+(rec.name||'—')+'</b><br><span style="color:var(--faint);font-size:11px">'+r.code+'</span></td><td>'+boardCell(r.pool)+'</td><td>'+ind+'</td><td style="text-align:center">'+r.entry+'</td><td style="text-align:center">'+exitT+'</td><td style="text-align:center">'+ageS+'</td>'+
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
  /* A5 打板实验五表：与 v9/短线池同标准——表头排序 + 搜索 + 板块/行业筛选（2026-08-28；2026-09-06 名称+代码同格后列索引前移） */
  // 2026-09-22 R-qlch-buyhint-0922：原映射过期（pools 未映射、hit/tier/advice 整体错位 1）→ 列头排序会排错，一并修正
  initTable('a5-zt', {{columns: {{name:0, board:1, ind:2, pct:3, status:4, amt:5, relpos:6, dist:7, pools:8, hit:9, tier:10, advice:11, buy:12}}}});
  // 同上修正：原 13 列只映射 10 个且 sbdate/relpos 起错位
  initTable('a5-wl', {{columns: {{name:0, board:1, ind:2, sbdate:3, pools:4, relpos:5, amt:6, gate:7, chg:8, ret1y:9, rsi:10, vr:11, ma5dev:12, buy:13}}}});
  initTable('a5-av', {{columns: {{name:0, board:1, sbdate:2, gap:3, relpos:4, amt:5, chg:6, ret1y:7, rsi:8, vr:9, ma5dev:10}}}});
  initTable('a5-pos', {{columns: {{name:0, board:1, entrydate:2, entrypx:3, gap:4, stage:5, chg:6, ret1y:7, rsi:8, vr:9, ma5dev:10}}}});
  initTable('a5-cl', {{columns: {{name:0, board:1, entrydate:2, exitdate:3, entrypx:4, exitpx:5, reason:6, netret:7, chg:8, ret1y:9, rsi:10, vr:11}}}});
  ['a5-zt','a5-wl','a5-av','a5-pos','a5-cl'].forEach(function(id){{
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
  /* 2026-09-17（R-v9wire-0917）：列表曾含 'tbl-v9'，v9 表格退役移除后此处首个 id 即 table=null
     → 抛错中止整个 forEach → 后两张在用表格（短线股票池/基金池）的四类联动静默失效。已移除 v9 + 加空值守卫。 */
  ['tbl-short-stk','tbl-short-fund'].forEach(function(id){{
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
    if(!table)return;   /* 表缺失（退役/未渲染）→ 跳过本 id，防 null 抛出中止其余表格接线 */
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
<script>{KXMM_JS}</script>
<script>{INTRADAY_JS}</script>
<script>{QLCH_JS}</script>
</body></html>"""

# --- #10 皮肤层（2026-09-18）：渲染期统一去 emoji ---
# 扁平控制台视觉语言：pictograph 一律清掉；保留 ✓✕（判定符号）、↑↓→ 箭头、①②③ 序号、▲▼ 与 ● 等排版符号。
# 放渲染期而非逐行改源码：实测产物里 90% 的 emoji 来自数据层（pool JSON / 复盘 md / 验证 JSON），
# 逐行改源码改不完、且会被每日链重新写入。
import re as _re_ui
_UI_EMOJI = ("\U0001F100-\U0001F1FF\U0001F300-\U0001FAFF\u2600-\u27BF"
             "\u2B00-\u2BFF\u23E9-\u23FF\uFE0F")
_UI_KEEP = "\u2713\u2714\u2715\u2717\U0001F441"   # 2026-09-23 用户要求：保留「👁 跟踪池」标题的眼睛图标
_ui_re = _re_ui.compile("(?![%s])[%s][ \t\u00a0\u2002\u2003]?" % (_UI_KEEP, _UI_EMOJI))
_ui_n = len(_ui_re.findall(html))
html = _ui_re.sub("", html)
print(f"UI 净化（#10 皮肤层）：清除 {_ui_n} 个 emoji")

# --- #10 第三步（2026-09-22 用户批准）：字号 / 圆角 / 阴影统一（渲染期归一 + 令牌化）---
# 口径：字号 6 档（11/12/13/15/20/40）、圆角只允许 --r(6px)/--r-sm(4px)/50%、
#       阴影只允许 --shadow/--shadow-lg/none/inset 系。产物里任何残留数字值 = 例外，便于 grep 审计。
_FS_SNAP = [("10px", "11px"), ("11.5px", "12px"), ("12.5px", "13px"), ("13.5px", "13px"),
            ("14px", "15px"), ("16px", "15px"), ("17px", "15px")]
_fs_hit = 0
for _o, _t in _FS_SNAP:
    _n = html.count("font-size:" + _o)
    if _n:
        html = html.replace("font-size:" + _o, "font-size:" + _t)
        _fs_hit += _n
_FS_TOK = {"11px": "--fs-xs", "12px": "--fs-sm", "13px": "--fs-md",
           "15px": "--fs-lg", "20px": "--fs-xl", "40px": "--fs-xl2"}
_fs_tok = [0]
def _fs_sub(m):
    v = m.group(1)
    if v in _FS_TOK:
        _fs_tok[0] += 1
        return "font-size:var(%s)" % _FS_TOK[v]
    return m.group(0)
html = _re_ui.sub(r"font-size:\s*([0-9.]+px)", _fs_sub, html)

_R_SNAP = {"2px": "var(--r-sm)", "3px": "var(--r-sm)", "4px": "var(--r-sm)",
           "6px": "var(--r)", "8px": "var(--r)", "10px": "var(--r)", "20px": "var(--r)",
           "0 8px 8px 0": "0 var(--r) var(--r) 0"}
_r_hit = 0
for _o, _t in _R_SNAP.items():
    _n = html.count("border-radius:" + _o)
    if _n:
        html = html.replace("border-radius:" + _o, "border-radius:" + _t)
        _r_hit += _n

_S_SNAP = {"0 8px 26px rgba(0,0,0,.14)": "--shadow-lg",
           "0 10px 24px rgba(0,0,0,.30)": "--shadow-lg",
           "0 12px 48px rgba(0,0,0,.3)": "--shadow-lg",
           "0 2px 8px rgba(0,0,0,.15)": "--shadow-float"}
_s_hit = 0
for _o, _t in _S_SNAP.items():
    _n = html.count("box-shadow:" + _o)
    if _n:
        html = html.replace("box-shadow:" + _o, "box-shadow:var(%s)" % _t)
        _s_hit += _n

print(f"UI 统一（#10 三步）：字号归一 {_fs_hit} 处 / 令牌化 {_fs_tok[0]} 处；"
      f"圆角归一 {_r_hit} 处；阴影归一 {_s_hit} 处")
_rest = _re_ui.findall(r"font-size:\s*[0-9.]+px", html)
if _rest:
    print(f"  ⚠ 仍残留数字字号 {len(_rest)} 处（应仅在白名单外，需人工确认）：{sorted(set(_rest))[:6]}")

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
print(f"  跟踪池清洗: {TRACK_PRUNED['raw']} → {TRACK_PRUNED['keep']} 条"
      f"（剔退休策略 {TRACK_PRUNED['drop']} 条：创业板/科创板不在现行主板限定内）")
print(f"  普适版表: {len(v9_items)} 行（{ {k:len(v) for k,v in v9_tiers.items()} }） | 中长线跟踪池: {track_v9_len} 只")