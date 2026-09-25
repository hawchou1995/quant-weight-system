# -*- coding: utf-8 -*-
"""Step4b (FIXED SIM): signal at close T -> buy open T+1 -> hold H -> sell open T+1+H.
FIX: exit-day invalid open no longer silently vaporises the position (defer to next valid open).
Also: t_start = first signal day; benchmark measured over the identical window."""
import json, pathlib, time, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = R / "backtest/wechat_hotspot_leader_0925"
U = json.loads((OUT / "universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); uni = U["universe"]
inds = np.array([u["ind"] for u in uni], dtype=object); sym = [u["sym"] for u in uni]
T, N = len(cal), len(uni)
g = {k: np.load(S / ("wl_" + k + ".npy"), mmap_mode="r") for k in
     ("CLOSE","OPEN","VOL","AMT","RET20","AMT20","VOL5","VOL60","VMA20_prev","ATR20","HHV60_prev","NV","VALID","IR20","IV20","IAMT20","IAMT60")}
C = np.asarray(g["CLOSE"]); O = np.asarray(g["OPEN"]); V = np.asarray(g["VOL"])
VALID = g["VALID"].astype(bool)
ind_names = sorted(set(inds.tolist())); gidx = {x:k for k,x in enumerate(ind_names)}
gcol = np.array([gidx[x] for x in inds], dtype=np.int32); NV = g["NV"]
IDX = pd.read_csv(R/"index_000300.csv"); IDX["date"] = IDX["date"].astype(str).str.slice(0,10)
IDX = IDX.set_index("date").reindex(cal)
BC = pd.to_numeric(IDX["close"], errors="coerce").to_numpy(dtype=float)
BO = pd.to_numeric(IDX["open"], errors="coerce").to_numpy(dtype=float)
BRKC = (C > g["HHV60_prev"]) & np.isfinite(g["HHV60_prev"]) & VALID
_cs = np.cumsum(BRKC.astype(np.int32), axis=0)
BRK20prev = np.zeros((T, N), dtype=np.int32)
_i = np.arange(21, T); BRK20prev[_i] = _cs[_i-1] - _cs[_i-21]
del _cs, BRKC
def pct_rank(x):
    o = np.isfinite(x); out = np.full(x.shape, np.nan)
    if o.sum() < 3: return out
    out[o] = (np.argsort(np.argsort(x[o])) + 1) / o.sum(); return out
def zz(x, base_mask):
    out = np.full(N, np.nan)
    for gg in np.unique(gcol[base_mask]):
        m = base_mask & (gcol == gg)
        if m.sum() < 2: continue
        v = x[m]; mu, sd = np.nanmean(v), np.nanstd(v)
        if not np.isfinite(sd) or sd <= 0: continue
        out[m] = (x[m] - mu) / sd
    return out
def build(P1=0.20, P2=0.30, Q=0.80, M=1.5, MIN_AMT=2e7, KNEW=3, LISTED=250, MINPX=2.0,
          FIRSTBRK=False, LOWRET20=False):
    sig = [None]*T
    for t in range(60, T):
        ir, iv = g["IR20"][t], g["IV20"][t]; ia20, ia60 = g["IAMT20"][t], g["IAMT60"][t]
        okg = np.isfinite(ir) & np.isfinite(iv) & np.isfinite(ia60) & (ia60 > 0)
        if okg.sum() < 5: continue
        r_ir = pct_rank(np.where(okg, ir, np.nan)); r_iv = pct_rank(np.where(okg, iv, np.nan))
        shrink = np.isfinite(ia20) & (ia20/np.where(ia60>0, ia60, np.nan) < Q)
        gate = np.where(okg, (r_ir <= P1) | ((r_iv <= P2) & shrink), False)
        amt20, vma_p, hhv_p = g["AMT20"][t], g["VMA20_prev"][t], g["HHV60_prev"][t]
        elig = (VALID[t] & (NV[t] >= LISTED) & (C[t] >= MINPX) & np.isfinite(amt20) & (amt20 >= MIN_AMT) & gate[gcol])
        if not elig.any(): continue
        brk = (np.isfinite(hhv_p) & np.isfinite(vma_p) & (vma_p > 0) & (C[t] > hhv_p) & (V[t] > M*vma_p))
        cand = elig & brk
        if FIRSTBRK: cand = cand & (BRK20prev[t] == 0)
        if not cand.any(): continue
        share = g["AMT20"][t] / np.where(g["IAMT20"][t][gcol] > 0, g["IAMT20"][t][gcol], np.nan)
        vr = g["VOL5"][t] / np.where(g["VOL60"][t] > 0, g["VOL60"][t], np.nan)
        F = np.zeros(N)
        for x in (share, g["ATR20"][t], vr, g["RET20"][t]):
            z = zz(np.where(np.isfinite(x), x, np.nan), elig)
            F = F + np.where(np.isfinite(z), z, 0.0)
        if LOWRET20:
            rm = g["RET20"][t]; low = np.zeros(N, dtype=bool)
            for gg in np.unique(gcol[cand]):
                m = cand & (gcol == gg)
                if m.sum() < 2: low[m] = True; continue
                low[m] = rm[m] <= np.nanmedian(rm[m])
            cand = cand & low
            if not cand.any(): continue
        ci = np.nonzero(cand)[0]
        sig[t] = ci[np.argsort(-F[ci])][:KNEW].tolist()
    return sig
def simulate(sig, H=10, KSLOT=5, cost_side=0.001):
    ts = next(t for t in range(T) if sig[t])
    cash = 1.0; pos = {}; nav = np.full(T, np.nan); trades = []
    nav[ts-1] = 1.0
    pending = sig[ts-1] if sig[ts-1] else []
    n_delay = 0; n_delay_pos = 0
    for t in range(ts, T):
        for j in [j for j, p in pos.items() if p["exit"] <= t]:
            p = pos[j]; px = O[t, j]
            if np.isfinite(px) and px > 0:
                pos.pop(j); cash += p["sh"]*px*(1-cost_side)
                trades.append(dict(entry_date=str(cal[p["en"]]), exit_date=str(cal[t]), code=sym[j],
                    ret_pct=round((px*(1-cost_side)/(p["px"]*(1+cost_side)) - 1)*100, 3),
                    days=int(t-p["en"]), delayed=int(p["delay"])))
            else:
                if p["exit"] == t:
                    p["delay"] += 1; n_delay += 1
                    if p["delay"] == 1: n_delay_pos += 1
                p["exit"] = t + 1
        for j in pending:
            if len(pos) >= KSLOT: break
            if j in pos: continue
            px = O[t, j]
            if not (np.isfinite(px) and px > 0): continue
            navprev = nav[t-1] if np.isfinite(nav[t-1]) else 1.0
            alloc = min(navprev/KSLOT, cash)
            if alloc <= 1e-9: break
            pos[j] = dict(en=t, exit=t+H, sh=alloc/(px*(1+cost_side)), px=px, delay=0)
            cash -= alloc
        pending = sig[t] if sig[t] else []
        mv = 0.0
        for j, p in pos.items():
            c = C[t, j]; mv += p["sh"]*(c if np.isfinite(c) and c > 0 else p["px"])
        nav[t] = cash + mv
    bnav = np.full(T, np.nan); bnav[ts-1] = 1.0
    b0 = BO[ts] if np.isfinite(BO[ts]) and BO[ts] > 0 else BC[ts]
    for t in range(ts, T): bnav[t] = BC[t]/b0
    return nav, bnav, trades, ts, n_delay_pos, len(pos)
def metrics(nav, bnav, trades):
    ok = np.isfinite(nav); v = nav[ok]; b = bnav[ok]; nd = len(v)-1
    tot = v[-1]/v[0]-1; ann = (v[-1]/v[0])**(244/nd)-1
    peak = np.maximum.accumulate(v); mdd = float((v/peak-1).min())
    dr = v[1:]/v[:-1]-1; sd = dr.std(ddof=1)
    sharpe = dr.mean()/sd*np.sqrt(244) if sd > 0 else 0.0
    btot = b[-1]/b[0]-1; bann = (b[-1]/b[0])**(244/nd)-1
    bpk = np.maximum.accumulate(b); bmdd = float((b/bpk-1).min())
    r = np.array([x["ret_pct"] for x in trades], dtype=float)
    yrs = {}
    for x in trades: yrs.setdefault(x["exit_date"][:4], []).append(x["ret_pct"])
    return dict(total_pct=round(tot*100,2), ann_pct=round(ann*100,2), mdd_pct=round(mdd*100,2),
        sharpe=round(float(sharpe),3), bench_total_pct=round(btot*100,2), bench_ann_pct=round(bann*100,2),
        bench_mdd_pct=round(bmdd*100,2), excess_ann_pp=round((ann-bann)*100,2),
        n=int(r.size), mean_pct=round(float(r.mean()),3) if r.size else None,
        med_pct=round(float(np.median(r)),3) if r.size else None,
        wr_pct=round(100*float((r>0).mean()),1) if r.size else None,
        avg_days=round(float(np.mean([x["days"] for x in trades])),1) if trades else None,
        per_year={k: dict(n=len(vv), mean=round(float(np.mean(vv)),3), sum=round(float(np.sum(vv)),1))
                  for k, vv in sorted(yrs.items())})
BASE = dict(P1=0.20,P2=0.30,Q=0.80,M=1.5,MIN_AMT=2e7,KNEW=3,H=10,KSLOT=5)
res = dict(base_params=BASE, engine_fix="exit on invalid open is DEFERRED to the next valid open (previous version silently dropped the position value)",
           trade_rule="signal at close T (all inputs use data <= T) -> buy at open of T+1 -> hold H trading days -> sell at open of T+1+H; equal weight; fractional shares; cost on both sides; NAV marked at close every day")
t00 = time.time()
def run(tag, cfg, H, KSLOT, costs=(("0bp",0.0),("20bp",0.0010),("115bp",0.00575))):
    sig = build(**cfg); nsig = sum(1 for x in sig if x)
    for nm, cs in costs:
        nav, bnav, tr, ts, ndp, still = simulate(sig, H=H, KSLOT=KSLOT, cost_side=cs)
        m = metrics(nav, bnav, tr)
        m["signal_days"] = nsig; m["start_date"] = str(cal[ts]); m["n_pos_delayed"] = ndp; m["n_still_open"] = still
        res["%s|%s" % (tag, nm)] = m
        print("  %-26s %-6s ann %+8.2f%%  mdd %7.2f%%  exc %+7.2fpp  n=%-5d mean %+.3f%% wr %5.1f%%  delay_pos=%d open=%d  [%.0fs]" %
              (tag, nm, m["ann_pct"], m["mdd_pct"], m["excess_ann_pp"], m["n"], m["mean_pct"] or 0, m["wr_pct"] or 0, ndp, still, time.time()-t00), flush=True)
    return sig
print("=== BASE (P1=.20 P2=.30 Q=.80 M=1.5 KNEW=3 H=10 KSLOT=5) ===", flush=True)
run("base", dict(P1=.20,P2=.30,Q=.80,M=1.5,MIN_AMT=2e7,KNEW=3), 10, 5)
print("=== H sensitivity ===", flush=True)
for H in (5, 20): run("H=%d" % H, dict(P1=.20,P2=.30,Q=.80,M=1.5,MIN_AMT=2e7,KNEW=3), H, 5, costs=(("20bp",0.0010),))
print("=== M sensitivity (放量倍数) ===", flush=True)
for M in (2.0, 3.0): run("M=%.1f" % M, dict(P1=.20,P2=.30,Q=.80,M=M,MIN_AMT=2e7,KNEW=3), 10, 5, costs=(("20bp",0.0010),))
print("=== P1 sensitivity (跌幅板块广度) ===", flush=True)
for P1 in (0.10, 0.40): run("P1=%.2f" % P1, dict(P1=P1,P2=.30,Q=.80,M=1.5,MIN_AMT=2e7,KNEW=3), 10, 5, costs=(("20bp",0.0010),))
print("=== full-signal portfolio (KNEW=1, KSLOT=10: every signal traded) ===", flush=True)
run("KNEW1_KSLOT10", dict(P1=.20,P2=.30,Q=.80,M=1.5,MIN_AMT=2e7,KNEW=1), 10, 10)
print("=== faithful '刚冒头' variants ===", flush=True)
run("firstbrk", dict(P1=.20,P2=.30,Q=.80,M=1.5,MIN_AMT=2e7,KNEW=3,FIRSTBRK=True), 10, 5)
run("firstbrk+lowret20", dict(P1=.20,P2=.30,Q=.80,M=1.5,MIN_AMT=2e7,KNEW=3,FIRSTBRK=True,LOWRET20=True), 10, 5)
(OUT/"result_0925b.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print("\nsaved result_0925b.json  total %.0fs" % (time.time()-t00))
