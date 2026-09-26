# -*- coding: utf-8 -*-
"""r3: ST confound test + capacity curve + cost ladder + composite key + 2x2x2 decomposition + timing gate."""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); uni=U["universe"]; T, N = len(cal), len(uni)
sym=[u["sym"] for u in uni]
names = json.loads((R/"data_full_names.json").read_text(encoding="utf-8"))
is_st_now = np.array([("ST" in (names.get(s,"") or "").upper()) or ("退" in (names.get(s,"") or "")) for s in sym], dtype=bool)
print("当前名含 ST/退: %d 只 (%.1f%%)" % (is_st_now.sum(), 100*is_st_now.mean()))
O = np.asarray(np.load(S/"wl_OPEN.npy", mmap_mode="r")); C = np.asarray(np.load(S/"wl_CLOSE.npy", mmap_mode="r"))
AMT20 = np.asarray(np.load(S/"wl_AMT20.npy", mmap_mode="r")); NV = np.asarray(np.load(S/"wl_NV.npy", mmap_mode="r"))
RET20 = np.asarray(np.load(S/"wl_RET20.npy", mmap_mode="r")); VOLBR = np.asarray(np.load(S/"wl2_VOLBR.npy", mmap_mode="r"))
GAPO = np.asarray(np.load(S/"wl2_GAPNEXT.npy", mmap_mode="r")); VALID = np.load(S/"wl_VALID.npy").astype(bool)
IDX = pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
BC = pd.to_numeric(IDX.set_index("date").reindex(cal)["close"], errors="coerce").to_numpy(float)
IM = pd.to_numeric(IDX.set_index("date").reindex(cal)["open"], errors="coerce").to_numpy(float)
def sh(a,k):
    b=np.full(a.shape,np.nan,dtype=np.float32); b[:-k]=a[k:]; return b
E1=sh(O,1); C2=sh(C,2); RT=C2/E1-1.0
RT[~(np.isfinite(C2)&(C2>0)&np.isfinite(E1)&(E1>0))]=np.nan
Cv=np.where(VALID, C, np.nan)
r1=np.full((T,N),np.nan,dtype=np.float32); r1[1:]=Cv[1:]/Cv[:-1]-1.0
ab=np.abs(r1)
print("computing 250d max |daily ret| (period-ST proxy) ...", flush=True)
MX250 = pd.DataFrame(ab).rolling(250, min_periods=60).max().to_numpy(dtype=np.float32)
STproxy = np.isfinite(MX250) & (MX250 <= 0.056)
print("  期内 ST 代理(250日最大绝对日收益<=5.6%%): %d 股日 (%.2f%% of valid)" % (int(STproxy.sum()), 100*STproxy.sum()/max(1,VALID.sum())), flush=True)
del r1, ab, MX250, Cv
MA20 = pd.Series(BC).rolling(20, min_periods=10).mean().to_numpy(); MA60 = pd.Series(BC).rolling(60, min_periods=30).mean().to_numpy()
def make_pool(excl_st=False, excl_stproxy=False, MINAMT=2e7):
    okb=np.zeros((T,N),bool); POOL={}
    stmask = np.zeros((T,N),bool)
    if excl_st_now_bool: stmask |= is_st_now[None,:]
    if excl_stproxy: stmask |= STproxy
    for t in range(60,T-3):
        okb[t]=(VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=MINAMT)&(~stmask[t]))
        g=GAPO[t]
        m=okb[t]&np.isfinite(g)&(g<=-0.01)&(g>=-0.03)&np.isfinite(RT[t])
        idx=np.nonzero(m)[0]
        if idx.size: POOL[t]=idx
    return okb, POOL
def tstat(x): return float(x.mean()/(x.std(ddof=1)/np.sqrt(x.size))) if x.size>1 and x.std(ddof=1)>0 else 0.0
def zs(x):
    x=np.asarray(x,float); mu=np.nanmean(x); sd=np.nanstd(x)
    return (x-mu)/sd if np.isfinite(sd) and sd>0 else np.zeros_like(x)
def rank_sel(POOL, key, K):
    o={}
    for t,idx in POOL.items():
        if key=="amt_lo": s=-AMT20[t][idx]
        elif key=="composite": s=zs(-np.log(np.where(AMT20[t][idx]>0,AMT20[t][idx],np.nan)))+zs(-np.log(np.where(VOLBR[t][idx]>0,VOLBR[t][idx],np.nan)))+zs(-RET20[t][idx])
        o[t]= idx if len(idx)<=K else idx[np.argsort(-np.where(np.isfinite(s),s,-1e30))][:K]
    return o
def ev_of(sig, POOL):
    a=[]; sdm=[]; pdm=[]
    for t,idx in sig.items():
        v=RT[t][idx]; v=v[np.isfinite(v)]
        if not v.size: continue
        pv=RT[t][POOL[t]]; pv=pv[np.isfinite(pv)]
        a.append(v); sdm.append(v.mean()*100); pdm.append(pv.mean()*100)
    a=np.concatenate(a)*100
    return dict(n=int(a.size), mean=round(float(a.mean()),4), med=round(float(np.median(a)),4), wr=round(float(100*(a>0).mean()),2),
                t_sig=round(tstat(np.array(sdm)),2), t_exc=round(tstat(np.array(sdm)-np.array(pdm)),2))
def sim(sig, KSLOT, cost_side=0.0010, gate=None):
    ts=min(sig); cash=1.0; pos={}; nav=np.full(T,np.nan); trades=[]; nav[ts]=1.0
    for t in range(ts+1,T):
        for _ in range(2):
            for j in [j for j,p in pos.items() if p["tgt"]<=t]:
                p=pos[j]; px=C[t,j]
                if np.isfinite(px) and px>0:
                    pos.pop(j); cash+=p["sh"]*px*(1-cost_side)
                    trades.append((str(cal[t])[:4],(px*(1-cost_side)/(p["px"]*(1+cost_side))-1)*100))
                else: p["tgt"]=t+1
        if gate is None or gate(t-1):
            for j in sig.get(t-1,[]):
                if len(pos)>=KSLOT: continue
                if j in pos: continue
                px=O[t,j]
                if not (np.isfinite(px) and px>0): continue
                navprev=nav[t-1] if np.isfinite(nav[t-1]) else 1.0
                alloc=min(navprev/KSLOT,cash)
                if alloc<=1e-12: break
                pos[j]=dict(en=t,tgt=t+2,sg=t-1,sh=alloc/(px*(1+cost_side)),px=px); cash-=alloc
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
    return dict(ann=round(ann*100,2), mdd=round(float((v/pk-1).min())*100,2), sharpe=round(float(dr.mean()/sd*np.sqrt(244)),2) if sd>0 else None,
        exc=round((ann-bann)*100,2), n=int(r.size), mean=round(float(r.mean()),3), med=round(float(np.median(r)),3),
        wr=round(100*float((r>0).mean()),1), negY=sum(1 for y in ys if np.mean([z[1] for z in trades if z[0]==y])<0), nY=len(ys),
        per_year={y: round(float(np.mean([z[1] for z in trades if z[0]==y])),3) for y in ys})
res={}
print("\n=== A. ST 混杂检验 (amt_lo, K=10, KSLOT=20, 20bp) ===")
for lab, eas, esp in (("原始", False, False), ("剔当前ST名", True, False), ("剔期内ST代理", False, True), ("两者都剔", True, True)):
    globals()["excl_st_now_bool"]=eas
    okb,POOL=make_pool(excl_st=eas, excl_stproxy=esp)
    sig=rank_sel(POOL,"amt_lo",10); e=ev_of(sig,POOL); m=sim(sig,20)
    res["ST_"+lab]=dict(ev=e,port=m,pool_days=len(POOL))
    print("  %-12s 池日=%4d 笔=%6d 毛均 %+8.4f%% 毛中 %+8.4f%% 毛胜 %6.2f%% t超额 %6.2f | 年化 %+7.2f%% MDD %7.2f%% 夏普 %5.2f" %
          (lab, len(POOL), e["n"], e["mean"], e["med"], e["wr"], e["t_exc"], m["ann"], m["mdd"], m["sharpe"] or 0), flush=True)
globals()["excl_st_now_bool"]=False
print("\n=== B. 容量曲线 (amt_lo, 2000万池, 20bp) ===")
okb,POOL=make_pool()
for K in (5,10,20,50,100):
    sig=rank_sel(POOL,"amt_lo",K); e=ev_of(sig,POOL); m=sim(sig,2*K)
    res["cap_K%d"%K]=dict(ev=e,port=m)
    print("  K=%-4d 笔=%6d 毛均 %+8.4f%% 毛胜 %6.2f%% | 年化 %+7.2f%% MDD %7.2f%% 夏普 %5.2f 超额 %+6.2fpp 负年 %d/%d" %
          (K, e["n"], e["mean"], e["wr"], m["ann"], m["mdd"], m["sharpe"] or 0, m["exc"], m["negY"], m["nY"]), flush=True)
print("\n=== C. 成本阶梯 (amt_lo K=10) ===")
sig=rank_sel(POOL,"amt_lo",10)
for nm,cs in (("0bp",0.0),("20bp",0.0010),("30bp",0.0015),("40bp",0.0020),("60bp",0.0030)):
    m=sim(sig,20,cost_side=cs); res["cost_"+nm]=m
    print("  %-5s 年化 %+7.2f%% MDD %7.2f%% 夏普 %5.2f 净均 %+7.4f%% 净中 %+7.4f%% 净胜 %5.2f%% 超额 %+6.2fpp" %
          (nm, m["ann"], m["mdd"], m["sharpe"] or 0, m["mean"], m["med"], m["wr"], m["exc"]), flush=True)
print("\n=== D. 复合打分 (-z lnAMT -z lnVOLBR -z RET20) vs 单键 ===")
for key in ("amt_lo","composite"):
    sig=rank_sel(POOL,key,10); e=ev_of(sig,POOL); m=sim(sig,20)
    res["cmp_"+key]=dict(ev=e,port=m)
    print("  %-10s 毛均 %+8.4f%% 毛中 %+8.4f%% 毛胜 %6.2f%% t超额 %6.2f | 年化 %+7.2f%% MDD %7.2f%% 夏普 %5.2f" %
          (key, e["mean"], e["med"], e["wr"], e["t_exc"], m["ann"], m["mdd"], m["sharpe"] or 0), flush=True)
print("\n=== E. 四格分解: 成交额高低 x 量比高低 (池内毛均值) ===")
for amt_hi in (False, True):
    for vol_hi in (False, True):
        a=[]
        for t,idx in POOL.items():
            am=AMT20[t][idx]; vb=VOLBR[t][idx]
            ma=np.nanmedian(am); mv=np.nanmedian(vb)
            m=(am>=ma) if amt_hi else (am<ma)
            m&= (vb>=mv) if vol_hi else (vb<mv)
            v=RT[t][idx][m]; v=v[np.isfinite(v)]
            if v.size: a.append(v)
        a=np.concatenate(a)*100
        print("  成交额%s x 量比%s : n=%7d 毛均 %+8.4f%% 毛中 %+8.4f%% 毛胜 %6.2f%%" %
              ("高" if amt_hi else "低","高" if vol_hi else "低", a.size, a.mean(), np.median(a), 100*(a>0).mean()))
print("\n=== F. 市场择时门 (amt_lo K=10, 20bp) ===")
for lab, gf in (("无门", None), ("HS300>MA20", lambda t: np.isfinite(MA20[t]) and BC[t]>MA20[t]),
                ("HS300>MA60", lambda t: np.isfinite(MA60[t]) and BC[t]>MA60[t]),
                ("HS300<MA60(反向)", lambda t: np.isfinite(MA60[t]) and BC[t]<MA60[t])):
    sig=rank_sel(POOL,"amt_lo",10); m=sim(sig,20,gate=gf); res["gate_"+lab]=m
    print("  %-16s 年化 %+7.2f%% MDD %7.2f%% 夏普 %5.2f 超额 %+6.2fpp 负年 %d/%d" % (lab, m["ann"], m["mdd"], m["sharpe"] or 0, m["exc"], m["negY"], m["nY"]), flush=True)
print("\n=== G. amt_lo 选中标的的 ADV 分布 -> 容量上限估算 ===")
adv=[]
for t,idx in rank_sel(POOL,"amt_lo",10).items(): adv.append(AMT20[t][idx])
adv=np.concatenate(adv)
for q in (10,25,50,75,90): print("    ADV p%-2d = %8.0f 万元" % (q, np.percentile(adv,q)/1e4))
print("   若单票不超过 ADV 的 1%%: 单票上限 = %.1f 万元; 20 只组合 -> 账户上限 ≈ %.0f 万元" %
      (np.median(adv)*0.01/1e4, np.median(adv)*0.01*20/1e4))
res["adv"]={"p10":float(np.percentile(adv,10)),"p25":float(np.percentile(adv,25)),"p50":float(np.median(adv)),
            "p75":float(np.percentile(adv,75)),"p90":float(np.percentile(adv,90))}
json.dump(res, open(S/"r3_opt.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved r3_opt.json")
