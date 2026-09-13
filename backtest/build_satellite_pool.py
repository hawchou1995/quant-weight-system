# -*- coding: utf-8 -*-
"""双卫星目标持仓 json 生成器（供 build_dual_system 渲染 sys-auto 卡片）
轨A 冷门低波 ln_amt20+atr20 Top10（60 交易日调仓）｜轨B A4D icir Top20（月频，r6b 原引擎口径）
输出：backtest/satellite_pool.json"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# ---- 轨 A：冷门低波（复用 signal_satellite 的数据装载与因子逻辑）----
src = open(HERE / "signal_satellite_0913.py", encoding="utf-8").read().split("def main()")[0]
src = src.replace('BASE = Path(__file__).resolve().parents[1]',
                  f'BASE = Path(r"{BASE}")')
g = {"__file__": str(HERE / "signal_satellite_0913.py")}
exec(src, g)
px, LAST_DAY, total_mv, days_ix = g["px"], g["LAST_DAY"], g["total_mv"], None
di_last = None
all_days = sorted({d for p in px.values() for d in p.index})
di_last = all_days.index(LAST_DAY)

ln_top, _ = g["signal_ln_atr"]({})
ln_rows = []
for c in ln_top:
    d = px[c].tail(1).iloc[0]
    ln_rows.append({"code": c, "close": round(float(d["close"]), 2),
                    "lot": round(float(d["close"]) * 100)})

# ---- 轨 B：A4D r6b 原引擎末截面 ----
src_b = open(HERE / "factorlab_0913" / "factor_blend_r6b_0913.py", encoding="utf-8").read().split("if __name__")[0]
gb = {"__file__": str(HERE / "factorlab_0913" / "factor_blend_r6b_0913.py")}
exec(src_b, gb)
di = gb["ND"] - 1
sc = gb["COMP_A4"][di]
ok = np.where(np.isfinite(sc) & gb["ELIG_A4"][di])[0]
ok = sorted(ok, key=lambda j: -sc[j])[:20]
prev = gb["close_m"][di - 1]
a4_rows = []
for j in ok:
    c = gb["codes"][j]
    clse = float(gb["close_m"][di, j])
    guard = bool(np.isfinite(prev[j]) and clse >= prev[j] * 1.098)
    a4_rows.append({"code": c, "close": round(clse, 2), "lot": round(clse * 100), "limit_guard": guard})

# ---- 调仓日历 ----
next_ln_in = 60 - (di_last % 60)
out = {
    "asof": str(LAST_DAY.date()),
    "track_a": {
        "name": "冷门低波 ln_amt20+atr20 Top10",
        "rebal": "每 60 个交易日",
        "next_rebal_in_days": int(next_ln_in),
        "bt": {"total": 127.4, "ann": 16.2, "mdd": -18.4, "sharpe": 1.238,
               "note": "安慰剂500 p=0.0000 · 与FB3相关-0.165 · slip50稳健 · ⚠ atr20 fwd语义待复核"},
        "rows": ln_rows,
    },
    "track_b": {
        "name": "A4D icir6因子 Top20",
        "rebal": "月频（次一交易日若为新月首调仓日）",
        "next_rebal": "每月调仓窗（rebal=20 · offset 0）",
        "bt": {"total": 114.2, "ann": 15.1, "mdd": -18.3, "sharpe": 1.074,
               "note": "相位中位1.075 · 安慰剂500 p=0.000 · DSR 0.987 · slip50稳健"},
        "rows": a4_rows,
    },
}
json.dump(out, open(HERE / "satellite_pool.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"[satellite_pool] asof {out['asof']} | 轨A {len(ln_rows)} 只 | 轨B {len(a4_rows)} 只 | 轨A 距下次调仓 {next_ln_in} 交易日")
