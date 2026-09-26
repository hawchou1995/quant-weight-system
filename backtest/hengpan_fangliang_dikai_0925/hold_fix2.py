# -*- coding: utf-8 -*-
"""hold_fix2.py — 关键配置的 2日(修正后) vs 3日(旧bug) 对照"""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
exec(open(S/"real_filters.py", encoding="utf-8").read().split("def sim(")[0])
MH = np.asarray(np.load(S/"wl_HIGH.npy", mmap_mode="r")); ML = np.asarray(np.load(S/"wl_LOW.npy", mmap_mode="r"))
def C_(fr,t,j): return float(MC[t,j]) if fr=="M" else float(DC[t,j])
def run(K, KSLOT, FILL, max_hold, stop=None, cost=0.000346):
    PICKS={}
    for t in range(1,T):
        if (t-1) in POOL:
            PICKS[t]=[p for p in pick(t-1, POOL[t-1], K) if (p[2]<=FILL if FILL is not None else True)]
    ts=min(POOL); cash=1.0; pos={}; nav=np.full(T,np.nan); nav[ts-1]=1.0; rets=[]; hold=[]
    for t in range(ts,T):
        for key in [k for k,p in pos.items() if p["last"]<=t]:
            p=pos[key]; fr,j=p["fr"],p["j"]; ex=None
            if stop is not None:
                for d in range(max(t,p["en"]+1), min(p["en"]+max_hold,T-1)+1):
                    o,h,l=float((MO if fr=="M" else DO)[d,j]),float((MH if fr=="M" else DH)[d,j]),float((ML if fr=="M" else DL)[d,j])
                    if not (np.isfinite(o) and np.isfinite(l) and o>0 and l>0): continue
                    lv=p["px"]*(1-stop)
                    if o<=lv: ex=o; break
                    if l<=lv: ex=lv; break
            cd=min(p["en"]+max_hold,T-1)
            if ex is None: ex=C_(fr,cd,j)
            if not (np.isfinite(ex) and ex>0): ex=0.0
            pos.pop(key); cash+=p["sh"]*ex*(1-cost)
            rets.append((str(cal[cd])[:4], (ex*(1-cost)/(p["px"]*(1+cost))-1)*100)); hold.append(cd-p["en"])
        for fr,j,gapv,o1v,c2v in PICKS.get(t,[]):
            if len(pos)>=KSLOT: continue
            key=(fr,j)
            if key in pos: continue
            px=o1v
            if not (np.isfinite(px) and px>0): continue
            navprev=nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            alloc=min(navprev/KSLOT,cash)
            if alloc<=1e-12: break
            pos[key]=dict(en=t,last=t+max_hold,sh=alloc/(px*(1+cost)),px=px,fr=fr,j=j); cash-=alloc
        mv=0.0
        for key,p in pos.items():
            c=C_(p["fr"],t,p["j"]); mv+=p["sh"]*(c if np.isfinite(c) and c>0 else p["px"])
        nav[t]=cash+mv
    IDX=pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
    BC=pd.to_numeric(IDX.set_index("date").reindex(cal)["close"],errors="coerce").to_numpy(float)
    bnav=np.full(T,np.nan); bnav[ts-1]=1.0
    for t in range(ts,T): bnav[t]=BC[t]/BC[ts-1]
    ok=np.isfinite(nav); v=nav[ok]; b=bnav[ok]; nd=len(v)-1
    ann=(v[-1]/v[0])**(244/nd)-1; pk=np.maximum.accumulate(v); mdd=float((v/pk-1).min())
    dr=v[1:]/v[:-1]-1; sd=dr.std(ddof=1); bann=(b[-1]/b[0])**(244/nd)-1
    r=np.array([x[1] for x in rets],float); ys={}
    for y,rr in rets: ys.setdefault(y,[]).append(rr)
    return dict(ann=round(ann*100,2), mdd=round(mdd*100,2), sharpe=round(float(dr.mean()/sd*np.sqrt(244)),2) if sd>0 else None,
        exc=round((ann-bann)*100,2), n=int(r.size), mean=round(float(r.mean()),4), med=round(float(np.median(r)),4),
        wr=round(float(100*(r>0).mean()),2), avg_hold=round(float(np.mean(hold)),2),
        negY=int(sum(1 for y,vv in ys.items() if np.mean(vv)<0)), nY=int(len(ys)))
print("="*112)
print("持有期修正影响: T+1开盘->T+2收盘 (正确, max_hold=1) vs T+3收盘 (旧bug, max_hold=2)")
print("="*112)
print("  %-30s %9s %8s %7s %8s %8s %7s %6s %5s %4s" % ("配置","年化","MDD","夏普","单笔净均","净中位","净胜率","笔数","持有","负年"))
res={}
for lab,K,KS,FL in (("K=10 仅>=1.5% KSLOT=4",10,4,-0.015),("K=10 仅>=1.5% KSLOT=6",10,6,-0.015),
                    ("K=10 仅>=2.0% KSLOT=6",10,6,-0.020),("K=3  全成交     KSLOT=6",3,6,None),
                    ("K=10 全成交     KSLOT=20",10,20,None)):
    for mh,tag in ((1,"2日 ✔正确"),(2,"3日 旧bug")):
        r=run(K,KS,FL,mh); res["%s|hold%d"%(lab,mh)]=r
        print("  %-30s %+9.2f%% %+8.2f%% %7.2f %+8.4f %+8.4f %7.2f %6d %5.1f %2d/%d   %s" %
              (lab, r["ann"], r["mdd"], r["sharpe"] or 0, r["mean"], r["med"], r["wr"], r["n"], r["avg_hold"], r["negY"], r["nY"], tag), flush=True)
print("\n【止损 −5% 在各配置下的效果 (正确持有期)】")
for lab,K,KS,FL in (("K=10 仅>=1.5% KSLOT=4",10,4,-0.015),("K=10 仅>=2.0% KSLOT=6",10,6,-0.020),("K=3  全成交     KSLOT=6",3,6,None)):
    r=run(K,KS,FL,1,stop=0.05); res[lab+"|stop5"]=r
    print("  %-30s %+9.2f%% %+8.2f%% %7.2f %+8.4f %+8.4f %7.2f %6d %5.1f %2d/%d" %
          (lab, r["ann"], r["mdd"], r["sharpe"] or 0, r["mean"], r["med"], r["wr"], r["n"], r["avg_hold"], r["negY"], r["nY"]), flush=True)
json.dump(res, open(S/"hold_fix2.json","w",encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("\nsaved hold_fix2.json")
