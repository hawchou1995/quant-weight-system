# -*- coding: utf-8 -*-
"""gushi 分时方法论验证（2026-09-14，pytdx 真逐笔）
样本：最近 8 个交易日的主板"活跃股事件"（T 日涨幅>5% 或触涨停，按成交额排序取每天前 120 只）
数据：对每个事件拉 T 日 + T+1 日逐笔（pytdx，缓存复用）
指标：净主动买占比 netbuy = (主动买额-主动卖额)/总额（buyorsell: 0=主动买 1=主动卖 2=中性）
     vwap 位置 = T+1 收盘 / T+1 VWAP - 1；资金留存度 keep = 1 - |T+1 净流出|/max(T 净流入, eps)
假设检验（gushi 核心逻辑）：
  H1 "资金没走完"：T+1 净主动买为正 → T+2/T+3 收益更好
  H2 VWAP 支撑：T+1 收盘站上 VWAP → 后续更好
  H3 净主动买占比因子：T+1 netbuy 横截面分组 → T+2/T+3 收益单调？
"""
import sys, json, time, pickle
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
sys.path.insert(0, str(BASE / "backtest"))
from pytdx_data_0914 import fetch_tick

t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

with open(OUT / "oss_panel_0913.pkl", "rb") as fh:
    P = pickle.load(fh)
cal = P["cal"]; codes = list(P["codes"]); st_mask = P["st_mask"]
ND, NC = P["close"].shape
O = P["open"].astype(np.float64); Hm = P["high"].astype(np.float64)
C = P["close"].astype(np.float64); AMT = P["amt"].astype(np.float64)
close_ff = pd.DataFrame(C).ffill().to_numpy()
Cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
with np.errstate(all="ignore"):
    chg1 = close_ff / Cprev - 1
touch = (Hm >= Cprev * 1.098) & np.isfinite(Cprev)
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()

# ---- 样本：最近 8 个交易日（ND-8..ND-1 中排除最后一天需 T+3 数据，用 ND-4 之前）
DAYS = [ND - 1 - k for k in range(4, 12)][::-1]  # 最近 8 个有 T+3 标签的交易日
log("样本日:", [cal[d] for d in DAYS])
EV = []
for d in DAYS:
    ok = (chg1[d] > 0.05) | touch[d]
    ok &= np.isfinite(C[d]) & (C[d] > 2) & np.isfinite(amt20[d]) & (amt20[d] >= 5e7)
    ok &= ~st_mask
    cand = np.flatnonzero(ok)
    if len(cand) == 0: continue
    top = cand[np.argsort(-np.where(np.isfinite(AMT[d][cand]), AMT[d][cand], 0))][:120]
    for j in top:
        EV.append((d, int(j), codes[int(j)]))
log(f"事件样本: {len(EV)} 个（{len(DAYS)} 天 × ≤120 只）")

# ---- 拉取 T 与 T+1 逐笔 ----
rows = []
for k, (d, j, code) in enumerate(EV):
    d1 = d + 1
    if d1 >= ND: continue
    try:
        t0d = fetch_tick(code, int(cal[d].replace("-", "")))
        t1d = fetch_tick(code, int(cal[d1].replace("-", "")))
    except Exception as e:
        if k < 3: print('EXC', k, code, repr(e)[:150], flush=True)
        continue
    finally:
        time.sleep(0.08)  # 限速保护（pytdx 直连）
    def metrics(tk):
        if tk is None or len(tk) == 0: return None
        px = pd.to_numeric(tk["price"], errors="coerce").to_numpy()
        vol = pd.to_numeric(tk["vol"], errors="coerce").to_numpy()
        bs = pd.to_numeric(tk["buyorsell"], errors="coerce").to_numpy()
        amt = px * vol
        total = amt.sum()
        if total <= 0: return None
        buy = amt[bs == 0].sum(); sell = amt[bs == 1].sum()
        return dict(netbuy=float((buy - sell) / total), vwap=float(total / vol.sum()) if vol.sum() > 0 else np.nan)
    m0, m1 = metrics(t0d), metrics(t1d)
    if m0 is None or m1 is None: continue
    pxT = close_ff[d, j]; pxT1 = close_ff[d1, j]
    r1 = pxT1 / pxT - 1
    r2 = close_ff[d1 + 1, j] / pxT1 - 1 if d1 + 1 < ND else np.nan
    r3 = close_ff[min(d1 + 2, ND - 1), j] / pxT1 - 1 if d1 + 2 < ND else np.nan
    rows.append(dict(date=str(cal[d]), code=code, netbuy_T=m0["netbuy"], netbuy_T1=m1["netbuy"],
                     vwap_T1=m1["vwap"], vwap_pos=float(pxT1 / m1["vwap"] - 1) if m1["vwap"] else np.nan,
                     r1=r1, r2=r2, r3=r3))
    if (k + 1) % 100 == 0:
        log(f"fetched {k+1}/{len(EV)} ok={len(rows)} t={time.time()-t0:.0f}s")

df = pd.DataFrame(rows)
log(f"有效事件: {len(df)}")
if len(df) < 50:
    log("样本不足，退出"); sys.exit(1)

# ---- H1: T+1 净主动买 > 0 → 后续更好 ----
g = df.groupby(df["netbuy_T1"] > 0)
for nm, sub in g:
    log(f"H1 T+1 netbuy{'>0' if nm else '<=0'}: n={len(sub)} r2均值={sub['r2'].mean()*100:+.3f}% r3={sub['r3'].mean()*100:+.3f}% wr2={np.mean(sub['r2']>0)*100:.1f}%")
# ---- H2: VWAP 位置 ----
g2 = df.groupby(df["vwap_pos"] > 0)
for nm, sub in g2:
    log(f"H2 T+1 收盘{'站上' if nm else '跌破'}VWAP: n={len(sub)} r2={sub['r2'].mean()*100:+.3f}% r3={sub['r3'].mean()*100:+.3f}%")
# ---- H3: netbuy_T1 横截面分位分组 ----
df["q"] = pd.qcut(df["netbuy_T1"], 5, labels=False, duplicates="drop")
log("H3 netbuy_T1 五分位 → r2/r3:")
for q in sorted(df["q"].dropna().unique()):
    sub = df[df["q"] == q]
    log(f"  Q{int(q)+1} (n={len(sub)}): netbuy中位={sub['netbuy_T1'].median():+.3f} r2={sub['r2'].mean()*100:+.3f}% r3={sub['r3'].mean()*100:+.3f}%")
# 相关性
c2 = df[["netbuy_T1", "r2"]].dropna().corr().iloc[0, 1]
c3 = df[["netbuy_T1", "r3"]].dropna().corr().iloc[0, 1]
log(f"corr(netbuy_T1, r2)={c2:+.4f} | corr(netbuy_T1, r3)={c3:+.4f}")

out = dict(meta=dict(sample_events=len(df), days=[str(cal[d]) for d in DAYS], pool="主板活跃股(涨幅>5%/触板, amt20>=5000万)"),
           h1={("pos" if k else "nonpos"): dict(n=int(len(v)), r2=float(v["r2"].mean()), r3=float(v["r3"].mean()),
               wr2=float(np.mean(v["r2"] > 0))) for k, v in g},
           h2={("above" if k else "below"): dict(n=int(len(v)), r2=float(v["r2"].mean()), r3=float(v["r3"].mean())) for k, v in g2},
           h3=dict(corr_r2=float(c2), corr_r3=float(c3)),
           raw_sample=df.head(30).to_dict(orient="records"))
json.dump(out, open(OUT / "gushi_flow_0914.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
df.to_csv(OUT / "gushi_flow_0914.csv", index=False)
log("saved gushi_flow_0914.json DONE")
