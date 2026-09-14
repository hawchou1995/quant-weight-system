# -*- coding: utf-8 -*-
"""MACD/KDJ 事件型信号快筛（预注册 R-macd-kdj-event-0915）
素材：知乎《KDJ结合MACD指标的完美使用方法》（p/600351017）
事件：E1 双金叉 / E2 强势区超跌 / E3 顶背离 / E4 底背离 / E5 单阳背离 / E6 单阴背离
方法：事件研究——超额 = 事件股 fwd − 同日 ELIG 截面均值；日聚类 t 检验
门：入场 excess20 ≥ +0.5% 且 |t| ≥ 2.0 且半段同号；E3/E6 反号（≤ −0.5%，t ≤ −2.0）
输出：backtest/oss_0913/macd_kdj_event_0915.json
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
codes = [str(c) for c in P["codes"]]
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
log(f"panel {ND}×{NC} | ELIG/日≈{ELIG.sum(1).mean():.0f}")

S = pd.DataFrame(close_ff)
e12 = S.ewm(span=12, adjust=False).mean()
e26 = S.ewm(span=26, adjust=False).mean()
DIF = (e12 - e26).to_numpy()
DEA = pd.DataFrame(DIF).ewm(span=9, adjust=False).mean().to_numpy()
HIST = DIF - DEA
K = E["kdj_k"].astype(np.float64)
J = E["kdj_j"].astype(np.float64)
D = (3.0 * K - J) / 2.0
chg1 = S.pct_change().to_numpy()


def sh(a, n=1):
    r = np.full_like(a, np.nan, dtype=np.float64)
    r[n:] = a[:-n]
    return r


def anyk(m, k):
    """近 k 日内（含今日）是否发生过"""
    m = np.asarray(m, dtype=bool)
    out = m.copy()
    for i in range(1, k):
        out |= sh(m.astype(np.float64), i) > 0.5
    return out


def dedupe(m, gap):
    """同标的同型事件 gap 日内只留首次"""
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


H1, K1, D1, J1 = sh(HIST), sh(K), sh(D), sh(J)
gc_macd = (HIST > 0) & (H1 <= 0)
gc_kdj_low = (K > D) & (K1 <= D1) & (J < 50)
E1 = dedupe(anyk(gc_macd, 3) & anyk(gc_kdj_low, 3), 5)
E2 = dedupe((DIF > 0) & (J < 20) & (J1 >= 20), 5)
E5 = dedupe((chg1 >= 0.06) & (HIST < 0), 5)
E6 = dedupe((chg1 <= -0.06) & (HIST > 0), 5)

# ---- 背离：20 日新高/新低 + DIF 不创新高/新低 ----
hi20c = S.rolling(20, min_periods=20).max().to_numpy()
lo20c = S.rolling(20, min_periods=20).min().to_numpy()
is_hi = np.isclose(close_ff, hi20c) & np.isfinite(hi20c)
is_lo = np.isclose(close_ff, lo20c) & np.isfinite(lo20c)
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
E3 = dedupe(top_div, 10)
E4 = dedupe(bot_div, 10)
log(f"事件计数（去重前/后）：E1 {int((anyk(gc_macd,3)&anyk(gc_kdj_low,3)).sum())}→{int(E1.sum())} | E2 {int(E2.sum())} | "
    f"E3 {int(top_div.sum())}→{int(E3.sum())} | E4 {int(bot_div.sum())}→{int(E4.sum())} | E5 {int(E5.sum())} | E6 {int(E6.sum())}")


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
    se = float(daily.std(ddof=1) / np.sqrt(len(days))) if len(days) > 1 else np.nan
    tt = mean_day / se if se and se > 0 else np.nan
    hit = float((vals > 0).mean())
    half = len(days) // 2
    h1, h2 = float(daily[:half].mean()), float(daily[half:].mean())
    sign_ok = (h1 > 0 and h2 > 0) if expect == "pos" else (h1 < 0 and h2 < 0)
    if expect == "pos":
        pass_ = (mean_all >= 0.005) and (abs(tt) >= 2.0) and sign_ok
    else:
        pass_ = (mean_all <= -0.005) and (tt <= -2.0) and sign_ok
    return dict(name=name, n=n, nd=len(days), excess20=round(mean_all, 4), excess_day=round(mean_day, 4),
                t=round(float(tt), 2), hit=round(hit, 3), h1=round(h1, 4), h2=round(h2, 4),
                verdict=("过门" if pass_ else "不过"))


log("=== fwd20 事件研究 ===")
F20, F60 = fwd(20), fwd(60)
res = {}
for mask, name, nme, expect in ((E1, "E1 双金叉(入场)", "dual_gc", "pos"),
                                (E2, "E2 强势区超跌(入场)", "zero_up_os", "pos"),
                                (E3, "E3 顶背离(出场候选)", "top_div", "neg"),
                                (E4, "E4 底背离(入场)", "bot_div", "pos"),
                                (E5, "E5 单阳背离(入场)", "big_up_neg", "pos"),
                                (E6, "E6 单阴背离(出场候选)", "big_dn_pos", "neg")):
    r20 = study(mask, F20, name, expect)
    r60 = study(mask, F60, name, expect)
    r = {**r20, "excess60": r60.get("excess20"), "t60": r60.get("t")}
    res[nme] = r
    log(f"{name:20s} n={r.get('n'):6d} 日={r.get('nd'):4d} ex20={r.get('excess20')} t={r.get('t')} "
        f"hit={r.get('hit')} h1/h2={r.get('h1')}/{r.get('h2')} ex60={r.get('excess60')} → {r.get('verdict')}")

json.dump(res, open(OUT / "macd_kdj_event_0915.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved macd_kdj_event_0915.json")
