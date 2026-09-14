# -*- coding: utf-8 -*-
"""短线选股独立审查（2026-09-14 盘前）：复算 9/11 收盘的买入信号
口径（生产同源）：khunter_all_strategies_backtest.SIGNALS（19 策略）∧ RSI_now<35（熊市）
不依赖隔壁 build_short_pool.py 的产物，直接调用其同源模块。
输出：hit 数 / RSI<35 数 / hit∧RSI<35（买入）/ watch(hit∧35≤RSI<59) / 与 short_pool.json 对账
"""
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
sys.path.insert(0, str(BASE / "backtest"))
import khunter_all_strategies_backtest as K
import khunter_timing_backtest as T

t0 = time.time()
LAST = "2026-09-11"
_nh = pd.read_csv(BASE / "data_fundamental" / "name_hist.csv", dtype={"code": str}).sort_values("TRADE_DATE").groupby("code").tail(1)
_name = _nh.set_index("code")["SECURITY_NAME_ABBR"].astype(str)
ST_SET = set(_name[_name.str.contains("ST")].index)

n_scan = n_d0 = 0
hits = []   # (code, rsi_now, hit_names)
rsi_below35 = []
for f in sorted((BASE / "data_full").glob("*.csv")):
    s = f.stem
    if not s.startswith(("sh600", "sh601", "sh603", "sh605", "sz000", "sz001", "sz002", "sz003")):
        continue
    code6 = s[2:]
    d = pd.read_csv(f, dtype={"date": str})
    if len(d) < 300:
        continue
    if d["date"].iloc[-1] != LAST:
        continue  # 必须 9/11 有行情（与生产一致）
    n_scan += 1
    d = d.rename(columns={"volume": "volume"})
    d["date"] = pd.to_datetime(d["date"])
    r = T.prep(d)
    i = len(d) - 1
    rsi_now = r["rsi"].iloc[i]
    if pd.isna(rsi_now):
        continue
    n_d0 += 1
    if rsi_now < 35:
        rsi_below35.append((code6, float(rsi_now)))
    sig_any = np.zeros(len(d), dtype=bool)
    hit_names = []
    for nm, fn in K.SIGNALS.items():
        try:
            sv = fn(r)
            if bool(sv.iloc[i]):
                hit_names.append(nm)
            sig_any |= sv.values
        except Exception:
            continue
    if bool(sig_any[i]):
        hits.append((code6, float(rsi_now), hit_names))
    if (n_scan % 500 == 0):
        print(f"  scanned {n_scan} t={time.time()-t0:.0f}s", flush=True)

print(f"\n=== 独立复算结果（asof {LAST}，主板剔ST扫描 {n_d0} 只）===")
print(f"1) KHunter 信号命中（hit）: {len(hits)} 只")
buy = [h for h in hits if h[1] < 35]
watch = [h for h in hits if 35 <= h[1] < 59]
print(f"2) hit ∧ RSI_now<35（熊市买入信号）: {len(buy)} 只  <=> short_pool.json buy_n={json.load(open(BASE/'short_pool.json', encoding='utf-8'))['sel_meta']['khunter']['buy_n']}")
print(f"3) hit ∧ 35≤RSI<59（观察区）: {len(watch)} 只  <=> watch_n=26")
print(f"4) RSI_now<35（全市场超卖）: {len(rsi_below35)} 只")
if hits:
    print("\nhit 明细（前 30）:")
    for c, rs, nm in hits[:30]:
        print(f"  {c} rsi_now={rs:.1f} {'BUY!' if rs < 35 else ''} {nm}")
else:
    print("\n** hit = 0：9/11 收盘全主板无任何 KHunter 15 策略信号命中 **")
if watch:
    print("\nwatch 明细（前 26）:")
    for c, rs, nm in watch[:26]:
        print(f"  {c} rsi_now={rs:.1f} {nm}")
print(f"\n总耗时 {time.time()-t0:.0f}s")
