# -*- coding: utf-8 -*-
"""短线 v3 最优参数固化（v5.11.7 滑点稳健版）
========================================================================================
参数按滑点稳健扫描更新（slip_opt_grid.json）：
- 股票 S50→S55（20bps 夏普 1.69→1.75、回撤 -8.7%→-7.1%）
- ETF  S50→S55（20bps 夏普 0.99→1.00）
- 基金 H5→H10（换手减半：A类30bps +10.6%→+90.7%；C类5bps +205%→+243.5%）
输出两套：
- short_v3_<asset>_summary.json / equity.csv      （0 滑点理想口径）
- short_v3_<asset>_slip20_summary.json / equity   （含滑点口径，看板主显）
用法：python finalize_short_v3.py [--asset all|stock|etf|fund]
"""
import sys, json, time
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
sys.path.insert(0, str(BASE))
import short_engine as S
import v8_selector as V

# 最优参数（穷举 + 滑点稳健扫描确定，夏普优先）
BEST = {
    "stock": dict(top_n=10, hold_days=10, score_min=55, ma5_exit=True, take_profit=0.0,
                  stop_loss=0.0, reversal=True,  fund_mode=False,
                  tag="T10/H10/S55 · 反转+MA5"),
    "etf":   dict(top_n=10, hold_days=10, score_min=55, ma5_exit=True, take_profit=0.12,
                  stop_loss=0.0, reversal=False, fund_mode=False,
                  tag="T10/H10/S55 · 动量+MA5+止盈12%"),
    "fund":  dict(top_n=5,  hold_days=10, score_min=40, ma5_exit=False, take_profit=0.0,
                  stop_loss=0.0, reversal=False, fund_mode=True,
                  tag="T5/H10/S40 · 动量（C类份额；换手减半抗申赎费）"),
}
SLIP = {"stock": 20, "etf": 20, "fund": 5}   # 看板主显口径：股票/ETF 20bps、基金 C类 5bps

def run_asset(asset, slip, suffix):
    t0 = time.time()
    if asset == "stock":
        pool = S.load_stock_pool()
    elif asset == "etf":
        pool = S.load_etf_pool()
    else:
        pool = S.load_fund_pool(3000)
    kw = dict(BEST[asset])
    tag = kw.pop("tag")
    eq, tr = S.run_short(pool, slippage_bps=slip, **kw)
    s = V.summary(eq, tr)
    out = {"strategy": f"short_v3_{asset}{suffix}", "params": tag,
           "slippage_bps": slip, "summary": s}
    json.dump(out, open(BASE / f"short_v3_{asset}{suffix}_summary.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    eq.to_csv(BASE / f"short_v3_{asset}{suffix}_equity.csv", index=False)
    print(f"  [{suffix or '理想'}] {tag} slip{slip}bps: 收益 {s['total_return_pct']}% | "
          f"回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 交易 {s['total_trades']} ({time.time()-t0:.0f}s)", flush=True)
    return out

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="all", choices=["stock", "etf", "fund", "all"])
    args = ap.parse_args()
    assets = ["stock", "etf", "fund"] if args.asset == "all" else [args.asset]
    for a in assets:
        run_asset(a, 0, "")           # 理想口径（对比用）
        run_asset(a, SLIP[a], "_slip20")   # 含滑点口径（看板主显）
