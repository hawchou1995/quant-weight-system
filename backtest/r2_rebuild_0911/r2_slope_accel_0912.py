# -*- coding: utf-8 -*-
"""r2 · 均线斜率加速度带限入场 + 斜率回落离场（用户提案，2026-09-12）
================================================================
用户提案：「均线斜率突然增加时入场（增幅不要太大），斜率降低时离场（考虑多大斜率离场）」。
与已测的区别：已测的是斜率【水平值】排序因子（f_slope20，三域负 IC、组合≈beta）；
本实验测【加速度 Δslope】+【带限（排除已陡峭段）】+【斜率回落条件退出】。
定义：
  sl_w(t) = OLS 斜率(MA_w 在 w 窗口) / close        （相对斜率，元/日/元）
  dsl(t)  = sl_w(t) − sl_w(t−5)                      （5 日加速度）
  入场带：dsl ∈ [lo, hi]，(lo,hi) = MA20/MA60 各取全样本正 dsl 分位带
          B1=[p60,p95] B2=[p75,p95] B3=[p90,p99]     （"增加但不能太大"→排除最陡段）
  离场：sl_w(t) < θ（θ=0，斜率翻负），或持有 60 交易日上限
预注册：6 配置（2 窗口 × 3 带）× k=20/40/60 事件研究 → 净@1.15% 幸存带 →
        事件驱动组合（N∈{10,20}×门控{开,关}）+ 分域拆解 + 安慰剂 100 seeds。
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
R2 = BASE / "backtest" / "r2_rebuild_0911"
sys.path.insert(0, str(R2))
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "backtest"))

import v8_selector as V  # noqa: E402
import r2_portfolio_engine_0912 as E  # noqa: E402

KS = (20, 40, 60)
WINDOWS = (20, 60)
COST_RT = 1.15


def roll_slope(y: np.ndarray, W: int):
    """滚动 OLS 斜率（对时间），前 W*2-2 为 NaN（先 MA 再回归需要 2W 窗口）"""
    from numpy.lib.stride_tricks import sliding_window_view
    ma = pd.Series(y).rolling(W, min_periods=W).mean().to_numpy()
    t = np.arange(W, dtype=float)
    tm = t.mean()
    tvar = ((t - tm) ** 2).sum()
    out = np.full(len(y), np.nan)
    if len(y) < 2 * W - 1:
        return out
    win = sliding_window_view(ma[W - 1:], W)
    finite = np.isfinite(win).all(axis=1)
    b = np.full(win.shape[0], np.nan)
    if finite.any():
        w = win[finite]
        b[finite] = (w @ t - W * tm * w.mean(axis=1)) / tvar
    out[W - 1 + W - 1:] = b
    return out


def main():
    t0 = time.time()
    pool = V.load_pool(use_cache=True)
    codes = [c for c in pool if c.startswith(("sh60", "sz00"))]
    idx = V.load_index(250).set_index("date")
    ma20i = idx["close"].rolling(20, min_periods=20).mean()
    ma250 = idx["close"].rolling(250, min_periods=250).mean()
    regime = pd.Series(np.where(idx["close"] < ma250, "bear",
                                np.where(idx["close"] < ma20i, "weak", "strong")),
                       index=idx.index)
    all_dates = regime.index
    n_d = len(all_dates)
    dpos_all = pd.Series(np.arange(n_d), index=all_dates)

    # 全样本 dsl 分布（先扫一遍累计分位样本）
    t1 = time.time()
    sl_store = {}
    quant_sample = {w: [] for w in WINDOWS}
    for ci, code in enumerate(codes):
        df = pool[code]
        c = df["close"].to_numpy(float)
        pos = dpos_all.reindex(df.index).to_numpy()
        for w in WINDOWS:
            sl = roll_slope(c, w)
            sl_rel = sl / c
            dsl = sl_rel - np.roll(sl_rel, 5)
            dsl[:max(5, 2 * w)] = np.nan
            sl_store[(code, w)] = (sl_rel, dsl, pos)
            finite = dsl[np.isfinite(dsl)]
            if len(finite) > 200:
                quant_sample[w].append(finite[::29])   # 抽样 1/29 控内存
        if ci % 800 == 0:
            print(f"  [sl] {ci} ({time.time()-t1:.0f}s)", flush=True)
    qs = {}
    for w in WINDOWS:
        arr = np.concatenate(quant_sample[w])
        qs[w] = {p: float(np.quantile(arr, p)) for p in (0.60, 0.75, 0.90, 0.95, 0.99)}
        print(f"  dsl 分位 w={w}: {qs[w]}", flush=True)
    del quant_sample

    BANDS = {}
    for w in WINDOWS:
        q = qs[w]
        BANDS[w] = {"B1": (q[0.60], q[0.95]), "B2": (q[0.75], q[0.95]), "B3": (q[0.90], q[0.99])}

    # 事件研究
    configs = [(w, bn) for w in WINDOWS for bn in BANDS[w]]
    n_cfg = len(configs)
    base_sum = {k: np.zeros(n_d) for k in KS}
    base_cnt = {k: np.zeros(n_d, dtype=np.int64) for k in KS}
    sig_sum = {(w, bn): {k: np.zeros(n_d) for k in KS} for w, bn in configs}
    sig_cnt = {(w, bn): {k: np.zeros(n_d, dtype=np.int64) for k in KS} for w, bn in configs}
    sig_dom = {(w, bn): {} for w, bn in configs}   # domain -> count

    MIN_BASE = 50
    done = 0
    for code in codes:
        df = pool[code]
        o = df["open"].to_numpy(float)
        base = o
        fwd = {}
        for k in KS:
            fwd[k] = np.full(len(o), np.nan)
            fwd[k][:-1-k] = o[1+k:-(0)] if False else o[k+1:] if False else None
        # 直接算：fwd_k[i] = o[i+1+k]/o[i+1]-1
        for k in KS:
            f = np.full(len(o), np.nan)
            f[:len(o)-1-k] = o[1+k:] / o[1:len(o)-k] - 1
            fwd[k] = f
        pos = dpos_all.reindex(df.index).to_numpy()
        okp = np.isfinite(pos)
        doms = regime.reindex(df.index).to_numpy()
        for (w, bn) in configs:
            sl_rel, dsl, posc = sl_store[(code, w)]
            lo, hi = BANDS[w][bn]
            s = (dsl >= lo) & (dsl < hi)
            s &= okp
            for k in KS:
                m = s & np.isfinite(fwd[k])
                if m.any():
                    p = pos[m].astype(np.int64)
                    np.add.at(sig_sum[(w, bn)][k], p, fwd[k][m])
                    np.add.at(sig_cnt[(w, bn)][k], p, 1)
            for k in np.where(s)[0]:
                dm = doms[k]
                if isinstance(dm, str):
                    dd = sig_dom[(w, bn)].setdefault(dm, 0)
                    sig_dom[(w, bn)][dm] = dd + 1
        # 基线（全部股票日）
        for k in KS:
            m = np.isfinite(fwd[k]) & okp
            np.add.at(base_sum[k], pos[m].astype(np.int64), fwd[k][m])
            np.add.at(base_cnt[k], pos[m].astype(np.int64), 1)
        done += 1
        if done % 800 == 0:
            print(f"  [es] {done} ({time.time()-t1:.0f}s)", flush=True)

    rows = []
    for (w, bn) in configs:
        for k in KS:
            sc = sig_cnt[(w, bn)][k].astype(float)
            bc = base_cnt[k].astype(float)
            sm = np.where(sc > 0, sig_sum[(w, bn)][k] / np.maximum(sc, 1), np.nan)
            bm = np.where(bc >= MIN_BASE, base_sum[k] / np.maximum(bc, 1), np.nan)
            edge = sm - bm
            okm = np.isfinite(edge) & (sc >= 5)
            if okm.sum() < 20:
                continue
            gross = float(np.nanmean(edge[okm])) * 100
            rows.append({"cfg": f"MA{w}_{bn}", "w": w, "band": bn, "k": k,
                         "n_signals": int(sc.sum()), "n_days": int(okm.sum()),
                         "gross_edge_pct": round(gross, 3),
                         "net115_pct": round(gross - COST_RT, 3),
                         "pos_fwd_rate_pct": round(float(np.mean(sm[okm] > 0) * 100), 1),
                         "edge_hit_rate_pct": round(float(np.mean(edge[okm] > 0) * 100), 1),
                         **{f"n_{dm}": int(sig_dom[(w, bn)].get(dm, 0))
                            for dm in ("bear", "weak", "strong")}})
    res = pd.DataFrame(rows).sort_values(["cfg", "k"])
    res.to_csv(R2 / "slope_accel_es_0912.csv", index=False, encoding="utf-8")
    print(res.to_string(index=False), flush=True)

    # 事件级最优带（任一 k 净115>0）
    best = res[res["net115_pct"] > 0].sort_values("net115_pct", ascending=False)
    print(f"\n[过闸带] {len(best)} 行：{best['cfg'].unique().tolist() if len(best) else '无'}", flush=True)
    json.dump({"quantiles": qs, "table": rows,
               "pass_bands": best["cfg"].unique().tolist() if len(best) else []},
              open(R2 / "slope_accel_es_0912.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"[done] {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
