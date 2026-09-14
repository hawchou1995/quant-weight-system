# -*- coding: utf-8 -*-
"""oss_0913 批10: 打板 × 纳次H GR2/FH 同源验证（待办"打板纳次H GR2/FH 同源"执行）
纳次H 公式（naci_breadth_0911.py 原文，本地可算部分）:
  JX/JX20/JX120 = SUM(V*C,N)/SUM(V,N) 筹码均价; YZ = INDEXC/MA(INDEXC,60) 大盘乖离
  GR2 := C>LLV(C,60)*1.5 AND C>MA(C,60)*1.3 AND C>JX*1.35 AND C=H
  FH  := C>JX*1.25*YZ AND EVERY(C>O,2) AND C>JX120*1.4 AND V>MA(V,5)*1.2
验证: 触板股 (H>=prev*1.098) 按 GR2/FH 状态分组 → T+1 open→close 与 T+1→T+3 收益
对照: 全触板 + 非触板全样本; 主板 5000万地板 2021 起
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
Cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
hist_n = np.cumsum(np.isfinite(O), axis=0)
ELIG = (np.isfinite(O) & np.isfinite(C) & (amt20 >= 5e7)
        & (~st[None, :]) & (hist_n >= 150) & (C > 2.0))

with np.errstate(all="ignore"):
    VC = V * close_ff
    JX = pd.DataFrame(VC).rolling(60, min_periods=40).sum().to_numpy() / (pd.DataFrame(V).rolling(60, min_periods=40).sum().to_numpy() + 1e-9)
    JX20 = pd.DataFrame(VC).rolling(20, min_periods=15).sum().to_numpy() / (pd.DataFrame(V).rolling(20, min_periods=15).sum().to_numpy() + 1e-9)
    JX120 = pd.DataFrame(VC).rolling(120, min_periods=80).sum().to_numpy() / (pd.DataFrame(V).rolling(120, min_periods=80).sum().to_numpy() + 1e-9)
MA60 = pd.DataFrame(close_ff).rolling(60, min_periods=40).mean().to_numpy()
LLV60 = pd.DataFrame(close_ff).rolling(60, min_periods=40).min().to_numpy()
MAV5 = pd.DataFrame(V).rolling(5, min_periods=4).mean().to_numpy()
idx = pd.read_csv(BASE / "index_000300.csv", parse_dates=["date"])
idx["d"] = idx["date"].dt.strftime("%Y-%m-%d")
i300 = idx.drop_duplicates("d").set_index("d")["close"].reindex([d for d in cal]).to_numpy()
YZ = i300 / pd.Series(i300).rolling(60, min_periods=40).mean().to_numpy()

with np.errstate(all="ignore"):
    GR2 = (close_ff > LLV60 * 1.5) & (close_ff > MA60 * 1.3) & (close_ff > JX * 1.35) & (np.abs(H - C) <= 0.01)
    yang = C >= O
    every2 = yang & np.vstack([np.zeros((1, NC), bool), yang[:-1]])
    FH = (close_ff > JX * 1.25 * YZ[:, None]) & every2 & (close_ff > JX120 * 1.4) & (V > MAV5 * 1.2)
GR2 = GR2 & np.isfinite(GR2); FH = FH & np.isfinite(FH)
log("GR2/FH built; daily hits GR2=", int(GR2[150:].sum(axis=1).mean()), "FH=", int(FH[150:].sum(axis=1).mean()))

touch = (H >= Cprev * 1.098) & np.isfinite(Cprev) & ELIG
# 标签: T+1 open→close; T+1 开盘 → T+3 收盘
nxt_oc = np.full((ND, NC), np.nan)
nxt_oc[:ND-1] = pd.DataFrame(close_ff).shift(-1).to_numpy()[:ND-1] / O[1:] - 1
o1 = np.vstack([np.full((1, NC), np.nan), O[1:]])
c3 = np.vstack([np.full((3, NC), np.nan), close_ff[:-3]])
next3 = c3 / o1 - 1

def stat(mask, lbl):
    m1 = mask & np.isfinite(nxt_oc); m3 = mask & np.isfinite(next3)
    if m1.sum() == 0:
        log(f"{lbl}: n=0"); return None
    v1, v3 = nxt_oc[m1], next3[m3]
    r = dict(label=lbl, n=int(m1.sum()),
             oc_mean=float(np.mean(v1)) * 100, oc_med=float(np.median(v1)) * 100, oc_wr=float(np.mean(v1 > 0)) * 100,
             d3_mean=float(np.mean(v3)) * 100, d3_med=float(np.median(v3)) * 100, d3_wr=float(np.mean(v3 > 0)) * 100)
    log(f"{lbl:24s} n={r['n']:6d} | T1 oc: mean={r['oc_mean']:+.3f}% med={r['oc_med']:+.3f}% wr={r['oc_wr']:.1f}% "
        f"| T1→T3: mean={r['d3_mean']:+.3f}% med={r['d3_med']:+.3f}% wr={r['d3_wr']:.1f}%")
    return r

rows = []
rows.append(stat(touch & (~GR2) & (~FH), "触板 无GR2无FH"))
rows.append(stat(touch & GR2 & (~FH), "触板 GR2"))
rows.append(stat(touch & (~GR2) & FH, "触板 FH"))
rows.append(stat(touch & GR2 & FH, "触板 GR2+FH"))
rows.append(stat(touch, "触板 全体"))
rows.append(stat((~touch) & ELIG, "非触板对照"))

out = dict(meta=dict(source="naci_breadth_0911.py 原文 GR2/FH 公式", window="2021 起主板 5000万地板",
                     n_days=ND, note="T1 oc=T+1 open→close; T1→T3=T+1 open→T+3 close"),
           results=[r for r in rows if r])
json.dump(out, open(OUT / "naci_daban_0913.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved naci_daban_0913.json DONE")
