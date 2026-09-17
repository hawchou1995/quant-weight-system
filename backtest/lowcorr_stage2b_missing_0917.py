# -*- coding: utf-8 -*-
"""stage2b：补齐 GitHub 清单中「可回测但未跑」的规则策略（2026-09-17）
复用 stage2 同一 harness（panel/eval/相位/成本；软锚版轨B 基准）。
新腿（规则来源=已 clone 仓库的原始代码，参数逐条对齐；偏离点显式申报）：
  g_allweather_erc     szjintz V1 全天候：6 ETF 资产级 ERC（SLSQP，0.05-0.40 界，60d 窗口）
                       【申报】调仓=20 日周期（原版=月末+±8% 阈值触发+80% 执行）
  k_crossborder_mom10  zhuleimed 跨境轮动：5 ETF（510300/510500/513100/513500/159920）
                       10 日动量 Top-1【申报】调仓=10 日周期（原版=信号驱动+5 日渐进）
  c2_gold_panic        zhuleimed 黄金避险：7 宽基 20d 动量 Top-1；硬阈值恐慌（AND 三条：
                       5日最大跌幅<-2% ∧ vol21/63>1.3 ∧ 下跌广度>60%）→ 全仓 518880
                       【申报】5 日检查（原版=日频）
  i_erba_rot           二八轮动：300 vs 500 20d 动量取强者，负动量持现金【申报】LAujust 未 clone，
                       按清单描述标准化（其原文公式 (C[t]-C[t-20])/C[t] 非标准收益率）
  j_dividend_ma120     红利 MA120：510880 收盘>MA120 → 持有，否则现金【申报】cyinen 规则为
                       notebook 反推（README 无文字规则），取最常见 MA120 择时形式
产物：backtest/lowcorr_stage2b_missing_0917.json
用法：python backtest/lowcorr_stage2b_missing_0917.py
"""
import json, sys, time, os
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import minimize

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "backtest"))
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

import lowcorr_stage2_crossasset_0916 as S2   # 复用 harness（有 __main__ 守卫，import 安全）
log(f"[import] stage2 harness OK（PHASES={S2.PHASES}, REBAL={S2.REBAL}, SLIP={S2.SLIP_MAIN}/{S2.SLIP_STRESS}）")

# ---------- 轨B 基准（软锚：面板已延展，22.87→当前版本） ----------
src = (BASE / "backtest" / "oss_0913" / "oss_super_combo_0913.py").read_text(encoding="utf-8")
g = {}
exec(src.split("comp = composite()")[0], g)
rB_run = g["run_engine"](g["composite"](), 20, offset=0)
annB = float(rB_run["ann"]) * 100
log(f"[轨B] off0 年化 {annB:.2f}%（历史锚 22.87% | 漂移 {abs(annB-22.87):.2f}pp=data vintage）")
if abs(annB - 22.87) > 3.0:
    log("[ABORT] 锚漂移>3pp，拒绝出数"); sys.exit(1)
eqB = rB_run["equity"]
cal = pd.to_datetime([str(d)[:10] for d in g["cal"]])
rB = eqB.pct_change().dropna()
log(f"[面板日历] {cal[0].date()} → {cal[-1].date()}（{len(cal)}d）")

P = S2.build_panel(cal)
n, col, codes = P["n"], {c: i for i, c in enumerate(P["codes"])}, P["codes"]
CN, ON, MN = P["CN"], P["ON"], P["MN"]
CF = pd.DataFrame(CN)   # wide close（ffill 后）

# ---------- 工具：动量/指标矩阵 ----------
M10 = (CF / CF.shift(10) - 1).to_numpy()
MA120 = CF.rolling(120, min_periods=120).mean().to_numpy()
def rebal(off, step=20):
    return list(range(off, n - 1, step))

# ---------- 恐慌指标（zhuleimed compute_panic_indicators 逐条复刻） ----------
BROAD7 = ["sh510050", "sh510300", "sh510500", "sh512100", "sh563000", "sz159915", "sh588000"]
ret5 = (CF / CF.shift(5) - 1)
r1 = CF.pct_change()
vol21 = r1.rolling(21, min_periods=21).std(ddof=0)
vol63 = r1.rolling(63, min_periods=63).std(ddof=0)
vr = vol21 / vol63.replace(0, np.nan)
b_idx = [col[c] for c in BROAD7 if c in col]
PANIC = np.zeros(n, dtype=bool)
for di in range(n):
    r5 = ret5.to_numpy()[di, b_idx]
    vv = vr.to_numpy()[di, b_idx]
    ok = np.isfinite(r5) & np.isfinite(vv)
    if ok.sum() < 4:
        continue
    r5, vv = r5[ok], vv[ok]
    max_dd = float(np.min(r5))
    avg_vr = float(np.mean(vv))
    breadth = float(np.mean(r5 < 0))
    PANIC[di] = (max_dd < -0.02) and (avg_vr > 1.3) and (breadth > 0.6)
log(f"[恐慌指标] 硬阈值(AND)触发天数 {int(PANIC.sum())}/{n}（{int(PANIC.sum())/n:.1%}）")

# ---------- 新腿定义 ----------
POOL6 = ["sh510300", "sh510500", "sh511260", "sh511010", "sh518880", "sz159985"]
have6 = [c for c in POOL6 if c in col]
log(f"[池] allweather6 命中 {len(have6)}/6：{have6}")
ret60_all = CF.pct_change()
LOGR = np.log(CF.where(CF > 0)).diff()

def erc_weights(di):
    win = LOGR.iloc[max(0, di - 60):di, [col[c] for c in have6]].to_numpy()
    rr = win[np.isfinite(win).all(axis=1)]
    if len(rr) < 40:
        return None
    Sig = np.cov(rr, rowvar=False, ddof=1)
    k = len(have6)
    def obj(w):
        rc = w * (Sig @ w)
        return float(np.sum((rc - rc.mean()) ** 2))
    res = minimize(obj, np.full(k, 1 / k), method="SLSQP",
                   bounds=[(0.05, 0.40)] * k,
                   constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
                   options={"maxiter": 300, "ftol": 1e-12})
    if not res.success:
        return None
    w = np.clip(res.x, 0, None)
    return w / w.sum()

def leg_allweather(off):
    out = {}
    for di in rebal(off, 20):
        if di + 1 >= n: continue
        w = erc_weights(di)
        out[di] = {c: float(wi) for c, wi in zip(have6, w)} if w is not None else {}
    return out

XB5 = ["sh510300", "sh510500", "sh513100", "sh513500", "sz159920"]
def leg_xb(off):
    out = {}
    for di in rebal(off, 10):
        if di + 1 >= n: continue
        cand = [(c, M10[di, col[c]]) for c in XB5 if c in col and np.isfinite(M10[di, col[c]])]
        out[di] = [max(cand, key=lambda x: x[1])[0]] if cand else []
    return out

def leg_goldpanic(off):
    out = {}
    for di in rebal(off, 5):
        if di + 1 >= n: continue
        if PANIC[di]:
            out[di] = ["sh518880"]
        else:
            cand = [(c, MN[di, col[c]]) for c in BROAD7 if c in col and np.isfinite(MN[di, col[c]])]
            out[di] = [max(cand, key=lambda x: x[1])[0]] if cand else []
    return out

def leg_erba(off):
    out = {}
    for di in rebal(off, 20):
        if di + 1 >= n: continue
        if "sh510300" not in col or "sh510500" not in col:
            out[di] = []; continue
        m3, m5 = MN[di, col["sh510300"]], MN[di, col["sh510500"]]
        if not np.isfinite(m3) or not np.isfinite(m5):
            out[di] = []
        elif m3 <= 0 and m5 <= 0:
            out[di] = []
        else:
            out[di] = ["sh510300" if m3 >= m5 else "sh510500"]
    return out

def leg_div(off):
    out = {}
    c = "sh510880"
    for di in rebal(off, 20):
        if di + 1 >= n: continue
        if c not in col:
            out[di] = []; continue
        v, m = CN[di, col[c]], MA120[di, col[c]]
        out[di] = [c] if (np.isfinite(v) and np.isfinite(m) and v > m) else []
    return out

LEGS = [
    {"name": "g_allweather_erc", "fn": leg_allweather, "weighted": True},
    {"name": "k_crossborder_mom10", "fn": leg_xb, "weighted": False},
    {"name": "c2_gold_panic", "fn": leg_goldpanic, "weighted": False},
    {"name": "i_erba_rot", "fn": leg_erba, "weighted": False},
    {"name": "j_dividend_ma120", "fn": leg_div, "weighted": False},
]

# ---------- 加权模拟器（逐行复制 S2.simulate，目标改 {code: weight}） ----------
COMM, TAX, MIN_COMM, LOT = S2.COMM, S2.TAX, S2.MIN_COMM, S2.LOT

def simulate_w(cal, P, targets_w, slip=S2.SLIP_MAIN, cash0=S2.CASH0):
    n_, col_ = len(cal), {c: i for i, c in enumerate(P["codes"])}
    CN_, ON_ = P["CN"], P["ON"]
    cash, shares, cost, first_buy, eq = cash0, {}, {}, None, np.full(n_, np.nan)
    trades, last, pending, entry_di = [], {}, None, {}
    for di in range(n_):
        if pending is not None:
            tgt = {c: w for c, w in pending.items() if w > 0}
            pv = cash + sum(shares[c] * (ON_[di, col_[c]] if np.isfinite(ON_[di, col_[c]]) and ON_[di, col_[c]] > 0 else last.get(c, 0.0)) for c in shares)
            # 1) 减仓/清仓
            for c in list(shares):
                j = col_[c]; o = ON_[di, j]
                if not np.isfinite(o) or o <= 0: continue
                pc = CN_[di - 1, j] if di > 0 else np.nan
                if np.isfinite(pc) and o <= pc * 0.902: continue
                tgt_val = tgt.get(c, 0.0) * pv
                cur_val = shares[c] * o
                if cur_val - tgt_val > o * LOT * 0.5:
                    sell_lots = int((cur_val - tgt_val) // (o * LOT))
                    if sell_lots >= 1:
                        sell_lots = min(sell_lots, int(shares[c] // LOT))   # 2026-09-17 修：显式整手，防浮点股数
                        px = o * (1 - slip); amt = px * sell_lots * LOT
                        fee = max(amt * COMM, MIN_COMM) + amt * TAX
                        cash += amt - fee
                        shares[c] -= sell_lots * LOT
                        if shares[c] <= 0:
                            trades.append({"symbol": c, "exit_date": str(cal[di].date())})
                            del shares[c]; cost.pop(c, None); entry_di.pop(c, None)
            # 2) 加仓/建仓
            for c, w in tgt.items():
                if c not in col_: continue
                j = col_[c]; o = ON_[di, j]
                if not np.isfinite(o) or o <= 0: continue
                pc = CN_[di - 1, j] if di > 0 else np.nan
                if np.isfinite(pc) and o >= pc * 1.098: continue
                need_val = w * pv - shares.get(c, 0.0) * o
                if need_val > o * LOT * 0.5:
                    lots = int(min(need_val, cash) / (o * (1 + slip) * LOT * (1 + COMM)))
                    if lots >= 1:
                        px = o * (1 + slip); amt = px * lots * LOT; fee = max(amt * COMM, MIN_COMM)
                        if amt + fee <= cash:
                            cash -= amt + fee
                            if c in shares:
                                shares[c] += lots * LOT; cost[c] += amt + fee
                            else:
                                shares[c] = lots * LOT; cost[c] = amt + fee; entry_di[c] = di
                                if first_buy is None: first_buy = di
            pending = None
        for c in shares:
            v = CN_[di, col_[c]]
            if np.isfinite(v): last[c] = v
        eq[di] = cash + sum(shares[c] * last.get(c, 0.0) for c in shares)
        if di in targets_w and di + 1 < n_:
            pending = targets_w[di]
    s = pd.Series(eq, index=cal).ffill()
    return s, trades, first_buy

# ---------- eval（复刻 S2.eval_leg，按腿选择模拟器） ----------
def eval_leg2(cal, P, L):
    name, fn = L["name"], L["fn"]
    sim = simulate_w if L.get("weighted") else (lambda c, p, t, slip: S2.simulate(c, p, t, slip=slip))
    per, rets, sh = {}, {}, []
    eq_off0 = None
    for off in S2.PHASES:
        s, tr, fb = sim(cal, P, fn(off), slip=S2.SLIP_MAIN)
        if fb is None:
            return None
        s2 = s.iloc[fb:]
        st = S2.V.summary(S2.mk_eqdf(s2), tr)
        per[off] = st; sh.append(st["sharpe"])
        rets[off] = s2.pct_change().dropna()
        if off == 0:
            off0 = dict(st=st, rets=rets[0], trades=tr); eq_off0 = s2
    s50, tr50, fb50 = sim(cal, P, fn(0), slip=S2.SLIP_STRESS)
    st50 = S2.V.summary(S2.mk_eqdf(s50.iloc[fb50:]), tr50) if fb50 is not None else {"sharpe": None}
    return {"leg": name, "phmed_sharpe": float(np.median(sh)), "sharpe_min": float(min(sh)),
            "sharpe_max": float(max(sh)), "slip50_sharpe": st50.get("sharpe"),
            "off0_ann_pct": off0["st"]["annual_return_pct"], "off0_mdd_pct": off0["st"]["max_drawdown_pct"],
            "off0_total_pct": off0["st"]["total_return_pct"], "n_trades": off0["st"]["total_trades"],
            "phase_sharpes": {str(k): v["sharpe"] for k, v in per.items()},
            "by_year_pct": {int(y): round(float(gx.iloc[-1] / gx.iloc[0] - 1) * 100, 1)
                            for y, gx in eq_off0.groupby(eq_off0.index.year)},
            "rets0": off0["rets"], "start": str(off0["rets"].index[0].date()), "end": str(off0["rets"].index[-1].date())}

rows = []
for L in LEGS:
    r = eval_leg2(cal, P, L)
    if r is None:
        log(f"  [skip] {L['name']}（无建仓）"); continue
    rets = r.pop("rets0")
    idx = rets.index.intersection(rB.index)
    rr, rb = rets.reindex(idx), rB.reindex(idx)
    corr = float(rr.corr(rb))
    r["corr_B"] = round(corr, 3)
    passed = corr <= S2.GATES["corr_B_max"] and r["phmed_sharpe"] >= S2.GATES["leg_phmed_min"]
    r["pass_gate"] = bool(passed)
    rows.append(r)
    log(f"[{r['leg']:22s}] phmed {r['phmed_sharpe']:+.3f} | off0 年化 {r['off0_ann_pct']:+7.2f}% mdd {r['off0_mdd_pct']:6.1f}% | 50bp {r['slip50_sharpe']} | corr_B {corr:+.3f} | 过闸 {'PASS' if passed else ' - '}")

out = {"meta": {"date": "2026-09-17", "stage": "2b-missing", "window": [str(cal[0].date()), str(cal[-1].date())],
                "note": "补齐 GitHub 清单未跑项；与 stage2 同 harness；本批数据版本=面板延展至 09-16（轨B 锚软校验）",
                "deviations": ["allweather: 20日周期(原版月末+阈值+80%)", "crossborder: 10日周期(原版信号驱动+5日渐进)",
                               "gold_panic: 5日检查(原版日频)", "erba/dividend: 标准化(原仓库未 clone/规则反推)"]},
       "n_legs": len(rows), "legs": rows}
(BASE / "backtest" / "lowcorr_stage2b_missing_0917.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
log(f"[落盘] lowcorr_stage2b_missing_0917.json | 腿 {len(rows)}")
print("\n腿名 | 相位中位夏普 | off0年化 | mdd | 50bp夏普 | corr vs 轨B | 过闸")
for r in sorted(rows, key=lambda x: -x["off0_ann_pct"]):
    log_flag = "PASS" if r["pass_gate"] else " - "
    print(f"{r['leg']:22s} | {r['phmed_sharpe']:+.3f} | {r['off0_ann_pct']:+7.2f}% | {r['off0_mdd_pct']:6.1f}% | {str(r['slip50_sharpe']):>6s} | {r['corr_B']:+.3f} | {log_flag}")
