# -*- coding: utf-8 -*-
"""v6 参数敏感性分析：评估调整权重/门槛/系数优化模型的可能性（数据说话）。
复用 weight_system_backtest_v6.py 的 run_experiment，跑参数网格。
"""
import importlib.util, sys, json, os

SPEC = r"D:/Documents/Workbuddy/股票基金/_quant_weight_ref/weight_system_backtest_v6.py"
spec = importlib.util.spec_from_file_location("v6sens", SPEC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

BASE_SW = {"ma_triple": False, "boll_pos": True, "reso_patch": False, "bull_bear": False,
           "extreme_vol": True, "pdv": True, "rsi_div": True, "score_mode": "patch"}

def scale_weight(base, key, delta):
    """调整某类权重 +delta，其余等比例缩放保持总和 1。"""
    w = dict(base)
    others = [k for k in w if k != key]
    other_sum = sum(w[k] for k in others)
    new_other = 1 - (w[key] + delta)
    w[key] += delta
    for k in others:
        w[k] *= (new_other / other_sum) if other_sum > 0 else 0
    return w

# 准备市场状态/牛熊系数/FG（与 main 一致）
idx = m.load_index("000300")
market_state = m.build_market_state(idx) if m.USE_MARKET_GATE else {}
bb_coef = m.build_bull_bear_coef(idx)
idx_full = m.load_index_full("000300")
fg_state = m.build_fg_index(idx_full) if idx_full is not None else {}

results = []
def run(name, weights, sw):
    r = m.run_experiment(name, weights, sw, market_state, bb_coef, fg_state)
    cs = r["combo_summary"]
    results.append({
        "name": name,
        "weights": {k: round(v, 4) for k, v in weights.items()},
        "switches": sw,
        "return_pct": round(cs["total_return_pct"], 2),
        "annual_pct": round(cs["annual_return_pct"], 2),
        "mdd_pct": round(cs["max_drawdown_pct"], 2),
        "sharpe": round(cs["sharpe"], 3),
        "win_rate_pct": round(cs["win_rate_pct"], 1),
        "trades": cs["total_trades"],
    })
    print(f"  {name}: 收益 {cs['total_return_pct']:+.2f}% / 回撤 {cs['max_drawdown_pct']:.2f}% / 夏普 {cs['sharpe']:.3f} / 胜率 {cs['win_rate_pct']:.1f}% / {cs['total_trades']}笔")

print("=== 参数敏感性分析（v6 100池 2016起，基线=当前生产配置）===\n")

# 1. 基线
run("基线(v4生产)", m.WT_A, dict(BASE_SW))

# 2. 六类权重 +5%（敏感性）
print("\n[权重敏感性 ±5pct]")
for key, label in [("trend", "趋势"), ("momentum", "动能"), ("volume", "量能"),
                   ("osc", "超买超卖"), ("risk", "风控"), ("news", "研报")]:
    w = scale_weight(m.WT_A, key, 0.05)
    run(f"权重[{label}+5%]", w, dict(BASE_SW))

# 3. 门槛敏感性
print("\n[门槛敏感性]")
for bw in [58, 60, 64, 66]:
    run(f"BUY_WEAK={bw}", m.WT_A, dict(BASE_SW))
for ss in [25, 28, 32, 35]:
    run(f"SELL_STRONG={ss}", m.WT_A, dict(BASE_SW))

# 4. FG 系数敏感性（恐惧机会方向）
print("\n[FG 系数敏感性·恐惧机会]")
for kbuy in [4.0, 8.0]:
    old = m.FG_K_BUY
    m.FG_K_BUY = kbuy
    run(f"FG机会 K_BUY={kbuy}", m.WT_A, {**BASE_SW, "fg_dynamic": True, "fg_mode": "opportunistic"})
    m.FG_K_BUY = old

# 5. 仓位上限
print("\n[仓位上限敏感性]")
for cap in [0.30, 0.70]:
    old = m.CAP_PCT
    m.CAP_PCT = cap
    run(f"CAP_PCT={cap}", m.WT_A, dict(BASE_SW))
    m.CAP_PCT = old

# 输出
out = {"pool": "100池(9领域×10+10退市)", "window": "2016-01-04~2026-08-07", "results": results}
p = r"D:/Documents/Workbuddy/股票基金/_quant_weight_ref/param_sensitivity_results.json"
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n已输出 {p}（{len(results)} 配置）")
