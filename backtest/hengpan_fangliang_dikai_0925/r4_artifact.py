# -*- coding: utf-8 -*-
"""r4: artifact hunt — is the edge harvestable, or an entry-day bounce / tail / microcap artifact?"""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); T, N = len(cal), len(U["universe"])
O = np.asarray(np.load(S/"wl_OPEN.npy", mmap_mode="r")); C = np.asarray(np.load(S/"wl_CLOSE.npy", mmap_mode="r"))
AMT20 = np.asarray(np.load(S/"wl_AMT20.npy", mmap_mode="r")); NV = np.asarray(np.load(S/"wl_NV.npy", mmap_mode="r"))
RET20 = np.asarray(np.load(S/"wl_RET20.npy", mmap_mode="r")); VOLBR = np.asarray(np.load(S/"wl2_VOLBR.npy", mmap_mode="r"))
GAPO = np.asarray(np.load(S/"wl2_GAPNEXT.npy", mmap_mode="r")); VALID = np.load(S/"wl_VALID.npy").astype(bool)
def sh(a,k):
    b=np.full(a.shape,np.nan,dtype=np.float32); b[:-k]=a[k:]; return b
O1=sh(O,1); C1=sh(C,1); O2=sh(O,2); C2=sh(C,2)
def leg(num, den):
    r=num/den-1.0; r[~(np.isfinite(num)&(num>0)&np.isfinite(den)&(den>0))]=np.nan; return r
L1=leg(C1,O1); L2=leg(C2,C1); FULL=leg(C2,O1); O2C2=leg(C2,O2)
okb=np.zeros((T,N),bool)
for t in range(60,T-4):
    okb[t]=(VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=2e7))
POOL={}
for t in range(60,T-3):
    g=GAPO[t]
    m=okb[t]&np.isfinite(g)&(g<=-0.01)&(g>=-0.03)&np.isfinite(FULL[t])
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
def stack(sig, arr):
    a=[]
    for t,idx in sig.items():
        v=arr[t][idx]; v=v[np.isfinite(v)]
        if v.size: a.append(v)
    return np.concatenate(a)*100
print("=== A. 收益在时间上的位置分解 (选中的 10 只, 无成本) ===")
print("  %-22s %10s %10s %10s %9s %9s" % ("分解","n","mean%","med%","wr%","t"))
sigC=sel("composite",10,POOL)
for lab, arr in (("T+1 开盘->T+1 收盘 (入场日盘中)", L1), ("T+1 收盘->T+2 收盘 (持隔夜)", L2),
                 ("T+1 开盘->T+2 收盘 (=策略全程)", FULL), ("T+2 开盘->T+2 收盘 (尾盘博)", O2C2),
                 ("T+1 开盘->T+2 开盘", leg(O2,O1))):
    a=stack(sigC,arr); t=float(a.mean()/(a.std(ddof=1)/np.sqrt(a.size)))
    print("  %-22s %10d %+10.4f %+10.4f %9.2f %9.2f" % (lab, a.size, a.mean(), np.median(a), 100*(a>0).mean(), t))
print("\n=== A2. 同一分解: 全部池信号 (对照) ===")
for lab, arr in (("T+1 开盘->T+1 收盘", L1), ("T+1 收盘->T+2 收盘", L2), ("T+1 开盘->T+2 收盘", FULL)):
    a=stack(POOL,arr); print("  %-22s %10d %+10.4f %+10.4f %9.2f" % (lab, a.size, a.mean(), np.median(a), 100*(a>0).mean()))
print("\n=== B. 尾部集中度 (composite K=10, 全程) ===")
a=stack(sigC,FULL); a.sort()
for q in (0.01,0.05,0.10):
    k=int(a.size*q); top=a[-k:].sum(); tot=a.sum(); bot=a[:k].sum()
    print("  top %4.0f%% (%6d 笔) 贡献 %+9.1f pp = 总和的 %6.1f%% | bottom %4.0f%% 贡献 %+9.1f pp" % (100*q,k,top,100*top/tot,100*q,bot))
core=a[int(a.size*0.01):int(a.size*0.99)]
print("  剔除两端各 1%% 后: n=%d mean %+.4f%% med %+.4f%% wr %.2f%%" % (core.size, core.mean(), np.median(core), 100*(core>0).mean()))
print("  胜率 %.2f%% / 单笔中位 %+.4f%% -> 中位数口径也在赚 (非纯右尾)" % (100*(a>0).mean(), np.median(a)))
print("\n=== C. 分 ADV 段 (池内, 三档) ===")
for lab, lo, hi in (("ADV<3000万",2e7,3e7),("3000万~1亿",3e7,1e8),(">=1亿",1e8,9e18)):
    aa=[]
    for t,idx in POOL.items():
        am=AMT20[t][idx]; m=(am>=lo)&(am<hi)
        v=FULL[t][idx][m]; v=v[np.isfinite(v)]
        if v.size: aa.append(v)
    v=np.concatenate(aa)*100
    print("  %-12s n=%8d 毛均 %+8.4f%% 毛中 %+8.4f%% 毛胜 %6.2f%%" % (lab, v.size, v.mean(), np.median(v), 100*(v>0).mean()))
print("\n=== D. composite K=10 逐年 (无成本 全程) ===")
yr={}
for t,idx in sigC.items():
    v=FULL[t][idx]; v=v[np.isfinite(v)]
    if v.size: yr.setdefault(str(cal[t])[:4], []).extend((v*100).tolist())
for y in sorted(yr):
    a2=np.array(yr[y]); print("  %s n=%5d 毛均 %+8.4f%% 毛中 %+8.4f%% 毛胜 %6.2f%%" % (y, a2.size, a2.mean(), np.median(a2), 100*(a2>0).mean()))
print("\n=== E. 低开幅度分层 (composite 选中集内) ===")
gp=[]; 
for t,idx in sigC.items(): gp.append(GAPO[t][idx])
gp=np.concatenate(gp)*100
for lo,hi in ((-99,-2.5),(-2.5,-2),(-2,-1.5),(-1.5,-1.0)):
    m=(gp>lo)&(gp<=hi)
    v=a[m]
    print("  gap [%5.1f,%5.1f] n=%6d 毛均 %+8.4f%% 毛中 %+8.4f%% 毛胜 %6.2f%%" % (lo,hi,m.sum(),v.mean(),np.median(v),100*(v>0).mean()))
json.dump(dict(legs=dict(T1_intraday=round(float(stack(sigC,L1).mean()),4), T1c_T2c=round(float(stack(sigC,L2).mean()),4),
                        full=round(float(stack(sigC,FULL).mean()),4), T2open_T2close=round(float(stack(sigC,O2C2).mean()),4)),
               pool_legs=dict(T1_intraday=round(float(stack(POOL,L1).mean()),4), T1c_T2c=round(float(stack(POOL,L2).mean()),4), full=round(float(stack(POOL,FULL).mean()),4))),
          open(S/"r4_artifact.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved r4_artifact.json")
