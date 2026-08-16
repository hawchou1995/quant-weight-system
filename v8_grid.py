# -*- coding: utf-8 -*-
"""
v8 参数网格扫描：top_n × hold_days × timing × 因子权重
目标：夏普 ≥0.8、回撤 ≤30%
"""
import os
import sys, json, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v8_selector as V

pool = V.load_pool()
print(f"池: {len(pool)} 只\n")

def run_case(label, **kw):
    t0 = time.time()
    eq, trades = V.run_v8(pool=pool, **kw)
    s = V.summary(eq, trades)
    s["seconds"] = round(time.time() - t0, 0)
    s["label"] = label
    print(f"[{label}] {s['seconds']}s | 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% "
          f"| 回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']}", flush=True)
    return s

results = {}

# 网格 1：top_n × hold_days（择时开，默认权重）
for top_n in [10, 20, 30, 50]:
    for hold in [21, 42, 63]:
        lbl = f"T{top_n}_H{hold}"
        results[lbl] = run_case(lbl, top_n=top_n, hold_days=hold, use_timing=True)

# 网格 2：择时开关（Top20/H42）
results["T20_H42_NOTIMING"] = run_case("T20_H42_NOTIMING", top_n=20, hold_days=42, use_timing=False)

# 网格 3：因子权重变体（Top20/H42，择时开）
results["W_mom50"] = run_case("W_mom50", top_n=20, hold_days=42, use_timing=True,
    w_mom=0.50, w_trend=0.20, w_aroon=0.15, w_vp=0.15)
results["W_trend50"] = run_case("W_trend50", top_n=20, hold_days=42, use_timing=True,
    w_mom=0.25, w_trend=0.50, w_aroon=0.15, w_vp=0.10)
results["W_aroon40"] = run_case("W_aroon40", top_n=20, hold_days=42, use_timing=True,
    w_mom=0.30, w_trend=0.20, w_aroon=0.40, w_vp=0.10)

with open("v8_grid_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\n===== 网格汇总（按夏普排序）=====")
for k, v in sorted(results.items(), key=lambda kv: -(kv[1].get("sharpe") or 0)):
    flag = "✅" if (v.get("sharpe") or 0) >= 0.8 and (v.get("max_drawdown_pct") or -99) > -30 else ""
    print(f"{k:<16} 收益 {v.get('total_return_pct')}% | 年化 {v.get('annual_return_pct')}% | 回撤 {v.get('max_drawdown_pct')}% | 夏普 {v.get('sharpe')} | 交易 {v.get('total_trades')} {flag}")