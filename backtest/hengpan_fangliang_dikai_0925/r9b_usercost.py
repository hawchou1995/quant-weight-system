# -*- coding: utf-8 -*-
"""r9b (FIXED): user real cost (万0.86 -> 6.92bp rt) + UNBOUNDED low-open pool (what a -1% limit order actually fills)."""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); T, N = len(cal), len(U["universe"])
O = np.asarray(np.load(S/"wl_OPEN.npy", mmap_mode="r")); C = np.asarray(np.load(S/"wl_CLOSE.npy", mmap_mode="r"))
Hh = np.asarray(np.load(S/"wl_HIGH.npy", mmap_mode="r")); Ll = np.asarray(np.load(S/"wl_LOW.npy", mmap_mode="r"))
AMT20 = np.asarray(np.load(S/"wl_AMT20.npy", mmap_mode="r")); NV = np.asarray(np.load(S/"wl_NV.npy", mmap_mode="r"))
RET20 = np.asarray(np.load(S/"wl_RET20.npy", mmap_mode="r")); VOLBR = np.asarray(np.load(S/"wl2_VOLBR.npy", mmap_mode="r"))
GAPO = np.asarray(np.load(S/"wl2_GAPNEXT.npy", mmap_mode="r")); VALID = np.load(S/"wl_VALID.npy").astype(bool)
def sh(a,k):
    b=np.full(a.shape,np.nan,dtype=np.float32); b[:-k]=a[k:]; return b
O1=sh(O,1); C2=sh(C,2)
FULL=C2/O1-1.0
FULL[~(np.isfinite(C2)&(C2>0)&np.isfinite(O1)&(O1>0))]=np.nan
print("=== 0. 真实费率 (往返 bp) ===")
def rt_bp(comm_wan): return 2*float(comm_wan) + 5.0 + 0.2
for w in (0.86,1.0,1.5,2.5,3.0):
    print("  佣金万%-4.2f: 佣金 %.2f + 印花税 5.00 + 过户费 0.20 = 往返 %.2f bp" % (w, 2*w, rt_bp(w)))
UC = rt_bp(0.86); CS = UC/2/1e4
print("  >>> 用户 万0.86 -> 往返 %.2f bp -> cost_side=%.6f" % (UC, CS))
def build_pool(maxdepth):
    okb=np.zeros((T,N),bool); P={}
    for t in range(60,T-4):
        okb[t]=(VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=2e7))
    for t in range(60,T-3):
        g=GAPO[t]
        m=okb[t]&np.isfinite(g)&(g<=-0.01)&np.isfinite(FULL[t])
        if maxdepth is not None: m=m&(g>=maxdepth)
        idx=np.nonzero(m)[0]
        if idx.size: P[t]=idx
    return P
def zs(x):
    x=np.asarray(x,float); mu=np.nanmean(x); sd=np.nanstd(x)
    return (x-mu)/sd if np.isfinite(sd) and sd>0 else np.zeros_like(x)
def sel(P,K=10):
    o={}
    for t,idx in P.items():
        sc=zs(-np.log(np.where(AMT20[t][idx]>0,AMT20[t][idx],np.nan)))+zs(-np.log(np.where(VOLBR[t][idx]>0,VOLBR[t][idx],np.nan)))+zs(-RET20[t][idx])
        o[t]= idx if len(idx)<=K else idx[np.argsort(-np.where(np.isfinite(sc),sc,-1e30))][:K]
    return o
IDX = pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
BC = pd.to_numeric(IDX.set_index("date").reindex(cal)["close"], errors="coerce").to_numpy(float)
def sim(sig, entry_arr, cost_side, K=10):
    ts=min(sig); cash=1.0; pos={}; nav=np.full(T,np.nan); trades=[]; nav[ts]=1.0
    for t in range(ts+1,T):
        for _ in range(2):
            for j in [j for j,p in pos.items() if p["tgt"]<=t]:
                p=pos[j]; px=C[t,j]
                if np.isfinite(px) and px>0:
                    pos.pop(j); cash+=p["sh"]*px*(1-cost_side)
                    trades.append((str(cal[t])[:4],(px*(1-cost_side)/(p["px"]*(1+cost_side))-1)*100))
                else: p["tgt"]=t+1
        for j in sig.get(t-1,[]):
            if len(pos)>=2*K: continue
            if j in pos: continue
            px=entry_arr[t,j]
            if not (np.isfinite(px) and px>0): continue
            navprev=nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            alloc=min(navprev/(2*K),cash)
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
    return dict(ann=round(float(ann*100),2), mdd=round(float((v/pk-1).min())*100,2),
        sharpe=round(float(dr.mean()/sd*np.sqrt(244)),2) if sd>0 else None, exc=round(float(ann-bann)*100,2),
        n=int(r.size), mean=round(float(r.mean()),4), med=round(float(np.median(r)),4), wr=round(float(100*(r>0).mean()),2),
        negY=int(sum(1 for y in ys if np.mean([z[1] for z in trades if z[0]==y])<0)), nY=int(len(ys)),
        per_year={y: round(float(np.mean([z[1] for z in trades if z[0]==y])),3) for y in ys})
P3=build_pool(-0.03); PUB=build_pool(None)
print("\n=== 1. 低开池范围对比 ===")
for lab,P in (("[-3%,-1%] (原口径)",P3),("<=-1% 无下限 (挂-1%限价单真实成交范围)",PUB)):
    n=sum(len(v) for v in P.values()); print("  %-42s 信号 %8d 日 %4d 每日中位 %3d" % (lab, n, len(P), int(np.median([len(v) for v in P.values()]))))
gp=[]
for t,idx in PUB.items(): gp.append(GAPO[t][idx])
gp=np.concatenate(gp)*100
print("  无下限池的跳空分布:")
for lo,hi,lab in ((-99,-8,"<=-8%"),(-8,-5,"-8~-5%"),(-5,-3,"-5~-3%"),(-3,-2,"-3~-2%"),(-2,-1.5,"-2~-1.5%"),(-1.5,-1,"-1.5~-1%")):
    m=(gp>lo)&(gp<=hi); print("    %-9s n=%8d 占比 %6.3f%%" % (lab, int(m.sum()), 100*m.sum()/gp.size))
print("\n=== 2. 用户费率 (%.2fbp 往返) x 滑价阶梯, 两种池 (composite K=10, KSLOT=20) ===" % UC)
VWAP=(O+Hh+Ll+C)/4.0
res={}
for plab,P in (("[-3,-1]",P3),("<=-1 unbounded",PUB)):
    sg=sel(P,10)
    print("  --- 池 %s ---" % plab)
    for lab, arr in (("0 (开盘价成交)",O),("+0.1%",O*1.001),("+0.2%",O*1.002),("+0.3%",O*1.003),("+0.5%",O*1.005),("+1.0%",O*1.01),("当日均价",VWAP),("错失开盘->收盘",C)):
        m=sim(sg, arr, CS)
        g=[m["mean"]>0, m["wr"]>=46, m["med"]>0, m["exc"]>0]
        res["%s|%s"%(plab,lab)]=m|{"gates":"".join("1" if x else "0" for x in g),"npass":int(sum(g))}
        print("    %-18s 年化 %+9.2f%% MDD %8.2f%% 夏普 %6.2f 超额 %+8.2fpp 净均 %+8.4f%% 净中 %+8.4f%% 净胜 %6.2f%% 负年 %d/%d 四闸 %s" %
              (lab, m["ann"], m["mdd"], m["sharpe"] or 0, m["exc"], m["mean"], m["med"], m["wr"], m["negY"], m["nY"], res["%s|%s"%(plab,lab)]["gates"]), flush=True)
print("\n=== 3. 摩擦预算 (无下限池, 0 滑价为基准) ===")
sg=sel(PUB,10)
for sl in (0.0,0.002,0.004,0.006,0.008):
    m=sim(sg, O*(1+sl), CS)
    print("  滑价 %.1f%% -> 总摩擦 %5.1f bp -> 年化 %+8.2f%% 净均 %+7.4f%%" % (sl*100, UC+sl*10000, m["ann"], m["mean"]), flush=True)
print("\n=== 4. 组合逐年 (无下限池, 理想开盘价, 用户费率) ===")
m=sim(sg, O, CS); print("  " + " ".join("%s%+.2f" % (y,v) for y,v in m["per_year"].items()))
print("\n=== 5. 容量: 竞价量口径敏感性 (ADV p50=2442万) ===")
for share in (0.02,0.03,0.05):
    for take in (0.1,0.2,0.3):
        cap=2442e4*share*take/1e4
        print("  竞价量占全天 %.0f%% x 吃下 %.0f%% -> 单票 %6.1f万 -> 20只 账户上限 %6.0f万" % (share*100,take*100,cap,cap*20))
json.dump({"_user_cost_rt_bp": round(float(UC),2),
           "_note": "成本 = 万0.86 佣金双边(1.72bp) + 印花税 5bp(卖出) + 过户费 0.1bp双边(0.2bp); 滑价=相对开盘价的加价; 池<=-1%无下限=挂-1%限价单的真实成交范围",
           "results": {k: {kk: vv for kk, vv in v.items()} for k,v in res.items()}},
          open(S/"r9b_usercost.json","w",encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("\nsaved r9b_usercost.json")
