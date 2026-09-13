# -*- coding: utf-8 -*-
"""短线 v3 最优参数固化（v5.11.7 滑点稳健版；2026-09-11 基金线升级 FB3-H20）
========================================================================================
参数按滑点稳健扫描更新（slip_opt_grid.json）：
- 股票 S50→S55（20bps 夏普 1.69→1.75、回撤 -8.7%→-7.1%）
- ETF  S50→S55（20bps 夏普 0.99→1.00）
- 基金 2026-09-11 用户拍板「基金线 FB3-H20 落实生产」：由 T5/H10/S40（run_short 动量）
  升级为 FB3-H20 牛熊 regime（run_short_regime，与 build_short_pool.py 生产选基完全同口径），
  持仓 20 日（≈月度轮动）。依据：2000 池研究 H20 733.38%/夏普 1.316/胜率 68.0% >
  H10 616.52%/1.217（_longfund_0911.py + _longfund_robust_0911.py 邻域/分段/等权对照）；
  3000 生产池复算（out/fb3h20_verify_3000.json）：H20 = 436.44%/年化 17.02%/夏普 1.07/胜率
  65.2% vs H10 = 390.61%/1.035/55.7% —— H20 三维占优（回撤 -29.49%→-36.06% 扩大）。
输出两套：
- short_v3_<asset>_summary.json / equity.csv      （0 滑点理想口径）
- short_v3_<asset>_slip20_summary.json / equity   （含滑点口径，看板主显）
用法：python finalize_short_v3.py [--asset all|stock|etf|fund]
"""
import os
import sys, json, time
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
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
}
# ⚠ 2026-09-11 基金线升级 FB3-H20（用户拍板「基金线 FB3-H20 落实生产」）：
#   牛/熊 regime 与 build_short_pool.py 生产选基完全同口径（FUND_W_BULL / FUND_W_BEAR /
#   FUND_S_BEAR / FUND_TOP_BEAR）；hold_days=20（≈月度级轮动。⚠ 引擎 rebal_days 只读
#   bull hold_days，熊 hold 为死参数——同步写 20 保持语义一致）。
#   历史对照：旧线 T5/H10/S40 动量（run_short，slip5）= +243.47%/夏普0.834/598笔，已退役。
FUND_BULL = dict(top_n=10, hold_days=20, score_min=30, reversal=False, min_amt=0,
                 weights=(40, 0, 30, 30), mask=(1, 1, 1, 1))
FUND_BEAR = dict(top_n=3, hold_days=20, score_min=45, reversal=False, min_amt=0,
                 weights=(25, 0, 30, 45), mask=(1, 1, 1, 1))
FUND_TAG = "FB3-H20 牛熊 · 牛动量重Top10/S30 · 熊低波重Top3/S45（C类份额；月度级轮动）"
SLIP = {"stock": 20, "etf": 20, "fund": 5}   # 看板主显口径：股票/ETF 20bps、基金 C类 5bps

def run_asset(asset, slip, suffix):
    t0 = time.time()
    if asset == "stock":
        pool = S.load_stock_pool()
        kw = dict(BEST["stock"]); tag = kw.pop("tag")
        eq, tr = S.run_short(pool, slippage_bps=slip, **kw)
    elif asset == "etf":
        pool = S.load_etf_pool()
        kw = dict(BEST["etf"]); tag = kw.pop("tag")
        eq, tr = S.run_short(pool, slippage_bps=slip, **kw)
    else:
        # 基金 = FB3-H20 牛熊 regime（run_short_regime；allow_bear_buy = 熊市防守开仓）
        # ⚠ 2026-09-13 用户拍板：生产池 3000 → 2000（2000 池研究口径 733.38%/夏普 1.316 优于 3000 池复算 436.44%/1.07）
        pool = S.load_fund_pool(2000)
        tag = FUND_TAG
        eq, tr = S.run_short_regime(pool, bull_cfg=dict(FUND_BULL), bear_cfg=dict(FUND_BEAR),
                                    allow_bear_buy=True, fund_mode=True, slippage_bps=slip)
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