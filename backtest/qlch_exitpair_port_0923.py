# -*- coding: utf-8 -*-
"""R-qlch-exitport-0923 · 出场规则组合级配对复现

预注册：backtest/PRE-REGISTRATION_20260923_qlch_exitpair_port.md（待判据确认；未确认前只允许 --plumb）

主统计量（全新）：d_t = rr_X4(t) - rr_X0(t)（同窗、同种子平均净值序列的逐日收益差）
判据 F1-F5 见预注册 §四。

用法
    python backtest/qlch_exitpair_port_0923.py --plumb
    python backtest/qlch_exitpair_port_0923.py --bootstrap 10000
"""
import argparse, importlib.util, json, sys, time
from pathlib import Path
import numpy as np

BK = Path(__file__).resolve().parent
GRID = "backtest/qlch_grid_bt_0923.py"
PREREG = "backtest/PRE-REGISTRATION_20260923_qlch_exitpair_port.md"
BFAM = BK / "qlch_bfamily_0923.json"
OUT = BK / "qlch_exitpair_port_0923.json"
VERSION = "qlch-exitpair-port-0923/v1"
COST_TIERS = {"P20": 0.0020, "S60": 0.0060}
RULES = {"X0": (15, -20, 20), "X1": (20, -30, 30), "X2": (20, -30, 40),
         "X3": (25, -30, 30), "X4": (25, -30, 40)}
COMPARISONS = [("X0", "X1"), ("X0", "X2"), ("X0", "X3"), ("X0", "X4")]
TARGET = ("X0", "X4")
V1_LO, V1_HI, V2_LO = "2022-01-04", "2024-06-28", "2024-07-01"
BLOCK = 21
ANN = 244.0
TAIL_DROP = 40
T0 = time.time()


def log(*a):
    print("[%7.1fs] %s" % (time.time() - T0, " ".join(str(x) for x in a)), flush=True)


def load_gateway():
    spec = importlib.util.spec_from_file_location("grid0923", str(BK / "qlch_grid_bt_0923.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def block_boot(d, n_boot, L=BLOCK, seed=20260923, chunk=250):
    n = d.size
    nb = int(np.ceil(n / L))
    hi = max(n - L, 0)
    rng = np.random.default_rng(seed)
    off = np.arange(L)
    out = np.empty(n_boot)
    got = 0
    while got < n_boot:
        m = min(chunk, n_boot - got)
        st = rng.integers(0, hi + 1, size=(m, nb))
        idx = (st[:, :, None] + off[None, None, :]).reshape(m, nb * L)[:, :n]
        out[got:got + m] = d[idx].mean(axis=1)
        got += m
    lo, hiq = np.percentile(out, [2.5, 97.5])
    return {"mean_pct": round(float(d.mean()) * 100, 5),
            "ann_pct": round(float(d.mean()) * 100 * ANN, 4),
            "ci95_lo_pct": round(float(lo) * 100, 5), "ci95_hi_pct": round(float(hiq) * 100, 5),
            "ann_ci95_lo_pct": round(float(lo) * 100 * ANN, 4), "ann_ci95_hi_pct": round(float(hiq) * 100 * ANN, 4),
            "p_gt0": round(float((out > 0).mean()), 4), "n_days": int(n),
            "block": L, "n_blocks": nb, "n_boot": n_boot}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--plumb", action="store_true")
    a = ap.parse_args()

    g = load_gateway()
    assert (g.GAP_LO, g.GAP_HI) == (-0.05, -0.02)
    assert abs(g.COST_RT - 0.0020) < 1e-12 and abs(g.COST_TOT - 0.0060) < 1e-12
    assert g.K == 3 and g.SEEDS == [20260921, 20260922, 20260923, 20260924, 20260925]
    assert g.TRAIN_HI == "2021-12-31" and g.VAL_LO == "2022-01-01"
    for tp, sl, h in RULES.values():
        assert tp in g.TPS and sl in g.SLS and h in g.HS
    log("冻结项断言通过 | 规则 %s | 块长 %d | 5 种子平均净值" % (RULES, BLOCK))

    eng = g.load_engine()
    P = eng.load_all()
    S = eng.build_signals(P)
    cal, T = S["cal"], S["close"].shape[0]
    ents = g.entry_cases(S)
    cnt = {k: int(ents[k]["e"].size) for k in "ABC"}
    assert cnt == {"A": 3440, "B": 346, "C": 35412}, cnt
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
    log("切片日数 " + " ".join("%s=%d" % (k, v[1] - v[0] + 1) for k, v in SL.items()))

    d = ents["A"]
    e, j, px = d["e"], d["j"], d["px"]
    kmax = max(h for _, _, h in RULES.values()) - 1
    Oa, Ha, La, Ca = g.case_path(e, j, S["open"], S["high"], S["low"], S["close"], T, kmax)

    runs = {}
    for name, (tp, sl, h) in RULES.items():
        kf, ex_px, ex_rs, hit = g.resolve_exit(px, Oa, Ha, La, Ca, tp / 100.0, sl / 100.0)
        use, x, opx, hold, reason = g.exit_plan(e, px, kf, ex_px, ex_rs, hit, Ca, h, T)
        gross = opx[use] / px[use] - 1.0
        for ck, cv in COST_TIERS.items():
            ret = gross - cv
            nav, inv, te, tx, tr, th, tv = g.simulate(e[use], x[use], ret, hold[use], T, g.SEEDS, g.K)
            met = g.metrics_all(nav, inv, te, tr, th, tv, SL, len(g.SEEDS))
            runs["%s|%s" % (name, ck)] = {"nav": nav, "met": met, "n_used": int(use.sum()),
                                          "t_hi": int(x[use].max())}
        log("规则 %s(TP%d/SL%d/H%d) 组合模拟完成（事件 %d）" % (name, tp, sl, h, int(use.sum())))

    # ---- plumb：与已公布产物逐字对拍 ----
    bfam = json.load(open(BFAM, encoding="utf-8"))
    cells = {c["cell_id"]: c for c in bfam["cells"]}
    xc, bad = {}, []
    for ck in COST_TIERS:
        ref = cells["A-X0-%s" % ck]["by_window"]
        for w in SL:
            mine = runs["X0|%s" % ck]["met"][w]
            same = all(mine[k] == ref[w][k] for k in mine)
            xc["A-X0-%s|%s" % (ck, w)] = {"match": bool(same), "mine": mine, "bfamily": ref[w]}
            if not same:
                bad.append("A-X0-%s|%s" % (ck, w))
    log("对拍 A|X0 组合级指标（5 窗 × 2 成本 = 10 组，逐字段）：%d/10 一致 %s"
        % (10 - len(bad), "✓" if not bad else "**✗ %s**" % bad))
    if bad:
        for b in bad[:2]:
            log("  不一致 %s\n    mine=%s\n    bfamily=%s" % (b, xc[b]["mine"], xc[b]["bfamily"]))
    if a.plumb:
        assert not bad, "PLUMB 失败：组合级对拍不一致"
        log("PLUMB 通过：组合级管路与已公布产物逐字一致；配对统计量**未计算**（待判据确认）")
        return

    res = {"meta": {"title": "R-qlch-exitport-0923 · 出场规则组合级配对复现", "version": VERSION,
                    "preregistration": PREREG, "engine": GRID, "rules": RULES,
                    "comparisons": COMPARISONS, "target": TARGET, "cost_tiers": COST_TIERS,
                    "windows": {k: {"lo": cal[v[0]], "hi": cal[v[1]], "days": v[1] - v[0] + 1} for k, v in SL.items()},
                    "block_boot": {"L": BLOCK, "n": a.bootstrap, "seed": 20260923},
                    "build": "5 种子平均净值序列；K=3；单票=净值/3；现金约束", "tail_drop_days": TAIL_DROP,
                    "run_at": time.strftime("%Y-%m-%d %H:%M:%S"), "python": sys.version.split()[0],
                    "numpy": np.__version__}, "plumb": {k: v["match"] for k, v in xc.items()},
           "levels": {}, "paired": {}, "yearwise": {}, "gate": {}}

    for k, v in runs.items():
        res["levels"][k] = v["met"]

    def rr(rule, ck):
        nav = runs["%s|%s" % (rule, ck)]["nav"]
        return np.diff(nav) / nav[:-1]

    for r0, r1 in COMPARISONS:
        for ck in COST_TIERS:
            a0, a1 = rr(r0, ck), rr(r1, ck)
            for w, (lo, hi) in SL.items():
                s, en = lo + 1, hi + 1
                dd = a1[s:en] - a0[s:en]
                b = block_boot(dd, a.bootstrap)
                m0, m1 = runs["%s|%s" % (r0, ck)]["met"][w], runs["%s|%s" % (r1, ck)]["met"][w]
                b.update({"dsharpe": round(m1["sharpe"] - m0["sharpe"], 4),
                          "dcagr_pp": round(m1["cagr"] - m0["cagr"], 4),
                          "dturn": round(m1["turn"] - m0["turn"], 3),
                          "dhold": round(m1["hold"] - m0["hold"], 3),
                          "dinv_pp": round(m1["inv"] - m0["inv"], 3),
                          "dmdd_pp": round(m1["mdd"] - m0["mdd"], 4),
                          "n_pairs": int(m1["n"] - m0["n"])})
                if w == "full":
                    k2 = hi + 1 - TAIL_DROP
                    b["tail_trunc"] = block_boot(a1[s:k2] - a0[s:k2], min(a.bootstrap, 2000))
                res["paired"]["%s->%s|%s|%s" % (r0, r1, w, ck)] = b

    # 逐段（自然年）
    tgt = res["paired"]["%s->%s|full|P20" % TARGET]
    a0, a1 = rr("X0", "P20"), rr("X4", "P20")
    lo, hi = SL["full"]
    dd = a1[lo + 1:hi + 1] - a0[lo + 1:hi + 1]
    yrs = np.array([cal[t][:4] for t in range(lo + 1, hi + 1)])
    for y in sorted(set(yrs.tolist())):
        m = yrs == y
        res["yearwise"][y] = {"days": int(m.sum()), "mean_pct": round(float(dd[m].mean()) * 100, 5),
                              "ann_pct": round(float(dd[m].mean()) * 100 * ANN, 4)}
    pos = sum(1 for y, v in res["yearwise"].items() if v["mean_pct"] > 0)
    tot = len(res["yearwise"])
    annP20 = res["paired"]["%s->%s|full|P20" % TARGET]["ann_pct"]
    annS60 = res["paired"]["%s->%s|full|S60" % TARGET]["ann_pct"]
    F1 = (tgt["mean_pct"] > 0 and tgt["ci95_lo_pct"] > 0)
    tr_, va_ = res["paired"]["%s->%s|train|P20" % TARGET], res["paired"]["%s->%s|val|P20" % TARGET]
    F2 = (tr_["mean_pct"] > 0 and va_["mean_pct"] > 0)
    F3 = (annS60 >= annP20 and annS60 > 0)
    F4 = (pos / tot >= 0.60)
    F5 = (tgt["dturn"] < 0 and tgt["dhold"] > 0)
    res["gate"] = {"F1_main": {"ann_pct": annP20, "ci95_lo_pct": tgt["ci95_lo_pct"], "pass": bool(F1)},
                   "F2_dual_blind": {"train_ann": tr_["ann_pct"], "val_ann": va_["ann_pct"], "pass": bool(F2)},
                   "F3_cost_mechanism": {"ann_P20": annP20, "ann_S60": annS60, "pass": bool(F3)},
                   "F4_yearwise": {"positive": pos, "total": tot, "share": round(pos / tot, 4), "pass": bool(F4)},
                   "F5_structure": {"dturn": tgt["dturn"], "dhold": tgt["dhold"], "pass_diag": bool(F5)},
                   "verdict": "PASS" if (F1 and F2 and F3 and F4) else "FAIL",
                   "consequence": "全过 -> 出场参数改动进入候选（仍不改生产）；任一不过 -> 判负归档"}
    log("判据 F1=%s F2=%s F3=%s F4=%s | 诊断 F5=%s -> %s" % (F1, F2, F3, F4, F5, res["gate"]["verdict"]))
    res["meta"]["elapsed_sec"] = round(time.time() - T0, 1)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    log("已落盘 %s" % OUT.name)


if __name__ == "__main__":
    main()