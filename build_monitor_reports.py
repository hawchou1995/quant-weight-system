# -*- coding: utf-8 -*-
"""标的监控报告总页：34 只标的各一份监控报告（信号/因子/K线/交易史/建议），锚点直达。"""
import json
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import sys
sys.path.insert(0, str(BASE))
from ui_components import THEME_CSS, NAV_HTML, COMMON_JS

js_src = (BASE / "enhanced_data.js").read_text(encoding="utf-8")
DATA = json.loads(js_src[len("window.ENH = "):-1])
details = DATA["details"]

def tier_pill(t):
    cls = {"满仓加仓": "pill-full", "轻仓加仓": "pill-add", "观望": "pill-watch", "减至半仓": "pill-cut", "清仓": "pill-clear"}.get(t, "pill-watch")
    return f'<span class="pill {cls}">{t}</span>'

def kline_svg(kl, code):
    """K线改为 JS 容器渲染（数据在 enhanced_data.js，HTML 瘦身）"""
    if not kl:
        return '<div class="note">无K线</div>'
    return f'<div class="kline-box" data-code="{code}" style="background:var(--card2);border-radius:10px;min-height:160px"></div>'

def action_for(d):
    return {"满仓加仓": "持有至目标仓位", "轻仓加仓": "可加至目标仓位", "观望": "持有不加 / 观望",
            "减至半仓": "减至半仓", "清仓": "清仓离场"}.get(d["tier"], "—")

def render_trades(ts, label):
    if not ts:
        return f'<div class="note">{label}：未交易过此标的</div>'
    h = f'<table><tr><th>买入</th><th>卖出</th><th>收益</th><th>持有</th></tr>'
    for t in ts[-6:]:
        cls = "up" if t["pct"] > 0 else "down"
        h += f'<tr><td>{t["e"]}</td><td>{t["x"]}</td><td class="{cls}">{t["pct"]:+.1f}%</td><td>{t["days"]}天</td></tr>'
    return h + "</table>"

reports_html = ""
for c, d in sorted(details.items(), key=lambda kv: -kv[1]["score"]):
    f = d["factors"]
    chg_txt = f'{d["chg"]:+.2f}%' if d["chg"] is not None else "—"
    chg_cls = "up" if (d["chg"] or 0) > 0 else "down"
    ret_txt = f'{d["ret_1y"]:+.0f}%' if d["ret_1y"] is not None else "—"
    chg_tier = f'<span class="{"pill-chg-up" if d["tier"] in ("满仓加仓", "轻仓加仓") else "pill-chg-down"}">{d["tier_prev"]}→{d["tier"]}</span>' if d["tier_prev"] and d["tier_prev"] != d["tier"] else '<span style="color:var(--faint)">不变</span>'
    bars = "".join(
        f'<div class="fbar"><div class="fl"><span>{lbl}</span><b>{v}</b></div><div class="track"><div class="fill" style="width:{v}%"></div></div></div>'
        for lbl, v in [("动量", f["mom"]), ("趋势", f["trend"]), ("Aroon", f["aroon"]), ("量价", f["vp"])])
    reports_html += f'''
<div class="card" id="{c}">
<h2>{d["name"]} <span style="font-size:13px;color:var(--faint);font-weight:400">{d["code"]}</span>
<span class="board-tag">{d["board"]}</span> <span class="board-tag">{d["industry"]}</span>
<span style="margin-left:auto;display:inline-flex;gap:8px">{tier_pill(d["tier"])} {chg_tier}</span></h2>
<div class="sub">{d["biz"]} ｜ 建议：<b>{action_for(d)}</b>（回测体系信号，仅供参考）</div>
<div class="kpis">
<div class="kpi"><div class="l">现价</div><div class="v">{d["px"]:.2f}</div><div class="s">{chg_txt}（当日）</div></div>
<div class="kpi"><div class="l">近一年</div><div class="v {chg_cls}">{ret_txt}</div><div class="s">—</div></div>
<div class="kpi"><div class="l">权重分</div><div class="v">{d["score"]:.1f}</div><div class="s">{tier_pill(d["tier"])}</div></div>
<div class="kpi"><div class="l">RSI(14)</div><div class="v">{d["rsi"]:.0f}</div><div class="s">{"超买" if d["rsi"] >= 85 else "正常" if d["rsi"] >= 30 else "超卖"}</div></div>
</div>
<div class="factor-bars">{bars}</div>
<div class="two-col" style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
<div><h4>K线（近 250 日 · 红涨绿跌）</h4>{kline_svg(d["kline"], c)}</div>
<div>
<h4>v9-auto 交易史</h4>{render_trades(d["trades"]["v9_auto"], "v9-auto")}
<h4>v8-lite 交易史</h4>{render_trades(d["trades"]["v8_lite"], "v8-lite")}
</div></div>
</div>'''

html = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>标的监控报告（2026-08-14）</title>
<style>{THEME_CSS}
h4{{margin:10px 0 6px;font-size:13px;color:var(--sub)}}
.two-col h4{{margin-top:0}}
</style></head><body>
{NAV_HTML}
<div class="container">
<div class="card" id="overview">
<h2>📈 标的监控报告 <span class="badge badge-auto">2026-08-14 收盘口径</span></h2>
<div class="sub">34 只监控标的 · 每份报告 = 当前信号（档位/得分/因子拆分）+ K线 + 两体系交易史 + 建议动作 · 顶部「标的报告」下拉可直达任意标的</div>
<div class="rule-box"><b>阅读指引</b>：档位 = 满仓加仓(≥75) / 轻仓加仓(≥60) / 观望(≥45) / 减至半仓(≥30) / 清仓(&lt;30)；建议动作为信号解读，执行与否由你决定；卖出闸门：移动止损 + 指数破位（v9: MA150 / v8: MA200）。</div>
</div>
{reports_html}
</div>
<script src="enhanced_data.js"></script>
<script>{COMMON_JS}</script>
</body></html>"""

out = BASE / "monitor_reports.html"
out.write_text(html, encoding="utf-8")
print(f"标的监控报告已生成: {out} ({out.stat().st_size/1024:.0f} KB)")
