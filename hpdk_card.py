# -*- coding: utf-8 -*-
"""hpdk_card.py — 「缩量超跌」看板卡片与盘中 payload（2026-09-27 新增，R-hpdk-dash-0927）
原名「横盘低开·两日」，2026-09-28 更名（预注册勘误 E-17）；内部标识 st-hpdk / 产物名 hpdk_* 不变。

为什么单独成模块：卡片 HTML 很长，塞进 build_dual_system.py 会放大 diff 噪声。
本模块只读该策略自己的产物，**不读任何别的策略文件**（隔离约束，见 _verify_hpdk_live.py）：
  · backtest/hpdk_candidates.json   ← hpdk_candidates.py（信号逻辑 100% 复用冻结脚本 oos_run.py，
                                       并有 A11「逐位对拍 ≥25 个交易日」自证）
  · backtest/hpdk_oos_view.json     ← 同上，冻结 OOS 台账的只读投影

三个入口都接受 BASE（仓库根路径），由 build_dual_system.py 注入。
"""
import json
import math

RENDER_N = 600        # 服务端渲染行数上限（盘中重算用内嵌全量池，不受此限制）
LEVEL3 = 3.0          # 每股净资产门槛（与冻结规格一致，仅用于文案）

# ── 「数据截止」徽章（R-asof-ui-0928）───────────────────────────────────────────
# 必须与 build_dual_system.asof_badge 输出**逐字节一致**（用户要求全站选股池统一）：
#   位置 = h2 内紧跟标题；样式 = class="view-badge auto"；文本 = `数据截至 DATE [HH:MM] · 口径`。
# 两处各留一份定义：本模块是被 build_dual_system 在文件后段 import 的，反向导入会成环。
def asof_badge(date, tag="收盘", ts="15:00", note="收盘数据"):
    d = str(date) if date not in (None, "") else "—"
    t = (" " + str(ts)) if ts else ""
    return ('<span class="view-badge auto" title="%s">数据截至 %s%s · %s</span>'
            % (note, d, t, tag))


def _read(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}
ST_BADGE = ('<span class="badge" style="background:rgba(220,38,38,.18);color:var(--down);'
            'margin-left:4px" title="现行名称含 ST/退：预注册勘误 E-19 后，冻结判据只做**点时 ST 代理**、'
            '关掉了现行名称过滤 ⇒ 近期才被 ST 的票会漏进来。此徽章只做标记，不改选股与排名">ST</span>')


def is_st_name(name):
    n = (name or "").upper()
    return ("ST" in n) or ("退" in (name or ""))


def mark_st_rows(html, names):
    """把行内 `<b>名称</b>` 后补一个 ST 徽章（显示层标记；不改选股、不改排名）。

    背景（2026-09-29 用户质疑「选股池混进了 *ST」）：E-19 关掉了「按现行名称含 ST/退」的剔除，
    改为只用点时代理 STP = 250 日最大绝对日收益 ≤5.6%；该代理对「近期才戴帽」的票不敏感
    （窗口内仍留有戴帽前的大涨跌幅）⇒ 现行 ST 会漏进名单。策略层改判据须走勘误，先做到「看得见」。
    """
    for nm in names:
        if not nm or not is_st_name(nm):
            continue
        old = "<b>%s</b>" % nm
        if old in html:
            html = html.replace(old, "<b>%s</b>%s" % (nm, ST_BADGE), 1)
    return html


# ── 📌 买日批次跟踪表（R-hpdk-cohort-0929，2026-09-29 从主卡移入跟踪池卡）─────────────
# 用户反馈「跟踪池还是没有昨日 top4」根因是**放错卡**：本表原先挂在「缩量超跌主卡」，
# 而用户的查看位在「👁 跟踪池 · 缩量超跌」⇒ 抽成模块级函数并在跟踪池卡内调用。
# 口径：以**买日**为主键、覆盖全部命中历史买日（含影子账本窗口外那批）；买入价=买日开盘，
# 止盈线=×1.02，了结日=买日之后第一个交易日；了结判定与冻结规则逐条一致。
def cohort_block(BASE):
    co = _read(BASE / "backtest" / "hpdk_cohorts.json")
    if not (co and (co.get("batches") or [])):
        return ""
    rows = []
    for b in co["batches"]:
        ex = b.get("exit_date") or "未到"
        for x in (b.get("rows") or []):
            ret = x.get("ret_pct")
            col = "" if ret is None else ("var(--up)" if ret > 0 else "var(--down)")
            _badge = ("<span class=\"badge badge-auto\">已了结</span>" if x.get("status") == "已了结"
                      else ("<span class=\"badge badge-auto\">持有中</span>"
                            if str(x.get("status") or "").startswith("持有中")
                            else "<span style=\"color:var(--faint)\">%s</span>" % (x.get("status") or "—")))
            rows.append(
                '<tr data-code="%s" data-search="%s">'
                '<td data-key="bd" style="font-variant-numeric:tabular-nums">%s</td>'
                '<td data-key="xd" style="font-variant-numeric:tabular-nums">%s</td>'
                '<td data-key="name"><b>%s</b><br><span style="color:var(--sub);font-size:var(--fs-xs);'
                'font-variant-numeric:tabular-nums">%s</span></td>'
                '<td data-key="ind" style="color:var(--sub)">%s</td>'
                '<td data-key="entry" data-v="%s" style="text-align:right;'
                'font-variant-numeric:tabular-nums">%s</td>'
                '<td data-key="tp" data-v="%s" style="text-align:right;color:var(--up);'
                'font-variant-numeric:tabular-nums">%s</td>'
                '<td data-key="state" style="text-align:center">%s</td>'
                '<td data-key="exit" data-v="%s" style="text-align:right;'
                'font-variant-numeric:tabular-nums">%s</td>'
                '<td data-key="ret" data-v="%s" style="text-align:right;color:%s;'
                'font-variant-numeric:tabular-nums">%s</td></tr>'
                % (x.get("sym") or x.get("code"),
                   " ".join([str(x.get("name") or ""), str(x.get("code") or ""), str(x.get("ind") or "")]),
                   b.get("buy_date"), ex, x.get("name") or "", x.get("code") or "",
                   x.get("ind") or "—",
                   x.get("entry") or "", ("%.3f" % x["entry"]) if x.get("entry") else "—",
                   x.get("tp") or "", ("%.4f" % x["tp"]) if x.get("tp") else "—",
                   _badge,
                   x.get("exit") or "", ("%.3f" % x["exit"]) if x.get("exit") else "—",
                   ret if ret is not None else "", col, ("%+.2f%%" % ret) if ret is not None else "—"))
    return (
        '<div class="sub" style="margin-top:12px"><b>📌 买日批次跟踪'
        f'（模型买入名单 · 逐笔到了结 · 覆盖全部命中历史买日）</b>'
        '<span style="color:var(--sub)"> —— 以<b>买日</b>为主键；'
        f'止盈 = 买入价×{(1 + (co.get("tp") or 0.02)):.2f}；了结日 = 买日之后第一个交易日；'
        '了结判定：了结日 open≥止盈按 open / 盘中 high≥止盈按止盈价 / 否则尾盘；'
        f'净收益含往返成本 {co.get("cost_roundtrip_bp", 6.92)}bp。'
        f'批次 {co.get("n_batches")} · 已了结 {co.get("n_settled")} / 持有中 {co.get("n_holding")}'
        '<br><span style="color:var(--warn)">⚠ 这是<b>模型买入名单</b>（F 前 10）；'
        '你自己的实际成交请在下方「💼 实盘登记」里逐笔登记。</span></span></div>'
        '<div class="tbl-wrap"><table class="tbl" id="tbl-hpdk-cohort" style="width:100%;font-size:12px">'
        '<thead><tr><th data-key="bd">买日</th><th data-key="xd">了结日</th>'
        '<th data-key="name">标的</th><th data-key="ind">行业</th>'
        '<th data-key="entry" style="text-align:right">买入价</th>'
        '<th data-key="tp" style="text-align:right">止盈价 +2%</th>'
        '<th data-key="state" style="text-align:center">状态</th>'
        '<th data-key="exit" style="text-align:right">卖出价</th>'
        '<th data-key="ret" style="text-align:right">净收益</th></tr></thead>'
        '<tbody>' + mark_st_rows("".join(rows),
                                [x.get("name") for b in co["batches"] for x in (b.get("rows") or [])])
        + '</tbody></table></div>')


def _zs(v):
    n = len(v)
    if n == 0:
        return []
    mu = sum(v) / n
    sd = (sum((x - mu) ** 2 for x in v) / n) ** 0.5
    return [(x - mu) / sd if sd > 0 else 0.0 for x in v]


def rows_with_proxy(d):
    """资格池行 + **盘前代理分**，按代理分降序。

    ⚠ 代理分 = 在**全体资格池**内做横截面 z 标准化，**不是冻结口径**。冻结口径是在
    「次日开盘低开 −3%~−1% 的子集」内标准化，而该子集要等 T+1 开盘才知道 ——
    故代理分只作盘前准备用；正式前 10 由浏览器端在 09:25 后用真实今开重算。
    """
    rs = [r for r in (d.get("rows") or [])
          if r.get("amt20") and r.get("volbr") and r.get("ret20") is not None]
    za = _zs([-math.log(max(r["amt20"], 1e-9)) for r in rs])
    zv = _zs([-math.log(max(r["volbr"], 1e-9)) for r in rs])
    zr = _zs([-r["ret20"] for r in rs])
    for i, r in enumerate(rs):
        r["proxy"] = za[i] + zv[i] + zr[i]
    rs.sort(key=lambda r: -r["proxy"])
    for i, r in enumerate(rs):
        r["proxy_rank"] = i + 1
    return rs


def _tier(b):
    return {"主板": "main", "创业板": "gem", "科创板": "star"}.get(b, "other")


def hpdk_payload(BASE):
    """构建期把「盘中买点判定」需要的资格池内嵌成 window.HPDK（与 qlch 同范式 · ADR-0009）。

    为什么在浏览器端判定：判定只读行情、只改 DOM —— **零落盘**（不写 json / 不碰账本 / 不发请求）。
    """
    d = _read(BASE / "backtest" / "hpdk_candidates.json")
    if not d:
        return None
    cols = ["code", "name", "ind", "board", "close", "amt20", "volbr", "ret20"]
    rows = [[r.get("code", ""), r.get("name", ""), r.get("ind", ""), r.get("board", ""),
             r.get("close"), r.get("amt20"), r.get("volbr"), r.get("ret20")]
            for r in (d.get("rows") or [])]
    cap = d.get("capacity") or {}
    par = d.get("params") or {}
    gb = d.get("gap_band") or [-0.03, -0.01]
    return dict(as_of=d.get("as_of"), buy_date=d.get("buy_date"), exit_date=d.get("exit_date"),
                calendar_fallback=d.get("calendar_fallback"),
                gap_lo=gb[0], gap_hi=gb[1], tp=par.get("TP", 0.02), k=par.get("K", 10),
                kslot=cap.get("kslot"), capital=cap.get("capital"),
                minamt=par.get("MINAMT"), minpx=par.get("MINPX"),
                frozen_sha256=d.get("frozen_sha256"), a11=d.get("a11_check") or {},
                cols=cols, rows=rows)


def hpdk_card(BASE):
    """子视图主卡。形态对齐 qlch_card()：系统头 → 口径 → 明日买点表 → 当日流程。"""
    d = _read(BASE / "backtest" / "hpdk_candidates.json")
    L = ['<div class="card" id="hpdk-card">']
    if not d:
        L.append('<h2>🎯 缩量超跌 <span class="view-badge auto">产物未生成</span></h2>'
                 '<div class="sub" style="color:var(--faint)">跑 <code>'
                 'backtest/hengpan_fangliang_dikai_0925/hpdk_candidates.py</code> 写入 '
                 '<code>backtest/hpdk_candidates.json</code> 后本卡自动出现。</div></div>')
        return "".join(L)
    cap = d.get("capacity") or {}
    par = d.get("params") or {}
    a11 = d.get("a11_check") or {}
    ssha = (d.get("frozen_sha256") or "—")[:16]
    tp = 1 + (par.get("TP", 0.02) or 0)
    kslot = par.get("KSLOT", 20)
    capital = cap.get("capital", 0) or 0
    k_ops = cap.get("kslot") or 0
    h = _read(BASE / "backtest" / "hpdk_hits.json")        # 今日命中（收盘链全池复算 · R-hpdk-hits-0928）
    L.append(f'<h2>🎯 缩量超跌 {asof_badge(d.get("as_of"))}</h2>')
    # R-hpdk-top-0929：卡片**最上方**的「今日买入清单」容器 —— 盘中由 HPDK_JS 用全池报价填充
    # （用户 2026-09-29 要求：要图3那种看清单的方式，且要置顶；同屏只留一个买入口径）。
    L.append('<div id="hpdk-live-top" class="sub" style="margin:8px 0 2px"></div>')
    L.append(
        '<div class="sub"><b>策略定义（与冻结预注册逐条一致；本页不复述自定义口径）</b>：T 收盘判定 → '
        f'资格 = 上市有效交易日 ≥{par.get("LISTED", 250)} ＋ 收盘 ≥{par.get("MINPX", 3.0):.2f} 元 ＋ '
        f'20 日均额 ≥{(par.get("MINAMT", 2e7) or 0) / 1e4:.0f} 万 ＋ 非 ST/*ST（<b>双轨</b>：历史日 = 点时代理 STP〔E-19〕；<b>live frontier = 现行名称</b>〔E-20 · 你批准的 A 案〕）＋ '
        '每股净资产 ≥3 元（报告期 +4 个月后方可用）'
        '＋ **只买主板**（sh600/601/603/605 ＋ sz000/001/002/003；剔创业板 300/301/302、科创板 688）'
        '｜ <b>次日开盘跳空 gap = 今开/昨收 − 1 ∈ [−3%, −1%]</b>（低开至少 1%、不超过 3%）'
        f'｜ 复合分 F = z(−ln 成交额20) + z(−ln 量比) + z(−20 日涨幅)，取前 {par.get("K", 10)} 只'
        f'｜ 仓位 = min(前一日净值/{kslot}, 可用现金)，最多同持 {kslot} 只'
        f'｜ 出场 = 止盈 +{(par.get("TP", 0.02) or 0) * 100:.0f}%（<b>基准 = 实际成交价</b>，即买入日开盘价 ×1.02）／ 未达标 T+2 尾盘（<b>不止损</b>）'
        '<br><span style="color:var(--warn)">⚠ <b>原名为「横盘低开·两日」（历史遗留）</b>：样本内实测「横盘」无用、'
        '「放量」方向相反（要缩量）⇒ <b>冻结规格里既无横盘条件也无放量条件</b>，'
        '真实因子只有「缩量 ＋ 低成交额 ＋ 超跌」的复合分；'
        '<b>2026-09-28 起显示名改为「缩量超跌」</b>（只改显示层，内部标识与产物名不变，见预注册勘误 E-17）。</span>'
        f'<br>冻结脚本 <code>oos_run.py</code> SHA256 <code>{ssha}…</code> ｜ 候选生成器与其逐位对拍 '
        f'<b>{a11.get("days_bitwise_equal", 0)}/{a11.get("days_compared", 0)} 个交易日完全相等</b></div>')
    L.append(
        '<div class="sub" style="margin-top:8px"><b>盘中判定（浏览器端 · 零落盘）</b>：'
        '09:15–09:25 集合竞价只灰标<b>竞价预判</b>，<b>不剔除任何标的</b>；'
        '<b>09:25 起用真实今开判定</b> —— 命中（今开/昨收−1 ∈ [−3%, −1%] ＋ 可交易 ＋ 准入过滤件达标）者'
        '进入当日候选，其余 <b>自动从清单剔除</b>（不是置灰）。'
        '<b>该实时判定只是盘中提示；当日命中的权威记录见下方「今日命中（收盘链全池复算）」</b>'
        '（前端只在渲染的 600 行内做 F 排名 → 会少报；2026-09-28 实测全池 146 只、前端仅 3 只，'
        'F 第 2 名浙江自然被第 601 行上限截掉）。'
        f'<br><b>操作口径（与回测指标带分列，不混写）</b>：本金 <b>{capital / 1e4:.0f} 万</b> / '
        f'KSLOT <b>{k_ops or "—"}</b> → 单票分配 min(本金/KSLOT, 该股 ADV×1%) = '
        f'<b>{capital / max(1, k_ops) / 1e4:.1f} 万</b>；<b>硬约束：单票 ≤ 该股 20 日均额×1%</b> '
        '⇒ 本配置账户上限约 <b>101 万元</b>。'
        '<br>买入价 = <b>次日开盘价</b>（集合竞价单一价格撮合，须 09:25 前挂单，见下方流程）；'
        f'止盈价 = <b>买入价 × {tp:.2f}</b>；未达止盈则 <b>{d.get("exit_date")} 尾盘</b>卖出。</div>')
    rows = rows_with_proxy(d)
    shown = rows[:RENDER_N]
    L.append('<div id="hpdk-pool-note">')    # 开 2026-09-29：池子说明段
    L.append(
        f'<div class="sub" style="margin-top:10px"><b>明日买点准备清单</b>（信号日 <b>{d.get("as_of")}</b> 收盘 · '
        f'买日 <b>{d.get("buy_date")}</b> · 了结日 <b>{d.get("exit_date")}</b>）· '
        f'资格池 <b>{len(rows)}</b> 只 → 下表按<b>盘前代理分</b>降序展示前 <b>{len(shown)}</b> 只'
        '<br><span style="color:var(--warn)">⚠ <b>这不是买入名单</b>：真正的前 '
        f'{par.get("K", 10)} 名要在「次日开盘低开 −3%~−1% 的子集」内重算复合分，而该子集 09:25 才知道；'
        '代理分是在<b>全体资格池</b>内标准化的，与正式排名不同。搜索 / 排序 / 板块筛选由板内通用脚本接管；'
        '09:25 后本表按真实今开自动剔除并置顶命中者。'
        '<b>全卡只有一个买入口径</b>：卡片最上方的「今日买入清单」（全池判定 · 09:25 首算即冻结）——'
        '本表是它的<b>盘前准备视图</b>。</span></div>')
    L.append('</div>')                       # 关：#hpdk-pool-note（池子说明段，随池子一起被搬进折叠区）
    if h and h.get("signal_date") and h.get("n_hits") is not None:
        _top_k = h.get("k") or 0
        L.append(
            '<div class="sub" style="margin-top:12px;border-left:3px solid var(--down);'
            'background:rgba(5,150,105,.08);padding:8px 10px;line-height:1.75">'
            f'<b>✅ 今日命中（收盘链全池复算 · 可回看 · 跨设备一致）</b>：买日 <b>{h.get("date")}</b> · '
            f'信号日 <b>{h.get("signal_date")}</b> · 资格池 <b>{h.get("n_pool")}</b> → '
            f'命中 <b>{h.get("n_hits")}</b> 只（开盘跳空带内 ∩ 可交易 ∩ 可算分）'
            f'｜ F 前 <b>{_top_k}</b> 只 = 当日买入候选'
            f'<br><span style="color:var(--faint)">{h.get("rule", "")}'
            '（原设计只有浏览器端 600 行内排名，会少报且跨日即焚 —— 本表为全池复算的权威记录）'
            '</span></div>')
        _ic = h.get("ind_counts") or {}
        _dedn = len(h.get("top_dedup_ind") or [])
        # 样式对齐站点既有表（2026-09-29 用户反馈「面目全非」）：每个 td 带 data-key/data-v
        # （板内通用排序/搜索接管）、标的用 <b>名</b><br><span>码</span>、数值 tabular-nums、
        # 状态用 badge、候选行加 hpdk-top 高亮 —— 与「明日买点准备清单」表同一视觉语言。
        _hr = "".join(
            '<tr data-code="%s" data-search="%s"%s>'
            '<td data-key="rank" data-v="%s" style="text-align:center;'
            'font-variant-numeric:tabular-nums">%s</td>'
            '<td data-key="name"><b>%s</b><br><span style="color:var(--sub);font-size:var(--fs-xs);'
            'font-variant-numeric:tabular-nums">%s</span></td>'
            '<td data-key="ind" style="color:var(--sub)">%s%s</td>'
            '<td data-key="gap" data-v="%s" style="text-align:right;color:var(--down);'
            'font-variant-numeric:tabular-nums">%+.2f%%</td>'
            '<td data-key="F" data-v="%s" style="text-align:right;'
            'font-variant-numeric:tabular-nums">%+.3f</td>'
            '<td data-key="cand" style="text-align:center">%s</td></tr>'
            % (x.get("sym") or x.get("code"), " ".join(
                   [str(x.get("name") or ""), str(x.get("code") or ""), str(x.get("ind") or "")]),
               ' class="hpdk-top"' if x["rank"] <= _top_k else "",
               x["rank"], x["rank"], x["name"], x["code"], x.get("ind") or "—",
               (' <span class="badge badge-auto">同行业第 %d 只</span>' % x["ind_seq"])
               if (x.get("ind_seq") or 1) > 1 else "",
               x["gap_pct"], x["gap_pct"], x["F"], x["F"],
               '<span class="badge badge-auto">✅ 买入候选</span>' if x["rank"] <= _top_k
               else '<span style="color:var(--faint)">—</span>')
            for x in (h.get("rows") or []))
        _topk_r = (h.get("top") or [])[:_top_k]
        _ind_top = {}
        for _x in _topk_r:
            _ind_top[_x.get("ind", "—")] = _ind_top.get(_x.get("ind", "—"), 0) + 1
        _n_dup = _top_k - len(_ind_top)
        _ded_codes = h.get("top_dedup_ind") or []
        _added = [c for c in _ded_codes if c not in {x["code"] for x in _topk_r}]
        L.append(
            f'<div class="sub" style="margin-top:10px"><b>买日 {h.get("date")} 的全池命中清单（{len(h.get("rows") or [])} 只 · '
            f'按 F 降序）</b> · 该买日前 {_top_k} 只即<b>当时</b>的买入候选'
            f'<br><span style="color:var(--warn)">⚠ 这是<b>买日 {h.get("date")}（信号日 {h.get("signal_date")}）的存档</b>，'
            f'<b>不是今天的买入名单</b> —— 今天的清单只看卡片最上方「今日买入清单」。</span>'
            f'<br><b>行业集中度</b>（命中全池）：'
            + " ｜ ".join(f'{k} <b>{v}</b> 只' for k, v in list(_ic.items())[:6])
            + f'<br><span style="color:var(--warn)">⚠ 冻结判据里<b>没有行业约束</b>：F 前 {_top_k} 只中有 '
            f'<b>{_n_dup}</b> 只与更靠前者同行业（' + "、".join(f'{k} {v} 席' for k, v in _ind_top.items() if v > 1)
            + f'）；按「同行业只取 1 只」（2026-09-28 你的实际操作口径）去重后，'
            f'前 {_top_k} 名顺延为 {_dedn} 只互不同行业 —— 新增纳入 '
            + ("、".join(_added[:6]) or "无")
            + f'（第 {_top_k + 1} 名之后顺延）。本表只做显示（不改选股、不改排名）；'
            f'要把它变成策略约束须走预注册勘误。</span></div>'
            '<div class="toolbar"><input type="text" id="tbl-hpdk-hits-q" '
            'placeholder="🔍 搜索名称 / 代码 / 行业…" autocomplete="off" spellcheck="false">'
            '<span class="count" id="tbl-hpdk-hits-count"></span></div>'
            '<div class="tbl-wrap"><table class="tbl" id="tbl-hpdk-hits" style="width:100%;font-size:12px">'
            '<thead><tr><th data-key="rank" style="text-align:center">F 名次</th>'
            '<th data-key="name">标的</th><th data-key="ind">行业</th>'
            '<th data-key="gap" style="text-align:right">今开跳空</th>'
            '<th data-key="F" style="text-align:right">F 复合分</th>'
            f'<th data-key="cand" style="text-align:center">当日候选（前 {_top_k}）</th></tr></thead>'
            f'<tbody>{mark_st_rows(_hr, [x.get("name") for x in (h.get("rows") or [])])}</tbody>'
            '</table></div>')
    # 近 N 日命中回看（R-hpdk-hist-0929）：卡片主区块只显示"最近一个已完成买日"，
    # 而用户关心的往往是"昨天/前几天的买日命中"（含自己实际下单那批）⇒ 把历史档
    # backtest/hpdk_hits_history.jsonl 的最近若干日紧凑渲染出来（一行一日）。
    _hp = BASE / "backtest" / "hpdk_hits_history.jsonl"
    if _hp.exists():
        try:
            _hs = [json.loads(l) for l in _hp.read_text(encoding="utf-8").splitlines() if l.strip()]
        except Exception:
            _hs = []
        _hs = [x for x in _hs if x.get("date")][-5:][::-1]
        if len(_hs) > 1:
            _rs = "".join(
                '<tr><td style="text-align:center">%s</td><td style="text-align:center">%s</td>'
                '<td style="text-align:right">%s</td><td style="text-align:right">%s</td>'
                '<td>%s</td></tr>'
                % (x.get("date"), x.get("signal_date"), x.get("n_pool"), x.get("n_hits"),
                   "、".join(str(c) for c in (x.get("top") or [])[:6]) or "—")
                for x in _hs)
            L.append(
                f'<div class="sub" style="margin-top:10px"><b>近 {len(_hs)} 个买日命中回看</b>'
                '<span style="color:var(--faint)">（来自 backtest/hpdk_hits_history.jsonl；'
                '上方主区块只显示最近一个买日）</span></div>'
                '<div class="tbl-wrap"><table class="tbl" id="tbl-hpdk-hist" '
                'style="width:100%;font-size:12px"><thead><tr>'
                '<th style="text-align:center">买日</th><th style="text-align:center">信号日</th>'
                '<th style="text-align:right">资格池</th><th style="text-align:right">命中</th>'
                f'<th>F 前 6</th></tr></thead><tbody>{_rs}</tbody></table></div>')
    L.append('<div class="sub" style="margin-top:6px;color:var(--warn)"><b>板块限定（2026-09-27 用户决定：只买主板）</b> —— 同一面板、同一记账规则下的同尺子对比：全窗 年化 <b>+72.59% → +47.77%</b>（−24.82pp）、夏普 <b>2.79 → 2.12</b>、最大回撤 <b>−32.29% → −29.13%</b>（<b>改善 3.16pp</b>）、净胜率 63.14% → 60.63%、单笔净均 +0.5574% → +0.4028%；2018+ 年化 +105.38% → +64.24%。选股集合仅 <b>55.5% 重合</b>（横截面 z 在候选池内标准化 ⇒ 缩池后标准分整体改变）。<b>代价明确：用年化换回撤，风险调整后更差。</b>完整逐项读数见 <code>backtest/报告-只买主板-回测对比-20260927.md</code> 与 <code>backtest/hengpan_fangliang_dikai_0925/evidence_board.json</code>（另有：全池 KSLOT=4 口径 +249.67%、主板 KSLOT=4 +189.75%，操作档见上）。</div>')
    L.append('<div class="sub" style="margin-top:6px;color:var(--warn)">'
             '<b>准入门槛扫描（2026-09-27）</b> —— 用户问「量比要多于多少 / 盈亏比要大于多少会不会改善」：'
             '<b>三个方向全部为负优化，未采纳任何门槛</b>。量比下限单调恶化（≥0.5 +43.59% → ≥1.5 +13.46%，'
             '基线 +47.77%）；量比上限越紧越差；盈亏比下限 ≥1.0 直接把年化打到 <b>−4.32%</b>、'
             '样本从 23,759 砍到 <b>3,272 笔</b>（≥3.0 零成交）。原因：复合分里的 z(−ln 量比)'
             '<b>已经软性偏好缩量</b>，加硬门槛只截断有用样本；且任何门槛都会改变当日候选池 ⇒ '
             '横截面 z 重算 ⇒ 选股整体重排。完整 18 臂读数见 '
             '<code>backtest/报告-准入门槛扫描-量比与盈亏比-20260927.md</code>。</div>')
    L.append('<div id="hpdk-pool-sec">')     # 开 2026-09-29：盘前选股池（明日买点准备清单）整段
    L.append('<div class="toolbar">'
             '<input type="text" id="tbl-hpdk-cand-q" '
             'placeholder="🔍 搜索名称 / 代码 / 板块 / 行业…" autocomplete="off" spellcheck="false">'
             '<select id="tbl-hpdk-cand-tier" class="flt" title="按板块筛选">'
             '<option value="">全部板块</option><option value="main">主板</option>'
             '<option value="gem">创业板</option><option value="star">科创板</option></select>'
             '<span class="count" id="tbl-hpdk-cand-count"></span></div>')
    L.append('<div class="tbl-wrap"><table class="tbl" id="tbl-hpdk-cand" style="width:100%;font-size:12px">'
             '<thead><tr>'
             '<th data-key="rank" style="text-align:center">#</th>'
             '<th data-key="name">标的</th>'
             '<th data-key="status" style="text-align:center" '
             'title="盘中判定结果：竞价预判 / 今日买入候选 #n / 留存 · F 第 n 位；买日 09:25 后不达标的行会被移除">状态</th>'
             '<th data-key="board">板块</th><th data-key="ind">行业</th>'
             '<th data-key="px" style="text-align:right">现价</th>'
             '<th data-key="chg" style="text-align:right">涨跌幅</th>'
             '<th data-key="amt" style="text-align:right" title="20 日均额 —— 复合分第一项">成交额20</th>'
             '<th data-key="vr" style="text-align:right" title="量比（当日量 / 前 20 日均量，不含当日）">量比</th>'
             '<th data-key="r20" style="text-align:right" title="20 日涨幅">20日涨幅</th>'
             '<th data-key="buy" style="text-align:right" '
             'title="买入价 = 次日开盘价，必须低开 1%~3%；下表给触发区间（今收×0.97 ~ ×0.99）">买入价</th>'
             f'<th data-key="tp" style="text-align:right" title="止盈价 = 实际买入价 ×{tp:.2f}">'
             f'止盈价 +{(par.get("TP", 0.02) or 0) * 100:.0f}%</th>'
             '<th data-key="sell" style="text-align:center" '
             'title="未触止盈则 T+2（买日次一交易日）尾盘卖出">卖出时点</th>'
             '<th data-key="qty" style="text-align:right" '
             'title="按操作口径本金/KSLOT 与该股 ADV×1% 取小后折算的整手股数">建议股数</th>'
             '<th data-key="cap" style="text-align:center" '
             'title="单票可买 = min(本金/KSLOT, 该股 20日均额×1%)。标「限至 X万」= 该股流动性装不下单票计划额，只能少买一点（建议股数已按缩小后规模折算）——不是不能买。">单票可买（上限）</th>'
             '</tr></thead><tbody>')
    for r in shown:
        c = r.get("close")
        amt = r.get("amt20")
        lo, hi = r.get("buy_lo"), r.get("buy_hi")
        qty = r.get("order_size")
        rz = r.get("ret20")
        col = "var(--up)" if (rz is not None and rz > 0) else "var(--down)"
        search = " ".join([str(r.get("name", "")), str(r.get("code", "")),
                           str(r.get("board", "")), str(r.get("ind") or "")]).strip()
        L.append(
            f'<tr data-code="{r.get("sym", "")}" data-tier="{_tier(r.get("board"))}" '
            f'data-search="{search}">'
            f'<td data-key="rank" data-v="{r.get("proxy_rank")}" style="text-align:center">'
            f'{r.get("proxy_rank")}</td>'
            f'<td data-key="name"><b>{r.get("name")}</b><br><span style="color:var(--sub);'
            f'font-size:var(--fs-xs);font-variant-numeric:tabular-nums">{r.get("code")}</span></td>'
            f'<td data-key="status" style="text-align:center;color:var(--faint)">—</td>'
            f'<td data-key="board">{r.get("board")}</td>'
            f'<td data-key="ind" style="color:var(--sub)">{r.get("ind") or "—"}</td>'
            f'<td data-key="px" data-v="{"" if c is None else c}" '
            f'style="text-align:right;font-variant-numeric:tabular-nums">'
            f'{("—" if c is None else format(c, ".2f"))}</td>'
            '<td data-key="chg" data-v=""></td>'
            f'<td data-key="amt" data-v="{"" if amt is None else amt}" style="text-align:right">'
            f'{("—" if amt is None else format(amt / 1e8, ".2f") + "亿")}</td>'
            f'<td data-key="vr" data-v="{r.get("volbr")}" style="text-align:right">'
            f'{format(r.get("volbr"), ".2f")}</td>'
            f'<td data-key="r20" data-v="{rz}" style="text-align:right;color:{col}">'
            f'{format(rz * 100, "+.2f")}%</td>'
            f'<td data-key="buy" data-v="{lo}" style="text-align:right;font-variant-numeric:tabular-nums">'
            '<span class="badge badge-auto">● 低开 1%~3% 才买</span>'
            f'<div style="margin-top:3px">{format(lo, ".3f")} ~ {format(hi, ".3f")}</div></td>'
            f'<td data-key="tp" data-v="{round(lo * tp, 3)}" '
            f'style="text-align:right;font-variant-numeric:tabular-nums;color:var(--up)">'
            f'{format(lo * tp, ".3f")} ~ {format(hi * tp, ".3f")}</td>'
            f'<td data-key="sell" data-v="{d.get("exit_date")}" style="text-align:center;color:var(--sub)">'
            f'T+2<br>{d.get("exit_date")} 尾盘</td>'
            f'<td data-key="qty" data-v="{qty}" style="text-align:right;'
            f'font-variant-numeric:tabular-nums">{qty:,} 股</td>'
            f'<td data-key="cap" data-v="{1 if r.get("cap_ok") else 0}" style="text-align:center" '
            f'title="（构建期预览；买日盘中按真实今开与本金额重算）「限至 X万」= 只能按该股 20日均额×1% 少买，不是不能买">'
            + ("足额" if r.get("cap_ok") else
               "<span style='color:var(--warn)'>限至 %.1f万</span>" % ((r.get("cap_single") or 0) / 1e4))
            + '</td>'
            '</tr>')
    L.append('</tbody></table></div>')
    L.append('<div class="sub" style="color:var(--faint)">当日流程：① 前一晚 / 09:15 前按上表挂 '
             '<code>今收×0.99</code> 限价买单 → ② 09:15–09:20【可撤单窗口】看虚拟开盘价，撤掉跌幅 &gt;3% '
             '的标的 → ③ 09:25 集合竞价撮合，开盘落在 −1%~−3% 的自动以开盘价成交 → '
             '④ T+2 09:15 前挂 <code>买入价×1.02</code> 限价卖单 → ⑤ T+2 14:55 未成交市价卖。</div>')
    L.append('</div>')                       # 关：#hpdk-pool-sec（盘前选股池整段；由 HPDK_JS 搬到卡片最上方并折叠）
    L.append('</div>')
    return "".join(L)


def hpdk_oos_card(BASE):
    """前向 OOS（预注册冻结）只读进度卡。"""
    ov = _read(BASE / "backtest" / "hpdk_oos_view.json")
    L = ['<div class="card" id="hpdk-oos-card">',
         '<h2>📈 前向 OOS（预注册冻结 · 只读账本） '
         f'<span class="view-badge auto">{ov.get("verdict") or "无读数"}</span></h2>']
    if not ov:
        L.append('<div class="sub" style="color:var(--faint)">产物未生成</div></div>')
        return "".join(L)
    g = ov.get("gates") or {}
    tick = lambda b: "✓" if b else "✗"          # noqa: E731
    L.append('<div class="sub">'
             f'冻结脚本 SHA <code>{(ov.get("script_sha256") or "—")[:16]}…</code> · '
             f'shadow_start <b>{ov.get("shadow_start")}</b> · 最后扫描 <b>{ov.get("last_scan_date")}</b> · '
             f'已完成 <b>{ov.get("n_settled") or 0}</b> 笔 / 待了结 <b>{ov.get("n_pending") or 0}</b> 笔'
             f'<br>{ov.get("exit_rule") or ""}</div>')
    L.append('<div class="sub" style="margin-top:6px">验收判据（预注册 §四）：'
             f'笔数 ≥300 <b>{tick(g.get("n"))}</b> · 信号日 ≥120 <b>{tick(g.get("days"))}</b> · '
             f'净均 &gt;0 <b>{tick(g.get("mean"))}</b> · 胜率 ≥46% <b>{tick(g.get("wr"))}</b> · '
             f'净中位 &gt;0 <b>{tick(g.get("med"))}</b> ｜ 执行线：实际成交均价÷当日开盘价−1 ≤ +0.20%'
             f'（已填 {(ov.get("exec_dev_pct") or {}).get("n", 0)} 笔）</div>')
    a = ov.get("acceptance") or {}
    if a:
        L.append(f'<div class="sub" style="margin-top:6px">主口径：笔数 <b>{a.get("n")}</b> · '
                 f'净均 <b>{a.get("mean_pct")}%</b> · 净中位 <b>{a.get("med_pct")}%</b> · '
                 f'胜率 <b>{a.get("wr_pct")}%</b> · 止盈率 <b>{ov.get("tp_hit_pct")}%</b></div>')
    last = (ov.get("last") or [])[-20:]
    if last:
        L.append('<table class="tbl" id="tbl-hpdk-oos" style="width:100%;font-size:12px;margin-top:8px">'
                 '<thead><tr><th>信号日</th><th>标的</th><th>低开</th><th>买日</th><th>买入价</th>'
                 '<th>了结日</th><th>卖出价</th><th>止盈</th><th>净收益</th><th>实际成交价</th>'
                 '<th>委托股数</th></tr></thead><tbody>')
        for x in last:
            L.append(f'<tr><td>{x.get("signal_date")}</td><td>{x.get("code")} {x.get("name")}</td>'
                     f'<td>{x.get("gap_pct")}%</td><td>{x.get("entry_date")}</td>'
                     f'<td>{x.get("entry_open")}</td><td>{x.get("exit_date")}</td>'
                     f'<td>{x.get("exit_px")}</td><td>{"是" if x.get("tp_hit") else "否"}</td>'
                     f'<td>{x.get("ret_pct")}%</td><td>{x.get("real_fill_px") or "—"}</td>'
                     f'<td>{x.get("order_size") or "—"}</td></tr>')
        L.append('</tbody></table>')
    L.append('</div>')
    return "".join(L)


def _hpdk_paper_read(BASE):
    return _read(BASE / "backtest" / "hpdk_paper.json")


def hpdk_paper_card(BASE):
    """💼 模拟盘（前向账户）—— 只读 backtest/hpdk_paper.json（由 hpdk_paper.py 从冻结 OOS 台账派生）。"""
    d = _hpdk_paper_read(BASE)
    L = ['<div class="card" id="hpdk-paper-card">']
    if not d:
        L.append('<h2>💼 模拟盘 · 缩量超跌 <span class="view-badge auto">产物未生成</span></h2>'
                 '<div class="sub" style="color:var(--faint)">跑 <code>'
                 'backtest/hengpan_fangliang_dikai_0925/hpdk_paper.py</code> 写入 '
                 '<code>backtest/hpdk_paper.json</code> 后本卡自动出现。</div></div>')
        return "".join(L)
    cfg = d.get("config") or {}
    acc = d.get("account") or {}
    rec = d.get("reconcile") or {}
    started = (acc.get("n_settled") or 0) > 0 or (acc.get("n_positions") or 0) > 0
    L.append('<h2>💼 模拟盘 · 缩量超跌 %s <span class="view-badge auto">%s</span></h2>'
             % (asof_badge(d.get("as_of")),
                "运行中" if started else "未开始（首个信号日 %s）" % cfg.get("shadow_start")))
    L.append('<div class="sub"><b>口径（操作档，与「建议股数／单票可买」同源）</b>：'
             '本金 <b>%.0f 万</b> · KSLOT <b>%s</b> · 单票 = min(前一日净值/KSLOT, 可用现金, 该股 20日均额×1%%) · '
             '止盈 <b>+%.0f%%</b>（未达标 T+2 尾盘）· 成本 <b>%.2f bp</b> 往返 · 池 = <b>%s</b>'
             '<br><b>台账来源</b>：冻结前瞻 OOS 台账 <code>oos_trades.jsonl</code>（脚本 SHA <code>%s…</code>）；'
             '本卡由 <code>hpdk_paper.py</code> 重放派生，并与台账<b>对拍</b>：台账 <b>%s</b> 笔 / 重放可了结 '
             '<b>%s</b> 笔 / 不一致 <b style="color:%s">%s</b> 项。</div>'
             % ((cfg.get("capital", 0) or 0) / 1e4, cfg.get("kslot", "—"),
                (cfg.get("tp", 0.02) or 0) * 100, cfg.get("cost_rt_bp", 0),
                "主板（剔创业板/科创板）" if cfg.get("mainboard") else "全池",
                (d.get("frozen_script_sha256") or "—")[:16],
                rec.get("ledger_n", "—"), rec.get("replay_settleable", "—"),
                "var(--down)" if rec.get("mismatches") else "var(--up)",
                len(rec.get("mismatches") or [])))
    band = []
    for lbl, val, col in (("净值", "%.4f" % (acc.get("nav") or 1.0), None),
                          ("累计收益", "%+.2f%%" % (acc.get("ret_pct") or 0.0),
                           "var(--up)" if (acc.get("ret_pct") or 0) >= 0 else "var(--down)"),
                          ("持有", "%s 只" % (acc.get("n_positions") or 0), None),
                          ("已了结", "%s 笔" % (acc.get("n_settled") or 0), None),
                          ("胜率", "%s%%" % acc["win_rate"] if acc.get("win_rate") is not None else "—", None),
                          ("单笔净均", "%+.4f%%" % acc["mean_per_trade"] if acc.get("mean_per_trade") is not None else "—", None),
                          ("单笔净中位", "%+.4f%%" % acc["med_per_trade"] if acc.get("med_per_trade") is not None else "—", None),
                          ("累计盈亏", "{:+,.0f} 元".format(acc.get("total_pnl") or 0), None)):
        st = ' style="color:%s"' % col if col else ""
        band.append('<span><span style="color:var(--faint)">%s</span> <b%s>%s</b></span>' % (lbl, st, val))
    L.append('<div class="sub" style="display:flex;gap:20px;flex-wrap:wrap;margin-top:8px">'
             + "".join(band) + '</div>')
    if not started:
        L.append('<div class="sub" style="margin-top:8px;color:var(--warn)">'
                 '<b>账户自 2026-09-28 起逐日累积</b>：该日收盘出信号 → 09-29 集合竞价买入 → 09-30 了结。'
                 '在此之前净值为 1.0000、无持仓、无成交。'
                 '<b>本策略的前向证据 = 冻结 OOS 台账</b>，本卡只是把台账按操作档本金记账后的钱账视图；'
                 '投产判定请看上方「前向 OOS」卡。</div>')
    tr = d.get("track") or []
    st = [x for x in tr if x.get("state") == "已了结"]
    if st:
        L.append('<div class="etf-sec" style="margin-top:14px">已了结明细（最近 %d 笔）</div>' % min(len(st), 40))
        L.append('<div class="tbl-wrap"><table class="tbl" id="tbl-hpdk-paper" style="width:100%;font-size:12px">'
                 '<thead><tr><th>信号日</th><th>标的</th><th>买日</th><th style="text-align:right">买入价</th>'
                 '<th>了结日</th><th style="text-align:right">卖出价</th><th style="text-align:right">净收益</th>'
                 '<th style="text-align:right">股数</th><th style="text-align:right">分配额</th></tr></thead><tbody>')
        for x in st[-40:]:
            rc = "var(--up)" if (x.get("ret_pct") or 0) > 0 else "var(--down)"
            L.append('<tr><td>%s</td><td>%s %s</td><td>%s</td><td style="text-align:right">%s</td>'
                     '<td>%s</td><td style="text-align:right">%s</td>'
                     '<td style="text-align:right;color:%s">%+.4f%%</td>'
                     '<td style="text-align:right">%s</td><td style="text-align:right">%s</td></tr>'
                     % (x.get("signal_date"), x.get("code"), x.get("name"), x.get("entry_date"),
                        x.get("entry_open"), x.get("exit_date"), x.get("exit_px"), rc,
                        x.get("ret_pct"), "{:,}".format(x.get("shares") or 0),
                        "{:,.0f}".format(x.get("alloc") or 0)))
        L.append('</tbody></table></div>')
    L.append('</div>')
    return "".join(L)


def hpdk_track_card(BASE):
    """👁 跟踪池 · 状态 = 待买入 / 持有中 / 已了结（只读 hpdk_paper.json）。"""
    d = _hpdk_paper_read(BASE)
    L = ['<div class="card" id="hpdk-track-card">']
    if not d:
        L.append('<h2>👁 跟踪池 · 缩量超跌</h2><div class="sub" style="color:var(--faint)">'
                 '产物未生成（见模拟盘卡说明）</div></div>')
        return "".join(L)
    tr = d.get("track") or []
    ho = [x for x in tr if x.get("state") == "持有中"]
    se = [x for x in tr if x.get("state") == "已了结"]
    pe = [x for x in tr if x.get("state") == "待判定"]
    L.append('<h2>👁 跟踪池 · 缩量超跌 <span class="view-badge auto">影子跟踪 · 只记账不成交</span></h2>')
    L.append('<div class="sub"><span class="badge badge-auto">持有中 %d</span> '
             '<span class="badge badge-auto">已了结 %d</span> '
             '<span class="badge badge-auto">待判定 %d</span>'
             '<br><b>状态含义</b>：<b>待判定</b> = 信号日已过、买入日未到（09:25 用真实今开筛出低开 1~3%% 的子集后才定榜）；'
             '<b>持有中</b> = 已按买入日开盘价成交、但还没到 T+2 了结日；<b>已了结</b> = 已出场（止盈或 T+2 尾盘）。'
             '%s</div>'
             % (len(ho), len(se), len(pe),
                ("当前资格池：信号日 <b>%s</b> → 买日 <b>%s</b> → 了结日 <b>%s</b>，共 <b>%s</b> 只（"
                 "<span style='color:var(--faint)'>这只是待筛选全体，不是买入名单</span>）"
                 % ((d.get("pool_now") or {}).get("as_of"), (d.get("pool_now") or {}).get("buy_date"),
                    (d.get("pool_now") or {}).get("exit_date"), (d.get("pool_now") or {}).get("n")))
                if d.get("pool_now") else ""))
    # 2026-09-29（R-hpdk-tracknote-0929，用户反馈「昨天早盘买入的没出现在跟踪池」）：
    # 根因是**预注册窗口边界**，不是漏记——影子账本 SHADOW_START=2026-09-25 ⇒ 首个信号日
    # = 09-28（09-25 休市；hpdk_paper 日志实证：首个信号日索引 2852/日历 2853 日）；
    # 而用户 09-28 早盘买入那批来自**信号日 09-24 = 样本内最后一日** ⇒ 按预注册不在影子盘内。
    # 面板在 09-28 盘前却给了「今日买入候选」⇒ 指导与记账不一致。此处把边界与去向写清楚。
    _h = _read(BASE / "backtest" / "hpdk_hits.json")
    _ss = ((d.get("config") or {}).get("shadow_start"))
    _sigs = [x.get("signal_date") for x in tr if x.get("signal_date")]
    if _h and _h.get("signal_date") and _ss and str(_h["signal_date"]) < str(_ss):
        _topn = "、".join("%s %s" % (x.get("name", ""), x.get("code", ""))
                          for x in (_h.get("top") or [])[:6])
        L.append(
            '<div class="sub" style="margin-top:8px;border-left:3px solid var(--warn);'
            'background:rgba(255,180,60,.08);padding:8px 10px;line-height:1.75">'
            f'<b>⚠ 为什么「上次买日那批」不在本表里</b>：影子账本窗口自 <b>{_ss}</b> 起（预注册）'
            f'⇒ 其<b>首个信号日 = {min(_sigs) if _sigs else "—"}</b>（{_ss} 为休市日，顺延）；'
            f'而最近一次买日 <b>{_h.get("date")}</b> 的信号日是 <b>{_h.get("signal_date")}</b>'
            f'（<b>样本内最后一日</b>）⇒ 按预注册<b>不计入影子账本</b>，故本表看不到它。'
            f'<br>该批的权威记录见上方「<b>✅ 今日命中（收盘链全池复算）</b>」区块：'
            f'命中 <b>{_h.get("n_hits")}</b> 只，F 前 {_h.get("k")}（{_topn}…）。'
            f'<span style="color:var(--faint)">（本表 = 影子账本；命中区块 = 买日口径，独立于 OOS 窗口）</span>'
            '</div>')
    # 2026-09-29（R-hpdk-cohort-0929b）：把「买日批次跟踪」表放进**跟踪池卡**（用户查看位）。
    # 原先挂在主卡 ⇒ 用户连问三次「跟踪池还是没有昨日 top4」。口径不变（模型买入名单，
    # 覆盖全部命中历史买日，含影子账本窗口外那批）。
    L.append(cohort_block(BASE))
    L.append('<div class="toolbar">'
             '<input type="text" id="tbl-hpdk-track-q" placeholder="🔍 搜索名称 / 代码 / 板块…" '
             'autocomplete="off" spellcheck="false">'
             '<select id="tbl-hpdk-track-tier" class="flt" title="按状态筛选">'
             '<option value="">全部状态</option><option value="hold">持有中</option>'
             '<option value="settled">已了结</option><option value="pending">待判定</option></select>'
             '<span class="count" id="tbl-hpdk-track-count"></span></div>')
    L.append('<div class="tbl-wrap"><table class="tbl" id="tbl-hpdk-track" style="width:100%;font-size:12px">'
             '<thead><tr><th data-key="state">状态</th><th data-key="sig">信号日</th>'
             '<th data-key="name">标的</th><th data-key="board">板块</th><th data-key="ind">行业</th>'
             '<th data-key="gap" style="text-align:right">低开</th>'
             '<th data-key="ed">买日</th><th data-key="epx" style="text-align:right">买入价</th>'
             '<th data-key="xd">了结日</th><th data-key="xpx" style="text-align:right">卖出价</th>'
             '<th data-key="ret" style="text-align:right">净收益</th>'
             '<th data-key="qty" style="text-align:right">建议股数</th>'
             '</tr></thead><tbody>')
    TIER = {"持有中": "hold", "已了结": "settled", "待判定": "pending"}
    if not tr:
        L.append('<tr><td colspan="12" style="text-align:center;color:var(--faint)">'
                 '跟踪池为空 —— 首个信号日 <b>2026-09-28</b>，首批买入 09-29，首批了结 09-30；'
                 '本表随日链自动填充。</td></tr>')
    for x in tr:
        stt = x.get("state")
        col = {"持有中": "var(--warn)", "已了结": "var(--faint)", "待判定": "var(--sub)"}.get(stt, "")
        gap = x.get("gap")
        L.append('<tr data-tier="%s" data-code="%s" data-search="%s">'
                 '<td data-key="state" style="color:%s">%s</td>'
                 '<td data-key="sig">%s</td><td data-key="name">%s %s</td>'
                 '<td data-key="board">%s</td><td data-key="ind" style="color:var(--sub)">%s</td>'
                 '<td data-key="gap" style="text-align:right">%s</td>'
                 '<td data-key="ed">%s</td><td data-key="epx" style="text-align:right">%s</td>'
                 '<td data-key="xd">%s</td><td data-key="xpx" style="text-align:right">%s</td>'
                 '<td data-key="ret" style="text-align:right">%s</td>'
                 '<td data-key="qty" style="text-align:right">%s</td></tr>'
                 % (TIER.get(stt, ""), x.get("code") or "",
                    " ".join([str(x.get("name") or ""), str(x.get("code") or ""),
                              str(x.get("board") or "")]).strip(),
                    col, stt, x.get("signal_date") or "—", x.get("code") or "", x.get("name") or "",
                    x.get("board") or "—", x.get("ind") or "—",
                    ("%+.2f%%" % gap) if gap is not None else "—",
                    x.get("entry_date") or "—",
                    ("%.3f" % x["entry_open"]) if x.get("entry_open") else "—",
                    x.get("exit_date") or ("待 T+2" if stt == "持有中" else "—"),
                    ("%.3f" % x["exit_px"]) if x.get("exit_px") else "—",
                    ("%+.4f%%" % x["ret_pct"]) if x.get("ret_pct") is not None else "—",
                    "{:,}".format(x.get("shares") or 0)))
    L.append('</tbody></table></div>')
    # ── 💼 实盘登记（2026-09-29，R-hpdk-real-0929 · 用户「按你的来」）─────────────────────
    # 与影子账本**彻底分离**：影子账本 = 冻结 OOS 台账派生（预注册窗口、SHA 锁定）；
    # 实盘登记 = 你自己的真实成交，**只存本机浏览器 localStorage**，不上传、不入库、不碰台账。
    # 公开仓里绝不落你的真实持仓（本块 HTML 不含任何成交数据，只有表单与逻辑）。
    # 了结日按冻结口径 = 买入日 + 1 个交易日（entry=cal[t+1] / exit=cal[t+2]）。
    try:
        _cal = [ln.split(",")[0].strip() for ln in
                (BASE / "index_000300.csv").read_text(encoding="utf-8-sig").splitlines()[1:]
                if ln[:4].isdigit()]
    except Exception:
        _cal = []
    _cal90 = _cal[-90:]
    _last_td = (_cal90[-1] if _cal90 else "")
    L.append(
        '<div class="sub" style="margin-top:16px;border-top:1px dashed var(--border);padding-top:10px">'
        '<b>💼 实盘登记（你的真实成交 · 仅存本机浏览器）</b>'
        '<span style="color:var(--faint)"> —— 与上表（影子账本/模拟）分开记账：'
        '本块数据只写在你这台浏览器的 localStorage，<b>不上传服务器、不入仓库、不改冻结台账</b>；'
        '换浏览器/清缓存即消失（可用下方「导出」自行备份）。</span>'
        f'<br><span style="color:var(--faint)">了结日按冻结口径 = 买入日 + 1 个交易日'
        f'（当前日历末日 {_last_td}）</span></div>'
        '<div class="toolbar" id="hpdk-real-bar">'
        '<input type="text" id="hpdk-real-code" placeholder="代码（6 位，如 600327）" style="width:170px">'
        f'<input type="text" id="hpdk-real-date" placeholder="买入日 YYYY-MM-DD" value="{_last_td}" style="width:150px">'
        '<input type="text" id="hpdk-real-px" placeholder="买入价" style="width:90px">'
        '<input type="text" id="hpdk-real-qty" placeholder="股数" style="width:90px">'
        '<button type="button" id="hpdk-real-add">＋ 登记</button>'
        '<button type="button" id="hpdk-real-clear">清空</button>'
        '<button type="button" id="hpdk-real-exp">导出 JSON</button>'
        '<span class="count" id="hpdk-real-count"></span></div>'
        '<div class="tbl-wrap"><table class="tbl" id="tbl-hpdk-real" style="width:100%;font-size:12px">'
        '<thead><tr><th data-key="bd">买日</th><th data-key="name">标的</th>'
        '<th data-key="px" style="text-align:right">买入价</th>'
        '<th data-key="qty" style="text-align:right">股数</th>'
        '<th data-key="cost" style="text-align:right">成本</th>'
        '<th data-key="tp" style="text-align:right">止盈价 +2%</th>'
        '<th data-key="xd">了结日（买日+1 交易日）</th>'
        '<th data-key="state" style="text-align:center">状态</th>'
        '<th style="text-align:center">操作</th></tr></thead>'
        '<tbody><tr><td colspan="9" style="text-align:center;color:var(--faint)">'
        '尚无登记 —— 用上方表单逐笔添加（默认买入日 = 最近交易日）</td></tr></tbody></table></div>')
    L.append(
        '<script>(function(){'
        'var LS="quant_hpdk_real_v1", CAL=' + json.dumps(_cal90, ensure_ascii=False) + ';'
        'function norm(c){c=String(c||"").replace(/^(sh|sz|bj)/i,"").trim();'
        'if(!/^\\d{6}$/.test(c))return "";'
        '/* code review 修正（0929）：原来「非 6 开头一律 sz」⇒ 8xx/4xx（北交所）、9xx（B股）'
        '会被静默映射成不存在的深市代码；本策略只覆盖 沪6 / 深00＋中小02 / 创业板30 / 科创68 */'
        'if(c[0]==="6")return "sh"+c;'
        'if(c[0]==="0"||c[0]==="3")return "sz"+c;'
        'return "";}'
        'function bare(c){return String(c||"").replace(/^(sh|sz|bj)/i,"");}'
        'function load(){try{var a=JSON.parse(localStorage.getItem(LS));return (a&&a.length)?a:[]}catch(e){return []}}'
        'function save(a){try{localStorage.setItem(LS,JSON.stringify(a))}catch(e){}}'
        'function exitOf(d){var i=CAL.indexOf(d);if(i<0)return "";return CAL[i+1]||"";}'
        'function stateOf(d){var i=CAL.indexOf(d);if(i<0)return "买日不在日历";'
        'var x=CAL[i+1];if(!x)return "持有中（下一交易日未到）";'
        'return (CAL[CAL.length-1]>=x)?"已到期（了结日尾盘卖出）":("持有中 · 了结 "+x);}'
        '/* 名称查表：从 window.HPDK 资格池取 代码→名称（与站点其它表同款「名+码」两行显示） */'
        'function nameOf(sym){var rs=(window.HPDK&&window.HPDK.rows)||[],k;'
        'for(k=0;k<rs.length;k++)if(rs[k]&&rs[k].code===bare(sym))return rs[k].name||"";return "";}'
        'function render(){var tb=document.querySelector("#tbl-hpdk-real tbody");if(!tb)return;'
        'var a=load(),i,rows="",tot=0;'
        'for(i=0;i<a.length;i++){var r=a[i],cost=(Number(r.px)||0)*(Number(r.qty)||0);tot+=cost;'
        'var nm=nameOf(r.sym),st=stateOf(r.date);'
        'var stB=/^已到期/.test(st)?"<span class=badge badge-auto>"+st+"</span>"'
        ':(/^持有中/.test(st)?"<span class=badge badge-auto>"+st+"</span>"'
        ':"<span style=color:var(--faint)>"+st+"</span>");'
        'rows+="<tr>"'
        '+"<td data-key=bd style=font-variant-numeric:tabular-nums>"+r.date+"</td>"'
        '+"<td data-key=name><b>"+(nm||bare(r.sym))+"</b><br>"'
        '+"<span style=color:var(--sub);font-size:var(--fs-xs);font-variant-numeric:tabular-nums>"'
        '+bare(r.sym)+"</span></td>"'
        '+"<td data-key=px style=text-align:right;font-variant-numeric:tabular-nums>"'
        '+(Number(r.px)||0).toFixed(3)+"</td>"'
        '+"<td data-key=qty style=text-align:right;font-variant-numeric:tabular-nums>"'
        '+(Number(r.qty)||0).toLocaleString()+" 股</td>"'
        '+"<td data-key=cost style=text-align:right;font-variant-numeric:tabular-nums>"'
        '+cost.toFixed(0)+" 元</td>"'
        '+"<td data-key=tp style=text-align:right;color:var(--up);font-variant-numeric:tabular-nums>"'
        '+((Number(r.px)||0)*1.02).toFixed(3)+"</td>"'
        '+"<td data-key=xd>"+(exitOf(r.date)||"—")+"</td>"'
        '+"<td data-key=state style=text-align:center>"+stB+"</td>"'
        "+\"<td style=text-align:center><button type=button data-del='\"+i+\"'>删</button></td></tr>\";}"
        'if(!a.length)rows="<tr><td colspan=9 style=text-align:center;color:var(--faint)>尚无登记</td></tr>";'
        'tb.innerHTML=rows;'
        'var c=document.getElementById("hpdk-real-count");'
        'if(c)c.textContent="共 "+a.length+" 笔 · 合计成本 "+tot.toFixed(0)+" 元";}'
        'function add(){var sym=norm(document.getElementById("hpdk-real-code").value);'
        'var d=document.getElementById("hpdk-real-date").value.trim();'
        'var px=parseFloat(document.getElementById("hpdk-real-px").value);'
        'var qy=parseInt(document.getElementById("hpdk-real-qty").value,10);'
        'if(!sym||!/^\\d{4}-\\d{2}-\\d{2}$/.test(d)||!(px>0)){alert("请填：6 位代码（仅支持 6/0/3 开头：沪市主板 · 深市主板/中小 · 创业板）/ 买日 YYYY-MM-DD / 正数买入价");return;}'
        'var a=load();a.push({sym:sym,date:d,px:px,qty:(qy>0?qy:0),ts:new Date().toISOString()});'
        'save(a);document.getElementById("hpdk-real-code").value="";'
        'document.getElementById("hpdk-real-px").value="";document.getElementById("hpdk-real-qty").value="";render();}'
        'function del(i){var a=load();a.splice(i,1);save(a);render();}'
        'function clr(){if(confirm("清空全部实盘登记？（仅影响本机浏览器）")){save([]);render();}}'
        'function exp(){var t=JSON.stringify(load(),null,1);'
        'try{navigator.clipboard.writeText(t);alert("已复制到剪贴板（"+load().length+" 笔）")}'
        'catch(e){window.prompt("手动复制：",t)}}'
        'document.addEventListener("click",function(e){var t=e.target;if(!t||!t.getAttribute)return;'
        'var dl=t.getAttribute("data-del");if(dl!==null&&dl!==undefined&&dl!==""){del(parseInt(dl,10));return;}'
        'if(t.id==="hpdk-real-add")add();else if(t.id==="hpdk-real-clear")clr();'
        'else if(t.id==="hpdk-real-exp")exp();});'
        'window.HPDK_REAL={list:load,add:add,del:del,clear:clr,exitOf:exitOf,stateOf:stateOf,cal:CAL};'
        'render();'
        '})();</script>')
    L.append('</div>')
    return "".join(L)

