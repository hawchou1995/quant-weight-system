# -*- coding: utf-8 -*-
"""E0 幸存者偏差对照：全集(真实口径, 已有+121.05%) vs 幸存者宇宙(剔除退市/断档股)。
复用 r2_naci_exit_0912.py 引擎源码, 仅注入 STALE 过滤后 exec, 只跑 E0。
"""
import json
import time
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[2]
ENGINE = BASE / "backtest" / "r2_rebuild_0911" / "r2_naci_exit_0912.py"
DATA = BASE / "data_full"
OUT = BASE / "backtest" / "r2_rebuild_0911" / "e0_survivorship_0912.json"

t0 = time.time()

# ---- 1. 识别退市/断档股（last < 2026-08-01 的主板文件）----
stale = []
for f in sorted(DATA.glob("*.csv")):
    code = f.stem
    if not (code.startswith("sh60") or code.startswith("sz00")):
        continue
    try:
        d = pd.read_csv(f, usecols=["date"], dtype={"date": str})
        if d["date"].iloc[-1] < "2026-08-01":
            stale.append(code[2:])
    except Exception:
        continue
print(f"[stale] 退市/断档股 {len(stale)} 只", flush=True)

# ---- 2. 注入过滤后 exec 引擎 ----
src = ENGINE.read_text(encoding="utf-8")
anchor = "    code = f.stem\n"
assert src.count(anchor) == 1
src = src.replace(anchor, anchor + "    if code[2:] in STALE_CODES:\n        continue\n")
g = {"__name__": "e0_surv", "__file__": str(ENGINE), "STALE_CODES": set(stale)}
exec(compile(src, str(ENGINE), "exec"), g)

# ---- 3. 幸存者宇宙跑 E0 ----
r = g["run"](entry="A", exits=("base",))
print(f"[survivor-only E0] {r['total_pct']}% | 年化 {r['ann_pct']}% | 回撤 {r['mdd_pct']}% | "
      f"夏普 {r['sharpe']} | {r['n_trades']}笔 胜率{r['win_rate']}%", flush=True)
print(f"[reasons] {r['reasons']}", flush=True)

full = json.load(open(BASE / "backtest" / "r2_rebuild_0911" / "naci_exit_0912.json", encoding="utf-8"))["A"]["E0基线"]
diff = {k: (round(r[k] - full[k], 2) if isinstance(r[k], (int, float)) else r[k]) for k in r if k != "reasons"}
res = {
    "full_universe_E0": full,
    "survivor_only_E0": {k: v for k, v in r.items() if k != "reasons"},
    "survivor_minus_full": diff,
    "stale_codes_n": len(stale),
}
json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"[bias] 幸存者宇宙 - 全集: {diff}", flush=True)
print(f"done {time.time()-t0:.0f}s", flush=True)
