# -*- coding: utf-8 -*-
"""q12: persist the depth-bucket tables + sample-day layer printout (evidence chain completeness)."""
import json, pathlib, numpy as np
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); uni=U["universe"]; T, N = len(cal), len(uni)
sym=[u["sym"] for u in uni]
O = np.asarray(np.load(S/"wl_OPEN.npy", mmap_mode="r")); C = np.asarray(np.load(S/"wl_CLOSE.npy", mmap_mode="r"))
AMT20 = np.asarray(np.load(S/"wl_AMT20.npy", mmap_mode="r")); NV = np.asarray(np.load(S/"wl_NV.npy", mmap_mode="r"))
VALID = np.load(S/"wl_VALID.npy").astype(bool); VOLBR = np.asarray(np.load(S/"wl2_VOLBR.npy", mmap_mode="r"))
RANGE = np.asarray(np.load(S/"wl2_RANGE20prev.npy", mmap_mode="r")); ABSRET = np.asarray(np.load(S/"wl2_ABSRET20.npy", mmap_mode="r"))
SHR = np.asarray(np.load(S/"wl2_SHRINK.npy", mmap_mode="r")); GAPO = np.asarray(np.load(S/"wl2_GAPNEXT.npy", mmap_mode="r"))
def sh(a,k):
    b=np.full(a.shape,np.nan,dtype=np.float32); b[:-k]=a[k:]; return b
E1=sh(O,1); C2=sh(C,2); RT=C2/E1-1.0
RT[~(np.isfinite(C2)&(C2>0)&np.isfinite(E1)&(E1>0))]=np.nan
def pct_rank(x):
    o=np.isfinite(x); out=np.full(x.shape,np.nan)
    if o.sum()<3: return out
    out[o]=(np.argsort(np.argsort(x[o]))+1)/o.sum(); return out
PR=np.full((T,N),np.nan,dtype=np.float32); PA=np.full((T,N),np.nan,dtype=np.float32); okb=np.zeros((T,N),bool); okday=np.zeros(T,bool)
for t in range(60,T-3):
    b=(VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=2e7)); okb[t]=b
    bb=b&np.isfinite(RANGE[t])&np.isfinite(ABSRET[t])&np.isfinite(VOLBR[t])
    if bb.sum()<10: continue
    okday[t]=True; PR[t]=pct_rank(np.where(bb,RANGE[t],np.nan)); PA[t]=pct_rank(np.where(bb,ABSRET[t],np.nan))
EDGES=[(-99,-3),(-3,-2),(-2,-1),(-1,-0.5),(-0.5,0)]
FLAT40=lambda t:(PR[t]<=0.40)&(PA[t]<=0.40)&np.isfinite(SHR[t])&(SHR[t]<=1.0)
def buckets(extra):
    out=[]
    for a,b in EDGES:
        acc=[]
        for t in range(60,T-3):
            if not okday[t]: continue
            g=GAPO[t]
            m=extra(t)&np.isfinite(g)&(g*100>a)&(g*100<=b)&okb[t]
            v=RT[t][m]; v=v[np.isfinite(v)]
            if v.size: acc.append(v)
        if not acc: out.append(dict(band=[a,b], n=0)); continue
        v=np.concatenate(acc)*100
        out.append(dict(band=[a,b], n=int(v.size), mean=round(float(v.mean()),4), med=round(float(np.median(v)),4), wr=round(float(100*(v>0).mean()),2)))
    return out
res = dict(explain="入场 T+1 开盘 -> 出场 T+2 尾盘, 无成本无槽位; band 单位 %; 左闭右开 (a, b]",
   pool_lowopen=buckets(lambda t: np.ones(N,bool)),
   configB_lowopen=buckets(lambda t: FLAT40(t)&np.isfinite(VOLBR[t])&(VOLBR[t]>=1.5)))
print("=== 全池低开 深度分桶 ===")
for r in res["pool_lowopen"]:
    print("  [%6.1f,%5.1f] n=%9d mean %+8.4f%% med %+8.4f%% wr %6.2f%%" % (r["band"][0],r["band"][1],r["n"],r.get("mean",0),r.get("med",0),r.get("wr",0)))
print("=== 配置B(横盘40+量比1.5)低开 深度分桶 ===")
for r in res["configB_lowopen"]:
    print("  [%6.1f,%5.1f] n=%9d mean %+8.4f%% med %+8.4f%% wr %6.2f%%" % (r["band"][0],r["band"][1],r["n"],r.get("mean",0),r.get("med",0),r.get("wr",0)))
# sample-day layer printout
samples=[]
for t in [1200, 1600, 2000, 2400, 2800]:
    if not okday[t]: continue
    flat=FLAT40(t); spk=flat&np.isfinite(VOLBR[t])&(VOLBR[t]>=2.0)
    g=GAPO[t]; low=spk&np.isfinite(g)&(g<0)
    row=dict(date=str(cal[t]), pool=int(okb[t].sum()), flat=int(flat.sum()), flat_spk=int(spk.sum()), spk_lowopen=int(low.sum()), names=[])
    for j in np.nonzero(low)[0][:3]:
        row["names"].append(dict(sym=sym[j], volbr=round(float(VOLBR[t][j]),2), range_prev_pct=round(float(RANGE[t][j]*100),2),
                                 absret20_pct=round(float(ABSRET[t][j]*100),2), gap_pct=round(float(g[j]*100),2),
                                 ret_t2close_pct=round(float((C2[t][j]/E1[t][j]-1)*100),2) if (E1[t][j]>0 and C2[t][j]>0) else None))
    samples.append(row)
res["sample_days"]=samples
print("\n=== 抽样逐层打印 ===")
for r in samples: print("  %s 池=%d 横盘=%d 横盘+放量=%d +低开=%d" % (r["date"],r["pool"],r["flat"],r["flat_spk"],r["spk_lowopen"]))
json.dump(res, open(S/"q12_depth_buckets.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved q12_depth_buckets.json")
