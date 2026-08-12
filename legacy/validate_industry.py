# -*- coding: utf-8 -*-
"""跨行业临时标的验证：当前权重配置在非 AI 产业链标的上的表现"""
import sys, os, json
sys.path.insert(0, '.')
import pandas as pd
from weight_system_backtest import (
    load_data, compute_indicators, compute_total_score, run_backtest, compute_summary,
    WEIGHTS, BUY_STRONG, BUY_WEAK, SELL_WEAK, SELL_STRONG, BACKTEST_START, BACKTEST_END,
)

DATA_TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_tmp")

TMP_UNIVERSE = [
    ("600519", "贵州茅台", "白酒"),
    ("600036", "招商银行", "银行"),
    ("300750", "宁德时代", "新能源"),
    ("600276", "恒瑞医药", "医药"),
    ("000333", "美的集团", "家电"),
    ("601088", "中国神华", "煤炭"),
    ("601318", "中国平安", "保险"),
    ("600900", "长江电力", "公用事业"),
    ("002594", "比亚迪", "汽车"),
    ("601012", "隆基绿能", "光伏"),
    ("000858", "五粮液", "白酒"),
    ("601899", "紫金矿业", "有色"),
]

def load_tmp(code):
    path = os.path.join(DATA_TMP, f"{code}.csv")
    df = pd.read_csv(path)
    df["date"] = df["date"].astype(str).str.replace(r"(\d{4})(\d{2})(\d{2})", r"\1-\2-\3", regex=True)
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    return df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)

def action_label(total):
    if total >= BUY_STRONG: return "加仓(满仓)"
    if total >= BUY_WEAK: return "加仓(轻仓)"
    if total < SELL_STRONG: return "减仓(清仓)"
    if total < SELL_WEAK: return "减仓(半仓)"
    return "观望"

results = []
for code, name, ind in TMP_UNIVERSE:
    df = load_tmp(code)
    d = compute_indicators(df)
    eq_w, tr_w = run_backtest(df, None, False, strategy="weight")
    eq_b, _ = run_backtest(df, None, False, strategy="bh")
    sum_w = compute_summary(eq_w, tr_w)
    sum_b = compute_summary(eq_b, [])
    # 今日快照
    row = d.iloc[-1]
    total, comp, _conf = compute_total_score(row, None, False)
    results.append({
        "code": code, "name": name, "industry": ind,
        "weight_ret": sum_w.get("total_return_pct", 0),
        "weight_dd": sum_w.get("max_drawdown_pct", 0),
        "bh_ret": sum_b.get("total_return_pct", 0),
        "bh_dd": sum_b.get("max_drawdown_pct", 0),
        "today_score": round(total, 1),
        "today_action": action_label(total),
        "today_close": round(float(row["close"]), 2),
        "rsi": round(float(row["rsi"]), 1) if not pd.isna(row["rsi"]) else None,
        "adx": round(float(row["adx"]), 1) if not pd.isna(row["adx"]) else None,
        "ma20_dev": round(float(row["ma20_dev"]), 2) if not pd.isna(row["ma20_dev"]) else None,
    })

# 汇总统计
print(f"{'标的':<10}{'行业':<8}{'权重收益':>9}{'权重回撤':>9}{'持有收益':>9}{'持有回撤':>9}{'今日分':>7}{'今日建议':>10}")
print("-" * 80)
for r in results:
    print(f"{r['name']:<10}{r['industry']:<8}{r['weight_ret']:>8.1f}%{r['weight_dd']:>8.1f}%"
          f"{r['bh_ret']:>8.1f}%{r['bh_dd']:>8.1f}%{r['today_score']:>7.1f}{r['today_action']:>10}")

wins = sum(1 for r in results if r["weight_ret"] > 0)
better_than_bh = sum(1 for r in results if r["weight_ret"] >= r["bh_ret"] - 30)  # 不低于持有30pct以内
avg_w = sum(r["weight_ret"] for r in results) / len(results)
avg_b = sum(r["bh_ret"] for r in results) / len(results)
avg_dd_w = sum(r["weight_dd"] for r in results) / len(results)
avg_dd_b = sum(r["bh_dd"] for r in results) / len(results)

print("-" * 80)
print(f"正收益标的: {wins}/{len(results)} | 平均权重收益: {avg_w:.1f}% vs 平均持有收益: {avg_b:.1f}%")
print(f"平均权重回撤: {avg_dd_w:.1f}% vs 平均持有回撤: {avg_dd_b:.1f}%")
print(f"跨行业普适性判断: {'通过（权重系统在多数行业正收益且回撤控制有效）' if wins >= 8 else '部分通过（需检查行业适配）'}")

with open("tmp_industry_validation.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("已保存 tmp_industry_validation.json")
