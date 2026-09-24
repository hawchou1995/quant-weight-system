# -*- coding: utf-8 -*-
"""SUPER 生产信号模块（13 因子 ICIR 复合 · 无行业因子 · 权重冻结）
口径冻结自 super_combo_0913.json（phmed S 1.151 / off0 年化 +22.87% / 50bp 档 S 1.00 / 安慰剂 p=0.000）
供 signal_satellite_0913.py exec 复用；输出与 r6b 引擎同构接口：
  COMP_SUPER (ND,NC) / ELIG_SUPER (ND,NC) / codes / close_m / cal / ND / SUPER_META
"""
import numpy as np, pandas as pd, pickle, json, os
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]  # 仓库根（调用方均注入 __file__ / import 天然有）
FL = BASE / "backtest" / "factorlab_0913"
OUT = BASE / "backtest" / "oss_0913"

# ---- 冻结口径（自 super_combo_0913.json 复现，禁止改参——改参须重跑全链审计）----
META = json.load(open(OUT / "super_combo_0913.json", encoding="utf-8"))["meta"]
PICKED = META["picked"]           # 13 因子
WEIGHTS = META["weights"]         # ICIR 归一权重
SIGN = META["sign"]               # IC 方向
AMT_FLOOR = 3e6; PRICE_FLOOR = 2.0; WARMUP = 150

with open(OUT / "oss_panel_0913.pkl", "rb") as fh:
    P = pickle.load(fh)
with open(FL / "panel_0913.pkl", "rb") as fh:
    FP = pickle.load(fh)
cal = P["cal"]; codes = P["codes"]; st = P["st_mask"]
ND, NC = P["close"].shape
E = P["ext"]; FD = FP["factors"]
O = P["open"].astype(np.float64); H = P["high"].astype(np.float64)
L = P["low"].astype(np.float64); C = P["close"].astype(np.float64)
V = P["vol"].astype(np.float64); AMT = P["amt"].astype(np.float64)
ATR = E["atr14"].astype(np.float64); J = E["kdj_j"].astype(np.float64)
ZW = E["z_white"].astype(np.float64); ZY = E["z_yellow"].astype(np.float64)
close_m = C
close_ff = pd.DataFrame(C).ffill().to_numpy()
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
hist_n = np.cumsum(np.isfinite(O), axis=0)
lo20 = pd.DataFrame(L).rolling(20, min_periods=15).min().to_numpy()
hi20 = pd.DataFrame(H).rolling(20, min_periods=15).max().to_numpy()
hi120 = pd.DataFrame(H).rolling(120, min_periods=80).max().to_numpy()
sig20 = pd.DataFrame(close_ff).rolling(20, min_periods=20).std(ddof=0).to_numpy()
Cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
with np.errstate(all="ignore"):
    TR = np.maximum.reduce([H - L, np.abs(H - Cprev), np.abs(L - Cprev)])
tr20 = pd.DataFrame(TR).rolling(20, min_periods=20).mean().to_numpy()
v5 = pd.DataFrame(V).rolling(5, min_periods=5).mean().to_numpy()
v20 = pd.DataFrame(V).rolling(20, min_periods=20).mean().to_numpy()
lo60 = pd.DataFrame(L).rolling(60, min_periods=40).min().to_numpy()
up90 = pd.DataFrame(H).rolling(90, min_periods=60).max().shift(1).to_numpy()

with np.errstate(all="ignore"):
    ALL = {
        "neg_j": -J, "shrink": -(v5 / v20),
        "low_lift": (lo20 / lo60 - 1) * 100,
        "neg_dbbi": -np.abs(E["dist_bbi"].astype(np.float64)),
        "neg_dyel": -np.abs(E["dist_yellow"].astype(np.float64)),
        "wy_ratio": (ZW / ZY - 1) * 100,
        "neg_sspace": -((close_ff / lo20 - 1) * 100),
        "pspace": (hi20 / close_ff - 1) * 100,
        "dd120": (close_ff / hi120 - 1) * 100,
        "slope_bbi": (E["bbi"].astype(np.float64) / pd.DataFrame(E["bbi"].astype(np.float64)).shift(3).to_numpy() - 1) * 100,
        "sqz_ratio": -(sig20 / tr20),
        "neg_atrp": -(ATR / close_ff) * 100,
        "brk90": (close_ff / up90 - 1) * 100,
        "neg_vr": -(v5 / v20),
    }
for k in ["amount20", "size_rev", "amp20", "ret60", "bp", "size_ep"]:
    ALL[k] = FD[k].astype(np.float64)

ELIG_SUPER = (np.isfinite(O) & np.isfinite(C) & (amt20 >= AMT_FLOOR)
              & (~st[None, :]) & (hist_n >= WARMUP) & (C > PRICE_FLOOR))

def _composite():
    num = np.zeros((ND, NC)); den = np.zeros((ND, NC))
    for k in PICKED:
        a = np.where(ELIG_SUPER, ALL[k] * SIGN[k], np.nan)
        mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
        z = np.clip((a - mu) / (sd + 1e-12), -3, 3)
        ok = np.isfinite(z)
        num += np.where(ok, z * WEIGHTS[k], 0.0); den += np.where(ok, WEIGHTS[k], 0.0)
    return np.where(den > 0.4 * sum(WEIGHTS.values()), num / np.maximum(den, 1e-9), np.nan)

COMP_SUPER = _composite()
SUPER_META = dict(picked=PICKED, weights=WEIGHTS, sign=SIGN,
                  source="super_combo_0913.json (phmed S 1.151)", asof=str(cal[-1]))
