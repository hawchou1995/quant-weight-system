# -*- coding: utf-8 -*-
"""C3 仓位结构回测（R-position-0915）· 轨A 冷门低波 turn/N20/F30 全 30 相位
预注册 3 规则 + 组合臂（只新建本文件，复用 satellite_opt 前缀 exec harness，不改既有文件）：
  C3a 回撤阶梯减仓：净值自峰值回撤触及 -8% → 新开仓预算 1/2；-12% → 1/4；-15% → 停止新开仓（持仓不动、出场照常）；回撤回升至 -6% 以内 → 恢复正常（-8~-6 为滞回带，保持原档）
  C3b 分批建仓：调仓日先建半仓（50% 目标金额，整手取整）；入场执行日 +10 个交易日后收盘判定：仍在该日 score Top-40 内且浮盈 ≥0 → 次日开盘补足剩余半仓；否则不补（剩余留现金至下次调仓）
  C3c 加仓≤1 次：持仓浮盈 ≥0.8% 且该日 score 仍在 Top-10 内 → 允许 1 次加仓，加仓金额 = 初始仓位×50%，单票总仓位 ≤ 初始单票目标×1.5（现金不足则跳过）
口径：T 收盘信号 → T+1 开盘执行；滑点/佣金/印花税/整手/涨停不追/跌停不卖 同基线。
判定门：30 相位 phmed Sharpe ≥ 基线 + 0.10 且 50bp 档（slip=0.005）不劣化。
"""
import sys, json, time, math
import numpy as np, pandas as pd
from pathlib import Path
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

# ---------- 轨A harness：复用 satellite_opt 前缀（P/ELIG/RK/TOP/ORDER/run_ln）----------
src = open(OUT / "satellite_opt_0913.py", encoding="utf-8").read()
exec(src.split("# ---- 复现基线")[0])
VAR = "turn"; N_BASE, F_BASE = 20, 30
log("轨A harness ok | elig/day:", float(ELIG[WARMUP:].sum(axis=1).mean()))

# score 排名掩码（Top-40 / Top-10）
IN40 = np.zeros((ND, NC), dtype=bool); IN10 = np.zeros((ND, NC), dtype=bool)
for di in range(ND):
    IN40[di, ORDER[VAR][di][:40]] = True
    IN10[di, ORDER[VAR][di][:10]] = True
log("Top-40 / Top-10 masks ok")

# C3a 阈值
A_CUT1, A_CUT2, A_CUT3, A_RESET = -0.08, -0.12, -0.15, -0.06   # 减档 / 恢复
A_SC1, A_SC2, A_SC3 = 0.5, 0.25, 0.0                          # 新开仓预算系数

def run_c3(variant, N, F, offset, c3a=False, c3b=False, c3c=False, cash0=CASH0, slip=SLIP):
    shares = np.zeros(NC); cost_basis = np.zeros(NC)
    cash = cash0; eq_curve = np.full(ND, np.nan); trades = []
    entry_di = np.full(NC, -1)
    pend_buy = []; pend_sell = []
    eq_prev = cash0
    top = TOP[variant]
    # C3a 状态
    peak = cash0; scale = 1.0
    n_a_shift = 0; n_a_stop = 0; n_a_buys_half = 0; n_a_buys_qtr = 0; n_a_days_off = 0
    # C3b 状态
    pend_add = {}    # j -> [due_di, rest_budget]（半仓后待补）
    pend_fill = {}   # j -> rest_budget（次日开盘执行）
    n_b_half = 0; n_b_fill = 0; n_b_drop = 0
    # C3c 状态
    added = np.zeros(NC, dtype=bool); tgt0 = np.zeros(NC); init_amt = np.zeros(NC)
    pend_addc = {}   # j -> 加仓目标金额（次日开盘执行）
    n_c_hit = 0; n_c_add = 0; n_c_skip = 0; n_c_capped = 0
    for di in range(WARMUP, ND):
        px_open = O[di]; px_prev = close_ff[di - 1]
        # ---- 卖（同基线：跌停不卖，挂到下一日）----
        if pend_sell:
            keep = []
            for j in pend_sell:
                if not np.isfinite(px_open[j]) or px_open[j] <= px_prev[j] * 0.902:
                    keep.append(j); continue
                px = px_open[j] * (1 - slip); amt = px * shares[j]
                fee = max(amt * COMM, MIN_COMM) + amt * TAX
                cash += amt - fee
                ret = (amt - fee) / cost_basis[j] - 1 if cost_basis[j] > 0 else np.nan
                trades.append((entry_di[j], di, (amt - fee) - cost_basis[j], ret))
                shares[j] = 0.0; cost_basis[j] = 0.0; entry_di[j] = -1
                added[j] = False; tgt0[j] = 0.0; init_amt[j] = 0.0
                pend_add.pop(j, None); pend_fill.pop(j, None); pend_addc.pop(j, None)
            pend_sell = keep
        # ---- C3b 补仓执行（到点次开；预占资金，先于调仓买入）----
        if c3b and pend_fill:
            for j, rest in list(pend_fill.items()):
                del pend_fill[j]
                if shares[j] <= 0 or not np.isfinite(px_open[j]) or px_open[j] <= 0.01:
                    n_b_drop += 1; continue
                px = px_open[j] * (1 + slip)
                lots = math.floor(min(rest, cash) / (px * 100.0))
                if lots < 1: n_b_drop += 1; continue
                amt = px * lots * 100.0; fee = max(amt * COMM, MIN_COMM)
                if amt + fee > cash: n_b_drop += 1; continue
                cash -= amt + fee; shares[j] += lots * 100.0; cost_basis[j] += amt + fee
                n_b_fill += 1
        # ---- 调仓买入（基线逻辑 + C3a 缩放 / C3b 半仓）----
        if pend_buy:
            held_n = int((shares > 0).sum())
            for j in pend_buy:
                if held_n >= N: break
                if shares[j] > 0 or not np.isfinite(px_open[j]) or px_open[j] <= 0.01: continue
                if px_open[j] >= px_prev[j] * 1.098: continue
                full = eq_prev / N                              # 初始单票目标
                if c3a and scale <= 0.0: n_a_stop += 1; continue  # 停止新开仓
                k = scale if c3a else 1.0
                budget = full * k * (0.5 if c3b else 1.0)       # C3b：先建半仓
                lots = math.floor(min(budget, cash) / (px_open[j] * (1 + slip) * 100.0))
                if lots < 1: continue
                px = px_open[j] * (1 + slip); amt = px * lots * 100.0
                fee = max(amt * COMM, MIN_COMM)
                if amt + fee > cash: continue
                cash -= amt + fee; shares[j] = lots * 100.0
                cost_basis[j] = amt + fee; entry_di[j] = di - 1
                tgt0[j] = full; init_amt[j] = amt + fee; added[j] = False
                if c3a and scale == A_SC1: n_a_buys_half += 1
                if c3a and scale == A_SC2: n_a_buys_qtr += 1
                if c3b:
                    pend_add[j] = [di + 10, max(0.0, full - (amt + fee))]; n_b_half += 1
                held_n += 1
            pend_buy = []
        # ---- C3c 加仓执行（次开）----
        if c3c and pend_addc:
            for j, tgt_amt in list(pend_addc.items()):
                del pend_addc[j]
                if shares[j] <= 0 or not np.isfinite(px_open[j]) or px_open[j] <= 0.01:
                    continue
                px = px_open[j] * (1 + slip)
                cap_v = 1.5 * tgt0[j] - shares[j] * px          # 1.5× 初始单票目标上限
                eff = min(tgt_amt, max(0.0, cap_v), cash)
                lots = math.floor(eff / (px * 100.0))
                if lots < 1: n_c_skip += 1; continue            # 现金/额度不足 → 跳过，条件次日重判
                amt = px * lots * 100.0; fee = max(amt * COMM, MIN_COMM)
                if amt + fee > cash: n_c_skip += 1; continue
                cash -= amt + fee; shares[j] += lots * 100.0; cost_basis[j] += amt + fee
                added[j] = True; n_c_add += 1
        # ---- mark ----
        nz = np.flatnonzero(shares)
        eq_prev = cash if len(nz) == 0 else cash + float(np.dot(shares[nz], close_ff[di][nz]))
        eq_curve[di] = eq_prev
        # ---- C3a 回撤状态更新（收盘后，作用于次日买入）----
        if c3a:
            if eq_prev > peak: peak = eq_prev
            dd = eq_prev / peak - 1
            new = scale
            if dd <= A_CUT3: new = A_SC3
            elif dd <= A_CUT2: new = A_SC2
            elif dd <= A_CUT1: new = A_SC1
            elif dd > A_RESET: new = 1.0
            if new != scale: n_a_shift += 1
            scale = new
            if scale < 1.0: n_a_days_off += 1
        # ---- C3b 到点判定（入场执行日 +10 收盘）----
        if c3b and pend_add:
            for j, (due, rest) in list(pend_add.items()):
                if di < due: continue
                del pend_add[j]
                if shares[j] <= 0 or j in pend_sell: n_b_drop += 1; continue
                avg = cost_basis[j] / shares[j] if shares[j] > 0 else np.nan
                ok = (IN40[di, j] and np.isfinite(close_ff[di, j]) and cost_basis[j] > 0
                      and close_ff[di, j] >= avg)
                if ok: pend_fill[j] = rest
                else: n_b_drop += 1
        # ---- 调仓信号（同基线）----
        if (di - WARMUP - offset) % F == 0 and di + 1 < ND:
            tgt = [int(j) for j in top[di][:N]]
            tgtS = set(tgt)
            held = np.flatnonzero(shares > 0)
            for j in held:
                if int(j) not in tgtS and int(j) not in pend_sell: pend_sell.append(int(j))
            pend_buy = [j for j in tgt if shares[j] == 0]
            if c3b:  # 调仓日清理未到点半仓挂单（剩余现金归池）
                for j in list(pend_add.keys()): n_b_drop += 1; del pend_add[j]
        # ---- C3c 触发判定（收盘：浮盈≥0.8% 且 Top-10）----
        if c3c:
            for j in np.flatnonzero(shares > 0):
                jj = int(j)
                if added[jj] or jj in pend_sell or cost_basis[jj] <= 0: continue
                if not np.isfinite(close_ff[di, jj]): continue
                if close_ff[di, jj] / (cost_basis[jj] / shares[jj]) - 1 < 0.008: continue
                if not IN10[di, jj]: continue
                n_c_hit += 1
                cap_v = 1.5 * tgt0[jj] - shares[jj] * close_ff[di, jj]
                if cap_v <= 0: added[jj] = True; n_c_capped += 1; continue
                pend_addc[jj] = min(0.5 * init_amt[jj], cap_v)
    eq = pd.Series(eq_curve[WARMUP:], index=pd.to_datetime(cal[WARMUP:])).ffill().dropna()
    ret = eq.pct_change().dropna()
    yrs = len(eq) / 244.0
    ann = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    sharpe = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    closed = [t for t in trades if np.isfinite(t[3])]
    return dict(ann=float(ann), sharpe=float(sharpe), mdd=float(dd), n_trades=len(closed),
                win=float(np.mean([t[3] > 0 for t in closed])) if closed else np.nan,
                n_a_shift=n_a_shift, n_a_stop=n_a_stop, n_a_buys_half=n_a_buys_half,
                n_a_buys_qtr=n_a_buys_qtr, n_a_days_off=n_a_days_off,
                n_b_half=n_b_half, n_b_fill=n_b_fill, n_b_drop=n_b_drop,
                n_c_hit=n_c_hit, n_c_add=n_c_add, n_c_skip=n_c_skip, n_c_capped=n_c_capped)

# ---------- 臂定义（预注册）----------
ARMS = [("BASE", {}), ("C3a", dict(c3a=True)), ("C3b", dict(c3b=True)),
        ("C3c", dict(c3c=True)), ("C3a+C3c", dict(c3a=True, c3c=True))]
CNT_KEYS = ["n_a_shift", "n_a_stop", "n_a_buys_half", "n_a_buys_qtr", "n_a_days_off",
            "n_b_half", "n_b_fill", "n_b_drop", "n_c_hit", "n_c_add", "n_c_skip", "n_c_capped"]

# 基线复现核对：run_c3(全关) 必须与 run_ln 完全一致
m_ln = run_ln(VAR, N_BASE, F_BASE, 0); m_c3 = run_c3(VAR, N_BASE, F_BASE, 0)
same = all(abs(m_ln[k] - m_c3[k]) < 1e-12 for k in ["ann", "sharpe", "mdd"])
log(f"refactor 核对 off0: run_ln S={m_ln['sharpe']:.6f} vs run_c3 S={m_c3['sharpe']:.6f} | identical={same}")
assert same, "run_c3 全关应与 run_ln 完全一致"

res = {"config": dict(engine="satellite_opt_0913 prefix", variant=VAR, N=N_BASE, F=F_BASE,
                      phases=30, gate="phmed >= base+0.10 且 50bp 不劣化",
                      c3a=dict(cut=[A_CUT1, A_CUT2, A_CUT3], reset=A_RESET, scale=[A_SC1, A_SC2, A_SC3]),
                      c3b=dict(half=0.5, wait=10, cond="Top-40 & 浮盈>=0"),
                      c3c=dict(gain=0.008, top=10, add=0.5, cap=1.5)),
       "refactor_check": dict(run_ln_s0=m_ln["sharpe"], run_c3_s0=m_c3["sharpe"], identical=bool(same)),
       "arms": {}}

for slip, tag in [(SLIP, "20bp"), (0.005, "50bp")]:
    for name, kw in ARMS:
        shs, anns, cnt = [], [], {k: [] for k in CNT_KEYS}
        for off in range(30):
            m = run_c3(VAR, N_BASE, F_BASE, off, slip=slip, **kw)
            shs.append(m["sharpe"]); anns.append(m["ann"])
            for k in CNT_KEYS: cnt[k].append(m[k])
            if off == 0: o0 = m
        s = dict(phmed=float(np.median(shs)), phmin=float(min(shs)), phmax=float(max(shs)),
                 phmed_ann=float(np.median(anns)),
                 off0={k: o0[k] for k in ["ann", "sharpe", "mdd", "n_trades", "win"]},
                 counts_mean={k: float(np.mean(cnt[k])) for k in CNT_KEYS})
        if tag == "20bp":
            res["arms"][name] = s; res["arms"][name]["slip50"] = None
        else:
            res["arms"][name]["slip50"] = dict(s, counts_mean=None)
        log(f"{tag} {name:7s} | phmed S={s['phmed']:.3f} (min {s['phmin']:.2f}/max {s['phmax']:.2f}) "
            f"ann_med {s['phmed_ann']*100:+.2f}% | off0 S={o0['sharpe']:.2f} ann {o0['ann']*100:+.2f}% mdd {o0['mdd']*100:.1f}%")

b, b50 = res["arms"]["BASE"]["phmed"], res["arms"]["BASE"]["slip50"]["phmed"]
res["gate"] = {"base_20bp_phmed": b, "base_50bp_phmed": b50,
               "base_50bp_phmin": res["arms"]["BASE"]["slip50"]["phmin"], "arms": {}}
for name, _ in ARMS:
    if name == "BASE": continue
    v = res["arms"][name]; v50 = v["slip50"]
    d, d50 = v["phmed"] - b, v50["phmed"] - b50
    ok = (d >= 0.10) and (d50 >= 0)
    res["gate"]["arms"][name] = dict(delta_phmed=float(d), delta_50bp=float(d50), pass_gate=bool(ok))
    log(f"  门控 {name:7s}: Δ20bp {d:+.3f} / Δ50bp {d50:+.3f} → {'过' if ok else '不过'}")
log("触发统计(30 相位均值):")
for name, _ in ARMS:
    if name == "BASE": continue
    c = res["arms"][name]["counts_mean"]
    log(f"  {name}: " + " ".join(f"{k.replace('n_','')}={c[k]:.1f}" for k in CNT_KEYS if abs(c[k]) > 1e-9))

json.dump(res, open(OUT / "c3_position_0915.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved c3_position_0915.json")
