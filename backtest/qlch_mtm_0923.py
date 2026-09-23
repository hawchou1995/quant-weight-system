# -*- coding: utf-8 -*-
"""R-qlch-mtm-0923 · MTM（真实盯市）口径下的组合级夏普比较：X0 / X4 / E2
沿用 qlch_amort_0923 的三种计价框架，仅取 mtm；K=3 · 5 种子平均净值 · 全池。
输出：各臂夏普/年化/回撤/换手/占用 + 配对逐日差（块 bootstrap CI）
"""
import importlib.util, json, os, sys, time, io
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
T0=time.time(); BK="backtest"
os.environ["QLCH_VARIANT"]="B4"; os.environ["QLCH_MAXPOS"]="3"; os.environ["QLCH_GATE"]="20"; os.environ["QLCH_MAINBOARD"]="0"
sp=importlib.util.spec_from_file_location("g", BK+"/qlch_grid_bt_0923.py"); g=importlib.util.module_from_spec(sp); sp.loader.exec_module(g)
sp2=importlib.util.spec_from_file_location("eng", BK+"/qlch_paper_20260921.py"); eng=importlib.util.module_from_spec(sp2); sp2.loader.exec_module(eng)
P=eng.load_all(); S=eng.build_signals(P); cal,T=S["cal"],S["close"].shape[0]
O,H,L,C=S["open"],S["high"],S["low"],S["close"]
ents=g.entry_cases(S); d=ents["A"]; e,j,px=d["e"],d["j"],d["px"]
Oa,Ha,La,Ca=g.case_path(e,j,O,H,L,C,T,39)
def mtm_nav(kind, cost, K=3):
    if kind=="E2": kf,ep,rs,hit=g.resolve_exit(px,Oa,Ha,La,Ca,1e9,-1e9); H=2
    elif kind=="X0": kf,ep,rs,hit=g.resolve_exit(px,Oa,Ha,La,Ca,0.15,-0.20); H=20
    else: kf,ep,rs,hit=g.resolve_exit(px,Oa,Ha,La,Ca,0.25,-0.30); H=40
    use,x,opx,hold,reason=g.exit_plan(e,px,kf,ep,rs,hit,Ca,H,T)
    eu,xu,pxu,ju,hu= e[use],x[use].astype(int),px[use],j[use],hold[use].astype(int)
    retf=opx[use]/pxu-1.0-cost
    navs=[]
    for sd in g.SEEDS:
        rng=np.random.default_rng(sd); cash=1.0; pos=[]; nav=np.ones(T); bd={}
        for i in range(eu.size): bd.setdefault(int(eu[i]),[]).append(i)
        for t in range(int(eu.min()),T):
            if pos:
                still=[]
                for q in pos:
                    if q[0]==t: cash+=q[1]*(1.0+retf[q[5]])
                    else: still.append(q)
                pos=still
            mv=0.0
            for q in pos:
                pt=C[t,q[6]]; mv += q[1]*(pt/q[7]) if (np.isfinite(pt) and pt>0) else q[1]
            lst,room=bd.get(t),K-len(pos)
            if lst and room>0 and cash>1e-12:
                sel=lst if len(lst)<=room else [lst[i] for i in sorted(rng.choice(len(lst),size=room,replace=False))]
                for ii in sel:
                    alloc=min(cash,(cash+mv)/K)
                    if alloc<=1e-12: break
                    cash-=alloc; pos.append((int(xu[ii]),alloc,retf[ii],int(hu[ii]),t,ii,int(ju[ii]),float(pxu[ii])))
            mv2=0.0
            for q in pos:
                pt=C[t,q[6]]; mv2 += q[1]*(pt/q[7]) if (np.isfinite(pt) and pt>0) else q[1]
            nav[t]=cash+mv2
        navs.append(nav)
    return np.mean(navs,axis=0), int(eu.min()), int(eu.size)
def met(nav,i0):
    v=nav[i0:]; rr=np.diff(v)/v[:-1]; yrs=len(rr)/244.0
    return {"sharpe":round(float(rr.mean()/rr.std(ddof=1)*np.sqrt(244.0)),3),
            "cagr":round(float((v[-1]/v[0])**(1/yrs)-1)*100,3),
            "mdd":round(float((v/np.maximum.accumulate(v)-1).min())*100,3),
            "vol_d":round(float(rr.std(ddof=1))*100,4), "n_events":None}, rr
out={"meta":{"title":"R-qlch-mtm-0923","mode":"mtm","pool":"全池(B4_K3)","K":3,"seeds":5,"run_at":time.strftime("%Y-%m-%d %H:%M:%S")},"arms":{},"paired":{}}
navs={}
for kind in ("X0","X4","E2"):
    for ck,cv in (("P20",0.0020),("S60",0.0060),("REAL",0.00070)):
        nav,i0,nev=mtm_nav(kind,cv); m,rr=met(nav,i0); m["n_events"]=nev
        out["arms"]["%s|%s"%(kind,ck)]=m; navs[(kind,ck)]=(nav,i0,rr)
        print("  MTM %-3s %s 夏普 %6.3f 年化%+7.2f%% 回撤%+7.2f%% 日波动%.4f%%" % (kind,ck,m["sharpe"],m["cagr"],m["mdd"],m["vol_d"]), flush=True)
def boot(dd,nb=2000,L=21,seed=20260923,chunk=200):
    n=dd.size; nbk=int(np.ceil(n/L)); hi=max(n-L,0); rng=np.random.default_rng(seed); off=np.arange(L); o=np.empty(nb); got=0
    while got<nb:
        m=min(chunk,nb-got); st=rng.integers(0,hi+1,size=(m,nbk)); idx=(st[:,:,None]+off[None,None,:]).reshape(m,nbk*L)[:,:n]
        o[got:got+m]=dd[idx].mean(axis=1); got+=m
    return round(float(o.mean())*100*244,3), round(float(np.percentile(o,2.5))*100*244,3), round(float(np.percentile(o,97.5))*100*244,3)
print("\n=== MTM 逐日配对差（Δ年化，块 bootstrap）===")
for a,b in ():
    na,ia,ra=navs[(a,"P20")]; nb_,ib,rb=navs[(b,"P20")]
    lo=max(ia,ib); ra2=ra[lo-ia-1:]; rb2=rb[lo-ib-1:]
    n=min(ra2.size,rb2.size); dd=ra2[:n]-rb2[:n]
    m,cl,ch=boot(dd); out["paired"]["%s-%s|P20"%("" + a,b)]={"ann_pp":m,"ci95":[cl,ch]}
    print("  %s−%s Δ年化 %+7.2f%% CI[%+7.2f,%+7.2f]" % (a,b,m,cl,ch), flush=True)
json.dump(out, open("backtest/qlch_mtm_0923.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("已落盘 backtest/qlch_mtm_0923.json | 耗时 %.0fs" % (time.time()-T0))