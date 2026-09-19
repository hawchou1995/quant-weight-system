# -*- coding: utf-8 -*-
"""诊断2: 用动态ICIR权重 vs 冻结JSON权重 分别跑引擎，看哪个复现公布数字。"""
import numpy as np, pandas as pd, pickle, json, os, math, importlib.util, sys
BASE=r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
OSS=os.path.join(BASE,"backtest","oss_0913"); FL=os.path.join(BASE,"backtest","factorlab_0913")
CFG=json.load(open(os.path.join(OSS,"super_combo_0913.json"),encoding="utf-8"))
spec=importlib.util.spec_from_file_location("rep",os.path.join(BASE,"backtest","valve_trackB_1_replicate.py"))
# 直接复用 diag 里算好的 EV/picked/ALL: 重新算一遍(便宜)
exec(open(os.path.join(BASE,"backtest","valve_trackB_0_diag.py"),encoding="utf-8").read())
Wd={}
for k in picked: Wd[k]=max(abs(EV[k][1]),0.01)
sW=sum(Wd.values()); Wd={k:v/sW for k,v in Wd.items()}
PICK=CFG["meta"]["picked"]; WJ={k:float(v) for k,v in CFG["meta"]["weights"].items()}
def make_comp(weights):
    num=np.zeros((ND,NC)); den=np.zeros((ND,NC))
    for k in PICK:
        a=np.where(ELIG3,ALL[k]*sign[k],np.nan)
        mu=np.nanmean(a,axis=1,keepdims=True); sd=np.nanstd(a,axis=1,keepdims=True)
        z=np.clip((a-mu)/(sd+1e-12),-3,3); ok=np.isfinite(z)
        num+=np.where(ok,z*weights[k],0.0); den+=np.where(ok,weights[k],0.0)
    return np.where(den>0.4,num/np.maximum(den,1e-9),np.nan)
# 引擎(逐字)
CASH0=170000.0; COMM,TAX,SLIP,MIN_COMM=0.00025,0.0005,0.0020,5.0; WARMUP=150;F=20
ALLf={**{k:ALL[k] for k in PICK}}
def etf_series(fn,col):
    df=pd.read_csv(os.path.join(BASE,"data_full",fn),parse_dates=["date"]); df["d"]=df["date"].dt.strftime("%Y-%m-%d")
    return df.drop_duplicates("d").set_index("d")[col].reindex([d for d in cal]).to_numpy()
sc1000=etf_series("sh512100.csv","close"); ma20sc=pd.Series(sc1000).rolling(20,min_periods=15).mean().to_numpy()
_ret1=pd.DataFrame(close_ff).pct_change(); _v20f=(-_ret1.rolling(20,min_periods=15).std()).to_numpy()
volpct=pd.DataFrame(np.where(ELIG3,_v20f,np.nan)).rank(axis=1,pct=True).to_numpy()
def run_engine(comp,N,offset=0,cash0=CASH0,slip=SLIP,calm=True,gate_override=None):
    shares=np.zeros(NC);cost_basis=np.zeros(NC);cash=cash0;eq_curve=np.full(ND,np.nan);trades=[]
    entry_di=np.full(NC,-1);pend_buy=[];pend_sell=[];eq_prev_known=cash0
    def mark(di):
        nz=np.flatnonzero(shares); return cash if len(nz)==0 else cash+float(np.dot(shares[nz],close_ff[di][nz]))
    for di in range(WARMUP,ND):
        px_open=O[di];px_prev=close_ff[di-1]
        if pend_sell:
            keep=[]
            for j in pend_sell:
                if not np.isfinite(px_open[j]) or px_open[j]<=px_prev[j]*0.902: keep.append(j); continue
                px=px_open[j]*(1-slip);amt=px*shares[j];fee=max(amt*COMM,MIN_COMM)+amt*TAX;proceeds=amt-fee
                cash+=proceeds;ret=proceeds/cost_basis[j]-1 if cost_basis[j]>0 else np.nan
                trades.append((entry_di[j],di,proceeds-cost_basis[j],ret))
                shares[j]=0.0;cost_basis[j]=0.0;entry_di[j]=-1
            pend_sell=keep
        if pend_buy:
            for j in pend_buy:
                if shares[j]>0 or not np.isfinite(px_open[j]) or not ELIG3[di-1][j]: continue
                if px_open[j]>=px_prev[j]*1.098 or px_open[j]<=0.01: continue
                budget=eq_prev_known/N
                lots=math.floor(min(budget,cash)/(px_open[j]*(1+slip)*100.0))
                if lots<1: continue
                px=px_open[j]*(1+slip);amt=px*lots*100.0;fee=max(amt*COMM,MIN_COMM)
                if amt+fee>cash: continue
                cash-=amt+fee;shares[j]=lots*100.0;cost_basis[j]=amt+fee;entry_di[j]=di-1
            pend_buy=[]
        eq_prev_known=mark(di);eq_curve[di]=eq_prev_known
        if (di-WARMUP-offset)%F==0 and di+1<ND:
            row=comp[di];ok=ELIG3[di]&np.isfinite(row)
            gate_open=bool(np.isfinite(ma20sc[di]) and sc1000[di]>ma20sc[di]) if gate_override is None else gate_override
            if ok.sum()>=N:
                cand=np.flatnonzero(ok)
                if gate_open: N_eff=N;sel=cand
                else:
                    N_eff=max(2,N//2);sel=cand
                    if calm:
                        sub=cand[np.isfinite(volpct[di][cand])&(volpct[di][cand]<=0.5)]
                        if len(sub)>=N_eff: sel=sub
                ordj=sel[np.argsort(-row[sel])];topN=[int(j) for j in ordj[:N_eff]];topS=set(topN)
                held=np.flatnonzero(shares>0)
                for j in held:
                    if int(j) not in topS: pend_sell.append(int(j))
                n_after=int(len([j for j in held if int(j) in topS]))
                pend_buy=[j for j in topN if shares[j]==0][:max(0,N_eff-n_after)]
    eq=pd.Series(eq_curve[WARMUP:],index=pd.to_datetime(cal[WARMUP:])).ffill().dropna()
    ret=eq.pct_change().dropna();yrs=len(eq)/244.0
    ann=(eq.iloc[-1]/eq.iloc[0])**(1/yrs)-1
    sharpe=ret.mean()/ret.std()*np.sqrt(244) if ret.std()>0 else np.nan
    dd=(eq/eq.cummax()-1).min();closed=[t for t in trades if np.isfinite(t[3])]
    yr={int(y):float(eq[eq.index.year==y].iloc[-1]/eq[eq.index.year==y].iloc[0]-1) for y in sorted(set(eq.index.year))}
    return dict(ann=float(ann),sharpe=float(sharpe),mdd=float(dd),win=float(np.mean([t[3]>0 for t in closed])),
                n_trades=len(closed),by_year=yr,eq=eq)
PUB=CFG["best"]["off0"]
c=make_comp(WJ)
for tag,kw in (("自动闸(现状)",dict()),("闸全开",dict(gate_override=True)),("闸全关",dict(gate_override=False))):
    m=run_engine(c,20,offset=0,**kw)
    print(f"[{tag}] ann={m['ann']*100:.3f}% S={m['sharpe']:.4f} mdd={m['mdd']*100:.2f}% win={m['win']*100:.2f}% n={m['n_trades']}")
    print("    by_year:",{k:round(v*100,2) for k,v in m['by_year'].items()})
print(f"[引擎公布 ] ann={PUB['ann']*100:.3f}% S={PUB['sharpe']:.4f} mdd={PUB['mdd']*100:.2f}% win={PUB['win']*100:.2f}% n={PUB['n_trades']}")
print("    by_year:",{k:round(v*100,2) for k,v in PUB['by_year'].items()})
# 2022 闸状态统计
import numpy as np
g=np.array([bool(np.isfinite(ma20sc[di]) and sc1000[di]>ma20sc[di]) for di in range(ND)])
idx=[di for di in range(150,ND) if (di-150)%20==0 and di+1<ND]
for y in (2021,2022,2023,2024,2025,2026):
    sel=[di for di in idx if str(cal[di]).startswith(str(y))]
    if sel: print(f"  {y} 调仓日 {len(sel)} 个, 闸开 {sum(g[di] for di in sel)}")
print("sh512100 非有限值个数:", int((~np.isfinite(sc1000)).sum()), "| 最后5个日期close:", [(str(cal[i]),None if not np.isfinite(sc1000[i]) else round(float(sc1000[i]),3)) for i in range(ND-5,ND)])
