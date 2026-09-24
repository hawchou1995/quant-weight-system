# -*- coding: utf-8 -*-
"""factor_gate — 因子入库前置闸（R-factorgate-0918）
audit   <mod:func>          因果审计：截断重算查前视
profile <f.npz>             无信号全市场分位画像
compare <f.npz> <sig.npz>   信号 vs 市场量级比
infer   <sig.npz>           聚类稳健推断：按天重算显著性与有效样本量（见 factor_infer.py）
selftest                    内置正/负对照（须一过一败）
"""
import os
import sys, json, importlib
import numpy as np
from scipy.ndimage import maximum_filter1d, minimum_filter1d

# 2026-09-22 修复（R-dash-track-0922）：原为相对路径，从仓库根目录调用（日链写法
# `["backtest/revscreen_regen.py"]`）会 FileNotFoundError → 静默陈旧。改为 __file__ 锚定的绝对路径。
PANEL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "kv_resonance_0913", "panel_kv_0913.npz")
KEYS = ("close", "high", "low", "open", "amount", "mask")

def load_panel(path=PANEL, trunc=None, f32=False, sub=1):
    D = np.load(path, allow_pickle=True)
    P = {}
    for k in KEYS:
        try:
            a = D[k]
        except KeyError:
            if k == "mask":          # 扩展面板用 MB 作键名
                a = D["MB"]
            else:
                raise
        if trunc is not None:
            a = a[:trunc]
        if sub > 1:
            a = a[:, ::sub]
        if k == "mask":
            P[k] = a.astype(bool)
        else:
            P[k] = a.astype(np.float32 if f32 else np.float64)
    return P

def roll_trailing(a, n, kind):
    """尾随窗口 [i-n+1, i]。scipy 默认 origin=0 为居中窗口会前视 n//2 天——禁用默认写法。"""
    o = n - 1 - n // 2
    v = np.isfinite(a)
    av = np.where(v, a, -np.inf if kind == "max" else np.inf)
    fn = maximum_filter1d if kind == "max" else minimum_filter1d
    f = fn(av, n, axis=0, origin=o)
    cnt = np.cumsum(v, axis=0)
    cw = cnt.copy()
    cw[n:] = cnt[n:] - cnt[:-n]
    ok = cw >= max(1, n - 2)
    f = np.where(ok & (f > -np.inf) & (f < np.inf), f, np.nan)
    f[:n-1] = np.nan
    return f

def fwd_ret(P, hold=10):
    """R[i] = C[i+hold+1] / O[i+1] - 1  （入场 T+1 开盘 -> 出场 T+hold+1 收盘）"""
    C = P["close"]; O = P["open"]
    T, N = C.shape
    R = np.full((T, N), np.nan)
    if T > hold + 1:
        R[:T-hold-1] = C[hold+1:] / np.maximum(O[1:T-hold], 1e-9) - 1
    return R

def bucketize(F, mask, nb=5):
    """按当日截面分位切 nb 桶，返回 (b, qs)。b=-1 表示不可用。"""
    T, N = F.shape
    pct = np.linspace(0.0, 100.0, nb + 1)[1:-1]
    qs = np.full((T, nb - 1), np.nan)
    for i in range(T):
        v = F[i][mask[i]]
        v = v[np.isfinite(v)]
        if len(v) >= 100:
            qs[i] = np.percentile(v, pct)
    okbase = mask & np.isfinite(F) & np.isfinite(qs[:, 0])[:, None]
    b = np.full((T, N), -1, np.int8)
    prev = np.ones((T, N), bool)
    for k in range(nb):
        if k == nb - 1:
            m = okbase & prev
        else:
            m = okbase & prev & (F < qs[:, k][:, None])
        b = np.where(m, k, b)
        if k < nb - 1:
            prev = prev & (F >= qs[:, k][:, None])
    return b, qs

def _stat(v):
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return None
    return {"n": int(len(v)), "mean": float(v.mean()), "med": float(np.median(v)), "wr": float((v > 0).mean())}

def profile(F, R, mask, nb=5):
    b, qs = bucketize(F, mask, nb)
    ok = mask & np.isfinite(R)
    out = {}
    means = []
    for k in range(nb):
        s = _stat(R[ok & (b == k)])
        out["B%d" % (k + 1)] = s
        means.append(s["mean"] if s else np.nan)
    fin = [x for x in means if np.isfinite(x)]
    out["spread_pp"] = float((max(fin) - min(fin)) * 100) if fin else None
    out["mono_inc"] = bool(all(means[i] < means[i+1] for i in range(nb-1))) if all(np.isfinite(means)) else False
    out["mono_dec"] = bool(all(means[i] > means[i+1] for i in range(nb-1))) if all(np.isfinite(means)) else False
    return out, b

def audit_fn(fn, sample=12, tol=1e-6, verbose=True, sub=1):
    P = load_panel(sub=sub)
    T = P["close"].shape[0]
    full = np.asarray(fn(P), dtype=np.float64)
    del P
    rng = np.random.default_rng(20260918)
    lo = 120
    idx = set([lo, T - 1])
    while len(idx) < sample:
        idx.add(int(rng.integers(lo, T)))
    idx = sorted(idx)
    bad = 0
    worst = 0.0
    rows = []
    for i in idx:
        Pt = load_panel(trunc=i + 1, sub=sub)
        got = np.asarray(fn(Pt), dtype=np.float64)
        a = got[i]; bb = full[i]
        nanmis = int((np.isfinite(a) != np.isfinite(bb)).sum())
        m = np.isfinite(a) & np.isfinite(bb)
        mx = float(np.abs(a[m] - bb[m]).max()) if m.any() else 0.0
        if nanmis > 0 or mx > tol:
            bad += 1
        worst = max(worst, mx)
        rows.append((i, nanmis, mx))
    res = {"n_sample": len(idx), "mismatch_rows": bad, "mismatch_rate": bad / len(idx), "max_abs_diff": worst, "tol": tol, "verdict": "PASS" if bad == 0 else "FAIL"}
    if verbose:
        for i, nm, mx in rows:
            print("   day %5d  nan_mismatch=%d  max_abs_diff=%.3e" % (i, nm, mx))
    return res

def compare(F, S, R, mask, nb=5, thr=1.5):
    b, qs = bucketize(F, mask, nb)
    ok = mask & np.isfinite(R) & (b >= 0)
    s = ok & S
    sig = _stat(R[s])
    if sig is None:
        return {"error": "signal has no valid samples"}, b
    w = np.array([float((s & (b == k)).sum()) for k in range(nb)])
    if w.sum() == 0:
        return {"error": "signal outside buckets"}, b
    w = w / w.sum()
    mk = np.array([float(R[ok & (b == k)].mean()) for k in range(nb)])
    matched = float((w * mk).sum())
    ratio = (sig["mean"] / matched) if matched != 0 else None
    out = {"signal": sig, "market_matched_mean": matched, "ratio": ratio,
           "bucket_weights": [round(float(x), 3) for x in w],
           "bucket_market_means": [round(float(x), 5) for x in mk],
           "thr": thr,
           "verdict": ("SIGNAL" if (ratio is not None and ratio >= thr) else "NOT_A_SIGNAL")}
    return out, b

def _relpos_trailing(P):
    HH = roll_trailing(P["high"], 60, "max")
    LL = roll_trailing(P["low"], 60, "min")
    return (P["close"] - LL) / np.maximum(HH - LL, 1e-9)

def _relpos_centered(P):
    """负对照：故意使用 scipy 默认居中窗口（= R-lookahead-0918 的缺陷写法）"""
    HH = maximum_filter1d(P["high"], 60, axis=0)
    LL = minimum_filter1d(P["low"], 60, axis=0)
    return (P["close"] - LL) / np.maximum(HH - LL, 1e-9)

def qmask(F, mask, pct):
    T = F.shape[0]
    q = np.full(T, np.nan)
    for i in range(T):
        v = F[i][mask[i]]
        v = v[np.isfinite(v)]
        if len(v) >= 100:
            q[i] = np.percentile(v, pct)
    return mask & np.isfinite(F) & (F < q[:, None])

def selftest():
    print("=== T1 负对照：居中 roll 的 rel_pos60（期望 FAIL）===")
    r1 = audit_fn(_relpos_centered, sample=8, verbose=False)
    print("   ", json.dumps({k: r1[k] for k in ("n_sample", "mismatch_rows", "mismatch_rate", "max_abs_diff", "verdict")}, ensure_ascii=False))
    print("=== T2 正对照：尾随 roll_trailing 同一因子（期望 PASS）===")
    r2 = audit_fn(_relpos_trailing, sample=8, verbose=False)
    print("   ", json.dumps({k: r2[k] for k in ("n_sample", "mismatch_rows", "mismatch_rate", "max_abs_diff", "verdict")}, ensure_ascii=False))
    P = load_panel()
    F = _relpos_trailing(P)
    R = fwd_ret(P, 10)
    print("=== T3 profile：尾随 rel_pos60 全市场四分位（极差应 <1pp）===")
    pr, _ = profile(F, R, P["mask"], 4)
    for k in ("B1", "B2", "B3", "B4"):
        s = pr[k]
        print("    %s n=%d mean=%+.3f%% med=%+.3f%%" % (k, s["n"], s["mean"] * 100, s["med"] * 100))
    print("    spread_pp=%.3f mono_inc=%s mono_dec=%s" % (pr["spread_pp"], pr["mono_inc"], pr["mono_dec"]))
    print("=== T4 compare：纯因子代理信号 S=(rel_pos60<当日q20)（期望 NOT_A_SIGNAL）===")
    S = qmask(F, P["mask"], 20)
    cm, _ = compare(F, S, R, P["mask"], 5)
    print("   ", json.dumps({k: cm.get(k) for k in ("signal", "market_matched_mean", "ratio", "bucket_weights", "verdict")}, ensure_ascii=False))
    chk = (r1["verdict"] == "FAIL") and (r2["verdict"] == "PASS") and (pr["spread_pp"] is not None and pr["spread_pp"] < 1.0) and (cm.get("verdict") == "NOT_A_SIGNAL")
    print("SELFTEST:", "ALL PASS" if chk else "FAILED")
    return chk

def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    mode = a[0]
    if mode == "audit":
        mod, fn = a[1].split(":")
        sub = int(a[a.index("--sub") + 1]) if "--sub" in a else 1
        smp = int(a[a.index("--sample") + 1]) if "--sample" in a else 12
        r = audit_fn(getattr(importlib.import_module(mod), fn), sample=smp, sub=sub)
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif mode == "profile":
        P = load_panel()
        F = np.load(a[1])["f"].astype(np.float64)
        R = fwd_ret(P, 10)
        pr, _ = profile(F, R, P["mask"], 5)
        print(json.dumps(pr, ensure_ascii=False, indent=1))
    elif mode == "compare":
        P = load_panel()
        F = np.load(a[1])["f"].astype(np.float64)
        S = np.load(a[2])["sig"].astype(bool)
        R = fwd_ret(P, 10)
        cm, _ = compare(F, S, R, P["mask"], 5)
        print(json.dumps(cm, ensure_ascii=False, indent=1))
    elif mode == "selftest":
        selftest()
    elif mode == "selftest2":
        selftest2()
    elif mode == "finite-check":
        keys = a[a.index("--keys") + 1].split(",") if "--keys" in a else None
        r = finite_check(a[1], keys=keys, ret=("--ret" in a))
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif mode == "sample-check":
        ths = tuple(float(x) for x in a[a.index("--ths") + 1].split(",")) if "--ths" in a else (0.01, 0.03, 0.05)
        mn = int(a[a.index("--min") + 1]) if "--min" in a else 30
        r = sample_check(a[1], ths=ths, minu=mn, absv=("--abs" in a))
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif mode == "warmup-check":
        r = warmup_check(a[1])
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif mode == "infer":
        import factor_infer as FI
        o = FI.infer(
            a[1],
            key=(a[a.index("--key") + 1] if "--key" in a else None),
            hold=int(a[a.index("--hold") + 1]) if "--hold" in a else FI.HOLD,
            block=int(a[a.index("--block") + 1]) if "--block" in a else 20,
            B=int(a[a.index("--B") + 1]) if "--B" in a else 1000,
            excess=("--excess" in a),
        )
        print(FI._plain(o))
        print(json.dumps(o, ensure_ascii=False, indent=1))
    else:
        print(__doc__)


# ================= v2 新增：三类缺陷检查 =================

def finite_check(path, keys=None, ret=False, panel_path=None, save=None):
    D = np.load(path, allow_pickle=True)
    if keys is None:
        keys = [k for k in D.keys() if hasattr(D[k], "shape") and getattr(D[k], "ndim", 0) >= 1 and D[k].dtype.kind == "f"]
    out = {}
    fail = False
    for k in keys:
        a = D[k]
        wi = np.isinf(a)
        nan = int(np.isnan(a).sum())
        pinf = int((wi & (a > 0)).sum())
        ninf = int((wi & (a < 0)).sum())
        out[k] = {"nan": nan, "posinf": pinf, "neginf": ninf}
        if pinf or ninf:
            fail = True
    res = {"keys": out, "verdict": "FAIL" if fail else "PASS"}
    if ret:
        P = load_panel(panel_path) if panel_path else load_panel()
        C = P["close"].astype(np.float64)
        r = np.full_like(C, np.nan)
        r[1:] = C[1:] / C[:-1] - 1
        bad = np.isinf(r)          # 只计 inf；NaN 是面板天然状态，不构成缺陷
        bad[0, :] = False
        idx = np.argwhere(bad)
        zc = int(((C[:-1] <= 0) & np.isfinite(C[:-1])).sum())
        res["ret_nonfinite_cells"] = int(len(idx))
        res["ret_sample_cells"] = [[int(i), int(j)] for i, j in idx[:5]]
        res["zero_neg_prev_close"] = zc
        if len(idx):
            fail = True
            res["verdict"] = "FAIL"
    return res

def sample_check(path, ths=(0.01, 0.03, 0.05), minu=30, panel_path=None, key="f", absv=False):
    P = load_panel(panel_path) if panel_path else load_panel()
    F = np.load(path)[key].astype(np.float64)
    mask = P["mask"]
    T, N = F.shape
    R = np.full((T, N), np.nan, dtype=np.float32)
    for i in range(T):
        m = mask[i] & np.isfinite(F[i])
        if int(m.sum()) < 50:
            continue
        v = F[i][m]
        rk = np.argsort(np.argsort(v)).astype(np.float32) + 1.0
        R[i][m] = rk / len(v)
    fin = F[mask & np.isfinite(F)]
    out = {"factor": path, "pct": {}, "thresholds": {}, "min_uniq": minu}
    for q in (1, 5, 10, 25, 50):
        out["pct"]["p%d" % q] = round(float(np.percentile(fin, q)), 6)
    out["mode"] = "abs" if absv else "quantile"
    for th in ths:
        if absv:
            sel = mask & np.isfinite(F) & (F <= th)
        else:
            sel = mask & np.isfinite(R) & (R <= th)
        ii, jj = np.where(sel)
        uniq = int(len(np.unique(jj)))
        out["thresholds"]["%.3f" % th] = {"n": int(len(ii)), "uniq": uniq,
                                          "verdict": ("UNDECIDABLE" if uniq < minu else "OK")}
    out["verdict"] = "FAIL" if any(v["verdict"] == "UNDECIDABLE" for v in out["thresholds"].values()) else "PASS"
    return out

def warmup_check(path, thr=0.5):
    D = np.load(path, allow_pickle=True)
    mask = D["mask"].astype(bool)
    T, N = mask.shape
    fv = np.full(N, -1, dtype=np.int32)
    for j in range(N):
        ix = np.flatnonzero(mask[:, j])
        if len(ix):
            fv[j] = int(ix[0])
    vals = fv[fv >= 0]
    det = bool(vals.min() > 0 and float((vals > 0).mean()) >= thr)
    return {"codes_with_data": int(len(vals)), "min": int(vals.min()),
            "p25": int(np.percentile(vals, 25)), "median": int(np.median(vals)),
            "gt0": int((vals > 0).sum()), "gt0_share": round(float((vals > 0).mean()), 4),
            "warmup_detected": det, "implied_warmup_days": int(vals.min()) if det else 0,
            "verdict": "WARN" if det else "OK",
            "note": ("检测到引擎域门：上市初期被系统性排除 -> 收益集中在上市初期的策略必须走裸面板版（陷阱 ★176）" if det else "未见系统性上市初期排除")}

def selftest2():
    import os
    ok = True
    print("=== T5 finite-check: 真实扩展面板(含零价行) -> 期望 FAIL ===")
    if os.path.exists("_tmp_0918_sn_panel_ext.npz"):
        r5 = finite_check("_tmp_0918_sn_panel_ext.npz", ret=True, panel_path="_tmp_0918_sn_panel_ext.npz")
        print("   ", json.dumps({k: r5[k] for k in ("verdict", "ret_nonfinite_cells", "zero_neg_prev_close")}, ensure_ascii=False))
        print("    样例单元 [row, col]:", r5.get("ret_sample_cells"))
        good5 = (r5["verdict"] == "FAIL" and r5["ret_nonfinite_cells"] > 0 and r5["zero_neg_prev_close"] > 0)
    else:
        print("    [SKIP] 面板缺失"); good5 = False
    print()
    print("=== T6 sample-check: 真实 FR 面板 + 极紧阈值 -> 期望 UNDECIDABLE ===")
    if os.path.exists("_tmp_0918_sn_mv.npz"):
        M = np.load("_tmp_0918_sn_prep.npz")          # 主板口径 FR (2599x4087) = 复现 ★177 原案
        np.savez_compressed("_tmp_gate_FR_mb.npz", f=M["FR"])
        r6 = sample_check("_tmp_gate_FR_mb.npz", ths=(0.03, 0.05), minu=30, absv=True)
        for k, v in r6["thresholds"].items():
            print("     th=%s  n=%7d  uniq=%5d  %s" % (k, v["n"], v["uniq"], v["verdict"]))
        print("     FR 分布:", r6["pct"])
        good6 = r6["verdict"] == "FAIL"
    else:
        print("    [SKIP] FR 面板缺失"); good6 = False
    print()
    print("=== T7 warmup-check: 真实 KV 面板 -> 期望检出 warmup≈119-120 ===")
    if os.path.exists("kv_resonance_0913/panel_kv_0913.npz"):
        r7 = warmup_check("kv_resonance_0913/panel_kv_0913.npz")
        print("   ", json.dumps({k: r7[k] for k in ("codes_with_data", "min", "p25", "median", "gt0", "gt0_share", "warmup_detected", "implied_warmup_days", "verdict")}, ensure_ascii=False))
        good7 = r7["warmup_detected"] and 115 <= r7["implied_warmup_days"] <= 125
    else:
        print("    [SKIP] KV 面板缺失"); good7 = False
    ok = good5 and good6 and good7
    print()
    print("SELFTEST2:", "ALL PASS" if ok else "FAILED", "| T5=%s T6=%s T7=%s" % (good5, good6, good7))
    return ok


if __name__ == "__main__":
    main()
