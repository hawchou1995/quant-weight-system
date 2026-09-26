# -*- coding: utf-8 -*-
"""sv3b (FIXED): delisted-name panel + extended-universe re-run. Entry=O[t], exit=C[exit_day] (no shifted arrays)."""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); T = len(cal); lut={d:i for i,d in enumerate(cal)}
mnames=[u["sym"] for u in U["universe"]]
bars = pd.read_csv(R/"backtest/_delisted_universe/delisted_bars.csv.gz")
bars["ri"]=bars["date"].map(lut); bars=bars[bars["ri"].notna()].copy(); bars["ri"]=bars["ri"].astype(int)
syms=sorted(bars["sym"].unique()); ND=len(syms)
D={k:np.zeros((T,ND),dtype=np.float32) for k in ("OPEN","HIGH","LOW","CLOSE","VOL","AMT")}
dcol={s_:i for i,s_ in enumerate(syms)}
for r in bars.itertuples(index=False):
    j=dcol[r.sym]
    D["OPEN"][r.ri,j]=r.open; D["HIGH"][r.ri,j]=r.high; D["LOW"][r.ri,j]=r.low
    D["CLOSE"][r.ri,j]=r.close; D["VOL"][r.ri,j]=r.volume; D["AMT"][r.ri,j]=r.amount
DC,DO,DH,DL,DV,DA=(D[k] for k in ("CLOSE","OPEN","HIGH","LOW","VOL","AMT"))
DVALID=(DC>0)&np.isfinite(DC)&(DO>0)
Dc=np.where(DVALID,DC,np.nan); Dv=np.where(DVALID,DV,np.nan); Da=np.where(DVALID,DA,np.nan)
DRET20=np.full((T,ND),np.nan,dtype=np.float32); DRET20[20:]=Dc[20:]/Dc[:-20]-1.0
DAMT20=pd.DataFrame(Da).rolling(20,min_periods=10).mean().to_numpy(dtype=np.float32)
DVMA20=pd.DataFrame(Dv).rolling(20,min_periods=10).mean().to_numpy(dtype=np.float32)
DVOLBR=DV/np.where(DVMA20>0,DVMA20,np.nan)
DNV=np.cumsum(DVALID,axis=0).astype(np.int32)
DGAP=np.full((T,ND),np.nan,dtype=np.float32); DGAP[:-1]=DO[1:]/np.where(DC[:-1]>0,DC[:-1],np.nan)-1.0
print("退市帧 %d 只 / %d 行; 有效格 %.2f%%; NV>=250 的 %d 只" % (ND,len(bars),100*DVALID.sum()/DVALID.size,int((DNV[-1]>=250).sum())))
MM=lambda n: np.asarray(np.load(S/n, mmap_mode="r"))
MO,MC,MA,MR=MM("wl_OPEN.npy"),MM("wl_CLOSE.npy"),MM("wl_AMT20.npy"),MM("wl_RET20.npy")
MVOLBR,MGAP,MNV,MC_=MM("wl2_VOLBR.npy"),MM("wl2_GAPNEXT.npy"),MM("wl_NV.npy"),MM("wl_CLOSE.npy")
MVALID=np.load(S/"wl_VALID.npy").astype(bool)
def zs(x):
    x=np.asarray(x,float); mu=np.nanmean(x); sd=np.nanstd(x)
    return (x-mu)/sd if np.isfinite(sd) and sd>0 else np.zeros_like(x)
MINAMT=2e7
def pool_day(t, fr):
    if fr=="M":
        ok=MVALID[t]&(MNV[t]>=250)&(MC_[t]>=2.0)&np.isfinite(MA[t])&(MA[t]>=MINAMT)
        g,amt,vb,rt=MGAP[t],MA[t],MVOLBR[t],MR[t]
    else:
        ok=DVALID[t]&(DNV[t]>=250)&(DC[t]>=2.0)&np.isfinite(DAMT20[t])&(DAMT20[t]>=MINAMT)
        g,amt,vb,rt=DGAP[t],DAMT20[t],DVOLBR[t],DRET20[t]
    m=ok&np.isfinite(g)&(g<=-0.01)&(g>=-0.03)&np.isfinite(amt)&(amt>0)&np.isfinite(vb)&(vb>0)&np.isfinite(rt)
    return np.nonzero(m)[0]
def build(universe, K=10):
    sig={}; st=dict(pool_main=0,pool_dead=0,picks_main=0,picks_dead=0)
    for t in range(60,T-3):
        parts=[]
        for fr in universe:
            ix=pool_day(t,fr)
            if not ix.size: continue
            amt = (MA[t][ix] if fr=="M" else DAMT20[t][ix])
            vb  = (MVOLBR[t][ix] if fr=="M" else DVOLBR[t][ix])
            rt  = (MR[t][ix] if fr=="M" else DRET20[t][ix])
            parts.append((fr, ix, np.column_stack([amt,vb,rt])))
            st["pool_main" if fr=="M" else "pool_dead"] += int(ix.size)
        if not parts: continue
        F=np.vstack([p[2] for p in parts])
        comp=zs(-np.log(F[:,0]))+zs(-np.log(F[:,1]))+zs(-F[:,2])
        sel=[]; off=0
        for fr,ix,_ in parts:
            sel.append((fr, ix, comp[off:off+ix.size])); off+=ix.size
        merged=np.concatenate([s[2] for s in sel]); kmax=np.minimum(K, merged.size)
        top=np.argsort(-merged)[:kmax]
        out=[]
        starts=np.cumsum([0]+[s[1].size for s in sel])
        for k in top:
            bi=int(np.searchsorted(starts, k, side="right")-1)
            fr,ix,_=sel[bi]; loc=int(ix[k-starts[bi]])
            out.append((fr,loc)); st["picks_main" if fr=="M" else "picks_dead"] += 1
        sig[t]=out
    return sig, st
def sim(sig, cost_side=0.000346, K=10):
    def arr(fr, which):
        if which=="in": return MO if fr=="M" else DO
        return MC_ if fr=="M" else DC
    def exit_px(fr,j,t):
        a=arr(fr,"out"); x=a[t,j]
        if np.isfinite(x) and x>0: return x,t,0
        for k in range(t+1,min(t+6,T)):
            x=a[k,j]
            if np.isfinite(x) and x>0: return x,k,1
        for k in range(min(t,T-1),max(0,t-40),-1):
            x=a[k,j]
            if np.isfinite(x) and x>0: return x,k,2
        return np.nan,t,3
    ts=min(sig); cash=1.0; pos={}; nav=np.full(T,np.nan); trades=[]; nav[ts]=1.0
    for t in range(ts+1,T):
        for key in [k for k,p in pos.items() if p["tgt"]<=t]:
            p=pos[key]; x,used,flag=exit_px(p["fr"],p["j"],t)
            if np.isfinite(x) and x>0:
                pos.pop(key); cash+=p["sh"]*x*(1-cost_side)
                trades.append((str(cal[used])[:4],(x*(1-cost_side)/(p["px"]*(1+cost_side))-1)*100,p["fr"],flag))
            else:
                p["tgt"]=t+1
        for fr,j in sig.get(t-1,[]):
            if len(pos)>=2*K: continue
            key=(fr,j)
            if key in pos: continue
            x=arr(fr,"in")[t,j]
            if not (np.isfinite(x) and x>0): continue
            navprev=nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            alloc=min(navprev/(2*K),cash)
            if alloc<=1e-12: break
            pos[key]=dict(en=t,tgt=t+2,sh=alloc/(x*(1+cost_side)),px=x,fr=fr,j=j); cash-=alloc
        mv=0.0
        for key,p in pos.items():
            c=arr(p["fr"],"out")[t,p["j"]]
            mv += p["sh"]*(c if np.isfinite(c) and c>0 else p["px"])
        nav[t]=cash+mv
    IDX=pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
    BC=pd.to_numeric(IDX.set_index("date").reindex(cal)["close"],errors="coerce").to_numpy(float)
    bnav=np.full(T,np.nan); bnav[ts]=1.0
    for t in range(ts+1,T): bnav[t]=BC[t]/BC[ts]
    ok=np.isfinite(nav); v=nav[ok]; b=bnav[ok]; nd=len(v)-1
    ann=(v[-1]/v[0])**(244/nd)-1; pk=np.maximum.accumulate(v); dr=v[1:]/v[:-1]-1; sd=dr.std(ddof=1)
    bann=(b[-1]/b[0])**(244/nd)-1
    r=np.array([x[1] for x in trades],float)
    dm=[x[1] for x in trades if x[2]=="D"]
    ys=sorted(set(x[0] for x in trades))
    return dict(ann=round(float(ann*100),2), mdd=round(float((v/pk-1).min())*100,2),
        sharpe=round(float(dr.mean()/sd*np.sqrt(244)),2) if sd>0 else None, exc=round(float(ann-bann)*100,2),
        n=int(r.size), mean=round(float(r.mean()),4), med=round(float(np.median(r)),4), wr=round(float(100*(r>0).mean()),2),
        negY=int(sum(1 for y in ys if np.mean([z[1] for z in trades if z[0]==y])<0)), nY=int(len(ys)),
        n_dead=int(len(dm)), dead_mean=round(float(np.mean(dm)),4) if dm else None,
        used_lastpx=int(sum(1 for x in trades if x[3]==2)), wiped=int(sum(1 for x in trades if x[3]==3)),
        per_year={y: round(float(np.mean([z[1] for z in trades if z[0]==y])),3) for y in ys})
res={}
print("\n=== 对照 ===")
for lab,uni in (("仅现存(5207)",["M"]),("扩展(5207+250退市)",["M","D"])):
    sig,st=build(uni); out=sim(sig); out["stats"]=st; res[lab]=out
    print("  %-20s 笔数 %6d (退市股 %4d, 均值 %s) 年化 %+8.2f%% MDD %7.2f%% 夏普 %5.2f 超额 %+8.2fpp 净均 %+7.4f%% 净中 %+7.4f%% 净胜 %5.2f%% 负年 %d/%d" %
          (lab,out["n"],out["n_dead"],out["dead_mean"],out["ann"],out["mdd"],out["sharpe"] or 0,out["exc"],out["mean"],out["med"],out["wr"],out["negY"],out["nY"]), flush=True)
    st2=out["stats"]; print("     池日均: 现存 %.0f 条 / 退市 %.0f 条 | 选中: 现存 %d / 退市 %d | 用末价了结 %d 笔, 归零 %d 笔" %
          (st2["pool_main"]/2340, st2["pool_dead"]/2340, st2["picks_main"], st2["picks_dead"], out["used_lastpx"], out["wiped"]))
print("\n回归验证: '仅现存' 应 = r9b 的 +141.04% / 净均 +0.8151%")
json.dump(res, open(S/"sv3b_extended.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved sv3b_extended.json")
