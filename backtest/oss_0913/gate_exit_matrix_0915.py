# -*- coding: utf-8 -*-
"""轨A：闸门(use_gate) × pct40(exit) × 成本档 组合矩阵（补齐闸门结论）
口径：turn N20/F30，30 相位；闸门=sc1000 MA20 下方时只持 N/2（半仓）
"""
import numpy as np, json, time
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:5.1f}s]", *a, flush=True)

src = open("satellite_opt_0913.py", encoding="utf-8").read()
exec(src.split("# ---- 复现基线")[0])
SPCT = None
S_ALL = SCORE["turn"]
SPCT = pd.DataFrame(np.where(ELIG, S_ALL, np.nan)).rank(axis=1, pct=True).to_numpy()

def run(tag, exit_pct40=False, use_gate=False, slip=0.0020, offset=0):
    shares = np.zeros(NC); cost_basis = np.zeros(NC)
    cash = CASH0; eq_curve = np.full(ND, np.nan); trades = []
    entry_di = np.full(NC, -1); pend_buy = []; pend_sell = []
    eq_prev = CASH0; n_exit = 0
    top = TOP["turn"]
    for di in range(WARMUP, ND):
        px_open = O[di]; px_prev = close_ff[di - 1]
        if pend_sell:
            keep = []
            for j in pend_sell:
                if not np.isfinite(px_open[j]) or px_open[j] <= px_prev[j] * 0.902: keep.append(j); continue
                px = px_open[j] * (1 - slip); amt = px * shares[j]
                fee = max(amt * COMM, MIN_COMM) + amt * TAX
                cash += amt - fee
                shares[j] = 0.0; cost_basis[j] = 0.0; entry_di[j] = -1
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
                if np.isfinite(SPCT[di, jj]) and SPCT[di, jj] > 0.40 and jj not in pend_sell:
                    pend_sell.append(jj); n_exit += 1
        if (di - WARMUP - offset) % 30 == 0 and di + 1 < ND:
            tgt = [int(j) for j in top[di][:20]]; tgtS = set(tgt)
            held = np.flatnonzero(shares > 0)
            for j in held:
                if int(j) not in tgtS and int(j) not in pend_sell: pend_sell.append(int(j))
            pend_buy = [j for j in tgt if shares[j] == 0]
    eq = pd.Series(eq_curve[WARMUP:], index=pd.to_datetime(cal[WARMUP:])).ffill().dropna()
    ret = eq.pct_change().dropna()
    yrs = len(eq) / 244.0
    ann = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    sharpe = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    return dict(ann=float(ann), sharpe=float(sharpe), mdd=float(dd), n_exit=n_exit)

MATRIX = [
    ("ungated+base 20bp", dict()),
    ("gated+base   20bp", dict(use_gate=True)),
    ("ungated+pct40 20bp", dict(exit_pct40=True)),
    ("gated+pct40  20bp", dict(exit_pct40=True, use_gate=True)),
    ("ungated+base 50bp", dict(slip=0.0050)),
    ("gated+base   50bp", dict(use_gate=True, slip=0.0050)),
    ("ungated+pct40 50bp", dict(exit_pct40=True, slip=0.0050)),
    ("gated+pct40  50bp", dict(exit_pct40=True, use_gate=True, slip=0.0050)),
]
res = {}
for tag, kw in MATRIX:
    shs, anns, mdd = [], [], []
    o0 = None
    for off in range(30):
        m = run(tag, offset=off, **kw)
        shs.append(m["sharpe"]); anns.append(m["ann"]); mdd.append(m["mdd"])
        if off == 0: o0 = m
    res[tag] = dict(phmed=float(np.median(shs)), phmin=float(min(shs)), phmax=float(max(shs)),
                    phmed_ann=float(np.median(anns)), off0=o0)
    log(f"{tag:20s} | phmed S={np.median(shs):.3f} (min {min(shs):.2f}/max {max(shs):.2f}) | off0 ann {o0['ann']*100:+.2f}% S={o0['sharpe']:.2f} mdd {o0['mdd']*100:.1f}%")
json.dump(res, open("gate_exit_matrix_0915.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved gate_exit_matrix_0915.json")
