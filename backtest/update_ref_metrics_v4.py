# -*- coding: utf-8 -*-
"""更新 ref_metrics.json 为 v4 选型（量价三件套补丁式）回测结果：
- combined ← v4 选型 27 池组合汇总
- items[27池标的].bt/buyhold ← v4 选型 per-symbol 完整指标
- 非 27 池标的（监控池独有 15 只）保留旧 fallback 数据并标注
"""
import json, os, sys
from datetime import datetime

sys.path.insert(0, r"D:/Documents/Workbuddy/股票基金/_quant_weight_ref")
BASE = r"D:/Documents/Workbuddy/股票基金/行情监控"
import weight_system_backtest_v4 as v3

# ---- 1. v3 选型回测（仅布林位置分 / 权重甲）----
print("运行 v4 选型回测（量价三件套补丁式，权重甲）...")
idx = v3.load_index("000300")
market_state = v3.build_market_state(idx) if v3.USE_MARKET_GATE else {}
bb_coef = v3.build_bull_bear_coef(idx)

# 开关：v4 选型 = 量价三件套补丁式（布林位置分 + 地量天量 + 纯量价背离 + RSI背离）
v3.USE_MA_TRIPLE = False
v3.USE_BOLL_POS = True
v3.USE_RESO_PATCH = False
v3.USE_BULL_BEAR = False
v3.USE_EXTREME_VOL = True
v3.USE_PDV = True
v3.USE_RSI_DIV = True
v3.SCORE_MODE = "patch"
weights = v3.WT_A

results = {}
all_trades = []
combined_equity = {}
for sector, members in v3.SECTOR_POOL.items():
    for code, nm, typ, market, news_level in members:
        df = v3.load_data(code)
        eq_w, tr_w, _ = v3.run_backtest(df, news_level, market_state, bb_coef, weights, strategy="weight")
        eq_b, tr_b, _ = v3.run_backtest(df, news_level, market_state, bb_coef, weights, strategy="bh")
        sum_w = v3.compute_summary(eq_w, tr_w)
        sum_b = v3.compute_summary(eq_b, tr_b)
        norm = []
        if eq_w:
            base = eq_w[0]["value"]
            for p in eq_w:
                norm.append({"date": p["date"], "value": round(100 * p["value"] / base, 4)})
        all_trades.extend(tr_w)
        results[code] = {"sector": sector, "name": nm, "weight": sum_w, "buyhold": sum_b}
        for p in norm:
            combined_equity.setdefault(p["date"], []).append(p["value"])

combo = []
for date in sorted(combined_equity.keys()):
    vals = combined_equity[date]
    combo.append({"date": date, "value": round(sum(vals) / len(vals), 4)})
combo_summary = v3.compute_summary(combo, all_trades)
print(f"v4 选型组合：+{combo_summary['total_return_pct']}% / 回撤 {combo_summary['max_drawdown_pct']}% / "
      f"夏普 {combo_summary['sharpe']} / 胜率 {combo_summary['win_rate_pct']}% / {combo_summary['total_trades']} 笔")

# ---- 2. 更新 ref_metrics.json ----
path = os.path.join(BASE, "ref_metrics.json")
with open(path, encoding="utf-8") as f:
    rm = json.load(f)

# combined
rm["combined"] = combo_summary
rm["combined_window"] = "2024-01起·27池(9领域)·v4选型(量价三件套补丁式)"
rm["generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

# items：27 池标的更新 bt/buyhold
updated = 0
for code, r in results.items():
    if code not in rm["items"]:
        continue
    it = rm["items"][code]
    it["bt_window"] = "2024-01起·v3选型(布林位置分)"
    it["bt"] = r["weight"]
    it["buyhold_return_pct"] = r["buyhold"].get("total_return_pct")
    updated += 1
print(f"已更新 {updated} 个标的 bt/buyhold")

# 非 27 池标的标注（监控池独有，沿用旧 fallback）
fallback = [c for c in rm["items"] if c not in results]
print(f"保留旧 fallback 标的 {len(fallback)} 只：{sorted(fallback)}")
rm["fallback_v15_count"] = len(fallback)

with open(path, "w", encoding="utf-8") as f:
    json.dump(rm, f, ensure_ascii=False, indent=2)
print(f"OK: {path}")
