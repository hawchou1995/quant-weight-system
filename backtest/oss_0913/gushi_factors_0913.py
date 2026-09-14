# -*- coding: utf-8 -*-
"""oss_0913 批8: gushi.in 论坛方法论迁移验证
因子（本地构造）:
  zt_hist60  = 过去 60 日涨停次数（连板基因代理）
  zt_rec5    = 过去 5 日涨停次数
  lianban20  = 最近 20 日内最大连续涨停高度
  cmf20      = Chaikin 资金流强度 sum(((C-L)-(H-C))/(H-L)*V, 20)/sum(V,20)（主力资金代理）
  mf_shift   = 近5日 CMF 均值 - 前20日 CMF 均值（"资金没走完/流入加速"逻辑）
检验:
  A. IC 体检 (H20, 主板 5000万地板)
  B. 打板场景: 当日触板股 (high>=prev*1.098) 按 zt_hist60 分位分组 → T+1 open→close 收益
申报: 涨停判定用前复权价比值 1.098（主板10%近似）；资金流为价量代理（无 Level-2）
"""
import numpy as np, pandas as pd, pickle, json, os, time
from pathlib import Path

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

with open(OUT / "oss_panel_0913.pkl", "rb") as fh:
    P = pickle.load(fh)
cal = P["cal"]; codes = P["codes"]; st = P["st_mask"]
ND, NC = P["close"].shape
O = P["open"].astype(np.float64); H = P["high"].astype(np.float64)
L = P["low"].astype(np.float64); C = P["close"].astype(np.float64)
V = P["vol"].astype(np.float64); AMT = P["amt"].astype(np.float64)
close_ff = pd.DataFrame(C).ffill().to_numpy()
Cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
hist_n = np.cumsum(np.isfinite(O), axis=0)
ELIG = (np.isfinite(O) & np.isfinite(C) & (amt20 >= 5e7)
        & (~st[None, :]) & (hist_n >= 150) & (C > 2.0))
log("elig/day:", int(ELIG[25:].sum(axis=1).mean()))

# ---- 涨停矩阵（主板 10%: ret >= 9.8%）----
with np.errstate(all="ignore"):
    ret = close_ff / Cprev - 1
ZT = (ret >= 0.098) & np.isfinite(ret)

# ---- 因子构造 ----
zt_hist60 = pd.DataFrame(ZT.astype(float)).rolling(60, min_periods=40).sum().to_numpy()
zt_rec5 = pd.DataFrame(ZT.astype(float)).rolling(5, min_periods=3).sum().to_numpy()
# 连板高度: 用累计计数技巧（连续 True 的 run length）
run = np.zeros((ND, NC), dtype=np.float64)
for i in range(1, ND):
    run[i] = np.where(ZT[i], run[i - 1] + 1, 0)
lianban20 = pd.DataFrame(run).rolling(20, min_periods=15).max().to_numpy()
# CMF20
with np.errstate(all="ignore"):
    hl = H - L
    mfv = np.where(hl > 0, ((C - L) - (H - C)) / hl * V, 0.0)
cmf20 = pd.DataFrame(mfv).rolling(20, min_periods=15).sum().to_numpy() / (
    pd.DataFrame(V).rolling(20, min_periods=15).sum().to_numpy() + 1e-9)
cmf5 = pd.DataFrame(mfv).rolling(5, min_periods=4).sum().to_numpy() / (
    pd.DataFrame(V).rolling(5, min_periods=4).sum().to_numpy() + 1e-9)
mf_shift = cmf5 - cmf20
log("factors built")

# ---- A. IC 体检 ----
fwdH = np.full((ND, NC), np.nan); fwdH[:ND-21] = O[21:] / O[1:ND-20] - 1
def rank_ic(mat, mask):
    a = np.where(mask & np.isfinite(mat), mat, np.nan)
    r = pd.DataFrame(a).rank(axis=1).to_numpy()
    zy = pd.DataFrame(np.where(mask & np.isfinite(fwdH), fwdH, np.nan)).rank(axis=1).to_numpy()
    zf = r - np.nanmean(r, axis=1, keepdims=True); zz = zy - np.nanmean(zy, axis=1, keepdims=True)
    zf = zf/(np.nanstd(zf,axis=1,keepdims=True)+1e-12); zz = zz/(np.nanstd(zz,axis=1,keepdims=True)+1e-12)
    both = np.isfinite(zf) & np.isfinite(zz); n = both.sum(axis=1)
    ic = np.where(n>50, np.nansum(np.where(both, zf*zz, 0), axis=1)/np.maximum(n,1), np.nan)
    v = ic[np.isfinite(ic)]
    return float(v.mean()), float(v.mean()/(v.std()+1e-12))
IC = {}
for nm, mat in [("zt_hist60", zt_hist60), ("zt_rec5", zt_rec5), ("lianban20", lianban20),
                ("cmf20", cmf20), ("mf_shift", mf_shift)]:
    ic, icir = rank_ic(mat, ELIG)
    IC[nm] = dict(ic=ic, icir=icir)
    log(f"IC {nm:10s} = {ic:+.4f} ICIR={icir:+.2f}")

# ---- B. 打板场景: 触板股按连板基因分组 → T+1 open→close ----
touch = (H >= Cprev * 1.098) & np.isfinite(Cprev) & ELIG
# 标签: T+1 的 open→close 收益（打板持有到次日收盘；shift(-1) 仅用于评估标签非信号）
nxt_oc = np.full((ND, NC), np.nan)
nxt_oc[:ND-1] = (pd.DataFrame(close_ff).shift(-1).to_numpy()[:ND-1] / O[1:] - 1)
rows = []
for band_lo, band_hi, lbl in [(0, 0.01, "0次"), (0.01, 2.01, "1-2次"), (2.01, 5.01, "3-5次"), (5.01, 999, ">5次")]:
    m = touch & (zt_hist60 > band_lo) & (zt_hist60 <= band_hi) & np.isfinite(nxt_oc)
    n = int(m.sum())
    if n > 0:
        vals = nxt_oc[m]
        rows.append(dict(band=lbl, n=n, mean=float(np.mean(vals)) * 100, med=float(np.median(vals)) * 100,
                         wr=float(np.mean(vals > 0)) * 100))
        log(f"触板 {lbl:6s}: n={n:6d} T+1开→收 mean={np.mean(vals)*100:+.3f}% med={np.median(vals)*100:+.3f}% wr={np.mean(vals>0)*100:.1f}%")
# 对照: 非触板全样本的 T+1 open→close
m0 = (~touch) & ELIG & np.isfinite(nxt_oc)
v0 = nxt_oc[m0]
log(f"非触板对照: n={int(m0.sum())} mean={np.mean(v0)*100:+.3f}% med={np.median(v0)*100:+.3f}% wr={np.mean(v0>0)*100:.1f}%")

out = dict(meta=dict(source="gushi.in 论坛方法论迁移", n_factors=5,
                     note="涨停=前复权比值>=9.8%; 资金流=CMF 价量代理（无Level-2）"),
           ic=IC, touch_by_zt=rows,
           control=dict(n=int(m0.sum()), mean=float(np.mean(v0)) * 100, med=float(np.median(v0)) * 100,
                        wr=float(np.mean(v0 > 0)) * 100))
json.dump(out, open(OUT / "gushi_factors_0913.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1, default=float)
log("saved gushi_factors_0913.json DONE")
