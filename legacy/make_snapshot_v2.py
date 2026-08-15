# -*- coding: utf-8 -*-
"""v1.1 快照：8-07 与 8-10 两日建议 + 变动记录 + 临时行业标的参考"""
import sys, json
sys.path.insert(0, '.')
import pandas as pd
from weight_system_backtest import (
    load_data, compute_indicators, compute_total_score, UNIVERSE, WEIGHTS,
    BUY_STRONG, BUY_WEAK, SELL_WEAK, SELL_STRONG,
)

def action_label(total):
    """精细化档位：满仓加仓/轻仓加仓/观望/减至半仓/清仓（供变动记录对比）"""
    if total >= BUY_STRONG: return "满仓加仓"
    if total >= BUY_WEAK: return "轻仓加仓"
    if total < SELL_STRONG: return "清仓"
    if total < SELL_WEAK: return "减至半仓"
    return "观望"

def action_tier(total):
    """返回精细档位建议 + 说明（含 v1.4 仓位模型份额口径）"""
    from weight_system_backtest import POSITION_MODEL, CAP_PCT, STEP_PCT
    if POSITION_MODEL == "target_cap":
        share = f"单次最多调整 {CAP_PCT*100:.0f}% 仓位"
    elif POSITION_MODEL == "incremental":
        share = f"每次加仓={STEP_PCT*100:.0f}%总资产 / 减仓={STEP_PCT*100:.0f}%持有"
    else:
        share = "调整至目标仓位"
    if total >= BUY_STRONG: return "满仓加仓", f"满仓加仓（≥75 分，{share}）"
    if total >= BUY_WEAK: return "轻仓加仓", f"轻仓加仓（60-74 分，{share}）"
    if total < SELL_STRONG: return "清仓", f"清仓（<30 分，{share}）"
    if total < SELL_WEAK: return "减至半仓", f"减至半仓（30-44 分，{share}）"
    return "观望", "维持现状（45-59 分）"

def snapshot_at(df_full, target_date):
    """计算指定日期（或其前最近交易日）的信号"""
    d = compute_indicators(df_full)
    d = d[d["date"] <= pd.Timestamp(target_date)]
    if d.empty:
        return None
    row = d.iloc[-1]
    if pd.isna(row["ma20"]) or pd.isna(row["rsi"]):
        return None
    return row

def classify_market(code, typ):
    """按代码前缀细分板块（类型列展示用）：
    创业板 300/301 | 科创板 688 | 沪主板 600/601/603/605 | 深主板 000/001/002
    美股(05/06/09前缀)/港股(00700等5位)预留；ETF/基金保持原分类"""
    if typ == "ETF":
        return "ETF"
    if typ == "基金":
        return "基金"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith("688"):
        return "科创板"
    if code.startswith(("600", "601", "603", "605")):
        return "沪主板"
    if code.startswith(("000", "001", "002")):
        return "深主板"
    if len(code) == 6 and code.isdigit():
        if code[0] in ("0", "1", "2", "3") and typ == "美股":
            return "美股"
        if code[0] in ("0", "1", "2", "3", "4", "5") and typ == "港股":
            return "港股"
    return typ

def build_rows(target_date):
    rows = []
    for code, name, typ, market, news_level in UNIVERSE:
        df = load_data(code)
        row = snapshot_at(df, target_date)
        if row is None:
            rows.append({"code": code, "name": name, "type": classify_market(code, typ), "available": False})
            continue
        total, comp, conf = compute_total_score(row, news_level, is_fund=(typ == "基金"))
        act, desc = action_tier(total)
        # 数据溯源（方法论要点 1：数值+as-of+来源等级）
        provenance = {
            "as_of": str(row["date"].date()),
            "kline": {"source": "腾讯自选股接口(westock)" if typ != "基金" else "通达信基金净值(setcode=33)",
                      "level": "A", "note": "日线前复权" if typ != "基金" else "净值T-1"},
            "news": {"source": "vault研报情报L1-L3", "level": "B",
                     "note": news_level or "无情报（中性50）"},
            "indicators": {"source": "本地计算(向量化)", "level": "A",
                           "note": "MA/MACD/KDJ/RSI/ADX/ATR"},
        }
        rows.append({
            "code": code, "name": name, "type": classify_market(code, typ), "news_level": news_level or "-",
            "date": str(row["date"].date()),
            "close": round(float(row["close"]), 3),
            "pct_chg": round(float(row["pct_chg"]), 2) if not pd.isna(row["pct_chg"]) else None,
            "ma20": round(float(row["ma20"]), 3) if not pd.isna(row["ma20"]) else None,
            "ma20_dev": round(float(row["ma20_dev"]), 2) if not pd.isna(row["ma20_dev"]) else None,
            "rsi": round(float(row["rsi"]), 1) if not pd.isna(row["rsi"]) else None,
            "macd_hist": round(float(row["macd_hist"]), 4) if not pd.isna(row["macd_hist"]) else None,
            "k": round(float(row["k"]), 1) if not pd.isna(row["k"]) else None,
            "d": round(float(row["d"]), 1) if not pd.isna(row["d"]) else None,
            "adx": round(float(row["adx"]), 1) if not pd.isna(row["adx"]) else None,
            "atr_pct": round(float(row["atr_pct"]), 2) if not pd.isna(row["atr_pct"]) else None,
            "total_score": round(total, 1),
            "components": {k: round(v, 1) for k, v in comp.items() if k != "total"},
            "confidence": conf,
            "provenance": provenance,
            "action": act,
            "action_desc": desc,
        })
    return rows

# 8-07（上一交易日）与 8-10（今日）
rows_0807 = build_rows("2026-08-07")
rows_0810 = build_rows("2026-08-10")

# 合并变动记录
signals = []
prev_map = {r["code"]: r for r in rows_0807 if r.get("available", True)}
for r in rows_0810:
    prev = prev_map.get(r["code"])
    change = "-"
    if prev and prev.get("available", True):
        if prev["action"] != r["action"]:
            change = f"{prev['action']}➡️{r['action']}"
    r["prev_action"] = prev["action"] if prev and prev.get("available", True) else "-"
    r["change"] = change
    signals.append(r)

out = {
    "generated_at": "2026-08-10T18:50:00+08:00",
    "snapshot_dates": ["2026-08-07", "2026-08-10"],
    "weights": WEIGHTS,
    "thresholds": {"BUY_STRONG": BUY_STRONG, "BUY_WEAK": BUY_WEAK,
                   "SELL_WEAK": SELL_WEAK, "SELL_STRONG": SELL_STRONG},
    "signals": signals,
    "note": "变动记录 = 8-07 建议 ➡️ 8-10 建议；「-」表示建议未变",
}
with open("snapshot_20260810_v2.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"v1.1 快照已生成（{len(signals)} 标的），含变动记录")
print(f"{'标的':<14}{'8-07建议':>8}{'8-10建议':>8}{'变动':>12}{'8-10总分':>9}")
for s in signals:
    print(f"{s['name']}({s['code']})".ljust(16) + f"{s['prev_action']:>8}{s['action']:>8}{s['change']:>12}{s['total_score']:>9.1f}")
