# -*- coding: utf-8 -*-
"""v9split 分层回测 A80_M78 版（回测参考按最新方案更新）
与 split_backtest.v9_split 同参数（V9_KW: T3/m25/s65/SL5.5/MA150 择时），注入 Aroon 过滤：
  aroon_osc < 80 且 mom_12_1 > 0.78 → 总分×0.6（score_row_v2 同口径，mom_th 已按路线A=0.78）
输出：v9split_<group>_a80_summary.json / v9split_<group>_a80_equity.csv（fallback 时 build 可回退旧文件）
"""
import os, sys, json, time
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import v8_selector as V
import _aroon_inhibit_exp as X

GROUPS = [
    ("all",       "股票一体 · 全A"),
    ("main_only", "纯主板"),
    ("gem_only",  "纯创业板"),
    ("star_only", "纯科创板"),
]
# 与 split_backtest.V9_KW 一致
KW = dict(top_n=3, mom_min=0.25, score_min=65, stop_loss=0.055,
          use_timing=True, ma_window=150, cash0=500000)

if __name__ == "__main__":
    for group, label in GROUPS:
        t0 = time.time()
        eq, tr = X.run_auto_inhibit(aroon_th=80, mom_th=0.78, perm=group, **KW)
        s = V.summary(eq, tr)
        out = {"strategy": f"v9_split_{group}_a80", "label": label,
               "params": "T3/m25/s65/SL5.5/MA150 择时 · Aroon强趋势过滤(A80_M78)",
               "aroon_th": 80, "mom_th": 0.78, "summary": s}
        json.dump(out, open(BASE / f"v9split_{group}_a80_summary.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        eq.to_csv(BASE / f"v9split_{group}_a80_equity.csv", index=False)
        print(f"中长线A80[{group}] {label}: 收益{s['total_return_pct']}% 年化{s['annual_return_pct']}% "
              f"回撤{s['max_drawdown_pct']}% 夏普{s['sharpe']} 胜率{s['win_rate_pct']}% 交易{s['total_trades']} ({time.time()-t0:.0f}s)", flush=True)
