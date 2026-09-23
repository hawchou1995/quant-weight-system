# -*- coding: utf-8 -*-
"""R-qlch-e2vx4-0923 · E2（固定2日持有）vs X4（新生产）同事件配对（全池）
预注册：backtest/PRE-REGISTRATION_20260923_qlch_e2vx4.md
"""
import importlib.util, json, os, sys, time, io
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
BK = "backtest"; T0 = time.time()
RULES = {"X0": ("tpsl", 15, -20, 20), "X4": ("tpsl", 25, -30, 40), "E2": ("fixed", 0, 0, 2)}
PAIRS = [("E2", "X4"), ("E2", "X0"), ("X4", "X0")]
COSTS = {"P20": 0.0020, "S60": 0.0060}
os.environ["QLCH_VARIANT"] = "B4"; os.environ["QLCH_MAXPOS"] = "3"
os.environ["QLCH_GATE"] = "20"; os.environ["QLCH_MAINBOARD"] = "0"
sp = importlib.util.spec_from_file_location("g", BK + "/qlch_grid_bt_0923.py")
g = importlib.util.module_from_spec(sp); sp.loader.exec_module(g)
sp2 = importlib.util.spec_from_file_location("eng", BK + "/qlch_paper_20260921.py")
eng = importlib.util.module_from_spec(sp2); sp2.loader.exec_module(eng)
print("[%4.1fs] MAINBOARD=%s VARIANT=%s（在产口径）" % (time.time()-T0, eng.MAINBOARD, eng.VARIANT), flush=True)
P = eng.load_all(); S = eng.build_signals(P)
cal, T = S["cal"], S["close"].shape[0]
ents = g.entry_cases(S); cnt = {k: int(ents[k]["e"].size) for k in "ABC"}
assert cnt == {"A": 3895, "B": 399, "C": 41589}, cnt
print("[%4.1fs] 全池事件数 A=%d B=%d C=%d（对拍 allpool 一致 ✓）" % (time.time()-T0, cnt["A"], cnt["B"], cnt["C"]), flush=True)
d = ents["A"]; e, j, px = d["e"], d["j"], d["px"]
kmax = 40
Oa, Ha, La, Ca = g.case_path(e, j, S["open"], S["high"], S["low"], S["close"], T, kmax)
i_first = int(np.concatenate([ents[k]["e"] for k in "ABC"]).min())
i_tr = max([i for i, x in enumerate(cal) if x <= g.TRAIN_HI] or [0])
i_va = min([i for i, x in enumerate(cal) if x >= g.VAL_LO] or [T-1])
W = {"full": (i_first, T-1), "train": (i_first, i_tr), "val": (i_va, T-1)}
R = {}
for nm, (kind, tp, sl, h) in RULES.items():
    if kind == "tpsl":
        kf, expx, exrs, hit = g.resolve_exit(px, Oa, Ha, La, Ca, tp/100.0, sl/100.0)
    else:
        kf, expx, exrs, hit = g.resolve_exit(px, Oa, Ha, La, Ca, 1e9, -1e9)
    use, x, opx, hold, reason = g.exit_plan(e, px, kf, expx, exrs, hit, Ca, h, T)
    gross = np.full(e.size, np.nan); gross[use] = opx[use]/px[use] - 1.0
    rf = {ck: gross - cv for ck, cv in COSTS.items()}
    R[nm] = {"use": use, "x": x, "hold": hold, "reason": reason, "retf": rf, "n": int(use.sum())}
    print("[%4.1fs] %s：可用 %d | 单笔均值(20bp) %+.3f%% | 持有均值 %.2f 日 | 出场原因 %s"
          % (time.time()-T0, nm, R[nm]["n"], np.nanmean(rf["P20"])*100, hold[use].mean(),
             {int(k): int((reason[use]==k).sum()) for k in sorted(set(reason[use].tolist()))}), flush=True)
# P4 结构自检
assert np.all(R["E2"]["hold"][R["E2"]["use"]] == 2), "E2 持有必须恒为 2 日（可用事件内）"
assert set(R["E2"]["reason"][R["E2"]["use"]].tolist()) == {4}, "E2 出场原因必须单一（到期平仓）"
print("[%4.1fs] P4 结构自检通过：E2 持有恒 2 日 / 出场单一；X4 平均持有 %.2f 日" % (time.time()-T0, R["X4"]["hold"][R["X4"]["use"]].mean()), flush=True)
def boot(dv, key, nb=10000, L=21, seed=20260923, chunk=250):
    ks = np.unique(key); kd = {k: i for i, k in enumerate(ks)}; nk = ks.size
    ki = np.array([kd[k] for k in key]); s = np.zeros(nk); c = np.zeros(nk)
    np.add.at(s, ki, dv); np.add.at(c, ki, 1.0)
    rng = np.random.default_rng(seed); off = np.arange(L); nbk = int(np.ceil(nk/L)); hi = max(nk-L, 0)
    out = np.empty(nb); got = 0
    while got < nb:
        m = min(chunk, nb-got)
        st = rng.integers(0, hi+1, size=(m, nbk))
        idx = (st[:, :, None] + off[None, None, :]).reshape(m, nbk*L)[:, :nk]
        n = c[idx].sum(axis=1); v = np.full(m, np.nan); ok = n > 0
        v[ok] = s[idx][ok].sum(axis=1)/n[ok]; out[got:got+m] = v; got += m
    v = out[np.isfinite(out)]
    return {"mean_pp": round(float(dv.mean())*100, 4), "ci95_lo_pp": round(float(np.percentile(v,2.5))*100, 4),
            "ci95_hi_pp": round(float(np.percentile(v,97.5))*100, 4), "p_a_gt_b": round(float((v>0).mean()), 4),
            "n": int(dv.size), "clusters": int(nk), "sd_pp": round(float(dv.std(ddof=1))*100, 3),
            "discernible_pp": round(1.96*float(dv.std(ddof=1))/np.sqrt(dv.size)*2.8*100, 3)}
res = {"meta": {"title": "R-qlch-e2vx4-0923", "preregistration": "backtest/PRE-REGISTRATION_20260923_qlch_e2vx4.md",
                "pool": "全池(B4_K3)", "rules": {k: list(v) for k, v in RULES.items()}, "pairs": PAIRS,
                "windows": {k: {"lo": cal[v[0]], "hi": cal[v[1]]} for k, v in W.items()},
                "run_at": time.strftime("%Y-%m-%d %H:%M:%S")}, "event": {}, "levels": {}, "gate": {}}
print("\n=== 同事件配对差（全池；Δ = 前者 − 后者）===")
for a, b in PAIRS:
    for w, (lo, hi) in W.items():
        m = (e >= lo) & (e <= hi) & np.isfinite(R[a]["retf"]["P20"]) & np.isfinite(R[b]["retf"]["P20"])
        dv = R[a]["retf"]["P20"][m] - R[b]["retf"]["P20"][m]
        r = boot(dv, e[m]); res["event"]["%s-%s|%s" % (a, b, w)] = r
        print("  %s-%s %-5s Δ %+7.3fpp CI[%+7.3f,%+7.3f] P(>0)=%.3f n=%5d 簇%4d σ(d)=%5.2f 可辨≈%4.2f"
              % (a, b, w, r["mean_pp"], r["ci95_lo_pp"], r["ci95_hi_pp"], r["p_a_gt_b"], r["n"], r["clusters"], r["sd_pp"], r["discernible_pp"]), flush=True)
for w, (lo, hi) in W.items():
    m = (e >= lo) & (e <= hi) & np.isfinite(R["E2"]["retf"]["P20"]) & np.isfinite(R["X4"]["retf"]["P20"])
    dv = R["E2"]["retf"]["P20"][m] - R["X4"]["retf"]["P20"][m]
    yrs = np.array([cal[t][:4] for t in e[m]])
    res["yearly_%s" % w] = {str(y): round(float(dv[yrs == y].mean())*100, 3) for y in sorted(set(yrs.tolist()))}
print("\n=== 组合级水平（含 0922 卡片 E2 对照）===")
for nm in ("X0", "X4", "E2"):
    use = R[nm]["use"]
    for ck, cv in COSTS.items():
        nav, inv, te, tx, tr, th, tv = g.simulate(e[use], R[nm]["x"][use], (R[nm]["retf"][ck])[use], R[nm]["hold"][use], T, g.SEEDS, g.K)
        met = g.metrics_all(nav, inv, te, tr, th, tv, W, len(g.SEEDS))
        res["levels"]["%s|%s" % (nm, ck)] = met
        f = met["full"]
        print("  %s %s full 年化%+7.2f%% 夏普%6.3f 回撤%+7.2f%% 笔%5d 换手%5.1f 资金占用%5.1f%% | train 年化%+7.2f%% 夏普%6.3f 回撤%+7.2f%% | val 年化%+7.2f%% 夏普%6.3f"
              % (nm, ck, f["cagr"], f["sharpe"], f["mdd"], f["n"], f["turn"], f["inv"], met["train"]["cagr"], met["train"]["sharpe"], met["train"]["mdd"], met["val"]["cagr"], met["val"]["sharpe"]), flush=True)
main = res["event"]["E2-X4|full"]; tr_ = res["event"]["E2-X4|train"]; va = res["event"]["E2-X4|val"]
P1 = "E2 显著更好" if main["ci95_lo_pp"] > 0 else ("X4 显著更好" if main["ci95_hi_pp"] < 0 else "无差异（CI 含 0）")
P2 = (tr_["mean_pp"] * va["mean_pp"] > 0)
yv = res["yearly_full"]; sgn = [v for v in yv.values() if v != 0]
P3 = (sum(1 for v in sgn if (v > 0) == (main["mean_pp"] > 0)) / max(len(sgn), 1) >= 0.60)
res["gate"] = {"P1": {"verdict": P1, "mean_pp": main["mean_pp"], "ci": [main["ci95_lo_pp"], main["ci95_hi_pp"]]},
               "P2_dual_blind": {"train": tr_["mean_pp"], "val": va["mean_pp"], "same_sign": bool(P2)},
               "P3_yearly_share": {"share": round(sum(1 for v in sgn if (v > 0) == (main["mean_pp"] > 0))/max(len(sgn),1), 3), "pass": bool(P3), "yearly": yv},
               "P4_structure": {"pass": True, "E2_hold": 2, "X4_hold_mean": round(float(R["X4"]["hold"][R["X4"]["use"]].mean()), 2)},
               "consequence": "见预注册 §四；任何情形不改生产"}
print("\n[判决] P1=%s（Δ=%+.3fpp CI[%+.3f,%+.3f]）| P2 双盲同号=%s | P3 逐年同号率=%.0f%% (%s)"
      % (P1, main["mean_pp"], main["ci95_lo_pp"], main["ci95_hi_pp"], P2, res["gate"]["P3_yearly_share"]["share"]*100, "过" if P3 else "不过"), flush=True)
json.dump(res, open("backtest/qlch_e2vx4_0923.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已落盘 backtest/qlch_e2vx4_0923.json | 总耗时 %.1f s" % (time.time()-T0))