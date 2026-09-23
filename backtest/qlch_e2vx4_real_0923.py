# -*- coding: utf-8 -*-
"""R-qlch-e2vx4-real-0923 · ① E2 出场日涨跌停可成交性核验 ② 用户成本档(7bp)+MTM 的 E2 vs X4 组合级配对
修：配对索引改为「同面板日」对齐（rr[j] 对应第 j+1 日）；此前版本作废
"""
import importlib.util, json, os, sys, time, io
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
T0=time.time(); BK="backtest"; COST=0.00070
os.environ["QLCH_VARIANT"]="B4"; os.environ["QLCH_MAXPOS"]="3"; os.environ["QLCH_GATE"]="20"; os.environ["QLCH_MAINBOARD"]="0"
sp=importlib.util.spec_from_file_location("g", BK+"/qlch_grid_bt_0923.py"); g=importlib.util.module_from_spec(sp); sp.loader.exec_module(g)
sp2=importlib.util.spec_from_file_location("eng", BK+"/qlch_paper_20260921.py"); eng=importlib.util.module_from_spec(sp2); sp2.loader.exec_module(eng)
P=eng.load_all(); S=eng.build_signals(P); cal,T=S["cal"],S["close"].shape[0]
O,H,L,C=S["open"],S["high"],S["low"],S["close"]; codes=S["codes"]
ents=g.entry_cases(S); d=ents["A"]; e,j,px=d["e"],d["j"],d["px"]
Oa,Ha,La,Ca=g.case_path(e,j,O,H,L,C,T,39)
def exits(kind):
    if kind=="E2": kf,ep,rs,hit=g.resolve_exit(px,Oa,Ha,La,Ca,1e9,-1e9); H=2
    else: kf,ep,rs,hit=g.resolve_exit(px,Oa,Ha,La,Ca,0.25,-0.30); H=40
    use,x,opx,hold,reason=g.exit_plan(e,px,kf,ep,rs,hit,Ca,H,T)
    return use,x.astype(int),opx,hold.astype(int),reason.astype(int)
def limw(code, dt):
    c=str(code).lower()[2:5]
    if c.startswith("688") or c.startswith("689"): return 0.20
    if c.startswith("300") or c.startswith("301"): return 0.20 if dt>="2020-08-24" else 0.10
    return 0.10
def ld(dd,col):
    if dd<=0: return np.nan
    pc=C[dd-1,col]
    return round(pc*(1-limw(codes[col],cal[dd])),2) if (np.isfinite(pc) and pc>0) else np.nan
# ---------- ① E2 ----------
u,x,opx,hold,rsn=exits("E2"); eu,xu,pxu,ju= e[u],x[u],px[u],j[u]
bad=0; rows=[]
for i in range(xu.size):
    L_=ld(xu[i],ju[i])
    if np.isfinite(L_) and C[xu[i],ju[i]]<=L_+1e-9:
        bad+=1; rows.append(i)
print("① E2 出场日涨跌停核验：可用 %d 笔 | 收盘封跌停（不可卖） %d 笔 = %.2f%%"
      % (xu.size,bad,100*bad/xu.size),flush=True)
r0=opx[u]/pxu-1.0-COST
print("   事件级（7bp）：原 n=%d 均值%+.3f%% 胜率%.1f%%" % (r0.size,r0.mean()*100,(r0>0).mean()*100),flush=True)
if bad:
    keep=np.ones(xu.size,bool); newpx=opx[u].copy()
    for i in rows:
        col=ju[i]; got=False
        for k in range(1,6):
            dd=xu[i]+k
            if dd>=T: break
            L2=ld(dd,col)
            if np.isfinite(C[dd,col]) and (not np.isfinite(L2) or C[dd,col]>L2+1e-9):
                newpx[i]=C[dd,col]; got=True; break
        if not got: keep[i]=False
    r1=(newpx[keep]/pxu[keep]-1.0-COST)
    print("   修正后：n=%d 均值%+.3f%% 胜率%.1f%%（顺延成交）" % (r1.size,r1.mean()*100,(r1>0).mean()*100),flush=True)
# ---------- ② MTM 组合级 + 配对 ----------
def mtm_nav(kind):
    u,x,opx,hold,rsn=exits(kind); eu,xu,pxu,ju,hu=e[u],x[u],px[u],j[u],hold[u]
    retf=opx[u]/pxu-1.0-COST; navs=[]
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
            lst,room=bd.get(t),3-len(pos)
            if lst and room>0 and cash>1e-12:
                sel=lst if len(lst)<=room else [lst[i] for i in sorted(rng.choice(len(lst),size=room,replace=False))]
                for ii in sel:
                    alloc=min(cash,(cash+mv)/3)
                    if alloc<=1e-12: break
                    cash-=alloc; pos.append((int(xu[ii]),alloc,retf[ii],int(hu[ii]),t,ii,int(ju[ii]),float(pxu[ii])))
            mv2=sum(q[1]*((C[t,q[6]]/q[7]) if (np.isfinite(C[t,q[6]]) and C[t,q[6]]>0) else 1.0) for q in pos)
            nav[t]=cash+mv2
        navs.append(nav)
    return np.mean(navs,axis=0), int(eu.min())
navE,i0E=mtm_nav("E2"); navX,i0X=mtm_nav("X4")
i0=max(i0E,i0X)
def met(nav):
    v=nav[i0:]; rr=np.diff(v)/v[:-1]; yrs=len(rr)/244.0
    return dict(sharpe=round(float(rr.mean()/rr.std(ddof=1)*np.sqrt(244)),3), cagr=round(float((v[-1]/v[0])**(1/yrs)-1)*100,3),
                mdd=round(float((v/np.maximum.accumulate(v)-1).min())*100,3)), np.diff(nav)/nav[:-1]
mE,rrE=met(navE); mX,rrX=met(navX)
j0=i0-1; jT=T-1
dd=rrE[j0:jT]-rrX[j0:jT]
def boot(s,nb=4000,L=21,seed=20260923):
    n=s.size; nbk=int(np.ceil(n/L)); hi=max(n-L,0); rng=np.random.default_rng(seed); off=np.arange(L); o=np.empty(nb); got=0
    while got<nb:
        m=min(200,nb-got); st=rng.integers(0,hi+1,size=(m,nbk)); idx=(st[:,:,None]+off[None,None,:]).reshape(m,nbk*L)[:,:n]
        o[got:got+m]=s[idx].mean(axis=1); got+=m
    lo,hi_=np.percentile(o,[2.5,97.5]); return round(float(s.mean())*100*244,3), round(float(lo)*100*244,3), round(float(hi_)*100*244,3)
ann,cl,ch=boot(dd)
i_tr=max([i for i,dt in enumerate(cal) if dt<=g.TRAIN_HI] or [0]); i_va=min([i for i,dt in enumerate(cal) if dt>=g.VAL_LO] or [T-1])
def sub(lo,hi): 
    a=max(lo,i0)-1; b=hi-1
    s=rrE[a:b]-rrX[a:b]; return round(float(s.mean())*100*244,3)
tr_,va_=sub(i0,i_tr),sub(i_va,T-1)
print("\n② 用户成本档 7bp + MTM（同面板日对齐，i0=%s）：" % cal[i0],flush=True)
print("   E2 夏普 %.3f 年化%+.2f%% 回撤%+.2f%% | X4 夏普 %.3f 年化%+.2f%% 回撤%+.2f%%" % (mE['sharpe'],mE['cagr'],mE['mdd'],mX['sharpe'],mX['cagr'],mX['mdd']),flush=True)
print("   配对 Δ年化(E2−X4) = %+.2f%%  CI95[%+.2f%%,%+.2f%%]  n=%d 日 | train %+.2f%% / val %+.2f%%" % (ann,cl,ch,dd.size,tr_,va_),flush=True)
json.dump({"limit_E2":{"usable":int(xu.size),"unfillable":int(bad),"share_pct":round(100*bad/xu.size,3)},
 "mtm_real_7bp":{"E2":{"sharpe":mE['sharpe'],"cagr":mE['cagr'],"mdd":mE['mdd']},"X4":{"sharpe":mX['sharpe'],"cagr":mX['cagr'],"mdd":mX['mdd']},
 "paired_ann_pct":ann,"ci95":[cl,ch],"train":tr_,"val":va_,"i0":cal[i0]}}, open("backtest/qlch_e2vx4_real_0923.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("已落盘 backtest/qlch_e2vx4_real_0923.json | 耗时 %.0fs" % (time.time()-T0))