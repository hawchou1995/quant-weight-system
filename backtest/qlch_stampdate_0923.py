# -*- coding: utf-8 -*-
"""R-qlch-stampdate-0923 · 按日期生效的印花税（2023-08-28 前 0.1% / 后 0.05%）重跑 MTM 三臂
成本(往返, 按**卖出日**计) = 佣金 0.86bp×2 + 印花税(0.1%/0.05%) + 过户 0.001%×2
  => 2023-08-28 前 11.92bp / 之后 6.92bp
"""
import importlib.util, json, os, sys, time, io
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
T0=time.time(); BK="backtest"; DT="2023-08-28"
os.environ["QLCH_VARIANT"]="B4"; os.environ["QLCH_MAXPOS"]="3"; os.environ["QLCH_GATE"]="20"; os.environ["QLCH_MAINBOARD"]="0"
sp=importlib.util.spec_from_file_location("g", BK+"/qlch_grid_bt_0923.py"); g=importlib.util.module_from_spec(sp); sp.loader.exec_module(g)
sp2=importlib.util.spec_from_file_location("eng", BK+"/qlch_paper_20260921.py"); eng=importlib.util.module_from_spec(sp2); sp2.loader.exec_module(eng)
P=eng.load_all(); S=eng.build_signals(P); cal,T=S["cal"],S["close"].shape[0]
O,H,L,C=S["open"],S["high"],S["low"],S["close"]
ents=g.entry_cases(S); d=ents["A"]; e,j,px=d["e"],d["j"],d["px"]
Oa,Ha,La,Ca=g.case_path(e,j,O,H,L,C,T,39)
COMM=0.000086*2; XFER=0.00001*2
def cost_vec(xday):
    stamp=np.where(np.array([cal[t] for t in xday])>=DT, 0.0005, 0.0010)
    return COMM+stamp+XFER
def arm(kind):
    if kind=="E2": kf,ep,rs,hit=g.resolve_exit(px,Oa,Ha,La,Ca,1e9,-1e9); H=2
    elif kind=="X0": kf,ep,rs,hit=g.resolve_exit(px,Oa,Ha,La,Ca,0.15,-0.20); H=20
    else: kf,ep,rs,hit=g.resolve_exit(px,Oa,Ha,La,Ca,0.25,-0.30); H=40
    use,x,opx,hold,reason=g.exit_plan(e,px,kf,ep,rs,hit,Ca,H,T)
    xu=x[use].astype(int); retf=opx[use]/px[use]-1.0-cost_vec(xu)
    return e[use],xu,px[use],j[use],hold[use].astype(int),retf
def nav_mtm(kind,K=3):
    eu,xu,pxu,ju,hu,retf=arm(kind)
    navs=[]; navs5=[]
    for sd in g.SEEDS:
        rng=np.random.default_rng(sd); cash=1.0; pos=[]; nav=np.ones(T); bd={}
        for i in range(eu.size): bd.setdefault(int(eu[i]),[]).append(i)
        for t in range(int(eu.min()),T):
            if pos:
                st=[]
                for q in pos:
                    if q[0]==t: cash+=q[1]*(1.0+retf[q[5]])
                    else: st.append(q)
                pos=st
            mv=sum(q[1]*((C[t,q[6]]/q[7]) if (np.isfinite(C[t,q[6]]) and C[t,q[6]]>0) else 1.0) for q in pos)
            lst,room=bd.get(t),K-len(pos)
            if lst and room>0 and cash>1e-12:
                sel=lst if len(lst)<=room else [lst[i] for i in sorted(rng.choice(len(lst),size=room,replace=False))]
                for ii in sel:
                    alloc=min(cash,(cash+mv)/K)
                    if alloc<=1e-12: break
                    cash-=alloc; pos.append((int(xu[ii]),alloc,retf[ii],int(hu[ii]),t,ii,int(ju[ii]),float(pxu[ii])))
            mv2=sum(q[1]*((C[t,q[6]]/q[7]) if (np.isfinite(C[t,q[6]]) and C[t,q[6]]>0) else 1.0) for q in pos)
            nav[t]=cash+mv2
        navs.append(nav)
    v=np.mean(navs,axis=0)[int(eu.min()):]; rr=np.diff(v)/v[:-1]; yrs=len(rr)/244.0
    return dict(sharpe=round(float(rr.mean()/rr.std(ddof=1)*np.sqrt(244)),3),
                cagr=round(float((v[-1]/v[0])**(1/yrs)-1)*100,3),
                mdd=round(float((v/np.maximum.accumulate(v)-1).min())*100,3),
                n_events=int(eu.size), mean_net_pct=round(float(retf.mean())*100,4))
out={"meta":{"title":"R-qlch-stampdate-0923","rule":"stamp 0.1% before 2023-08-28 -> 0.05% after; cost by EXIT date",
             "cost_pre_bp":round((COMM+0.0010+XFER)*10000,2),"cost_post_bp":round((COMM+0.0005+XFER)*10000,2),
             "pool":"全池(B4_K3)","conv":"MTM","run_at":time.strftime("%Y-%m-%d %H:%M:%S")},"arms":{}}
print("成本：2023-08-28 前 %.2fbp / 之后 %.2fbp（按卖出日）" % (out["meta"]["cost_pre_bp"], out["meta"]["cost_post_bp"]))
for kind in ("X0","X4","E2"):
    m=nav_mtm(kind); out["arms"][kind]=m
    print("  %-3s 夏普 %6.3f | 年化 %+7.2f%% | 回撤 %+7.2f%% | 事件 %d | 单笔均值(含变动成本) %+.3f%%"
          % (kind,m["sharpe"],m["cagr"],m["mdd"],m["n_events"],m["mean_net_pct"]), flush=True)
json.dump(out, open("backtest/qlch_stampdate_0923.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("已落盘 backtest/qlch_stampdate_0923.json | 耗时 %.0fs" % (time.time()-T0))