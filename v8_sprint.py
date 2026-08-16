# -*- coding: utf-8 -*-
"""
v8 冲刺网格：F7 邻域微调（目标夏普 ≥0.8）
F7 = Top20/H42/择时/止损20%/价格≥2/动量>0/波动<60%
微调维度：动量门槛、波动上限、止损、持有期、TopN
"""
import os
import sys, json, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v8_enhance2 as E

pool = E.load_pool() if hasattr(E, "load_pool") else E.V.load_pool()
pool = E.pool

def run_case(label, **kw):
    t0 = time.time()
    eq, trades = E.run_v8_single_timing(pool=pool, **kw)
    s = E.V.summary(eq, trades)
    s["seconds"] = round(time.time() - t0, 0)
    s["label"] = label
    print(f"[{label}] {s['seconds']}s | 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% "
          f"| 回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']}", flush=True)
    return s

results = {}
F7 = dict(top_n=20, hold_days=42, use_timing=True, stop_loss=0.20,
          min_price=2.0, min_mom=0.0, max_vol=0.60)

# 动量门槛微调
for mm in [0.05, 0.10, 0.20]:
    results[f"G1_动量>{mm}"] = run_case(f"G1_动量>{mm}", **{**F7, "min_mom": mm})
# 波动上限微调
for mv in [0.50, 0.55, 0.70]:
    results[f"G2_波动<{int(mv*100)}%"] = run_case(f"G2_波动<{int(mv*100)}%", **{**F7, "max_vol": mv})
# 止损微调
for sl in [0.18, 0.22]:
    results[f"G3_止损{int(sl*100)}%"] = run_case(f"G3_止损{int(sl*100)}%", **{**F7, "stop_loss": sl})
# 持有期微调
for hd in [35, 49, 63]:
    results[f"G4_持有{hd}"] = run_case(f"G4_持有{hd}", **{**F7, "hold_days": hd})
# TopN 微调
for tn in [15, 25, 30]:
    results[f"G5_Top{tn}"] = run_case(f"G5_Top{tn}", **{**F7, "top_n": tn})
# 动量权重提升（mom50）
results["G6_动量权重50"] = run_case("G6_动量权重50", **{**F7, "w_mom": 0.50, "w_trend": 0.20, "w_aroon": 0.15, "w_vp": 0.15})
# 综合最优猜测：动量>0.05 + 波动<55% + 止损20% + H42 + Top20
results["G7_综合"] = run_case("G7_综合", **{**F7, "min_mom": 0.05, "max_vol": 0.55})
# 综合2：动量>0.10 + 波动<55% + 止损18%
results["G8_综合2"] = run_case("G8_综合2", **{**F7, "min_mom": 0.10, "max_vol": 0.55, "stop_loss": 0.18})

with open("v8_sprint_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\n===== 冲刺网格汇总（按夏普排序）=====")
for k, v in sorted(results.items(), key=lambda kv: -(kv[1].get("sharpe") or 0)):
    ok = "✅达标" if (v.get("sharpe") or 0) >= 0.8 and (v.get("max_drawdown_pct") or -99) > -30 else ""
    print(f"{k:<16} 收益 {v.get('total_return_pct')}% | 年化 {v.get('annual_return_pct')}% | 回撤 {v.get('max_drawdown_pct')}% | 夏普 {v.get('sharpe')} | 交易 {v.get('total_trades')} {ok}")