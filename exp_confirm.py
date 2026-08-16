# -*- coding: utf-8 -*-
"""
全量确认（命中候选 → 6870 只全量池）
======================================
子样本命中：A5 Aroon±8（夏普 +0.154）、S1 低开3%清仓（回撤 -3.5pct、夏普 +0.171）
全量确认：基线 / Aroon±8 / S1低开3% / Aroon+S1 组合
"""
import os
import sys, json, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exp_engine import run_pool, BASE

DATA = str(BASE / "data_full")
codes = sorted(p.stem for p in Path(DATA).glob("*.csv"))
OUT = BASE / "exp_confirm_results.json"

def run(label, **kw):
    t0 = time.time()
    cs, res, combo = run_pool(codes, DATA, label, **kw)
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
results["基线"] = run("基线")
results["Aroon±8"] = run("Aroon±8", use_aroon=True, extra_bonuses={"aroon_osc": 8})
results["S1低开3%清仓"] = run("S1低开3%清仓", sig_lowopen=0.03)
results["Aroon+S1组合"] = run("Aroon+S1组合", use_aroon=True,
    extra_bonuses={"aroon_osc": 8}, sig_lowopen=0.03)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n已保存: {OUT}")
print("\n===== 全量确认汇总 =====")
for k, v in sorted(results.items(), key=lambda kv: -(kv[1].get("sharpe") or 0)):
    print(f"{k:<16} 收益 {v.get('total_return_pct')}% | 回撤 {v.get('max_drawdown_pct')}% | 夏普 {v.get('sharpe')} | 胜率 {v.get('win_rate_pct')}% | 交易 {v.get('total_trades')}")