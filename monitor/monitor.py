# -*- coding: utf-8 -*-
"""
关注标的行情监控 v4 —— 权重系统驱动（quant-weight-system v1.4 融合版）
================================================================
- 信号判定：完全由六类加权打分（趋势30/动能25/量能15/超买超卖15/风控10/研报5）总分档位驱动
  （≥75 满仓加仓 / 60-74 轻仓加仓 / 45-59 观望 / 30-44 减至半仓 / <30 清仓；target_cap 单次上限50%）
- 置信度独立展示；档位变化跟踪；板块/行业/近一年涨跌/回测指标并入
- 输出：reports/<date>_监控报告.md + dashboard_data.json（看板数据）
"""
import json, os, sys, statistics

import weight_score

BASE = os.path.dirname(os.path.abspath(__file__))
WATCHLIST = os.path.join(BASE, "watchlist.json")
STATUS = os.path.join(BASE, "信号状态.json")
RAW_DIR = os.path.join(BASE, "raw_kline")
REPORT_DIR = os.path.join(BASE, "reports")
REF_METRICS = os.path.join(BASE, "ref_metrics.json")

INFO_FILE = os.path.join(BASE, "研报情报.json")
INDICES_FILE = os.path.join(BASE, "indices.json")
EVENTS_FILE = os.path.join(BASE, "events.json")
INFO_VIEW_LABEL = {"看多": "L1 看多", "观望": "L2 观望", "谨慎": "L3 谨慎", "看空": "L4 看空"}
VIEW_TO_LEVEL = {"看多": "L1", "观望": "L2", "谨慎": "L3", "看空": "L4"}

def load_events():
    try:
        with open(EVENTS_FILE, encoding="utf-8") as f:
            return {it["code"]: it["note"] for it in json.load(f)["items"]}
    except Exception:
        return {}

def market_state():
    """大盘状态三档 + 恐贪指数 FG（v5 投产：恐惧机会动态门槛）。
    沪深300 收盘 vs MA20——偏离 >+2% → strong；<0 → weak；否则 normal。
    FG：沪深300 日K 5 维滚动分位归一化（W=250），由 weight_score.compute_fg 计算。
    返回 (market_state, fg)。"""
    try:
        with open(INDICES_FILE, encoding="utf-8") as f:
            idx = json.load(f)["indexes"]
        rows = idx["000300"]["rows"]
        closes = [r["c"] for r in rows]
        if len(closes) < 20:
            return "normal", None
        ma20 = statistics.mean(closes[-20:])
        dev = (closes[-1] / ma20 - 1) * 100
        if dev > 2.0:
            ms = "strong"
        elif dev < 0:
            ms = "weak"
        else:
            ms = "normal"
        # FG：需要 OHLCV（indices.json 已合并 h/l/v）
        highs = [r.get("h") for r in rows]
        lows = [r.get("l") for r in rows]
        vols = [r.get("v") for r in rows]
        has_ohlcv = all(h is not None and l is not None and v is not None for h, l, v in zip(highs, lows, vols))
        if not has_ohlcv:
            return ms, None
        fg_res = weight_score.compute_fg(closes, highs, lows, vols)
        return ms, fg_res.get("fg")
    except Exception:
        return "normal", None

def load_info():
    try:
        with open(INFO_FILE, encoding="utf-8") as f:
            return {it["code"]: it for it in json.load(f)["items"]}
    except Exception:
        return {}

def load_ref():
    try:
        with open(REF_METRICS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"items": {}, "combined": {}}

def load_latest_raw():
    files = sorted(f for f in os.listdir(RAW_DIR) if f.endswith(".json"))
    if not files:
        sys.exit("raw_kline 目录为空")
    with open(os.path.join(RAW_DIR, files[-1]), encoding="utf-8") as f:
        return json.load(f)

def main():
    with open(WATCHLIST, encoding="utf-8") as f:
        watchlist = {it["code"]: it for it in json.load(f)}
    raw = load_latest_raw()
    info = load_info()
    ref = load_ref()
    events = load_events()
    mkt, fg = market_state()
    date = raw["snapshot_date"]

    rows_out = []
    for item in raw["items"]:
        code = item["code"]
        w = watchlist.get(code, {})
        name = item.get("name", w.get("name", code))
        itype = w.get("type", "")
        seq_raw = [(r["d"], r["c"], r["v"], r.get("h"), r.get("l")) for r in item["rows"]]
        seq = [x for x in seq_raw if x[2] > 0]
        today_ymd = date.replace("-", "")
        # 早盘快照修复（2026-08-12）：当日K线 v=0（仅竞价价/占位价）若被过滤，
        # 涨跌幅会静默退化成上一交易日（如 8/12 报告误显示 8/11 的 +6.73%）。
        # 当日K线存在且为末根时补回 seq，涨跌幅以当日价为准（占位价=昨收时显示 0）。
        if seq_raw and seq_raw[-1][0] == today_ymd and (not seq or seq[-1][0] != today_ymd):
            seq.append(seq_raw[-1])
        if len(seq) < 2:
            seq = seq_raw
        today_intraday = seq and seq[-1][0] == date.replace("-", "")
        last_d, last_c, last_v, last_h, last_l = seq[-1]
        prev_c = seq[-2][1]
        pct_chg = (last_c - prev_c) / prev_c * 100.0
        closes = [r[1] for r in seq]
        vols = [r[2] for r in seq]
        highs = [r[3] for r in seq if r[3] is not None] or None
        lows = [r[4] for r in seq if r[4] is not None] or None
        # 权重系统打分（唯一信号来源；市场弱势防御态调节门槛）
        iv = info.get(code)
        news_level = VIEW_TO_LEVEL.get(iv["view"]) if iv and iv.get("view") else None
        wscore = weight_score.evaluate(closes, highs, lows, vols, news_level=news_level,
                                       is_fund=(itype == "基金"), market_state=mkt, fg=fg)
        # 参考指标（回测/近一年/板块）
        rm = ref.get("items", {}).get(code, {})
        rows_out.append({
            "code": code, "name": name, "type": itype,
            "note": w.get("note", ""),
            "date": last_d, "close": last_c, "pct_chg": pct_chg,
            "weight": wscore,
            "market": rm.get("market", itype), "industry": w.get("industry") or rm.get("industry") or w.get("note", ""),
            "year_return": rm.get("year_return_pct"),
            "bt": rm.get("bt", {}), "bt_window": rm.get("bt_window"), "buyhold_return": rm.get("buyhold_return_pct"),
            "info_view": iv["view"] if iv else None,
            "info_source": iv["source"] if iv else None,
            "info_date": iv["date"] if iv else None,
            "info_points": iv["points"] if iv else [],
            "risk_note": events.get(code, ""),
            "group": "基金" if itype == "基金" else "股票/ETF",
            "today_intraday": today_intraday,
        })

    # 档位变化跟踪（对比上次操作档位）
    with open(STATUS, encoding="utf-8") as f:
        status = json.load(f)
    prev = status.get("actions", {})
    for r in rows_out:
        r["prev_action"] = prev.get(r["code"])
        r["changed"] = (prev.get(r["code"]) not in (None, r["weight"]["action"]))
    status["updated"] = date
    status["actions"] = {r["code"]: r["weight"]["action"] for r in rows_out}
    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

    # ---------- 看板数据 ----------
    dash = {
        "date": date, "note": raw.get("snapshot_note", ""),
        "intraday": any(r["today_intraday"] for r in rows_out),
        "market_state": mkt,
        "fg": fg,
        "combined": ref.get("combined", {}),
        "combined_window": ref.get("combined", {}).get("window", "2021-08起·100池") + "·" + ref.get("combined", {}).get("pool", "100池"),
        "weights": weight_score.WEIGHTS,
        "items": [{
            "code": r["code"], "name": r["name"], "type": r["type"],
            "market": r["market"], "industry": r["industry"],
            "close": round(r["close"], 2), "pct_chg": round(r["pct_chg"], 2),
            "year_return": round(r["year_return"], 1) if r["year_return"] is not None else None,
            "score": r["weight"]["total"],
            "conf": r["weight"]["conf"],
            "action": r["weight"]["action"],
            "prev_action": r["prev_action"], "changed": r["changed"],
            "comp": r["weight"]["comp"],
            "osc_detail": r["weight"].get("osc_detail"),
            "vol_detail": r["weight"].get("vol_detail"),
            "fg_info": r["weight"].get("fg_info"),
            "bt": r["bt"], "bt_window": r["bt_window"], "buyhold_return": r["buyhold_return"],
            "news": r["info_view"], "risk_note": r["risk_note"],
        } for r in rows_out],
    }
    dash_path = os.path.join(BASE, "dashboard_data.json")
    with open(dash_path, "w", encoding="utf-8") as f:
        json.dump(dash, f, ensure_ascii=False, indent=2)

    # ---------- md 报告（简化） ----------
    os.makedirs(REPORT_DIR, exist_ok=True)
    md_path = os.path.join(REPORT_DIR, f"{date}_监控报告.md")

    def fmt_pct(v, digits=2, sign=True):
        if v is None:
            return "—"
        return f"{v:+.{digits}f}%" if sign else f"{v:.{digits}f}%"

    def conf_label(c):
        return f"{c['level']}置信（覆盖{c['coverage']:.0%}）"

    lines = [
        f"# 关注标的行情监控报告（{date}）",
        "",
        f"> 数据时间点：{'盘中实时' if dash['intraday'] else '最近交易日收盘'}｜{raw.get('snapshot_note', '')}",
        "",
        f"> 市场状态：**{'防御态（weak）' if mkt == 'weak' else '正常态（normal）'}**——{'加仓门槛上调至 65 分、清仓阈值提前至 35 分' if mkt == 'weak' else '加仓门槛 60 分、清仓阈值 30 分'}（沪深300 相对 MA20 判定）",
        "",
        "## 一、权重系统与汇总表",
        "",
        "**权重系统（quant-weight-system v1.4）**：六类加权打分（趋势30/动能25/量能15/超买超卖15/风控10/研报5）→ 总分 0-100 → 满仓加仓(≥75)/轻仓加仓(60-74)/观望(45-59)/减至半仓(30-44)/清仓(<30)；稳健加减仓 = 目标制 + 单次上限 50%。置信度：覆盖率≥80% 且方向一致≥75% → 高。v2 增强：量价配合按高低位区分（A3）。",
        "",
        "| 标的 | 板块 | 现价 | 涨跌幅 | 近一年 | 权重总分 | 置信度 | 操作档位 | 档位变化 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for g in ("股票/ETF", "基金"):
        grp = [r for r in rows_out if r["group"] == g]
        if grp:
            lines.append(f"**{g}（{len(grp)} 只）**")
            lines.append("")
            for r in grp:
                change = f"{r['prev_action']} → **{r['weight']['action']}**" if r["changed"] else ("—" if not r["prev_action"] else r["weight"]["action"])
                lines.append(f"| {r['name']} {r['code']} | {r['market']} | {r['close']:.2f} | {fmt_pct(r['pct_chg'])} | {fmt_pct(r['year_return'])} | **{r['weight']['total']:.0f} 分** | {conf_label(r['weight']['conf'])} | **{r['weight']['action']}** | {change} |")
            lines.append("")

    lines += ["## 二、逐标的依据", ""]
    for g in ("股票/ETF", "基金"):
        grp = [r for r in rows_out if r["group"] == g]
        if grp:
            lines.append(f"### {g}")
            lines.append("")
            for r in grp:
                w = r["weight"]
                c = w["comp"]
                lines.append(f"#### {r['name']}（{r['code']}）[{r['market']}/{r['industry']}]")
                lines.append(f"- 数据日期：{r['date']}｜现价 {r['close']:.2f}｜涨跌幅 {fmt_pct(r['pct_chg'])}｜近一年 {fmt_pct(r['year_return'])}")
                lines.append(f"- 权重总分：**{w['total']:.1f} 分** → {w['action_desc']}")
                lines.append(f"- 六类分解：趋势 {c['trend']:.0f}｜动能 {c['momentum']:.0f}｜量能 {c['volume']:.0f}｜超买超卖 {c['osc']:.0f}｜风控 {c['risk']:.0f}｜研报 {c['news']:.0f}（权重 30/25/15/15/10/5）")
                lines.append(f"- 置信度：{conf_label(w['conf'])}｜方向一致 {w['conf']['agree_ratio']:.0%}")
                if r["bt"]:
                    bt = r["bt"]
                    lines.append(f"- 回测（2016-01~2026-08，100池）：收益 {fmt_pct(bt.get('total_return_pct'), 1)}｜最大回撤 {fmt_pct(bt.get('max_drawdown_pct'), 1)}（买入持有 {fmt_pct(r['buyhold_return'], 1)}）")
                prov = w["provenance"]
                src = f"K线[{prov['kline']['level']}级]"
                if prov.get("news"):
                    src += f" + 研报[{prov['news']['level']}级 {prov['news']['level_tag']}]"
                lines.append(f"- 数据溯源：{src}｜窗口 {prov['window']} 根｜{prov['note']}")
                if r["info_view"]:
                    lines.append(f"- 研报情报：{INFO_VIEW_LABEL[r['info_view']]}（{r['info_source']}，{r['info_date']}）")
                    for p in r["info_points"]:
                        lines.append(f"  - {p}")
                if r["risk_note"]:
                    lines.append(f"- 事件标注：{r['risk_note']}")
                lines.append("")

    lines += [
        "## 三、风险声明",
        "",
        "> ⚠️ 本报告由自动化规则生成，仅供个人参考，**不构成任何投资建议**。",
        "> 信号基于历史价格与量能的机械规则，未考虑基本面、消息面与个人持仓成本。",
        "> 最终投资决策由您自行判断，并承担全部盈亏责任。投资有风险，决策需谨慎。",
    ]
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"OK: {md_path}")
    print(f"OK: {dash_path}")
    for r in rows_out:
        print(f"  {r['name']:10s} [{r['market']}] {r['pct_chg']:+6.2f}%  近一年{fmt_pct(r['year_return'],1)}  权重{r['weight']['total']:.0f}分/{r['weight']['action']}（{r['weight']['conf']['level']}）")

if __name__ == "__main__":
    main()
