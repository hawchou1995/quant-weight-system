# -*- coding: utf-8 -*-
"""R-qlch-exitpair-0923 · 出场规则同事件配对检验

预注册：`backtest/PRE-REGISTRATION_20260923_qlch_exitpair.md`（**待用户确认判据**；未获确认前只允许 `--plumb`）

设计
- 事件集：A 族事件（生产入场情形），沿用 `qlch_grid_bt_0923.py` 的 entry_cases
- 规则集（预声明 5 档）：X0(15/−20/20)、X1(20/−30/30)、X2(20/−30/40)、X3(25/−30/30)、X4(25/−30/40)
- 统计量（**本轮唯一新统计量**）：同事件配对差 d_i = r_i(目标规则) − r_i(X0)，**按入场日聚类** bootstrap
- 配对集 = 两规则 `use` 掩码的**交集**（因 H=40 在面板末端截断更多）
- 成本两档：20bp（主）/ 60bp（自检）

用法
    python backtest/qlch_exitpair_0923.py --plumb          # 自检：只核对事件数与已公布的 A|X0 聚合量，不产出配对统计量
    python backtest/qlch_exitpair_0923.py --bootstrap 10000  # 正式评估（须先获用户确认判据）
"""
import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np

BK = Path(__file__).resolve().parent
BASE = BK.parent
GRID = "backtest/qlch_grid_bt_0923.py"
PREREG = "backtest/PRE-REGISTRATION_20260923_qlch_exitpair.md"
BLEG_JSON = BK / "qlch_bleg_event_0923.json"
OUT_JSON = BK / "qlch_exitpair_0923.json"
VERSION = "qlch-exitpair-0923/v1"
COST_TIERS = {"P20": 0.0020, "S60": 0.0060}
RULES = {"X0": (15, -20, 20), "X1": (20, -30, 30), "X2": (20, -30, 40),
         "X3": (25, -30, 30), "X4": (25, -30, 40)}
COMPARISONS = [("X0", "X1"), ("X0", "X2"), ("X0", "X3"), ("X0", "X4")]
TARGET = ("X0", "X4")
T0 = time.time()


def log(*a):
    print("[%7.1fs] %s" % (time.time() - T0, " ".join(str(x) for x in a)), flush=True)


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def freeze_assertions(g):
    assert (g.GAP_LO, g.GAP_HI) == (-0.05, -0.02)
    assert abs(g.COST_RT - 0.0020) < 1e-12 and abs(g.COST_TOT - 0.0060) < 1e-12
    assert g.TRAIN_HI == "2021-12-31" and g.VAL_LO == "2022-01-01"
    for tp, sl, h in RULES.values():
        assert tp in g.TPS and sl in g.SLS and h in g.HS, (tp, sl, h)


def boot_paired(d, key, n_boot, seed=20260923, chunk=500):
    """按 key（入场日）聚类 bootstrap 的配对差均值分布。"""
    keys, inv = np.unique(key), None
    nk = keys.size
    idx_of = {k: i for i, k in enumerate(keys)}
    ki = np.array([idx_of[k] for k in key])
    s = np.zeros(nk); c = np.zeros(nk)
    np.add.at(s, ki, d); np.add.at(c, ki, 1.0)
    rng = np.random.default_rng(seed)
    out = np.empty(n_boot); got = 0
    while got < n_boot:
        m = min(chunk, n_boot - got)
        idx = rng.integers(0, nk, size=(m, nk))
        n = c[idx].sum(axis=1)
        ok = n > 0
        v = np.full(m, np.nan)
        v[ok] = s[idx][ok].sum(axis=1) / n[ok]
        out[got:got + m] = v
        got += m
    v = out[np.isfinite(out)]
    return {"mean_pp": round(float(d.mean()) * 100, 4),
            "median_pp": round(float(np.median(d)) * 100, 4),
            "ci95_lo_pp": round(float(np.percentile(v, 2.5)) * 100, 4),
            "ci95_hi_pp": round(float(np.percentile(v, 97.5)) * 100, 4),
            "p_gt0": round(float((v > 0).mean()), 4),
            "n_events": int(d.size), "n_clusters": int(nk)}


def aggregate(x):
    if x.size == 0:
        return {"n": 0}
    return {"n": int(x.size), "mean_pct": round(float(x.mean()) * 100, 4),
            "median_pct": round(float(np.median(x)) * 100, 4),
            "std_pct": round(float(x.std(ddof=1)) * 100, 4) if x.size > 1 else None,
            "wr_pct": round(float((x > 0).mean()) * 100, 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--plumb", action="store_true", help="只自检管路，不产出配对统计量")
    args = ap.parse_args()

    g = load_module(BK / "qlch_grid_bt_0923.py", "qlch_grid_0923")
    freeze_assertions(g)
    log("冻结项断言通过 · 规则集 %s" % (RULES,))
    if args.plumb:
        log("★ PLUMB 模式：仅核对事件数与已公布的 A|X0 聚合量（不计算配对统计量）")
    eng = g.load_engine()
    P = eng.load_all()
    S = eng.build_signals(P)
    cal, T = S["cal"], S["close"].shape[0]
    ents = g.entry_cases(S)
    cnt = {k: int(ents[k]["e"].size) for k in "ABC"}
    log("事件数 A=%d B=%d C=%d" % (cnt["A"], cnt["B"], cnt["C"]))

    bleg = json.load(open(BLEG_JSON, encoding="utf-8"))
    prev = bleg["meta"]["entry_opportunities"]
    assert prev == {"A": cnt["A"], "B": cnt["B"], "C": cnt["C"]}, (prev, cnt)
    log("对拍 bleg JSON entry_opportunities 逐字一致 ✓")

    i_first = int(np.concatenate([ents[k]["e"] for k in "ABC"]).min())
    i_train = max([i for i, d in enumerate(cal) if d <= g.TRAIN_HI] or [0])
    i_val = min([i for i, d in enumerate(cal) if d >= g.VAL_LO] or [T - 1])
    WINDOWS = {"full": (i_first, T - 1), "train": (i_first, i_train), "val": (i_val, T - 1)}

    # ---- A 族事件：逐规则定案 ----
    d = ents["A"]
    e, j, px = d["e"], d["j"], d["px"]
    kmax = max(h for _, _, h in RULES.values()) - 1
    Oa, Ha, La, Ca = g.case_path(e, j, S["open"], S["high"], S["low"], S["close"], T, kmax)
    per_rule = {}
    for name, (tp, sl, h) in RULES.items():
        kf, ex_px, ex_rs, hit = g.resolve_exit(px, Oa, Ha, La, Ca, tp / 100.0, sl / 100.0)
        use, x, opx, hold, reason = g.exit_plan(e, px, kf, ex_px, ex_rs, hit, Ca, h, T)
        gross = opx / px - 1.0
        per_rule[name] = {"use": use, "x": x, "hold": hold, "reason": reason,
                          "n_used": int(use.sum()),
                          "ret": {ck: gross - cv for ck, cv in COST_TIERS.items()}}
        log("规则 %s(TP%d/SL%d/H%d)：可用 %d / %d（面板末截断 %d）"
            % (name, tp, sl, h, use.sum(), e.size, int((~use).sum())))

    # ---- 对拍：A|X0 聚合量须与已公布 JSON 一致 ----
    xcheck = {}
    for w, (lo, hi) in WINDOWS.items():
        m = (e >= lo) & (e <= hi) & per_rule["X0"]["use"]
        for ck, cost in COST_TIERS.items():
            key = "X0|%s|%s" % (w, ck)
            mine = aggregate(per_rule["X0"]["ret"][ck][m])
            theirs = bleg["cases"].get(key, {}).get("A", {}).get("rets")
            same = (theirs is not None and mine == {k: theirs[k] for k in mine})
            xcheck[key] = {"mine": mine, "ibleg": theirs, "match": bool(same)}
            if not same:
                log("!! 对拍不一致 %s\n   mine=%s\n   bleg=%s" % (key, mine, theirs))
    n_ok = sum(1 for v in xcheck.values() if v["match"])
    log("对拍 A|X0 六组聚合量（full/train/val × P20/S60）：%d/%d 逐位一致 %s"
        % (n_ok, len(xcheck), "✓" if n_ok == len(xcheck) else "**✗**"))
    if args.plumb:
        assert n_ok == len(xcheck), "PLUMB 失败：对拍不一致"
        log("PLUMB 通过：管路可用、口径与已公布产物一致；配对统计量**未计算**（待用户确认判据）")
        return

    # ---- 正式评估：同事件配对 ----
    result = {"meta": {
        "title": "R-qlch-exitpair-0923 · 出场规则同事件配对检验",
        "script": "backtest/qlch_exitpair_0923.py", "version": VERSION, "preregistration": PREREG,
        "engine": GRID + " → " + g.ENGINE, "cost_tiers": COST_TIERS, "rules": RULES,
        "comparisons": COMPARISONS, "target": TARGET,
        "bootstrap": {"n": args.bootstrap, "cluster": "entry_day", "seed": 20260923},
        "windows": {k: {"lo": cal[v[0]], "hi": cal[v[1]]} for k, v in WINDOWS.items()},
        "windows_by": "entry_day", "entry_events_A": cnt["A"],
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"), "python": sys.version.split()[0],
        "numpy": np.__version__}, "plumb_xcheck": {k: v["match"] for k, v in xcheck.items()},
        "pairs": {}, "gate": {}, "structure": {}}

    for (r0, r1) in COMPARISONS:
        use_both = per_rule[r0]["use"] & per_rule[r1]["use"]
        for w, (lo, hi) in WINDOWS.items():
            m = use_both & (e >= lo) & (e <= hi)
            for ck in COST_TIERS:
                dd = per_rule[r1]["ret"][ck][m] - per_rule[r0]["ret"][ck][m]
                bk = boot_paired(dd, e[m], args.bootstrap)
                bk.update({"dropped_not_usable_both": int(((e >= lo) & (e <= hi) & ~use_both).sum()),
                           "hold_%s" % r0: round(float(per_rule[r0]["hold"][m].mean()), 3),
                           "hold_%s" % r1: round(float(per_rule[r1]["hold"][m].mean()), 3)})
                result["pairs"]["%s->%s|%s|%s" % (r0, r1, w, ck)] = bk

    # 结构自检（E5）：持有期与止盈触发率
    for r in RULES:
        use = per_rule[r]["use"]
        result["structure"][r] = {
            "mean_hold": round(float(per_rule[r]["hold"][use].mean()), 3),
            "tp_share_pct": round(float(np.isin(per_rule[r]["reason"][use], [1, 3]).mean()) * 100, 3),
            "sl_share_pct": round(float(np.isin(per_rule[r]["reason"][use], [0, 2]).mean()) * 100, 3),
            "expiry_share_pct": round(float((per_rule[r]["reason"][use] == 4).mean()) * 100, 3)}

    # 判据 E1..E4
    def P(cmp_, w, ck):
        return result["pairs"]["%s->%s|%s|%s" % (cmp_[0], cmp_[1], w, ck)]

    tp_, ts_ = P(TARGET, "full", "P20"), P(TARGET, "full", "S60")
    E1 = (tp_["mean_pp"] > 0 and tp_["ci95_lo_pp"] > 0)
    E2 = all(P(TARGET, w, "P20")["mean_pp"] > 0 for w in ("train", "val"))
    rev = [c for c in COMPARISONS if c != TARGET and P(c, "full", "P20")["ci95_hi_pp"] < 0]
    E3 = (len(rev) == 0)
    E4 = ((tp_["mean_pp"] > 0) == (ts_["mean_pp"] > 0))
    result["gate"] = {
        "E1_target_full_P20": {"mean_pp": tp_["mean_pp"], "ci95_lo_pp": tp_["ci95_lo_pp"], "pass": bool(E1)},
        "E2_dual_blind_same_sign": {"train": P(TARGET, "train", "P20")["mean_pp"],
                                    "val": P(TARGET, "val", "P20")["mean_pp"], "pass": bool(E2)},
        "E3_neighbor_no_reversal": {"reversed": [list(c) for c in rev], "pass": bool(E3)},
        "E4_cost_selfcheck": {"P20": tp_["mean_pp"], "S60": ts_["mean_pp"], "pass": bool(E4)},
        "verdict": "PASS" if (E1 and E2 and E3 and E4) else "FAIL",
        "consequence": "全过 → 仅得出「出场参数值得组合级复现」（另立预注册）；任何情形均不改生产"}
    log("判据：E1=%s E2=%s E3=%s E4=%s → %s" % (E1, E2, E3, E4, result["gate"]["verdict"]))
    result["meta"]["elapsed_sec"] = round(time.time() - T0, 1)
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    log("已落盘 %s" % OUT_JSON.name)


if __name__ == "__main__":
    main()
