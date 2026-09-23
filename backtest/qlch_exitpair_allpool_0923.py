# -*- coding: utf-8 -*-
"""全池（QLCH_MAINBOARD=0，= 卡片标注的在产轨 B4_K3）上的出场规则证据复现。
同一套原语（grid 的 entry_cases/case_path/resolve_exit/exit_plan/simulate/metrics_all），只换池。"""
import importlib.util, json, sys, io, os, math
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BK = "backtest"
os.environ["QLCH_VARIANT"] = "B4"; os.environ["QLCH_MAXPOS"] = "3"
os.environ["QLCH_GATE"] = "20"; os.environ["QLCH_MAINBOARD"] = "0"
spec = importlib.util.spec_from_file_location("grid0923", BK + "/qlch_grid_bt_0923.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
spec2 = importlib.util.spec_from_file_location("eng", BK + "/qlch_paper_20260921.py")
eng = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(eng)
print("MAINBOARD=%s VARIANT=%s MAXPOS=%s GATE=%s" % (eng.MAINBOARD, eng.VARIANT, eng.MAXPOS, eng.GATE_MA))
P = eng.load_all(); S = eng.build_signals(P)
cal, T = S["cal"], S["close"].shape[0]
ents = g.entry_cases(S)
cnt = {k: int(ents[k]["e"].size) for k in "ABC"}
print("事件数（全池）A=%d B=%d C=%d" % (cnt["A"], cnt["B"], cnt["C"]))
RULES = {"X0": (15, -20, 20), "X1": (20, -30, 30), "X2": (20, -30, 40), "X3": (25, -30, 30), "X4": (25, -30, 40)}
d = ents["A"]; e, j, px = d["e"], d["j"], d["px"]
kmax = max(h for _, _, h in RULES.values()) - 1
Oa, Ha, La, Ca = g.case_path(e, j, S["open"], S["high"], S["low"], S["close"], T, kmax)
i_first = int(np.concatenate([ents[k]["e"] for k in "ABC"]).min())
i_tr = max([i for i, x in enumerate(cal) if x <= g.TRAIN_HI] or [0])
i_va = min([i for i, x in enumerate(cal) if x >= g.VAL_LO] or [T - 1])
runs, rets = {}, {}
for nm, (tp, sl, h) in RULES.items():
    kf, ex_px, ex_rs, hit = g.resolve_exit(px, Oa, Ha, La, Ca, tp / 100.0, sl / 100.0)
    use, x, opx, hold, reason = g.exit_plan(e, px, kf, ex_px, ex_rs, hit, Ca, h, T)
    gross = opx[use] / px[use] - 1.0
    rf20 = np.full(e.size, np.nan); rf20[use] = gross - 0.0020
    rf60 = np.full(e.size, np.nan); rf60[use] = gross - 0.0060
    runs[nm] = {"use": use, "x": x, "hold": hold, "reason": reason, "n": int(use.sum()),
                "ret20": gross - 0.0020, "ret60": gross - 0.0060, "retf20": rf20, "retf60": rf60}
    nav, inv, te, tx, tr, th, tv = g.simulate(e[use], x[use], runs[nm]["ret20"], hold[use], T, g.SEEDS, g.K)
    rets[nm] = np.diff(nav) / nav[:-1]
    met = g.metrics_all(nav, inv, te, tr, th, tv, {"full": (i_first, T - 1), "train": (i_first, i_tr), "val": (i_va, T - 1)}, len(g.SEEDS))
    runs[nm]["met"] = met
    print("  规则 %s 可用 %d | 单笔均值 %+7.3f%% 胜率 %5.1f%% 持有 %5.2f | 组合 full 年化%+7.2f%% 夏普%6.3f 回撤%+7.2f%% 笔%4d 换手%5.1f | val 年化%+7.2f%% 夏普%6.3f"
          % (nm, runs[nm]["n"], float(runs[nm]["ret20"].mean()) * 100, float((runs[nm]["ret20"] > 0).mean()) * 100,
             float(hold[use].mean()), met["full"]["cagr"], met["full"]["sharpe"], met["full"]["mdd"], met["full"]["n"], met["full"]["turn"],
             met["val"]["cagr"], met["val"]["sharpe"]))
def boot(dv, key, nb=10000, L=21, seed=20260923, chunk=250):
    ks = np.unique(key); kd = {k: i for i, k in enumerate(ks)}; nk = ks.size
    ki = np.array([kd[k] for k in key]); s = np.zeros(nk); c = np.zeros(nk)
    np.add.at(s, ki, dv); np.add.at(c, ki, 1.0)
    rng = np.random.default_rng(seed); off = np.arange(L); nbk = int(np.ceil(nk / L)); hi = max(nk - L, 0)
    out = np.empty(nb); got = 0
    while got < nb:
        m = min(chunk, nb - got)
        st = rng.integers(0, hi + 1, size=(m, nbk)); idx = (st[:, :, None] + off[None, None, :]).reshape(m, nbk * L)[:, :nk]
        n = c[idx].sum(axis=1); v = np.full(m, np.nan); ok = n > 0
        v[ok] = s[idx][ok].sum(axis=1) / n[ok]; out[got:got + m] = v; got += m
    v = out[np.isfinite(out)]
    return {"mean_pp": round(float(dv.mean()) * 100, 4), "ci95_lo_pp": round(float(np.percentile(v, 2.5)) * 100, 4),
            "ci95_hi_pp": round(float(np.percentile(v, 97.5)) * 100, 4), "p_gt0": round(float((v > 0).mean()), 4), "n": int(dv.size), "clusters": int(nk)}
print("\n=== 同事件配对差（A 事件，全池；按入场日聚类块 bootstrap）===")
res = {}
for nm in ("X1", "X2", "X3", "X4"):
    for w, (lo, hi) in (("full", (i_first, T - 1)), ("train", (i_first, i_tr)), ("val", (i_va, T - 1))):
        m = (e >= lo) & (e <= hi) & np.isfinite(runs["X0"]["retf20"]) & np.isfinite(runs[nm]["retf20"])
        dd = runs[nm]["retf20"][m] - runs["X0"]["retf20"][m]
        b = boot(dd, e[m]); res["X0->%s|%s" % (nm, w)] = b
        print("  X0->%s %-5s Δ均笔 %+7.3fpp CI[%+7.3f,%+7.3f] P=%.3f 事件%5d 簇%4d" % (nm, w, b["mean_pp"], b["ci95_lo_pp"], b["ci95_hi_pp"], b["p_gt0"], b["n"], b["clusters"]))
print("\n=== 组合级逐日配对（Δ年化 = Δ日均×244，块 bootstrap）===")
for nm in ("X4",):
    for w, (lo, hi) in (("full", (i_first, T - 1)), ("train", (i_first, i_tr)), ("val", (i_va, T - 1))):
        dd = rets[nm][lo:hi] - rets["X0"][lo:hi]
        b = boot(dd, np.arange(dd.size) // 21)  # 以 21 日为块聚类（保持时间结构）
        print("  X0->%s %-5s Δ年化 %+7.3f%% CI[%+7.3f,%+7.3f] P=%.3f 天%d" % (nm, w, b["mean_pp"] * 244 / 100, b["ci95_lo_pp"] * 244 / 100, b["ci95_hi_pp"] * 244 / 100, b["p_gt0"], b["n"]))
json.dump({"pool": "all(B4_K3)", "MAINBOARD": False, "events": cnt, "event_paired": res,
           "levels": {k: runs[k]["met"] for k in RULES},
           "per_rule_event": {k: {"n": runs[k]["n"], "mean_pct": round(float(runs[k]["ret20"].mean()) * 100, 4),
                                  "wr_pct": round(float((runs[k]["ret20"] > 0).mean()) * 100, 3),
                                  "hold": round(float(runs[k]["hold"][runs[k]["use"]].mean()), 3)} for k in RULES}},
          open(r"C:\Users\Admin\.pi-desktop\scratch\819deaca-ff8f-4e41-a272-5b5cb031c25d\allpool_exit.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n(已写 scratch/allpool_exit.json)")