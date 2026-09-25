# -*- coding: utf-8 -*-
"""Step6b (FIXED): factor decomposition. FWD now NaN unless BOTH opens > 0."""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = R / "backtest/wechat_hotspot_leader_0925"
U = json.loads((OUT / "universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); uni = U["universe"]
inds = np.array([u["ind"] for u in uni], dtype=object); sym = np.array([u["sym"] for u in uni])
T, N = len(cal), len(uni)
g = {k: np.load(S / ("wl_" + k + ".npy"), mmap_mode="r") for k in
     ("CLOSE","OPEN","VOL","AMT","RET20","AMT20","VOL5","VOL60","VMA20_prev","ATR20","HHV60_prev","NV","VALID","IR20","IV20","IAMT20","IAMT60")}
C = np.asarray(g["CLOSE"]); O = np.asarray(g["OPEN"]); V = np.asarray(g["VOL"])
VALID = g["VALID"].astype(bool)
ind_names = sorted(set(inds.tolist())); gidx = {x:k for k,x in enumerate(ind_names)}
gcol = np.array([gidx[x] for x in inds], dtype=np.int32); NV = g["NV"]
H = 10
FWD = np.full((T, N), np.nan, dtype=np.float32)
num = O[H+1:]; den = O[1:T-H]
ok = (num > 0) & (den > 0) & np.isfinite(num) & np.isfinite(den)
tmp = np.full((T-H-1, N), np.nan, dtype=np.float32); tmp[ok] = num[ok]/den[ok] - 1.0
FWD[:T-H-1] = tmp
print("FWD finite cells: %d ; rows usable: %d..%d" % (int(np.isfinite(FWD).sum()), 60, T-H-2))
def pct_rank(x):
    o = np.isfinite(x); out = np.full(x.shape, np.nan)
    if o.sum() < 3: return out
    out[o] = (np.argsort(np.argsort(x[o])) + 1) / o.sum(); return out
def zz(x, base_mask):
    out = np.full(N, np.nan)
    for gg in np.unique(gcol[base_mask]):
        m = base_mask & (gcol == gg)
        if m.sum() < 2: continue
        v = x[m]; mu, sd = np.nanmean(v), np.nanstd(v)
        if not np.isfinite(sd) or sd <= 0: continue
        out[m] = (x[m] - mu) / sd
    return out
BRKC = (C > g["HHV60_prev"]) & np.isfinite(g["HHV60_prev"]) & VALID
cs = np.cumsum(BRKC.astype(np.int64), axis=0)
BRK20prev = np.zeros((T, N), dtype=np.int32)
ii = np.arange(21, T); BRK20prev[ii] = (cs[ii-1] - cs[ii-21]).astype(np.int32)
P1,P2,Q,M,MINAMT,KNEW,LISTED,MINPX = 0.20,0.30,0.80,1.5,2e7,3,250,2.0
KEYS = ("V0_control","V1_gate_only","V2_brk_only","V3_gate_brk_ALL","V4_top3_F","V5a_top3_share",
        "V5b_top3_atr","V5c_top3_vr","V5d_top3_ret20","V6_firstbrk_top3F","V7_firstbrk_lowret20")
acc = {k: [] for k in KEYS}
ndays = {k: 0 for k in KEYS}
for t in range(60, T-H-1):
    ir, iv = g["IR20"][t], g["IV20"][t]; ia20, ia60 = g["IAMT20"][t], g["IAMT60"][t]
    okg = np.isfinite(ir) & np.isfinite(iv) & np.isfinite(ia60) & (ia60 > 0)
    if okg.sum() < 5: continue
    r_ir = pct_rank(np.where(okg, ir, np.nan)); r_iv = pct_rank(np.where(okg, iv, np.nan))
    shrink = np.isfinite(ia20) & (ia20 / np.where(ia60 > 0, ia60, np.nan) < Q)
    gate = np.where(okg, (r_ir <= P1) | ((r_iv <= P2) & shrink), False)
    amt20, vma_p, hhv_p = g["AMT20"][t], g["VMA20_prev"][t], g["HHV60_prev"][t]
    base = (VALID[t] & (NV[t] >= LISTED) & (C[t] >= MINPX) & np.isfinite(amt20) & (amt20 >= MINAMT))
    elig = base & gate[gcol]
    brk = (np.isfinite(hhv_p) & np.isfinite(vma_p) & (vma_p > 0) & (C[t] > hhv_p) & (V[t] > M * vma_p))
    fw = FWD[t]
    def put(key, mask):
        m = mask & np.isfinite(fw)
        if m.sum(): acc[key].append(fw[m]); ndays[key] += 1
    put("V0_control", base); put("V1_gate_only", elig)
    put("V2_brk_only", base & brk); put("V3_gate_brk_ALL", elig & brk)
    cand = elig & brk
    if not cand.any(): continue
    ci = np.nonzero(cand)[0]
    share = g["AMT20"][t] / np.where(g["IAMT20"][t][gcol] > 0, g["IAMT20"][t][gcol], np.nan)
    vr = g["VOL5"][t] / np.where(g["VOL60"][t] > 0, g["VOL60"][t], np.nan)
    Z = {}
    for k_, x in (("share", share), ("atr", g["ATR20"][t]), ("vr", vr), ("ret20", g["RET20"][t])):
        Z[k_] = zz(np.where(np.isfinite(x), x, np.nan), elig)
    F = sum(np.where(np.isfinite(Z[k_]), Z[k_], 0.0) for k_ in ("share","atr","vr","ret20"))
    def topk(key, score, pool):
        pc = np.nonzero(pool)[0]
        if not pc.size: return
        s = np.where(np.isfinite(score), score, -1e9)[pc]
        sel = pc[np.argsort(-s)][:KNEW]
        mk = np.zeros(N, dtype=bool); mk[sel] = True
        put(key, mk)
    topk("V4_top3_F", F, cand)
    for key, k_ in (("V5a_top3_share","share"),("V5b_top3_atr","atr"),("V5c_top3_vr","vr"),("V5d_top3_ret20","ret20")):
        topk(key, Z[k_], cand)
    first = cand & (BRK20prev[t] == 0)
    topk("V6_firstbrk_top3F", F, first)
    if first.any():
        rm = g["RET20"][t]; low = np.zeros(N, dtype=bool)
        for gg in np.unique(gcol[first]):
            m = first & (gcol == gg)
            if m.sum() < 2: continue
            low[m] = rm[m] <= np.nanmedian(rm[m])
        topk("V7_firstbrk_lowret20", F, first & low)
print("\n=== FIXED decomposition: fwd %d-day open-to-open, entry T+1, both opens valid, no slots ===" % H)
out = {}
for k in KEYS:
    if not acc[k]: print("  %-22s (no data)" % k); continue
    a = np.concatenate(acc[k]) * 100
    out[k] = dict(obs=int(a.size), sig_days=ndays[k], mean_pct=round(float(a.mean()),4),
                  med_pct=round(float(np.median(a)),3), wr_pct=round(float(100*(a>0).mean()),2))
    print("  %-22s days=%4d obs=%9d  mean %+7.4f%%  med %+7.3f%%  wr %5.2f%%" % (k, ndays[k], a.size, a.mean(), np.median(a), 100*(a>0).mean()))
json.dump(out, open(S/"w6b_decomp.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved w6b_decomp.json")
