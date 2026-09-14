# -*- coding: utf-8 -*-
"""地量星信号补测（2026-09-14）：停牌偏差量化 + 参数扫描 + KHunter 增量
① 停牌偏差：T+1 停牌被排除的样本量 + 用"停牌恢复后首个可交易日"补测的收益对比
② 参数扫描：vol5/vol20 ∈ {0.4..0.8} × 回撤 ∈ {-5..-20%} 网格 → 5日超额/胜率
③ KHunter 增量：地量星事件 vs KHunter hit 重叠率；两信号事件收益对比（H20/日线）
"""
import numpy as np, pandas as pd, pickle, json, time, sys
from pathlib import Path

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
sys.path.insert(0, str(BASE / "backtest"))
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
ELIG = (np.isfinite(O) & np.isfinite(C) & (amt20 >= 5e7) & (~st[None, :]) & (hist_n >= 150) & (C > 2.0))
v5 = pd.DataFrame(V).rolling(5, min_periods=5).mean().to_numpy()
v20 = pd.DataFrame(V).rolling(20, min_periods=15).mean().to_numpy()
with np.errstate(all="ignore"):
    shrink = v5 / v20
    body = np.abs(C - O) / O
hi20 = pd.DataFrame(C).rolling(20, min_periods=15).max().to_numpy()
with np.errstate(all="ignore"):
    dd20 = close_ff / hi20 - 1

# 修正(0914): 原 vstack 错位（前视伪影）；o1[t]=O[t+1], c5[t]=close[t+5]
o1 = np.full((ND, NC), np.nan); o1[:ND-1] = O[1:]
c5 = np.full((ND, NC), np.nan); c5[:ND-5] = close_ff[5:]
with np.errstate(all="ignore"):
    r5 = c5 / o1 - 1  # T 收盘信号 → T+1 开盘买 → T+5 收盘

SIG0 = (shrink <= 0.6) & (body <= 0.01) & (dd20 <= -0.08) & ELIG & np.isfinite(shrink)

# ---------- ① 停牌偏差 ----------
# 信号事件中 T+1 停牌（o1 NaN）的比例
sig_all = SIG0.copy()
tradable = np.isfinite(o1)
blocked = sig_all & ~tradable
n_sig = int(sig_all[150:].sum()); n_blocked = int(blocked[150:].sum())
log(f"① 停牌偏差: 信号总事件 {n_sig}, T+1 停牌被排除 {n_blocked} ({n_blocked/max(1,n_sig)*100:.2f}%)")
# 被排除样本的"恢复后"表现：找每个被排除事件的下一个可交易日，用其开盘买入 → +4日
rec_ret = []
bi, bj = np.where(blocked[150:])
for k in range(len(bi)):
    d0 = bi[k] + 150; j = bj[k]
    for d1 in range(d0 + 1, min(d0 + 10, ND)):  # 最多等 9 天
        if np.isfinite(O[d1, j]):
            if d1 + 4 < ND and np.isfinite(close_ff[d1 + 4, j]):
                rec_ret.append(close_ff[d1 + 4, j] / O[d1, j] - 1)
            break
rec_arr = np.array(rec_ret)
log(f"   被排除样本恢复后 4 日收益: n={len(rec_arr)}, mean={np.mean(rec_arr)*100:+.3f}%, wr={np.mean(rec_arr>0)*100:.1f}%")
m_ref = sig_all & tradable & np.isfinite(r5)
v_ref = r5[m_ref]
log(f"   可交易样本对照: n={int(m_ref[150:].sum())}, mean={np.mean(v_ref)*100:+.3f}%, wr={np.mean(v_ref>0)*100:.1f}%")

# ---------- ② 参数扫描 ----------
log("② 参数扫描（5日超额 vs 全池同期）...")
base_all = ELIG & np.isfinite(r5)
grid = []
for sh_th in [0.4, 0.5, 0.6, 0.7, 0.8]:
    for dd_th in [-0.05, -0.08, -0.12, -0.15, -0.20]:
        sig = (shrink <= sh_th) & (body <= 0.01) & (dd20 <= dd_th) & ELIG & np.isfinite(shrink)
        m = sig & np.isfinite(r5)
        if m.sum() < 500: continue
        vs = r5[m]
        # 同期超额（逐日基准）
        day_mean = np.where(base_all, np.where(np.isfinite(r5), r5, np.nan), np.nan)
        dm = np.nanmean(day_mean, axis=1)
        sig_days = sig & np.isfinite(r5)
        exc = np.nanmean(np.where(sig_days, r5 - dm[:, None], np.nan))
        grid.append(dict(shrink=sh_th, dd=dd_th, n=int(m.sum()), mean=float(np.mean(vs))*100,
                         med=float(np.median(vs))*100, wr=float(np.mean(vs>0))*100, excess=float(exc)*100))
        log(f"   shrink<={sh_th} dd<={dd_th}: n={int(m.sum()):6d} mean={np.mean(vs)*100:+.3f}% wr={np.mean(vs>0)*100:.1f}% 超额={(exc)*100:+.3f}pp")

# ---------- ③ KHunter 增量 ----------
log("③ KHunter 增量（重叠 + 收益对比）...")
import khunter_all_strategies_backtest as K
import khunter_timing_backtest as T
_nh = pd.read_csv(BASE / "data_fundamental" / "name_hist.csv", dtype={"code": str}).sort_values("TRADE_DATE").groupby("code").tail(1)
_name = _nh.set_index("code")["SECURITY_NAME_ABBR"].astype(str)
ST_SET = set(_name[_name.str.contains("ST")].index)
r20 = np.full((ND, NC), np.nan)
hit20 = np.zeros((ND, NC), dtype=bool)
n_scan = 0
ci = {c: i for i, c in enumerate(codes)}
for f in sorted((BASE / "data_full").glob("*.csv")):
    s = f.stem
    if not s.startswith(("sh600", "sh601", "sh603", "sh605", "sz000", "sz001", "sz002", "sz003")):
        continue
    code6 = s[2:]
    if code6 in ST_SET or code6 not in {c for c in codes}:
        continue
    d = pd.read_csv(f, dtype={"date": str})
    if len(d) < 300 or d["date"].iloc[-1] != "2026-09-11": continue
    if len(d) > ND: d = d.tail(ND)
    n_scan += 1
    d["date"] = pd.to_datetime(d["date"])
    r = T.prep(d)
    sig_any = np.zeros(len(d), dtype=bool)
    for nm, fn in K.SIGNALS.items():
        try:
            sv = fn(r)
            sig_any |= sv.values
        except Exception:
            continue
    j = ci.get(code6)
    if j is not None:
        m = min(len(d), ND)
        hit20[ND - m:, j] = sig_any[-m:]
    if n_scan % 800 == 0: log(f"   khunter scan {n_scan} t={time.time()-t0:.0f}s")
log(f"   khunter hit 覆盖: {n_scan} 只扫描, hit 日数={int(hit20[150:].sum())}")

# 重叠: 地量星事件中有多少同时 khunter hit
ov = (SIG0 & hit20 & np.isfinite(r5))
log(f"   重叠（地量星 ∧ khunter）: n={int(ov[150:].sum())}")
m_a = SIG0 & np.isfinite(r5); m_k = hit20 & np.isfinite(r5) & ELIG
for nm, m in [("地量星", m_a), ("KHunter", m_k), ("重叠", ov)]:
    if m.sum() > 0:
        v = r5[m]
        log(f"   {nm:8s} 5日: n={int(m.sum()):6d} mean={np.mean(v)*100:+.3f}% wr={np.mean(v>0)*100:.1f}%")

out = dict(
    frozen=dict(n_sig=n_sig, n_blocked=n_blocked, blocked_pct=n_blocked/max(1,n_sig)*100,
                blocked_recover_mean=float(np.mean(rec_arr))*100 if len(rec_arr) else None,
                blocked_recover_wr=float(np.mean(rec_arr>0))*100 if len(rec_arr) else None,
                tradable_mean=float(np.mean(v_ref))*100, tradable_wr=float(np.mean(v_ref>0))*100,
                tradable_n=int(m_ref[150:].sum())),
    grid=grid,
    khunter=dict(scanned=n_scan, overlap_n=int(ov[150:].sum()),
                 hit_days=int(hit20[150:].sum())))
json.dump(out, open(OUT / "br7uce_audit_0914.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved br7uce_audit_0914.json DONE")
