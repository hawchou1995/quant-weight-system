# -*- coding: utf-8 -*-
"""
全部实验重跑（v3 · 窗口修复 2016-01-04 起）
============================================
修正 exp_engine BACKTEST_START 后，全矩阵 + 三信号 + 关键组合统一重跑
输出：exp_v3_results.json（含每实验完整指标）
"""
import sys, json, time
from pathlib import Path
sys.path.insert(0, r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
from exp_engine import run_pool, BASE

DATA = str(BASE / "data_full")
subs = (BASE / "subsample_1000.txt").read_text(encoding="utf-8").splitlines()
OUT = BASE / "exp_v3_results.json"

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
          f"| 夏普 {row['sharpe']} | 胜率 {row['win_rate_pct']}% | 交易 {row['total_trades']}", flush=True)
    return row

results = {}

# ===== 基线 =====
results["基线"] = run("基线")

# ===== A 组：素材吸收候选 =====
results["A1_逃顶3扣分8"] = run("A1_逃顶3扣分8", use_escape=True,
    extra_penalties={"esc_stall": 8, "esc_break": 8, "esc_volpeak": 8})
results["A2_逃顶3扣分5"] = run("A2_逃顶3扣分5", use_escape=True,
    extra_penalties={"esc_stall": 5, "esc_break": 5, "esc_volpeak": 5})
results["A4_Aroon±5"] = run("A4_Aroon±5", use_aroon=True, extra_bonuses={"aroon_osc": 5})
results["A5_Aroon±8"] = run("A5_Aroon±8", use_aroon=True, extra_bonuses={"aroon_osc": 8})
results["A6_MFI±5"] = run("A6_MFI±5", use_mfi=True, extra_bonuses={"mfi": 5})
results["A7_MFI±8"] = run("A7_MFI±8", use_mfi=True, extra_bonuses={"mfi": 8})

# ===== B 组：权重扫描 =====
base_w = {"trend": 0.30, "momentum": 0.25, "volume": 0.15, "osc": 0.15, "risk": 0.10, "news": 0.05}
def bump(key, delta):
    w = dict(base_w)
    w[key] += delta
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
w_no_news = dict(base_w); w_no_news["news"] = 0.0
others = sum(v for k, v in w_no_news.items() if k != "news")
for k in w_no_news:
    if k != "news":
        w_no_news[k] = round(w_no_news[k] / others, 4)
results["B3_news归零"] = run("B3_news归零", weights_override=w_no_news)

# ===== C 组：门槛扫描 =====
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

# ===== D 组 =====
results["D1_涨跌停约束"] = run("D1_涨跌停约束", limit_rule=True)

# ===== 三信号 =====
results["S1_低开3%清仓"] = run("S1_低开3%清仓", sig_lowopen=0.03)
results["S1b_低开2%清仓"] = run("S1b_低开2%清仓", sig_lowopen=0.02)
results["S1c_低开5%清仓"] = run("S1c_低开5%清仓", sig_lowopen=0.05)
results["S2_三拉5%兑现50"] = run("S2_三拉5%兑现50", sig_triple_pump=(0.05, 0.5))
results["S2e_三拉5%兑现70"] = run("S2e_三拉5%兑现70", sig_triple_pump=(0.05, 0.7))
results["S3_高位3%量比2清仓"] = run("S3_高位3%量比2清仓", sig_highvol=(0.03, 2.0))
results["S3e_高位3%量比3清仓"] = run("S3e_高位3%量比3清仓", sig_highvol=(0.03, 3.0))
results["S12_低开+三拉"] = run("S12_低开+三拉", sig_lowopen=0.03, sig_triple_pump=(0.05, 0.5))
results["S123_三信号全开"] = run("S123_三信号全开",
    sig_lowopen=0.03, sig_triple_pump=(0.05, 0.5), sig_highvol=(0.03, 2.0))

# ===== 组合 =====
results["Aroon8+S1低开3"] = run("Aroon8+S1低开3",
    use_aroon=True, extra_bonuses={"aroon_osc": 8}, sig_lowopen=0.03)
results["Aroon8+门槛优化"] = run("Aroon8+门槛优化",
    use_aroon=True, extra_bonuses={"aroon_osc": 8},
    thresholds=th(buy_strong=70, sell_weak=45))

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n已保存: {OUT}")

print("\n===== v3 汇总（按夏普排序）=====")
for k, v in sorted(results.items(), key=lambda kv: -(kv[1].get("sharpe") or 0)):
    print(f"{k:<20} 收益 {v.get('total_return_pct')}% | 回撤 {v.get('max_drawdown_pct')}% | 夏普 {v.get('sharpe')} | 胜率 {v.get('win_rate_pct')}% | 交易 {v.get('total_trades')}")
