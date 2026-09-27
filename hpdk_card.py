# -*- coding: utf-8 -*-
"""hpdk_card.py — 「横盘低开·两日」看板卡片与盘中 payload（2026-09-27 新增，R-hpdk-dash-0927）

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


def _read(p):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


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
        L.append('<h2>🎯 横盘低开·两日 <span class="view-badge auto">产物未生成</span></h2>'
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
    L.append(f'<h2>🎯 横盘低开·两日 <span class="view-badge auto">数据 as_of {d.get("as_of")}</span></h2>')
    L.append(
        '<div class="sub"><b>策略定义（与冻结预注册逐条一致；本页不复述自定义口径）</b>：T 收盘判定 → '
        f'资格 = 上市有效交易日 ≥{par.get("LISTED", 250)} ＋ 收盘 ≥{par.get("MINPX", 3.0):.2f} 元 ＋ '
        f'20 日均额 ≥{(par.get("MINAMT", 2e7) or 0) / 1e4:.0f} 万 ＋ 非 ST/*ST（期内代理 ＋ 现名）＋ '
        '每股净资产 ≥3 元（报告期 +4 个月后方可用）'
        '＋ **只买主板**（sh600/601/603/605 ＋ sz000/001/002/003；剔创业板 300/301/302、科创板 688）'
        '｜ <b>次日开盘跳空 gap = 今开/昨收 − 1 ∈ [−3%, −1%]</b>（低开至少 1%、不超过 3%）'
        f'｜ 复合分 F = z(−ln 成交额20) + z(−ln 量比) + z(−20 日涨幅)，取前 {par.get("K", 10)} 只'
        f'｜ 仓位 = min(前一日净值/{kslot}, 可用现金)，最多同持 {kslot} 只'
        f'｜ 出场 = 止盈 +{(par.get("TP", 0.02) or 0) * 100:.0f}% ／ 未达标 T+2 尾盘（<b>不止损</b>）'
        '<br><span style="color:var(--warn)">⚠ 名字里的「横盘放量」是历史遗留：样本内实测「横盘」无用、'
        '「放量」方向相反（要缩量），<b>冻结规格里既无横盘条件也无放量条件</b>，'
        '只剩「缩量 ＋ 低成交额 ＋ 超跌」的复合分。</span>'
        f'<br>冻结脚本 <code>oos_run.py</code> SHA256 <code>{ssha}…</code> ｜ 候选生成器与其逐位对拍 '
        f'<b>{a11.get("days_bitwise_equal", 0)}/{a11.get("days_compared", 0)} 个交易日完全相等</b></div>')
    L.append(
        '<div class="sub" style="margin-top:8px"><b>盘中判定（浏览器端 · 零落盘）</b>：'
        '09:15–09:25 集合竞价只灰标<b>竞价预判</b>，<b>不剔除任何标的</b>；'
        '<b>09:25 起用真实今开判定</b> —— 命中（今开/昨收−1 ∈ [−3%, −1%] ＋ 可交易 ＋ 准入过滤件达标）者'
        '进入当日候选，其余 <b>自动从清单剔除</b>（不是置灰）。'
        f'<br><b>操作口径（与回测指标带分列，不混写）</b>：本金 <b>{capital / 1e4:.0f} 万</b> / '
        f'KSLOT <b>{k_ops or "—"}</b> → 单票分配 min(本金/KSLOT, 该股 ADV×1%) = '
        f'<b>{capital / max(1, k_ops) / 1e4:.1f} 万</b>；<b>硬约束：单票 ≤ 该股 20 日均额×1%</b> '
        '⇒ 本配置账户上限约 <b>101 万元</b>。'
        '<br>买入价 = <b>次日开盘价</b>（集合竞价单一价格撮合，须 09:25 前挂单，见下方流程）；'
        f'止盈价 = <b>买入价 × {tp:.2f}</b>；未达止盈则 <b>{d.get("exit_date")} 尾盘</b>卖出。</div>')
    rows = rows_with_proxy(d)
    shown = rows[:RENDER_N]
    L.append(
        f'<div class="sub" style="margin-top:10px"><b>明日买点准备清单</b>（信号日 <b>{d.get("as_of")}</b> 收盘 · '
        f'买日 <b>{d.get("buy_date")}</b> · 了结日 <b>{d.get("exit_date")}</b>）· '
        f'资格池 <b>{len(rows)}</b> 只 → 下表按<b>盘前代理分</b>降序展示前 <b>{len(shown)}</b> 只'
        '<br><span style="color:var(--warn)">⚠ <b>这不是买入名单</b>：真正的前 '
        f'{par.get("K", 10)} 名要在「次日开盘低开 −3%~−1% 的子集」内重算复合分，而该子集 09:25 才知道；'
        '代理分是在<b>全体资格池</b>内标准化的，与正式排名不同。搜索 / 排序 / 板块筛选由板内通用脚本接管；'
        '09:25 后本表按真实今开自动剔除并置顶命中者。</span></div>')
    L.append('<div class="sub" style="margin-top:6px;color:var(--warn)"><b>板块限定（2026-09-27 用户决定：只买主板）</b> —— 同一面板、同一记账规则下的同尺子对比：全窗 年化 <b>+72.59% → +47.77%</b>（−24.82pp）、夏普 <b>2.79 → 2.12</b>、最大回撤 <b>−32.29% → −29.13%</b>（<b>改善 3.16pp</b>）、净胜率 63.14% → 60.63%、单笔净均 +0.5574% → +0.4028%；2018+ 年化 +105.38% → +64.24%。选股集合仅 <b>55.5% 重合</b>（横截面 z 在候选池内标准化 ⇒ 缩池后标准分整体改变）。<b>代价明确：用年化换回撤，风险调整后更差。</b>完整逐项读数见 <code>backtest/报告-只买主板-回测对比-20260927.md</code> 与 <code>backtest/hengpan_fangliang_dikai_0925/evidence_board.json</code>（另有：全池 KSLOT=4 口径 +249.67%、主板 KSLOT=4 +189.75%，操作档见上）。</div>')
    L.append('<div class="sub" style="margin-top:6px;color:var(--warn)">'
             '<b>准入门槛扫描（2026-09-27）</b> —— 用户问「量比要多于多少 / 盈亏比要大于多少会不会改善」：'
             '<b>三个方向全部为负优化，未采纳任何门槛</b>。量比下限单调恶化（≥0.5 +43.59% → ≥1.5 +13.46%，'
             '基线 +47.77%）；量比上限越紧越差；盈亏比下限 ≥1.0 直接把年化打到 <b>−4.32%</b>、'
             '样本从 23,759 砍到 <b>3,272 笔</b>（≥3.0 零成交）。原因：复合分里的 z(−ln 量比)'
             '<b>已经软性偏好缩量</b>，加硬门槛只截断有用样本；且任何门槛都会改变当日候选池 ⇒ '
             '横截面 z 重算 ⇒ 选股整体重排。完整 18 臂读数见 '
             '<code>backtest/报告-准入门槛扫描-量比与盈亏比-20260927.md</code>。</div>')
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
        L.append('<h2>💼 模拟盘 · 横盘低开·两日 <span class="view-badge auto">产物未生成</span></h2>'
                 '<div class="sub" style="color:var(--faint)">跑 <code>'
                 'backtest/hengpan_fangliang_dikai_0925/hpdk_paper.py</code> 写入 '
                 '<code>backtest/hpdk_paper.json</code> 后本卡自动出现。</div></div>')
        return "".join(L)
    cfg = d.get("config") or {}
    acc = d.get("account") or {}
    rec = d.get("reconcile") or {}
    started = (acc.get("n_settled") or 0) > 0 or (acc.get("n_positions") or 0) > 0
    L.append('<h2>💼 模拟盘 · 横盘低开·两日 <span class="view-badge auto">%s</span></h2>'
             % ("运行中 · as_of " + str(d.get("as_of")) if started
                else "未开始（首个信号日 %s）" % cfg.get("shadow_start")))
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
        L.append('<h2>👁 跟踪池 · 横盘低开·两日</h2><div class="sub" style="color:var(--faint)">'
                 '产物未生成（见模拟盘卡说明）</div></div>')
        return "".join(L)
    tr = d.get("track") or []
    ho = [x for x in tr if x.get("state") == "持有中"]
    se = [x for x in tr if x.get("state") == "已了结"]
    pe = [x for x in tr if x.get("state") == "待判定"]
    L.append('<h2>👁 跟踪池 · 横盘低开·两日 <span class="view-badge auto">影子跟踪 · 只记账不成交</span></h2>')
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
    L.append('</div>')
    return "".join(L)

