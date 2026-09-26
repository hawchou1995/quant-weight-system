# -*- coding: utf-8 -*-
"""q11: EXACT simulator-based net stats for configs A and B (remove the approximation used in q6)."""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); T, N = len(cal), len(U["universe"])
O = np.asarray(np.load(S/"wl_OPEN.npy", mmap_mode="r")); C = np.asarray(np.load(S/"wl_CLOSE.npy", mmap_mode="r"))
AMT20 = np.asarray(np.load(S/"wl_AMT20.npy", mmap_mode="r")); NV = np.asarray(np.load(S/"wl_NV.npy", mmap_mode="r"))
VALID = np.load(S/"wl_VALID.npy").astype(bool); VOLBR = np.asarray(np.load(S/"wl2_VOLBR.npy", mmap_mode="r"))
RANGE = np.asarray(np.load(S/"wl2_RANGE20prev.npy", mmap_mode="r")); ABSRET = np.asarray(np.load(S/"wl2_ABSRET20.npy", mmap_mode="r"))
SHR = np.asarray(np.load(S/"wl2_SHRINK.npy", mmap_mode="r")); GAPO = np.asarray(np.load(S/"wl2_GAPNEXT.npy", mmap_mode="r"))
IDX = pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
BC = pd.to_numeric(IDX.set_index("date").reindex(cal)["close"], errors="coerce").to_numpy(float)
def sh(a,k):
    b=np.full(a.shape,np.nan,dtype=np.float32); b[:-k]=a[k:]; return b
E1=sh(O,1); C2=sh(C,2); RT=C2/E1-1.0
RT[~(np.isfinite(C2)&(C2>0)&np.isfinite(E1)&(E1>0))]=np.nan
def pct_rank(x):
    o=np.isfinite(x); out=np.full(x.shape,np.nan)
    if o.sum()<3: return out
    out[o]=(np.argsort(np.argsort(x[o]))+1)/o.sum(); return out
PR=np.full((T,N),np.nan,dtype=np.float32); PA=np.full((T,N),np.nan,dtype=np.float32); okday=np.zeros(T,bool); okb=np.zeros((T,N),bool)
for t in range(60,T-3):
    b=(VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=2e7)); okb[t]=b
    bb=b&np.isfinite(RANGE[t])&np.isfinite(ABSRET[t])&np.isfinite(VOLBR[t])
    if bb.sum()<10: continue
    okday[t]=True; PR[t]=pct_rank(np.where(bb,RANGE[t],np.nan)); PA[t]=pct_rank(np.where(bb,ABSRET[t],np.nan))
def build(Pq,K):
    sig={}
    for t in range(60,T-3):
        if not okday[t]: continue
        m=(PR[t]<=Pq)&(PA[t]<=Pq)&np.isfinite(SHR[t])&(SHR[t]<=1.0)&(VOLBR[t]>=K)
        g=GAPO[t]; m=m&np.isfinite(g)&(g<0)&np.isfinite(RT[t])
        idx=np.nonzero(m)[0]
        if idx.size: sig[t]=idx.tolist()
    return sig
def simulate(sig, cost_side=0.0):
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
        if pend:
            navprev=nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            fr=[j for j in pend if j not in pos and np.isfinite(O[t,j]) and O[t,j]>0]
            if fr:
                per=min(navprev/2.0,cash)/len(fr)
                for j in fr:
                    if per<=1e-12: break
                    pos[j]=dict(en=t,tgt=t+2,sg=t-1,sh=per/(O[t,j]*(1+cost_side)),px=O[t,j]); cash-=per
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
    ann_=ann*100; bann_=bann*100
    return dict(n=int(r.size), mean=round(float(r.mean()),4), med=round(float(np.median(r)),4),
        wr=round(100*float((r>0).mean()),2), ann=round(ann_,2), mdd=round(float((v/pk-1).min())*100,2),
        sharpe=round(float(dr.mean()/sd*np.sqrt(244)),2) if sd>0 else None, exc=round(ann_-bann_,2),
        negY=sum(1 for y in ys if np.mean([z[1] for z in trades if z[0]==y])<0), nY=len(ys))
res={}
print("=== 配置 A(忠实base Pq0.30 K2.0) / B(网格 Pq0.40 K1.5) 的模拟器净口径 + 四闸 ===")
for tag, Pq, K in (("A_忠实base Pq0.30/K2.0",0.30,2.0), ("B_网格 Pq0.40/K1.5",0.40,1.5)):
    sig=build(Pq,K); print("  %s  信号 %d" % (tag, sum(len(v) for v in sig.values())))
    for nm,cs in (("0bp",0.0),("10bp",0.0005),("20bp",0.0010),("40bp",0.0020)):
        m=simulate(sig,cost_side=cs)
        g=[m["mean"]>0, m["wr"]>=46, m["med"]>0, m["exc"]>0]
        print("    %-5s n=%6d 净均 %+8.4f%% 净中 %+8.4f%% 净胜 %6.2f%% 年化 %+7.2f%% MDD %7.2f%% 夏普 %5.2f 超额 %+6.2fpp | 四闸 %d/4 %s" %
              (nm, m["n"], m["mean"], m["med"], m["wr"], m["ann"], m["mdd"], m["sharpe"] or 0, m["exc"], sum(g), "".join("1" if x else "0" for x in g)), flush=True)
        res["%s|%s" % (tag,nm)]=m
json.dump(res, open(S/"q11_exact_gates.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved q11_exact_gates.json")
