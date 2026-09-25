# -*- coding: utf-8 -*-
"""Step3: WeChat-article factor  ->  daily signals + portfolio backtest.

Factor (from 《热点刚冒头就能抓到龙头的三个方法》):
  A. 赛道门 = 行业 20 日跌幅最大的前 P1  OR  行业 20 日波动最低的前 P2 且缩量(amt20/amt60<Q)
  B. 个股层 = 行业内「资金集中」代理: 成交额占比 + 波动幅度 + 放量比 + 20日涨幅 (行业内 z 求和)
  C. 买点   = 放量突破: close > HHV(close,60)[t-1]  且  VOL > M * mean(VOL,20)[t-1]
Trade: 信号 T 收盘确认 -> T+1 开盘等权买入 -> 持 H 日 -> 开盘卖出.
"""
import json, pathlib, sys, time, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = R / "backtest/wechat_hotspot_leader_0925"
U = json.loads((OUT / "universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object)
uni = U["universe"]
inds = np.array([u["ind"] for u in uni], dtype=object)
sym = [u["sym"] for u in uni]
T, N = len(cal), len(uni)
P = {k: np.load(S / ("wl_" + k + ".npy")) for k in ("CLOSE", "OPEN", "HIGH", "LOW", "VOL", "AMT")}
C, O, H, L, V, A = (P["CLOSE"], P["OPEN"], P["HIGH"], P["LOW"], P["VOL"], P["AMT"])
t0 = time.time()

def roll_mean(x, w):
    return pd.DataFrame(x).rolling(w, min_periods=max(2, w // 2)).mean().to_numpy(dtype=np.float32)

def roll_std(x, w):
    return pd.DataFrame(x).rolling(w, min_periods=max(2, w // 2)).std().to_numpy(dtype=np.float32)

VALID = (C > 0) & np.isfinite(C) & (O > 0)
Cv = np.where(VALID, C, np.nan)
ret1 = np.zeros_like(Cv); ret1[1:] = Cv[1:] / Cv[:-1] - 1.0
RET20 = np.zeros_like(Cv); RET20[20:] = Cv[20:] / Cv[:-20] - 1.0
AMT20 = roll_mean(np.where(VALID, A, np.nan), 20)
AMT60 = roll_mean(np.where(VALID, A, np.nan), 60)
VOL5 = roll_mean(np.where(VALID, V, np.nan), 5)
VOL60 = roll_mean(np.where(VALID, V, np.nan), 60)
VMA20 = roll_mean(np.where(VALID, V, np.nan), 20)
ATR20 = roll_mean(np.where(VALID, (H - L) / np.where(C > 0, C, np.nan), np.nan), 20)
HHV60 = pd.DataFrame(Cv).rolling(60, min_periods=30).max().to_numpy(dtype=np.float32)
HHV60_prev = np.zeros_like(HHV60); HHV60_prev[1:] = HHV60[:-1]
VMA20_prev = np.zeros_like(VMA20); VMA20_prev[1:] = VMA20[:-1]
NV = np.cumsum(VALID, axis=0).astype(np.int32)          # 上市/有效天数
print("features done %.0fs" % (time.time() - t0), flush=True)

# ---- industry aggregates (equal-weight over valid members) ----
r1f = np.where(VALID & np.isfinite(ret1), ret1, np.nan)
ind_names = sorted(set(inds.tolist()))
IR20 = {}; IV20 = {}; IAMT20 = {}; IAMT60 = {}
for g in ind_names:
    m = (inds == g)
    rg = np.nanmean(r1f[:, m], axis=1)
    s = pd.Series(rg)
    IR20[g] = (s.rolling(20, min_periods=10).apply(lambda x: np.prod(1 + x) - 1, raw=True)).to_numpy()
    IV20[g] = s.rolling(20, min_periods=10).std().to_numpy()
    IAMT20[g] = np.nansum(AMT20[:, m], axis=1)
    IAMT60[g] = np.nansum(AMT60[:, m], axis=1)
IR20 = pd.DataFrame(IR20, index=range(T))[ind_names].to_numpy(dtype=np.float32)
IV20 = pd.DataFrame(IV20, index=range(T))[ind_names].to_numpy(dtype=np.float32)
IAMT20 = pd.DataFrame(IAMT20, index=range(T))[ind_names].to_numpy(dtype=np.float32)
IAMT60 = pd.DataFrame(IAMT60, index=range(T))[ind_names].to_numpy(dtype=np.float32)
gidx = {g: k for k, g in enumerate(ind_names)}
gcol = np.array([gidx[g] for g in inds], dtype=np.int32)
print("industry aggregates done %.0fs  n_ind=%d" % (time.time() - t0, len(ind_names)), flush=True)
np.save(S / "wl_IR20.npy", IR20); np.save(S / "wl_IV20.npy", IV20)
np.save(S / "wl_IAMT20.npy", IAMT20); np.save(S / "wl_IAMT60.npy", IAMT60)
for nm, a in (("RET20", RET20), ("AMT20", AMT20), ("VOL5", VOL5), ("VOL60", VOL60),
              ("VMA20_prev", VMA20_prev), ("ATR20", ATR20), ("HHV60_prev", HHV60_prev),
              ("NV", NV), ("VALID", VALID.astype(np.uint8))):
    np.save(S / ("wl_" + nm + ".npy"), a)
print("saved features")
