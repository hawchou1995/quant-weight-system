# -*- coding: utf-8 -*-
"""q7: marginal contribution of each condition — is 横盘+放量 adding anything over plain 低开?"""
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
    b=(VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=2e7))
    okb[t]=b
    bb=b&np.isfinite(RANGE[t])&np.isfinite(ABSRET[t])&np.isfinite(VOLBR[t])
    if bb.sum()<10: continue
    okday[t]=True; PR[t]=pct_rank(np.where(bb,RANGE[t],np.nan)); PA[t]=pct_rank(np.where(bb,ABSRET[t],np.nan))
def tstat(x): return float(x.mean()/(x.std(ddof=1)/np.sqrt(x.size))) if x.size>1 and x.std(ddof=1)>0 else 0.0
def eval_mask(fn, tag):
    ev=[]; sdm=[]; cdm=[]
    for t in range(60,T-3):
        if not okday[t]: continue
        m = fn(t) & okb[t]
        v = RT[t][m]; v = v[np.isfinite(v)]
        if not v.size: continue
        ev.append(v); sdm.append(v.mean()*100)
        cv = RT[t][okb[t]]; cv = cv[np.isfinite(cv)]
        if cv.size: cdm.append(cv.mean()*100)
    ev=np.concatenate(ev)*100
    sdm=np.array(sdm); d=sdm-np.array(cdm)
    return dict(tag=tag, n=int(ev.size), per_year=int(ev.size/9.7), mean=round(float(ev.mean()),4), med=round(float(np.median(ev)),4),
                wr=round(float(100*(ev>0).mean()),2), t_sig=round(tstat(sdm),2), t_exc=round(tstat(d),2))
FLAT40 = lambda t: (PR[t]<=0.40)&(PA[t]<=0.40)&np.isfinite(SHR[t])&(SHR[t]<=1.0)
def g(t): return GAPO[t]
def lo(t, k=0.0): return np.isfinite(g(t))&(g(t)<=-k)&(g(t)<0 if k==0 else True)
def hi(t): return np.isfinite(g(t))&(g(t)>0)
def spk(t,K): return np.isfinite(VOLBR[t])&(VOLBR[t]>=K)
CASES = [
 ("0 全池对照(不限跳空)",            lambda t: np.ones(N,bool)),
 ("1 全部低开 (仅低开)",             lambda t: lo(t)),
 ("2 全部高开 (对照)",               lambda t: hi(t)),
 ("3 低开+横盘Pq40",                 lambda t: lo(t)&FLAT40(t)),
 ("4 低开+量比>=1.5 (无横盘)",        lambda t: lo(t)&spk(t,1.5)),
 ("5 低开+横盘+量比>=1.5 (=配置B)",   lambda t: lo(t)&FLAT40(t)&spk(t,1.5)),
 ("6 低开+横盘+量比>=2.0",           lambda t: lo(t)&FLAT40(t)&spk(t,2.0)),
 ("7 高开+横盘+量比>=1.5 (对照)",     lambda t: hi(t)&FLAT40(t)&spk(t,1.5)),
 ("8 横盘+量比>=1.5 (不限跳空)",      lambda t: FLAT40(t)&spk(t,1.5)),
 ("9 低开+横盘Pq30+量比>=2.0 (旧base)", lambda t: lo(t)&(PR[t]<=0.30)&(PA[t]<=0.30)&np.isfinite(SHR[t])&(SHR[t]<=1.0)&spk(t,2.0)),
]
print("=== 条件剥层: 入场 T+1 开盘 -> 出场 T+2 尾盘 (无成本, 无槽位) ===")
print("  %-34s %8s %7s %9s %9s %8s %7s %7s" % ("条件","n","/年","mean%","med%","wr%","t(信号)","t(超额)"))
out=[]
for tag, fn in CASES:
    r = eval_mask(fn, tag); out.append(r)
    print("  %-34s %8d %7d %+9.4f %+9.4f %8.2f %7.2f %7.2f" % (r["tag"], r["n"], r["per_year"], r["mean"], r["med"], r["wr"], r["t_sig"], r["t_exc"]), flush=True)
print("\n=== 低开深度分桶 (全池低开, T+2 尾盘) ===")
EDGES = [(-99,-3),(-3,-2),(-2,-1),(-1,-0.5),(-0.5,0)]
print("  %-16s %9s %10s %9s %7s" % ("跳空区间%","n","mean%","med%","wr%"))
for a,b in EDGES:
    acc=[]
    for t in range(60,T-3):
        if not okday[t]: continue
        m = np.isfinite(g(t))&(g(t)*100>a)&(g(t)*100<=b)&okb[t]
        v=RT[t][m]; v=v[np.isfinite(v)]
        if v.size: acc.append(v)
    if not acc: continue
    v=np.concatenate(acc)*100
    print("  [%6.1f,%5.1f] %9d %+10.4f %+9.4f %7.2f" % (a,b,v.size,v.mean(),np.median(v),100*(v>0).mean()))
print("\n=== 配置B 的低开深度分桶 ===")
for a,b in EDGES:
    acc=[]
    for t in range(60,T-3):
        if not okday[t]: continue
        m = FLAT40(t)&spk(t,1.5)&np.isfinite(g(t))&(g(t)*100>a)&(g(t)*100<=b)&okb[t]
        v=RT[t][m]; v=v[np.isfinite(v)]
        if v.size: acc.append(v)
    if not acc: continue
    v=np.concatenate(acc)*100
    print("  [%6.1f,%5.1f] %9d %+10.4f %+9.4f %7.2f" % (a,b,v.size,v.mean(),np.median(v),100*(v>0).mean()))
json.dump(dict(layers=out), open(S/"q7_marginal.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved q7_marginal.json")
