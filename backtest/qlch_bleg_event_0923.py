# -*- coding: utf-8 -*-
"""R-qlch-bleg-0923 · G2 事件级 B 腿增量检验（历史域）

预注册：`backtest/PRE-REGISTRATION_20260923_qlch_bleg_followup.md`（§四 G2，用户 2026-09-22 批准）

设计要点（与预注册逐字对应）
- 只读复用 `backtest/qlch_grid_bt_0923.py` 的入场/出场原语：
      entry_cases → case_path → resolve_exit → exit_plan（**同一套代码**，不另写判定）
- **事件级 = 逐事件单笔收益，不启用 K=3 槽位**（故不受槽位竞争影响；但事件级 ≠ 组合级，不可直接换算）
- 出场规则：X3（TP+25% / SL−30% / MAXHOLD 30，T+1 不可卖，跳空优先级沿用引擎）
- 判据：`均值(B) − 均值(A) ≥ +1.0pp` 且 10,000 次 bootstrap 95% CI 下界 > 0
- 成本两档：生产档 20bp（主）/ 压力档 60bp（报）
- bootstrap 聚类：按**入场交易日**（主）/ 按**标的**（稳健）
- 分窗归属：按**入场日**（同一事件不跨窗重复计入）；另报出场日越窗事件数

用法：`python backtest/qlch_bleg_event_0923.py [--bootstrap 10000]`
产物：`backtest/qlch_bleg_event_0923.json`（**不写任何账本**）
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
PREREG = "backtest/PRE-REGISTRATION_20260923_qlch_bleg_followup.md"
OUT_JSON = BK / "qlch_bleg_event_0923.json"
VERSION = "qlch-bleg-event-0923/v1"
COST_TIERS = {"P20": 0.0020, "S60": 0.0060}
X3 = {"tp": 25, "sl": -30, "h": 30}
X0 = {"tp": 15, "sl": -20, "h": 20}
PREV_JSON = "backtest/qlch_bfamily_0923.json"

T0 = time.time()


def log(*a):
    print("[%7.1fs] %s" % (time.time() - T0, " ".join(str(x) for x in a)), flush=True)


def load_module(path, name):
    """importlib 加载（两文件均有 __main__ 守卫 → main() 不执行）。"""
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def freeze_assertions(g):
    """冻结项断言：与预注册 §一 逐项对齐（任何漂移 → 立即失败，不出数）。"""
    assert (g.GAP_LO, g.GAP_HI) == (-0.05, -0.02), (g.GAP_LO, g.GAP_HI)
    assert abs(g.COST_RT - 0.0020) < 1e-12, g.COST_RT
    assert abs(g.COST_TOT - 0.0060) < 1e-12, g.COST_TOT
    assert g.K == 3, g.K
    assert g.SEEDS == [20260921, 20260922, 20260923, 20260924, 20260925], g.SEEDS
    assert g.TRAIN_HI == "2021-12-31" and g.VAL_LO == "2022-01-01", (g.TRAIN_HI, g.VAL_LO)
    assert 25 in g.TPS and -30 in g.SLS and 30 in g.HS, (g.TPS, g.SLS, g.HS)
    assert 15 in g.TPS and -20 in g.SLS and 20 in g.HS


def stats(x):
    if x.size == 0:
        return {"n": 0}
    return {
        "n": int(x.size),
        "mean_pct": round(float(x.mean()) * 100, 4),
        "median_pct": round(float(np.median(x)) * 100, 4),
        "std_pct": round(float(x.std(ddof=1)) * 100, 4) if x.size > 1 else None,
        "p25_pct": round(float(np.percentile(x, 25)) * 100, 4),
        "p75_pct": round(float(np.percentile(x, 75)) * 100, 4),
        "wr_pct": round(float((x > 0).mean()) * 100, 3),
    }


def boot_delta(retA, keyA, retB, keyB, n_boot, seed=20260923, chunk=500):
    """聚类 bootstrap：按 key（入场日 / 标的）成块重采样，估计 mean(B)−mean(A) 的分布。

    返回 dict(point, ci_lo, ci_hi, p_gt0, n_days_or_clusters)。
    """
    keys = np.union1d(keyA, keyB)
    kidx = {k: i for i, k in enumerate(keys)}
    nk = keys.size
    if nk == 0 or retA.size == 0 or retB.size == 0:
        return None
    sA = np.zeros(nk); cA = np.zeros(nk)
    sB = np.zeros(nk); cB = np.zeros(nk)
    np.add.at(sA, np.array([kidx[k] for k in keyA]), retA)
    np.add.at(cA, np.array([kidx[k] for k in keyA]), 1.0)
    np.add.at(sB, np.array([kidx[k] for k in keyB]), retB)
    np.add.at(cB, np.array([kidx[k] for k in keyB]), 1.0)
    rng = np.random.default_rng(seed)
    out = np.empty(n_boot)
    got = 0
    while got < n_boot:
        m = min(chunk, n_boot - got)
        idx = rng.integers(0, nk, size=(m, nk))
        nA = cA[idx].sum(axis=1); nB = cB[idx].sum(axis=1)
        ok = (nA > 0) & (nB > 0)
        d = np.full(m, np.nan)
        if ok.any():
            mA = sA[idx][ok].sum(axis=1) / nA[ok]
            mB = sB[idx][ok].sum(axis=1) / nB[ok]
            d[ok] = mB - mA
        out[got:got + m] = d
        got += m
    d = out[np.isfinite(out)]
    return {
        "point_pp": round(float(retB.mean() - retA.mean()) * 100, 4),
        "ci95_lo_pp": round(float(np.percentile(d, 2.5)) * 100, 4),
        "ci95_hi_pp": round(float(np.percentile(d, 97.5)) * 100, 4),
        "p_delta_gt0": round(float((d > 0).mean()), 4),
        "n_clusters": int(nk),
        "n_boot_used": int(d.size),
        "n_boot_dropped": int(n_boot - d.size),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", type=int, default=10000)
    args = ap.parse_args()
    n_boot = args.bootstrap

    log("版本 %s | 预注册 %s" % (VERSION, PREREG))
    g = load_module(BK / "qlch_grid_bt_0923.py", "qlch_grid_0923")
    freeze_assertions(g)
    log("冻结项断言通过：带 [%.2f,%.2f] · 成本 20bp/60bp · K=%d · 种子 5 · 训练≤%s 验证≥%s · X3=%s"
        % (g.GAP_LO, g.GAP_HI, g.K, g.TRAIN_HI, g.VAL_LO, X3))
    eng = g.load_engine()
    log("引擎载入：VARIANT=%s MAINBOARD=%s GATE=%s COST_RT=%s"
        % (eng.VARIANT, eng.MAINBOARD, eng.GATE_MA, eng.COST_RT))
    P = eng.load_all()
    S = eng.build_signals(P)
    cal, T = S["cal"], S["close"].shape[0]
    log("面板 %s .. %s 共 %d 交易日 %d 只；候选(信号日) %d 个股票日"
        % (cal[0], cal[-1], T, S["close"].shape[1], int(S["cand"].sum())))

    ents = g.entry_cases(S)
    cnt = {k: int(ents[k]["e"].size) for k in "ABC"}
    log("入场情形事件数 A=%d B=%d C=%d" % (cnt["A"], cnt["B"], cnt["C"]))

    # ---- 对拍上一轮（笔数口径必须逐字一致）----
    prev_path = BASE / PREV_JSON
    prev = json.load(open(prev_path, encoding="utf-8")) if prev_path.exists() else None
    prev_opp = prev.get("entry_opportunities") if prev else None
    cross = {"prev_json": PREV_JSON, "prev_entry_opportunities": prev_opp,
             "now": {"A": cnt["A"], "B": cnt["B"], "C": cnt["C"]},
             "match": bool(prev_opp and prev_opp == {"A": cnt["A"], "B": cnt["B"], "C": cnt["C"]})}
    if prev_opp:
        assert prev_opp == {"A": cnt["A"], "B": cnt["B"], "C": cnt["C"]}, (prev_opp, cnt)
        log("对拍上一轮 entry_opportunities 一致 ✓（A=%d B=%d C=%d）" % (cnt["A"], cnt["B"], cnt["C"]))

    all_e = np.concatenate([ents[k]["e"] for k in "ABC"])
    i_first = int(all_e.min())
    i_train = max([i for i, d in enumerate(cal) if d <= g.TRAIN_HI] or [0])
    i_val = min([i for i, d in enumerate(cal) if d >= g.VAL_LO] or [T - 1])
    WINDOWS = {"full": (i_first, T - 1), "train": (i_first, i_train), "val": (i_val, T - 1)}
    log("分窗（按入场日）：full %s..%s · train ..%s · val %s.. · 交易日 %d/%d/%d"
        % (cal[i_first], cal[-1], cal[i_train], cal[i_val],
           WINDOWS["full"][1] - i_first + 1, i_train - i_first + 1, T - i_val))

    # ---- 逐事件出场定案（分别对 A/B/C 自算，不并表 → 无槽位竞争）----
    kmax = max(g.HS) - 1
    per_case = {}
    for k in "ABC":
        d = ents[k]
        e, j, px = d["e"], d["j"], d["px"]
        Oa, Ha, La, Ca = g.case_path(e, j, S["open"], S["high"], S["low"], S["close"], T, kmax)
        per_case[k] = {"e": e, "j": j, "px": px, "Ca": Ca,
                       "paths": (Oa, Ha, La, Ca),
                       "runs": {}}
        for label, cfg in (("X3", X3), ("X0", X0)):
            kf, ex_px, ex_rs, hit = g.resolve_exit(px, Oa, Ha, La, Ca, cfg["tp"] / 100.0, cfg["sl"] / 100.0)
            use, x, opx, hold, reason = g.exit_plan(e, px, kf, ex_px, ex_rs, hit, Ca, cfg["h"], T)
            gross = opx / px - 1.0
            per_case[k]["runs"][label] = {
                "use": use, "x": x, "hold": hold, "reason": reason, "gross": gross,
                "n_events": int(e.size), "n_used": int(use.sum()),
                "n_dropped_panel_end": int((~use).sum()),
                "ret": {ck: gross - cv for ck, cv in COST_TIERS.items()},
            }
        log("情形 %s：事件 %d（可用 %d，面板末截断 %d）"
            % (k, e.size, per_case[k]["runs"]["X3"]["n_used"], per_case[k]["runs"]["X3"]["n_dropped_panel_end"]))

    # ---- 统计 + bootstrap（主 X3；X0 仅报）----
    result = {"meta": {
        "title": "R-qlch-bleg-0923 · G2 事件级 B 腿增量检验（历史域）",
        "script": "backtest/qlch_bleg_event_0923.py", "version": VERSION,
        "preregistration": PREREG, "engine": GRID + " → " + g.ENGINE,
        "cost_tiers": COST_TIERS, "primary_exit": "X3 (TP25/SL-30/H30)",
        "secondary_exit": "X0 (TP15/SL-20/H20)",
        "bootstrap": {"n": n_boot, "cluster_primary": "entry_day",
                      "cluster_robust": "stock", "seed": 20260923,
                      "note": "成块重采样；A/B 各自独立聚合，Δ = mean(B) − mean(A)"},
        "windows_by": "entry_day", "windows": {k: {"lo_i": v[0], "hi_i": v[1],
                                                   "lo": cal[v[0]], "hi": cal[v[1]]}
                                               for k, v in WINDOWS.items()},
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "python": sys.version.split()[0], "numpy": np.__version__,
        "panels": {"cal_0": cal[0], "cal_last": cal[-1], "T": int(T), "n_symbols": int(S["close"].shape[1])},
        "entry_opportunities": cnt,
    }, "crosscheck_prev_round": cross, "cases": {}, "gate_G2": {}, "log": []}

    def win_mask(e, w):
        lo, hi = WINDOWS[w]
        return (e >= lo) & (e <= hi)

    for label in ("X3", "X0"):
        for w in ("full", "train", "val"):
            for ck in ("P20", "S60"):
                key = "%s|%s|%s" % (label, w, ck)
                rec = {}
                keep = {}
                for k in "ABC":
                    r = per_case[k]["runs"][label]
                    m = r["use"] & win_mask(per_case[k]["e"], w)
                    ret = r["ret"][ck][m]
                    keyday = per_case[k]["e"][m]
                    keystk = per_case[k]["j"][m]
                    keep[k] = (ret, keyday, keystk, r, m)
                    rec[k] = {"n_events_in_win": int(win_mask(per_case[k]["e"], w).sum()),
                              "n_used": int(m.sum()),
                              "n_dropped_panel_end": int((win_mask(per_case[k]["e"], w) & ~r["use"]).sum()),
                              "rets": stats(ret),
                              "mean_hold": round(float(r["hold"][m].mean()), 3) if m.any() else None,
                              "exit_reasons": {g.RSN[i]: int((r["reason"][m] == i).sum()) for i in sorted(g.RSN)},
                              "over_window_exit": int(((r["x"][m] > WINDOWS[w][1])).sum()) if m.any() else 0}
                # bootstrap Δ = mean(B) − mean(A)
                retA, dayA, stkA = keep["A"][0], keep["A"][1], keep["A"][2]
                retB, dayB, stkB = keep["B"][0], keep["B"][1], keep["B"][2]
                rec["delta_B_minus_A"] = {
                    "by_day": boot_delta(retA, dayA, retB, dayB, n_boot),
                    "by_stock": boot_delta(retA, stkA, retB, stkB, n_boot, seed=20260924),
                }
                # 同日配对（仅两情形同日都有事件的日子）
                if retA.size and retB.size:
                    common = np.intersect1d(dayA, dayB)
                    if common.size:
                        dmA = {d: retA[dayA == d].mean() for d in common}
                        dmB = {d: retB[dayB == d].mean() for d in common}
                        dif = np.array([dmB[d] - dmA[d] for d in common])
                        rec["delta_same_day_paired"] = {
                            "n_days": int(common.size),
                            "mean_pp": round(float(dif.mean()) * 100, 4),
                            "median_pp": round(float(np.median(dif)) * 100, 4),
                            "share_days_positive": round(float((dif > 0).mean()), 4),
                        }
                result["cases"][key] = rec

    # ---- G2 判据（预注册 §四 G2，主档 = full 窗 + 生产档 20bp）----
    def gate(label, w, ck):
        rec = result["cases"]["%s|%s|%s" % (label, w, ck)]
        d = rec["delta_B_minus_A"]
        pt = d["by_day"]["point_pp"] if d["by_day"] else None
        lo = d["by_day"]["ci95_lo_pp"] if d["by_day"] else None
        return {"window": w, "cost": ck, "exit": label,
                "point_pp": pt, "ci95_lo_pp": lo,
                "thr_point_pp": 1.0, "thr_ci": ">0",
                "pass_point": bool(pt is not None and pt >= 1.0),
                "pass_ci": bool(lo is not None and lo > 0.0),
                "pass": bool(pt is not None and lo is not None and pt >= 1.0 and lo > 0.0)}

    g_primary = gate("X3", "full", "P20")
    g_pressure = gate("X3", "full", "S60")
    result["gate_G2"] = {
        "rule": "预注册 §四 G2：均值(B)−均值(A) ≥ +1.0pp 且 bootstrap 95% CI 下界 > 0（主 = X3 · full 窗 · 生产档 20bp）",
        "primary_P20": g_primary, "stress_S60": g_pressure,
        "by_window": {w: gate("X3", w, "P20") for w in ("full", "train", "val")},
        "verdict": ("PASS" if g_primary["pass"] else "FAIL"),
        "pressure_note": ("压力档（60bp）同步成立" if g_pressure["pass"]
                          else "压力档（60bp）不成立 —— 已在报告披露"),
    }
    log("G2 判据（主·full·P20）：Δ=%s pp，CI 下界=%s pp → %s"
        % (g_primary["point_pp"], g_primary["ci95_lo_pp"], result["gate_G2"]["verdict"]))
    log("副（full·S60）：Δ=%s pp，CI 下界=%s pp → %s"
        % (g_pressure["point_pp"], g_pressure["ci95_lo_pp"], "PASS" if g_pressure["pass"] else "FAIL"))

    result["meta"]["elapsed_sec"] = round(time.time() - T0, 1)
    result["log"] = ["(省略中间日志；完整 stdout 见运行记录)"]
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    log("已落盘 %s（%.1f KB）" % (OUT_JSON.name, OUT_JSON.stat().st_size / 1024))
    log("总耗时 %.1f s" % (time.time() - T0))


if __name__ == "__main__":
    main()
