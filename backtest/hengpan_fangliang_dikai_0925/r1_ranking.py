# -*- coding: utf-8 -*-
"""r1: does ANY ranking key make a capacity-limited portfolio work? + signal refinement."""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); T, N = len(cal), len(U["universe"])
inds = np.array([u["ind"] for u in U["universe"]], dtype=object)
ind_names = sorted(set(inds.tolist())); gcol = np.array([ind_names.index(x) for x in inds], dtype=np.int32)
O = np.asarray(np.load(S/"wl_OPEN.npy", mmap_mode="r")); C = np.asarray(np.load(S/"wl_CLOSE.npy", mmap_mode="r"))
AMT20 = np.asarray(np.load(S/"wl_AMT20.npy", mmap_mode="r")); NV = np.asarray(np.load(S/"wl_NV.npy", mmap_mode="r"))
ATR20 = np.asarray(np.load(S/"wl_ATR20.npy", mmap_mode="r")); RET20 = np.asarray(np.load(S/"wl_RET20.npy", mmap_mode="r"))
VOLBR = np.asarray(np.load(S/"wl2_VOLBR.npy", mmap_mode="r")); SHR = np.asarray(np.load(S/"wl2_SHRINK.npy", mmap_mode="r"))
GAPO = np.asarray(np.load(S/"wl2_GAPNEXT.npy", mmap_mode="r"))
VALID = np.load(S/"wl_VALID.npy").astype(bool)
IDX = pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
BC = pd.to_numeric(IDX.set_index("date").reindex(cal)["close"], errors="coerce").to_numpy(float)
def sh(a,k):
    b=np.full(a.shape,np.nan,dtype=np.float32); b[:-k]=a[k:]; return b
E1=sh(O,1); C2=sh(C,2); RT=C2/E1-1.0
RT[~(np.isfinite(C2)&(C2>0)&np.isfinite(E1)&(E1>0))]=np.nan
okb=np.zeros((T,N),bool)
for t in range(60,T-3):
    okb[t]=(VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=2e7))
POOL={}
for t in range(60,T-3):
    g=GAPO[t]
    m=okb[t]&np.isfinite(g)&(g<=-0.01)&(g>=-0.03)&np.isfinite(RT[t])
    idx=np.nonzero(m)[0]
    if idx.size: POOL[t]=idx
npool=sum(len(v) for v in POOL.values()); ndays=len(POOL)
print("R2 池: %d 日, %d 笔, 每日中位 %d" % (ndays, npool, int(np.median([len(v) for v in POOL.values()]))))
# 池基准（同日）
sdm_pool=[]; 
for t,idx in POOL.items():
    v=RT[t][idx]; v=v[np.isfinite(v)]
    if v.size: sdm_pool.append(v.mean()*100)
sdm_pool=np.array(sdm_pool)
def tstat(x): return float(x.mean()/(x.std(ddof=1)/np.sqrt(x.size))) if x.size>1 and x.std(ddof=1)>0 else 0.0
rng = np.random.default_rng(20260925)
def sc_of(key, t, idx):
    g=GAPO[t]; a=ATR20[t]; a=np.where(np.isfinite(a)&(a>0), a, np.nan)
    if key=="gap_deep":    s=-g[idx]
    elif key=="gap_shallow": s=g[idx]
    elif key=="relgap_deep":  s=-g[idx]/a[idx]
    elif key=="relgap_shallow": s=g[idx]/a[idx]
    elif key=="volbr_hi":  s=VOLBR[t][idx]
    elif key=="volbr_lo":  s=-VOLBR[t][idx]
    elif key=="amt_hi":    s=AMT20[t][idx]
    elif key=="amt_lo":    s=-AMT20[t][idx]
    elif key=="ret20_lo":  s=-RET20[t][idx]
    elif key=="ret20_hi":  s=RET20[t][idx]
    elif key=="atr_hi":    s=a[idx]
    elif key=="atr_lo":    s=-a[idx]
    elif key=="random":    s=rng.random(idx.size)
    return np.where(np.isfinite(s), s, -1e30)
KEYS=["gap_deep","gap_shallow","relgap_deep","relgap_shallow","volbr_hi","volbr_lo","amt_hi","amt_lo","ret20_lo","ret20_hi","atr_hi","atr_lo","random"]
def sel(key, K):
    out={}
    for t, idx in POOL.items():
        if len(idx)<=K: out[t]=idx
        else: out[t]=idx[np.argsort(-sc_of(key,t,idx))][:K]
    return out
def ev_stats(sig):
    ev=[]; sdm=[]
    for t,idx in sig.items():
        v=RT[t][idx]; v=v[np.isfinite(v)]
        if not v.size: continue
        ev.append(v); sdm.append(v.mean()*100)
    ev=np.concatenate(ev)*100; sdm=np.array(sdm)
    d=sdm-sdm_pool[:len(sdm)] if len(sdm)==len(sdm_pool) else sdm-np.array([np.mean([RT[t][i] for i in POOL[t] if np.isfinite(RT[t][i])])*100 for t in sig])
    return dict(n=int(ev.size), mean=round(float(ev.mean()),4), med=round(float(np.median(ev)),4),
                wr=round(float(100*(ev>0).mean()),2), t_sig=round(tstat(sdm),2), t_exc=round(tstat(d),2))
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
        for j in sig.get(t-1,[]):
            if len(pos)>=KSLOT: continue
            if j in pos: continue
            px=O[t,j]
            if not (np.isfinite(px) and px>0): continue
            navprev=nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            alloc=min(navprev/KSLOT,cash)
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
        exc=round((ann-bann)*100,2), n=int(r.size), mean=round(float(r.mean()),3),
        negY=sum(1 for y in ys if np.mean([z[1] for z in trades if z[0]==y])<0), nY=len(ys))
res={}
for K in (10,):
    print("\n=== K=%d/day 排序键扫描 (20bp, KSLOT=%d) ===" % (K, 2*K))
    print("  %-16s %8s %9s %9s %7s %7s %7s | %8s %8s %7s %7s" % ("排序键","笔数","毛均%","毛中%","毛胜%","t(信号)","t(超额)","年化","MDD","夏普","超额pp"))
    for key in KEYS:
        sig=sel(key,K); e=ev_stats(sig); m=simulate(sig,2*K)
        res["K%d_%s"%(K,key)]=dict(ev=e, port=m)
        print("  %-16s %8d %+9.4f %+9.4f %7.2f %7.2f %7.2f | %+8.2f %+8.2f %7.2f %+7.2f" %
              (key, e["n"], e["mean"], e["med"], e["wr"], e["t_sig"], e["t_exc"], m["ann"], m["mdd"], m["sharpe"] or 0, m["exc"]), flush=True)
print("\n=== 池基准(全部信号等权): 毛均 +0.4120%% / 年化 +12.44%% / MDD -49.10%% / 夏普 0.50 / 超额 +9.51pp ===")
json.dump(res, open(S/"r1_ranking.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved r1_ranking.json")
