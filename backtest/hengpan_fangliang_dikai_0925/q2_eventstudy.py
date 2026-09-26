# -*- coding: utf-8 -*-
"""q2: event study for 横盘突然放量 + 次日低开买入, with layer attribution and exit-horizon readings."""
import json, pathlib, pickle, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = R/"backtest/wechat_hotspot_leader_0925"
U = json.loads((OUT/"universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); uni = U["universe"]
inds = np.array([u["ind"] for u in uni], dtype=object); sym = [u["sym"] for u in uni]
T, N = len(cal), len(uni)
g = {k: np.load(S/("wl_"+k+".npy"), mmap_mode="r") for k in ("CLOSE","OPEN","VOL","AMT","AMT20","NV","VALID")}
C = np.asarray(g["CLOSE"]); O = np.asarray(g["OPEN"]); AMT20 = np.asarray(g["AMT20"])
NV = np.asarray(g["NV"]); VALID = g["VALID"].astype(bool)
d = {k: np.load(S/("wl2_"+k+".npy"), mmap_mode="r") for k in ("RANGE20prev","ABSRET20","VOLBR","SHRINK","GAPNEXT")}
RANGE = np.asarray(d["RANGE20prev"]); ABSRET = np.asarray(d["ABSRET20"])
VOLBR = np.asarray(d["VOLBR"]); SHRINK = np.asarray(d["SHRINK"]); GAPO = np.asarray(d["GAPNEXT"])
def sh1(a):  # a[t-1]
    b = np.full(a.shape, np.nan, dtype=np.float32); b[1:] = a[:-1]; return b
def fwd(a, k):  # a[t+k]
    b = np.full(a.shape, np.nan, dtype=np.float32); b[:-k] = a[k:]; return b
E1 = fwd(O, 1)                                  # 入场 = T+1 开盘
EX = {"T1close": fwd(C,1), "T2open": fwd(O,2), "T2close": fwd(C,2), "T3close": fwd(C,3)}
RET = {}
for k, v in EX.items():
    r = v/E1 - 1.0
    r[~(np.isfinite(v) & (v > 0) & np.isfinite(E1) & (E1 > 0))] = np.nan
    RET[k] = r.astype(np.float32)
print("h-days: E1 finite %d ; T2close finite %d" % (int(np.isfinite(E1).sum()), int(np.isfinite(RET["T2close"]).sum())))
def pct_rank(x):
    o = np.isfinite(x); out = np.full(x.shape, np.nan)
    if o.sum() < 3: return out
    out[o] = (np.argsort(np.argsort(x[o]))+1)/o.sum(); return out
PQ, K, SHR = 0.30, 2.0, 1.0
base_ok = lambda t: (VALID[t] & (NV[t] >= 250) & (C[t] >= 2.0) & np.isfinite(AMT20[t]) & (AMT20[t] >= 2e7))
buckets = {k: [] for k in ("C0_control","L1_flat","L2_flat_spk","L3_spk_lowopen","L4_spk_lowopen_ge1pct",
                           "L5_spk_highopen","L6_spk_anyopen")}
sig = {}
for t in range(60, T-3):
    b = base_ok(t) & np.isfinite(RANGE[t]) & np.isfinite(ABSRET[t]) & np.isfinite(VOLBR[t])
    if b.sum() < 10: continue
    m = RET["T2close"][t]
    mm = b & np.isfinite(m)
    if mm.any(): buckets["C0_control"].append(m[mm])
    pr = pct_rank(np.where(b, RANGE[t], np.nan)); pa = pct_rank(np.where(b, ABSRET[t], np.nan))
    flat = b & (pr <= PQ) & (pa <= PQ) & np.isfinite(SHRINK[t]) & (SHRINK[t] <= SHR)
    spk = flat & (VOLBR[t] >= K)
    for key, mask in (("L1_flat", flat), ("L2_flat_spk", spk), ("L6_spk_anyopen", spk)):
        m2 = mask & np.isfinite(m)
        if m2.any(): buckets[key].append(m[m2])
    gp = GAPO[t]
    low = spk & np.isfinite(gp) & (gp < 0)
    low1 = spk & np.isfinite(gp) & (gp <= -0.01)
    high = spk & np.isfinite(gp) & (gp > 0)
    for key, mask in (("L3_spk_lowopen", low), ("L4_spk_lowopen_ge1pct", low1), ("L5_spk_highopen", high)):
        m3 = mask & np.isfinite(m)
        if m3.any(): buckets[key].append(m[m3])
    if low.any():
        idx = np.nonzero(low & np.isfinite(RET["T2close"][t]))[0]
        if idx.size: sig[t] = idx.tolist()
print("\n=== 分层归因: 入场 T+1 开盘 -> 出场 T+2 尾盘, 无槽位/无成本, %d 日 ===" % (T-63))
out = {}
for k in buckets:
    if not buckets[k]: print("  %-22s (no data)" % k); continue
    a = np.concatenate(buckets[k])*100
    out[k] = dict(obs=int(a.size), mean=round(float(a.mean()),4), med=round(float(np.median(a)),3),
                  wr=round(float(100*(a>0).mean()),2), per_year=round(a.size/9.7,0))
    print("  %-22s obs=%8d (%6.0f/yr)  mean %+7.4f%%  med %+7.4f%%  wr %5.2f%%" %
          (k, a.size, a.size/9.7, a.mean(), np.median(a), 100*(a>0).mean()))
print("\n=== 出场口径三读 (base = 横盘+放量+次日低开, 同一信号集) ===")
ns = sum(len(v) for v in sig.values()); print("信号数 = %d (%.0f/年, %.1f/日)" % (ns, ns/9.7, ns/2300))
hout = {}
for k in ("T1close","T2open","T2close","T3close"):
    acc = []
    for t, idx in sig.items():
        v = RET[k][t][idx]; v = v[np.isfinite(v)]
        if v.size: acc.append(v)
    a = np.concatenate(acc)*100
    hout[k] = dict(obs=int(a.size), mean=round(float(a.mean()),4), med=round(float(np.median(a)),3),
                   wr=round(float(100*(a>0).mean()),2))
    tag = {"T1close":"T+1 尾盘(制度不允许,仅诊断)","T2open":"T+2 开盘","T2close":"T+2 尾盘 (base)","T3close":"T+3 尾盘 (另一读法)"}[k]
    print("  %-30s obs=%6d  mean %+7.4f%%  med %+7.4f%%  wr %5.2f%%" % (tag, a.size, a.mean(), np.median(a), 100*(a>0).mean()))
# control for the same exit horizons, over all eligible pairs
print("\n=== 同口径对照: 全池合格 (股票,日) 对, 入场 T+1 开盘 ===")
cout = {}
for k in ("T2close","T3close"):
    acc = []
    for t in range(60, T-3):
        b = base_ok(t); m = RET[k][t]
        mm = b & np.isfinite(m)
        if mm.any(): acc.append(m[mm])
    a = np.concatenate(acc)*100
    cout[k] = dict(obs=int(a.size), mean=round(float(a.mean()),4), med=round(float(np.median(a)),3), wr=round(float(100*(a>0).mean()),2))
    print("  control %-10s obs=%9d  mean %+7.4f%%  med %+7.4f%%  wr %5.2f%%" % (k, a.size, a.mean(), np.median(a), 100*(a>0).mean()))
# per-year for base set
print("\n=== base 信号集 逐年 (T+2 尾盘) ===")
py = {}
for t, idx in sig.items():
    v = RET["T2close"][t][idx]; v = v[np.isfinite(v)]
    if v.size: py.setdefault(str(cal[t])[:4], []).extend((v*100).tolist())
for y in sorted(py):
    a = np.array(py[y]); print("  %s n=%4d mean %+7.4f%% med %+7.4f%% wr %5.2f%%" % (y, a.size, a.mean(), np.median(a), 100*(a>0).mean()))
# gap distribution of the signal set
gp_all = []
for t, idx in sig.items():
    v = GAPO[t][idx]; v = v[np.isfinite(v)]; 
    if v.size: gp_all.append(v)
gpa = np.concatenate(gp_all)*100
print("\n入场跳空分布(%%): mean %+.3f  p10 %+.2f  p25 %+.2f  med %+.2f  p75 %+.2f  min %+.2f" %
      (gpa.mean(), np.percentile(gpa,10), np.percentile(gpa,25), np.median(gpa), np.percentile(gpa,75), gpa.min()))
json.dump(dict(layers=out, horizons=hout, control=cout, per_year={k:dict(n=len(v), mean=round(float(np.mean(v)),4)) for k,v in sorted(py.items())},
               n_signals=ns, gap=dict(mean=round(float(gpa.mean()),4), p25=round(float(np.percentile(gpa,25)),3), med=round(float(np.median(gpa)),3))),
          open(S/"q2_eventstudy.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
pickle.dump(sig, open(S/"q2_sig.pkl","wb"))
print("\nsaved q2_eventstudy.json + q2_sig.pkl")
