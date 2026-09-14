# -*- coding: utf-8 -*-
"""任务3b：相位统一网格 @1M 口径（隔离相位效应）
任务4：双轨合并净值（轨A候选④ + 轨B SUPER+pct40，各 34000，相位配对，含相关）"""
import numpy as np, pandas as pd, json, time, sys
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:5.1f}s]", *a, flush=True)

# ---- 轨A 引擎（复用 unify 脚本中的定义）----
exec(open("unify_phase_task3_0915.py", encoding="utf-8").read().split("# ---- 任务3")[0])

log("== 任务3b：0..59 同网格 @1M（隔离相位效应）==")
res3b = {}
for tag, fn in [("生产 base N10/F60", lambda o: run_A_prod(o, cash0=1_000_000.0)),
                ("候选④ turn+gate+pct40", lambda o: run_A(o, use_gate=True, exit_pct40=True, cash0=1_000_000.0))]:
    shs, anns = [], []
    for off in range(60):
        s = stats(fn(off))
        shs.append(s["sharpe"]); anns.append(s["ann"])
    res3b[tag] = dict(phmed=float(np.median(shs)), phmin=float(min(shs)), phmax=float(max(shs)), ann_med=float(np.median(anns)))
    log(f"{tag:24s} | phmed S={np.median(shs):.3f} (min {min(shs):.2f}/max {max(shs):.2f}) | ann_med {np.median(anns)*100:+.2f}%")

# ---- 轨B 引擎（SUPER + pct40）----
sys.path.insert(0, ".")
import oss_super_prod_0913 as S
COMP = S.COMP_SUPER; ELIG = S.ELIG_SUPER
O = S.O; C = S.C; close_ff = S.close_ff; cal = S.cal
ND, NC = S.ND, S.NC; WARMUP = S.WARMUP
COMM, TAX, SLIP, MIN_COMM = 0.00025, 0.0005, 0.0020, 5.0
N, F = 20, 20
_base = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
def etf_series(fn, col):
    df = pd.read_csv(_base + "/data_full/" + fn, parse_dates=["date"])
    df["d"] = df["date"].dt.strftime("%Y-%m-%d")
    return df.drop_duplicates("d").set_index("d")[col].reindex([d for d in cal]).to_numpy()
sc1000 = etf_series("sh512100.csv", "close")
ma20sc = pd.Series(sc1000).rolling(20, min_periods=15).mean().to_numpy()
_ret1 = pd.DataFrame(close_ff).pct_change()
_v20f = (-_ret1.rolling(20, min_periods=15).std()).to_numpy()
volpct = pd.DataFrame(np.where(ELIG, _v20f, np.nan)).rank(axis=1, pct=True).to_numpy()
SPCT = pd.DataFrame(np.where(ELIG & np.isfinite(COMP), COMP, np.nan)).rank(axis=1, pct=True).to_numpy()
_cp = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
with np.errstate(all="ignore"):
    TR = np.maximum.reduce([S.H - S.L, np.abs(S.H - _cp), np.abs(S.L - _cp)])
    ATRP = pd.DataFrame(TR).rolling(20, min_periods=15).mean().to_numpy() / np.where(close_ff > 0, close_ff, np.nan)
ATRMED = pd.DataFrame(ATRP).rolling(60, min_periods=40).median().to_numpy()
AMP2X = np.isfinite(ATRP) & np.isfinite(ATRMED) & (ATRP > 2 * ATRMED)
MA20 = pd.DataFrame(close_ff).rolling(20, min_periods=15).mean().to_numpy()
MA20_BRK = np.isfinite(MA20) & (close_ff < MA20)
ORDERB = np.argsort(np.where(ELIG & np.isfinite(COMP), -COMP, -np.inf), axis=1)
IN2N = np.zeros((ND, NC), dtype=bool)
for di in range(ND): IN2N[di, ORDERB[di][:40]] = True

mine_all = open("exit_lab_trackB_0915.py", encoding="utf-8").read().splitlines()
i0 = next(i for i, l in enumerate(mine_all) if l.startswith("def run_exit"))
i1 = next(i for i, l in enumerate(mine_all) if l.startswith("res = {}"))
exec("\n".join(mine_all[i0:i1]).replace("def run_exit(", "def run_B("))
log("轨B 引擎就绪")

def run_B_eq(offset, cash0=34000.0, slip=0.0020):
    """同 run_B 逻辑，输出净值序列（复制主体，返回 eq）"""
    shares = np.zeros(NC); cost_basis = np.zeros(NC); cash = cash0
    eq_curve = np.full(ND, np.nan); entry_di = np.full(NC, -1)
    pend_buy = []; pend_sell = []; eq_prev = cash0
    for di in range(WARMUP, ND):
        px_open = O[di]; px_prev = close_ff[di - 1]
        if pend_sell:
            keep = []
            for j in pend_sell:
                if not np.isfinite(px_open[j]) or px_open[j] <= px_prev[j] * 0.902: keep.append(j); continue
                px = px_open[j] * (1 - slip); amt = px * shares[j]
                fee = max(amt * COMM, MIN_COMM) + amt * TAX
                cash += amt - fee; shares[j] = 0.0; cost_basis[j] = 0.0; entry_di[j] = -1
            pend_sell = keep
        if pend_buy:
            for j in pend_buy:
                if shares[j] > 0 or not np.isfinite(px_open[j]) or not ELIG[di - 1][j]: continue
                if px_open[j] >= px_prev[j] * 1.098 or px_open[j] <= 0.01: continue
                lots = math.floor(min(eq_prev / 20, cash) / (px_open[j] * (1 + slip) * 100.0))
                if lots < 1: continue
                px = px_open[j] * (1 + slip); amt = px * lots * 100.0
                fee = max(amt * COMM, MIN_COMM)
                if amt + fee > cash: continue
                cash -= amt + fee; shares[j] = lots * 100.0; cost_basis[j] = amt + fee; entry_di[j] = di - 1
            pend_buy = []
        nz = np.flatnonzero(shares)
        eq_prev = cash if len(nz) == 0 else cash + float(np.dot(shares[nz], close_ff[di][nz]))
        eq_curve[di] = eq_prev
        for j in np.flatnonzero(shares > 0):
            jj = int(j)
            if np.isfinite(SPCT[di, jj]) and SPCT[di, jj] <= 0.60 and jj not in pend_sell:
                pend_sell.append(jj)
        if (di - WARMUP - offset) % F == 0 and di + 1 < ND:
            row = COMP[di]; ok = ELIG[di] & np.isfinite(row)
            gate_open = bool(np.isfinite(ma20sc[di]) and sc1000[di] > ma20sc[di])
            if ok.sum() >= 20:
                cand = np.flatnonzero(ok)
                if gate_open: N_eff = 20; sel = cand
                else:
                    N_eff = max(2, 10); sel = cand
                    sub = cand[np.isfinite(volpct[di][cand]) & (volpct[di][cand] <= 0.5)]
                    if len(sub) >= N_eff: sel = sub
                ordj = sel[np.argsort(-row[sel])]
                topN = [int(j) for j in ordj[:N_eff]]; topS = set(topN)
                held = np.flatnonzero(shares > 0)
                for j in held:
                    if int(j) not in topS and int(j) not in pend_sell: pend_sell.append(int(j))
                n_after = int(len([j for j in held if int(j) in topS]))
                pend_buy = [j for j in topN if shares[j] == 0][:max(0, N_eff - n_after)]
    return pd.Series(eq_curve[WARMUP:], index=pd.to_datetime(cal[WARMUP:])).ffill().dropna()

# ---- 任务4：合并（相位配对 o=0..19，各 34000）----
log("== 任务4：双轨合并净值（各 34000，相位配对 0..19）==")
comb_sh, comb_ann, comb_mdd, corrs = [], [], [], []
a_sh, b_sh = [], []
for o in range(20):
    eqA = run_A(o, use_gate=True, exit_pct40=True, cash0=34000.0)
    eqB = run_B_eq(o, cash0=34000.0)
    idx = eqA.index.intersection(eqB.index)
    a = eqA.reindex(idx); b = eqB.reindex(idx)
    a = a / a.iloc[0] * 34000.0; b = b / b.iloc[0] * 34000.0
    comb = a + b
    s = stats(comb); comb_sh.append(s["sharpe"]); comb_ann.append(s["ann"]); comb_mdd.append(s["mdd"])
    ra, rb = a.pct_change().dropna(), b.pct_change().dropna()
    corrs.append(float(ra.corr(rb)))
    sa, sb = stats(eqA), stats(eqB)
    a_sh.append(sa["sharpe"]); b_sh.append(sb["sharpe"])
    if o == 0:
        log(f"  off0: 轨A S={sa['sharpe']:.2f}/ann {sa['ann']*100:+.2f}% | 轨B S={sb['sharpe']:.2f}/ann {sb['ann']*100:+.2f}% | 合并 S={s['sharpe']:.2f}/ann {s['ann']*100:+.2f}%/mdd {s['mdd']*100:.1f}% | ρ={corrs[-1]:+.3f}")
res4 = dict(a_phmed=float(np.median(a_sh)), b_phmed=float(np.median(b_sh)),
            comb_phmed=float(np.median(comb_sh)), comb_ann=float(np.median(comb_ann)),
            comb_mdd=float(np.median(comb_mdd)), rho_med=float(np.median(corrs)),
            rho_min=float(min(corrs)), rho_max=float(max(corrs)))
log(f"相位中位: 轨A S={res4['a_phmed']:.3f} | 轨B S={res4['b_phmed']:.3f} | 合并 S={res4['comb_phmed']:.3f} (ann {res4['comb_ann']*100:+.2f}% / mdd {res4['comb_mdd']*100:.1f}%) | ρ 中位 {res4['rho_med']:+.3f} (范围 {res4['rho_min']:+.3f}~{res4['rho_max']:+.3f})")
json.dump(dict(task3b=res3b, task4=res4), open("dual_track_combined_0915.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved dual_track_combined_0915.json")
