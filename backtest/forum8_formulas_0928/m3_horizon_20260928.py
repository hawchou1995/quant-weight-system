# -*- coding: utf-8 -*-
"""m3_horizon_20260928.py — M3（受限版）：毛口径过门的 3 条 × 持有期扫描
问题：T+2 窗口里毛边际只有 +0.01~+0.12%，被 0.20% 回合成本吞掉；
      把持有期拉长（摊薄成本占比）能不能让「净口径」也过门？

口径（与 M2 v3 完全一致，只改持有期 K）：
  · 入场 = T+1 开盘（开盘涨停剔除，主板 1.10 / 创科 1.20）
  · 出场 = T+1+K 收盘（缺失顺延≤5日）
  · 基准 = 同 (入场日,出场日) 对的**可成交**全市场等权（剔除开盘涨停票）
  · 指标 = gross 超额（双方不计成本，安慰剂基线≈0）与 net 超额（信号腿扣 0.20%）
  · 门 = n ≥ 100 且按信号日聚类 95% CI 下界 > 0

用法: python m3_horizon_20260928.py --bodies DIR --out FILE [--ids 543,774,807]
"""
import argparse
import json
import os
import pathlib
import sys
import time

import numpy as np
from scipy import stats

R = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(R / "backtest/forum8_formulas_0928"))
import m2_sweep_20260928 as V1          # 复用 v1 的解析/编译/求值（冻结版）

COST = 0.0020
MIN_N = 100
ALPHA = 0.05
HORIZONS = (1, 2, 3, 5, 10, 20)


def log(*a):
    print(*a, flush=True)


def mult_of(code):
    c = code.lower()
    return 1.20 if (c.startswith("sz30") or c.startswith("sh688")) else 1.10


def horizon_study(sig, P, mult, K):
    O, H, L, C = P["O"], P["H"], P["L"], P["C"]
    Tn, N = C.shape
    pc = np.full_like(C, np.nan)
    pc[1:] = C[:-1]
    with np.errstate(all="ignore"):
        ZT = np.round(pc * mult[None, :], 2)
    t_idx, j_idx = np.where(sig)
    if t_idx.size == 0:
        return dict(K=K, n=0)
    e = t_idx + 1
    inw = e < Tn
    e_c = np.clip(e, 0, Tn - 1)
    zt = inw & np.isfinite(O[e_c, j_idx]) & (O[e_c, j_idx] >= ZT[e_c, j_idx] - 1e-4)
    ok = inw & np.isfinite(C[t_idx, j_idx]) & (C[t_idx, j_idx] > 0)
    ok &= np.isfinite(O[e_c, j_idx]) & (O[e_c, j_idx] > 0) & (~zt)
    t_idx, j_idx, e = t_idx[ok], j_idx[ok], e[ok]
    if t_idx.size == 0:
        return dict(K=K, n=0)
    x = e + K
    ext = np.zeros(x.shape, bool)               # 「已取到有效出场价」标志（不能只看下标在范围内）
    for k in range(0, 6):                       # 缺失顺延
        d = e + K + k
        need = (~ext) & (d <= Tn - 1)
        d_c = np.clip(d, 0, Tn - 1)
        good = need & np.isfinite(C[d_c, j_idx]) & (C[d_c, j_idx] > 0)
        x = np.where(good, d, x)
        ext |= good
    t_idx, j_idx, e, x = t_idx[ext], j_idx[ext], e[ext], x[ext]
    if t_idx.size == 0:
        return dict(K=K, n=0)
    entry = O[e, j_idx].astype(np.float64)
    exitp = C[x, j_idx].astype(np.float64)
    with np.errstate(all="ignore"):
        gross = exitp / entry - 1.0
    good = np.isfinite(gross) & np.isfinite(entry) & (entry > 0)
    t_idx, j_idx, e, x, gross = t_idx[good], j_idx[good], e[good], x[good], gross[good]
    # 可成交基准
    pairs, inv = np.unique(np.stack([e, x], axis=1), axis=0, return_inverse=True)
    bm = np.full(len(pairs), np.nan)
    for pi, (ee, xx) in enumerate(pairs):
        b = O[ee]
        c = C[xx]
        with np.errstate(all="ignore"):
            rr = c / b - 1.0
        m = np.isfinite(b) & (b > 0) & np.isfinite(c) & (c > 0)
        z = np.isfinite(O[ee]) & np.isfinite(ZT[ee]) & (O[ee] >= ZT[ee] - 1e-4)
        m = m & (~z)
        bm[pi] = np.nanmean(rr[m]) if m.any() else np.nan
    out = dict(K=K, n=int(len(gross)))
    for tag, retv in (("gross", gross), ("net", gross - COST)):
        exc = retv - bm[inv]
        okk = np.isfinite(exc)
        tt, ex_ = t_idx[okk], exc[okk]
        n = int(len(ex_))
        cnt = np.bincount(tt, minlength=Tn)
        s = np.bincount(tt, weights=ex_, minlength=Tn)
        dm = np.divide(s, cnt, out=np.zeros(Tn), where=cnt > 0)
        dm_act = dm[cnt > 0]
        nd = int(dm_act.size)
        sd = float(dm_act.std(ddof=1)) if nd > 1 else float("nan")
        se = sd / np.sqrt(nd) if nd > 1 else float("nan")
        tcrit = float(stats.t.ppf(1 - ALPHA / 2, nd - 1)) if nd > 1 else float("nan")
        ci_lo = float(dm_act.mean() - tcrit * se) if nd > 1 else float("nan")
        out[tag] = dict(mean_pct=round(float(ex_.mean()) * 100, 4),
                        med_pct=round(float(np.median(ex_)) * 100, 4),
                        day_mean_pct=round(float(dm_act.mean()) * 100, 4) if nd else None,
                        days=nd, t=round(float(dm_act.mean() / se), 3) if se and np.isfinite(se) and se > 0 else None,
                        ci_lo_pct=round(ci_lo * 100, 4) if np.isfinite(ci_lo) else None,
                        gate=bool(n >= MIN_N and np.isfinite(ci_lo) and ci_lo > 0))
    out["avg_hold_days"] = float((x - e + 1).mean())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bodies", required=True)
    ap.add_argument("--registry", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ids", default="543,774,807")
    a = ap.parse_args()

    t0 = time.time()
    dirp = pathlib.Path(a.bodies)
    registry = json.loads(pathlib.Path(a.registry).read_text(encoding="utf-8"))
    reg = {str(e["id"]): e for e in registry}
    z = np.load(V1.PANEL, allow_pickle=True)
    P = {k: z[k] for k in ("O", "H", "L", "C", "V", "A")}
    codes = [str(s) for s in z["syms"]]
    mult = np.array([mult_of(s) for s in codes])
    log("[panel] T=%d N=%d %s..%s" % (P["C"].shape[0], P["C"].shape[1],
                                      list(z["cal"])[0], list(z["cal"])[-1]))
    res = []
    for tid in a.ids.split(","):
        p = dirp / ("t%s.md" % tid)
        txt = p.read_text(encoding="utf-8")
        blocks = [V1.clean_code(b) for b in V1.extract_blocks(txt)]
        code = V1.normalize(max(blocks, key=len))
        t1 = time.time()
        r = V1.evaluate_formula(code, P)
        if r["kind"] != "①":
            log("[%s] 非①（%s）→ 跳过" % (tid, r.get("kind")))
            continue
        log("[%s] %s 求值完成 %d 列（%.0fs）" % (tid, r["signal_name"], r.get("eval_cols", 0),
                                                 time.time() - t1))
        row = dict(id=tid, title=reg.get(tid, {}).get("title"), signal=r.get("signal_name"),
                   horizons=[horizon_study(r["sig"], P, mult, K) for K in HORIZONS])
        res.append(row)
        for h in row["horizons"]:
            g, nn = h.get("gross", {}), h.get("net", {})
            log("   K=%-3d n=%-7d gross=%+.4f%% (t=%-6s CIlo=%+.4f%% %s) | net=%+.4f%% (CIlo=%+.4f%% %s)"
                % (h["K"], h.get("n", 0), g.get("mean_pct", 0), g.get("t"),
                   g.get("ci_lo_pct", 0), "过门" if g.get("gate") else "否证",
                   nn.get("mean_pct", 0), nn.get("ci_lo_pct", 0),
                   "过门" if nn.get("gate") else "否证"))
    out = dict(generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
               purpose="M3 受限版：3 条毛口径过门者的持有期扫描（成本能否被摊薄）",
               cost=COST, horizons=list(HORIZONS), min_n=MIN_N, alpha=ALPHA,
               rows=res, runtime_sec=round(time.time() - t0, 1))
    pathlib.Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log("[done] %s (%.0fs)" % (a.out, time.time() - t0))


if __name__ == "__main__":
    main()
