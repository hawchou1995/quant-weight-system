# -*- coding: utf-8 -*-
"""q3: portfolio sim (fixed engine) + day-clustered significance + cost ladder."""
import json, pathlib, pickle, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); uni = U["universe"]
sym = [u["sym"] for u in uni]; T, N = len(cal), len(uni)
O = np.asarray(np.load(S/"wl_OPEN.npy", mmap_mode="r")); C = np.asarray(np.load(S/"wl_CLOSE.npy", mmap_mode="r"))
AMT20 = np.asarray(np.load(S/"wl_AMT20.npy", mmap_mode="r")); NV = np.asarray(np.load(S/"wl_NV.npy", mmap_mode="r"))
VALID = np.load(S/"wl_VALID.npy").astype(bool)
VOLBR = np.asarray(np.load(S/"wl2_VOLBR.npy", mmap_mode="r"))
sig = pickle.load(open(S/"q2_sig.pkl","rb"))
ns = sum(len(v) for v in sig.values())
cnt = np.array([len(v) for v in sig.values()])
print("signals=%d over %d days ; per-day median=%.0f p75=%.0f p90=%.0f max=%d" %
      (ns, len(cnt), np.median(cnt), np.percentile(cnt,75), np.percentile(cnt,90), cnt.max()))
KSLOT_FULL = int(np.ceil(2*np.percentile(cnt,90)))
print("KSLOT for ~full coverage (2 x p90) = %d" % KSLOT_FULL)
def sh(a, k):   # a[t+k]
    b = np.full(a.shape, np.nan, dtype=np.float32); b[:-k] = a[k:]; return b
E1 = sh(O,1)
# ---- day-clustered significance ----
def rday(field, off):
    v = sh(field, off); r = v/E1 - 1.0
    r[~(np.isfinite(v)&(v>0)&np.isfinite(E1)&(E1>0))] = np.nan
    return r
def base_ok(t): return (VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=2e7))
R2 = rday(C, 2)
sdm, cdm, zeros, nz = [], [], 0, 0
for t, idx in sig.items():
    v = R2[t][idx]; v = v[np.isfinite(v)]
    if not v.size: continue
    b = base_ok(t); cv = R2[t][b]; cv = cv[np.isfinite(cv)]
    sdm.append(v.mean()); cdm.append(cv.mean() if cv.size else np.nan)
    zeros += int((np.abs(v) < 1e-6).sum()); nz += v.size
sdm = np.array(sdm); cdm = np.array(cdm)
d = sdm - cdm; d = d[np.isfinite(d)]
def tstat(x):
    return float(x.mean()/(x.std(ddof=1)/np.sqrt(x.size)))
print("\n=== 按日聚类的显著性 (n_days=%d) ===" % sdm.size)
print("  信号日均值/日   mean %+.4f%%/日  sd %.4f%%  t=%.2f" % (sdm.mean()*100, sdm.std(ddof=1)*100, tstat(sdm)))
print("  超额(信号-对照) mean %+.4f%%/日  sd %.4f%%  t=%.2f  -> %s" %
      (d.mean()*100, d.std(ddof=1)*100, tstat(d), "显著" if abs(tstat(d))>2 else "不显著"))
print("  逐笔方差口径: sd(笔)≈%.3f%%, 笔数=%d, 独立日=%d -> 有效独立信息量约 %d 天" % (0,0,0,0))
print("  恰好 0 收益的笔数 = %d / %d = %.3f%% (数据质量检查)" % (zeros, nz, 100.0*zeros/nz))
np.save(S/"q3_sigdaymean.npy", sdm)
# ---- benchmark ----
IDX = pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
IDX = IDX.set_index("date").reindex(cal)
BC = pd.to_numeric(IDX["close"], errors="coerce").to_numpy(float)
# ---- portfolio ----
def simulate(sig, ex_off=2, ex_field="close", KSLOT=22, cost_side=0.0, KNEW=None, rank=None):
    EX = {"close": C, "open": O}[ex_field]
    ts = min(sig)
    cash=1.0; pos={}; nav=np.full(T,np.nan); trades=[]
    nav[ts]=1.0
    cen = dict(entry_invalid=0, slot_full=0, defer=0, ok=0)
    for t in range(ts+1, T):
        for j in [j for j,p in pos.items() if p["tgt"] <= t]:
            p = pos[j]; need = p["tgt"] + ex_off      # 目标 = 信号日+1+off ; 用绝对日索引
            px = EX[t, j]
            if np.isfinite(px) and px > 0:
                pos.pop(j); cash += p["sh"]*px*(1-cost_side); cen["ok"] += 1
                trades.append(dict(sg=p["sg"], en=p["en"], ex=t, code=sym[j],
                    ret_pct=(px*(1-cost_side)/(p["px"]*(1+cost_side))-1)*100, days=int(t-p["en"])))
            else:
                if p["tgt"] == t: cen["defer"] += 1
                p["tgt"] = t+1
        for j in [j for j,p in pos.items() if p["tgt"] <= t]:   # 二次尝试(同日多次延迟后仍无效)
            p = pos[j]; px = EX[t, j]
            if np.isfinite(px) and px > 0:
                pos.pop(j); cash += p["sh"]*px*(1-cost_side); cen["ok"] += 1
                trades.append(dict(sg=p["sg"], en=p["en"], ex=t, code=sym[j],
                    ret_pct=(px*(1-cost_side)/(p["px"]*(1+cost_side))-1)*100, days=int(t-p["en"])))
            else: p["tgt"] = t+1
        pend = sig.get(t-1, [])
        if KNEW is not None and len(pend) > KNEW:
            sc = rank[t-1] if rank is not None else VOLBR[t-1]
            sc = np.where(np.isfinite(sc), sc, -1e9)[pend]
            pend = [pend[i] for i in np.argsort(-sc)[:KNEW]]
        for j in pend:
            if len(pos) >= KSLOT: cen["slot_full"] += 1; continue
            if j in pos: continue
            px = O[t, j]
            if not (np.isfinite(px) and px > 0): cen["entry_invalid"] += 1; continue
            navprev = nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            alloc = min(navprev/KSLOT, cash)
            if alloc <= 1e-9: cen["slot_full"] += 1; continue
            pos[j] = dict(en=t, tgt=t+ex_off, sg=t-1, sh=alloc/(px*(1+cost_side)), px=px, delay=0)
            cash -= alloc
        mv = 0.0
        for j,p in pos.items():
            c = C[t,j]; mv += p["sh"]*(c if np.isfinite(c) and c>0 else p["px"])
        nav[t] = cash + mv
    bnav = np.full(T,np.nan); bnav[ts]=1.0
    b0 = BC[ts]
    for t in range(ts+1,T): bnav[t] = BC[t]/b0
    return nav, bnav, trades, ts, cen
def metrics(nav, bnav, trades):
    ok=np.isfinite(nav); v=nav[ok]; b=bnav[ok]; nd=len(v)-1
    ann=(v[-1]/v[0])**(244/nd)-1; peak=np.maximum.accumulate(v)
    dr=v[1:]/v[:-1]-1; sd=dr.std(ddof=1)
    bann=(b[-1]/b[0])**(244/nd)-1; bpk=np.maximum.accumulate(b)
    r=np.array([x["ret_pct"] for x in trades],float); yr={}
    for x in trades: yr.setdefault(str(cal[x["ex"]])[:4], []).append(x["ret_pct"])
    return dict(total_pct=round((v[-1]/v[0]-1)*100,2), ann_pct=round(ann*100,2), mdd_pct=round(float((v/peak-1).min())*100,2),
        sharpe=round(float(dr.mean()/sd*np.sqrt(244)),3) if sd>0 else None, bench_total_pct=round((b[-1]/b[0]-1)*100,2),
        bench_ann_pct=round(bann*100,2), bench_mdd_pct=round(float((b/bpk-1).min())*100,2), excess_ann_pp=round((ann-bann)*100,2),
        n=int(r.size), mean_pct=round(float(r.mean()),3), med_pct=round(float(np.median(r)),3),
        wr_pct=round(100*float((r>0).mean()),1), avg_days=round(float(np.mean([x["days"] for x in trades])),1),
        neg_years=sum(1 for k,vv in yr.items() if np.mean(vv)<0), n_years=len(yr),
        per_year={k: dict(n=len(vv), mean=round(float(np.mean(vv)),3)) for k,vv in sorted(yr.items())})
res={}
COSTS=(("0bp",0.0),("10bp",0.0005),("20bp",0.0010),("40bp",0.0020),("115bp",0.00575))
print("\n=== A. 满覆盖组合 (每笔 = NAV/%d, 全部信号, 出场 T+2 尾盘) ===" % KSLOT_FULL)
for nm, cs in COSTS:
    nav,bnav,tr,ts,cen = simulate(sig, ex_off=2, ex_field="close", KSLOT=KSLOT_FULL, cost_side=cs)
    m = metrics(nav,bnav,tr); m["census"]=cen; m["start_date"]=str(cal[ts]); m["coverage_pct"]=round(100.0*len(tr)/ns,1)
    res["full_"+nm]=m
    print("  %-6s ann %+8.2f%%  mdd %7.2f%%  tot %8.2f%%  sh %6.2f  exc %+7.2fpp  n=%-5d mean %+.3f%% med %+.3f%% wr %5.1f%% negY %d/%d cov %.1f%%  [inv=%d slot=%d def=%d]" %
          (nm, m["ann_pct"], m["mdd_pct"], m["total_pct"], m["sharpe"] or 0, m["excess_ann_pp"], m["n"], m["mean_pct"], m["med_pct"], m["wr_pct"],
           m["neg_years"], m["n_years"], m["coverage_pct"], cen["entry_invalid"], cen["slot_full"], cen["defer"]), flush=True)
print("\n=== B. 可实操组合 (每日前 3 只按放量倍数, KSLOT=6) ===")
for nm, cs in (("0bp",0.0),("20bp",0.0010),("40bp",0.0020),("115bp",0.00575)):
    nav,bnav,tr,ts,cen = simulate(sig, ex_off=2, ex_field="close", KSLOT=6, cost_side=cs, KNEW=3)
    m = metrics(nav,bnav,tr); m["census"]=cen; m["start_date"]=str(cal[ts]); m["coverage_pct"]=round(100.0*len(tr)/ns,1)
    res["prac_"+nm]=m
    print("  %-6s ann %+8.2f%%  mdd %7.2f%%  tot %8.2f%%  sh %6.2f  exc %+7.2fpp  n=%-5d mean %+.3f%% med %+.3f%% wr %5.1f%% cov %.1f%%" %
          (nm, m["ann_pct"], m["mdd_pct"], m["total_pct"], m["sharpe"] or 0, m["excess_ann_pp"], m["n"], m["mean_pct"], m["med_pct"], m["wr_pct"], m["coverage_pct"]), flush=True)
print("\n=== C. 出场口径 (满覆盖, 20bp) ===")
for lbl, off, fld in (("T+2 尾盘", 2, "close"), ("T+2 开盘", 2, "open"), ("T+3 尾盘", 3, "close")):
    nav,bnav,tr,ts,cen = simulate(sig, ex_off=off, ex_field=fld, KSLOT=KSLOT_FULL, cost_side=0.0010)
    m = metrics(nav,bnav,tr); res["horizon_"+lbl]=m
    print("  %-9s ann %+8.2f%%  mdd %7.2f%%  sh %6.2f  exc %+7.2fpp  n=%-5d mean %+.3f%% wr %5.1f%%  negY %d/%d" %
          (lbl, m["ann_pct"], m["mdd_pct"], m["sharpe"] or 0, m["excess_ann_pp"], m["n"], m["mean_pct"], m["wr_pct"], m["neg_years"], m["n_years"]), flush=True)
print("\n=== 逐年 (满覆盖 20bp, T+2 尾盘) ===")
for y, r_ in res["full_20bp"]["per_year"].items(): print("  %s n=%4d mean %+7.3f%%" % (y, r_["n"], r_["mean"]))
OUTD = R/"backtest/hengpan_fangliang_dikai_0925"; OUTD.mkdir(parents=True, exist_ok=True)
res["spec"] = dict(signal="横盘(振幅分位<=0.30 且 |RET20|分位<=0.30) + 缩量(VMA20prev/VOL60prev<=1.0) + 突然放量(量比>=2.0) + 次日低开(open/前收-1<0)",
                   entry="T+1 开盘", exit="T+2 尾盘(收盘)", KSLOT_full=KSLOT_FULL, universe="5207 只 / 30 申万一级")
res["stats"] = dict(signals=ns, sig_days=int(len(cnt)), per_day_median=float(np.median(cnt)),
                    cluster_t_signal=round(tstat(sdm),2), cluster_t_excess=round(tstat(d),2),
                    daily_signal_mean_pct=round(float(sdm.mean()*100),4), daily_excess_mean_pct=round(float(d.mean()*100),4),
                    exact_zero_pct=round(100.0*zeros/nz,3), per_year=round(ns/9.7,0))
(OUTD/"result_0925.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print("\nsaved %s" % (OUTD/"result_0925.json"))
