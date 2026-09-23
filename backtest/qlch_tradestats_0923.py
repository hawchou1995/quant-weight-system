# -*- coding: utf-8 -*-
"""R-qlch-tradestats-0923 · 逐笔统计 + 夏普可信度核查（全池生产口径 X4）
只读；不改账本/参数。
"""
import importlib.util, json, os, sys, time, io
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
T0=time.time(); BK="backtest"
os.environ["QLCH_VARIANT"]="B4"; os.environ["QLCH_MAXPOS"]="3"; os.environ["QLCH_GATE"]="20"; os.environ["QLCH_MAINBOARD"]="0"
sp=importlib.util.spec_from_file_location("g", BK+"/qlch_grid_bt_0923.py"); g=importlib.util.module_from_spec(sp); sp.loader.exec_module(g)
sp2=importlib.util.spec_from_file_location("eng", BK+"/qlch_paper_20260921.py"); eng=importlib.util.module_from_spec(sp2); sp2.loader.exec_module(eng)
P=eng.load_all(); S=eng.build_signals(P); cal,T=S["cal"],S["close"].shape[0]
ents=g.entry_cases(S); d=ents["A"]; e,j,px=d["e"],d["j"],d["px"]
Oa,Ha,La,Ca=g.case_path(e,j,S["open"],S["high"],S["low"],S["close"],T,39)
kf,expx,exrs,hit=g.resolve_exit(px,Oa,Ha,La,Ca,0.25,-0.30)
use,x,opx,hold,reason=g.exit_plan(e,px,kf,expx,exrs,hit,Ca,40,T)
gross=opx[use]/px[use]-1.0
print("[%4.0fs] 全池 A 族事件 %d（可用 %d）| X4 单笔均值(20bp) %+.3f%% | 中位 %+.3f%%"
      % (time.time()-T0,e.size,use.sum(),(gross-0.002).mean()*100,np.median(gross-0.002)*100),flush=True)
i_first=int(np.concatenate([ents[k]["e"] for k in "ABC"]).min()); SL={"full":(i_first,T-1)}
# ---- 逐笔（事件级，含亏损；等权）----
for ck,cv in (("P20",0.0020),("S60",0.0060)):
    r=gross-cv; w=r[r>0]; l=r[r<=0]
    print("  事件级 %s：n=%d 胜率%.1f%% | 均值%+.3f%% 中位%+.3f%% | 盈单均值%+.3f%%(n=%d) 亏单均值%+.3f%%(n=%d) | 均值/中位差 %+.3fpp"
          % (ck,r.size,(r>0).mean()*100,r.mean()*100,np.median(r)*100,w.mean()*100,w.size,l.mean()*100,l.size,(r.mean()-np.median(r))*100),flush=True)
    print("           金额口径（每 1.0 元本金 · 单笔按净值×1/3 配置）：均值 %.6f 元 | 盈单 %.6f | 亏单 %.6f  ← 等权，未按仓位加权"
          % (r.mean()/3, w.mean()/3, l.mean()/3),flush=True)
# ---- 组合级（逐种子 + 种子平均）----
res={"event":{"n":int(use.sum())},"per_seed":[],"pooled":{},"sharpe":{}}
allsd=[]
for sd in g.SEEDS:
    nav,inv,te,tx,tr,th,tv=g.simulate(e[use],x[use],gross-0.0020,hold[use],T,[sd],g.K)
    met=g.metrics_all(nav,inv,te,tr,th,tv,SL,1)["full"]
    alloc=tv/2.0; amt=alloc*tr
    st={"seed":int(sd),"n":int(tr.size),"mean_net_pct":round(float(tr.mean())*100,4),
        "wr_pct":round(float((tr>0).mean())*100,2),
        "avg_win_pct":round(float(tr[tr>0].mean())*100,4) if (tr>0).any() else None,
        "avg_loss_pct":round(float(tr[tr<=0].mean())*100,4) if (tr<=0).any() else None,
        "amt_mean":round(float(amt.mean()),6),"amt_win":round(float(amt[tr>0].mean()),6) if (tr>0).any() else None,
        "amt_loss":round(float(amt[tr<=0].mean()),6) if (tr<=0).any() else None,
        "amt_weighted_ret_pct":round(float(amt.sum()/alloc.sum())*100,4),
        "cagr":met["cagr"],"sharpe":met["sharpe"],"mdd":met["mdd"],"turn":met["turn"],"inv":met["inv"]}
    res["per_seed"].append(st); allsd.append((nav,tr,alloc))
    print("  种子 %d：笔%4d 均值%+.3f%% 胜率%.1f%% | 每笔金额均值 %.6f（盈 %.6f / 亏 %.6f）| 金额加权净收益%+.3f%% | 夏普 %6.3f 年化%+7.2f%% 回撤%+7.2f%%"
          % (sd,st["n"],st["mean_net_pct"],st["wr_pct"],st["amt_mean"],st["amt_win"],st["amt_loss"],st["amt_weighted_ret_pct"],st["sharpe"],st["cagr"],st["mdd"]),flush=True)
navs=np.mean([a[0] for a in allsd],axis=0)
trp=np.concatenate([a[1] for a in allsd]); allocp=np.concatenate([a[2] for a in allsd])
rr=np.diff(navs)/navs[:-1]
def sharpe(r): return float(r.mean()/r.std(ddof=1)*np.sqrt(244.0))
sh_seed=[s["sharpe"] for s in res["per_seed"]]
res["sharpe"]={"per_seed": sh_seed, "per_seed_mean":round(float(np.mean(sh_seed)),4), "per_seed_sd":round(float(np.std(sh_seed,ddof=1)),4),
               "seed_avg_nav_sharpe":round(sharpe(rr),4), "inflation_pct":round((sharpe(rr)/np.mean(sh_seed)-1)*100,2)}
print("\n[夏普核查] 逐种子 %s → 均值 %.3f (sd %.3f) | **5 种子平均净值口径 %.3f** → 抬高 %+.1f%%"
      % (sh_seed,res["sharpe"]["per_seed_mean"],res["sharpe"]["per_seed_sd"],res["sharpe"]["seed_avg_nav_sharpe"],res["sharpe"]["inflation_pct"]),flush=True)
def boot_sharpe(r, nb=2000, L=21, seed=20260923, chunk=200):
    n=r.size; nbk=int(np.ceil(n/L)); hi=max(n-L,0); rng=np.random.default_rng(seed); off=np.arange(L)
    out=np.empty(nb); got=0
    while got<nb:
        m=min(chunk,nb-got); st=rng.integers(0,hi+1,size=(m,nbk))
        idx=(st[:,:,None]+off[None,None,:]).reshape(m,nbk*L)[:, :n]
        R=r[idx]; sd_=R.std(axis=1,ddof=1); ok=sd_>0; d=np.full(m,np.nan)
        d[ok]=R[ok].mean(axis=1)/sd_[ok]*np.sqrt(244.0); out[got:got+m]=d; got+=m
    v=out[np.isfinite(out)]
    return {"lo":round(float(np.percentile(v,2.5)),3),"hi":round(float(np.percentile(v,97.5)),3),"sd_of_sharpe":round(float(v.std(ddof=1)),3)}
b=boot_sharpe(rr); res["sharpe"]["block_boot_ci"]=b
print("[夏普核查] 按日块 bootstrap（L=21，2000 次）：95%% CI = [%.3f, %.3f]，SE(夏普) ≈ %.3f" % (b["lo"],b["hi"],b["sd_of_sharpe"]),flush=True)
nav60,inv60,te6,tx6,tr6,th6,tv6=g.simulate(e[use],x[use],gross-0.0060,hold[use],T,g.SEEDS,g.K)
rr60=np.diff(nav60)/nav60[:-1]; met60=g.metrics_all(nav60,inv60,te6,tr6,th6,tv6,SL,len(g.SEEDS))["full"]
res["sharpe"]["at_60bp"]={"sharpe":met60["sharpe"],"cagr":met60["cagr"],"mdd":met60["mdd"],"turn":met60["turn"],"inv":met60["inv"]}
print("[夏普核查] 60bp 档（种子平均口径）：夏普 %.3f 年化 %+.2f%% 回撤 %+.2f%%" % (met60["sharpe"],met60["cagr"],met60["mdd"]),flush=True)
res["pooled"]={"n":int(trp.size),"mean_net_pct":round(float(trp.mean())*100,4),"amt_mean":round(float(allocp.mean()),6),
               "amt_weighted_ret_pct":round(float(allocp.sum()*0+ (np.concatenate([a[1] for a in allsd])*np.concatenate([a[2] for a in allsd])).sum()/allocp.sum())*100,4)}
print("[组合级汇总] 5 种子合并成交 %d 笔 | 单笔净收益均值 %+.4f%% | 每笔金额均值 %.6f（按净值×1/3 口径）| 金额加权净收益 %+.4f%%"
      % (res["pooled"]["n"],res["pooled"]["mean_net_pct"],res["pooled"]["amt_mean"],res["pooled"]["amt_weighted_ret_pct"]),flush=True)
json.dump(res, open("backtest/qlch_tradestats_0923.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("已落盘 backtest/qlch_tradestats_0923.json | 耗时 %.0fs" % (time.time()-T0))