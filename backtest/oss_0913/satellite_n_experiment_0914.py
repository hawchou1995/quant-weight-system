# -*- coding: utf-8 -*-
"""双轨卫星持仓数实验（2026-09-14，用户问：只买 2-10 只？一行业一只买 2-5 只？）
轨A（冷门低波 turn 因子 rank(amt20)+rank(atr20)+rank(turn20)）与轨B（SUPER 13 因子 composite）
  × N ∈ {2,3,5,10,20} × 行业约束 {无, 每行业最多1只}
回测：分段（F=30 期，T 收盘选 Top-N → T+1 开盘买 → 持有 30 日 → 换仓，成本 1.15%/期），全相位
口径：主板（轨A 全池 3469 由 val_em+补齐；轨B 用 SUPER 的 elig）
"""
import numpy as np, pandas as pd, pickle, json, math, time
from pathlib import Path

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
FL = BASE / "backtest" / "factorlab_0913"
OUT = BASE / "backtest" / "oss_0913"
COST = 0.0115
H = 20
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

with open(OUT / "oss_panel_0913.pkl", "rb") as fh:
    P = pickle.load(fh)
with open(FL / "panel_0913.pkl", "rb") as fh:
    FP = pickle.load(fh)
cal = P["cal"]; codes = list(P["codes"]); st_mask = P["st_mask"]
ND, NC = P["close"].shape
O = P["open"].astype(np.float64); C = P["close"].astype(np.float64)
Hm = P["high"].astype(np.float64); Lm = P["low"].astype(np.float64)
V = P["vol"].astype(np.float64); AMT = P["amt"].astype(np.float64); FMV = P["fmv"].astype(np.float64)
close_ff = pd.DataFrame(C).ffill().to_numpy()
hist_n = np.cumsum(np.isfinite(O), axis=0)
# 行业映射（申万一级）
im = json.load(open(BASE / "stock_industry.json", encoding="utf-8"))["map"]
inds = sorted(set(im.values())); i2i = {n: i for i, n in enumerate(inds)}
ind_id = np.array([i2i.get(im.get(c, "其他"), i2i.get("其他")) for c in codes])
# 风险过滤（ST/退）
_nh = pd.read_csv(BASE / "data_fundamental" / "name_hist.csv", dtype={"code": str}).sort_values("TRADE_DATE").groupby("code").tail(1)
_nm = _nh.set_index("code")["SECURITY_NAME_ABBR"].astype(str)
RISK = set(_nm[_nm.str.contains("ST") | _nm.str.contains("退")].index)
risk_mask = np.array([c in RISK for c in codes])

# ---------- 因子 ----------
# 轨A: turn 因子（rank 和，升序优选）
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
turn20 = pd.DataFrame(np.where(FMV > 0, AMT / FMV * 100, np.nan)).rolling(20, min_periods=15).mean().to_numpy()
Cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
with np.errstate(all="ignore"):
    TR = np.maximum.reduce([Hm - Lm, np.abs(Hm - Cprev), np.abs(Lm - Cprev)])
atr20 = pd.DataFrame(TR).rolling(20, min_periods=15).mean().to_numpy() / close_ff
ELIG_A = (np.isfinite(O) & np.isfinite(C) & np.isfinite(amt20) & (amt20 >= 3e6)
          & (~risk_mask[None, :]) & (hist_n >= 30) & (C >= 2.0))
def rk(M, elig): return pd.DataFrame(np.where(elig, M, np.nan)).rank(axis=1, pct=True).to_numpy()
_r_turn = rk(turn20, ELIG_A); _r_turn = np.where(np.isfinite(_r_turn), _r_turn, 0.5)
S_A = rk(amt20, ELIG_A) + rk(atr20, ELIG_A) + _r_turn  # 低者优先
# 轨B: SUPER 13 因子 composite（复用生产模块）
import sys
sys.path.insert(0, str(OUT))
from oss_super_prod_0913 import COMP_SUPER, ELIG_SUPER, SIGN
S_B = COMP_SUPER  # 高者优先
ELIG_B = ELIG_SUPER
log("factors ready: A(amt+atr+turn) | B(SUPER 13)")

# ---------- 分段引擎（支持行业约束） ----------
def seg_backtest(score, elig, N, ascending, cap_one_per_industry, offset=0, F=H):
    n_seg = (ND - 1 - F - offset) // F
    rs = []
    for s in range(n_seg):
        t = offset + s * F
        ok = elig[t] & np.isfinite(score[t])
        cand = np.flatnonzero(ok)
        if len(cand) == 0:
            rs.append(0.0); continue
        sc = score[t][cand]
        order = cand[np.argsort(sc if ascending else -sc)]
        if cap_one_per_industry:
            seen = set(); pick = []
            for j in order:
                g = ind_id[j]
                if g in seen: continue
                seen.add(g); pick.append(j)
                if len(pick) >= N: break
            ordj = np.array(pick)
        else:
            ordj = order[:N]
        o1 = O[t + 1][ordj]; oH = O[min(t + 1 + F, ND - 1)][ordj]
        with np.errstate(all="ignore"):
            r = oH / o1 - 1
        r = r[np.isfinite(r)]
        rs.append(float(np.mean(r)) - COST if len(r) else 0.0)
    arr = np.array(rs)
    if len(arr) == 0: return None
    eq = np.cumprod(1 + arr)
    yrs = len(arr) * F / 244.0
    ann = (eq[-1]) ** (1 / yrs) - 1 if yrs > 0 and eq[-1] > 0 else -1
    sh = float(np.mean(arr) / (np.std(arr) + 1e-12) * np.sqrt(244 / F))
    mdd = float((eq / np.maximum.accumulate(eq) - 1).min())
    return dict(total=float(eq[-1] - 1), ann=float(ann), sharpe=sh, mdd=mdd, n_seg=len(arr))

def run_arm(score, elig, N, ascending, cap, F=H):
    shs, offs = [], []
    for off in range(F):
        m = seg_backtest(score, elig, N, ascending, cap, offset=off, F=F)
        if m: shs.append(m["sharpe"]); offs.append(m)
    if not offs: return None
    return dict(off0=offs[0], phmed_sharpe=float(np.median(shs)), phmin=float(min(shs)), phmax=float(max(shs)))

results = []
for track, score, elig, ascending in [("B_SUPER", S_B, ELIG_B, False)]:
    for N in [2, 3, 5, 10, 20]:
        for cap in [False, True]:
            # 行业约束（cap=True）在小 N 时才有意义；全跑作对照
            r = run_arm(score, elig, N, ascending, cap)
            if r is None: continue
            lbl = f"{track} N={N} {'行业1只' if cap else '无约束'}"
            results.append(dict(track=track, N=N, cap=cap, **r))
            log(f"{lbl:28s} | off0 S={r['off0']['sharpe']:+.3f} ann={r['off0']['ann']*100:+7.2f}% mdd={r['off0']['mdd']*100:5.1f}% | phmed S={r['phmed_sharpe']:+.3f} phmin={r['phmin']:+.2f}")

json.dump(dict(meta=dict(H=H, cost=COST, n_trials=len(results)), results=results),
          open(OUT / "satellite_n_f20_0914.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved satellite_n_f20_0914.json DONE")
