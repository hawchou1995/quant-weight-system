# -*- coding: utf-8 -*-
"""短线 v3 最优参数固化：重跑最优 → short_v3_<asset>_summary.json + short_v3_<asset>_equity.csv
========================================================================================
（看板从这些文件读短线回测 KPI 与净值曲线）
"""
import sys, json, time
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
sys.path.insert(0, str(BASE))
import short_engine as S
import v8_selector as V

# 最优参数（穷举确定，夏普优先）
BEST = {
    "stock": dict(top_n=10, hold_days=10, score_min=50, ma5_exit=True, take_profit=0.0,
                  stop_loss=0.0, reversal=True,  fund_mode=False,
                  tag="T10/H10/S50 · 反转+MA5"),
    "etf":   dict(top_n=10, hold_days=10, score_min=50, ma5_exit=True, take_profit=0.12,
                  stop_loss=0.0, reversal=False, fund_mode=False,
                  tag="T10/H10/S50 · 动量+MA5+止盈12%"),
    "fund":  dict(top_n=5,  hold_days=5,  score_min=40, ma5_exit=False, take_profit=0.0,
                  stop_loss=0.0, reversal=False, fund_mode=True,
                  tag="T5/H5/S40 · 动量（净值型不设MA5，实测MA5腰斩收益）"),
}

def run_asset(asset):
    t0 = time.time()
    if asset == "stock":
        pool = S.load_stock_pool()
    elif asset == "etf":
        pool = S.load_etf_pool()
    else:
        pool = S.load_fund_pool(3000)
    kw = dict(BEST[asset])
    tag = kw.pop("tag")
    print(f"{asset} 池 {len(pool)} 只 ({time.time()-t0:.0f}s) → 跑最优 {tag}", flush=True)
    eq, tr = S.run_short(pool, **kw)
    s = V.summary(eq, tr)
    # summary 附参数标签
    out = {"strategy": f"short_v3_{asset}", "params": tag, "summary": s}
    json.dump(out, open(BASE / f"short_v3_{asset}_summary.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    eq.to_csv(BASE / f"short_v3_{asset}_equity.csv", index=False)
    print(f"  {tag}: 收益 {s['total_return_pct']}% | 回撤 {s['max_drawdown_pct']}% | "
          f"夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']} ({time.time()-t0:.0f}s)", flush=True)
    return out

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="all", choices=["stock", "etf", "fund", "all"])
    args = ap.parse_args()
    assets = ["stock", "etf", "fund"] if args.asset == "all" else [args.asset]
    for a in assets:
        run_asset(a)
