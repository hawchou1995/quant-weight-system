# -*- coding: utf-8 -*-
"""生成 matplotlib 图表（组合净值对比 / 信号分布 / 各标的收益对比）"""
import json, sys, os
sys.path.insert(0, '.')
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 中文字体
for f in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc"]:
    if os.path.exists(f):
        fm.fontManager.addfont(f)
        plt.rcParams["font.family"] = fm.FontProperties(fname=f).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

with open("snapshot_20260810.json", encoding="utf-8") as f:
    snap = json.load(f)
with open("weight_system_results.json", encoding="utf-8") as f:
    results = json.load(f)

# 1. 组合净值对比（权重系统 vs 买入持有）
combo_w = snap["combined_weight"]
combo_b = snap["combined_buyhold"]
b_map = {p["date"]: p["value"] for p in combo_b}
dates_w = [p["date"] for p in combo_w]
vals_w = [p["value"] for p in combo_w]
vals_b = [b_map.get(d) for d in dates_w]

fig, ax = plt.subplots(figsize=(12, 5.5), dpi=110)
ax.plot(dates_w, vals_w, color="#d92d20", lw=1.6, label="权重系统（回撤18.8%）")
ax.plot(dates_w, vals_b, color="#666", lw=1.2, ls="--", label="买入持有（回撤39.9%）")
ax.set_title("组合净值对比：综合指标权重系统 vs 买入持有（19标的等权，2025-01 ~ 2026-08）")
ax.set_ylabel("净值（起点=100）")
ax.legend(loc="upper left")
ax.grid(alpha=0.3)
ax.tick_params(axis="x", rotation=30)
n = len(dates_w)
step = max(1, n // 12)
ax.set_xticks(dates_w[::step])
plt.tight_layout()
plt.show()
plt.savefig("weight_system_combined_equity.png")
plt.close()

# 2. 19 标的权重系统 vs 买入持有 vs 旧S1-S7 收益对比
codes = list(results["results"].keys())
names = [f"{results['results'][c]['name'][:4]}" for c in codes]
w_rets = [results["results"][c]["weight"].get("total_return_pct", 0) for c in codes]
b_rets = [results["results"][c]["buyhold"].get("total_return_pct", 0) for c in codes]
s_rets = [results["results"][c]["s1s7"].get("total_return_pct", 0) for c in codes]

fig, ax = plt.subplots(figsize=(13, 6), dpi=110)
x = range(len(codes))
ax.bar([i - 0.25 for i in x], w_rets, width=0.22, color="#d92d20", label="权重系统")
ax.bar(x, b_rets, width=0.22, color="#2b6cb0", label="买入持有")
ax.bar([i + 0.25 for i in x], s_rets, width=0.22, color="#8a94a6", label="旧S1-S7")
ax.set_xticks(list(x))
ax.set_xticklabels(names, rotation=45, ha="right", fontsize=8)
ax.set_ylabel("总收益 %")
ax.set_title("19 标的三种策略总收益对比（2025-01 ~ 2026-08）")
ax.legend()
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.show()
plt.savefig("weight_system_per_symbol_compare.png")
plt.close()

# 3. 今日信号总分分布（按操作分类着色）
sigs = snap["signals"]
sigs_sorted = sorted(sigs, key=lambda s: s["total_score"], reverse=True)
fig, ax = plt.subplots(figsize=(12, 5.5), dpi=110)
colors = []
for s in sigs_sorted:
    if s["action"] == "加仓":
        colors.append("#d92d20")
    elif s["action"] == "减仓":
        colors.append("#0f9d58")
    else:
        colors.append("#8a94a6")
ax.barh([f"{s['name']}({s['code']})" for s in sigs_sorted],
        [s["total_score"] for s in sigs_sorted], color=colors)
ax.axvline(60, color="#d92d20", ls="--", lw=0.8, alpha=0.6)
ax.axvline(45, color="#8a94a6", ls="--", lw=0.8, alpha=0.6)
ax.axvline(40, color="#0f9d58", ls="--", lw=0.8, alpha=0.6)
ax.text(61, len(sigs_sorted) - 0.5, "加仓区 ≥60", color="#d92d20", fontsize=9)
ax.text(45.5, len(sigs_sorted) - 0.5, "观望区 45-59", color="#8a94a6", fontsize=9)
ax.text(40.5, len(sigs_sorted) - 0.5, "减仓区 <40", color="#0f9d58", fontsize=9)
ax.set_xlabel("综合总分")
ax.set_title("今日（2026-08-10）19 标的综合总分与操作建议（红=加仓 灰=观望 绿=减仓）")
ax.tick_params(axis="y", labelsize=8)
plt.tight_layout()
plt.show()
plt.savefig("weight_system_snapshot_scores.png")
plt.close()

print("3 张图表已生成")
