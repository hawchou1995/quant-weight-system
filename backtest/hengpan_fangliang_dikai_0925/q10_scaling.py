# -*- coding: utf-8 -*-
"""q10: does concentration or the depth-ranking destroy the edge? scaling curve K x ranking."""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); T, N = len(cal), len(U["universe"])
O = np.asarray(np.load(S/"wl_OPEN.npy", mmap_mode="r")); C = np.asarray(np.load(S/"wl_CLOSE.npy", mmap_mode="r"))
AMT20 = np.asarray(np.load(S/"wl_AMT20.npy", mmap_mode="r")); NV = np.asarray(np.load(S/"wl_NV.npy", mmap_mode="r"))
VALID = np.load(S/"wl_VALID.npy").astype(bool); VOLBR = np.asarray(np.load(S/"wl2_VOLBR.npy", mmap_mode="r"))
GAPO = np.asarray(np.load(S/"wl2_GAPNEXT.npy", mmap_mode="r"))
IDX = pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
BC = pd.to_numeric(IDX.set_index("date").reindex(cal)["close"], errors="coerce").to_numpy(float)
def sh(a,k):
    b=np.full(a.shape,np.nan,dtype=np.float32); b[:-k]=a[k:]; return b
E1=sh(O,1); C2=sh(C,2); RT=C2/E1-1.0
RT[~(np.isfinite(C2)&(C2>0)&np.isfinite(E1)&(E1>0))]=np.nan
okb=np.zeros((T,N),bool)
for t in range(60,T-3):
    okb[t]=(VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=2e7))
rng = np.random.default_rng(20260925)
POOL={}
for t in range(60,T-3):
    g=GAPO[t]
    m=okb[t]&np.isfinite(g)&(g<=-0.01)&(g>=-0.03)&np.isfinite(RT[t])
    idx=np.nonzero(m)[0]
    if idx.size: POOL[t]=idx
np.save(S/"q10_pool_size.npy", np.array([len(v) for v in POOL.values()]))
print("信号池: %d 日, 合计 %d 笔, 每日中位 %d 只, p90 %d, max %d" %
      (len(POOL), sum(len(v) for v in POOL.values()), np.median([len(v) for v in POOL.values()]),
       np.percentile([len(v) for v in POOL.values()],90), max(len(v) for v in POOL.values())))
def sig_of(K, rank):
    sig={}
    for t, idx in POOL.items():
        if K is None or len(idx)<=K:
            sig[t]=idx.tolist(); continue
        if rank=="depth": sc = -GAPO[t][idx]
        elif rank=="vol": sc = VOLBR[t][idx]
        elif rank=="amt": sc = AMT20[t][idx]
        else: sc = rng.random(idx.size)
        sig[t]=idx[np.argsort(-sc)][:K].tolist()
    return sig
def simulate(sig, KSLOT, cost_side=0.0010):
    ts=min(sig); cash=1.0; pos={}; nav=np.full(T,np.nan); trades=[]; nav[ts]=1.0
    for t in range(ts+1,T):
        for _ in range(2):
            for j in [j for j,p in pos.items() if p["tgt"]<=t]:
                p=pos[j]; px=C[t,j]
                if np.isfinite(px) and px>0:
                    pos.pop(j); cash+=p["sh"]*px*(1-cost_side)
                    trades.append((str(cal[t])[:4],(px*(1-cost_side)/(p["px"]*(1+cost_side))-1)*100))
                else: p["tgt"]=t+1
        pend=sig.get(t-1,[])
        for j in pend:
            if len(pos)>=KSLOT: continue
            if j in pos: continue
            px=O[t,j]
            if not (np.isfinite(px) and px>0): continue
            navprev=nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            alloc=min(navprev/KSLOT, cash)
            if alloc<=1e-12: break
            pos[j]=dict(en=t,tgt=t+2,sg=t-1,sh=alloc/(px*(1+cost_side)),px=px); cash-=alloc
        mv=0.0
        for j,p in pos.items():
            c=C[t,j]; mv+=p["sh"]*(c if np.isfinite(c) and c>0 else p["px"])
        nav[t]=cash+mv
    bnav=np.full(T,np.nan); bnav[ts]=1.0
    for t in range(ts+1,T): bnav[t]=BC[t]/BC[ts]
    ok=np.isfinite(nav); v=nav[ok]; b=bnav[ok]; nd=len(v)-1
    ann=(v[-1]/v[0])**(244/nd)-1; pk=np.maximum.accumulate(v); dr=v[1:]/v[:-1]-1; sd=dr.std(ddof=1)
    bann=(b[-1]/b[0])**(244/nd)-1
    r=np.array([x[1] for x in trades],float); ys=sorted(set(x[0] for x in trades))
    return dict(ann=round(ann*100,2), mdd=round(float((v/pk-1).min())*100,2), sharpe=round(float(dr.mean()/sd*np.sqrt(244)),2) if sd>0 else None,
        exc=round((ann-bann)*100,2), n=int(r.size), mean=round(float(r.mean()),3), med=round(float(np.median(r)),3),
        wr=round(100*float((r>0).mean()),1), negY=sum(1 for y in ys if np.mean([z[1] for z in trades if z[0]==y])<0), nY=len(ys))
res={}
print("\n=== 规模-排序扫描: 低开[-3%,-1%], 20bp, KSLOT=2K (每天买 K 只) ===")
print("  %-24s %6s %8s %7s %7s %7s %8s %7s %5s" % ("配置","笔数","年化","MDD","夏普","超额pp","净均%","胜率","负年"))
for K in (3, 5, 10, 20, 50, 100, None):
    for rank in (("depth","random") if K else ("all",)):
        if K is None: rank="all"
        sig = sig_of(K, rank); m = simulate(sig, 2*(K if K else 400))
        tag = ("全池(%d只/日)" % int(np.median([len(v) for v in POOL.values()]))) if K is None else ("K=%d %s" % (K, rank))
        res[tag]=m
        print("  %-24s %6d %+8.2f%% %7.2f%% %7.2f %+8.2f %+7.3f %7.2f %5d/%d" %
              (tag, m["n"], m["ann"], m["mdd"], m["sharpe"] or 0, m["exc"], m["mean"], m["wr"], m["negY"], m["nY"]), flush=True)
json.dump(res, open(S/"q10_scaling.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved q10_scaling.json")
