# -*- coding: utf-8 -*-
"""r6 (FIXED): execution-price portfolio ladder. Entry arrays are day-t indexed (no shift)."""
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
O1=sh(O,1); C2=sh(C,2)
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
def sel(key,K,KSLOT_FLAG=True):
    o={}
    for t,idx in POOL.items():
        s=zs(-np.log(np.where(AMT20[t][idx]>0,AMT20[t][idx],np.nan)))+zs(-np.log(np.where(VOLBR[t][idx]>0,VOLBR[t][idx],np.nan)))+zs(-RET20[t][idx])
        o[t]= idx if len(idx)<=K else idx[np.argsort(-np.where(np.isfinite(s),s,-1e30))][:K]
    return o
sigC=sel("composite",10)
IDX = pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
BC = pd.to_numeric(IDX.set_index("date").reindex(cal)["close"], errors="coerce").to_numpy(float)
def sim(entry_arr, cost_side=0.0010, K=10):
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
            if len(pos)>=2*K: continue
            if j in pos: continue
            px=entry_arr[t,j]
            if not (np.isfinite(px) and px>0): continue
            navprev=nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            alloc=min(navprev/(2*K),cash)
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
                exc=round((ann-bann)*100,2), mean=round(float(r.mean()),3), med=round(float(np.median(r)),3),
                wr=round(100*float((r>0).mean()),1), negY=sum(1 for y in ys if np.mean([z[1] for z in trades if z[0]==y])<0), nY=len(ys), per_year={y: round(float(np.mean([z[1] for z in trades if z[0]==y])),3) for y in ys})
VWAP = (O+Hh+Ll+C)/4.0
ENT = [("① 理想: T+1 开盘价", O), ("② 开盘+0.2% 滑价", O*1.002), ("③ 开盘+0.5% 滑价", O*1.005),
       ("④ 开盘+1.0% 滑价", O*1.01), ("⑤ 当日均价 (O+H+L+C)/4", VWAP), ("⑥ 错失开盘: T+1 收盘", C)]
res={}
print("=== 修正后: 成交流动性阶梯 (composite K=10, KSLOT=20, 成本 20bp) ===")
print("  %-26s %9s %8s %7s %7s %8s %8s %7s %6s" % ("入场价情景","年化","MDD","夏普","超额pp","净均%","净中%","净胜%","负年"))
for lab, arr in ENT:
    m=sim(arr, cost_side=0.0010); res[lab]=m
    print("  %-26s %+9.2f%% %+8.2f%% %7.2f %+7.2f %+8.3f %+8.3f %7.1f %4d/%d" %
          (lab, m["ann"], m["mdd"], m["sharpe"] or 0, m["exc"], m["mean"], m["med"], m["wr"], m["negY"], m["nY"]), flush=True)
print("\n=== 成本 x 滑价 二维 (年化%) ===")
print("  %-14s %10s %10s %10s" % ("滑价\\成本","20bp","30bp","40bp"))
res2={}
for slab, arr in (("0", O), ("+0.2%", O*1.002), ("+0.5%", O*1.005), ("均价", VWAP)):
    row=[]
    for cs in (0.0010, 0.0015, 0.0020):
        m=sim(arr, cost_side=cs); row.append(m["ann"]); res2["%s|%dbp"%(slab,int(cs*1e4))]=m
    print("  %-14s %+9.2f%% %+9.2f%% %+9.2f%%" % (slab, row[0], row[1], row[2]), flush=True)
print("\n=== 基准参数下组合逐年 (理想开盘价, 20bp) ===")
m=sim(O, cost_side=0.0010)
print("  " + " ".join("%s%+.2f" % (y,v) for y,v in m["per_year"].items()))
json.dump(dict(scenarios=res, grid=res2), open(S/"r6_exec_fixed.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved r6_exec_fixed.json")

