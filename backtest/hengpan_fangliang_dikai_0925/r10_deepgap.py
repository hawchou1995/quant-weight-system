# -*- coding: utf-8 -*-
"""r10: quantify the deep-gap group (what a -1% limit order would ALSO fill) + verify user-cost numbers."""
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
O1=sh(O,1); C2=sh(C,2)
FULL=C2/O1-1.0
FULL[~(np.isfinite(C2)&(C2>0)&np.isfinite(O1)&(O1>0))]=np.nan
okb=np.zeros((T,N),bool)
for t in range(60,T-3):
    okb[t]=(VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=2e7))
POOL={}
for t in range(60,T-3):
    g=GAPO[t]
    m=okb[t]&np.isfinite(g)&(g<=-0.01)&np.isfinite(FULL[t])
    idx=np.nonzero(m)[0]
    if idx.size: POOL[t]=idx
def zs(x):
    x=np.asarray(x,float); mu=np.nanmean(x); sd=np.nanstd(x)
    return (x-mu)/sd if np.isfinite(sd) and sd>0 else np.zeros_like(x)
SIG={}
for t,idx in POOL.items():
    sc=zs(-np.log(np.where(AMT20[t][idx]>0,AMT20[t][idx],np.nan)))+zs(-np.log(np.where(VOLBR[t][idx]>0,VOLBR[t][idx],np.nan)))+zs(-RET20[t][idx])
    SIG[t]= idx if len(idx)<=10 else idx[np.argsort(-np.where(np.isfinite(sc),sc,-1e30))][:10]
print("=== 复合打分选中集: 按跳空深度拆分 (无成本, T+1开盘->T+2尾盘) ===")
band=[(-99,-8,"<=-8%"),(-8,-5,"-8~-5%"),(-5,-3,"-5~-3%"),(-3,-1,"-3~-1%")]
tot=0; wsum=0.0; res={}
for lo,hi,lab in band:
    a=[]
    for t,idx in SIG.items():
        g=GAPO[t][idx]*100
        m=(g>lo)&(g<=hi)
        v=FULL[t][idx][m]; v=v[np.isfinite(v)]
        if v.size: a.append(v)
    v=np.concatenate(a)*100 if a else np.array([np.nan])
    res[lab]=dict(n=int(v.size), mean=round(float(np.nanmean(v)),4), med=round(float(np.nanmedian(v)),4), wr=round(float(100*np.nanmean(v>0)),2))
    print("  %-9s n=%7d (%.2f%%) 毛均 %+8.4f%% 毛中 %+8.4f%% 毛胜 %6.2f%%" % (lab, v.size, 100*v.size/23534, np.nanmean(v), np.nanmedian(v), 100*np.nanmean(v>0)))
deep=[]
for t,idx in SIG.items():
    g=GAPO[t][idx]*100; m=g<=-3
    v=FULL[t][idx][m]; v=v[np.isfinite(v)]
    if v.size: deep.append(v)
d=np.concatenate(deep)*100
print("\n  深跌组(le-3pct): n=%d (%.2f%% of picks) 毛均 %+8.4f%% 毛中 %+8.4f%% 毛胜 %6.2f%%" % (d.size, 100*d.size/23534, d.mean(), np.median(d), 100*(d>0).mean()))
nd=[]; 
for t,idx in SIG.items():
    g=GAPO[t][idx]*100; m=g>-3
    v=FULL[t][idx][m]; v=v[np.isfinite(v)]
    if v.size: nd.append(v)
n2=np.concatenate(nd)*100
print("  常规组(>-3%%): n=%d 毛均 %+8.4f%% 毛中 %+8.4f%% 毛胜 %6.2f%%" % (n2.size, n2.mean(), np.median(n2), 100*(n2>0).mean()))
print("  -> 深跌组比常规组低 %.4f pp/笔; 用户费率(6.92bp)下深跌组净均 %+.4f%%" % (n2.mean()-d.mean(), d.mean()-0.0692))
res["deep_le3"]=dict(n=int(d.size), mean=round(float(d.mean()),4), med=round(float(np.median(d)),4), wr=round(float(100*(d>0).mean()),2))
res["normal_gt3"]=dict(n=int(n2.size), mean=round(float(n2.mean()),4), med=round(float(np.median(n2)),4), wr=round(float(100*(n2>0).mean()),2))
# verify user-cost headline numbers
uc=json.loads((S/"r9b_usercost.json").read_text(encoding="utf-8"))["results"]
checks=[("[-3,-1]|0 (开盘价成交)",141.04),("[-3,-1]|+0.2%",90.80),("[-3,-1]|+0.5%",34.61),
        ("<=-1 unbounded|0 (开盘价成交)",74.61),("<=-1 unbounded|+0.5%",-0.56),("<=-1 unbounded|当日均价",-13.77)]
print("\n=== 对拍 r9b 数字 ===")
bad=0
for k,v in checks:
    a=uc[k]["ann"]; ok=abs(float(a)-v)<1e-6
    if not ok: bad+=1
    print("  %s %-38s json=%s expect=%s" % ("OK " if ok else "FAIL", k, a, v))
print("%s" % ("ALL PASS" if bad==0 else "HAS FAILURES"))
json.dump(res, open(S/"r10_deepgap.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved r10_deepgap.json")

