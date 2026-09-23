# -*- coding: utf-8 -*-
"""R-qlch-amort-0923 · 摊销口径对照：同一批成交，三种净值计价约定下的夏普
amort（生产现行）= 多日收益按持有期几何摊销进日净值
realized        = 持仓按成本计价，收益在出场日一次性确认
mtm             = 按标的每日收盘 md 计价（真实盯市）
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
kf,expx,exrs,hit=g.resolve_exit(px,Oa,Ha,La,Ca,0.25,-0.30)
use,x,opx,hold,reason=g.exit_plan(e,px,kf,expx,exrs,hit,Ca,40,T)
eu,xu,pxu,ju,hu = e[use], x[use].astype(int), px[use], j[use], hold[use].astype(int)
def run(mode, cost, K=3, seeds=g.SEEDS):
    retf = opx[use]/pxu - 1.0 - cost
    navs=[]; trs=[]
    for sd in seeds:
        rng=np.random.default_rng(sd); cash=1.0; pos=[]; nav=np.ones(T); by_day={}
        for i in range(eu.size): by_day.setdefault(int(eu[i]), []).append(i)
        for t in range(int(eu.min()), T):
            if pos:
                still=[]
                for q in pos:
                    if q[0]==t:
                        cash += q[1]*(1.0+retf[q[5]])
                        if mode=="realized": pass
                        trs.append(retf[q[5]])
                    else: still.append(q)
                pos=still
            mv=0.0
            for q in pos:
                elap=min(t-q[4]+1, q[3])
                if mode=="amort": mv += q[1]*(1.0+retf[q[5]])**(elap/q[3])
                elif mode=="realized": mv += q[1]
                else:
                    p0=q[7]; pt=C[t, int(q[6])]
                    mv += q[1]*(pt/p0) if (np.isfinite(pt) and pt>0) else q[1]
            lst, room = by_day.get(t), K-len(pos)
            if lst and room>0 and cash>1e-12:
                sel = lst if len(lst)<=room else [lst[i] for i in sorted(rng.choice(len(lst), size=room, replace=False))]
                for ii in sel:
                    alloc=min(cash,(cash+mv)/K)
                    if alloc<=1e-12: break
                    cash-=alloc; pos.append((int(xu[ii]), alloc, retf[ii], int(hu[ii]), t, ii, int(ju[ii]), float(pxu[ii])))
            mv2=0.0
            for q in pos:
                elap=min(t-q[4]+1, q[3])
                if mode=="amort": mv2 += q[1]*(1.0+retf[q[5]])**(elap/q[3])
                elif mode=="realized": mv2 += q[1]
                else:
                    pt=C[t, int(q[6])]; mv2 += q[1]*(pt/q[7]) if (np.isfinite(pt) and pt>0) else q[1]
            tot=cash+mv2; nav[t]=tot
        nav[int(eu.min()):][nav[int(eu.min()):]==1.0] = nav[int(eu.min()):][nav[int(eu.min()):]==1.0]
        navs.append(nav)
    return np.mean(navs,axis=0)
i0=int(eu.min())
print("三种计价约定（全池 X4 · K=3 · 5 种子平均净值 · 窗口 %s→%s）" % (cal[i0], cal[-1]))
res={}
for mode in ("amort","realized","mtm"):
    for ck,cv in (("P20",0.0020),("S60",0.0060)):
        nav=run(mode,cv); v=nav[i0:]; rr=np.diff(v)/v[:-1]
        yrs=len(rr)/244.0
        sh=float(rr.mean()/rr.std(ddof=1)*np.sqrt(244.0)); cagr=float((v[-1]/v[0])**(1/yrs)-1)*100
        mdd=float((v/np.maximum.accumulate(v)-1).min())*100
        res["%s|%s"%(mode,ck)]={"sharpe":round(sh,3),"cagr":round(cagr,3),"mdd":round(mdd,3),"vol_daily_pct":round(float(rr.std(ddof=1))*100,4)}
        print("  %-9s %s 夏普 %6.3f | 年化 %+7.2f%% | 回撤 %+7.2f%% | 日波动 %.4f%%" % (mode,ck,sh,cagr,mdd,rr.std(ddof=1)*100), flush=True)
json.dump({"meta":{"title":"R-qlch-amort-0923","pool":"全池(B4_K3)","arm":"X4","window":[cal[i0],cal[-1]]},"modes":res},
          open("backtest/qlch_amort_0923.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("已落盘 backtest/qlch_amort_0923.json | 耗时 %.0fs" % (time.time()-T0))