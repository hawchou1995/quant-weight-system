# -*- coding: utf-8 -*-
"""oss_0913 批11: Br7uce 短线方法论迁移验证（B站 EP03）
可测信号（本地日线）:
  A. 缩量地量十字星（4/7 券商案例的一般化）:
     地量 = vol5/vol20 <= 0.6; 十字星 = |C-O|/O <= 1%; 超跌 = 20日回撤 <= -8%
  B. 高低切弱化版（板块内落后补涨）: 行业内 ret20 最低分位（下方 20%）× 行业 ret20 为正
评估: 信号日 T → T+1 开盘买入 → T+5/T+10 收益 vs 全池基准; 主板 5000万地板 2021 起
"""
import numpy as np, pandas as pd, pickle, json, time
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
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
hist_n = np.cumsum(np.isfinite(O), axis=0)
ELIG = (np.isfinite(O) & np.isfinite(C) & (amt20 >= 5e7)
        & (~st[None, :]) & (hist_n >= 150) & (C > 2.0))

v5 = pd.DataFrame(V).rolling(5, min_periods=5).mean().to_numpy()
v20 = pd.DataFrame(V).rolling(20, min_periods=15).mean().to_numpy()
with np.errstate(all="ignore"):
    shrink = v5 / v20
    body = np.abs(C - O) / O
    dd20 = close_ff / pd.DataFrame(C).rolling(20, min_periods=15).max().to_numpy() - 1
SIG_A = (shrink <= 0.6) & (body <= 0.01) & (dd20 <= -0.08) & ELIG & np.isfinite(shrink)
log("信号A 日均数量:", int(SIG_A[150:].sum(axis=1).mean()), "| 总事件:", int(SIG_A[150:].sum()))

# 收益标签: T+1 开盘 → T+1+4 收盘 (5日) / T+1+9 收盘 (10日)
# 修正(0914): 原 vstack 错位（o1[t]=O[t] 应为 O[t+1]; c5[t]=close[t-5] 应为 close[t+5]）——前视伪影修复
o1 = np.full((ND, NC), np.nan); o1[:ND-1] = O[1:]
c5 = np.full((ND, NC), np.nan); c5[:ND-5] = close_ff[5:]
c10 = np.full((ND, NC), np.nan); c10[:ND-10] = close_ff[10:]
with np.errstate(all="ignore"):
    r5 = c5 / o1 - 1   # T 收盘信号 → T+1 开盘买 → T+5 收盘
    r10 = c10 / o1 - 1

def stat(mask, lbl):
    m5 = mask & np.isfinite(r5); m10 = mask & np.isfinite(r10)
    if m5.sum() == 0: log(lbl, "n=0"); return None
    v_5, v_10 = r5[m5], r10[m10]
    r = dict(label=lbl, n=int(m5.sum()), r5_mean=float(np.mean(v_5))*100, r5_med=float(np.median(v_5))*100,
             r5_wr=float(np.mean(v_5>0))*100, r10_mean=float(np.mean(v_10))*100, r10_med=float(np.median(v_10))*100,
             r10_wr=float(np.mean(v_10>0))*100)
    log(f"{lbl:22s} n={r['n']:6d} | 5日 mean={r['r5_mean']:+.3f}% med={r['r5_med']:+.3f}% wr={r['r5_wr']:.1f}% | 10日 mean={r['r10_mean']:+.3f}% wr={r['r10_wr']:.1f}%")
    return r

rows = []
rows.append(stat(SIG_A, "A: 缩量地量十字星"))
rows.append(stat(SIG_A & (dd20 <= -0.15), "A变体: 深超跌(>=15%)"))
rows.append(stat(SIG_A & (dd20 > -0.15), "A变体: 浅超跌(8-15%)"))
rows.append(stat(ELIG & np.isfinite(r5), "基准: 全池全体"))

# B: 板块内落后（行业代理: 用 stock_industry + ret20 截面）
im = json.load(open(BASE / "stock_industry.json", encoding="utf-8"))["map"]
inds = sorted(set(im.values())); i2i = {n: i for i, n in enumerate(inds)}
ind_id = np.array([i2i.get(im.get(c, "其他"), i2i.get("其他")) for c in codes])
ret20 = close_ff / pd.DataFrame(close_ff).shift(20).to_numpy() - 1
ind_ret20 = np.full((ND, len(inds)), np.nan)
for g in range(len(inds)):
    m = ind_id == g
    if m.sum() == 0: continue
    with np.errstate(all="ignore"):
        ind_ret20[:, g] = np.nanmedian(np.where(np.isfinite(ret20[:, m]), ret20[:, m], np.nan), axis=1)
ind_r = ind_ret20[:, ind_id]
with np.errstate(all="ignore"):
    ind_rel = ret20 - ind_r  # 行业内相对强度
rk_rel = pd.DataFrame(np.where(ELIG & np.isfinite(ind_rel), ind_rel, np.nan)).rank(axis=1, pct=True).to_numpy()
SIG_B = (rk_rel <= 0.2) & (ind_r > 0) & ELIG & np.isfinite(ind_r)  # 行业正动量 + 行业内落后 20%
rows.append(stat(SIG_B, "B: 板块内高低切(落后)"))

out = dict(meta=dict(source="B站 BV1NQ92BkEaT Br7uce EP03", window="2021 起主板 5000万",
                     note="T+1 开盘买 → T+1+4/T+1+9 收盘; 申报: 十字星阈值 1%/地量 0.6 为原文案例参数近似"),
           results=[r for r in rows if r])
json.dump(out, open(OUT / "br7uce_signals_0913.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved br7uce_signals_0913.json DONE")
