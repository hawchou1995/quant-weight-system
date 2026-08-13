# -*- coding: utf-8 -*-
"""
任务2/3：逐标的详情多边形仪表盘看板生成器 v2（增强版）
========================================================
- 六角多边形仪表盘：X 轴正方向 0-100 刻度尺，外框角点=六类指标，分数连线成圈
- 中心总分保留 1 位小数（修复"总分永远没小数点"显示问题）
- 卡片增强（模仿推文「积极信号在积累」有价值内容）：
  · 操作建议（系统档位 → 明确动作 + 仓位建议）
  · 数据质量（置信度/覆盖率/回测胜率/数据窗口）
  · 买卖参考位表（现价/MA20/布林上轨/布林下轨/ATR 止损参考）
  · 信号热力图徽章（六类子分）
- A 股配色：红涨绿跌；深色仪表盘风格
输出：dist_per_symbol/polygon_dashboard.html
"""
import json, math, html, os, statistics

BASE = r"D:/Documents/Workbuddy/股票基金/逐标的详情看板_20260812"
DASH = json.load(open(r"D:/Documents/Workbuddy/股票基金/行情监控/dashboard_data.json", encoding="utf-8"))
ITEMS = DASH["items"]
REFS = json.load(open(os.path.join(BASE, "_ref_prices.json"), encoding="utf-8"))
FG = DASH.get("fg")

# 操作建议映射（系统档位 → 动作 + 仓位口径）
ADVICE = {
    "满仓加仓": ("积极加仓", "目标仓位上探；单次最多调整 50% 仓位（稳健增强）"),
    "轻仓加仓": ("分批加仓", "轻仓起步；单次最多调整 50% 仓位，回踩不破再补"),
    "观望": ("持有观望", "维持现状，等待总分突破 60 或跌破 45 再动"),
    "减至半仓": ("减至半仓", "减仓至半仓；若跌破清仓阈值则全部离场"),
    "清仓": ("清仓离场", "全部卖出；风险优先，不恋战"),
}

def advice_for(item):
    act = item["action"]
    if act in ADVICE:
        head, body = ADVICE[act]
    else:
        head, body = act, "维持现状"
    return head, body

# ---------- 多边形仪表盘 SVG ----------
def svg_radar(item, size=300):
    cx = cy = size / 2
    R = size * 0.40
    n = 6
    cats = ["trend", "momentum", "volume", "osc", "risk", "news"]
    labels = ["趋势", "动能", "量能", "超买超卖", "风控", "研报"]
    comp = item["comp"]
    score = item["score"]
    angles = [math.radians(i * 60) for i in range(n)]

    def pt(r, ang):
        return (cx + r * math.cos(ang), cy - r * math.sin(ang))

    parts = []
    for ring in [0.2, 0.4, 0.6, 0.8, 1.0]:
        pts = " ".join(f"{pt(R*ring, a)[0]:.1f},{pt(R*ring, a)[1]:.1f}" for a in angles)
        stroke = "#2a3a52" if ring < 1.0 else "#3d5575"
        parts.append(f'<polygon points="{pts}" fill="none" stroke="{stroke}" stroke-width="{1.5 if ring==1.0 else 1}"/>')
    for a in angles:
        x0, y0 = pt(0, a); x1, y1 = pt(R, a)
        parts.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" stroke="#22324a" stroke-width="1"/>')
    xs, ys = cx, cy
    xe, ye = cx + R, cy
    parts.append(f'<line x1="{xs:.1f}" y1="{ys:.1f}" x2="{xe:.1f}" y2="{ye:.1f}" stroke="#ffd500" stroke-width="2"/>')
    for v in [20, 40, 60, 80, 100]:
        rv = R * v / 100
        tx, ty = cx + rv, cy + 4
        parts.append(f'<text x="{tx:.1f}" y="{ty:.1f}" fill="#ffd500" font-size="7" text-anchor="middle">{v}</text>')
    vals = [comp.get(c, 50) for c in cats]
    # 研报维度：对称贡献分（±1.0/±1.5/0）→ 0-100 显示标尺映射（0→50 中性，+1.0→70，-1.0→30，-1.5→20）
    if abs(comp.get("news", 0) or 0) <= 5:
        vals[5] = 50 + comp["news"] * 20
    spts = " ".join(f"{pt(R*max(2,min(100,vals[i]))/100, angles[i])[0]:.1f},{pt(R*max(2,min(100,vals[i]))/100, angles[i])[1]:.1f}" for i in range(n))
    sc = score
    if sc >= 75: fill = "rgba(255,77,77,0.30)"; stroke = "#ff4d4d"
    elif sc >= 60: fill = "rgba(255,140,60,0.28)"; stroke = "#ff8c3c"
    elif sc >= 45: fill = "rgba(255,200,80,0.22)"; stroke = "#ffc850"
    elif sc >= 30: fill = "rgba(80,190,120,0.22)"; stroke = "#50be78"
    else: fill = "rgba(60,160,220,0.25)"; stroke = "#3ca0dc"
    parts.append(f'<polygon points="{spts}" fill="{fill}" stroke="{stroke}" stroke-width="2.5" stroke-linejoin="round"/>')
    for i in range(n):
        v = vals[i]
        xr, yr = pt(R * max(2, min(100, v)) / 100, angles[i])
        parts.append(f'<circle cx="{xr:.1f}" cy="{yr:.1f}" r="3" fill="{stroke}"/>')
        lx, ly = pt(R * 1.16, angles[i])
        anchor = "middle"
        if abs(angles[i]) < 0.3: anchor = "start"
        elif abs(angles[i] - math.pi) < 0.3: anchor = "end"
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" fill="#c8d6ea" font-size="9" text-anchor="{anchor}" font-weight="600">{labels[i]}</text>')
        vx, vy = pt(R * 1.16, angles[i])
        vy2 = vy + 10
        parts.append(f'<text x="{vx:.1f}" y="{vy2:.1f}" fill="#8fa3c0" font-size="8" text-anchor="{anchor}">{v:.1f}</text>')
    # 中心总分（保留 1 位小数）
    parts.append(f'<text x="{cx:.1f}" y="{cy-2:.1f}" fill="#ffffff" font-size="24" font-weight="800" text-anchor="middle">{score:.1f}</text>')
    parts.append(f'<text x="{cx:.1f}" y="{cy+14:.1f}" fill="#8fa3c0" font-size="8" text-anchor="middle">总分(0-100)</text>')
    return f'<svg viewBox="0 0 {size} {size}" width="100%" style="max-width:{size}px">{chr(10).join(parts)}</svg>'

# ---------- 卡片 ----------
def color_of_chg(p):
    if p is None: return "#8fa3c0"
    return "#ff4d4d" if p > 0 else ("#50be78" if p < 0 else "#c8d6ea")

def badge(action):
    m = {"满仓加仓": ("#ff4d4d", "满仓加仓"), "轻仓加仓": ("#ff8c3c", "轻仓加仓"),
         "观望": ("#ffc850", "观望"), "减至半仓": ("#50be78", "减至半仓"), "清仓": ("#3ca0dc", "清仓")}
    bg, txt = m.get(action, ("#5a6b85", action))
    return f'<span class="badge" style="background:{bg}22;color:{bg};border:1px solid {bg}55">{txt}</span>'

def comp_detail(item):
    od = item.get("osc_detail") or {}
    vd = item.get("vol_detail") or {}
    rows = []
    rows.append(f"RSI {od.get('rsi','—')} · KDJ {od.get('kdj','—')} · 布林 {od.get('boll','—')}" +
                (f" · {od.get('rsi_div','')}" if od.get('rsi_div') else ""))
    if vd.get("vr") is not None:
        rows.append(f"量比 {vd['vr']} · 量比分 {vd.get('vr_score','—')} · 价量配合 {vd.get('pv_score','—')}" +
                    (f" · {vd.get('extreme','')}" if vd.get('extreme') else "") +
                    (f" · {vd.get('pdv','')}" if vd.get('pdv') else ""))
    return "｜".join(rows) if rows else "—"

def ref_table(item):
    """买卖参考位表（仿推文 put/call 价差表形态）：参考位/现价/支撑/阻力/止损。"""
    ref = REFS.get(item["code"])
    if not ref:
        return "—（数据不足 20 根）"
    c = item.get("close")
    ma20, bup, bdn, atr, stop = ref["ma20"], ref["boll_up"], ref["boll_dn"], ref["atr"], ref["stop"]
    pos = "上方" if c > ma20 else "下方"
    return (f"现价 <b>{c}</b>（MA20 {pos} {ma20:.2f}）｜支撑 <b style='color:#50be78'>{bdn:.2f}</b>"
            f"｜阻力 <b style='color:#ff4d4d'>{bup:.2f}</b>｜ATR {atr:.2f}｜2×ATR 止损 <b style='color:#ffb3a0'>{stop:.2f}</b>")

def data_quality(item):
    conf = item["conf"]
    bt = item.get("bt") or {}
    cov = conf.get("coverage", 0)
    ag = conf.get("agree_ratio", 0)
    parts = [f"置信度 <b>{conf['level']}</b>（覆盖 {cov*100:.0f}% / 方向一致 {ag*100:.0f}%）"]
    if bt.get("win_rate_pct") is not None:
        parts.append(f"回测胜率 {bt['win_rate_pct']:.1f}% / {bt.get('total_trades','—')} 笔 / 夏普 {bt.get('sharpe','—')}")
    if bt.get("total_return_pct") is not None:
        parts.append(f"回测总收益 {bt['total_return_pct']:+.1f}%")
    return "｜".join(parts)

def card(item):
    c = color_of_chg(item.get("pct_chg"))
    bt = item.get("bt") or {}
    news = item.get("news") or "无"
    news_color = {"看多": "#ff4d4d", "谨慎": "#ffc850", "看空": "#50be78"}.get(news, "#8fa3c0")
    risk = item.get("risk_note") or "—"
    radar = svg_radar(item)
    yr = item.get("year_return")
    yr_s = f"{yr:+.1f}%" if yr is not None else "—"
    pc = item.get("pct_chg")
    pc_s = f"{pc:+.2f}%" if pc is not None else "—"
    adv_head, adv_body = advice_for(item)
    fg_info = item.get("fg_info") or {}
    fg_s = ""
    if fg_info.get("fg") is not None:
        fg_s = (f"<span class='fgchip'>FG {fg_info['fg']:.1f}（恐惧）</span>"
                if fg_info['fg'] < 45 else
                (f"<span class='fgchip' style='color:#ffd500'>FG {fg_info['fg']:.1f}（中性）</span>"
                 if fg_info['fg'] <= 55 else
                 f"<span class='fgchip' style='color:#ff4d4d'>FG {fg_info['fg']:.1f}（贪婪）</span>"))
        if fg_info.get("mode"):
            fg_s += f"<span class='fgchip dim'>门槛 {fg_info['bw_eff']:.1f}/{fg_info['ss_eff']:.1f}</span>"
    return f'''
<div class="card">
  <div class="card-head">
    <div class="card-title">
      <span class="name">{html.escape(item["name"])}</span>
      <span class="code">{item["code"]} · {item.get("industry","")}</span>
    </div>
    <div class="card-quote">
      <span class="price" style="color:{c}">{item.get("close","—")}</span>
      <span class="chg" style="color:{c}">{pc_s}</span>
      <span class="yr">年内 {yr_s}</span>
    </div>
  </div>
  <div class="advice"><span class="adv-head" style="color:{'#ff4d4d' if item['action'] in ('满仓加仓','轻仓加仓') else ('#50be78' if item['action'] in ('减至半仓','清仓') else '#ffc850')}">◆ {adv_head}</span><span class="adv-body">{html.escape(adv_body)}</span></div>
  <div class="card-body">
    <div class="radar-wrap">{radar}</div>
    <div class="info">
      <div class="row"><span class="k">系统档位</span><span class="v">{badge(item["action"])} {fg_s}</span></div>
      <div class="row"><span class="k">操作建议</span><span class="v"><b>{adv_head}</b>——{html.escape(adv_body)}</span></div>
      <div class="row"><span class="k">数据质量</span><span class="v">{data_quality(item)}</span></div>
      <div class="row"><span class="k">买卖参考位</span><span class="v">{ref_table(item)}</span></div>
      <div class="row"><span class="k">研报情报</span><span class="v" style="color:{news_color}">{news}</span></div>
      <div class="row"><span class="k">超买超卖</span><span class="v">{comp_detail(item)}</span></div>
      <div class="row"><span class="k">回测绩效</span><span class="v">总收益 {bt.get("total_return_pct","—")}% · 回撤 {bt.get("max_drawdown_pct","—")}% · 胜率 {bt.get("win_rate_pct","—")}% · 夏普 {bt.get("sharpe","—")}</span></div>
      <div class="row risk"><span class="k">风险提示</span><span class="v">{html.escape(str(risk))}</span></div>
    </div>
  </div>
</div>'''

cards = "".join(card(it) for it in ITEMS)

up = sum(1 for it in ITEMS if (it.get("pct_chg") or 0) > 0)
down = sum(1 for it in ITEMS if (it.get("pct_chg") or 0) < 0)
buy = [it["name"] for it in ITEMS if it["action"] in ("满仓加仓", "轻仓加仓")]
hold = [it["name"] for it in ITEMS if it["action"] == "观望"]
fg_line = f"恐贪指数 FG <b style='color:#ffd500'>{FG:.1f}</b>（恐惧机会动态门槛：加仓≥60.9/清仓&lt;29.1）" if FG is not None else "FG 不可用"

html_page = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>逐标的详情 · 多边形仪表盘（{DASH.get("date","")}）</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0d1526; color:#c8d6ea; font-family:"Microsoft YaHei","PingFang SC",sans-serif; padding:24px; }}
  .header {{ display:flex; align-items:baseline; gap:16px; flex-wrap:wrap; margin-bottom:6px; }}
  .header h1 {{ font-size:22px; color:#fff; font-weight:800; }}
  .header .sub {{ color:#8fa3c0; font-size:13px; }}
  .header .date {{ color:#ffd500; font-size:14px; font-weight:600; }}
  .market {{ display:flex; gap:20px; flex-wrap:wrap; margin:10px 0 18px; padding:12px 16px; background:#111c33; border-radius:10px; border:1px solid #1e3050; }}
  .market .ms {{ color:#ffd500; font-size:15px; font-weight:700; }}
  .market .stat {{ color:#8fa3c0; font-size:12px; }}
  .market .stat b {{ color:#c8d6ea; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(500px,1fr)); gap:16px; }}
  .card {{ background:#111c33; border:1px solid #1e3050; border-radius:12px; padding:14px; transition:border .2s; }}
  .card:hover {{ border-color:#ffd50066; }}
  .card-head {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:6px; }}
  .card-title .name {{ font-size:16px; font-weight:700; color:#fff; }}
  .card-title .code {{ font-size:11px; color:#8fa3c0; margin-left:6px; }}
  .card-quote {{ text-align:right; }}
  .card-quote .price {{ font-size:17px; font-weight:800; }}
  .card-quote .chg {{ font-size:13px; font-weight:700; margin-left:6px; }}
  .card-quote .yr {{ display:block; font-size:11px; color:#8fa3c0; margin-top:2px; }}
  .advice {{ background:#16233d; border-left:3px solid #ffc850; border-radius:6px; padding:6px 10px; margin-bottom:8px; font-size:12px; }}
  .adv-head {{ font-weight:800; margin-right:8px; }}
  .adv-body {{ color:#a9b8d0; }}
  .card-body {{ display:flex; gap:14px; }}
  .radar-wrap {{ flex:0 0 220px; }}
  .info {{ flex:1; min-width:0; font-size:12px; }}
  .row {{ display:flex; gap:8px; padding:4px 0; border-bottom:1px dashed #1a2842; }}
  .row:last-child {{ border-bottom:none; }}
  .k {{ flex:0 0 64px; color:#8fa3c0; }}
  .v {{ color:#c8d6ea; line-height:1.5; }}
  .row.risk .v {{ color:#ffb3a0; }}
  .badge {{ display:inline-block; padding:2px 10px; border-radius:12px; font-size:11px; font-weight:700; }}
  .fgchip {{ display:inline-block; padding:1px 8px; border-radius:10px; font-size:10px; background:#0d1526; border:1px solid #2a3a52; color:#ff8c3c; margin-left:4px; }}
  .fgchip.dim {{ color:#8fa3c0; }}
  .footer {{ margin-top:20px; color:#6b7d99; font-size:11px; text-align:center; padding:12px; border-top:1px solid #1e3050; }}
  .footnote {{ color:#8fa3c0; font-size:11px; margin:6px 0 14px; }}
</style>
</head>
<body>
  <div class="header">
    <h1>逐标的详情 · 多边形仪表盘</h1>
    <span class="date">{DASH.get("date","")} 尾盘快照</span>
    <span class="sub">六角指标：趋势/动能/量能/超买超卖/风控/研报 · 分数连线成圈 · X 轴正方向 0-100 刻度</span>
  </div>
  <div class="market">
    <span class="ms">市场状态：{DASH.get("market_state","normal")}</span>
    <span class="stat">{fg_line}</span>
    <span class="stat">标的 <b>{len(ITEMS)}</b> · 上涨 <b style="color:#ff4d4d">{up}</b> · 下跌 <b style="color:#50be78">{down}</b></span>
    <span class="stat">加仓信号 <b style="color:#ff8c3c">{len(buy)}</b> · 观望 <b>{len(hold)}</b></span>
    <span class="stat">权重配置 趋势30/动能25/量能15/超买超卖15/风控10/研报5</span>
  </div>
  <div class="footnote">参考：公众号「东胜小猢狲」2026-08-07《积极信号在积累，指标持续向好+期权策略》恐贪看板风格——各指标滚动分位归一化（W=250日），多边形外框角点=指标，分数连线成圈。增强：操作建议 / 数据质量 / 买卖参考位（MA20·布林·ATR·2×ATR 止损）。</div>
  <div class="grid">{cards}</div>
  <div class="footer">⚠️ 本看板仅供个人研究参考，不构成投资建议。数据源：通达信 K 线 + 权重系统 v5（含 FG 恐贪动态门槛）；最终投资决策由用户自行判断并承担全部盈亏责任。</div>
</body>
</html>'''

out_path = os.path.join(BASE, "polygon_dashboard.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html_page)
print("written:", out_path, len(html_page), "bytes")
