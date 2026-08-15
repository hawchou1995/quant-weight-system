# -*- coding: utf-8 -*-
"""全量池 v6 基线：组合净值 vs 全仓 buyhold 对照 + 年度收益 + 胜率分布"""
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")

# 1. 组合净值（weight 策略，等权）
eq = pd.read_csv(BASE / "fullpool_v6_equity.csv", dtype={"date": str})
eq["date"] = pd.to_datetime(eq["date"])

# 2. 全仓等权 buyhold 净值：逐日等权平均（每日所有标的归一化净值，2016 起）
import glob
daily = {}
for f in glob.glob(str(BASE / "data_full" / "*.csv")):
    code = Path(f).stem
    try:
        df = pd.read_csv(f, dtype={"date": str})
        df = df[df["date"] >= "2016-01-04"]
        if len(df) < 250:
            continue
        base0 = df["close"].iloc[0]
        if not base0 or base0 <= 0:
            continue
        df = df.copy()
        df["nav"] = df["close"] / base0 * 100
        for _, r in df.iterrows():
            daily.setdefault(r["date"], []).append(r["nav"])
    except Exception:
        pass
bh_dates = sorted(daily.keys())
bh_nav = [np.mean(daily[d]) for d in bh_dates]
bh = pd.DataFrame({"date": pd.to_datetime(bh_dates), "value": bh_nav})

# 合并画图
fig, axes = plt.subplots(2, 2, figsize=(14, 9))
fig.suptitle("v6 权重系统 · 全量池基线（2016-01 ~ 2026-08 · 6870 只等权）", fontsize=13)

ax = axes[0][0]
ax.plot(eq["date"], eq["value"], label=f"v6 权重系统（末值 {eq['value'].iloc[-1]:.1f}）", lw=1.5)
ax.plot(bh["date"], bh["value"], label=f"全仓等权买入持有（末值 {bh['value'].iloc[-1]:.1f}）", lw=1.5, alpha=0.85)
ax.set_title("组合净值（100 起）")
ax.legend()
ax.grid(alpha=0.3)

# 3. 年度收益（weight 组合）
eq = eq.set_index("date")
yearly_w = (eq["value"].resample("YE").last().pct_change() * 100).dropna()
yearly_w.index = yearly_w.index.year
# buyhold 年度
bh = bh.set_index("date")
yearly_b = (bh["value"].resample("YE").last().pct_change() * 100).dropna()
yearly_b.index = yearly_b.index.year

ax = axes[0][1]
years = sorted(set(yearly_w.index) | set(yearly_b.index))
x = np.arange(len(years))
ax.bar(x - 0.2, [yearly_w.get(y, 0) for y in years], width=0.4, label="v6 权重系统")
ax.bar(x + 0.2, [yearly_b.get(y, 0) for y in years], width=0.4, label="全仓买入持有", alpha=0.85)
ax.set_xticks(x, [str(y) for y in years], rotation=45)
ax.set_title("年度收益对比（%）")
ax.legend()
ax.grid(alpha=0.3)

# 4. 单标的收益分布（weight vs buyhold，来自 results.json）
import json
res = json.loads((BASE / "fullpool_v6_results.json").read_text(encoding="utf-8"))["results"]
w_ret = [r["weight"]["total_return_pct"] for r in res.values() if "error" not in r]
b_ret = [r["buyhold"]["total_return_pct"] for r in res.values() if "error" not in r]
ax = axes[1][0]
ax.hist(w_ret, bins=60, alpha=0.6, label=f"v6 权重系统（均值 {np.mean(w_ret):.1f}%）")
ax.hist(b_ret, bins=60, alpha=0.6, label=f"引擎 buyhold（均值 {np.mean(b_ret):.1f}%）")
ax.axvline(0, color="k", lw=0.8)
ax.set_title("单标的 10.6 年总收益分布（%）")
ax.legend(fontsize=9)
ax.grid(alpha=0.3)

# 5. 回撤曲线
eq2 = eq["value"]
cummax = eq2.cummax()
dd = (eq2 / cummax - 1) * 100
ax = axes[1][1]
ax.fill_between(eq2.index, dd, 0, color="crimson", alpha=0.4, label=f"最大回撤 {dd.min():.1f}%")
ax.set_title("v6 权重系统组合回撤（%）")
ax.legend()
ax.grid(alpha=0.3)

plt.tight_layout()
plt.show()
plt.savefig(BASE / "fullpool_v6_charts.png", dpi=130)
print("已保存: fullpool_v6_charts.png")
