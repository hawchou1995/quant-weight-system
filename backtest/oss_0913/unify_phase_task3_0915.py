# -*- coding: utf-8 -*-
"""任务3：相位口径统一复验（生产 base N10/F60 vs 候选④，同 0..59 网格）
任务4：双轨合并净值（轨A 候选④ + 轨B SUPER+pct40，各 34000 起、相位配对、日收益相关）
"""
import numpy as np, pandas as pd, json, time
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:5.1f}s]", *a, flush=True)

# ================= 轨A 引擎（satellite_opt 前缀 + gate/pct40） =================
srcA = open("satellite_opt_0913.py", encoding="utf-8").read()
exec(srcA.split("# ---- 复现基线")[0])
CASH_A = CASH0
log(f"轨A harness ok | CASH0={CASH_A}")
SPCT_A = pd.DataFrame(np.where(ELIG, SCORE["turn"], np.nan)).rank(axis=1, pct=True).to_numpy()

def run_A(offset=0, use_gate=False, exit_pct40=False, slip=0.0020, cash0=34000.0):
    shares = np.zeros(NC); cost_basis = np.zeros(NC); cash = cash0
    eq_curve = np.full(ND, np.nan); entry_di = np.full(NC, -1)
    pend_buy = []; pend_sell = []; eq_prev = cash0; n_exit = 0
    top = TOP["turn"]
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
            held_n = int((shares > 0).sum())
            slots = 20 if not use_gate else (20 if gate_open[di - 1] else 10)
            for j in pend_buy:
                if held_n >= slots: break
                if shares[j] > 0 or not np.isfinite(px_open[j]) or px_open[j] <= 0.01: continue
                if px_open[j] >= px_prev[j] * 1.098: continue
                lots = math.floor(min(eq_prev / 20, cash) / (px_open[j] * (1 + slip) * 100.0))
                if lots < 1: continue
                px = px_open[j] * (1 + slip); amt = px * lots * 100.0
                fee = max(amt * COMM, MIN_COMM)
                if amt + fee > cash: continue
                cash -= amt + fee; shares[j] = lots * 100.0; cost_basis[j] = amt + fee; entry_di[j] = di - 1
                held_n += 1
            pend_buy = []
        nz = np.flatnonzero(shares)
        eq_prev = cash if len(nz) == 0 else cash + float(np.dot(shares[nz], close_ff[di][nz]))
        eq_curve[di] = eq_prev
        if exit_pct40:
            for j in np.flatnonzero(shares > 0):
                jj = int(j)
                if np.isfinite(SPCT_A[di, jj]) and SPCT_A[di, jj] > 0.40 and jj not in pend_sell:
                    pend_sell.append(jj); n_exit += 1
        if (di - WARMUP - offset) % 30 == 0 and di + 1 < ND:
            tgt = [int(j) for j in top[di][:20]]; tgtS = set(tgt)
            held = np.flatnonzero(shares > 0)
            for j in held:
                if int(j) not in tgtS and int(j) not in pend_sell: pend_sell.append(int(j))
            pend_buy = [j for j in tgt if shares[j] == 0]
    eq = pd.Series(eq_curve[WARMUP:], index=pd.to_datetime(cal[WARMUP:])).ffill().dropna()
    return eq

def run_A_prod(offset, slip=0.0020, cash0=34000.0):
    """生产 base N10/F60（与 satellite_opt run_ln 同逻辑，含 cash0/eq 输出）"""
    shares = np.zeros(NC); cost_basis = np.zeros(NC); cash = cash0
    eq_curve = np.full(ND, np.nan); entry_di = np.full(NC, -1)
    pend_buy = []; pend_sell = []; eq_prev = cash0
    top = TOP["base"]
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
            held_n = int((shares > 0).sum())
            for j in pend_buy:
                if held_n >= 10: break
                if shares[j] > 0 or not np.isfinite(px_open[j]) or px_open[j] <= 0.01: continue
                if px_open[j] >= px_prev[j] * 1.098: continue
                lots = math.floor(min(eq_prev / 10, cash) / (px_open[j] * (1 + slip) * 100.0))
                if lots < 1: continue
                px = px_open[j] * (1 + slip); amt = px * lots * 100.0
                fee = max(amt * COMM, MIN_COMM)
                if amt + fee > cash: continue
                cash -= amt + fee; shares[j] = lots * 100.0; cost_basis[j] = amt + fee; entry_di[j] = di - 1
                held_n += 1
            pend_buy = []
        nz = np.flatnonzero(shares)
        eq_prev = cash if len(nz) == 0 else cash + float(np.dot(shares[nz], close_ff[di][nz]))
        eq_curve[di] = eq_prev
        if (di - WARMUP - offset) % 60 == 0 and di + 1 < ND:
            tgt = [int(j) for j in top[di][:10]]; tgtS = set(tgt)
            held = np.flatnonzero(shares > 0)
            for j in held:
                if int(j) not in tgtS and int(j) not in pend_sell: pend_sell.append(int(j))
            pend_buy = [j for j in tgt if shares[j] == 0]
    return pd.Series(eq_curve[WARMUP:], index=pd.to_datetime(cal[WARMUP:])).ffill().dropna()

def stats(eq):
    ret = eq.pct_change().dropna()
    yrs = len(eq) / 244.0
    ann = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    sh = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    return dict(ann=float(ann), sharpe=float(sh), mdd=float(dd))

# ---- 任务3：同 0..59 网格 ----
log("== 任务3：相位口径统一（0..59 同网格，20bp，cash0=34000）==")
res3 = {}
for tag, fn in [("生产 base N10/F60", lambda o: run_A_prod(o)),
                ("候选④ turn+gate+pct40", lambda o: run_A(o, use_gate=True, exit_pct40=True))]:
    shs, anns = [], []
    for off in range(60):
        s = stats(fn(off))
        shs.append(s["sharpe"]); anns.append(s["ann"])
    res3[tag] = dict(phmed=float(np.median(shs)), phmin=float(min(shs)), phmax=float(max(shs)),
                     ann_med=float(np.median(anns)))
    log(f"{tag:24s} | phmed S={np.median(shs):.3f} (min {min(shs):.2f}/max {max(shs):.2f}) | ann_med {np.median(anns)*100:+.2f}%")
json.dump(res3, open("exit_unify_phase_0915.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("任务3 完成")
