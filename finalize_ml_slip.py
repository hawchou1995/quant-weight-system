# -*- coding: utf-8 -*-
"""v5.11.9：中长线含滑点口径固化
v9 分层 slip20（split_backtest --mode v9 --slip 20）
ETF 中长线 0/20（etf_v3_final + etf_v3_final_slip20）
基金中长线 0/30（v8_fund_summary + v8_fund_slip30，V5 生产参数）
"""
import sys, json, time, subprocess
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
sys.path.insert(0, str(BASE))
PY = sys.executable
t0 = time.time()

# 1. v9 分层 slip20
print("== 1/3 v9 分层含滑点（slip20）==", flush=True)
r = subprocess.run([PY, str(BASE / "split_backtest.py"), "--mode", "v9", "--slip", "20"], capture_output=True, text=True)
print(r.stdout[-800:] or r.stderr[-500:], flush=True)

# 2. ETF 中长线 0/20
print("== 2/3 ETF 中长线 0/20 ==", flush=True)
import etf_opt_v2 as E2
import etf_opt_v3 as E3
import v8_selector as V
pool = E2.build_pool_with_factors()
for code, ddf in pool.items():
    ddf["ma5"] = ddf["close"].rolling(5).mean()
for slip, suffix in ((0, ""), (20, "_slip20")):
    eq, tr = E3.run_etf_v3(pool, mom_type="mom20", top_n=5, hold_days=21, freeze=5,
                           mom_thresh=None, ma5_exit=True, ma_win=150, slippage_bps=slip)
    s = V.summary(eq, tr)
    out = {"strategy": "v8_etf_v3 中长线",
           "params": "月频H21/Top5/mom20动量/MA5每日止损/冷冻5天/MA150择时" + (f" · 含{slip}bps滑点" if slip else ""),
           "slippage_bps": slip, "summary": s}
    json.dump(out, open(BASE / f"etf_v3_final{suffix}_summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    eq.to_csv(BASE / f"etf_v3_final{suffix}_equity.csv", index=False)
    print(f"  ETF slip{slip}: 收益 {s['total_return_pct']}% | 回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | {s['total_trades']} 笔", flush=True)

# 3. 基金中长线 0/30（V5 生产参数）
print("== 3/3 基金中长线 0/30（V5_ns15_ma100）==", flush=True)
import v8_fund_v5 as FS
for slip, suffix in ((0, ""), (30, "_slip30")):
    eq, tr = FS.run_fund_v5(top_n=10, hold_days=126, ma_window=100, nav_stop=0.15,
                            circuit=None, slippage_bps=slip)
    s = FS.summ(eq, tr)
    out = {"strategy": "v8_fund_v5 中长线",
           "params": "H126/MA100/nav_stop15%（净值型不设MA5）" + (f" · 含{slip}bps申赎费" if slip else ""),
           "slippage_bps": slip, "summary": s}
    json.dump(out, open(BASE / f"v8_fund{suffix}_summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    eq.to_csv(BASE / f"v8_fund{suffix}_equity.csv", index=False)
    print(f"  基金 slip{slip}: 收益 {s['total_return_pct']}% | 回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | {s['total_trades']} 笔", flush=True)

print(f"\n✅ 中长线含滑点固化完成（{time.time()-t0:.0f}s）", flush=True)
