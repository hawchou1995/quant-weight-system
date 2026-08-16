# -*- coding: utf-8 -*-
"""
子样本实验矩阵（grill 后执行）
================================
A 组 - 素材吸收 5 候选（逃顶3/Aroon/MFI）
B 组 - 权重扫描（单维 ±0.05）
C 组 - 门槛扫描（四边界 ±5）
D 组 - 上轮建议（buyhold 修复 / 涨跌停约束 / ETF 分池）
"""
import os
import sys, json, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exp_engine import run_pool, BASE

DATA = str(BASE / "data_full")
subs = (BASE / "subsample_1000.txt").read_text(encoding="utf-8").splitlines()
OUT = BASE / "exp_matrix_results.json"

def run(label, **kw):
    t0 = time.time()
    cs, res, combo = run_pool(subs, DATA, label, **kw)
    dt = time.time() - t0
    row = {
        "label": label, "seconds": round(dt, 0),
        "total_return_pct": cs.get("total_return_pct"),
        "annual_return_pct": cs.get("annual_return_pct"),
        "max_drawdown_pct": cs.get("max_drawdown_pct"),
        "sharpe": cs.get("sharpe"),
        "win_rate_pct": cs.get("win_rate_pct"),
        "total_trades": cs.get("total_trades"),
    }
    print(f"[{label}] {dt:.0f}s | 收益 {row['total_return_pct']}% | 回撤 {row['max_drawdown_pct']}% "
          f"| 夏普 {row['sharpe']} | 胜率 {row['win_rate_pct']}% | 交易 {row['total_trades']}")
    return row

results = {}

# ===== A 组：素材吸收候选 =====
# A0 基线（无候选）
results["A0_基线"] = run("A0_基线")
# A1 逃顶3信号扣分（每信号 -8）
results["A1_逃顶3扣分8"] = run("A1_逃顶3扣分8", use_escape=True,
    extra_penalties={"esc_stall": 8, "esc_break": 8, "esc_volpeak": 8})
# A2 逃顶3扣分 -5（敏感度）
results["A2_逃顶3扣分5"] = run("A2_逃顶3扣分5", use_escape=True,
    extra_penalties={"esc_stall": 5, "esc_break": 5, "esc_volpeak": 5})
# A3 逃顶3扣分 -12
results["A3_逃顶3扣分12"] = run("A3_逃顶3扣分12", use_escape=True,
    extra_penalties={"esc_stall": 12, "esc_break": 12, "esc_volpeak": 12})
# A4 Aroon ±5
results["A4_Aroon±5"] = run("A4_Aroon±5", use_aroon=True, extra_bonuses={"aroon_osc": 5})
# A5 Aroon ±8
results["A5_Aroon±8"] = run("A5_Aroon±8", use_aroon=True, extra_bonuses={"aroon_osc": 8})
# A6 MFI ±5
results["A6_MFI±5"] = run("A6_MFI±5", use_mfi=True, extra_bonuses={"mfi": 5})
# A7 MFI ±8
results["A7_MFI±8"] = run("A7_MFI±8", use_mfi=True, extra_bonuses={"mfi": 8})

# ===== B 组：权重扫描（单维 +0.05，其余按比例缩放保持和=1）=====
base_w = {"trend": 0.30, "momentum": 0.25, "volume": 0.15, "osc": 0.15, "risk": 0.10, "news": 0.05}
def bump(key, delta):
    w = dict(base_w)
    w[key] += delta
    # 其余按比例归一
    others = sum(v for k, v in w.items() if k != key)
    scale = (1 - w[key]) / others
    for k in w:
        if k != key:
            w[k] = round(w[k] * scale, 4)
    return w

for key in ["trend", "momentum", "volume", "osc", "risk"]:
    results[f"B1_{key}+0.05"] = run(f"B1_{key}+0.05", weights_override=bump(key, 0.05))
for key in ["trend", "momentum", "volume", "osc", "risk"]:
    results[f"B2_{key}-0.05"] = run(f"B2_{key}-0.05", weights_override=bump(key, -0.05))

# ===== C 组：门槛扫描（单边界 ±5）=====
def th(**kw):
    t = {"buy_strong": 75, "buy_weak": 60, "sell_weak": 40, "sell_strong": 30}
    t.update(kw)
    return t

results["C1_buy_strong70"] = run("C1_buy_strong70", thresholds=th(buy_strong=70))
results["C2_buy_strong80"] = run("C2_buy_strong80", thresholds=th(buy_strong=80))
results["C3_buy_weak55"] = run("C3_buy_weak55", thresholds=th(buy_weak=55))
results["C4_buy_weak65"] = run("C4_buy_weak65", thresholds=th(buy_weak=65))
results["C5_sell_weak35"] = run("C5_sell_weak35", thresholds=th(sell_weak=35))
results["C6_sell_weak45"] = run("C6_sell_weak45", thresholds=th(sell_weak=45))
results["C7_sell_strong25"] = run("C7_sell_strong25", thresholds=th(sell_strong=25))
results["C8_sell_strong35"] = run("C8_sell_strong35", thresholds=th(sell_strong=35))

# ===== D 组：上轮建议 =====
results["D1_涨跌停约束"] = run("D1_涨跌停约束", limit_rule=True)
results["D2_buyhold修复"] = run("D2_buyhold修复", fix_buyhold=True)
# ETF 分池：只跑 ETF 子集（150 只）
etf_sub = [c for c in subs if c.startswith(("sh5", "sz1"))]
if etf_sub:
    t0 = time.time()
    cs, res, combo = run_pool(etf_sub, DATA, "D3_ETF分池")
    results["D3_ETF分池"] = {
        "label": "D3_ETF分池", "seconds": round(time.time() - t0, 0),
        "total_return_pct": cs.get("total_return_pct"),
        "annual_return_pct": cs.get("annual_return_pct"),
        "max_drawdown_pct": cs.get("max_drawdown_pct"),
        "sharpe": cs.get("sharpe"),
        "win_rate_pct": cs.get("win_rate_pct"),
        "total_trades": cs.get("total_trades"),
        "n_symbols": len(etf_sub),
    }
    print(f"[D3_ETF分池] 收益 {cs.get('total_return_pct')}% | 回撤 {cs.get('max_drawdown_pct')}% | 夏普 {cs.get('sharpe')}")
# 股票分池
stock_sub = [c for c in subs if not c.startswith(("sh5", "sz1"))]
if stock_sub:
    t0 = time.time()
    cs, res, combo = run_pool(stock_sub, DATA, "D4_股票分池")
    results["D4_股票分池"] = {
        "label": "D4_股票分池", "seconds": round(time.time() - t0, 0),
        "total_return_pct": cs.get("total_return_pct"),
        "annual_return_pct": cs.get("annual_return_pct"),
        "max_drawdown_pct": cs.get("max_drawdown_pct"),
        "sharpe": cs.get("sharpe"),
        "win_rate_pct": cs.get("win_rate_pct"),
        "total_trades": cs.get("total_trades"),
        "n_symbols": len(stock_sub),
    }
    print(f"[D4_股票分池] 收益 {cs.get('total_return_pct')}% | 回撤 {cs.get('max_drawdown_pct')}% | 夏普 {cs.get('sharpe')}")

# 保存
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n已保存: {OUT}")

# 汇总表
print("\n===== 汇总（按夏普排序）=====")
for k, v in sorted(results.items(), key=lambda kv: -(kv[1].get("sharpe") or 0)):
    print(f"{k:<18} 收益 {v.get('total_return_pct')}% | 回撤 {v.get('max_drawdown_pct')}% | 夏普 {v.get('sharpe')} | 胜率 {v.get('win_rate_pct')}% | 交易 {v.get('total_trades')}")