# -*- coding: utf-8 -*-
"""平衡领域样本验证 v2：37 只 × 19 领域，验证权重配置普适性 + 领域归因"""
import sys, os, json
sys.path.insert(0, '.')
import pandas as pd
from weight_system_backtest import (
    load_data as _ld, compute_indicators, compute_total_score, run_backtest, compute_summary,
    WEIGHTS, BUY_STRONG, BUY_WEAK, SELL_WEAK, SELL_STRONG,
)

DATA_TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_tmp")

# code -> (name, industry) 全 39 只（2026-08-10 补齐消费/光伏，各领域 >=2 只）
TMP_UNIVERSE = [
    ("600519", "贵州茅台", "白酒"), ("000858", "五粮液", "白酒"), ("600887", "伊利股份", "消费"), ("603288", "海天味业", "消费"),
    ("600036", "招商银行", "银行"), ("601398", "工商银行", "银行"),
    ("300750", "宁德时代", "新能源"), ("601012", "隆基绿能", "光伏"), ("300274", "阳光电源", "新能源"), ("600438", "通威股份", "光伏"),
    ("600276", "恒瑞医药", "医药"), ("603259", "药明康德", "医药"), ("300760", "迈瑞医疗", "医药"),
    ("000333", "美的集团", "家电"), ("000651", "格力电器", "家电"),
    ("601088", "中国神华", "煤炭"), ("601225", "陕西煤业", "煤炭"),
    ("601318", "中国平安", "保险"), ("601601", "中国太保", "保险"),
    ("600900", "长江电力", "公用"), ("600905", "三峡能源", "公用"),
    ("002594", "比亚迪", "汽车"), ("601633", "长城汽车", "汽车"),
    ("601899", "紫金矿业", "有色"), ("600111", "北方稀土", "有色"),
    ("600048", "保利发展", "地产"), ("000002", "万科A", "地产"),
    ("600760", "中航沈飞", "军工"), ("600893", "航发动力", "军工"),
    ("600030", "中信证券", "券商"), ("300059", "东方财富", "券商"),
    ("688981", "中芯国际", "半导体"), ("603986", "兆易创新", "半导体"),
    ("002714", "牧原股份", "农业"), ("600598", "北大荒", "农业"),
    ("601006", "大秦铁路", "交运"), ("600009", "上海机场", "交运"),
    ("600941", "中国移动", "通信"), ("601728", "中国电信", "通信"),
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
    row = d.iloc[-1]
    total, comp, _conf = compute_total_score(row, None, False)
    results.append({
        "code": code, "name": name, "industry": ind,
        "weight_ret": sum_w.get("total_return_pct", 0),
        "weight_dd": sum_w.get("max_drawdown_pct", 0),
        "bh_ret": sum_b.get("total_return_pct", 0),
        "bh_dd": sum_b.get("max_drawdown_pct", 0),
        "trades": len(tr_w),
        "today_score": round(total, 1),
        "today_action": action_label(total),
        "components": {k: round(v, 1) for k, v in comp.items() if k != "total"},
    })

# ---- 汇总 ----
import statistics
n = len(results)
wins = sum(1 for r in results if r["weight_ret"] > 0)
avg_w = statistics.mean(r["weight_ret"] for r in results)
avg_b = statistics.mean(r["bh_ret"] for r in results)
avg_dd_w = statistics.mean(r["weight_dd"] for r in results)
avg_dd_b = statistics.mean(r["bh_dd"] for r in results)
# 跑赢/跑输持有
beat = sum(1 for r in results if r["weight_ret"] > r["bh_ret"])
# 领域归因
from collections import defaultdict
ind_stat = defaultdict(list)
for r in results:
    ind_stat[r["industry"]].append(r)
print(f"=== 全 {n} 只 × {len(ind_stat)} 领域验证 ===")
print(f"正收益: {wins}/{n} ({wins/n*100:.0f}%) | 跑赢买入持有: {beat}/{n} ({beat/n*100:.0f}%)")
print(f"平均收益: 权重 {avg_w:.1f}% vs 持有 {avg_b:.1f}% | 平均回撤: 权重 {avg_dd_w:.1f}% vs 持有 {avg_dd_b:.1f}%")
print(f"夏普口径: 权重系统在回撤端优势 {'显著' if avg_dd_w < avg_dd_b * 0.9 else '存在' if avg_dd_w < avg_dd_b else '不明显'}")
print()
print("=== 领域归因（按权重平均收益排序）===")
ind_rows = []
for ind, rs in sorted(ind_stat.items(), key=lambda kv: -statistics.mean(r["weight_ret"] for r in kv[1])):
    ind_avg = statistics.mean(r["weight_ret"] for r in rs)
    ind_bh = statistics.mean(r["bh_ret"] for r in rs)
    ind_dd = statistics.mean(r["weight_dd"] for r in rs)
    ind_rows.append({"industry": ind, "n": len(rs), "avg_w": round(ind_avg, 1),
                     "avg_bh": round(ind_bh, 1), "avg_dd": round(ind_dd, 1)})
    print(f"{ind:<6} {len(rs)}只 | 权重均收益 {ind_avg:>7.1f}% | 持有均收益 {ind_bh:>7.1f}% | 权重均回撤 {ind_dd:>6.1f}%")

# 弱领域识别：权重均收益 < 0 的领域
weak = [r for r in ind_rows if r["avg_w"] < 0]
print()
print(f"=== 弱领域（权重均收益为负）: {len(weak)} 个 ===")
for r in weak:
    print(f"  {r['industry']}: {r['n']}只 权重均收益 {r['avg_w']}% (持有 {r['avg_bh']}%)")

with open("tmp_industry_validation_v2.json", "w", encoding="utf-8") as f:
    json.dump({"summary": {
        "n": n, "industries": len(ind_stat), "wins": wins, "beat": beat,
        "avg_w": round(avg_w, 1), "avg_b": round(avg_b, 1),
        "avg_dd_w": round(avg_dd_w, 1), "avg_dd_b": round(avg_dd_b, 1),
        "weak_industries": [r for r in ind_rows if r["avg_w"] < 0],
    }, "by_industry": ind_rows, "results": results}, f, ensure_ascii=False, indent=2)
print("\n已保存 tmp_industry_validation_v2.json")
