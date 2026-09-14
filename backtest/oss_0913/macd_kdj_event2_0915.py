# -*- coding: utf-8 -*-
"""MACD/KDJ 事件型信号快筛 · 第二轮（R-macd-kdj-event2-0915）
素材：知乎《KDJ结合MACD指标的完美使用方法》——本轮测文章强调但首轮未测的形式：
E7 顶背离 ∧ KDJ 超买（J>80）共振（文章："MACD与KDJ同时背离更可靠"/"顶背离+KDJ高位超买做空"）
E8 底背离 ∧ KDJ 低位（J<20）共振
E9 J 下穿 0（文章："0 或负值区域，可大胆买入"）
E10 MACD 金叉 ∧ DIF>0（文章："MACD 黄白线位于 0 轴上方，KDJ 金叉是买入机会"/"只做强势区域"——此处测零轴上金叉）
门（与首轮同）：入场 excess20 ≥ +0.5% 且 |t| ≥ 2.0 且半段同号；E7 为出场候选（≤ −0.5%，t ≤ −2.0）
输出：backtest/oss_0913/macd_kdj_event2_0915.json
"""
import sys, json, time, pickle
import numpy as np, pandas as pd
from pathlib import Path

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)


with open(OUT / "oss_panel_0913.pkl", "rb") as fh:
    P = pickle.load(fh)
cal = P["cal"]
ND, NC = P["close"].shape
O = P["open"].astype(np.float64)
C = P["close"].astype(np.float64)
AMT = P["amt"].astype(np.float64)
st = P["st_mask"]
E = P["ext"]
close_ff = pd.DataFrame(C).ffill().to_numpy()
hist_n = np.cumsum(np.isfinite(O), axis=0)
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
ELIG = (np.isfinite(O) & np.isfinite(C) & (amt20 > 3e6) & (~st[None, :]) & (hist_n >= 150) & (C > 2.0))

S = pd.DataFrame(close_ff)
e12 = S.ewm(span=12, adjust=False).mean()
e26 = S.ewm(span=26, adjust=False).mean()
DIF = (e12 - e26).to_numpy()
DEA = pd.DataFrame(DIF).ewm(span=9, adjust=False).mean().to_numpy()
HIST = DIF - DEA
K = E["kdj_k"].astype(np.float64)
J = E["kdj_j"].astype(np.float64)
D = (3.0 * K - J) / 2.0


def sh(a, n=1):
    r = np.full_like(a, np.nan, dtype=np.float64)
    r[n:] = a[:-n]
    return r


def dedupe(m, gap):
    out = np.array(m, dtype=bool, copy=True)
    for j in range(NC):
        idx = np.where(out[:, j])[0]
        last = -10**9
        for i in idx:
            if i - last <= gap:
                out[i, j] = False
            else:
                last = i
    return out


H1, J1, K1, D1 = sh(HIST), sh(J), sh(K), sh(D)
is_hi = np.isclose(close_ff, S.rolling(20, min_periods=20).max().to_numpy()) & np.isfinite(S.rolling(20, min_periods=20).max().to_numpy())
is_lo = np.isclose(close_ff, S.rolling(20, min_periods=20).min().to_numpy()) & np.isfinite(S.rolling(20, min_periods=20).min().to_numpy())
top_div = np.zeros((ND, NC), dtype=bool)
bot_div = np.zeros((ND, NC), dtype=bool)
for j in range(NC):
    ih = np.where(is_hi[:, j])[0]
    for kk in range(1, len(ih)):
        t, tp = ih[kk], ih[kk - 1]
        if t - tp > 60:
            continue
        if np.isfinite(DIF[t, j]) and np.isfinite(DIF[tp, j]) and DIF[t, j] < DIF[tp, j]:
            top_div[t, j] = True
    il = np.where(is_lo[:, j])[0]
    for kk in range(1, len(il)):
        t, tp = il[kk], il[kk - 1]
        if t - tp > 60:
            continue
        if np.isfinite(DIF[t, j]) and np.isfinite(DIF[tp, j]) and DIF[t, j] > DIF[tp, j]:
            bot_div[t, j] = True

E7 = dedupe(top_div & (J > 80), 10)
E8 = dedupe(bot_div & (J < 20), 10)
E9 = dedupe((J < 0) & (J1 >= 0), 5)
E10 = dedupe((HIST > 0) & (H1 <= 0) & (DIF > 0), 5)
log(f"E7 {int(E7.sum())} | E8 {int(E8.sum())} | E9 {int(E9.sum())} | E10 {int(E10.sum())}")


def fwd(h):
    F = np.full((ND, NC), np.nan)
    F[:ND - 1 - h] = O[1 + h:ND] / O[1:ND - h] - 1
    return F


def study(mask, F, name, expect="pos"):
    m = mask & ELIG & np.isfinite(F)
    n = int(m.sum())
    days = np.where(m.any(axis=1))[0]
    if n < 30 or len(days) < 5:
        return dict(name=name, n=n, nd=len(days), verdict="事件过少")
    base = np.array([np.nanmean(F[i][ELIG[i] & np.isfinite(F[i])]) for i in range(ND)])
    EX = F - base[:, None]
    vals = EX[m]
    daily = np.array([np.nanmean(EX[i][m[i]]) for i in days])
    daily = daily[np.isfinite(daily)]
    mean_all = float(np.nanmean(vals))
    mean_day = float(daily.mean())
    se = float(daily.std(ddof=1) / np.sqrt(len(daily))) if len(daily) > 1 else np.nan
    tt = mean_day / se if se and se > 0 else np.nan
    hit = float((vals > 0).mean())
    half = len(daily) // 2
    h1, h2 = (float(daily[:half].mean()), float(daily[half:].mean())) if half > 0 else (np.nan, np.nan)
    sign_ok = (h1 > 0 and h2 > 0) if expect == "pos" else (h1 < 0 and h2 < 0)
    if expect == "pos":
        pass_ = (mean_all >= 0.005) and (abs(tt) >= 2.0) and sign_ok
    else:
        pass_ = (mean_all <= -0.005) and (tt <= -2.0) and sign_ok
    return dict(name=name, n=n, nd=len(days), excess20=round(mean_all, 4), excess_day=round(mean_day, 4),
                t=round(float(tt), 2), hit=round(hit, 3), h1=round(h1, 4), h2=round(h2, 4),
                verdict=("过门" if pass_ else "不过"))


F20, F60 = fwd(20), fwd(60)
res = {}
for mask, name, nme, expect in ((E7, "E7 顶背离+J>80(出场候选)", "top_div_jhigh", "neg"),
                                (E8, "E8 底背离+J<20(入场)", "bot_div_jlow", "pos"),
                                (E9, "E9 J下穿0(入场)", "j_cross0", "pos"),
                                (E10, "E10 零轴上金叉(入场)", "gc_above0", "pos")):
    r20 = study(mask, F20, name, expect)
    r60 = study(mask, F60, name, expect)
    r = {**r20, "excess60": r60.get("excess20"), "t60": r60.get("t")}
    res[nme] = r
    log(f"{name:22s} n={r.get('n'):6d} 日={r.get('nd'):4d} ex20={r.get('excess20')} t={r.get('t')} "
        f"hit={r.get('hit')} h1/h2={r.get('h1')}/{r.get('h2')} ex60={r.get('excess60')} → {r.get('verdict')}")

json.dump(res, open(OUT / "macd_kdj_event2_0915.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved macd_kdj_event2_0915.json")
