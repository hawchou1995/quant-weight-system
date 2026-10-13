# -*- coding: utf-8 -*-
"""短线基金轮动与热榜哨兵纸面账本的看板只读渲染器。"""
from __future__ import annotations

import html
import json
from pathlib import Path


def _esc(value) -> str:
    return html.escape(str(value if value not in (None, "") else "—"), quote=True)


def _money(value) -> str:
    try:
        return "{:,.2f}".format(float(value))
    except (TypeError, ValueError):
        return "—"


def _pct(value, signed=False) -> str:
    try:
        n = float(value)
        if signed and n == 0:
            return "0.00%"
        return ("%+.2f%%" if signed else "%.2f%%") % n
    except (TypeError, ValueError):
        return "—"


def _int(value) -> str:
    try:
        return str(int(value or 0))
    except (TypeError, ValueError):
        return "0"


def _read_json(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _read_js_object(path: Path, varname: str) -> dict:
    try:
        text = path.read_text(encoding="utf-8-sig")
        marker = "window.%s" % varname
        start = text.find(marker)
        start = text.find("{", start) if start >= 0 else -1
        if start < 0:
            return {}
        depth = 0
        quoted = False
        escaped = False
        for pos in range(start, len(text)):
            ch = text[pos]
            if quoted:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    quoted = False
                continue
            if ch == '"':
                quoted = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    value = json.loads(text[start:pos + 1])
                    return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        pass
    return {}


def _latest_index_date(base: Path) -> str:
    path = base / "index_000300.csv"
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        dates = [line.split(",", 1)[0].strip() for line in lines[1:] if line[:4].isdigit()]
        return dates[-1] if dates else "—"
    except OSError:
        return "—"


def fund_rotation_card(base: Path | str) -> str:
    """渲染独立短线基金账本；缺文件时仍给显式种子 NAV 和空仓，不输出 null。"""
    base = Path(base)
    state = _read_json(base / "backtest" / "fund_rotation_paper.json")
    pool = _read_json(base / "short_pool.json")
    asof = str(state.get("last_market_asof") or _latest_index_date(base))
    pool_asof = str(pool.get("as_of") or "—")
    fund_asof = str(pool.get("fund_as_of") or "—")
    initial = state.get("initial_cash", 100000.0)
    nav = state.get("nav", initial)
    cash = state.get("cash", initial)
    market_value = state.get("market_value", 0.0)
    ret = state.get("cum_return_pct", 0.0)
    status = str(state.get("status") or "WAITING_FOR_SIGNAL")
    status_names = {
        "ACTIVE": "持仓中",
        "WAITING_FOR_NEXT_NAV": "待净值成交",
        "SIGNAL_SOURCE_STALE": "候选数据陈旧 · 不生成新交易",
        "FLAT_NO_CANDIDATE": "空仓 / 无候选",
        "WAITING_FOR_SIGNAL": "未成交 / 空仓",
        "SIGNAL_DATE_MISSING": "信号日期缺失 · 空仓",
    }
    status_label = status_names.get(status, status)
    note = str(state.get("status_note") or "未初始化；按种子 NAV 100000.00 起记，当前空仓，收益 0.00%。")
    positions = state.get("positions") or {}
    fills = list(state.get("fills") or [])
    pending = state.get("pending_orders") or {}
    n_fills = state.get("n_fills", len(fills))
    n_closed = state.get("n_completed_trades", sum(1 for row in fills if row.get("side") == "sell"))

    position_rows = []
    for code, pos in sorted(positions.items()):
        units = float(pos.get("units") or 0.0)
        latest = float(pos.get("last_nav") or 0.0)
        value = units * latest
        basis = float(pos.get("cost_basis") or 0.0)
        position_rows.append(
            '<tr><td>{code}</td><td>{name}</td><td>{entry}</td><td>{units}</td>'
            '<td>{nav}</td><td>{value}</td><td>{basis}</td></tr>'.format(
                code=_esc(code), name=_esc(pos.get("name") or code),
                entry=_esc(pos.get("entry_date")), units=_money(units),
                nav=_money(latest), value=_money(value), basis=_money(basis)))
    if not position_rows:
        position_rows.append('<tr><td colspan="7" style="color:var(--faint)">空仓 · 暂无持仓</td></tr>')

    fill_rows = []
    for fill in fills[-30:][::-1]:
        side = "买入" if fill.get("side") == "buy" else "卖出"
        pnl = _money(fill.get("realized_pnl")) if fill.get("side") == "sell" else "—"
        fill_rows.append(
            '<tr><td>{date}</td><td>{side}</td><td>{code}</td><td>{name}</td>'
            '<td>{nav}</td><td>{units}</td><td>{fee}</td><td>{pnl}</td></tr>'.format(
                date=_esc(fill.get("date")), side=side, code=_esc(fill.get("code")),
                name=_esc(fill.get("name") or fill.get("code")), nav=_money(fill.get("nav")),
                units=_money(fill.get("units")), fee=_money(fill.get("fee")), pnl=pnl))
    if not fill_rows:
        fill_rows.append('<tr><td colspan="8" style="color:var(--faint)">尚无成交 · 模拟 NAV 保持种子值</td></tr>')

    return ''.join([
        '<div class="card" id="fund-rotation-paper-card">',
        '<h2>📈 模拟净值 · 基金轮动 <span class="badge badge-auto">独立纸面账户</span></h2>',
        '<div class="sub">候选 = 短线生产 <b>2000 基金池</b>；牛市分数≥30 Top10 / 熊市≥45 Top3；',
        '同基份额去重并优先 C 类由 <code>build_short_pool.py</code> 执行。本账本不重排候选。',
        '当前候选目标等权；集合变化按单位差额轮动；以信号净值日后首个可得净值成交；缺失净值保留待成交、',
        '不使用信号日净值；C 类 5bp/边。与中长线 FB3-H20 <code>fund_paper.json</code> 隔离。</div>',
        '<div class="tbl-wrap"><table class="tbl" id="tbl-fund-rotation-paper">',
        '<thead><tr><th>as-of</th><th>候选 as-of</th><th>基金净值 as-of</th><th>状态</th>',
        '<th>模拟 NAV</th><th>累计收益</th><th>持仓市值</th><th>现金</th><th>持仓数</th>',
        '<th>成交数</th><th>平仓数</th><th>待成交</th></tr></thead><tbody><tr>',
        ('<td>{asof}</td><td>{pool_asof}</td><td>{fund_asof}</td><td>{status}</td>'
         '<td><b>{nav}</b></td><td>{ret}</td><td>{market_value}</td><td>{cash}</td>'
         '<td>{npos}</td><td>{fills}</td><td>{closed}</td><td>{pending}</td>').format(
            asof=_esc(asof), pool_asof=_esc(pool_asof), fund_asof=_esc(fund_asof),
            status=_esc(status_label), nav=_money(nav), ret=_pct(ret, True),
            market_value=_money(market_value), cash=_money(cash), npos=_int(len(positions)),
            fills=_int(n_fills), closed=_int(n_closed), pending=_int(len(pending))),
        '</tr></tbody></table></div>',
        '<div class="sub" style="color:var(--faint)">种子 NAV {seed} · 样本起点 {seed_date} · 成本 {fee} / 边 · {note}</div>'.format(
            seed=_money(initial), seed_date=_esc(state.get("seed_date") or asof),
            fee=_pct(float(state.get("fee_per_side", 0.0005)) * 100), note=_esc(note)),
        '<div class="etf-sec" style="margin-top:12px">持仓明细</div>',
        '<div class="tbl-wrap"><table class="tbl" id="tbl-fund-rotation-positions">',
        '<thead><tr><th>代码</th><th>名称</th><th>建仓净值日</th><th>份额</th>',
        '<th>最新单位净值</th><th>市值</th><th>含买入成本的成本基数</th></tr></thead><tbody>',
        ''.join(position_rows), '</tbody></table></div>',
        '<div class="etf-sec" style="margin-top:12px">最近成交（最多 30 笔）</div>',
        '<div class="tbl-wrap"><table class="tbl" id="tbl-fund-rotation-fills">',
        '<thead><tr><th>净值日</th><th>方向</th><th>代码</th><th>名称</th><th>单位净值</th>',
        '<th>份额</th><th>费用</th><th>已实现盈亏</th></tr></thead><tbody>',
        ''.join(fill_rows), '</tbody></table></div></div>',
    ])


def sentinel_paper_card(base: Path | str, track_rel: str = "sentinel_track.js",
                        state_rel: str = "backtest/sentinel_state.json",
                        paper_rel: str = "backtest/sentinel_return_paper.json") -> str:
    """收益账本与原始否决状态分栏渲染；读取，不回写任何状态。"""
    base = Path(base)
    paper = _read_json(base / paper_rel)
    track = _read_js_object(base / track_rel, "SENTINEL_TRACK")
    veto_state = _read_json(base / state_rel)
    pool = _read_js_object(base / "sentinel_pool.js", "SENTINEL_POOL")
    portfolios = paper.get("portfolios") or {}
    asof = str(paper.get("as_of") or _latest_index_date(base))
    pool_asof = str(pool.get("as_of") or "—")
    signal_status = "触发" if pool.get("triggered") else "未触发"
    default = {"nav": 100000.0, "cum_net_return_pct": 0.0, "max_drawdown_pct": 0.0,
               "cash": 100000.0, "n_fills": 0, "n_completed_trades": 0,
               "positions": {}, "fills": [], "closed_trades": []}
    cost_labels = ["0.20%", "1.15%"]
    metric_rows = []
    position_rows = []
    fill_rows = []
    closed_rows = []
    any_position = False
    for label in cost_labels:
        port = portfolios.get(label) or dict(default)
        pos = port.get("positions") or {}
        any_position = any_position or bool(pos)
        metric_rows.append(
            '<tr><td>{cost} 往返</td><td>{nav}</td><td>{ret}</td><td>{mdd}</td>'
            '<td>{cash}</td><td>{positions}</td><td>{fills}</td><td>{closed}</td></tr>'.format(
                cost=_esc(label), nav=_money(port.get("nav", 100000.0)),
                ret=_pct(port.get("cum_net_return_pct", 0.0), True),
                mdd=_pct(port.get("max_drawdown_pct", 0.0), True),
                cash=_money(port.get("cash", 100000.0)), positions=_int(len(pos)),
                fills=_int(port.get("n_fills", len(port.get("fills") or []))),
                closed=_int(port.get("n_completed_trades", len(port.get("closed_trades") or [])))))
        for code, item in sorted(pos.items()):
            units = float(item.get("units") or 0.0)
            mark = float(item.get("last_close") or 0.0)
            value = units * mark
            entry_value = float(item.get("entry_value") or 0.0)
            entry_price = float(item.get("entry_price") or 0.0)
            position_rows.append(
                '<tr><td>{cost}</td><td>{code}</td><td>{name}</td><td>{sig}</td>'
                '<td>{entry}</td><td>{entrypx}</td><td>{mark}</td><td>{units}</td>'
                '<td>{value}</td><td>{rtn}</td><td>{exit}</td><td>{reason}</td></tr>'.format(
                    cost=_esc(label), code=_esc(code), name=_esc(item.get("name") or code),
                    sig=_esc(item.get("signal_date")), entry=_esc(item.get("entry_date")),
                    entrypx=_money(entry_price), mark=_money(mark), units=_money(units),
                    value=_money(value), rtn=_pct((mark / entry_price - 1.0) * 100.0 if entry_price else 0.0, True),
                    exit=_esc(item.get("exit_date") or item.get("exit_status") or "持仓中"),
                    reason=_esc(item.get("exit_reason") or "—")))
        for fill in (port.get("fills") or [])[-25:][::-1]:
            side = "买入" if fill.get("side") == "buy" else "卖出"
            fill_rows.append(
                '<tr><td>{cost}</td><td>{date}</td><td>{side}</td><td>{code}</td>'
                '<td>{name}</td><td>{price}</td><td>{units}</td><td>{fee}</td></tr>'.format(
                    cost=_esc(label), date=_esc(fill.get("date")), side=side,
                    code=_esc(fill.get("code")), name=_esc(fill.get("name") or fill.get("code")),
                    price=_money(fill.get("price")), units=_money(fill.get("units")), fee=_money(fill.get("fee"))))
        for trade in (port.get("closed_trades") or [])[-25:][::-1]:
            closed_rows.append(
                '<tr><td>{cost}</td><td>{code}</td><td>{name}</td><td>{entry}</td><td>{exit}</td>'
                '<td>{epx}</td><td>{xpx}</td><td>{gross}</td><td>{fee}</td><td>{net}</td>'
                '<td>{ret}</td><td>{reason}</td></tr>'.format(
                    cost=_esc(label), code=_esc(trade.get("code")), name=_esc(trade.get("name")),
                    entry=_esc(trade.get("entry_date")), exit=_esc(trade.get("exit_date")),
                    epx=_money(trade.get("entry_price")), xpx=_money(trade.get("exit_price")),
                    gross=_money(trade.get("gross_pnl")), fee=_money(trade.get("fee")),
                    net=_money(trade.get("net_pnl")), ret=_pct(trade.get("return_net_pct"), True),
                    reason=_esc(trade.get("exit_reason"))))
    if not position_rows:
        position_rows.append('<tr><td colspan="12" style="color:var(--faint)">未触发 / 空仓</td></tr>')
    if not fill_rows:
        fill_rows.append('<tr><td colspan="8" style="color:var(--faint)">未触发 / 空仓 · 暂无成交</td></tr>')
    if not closed_rows:
        closed_rows.append('<tr><td colspan="12" style="color:var(--faint)">暂无已平仓交易</td></tr>')

    veto = track.get("veto_state") or veto_state.get("veto_state") or {}
    enabled = bool(track.get("trading_enabled", veto_state.get("trading_enabled", False)))
    veto_rows = [
        ("trading_enabled", "true" if enabled else "false",
         track.get("trading_enabled_note") or veto_state.get("trading_enabled_note") or "保持只可否决"),
        ("否决状态", veto_state.get("status") or track.get("status") or "未记录",
         "纸面收益账本不改变此状态"),
        ("V1 / V2 / V3", "%s / %s / %s" % tuple(
            "触发" if veto.get(key) is True else ("未触发" if veto.get(key) is False else "未记录")
            for key in ("V1", "V2", "V3")), "只读否决位；任一触发须人工复核"),
        ("冻结版本 / 起点", paper.get("rule_version") or "R-jiandi-top30-0924/v1",
         "预注册 shadow_start=%s" % (veto_state.get("shadow_start") or track.get("shadow_start") or "2026-09-24")),
    ]
    veto_html = ''.join('<tr><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
        _esc(key), _esc(value), _esc(note)) for key, value, note in veto_rows)
    note = paper.get("status_note") or "未触发/空仓；种子 NAV 100000.00，累计净收益 0.00%。"
    empty_label = "当前持仓中" if any_position else "未触发 / 空仓"

    return ''.join([
        '<div class="card" id="card-sentinel-paper">',
        '<h2>📈 纸面收益 · 热榜哨兵 <span class="badge badge-auto">独立账本 · 不下单</span></h2>',
        '<div class="sub">冻结版本 <b>R-jiandi-top30-0924/v1</b> · 沪深主板；K≥2 且全市场共振 θ≥30；',
        'T 收盘确认 / T+1 开盘成交；K=5 槽等权；RSI(14) 域 55/65/65；持有上限 5 日。',
        '下表分别按预注册 <b>0.20%</b> / <b>1.15%</b> 往返成本记账；成本在平仓时按入场名义金额扣除。</div>',
        '<div class="tbl-wrap"><table class="tbl" id="tbl-sentinel-return">',
        '<thead><tr><th>成本口径</th><th>模拟 NAV</th><th>累计净收益</th><th>最大回撤</th>',
        '<th>现金</th><th>持仓数</th><th>成交数</th><th>已平仓数</th></tr></thead><tbody>',
        ''.join(metric_rows), '</tbody></table></div>',
        '<div class="sub" style="color:var(--faint)">as-of {asof} · 样本起点 {seed_date} · 当日信号 {signal}（池 as-of {pool_asof}）· {empty} · {note}</div>'.format(
            asof=_esc(asof), seed_date=_esc(paper.get("seed_date") or asof),
            signal=signal_status, pool_asof=_esc(pool_asof), empty=empty_label, note=_esc(note)),
        '<div class="etf-sec" style="margin-top:12px">当前持仓</div>',
        '<div class="tbl-wrap"><table class="tbl" id="tbl-sentinel-return-positions">',
        '<thead><tr><th>成本</th><th>代码</th><th>名称</th><th>信号日</th><th>入场日</th>',
        '<th>入场价</th><th>最新收盘</th><th>份额</th><th>市值</th><th>毛收益</th>',
        '<th>计划退出</th><th>退出原因</th></tr></thead><tbody>',
        ''.join(position_rows), '</tbody></table></div>',
        '<div class="etf-sec" style="margin-top:12px">最近成交</div>',
        '<div class="tbl-wrap"><table class="tbl" id="tbl-sentinel-return-fills">',
        '<thead><tr><th>成本</th><th>日期</th><th>方向</th><th>代码</th><th>名称</th>',
        '<th>成交价</th><th>份额</th><th>费用</th></tr></thead><tbody>',
        ''.join(fill_rows), '</tbody></table></div>',
        '<div class="etf-sec" style="margin-top:12px">已平仓明细</div>',
        '<div class="tbl-wrap"><table class="tbl" id="tbl-sentinel-return-closed">',
        '<thead><tr><th>成本</th><th>代码</th><th>名称</th><th>入场日</th><th>退出日</th>',
        '<th>入场价</th><th>退出价</th><th>毛盈亏</th><th>往返费用</th><th>净盈亏</th>',
        '<th>净收益</th><th>退出原因</th></tr></thead><tbody>',
        ''.join(closed_rows), '</tbody></table></div>',
        '<div class="etf-sec" style="margin-top:12px">只读否决状态（与收益账本隔离）</div>',
        '<div class="tbl-wrap"><table class="tbl" id="tbl-sentinel-veto-readonly">',
        '<thead><tr><th>项目</th><th>当前值</th><th>说明</th></tr></thead><tbody>',
        veto_html, '</tbody></table></div>',
        '<div class="sub" style="color:var(--faint)">收益账本：<code>{paper}</code> · '
        '只读否决来源：<code>{state}</code> / <code>{track}</code>；账户种子 NAV 100000.00。</div>'.format(
            paper=_esc(paper_rel), state=_esc(state_rel), track=_esc(track_rel)),
        '</div>',
    ])
