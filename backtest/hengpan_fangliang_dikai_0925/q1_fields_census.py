# -*- coding: utf-8 -*-
"""q1: derive fields for 横盘突然放量+次日低开 and CENSUS the event frequency (rule: count before you run)."""
import json, pathlib, time, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = R/"backtest/wechat_hotspot_leader_0925"
U = json.loads((OUT/"universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); uni = U["universe"]
T, N = len(cal), len(uni)
print("T=%d N=%d  %s..%s" % (T, N, cal[0], cal[-1]))
g = {k: np.load(S/("wl_"+k+".npy"), mmap_mode="r") for k in
     ("CLOSE","OPEN","HIGH","LOW","VOL","AMT","AMT20","RET20","VMA20_prev","NV","VALID")}
C = np.asarray(g["CLOSE"]); O = np.asarray(g["OPEN"]); H = np.asarray(g["HIGH"])
L = np.asarray(g["LOW"]); V = np.asarray(g["VOL"]); A = np.asarray(g["AMT"])
RET20 = np.asarray(g["RET20"]); VMA20P = np.asarray(g["VMA20_prev"])
NV = np.asarray(g["NV"]); VALID = g["VALID"].astype(bool)
def shift1(a):
    b = np.full(a.shape, np.nan, dtype=np.float32); b[1:] = a[:-1]; return b
t0=time.time()
Hv = np.where(VALID, H, np.nan); Lv = np.where(VALID, L, np.nan); Vv = np.where(VALID, V, np.nan)
HH20 = pd.DataFrame(Hv).rolling(20, min_periods=10).max().to_numpy(dtype=np.float32)
LL20 = pd.DataFrame(Lv).rolling(20, min_periods=10).min().to_numpy(dtype=np.float32)
VOL60i = pd.DataFrame(Vv).rolling(60, min_periods=30).mean().to_numpy(dtype=np.float32)
HH20P = shift1(HH20); LL20P = shift1(LL20); VOL60P = shift1(VOL60i); CKP = shift1(C)
del Hv, Lv, Vv, HH20, LL20, VOL60i
print("rolling done %.0fs" % (time.time()-t0), flush=True)
# 横盘振幅（前 20 日，不含 T）: (前期最高 − 前期最低)/前收
RANGE = (HH20P - LL20P) / np.where(CKP > 0, CKP, np.nan)
ABSRET = np.abs(RET20)
VOLBR  = V / np.where(VMA20P > 0, VMA20P, np.nan)          # 放量倍数 = 今日量 / 前 20 日均量
SHRINK = VMA20P / np.where(VOL60P > 0, VOL60P, np.nan)      # 横盘期量能比(20日均量/60日均量)
GAPO   = np.full((T, N), np.nan, dtype=np.float32)          # 次日开盘相对今收的跳空
GAPO[:-1] = O[1:] / np.where(C[:-1] > 0, C[:-1], np.nan) - 1.0
for nm, a in (("RANGE20prev",RANGE),("ABSRET20",ABSRET),("VOLBR",VOLBR),("SHRINK",SHRINK),("GAPNEXT",GAPO)):
    np.save(S/("wl2_"+nm+".npy"), a)
print("saved derived fields %.0fs" % (time.time()-t0), flush=True)
# ---------------- census ----------------
def pct_rank(x):
    o = np.isfinite(x); out = np.full(x.shape, np.nan)
    if o.sum() < 3: return out
    out[o] = (np.argsort(np.argsort(x[o]))+1)/o.sum(); return out
AMT20 = np.asarray(g["AMT20"])
base_ok = lambda t: (VALID[t] & (NV[t] >= 250) & (C[t] >= 2.0) & np.isfinite(AMT20[t]) & (AMT20[t] >= 2e7))
days = [t for t in range(60, T-2)]
tot_base = sum(int(base_ok(t).sum()) for t in days)
print("\neligible (stock,day) pairs = %d  over %d days (mean %.0f/day)" % (tot_base, len(days), tot_base/len(days)))
rows=[]
for Pq in (0.20, 0.30, 0.40):
    for K in (1.5, 2.0, 3.0):
        for SHR in (None, 1.0):
            n_flat=0; n_flat_spk=0; n_gap0=0; n_gap1=0; n_gap2=0; sdays=0; ps=0
            for t in days:
                b = base_ok(t) & np.isfinite(RANGE[t]) & np.isfinite(ABSRET[t]) & np.isfinite(VOLBR[t])
                if b.sum() < 10: continue
                pr = pct_rank(np.where(b, RANGE[t], np.nan)); pa = pct_rank(np.where(b, ABSRET[t], np.nan))
                flat = b & (pr <= Pq) & (pa <= Pq)
                if SHR is not None:
                    flat = flat & np.isfinite(SHRINK[t]) & (SHRINK[t] <= SHR)
                spk = flat & (VOLBR[t] >= K)
                n_flat += int(flat.sum()); n_flat_spk += int(spk.sum())
                g1 = GAPO[t]; ok = spk & np.isfinite(g1)
                n_gap0 += int((ok & (g1 < 0)).sum()); n_gap1 += int((ok & (g1 <= -0.01)).sum()); n_gap2 += int((ok & (g1 <= -0.02)).sum())
                if (ok & (g1 < 0)).any(): sdays += 1
            rows.append(dict(Pq=Pq, K=K, SHR=SHR, flat=n_flat, flat_spk=n_flat_spk, gap_any=n_gap0, gap_le1=n_gap1, gap_le2=n_gap2, sigdays=sdays))
df = pd.DataFrame(rows)
df["flat/y"] = (df["flat"]/9.7).round(0); df["spk/y"]=(df["flat_spk"]/9.7).round(0); df["gap0/y"]=(df["gap_any"]/9.7).round(0)
pd.set_option("display.width", 200)
print("\n=== census: 横盘(振幅分位<=Pq 且 |RET20|分位<=Pq) + 缩量 + 突然放量(VOLBR>=K) + 次日跳空 ===")
print(df.to_string(index=False))
print("\n列义: flat=横盘股日, flat_spk=横盘+突然放量, gap_any=再加次日任意低开, gap_le1/le2=低开>=1%/2%; sigdays=有信号的交易日数; /y=年均")
df.to_json(S/"q1_census.json", orient="records", force_ascii=False, indent=1)
print("saved q1_census.json")


