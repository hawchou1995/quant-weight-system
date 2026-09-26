# -*- coding: utf-8 -*-
"""r5: execution feasibility — how sensitive is the edge to the entry fill price?"""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); T, N = len(cal), len(U["universe"])
O = np.asarray(np.load(S/"wl_OPEN.npy", mmap_mode="r")); C = np.asarray(np.load(S/"wl_CLOSE.npy", mmap_mode="r"))
Hh = np.asarray(np.load(S/"wl_HIGH.npy", mmap_mode="r")); Ll = np.asarray(np.load(S/"wl_LOW.npy", mmap_mode="r"))
AMT20 = np.asarray(np.load(S/"wl_AMT20.npy", mmap_mode="r")); NV = np.asarray(np.load(S/"wl_NV.npy", mmap_mode="r"))
RET20 = np.asarray(np.load(S/"wl_RET20.npy", mmap_mode="r")); VOLBR = np.asarray(np.load(S/"wl2_VOLBR.npy", mmap_mode="r"))
GAPO = np.asarray(np.load(S/"wl2_GAPNEXT.npy", mmap_mode="r")); VALID = np.load(S/"wl_VALID.npy").astype(bool)
def sh(a,k):
    b=np.full(a.shape,np.nan,dtype=np.float32); b[:-k]=a[k:]; return b
O1=sh(O,1); C1=sh(C,1); H1=sh(Hh,1); L1=sh(Ll,1); C2=sh(C,2)
okb=np.zeros((T,N),bool)
for t in range(60,T-4):
    okb[t]=(VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=2e7))
POOL={}
for t in range(60,T-3):
    g=GAPO[t]
    m=okb[t]&np.isfinite(g)&(g<=-0.01)&(g>=-0.03)&np.isfinite(C2[t])&(C2[t]>0)&np.isfinite(O1[t])&(O1[t]>0)
    idx=np.nonzero(m)[0]
    if idx.size: POOL[t]=idx
def zs(x):
    x=np.asarray(x,float); mu=np.nanmean(x); sd=np.nanstd(x)
    return (x-mu)/sd if np.isfinite(sd) and sd>0 else np.zeros_like(x)
def sel(key,K,POOL):
    o={}
    for t,idx in POOL.items():
        if key=="composite":
            s=zs(-np.log(np.where(AMT20[t][idx]>0,AMT20[t][idx],np.nan)))+zs(-np.log(np.where(VOLBR[t][idx]>0,VOLBR[t][idx],np.nan)))+zs(-RET20[t][idx])
        elif key=="amt_lo": s=-AMT20[t][idx]
        o[t]= idx if len(idx)<=K else idx[np.argsort(-np.where(np.isfinite(s),s,-1e30))][:K]
    return o
sigC=sel("composite",10,POOL)
def ret_of(entry, exit_):
    r=exit_/entry-1.0
    bad=~(np.isfinite(exit_)&(exit_>0)&np.isfinite(entry)&(entry>0))
    r[bad]=np.nan; return r
def stack(sig, arr):
    a=[]
    for t,idx in sig.items():
        v=arr[t][idx]; v=v[np.isfinite(v)]
        if v.size: a.append(v)
    return np.concatenate(a)*100
print("=== A. 入场成交价情景 (出场固定 = T+2 尾盘, 无成本) ===")
print("  %-34s %9s %9s %8s" % ("入场价情景","mean%","med%","wr%"))
VWAP = (O1+H1+L1+C1)/4.0
scen = [("理想: T+1 开盘价 (基准)", O1), ("滑价 0.2% 高于开盘", O1*1.002), ("滑价 0.5% 高于开盘", O1*1.005),
        ("滑价 1.0% 高于开盘", O1*1.01), ("近似日内均价 (O+H+L+C)/4", VWAP), ("错失开盘: T+1 收盘价", C1)]
out={}
for lab, ent in scen:
    a=stack(sigC, ret_of(ent, C2)); out[lab]=dict(mean=round(float(a.mean()),4), med=round(float(np.median(a)),4), wr=round(float(100*(a>0).mean()),2))
    print("  %-34s %+9.4f %+9.4f %8.2f" % (lab, a.mean(), np.median(a), 100*(a>0).mean()))
print("\n=== B. 开盘价在当日区间中的位置 (微观结构检查) ===")
pos=[]
for t,idx in sigC.items():
    o=O1[t][idx]; h=H1[t][idx]; l=L1[t][idx]
    ok=(np.isfinite(h))&(np.isfinite(l))&(h>l)
    pos.append((o[ok]-l[ok])/(h[ok]-l[ok]))
pos=np.concatenate(pos)
print("  开盘价分位 (0=当日最低, 1=当日最高): mean %.3f med %.3f p25 %.3f p75 %.3f" % (pos.mean(), np.median(pos), np.percentile(pos,25), np.percentile(pos,75)))
print("  开盘=当日最低 的比例 %.2f%% ; 开盘<=当日25%%位 的比例 %.2f%%" % (100*(pos<=0.001).mean(), 100*(pos<=0.25).mean()))
print("\n=== C. 入场日盘中收益分布 (T+1 开盘->收盘) ===")
a=stack(sigC, ret_of(O1,C1))
for q in (1,5,10,25,50,75,90,95,99): print("    p%-2d = %+7.3f%%" % (q, np.percentile(a,q)))
print("    涨停收盘(>=9.5%%)占比 %.2f%% ; 下跌收盘占比 %.2f%%" % (100*(a>=9.5).mean(), 100*(a<0).mean()))
print("\n=== D. 组合年化: 不同入场价情景 (K=10, KSLOT=20, 20bp 成本) ===")
IDX = pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
BC = pd.to_numeric(IDX.set_index("date").reindex(cal)["close"], errors="coerce").to_numpy(float)
def sim(entry_map, cost_side=0.0010):
    ts=min(sigC); cash=1.0; pos={}; nav=np.full(T,np.nan); trades=[]; nav[ts]=1.0
    for t in range(ts+1,T):
        for _ in range(2):
            for j in [j for j,p in pos.items() if p["tgt"]<=t]:
                p=pos[j]; px=C[t,j]
                if np.isfinite(px) and px>0:
                    pos.pop(j); cash+=p["sh"]*px*(1-cost_side)
                    trades.append((str(cal[t])[:4],(px*(1-cost_side)/(p["px"]*(1+cost_side))-1)*100))
                else: p["tgt"]=t+1
        for j in sigC.get(t-1,[]):
            if len(pos)>=20: continue
            if j in pos: continue
            px=entry_map[t][j]
            if not (np.isfinite(px) and px>0): continue
            navprev=nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            alloc=min(navprev/20,cash)
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
    r=np.array([x[1] for x in trades],float)
    return dict(ann=round(ann*100,2), mdd=round(float((v/pk-1).min())*100,2), sharpe=round(float(dr.mean()/sd*np.sqrt(244)),2) if sd>0 else None,
                exc=round((ann-bann)*100,2), mean=round(float(r.mean()),3), med=round(float(np.median(r)),3), wr=round(100*float((r>0).mean()),1))
EM={ "理想 O1":O1, "O1*1.002":O1*1.002, "O1*1.005":O1*1.005, "O1*1.01":O1*1.01, "日内均价 (O+H+L+C)/4":VWAP, "T+1 收盘 (错失开盘)":C1 }
for lab, ent in EM.items():
    m=sim(ent); out[lab+" | 组合"]=m
    print("  %-24s 年化 %+8.2f%% MDD %7.2f%% 夏普 %5.2f 超额 %+7.2fpp 净均 %+7.3f%% 净中 %+7.3f%% 净胜 %5.1f%%" %
          (lab, m["ann"], m["mdd"], m["sharpe"] or 0, m["exc"], m["mean"], m["med"], m["wr"]), flush=True)
json.dump(out, open(S/"r5_execution.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved r5_execution.json")
