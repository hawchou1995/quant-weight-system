# -*- coding: utf-8 -*-
"""stops_930.py — 修正持仓期 + Q1(9:30后买入) + Q2(止损/止盈/移动止盈)
T+1 制度: 买入日不可卖 -> 止损最早 T+2 生效
"""
import json, pathlib, numpy as np, pandas as pd, time, statistics
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
exec(open(S/"real_filters.py", encoding="utf-8").read().split("def sim(")[0])
MH = np.asarray(np.load(S/"wl_HIGH.npy", mmap_mode="r")); ML = np.asarray(np.load(S/"wl_LOW.npy", mmap_mode="r"))
def H_(fr,t,j): return float(MH[t,j]) if fr=="M" else float(DH[t,j])
def L_(fr,t,j): return float(ML[t,j]) if fr=="M" else float(DL[t,j])
def O_(fr,t,j): return float(MO[t,j]) if fr=="M" else float(DO[t,j])
def C_(fr,t,j): return float(MC[t,j]) if fr=="M" else float(DC[t,j])
K,KSLOT,FILL=10,4,-0.015
PICKS={}
for t in range(1,T):
    if (t-1) in POOL: PICKS[t]=[p for p in pick(t-1, POOL[t-1], K) if p[2]<=FILL]
print("picks: %d 日 / %d 笔" % (len(PICKS), sum(len(v) for v in PICKS.values())))
def sim(prem=0.0, stop=None, tp=None, trail=None, max_hold=1, cost=0.000346):
    ts=min(POOL); cash=1.0; pos={}; nav=np.full(T,np.nan); nav[ts-1]=1.0
    rets=[]; hold=[]; nreg={"stop":0,"tp":0,"trail":0,"eod":0}
    for t in range(ts,T):
        for key in [k for k,p in pos.items() if p["last"]<=t]:
            p=pos[key]; fr,j=p["fr"],p["j"]; ex=None; why="eod"
            for d in range(max(t,p["en"]+1), min(p["en"]+max_hold, T-1)+1):
                o,h,l = O_(fr,d,j), H_(fr,d,j), L_(fr,d,j)
                if not (np.isfinite(h) and np.isfinite(l) and np.isfinite(o) and h>0 and l>0): continue
                p["maxh"]=max(p["maxh"], h)
                if stop is not None:
                    lv=p["px"]*(1-stop)
                    if o<=lv: ex,why=o,"stop"; break
                    if l<=lv: ex,why=lv,"stop"; break
                if tp is not None:
                    lv=p["px"]*(1+tp)
                    if o>=lv: ex,why=o,"tp"; break
                    if h>=lv: ex,why=lv,"tp"; break
                if trail is not None:
                    lv=p["maxh"]*(1-trail)
                    if o<=lv: ex,why=o,"trail"; break
                    if l<=lv: ex,why=lv,"trail"; break
            cd=min(p["en"]+max_hold, T-1)
            if ex is None:
                ex=C_(fr,cd,j)
                if not (np.isfinite(ex) and ex>0):
                    for k2 in range(cd+1,min(cd+6,T)):
                        if np.isfinite(C_(fr,k2,j)) and C_(fr,k2,j)>0: ex=C_(fr,k2,j); break
                    else: ex=0.0
            pos.pop(key); cash+=p["sh"]*ex*(1-cost)
            rets.append((str(cal[cd])[:4], (ex*(1-cost)/(p["px"]*(1+cost))-1)*100)); hold.append(cd-p["en"]); nreg[why]+=1
        for fr,j,gapv,o1v,c2v in PICKS.get(t,[]):
            if len(pos)>=KSLOT: continue
            key=(fr,j)
            if key in pos: continue
            px=o1v*(1+prem)
            if not (np.isfinite(px) and px>0): continue
            navprev=nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            alloc=min(navprev/KSLOT,cash)
            if alloc<=1e-12: break
            pos[key]=dict(en=t,last=t+max_hold,sh=alloc/(px*(1+cost)),px=px,fr=fr,j=j,maxh=o1v); cash-=alloc
        mv=0.0
        for key,p in pos.items():
            c=C_(p["fr"],t,p["j"]); mv+=p["sh"]*(c if np.isfinite(c) and c>0 else p["px"])
        nav[t]=cash+mv
    IDX=pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
    BC=pd.to_numeric(IDX.set_index("date").reindex(cal)["close"],errors="coerce").to_numpy(float)
    bnav=np.full(T,np.nan); bnav[ts-1]=1.0
    for t in range(ts,T): bnav[t]=BC[t]/BC[ts-1]
    ok=np.isfinite(nav); v=nav[ok]; b=bnav[ok]; nd=len(v)-1
    ann=(v[-1]/v[0])**(244/nd)-1; pk=np.maximum.accumulate(v); mdd=float((v/pk-1).min())
    dr=v[1:]/v[:-1]-1; sd=dr.std(ddof=1); bann=(b[-1]/b[0])**(244/nd)-1
    r=np.array([x[1] for x in rets],float); ys={}
    for y,rr in rets: ys.setdefault(y,[]).append(rr)
    return dict(ann=round(ann*100,2), mdd=round(mdd*100,2), sharpe=round(float(dr.mean()/sd*np.sqrt(244)),2) if sd>0 else None,
        exc=round((ann-bann)*100,2), n=int(r.size), mean=round(float(r.mean()),4), med=round(float(np.median(r)),4),
        wr=round(float(100*(r>0).mean()),2), avg_hold=round(float(np.mean(hold)),2) if hold else None,
        negY=int(sum(1 for y,vv in ys.items() if np.mean(vv)<0)), nY=int(len(ys)),
        stop_pct=round(100*nreg["stop"]/max(1,len(rets)),1), tp_pct=round(100*nreg["tp"]/max(1,len(rets)),1),
        trail_pct=round(100*nreg["trail"]/max(1,len(rets)),1))
print("\n" + "="*118)
print("基线: K=10 挂单 / 只成交低开>=1.5% / KSLOT=4 | 持有期已修正: T+1开盘 -> T+2收盘 | 成本6.92bp")
print("="*118)
res={}
print("\n【Q1】9:30 后买入 (=入场价相对开盘价加价)，无止损止盈")
print("  %-24s %9s %8s %7s %8s %8s %7s %7s %4s" % ("入场价","年化","MDD","夏普","单笔净均","净中位","净胜率","笔数","负年"))
for lab,p_ in (("开盘价(基准)",0.0),("开盘+0.1%",0.001),("开盘+0.2%",0.002),("开盘+0.3%",0.003),("开盘+0.5%",0.005),("开盘+1.0%",0.01)):
    r=sim(prem=p_); res["prem_"+lab]=r
    print("  %-24s %+9.2f%% %+8.2f%% %7.2f %+8.4f %+8.4f %7.2f %7d %2d/%d" %
          (lab, r["ann"], r["mdd"], r["sharpe"] or 0, r["mean"], r["med"], r["wr"], r["n"], r["negY"], r["nY"]), flush=True)
exc_h=[]; exc_l=[]; oeq=l_=0
for t,v in PICKS.items():
    for fr,j,gapv,o1v,c2v in v:
        h,l,o = H_(fr,t,j), L_(fr,t,j), O_(fr,t,j)
        if not (np.isfinite(h) and np.isfinite(l) and o>0): continue
        exc_h.append((h-o)/o*100); exc_l.append((o-l)/o*100)
        oeq += int(l >= o*0.9999); l_ += 1
print("  [买入日盘中偏移] 开盘后最大有利偏移 均值%.2f%% 中位%.2f%% | 最大不利偏移 均值%.2f%% 中位%.2f%% | 开盘即当日最低 %.1f%% (n=%d)" %
      (statistics.mean(exc_h), statistics.median(exc_h), statistics.mean(exc_l), statistics.median(exc_l), 100*oeq/l_, l_))
print("\n【Q2】止损 / 止盈 / 移动止盈 (持有期固定 T+1开盘->T+2收盘, max_hold=1)")
print("  %-30s %9s %8s %7s %8s %8s %7s %7s %7s %6s %6s" % ("出场规则","年化","MDD","夏普","单笔净均","净中位","净胜率","笔数","持有天","止损%","止盈%"))
cfg=[("无止损止盈(基准)",dict()),
     ("止损 -2%",dict(stop=0.02)),("止损 -3%",dict(stop=0.03)),("止损 -5%",dict(stop=0.05)),
     ("止损 -7%",dict(stop=0.07)),("止损 -10%",dict(stop=0.10)),
     ("止盈 +2%",dict(tp=0.02)),("止盈 +3%",dict(tp=0.03)),("止盈 +5%",dict(tp=0.05)),
     ("止盈 +7%",dict(tp=0.07)),("止盈 +10%",dict(tp=0.10)),
     ("移动止盈 1%",dict(trail=0.01)),("移动止盈 2%",dict(trail=0.02)),("移动止盈 3%",dict(trail=0.03)),
     ("止损-3% + 止盈+3%",dict(stop=0.03,tp=0.03)),("止损-5% + 止盈+5%",dict(stop=0.05,tp=0.05)),
     ("止损-5% + 移动2%",dict(stop=0.05,trail=0.02))]
for lab,kw in cfg:
    r=sim(**kw); res["h1_"+lab]=r
    print("  %-30s %+9.2f%% %+8.2f%% %7.2f %+8.4f %+8.4f %7.2f %7d %7.2f %6.1f %6.1f" %
          (lab, r["ann"], r["mdd"], r["sharpe"] or 0, r["mean"], r["med"], r["wr"], r["n"], r["avg_hold"] or 0, r["stop_pct"], r["tp_pct"]), flush=True)
print("\n【Q2b】拉长持有期 (不止损就多拿几天) x 止损")
print("  %-30s %9s %8s %7s %8s %8s %7s %7s %7s %4s" % ("出场规则","年化","MDD","夏普","单笔净均","净中位","净胜率","笔数","持有天","负年"))
for mh in (2,4,9):
    for lab,kw in (("纯持有%d日"%(mh+1),dict()),("持有%d日+止损-5%%"%(mh+1),dict(stop=0.05)),
                   ("持有%d日+止盈+5%%"%(mh+1),dict(tp=0.05)),("持有%d日+移动2%%"%(mh+1),dict(trail=0.02))):
        r=sim(max_hold=mh, **kw); res["h%d_%s"%(mh,lab)]=r
        print("  %-30s %+9.2f%% %+8.2f%% %7.2f %+8.4f %+8.4f %7.2f %7d %7.2f %2d/%d" %
              (lab, r["ann"], r["mdd"], r["sharpe"] or 0, r["mean"], r["med"], r["wr"], r["n"], r["avg_hold"] or 0, r["negY"], r["nY"]), flush=True)
json.dump(res, open(S/"stops930.json","w",encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("\nsaved stops930.json")

