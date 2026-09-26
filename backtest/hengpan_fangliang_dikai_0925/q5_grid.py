# -*- coding: utf-8 -*-
"""q5: parameter grid (横盘紧度 Pq x 放量倍数 K) - event study + cohort portfolio at 0/10/20bp."""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); uni = U["universe"]
T, N = len(cal), len(uni)
O = np.asarray(np.load(S/"wl_OPEN.npy", mmap_mode="r")); C = np.asarray(np.load(S/"wl_CLOSE.npy", mmap_mode="r"))
AMT20 = np.asarray(np.load(S/"wl_AMT20.npy", mmap_mode="r")); NV = np.asarray(np.load(S/"wl_NV.npy", mmap_mode="r"))
VALID = np.load(S/"wl_VALID.npy").astype(bool); VOLBR = np.asarray(np.load(S/"wl2_VOLBR.npy", mmap_mode="r"))
RANGE = np.asarray(np.load(S/"wl2_RANGE20prev.npy", mmap_mode="r")); ABSRET = np.asarray(np.load(S/"wl2_ABSRET20.npy", mmap_mode="r"))
SHR = np.asarray(np.load(S/"wl2_SHRINK.npy", mmap_mode="r")); GAPO = np.asarray(np.load(S/"wl2_GAPNEXT.npy", mmap_mode="r"))
IDX = pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
BC = pd.to_numeric(IDX.set_index("date").reindex(cal)["close"], errors="coerce").to_numpy(float)
def sh(a,k):
    b=np.full(a.shape,np.nan,dtype=np.float32); b[:-k]=a[k:]; return b
E1 = sh(O,1); C2 = sh(C,2)
RT = C2/E1 - 1.0; RT[~(np.isfinite(C2)&(C2>0)&np.isfinite(E1)&(E1>0))] = np.nan
def pct_rank(x):
    o=np.isfinite(x); out=np.full(x.shape,np.nan)
    if o.sum()<3: return out
    out[o]=(np.argsort(np.argsort(x[o]))+1)/o.sum(); return out
print("precomputing daily percentile ranks ...", flush=True)
PR = np.full((T,N), np.nan, dtype=np.float32); PA = np.full((T,N), np.nan, dtype=np.float32)
okday = np.zeros(T, dtype=bool)
for t in range(60, T-3):
    b = (VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=2e7)&np.isfinite(RANGE[t])&np.isfinite(ABSRET[t])&np.isfinite(VOLBR[t]))
    if b.sum() < 10: continue
    okday[t] = True; PR[t] = pct_rank(np.where(b, RANGE[t], np.nan)); PA[t] = pct_rank(np.where(b, ABSRET[t], np.nan))
print("done", flush=True)
CTRL = []
for t in range(60, T-3):
    if not okday[t]: continue
    b = (VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=2e7))
    v = RT[t][b]; v = v[np.isfinite(v)]
    if v.size: CTRL.append(v)
ctrl = np.concatenate(CTRL)*100
print("control (全池合格, T+1开盘->T+2尾盘): n=%d mean %+.4f%% wr %.2f%%" % (ctrl.size, ctrl.mean(), 100*(ctrl>0).mean()))
def build(Pq, K, SHRV=1.0, G0=0.0):
    sig = {}
    for t in range(60, T-3):
        if not okday[t]: continue
        flat = (PR[t] <= Pq) & (PA[t] <= Pq) & np.isfinite(SHR[t]) & (SHR[t] <= SHRV)
        spk = flat & (VOLBR[t] >= K)
        gp = GAPO[t]
        low = spk & np.isfinite(gp) & (gp <= -G0) & (gp < 0 if G0 == 0 else True)
        m = low & np.isfinite(RT[t])
        idx = np.nonzero(m)[0]
        if idx.size: sig[t] = idx.tolist()
    return sig
def simulate_cohort(sig, cost_side=0.0, H=2, ex_off=2):
    ts=min(sig); cash=1.0; pos={}; nav=np.full(T,np.nan); trades=[]; nav[ts]=1.0
    for t in range(ts+1,T):
        for _ in range(2):
            for j in [j for j,p in pos.items() if p["tgt"]<=t]:
                p=pos[j]; px=C[t,j]
                if np.isfinite(px) and px>0:
                    pos.pop(j); cash+=p["sh"]*px*(1-cost_side)
                    trades.append((str(cal[t])[:4], (px*(1-cost_side)/(p["px"]*(1+cost_side))-1)*100))
                else: p["tgt"]=t+1
        pend=sig.get(t-1,[])
        if pend:
            navprev = nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            fr=[j for j in pend if j not in pos and np.isfinite(O[t,j]) and O[t,j]>0]
            if fr:
                per=min(navprev/H, cash)/len(fr)
                for j in fr:
                    if per<=1e-12: break
                    pos[j]=dict(en=t,tgt=t+ex_off,sg=t-1,sh=per/(O[t,j]*(1+cost_side)),px=O[t,j]); cash-=per
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
                exc=round((ann-bann)*100,2), n=int(r.size), mean=round(float(r.mean()),3), med=round(float(np.median(r)),3),
                wr=round(100*float((r>0).mean()),1), negY=sum(1 for y in set(x[0] for x in trades) if np.mean([z[1] for z in trades if z[0]==y])<0),
                nY=len(set(x[0] for x in trades)))
res={}
print("\n=== 参数网格: 横盘紧度 Pq x 放量倍数 K (SHR<=1.0, 任意低开, 出场 T+2 尾盘) ===")
print("  Pq    K   n信号   /年   EV均%   EV中%  EV胜%   |  0bp年化  10bp  20bp  |  20bp回撤 20bp夏普 20bp超额 负年")
for Pq in (0.20, 0.30, 0.40):
    for K in (1.5, 2.0, 3.0, 5.0):
        sig = build(Pq, K)
        ns = sum(len(v) for v in sig.values())
        if ns < 200:
            print("  %.2f  %.1f  %6d  (样本不足)" % (Pq,K,ns)); continue
        ev = np.concatenate([RT[t][v] for t,v in sig.items()])*100; ev=ev[np.isfinite(ev)]
        m0=simulate_cohort(sig,0.0); m10=simulate_cohort(sig,0.0005); m20=simulate_cohort(sig,0.0010)
        key="Pq%.2f_K%.1f"%(Pq,K)
        res[key]=dict(n=ns, per_year=round(ns/9.7), ev_mean=round(float(ev.mean()),4), ev_med=round(float(np.median(ev)),4),
                      ev_wr=round(float(100*(ev>0).mean()),2), coh0=m0["ann"], coh10=m10["ann"], coh20=m20["ann"],
                      mdd20=m20["mdd"], sharpe20=m20["sharpe"], exc20=m20["exc"], wr20=m20["wr"], negY20=m20["negY"], nY20=m20["nY"])
        print("  %.2f  %.1f  %6d  %5.0f  %+7.4f  %+7.4f  %5.2f  |  %+7.2f  %+7.2f  %+7.2f  |  %7.2f  %7.2f  %+7.2f  %d/%d" %
              (Pq,K,ns,ns/9.7,ev.mean(),np.median(ev),100*(ev>0).mean(),m0["ann"],m10["ann"],m20["ann"],m20["mdd"],m20["sharpe"] or 0,m20["exc"],m20["negY"],m20["nY"]), flush=True)
json.dump(dict(control=dict(n=int(ctrl.size), mean=round(float(ctrl.mean()),4), wr=round(float(100*(ctrl>0).mean()),2)), grid=res),
          open(S/"q5_grid.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved q5_grid.json")

