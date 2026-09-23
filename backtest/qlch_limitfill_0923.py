# -*- coding: utf-8 -*-
"""R-qlch-limitfill-0923 · 涨跌停可成交性筛除（夏普虚高源 #1 核验）
全池 X4 生产口径。口径：
  涨跌停价 = round(前收 × (1 ± w), 2)；w = 10% / 20%（688/689 全程 20%；300/301 自 2020-08-24 起 20%）
  不可成交判定：
    ① 止损跳空（按 open 卖）：open ≤ 跌停价 → 开盘即跌停/一字 → **不可卖**
    ② 到期平仓（按 close 卖）：close ≤ 跌停价 → 收盘封跌停 → **不可卖**
    ③ 止损触发（按 SL 卖）/ 止盈类（按 TP 或 open 卖）：可成交（下方有量/上方有承接）
  处置（两口径）：
    B（主口径，贴近现实）：不可成交 → 出场顺延到首个「open > 当日跌停价」的交易日，按该日 open 成交（最多顺延 5 日；仍不可则剔除）
    A（上界，保守）：直接把不可成交事件剔除
"""
import importlib.util, json, os, sys, time, io
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
T0=time.time(); BK="backtest"
os.environ["QLCH_VARIANT"]="B4"; os.environ["QLCH_MAXPOS"]="3"; os.environ["QLCH_GATE"]="20"; os.environ["QLCH_MAINBOARD"]="0"
sp=importlib.util.spec_from_file_location("g", BK+"/qlch_grid_bt_0923.py"); g=importlib.util.module_from_spec(sp); sp.loader.exec_module(g)
sp2=importlib.util.spec_from_file_location("eng", BK+"/qlch_paper_20260921.py"); eng=importlib.util.module_from_spec(sp2); sp2.loader.exec_module(eng)
P=eng.load_all(); S=eng.build_signals(P); cal,T=S["cal"],S["close"].shape[0]
O,H,L,C=S["open"],S["high"],S["low"],S["close"]
codes=S.get("codes") or getattr(eng,"CODES",None) or P.get("codes")
assert codes is not None and len(codes)==C.shape[1], ("codes 不可得", None if codes is None else len(codes))
ents=g.entry_cases(S); d=ents["A"]; e,j,px=d["e"],d["j"],d["px"]
Oa,Ha,La,Ca=g.case_path(e,j,O,H,L,C,T,39)
kf,expx,exrs,hit=g.resolve_exit(px,Oa,Ha,La,Ca,0.25,-0.30)
use,x,opx,hold,reason=g.exit_plan(e,px,kf,expx,exrs,hit,Ca,40,T)
eu, xu, ru = e[use], x[use], reason[use]; ju = j[use]
def limw(code, d1):
    c=str(code).lower()
    if c[2:5].startswith(("688","689")): return 0.20
    if c[2:5].startswith(("300","301")): return 0.20 if d1 >= "2020-08-24" else 0.10
    return 0.10
def ld(day_idx, col):
    if day_idx <= 0: return np.nan
    pc = C[day_idx-1, col]
    if not np.isfinite(pc) or pc <= 0: return np.nan
    return round(pc*(1.0-limw(codes[col], cal[day_idx])), 2)
bad_fill = np.zeros(xu.size, bool); newday = xu.copy().astype(int); delayed = 0; dropped = 0
for i in range(xu.size):
    dphi = xu[i]; col = ju[i]; rsn = int(ru[i]); fill = opx[use][i]
    if rsn == 0:   # 止损跳空：按 open 卖
        ldn = ld(dphi, col)
        if np.isfinite(ldn) and fill <= ldn + 1e-9: bad_fill[i] = True
    elif rsn == 4: # 到期平仓：按 close 卖
        ldn = ld(dphi, col)
        if np.isfinite(ldn) and C[dphi, col] <= ldn + 1e-9: bad_fill[i] = True
if bad_fill.sum():
    for i in np.where(bad_fill)[0]:
        col=ju[i]; d0=xu[i]; best=None
        for k in range(1,6):
            dd=d0+k
            if dd>=T: break
            ldn=ld(dd,col)
            if np.isfinite(O[dd,col]) and O[dd,col]>0 and (not np.isfinite(ldn) or O[dd,col]>ldn+1e-9):
                best=dd; break
        if best is None: dropped+=1; newday[i]=-1
        else: newday[i]=best; delayed+=1
print("[%4.0fs] X4 生产口径：可用事件 %d | 不可成交（模型假设） %d 笔（%.2f%%）→ 顺延成交 %d / 剔除 %d"
      % (time.time()-T0, xu.size, int(bad_fill.sum()), 100*bad_fill.mean(), delayed, dropped), flush=True)
def stats(r):
    return dict(n=int(r.size), mean=round(float(r.mean())*100,4), wr=round(float((r>0).mean())*100,2),
                win=round(float(r[r>0].mean())*100,4) if (r>0).any() else None,
                loss=round(float(r[r<=0].mean())*100,4) if (r<=0).any() else None)
base = opx[use]/px[use]-1.0
# B：顺延成交（若延后日无有效 open 则用该日 close/剔除）
new_opx = opx[use].copy()
for i in np.where(bad_fill & (newday>=0))[0]:
    dd=newday[i]; col=ju[i]
    new_opx[i] = O[dd,col] if np.isfinite(O[dd,col]) and O[dd,col]>0 else C[dd,col]
keepB = (newday>=0)
keepA = ~bad_fill
res={"counts":{"events":int(xu.size),"model_unfillable":int(bad_fill.sum()),
      "delay":int(delayed),"drop":int(dropped),"share_pct":round(float(100*bad_fill.mean()),3)},
     "affected_examples":[]}
for i in np.where(bad_fill)[0][:8]:
    res["affected_examples"].append({"code":str(codes[ju[i]]),"entry":cal[eu[i]],"exit_model":cal[xu[i]],
        "reason":int(ru[i]),"fill_model":round(float(opx[use][i]),3),
        "limit_down":None if not np.isfinite(ld(xu[i],ju[i])) else float(ld(xu[i],ju[i])),
        "new_exit":None if newday[i]<0 else cal[newday[i]],"fill_new":None if newday[i]<0 else round(float(new_opx[i]),3)})
out={"meta":{"title":"R-qlch-limitfill-0923","pool":"全池(B4_K3)","arm":"X4(25/-30/40)","run_at":time.strftime("%Y-%m-%d %H:%M:%S")},
     "counts":res["counts"],"affected_examples":res["affected_examples"]}
print("\n=== 事件级（单笔均值/胜率，含亏损单、等权）===")
for tag, keep, opx_ in (("原口径（含不可成交）", np.ones(xu.size,bool), opx[use]),
                        ("B 顺延成交（主口径）", keepB, new_opx),
                        ("A 直接剔除（保守上界）", keepA, opx[use])):
    r = opx_[keep]/px[use][keep]-1.0-0.0020
    st=stats(r); out["event_%s"%tag]=st
    print("  %-22s n=%4d 均值%+.3f%% 胜率%.1f%% 盈单%+.3f%% 亏单%+.3f%%" % (tag, st["n"], st["mean"], st["wr"], st["win"] or 0, st["loss"] or 0), flush=True)
def sharpe_run(opx_, xday, keep, cost):
    idx=np.where(keep)[0]
    nav,inv,te,tx,tr,th,tv=g.simulate(eu[idx], xday[idx], opx_[idx]/px[use][idx]-1.0-cost, hold[use][idx], T, g.SEEDS, g.K)
    rr=np.diff(nav)/nav[:-1]
    met=g.metrics_all(nav,inv,te,tr,th,tv,{"full":(int(eu.min()),T-1)},len(g.SEEDS))["full"]
    return met, rr
def bci(r,nb=2000,L=21,seed=20260923):
    n=r.size; nbk=int(np.ceil(n/L)); hi=max(n-L,0); rng=np.random.default_rng(seed); off=np.arange(L); out=np.empty(nb); got=0
    while got<nb:
        m=min(200,nb-got); st=rng.integers(0,hi+1,size=(m,nbk)); idx=(st[:,:,None]+off[None,None,:]).reshape(m,nbk*L)[:,:n]
        R=r[idx]; s=R.std(axis=1,ddof=1); d=np.full(m,np.nan); ok=s>0
        d[ok]=R[ok].mean(axis=1)/s[ok]*np.sqrt(244.0); out[got:got+m]=d; got+=m
    v=out[np.isfinite(out)]; return [round(float(np.percentile(v,2.5)),3), round(float(np.percentile(v,97.5)),3)]
print("\n=== 组合级（种子平均净值口径）===")
for tag, opx_, xd, keep in (("原口径（含不可成交）", opx[use], xu, np.ones(xu.size,bool)),
                            ("B 顺延成交（主口径）", new_opx, newday.clip(min=1), keepB)):
    for ck,cv in (("P20",0.0020),("S60",0.0060)):
        met, rr = sharpe_run(opx_, xd, keep, cv); sh=met["sharpe"]
        ci = bci(rr) if ck=="P20" else None
        out["port_%s_%s"%(tag,ck)]={"sharpe":sh,"cagr":met["cagr"],"mdd":met["mdd"],"n":met["n"],"turn":met["turn"],"inv":met["inv"],"sharpe_ci95":ci}
        print("  %-22s %s 夏普 %6.3f 年化%+7.2f%% 回撤%+7.2f%% 笔%4d 换手%5.1f%s" % (tag, ck, sh, met["cagr"], met["mdd"], met["n"], met["turn"], ("  CI95=[%.3f,%.3f]"%(ci[0],ci[1])) if ci else ""), flush=True)
json.dump(out, open("backtest/qlch_limitfill_0923.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n已落盘 backtest/qlch_limitfill_0923.json | 耗时 %.0fs" % (time.time()-T0))