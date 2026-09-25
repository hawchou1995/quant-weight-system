# -*- coding: utf-8 -*-
"""Step2: build float32 panel (CLOSE/OPEN/HIGH/LOW/VOL/AMT) for the universe."""
import json, pathlib, time, numpy as np, pandas as pd
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
OUT = R / "backtest/wechat_hotspot_leader_0925"
U = json.loads((OUT / "universe.json").read_text(encoding="utf-8"))
cal = U["calendar"]; uni = U["universe"]
T = len(cal); N = len(uni)
didx = {d: i for i, d in enumerate(cal)}
print("T=%d N=%d" % (T, N))
F = {k: np.zeros((T, N), dtype=np.float32) for k in ("CLOSE", "OPEN", "HIGH", "LOW", "VOL", "AMT")}
cnt = np.zeros(N, dtype=np.int32)
t0 = time.time(); bad = 0
for j, u in enumerate(uni):
    p = R / "data_full" / (u["sym"] + ".csv")
    try:
        df = pd.read_csv(p)
    except Exception:
        bad += 1; continue
    if df.empty or "date" not in df.columns:
        bad += 1; continue
    for c in ("close", "open", "high", "low", "volume", "amount"):
        if c not in df.columns:
            df[c] = np.nan
    dts = df["date"].astype(str).str.slice(0, 10).to_numpy()
    ri = np.array([didx.get(d, -1) for d in dts], dtype=np.int64)
    ok = ri >= 0
    if not ok.any():
        bad += 1; continue
    ri = ri[ok]
    for nm, col in (("CLOSE", "close"), ("OPEN", "open"), ("HIGH", "high"), ("LOW", "low"),
                    ("VOL", "volume"), ("AMT", "amount")):
        v = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=np.float64)[ok]
        F[nm][ri, j] = v.astype(np.float32)
    cnt[j] = int(ok.sum())
    if (j + 1) % 1000 == 0:
        print("  %d/%d  %.0fs" % (j + 1, N, time.time() - t0), flush=True)
print("loaded %d stocks (bad=%d) in %.0fs" % (N - bad, bad, time.time() - t0))
np.save(S / "wl_cal.npy", np.array(cal, dtype=object), allow_pickle=True)
for nm, a in F.items():
    np.save(S / ("wl_" + nm + ".npy"), a)
np.save(S / "wl_cnt.npy", cnt)
print("panel bytes per field: %.1f MB" % (F["CLOSE"].nbytes / 1e6))
print("cnt: min=%d median=%d max=%d ; 少于250行=%d" % (cnt.min(), int(np.median(cnt)), cnt.max(), int((cnt < 250).sum())))
