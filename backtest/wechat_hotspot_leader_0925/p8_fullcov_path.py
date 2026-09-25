# -*- coding: utf-8 -*-
"""Step8: FULL-COVERAGE factor portfolio (KSLOT=KNEW*H -> every signal traded) + average holding path."""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = R / "backtest/wechat_hotspot_leader_0925"
U = json.loads((OUT/"universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); uni = U["universe"]
inds = np.array([u["ind"] for u in uni], dtype=object); sym = [u["sym"] for u in uni]
T, N = len(cal), len(uni)
g = {k: np.load(S/("wl_"+k+".npy"), mmap_mode="r") for k in
     ("CLOSE","OPEN","VOL","AMT","RET20","AMT20","VOL5","VOL60","VMA20_prev","ATR20","HHV60_prev","NV","VALID","IR20","IV20","IAMT20","IAMT60")}
C = np.asarray(g["CLOSE"]); O = np.asarray(g["OPEN"]); V = np.asarray(g["VOL"]); VALID = g["VALID"].astype(bool)
ind_names = sorted(set(inds.tolist())); gidx = {x:k for k,x in enumerate(ind_names)}
gcol = np.array([gidx[x] for x in inds], dtype=np.int32); NV = g["NV"]
IDX = pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
IDX = IDX.set_index("date").reindex(cal)
BC = pd.to_numeric(IDX["close"], errors="coerce").to_numpy(float)
BO = pd.to_numeric(IDX["open"], errors="coerce").to_numpy(float)
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
sig=[None]*T
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
    ci=np.nonzero(cand)[0]; sig[t]=ci[np.argsort(-F[ci])][:KNEW].tolist()
nsig=sum(len(x) for x in sig if x); print("signals total=%d over %d days" % (nsig, sum(1 for x in sig if x)))
def simulate(KSLOT, cost_side=0.0):
    ts=next(t for t in range(T) if sig[t])
    cash=1.0; pos={}; nav=np.full(T,np.nan); trades=[]; nav[ts-1]=1.0
    pending=sig[ts-1] if sig[ts-1] else []
    for t in range(ts,T):
        for j in [j for j,p in pos.items() if p["exit"]<=t]:
            p=pos[j]; px=O[t,j]
            if np.isfinite(px) and px>0:
                pos.pop(j); cash+=p["sh"]*px*(1-cost_side)
                trades.append(dict(entry_date=str(cal[p["en"]]), exit_date=str(cal[t]), code=sym[j], sg=p["sg"],
                    ret_pct=round((px*(1-cost_side)/(p["px"]*(1+cost_side))-1)*100,3), days=int(t-p["en"])))
            else: p["exit"]=t+1
        for j in pending:
            if len(pos)>=KSLOT: break
            if j in pos: continue
            px=O[t,j]
            if not (np.isfinite(px) and px>0): continue
            navprev=nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            alloc=min(navprev/KSLOT,cash)
            if alloc<=1e-9: break
            pos[j]=dict(en=t,exit=t+H,sg=t-1,sh=alloc/(px*(1+cost_side)),px=px); cash-=alloc
        pending=sig[t] if sig[t] else []
        mv=0.0
        for j,p in pos.items():
            c=C[t,j]; mv+=p["sh"]*(c if np.isfinite(c) and c>0 else p["px"])
        nav[t]=cash+mv
    bnav=np.full(T,np.nan); bnav[ts-1]=1.0
    b0=BO[ts] if np.isfinite(BO[ts]) and BO[ts]>0 else BC[ts]
    for t in range(ts,T): bnav[t]=BC[t]/b0
    return nav,bnav,trades,ts
def metrics(nav,bnav,trades):
    ok=np.isfinite(nav); v=nav[ok]; b=bnav[ok]; nd=len(v)-1
    ann=(v[-1]/v[0])**(244/nd)-1; peak=np.maximum.accumulate(v); mdd=float((v/peak-1).min())
    dr=v[1:]/v[:-1]-1; sd=dr.std(ddof=1)
    bann=(b[-1]/b[0])**(244/nd)-1; bpk=np.maximum.accumulate(b)
    r=np.array([x["ret_pct"] for x in trades],float); yrs={}
    for x in trades: yrs.setdefault(x["exit_date"][:4],[]).append(x["ret_pct"])
    return dict(total_pct=round((v[-1]/v[0]-1)*100,2), ann_pct=round(ann*100,2), mdd_pct=round(mdd*100,2),
        sharpe=round(float(dr.mean()/sd*np.sqrt(244)),3) if sd>0 else None,
        bench_total_pct=round((b[-1]/b[0]-1)*100,2), bench_ann_pct=round(bann*100,2),
        bench_mdd_pct=round(float((b/bpk-1).min())*100,2), excess_ann_pp=round((ann-bann)*100,2),
        n=int(r.size), mean_pct=round(float(r.mean()),3), med_pct=round(float(np.median(r)),3),
        wr_pct=round(100*float((r>0).mean()),1), avg_days=round(float(np.mean([x["days"] for x in trades])),1),
        n_years_neg=sum(1 for k,vv in yrs.items() if np.mean(vv)<0),
        per_year={k: dict(n=len(vv), mean=round(float(np.mean(vv)),3)) for k,vv in sorted(yrs.items())})
res={}
print("\n=== FULL-COVERAGE factor portfolio: KNEW=3, KSLOT=30 (=KNEW*H), H=10 ===")
for nm,cs in (("0bp",0.0),("20bp",0.0010),("115bp",0.00575)):
    nav,bnav,tr,ts=simulate(30,cs); m=metrics(nav,bnav,tr); m["start_date"]=str(cal[ts])
    m["coverage_pct"]=round(100.0*len(tr)/nsig,1); res["full_cov_"+nm]=m
    print("  %-6s ann %+8.2f%%  mdd %7.2f%%  tot %8.2f%%  exc %+7.2fpp  bench ann %+.2f%%  n=%-5d mean %+.3f%% med %+.3f%% wr %5.1f%%  cov %.1f%%  neg_years=%d" %
          (nm, m["ann_pct"], m["mdd_pct"], m["total_pct"], m["excess_ann_pp"], m["bench_ann_pct"], m["n"], m["mean_pct"], m["med_pct"], m["wr_pct"], m["coverage_pct"], m["n_years_neg"]), flush=True)
# average holding path of the signal set
R1 = np.full((T,N), np.nan, dtype=np.float32)
R1[1:] = O[1:]/np.where(O[:-1]>0, O[:-1], np.nan) - 1.0
path = np.zeros(H+1); cnt = np.zeros(H+1); entry_intra = []
for t in range(60, T-H-2):
    if not sig[t]: continue
    for d in range(1, H+1):
        x = R1[t+1+d][sig[t]]; x = x[np.isfinite(x)]
        if x.size: path[d] += x.sum(); cnt[d] += x.size
    c1 = C[t+1][sig[t]]; o1 = O[t+1][sig[t]]
    ok = (o1>0)&(c1>0)&np.isfinite(o1)&np.isfinite(c1)
    if ok.any(): entry_intra.append(c1[ok]/o1[ok]-1.0)
ei = np.concatenate(entry_intra)
print("\n=== average path (top-%d signals, no slots) ===" % KNEW)
print("entry day open->close: mean %+.4f%%  wr %.2f%%  n=%d" % (ei.mean()*100, 100*(ei>0).mean(), ei.size))
print("  d:  mean open-to-open daily return of the signal set")
cum=ei.mean()*100
print("   entry-day intraday        %+.4f%%" % (ei.mean()*100))
lines=[]
for d in range(1, H+1):
    v=path[d]/cnt[d]; cum+=v*100
    lines.append((d, v*100, cum))
    print("   day %2d  mean %+.4f%%   cum(since entry open) %+.4f%%" % (d, v*100, cum))
res["avg_path"]=dict(entry_day_intraday_pct=round(float(ei.mean()*100),4),
    daily_mean_pct=[round(float(path[d]/cnt[d]*100),4) for d in range(1,H+1)],
    cum_from_entry_open_pct=[round(float(x[2]),4) for x in lines])
old=json.loads((OUT/"result_0925b.json").read_text(encoding="utf-8"))
old["full_coverage"]=res["full_cov_0bp"]; old["full_coverage_20bp"]=res["full_cov_20bp"]; old["full_coverage_115bp"]=res["full_cov_115bp"]
old["avg_path"]=res["avg_path"]
(OUT/"result_0925b.json").write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
print("\nmerged into result_0925b.json")
