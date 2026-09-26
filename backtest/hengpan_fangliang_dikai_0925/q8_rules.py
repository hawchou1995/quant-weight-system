# -*- coding: utf-8 -*-
"""q8: stripped-down rules (drop 横盘) + break-even cost + four-gate table + cohort portfolio."""
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
def tstat(x): return float(x.mean()/(x.std(ddof=1)/np.sqrt(x.size))) if x.size>1 and x.std(ddof=1)>0 else 0.0
def build(maskf):
    sig={}
    for t in range(60,T-3):
        m=maskf(t)&okb[t]&np.isfinite(RT[t])
        idx=np.nonzero(m)[0]
        if idx.size: sig[t]=idx.tolist()
    return sig
def simulate_cohort(sig, cost_side=0.0):
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
    return dict(ann=round(ann*100,2), bann=round(bann*100,2), mdd=round(float((v/pk-1).min())*100,2),
        sharpe=round(float(dr.mean()/sd*np.sqrt(244)),2) if sd>0 else None, exc=round((ann-bann)*100,2), n=int(r.size),
        mean=round(float(r.mean()),3), med=round(float(np.median(r)),3), wr=round(100*float((r>0).mean()),1),
        negY=sum(1 for y in ys if np.mean([z[1] for z in trades if z[0]==y])<0), nY=len(ys),
        per_year={y: round(float(np.mean([z[1] for z in trades if z[0]==y])),3) for y in ys})
X = lambda t: GAPO[t]
RULES = [
 ("R1 低开[-3%,-1%]+量比>=1.5", lambda t: (X(t)<=-0.01)&(X(t)>=-0.03)&(VOLBR[t]>=1.5)),
 ("R2 低开[-3%,-1%] 仅此",      lambda t: (X(t)<=-0.01)&(X(t)>=-0.03)),
 ("R3 低开[-2%,-1%]+量比>=1.5", lambda t: (X(t)<=-0.01)&(X(t)>=-0.02)&(VOLBR[t]>=1.5)),
 ("R4 低开[-2%,-1%] 仅此",      lambda t: (X(t)<=-0.01)&(X(t)>=-0.02)),
 ("R5 任意低开+量比>=1.5",      lambda t: (X(t)<0)&np.isfinite(X(t))&(VOLBR[t]>=1.5)),
 ("R6 任意低开 仅此",           lambda t: (X(t)<0)&np.isfinite(X(t))),
]
res={}
print("=== 剥简规则: 入场 T+1 开盘 -> 出场 T+2 尾盘 ===")
print("  %-28s %8s %7s %9s %9s %7s %7s %7s %9s" % ("规则","n","/年","毛均%","毛中%","胜%","t(信号)","t(超额)","盈亏平衡成本"))
for tag, f in RULES:
    sig = build(f); ns=sum(len(v) for v in sig.values())
    ev=np.concatenate([RT[t][v] for t,v in sig.items()])*100; ev=ev[np.isfinite(ev)]
    sdm=[];cdm=[]
    for t,idx in sig.items():
        v=RT[t][idx]; v=v[np.isfinite(v)]
        if not v.size: continue
        sdm.append(v.mean()*100)
        cv=RT[t][okb[t]]; cv=cv[np.isfinite(cv)]
        if cv.size: cdm.append(cv.mean()*100)
    ts_=tstat(np.array(sdm)); te=tstat(np.array(sdm)-np.array(cdm))
    be = float(ev.mean())   # 毛均值(%)= 盈亏平衡的往返成本(%)
    scen={}
    for nm,cs in (("0bp",0.0),("10bp",0.0005),("20bp",0.0010),("30bp",0.0015),("40bp",0.0020)):
        scen[nm]=simulate_cohort(sig, cost_side=cs)
    res[tag]=dict(n=ns, per_year=round(ns/9.7), gross_mean=round(float(ev.mean()),4), gross_med=round(float(np.median(ev)),4),
                  gross_wr=round(float(100*(ev>0).mean()),2), t_sig=round(ts_,2), t_exc=round(te,2), breakeven_cost_bp=round(be,1), scen=scen)
    print("  %-28s %8d %7.0f %+9.4f %+9.4f %7.2f %7.2f %7.2f %8.1fbp" % (tag, ns, ns/9.7, ev.mean(), np.median(ev), 100*(ev>0).mean(), ts_, te, be), flush=True)
print("\n=== 组合与四闸 (队列等权, 全部信号成交) ===")
for tag in res:
    print("  %s" % tag)
    for nm, m in res[tag]["scen"].items():
        cs=float(nm.replace("bp",""))/1e4
        evn=res[tag]["gross_mean"]-cs*100
        g=[evn>0, res[tag]["gross_wr"], (res[tag]["gross_med"]-cs*100)>0, m["exc"]>0]
        npass=sum(1 for x in g if x)
        print("    %-5s 年化 %+7.2f%% MDD %7.2f%% 夏普 %5.2f 超额 %+7.2fpp 净均%+7.4f%% 净中%+7.4f%% | 四闸 %d/4 %s" %
              (nm, m["ann"], m["mdd"], m["sharpe"] or 0, m["exc"], evn, res[tag]["gross_med"]-cs*100, npass, "".join("1" if x else "0" for x in g)), flush=True)
print("\n=== 逐年净收益 (20bp) ===")
for tag in res:
    print("  %-28s " % tag + " ".join("%s%+.2f" % (y,v) for y,v in res[tag]["scen"]["20bp"]["per_year"].items()))
json.dump(res, open(S/"q8_rules.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved q8_rules.json")
