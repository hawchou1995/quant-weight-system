# -*- coding: utf-8 -*-
"""tp_grid.py — 细网格: 止盈档位(不止损, 未达标 T+2 尾盘离场) + 灾难止损叠加"""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
exec(open(S/"real_filters.py", encoding="utf-8").read().split("def sim(")[0])
MH = np.asarray(np.load(S/"wl_HIGH.npy", mmap_mode="r")); ML = np.asarray(np.load(S/"wl_LOW.npy", mmap_mode="r"))
def H_(fr,t,j): return float(MH[t,j]) if fr=="M" else float(DH[t,j])
def L_(fr,t,j): return float(ML[t,j]) if fr=="M" else float(DL[t,j])
def O_(fr,t,j): return float(MO[t,j]) if fr=="M" else float(DO[t,j])
def C_(fr,t,j): return float(MC[t,j]) if fr=="M" else float(DC[t,j])
def sim_cfg(K,KSLOT,FILL,tp=None,stop=None,max_hold=1,cost=0.000346):
    PICKS={}
    for t in range(1,T):
        if (t-1) in POOL: PICKS[t]=[p for p in pick(t-1,POOL[t-1],K) if (p[2]<=FILL if FILL is not None else True)]
    ts=min(POOL); cash=1.0; pos={}; nav=np.full(T,np.nan); nav[ts-1]=1.0; rets=[]; hold=[]; nb={"tp":0,"stop":0}
    for t in range(ts,T):
        for key in [k for k,p in pos.items() if p["last"]<=t]:
            p=pos[key]; fr,j=p["fr"],p["j"]; ex=None
            for d in range(max(t,p["en"]+1), min(p["en"]+max_hold,T-1)+1):
                o,h,l=O_(fr,d,j),H_(fr,d,j),L_(fr,d,j)
                if not (np.isfinite(o) and np.isfinite(h) and np.isfinite(l) and o>0): continue
                if stop is not None:
                    lv=p["px"]*(1-stop)
                    if o<=lv: ex=o; nb["stop"]+=1; break
                    if l<=lv: ex=lv; nb["stop"]+=1; break
                if tp is not None:
                    lv=p["px"]*(1+tp)
                    if o>=lv: ex=o; nb["tp"]+=1; break
                    if h>=lv: ex=lv; nb["tp"]+=1; break
            cd=min(p["en"]+max_hold,T-1)
            if ex is None:
                ex=C_(fr,cd,j)
                if not (np.isfinite(ex) and ex>0):
                    for k2 in range(cd+1,min(cd+6,T)):
                        if np.isfinite(C_(fr,k2,j)) and C_(fr,k2,j)>0: ex=C_(fr,k2,j); break
                    else: ex=0.0
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
        wr=round(float(100*(r>0).mean()),2), negY=int(sum(1 for y,vv in ys.items() if np.mean(vv)<0)), nY=int(len(ys)),
        tp_rate=round(100*nb["tp"]/max(1,len(rets)),1), stop_rate=round(100*nb["stop"]/max(1,len(rets)),1))
res={}
print("="*118)
print("您的方案 = 止盈 +X%, 不止损, 未达标则 T+2 尾盘离场  (基线: K=10挂单/只成交低开>=1.5%/KSLOT=4/成本6.92bp)")
print("="*118)
print("  %-22s %9s %8s %7s %8s %8s %7s %6s %6s %5s" % ("出场规则","年化","MDD","夏普","单笔净均","净中位","净胜率","笔数","止盈率","负年"))
for lab,tp in (("不止盈(纯尾盘)",None),("止盈 +1.0%",0.010),("止盈 +1.5%",0.015),("止盈 +2.0%",0.020),
               ("止盈 +2.5%",0.025),("止盈 +3.0%",0.030),("止盈 +3.5%",0.035),("止盈 +4.0%",0.040),
               ("止盈 +5.0%",0.050),("止盈 +6.0%",0.060)):
    r=sim_cfg(10,4,-0.015,tp=tp); res[lab]=r
    print("  %-22s %+9.2f%% %+8.2f%% %7.2f %+8.4f %+8.4f %7.2f %6d %5.1f%% %2d/%d" %
          (lab, r["ann"], r["mdd"], r["sharpe"] or 0, r["mean"], r["med"], r["wr"], r["n"], r["tp_rate"], r["negY"], r["nY"]), flush=True)
print("\n  叠加「灾难止损」(很少触发, 只防极端):")
for lab,tp,st in (("止盈+2% + 灾难止损-8%",0.020,0.08),("止盈+2% + 灾难止损-10%",0.020,0.10),("止盈+3% + 灾难止损-8%",0.030,0.08)):
    r=sim_cfg(10,4,-0.015,tp=tp,stop=st); res[lab]=r
    print("  %-22s %+9.2f%% %+8.2f%% %7.2f %+8.4f %+8.4f %7.2f %6d %5.1f%% %2d/%d  (止损触发 %.1f%%)" %
          (lab, r["ann"], r["mdd"], r["sharpe"] or 0, r["mean"], r["med"], r["wr"], r["n"], r["tp_rate"], r["negY"], r["nY"], r["stop_rate"]), flush=True)
print("\n  另一基准口径 (K=3 全成交 KSLOT=6) 下的止盈档位:")
for lab,tp in (("不止盈",None),("止盈 +2.0%",0.020),("止盈 +3.0%",0.030)):
    r=sim_cfg(3,6,None,tp=tp); res["K3_"+lab]=r
    print("  %-22s %+9.2f%% %+8.2f%% %7.2f %+8.4f %+8.4f %7.2f %6d %5.1f%% %2d/%d" %
          (lab, r["ann"], r["mdd"], r["sharpe"] or 0, r["mean"], r["med"], r["wr"], r["n"], r["tp_rate"], r["negY"], r["nY"]), flush=True)
json.dump(res, open(S/"tp_grid.json","w",encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("\nsaved tp_grid.json")
