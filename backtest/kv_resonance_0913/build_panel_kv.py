# -*- coding: utf-8 -*-
"""Build the shared stock panel for kv_resonance_0913 (S1 徒手哥口诀 + S2 MR行业轮动).

Output: panel_kv_0913.npz  (uncompressed, float32 matrices aligned to cal x codes)
Cal : index_000300.csv dates >= 2016-01-04
Codes: main board (sh6*/sz0*) from data_full (incl. delisted -> no survivorship bias)
"""
import json
import os
import time

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 仓库根（2026-09-24 云端可移植；本机解析恒等）
OUT = os.path.join(BASE, "backtest", "kv_resonance_0913")
os.makedirs(OUT, exist_ok=True)
START = "2016-01-04"
t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:7.1f}s]", *a, flush=True)


# ---------- 1. calendar ----------
idx = pd.read_csv(os.path.join(BASE, "index_000300.csv"), parse_dates=["date"])
cal = idx.loc[idx["date"] >= START, "date"].dt.strftime("%Y-%m-%d").reset_index(drop=True)
ND = len(cal)
di = {d: i for i, d in enumerate(cal)}
log("calendar:", ND, cal.iloc[0], "->", cal.iloc[-1])

# ---------- 2. codes ----------
files = [f for f in os.listdir(os.path.join(BASE, "data_full")) if f.endswith(".csv")]
codes = sorted(os.path.splitext(f)[0] for f in files if f.startswith(("sh6", "sz0")))
NC = len(codes)
ci = {c: i for i, c in enumerate(codes)}
log("main board codes:", NC)

# ---------- 3. load OHLCV ----------
O = np.full((ND, NC), np.nan, dtype=np.float32)
H = np.full((ND, NC), np.nan, dtype=np.float32)
L = np.full((ND, NC), np.nan, dtype=np.float32)
C = np.full((ND, NC), np.nan, dtype=np.float32)
A = np.full((ND, NC), np.nan, dtype=np.float32)
loaded = 0
for k, c in enumerate(codes):
    try:
        df = pd.read_csv(os.path.join(BASE, "data_full", c + ".csv"),
                         usecols=["date", "open", "high", "low", "close", "amount"])
    except Exception as e:
        log("skip", c, e)
        continue
    d = df["date"].astype(str).values
    rows = np.array([di.get(x, -1) for x in d])
    m = rows >= 0
    if not m.any():
        continue
    r = rows[m]
    j = ci[c]
    O[r, j] = df["open"].values[m]
    H[r, j] = df["high"].values[m]
    L[r, j] = df["low"].values[m]
    C[r, j] = df["close"].values[m]
    A[r, j] = df["amount"].values[m]
    loaded += 1
    if (k + 1) % 1000 == 0:
        log("loaded", k + 1, "codes")
log("loaded codes:", loaded)

Od = pd.DataFrame(O)
Hd = pd.DataFrame(H)
Ld = pd.DataFrame(L)
Cd = pd.DataFrame(C)
Ad = pd.DataFrame(A)

# ---------- 4. S1 factors (T-available only) ----------
ret20 = Cd / Cd.shift(20) - 1.0
amt_ratio20 = Ad / Ad.rolling(20, min_periods=10).mean().shift(1)
pc = Cd.shift(1)
tr = pd.concat([(Hd - Ld).stack(), (Hd - pc).abs().stack(), (Ld - pc).abs().stack()], axis=1).max(axis=1).unstack()
atr20 = tr.rolling(20, min_periods=10).mean().shift(1)
longbar = (Cd - Od) / atr20.replace(0, np.nan)
hhv60 = Hd.rolling(60, min_periods=30).max().shift(1)
breakout60 = Cd / hhv60 - 1.0
log("factors computed")

# ---------- 5. labels: T close signal -> T+1 open entry ----------
ent = Od.shift(-1)
fwd5 = Od.shift(-6) / ent - 1.0
fwd10 = Od.shift(-11) / ent - 1.0
fwd20 = Od.shift(-21) / ent - 1.0
log("labels computed")

# ---------- 6. tradable mask ----------
listed = Cd.notna().cumsum()
amt20 = Ad.rolling(20, min_periods=10).mean()
mask = (listed >= 120) & (Cd >= 1.5) & (amt20 >= 1e7)
log("mask mean per day (last 250d):", float(mask.tail(250).sum(axis=1).mean()))

# ---------- 7. industry map ----------
ind_raw = json.load(open(os.path.join(BASE, "stock_industry.json"), encoding="utf-8"))
ind = ind_raw.get("map", ind_raw)
ind_names = sorted(set(ind.values()))
inm = {n: i for i, n in enumerate(ind_names)}
ind_id = np.full(NC, -1, dtype=np.int16)
for c, j in ci.items():
    v = ind.get(c) or ind.get(c[2:])
    if v in inm:
        ind_id[j] = inm[v]
log("industries:", len(ind_names), "| mapped codes:", int((ind_id >= 0).sum()), "/", NC)

# ---------- 8. save ----------
np.savez(os.path.join(OUT, "panel_kv_0913.npz"),
         cal=np.array(cal.values, dtype=object),
         codes=np.array(codes, dtype=object),
         ind_names=np.array(ind_names, dtype=object),
         ind_id=ind_id,
         open=O, high=H, low=L, close=C, amount=A,
         ret20=ret20.values.astype(np.float32),
         amt_ratio20=amt_ratio20.values.astype(np.float32),
         longbar=longbar.values.astype(np.float32),
         breakout60=breakout60.values.astype(np.float32),
         fwd5=fwd5.values.astype(np.float32),
         fwd10=fwd10.values.astype(np.float32),
         fwd20=fwd20.values.astype(np.float32),
         mask=mask.values)
sz = os.path.getsize(os.path.join(OUT, "panel_kv_0913.npz")) / 1024 / 1024
log(f"saved panel_kv_0913.npz {sz:.0f} MB")
# quick sanity
log("ret20 sample:", np.nanmean(ret20.values[-1]), "| fwd5 sample:", np.nanmean(fwd5.values[-30]))
