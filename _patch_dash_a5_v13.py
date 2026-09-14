# -*- coding: utf-8 -*-
"""build_dual_system.py A5 卡 v1.3 补丁：双池展示 + 回测参考卡 + 口径文案"""
P = "build_dual_system.py"
src = open(P, encoding="utf-8").read()
ok = []


def rep(old, new, tag):
    global src
    assert old in src, f"MISS {tag}"
    src = src.replace(old, new, 1)
    ok.append(tag)


# A) 打板族回测参考卡 → v1.3
rep('''def bt_a5_html():
    """打板族过闸档位回测参考卡（2026-09-04 精简：只显示生产在用最优配置）
    口径：BASE 生产档（rel_pos≤0.5 + amt≥5e7 + room≥0.20）= 9/1 融合网格 260 配置 牛熊独立四闸唯一全维通过
        2026-09-04 放宽扫描 14 配置证实其为唯一全维最优（权威数据 daban_loosen_sweep_20260904.csv）"""
    c1 = f\'\'\'<div class="bt-card" id="bt-a5-all">
<div class="bt-head"><b>✅ 生产在用配置（G3_M3 过闸族）</b><span class="bt-tag">唯一四闸 · 全维最优 · 不改</span></div>
<div class="kpis">
<div class="kpi"><div class="l">四闸</div><div class="v" style="color:var(--up)">✅ 通过</div><div class="s">n=358 · wr 51.1% · 2021+ 制度一致区间</div></div>
<div class="kpi"><div class="l">交易中位</div><div class="v" style="color:var(--up)">+0.13%</div><div class="s">均值 +0.69% · 2024 灾年 +0.9%</div></div>
<div class="kpi"><div class="l">累计 / 回撤</div><div class="v">+26.2%</div><div class="s">mdd -15.8% · 放宽 14 配置中最小</div></div>
<div class="kpi"><div class="l">牛 / 熊</div><div class="v">+0.28% / +0.07%</div><div class="s">n=102 / 256 · 牛熊中位均正</div></div>
</div></div>\'\'\'
    return (f\'<div class="card" id="bt-a5">\\n\'
            f\'<h2>🏆 打板族（生产配置） <span class="badge badge-auto">G3_M3 过闸族 · 9/4 放宽扫描证实全维最优</span></h2>\\n\'
            f\'<div class="sub">生产预筛 = <b>rel_pos≤0.5 + 成交额≥5000万 + 距60日高点≥20%（ROOM_MIN=0.20）</b> + 首板次日低开 gap∈[-5%,-2%] + 止盈 8%/2 天。牛熊独立四闸（n≥30 + wr≥40% + 均值&gt;0 + 中位&gt;0）通过，为 9/1 融合网格唯一牛熊双过闸族</div>\\n\'
            f\'<div class="sub" style="color:#059669">✅ <b>9/4 放宽扫描 14 配置确认最优</b>：放宽 rel_pos(0.6/0.7/0.8/1.0) 中位全转负、降 amt(3e7/2e7/1e7) 过闸但劣化、降 room(0.10/0.00) 四闸灭 —— <b>生产参数维持不变</b>（回测期望，模拟盘验证门通过前不改权重）</div>\\n\'
            f\'<div class="bt-grid">{c1}</div>\\n</div>\')''',
    '''def bt_a5_html():
    """打板族回测参考卡（v1.3 · 2026-09-15 双池独立滤网上线）
    口径：线上基底（rel_pos≤0.5 + amt≥5e7 + room≥0.20）上叠加双池——池A 超跌 ret20≤-7.31% / 池B 趋势 ADX14≥27.9
    数据：R-daban-opt-0915（真实 amount + 严格 rel_pos 修正口径，2016-2026，含成本）"""
    c1 = f\'\'\'<div class="bt-card" id="bt-a5-all">
<div class="bt-head"><b>🆕 v1.3 双池独立滤网（2026-09-15 上线）</b><span class="bt-tag">各自独立 · 不做共振交集</span></div>
<div class="kpis">
<div class="kpi"><div class="l">池A 超跌 ret20≤-7.31%</div><div class="v" style="color:var(--up)">+1.37%/笔</div><div class="s">n=282 · 胜率 58.2% · 10/10 年正</div></div>
<div class="kpi"><div class="l">池B 趋势 ADX≥27.9</div><div class="v" style="color:var(--up)">+1.19%/笔</div><div class="s">n=255 · 胜率 54.9% · 8/10 年正</div></div>
<div class="kpi"><div class="l">并集（验证门基准）</div><div class="v" style="color:var(--up)">+1.19%/笔</div><div class="s">n=396 · 胜率 56.1% · ≈38.6 笔/年</div></div>
<div class="kpi"><div class="l">对照：旧口径基底</div><div class="v">+0.57%/笔</div><div class="s">n=692 · 胜率 50.6%（v1 归档 11 笔 -1.71%）</div></div>
</div></div>\'\'\'
    return (f\'<div class="card" id="bt-a5">\\n\'
            f\'<h2>🏆 打板族（生产配置） <span class="badge badge-auto">v1.3 双池独立滤网 · 2026-09-15 上线</span></h2>\\n\'
            f\'<div class="sub">生产预筛 = <b>rel_pos≤0.5 + 成交额≥5000万 + 距60日高点≥20%（ROOM_MIN=0.20）</b> + <b>双池至少命中其一（池A 超跌 ret20≤-7.31% / 池B 趋势 ADX14≥27.9，各自独立成池）</b> + 首板次日低开 gap∈[-5%,-2%] + 止盈 8%/2 天</div>\\n\'
            f\'<div class="sub" style="color:#059669">✅ <b>R-daban-opt-0915 实测（修正口径：真实 amount + 严格 rel_pos）</b>：线上基底 692 笔 +0.57% → 双池并集 396 笔 +1.19%（池A 单独最强 10/10 年正）；差窗口 2024-05 后 并集 +0.35% vs 基底 -0.40%。<b>验证门基准随口径切换为并集（56.1%/+1.19%/tp25.0%），新口径独立计数</b></div>\\n\'
            f\'<div class="bt-grid">{c1}</div>\\n</div>\')''', "bt_a5_card")

# B) KPI 闸文本
rep('<div class="s">基准 {bench.get("mean_net", "—"):+.2f}% · 闸 &gt;-0.5%</div>',
    '<div class="s">基准 {bench.get("mean_net", "—"):+.2f}% · 闸 &gt;+0.5%</div>', "kpi-mean")
rep('<div class="s">基准 {bench.get("tp_ratio", "—")}% · 闸 [12,32]%</div>',
    '<div class="s">基准 {bench.get("tp_ratio", "—")}% · 闸 [15,35]%</div>', "kpi-tp")

# C) 已平仓 KPI 加 v1 归档
rep('''    kpis.append(f'<div class="kpi"><div class="l">已平仓信号</div><div class="v">{st.get("n", 0)}<span style="font-size:13px;color:var(--faint)">/30</span></div><div class="s">触发验证门判定</div></div>')''',
    '''    _v1n = st.get("v1_n", 0)
    _v1s = f' · v1 归档 {_v1n} 笔' if _v1n else ''
    kpis.append(f'<div class="kpi"><div class="l">已平仓信号（新口径）</div><div class="v">{st.get("n", 0)}<span style="font-size:13px;color:var(--faint)">/30</span></div><div class="s">触发验证门判定{_v1s}</div></div>')''', "kpi-closed")

# D) 观察清单加池列
rep('''         _txt_td(w["sb_date"]), _num_td(w.get("rel_pos"), 2), _txt_td(f'{w.get("amt", 0)/1e4:.0f}'),''',
    '''         _txt_td(w["sb_date"]), _txt_td("/".join(w.get("pools", [])) or "—"), _num_td(w.get("rel_pos"), 2), _txt_td(f'{w.get("amt", 0)/1e4:.0f}'),''', "wl-cells")
rep('''("sbdate","首板日"),("relpos","相对位置"),("amt","成交额(万)"),("gate","过闸")''',
    '''("sbdate","首板日"),("pools","滤网池"),("relpos","相对位置"),("amt","成交额(万)"),("gate","过闸")''', "wl-head")

# E) 持仓加池列
rep('''         _txt_td(p["entry_date"]), _num_td(p["entry_px"], 2), _pct_td(p.get("gap")*100, 2),
         _txt_td(f'T+{p.get("exit_stage", 1)}'),''',
    '''         _txt_td(p["entry_date"]), _num_td(p["entry_px"], 2), _pct_td(p.get("gap")*100, 2),
         _txt_td("/".join(p.get("pools", [])) or "v1"), _txt_td(f'T+{p.get("exit_stage", 1)}'),''', "pos-cells")
rep('''("entrypx","入场价"),("gap","低开"),("stage","出场阶段")''',
    '''("entrypx","入场价"),("gap","低开"),("pools","滤网池"),("stage","出场阶段")''', "pos-head")

# F) 已平仓加池列
rep('''         _txt_td(REASON_CN.get(p["exit_reason"], p["exit_reason"] or "—")),
         _pct_td(p.get("net_ret", 0)*100, 2),''',
    '''         _txt_td(REASON_CN.get(p["exit_reason"], p["exit_reason"] or "—")),
         _txt_td("/".join(p.get("pools", [])) or "v1"),
         _pct_td(p.get("net_ret", 0)*100, 2),''', "closed-cells")
rep('''("reason","原因"),("netret","净收益")''',
    '''("reason","原因"),("pools","滤网池"),("netret","净收益")''', "closed-head")

# G) 系统头
rep('''<span class="badge badge-auto" style="background:#059669;color:#fff">✅ 过闸打板族（G3_M3 牛熊双过）· 模拟盘观察中</span>
<span class="badge badge-auto">信号 = 首板次日低开 2-5% + 相对位置≤0.5 + 成交额≥5000万（生产预筛口径）</span>''',
    '''<span class="badge badge-auto" style="background:#059669;color:#fff">✅ v1.3 双池独立滤网（2026-09-15 上线）· 模拟盘观察中</span>
<span class="badge badge-auto">信号 = 首板次日低开 2-5% + rel_pos≤0.5 + 成交额≥5000万 + <b>双池至少命中其一（池A 超跌 / 池B 趋势）</b></span>''', "head-badges")
rep('''<div class="sys-head-note"><b>定位</b>：9/3 生产档位敏感性确认 <b>G3_M3（低位+空间≥20%）牛熊双过闸</b>（牛 n=78 wr51.3% +2.52% / 熊 n=104 wr55.8% +0.27%）；裸 rel_pos 不过闸；<b>生产预筛已接入 G3_M3 过闸族</b>（阶段1 = 首板 + rel_pos≤0.5 + <b>F3 空间因子 dist_high≥20%（ROOM_MIN=0.20）</b> + 成交额≥5000万 → 仅过闸族入观察清单）。模拟盘观察 30 信号/3 个月，通过前不改生产权重；G6 组 n&lt;30 禁止投产</div>''',
    '''<div class="sys-head-note"><b>定位</b>：<b>v1.3 双池独立滤网（2026-09-15 用户拍板替换生产口径）</b>——在生产预筛（首板 + rel_pos≤0.5 + F3 空间≥20% + 成交额≥5000万）之上叠加 <b>池A 超跌（ret20≤-7.31%）</b> 与 <b>池B 趋势（ADX14≥27.9）</b>，<b>两因子各自独立成池、不做共振交集</b>（回测：并集 396 笔 +1.19%/笔、胜率 56.1%、≈38.6 笔/年；池A 10/10 年正）。模拟盘验证门基准随口径切换、新口径独立计数（v1 旧口径 11 笔归档）；通过前不改实盘权重</div>''', "head-note")

# H) 涨停全景口径说明
rep('''<div class="sub">收盘涨幅 ≥9.5% 或封板标的（{zp_date} 收盘口径）· <b>✅ A5命中</b> = 首板 + 非一字 + rel_pos≤0.5 + F3空间≥20% + 成交额≥5000万（G3_M3 过闸族，明日低开 2-5% 则入场）· 纯观察，不构成交易信号</div>''',
    '''<div class="sub">收盘涨幅 ≥9.5% 或封板标的（{zp_date} 收盘口径）· <b>✅ A5命中</b> = 首板 + 非一字 + rel_pos≤0.5 + F3空间≥20% + 成交额≥5000万 + 双池至少命中其一（v1.3）· 纯观察，不构成交易信号</div>''', "zp-sub")

# I) 净值曲线卡文案
rep('''<div class="sub">回测组合复利 -72.2% 警示：边缘太薄（σ≈5%/日），净值曲线难看属正常，验证的是边缘是否存在而非盈利</div>''',
    '''<div class="sub">回测（v1.3 修正口径）：线上基底 5 槽位组合 +18.9%/回撤 −35.4%；双池并集 +39.7%/回撤 −8.7%（近似模拟）。净值曲线验证的是边缘是否存在而非盈利，小仓位实验形态</div>''', "curve-sub")

# J) 观察清单卡说明
rep('''<div class="sub">今日首板 · 明日低开 2-5% 则入场（与回测口径一致）· 当日涨跌幅为实时数据（早盘/尾盘/收盘更新），近一年/RSI/量比/MA5偏离为收盘口径</div>''',
    '''<div class="sub">今日首板 · 双池至少命中其一（池A 超跌 / 池B 趋势）· 明日低开 2-5% 则入场 · 当日涨跌幅为实时数据，近一年/RSI/量比/MA5偏离为收盘口径</div>''', "wl-sub")

open(P, "w", encoding="utf-8").write(src)
print("PATCHED build_dual_system:", ok)
print("总计:", len(ok))
