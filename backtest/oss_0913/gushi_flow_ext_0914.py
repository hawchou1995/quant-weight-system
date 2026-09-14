# -*- coding: utf-8 -*-
"""订单流反转因子扩样本验证（2026-09-14）
A: T 日 netbuy 横截面因子（全市场随机抽样 150 只/天 × 最近 45 交易日）
   → 五分位 vs T+1/T+3 收益（检验普适性；活跃股子组单列）
B: T+1 netbuy 留存检验（A 的前 15 天子样本拉 T+1 日）
口径申报：pytdx buyorsell Level-1 代理；随机抽样 seed 固定；面板标签（T 收盘→T+1/T+3 收盘）
"""
import sys, json, time, pickle
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
sys.path.insert(0, str(BASE / "backtest"))
from pytdx_data_0914 import fetch_tick

t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

with open(OUT / "oss_panel_0913.pkl", "rb") as fh:
    P = pickle.load(fh)
cal = P["cal"]; codes = list(P["codes"]); st_mask = P["st_mask"]
ND, NC = P["close"].shape
O = P["open"].astype(np.float64); C = P["close"].astype(np.float64)
AMT = P["amt"].astype(np.float64)
close_ff = pd.DataFrame(C).ffill().to_numpy()
Cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
with np.errstate(all="ignore"):
    chg1 = close_ff / Cprev - 1
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
Hm = P["high"].astype(np.float64)
with np.errstate(all="ignore"):
    touch = (Hm >= Cprev * 1.098) & np.isfinite(Cprev)

_nh = pd.read_csv(BASE / "data_fundamental" / "name_hist.csv", dtype={"code": str}).sort_values("TRADE_DATE").groupby("code").tail(1)
_names = _nh.set_index("code")["SECURITY_NAME_ABBR"].astype(str)
RISK = set(_names[_names.str.contains("ST") | _names.str.contains("退")].index)
risk_mask = np.array([c in RISK for c in codes])

# ---- 样本: 最近 45 交易日（保证 T+3 标签可用）× 每天 150 只随机（主板 elig）----
DAYS = [ND - 4 - k for k in range(45)][::-1]
rng = np.random.default_rng(42)
EV = []
for d in DAYS:
    ok = np.isfinite(C[d]) & (C[d] >= 2) & np.isfinite(amt20[d]) & (amt20[d] >= 5e7) & (~risk_mask)
    cand = np.flatnonzero(ok)
    if len(cand) == 0: continue
    pick = rng.choice(cand, size=min(150, len(cand)), replace=False)
    for j in pick:
        active = bool((chg1[d, j] > 0.05) or touch[d, j]) if np.isfinite(chg1[d, j]) else False
        EV.append((d, int(j), str(codes[int(j)]), active))
log(f"样本: {len(EV)} 事件（{len(DAYS)} 天 × 150）| 活跃股占 {np.mean([e[3] for e in EV])*100:.1f}%")

def metrics(tk):
    if tk is None or len(tk) == 0: return None
    px = pd.to_numeric(tk["price"], errors="coerce").to_numpy()
    vol = pd.to_numeric(tk["vol"], errors="coerce").to_numpy()
    bs = pd.to_numeric(tk["buyorsell"], errors="coerce").to_numpy()
    with np.errstate(all="ignore"):
        amt = px * vol
    total = np.nansum(amt)
    if not np.isfinite(total) or total <= 0: return None
    buy = np.nansum(amt[bs == 0]); sell = np.nansum(amt[bs == 1])
    return dict(netbuy=float((buy - sell) / total), vwap=float(total / np.nansum(vol)) if np.nansum(vol) > 0 else np.nan)

rows = []
for k, (d, j, code, active) in enumerate(EV):
    try:
        tk = fetch_tick(code, int(str(cal[d]).replace("-", "")))
        m = metrics(tk)
    except Exception as e:
        m = None
    time.sleep(0.06)
    if m is None: continue
    pxT = close_ff[d, j]
    r1 = close_ff[d + 1, j] / pxT - 1 if d + 1 < ND else np.nan
    r3 = close_ff[min(d + 3, ND - 1), j] / pxT - 1 if d + 3 < ND else np.nan
    rows.append(dict(date=str(cal[d]), code=code, active=bool(active), netbuy_T=m["netbuy"],
                     vwap_pos=float(pxT / m["vwap"] - 1) if m["vwap"] else np.nan, r1=r1, r3=r3))
    if (k + 1) % 500 == 0:
        log(f"fetched {k+1}/{len(EV)} ok={len(rows)} t={time.time()-t0:.0f}s")

df = pd.DataFrame(rows)
log(f"有效事件: {len(df)}")
df.to_csv(OUT / "gushi_flow_ext_0914.csv", index=False)

def analyze(sub, label):
    if len(sub) < 100:
        log(f"{label}: n={len(sub)} 样本不足"); return None
    sub = sub.copy()
    sub["q"] = pd.qcut(sub["netbuy_T"], 5, labels=False, duplicates="drop")
    res = {}
    for q in sorted(sub["q"].dropna().unique()):
        s2 = sub[sub["q"] == q]
        res[f"Q{int(q)+1}"] = dict(n=int(len(s2)), netbuy=float(s2["netbuy_T"].median()),
                                    r1=float(s2["r1"].mean()), r3=float(s2["r3"].mean()))
        log(f"  {label} Q{int(q)+1}: n={len(s2)} netbuy中位={s2['netbuy_T'].median():+.3f} r1={s2['r1'].mean()*100:+.3f}% r3={s2['r3'].mean()*100:+.3f}%")
    c1 = sub[["netbuy_T", "r1"]].dropna().corr().iloc[0, 1]
    c3 = sub[["netbuy_T", "r3"]].dropna().corr().iloc[0, 1]
    n = int(len(sub))
    t1 = c1 * np.sqrt((n - 2) / max(1e-9, 1 - c1 ** 2)); t3 = c3 * np.sqrt((n - 2) / max(1e-9, 1 - c3 ** 2))
    log(f"  {label}: corr(netbuy,r1)={c1:+.4f} (t={t1:+.1f}) | corr(netbuy,r3)={c3:+.4f} (t={t3:+.1f}) | n={n}")
    return dict(quintiles=res, corr_r1=float(c1), corr_r3=float(c3), t_r1=float(t1), t_r3=float(t3), n=n)

log("=== A: 全样本（随机 45 天）===")
A = analyze(df, "ALL")
log("=== A2: 活跃股子组 ===")
A2 = analyze(df[df["active"]], "ACTIVE")
log("=== A3: 非活跃子组 ===")
A3 = analyze(df[~df["active"]], "QUIET")

# B: T+1 留存检验（前 15 天子样本）
DAYS15 = set(str(cal[d]) for d in DAYS[:15])
sub15 = df[df["date"].isin(DAYS15)]
di_map = {str(c): i for i, c in enumerate(cal)}
ci = {c: i for i, c in enumerate(codes)}
log(f"=== B: T+1 留存检验（{len(sub15)} 事件）===")
rowsB = []
for k, r in enumerate(sub15.itertuples()):
    d = di_map.get(r.date)
    d1 = d + 1 if d is not None else None
    if d1 is None or d1 >= ND: continue
    try:
        tk = fetch_tick(r.code, int(str(cal[d1]).replace("-", "")))
        m = metrics(tk)
    except Exception:
        m = None
    time.sleep(0.06)
    if m is None: continue
    j = ci.get(r.code)
    if j is None: continue
    pxT1 = close_ff[d1, j]
    rb2 = close_ff[d1 + 1, j] / pxT1 - 1 if d1 + 1 < ND else np.nan   # T+1 → T+2
    rb4 = close_ff[min(d1 + 3, ND - 1), j] / pxT1 - 1 if d1 + 3 < ND else np.nan  # T+1 → T+4
    rowsB.append(dict(netbuy_T=r.netbuy_T, netbuy_T1=m["netbuy"], rb2=rb2, rb4=rb4))
    if (k + 1) % 300 == 0:
        log(f"  B fetched {k+1}/{len(sub15)} ok={len(rowsB)}")
dB = pd.DataFrame(rowsB)
B = None
if len(dB) > 100:
    dB["q"] = pd.qcut(dB["netbuy_T1"], 5, labels=False, duplicates="drop")
    resB = {}
    for q in sorted(dB["q"].dropna().unique()):
        s2 = dB[dB["q"] == q]
        resB[f"Q{int(q)+1}"] = dict(n=int(len(s2)), netbuy_T1=float(s2["netbuy_T1"].median()),
                                     rb2=float(s2["rb2"].mean()), rb4=float(s2["rb4"].mean()))
        log(f"  B Q{int(q)+1}: n={len(s2)} netbuyT1中位={s2['netbuy_T1'].median():+.3f} T+2={s2['rb2'].mean()*100:+.3f}% T+4={s2['rb4'].mean()*100:+.3f}%")
    cb2 = dB[["netbuy_T1", "rb2"]].dropna().corr().iloc[0, 1]
    nb = int(len(dB))
    tb2 = cb2 * np.sqrt((nb - 2) / max(1e-9, 1 - cb2 ** 2))
    c12 = dB[["netbuy_T", "netbuy_T1"]].dropna().corr().iloc[0, 1]
    log(f"  B: corr(netbuyT1, T+2收益)={cb2:+.4f} (t={tb2:+.1f}) | corr(T净买,T+1净买)={c12:+.4f} | n={nb}")
    B = dict(quintiles=resB, corr_rb2=float(cb2), t_rb2=float(tb2), retention_corr=float(c12), n=nb)

out = dict(meta=dict(events=len(df), days=len(DAYS), sample_per_day=150, seed=42,
                     note="pytdx buyorsell Level-1 代理; T 收盘→T+1/T+3 收盘"),
           A_all=A, A_active=A2, A_quiet=A3, B_retention=B)
json.dump(out, open(OUT / "gushi_flow_ext_0914.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved gushi_flow_ext_0914.json DONE")
