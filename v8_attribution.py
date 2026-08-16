# -*- coding: utf-8 -*-
"""
v8 分年度归因 + 空仓期现金管理测算
===================================
1. 分年度收益/回撤（基于 v8_final_equity.csv）
2. 空仓期天数统计 + 货基（年化 2%）收益增厚测算
"""
import os
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
eq = pd.read_csv(BASE / "v8_final_equity.csv", dtype={"date": str})
eq["date"] = pd.to_datetime(eq["date"])
eq = eq.sort_values("date").reset_index(drop=True)

# 持仓状态：需要知道每日是否有持仓 → 用 equity 变化 + trades 推断
trades = pd.read_csv(BASE / "v8_final_trades.csv", dtype={"entry_date": str, "exit_date": str})
trades["entry_date"] = pd.to_datetime(trades["entry_date"])
trades["exit_date"] = pd.to_datetime(trades["exit_date"])

# 每日持仓市值 = equity - cash。空仓判定：equity 连续不变（现金闲置）
# 更精确：从 trades 构建每日持仓区间
holding_days = set()
for _, t in trades.iterrows():
    d = t["entry_date"]
    while d <= t["exit_date"]:
        holding_days.add(d)
        d += pd.Timedelta(days=1)

# 年度统计
eq["year"] = eq["date"].dt.year
eq["value"] = pd.to_numeric(eq["value"])

print("=" * 78)
print("v8 分年度归因（2016-2026）")
print("=" * 78)
print(f"{'年份':<6}{'年初':>12}{'年末':>12}{'年度收益':>10}{'持仓天数':>10}{'空仓天数':>10}")
rows = []
for year, grp in eq.groupby("eq_year" if False else "year"):
    grp = grp.sort_values("date")
    v0 = grp["value"].iloc[0]
    v1 = grp["value"].iloc[-1]
    ret = (v1 / v0 - 1) * 100 if v0 else 0
    days_in_year = grp["date"].dt.date
    hold = sum(1 for d in grp["date"] if d in holding_days)
    idle = len(grp) - hold
    # 年内最大回撤
    dd = (grp["value"] / grp["value"].cummax() - 1) * 100
    mdd = dd.min()
    rows.append({"year": year, "ret": ret, "mdd": mdd, "hold": hold, "idle": idle})
    print(f"{year:<6}{v0:>12,.0f}{v1:>12,.0f}{ret:>9.1f}%{hold:>10}{idle:>10}")

print("-" * 78)
# 现金管理测算：空仓日按货基年化 2%（= 万 0.55/日）计
total_idle = sum(r["idle"] for r in rows)
CASH_YIELD = 0.02
# 空仓期资金=全现金；按现金在组合中占比估算增厚
# 简化：空仓日资金全部现金，货基收益 = 现金 × 2%/365 × 天数
# 从 equity 序列计算每日现金近似 = 空仓日 equity 全为现金
cash_days = eq[~eq["date"].isin(holding_days)]
est_gain = 0
for _, r in cash_days.iterrows():
    est_gain += r["value"] * CASH_YIELD / 365
final_v = eq["value"].iloc[-1]
boost_pct = est_gain / eq["value"].iloc[0] * 100
print(f"总空仓天数: {total_idle}（占 {(total_idle/len(eq))*100:.1f}%）")
print(f"空仓期货基收益估算: +{est_gain:,.0f} 元（相对初始资金 {boost_pct:.2f}%）")
print(f"加货基后终值: {final_v + est_gain:,.0f}（原 {final_v:,.0f}）")
print(f"总收益: {((final_v + est_gain)/eq['value'].iloc[0]-1)*100:.1f}%（原 {((final_v/eq['value'].iloc[0])-1)*100:.1f}%）")

# 年度明细存 json
out = {"yearly": rows, "total_idle_days": total_idle,
       "cash_yield_gain": round(est_gain, 0), "boost_pct": round(boost_pct, 2),
       "final_value_with_yield": round(final_v + est_gain, 0)}
with open(BASE / "v8_yearly_attribution.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("已保存: v8_yearly_attribution.json")