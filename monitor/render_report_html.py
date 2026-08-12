# -*- coding: utf-8 -*-
"""
监控报告 HTML 渲染（2026-08-11 起，配合 monitor.py v4 权重系统）
==============================================================
输入：dashboard_data.json（monitor.py 输出）+ 研报情报.json + raw_kline/<date>.json
输出：reports/<date>_监控报告.html（股票/ETF 与基金分两个汇总表，含研报情报列）
- 涨跌幅红涨绿跌（A 股习惯）；场外基金量能类退化，量能比显示 —
- 研报情报共振/背离判定：技术档位方向 vs 研报观点方向一致→共振强化、冲突→背离提示谨慎
用法：python render_report_html.py
"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.join(BASE, "dashboard_data.json")
INFO = os.path.join(BASE, "研报情报.json")
RAW_DIR = os.path.join(BASE, "raw_kline")
REPORT_DIR = os.path.join(BASE, "reports")

INFO_VIEW_LABEL = {"看多": "L1 看多", "观望": "L2 观望", "谨慎": "L3 谨慎", "看空": "L4 看空"}
BUY_ACTIONS = {"满仓加仓", "轻仓加仓"}
SELL_ACTIONS = {"减至半仓", "清仓"}


def res_map(direction, view):
    """共振/背离判定：direction = 技术方向(bull/bear/neutral)，view = 研报观点"""
    if view is None or direction == "neutral":
        return None
    view_bull = view == "看多"
    view_bear = view in ("谨慎", "看空")
    if direction == "bull":
        return "共振" if view_bull else ("背离" if view_bear else None)
    if direction == "bear":
        return "共振" if view_bear else ("背离" if view_bull else None)
    return None


def main():
    with open(DASH, encoding="utf-8") as f:
        dash = json.load(f)
    date = dash["date"]
    try:
        with open(INFO, encoding="utf-8") as f:
            info = {it["code"]: it for it in json.load(f)["items"]}
    except Exception:
        info = {}
    # 每个标的最后 K 线日期（数据日期）
    raw = None
    try:
        files = sorted(x for x in os.listdir(RAW_DIR) if x.endswith(".json"))
        with open(os.path.join(RAW_DIR, files[-1]), encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        pass
    last_d = {}
    if raw:
        for it in raw.get("items", []):
            if it.get("rows"):
                last_d[it["code"]] = it["rows"][-1].get("d", "")

    def cls(v):
        return "up" if v > 0 else ("down" if v < 0 else "flat")

    def fmt_pct(v, digits=2, sign=True):
        if v is None:
            return "—"
        return f"{v:+.{digits}f}%" if sign else f"{v:.{digits}f}%"

    def sig_badge(action):
        if action in BUY_ACTIONS:
            return f'<span class="sig buy">{action}</span>'
        if action in SELL_ACTIONS:
            return f'<span class="sig sell">{action}</span>'
        return f'<span class="sig hold">{action}</span>'

    def score_badge(score):
        cls_b = "buy" if score >= 60 else ("sell" if score < 45 else "flat")
        return f'<span class="bdg {cls_b}">{score:.0f} 分</span>'

    def conf_badge(conf):
        level = conf.get("level", "中")
        cls_b = {"高": "res-ok", "中": "flat"}.get(level, "flat")
        return f'<span class="bdg {cls_b}">{level}置信</span>'

    def news_badge(item):
        view = item.get("news")
        if not view:
            return '<span class="bdg miss">无研报</span>'
        label = INFO_VIEW_LABEL.get(view, view)
        cls_b = "buy" if view == "看多" else ("sell" if view in ("谨慎", "看空") else "flat")
        return f'<span class="bdg {cls_b}">{label}</span>'

    def action_dir(action):
        if action in BUY_ACTIONS:
            return "bull"
        if action in SELL_ACTIONS:
            return "bear"
        return "neutral"

    def change_html(r):
        if r.get("changed"):
            return f'<span class="change">{r["prev_action"]} → <b>{r["action"]}</b></span>'
        if not r.get("prev_action"):
            return "—"
        return r["action"]

    # ---------- 汇总表 ----------
    def table_html(group_items):
        rows = []
        for r in group_items:
            iv = info.get(r["code"])
            news_txt = news_badge(r)
            res = res_map(action_dir(r["action"]), r.get("news"))
            if res:
                cls_r = "res-ok" if res == "共振" else "res-warn"
                news_txt += f' <span class="bdg {cls_r}">{res}</span>'
            rows.append(
                "<tr>"
                f'<td><b>{r["name"]}</b><br><span class="sub">{r["code"]}</span></td>'
                f'<td>{r["close"]:.2f}</td>'
                f'<td class="{cls(r["pct_chg"])}">{fmt_pct(r["pct_chg"])}</td>'
                f'<td>{fmt_pct(r.get("year_return"), 1)}</td>'
                f'<td>{score_badge(r["score"])}</td>'
                f'<td>{conf_badge(r["conf"])}</td>'
                f'<td>{sig_badge(r["action"])}</td>'
                f'<td>{change_html(r)}</td>'
                f'<td>{news_txt}</td>'
                "</tr>"
            )
        return (
            f'<table><tr><th>标的</th><th>现价</th><th>涨跌幅</th><th>近一年</th>'
            f'<th>权重总分</th><th>置信度</th><th>操作档位</th><th>档位变化</th><th>研报情报</th></tr>'
            + "".join(rows) + "</table>"
        )

    items = dash["items"]
    stock_etf = [r for r in items if r["type"] != "基金"]
    funds = [r for r in items if r["type"] == "基金"]

    mkt_txt = "**防御态（weak）**" if dash["market_state"] == "weak" else "**正常态（normal）**"
    intraday_txt = "盘中实时（接近收盘）" if dash.get("intraday") else "最近交易日收盘"

    # ---------- 逐标的卡片 ----------
    cards = []
    for r in items:
        iv = info.get(r["code"])
        comp = r["comp"]
        d = last_d.get(r["code"], "")
        d_disp = f"{d[:4]}-{d[4:6]}-{d[6:]}" if d else "—"
        lines = [
            f'<div class="card"><h3>{r["name"]} <span class="sub">{r["code"]}</span></h3>',
            f'<p class="meta">数据日期 {d_disp} ｜ 现价 {r["close"]:.2f} ｜ 涨跌幅 <span class="{cls(r["pct_chg"])}">{fmt_pct(r["pct_chg"])}</span> ｜ 近一年 {fmt_pct(r.get("year_return"), 1)} ｜ {r["market"]}/{r["industry"]}</p>',
            f'<p class="meta">权重总分：{score_badge(r["score"])} → <b>{r["action"]}</b>（前值 {r["prev_action"] or "—"}） ｜ 置信度：{conf_badge(r["conf"])}</p>',
            f'<p class="meta" style="margin-left:12px">· 六类分解：趋势 {comp["trend"]:.0f}｜动能 {comp["momentum"]:.0f}｜量能 {comp["volume"]:.0f}｜超买超卖 {comp["osc"]:.0f}｜风控 {comp["risk"]:.0f}｜研报 {comp["news"]:.0f}（权重 30/25/15/15/10/5）</p>',
        ]
        if r.get("bt"):
            bt = r["bt"]
            lines.append(
                f'<p class="meta" style="margin-left:12px">· 回测（target_cap）：收益 {fmt_pct(bt.get("total_return_pct"), 1)}｜胜率 {bt.get("win_rate_pct", 0):.0f}%｜最大回撤 {fmt_pct(bt.get("max_drawdown_pct"), 1)}｜{bt.get("total_trades", 0)} 笔（买入持有 {fmt_pct(r.get("buyhold_return"), 1)}）</p>'
            )
        if iv:
            res = res_map(action_dir(r["action"]), r.get("news"))
            res_badge = f'<span class="bdg res-ok">共振</span>' if res == "共振" else (
                f'<span class="bdg res-warn">背离</span>' if res == "背离" else "")
            lines.append(
                f'<p class="meta">研报情报：{news_badge(r)} {res_badge}（{iv.get("source", "")}，{iv.get("date", "")}）</p>'
            )
            if res == "共振":
                lines.append(
                    f'<p class="meta">共振判定：技术信号【{r["action"]}】与研报观点【{iv["view"]}】方向一致 → <b>共振，信号强化</b></p>'
                )
            elif res == "背离":
                lines.append(
                    f'<p class="meta res-warn-t">共振判定：技术信号【{r["action"]}】与研报观点【{iv["view"]}】方向冲突 → <b>⚠ 背离，建议谨慎核实后再操作</b></p>'
                )
            for p in iv.get("points", []):
                lines.append(f'<p class="meta" style="margin-left:12px">· {p}</p>')
        if r.get("risk_note"):
            lines.append(f'<p class="meta" style="margin-left:12px">⚠ 事件标注：{r["risk_note"]}</p>')
        lines.append("</div>")
        cards.append("".join(lines))

    stock_cards = "".join(c for c, r in zip(cards, items) if r["type"] != "基金")
    fund_cards = "".join(c for c, r in zip(cards, items) if r["type"] == "基金")

    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>关注标的监控报告 {date}</title>
<style>
body {{ font-family: "Microsoft YaHei", sans-serif; margin: 24px auto; max-width: 1100px; background: #f7f8fa; color: #222; }}
h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; margin-top: 28px; border-left: 4px solid #2b6cb0; padding-left: 8px; }}
.note {{ color: #666; font-size: 13px; background: #eef2f7; padding: 8px 12px; border-radius: 6px; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
th, td {{ border: 1px solid #e2e8f0; padding: 8px 10px; font-size: 13px; text-align: center; }}
th {{ background: #f1f5f9; }}
.up {{ color: #d92d20; font-weight: 600; }} .down {{ color: #0f9d58; font-weight: 600; }} .flat {{ color: #666; }}
.sig {{ display: inline-block; padding: 2px 10px; border-radius: 12px; color: #fff; font-size: 12px; }}
.sig.buy {{ background: #d92d20; }} .sig.sell {{ background: #0f9d58; }} .sig.hold {{ background: #8a94a6; }}
.bdg {{ display: inline-block; padding: 1px 7px; border-radius: 4px; font-size: 11px; margin: 1px; white-space: nowrap; }}
.bdg.sell {{ background: #e8f5ec; color: #0f9d58; border: 1px solid #0f9d58; }}
.bdg.buy {{ background: #fdeceb; color: #d92d20; border: 1px solid #d92d20; }}
.bdg.miss {{ background: #f1f3f5; color: #8a94a6; border: 1px dashed #c3cad3; }}
.bdg.flat {{ background: #eef1f4; color: #6b7280; }}
.bdg.res-ok {{ background: #e8f5ec; color: #0f9d58; border: 1px solid #0f9d58; }}
.bdg.res-warn {{ background: #fef6e7; color: #b45309; border: 1px solid #b45309; }}
.res-warn-t {{ color: #b45309; }}
.sub {{ color: #8892a0; font-size: 11px; font-weight: normal; }}
.change {{ color: #b45309; }}
.card {{ background: #fff; border-radius: 8px; padding: 12px 16px; margin: 10px 0; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
.card h3 {{ margin: 0 0 6px; font-size: 15px; }}
.card .meta {{ margin: 0 0 8px; font-size: 12px; color: #555; }}
.card ul {{ margin: 0; padding-left: 20px; font-size: 13px; }}
.risk {{ background: #fef6e7; border: 1px solid #f0d9a8; border-radius: 8px; padding: 12px 16px; font-size: 13px; color: #6b4f1d; }}
</style></head><body>
<h1>关注标的行情监控报告（{date}）</h1>
<p class="note">数据时间点：{intraday_txt}｜{dash.get("note", "")}</p>
<h2>一、权重系统与汇总表</h2>
<p class="note">权重系统（quant-weight-system v1.4）：六类加权打分（趋势30/动能25/量能15/超买超卖15/风控10/研报5）→ 总分 0-100 → 满仓加仓(≥75)/轻仓加仓(60-74)/观望(45-59)/减至半仓(30-44)/清仓(&lt;30)；稳健加减仓 = 目标制 + 单次上限 50%。市场状态：{mkt_txt}。置信度：覆盖率≥80% 且方向一致≥75% → 高。</p>
<p style="margin:14px 0 6px;font-weight:600;font-size:14px">股票/ETF汇总表（{len(stock_etf)} 只）</p>
{table_html(stock_etf)}
<p style="margin:14px 0 6px;font-weight:600;font-size:14px">基金汇总表（{len(funds)} 只）</p>
{table_html(funds)}
<h2>二、逐标的依据</h2>
<h3 style="margin:18px 0 8px;font-size:15px">股票/ETF</h3>
{stock_cards}
<h3 style="margin:18px 0 8px;font-size:15px">基金</h3>
{fund_cards}
<h2>三、风险声明</h2>
<div class="risk">⚠️ 本报告由自动化规则生成，仅供个人参考，<b>不构成任何投资建议</b>。信号基于历史价格与量能的机械规则，未考虑基本面、消息面与个人持仓成本。最终投资决策由您自行判断，并承担全部盈亏责任。投资有风险，决策需谨慎。</div>
</body></html>"""

    os.makedirs(REPORT_DIR, exist_ok=True)
    out = os.path.join(REPORT_DIR, f"{date}_监控报告.html")
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(html)
    print(f"OK: {out}")


if __name__ == "__main__":
    main()
