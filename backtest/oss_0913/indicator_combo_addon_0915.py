# -*- coding: utf-8 -*-
"""指标组合 · 第二步：ρ 检查 + 加进 SUPER 13 的增量测试（≤8 臂预算内）"""
import sys, json, time, math
import numpy as np, pandas as pd
from pathlib import Path
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
sys.path.insert(0, str(OUT))
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)
exec(open(OUT / "fib_combo_0914.py", encoding="utf-8").read())   # 复用引擎（会重跑其臂 ~13s）
COMP = S.COMP_SUPER
S_OHLC = (S.O, S.H, S.L, S.C, S.close_ff)
O2 = S.O; H2 = S.H; L2 = S.L; C2 = S.C; close_ff2 = S.close_ff
ELIG2 = S.ELIG_SUPER; ND2, NC2 = S.ND, S.NC

Sdf = pd.DataFrame(close_ff2)
d_ = Sdf.diff(); ru = d_.clip(lower=0).ewm(alpha=1/14, adjust=False).mean(); rd = (-d_).clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
RSI = (100 - 100 / (1 + ru / rd.replace(0, np.nan))).to_numpy()
e12 = Sdf.ewm(span=12, adjust=False).mean(); e26 = Sdf.ewm(span=26, adjust=False).mean()
DIF = (e12 - e26).to_numpy(); DEA = pd.DataFrame(DIF).ewm(span=9, adjust=False).mean().to_numpy()
MACD_DIF = np.where(np.isfinite(close_ff2) & (close_ff2 > 0), DIF / close_ff2 * 100, np.nan)
MACD_HIST = np.where(np.isfinite(close_ff2) & (close_ff2 > 0), (DIF - DEA) / close_ff2 * 100, np.nan)
NEW = {"rsi14": RSI, "macd_dif": MACD_DIF, "macd_hist": MACD_HIST}

sample = np.arange(S.WARMUP, ND2, 3)
def zmat(m, sgn=1.0):
    a = (m * sgn)[sample]; a = np.where(np.isfinite(a) & ELIG2[sample], a, np.nan)
    mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
    return np.clip((a - mu) / (sd + 1e-12), -8, 8)

EV = {k: rank_ic(m) for k, m in NEW.items()}
log("ρ 检查（vs picked 13 + COMP 自身）:")
survivors = []
for k, m in NEW.items():
    ZN = zmat(m, 1.0 if EV[k][0] >= 0 else -1.0)
    worst = []
    for rk in S.PICKED:
        Zk = zmat(S.ALL[rk]); mm = np.isfinite(ZN) & np.isfinite(Zk)
        if mm.sum() > 500: worst.append((rk, float(np.corrcoef(ZN[mm], Zk[mm])[0, 1])))
    worst.sort(key=lambda x: -abs(x[1]))
    mx = abs(worst[0][1]) if worst else 0.0
    ok = mx < 0.6
    if ok: survivors.append(k)
    log(f"  {k:10s} ρmax={mx:.3f}（{worst[0][0]}）→ {'进增量测试' if ok else '冗余筛除'}")

res = dict(ic={k: EV[k] for k in NEW}, survivors=survivors)
if survivors:
    # 增量：13 + survivor（各占 15% 份额，多者均分）
    LAM = 0.15
    Wn = {k: v * (1 - LAM) for k, v in S.WEIGHTS.items()}
    raw = {k: max(abs(EV[k][1]), 0.01) for k in survivors}
    sr = sum(raw.values())
    for k in survivors: Wn[k] = raw[k] / sr * LAM
    def comp14():
        num = np.zeros((ND2, NC2)); den = np.zeros((ND2, NC2))
        for k, w in Wn.items():
            mat = NEW[k] if k in NEW else S.ALL[k]
            sgn = (1.0 if EV[k][0] >= 0 else -1.0) if k in NEW else S.SIGN[k]
            a = np.where(ELIG2, mat * sgn, np.nan)
            mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
            z = np.clip((a - mu) / (sd + 1e-12), -3, 3)
            okf = np.isfinite(z)
            num += np.where(okf, z * w, 0.0); den += np.where(okf, w, 0.0)
        return np.where(den > 0.4, num / np.maximum(den, 1e-9), np.nan)
    C_new = comp14()
    shs = [run_engine(C_new, 20, offset=o)["sharpe"] for o in range(20)]
    o0 = run_engine(C_new, 20, offset=0)
    m50 = run_engine(C_new, 20, offset=0, slip=SLIP_STRESS)
    res["addon"] = dict(survivors=survivors, phmed=float(np.median(shs)), phmin=float(min(shs)), phmax=float(max(shs)),
                        off0=dict(ann=o0["ann"], sharpe=o0["sharpe"], mdd=o0["mdd"]),
                        slip50=dict(ann=m50["ann"], sharpe=m50["sharpe"]))
    log(f"增量（13+{survivors}）：phmed S={np.median(shs):.3f} (min {min(shs):.2f}/max {max(shs):.2f}) | off0 年化 {o0['ann']*100:+.2f}% S={o0['sharpe']:.2f} | 50bp S={m50['sharpe']:.2f}")
    log(f"对照 SUPER 13 基线：phmed 1.151 / off0 22.87%/1.297 / 50bp 1.004")
else:
    log("无幸存者（全部冗余）→ 无增量测试")
json.dump(res, open(OUT / "indicator_combo_addon_0915.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved indicator_combo_addon_0915.json")
