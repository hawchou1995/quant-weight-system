# -*- coding: utf-8 -*-
"""文章4「天鉴尾盘」事件验证 + 策略化（v5.11.10 研究稿）
============================================
事件条件（日线可算，无未来函数）：
- EMA5 > MA14 * 1.017（短线结构未破）
- L > REF(L,2) * 1.03（低点抬高）
- H > REF(C,1) * 1.005（盘中摸到昨收上方 0.5%）
- C < O（收阴）且 (H-C)/H > 0.021（从最高回落 2.1%+）
- V <= REF(V,1) * 1.2（无明显放量）
- 剔 ST/退市/仙股
统计：T+1 开盘涨幅 / 盘中最高（相对 T 收盘）/ 2% 止盈命中 / 收盘 / T+2 收盘
策略化：T+1 开盘买 → 2% 止盈（盘中触及）否则 T+1 收盘卖；对照持有 T+2 收盘
"""
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
sys.path.insert(0, str(BASE))
import short_engine as S
import v8_selector as V

t0 = time.time()
pool = S.load_stock_pool()
names = json.load(open(BASE / "data_full_names.json", encoding="utf-8"))
print(f"股票池 {len(pool)} 只 ({time.time()-t0:.0f}s)", flush=True)

sig_days, rows = [], []
for code, ddf in pool.items():
    nm = names.get(code, "")
    if "ST" in nm or "退" in nm:
        continue
    if len(ddf) < 60:
        continue
    d = ddf.copy()
    c, o, h, l, v = d["close"], d["open"], d["high"], d["low"], d["volume"]
    ema5 = c.ewm(span=5, adjust=False).mean()
    ma14 = c.rolling(14).mean()
    cond = (
        (ema5 > ma14 * 1.017)
        & (l > l.shift(2) * 1.03)
        & (h > c.shift(1) * 1.005)
        & (c < o)
        & ((h - c) / h > 0.021)
        & (v <= v.shift(1) * 1.2)
    )
    idx = d.index[cond.values]
    if len(idx) == 0:
        continue
    sig_days.append((code, idx))
print(f"信号 {sum(len(x[1]) for x in sig_days)} 次 ({time.time()-t0:.0f}s)", flush=True)

# 逐信号统计 T+1/T+2
recs = []
for code, idx in sig_days:
    ddf = pool[code]
    pos = ddf.index.get_indexer(idx)
    for p in pos:
        if p + 1 >= len(ddf):
            continue
        r1 = ddf.iloc[p + 1]
        r2 = ddf.iloc[p + 2] if p + 2 < len(ddf) else None
        ref = ddf.iloc[p]["close"]
        o1 = r1["open"] / ref - 1
        h1 = r1["high"] / ref - 1          # T+1 盘中最高（相对信号日收盘）
        c1 = r1["close"] / ref - 1
        c2 = (r2["close"] / ref - 1) if r2 is not None else None
        recs.append({"o1": o1 * 100, "h1": h1 * 100, "c1": c1 * 100, "c2": (c2 * 100 if c2 is not None else None)})
df = pd.DataFrame(recs)
n = len(df)
print(f"\n信号总数: {n}")
print(f"T+1 开盘涨幅中位: {df['o1'].median():+.2f}% | 均值: {df['o1'].mean():+.2f}%")
print(f"T+1 盘中最高中位: {df['h1'].median():+.2f}% | 均值: {df['h1'].mean():+.2f}%")
print(f"T+1 冲高率(h1>0): {(df['h1'] > 0).mean()*100:.1f}%")
print(f"T+1 冲高≥1%: {(df['h1'] >= 1).mean()*100:.1f}% | ≥2%: {(df['h1'] >= 2).mean()*100:.1f}% | ≥5%: {(df['h1'] >= 5).mean()*100:.1f}%")
print(f"T+1 收盘涨幅中位: {df['c1'].median():+.2f}% | 收盘胜率: {(df['c1'] > 0).mean()*100:.1f}%")
print(f"T+2 收盘涨幅中位: {df['c2'].median():+.2f}% | T+2 胜率: {(df['c2'] > 0).mean()*100:.1f}%")

# 策略化 A：T+1 开盘买 → 盘中≥2% 止盈 → 否则 T+1 收盘卖（含滑点 20bps）
# 用每日 max(high) 近似盘中触发（忽略日内路径细节，高估止盈命中，标注）
tp, sl = 0.02, 0.03
buy = df["o1"].values / 100 + 1
hit_tp = df["h1"].values / 100 + 1 >= tp + 1
hit_sl = df["o1"].values / 100 + 1 <= 1 - sl
ret = np.where(hit_tp, tp, np.where(hit_sl, -sl, df["c1"].values / 100))
ret = ret - 2 * 20 / 10000   # 双边滑点 20bps
win = (ret > 0).mean() * 100
print(f"\n策略A(T+1开买, 2%止盈/3%止损, 含20bps): 均值 {ret.mean()*100:+.2f}%/笔 | 胜率 {win:.1f}% | "
      f"止盈命中 {(hit_tp).mean()*100:.1f}% | 止损 {(hit_sl).mean()*100:.1f}%")
# 策略B：持有到 T+2 收盘
ret2 = df["c2"].values / 100 - 2 * 20 / 10000
print(f"策略B(T+1开买, T+2收盘卖, 含20bps): 均值 {np.nanmean(ret2)*100:+.2f}%/笔 | 胜率 {np.nanmean(ret2 > 0)*100:.1f}%")

df.to_csv(BASE / "research_skyfall_events.csv", index=False)
json.dump({"n": n, "h1_med": float(df["h1"].median()), "tp2_hit": float((df["h1"] >= 2).mean()),
           "stratA_ret": float(ret.mean() * 100), "stratA_win": float(win)},
          open(BASE / "research_skyfall_summary.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n✅ 完成 ({time.time()-t0:.0f}s)")
