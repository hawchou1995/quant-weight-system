# -*- coding: utf-8 -*-
"""Step4: signals + portfolio simulation + metrics + sensitivities."""
import json, pathlib, time, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = R / "backtest/wechat_hotspot_leader_0925"
U = json.loads((OUT / "universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); uni = U["universe"]
inds = np.array([u["ind"] for u in uni], dtype=object)
g = {k: np.load(S / ("wl_" + k + ".npy"), mmap_mode="r") for k in
     ("CLOSE", "OPEN", "VOL", "AMT", "RET20", "AMT20", "VOL5", "VOL60", "VMA20_prev",
      "ATR20", "HHV60_prev", "NV", "VALID", "IR20", "IV20", "IAMT20", "IAMT60")}
C, O = np.asarray(g["CLOSE"]), np.asarray(g["OPEN"])
VALID = g["VALID"].astype(bool)
T, N = C.shape
ind_names = sorted(set(inds.tolist())); gidx = {x: k for k, x in enumerate(ind_names)}
gcol = np.array([gidx[x] for x in inds], dtype=np.int32)
IDX = pd.read_csv(R / "index_000300.csv")
IDX["date"] = IDX["date"].astype(str).str.slice(0, 10)
IDX = IDX.set_index("date").reindex(cal)
BENCH_C = pd.to_numeric(IDX["close"], errors="coerce").to_numpy(dtype=float)
BENCH_O = pd.to_numeric(IDX["open"], errors="coerce").to_numpy(dtype=float)

def pct_rank(x):
    """ascending percentile in [0,1]; NaN -> NaN"""
    ok = np.isfinite(x)
    out = np.full(x.shape, np.nan)
    if ok.sum() < 3: return out
    v = x[ok]; order = np.argsort(np.argsort(v))
    out[ok] = (order + 1) / len(v)
    return out

def build_signals(P1=0.20, P2=0.30, Q=0.80, M=1.5, MIN_AMT=2e7, KNEW=3, LISTED=250, MINPX=2.0, verbose=False):
    sig = [None] * T
    for t in range(60, T):
        ir, iv = g["IR20"][t], g["IV20"][t]
        ia20, ia60 = g["IAMT20"][t], g["IAMT60"][t]
        okg = np.isfinite(ir) & np.isfinite(iv) & np.isfinite(ia60) & (ia60 > 0)
        if okg.sum() < 5:
            continue
        r_ir = pct_rank(np.where(okg, ir, np.nan)); r_iv = pct_rank(np.where(okg, iv, np.nan))
        shrink = np.isfinite(ia20) & (ia20 / np.where(ia60 > 0, ia60, np.nan) < Q)
        gate = (r_ir <= P1) | ((r_iv <= P2) & shrink)          # 赛道门（跌幅大 OR 缩量横盘）
        gate = np.where(okg, gate, False)
        amt20, vma_p, hhv_p = g["AMT20"][t], g["VMA20_prev"][t], g["HHV60_prev"][t]
        elig = (VALID[t] & (g["NV"][t] >= LISTED) & (C[t] >= MINPX) &
                np.isfinite(amt20) & (amt20 >= MIN_AMT) & gate[gcol])
        if not elig.any():
            continue
        brk = np.isfinite(hhv_p) & np.isfinite(vma_p) & (vma_p > 0) & (C[t] > hhv_p) & (g["VOL"][t] > M * vma_p)
        cand = elig & brk
        if not cand.any():
            continue
        ci = np.nonzero(cand)[0]
        # 行业内 z（在**该行业当日全部合格股**上算，语义=行业内相对强弱）
        def zz(x, base_mask):
            out = np.full(N, np.nan)
            for gg in np.unique(gcol[base_mask]):
                m = base_mask & (gcol == gg)
                if m.sum() < 2: continue
                v = x[m]; mu, sd = np.nanmean(v), np.nanstd(v)
                if not np.isfinite(sd) or sd <= 0: continue
                out[m] = (x[m] - mu) / sd
            return out
        share = np.where(np.isfinite(g["IAMT20"][t][gcol]) & (g["IAMT20"][t][gcol] > 0),
                         g["AMT20"][t] / np.where(g["IAMT20"][t][gcol] > 0, g["IAMT20"][t][gcol], np.nan), np.nan)
        vr = g["VOL5"][t] / np.where(g["VOL60"][t] > 0, g["VOL60"][t], np.nan)
        F = np.zeros(N)
        for x in (share, g["ATR20"][t], vr, g["RET20"][t]):
            z = zz(np.where(np.isfinite(x), x, np.nan), elig)
            F = F + np.where(np.isfinite(z), z, 0.0)
        order = ci[np.argsort(-F[ci])][:KNEW]
        sig[t] = order.tolist()
    return sig

def simulate(sig, H=10, KSLOT=5, cost_side=0.001, t_start=250):
    cash = 1.0; pos = {}; nav = np.full(T, np.nan); trades = []
    nav[t_start - 1] = 1.0
    pending = []
    for t in range(t_start, T):
        # 1) 卖出（open[t]）
        for j in [j for j, p in pos.items() if p["exit"] == t]:
            p = pos.pop(j); px = O[t, j]
            if np.isfinite(px) and px > 0:
                cash += p["sh"] * px * (1 - cost_side)
                trades.append(dict(entry_date=str(cal[p["en"]]), exit_date=str(cal[t]), code=uni[j]["sym"],
                                   name=None, ret_pct=round((px * (1 - cost_side) / (p["px"] * (1 + cost_side)) - 1) * 100, 3),
                                   days=int(t - p["en"])))
        # 2) 买入（open[t]，用 t-1 收盘信号）
        for j in pending:
            if len(pos) >= KSLOT: break
            if j in pos: continue
            px = O[t, j]
            if not (np.isfinite(px) and px > 0): continue
            navprev = nav[t - 1] if np.isfinite(nav[t - 1]) else 1.0
            alloc = min(navprev / KSLOT, cash)
            if alloc <= 1e-9: break
            sh = alloc / (px * (1 + cost_side)); cash -= alloc
            pos[j] = dict(en=t, exit=t + H, sh=sh, px=px)
        pending = sig[t] if sig[t] else []
        # 3) 收盘盯市
        mv = 0.0
        for j, p in pos.items():
            c = C[t, j]; mv += p["sh"] * (c if np.isfinite(c) and c > 0 else p["px"])
        nav[t] = cash + mv
    bnav = np.full(T, np.nan); bnav[t_start - 1] = 1.0
    b0 = BENCH_O[t_start] if np.isfinite(BENCH_O[t_start]) else BENCH_C[t_start]
    for t in range(t_start, T):
        bnav[t] = BENCH_C[t] / b0
    return nav, bnav, trades

def metrics(nav, bnav, trades, H):
    ok = np.isfinite(nav)
    v = nav[ok]; b = bnav[ok]
    nd = len(v) - 1
    tot = v[-1] / v[0] - 1; ann = (v[-1] / v[0]) ** (244 / nd) - 1
    peak = np.maximum.accumulate(v); mdd = float((v / peak - 1).min())
    dr = v[1:] / v[:-1] - 1; sd = dr.std(ddof=1)
    sharpe = dr.mean() / sd * np.sqrt(244) if sd > 0 else 0
    btot = b[-1] / b[0] - 1; bann = (b[-1] / b[0]) ** (244 / nd) - 1
    bpk = np.maximum.accumulate(b); bmdd = float((b / bpk - 1).min())
    r = np.array([x["ret_pct"] for x in trades], dtype=float)
    yrs = {}
    for x in trades:
        yrs.setdefault(x["exit_date"][:4], []).append(x["ret_pct"])
    return dict(days=int(nd), total_pct=round(tot * 100, 2), ann_pct=round(ann * 100, 2),
                mdd_pct=round(mdd * 100, 2), sharpe=round(sharpe, 3),
                bench_total_pct=round(btot * 100, 2), bench_ann_pct=round(bann * 100, 2),
                bench_mdd_pct=round(bmdd * 100, 2),
                excess_ann_pp=round((ann - bann) * 100, 2),
                n=int(r.size), mean_pct=round(float(r.mean()), 3) if r.size else None,
                med_pct=round(float(np.median(r)), 3) if r.size else None,
                wr_pct=round(100 * float((r > 0).mean()), 1) if r.size else None,
                avg_days=round(float(np.mean([x["days"] for x in trades])), 1) if trades else None,
                per_year={k: dict(n=len(vv), sum=round(float(np.sum(vv)), 1),
                                  mean=round(float(np.mean(vv)), 3)) for k, vv in sorted(yrs.items())})

BASE = dict(P1=0.20, P2=0.30, Q=0.80, M=1.5, MIN_AMT=2e7, KNEW=3, H=10, KSLOT=5)
res = {"base_params": BASE, "note": "signal at close T -> buy open T+1 (shift 1, no lookahead); fractional shares; "
                                    "cost applied on both sides; NAV marked at close daily (full holding period)"}
t0 = time.time()
sigB = build_signals(**{k: BASE[k] for k in ("P1", "P2", "Q", "M", "MIN_AMT", "KNEW")})
print("base signals built %.0fs ; signal days=%d" % (time.time() - t0, sum(1 for s in sigB if s)))
for tag, cs in (("cost_20bp_rt", 0.0010), ("cost_115bp_rt", 0.00575)):
    nav, bnav, tr = simulate(sigB, H=BASE["H"], KSLOT=BASE["KSLOT"], cost_side=cs)
    res[tag] = metrics(nav, bnav, tr, BASE["H"])
    print("  %-14s ann %+.2f%%  mdd %.2f%%  excess %+.2fpp  n=%d mean %+.3f%% wr %.1f%%"
          % (tag, res[tag]["ann_pct"], res[tag]["mdd_pct"], res[tag]["excess_ann_pp"],
             res[tag]["n"], res[tag]["mean_pct"] or 0, res[tag]["wr_pct"] or 0), flush=True)
np.save(S / "wl_nav_base.npy", simulate(sigB, H=BASE["H"], KSLOT=BASE["KSLOT"], cost_side=0.0010)[0])
np.save(S / "wl_bnav.npy", simulate(sigB, H=BASE["H"], KSLOT=BASE["KSLOT"], cost_side=0.0010)[1])
# sensitivities
sens = {}
for H in (5, 10, 20):
    nav, bnav, tr = simulate(sigB, H=H, KSLOT=BASE["KSLOT"], cost_side=0.0010)
    sens["H=%d" % H] = metrics(nav, bnav, tr, H)
for M in (1.2, 1.5, 2.0):
    s2 = build_signals(**{**{k: BASE[k] for k in ("P1", "P2", "Q", "MIN_AMT", "KNEW")}, "M": M})
    nav, bnav, tr = simulate(s2, H=BASE["H"], KSLOT=BASE["KSLOT"], cost_side=0.0010)
    sens["M=%.1f" % M] = metrics(nav, bnav, tr, BASE["H"])
for P1 in (0.10, 0.20, 0.40):
    s2 = build_signals(**{**{k: BASE[k] for k in ("P2", "Q", "M", "MIN_AMT", "KNEW")}, "P1": P1})
    nav, bnav, tr = simulate(s2, H=BASE["H"], KSLOT=BASE["KSLOT"], cost_side=0.0010)
    sens["P1=%.2f" % P1] = metrics(nav, bnav, tr, BASE["H"])
res["sensitivities"] = sens
(OUT / "result_0925.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print("saved result_0925.json  total %.0fs" % (time.time() - t0))
print()
print("=== BASE (H=10, cost 20bp rt) ===")
b = res["cost_20bp_rt"]
print(json.dumps({k: v for k, v in b.items() if k != "per_year"}, ensure_ascii=False, indent=1))
print("per_year:", json.dumps(b["per_year"], ensure_ascii=False))
