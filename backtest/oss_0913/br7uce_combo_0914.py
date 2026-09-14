# -*- coding: utf-8 -*-
"""地量星信号组合级回测（2026-09-14）——事件 edge 能否兑现为组合净值
设计：每 H 日一期，期初从当日信号列表按 dd20（回撤深度）升序取 Top-N，T+1 开盘等权买入，持有 H 日
网格：参数档 {base(shrink<=0.6∧dd<=-8%), deep(dd<=-15%), deep2(dd<=-20%)} × N{5,10,20} × H{5,10,20} × 全相位
成本：往返 0.115%（20bp 滑点+费用近似）；对照：随机选股（同池同 N）
"""
import numpy as np, pandas as pd, pickle, json, time
from pathlib import Path

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
COST = 0.00115
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

with open(OUT / "oss_panel_0913.pkl", "rb") as fh:
    P = pickle.load(fh)
cal = P["cal"]; codes = P["codes"]; st_mask = P["st_mask"]
ND, NC = P["close"].shape
O = P["open"].astype(np.float64); C = P["close"].astype(np.float64)
V = P["vol"].astype(np.float64); AMT = P["amt"].astype(np.float64)
close_ff = pd.DataFrame(C).ffill().to_numpy()
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
hist_n = np.cumsum(np.isfinite(O), axis=0)
ELIG = (np.isfinite(O) & np.isfinite(C) & (amt20 >= 5e7) & (~st_mask[None, :])
        & (hist_n >= 150) & (C > 2.0))
v5 = pd.DataFrame(V).rolling(5, min_periods=5).mean().to_numpy()
v20 = pd.DataFrame(V).rolling(20, min_periods=15).mean().to_numpy()
hi20 = pd.DataFrame(C).rolling(20, min_periods=15).max().to_numpy()
with np.errstate(all="ignore"):
    shrink = v5 / v20
    body = np.abs(C - O) / O
    dd20 = close_ff / hi20 - 1
BASE_SIG = (shrink <= 0.6) & (body <= 0.01) & ELIG & np.isfinite(shrink)
PARAMS = {
    "base": BASE_SIG & (dd20 <= -0.08),
    "deep": BASE_SIG & (dd20 <= -0.15),
    "deep2": BASE_SIG & (dd20 <= -0.20),
}
log("params:", {k: int(v[150:].sum()) for k, v in PARAMS.items()})

def seg_engine(sig, N, H, offset, rank_mat):
    """段制: 每 H 日一期（带 offset 相位）; 期初信号按 rank 排序取 TopN"""
    n_seg = (ND - 1 - H - offset) // H
    rs = []
    for s in range(n_seg):
        t = offset + s * H
        ok = sig[t] & np.isfinite(close_ff[t])
        cand = np.flatnonzero(ok)
        if len(cand) == 0:
            rs.append(0.0); continue
        rk = rank_mat[t][cand]
        ordj = cand[np.argsort(np.where(np.isfinite(rk), rk, 1e9))][:N]
        o1 = O[t + 1][ordj]; oH = O[min(t + 1 + H, ND - 1)][ordj]
        with np.errstate(all="ignore"):
            r = oH / o1 - 1
        r = r[np.isfinite(r)]
        rs.append(float(np.mean(r)) - COST if len(r) else 0.0)
    arr = np.array(rs)
    eq = np.cumprod(1 + arr)
    if len(arr) == 0: return None
    yrs = len(arr) * H / 244.0
    ann = (eq[-1]) ** (1 / yrs) - 1 if yrs > 0 and eq[-1] > 0 else -1
    sh = float(np.mean(arr) / (np.std(arr) + 1e-12) * np.sqrt(244 / H))
    mdd = float((eq / np.maximum.accumulate(eq) - 1).min())
    by_year = {}
    for y in sorted(set(str(cal[offset + s * H])[:4] for s in range(n_seg))):
        idxs = [s for s in range(n_seg) if str(cal[offset + s * H])[:4] == y]
        if idxs: by_year[y] = float(np.prod(1 + arr[idxs]) - 1)
    return dict(total=float(eq[-1] - 1), ann=float(ann), sharpe=sh, mdd=mdd, by_year=by_year)

results = []
for pname, sig in PARAMS.items():
    for N in [5, 10, 20]:
        for H in [5, 10, 20]:
            shs, offs = [], []
            for off in range(H):
                m = seg_engine(sig, N, H, off, dd20)  # 按回撤深度排序（越深越优先）
                if m is None: continue
                shs.append(m["sharpe"]); offs.append(m)
            if not offs: continue
            med = float(np.median(shs)); o0 = offs[0]
            results.append(dict(param=pname, N=N, H=H, off0_sharpe=o0["sharpe"], off0_ann=o0["ann"],
                                off0_mdd=o0["mdd"], off0_by_year=o0["by_year"],
                                phmed_sharpe=med, phmed_ann=float(np.median([o["ann"] for o in offs])),
                                phmin=float(min(shs))))
            log(f"{pname:6s} N={N:2d} H={H:2d} | off0 S={o0['sharpe']:+.3f} ann={o0['ann']*100:+7.2f}% mdd={o0['mdd']*100:5.1f}% | phmed S={med:+.3f} phmin={min(shs):+.2f}")

# 对照: 随机选股（同池, base 参数 N10 H10）
rng = np.random.default_rng(9)
ctrl = []
for seed_i in range(100):
    rmat = np.where(ELIG & np.isfinite(close_ff), rng.random((ND, NC)), np.nan)
    m = seg_engine(PARAMS["base"], 10, 10, 0, rmat)
    if m: ctrl.append(m["sharpe"])
log(f"对照(随机选股 N10/H10): median={np.median(ctrl):+.3f} p90={np.percentile(ctrl,90):+.3f} max={max(ctrl):+.3f}")

results.sort(key=lambda r: -r["phmed_sharpe"])
log("=== TOP 8 (phmed Sharpe) ===")
for r in results[:8]:
    yy = " ".join(f"{y}:{v:+.2f}" for y, v in r["off0_by_year"].items())
    log(f"{r['param']:6s} N={r['N']:2d} H={r['H']:2d} | phmed S={r['phmed_sharpe']:+.3f} ann={r['phmed_ann']*100:+.2f}% | off0 S={r['off0_sharpe']:+.3f} | {yy}")

out = dict(meta=dict(window="2021-01-04~2026-09-11", pool="主板 5000万", cost=COST,
                     rank="按 dd20 回撤深度升序（深优先）", n_trials=len(results) + 100),
           results=results, control=dict(median=float(np.median(ctrl)), p90=float(np.percentile(ctrl, 90)), max=float(max(ctrl))))
json.dump(out, open(OUT / "br7uce_combo_0914.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved br7uce_combo_0914.json DONE")
