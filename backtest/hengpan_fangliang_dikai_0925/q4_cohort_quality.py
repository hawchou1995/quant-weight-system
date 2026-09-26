# -*- coding: utf-8 -*-
"""q4: cohort-equal-weight portfolio (zero signals dropped) + data-quality checks + sample-day layer printout."""
import json, pathlib, pickle, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); uni = U["universe"]
sym = [u["sym"] for u in uni]; names = [u.get("name") for u in uni]; T, N = len(cal), len(uni)
O = np.asarray(np.load(S/"wl_OPEN.npy", mmap_mode="r")); C = np.asarray(np.load(S/"wl_CLOSE.npy", mmap_mode="r"))
H_ = np.asarray(np.load(S/"wl_HIGH.npy", mmap_mode="r")); L_ = np.asarray(np.load(S/"wl_LOW.npy", mmap_mode="r"))
AMT20 = np.asarray(np.load(S/"wl_AMT20.npy", mmap_mode="r")); NV = np.asarray(np.load(S/"wl_NV.npy", mmap_mode="r"))
VALID = np.load(S/"wl_VALID.npy").astype(bool); VOLBR = np.asarray(np.load(S/"wl2_VOLBR.npy", mmap_mode="r"))
RANGE = np.asarray(np.load(S/"wl2_RANGE20prev.npy", mmap_mode="r")); ABSRET = np.asarray(np.load(S/"wl2_ABSRET20.npy", mmap_mode="r"))
SHR = np.asarray(np.load(S/"wl2_SHRINK.npy", mmap_mode="r")); GAPO = np.asarray(np.load(S/"wl2_GAPNEXT.npy", mmap_mode="r"))
sig = pickle.load(open(S/"q2_sig.pkl","rb")); ns = sum(len(v) for v in sig.values())
IDX = pd.read_csv(R/"index_000300.csv"); IDX["date"]=IDX["date"].astype(str).str.slice(0,10)
BC = pd.to_numeric(IDX.set_index("date").reindex(cal)["close"], errors="coerce").to_numpy(float)
# ---------- data quality ----------
print("=== D. 数据质量检查 ===")
z = 0; low_px = 0; zp = []
ex_ld = 0; exn = 0; en_ld = 0
for t, idx in sig.items():
    o1 = O[t+1][idx]; c2 = C[t+2][idx]; c1 = C[t+1][idx]
    okk = np.isfinite(o1)&(o1>0)&np.isfinite(c2)&(c2>0)
    r = c2[okk]/o1[okk]-1.0
    zero = np.abs(r) < 1e-7
    z += int(zero.sum()); zp.append(o1[okk][zero])
    if okk.any():
        e = np.isfinite(c1[okk])&(c1[okk]>0)
        exn += int(e.sum())
        ex_ld += int((c2[okk][e]/c1[okk][e]-1.0 <= -0.095).sum())
        g = GAPO[t][idx][okk]
        en_ld += int((g <= -0.095).sum())
print("  恰好 0 收益: %d 笔 ; 其中入场价分布 p10=%.2f med=%.2f p90=%.2f (全样本 med=%.2f)" %
      (z, np.percentile(np.concatenate(zp),10), np.median(np.concatenate(zp)), np.percentile(np.concatenate(zp),90),
       np.median(O[O>0])))
print("  出场日 T+2 收跌停(<=-9.5%%): %d / %d = %.3f%%  (无法卖出 -> 结果偏乐观)" % (ex_ld, exn, 100.0*ex_ld/max(1,exn)))
print("  入场日 T+1 开盘跌停(<=-9.5%%): %d 笔 = %.3f%% (可买, 有卖盘)" % (en_ld, 100.0*en_ld/ns))
np.save(S/"q4_zeropx.npy", np.concatenate(zp))
# ---------- cohort EW portfolio ----------
def simulate_cohort(sig, ex_off=2, ex_field="close", H=2, cost_side=0.0):
    EX = {"close": C, "open": O}[ex_field]
    ts = min(sig); cash=1.0; pos={}; nav=np.full(T,np.nan); trades=[]; nav[ts]=1.0
    cen = dict(entry_invalid=0, defer=0, ok=0, dup=0)
    for t in range(ts+1, T):
        for _ in range(2):
            for j in [j for j,p in pos.items() if p["tgt"] <= t]:
                p = pos[j]; px = EX[t, j]
                if np.isfinite(px) and px > 0:
                    pos.pop(j); cash += p["sh"]*px*(1-cost_side); cen["ok"] += 1
                    trades.append(dict(sg=p["sg"], en=p["en"], ex=t, code=sym[j], px_in=p["px"], px_out=px,
                        ret_pct=(px*(1-cost_side)/(p["px"]*(1+cost_side))-1)*100, days=int(t-p["en"])))
                else:
                    if p["tgt"] == t: cen["defer"] += 1
                    p["tgt"] = t+1
        pend = sig.get(t-1, [])
        if pend:
            navprev = nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            fresh = [j for j in pend if j not in pos and np.isfinite(O[t,j]) and O[t,j] > 0]
            cen["dup"] += len(pend)-len(fresh)
            if fresh:
                tot = min(navprev/H, cash); per = tot/len(fresh)
                for j in fresh:
                    px = O[t,j]
                    if per <= 1e-12: break
                    pos[j] = dict(en=t, tgt=t+ex_off, sg=t-1, sh=per/(px*(1+cost_side)), px=px)
                    cash -= per
        mv = 0.0
        for j,p in pos.items():
            c = C[t,j]; mv += p["sh"]*(c if np.isfinite(c) and c>0 else p["px"])
        nav[t] = cash + mv
    bnav = np.full(T,np.nan); bnav[ts]=1.0
    for t in range(ts+1,T): bnav[t]=BC[t]/BC[ts]
    return nav,bnav,trades,ts,cen
def metrics(nav,bnav,trades):
    ok=np.isfinite(nav); v=nav[ok]; b=bnav[ok]; nd=len(v)-1
    ann=(v[-1]/v[0])**(244/nd)-1; peak=np.maximum.accumulate(v); dr=v[1:]/v[:-1]-1; sd=dr.std(ddof=1)
    bann=(b[-1]/b[0])**(244/nd)-1; bpk=np.maximum.accumulate(b)
    r=np.array([x["ret_pct"] for x in trades],float); yr={}
    for x in trades: yr.setdefault(str(cal[x["ex"]])[:4],[]).append(x["ret_pct"])
    return dict(total_pct=round((v[-1]/v[0]-1)*100,2), ann_pct=round(ann*100,2), mdd_pct=round(float((v/peak-1).min())*100,2),
        sharpe=round(float(dr.mean()/sd*np.sqrt(244)),3) if sd>0 else None, bench_total_pct=round((b[-1]/b[0]-1)*100,2),
        bench_ann_pct=round(bann*100,2), bench_mdd_pct=round(float((b/bpk-1).min())*100,2), excess_ann_pp=round((ann-bann)*100,2),
        n=int(r.size), mean_pct=round(float(r.mean()),3), med_pct=round(float(np.median(r)),3), wr_pct=round(100*float((r>0).mean()),1),
        avg_days=round(float(np.mean([x["days"] for x in trades])),1), neg_years=sum(1 for k,vv in yr.items() if np.mean(vv)<0),
        n_years=len(yr), per_year={k:dict(n=len(vv),mean=round(float(np.mean(vv)),3)) for k,vv in sorted(yr.items())})
res = {}
print("\n=== E. 队列等权组合 (每信号都成交, 每新建仓日投入 NAV/2 等分; 无槽位丢弃) ===")
for nm, cs in (("0bp",0.0),("10bp",0.0005),("20bp",0.0010),("40bp",0.0020),("115bp",0.00575)):
    nav,bnav,tr,ts,cen = simulate_cohort(sig, cost_side=cs)
    m = metrics(nav,bnav,tr); m["census"]=cen; m["start_date"]=str(cal[ts]); m["coverage_pct"]=round(100.0*len(tr)/ns,1)
    res["cohort_"+nm]=m
    print("  %-6s ann %+8.2f%%  mdd %7.2f%%  tot %8.2f%%  sh %6.2f  exc %+7.2fpp  n=%-5d mean %+.3f%% med %+.3f%% wr %5.1f%% cov %.1f%% negY %d/%d" %
          (nm, m["ann_pct"], m["mdd_pct"], m["total_pct"], m["sharpe"] or 0, m["excess_ann_pp"], m["n"], m["mean_pct"], m["med_pct"], m["wr_pct"], m["coverage_pct"], m["neg_years"], m["n_years"]), flush=True)
print("\n  逐年 (队列等权 20bp):")
for y,r_ in res["cohort_20bp"]["per_year"].items(): print("    %s n=%4d mean %+7.3f%%" % (y, r_["n"], r_["mean"]))
# ---------- sample-day layer printout (ironclad rule: print the layers before trusting) ----------
print("\n=== F. 抽样逐层打印 (5 个交易日) ===")
def pct_rank(x):
    o=np.isfinite(x); out=np.full(x.shape,np.nan)
    if o.sum()<3: return out
    out[o]=(np.argsort(np.argsort(x[o]))+1)/o.sum(); return out
sdays = sorted(sig.keys())
for t in [sdays[10], sdays[len(sdays)//3], sdays[len(sdays)//2], sdays[3*len(sdays)//4], sdays[-12]]:
    b = (VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=2e7)&np.isfinite(RANGE[t])&np.isfinite(ABSRET[t])&np.isfinite(VOLBR[t]))
    pr = pct_rank(np.where(b,RANGE[t],np.nan)); pa = pct_rank(np.where(b,ABSRET[t],np.nan))
    flat = b&(pr<=0.30)&(pa<=0.30)&np.isfinite(SHR[t])&(SHR[t]<=1.0)
    spk = flat&(VOLBR[t]>=2.0)
    gp = GAPO[t]; low = spk&np.isfinite(gp)&(gp<0)
    sel = np.nonzero(low)[0]
    print("  %s  合格池=%d  横盘=%d  横盘+放量=%d  再加低开=%d" % (cal[t], b.sum(), flat.sum(), spk.sum(), low.sum()))
    for j in sel[:3]:
        print("      %s %s  量比%.2f 前20日振幅%.1f%% |RET20|%.1f%% 跳空%+.2f%% -> T+2尾盘收益%+.2f%%" %
              (sym[j], (names[j] or "") if isinstance(names, list) else "", VOLBR[t][j], RANGE[t][j]*100, ABSRET[t][j]*100, gp[j]*100,
               (C[t+2][j]/O[t+1][j]-1)*100 if (O[t+1][j]>0 and C[t+2][j]>0) else float('nan')))
OUTD = R/"backtest/hengpan_fangliang_dikai_0925"
old = json.loads((OUTD/"result_0925.json").read_text(encoding="utf-8"))
old["cohort"] = {k:v for k,v in res.items()}
old["data_quality"] = dict(exact_zero=z, exact_zero_pct=round(100.0*z/ns,3), zero_med_px=round(float(np.median(np.concatenate(zp))),3),
    exit_limitdown=ex_ld, exit_limitdown_pct=round(100.0*ex_ld/max(1,exn),3), entry_limitdown_pct=round(100.0*en_ld/ns,3))
(OUTD/"result_0925.json").write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
print("\nmerged into %s" % (OUTD/"result_0925.json"))

