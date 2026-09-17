# -*- coding: utf-8 -*-
"""知识库清算 Top5 · 第一批回测（主板域） —— 2026-09-16  v2（NaN 修复版）
================================================================================
预注册来源：backtest/清单-知识库未测策略存量分类-20260916.md §7.2 Top20（§7.5 首批 5 条）
本批对象（逐条独立，跑一条落盘一条）：
  ① kb1 分歧弱转强（页1 §1.3 #16）            ② kb2 PCA 特质换手波动率（页4 §4.2 J#42）
  ③ kb3 笔均量/均笔额（页2 §2.3 09-16[2]）    ④ kb4 「该跌不跌」龙头相对强度（页3 §3.3 #12）
  ⑤ kb5 打板过滤组 P1（页6.1，A5 历史信号条件分组；独立脚本 kb5_cond_features_0916.py 提特征）

--- v1 → v2 的唯一实质改动（NaN 根因修复，证据见 _diag_kb1_nan_0916.py 输出）---
v1 把稀疏事件信号（signal_state：无信号日 = NaN）直接喂给 N=20 的冻结 run_engine。
引擎建仓门为 `if ok.sum() >= N`（N=20），而 kb1 每日可用候选 中位 2 / **最大 9 < 20**
→ 该门永假 → 引擎从不建仓 → 净值恒 170000 → 日收益 std=0 → 夏普 NaN / 年化 0 / 回撤 0 / corr NaN。
修复 = **候选不足时按实际可选数建仓（N_eff = min(N, #cand)，N 仍为 20 仅作单笔 1/N 的资金切分）**，
逐行复刻冻结引擎、仅在稀疏域生效；对生产 composite 的净值与冻结引擎**逐位一致**（自检断言 diff<1e-9）。
密集因子腿（kb2/kb3/kb4）仍走**原封冻结引擎**（max 候选 ≥20），引擎模式逐腿记录 engine_mode。

口径（严格遵守任务书）：
  · universe = A 股主板 sh60*/sz00*（冻结面板本已全主板，前缀过滤为恒等变换，见 universe_audit）
  · 基准自检：全宇宙 off0 年化必须 = 22.87%，否则 ABORT
  · 5 相位 0/4/8/12/16 → 相位中位夏普；双成本档 20bp / 50bp
  · corr = 腿 off0 净值日收益 vs 轨B off0 净值日收益（同窗对齐）
  · 组合层（修正口径）：**不从轨B挪仓位**。(i) 现金端 r_new=r_B+λ·c_t·r_L（c_t=轨B实测闲置现金权重）；
    (ii) 增量资金 主仓:候选 混合边际。任一 ΔSharpe≥+0.02 且 Calmar 不降 → 组合层改善
  · 验收闸：corr ≤0.30 ∧ 相位中位夏普 ≥0.5 ∧ 50bp ≥0.3 ∧ 分半同号（两半夏普均>0）

纪律：只改 backtest/；先冒烟后全量；每测完一条即落盘 JSON + 追加报告 md；数字全部来自实际运行输出。
用法：python backtest/kb_batch1_top5_0916.py [--smoke] [--only kb1,kb2]
"""
import argparse
import gc
import json
import math
import os
import sys
import time
import warnings
from pathlib import Path

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OSS = BASE / "backtest" / "oss_0913"
RES = BASE / "backtest" / "kb_batch1_top5_0916.json"
REPORT = BASE / "backtest" / "报告-知识库Top5回测-20260916.md"

import numpy as np                      # noqa: E402
import pandas as pd                     # noqa: E402

warnings.filterwarnings("ignore")

PHASES = [0, 4, 8, 12, 16]
TOPN = 20
SLIP_MAIN, SLIP_STRESS = 0.0020, 0.0050
ANN_ENGINE = 244.0
CASH0 = 170_000.0
GATES = dict(corr_B_max=0.30, phmed_sharpe_min=0.50, slip50_sharpe_min=0.30,
             blend_dsharpe_min=0.02)
MB_RULE = "sh60*(600/601/603/605) | sz00*(000/001/002/003)"

t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)


def jsafe(o):
    """NaN/Inf → None（JSON 合法）"""
    if isinstance(o, dict):
        return {k: jsafe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsafe(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


# ============================================================ 0) 冻结引擎前缀
def load_engine():
    src = (OSS / "oss_super_combo_0913.py").read_text(encoding="utf-8")
    G = {}
    exec(src.split("comp = composite()")[0], G)          # noqa: S102 生产冻结前缀
    r_all = G["run_engine"](G["composite"](), TOPN, offset=0)
    ann_all = float(r_all["ann"]) * 100
    log(f"[轨B·全宇宙自检] off0 年化 {ann_all:.2f}%（官方 22.87%）| 夏普(√244) {r_all['sharpe']:.3f} | "
        f"回撤 {r_all['mdd']*100:.1f}% | {r_all['equity'].index[0].date()}→{r_all['equity'].index[-1].date()}"
        f"（{len(r_all['equity'])}d, {r_all['n_trades']} 笔）")
    _anchor = 22.87
    try:
        import json as _js, os as _os
        _af = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "engine_anchor.json")
        if _os.path.exists(_af):
            _anchor = float(_js.load(open(_af, encoding="utf-8"))["base_off0_ann"])
    except Exception:
        pass
    if abs(ann_all - _anchor) > 0.5:
        log(f"[ABORT] 轨B 复现年化 {ann_all:.2f}% ≠ 锚 {_anchor}%（engine_anchor.json/历史 22.87）→ 口径未对齐，拒绝出结论")
        sys.exit(2)

    codes = G["codes"]
    norm = [str(c).strip().lower().replace("sh", "").replace("sz", "").replace("bj", "") for c in codes]
    mb = np.array([s.startswith("60") or s.startswith("00") for s in norm], bool)
    from collections import Counter
    census = {"n_codes": len(norm), "n_mainboard": int(mb.sum()), "n_excluded": int((~mb).sum()),
              "prefix3_census_all": dict(sorted(Counter(s[:3] for s in norm).items())),
              "mainboard_rule": MB_RULE}
    elig_all = G["ELIG3"].copy()
    elig_mb = elig_all & mb[None, :]
    n_mb = elig_mb.sum(axis=1)
    G["ELIG3"] = elig_mb
    ret1 = pd.DataFrame(G["close_ff"]).pct_change()
    v20f = (-ret1.rolling(20, min_periods=15).std()).to_numpy()
    G["volpct"] = pd.DataFrame(np.where(G["ELIG3"], v20f, np.nan)).rank(axis=1, pct=True).to_numpy()
    aud = {"universe": "mainboard(sh60|sz00)", "filter_applied_to": "腿与轨B 同时生效",
           "elig_daily_median": int(np.median(n_mb)), "elig_daily_mean": round(float(n_mb.mean()), 1),
           "elig_daily_min": int(n_mb.min()), "elig_days_below_topn": int((n_mb < TOPN).sum()),
           "prefix_filter_bitwise_noop": bool(np.array_equal(elig_all, elig_mb)),
           "note": "noop=True → 冻结面板本身已只含主板标的，前缀过滤为恒等变换", **census}
    del ret1, v20f
    gc.collect()
    r_mb = G["run_engine"](G["composite"](), TOPN, offset=0)
    annB = float(r_mb["ann"]) * 100
    log(f"[轨B·主板域] off0 年化 {annB:.2f}% | 夏普 {r_mb['sharpe']:.3f} | 回撤 {r_mb['mdd']*100:.1f}% | "
        f"日均可选 {aud['elig_daily_mean']} 只 | noop={aud['prefix_filter_bitwise_noop']}")
    return G, r_mb["equity"].pct_change().dropna(), r_mb, annB, aud


# ---------------------------------------------------------- 冻结引擎逐行复刻（+1 行稀疏域适配）
def make_runner(G):
    """run_engine_x = 冻结 run_engine 的逐行复刻，唯一差别：
       fused=False（密集腿）与冻结版**逐位一致**；fused=True（稀疏腿）把
       `if ok.sum() >= N` 放宽为 `>= 1` 且 N_eff = min(N, len(cand))，
       单笔资金切分仍用 eq/N（N=20）→ 未满仓部分留现金。
       返回 (runner, verify_fn)"""
    O_, close_ff = G["O"], G["close_ff"]
    ELIG, ma20sc, sc1000, volpct = G["ELIG3"], G["ma20sc"], G["sc1000"], G["volpct"]
    COMM, TAX, MIN_COMM = G["COMM"], G["TAX"], G["MIN_COMM"]
    WARMUP, F, cal = G["WARMUP"], G["F"], G["cal"]
    ND, NC = G["C"].shape
    CAL_IDX = pd.to_datetime(cal[WARMUP:])

    def runner(comp, N=TOPN, offset=0, cash0=CASH0, slip=SLIP_MAIN, calm=True, fused=False):
        shares = np.zeros(NC); cost_basis = np.zeros(NC)
        cash = cash0; eq_curve = np.full(ND, np.nan); cash_curve = np.full(ND, np.nan)
        trades = []; entry_di = np.full(NC, -1); pend_buy = []; pend_sell = []
        eq_prev_known = cash0
        n_reb, n_skip = 0, 0
        for di in range(WARMUP, ND):
            px_open = O_[di]; px_prev = close_ff[di - 1]
            if pend_sell:
                keep = []
                for j in pend_sell:
                    if not np.isfinite(px_open[j]) or px_open[j] <= px_prev[j] * 0.902:
                        keep.append(j); continue
                    px = px_open[j] * (1 - slip); amt = px * shares[j]
                    fee = max(amt * COMM, MIN_COMM) + amt * TAX
                    proceeds = amt - fee
                    cash += proceeds
                    ret = proceeds / cost_basis[j] - 1 if cost_basis[j] > 0 else np.nan
                    trades.append((entry_di[j], di, proceeds - cost_basis[j], ret))
                    shares[j] = 0.0; cost_basis[j] = 0.0; entry_di[j] = -1
                pend_sell = keep
            if pend_buy:
                for j in pend_buy:
                    if shares[j] > 0 or not np.isfinite(px_open[j]) or not ELIG[di - 1][j]:
                        continue
                    if px_open[j] >= px_prev[j] * 1.098 or px_open[j] <= 0.01:
                        continue
                    budget = eq_prev_known / N
                    lots = math.floor(min(budget, cash) / (px_open[j] * (1 + slip) * 100.0))
                    if lots < 1:
                        continue
                    px = px_open[j] * (1 + slip); amt = px * lots * 100.0
                    fee = max(amt * COMM, MIN_COMM)
                    if amt + fee > cash:
                        continue
                    cash -= amt + fee; shares[j] = lots * 100.0
                    cost_basis[j] = amt + fee; entry_di[j] = di - 1
                pend_buy = []
            nz = np.flatnonzero(shares)
            eq_prev_known = cash if len(nz) == 0 else cash + float(np.dot(shares[nz], close_ff[di][nz]))
            eq_curve[di] = eq_prev_known; cash_curve[di] = cash
            if (di - WARMUP - offset) % F == 0 and di + 1 < ND:
                row = comp[di]
                ok = ELIG[di] & np.isfinite(row)
                gate_open = bool(np.isfinite(ma20sc[di]) and sc1000[di] > ma20sc[di])
                _min_c = 1 if fused else N
                if ok.sum() >= _min_c:
                    n_reb += 1
                    cand = np.flatnonzero(ok)
                    _cap = min(N, len(cand))
                    if gate_open:
                        N_eff = _cap; sel = cand
                    else:
                        N_eff = (max(1, _cap // 2) if fused else max(2, N // 2)); sel = cand
                        if calm:
                            sub = cand[np.isfinite(volpct[di][cand]) & (volpct[di][cand] <= 0.5)]
                            if len(sub) >= N_eff:
                                sel = sub
                    ordj = sel[np.argsort(-row[sel])]
                    topN = [int(j) for j in ordj[:N_eff]]; topS = set(topN)
                    held = np.flatnonzero(shares > 0)
                    for j in held:
                        if int(j) not in topS:
                            pend_sell.append(int(j))
                    n_after = int(len([j for j in held if int(j) in topS]))
                    pend_buy = [j for j in topN if shares[j] == 0][:max(0, N_eff - n_after)]
                else:
                    n_skip += 1
        eq = pd.Series(eq_curve[WARMUP:], index=CAL_IDX).ffill().dropna()
        cw = pd.Series(cash_curve[WARMUP:], index=CAL_IDX)
        cash_w = (cw / eq.replace(0, np.nan)).clip(0, 1).fillna(0.0)
        closed = [t for t in trades if np.isfinite(t[3])]
        ret = eq.pct_change().dropna()
        yrs = len(eq) / ANN_ENGINE
        m = dict(
            equity=eq, cash_w=cash_w, ret=ret,
            ann=float((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1),
            total=float(eq.iloc[-1] / eq.iloc[0] - 1),
            sharpe=float(ret.mean() / ret.std() * np.sqrt(ANN_ENGINE)) if ret.std() > 0 else float("nan"),
            vol=float(ret.std() * np.sqrt(ANN_ENGINE)),
            mdd=float((eq / eq.cummax() - 1).min()),
            n_trades=len(closed),
            win=float(np.mean([t[3] > 0 for t in closed])) if closed else float("nan"),
            by_year={int(y): float(eq[eq.index.year == y].iloc[-1] / eq[eq.index.year == y].iloc[0] - 1)
                     for y in sorted(set(eq.index.year))},
            n_rebal=n_reb, n_rebal_skipped=n_skip,
            invested_mean=float(1.0 - cash_w.mean()))
        return m

    def verify():
        """复刻校验：对生产 composite，fused=False 必须与冻结 run_engine 逐位一致"""
        comp = G["composite"]()
        worst = {}
        for off, slip in ((0, SLIP_MAIN), (0, SLIP_STRESS), (4, SLIP_MAIN), (8, SLIP_MAIN)):
            a = runner(comp, TOPN, offset=off, slip=slip)
            b = G["run_engine"](comp, TOPN, offset=off, slip=slip)
            d = float(np.max(np.abs(a["equity"].reindex(b["equity"].index).to_numpy()
                                      - b["equity"].to_numpy())))
            ds = abs(a["sharpe"] - float(b["sharpe"]))
            worst[f"off{off}_slip{int(slip*1e4)}"] = (d, ds, a["n_trades"], b["n_trades"])
        del comp; gc.collect()
        return worst

    return runner, verify


# ============================================================ 1) 通用评估
def perf_ret(r):
    """收益序列口径（组合层用）：年化 244"""
    r = r.dropna()
    if len(r) < 30:
        return dict(ann_pct=None, sharpe=None, vol_pct=None, mdd_pct=None, calmar=None, n_days=int(len(r)))
    eq = (1 + r).cumprod()
    yrs = len(r) / ANN_ENGINE
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    sharpe = r.mean() / r.std() * np.sqrt(ANN_ENGINE) if r.std() > 0 else np.nan
    mdd = (eq / eq.cummax() - 1).min()
    return dict(ann_pct=round(float(cagr) * 100, 2), sharpe=round(float(sharpe), 3),
                vol_pct=round(float(r.std()) * np.sqrt(ANN_ENGINE) * 100, 2),
                mdd_pct=round(float(mdd) * 100, 2),
                calmar=round(float(cagr) / abs(float(mdd)), 2) if mdd < 0 else None, n_days=int(len(r)))


def zcomp(mat, ELIG3):
    a = np.where(ELIG3, mat.astype(np.float64), np.nan)
    mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
    return np.clip((a - mu) / (sd + 1e-12), -3, 3)


def cand_density(comp, ELIG3):
    fin = np.isfinite(comp) & ELIG3
    n = fin.sum(axis=1)
    act = n[n > 0]
    return dict(days_with_cand=int((n > 0).sum()), n_days=int(len(n)),
                median_act=int(np.median(act)) if len(act) else 0,
                mean_act=round(float(act.mean()), 2) if len(act) else 0.0,
                max=int(n.max()), days_ge_topn=int((n >= TOPN).sum()))


def eval_leg(G, runner, rB, comp, name, smoke=False, force_fused=None):
    dens = cand_density(comp, G["ELIG3"])
    fused = (dens["max"] < TOPN) if force_fused is None else force_fused
    per, shs = {}, []
    offs = PHASES[:2] if smoke else PHASES
    for off in offs:
        m = runner(comp, TOPN, offset=off, fused=fused)
        per[off] = m; shs.append(float(m["sharpe"]))
    o0 = per[0]
    m50 = runner(comp, TOPN, offset=0, slip=SLIP_STRESS, fused=fused)
    rets = o0["ret"]
    idx = rets.index.intersection(rB.index)
    rr, rb = rets.reindex(idx), rB.reindex(idx)
    corr = float(np.corrcoef(rr, rb)[0, 1]) if len(idx) > 30 else np.nan
    mid = idx[len(idx) // 2] if len(idx) >= 260 else None
    halves = {}
    if mid is not None:
        for tag, sl in (("h1", idx[idx < mid]), ("h2", idx[idx >= mid])):
            p = perf_ret(rets.reindex(sl))
            halves[tag] = {"sharpe": p["sharpe"], "ann_pct": p["ann_pct"],
                           "mdd_pct": p["mdd_pct"], "window": [str(sl[0].date()), str(sl[-1].date())]}
        halves["same_sign"] = bool((halves["h1"]["sharpe"] or 0) > 0 and (halves["h2"]["sharpe"] or 0) > 0)
    out = dict(
        leg=name, engine_mode=("fused(候选不足N→N_eff=min(N,#cand),单笔仍 eq/N)" if fused else "frozen(原封)"),
        cand=dict(dens), n_rebal=int(o0["n_rebal"]), n_rebal_skipped=int(o0["n_rebal_skipped"]),
        invested_mean=round(float(o0["invested_mean"]), 4),
        phmed_sharpe=round(float(np.median(shs)), 3), sharpe_min=round(float(np.min(shs)), 3),
        sharpe_max=round(float(np.max(shs)), 3),
        phase_sharpes={str(k): round(v["sharpe"], 4) for k, v in per.items()},
        slip50_sharpe=round(float(m50["sharpe"]), 3), slip50_ann_pct=round(float(m50["ann"]) * 100, 2),
        off0_ann_pct=round(float(o0["ann"]) * 100, 2), off0_sharpe=round(float(o0["sharpe"]), 3),
        off0_vol_pct=round(float(o0["vol"]) * 100, 2), off0_mdd_pct=round(float(o0["mdd"]) * 100, 2),
        n_trades=int(o0["n_trades"]), win=(round(float(o0["win"]), 4) if np.isfinite(o0["win"]) else None),
        by_year_pct={int(y): round(v * 100, 1) for y, v in o0["by_year"].items()},
        corr_B=round(corr, 3) if np.isfinite(corr) else None,
        align_n=int(len(idx)), align_start=str(idx[0].date()), align_end=str(idx[-1].date()),
        halves=halves)
    out["pass_G1"] = bool(out["corr_B"] is not None and out["corr_B"] <= GATES["corr_B_max"])
    out["pass_G2"] = bool(out["phmed_sharpe"] >= GATES["phmed_sharpe_min"]
                          and out["slip50_sharpe"] >= GATES["slip50_sharpe_min"])
    out["pass_G4_samesign"] = bool(halves.get("same_sign", False))
    out["pass_all"] = bool(out["pass_G1"] and out["pass_G2"] and out["pass_G4_samesign"])
    return out, o0, m50


def combo_layer(rB, rl, cashB, name, out_entry):
    """(i) 现金端 r_new = r_B + λ·c_t·r_L ；(ii) 增量资金 主仓:候选 混合边际"""
    idx = rB.index
    cB = cashB.reindex(idx).fillna(0.0)
    entry = {"leg": name, "cash_frac_median": round(float(cB.median()), 4),
             "cash_frac_mean": round(float(cB.mean()), 4), "cash_i": {}, "increment": {}}
    rb = rB.reindex(idx); base = perf_ret(rb)
    entry["base_100B"] = base
    rl = rl.reindex(idx).fillna(0.0)
    for lam in (0.25, 0.50, 0.75, 1.00):
        v = perf_ret(rb + lam * cB * rl)
        v["d_sharpe"] = round((v["sharpe"] or 0) - (base["sharpe"] or 0), 3)
        v["d_ann_pp"] = round((v["ann_pct"] or 0) - (base["ann_pct"] or 0), 2)
        v["d_calmar"] = round((v["calmar"] or 0) - (base["calmar"] or 0), 2)
        v["d_mdd_pp"] = round((v["mdd_pct"] or 0) - (base["mdd_pct"] or 0), 2)
        v["gate"] = bool(v["d_sharpe"] >= GATES["blend_dsharpe_min"]
                         and (v["calmar"] or 0) >= (base["calmar"] or 0))
        entry["cash_i"][f"lam{int(lam*100)}"] = v
    for M in (85_000.0, 170_000.0):
        for alpha in (0.5, 1.0):
            wB = (CASH0 + (1 - alpha) * M) / (CASH0 + M); wC = alpha * M / (CASH0 + M)
            v = perf_ret(wB * rb + wC * rl)
            v["wB"] = round(wB, 4); v["wC"] = round(wC, 4)
            v["d_sharpe"] = round((v["sharpe"] or 0) - (base["sharpe"] or 0), 3)
            v["d_ann_pp"] = round((v["ann_pct"] or 0) - (base["ann_pct"] or 0), 2)
            v["d_calmar"] = round((v["calmar"] or 0) - (base["calmar"] or 0), 2)
            v["gate"] = bool(v["d_sharpe"] >= GATES["blend_dsharpe_min"])
            entry["increment"][f"M{int(M/1000)}k_a{int(alpha*100)}"] = v
    entry["cash_i_best_dS"] = max((v["d_sharpe"] for v in entry["cash_i"].values()), default=None)
    entry["increment_best_dS"] = max((v["d_sharpe"] for v in entry["increment"].values()), default=None)
    entry["combo_improve"] = bool(max(entry["cash_i_best_dS"] or -9, entry["increment_best_dS"] or -9)
                                  >= GATES["blend_dsharpe_min"])
    return entry


# ============================================================ 2) 因子构造
def build_fenzhi(G):
    """#16 分歧弱转强（原文逐句复刻，通达信语义）—— 与 v1 逐字一致"""
    O, H, L, C = (G["O"].astype(np.float64), G["H"].astype(np.float64),
                  G["L"].astype(np.float64), G["C"].astype(np.float64))
    V = G["V"].astype(np.float64)
    valid = np.isfinite(O) & np.isfinite(H) & np.isfinite(L) & np.isfinite(C) & (C > 0)
    ND, NC = C.shape
    XG = np.zeros((ND, NC), bool)
    cnt = dict(zt=0, nb=0, g1=0, g2=0, g3=0, g4=0, xg=0, stocks_with_xg=0)
    for j in range(NC):
        m = valid[:, j]
        if m.sum() < 130:
            continue
        c = C[m, j]; o = O[m, j]; h = H[m, j]; l = L[m, j]; v = V[m, j]
        n = len(c)
        pv = np.concatenate([[np.nan], c[:-1]])
        ret = c / pv - 1
        x_zt = (np.abs(c - h) <= np.maximum(1e-8, h * 1e-6)) & (ret >= 0.095)
        x_zt = np.nan_to_num(x_zt, nan=False).astype(bool)
        cnt["zt"] += int(x_zt.sum())
        m5 = pd.Series(c).rolling(5, min_periods=5).mean().to_numpy()
        m10 = pd.Series(c).rolling(10, min_periods=10).mean().to_numpy()
        v5 = pd.Series(v).rolling(5, min_periods=5).mean().to_numpy()
        v10 = pd.Series(v).rolling(10, min_periods=10).mean().to_numpy()
        hh3 = pd.Series(c).rolling(3, min_periods=3).max().to_numpy()
        zt_cnt10 = pd.Series(x_zt.astype(float)).rolling(10, min_periods=10).sum().to_numpy()
        x_nb = x_zt & (np.abs(zt_cnt10 - 1) < 1e-9) & (c / o > 1.05) & (l < np.concatenate([[np.nan], h[:-1]]))
        x_nb = np.nan_to_num(x_nb, nan=False).astype(bool)
        cnt["nb"] += int(x_nb.sum())
        x_n1 = np.full(n, -1, int); last = -1
        for k in range(n):
            x_n1[k] = k - last if last >= 0 else -1
            if x_nb[k]:
                last = k
        zg = (c / pv - 1) * 100
        for k in range(n):
            n1 = x_n1[k]
            if n1 < 3 or k - n1 < 0:
                continue
            i0 = k - n1
            g1 = (v10[k] > v5[k]) and (v10[k - 1] <= v5[k - 1]) if np.isfinite(v10[k]) else False
            if g1:
                g1 = bool(np.sum(x_zt[i0 + 1:k + 1]) == 0) and bool(np.all(m5[i0 + 1:k + 1] > m10[i0 + 1:k + 1]))
            cnt["g1"] += int(g1)
            hhv_win = np.nanmax(c[i0 + 1:k + 1])
            ref_hh3 = hh3[k - n1 + 2] if (n1 - 3 >= 0) else np.nan
            g2 = np.isfinite(ref_hh3) and (abs(hhv_win - ref_hh3) < max(1e-8, abs(ref_hh3) * 1e-6)) \
                and bool(np.nanmin(zg[i0 + 1:k + 1]) > -10)
            cnt["g2"] += int(g2)
            g3 = bool(np.nanmin(l[i0 + 1:k + 1]) > 1.03 * o[i0]) and bool(v[k] == np.nanmin(v[i0 + 1:k + 1]))
            cnt["g3"] += int(g3)
            g4 = np.isfinite(m10[k]) and np.isfinite(m5[k]) and (m10[k] > m5[k]) and (m10[k - 1] <= m5[k - 1]) \
                and bool(c[k] > np.nanmin(l[i0 + 1:k + 1]))
            cnt["g4"] += int(g4)
            if g2 and g3 and g4:
                kp = k - 1
                if kp > i0:
                    g1p = np.isfinite(v10[kp]) and (v10[kp] > v5[kp]) and (v10[kp - 1] <= v5[kp - 1])
                    if g1p:
                        g1p = bool(np.sum(x_zt[i0 + 1:kp + 1]) == 0) and \
                              bool(np.all(m5[i0 + 1:kp + 1] > m10[i0 + 1:kp + 1]))
                    if g1p:
                        gidx = np.flatnonzero(m)[k]
                        XG[gidx, j] = True
                        cnt["xg"] += 1
    cnt["stocks_with_xg"] = int((XG.sum(axis=0) > 0).sum())
    return XG, cnt


def signal_state(XG, win):
    """事件信号 → 截面分：信号后 win 日内 = 1-越近越高，否则 NaN（稀疏）"""
    ND, NC = XG.shape
    out = np.full((ND, NC), np.nan)
    last = np.full(NC, -1, int)
    for i in range(ND):
        row = XG[i]
        if row.any():
            last[row] = i
        ds = i - last
        ok = (last >= 0) & (ds <= win)
        out[i, ok] = 1.0 - ds[ok] / (win + 1.0)
    return out


def build_pca_turnover(G, mode="pca"):
    """#42 PCA 特质换手波动率（21 日窗 + 截面 PCA + 逐股残差 std）"""
    V = G["V"].astype(np.float64)
    ND, NC = V.shape
    W = 21
    out = np.full((ND, NC), np.nan); ev1 = np.full(ND, np.nan); nkeep = np.zeros(ND, int)
    for i in range(W - 1, ND):
        blk = V[i - W + 1:i + 1, :]
        keep = np.isfinite(blk).sum(axis=0) > 0
        if keep.sum() < 50:
            continue
        Y = np.where(np.isfinite(blk[:, keep]), blk[:, keep], 0.0)
        nan_mask = ~np.isfinite(blk[:, keep])
        mu = Y.mean(axis=0, keepdims=True); sd = Y.std(axis=0, keepdims=True)
        sd = np.where(sd > 0, sd, 1.0)
        Z = (Y - mu) / sd
        if mode == "pca":
            U, S, Vt = np.linalg.svd(Z - Z.mean(axis=0, keepdims=True), full_matrices=False)
            k = min(2, S.size)
            tot = np.sum(S ** 2)
            evr = (S[:k] ** 2) / tot if tot > 0 else np.zeros(k)
            nk = 2 if (k >= 2 and evr[0] < 0.2) else 1
            X = U[:, :nk] * S[:nk]
        else:
            X = Z.mean(axis=1, keepdims=True); nk = 1; evr = np.array([np.nan])
        A = np.c_[np.ones(X.shape[0]), X]
        beta, *_ = np.linalg.lstsq(A, Y, rcond=None)
        resid = np.where(nan_mask, np.nan, Y - A @ beta)
        with np.errstate(all="ignore"):
            sig = np.nanstd(resid, axis=0, ddof=1)
        out[i, keep] = sig
        ev1[i] = evr[0] if len(evr) else np.nan
        nkeep[i] = nk
    return out, dict(ev1_median=round(float(np.nanmedian(ev1)), 4),
                     nkeep_frac2=round(float((nkeep == 2).mean()), 4),
                     note="换手率用成交量替代（StandardScaler 逐列对个股常数因子不变 → 等价）；"
                          "numpy SVD 复刻 sklearn PCA；残差 std ddof=1")


def build_bijunliang(G):
    """#3 笔均量/均笔额 —— 无「成交笔数」列 → 按任务书用 amount/volume(VWAP) 代理（显式申报）"""
    V = G["V"].astype(np.float64); AMT = G["AMT"].astype(np.float64)
    with np.errstate(all="ignore"):
        VWAP = np.where((V > 0) & np.isfinite(AMT), AMT / V, np.nan)
        lv = np.log(np.where(VWAP > 0, VWAP, np.nan))
    mv20 = pd.DataFrame(lv).rolling(20, min_periods=15).mean().to_numpy()
    mv60 = pd.DataFrame(lv).rolling(60, min_periods=40).mean().to_numpy()
    vwap_z = lv - mv20
    vwap_pos = lv - mv60
    ret1 = pd.DataFrame(G["close_ff"]).pct_change().to_numpy()
    amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
    with np.errstate(all="ignore"):
        amihud = -np.abs(ret1) / np.where(amt20 > 0, amt20, np.nan) * 1e9
    Lf = G["L"].astype(np.float64); Hf = G["H"].astype(np.float64)
    lo60 = pd.DataFrame(Lf).rolling(60, min_periods=40).min().to_numpy()
    hi60 = pd.DataFrame(Hf).rolling(60, min_periods=40).max().to_numpy()
    cff = G["close_ff"]
    with np.errstate(all="ignore"):
        rp60 = (cff - lo60) / np.where(hi60 > lo60, hi60 - lo60, np.nan)
    ret20 = cff / pd.DataFrame(cff).shift(20).to_numpy() - 1
    up = (vwap_z > 0).astype(np.float64)
    up_cnt = pd.DataFrame(up).rolling(5, min_periods=5).sum().to_numpy()
    R1 = np.where((rp60 <= 0.3) & (up_cnt >= 3) & (ret20 <= 0), 1.0, 0.0)
    vol20 = pd.DataFrame(V).rolling(20, min_periods=15).mean().to_numpy()
    brk60 = np.where(cff >= hi60 * 0.999, 1.0, 0.0)
    R2 = np.where((brk60 > 0) & (V >= 1.5 * vol20) & (vwap_z < 0), 1.0, 0.0)
    EL = G["ELIG3"]
    return dict(vwap_z=vwap_z, vwap_pos=vwap_pos, amihud=amihud, R1=R1, R2=R2,
                R1_n=int(np.nansum(np.where(EL, R1, np.nan))),
                R2_n=int(np.nansum(np.where(EL, R2, np.nan))))


def build_gaidiebudie(G):
    """#4「该跌不跌」龙头相对强度（1-2天/1-2周/1-2月/3月 + 大盘关键位）"""
    C = G["close_ff"]
    hs = pd.read_csv(BASE / "index_000300.csv", parse_dates=["date"])
    hs["d"] = hs["date"].dt.strftime("%Y-%m-%d")
    hs = hs.drop_duplicates("d").set_index("d")["close"].reindex([str(d)[:10] for d in G["cal"]]).ffill()
    hsv = hs.to_numpy(dtype=np.float64)
    out = {}
    for W, tag in ((2, "rs2"), (10, "rs10"), (20, "rs20"), (60, "rs60")):
        sr = C / pd.DataFrame(C).shift(W).to_numpy() - 1
        br = hsv / np.concatenate([np.full(W, np.nan), hsv[:-W]]) - 1
        out[tag + "_excess"] = sr - br[:, None]
        out[tag + "_gdbd"] = np.where((br < 0)[:, None] & (sr >= 0), 1.0, 0.0)
    lo250 = pd.Series(hsv).rolling(250, min_periods=120).min().to_numpy()
    hi250 = pd.Series(hsv).rolling(250, min_periods=120).max().to_numpy()
    with np.errstate(all="ignore"):
        hsl_pos = (hsv - lo250) / np.where(hi250 > lo250, hi250 - lo250, np.nan)
    out["_keylevel_mask"] = ((hsl_pos <= 0.30) | (hsv / lo250 - 1 <= 0.05)).astype(float)
    out["_hs"] = hsv
    return out


# ============================================================ 3) 主流程
STATE = {"legs": [], "combos": {}, "kb5_event_test": {}}


def dump(status="partial", META=None):
    payload = {"meta": {}, "n_legs": len(STATE["legs"]), "legs": STATE["legs"],
               "combos": STATE["combos"], "kb5_event_test": STATE["kb5_event_test"]}
    if META is not None:
        STATE["_meta"] = META
    payload["meta"] = {**STATE.get("_meta", {}), "status": status}
    RES.write_text(json.dumps(jsafe(payload), ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"  [落盘] {RES.name} ← {len(STATE['legs'])} 腿 / {len(STATE['combos'])} 组合层（status={status}）")


def append_report(lines, reset=False):
    if reset or not REPORT.exists():
        REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        with REPORT.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    log(f"  [报告] {REPORT.name} ← 追加 {len(lines)} 行")


def leg_block(r):
    """报告用：单腿 markdown 片段"""
    h1, h2 = r["halves"].get("h1", {}), r["halves"].get("h2", {})
    yz = " / ".join(f"{y}:{v:+.0f}%" for y, v in sorted(r["by_year_pct"].items()))
    return [
        f"### {r['leg']}",
        f"- 口径：{r['desc']} | 方向 `{r['direction']}` | kb={r['kb']} | 引擎 {r['engine_mode']}",
        f"- 截面候选：中位 {r['cand']['median_act']} 只 / 均值 {r['cand']['mean_act']} / 最大 {r['cand']['max']} / "
        f"≥20 的日数 {r['cand']['days_ge_topn']}；再平衡 {r['n_rebal']} 次（跳过 {r['n_rebal_skipped']} 次）；"
        f"平均持仓市值占账户 {r['invested_mean']*100:.1f}%",
        f"- **相位中位夏普 {r['phmed_sharpe']:+.3f}**（min {r['sharpe_min']:+.3f} / max {r['sharpe_max']:+.3f}）；"
        f"各相位 {r['phase_sharpes']}",
        f"- off0：年化 {r['off0_ann_pct']:+.2f}% / 夏普 {r['off0_sharpe']:+.3f} / 波动 {r['off0_vol_pct']:.2f}% / "
        f"**回撤 {r['off0_mdd_pct']:.2f}%** / {r['n_trades']} 笔 / 胜率 {r['win']}",
        f"- 50bp 档：夏普 {r['slip50_sharpe']:+.3f} / 年化 {r['slip50_ann_pct']:+.2f}%",
        f"- **corr vs 轨B {r['corr_B']}**（对齐 {r['align_n']} 日 {r['align_start']}→{r['align_end']}）",
        f"- 分半：h1 夏普 {h1.get('sharpe')}（{h1.get('window')}） / h2 夏普 {h2.get('sharpe')}（{h2.get('window')}）"
        f" → 同号 **{r['halves'].get('same_sign')}**",
        f"- 逐年：{yz}",
        f"- 闸门：corr≤0.3 **{r['pass_G1']}** | 相位中位≥0.5 ∧ 50bp≥0.3 **{r['pass_G2']}** | "
        f"分半同号 **{r['pass_G4_samesign']}** → **总判定 {'PASS' if r['pass_all'] else '未通过'}**",
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--only", type=str, default="kb1,kb2,kb3,kb4")
    ap.add_argument("--report-reset", action="store_true")
    a = ap.parse_args()
    ONLY = set(x.strip() for x in a.only.split(",") if x.strip())

    G, rB, rBfull, annB, uni_aud = load_engine()
    runner, verify = make_runner(G)
    log("[复刻自检] 逐点/夏普/笔数 差异（off,slip → Δmax净值, Δ夏普, 复刻笔数, 冻结笔数）：")
    vv = verify()
    maxd = max(v[0] for v in vv.values())
    for k, v in vv.items():
        log(f"    {k:16s} Δnet={v[0]:.2e} ΔS={v[1]:.2e} trades {v[2]}/{v[3]}")
    assert maxd < 1e-9, "复刻引擎与冻结引擎不一致，拒绝继续"
    log(f"[复刻自检] 通过（最大逐点差 {maxd:.2e}）→ fused=False 与原封冻结引擎逐位一致")

    eqB2, cashB, _ = None, None, None
    comp_B = G["composite"]()
    mB = runner(comp_B, TOPN, offset=0)
    cashB = mB["cash_w"]
    del comp_B; gc.collect()
    log(f"[轨B 现金端] 闲置现金权重 中位 {cashB.median():.3f} / 均值 {cashB.mean():.3f} | "
        f"平均持仓 {mB['invested_mean']*100:.1f}%")

    cal = G["cal"]; ND, NC = G["C"].shape
    log(f"[面板] {ND} 交易日 × {NC} 只 | {str(cal[0])[:10]} → {str(cal[-1])[:10]}")

    META = {
        "date": "2026-09-16", "batch": "kb_top5_batch1", "version": "v2 (NaN 修复版)",
        "universe": "mainboard(sh60|sz00)", "universe_audit": uni_aud,
        "engine": "oss_0913/oss_super_combo_0913.py 前缀 run_engine；本脚本用其逐行复刻 runner",
        "engine_replica_check": {k: {"max_abs_equity_diff": v[0], "d_sharpe": v[1],
                                     "trades_replica": v[2], "trades_frozen": v[3]} for k, v in vv.items()},
        "sparse_signal_adapter": "候选数 < N(20) 时 N_eff=min(N,#cand)、建仓门 >=1；单笔资金切分仍 eq/N "
                                 "→ 未满仓部分留现金；对生产 composite 与冻结引擎逐位一致（自检 diff<1e-9）",
        "nan_diagnosis": "v1 全 NaN 根因：kb1 稀疏事件信号每日候选 max 9 < N=20 → 冻结引擎建仓门 "
                         "`ok.sum() >= N` 永假 → 0 笔成交 → 净值恒现金 → 日收益 std=0 → 夏普/相关性 NaN。"
                         "非数据缺失（XG 事件 164 个、147 个交易日有信号）。",
        "topn": TOPN, "phases": PHASES, "slip_main_bps": SLIP_MAIN * 1e4,
        "slip_stress_bps": SLIP_STRESS * 1e4, "cash0": CASH0, "gates": GATES,
        "trackB": {"off0_ann_pct": round(annB, 2), "official_full_universe": 22.87,
                   "off0_sharpe": round(float(rBfull["sharpe"]), 3),
                   "off0_mdd_pct": round(float(rBfull["mdd"]) * 100, 2),
                   "n_trades": int(rBfull["n_trades"]),
                   "window": [str(rBfull["equity"].index[0].date()), str(rBfull["equity"].index[-1].date())]},
        "combo_layer_rule": "修正口径（2026-09-16）：不从轨B挪仓位。(i) 现金端 r_new=r_B+λ·c_t·r_L"
                            "（c_t=轨B实测闲置现金权重）；(ii) 增量资金 主仓:候选 混合边际。"
                            "任一 ΔSharpe≥+0.02 且 Calmar 不降 → 组合层改善",
        "source": "backtest/清单-知识库未测策略存量分类-20260916.md §7.2 Top20 / §7.5 首批5条",
        "origin_audit": ORIGIN_AUDIT,
        "data_gaps": DATA_GAPS,
    }
    STATE["_meta"] = META

    def record(name, mat, kb, desc, direction, approx=None):
        comp = zcomp(mat, G["ELIG3"])
        del mat; gc.collect()
        r, o0, m50 = eval_leg(G, runner, rB, comp, name, smoke=a.smoke)
        r["kb"] = kb; r["desc"] = desc; r["direction"] = direction; r["approx"] = approx
        log(f"  [{name:20s}] 引擎={r['engine_mode'][:6]} 候选max{r['cand']['max']:>4} | "
            f"phmed {r['phmed_sharpe']:+.3f} | 50bp {r['slip50_sharpe']:+.3f} | "
            f"off0 年化 {r['off0_ann_pct']:+.1f}% S{r['off0_sharpe']:+.2f} "
            f"mdd {r['off0_mdd_pct']:6.1f}% | corrB {r['corr_B']} | "
            f"{'PASS' if r['pass_all'] else ' -  '}")
        STATE["legs"] = [x for x in STATE["legs"] if x["leg"] != name] + [r]
        STATE["combos"][name] = combo_layer(rB, o0["ret"], cashB, name, r)
        c = STATE["combos"][name]
        log(f"  [组合层·{name:20s}] 现金端 bestΔS {c['cash_i_best_dS']:+.3f} | "
            f"增量 bestΔS {c['increment_best_dS']:+.3f} | 改善={'YES' if c['combo_improve'] else 'NO'}")
        dump("running")
        append_report(leg_block(r))
        del comp; gc.collect()
        return r

    if a.report_reset or not REPORT.exists():
        append_report(REPORT_HEADER, reset=True)

    # ---------------- kb1 分歧弱转强 ----------------
    if "kb1" in ONLY:
        log("[kb1] 分歧弱转强 信号计算（通达信语义逐股循环）…")
        XG, cnt = build_fenzhi(G)
        META["kb1_signal_census"] = cnt
        log(f"[kb1] X_ZT {cnt['zt']} | X_NB(首板) {cnt['nb']} | GSZJ1 {cnt['g1']} | GSZJ2 {cnt['g2']} | "
            f"GSZJ3 {cnt['g3']} | GSZJ4 {cnt['g4']} | **XG {cnt['xg']}** | 有信号个股 {cnt['stocks_with_xg']}")
        ev = kb1_event_stats(G, XG)
        META["kb1_event_stats"] = ev
        log(f"[kb1] 事件级验证（T+1 开盘买，n={ev['n_events']}）：" +
            " | ".join(f"后{k}日 超额均值 {v['excess_mean_pct']:+.2f}% 中位 {v['excess_med_pct']:+.2f}% "
                       f"胜率 {v['win']*100:.0f}%" for k, v in ev["fwd"].items()))
        for win in ([10, 20] if a.smoke else [10, 20, 30]):
            record(f"fenzhi_w{win}", signal_state(XG, win), "kb1",
                   f"分歧弱转强事件后 {win} 日内按新鲜度排序（稀疏事件信号→截面分，非信号=空）",
                   "long", approx="ZTPRICE 用 ret≥9.5%∧C=H 近似；X_N1<3 不判")
        append_report(kb1_report_block(ev, cnt, [x for x in STATE["legs"] if x["kb"] == "kb1"]))
        dump("kb1 done")

    # ---------------- kb2 PCA 特质换手波动率 ----------------
    if "kb2" in ONLY:
        log("[kb2] PCA 特质换手波动率 计算（21 日窗 × 1381 日 SVD）…")
        sig_pca, pca_info = build_pca_turnover(G, "pca")
        META["kb2_pca_info"] = pca_info
        log(f"[kb2] PC1 解释度中位 {pca_info['ev1_median']} | 取 2 主成分日占比 {pca_info['nkeep_frac2']}")
        record("pca_sigma_lo", -sig_pca, "kb2", "PCA 残差 std（PC1 解释），低值做多＝原文「空头因子」方向", "lo")
        record("pca_sigma_hi", sig_pca, "kb2", "PCA 残差 std（PC1 解释），高值做多＝反向对照", "hi")
        del sig_pca; gc.collect()
        sig_mean, _ = build_pca_turnover(G, "mean")
        record("mean_sigma_lo", -sig_mean, "kb2", "残差 std（**截面均值**解释）＝原文自述对照臂，低值做多", "lo")
        record("mean_sigma_hi", sig_mean, "kb2", "残差 std（截面均值解释），高值做多", "hi")
        del sig_mean; gc.collect()
        dump("kb2 done")

    # ---------------- kb3 笔均量/均笔额（VWAP 代理） ----------------
    if "kb3" in ONLY:
        log("[kb3] 笔均量/均笔额 VWAP 代理 计算…")
        B = build_bijunliang(G)
        META["kb3_proxy"] = {"proxy": "amount/volume(VWAP)", "R1_n_days": B["R1_n"], "R2_n_days": B["R2_n"],
                             "declared_approx": "VWAP 度量平均成交价，非每笔规模 → 代理有效性弱，结论不可外推原文"}
        log(f"[kb3] 原文规则命中（日×股）：R1(底部吸筹) {B['R1_n']} | R2(创新高背离) {B['R2_n']}")
        record("vwap_z_hi", B["vwap_z"], "kb3", "VWAP 相对自身 20 日均值（自比），高值做多", "hi")
        record("vwap_z_lo", -B["vwap_z"], "kb3", "VWAP 相对自身 20 日均值（自比），低值做多", "lo")
        record("amihud_hi", B["amihud"], "kb3", "Amihud 冲击 −|ret|/amount20（大单/冲击代理），高值做多", "hi")
        record("R1_bottom", B["R1"], "kb3", "原文 R1：rp60≤0.3 ∧ VWAP自比连5日中≥3日>0 ∧ ret20≤0", "rule")
        record("R1mR2", np.where(np.isnan(B["R1"]), np.nan, B["R1"] - B["R2"]), "kb3",
               "原文 R1 正向 − R2（创新高背离剔除）", "rule")
        del B; gc.collect()
        dump("kb3 done")

    # ---------------- kb4 该跌不跌 ----------------
    if "kb4" in ONLY:
        log("[kb4] 该跌不跌相对强度 计算…")
        D = build_gaidiebudie(G)
        META["kb4_keylevel_frac"] = round(float(np.mean(D["_keylevel_mask"])), 4)
        log(f"[kb4] 大盘关键位（hs300 近250日区间分位≤0.3 或距低点≤5%）占比 {META['kb4_keylevel_frac']:.3f}")
        for tag, W, human in (("rs2", 2, "1-2天"), ("rs10", 10, "1-2周"), ("rs20", 20, "1-2月"), ("rs60", 60, "3月")):
            record(f"{tag}_hi", D[tag + "_excess"], "kb4", f"个股−hs300 {W}日超额（{human}），高值做多", "hi")
        record("rs60_lo", -D["rs60_excess"], "kb4", "3月超额，低值做多（反向对照）", "lo")
        for tag, W in (("rs10", 10), ("rs60", 60)):
            record(f"gdbd{W}", D[tag + "_excess"] + 0.05 * D[tag + "_gdbd"], "kb4",
                   f"「该跌不跌」增强：{W}日超额 + 0.05×[大盘跌∧个股不跌]", "rule")
        record("rs60_keylevel", D["rs60_excess"] * np.where(D["_keylevel_mask"] > 0, 1.0, 0.2), "kb4",
               "3月超额 × 关键位权重（关键位 1.0 / 非关键位 0.2）", "rule")
        del D; gc.collect()
        dump("kb4 done")

    # ---------------- 汇总表 ----------------
    lines = summary_block(STATE, META)
    append_report(lines)
    dump("complete")
    log("[done] 全部落盘")


def kb1_event_stats(G, XG, ks=(5, 10, 20, 30)):
    """事件级验证：信号日 k → T+1 开盘买入，持有 ks 日 → 个股收益与超额（vs hs300）"""
    O = G["O"].astype(np.float64); C = G["close_ff"]
    hs = pd.read_csv(BASE / "index_000300.csv", parse_dates=["date"])
    hs["d"] = hs["date"].dt.strftime("%Y-%m-%d")
    hsv = hs.drop_duplicates("d").set_index("d")["close"].reindex(
        [str(d)[:10] for d in G["cal"]]).ffill().to_numpy(dtype=np.float64)
    ii, jj = np.nonzero(XG)
    ND = O.shape[0]
    # 同窗「沪深300 超额」分母：主板等权（全 ELIG 等权日收益累乘）
    R1 = pd.DataFrame(C).pct_change().to_numpy()
    EL = G["ELIG3"]
    with np.errstate(all="ignore"):
        mkt = np.nanmean(np.where(EL, R1, np.nan), axis=1)
    out = {"n_events": int(len(ii)), "fwd": {}}
    for k in ks:
        sr_list, ex, exm = [], [], []
        for a_, b_ in zip(ii, jj):
            e = a_ + 1 + k
            if e >= ND or not np.isfinite(O[a_ + 1, b_]):
                continue
            sr = C[e, b_] / O[a_ + 1, b_] - 1
            bh = hsv[e] / hsv[a_ + 1] - 1
            mr = np.nanprod(1 + np.where(np.isfinite(mkt[a_ + 1:e + 1]), mkt[a_ + 1:e + 1], 0)) - 1
            sr_list.append(sr); ex.append(sr - bh); exm.append(sr - mr)
        if not sr_list:
            continue
        out["fwd"][int(k)] = dict(n=len(sr_list),
                                  ret_mean_pct=round(float(np.mean(sr_list)) * 100, 2),
                                  ret_med_pct=round(float(np.median(sr_list)) * 100, 2),
                                  win=round(float(np.mean(np.array(sr_list) > 0)), 3),
                                  excess_mean_pct=round(float(np.mean(ex)) * 100, 2),
                                  excess_med_pct=round(float(np.median(ex)) * 100, 2),
                                  excess_win=round(float(np.mean(np.array(ex) > 0)), 3),
                                  excess_mkt_mean_pct=round(float(np.mean(exm)) * 100, 2))
    return out


def kb1_report_block(ev, cnt, legs1):
    ln = ["", "## kb1 分歧弱转强（页1 §1.3 #16）", "",
          f"信号命中普查：X_ZT={cnt['zt']} / X_NB 首板={cnt['nb']} / GSZJ1={cnt['g1']} / GSZJ2={cnt['g2']} / "
          f"GSZJ3={cnt['g3']} / GSZJ4={cnt['g4']} / **XG={cnt['xg']}**（{cnt['stocks_with_xg']} 只个股）",
          "", "**事件级验证**（信号日 T 的 T+1 开盘买入、持有 k 个交易日、不减成本）：", "",
          "| 持有 k 日 | n | 个股收益均值 | 中位 | 胜率 | 超额 vs 沪深300 均值 | 中位 | 超额胜率 | 超额 vs 主板等权 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for k, v in ev["fwd"].items():
        ln.append(f"| {k} | {v['n']} | {v['ret_mean_pct']:+.2f}% | {v['ret_med_pct']:+.2f}% | {v['win']*100:.1f}% | "
                  f"{v['excess_mean_pct']:+.2f}% | {v['excess_med_pct']:+.2f}% | {v['excess_win']*100:.1f}% | "
                  f"{v['excess_mkt_mean_pct']:+.2f}% |")
    return ln


def summary_block(STATE, META):
    legs = STATE["legs"]
    ln = ["", "---", "", "## 汇总表（全部腿）", "",
          "| 条目 | 腿 | 引擎 | 相位中位夏普 | 50bp | off0 年化 | 回撤 | corr vs 轨B | 分半同号 | 组合层ΔS | 判定 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in legs:
        c = STATE["combos"].get(r["leg"], {})
        ds = max(c.get("cash_i_best_dS") or -9, c.get("increment_best_dS") or -9)
        ln.append(f"| {r['kb']} | {r['leg']} | {r['engine_mode'][:6]} | **{r['phmed_sharpe']:+.3f}** | "
                  f"{r['slip50_sharpe']:+.3f} | {r['off0_ann_pct']:+.2f}% | {r['off0_mdd_pct']:.1f}% | "
                  f"{r['corr_B']} | {'Y' if r['pass_G4_samesign'] else 'N'} | {ds:+.3f} | "
                  f"{'PASS' if r['pass_all'] else '未通过'} |")
    ln += ["", "> 闸门：corr vs 轨B ≤0.30 ∧ 相位中位夏普 ≥0.50 ∧ 50bp 夏普 ≥0.30 ∧ 分半同号（两半夏普均>0）；"
           "组合层：ΔSharpe ≥ +0.02 且 Calmar 不降。", ""]
    return ln


REPORT_HEADER = [
    "# 报告 · 知识库 Top5 第一批回测（主板域）— 2026-09-16",
    "",
    "> 本文由 `backtest/kb_batch1_top5_0916.py` **跑一条追加一条**生成（防中断丢结论）。",
    "> 预注册来源：`backtest/清单-知识库未测策略存量分类-20260916.md` §7.2 Top20 / §7.5 首批 5 条。",
    "> 全部数字来自实际运行输出；近似与缺数据项逐条显式申报。",
    "",
    "**口径**：universe=主板(sh60|sz00，冻结面板本已全主板)；引擎=生产冻结 "
    "`oss_super_combo_0913.py 前缀 run_engine`（本脚本用其逐行复刻并与冻结版做逐位一致性自检）；"
    "基准自检 轨B off0 年化 = 22.87%；5 相位 0/4/8/12/16 取中位；双成本档 20bp/50bp；"
    "corr = 腿 off0 净日收益 vs 轨B off0 净日收益；组合层=**现金端 / 增量资金**（不从轨B挪仓位）。",
    "",
    "### NaN 诊断结论（v1 缺陷 → v2 修复）",
    "",
    "**根因一句话**：v1 把「无信号日=NaN」的稀疏事件信号直接喂给 N=20 的冻结引擎，而引擎建仓门为 "
    "`if ok.sum() >= N`；kb1 每日可用候选数最大仅 9 只（<20）→ 该门**永假** → 引擎 0 笔成交 → "
    "净值恒等于初始现金 → 日收益标准差 = 0 → 夏普/相关性 NaN、年化与回撤 0。**不是数据缺失**。",
    "",
    "**证据**（`backtest/_diag_kb1_nan_0916.py` 实跑输出）：",
    "",
    "```",
    "[Q1] 事件命中数：X_ZT=74601 X_NB(首板)=30432 GSZJ1=12383 GSZJ2=438343 GSZJ3=95561 GSZJ4=196302",
    "     **XG=164** 有信号个股=160 | 信号分布：147 个交易日有信号 2021-01-27 → 2026-08-31",
    "[Q2] win=10: 有候选交易日 769/1381 | 候选数 中位=2 均值=1.9 max=5  | >=20 的日数=0",
    "[Q2] win=20: 有候选交易日 995/1381 | 候选数 中位=2 均值=2.9 max=9  | >=20 的日数=0",
    "[Q2] win=30: 有候选交易日 1143/1381 | 候选数 中位=3 均值=3.7 max=10 | >=20 的日数=0",
    "[Q3] run_engine(comp_w20, N=20) -> n_trades=0 equity 首 170000.0 末 170000.0 日收益 std=0.00e+00 sharpe=nan",
    "[Q3] run_engine(comp_w20, N=5)  -> n_trades=34 equity 末 275385.8 sharpe=+0.509",
    "```",
    "",
    "→ 事件**非空集**（164 个 XG、147 个交易日），且仅依赖本地 O/H/L/C/V，**与「本地缺数据」无关**；"
    "缺陷在「稀疏事件信号 → N20 引擎」的映射：候选不足 20 时引擎整体跳过再平衡。",
    "→ **修复**：候选不足 N 时 `N_eff = min(N, #cand)` 且建仓门降为 ≥1（单笔资金切分仍用 eq/N，"
    "未满仓部分留现金）；对生产 composite 与冻结引擎**逐位一致**（自检 diff < 1e-9），只在稀疏域生效。",
    "",
]

DATA_GAPS = [
    "无「成交笔数」列（kb3 原文核心输入：笔均量=量÷笔数）→ 只能用 amount/volume(VWAP) 代理，"
    "VWAP 度量的是平均成交价而非每笔规模，**代理有效性弱**，结论不可外推原文；"
    "获取路径：通达信本地导出 / 东财分笔 / Tushare 逐笔",
    "无分钟/分时数据 → kb5 的 F1/F2/F4/E4 类（盘中时点）不可测",
    "前复权面板无法还原 2 位小数涨停价 → ZTPRICE / 涨停价均用 ret≥9.5%（主板）近似",
    "A5 事件为 2016-2026 全样本（v8 缓存口径），与冻结引擎面板（2021-01 起）不同源——"
    "kb5 为事件级独立口径，不进 run_engine",
]

ORIGIN_AUDIT = {
    "kb1": {"page": "页1 §1.3 #16", "src": "99-Archive/00raw-剪藏-20260827/公式之家/"
                                           "2026-07-25 - 通达信〖分歧弱转强〗指标套装，首板缩量回调共振选股模型.md",
            "verdict": "一致",
            "notes": ["X_FW:=CODELIKE('60') OR CODELIKE('00') → 原文显式主板限定，与清单一致",
                      "GSZJ4:=CROSS(M10,M5) 原文确为 MA10 上穿 MA5，清单照录一致",
                      "GSZJ2 的 REF(HHV(C,3),X_N1-3) 与 GSZJ3 的 REF(O,X_N1)=首板开盘价 逐字核对一致",
                      "实现近似（非阈值差异）：ZTPRICE 用「C=H ∧ ret≥9.5%」替代；X_N1<3 的窗口不判"]},
    "kb2": {"page": "页4 §4.2 J#42", "src": "99-Archive/00raw-剪藏-20260824/"
                                            "2026-08-22 - 用PCA提取主成分后，再计算残差波动，这个思路能带来显著提升吗？.md",
            "verdict": "一致",
            "notes": ["21 交易日截面 PCA → F1（解释度<20% 取前 2）→ 逐股时序回归 → 残差 std，与原文逐字一致",
                      "原文自述：sigma 最好、mu 次之、skew/ivr 差；且「IC 相比旧版仅微幅提升，"
                      "有的甚至不如直接用截面均值作解释变量」→ 本批加 mean 对照臂",
                      "原文明确「最大组（高 sigma）表现远差于其他组 = 典型空头因子」→ 做多方向为低 sigma",
                      "实现近似：换手率用成交量替代（逐列标准化下等价）；numpy SVD 复刻 sklearn PCA"]},
    "kb3": {"page": "页2 §2.3 09-16[2]", "src": "99-Archive/00raw-剪藏-20260916b/大财师兄/"
                                                "2026-09-16 - 成交量、成交额、成交笔数：三个概念的区别和搭配使用.md",
            "verdict": "一致（文字）；**原文无任何数字阈值**",
            "notes": ["笔均量=总成交量÷总成交笔数、均笔额=总成交额÷总成交笔数 —— 公式一致",
                      "原文阈值均为定性语（「连续多日维持较高水平」「萎缩」）→ **无数字可核对**；"
                      "本批把定性语操作化为：自比（相对自身 20/60 日均值）、连续多日=5 日中≥3 日、"
                      "「股价不涨」= ret20≤0、「低位」= rp60≤0.3、「量放大」= ≥1.5×20日均量（**这 4 个数字原文未给，属本批操作化**）",
                      "原文明确「笔均量不能横向比，只能自己跟自己比」→ 本批用自身历史相对口径"]},
    "kb4": {"page": "页3 §3.3 #12", "src": "99-Archive/00raw-剪藏-20260831/大阳金融研究所/"
                                            "2026-08-29 - 如何从全市场5000多只个股中选出龙头股？.md",
            "verdict": "一致（时间分档）；**原文另含清单未收录的对称条件**",
            "notes": ["时间分档 1-2天/1-2周/1-2月/3月 与清单一致（原文：一两天的背离可能是偶然…能横住三个月=三面共振）",
                      "原文另有「大盘创新低它不创新低，大盘反弹它创新高」→ 清单未收录；本批以 rs{n}_excess 与 "
                      "gdbd{n}（大盘跌∧个股不跌）覆盖其方向，未单独建「大盘创新低它不创新低」条件臂",
                      "关键位原文为「一个重要的底部，或者大盘的关键支撑位」（定性）→ 操作化为 hs300 近250日"
                      "区间分位≤0.30 或距250日低点≤5%（**阈值属本批操作化**）",
                      "实现近似：大盘用沪深300（本地最完整）而非上证指数"]},
    "kb5": {"page": "页6.1 打板战法 §1/§2", "src": "99-Archive/00raw-20260829/李韩薇/"
                                                     "2026-06-26 - 打板必看！4种绝对不能打的首板….md + "
                                                     "99-Archive/00raw-20260829/量化板上板/"
                                                     "2026-05-27 - 散户打板 一套从选股到卖出的完整交易系统….md",
            "verdict": "部分不一致（F3/F5/F9 见 notes）",
            "notes": ["F5 `MA5>MA10>MA20>MA60>MA120` 原文一字不差，但**原文极性是「第1步 入选必要条件」**，"
                      "清单归入「过滤族」→ 本批按原文极性：F5=必须满足",
                      "F7 `当前价距离布林带上轨≤1%` 原文一致（close≥上轨×0.99 等价）",
                      "F8 `RSI(14)≥85` 原文一字不差",
                      "F9「当日已触发一次冲板回落（最高价≥涨停价-1%，现价回落≥3%）」阈值一致，"
                      "但**原文未定义「回落」基准** → 本批用 (high−close)/high（属操作化）",
                      "**F3 不一致**：原文=「短期累计涨幅超过50%，处于近两三个月价格高点」+"
                      "「单日成交额是近20日均量的3倍以上」；清单转写为「20日累计涨幅>50%」，"
                      "原文**未给 20 日窗口**，且漏掉「近两三个月价格高点」条件 → 本批同时报 F3(清单转写) 与 "
                      "F3_orig(原文完整，高点=近60日高点×0.95 操作化)",
                      "F5/F7/F8 按「首板日」计算（原文为盘中决策日）"]},
}


if __name__ == "__main__":
    main()
