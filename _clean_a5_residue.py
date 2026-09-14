# -*- coding: utf-8 -*-
"""A5 残党清理（v1.3 终版，幂等）：build_a5_review.py 补 bench 字段 + build_dual_system.py 9 处旧标识清理 + 已平仓表只显新口径"""
ok = []

# ---------- 1) build_a5_review.py：bench 入 JSON（幂等） ----------
P = "build_a5_review.py"
src = open(P, encoding="utf-8").read()
old = 'json.dump(out, open(os.path.join(REVIEW_DIR, "a5_review.json"), "w", encoding="utf-8")'
assert old in src, "MISS review-bench"
if 'out["bench"]' not in src:
    src = src.replace(old, 'out["bench"] = bench   # v1.3：基准随口径单一数据源\n' + old, 1)
    open(P, "w", encoding="utf-8").write(src)
ok.append("review-bench")

# ---------- 2) build_dual_system.py ----------
P = "build_dual_system.py"
s = open(P, encoding="utf-8").read()


def rep(old, new, tag):
    global s
    if old not in s:
        raise AssertionError(f"MISS {tag}")
    s = s.replace(old, new, 1)
    ok.append(tag)


rep('"""过闸族标注：F3 空间因子（首板日距前60日收盘高点≥20%，百分比单位）+ rel_pos≤0.5（G3_M3 唯一牛熊双过闸）"""',
    '"""生产预筛标注：F3 空间因子（首板日距前60日收盘高点≥20%）+ rel_pos≤0.5（v1.3 起为双池滤网的前置条件）"""', "gatecell-doc")

rep('title="G3_M3 过闸族：F3空间≥20% + 低位rel≤0.5"',
    'title="生产预筛：F3空间≥20% + 低位rel≤0.5（池A/池B 为附加滤网）"', "gatecell-title")

rep('<h2>🎯 打板族（过闸档位） <span class="view-badge auto">G3_M3 · 过闸档位 · 模拟盘观察</span></h2>',
    '<h2>🎯 打板族（双池滤网 v1.3） <span class="view-badge auto">池A 超跌 / 池B 趋势 · 模拟盘观察</span></h2>', "a5view-h2")

# A5_REVIEW_BLOCK KPI：改读 JSON bench（v1.3 兜底）
rep("""    _a5kpi = (
        f'<div class="kpi"><div class="l">已平仓</div><div class="v">{_ars.get("n", 0)}/30</div><div class="s">触发判定阈值</div></div>'
        f'<div class="kpi"><div class="l">胜率</div><div class="v">{f"{_wr:.1f}%" if _wr is not None else "—"}</div><div class="s">基准 46.1% · 闸 [35,55]%</div></div>'
        f'<div class="kpi"><div class="l">均值净</div><div class="v" style="color:{("var(--up)" if (_mn or 0) >= 0 else "var(--down)")}">{f"{_mn:+.2f}%" if _mn is not None else "—"}</div><div class="s">基准 -0.17% · 闸 &gt;-0.5%</div></div>'
        f'<div class="kpi"><div class="l">止盈占比</div><div class="v">{f"{_tp:.1f}%" if _tp is not None else "—"}</div><div class="s">基准 21.5% · 闸 [12,32]%</div></div>'
        f'<div class="kpi"><div class="l">净值</div><div class="v">{_ars.get("nav", 1.0):.4f}</div><div class="s">已平仓复利</div></div>'
    )""",
    """    _arb = _ar.get("bench", {}) or {}
    _bwr = _arb.get("win_rate", 56.1); _bmn = _arb.get("mean_net", 1.19); _btp = _arb.get("tp_ratio", 25.0)
    _v1n_ = _ars.get("v1_n", 0)
    _a5kpi = (
        f'<div class="kpi"><div class="l">已平仓（新口径）</div><div class="v">{_ars.get("n", 0)}/30</div><div class="s">触发判定阈值' + (f' · v1 归档 {_v1n_} 笔' if _v1n_ else '') + '</div></div>'
        f'<div class="kpi"><div class="l">胜率</div><div class="v">{f"{_wr:.1f}%" if _wr is not None else "—"}</div><div class="s">基准 {_bwr:.1f}% · 闸 [46,66]%</div></div>'
        f'<div class="kpi"><div class="l">均值净</div><div class="v" style="color:{("var(--up)" if (_mn or 0) >= 0 else "var(--down)")}">{f"{_mn:+.2f}%" if _mn is not None else "—"}</div><div class="s">基准 +{_bmn:.2f}% · 闸 &gt;+0.5%</div></div>'
        f'<div class="kpi"><div class="l">止盈占比</div><div class="v">{f"{_tp:.1f}%" if _tp is not None else "—"}</div><div class="s">基准 {_btp:.1f}% · 闸 [15,35]%</div></div>'
        f'<div class="kpi"><div class="l">净值</div><div class="v">{_ars.get("nav", 1.0):.4f}</div><div class="s">全部已平仓复利（含 v1 归档）</div></div>'
    )""", "a5rev-kpi")

rep("""    A5_REVIEW_BLOCK = (f'<h2>🎯 打板族（过闸档位）模拟盘验证 <span class="badge badge-auto">生产预筛口径 · 非实盘指令</span></h2>'
                       f'<div class="sub">逐笔模拟盘跟踪（net_ret 含成本）· 验证门参考 = G3_M3 过闸（牛 +2.52% / 熊 +0.27%）· 30 信号或 3 个月触发判定 · 详细见「🎯 打板族」视图</div>'""",
    """    A5_REVIEW_BLOCK = (f'<h2>🎯 打板族（双池滤网 v1.3）模拟盘验证 <span class="badge badge-auto">池A 超跌 / 池B 趋势 · 非实盘指令</span></h2>'
                       f'<div class="sub">逐笔模拟盘跟踪（net_ret 含成本）· 验证门基准 = 双池并集（胜率 56.1% / 均值 +1.19% / tp 25.0%）· 新口径独立计数（v1 旧口径 11 笔归档）· 详细见「🎯 打板族」视图</div>'""", "a5rev-block")

rep('<div class="sub">左侧导航切换：🅰️ 全量池中/长线（全市场自动池·股票分层+基金） / ⚡ 短线 / 🎯 打板族（过闸档位·模拟盘观察） · 信号仅供参考</div>',
    '<div class="sub">左侧导航切换：🅰️ 全量池中/长线（全市场自动池·股票分层+基金） / ⚡ 短线 / 🎯 打板族（双池滤网 v1.3 · 模拟盘观察） · 信号仅供参考</div>', "view-switch")

rep('<!-- ============ 视图 D：打板族（过闸档位 · 第三个系统，G3_M3 过闸 + 生产预筛模拟盘） ============ -->',
    '<!-- ============ 视图 D：打板族（双池滤网 v1.3 · 第三个系统，池A 超跌/池B 趋势 + 生产预筛模拟盘） ============ -->', "view-comment")

rep('''<h2>🎯 打板族（过闸档位）模拟盘验证 <span class="badge badge-auto">生产预筛口径 · 非实盘指令</span></h2>
<div class="sub">逐笔模拟盘跟踪（net_ret 含成本）· 验证门参考 = G3_M3 过闸（牛 +2.52% / 熊 +0.27%）· 30 信号或 3 个月触发判定 · 详细见「🎯 打板族」视图</div>''',
    '''<h2>🎯 打板族（双池滤网 v1.3）模拟盘验证 <span class="badge badge-auto">池A 超跌 / 池B 趋势 · 非实盘指令</span></h2>
<div class="sub">逐笔模拟盘跟踪（net_ret 含成本）· 验证门基准 = 双池并集（胜率 56.1% / 均值 +1.19% / tp 25.0%）· 新口径独立计数（v1 旧口径 11 笔归档）· 详细见「🎯 打板族」视图</div>''', "viewreview-card")

# 已平仓表：只显示新口径
rep('    closed_rows = [_row(', '    closed_new = [p for p in closed if p.get("pools")]     # v1.3：看板只列新口径；v1 归档见复盘日志/state\n    closed_rows = [_row(', "closed-filter")
rep('''<h2>📜 已平仓（累计） <span class="badge badge-auto">{len(closed)} 笔</span></h2>
<div class="sub">模拟盘逐笔净收益（含成本买 0.525%/卖 0.625%）· 累计 ≥30 笔触发验证门判定</div>''',
    '''<h2>📜 已平仓（新口径） <span class="badge badge-auto">{len(closed_new)} 笔 · v1 归档 {len(closed) - len(closed_new)} 笔</span></h2>
<div class="sub">模拟盘逐笔净收益（含成本买 0.525%/卖 0.625%）· 累计 ≥30 笔触发验证门判定 · <b>v1 旧口径 11 笔（均值 −1.71%）已归档</b>（完整记录见复盘日志与 paper_state.json，不再逐笔展示）</div>''', "closed-card")
rep('], closed_rows, "（尚无平仓记录）")}', '], closed_rows, "（新口径尚无平仓记录——2026-09-15 起计）")}', "closed-empty")

open(P, "w", encoding="utf-8").write(s)
print("PATCHED:", ok)
print("总计:", len(ok))
