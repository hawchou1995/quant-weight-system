# -*- coding: utf-8 -*-
"""
三信号注入回测（子样本 1000 只）
==================================
S1 低开清仓：次日开盘低开 >3% → 开盘清仓
S2 三拉兑现：持仓累计 3 次单日涨幅 ≥5% → 兑现 50%（减仓至 50%）
S3 高位巨量：收盘距 60 日高点 <3% 且 量比 ≥2 → 次日开盘清仓
对照：基线 + 单信号 + 两两组合 + 三信号全开
"""
import os
import sys, json, time
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exp_engine import run_pool, BASE

DATA = str(BASE / "data_full")
subs = (BASE / "subsample_1000.txt").read_text(encoding="utf-8").splitlines()
OUT = BASE / "exp_signal_results.json"

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

# 基线
results["S0_基线"] = run("S0_基线")

# S1 低开清仓（3%）
results["S1_低开3%清仓"] = run("S1_低开3%清仓", sig_lowopen=0.03)
# S1 敏感度：低开 2% / 5%
results["S1b_低开2%清仓"] = run("S1b_低开2%清仓", sig_lowopen=0.02)
results["S1c_低开5%清仓"] = run("S1c_低开5%清仓", sig_lowopen=0.05)

# S2 三拉兑现（涨幅≥5%，兑现 50%）
results["S2_三拉5%兑现50"] = run("S2_三拉5%兑现50", sig_triple_pump=(0.05, 0.5))
# S2 敏感度：拉升阈值 3% / 7%；兑现 30% / 70%
results["S2b_三拉3%兑现50"] = run("S2b_三拉3%兑现50", sig_triple_pump=(0.03, 0.5))
results["S2c_三拉7%兑现50"] = run("S2c_三拉7%兑现50", sig_triple_pump=(0.07, 0.5))
results["S2d_三拉5%兑现30"] = run("S2d_三拉5%兑现30", sig_triple_pump=(0.05, 0.3))
results["S2e_三拉5%兑现70"] = run("S2e_三拉5%兑现70", sig_triple_pump=(0.05, 0.7))

# S3 高位巨量（距60日高点<3% 且 量比≥2）
results["S3_高位3%量比2清仓"] = run("S3_高位3%量比2清仓", sig_highvol=(0.03, 2.0))
# S3 敏感度：高位 1% / 5%；量比 1.5 / 3
results["S3b_高位1%量比2清仓"] = run("S3b_高位1%量比2清仓", sig_highvol=(0.01, 2.0))
results["S3c_高位5%量比2清仓"] = run("S3c_高位5%量比2清仓", sig_highvol=(0.05, 2.0))
results["S3d_高位3%量比1.5清仓"] = run("S3d_高位3%量比1.5清仓", sig_highvol=(0.03, 1.5))
results["S3e_高位3%量比3清仓"] = run("S3e_高位3%量比3清仓", sig_highvol=(0.03, 3.0))

# 两两组合
results["S12_低开+三拉"] = run("S12_低开+三拉", sig_lowopen=0.03, sig_triple_pump=(0.05, 0.5))
results["S13_低开+高位巨量"] = run("S13_低开+高位巨量", sig_lowopen=0.03, sig_highvol=(0.03, 2.0))
results["S23_三拉+高位巨量"] = run("S23_三拉+高位巨量", sig_triple_pump=(0.05, 0.5), sig_highvol=(0.03, 2.0))

# 三信号全开
results["S123_三信号全开"] = run("S123_三信号全开",
    sig_lowopen=0.03, sig_triple_pump=(0.05, 0.5), sig_highvol=(0.03, 2.0))

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n已保存: {OUT}")

# 汇总
print("\n===== 汇总（按夏普排序）=====")
for k, v in sorted(results.items(), key=lambda kv: -(kv[1].get("sharpe") or 0)):
    print(f"{k:<20} 收益 {v.get('total_return_pct')}% | 回撤 {v.get('max_drawdown_pct')}% | 夏普 {v.get('sharpe')} | 胜率 {v.get('win_rate_pct')}% | 交易 {v.get('total_trades')}")