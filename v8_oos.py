# -*- coding: utf-8 -*-
"""
v8 样本外验证（walk-forward）
==============================
用 2016-2022 训练期确定参数 → 2023-2026 样本外滚动验证
方法：固定参数（Top25/H42/止损20%/波动<60%），分两个半段对比
前半段 2016-2021（训练/参数选定期） vs 后半段 2022-2026（样本外）
若后半段夏普/收益与前半段同量级 → 参数非过拟合
"""
import os
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v8_selector as V

# 直接复用最终参数跑两个子窗口
# v8_enhance2.run_v8_single_timing 用全局 V.START/END——需要改窗口
import v8_enhance2 as E

pool = E.pool
print(f"池: {len(pool)} 只\n")

def run_window(label, start, end, **kw):
    # 临时修改窗口
    old_s, old_e = V.START, V.END
    V.START, V.END = start, end
    t0 = time.time()
    eq, trades = E.run_v8_single_timing(pool=pool, **kw)
    s = V.summary(eq, trades)
    V.START, V.END = old_s, old_e
    s["seconds"] = round(time.time() - t0, 0)
    s["label"] = label
    print(f"[{label}] {start}~{end} | 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% "
          f"| 回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']}", flush=True)
    return s

results = {}
KW = dict(top_n=25, hold_days=42, use_timing=True, stop_loss=0.20,
          min_price=2.0, max_vol=0.60)

# 全样本（基准）
results["全样本_2016-2026"] = run_window("全样本_2016-2026", "2016-01-04", "2026-08-14", **KW)
# 训练期（参数选定）
results["训练期_2016-2022"] = run_window("训练期_2016-2022", "2016-01-04", "2022-12-31", **KW)
# 样本外（参数未见的 2023-2026）
results["样本外_2023-2026"] = run_window("样本外_2023-2026", "2023-01-01", "2026-08-14", **KW)
# 分年度滚动（2022 起逐年）
for y in [2022, 2023, 2024, 2025, 2026]:
    lbl = f"年度_{y}"
    results[lbl] = run_window(lbl, f"{y}-01-01", f"{y}-12-31" if y < 2026 else "2026-08-14", **KW)

with open("v8_oos_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\n===== 样本外验证汇总 =====")
for k, v in results.items():
    print(f"{k:<20} 收益 {v.get('total_return_pct')}% | 年化 {v.get('annual_return_pct')}% | 回撤 {v.get('max_drawdown_pct')}% | 夏普 {v.get('sharpe')}")