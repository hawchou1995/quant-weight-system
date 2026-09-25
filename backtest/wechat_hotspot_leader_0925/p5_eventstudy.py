# -*- coding: utf-8 -*-
"""Step5b: layer counts + event study (no slot constraint) -> bug or real?"""
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
gcol = np.array([gidx[x] for x in inds], dtype=np.int32)
NV = g["NV"]

def pct_rank(x):
    ok = np.isfinite(x); out = np.full(x.shape, np.nan)
    if ok.sum() < 3: return out
    v = x[ok]; out[ok] = (np.argsort(np.argsort(v)) + 1) / len(v)
    return out

def zz(x, base_mask):
    out = np.full(N, np.nan)
    for gg in np.unique(gcol[base_mask]):
        m = base_mask & (gcol == gg)
        if m.sum() < 2: continue
        v = x[m]; mu, sd = np.nanmean(v), np.nanstd(v)
        if not np.isfinite(sd) or sd <= 0: continue
        out[m] = (x[m] - mu) / sd
    return out

P1,P2,Q,M,MINAMT,KNEW,LISTED,MINPX = 0.20,0.30,0.80,1.5,2e7,3,250,2.0
rec = []            # per-day layer counts
allC = []           # event study: every candidate
topC = []           # event study: top-KNEW only
H = 10
for t in range(60, T-1):
    ir, iv = g["IR20"][t], g["IV20"][t]
    ia20, ia60 = g["IAMT20"][t], g["IAMT60"][t]
    okg = np.isfinite(ir) & np.isfinite(iv) & np.isfinite(ia60) & (ia60 > 0)
    if okg.sum() < 5: continue
    r_ir = pct_rank(np.where(okg, ir, np.nan)); r_iv = pct_rank(np.where(okg, iv, np.nan))
    shrink = np.isfinite(ia20) & (ia20 / np.where(ia60 > 0, ia60, np.nan) < Q)
    gate = np.where(okg, (r_ir <= P1) | ((r_iv <= P2) & shrink), False)
    amt20, vma_p, hhv_p = g["AMT20"][t], g["VMA20_prev"][t], g["HHV60_prev"][t]
    elig = (VALID[t] & (NV[t] >= LISTED) & (C[t] >= MINPX) & np.isfinite(amt20) & (amt20 >= MINAMT) & gate[gcol])
    brk = np.isfinite(hhv_p) & np.isfinite(vma_p) & (vma_p > 0) & (C[t] > hhv_p) & (V[t] > M * vma_p)
    cand = elig & brk
    if not cand.any(): continue
    ci = np.nonzero(cand)[0]
    share = g["AMT20"][t] / np.where(g["IAMT20"][t][gcol] > 0, g["IAMT20"][t][gcol], np.nan)
    vr = g["VOL5"][t] / np.where(g["VOL60"][t] > 0, g["VOL60"][t], np.nan)
    F = np.zeros(N)
    for x in (share, g["ATR20"][t], vr, g["RET20"][t]):
        z = zz(np.where(np.isfinite(x), x, np.nan), elig)
        F = F + np.where(np.isfinite(z), z, 0.0)
    order = ci[np.argsort(-F[ci])][:KNEW]
    if t+1+H >= T: continue
    o1 = O[t+1]; o2 = O[t+1+H]
    fwd = o2/o1 - 1.0
    ok1 = np.isfinite(o1) & (o1>0) & np.isfinite(o2) & (o2>0)
    gap = o1/np.where(C[t]>0, C[t], np.nan) - 1.0
    rec.append(dict(d=str(cal[t]), n_okg=int(okg.sum()), n_gate=int(gate.sum()), n_elig=int(elig.sum()),
                    n_cand=int(cand.sum()), n_top=len(order)))
    for j in ci:
        if ok1[j]: allC.append(dict(y=str(cal[t])[:4], code=sym[j], ret=float(fwd[j])*100, gap=float(gap[j])*100, z=F[j]))
    for j in order:
        if ok1[j]: topC.append(dict(y=str(cal[t])[:4], code=sym[j], ret=float(fwd[j])*100, gap=float(gap[j])*100, z=F[j]))
R_ = pd.DataFrame(rec); A_ = pd.DataFrame(allC); T_ = pd.DataFrame(topC)
print("\n--- B. layer counts (per signal day) ---")
print("signal days=%d  (of %d loop days)" % (len(R_), T-61))
print(R_[["n_okg","n_gate","n_elig","n_cand","n_top"]].describe().loc[["mean","50%","min","max"]].round(1).to_string())
print("\nfirst 6 signal days:"); print(R_.head(6).to_string(index=False))
print("\nlast 6 signal days:"); print(R_.tail(6).to_string(index=False))
def stat(df, tag):
    r = df["ret"]
    print("%-22s n=%6d  mean %+.3f%%  med %+.3f%%  wr %.1f%%  p25 %+.2f  p75 %+.2f  gap_open_mean %+.2f%%" %
          (tag, len(r), r.mean(), r.median(), 100*(r>0).mean(), r.quantile(.25), r.quantile(.75), df["gap"].mean()))
print("\n--- C. event study: OPEN[t+1] -> OPEN[t+1+%d] (no slot constraint) ---" % H)
stat(A_, "ALL candidates")
stat(T_, "TOP-%d by F" % KNEW)
print("\nby year (ALL / TOP):")
for y in sorted(A_["y"].unique()):
    a = A_[A_["y"]==y]; t_ = T_[T_["y"]==y]
    print("  %s  ALL n=%5d mean %+7.3f%% wr %4.1f%%   |  TOP n=%5d mean %+7.3f%% wr %4.1f%%   gap %+5.2f%%" %
          (y, len(a), a["ret"].mean(), 100*(a["ret"]>0).mean(), len(t_), t_["ret"].mean() if len(t_) else float('nan'),
           100*(t_["ret"]>0).mean() if len(t_) else float('nan'), t_["gap"].mean() if len(t_) else float('nan')))
print("\n--- D. entry feasibility: share of top-K entries with open gap > +9.5%% (near limit-up, likely unfillable) ---")
print("gap>9.5%%: %.2f%%   gap>5%%: %.2f%%   gap<-5%%: %.2f%%" % (100*(T_["gap"]>9.5).mean(), 100*(T_["gap"]>5).mean(), 100*(T_["gap"]<-5).mean()))
json.dump(dict(layer=R_.to_dict("records"),
               ev_all=dict(n=int(len(A_)), mean=round(float(A_["ret"].mean()),4), med=round(float(A_["ret"].median()),4), wr=round(float(100*(A_["ret"]>0).mean()),2)),
               ev_top=dict(n=int(len(T_)), mean=round(float(T_["ret"].mean()),4), med=round(float(T_["ret"].median()),4), wr=round(float(100*(T_["ret"]>0).mean()),2)),
               entry_gap_gt95_pct=round(float(100*(T_["gap"]>9.5).mean()),2)),
          open(S/"w5_diag.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved w5_diag.json")
