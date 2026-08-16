# -*- coding: utf-8 -*-
"""
v8 增强网格：在最优基线（Top20/H42/择时）上叠加风控增强
目标：夏普 ≥0.8、回撤 ≤30%
增强项：回撤熔断（10/15/20%）、波动率目标仓位（0.12/0.15/0.18）、双均线快线（MA20/50/100）
"""
import os
import sys, json, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v8_selector as V

pool = V.load_pool()

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
BASE_KW = dict(top_n=20, hold_days=42, use_timing=True, w_mom=0.35, w_trend=0.25, w_aroon=0.20, w_vp=0.20)

# 基线（增强前）
results["E0_基线"] = run_case("E0_基线", **BASE_KW)

# 熔断扫描
for dc in [0.10, 0.15, 0.20]:
    kw = {**BASE_KW, "drawdown_circuit": dc}
    results[f"E1_熔断{int(dc*100)}%"] = run_case(f"E1_熔断{int(dc*100)}%", **kw)

# 波动率目标
for vt in [0.12, 0.15, 0.18]:
    kw = {**BASE_KW, "vol_target": vt}
    results[f"E2_波动目标{int(vt*100)}%"] = run_case(f"E2_波动目标{int(vt*100)}%", **kw)

# 双均线快线
for mf in [20, 50, 100]:
    kw = {**BASE_KW, "ma_fast": mf}
    results[f"E3_快线MA{mf}"] = run_case(f"E3_快线MA{mf}", **kw)

# 组合增强（熔断15% + 波动目标15% + 快线50）
kw = {**BASE_KW, "drawdown_circuit": 0.15, "vol_target": 0.15, "ma_fast": 50}
results["E4_组合增强"] = run_case("E4_组合增强", **kw)

# 组合增强 + 动量加权重
kw = {**BASE_KW, "w_mom": 0.50, "w_trend": 0.20, "w_aroon": 0.15, "w_vp": 0.15,
      "drawdown_circuit": 0.15, "vol_target": 0.15, "ma_fast": 50}
results["E5_组合+动量50"] = run_case("E5_组合+动量50", **kw)

with open("v8_enhance_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\n===== 增强网格汇总（按夏普排序）=====")
for k, v in sorted(results.items(), key=lambda kv: -(kv[1].get("sharpe") or 0)):
    ok = "✅达标" if (v.get("sharpe") or 0) >= 0.8 and (v.get("max_drawdown_pct") or -99) > -30 else ""
    print(f"{k:<16} 收益 {v.get('total_return_pct')}% | 年化 {v.get('annual_return_pct')}% | 回撤 {v.get('max_drawdown_pct')}% | 夏普 {v.get('sharpe')} | 交易 {v.get('total_trades')} {ok}")