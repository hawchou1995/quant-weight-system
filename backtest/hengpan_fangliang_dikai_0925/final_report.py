# -*- coding: utf-8 -*-
"""final_report.py — 定版合并报表: 同口径下的年化/回撤/信号密度/单笔统计/分年度
口径: 扩展池(现存5207+退市253) + 修正后 VOLBR(滞后) + K=10,KSLOT=20 + 成本 6.92bp 往返
"""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); T = len(cal); lut={d:i for i,d in enumerate(cal)}
mnames=[u["sym"] for u in U["universe"]]
bars = pd.read_csv(R/"backtest/_delisted_universe/delisted_bars.csv.gz")
bars["ri"]=bars["date"].map(lut); bars=bars[bars["ri"].notna()].copy(); bars["ri"]=bars["ri"].astype(int)
syms=sorted(bars["sym"].unique()); ND=len(syms)
D={k:np.zeros((T,ND),dtype=np.float32) for k in ("OPEN","CLOSE","VOL","AMT")}
dcol={s_:i for i,s_ in enumerate(syms)}
for r in bars.itertuples(index=False):
    j=dcol[r.sym]
    D["OPEN"][r.ri,j]=r.open; D["CLOSE"][r.ri,j]=r.close; D["VOL"][r.ri,j]=r.volume; D["AMT"][r.ri,j]=r.amount
DO,DC,DV,DA=(D[k] for k in ("OPEN","CLOSE","VOL","AMT"))
DVALID=(DC>0)&np.isfinite(DC)&(DO>0)
Dc=np.where(DVALID,DC,np.nan); Dv=np.where(DVALID,DV,np.nan); Da=np.where(DVALID,DA,np.nan)
DRET20=np.full((T,ND),np.nan,dtype=np.float32); DRET20[20:]=Dc[20:]/Dc[:-20]-1.0
DAMT20=pd.DataFrame(Da).rolling(20,min_periods=10).mean().to_numpy(dtype=np.float32)
DVMA20=pd.DataFrame(Dv).rolling(20,min_periods=10).mean().to_numpy(dtype=np.float32)
DVMA20p=np.full_like(DVMA20,np.nan); DVMA20p[1:]=DVMA20[:-1]
DVOLBR=DV/np.where(DVMA20p>0,DVMA20p,np.nan)
DNV=np.cumsum(DVALID,axis=0).astype(np.int32)
DGAP=np.full((T,ND),np.nan,dtype=np.float32); DGAP[:-1]=DO[1:]/np.where(DC[:-1]>0,DC[:-1],np.nan)-1.0
MM=lambda n: np.asarray(np.load(S/n, mmap_mode="r"))
MO,MC,MA,MR=MM("wl_OPEN.npy"),MM("wl_CLOSE.npy"),MM("wl_AMT20.npy"),MM("wl_RET20.npy")
MVOLBR,MGAP,MNV=MM("wl2_VOLBR.npy"),MM("wl2_GAPNEXT.npy"),MM("wl_NV.npy")
MVALID=np.load(S/"wl_VALID.npy").astype(bool); NM=MC.shape[1]
def zs(x):
    x=np.asarray(x,float); mu=np.nanmean(x); sd=np.nanstd(x)
    return (x-mu)/sd if np.isfinite(sd) and sd>0 else np.zeros_like(x)
P1,P2,MINAMT,MINPX,LISTED,K,KSLOT=0.01,0.03,2e7,2.0,250,10,20
def eligM(t): return MVALID[t]&(MNV[t]>=LISTED)&(MC[t]>=MINPX)&np.isfinite(MA[t])&(MA[t]>=MINAMT)
def eligD(t): return DVALID[t]&(DNV[t]>=LISTED)&(DC[t]>=MINPX)&np.isfinite(DAMT20[t])&(DAMT20[t]>=MINAMT)
pool_sizes=[]; picks_per_day=[]; empty_days=0; sig={}
for t in range(60,T-3):
    parts=[]
    for fr in ("M","D"):
        if fr=="M":
            ok=eligM(t); g=MGAP[t]; amt=MA[t]; vb=MVOLBR[t]; rt=MR[t]
        else:
            ok=eligD(t); g=DGAP[t]; amt=DAMT20[t]; vb=DVOLBR[t]; rt=DRET20[t]
        m=ok&np.isfinite(g)&(g<=-P1)&(g>=-P2)&np.isfinite(amt)&(amt>0)&np.isfinite(vb)&(vb>0)&np.isfinite(rt)
        ix=np.nonzero(m)[0]
        if ix.size: parts.append((fr,ix,np.column_stack([amt[ix],vb[ix],rt[ix]])))
    n=sum(p[1].size for p in parts); pool_sizes.append(n)
    if not parts: empty_days+=1; continue
    F=np.vstack([p[2] for p in parts]); comp=zs(-np.log(F[:,0]))+zs(-np.log(F[:,1]))+zs(-F[:,2])
    sel=[]; off=0
    for fr,ix,_ in parts: sel.append((fr,ix,comp[off:off+ix.size])); off+=ix.size
    merged=np.concatenate([s[2] for s in sel]); starts=np.cumsum([0]+[s[1].size for s in sel])
    out=[]
    for k in np.argsort(-merged)[:min(K,merged.size)]:
        bi=int(np.searchsorted(starts,k,side="right")-1); fr,ix,_=sel[bi]
        out.append((fr,int(ix[k-starts[bi]])))
    sig[t]=out; picks_per_day.append(len(out))
pool_sizes=np.array(pool_sizes); picks_per_day=np.array(picks_per_day)
def arr(fr,which):
    if which=="in": return MO if fr=="M" else DO
    return MC if fr=="M" else DC
def sim(entry_mode, slip, cost_side):
    ts=min(sig); cash=1.0; pos={}; nav=np.full(T,np.nan); trades=[]; nav[ts-1 if ts>0 else 0]=1.0
    for t in range(ts+1,T):
        for key in [k for k,p in pos.items() if p["tgt"]<=t]:
            p=pos[key]; a=arr(p["fr"],"out"); x=a[t,p["j"]]; used=t; flag=0
            if not (np.isfinite(x) and x>0):
                for k2 in range(t+1,min(t+6,T)):
                    if np.isfinite(a[k2,p["j"]]) and a[k2,p["j"]]>0: x,used,flag=a[k2,p["j"]],k2,1; break
                else:
                    for k2 in range(min(t,T-1),max(0,t-40),-1):
                        if np.isfinite(a[k2,p["j"]]) and a[k2,p["j"]]>0: x,used,flag=a[k2,p["j"]],k2,2; break
                    else: x,used,flag=0.0,t,3
            if np.isfinite(x) and x>0:
                pos.pop(key); cash+=p["sh"]*x*(1-cost_side)
                trades.append((str(cal[used])[:4], str(cal[p["en"]])[:4], (x*(1-cost_side)/(p["px"]*(1+cost_side))-1)*100, flag))
            else: p["tgt"]=t+1
        for fr,j in sig.get(t-1,[]):
            if len(pos)>=KSLOT: continue
            key=(fr,j)
            if key in pos: continue
            if entry_mode=="open":
                base=arr(fr,"in")[t,j]; x=base*(1+slip) if np.isfinite(base) and base>0 else np.nan
            else:
                x=arr(fr,"out")[t,j]
            if not (np.isfinite(x) and x>0): continue
            navprev=nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            alloc=min(navprev/KSLOT,cash)
            if alloc<=1e-12: break
            pos[key]=dict(en=t,tgt=t+2,sh=alloc/(x*(1+cost_side)),px=x,fr=fr,j=j); cash-=alloc
        mv=0.0
        for key,p in pos.items():
            c=arr(p["fr"],"out")[t,p["j"]]; mv += p["sh"]*(c if np.isfinite(c) and c>0 else p["px"])
        nav[t]=cash+mv
    IDX=pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
    BC=pd.to_numeric(IDX.set_index("date").reindex(cal)["close"],errors="coerce").to_numpy(float)
    bnav=np.full(T,np.nan); bnav[ts-1 if ts>0 else 0]=1.0
    for t in range(ts,T): bnav[t]=BC[t]/BC[ts-1 if ts>0 else 0]
    return nav,bnav,trades
COST=0.000346
SCEN=[("S1 以开盘价成交", "open", 0.0), ("S2 开盘价+0.2%滑价", "open", 0.002),
      ("S3 开盘价+0.5%滑价", "open", 0.005), ("S4 错失开盘(买T+1收盘)", "close", 0.0)]
res={}
print("=" * 118)
print("定版口径: 扩展池 5,460(现存5,207+退市253) | 复合打分 | K=10 | KSLOT=20 | 成本 6.92bp 往返 | 区间 2017-01~2026-09")
print("=" * 118)
for lab, mode, slip in SCEN:
    nav,bnav,tr = sim(mode, slip, COST)
    ok=np.isfinite(nav); v=nav[ok]; b=bnav[ok]; nd=len(v)-1
    ann=(v[-1]/v[0])**(244/nd)-1; pk=np.maximum.accumulate(v); mdd=float((v/pk-1).min())
    dr=v[1:]/v[:-1]-1; sd=dr.std(ddof=1); bann=(b[-1]/b[0])**(244/nd)-1
    r=np.array([x[2] for x in tr],float)
    # 分年度 NAV 收益
    yr={}
    idx=[i for i,d in enumerate(cal) if np.isfinite(nav[i])]
    for y in sorted({str(cal[i])[:4] for i in idx}):
        ii=[i for i in idx if str(cal[i])[:4]==y]
        if len(ii)<2: continue
        yr[y]=float(nav[ii[-1]]/nav[ii[0]]-1)*100
    # 分年度单笔
    yt={}
    for t4,t5,rr,fl in tr: yt.setdefault(t4,[]).append(rr)
    res[lab]=dict(ann=round(ann*100,2), mdd=round(mdd*100,2), sharpe=round(float(dr.mean()/sd*np.sqrt(244)),2),
                  bench_ann=round(bann*100,2), exc=round((ann-bann)*100,2), n=int(r.size),
                  mean=round(float(r.mean()),4), med=round(float(np.median(r)),4), wr=round(float(100*(r>0).mean()),2),
                  nav_year={k:round(v_,2) for k,v_ in yr.items()},
                  trade_year={k:dict(n=len(vv), mean=round(float(np.mean(vv)),4), med=round(float(np.median(vv)),4), wr=round(float(100*np.mean(np.array(vv)>0)),2)) for k,vv in sorted(yt.items())})
    print("%-24s 年化 %+9.2f%% | MDD %7.2f%% | 夏普 %5.2f | 单笔净均 %+7.4f%% | 净中位 %+7.4f%% | 净胜率 %5.2f%% | 笔数 %5d | 超额 %+8.2fpp"
          % (lab, ann*100, mdd*100, float(dr.mean()/sd*np.sqrt(244)), r.mean(), np.median(r), 100*(r>0).mean(), r.size, (ann-bann)*100), flush=True)
print("-" * 118)
print("信号密度: 合格池/日  均值 %.0f 中位 %d p90 %d max %d" % (pool_sizes.mean(), np.median(pool_sizes), np.percentile(pool_sizes,90), pool_sizes.max()))
print("          实际买入/日 均值 %.1f 中位 %d (上限 K=10) ; 覆盖率 %.1f%% ; 无信号日 %d / %d" %
      (picks_per_day.mean(), np.median(picks_per_day), 100*picks_per_day.sum()/max(1,pool_sizes.sum()), empty_days, len(pool_sizes)))
print("          年换手 ≈ %.0f 倍净值 (KSLOT=20, 持2日)" % (244/2))
print("-" * 118)
print("分年度 【NAV 收益 %】:")
hdr="  %-6s" % "年"; 
for lab,_,_ in SCEN: hdr += " %18s" % lab[:18]
print(hdr)
years=sorted({y for lab in res for y in res[lab]["nav_year"]})
for y in years:
    line="  %-6s" % y
    for lab,_,_ in SCEN: line += " %+18.2f" % res[lab]["nav_year"].get(y,float("nan"))
    print(line)
print("-" * 118)
print("分年度 【单笔净收益】 (S2 开盘价+0.2%滑价):")
print("  %-6s %7s %11s %11s %9s" % ("年","笔数","净均值%","净中位%","胜率%"))
for y,d_ in res["S2 开盘价+0.2%滑价"]["trade_year"].items():
    print("  %-6s %7d %+11.4f %+11.4f %9.2f" % (y, d_["n"], d_["mean"], d_["med"], d_["wr"]))
json.dump(res, open(S/"final_report.json","w",encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("\nsaved final_report.json")
