# -*- coding: utf-8 -*-
"""Step9: census of why signals are not traded (slot full / invalid entry open / already held / end of data)."""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = R / "backtest/wechat_hotspot_leader_0925"
U = json.loads((OUT/"universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); uni = U["universe"]
inds = np.array([u["ind"] for u in uni], dtype=object)
T, N = len(cal), len(uni)
g = {k: np.load(S/("wl_"+k+".npy"), mmap_mode="r") for k in
     ("CLOSE","OPEN","VOL","AMT","RET20","AMT20","VOL5","VOL60","VMA20_prev","ATR20","HHV60_prev","NV","VALID","IR20","IV20","IAMT20","IAMT60")}
C = np.asarray(g["CLOSE"]); O = np.asarray(g["OPEN"]); V = np.asarray(g["VOL"]); VALID = g["VALID"].astype(bool)
ind_names = sorted(set(inds.tolist())); gidx = {x:k for k,x in enumerate(ind_names)}
gcol = np.array([gidx[x] for x in inds], dtype=np.int32); NV = g["NV"]
def pct_rank(x):
    o=np.isfinite(x); out=np.full(x.shape,np.nan)
    if o.sum()<3: return out
    out[o]=(np.argsort(np.argsort(x[o]))+1)/o.sum(); return out
def zz(x,bm):
    out=np.full(N,np.nan)
    for gg in np.unique(gcol[bm]):
        m=bm&(gcol==gg)
        if m.sum()<2: continue
        v=x[m]; mu,sd=np.nanmean(v),np.nanstd(v)
        if not np.isfinite(sd) or sd<=0: continue
        out[m]=(x[m]-mu)/sd
    return out
P1,P2,Q,M,MIN_AMT,KNEW,LISTED,MINPX,H = .20,.30,.80,1.5,2e7,3,250,2.0,10
sig=[None]*T; nsig=0
for t in range(60,T):
    ir,iv=g["IR20"][t],g["IV20"][t]; ia20,ia60=g["IAMT20"][t],g["IAMT60"][t]
    okg=np.isfinite(ir)&np.isfinite(iv)&np.isfinite(ia60)&(ia60>0)
    if okg.sum()<5: continue
    r_ir=pct_rank(np.where(okg,ir,np.nan)); r_iv=pct_rank(np.where(okg,iv,np.nan))
    shrink=np.isfinite(ia20)&(ia20/np.where(ia60>0,ia60,np.nan)<Q)
    gate=np.where(okg,(r_ir<=P1)|((r_iv<=P2)&shrink),False)
    amt20,vma_p,hhv_p=g["AMT20"][t],g["VMA20_prev"][t],g["HHV60_prev"][t]
    elig=(VALID[t]&(NV[t]>=LISTED)&(C[t]>=MINPX)&np.isfinite(amt20)&(amt20>=MIN_AMT)&gate[gcol])
    if not elig.any(): continue
    cand=elig&(np.isfinite(hhv_p)&np.isfinite(vma_p)&(vma_p>0)&(C[t]>hhv_p)&(V[t]>M*vma_p))
    if not cand.any(): continue
    share=g["AMT20"][t]/np.where(g["IAMT20"][t][gcol]>0,g["IAMT20"][t][gcol],np.nan)
    vr=g["VOL5"][t]/np.where(g["VOL60"][t]>0,g["VOL60"][t],np.nan)
    F=np.zeros(N)
    for x in (share,g["ATR20"][t],vr,g["RET20"][t]):
        z=zz(np.where(np.isfinite(x),x,np.nan),elig); F=F+np.where(np.isfinite(z),z,0.0)
    ci=np.nonzero(cand)[0]; sig[t]=ci[np.argsort(-F[ci])][:KNEW].tolist(); nsig+=len(sig[t])
def simulate(KSLOT, cost_side=0.0):
    ts=next(t for t in range(T) if sig[t])
    cash=1.0; pos={}; nav=np.full(T,np.nan); nav[ts-1]=1.0
    pending=sig[ts-1] if sig[ts-1] else []
    cen=dict(slot_full=0, invalid_open=0, already_held=0, ok=0); rows=[]
    for t in range(ts,T):
        for j in [j for j,p in pos.items() if p["exit"]<=t]:
            p=pos[j]; px=O[t,j]
            if np.isfinite(px) and px>0:
                pos.pop(j); cash+=p["sh"]*px*(1-cost_side); cen["ok"]+=1
                rows.append((p["sg"], j, t))
            else: p["exit"]=t+1
        for j in pending:
            if len(pos)>=KSLOT: cen["slot_full"]+=1; continue
            if j in pos: cen["already_held"]+=1; continue
            px=O[t,j]
            if not (np.isfinite(px) and px>0): cen["invalid_open"]+=1; continue
            navprev=nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            alloc=min(navprev/KSLOT,cash)
            if alloc<=1e-9: cen["slot_full"]+=1; continue
            pos[j]=dict(en=t,exit=t+H,sg=t-1,sh=alloc/(px*(1+cost_side)),px=px); cash-=alloc
        pending=sig[t] if sig[t] else []
        mv=0.0
        for j,p in pos.items():
            c=C[t,j]; mv+=p["sh"]*(c if np.isfinite(c) and c>0 else p["px"])
        nav[t]=cash+mv
    return nav, cen, rows
print("signals total = %d" % nsig)
nav, cen, rows = simulate(30, 0.0)
tot = sum(cen.values()); print("census over executed decisions: %s  (traded=%d / signals=%d = %.1f%%)" % (cen, cen["ok"], nsig, 100.0*cen["ok"]/nsig))
print("untraded signals = %d  (slot_full %d + invalid_open %d + already_held %d)" % (nsig-cen["ok"], cen["slot_full"], cen["invalid_open"], cen["already_held"]))
last_sig = max(t for t in range(T) if sig[t]); print("last signal day = %s (idx %d) ; signals in final %d days have no room to exit" % (cal[last_sig], last_sig, H))
byy = {}
for sg, j, t in rows:
    y = str(cal[t])[:4]; byy.setdefault(y, [0,0]); byy[y][0]+=1
for t in range(T):
    if sig[t]: byy.setdefault(str(cal[t])[:4], [0,0])[1] += len(sig[t])
print("\nyear  traded / signals  coverage")
for y in sorted(byy): print("  %s  %5d / %5d   %5.1f%%" % (y, byy[y][0], byy[y][1], 100.0*byy[y][0]/max(1,byy[y][1])))
# entry-open validity of untraded-invalid signals
print("\nsanity: OPEN[t+1]<=0 counts among signals (entry impossible):")
cnt=0; tot2=0
for t in range(T-11):
    if not sig[t]: continue
    for j in sig[t]:
        tot2+=1
        if not (np.isfinite(O[t+1,j]) and O[t+1,j]>0): cnt+=1
print("  %d / %d = %.2f%%" % (cnt, tot2, 100.0*cnt/max(1,tot2)))
json.dump(dict(nsig=nsig, census=cen, coverage_by_year={k: dict(traded=v[0], signals=v[1]) for k,v in sorted(byy.items())},
               entry_open_invalid_pct=round(100.0*cnt/max(1,tot2),3)),
          open(S/"w9_census.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved w9_census.json")
