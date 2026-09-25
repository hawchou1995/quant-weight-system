# -*- coding: utf-8 -*-
"""Step7: reconcile event-study vs portfolio-trade mean (coverage by year, common-entry diff)."""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = R / "backtest/wechat_hotspot_leader_0925"
U = json.loads((OUT/"universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); uni = U["universe"]
inds = np.array([u["ind"] for u in uni], dtype=object)
T, N = len(cal), len(uni)
g = {k: np.load(S/("wl_"+k+".npy"), mmap_mode="r") for k in
     ("CLOSE","OPEN","VOL","AMT","RET20","AMT20","VOL5","VOL60","VMA20_prev","ATR20","HHV60_prev","NV","VALID","IR20","IV20","IAMT20","IAMT60")}
C = np.asarray(g["CLOSE"]); O = np.asarray(g["OPEN"]); V = np.asarray(g["VOL"]); VALID = g["VALID"].astype(bool)
ind_names = sorted(set(inds.tolist())); gidx = {x:k for k,x in enumerate(ind_names)}
gcol = np.array([gidx[x] for x in inds], dtype=np.int32); NV = g["NV"]
_cs = np.cumsum(((C > g["HHV60_prev"]) & np.isfinite(g["HHV60_prev"]) & VALID).astype(np.int32), axis=0)
BRK20prev = np.zeros((T,N), dtype=np.int32); _i = np.arange(21,T); BRK20prev[_i] = _cs[_i-1]-_cs[_i-21]
def pct_rank(x):
    o = np.isfinite(x); out = np.full(x.shape, np.nan)
    if o.sum() < 3: return out
    out[o] = (np.argsort(np.argsort(x[o]))+1)/o.sum(); return out
def zz(x, bm):
    out = np.full(N, np.nan)
    for gg in np.unique(gcol[bm]):
        m = bm & (gcol==gg)
        if m.sum() < 2: continue
        v = x[m]; mu, sd = np.nanmean(v), np.nanstd(v)
        if not np.isfinite(sd) or sd<=0: continue
        out[m] = (x[m]-mu)/sd
    return out
def build(P1=.20,P2=.30,Q=.80,M=1.5,MIN_AMT=2e7,KNEW=3,LISTED=250,MINPX=2.0,FIRSTBRK=False,LOWRET20=False):
    sig=[None]*T
    for t in range(60,T):
        ir,iv = g["IR20"][t], g["IV20"][t]; ia20,ia60 = g["IAMT20"][t], g["IAMT60"][t]
        okg = np.isfinite(ir)&np.isfinite(iv)&np.isfinite(ia60)&(ia60>0)
        if okg.sum()<5: continue
        r_ir=pct_rank(np.where(okg,ir,np.nan)); r_iv=pct_rank(np.where(okg,iv,np.nan))
        shrink = np.isfinite(ia20)&(ia20/np.where(ia60>0,ia60,np.nan)<Q)
        gate = np.where(okg,(r_ir<=P1)|((r_iv<=P2)&shrink),False)
        amt20,vma_p,hhv_p = g["AMT20"][t], g["VMA20_prev"][t], g["HHV60_prev"][t]
        elig = (VALID[t]&(NV[t]>=LISTED)&(C[t]>=MINPX)&np.isfinite(amt20)&(amt20>=MIN_AMT)&gate[gcol])
        if not elig.any(): continue
        cand = elig & (np.isfinite(hhv_p)&np.isfinite(vma_p)&(vma_p>0)&(C[t]>hhv_p)&(V[t]>M*vma_p))
        if FIRSTBRK: cand = cand & (BRK20prev[t]==0)
        if not cand.any(): continue
        share = g["AMT20"][t]/np.where(g["IAMT20"][t][gcol]>0, g["IAMT20"][t][gcol], np.nan)
        vr = g["VOL5"][t]/np.where(g["VOL60"][t]>0, g["VOL60"][t], np.nan)
        F = np.zeros(N)
        for x in (share, g["ATR20"][t], vr, g["RET20"][t]):
            z = zz(np.where(np.isfinite(x),x,np.nan), elig); F = F + np.where(np.isfinite(z),z,0.0)
        if LOWRET20:
            rm = g["RET20"][t]; low = np.zeros(N, dtype=bool)
            for gg in np.unique(gcol[cand]):
                m = cand&(gcol==gg)
                if m.sum()<2: low[m]=True; continue
                low[m] = rm[m] <= np.nanmedian(rm[m])
            cand = cand & low
            if not cand.any(): continue
        ci = np.nonzero(cand)[0]; sig[t] = ci[np.argsort(-F[ci])][:KNEW].tolist()
    return sig
def simulate(sig, H=10, KSLOT=5, cost_side=0.0):
    ts = next(t for t in range(T) if sig[t])
    cash=1.0; pos={}; nav=np.full(T,np.nan); trades=[]; nav[ts-1]=1.0
    pending = sig[ts-1] if sig[ts-1] else []
    for t in range(ts,T):
        for j in [j for j,p in pos.items() if p["exit"]<=t]:
            p=pos[j]; px=O[t,j]
            if np.isfinite(px) and px>0:
                pos.pop(j); cash += p["sh"]*px*(1-cost_side)
                trades.append(dict(sg=p["sg"], en=p["en"], ex=t, j=j,
                    ret=(px*(1-cost_side)/(p["px"]*(1+cost_side))-1)*100))
            else:
                p["exit"]=t+1
        for j in pending:
            if len(pos)>=KSLOT: break
            if j in pos: continue
            px=O[t,j]
            if not (np.isfinite(px) and px>0): continue
            navprev = nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            alloc = min(navprev/KSLOT, cash)
            if alloc<=1e-9: break
            pos[j]=dict(en=t, exit=t+H, sg=t-1, sh=alloc/(px*(1+cost_side)), px=px)
            cash-=alloc
        pending = sig[t] if sig[t] else []
        mv=0.0
        for j,p in pos.items():
            c=C[t,j]; mv += p["sh"]*(c if np.isfinite(c) and c>0 else p["px"])
        nav[t]=cash+mv
    return nav, trades
def evset(sig, H=10):
    out=[]
    for t in range(T):
        if not sig[t] or t+1+H>=T: continue
        o1=O[t+1]; o2=O[t+1+H]
        for j in sig[t]:
            if np.isfinite(o1[j]) and o1[j]>0 and np.isfinite(o2[j]) and o2[j]>0:
                out.append(dict(sg=t, j=j, ret=(o2[j]/o1[j]-1)*100, y=str(cal[t])[:4]))
    return pd.DataFrame(out)
REPORT={}
for tag, cfg in (("V4_base", dict(P1=.20,P2=.30,Q=.80,M=1.5,MIN_AMT=2e7,KNEW=3)),
                 ("V7_firstbrk_lowret20", dict(P1=.20,P2=.30,Q=.80,M=1.5,MIN_AMT=2e7,KNEW=3,FIRSTBRK=True,LOWRET20=True))):
    sig = build(**cfg); ev = evset(sig); nav, tr = simulate(sig, H=10, KSLOT=5, cost_side=0.0)
    trd = pd.DataFrame(tr); trd["y"] = [str(cal[x])[:4] for x in trd["sg"]]
    evk = ev.set_index(["sg","j"]); trk = trd.set_index(["sg","j"])
    tkey = set(trk.index.tolist()); intra = evk.index.isin(tkey)
    common = evk[intra]["ret"]; portc = trk.loc[common.index]["ret"]
    print("\n===== %s =====" % tag)
    print("event-study obs=%d mean %+.4f%%  |  portfolio trades=%d mean %+.4f%%  coverage %.1f%%" %
          (len(ev), ev["ret"].mean(), len(trd), trd["ret"].mean(), 100.0*len(trd)/max(1,len(ev))))
    print("common n=%d  max|ev-port|=%.6f pp  mean(ev|common) %+.4f%%  mean(port|common) %+.4f%%" %
          (len(common), float(np.abs(common.to_numpy()-portc.to_numpy()).max()) if len(common) else 0.0,
           common.mean(), portc.mean()))
    miss = evk[~intra]
    print("NOT traded: n=%d mean %+.4f%%   | traded-subset mean %+.4f%%" % (len(miss), miss["ret"].mean(), evk[intra]["ret"].mean()))
    evf = ev.groupby("y")["ret"].agg(["size","mean"]).rename(columns={"size":"n_full","mean":"m_full"})
    evt = evk[intra].groupby("y")["ret"].agg(["size","mean"]).rename(columns={"size":"n_trd","mean":"m_trd"})
    print(evf.join(evt, how="outer").round(3).to_string())
    REPORT[tag]=dict(ev_n=int(len(ev)), ev_mean=round(float(ev["ret"].mean()),4), tr_n=int(len(trd)),
        tr_mean=round(float(trd["ret"].mean()),4),
        maxdiff_common=round(float(np.abs(common.to_numpy()-portc.to_numpy()).max()),6) if len(common) else None,
        miss_mean=round(float(miss["ret"].mean()),4), miss_n=int(len(miss)))
json.dump(REPORT, open(S/"w7_reconcile.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved w7_reconcile.json")
