# -*- coding: utf-8 -*-
"""oss_0913 批1: 扩展面板指标 — niuone 技术指标全家桶 + ATR
覆盖: BBI(MA3/6/12/24), KDJ(9,3,3, J=3K-2D), EMA20/50, 白线=EMA(EMA(C,10),10),
黄线=(MA14+MA28+MA57+MA114)/4, ATR14(SMA of TR), 振幅, 量比(5/20), 距高低点等.
公式忠实复刻 niuone app/strategies/scoring/common.py + features.py.
"""
import numpy as np, pandas as pd, pickle, os, time

BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
OUT = os.path.join(BASE, "backtest", "oss_0913")
os.makedirs(OUT, exist_ok=True)
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

with open(os.path.join(BASE, "backtest", "factorlab_0913", "panel_0913.pkl"), "rb") as fh:
    P = pickle.load(fh)
cal = P["cal"]; codes = P["codes"]
O = P["open"].astype(np.float64); H = P["high"].astype(np.float64)
L = P["low"].astype(np.float64); C = P["close"].astype(np.float64)
V = P["vol"].astype(np.float64); A = P["amt"].astype(np.float64)
ND, NC = C.shape
log("panel loaded", ND, NC)

# 用 close ffill 做指标连续性 (停牌股指标不中断; 与 niuone 用日线序列口径一致)
Cff = pd.DataFrame(C).ffill().to_numpy()

def sma(df, n):  return df.rolling(n, min_periods=n).mean()
def ema_mat(M, n):
    k = 2.0 / (n + 1); out = np.full_like(M, np.nan); prev = None
    for i in range(M.shape[0]):
        row = M[i]
        if prev is None:
            prev = row.copy()
        else:
            prev = np.where(np.isfinite(row), row * k + prev * (1 - k), prev)
        out[i] = prev
    return out

MA = {n: pd.DataFrame(Cff).rolling(n, min_periods=n).mean().to_numpy() for n in [3, 6, 12, 14, 24, 28, 57, 114]}
BBI = (MA[3] + MA[6] + MA[12] + MA[24]) / 4
log("BBI done")

# KDJ(9,3,3): rsv=(C-LLV9)/(HHV9-LLV9)*100, K=2/3K+1/3rsv, D=2/3D+1/3K, J=3K-2D; 初值 K=D=50
n = 9
LLV = pd.DataFrame(L).rolling(n, min_periods=n).min().to_numpy()
HHV = pd.DataFrame(H).rolling(n, min_periods=n).max().to_numpy()
with np.errstate(all="ignore"):
    span = HHV - LLV
    RSV = np.where(span > 0, (Cff - LLV) / span * 100, 50.0)
RSV = np.where(np.isfinite(LLV), RSV, np.nan)
K = np.full_like(Cff, np.nan); Dk = np.full_like(Cff, np.nan)
kp = np.full(NC, 50.0); dp = np.full(NC, 50.0)
started = np.zeros(NC, bool)
for i in range(ND):
    ok = np.isfinite(RSV[i])
    kp = np.where(ok, 2/3 * kp + 1/3 * RSV[i], kp)
    dp = np.where(ok, 2/3 * dp + 1/3 * kp, dp)
    K[i] = np.where(ok, kp, np.nan); Dk[i] = np.where(ok, dp, np.nan)
J = 3 * K - 2 * Dk
log("KDJ done")

EMA20 = ema_mat(Cff, 20); EMA50 = ema_mat(Cff, 50)
Z_WHITE = ema_mat(ema_mat(Cff, 10), 10)
Z_YELLOW = (MA[14] + MA[28] + MA[57] + MA[114]) / 4
log("EMA/白黄线 done")

# ATR14: TR = max(H-L, |H-Cprev|, |L-Cprev|), SMA 平滑 (niuone SQZ 用 SMA(TR,L); Fibo 用 ATR14)
Cprev = np.vstack([np.full((1, NC), np.nan), Cff[:-1]])
with np.errstate(all="ignore"):
    TR = np.maximum.reduce([H - L, np.abs(H - Cprev), np.abs(L - Cprev)])
ATR14 = pd.DataFrame(TR).rolling(14, min_periods=14).mean().to_numpy()
log("ATR done")

# 其他派生
AMP = (H - L) / pd.DataFrame(Cprev).replace(0, np.nan).to_numpy() * 100       # 振幅% (避除零)
CHG = (Cff / Cprev - 1) * 100                                                   # 涨跌幅%
YANG = (C >= O).astype(np.float64)                                              # 阳线
VR5_20 = pd.DataFrame(V).rolling(5, min_periods=5).mean().to_numpy() / pd.DataFrame(V).rolling(20, min_periods=20).mean().to_numpy()
HI20 = pd.DataFrame(H).rolling(20, min_periods=20).max().to_numpy()
LO20 = pd.DataFrame(L).rolling(20, min_periods=20).min().to_numpy()
HI60 = pd.DataFrame(H).rolling(60, min_periods=60).max().to_numpy()
LO120 = pd.DataFrame(L).rolling(120, min_periods=120).min().to_numpy()
HI120 = pd.DataFrame(H).rolling(120, min_periods=120).max().to_numpy()
VOL5 = pd.DataFrame(V).rolling(5, min_periods=5).mean().to_numpy()

DIST_BBI = (Cff / BBI - 1) * 100
DIST_YELLOW = (Cff / Z_YELLOW - 1) * 100
DD_HI120 = (Cff / HI120 - 1) * 100          # 距120日高点回撤%
DIST_LO120 = (Cff / LO120 - 1) * 100        # 距120日低点%

EXT = {
    "bbi": BBI.astype(np.float32), "kdj_j": J.astype(np.float32), "kdj_k": K.astype(np.float32),
    "ema20": EMA20.astype(np.float32), "ema50": EMA50.astype(np.float32),
    "z_white": Z_WHITE.astype(np.float32), "z_yellow": Z_YELLOW.astype(np.float32),
    "atr14": ATR14.astype(np.float32), "amp": AMP.astype(np.float32), "chg": CHG.astype(np.float32),
    "yang": YANG.astype(np.float32), "vr5_20": VR5_20.astype(np.float32),
    "hi20": HI20.astype(np.float32), "lo20": LO20.astype(np.float32),
    "hi60": HI60.astype(np.float32), "lo120": LO120.astype(np.float32), "hi120": HI120.astype(np.float32),
    "dist_bbi": DIST_BBI.astype(np.float32), "dist_yellow": DIST_YELLOW.astype(np.float32),
    "dd_hi120": DD_HI120.astype(np.float32), "dist_lo120": DIST_LO120.astype(np.float32),
}
log("derived:", len(EXT), "indicators")

P["ext"] = EXT
with open(os.path.join(OUT, "oss_panel_0913.pkl"), "wb") as fh:
    pickle.dump(P, fh, protocol=4)
log("saved oss_panel_0913.pkl", round(os.path.getsize(os.path.join(OUT, "oss_panel_0913.pkl"))/1e6), "MB")

# 断言: KDJ 边界 + BBI 对拍 + 白线递推
i_t, j_t = 500, 0
c0 = Cff[:, j_t]
assert abs(np.nanmean(K[300:, :]) - 50) < 25, "K mean out of range"
man_bbi = (np.nanmean(c0[i_t-2:i_t+1]) + np.nanmean(c0[i_t-5:i_t+1]) + np.nanmean(c0[i_t-11:i_t+1]) + np.nanmean(c0[i_t-23:i_t+1])) / 4
assert abs(BBI[i_t, j_t] - man_bbi) < 1e-6, f"BBI mismatch {BBI[i_t,j_t]} vs {man_bbi}"
man_yellow = (np.nanmean(c0[i_t-13:i_t+1]) + np.nanmean(c0[i_t-27:i_t+1]) + np.nanmean(c0[i_t-56:i_t+1]) + np.nanmean(c0[i_t-113:i_t+1])) / 4
assert abs(Z_YELLOW[i_t, j_t] - man_yellow) < 1e-6, "yellow mismatch"
# 白线: EMA(EMA) 递推抽查 (手工递推前 30 步)
c = c0[:30]; k10 = 2/11; e1 = c[0]; e2 = c[0]; w_prev = None
for x in c:
    e1 = x * k10 + e1 * (1 - k10); e2 = e1 * k10 + e2 * (1 - k10)
assert abs(Z_WHITE[29, j_t] - e2) < 1e-6, f"white mismatch {Z_WHITE[29,j_t]} vs {e2}"
log("ALL ASSERTIONS PASSED")
