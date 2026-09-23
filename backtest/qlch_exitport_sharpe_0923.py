# -*- coding: utf-8 -*-
"""R-qlch-exitport-s-0923 · 出场规则组合级配对（配对 Δ夏普口径 · 功率先算后冻）

预注册：backtest/PRE-REGISTRATION_20260923_qlch_exitport_sharpe.md（待判据确认；未确认前只允许 --plumb）

统计量：ΔS = S_X4 - S_X0（年化），块 bootstrap（L=21，10,000）在同一批重采样交易日上同时重算两臂夏普。
判据：G1（CI 下界>0）/ G1-power（W<=0.43 则有功率，含 0 即否证；W>0.43 则不可判定）/ G2 双盲 / G3 成本机制 / G4 逐段。
"""
import argparse, importlib.util, json, math, sys, time
from pathlib import Path
import numpy as np

BK = Path(__file__).resolve().parent
GRID = "backtest/qlch_grid_bt_0923.py"
PREREG = "backtest/PRE-REGISTRATION_20260923_qlch_exitport_sharpe.md"
BFAM = BK / "qlch_bfamily_0923.json"
OUT = BK / "qlch_exitport_sharpe_0923.json"
VERSION = "qlch-exitport-sharpe-0923/v1"
COST_TIERS = {"P20": 0.0020, "S60": 0.0060}
RULES = {"X0": (15, -20, 20), "X1": (20, -30, 30), "X2": (20, -30, 40),
         "X3": (25, -30, 30), "X4": (25, -30, 40)}
COMPARISONS = [("X0", "X1"), ("X0", "X2"), ("X0", "X3"), ("X0", "X4")]
TARGET = ("X0", "X4")
V1_LO, V1_HI, V2_LO = "2022-01-04", "2024-06-28", "2024-07-01"
BLOCK, ANN, W_POWER = 21, 244.0, 0.43
REF_DS, REF_X4_SHARPE = 0.842, 2.010
T0 = time.time()


def log(*a):
    print("[%7.1fs] %s" % (time.time() - T0, " ".join(str(x) for x in a)), flush=True)


def ann_sharpe(r):
    sd = r.std(ddof=1)
    return float(r.mean() / sd * np.sqrt(ANN)) if sd > 0 else 0.0


def boot_ds(r0, r1, n_boot, L=BLOCK, seed=20260923, chunk=200):
    """配对块 bootstrap：同一批重采样交易日上同时重算两臂夏普。"""
    n = r0.size
    nb = int(np.ceil(n / L))
    hi = max(n - L, 0)
    rng = np.random.default_rng(seed)
    off = np.arange(L)
    out = np.full(n_boot, np.nan)
    got = 0
    while got < n_boot:
        m = min(chunk, n_boot - got)
        st = rng.integers(0, hi + 1, size=(m, nb))
        idx = (st[:, :, None] + off[None, None, :]).reshape(m, nb * L)[:, :n]
        A, B = r0[idx], r1[idx]
        sa, sb = A.std(axis=1, ddof=1), B.std(axis=1, ddof=1)
        d = np.full(m, np.nan)
        ok = (sa > 0) & (sb > 0)
        if ok.any():
            d[ok] = (B[ok].mean(axis=1) / sb[ok] - A[ok].mean(axis=1) / sa[ok]) * np.sqrt(ANN)
        out[got:got + m] = d
        got += m
    v = out[np.isfinite(out)]
    lo, hiq = np.percentile(v, [2.5, 97.5])
    W = float((hiq - lo) / 2.0)
    return {"dS": round(ann_sharpe(r1) - ann_sharpe(r0), 4),
            "S_base": round(ann_sharpe(r0), 4), "S_target": round(ann_sharpe(r1), 4),
            "ci95_lo": round(float(lo), 4), "ci95_hi": round(float(hiq), 4),
            "W": round(W, 4), "p_gt0": round(float((v > 0).mean()), 4),
            "n_days": int(n), "block": L, "n_boot": int(v.size),
            "power_ok": bool(W <= W_POWER),
            "power_detect_prob_at_ref": round(float(0.5 * math.erfc((1.96 * (W - REF_DS) / W) / math.sqrt(2))), 4) if W > 0 else 1.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--plumb", action="store_true")
    a = ap.parse_args()

    spec = importlib.util.spec_from_file_location("grid0923", str(BK / "qlch_grid_bt_0923.py"))
    g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
    assert (g.GAP_LO, g.GAP_HI) == (-0.05, -0.02)
    assert abs(g.COST_RT - 0.0020) < 1e-12 and abs(g.COST_TOT - 0.0060) < 1e-12
    assert g.K == 3 and g.SEEDS == [20260921, 20260922, 20260923, 20260924, 20260925]
    assert g.TRAIN_HI == "2021-12-31" and g.VAL_LO == "2022-01-01"
    for tp, sl, h in RULES.values():
        assert tp in g.TPS and sl in g.SLS and h in g.HS
    log("冻结项断言通过 | 功率门 W<=%.2f | 参照效应量 ΔS*=%.3f" % (W_POWER, REF_DS))

    eng = g.load_engine(); P = eng.load_all(); S = eng.build_signals(P)
    cal, T = S["cal"], S["close"].shape[0]
    ents = g.entry_cases(S)
    assert {k: int(ents[k]["e"].size) for k in "ABC"} == {"A": 3440, "B": 346, "C": 35412}
    log("事件数对拍 3440/346/35412 一致 ✓")
    all_e = np.concatenate([ents[k]["e"] for k in "ABC"])
    i_first = int(all_e.min())
    i_tr = max([i for i, d in enumerate(cal) if d <= g.TRAIN_HI] or [0])
    i_va = min([i for i, d in enumerate(cal) if d >= g.VAL_LO] or [T - 1])
    i_v1 = min([i for i, d in enumerate(cal) if d >= V1_LO] or [T - 1])
    i_v1h = max([i for i, d in enumerate(cal) if d <= V1_HI] or [0])
    i_v2 = min([i for i, d in enumerate(cal) if d >= V2_LO] or [T - 1])
    SL = {"full": (i_first, T - 1), "train": (i_first, i_tr), "val": (i_va, T - 1),
          "v1": (i_v1, i_v1h), "v2": (i_v2, T - 1)}

    d = ents["A"]; e, j, px = d["e"], d["j"], d["px"]
    kmax = max(h for _, _, h in RULES.values()) - 1
    Oa, Ha, La, Ca = g.case_path(e, j, S["open"], S["high"], S["low"], S["close"], T, kmax)
    runs, rets = {}, {}
    for name, (tp, sl, h) in RULES.items():
        kf, ex_px, ex_rs, hit = g.resolve_exit(px, Oa, Ha, La, Ca, tp / 100.0, sl / 100.0)
        use, x, opx, hold, reason = g.exit_plan(e, px, kf, ex_px, ex_rs, hit, Ca, h, T)
        gross = opx[use] / px[use] - 1.0
        for ck, cv in COST_TIERS.items():
            nav, inv, te, tx, tr, th, tv = g.simulate(e[use], x[use], gross - cv, hold[use], T, g.SEEDS, g.K)
            runs["%s|%s" % (name, ck)] = (nav, inv, te, tr, th, tv, int(use.sum()))
            rets["%s|%s" % (name, ck)] = np.diff(nav) / nav[:-1]
        log("规则 %s 组合模拟完成（事件 %d）" % (name, int(use.sum())))

    bfam = json.load(open(BFAM, encoding="utf-8"))
    cells = {c["cell_id"]: c for c in bfam["cells"]}
    bad = []
    for ck in COST_TIERS:
        ref = cells["A-X0-%s" % ck]["by_window"]
        for w in SL:
            mine = g.metrics_all(runs["X0|%s" % ck][0], runs["X0|%s" % ck][1], runs["X0|%s" % ck][2],
                                 runs["X0|%s" % ck][3], runs["X0|%s" % ck][4], runs["X0|%s" % ck][5], SL, len(g.SEEDS))[w]
            if not all(mine[k] == ref[w][k] for k in mine):
                bad.append("A-X0-%s|%s" % (ck, w))
    s4 = g.metrics_all(runs["X4|P20"][0], runs["X4|P20"][1], runs["X4|P20"][2], runs["X4|P20"][3],
                       runs["X4|P20"][4], runs["X4|P20"][5], SL, len(g.SEEDS))["full"]["sharpe"]
    log("plumb：A|X0 组合级 5 窗×2 成本 = %d/10 一致 %s；A|X4-P20 full 夏普 = %.4f（参照 %.3f）%s"
        % (10 - len(bad), "✓" if not bad else "**✗ %s**" % bad, s4, REF_X4_SHARPE,
           "✓" if abs(s4 - REF_X4_SHARPE) < 5e-4 else "**✗**"))
    if bad or abs(s4 - REF_X4_SHARPE) >= 5e-4:
        log("PLUMB 失败：对拍不一致 → 不出数")
        sys.exit(2)
    if a.plumb:
        log("PLUMB 通过：组合级与已公布产物一致；ΔS bootstrap **未计算**（待判据确认）")
        return

    res = {"meta": {"title": "R-qlch-exitport-s-0923 · 配对 Δ夏普口径", "version": VERSION,
                    "preregistration": PREREG, "engine": GRID, "rules": RULES, "comparisons": COMPARISONS,
                    "target": TARGET, "cost_tiers": COST_TIERS,
                    "windows": {k: {"lo": cal[v[0]], "hi": cal[v[1]], "days": v[1] - v[0] + 1} for k, v in SL.items()},
                    "block_boot": {"L": BLOCK, "n": a.bootstrap, "seed": 20260923, "paired": True},
                    "power_gate": {"W_threshold": W_POWER, "ref_effect": REF_DS},
                    "run_at": time.strftime("%Y-%m-%d %H:%M:%S"), "python": sys.version.split()[0],
                    "numpy": np.__version__}, "plumb": {"A_X0_10_10": not bad, "X4_full_sharpe": s4},
           "levels": {}, "dsharpe": {}, "yearwise": {}, "gate": {}}

    for k, v in runs.items():
        res["levels"][k] = g.metrics_all(v[0], v[1], v[2], v[3], v[4], v[5], SL, len(g.SEEDS))

    for r0, r1 in COMPARISONS:
        for ck in COST_TIERS:
            for w, (lo, hi) in SL.items():
                res["dsharpe"]["%s->%s|%s|%s" % (r0, r1, w, ck)] = boot_ds(rets["%s|%s" % (r0, ck)][lo:hi],
                                                                           rets["%s|%s" % (r1, ck)][lo:hi], a.bootstrap)

    lo, hi = SL["full"]
    dd = rets["X4|P20"][lo:hi] - rets["X0|P20"][lo:hi]
    yrs = np.array([cal[t][:4] for t in range(lo + 1, hi + 1)])
    for y in sorted(set(yrs.tolist())):
        m = yrs == y
        res["yearwise"][y] = {"days": int(m.sum()), "ann_pct": round(float(dd[m].mean()) * 100 * ANN, 4)}
    pos = sum(1 for v in res["yearwise"].values() if v["ann_pct"] > 0)
    tot = len(res["yearwise"])

    main = res["dsharpe"]["%s->%s|full|P20" % TARGET]
    t60 = res["dsharpe"]["%s->%s|full|S60" % TARGET]
    tr_ = res["dsharpe"]["%s->%s|train|P20" % TARGET]
    va_ = res["dsharpe"]["%s->%s|val|P20" % TARGET]
    G1 = main["ci95_lo"] > 0
    if G1:
        verdict, note = "PASS", "CI 下界 > 0 → 出场参数改动进入候选（仍不改生产）"
    elif main["power_ok"]:
        verdict, note = "FAIL", "CI 含 0 且 W=%.3f <= %.2f → **有功率的否证** → 判负归档" % (main["W"], W_POWER)
    else:
        verdict, note = "INCONCLUSIVE", "CI 含 0 且 W=%.3f > %.2f → **不可判定（证据不足）**，不判负" % (main["W"], W_POWER)
    G2 = (tr_["dS"] > 0 and va_["dS"] > 0)
    G3 = (t60["dS"] >= main["dS"] and t60["dS"] > 0)
    G4 = (pos / tot >= 0.60)
    res["gate"] = {"G1_main": {"dS": main["dS"], "ci95_lo": main["ci95_lo"], "ci95_hi": main["ci95_hi"],
                               "W": main["W"], "power_ok": main["power_ok"], "pass": bool(G1)},
                   "G1_power_rule": {"W_threshold": W_POWER, "ref_effect": REF_DS,
                                     "detect_prob_at_ref": main["power_detect_prob_at_ref"],
                                     "outcome": verdict, "note": note},
                   "G2_dual_blind": {"train_dS": tr_["dS"], "val_dS": va_["dS"], "pass": bool(G2)},
                   "G3_cost_mechanism": {"dS_P20": main["dS"], "dS_S60": t60["dS"], "pass": bool(G3)},
                   "G4_yearwise": {"positive": pos, "total": tot, "pass": bool(G4)},
                   "verdict": verdict if verdict != "PASS" else ("PASS" if (G2 and G3 and G4) else "FAIL"),
                   "consequence": "见预注册 §三"}
    log("G1=%s(W=%.3f,power_ok=%s) G2=%s G3=%s G4=%s -> %s"
        % (G1, main["W"], main["power_ok"], G2, G3, G4, res["gate"]["verdict"]))
    res["meta"]["elapsed_sec"] = round(time.time() - T0, 1)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    log("已落盘 %s" % OUT.name)


if __name__ == "__main__":
    main()