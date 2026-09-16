# -*- coding: utf-8 -*-
"""扩窗评估（2018+，官方口径 PB）：核心臂 × 三关门 × DSR 重算。

背景：fetch_val_em_pre2021.py 把东财官方估值从 2021+ 扩到 2018-01-02（2,875 票 / 197 万行）。
      本脚本回答：扩窗后冠军还成立吗？三关门还过吗？DSR 改善多少？
"""
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import value_lh_0914 as V           # noqa: E402
import value_arms_0914 as A         # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "value_ext_0914.json")
GAMMA = 0.5772156649


def zinv(p):
    return stats.norm.ppf(p)


def main():
    feat = V.load_features()
    if "_raw_close" not in feat:
        feat["_raw_close"] = V.raw_close(feat, validate=False)
    f = A.build_factors(feat, None)
    ex = V.st_mask(feat)

    arms = [("F_roe_pb", "roe_pb", None), ("F_ep", "ep", None), ("F_bp", "bp", None),
            ("G4_A5", "roe_pb", lambda: A.gate(f["gpm_rel"] > 0)),
            ("G3_E4", "dy", lambda: A.gate(f["div_years"] >= 4, f["dy"] > 0.01))]
    res = {"arms": {}, "gates": {}, "dsr": {}}
    print("=" * 104)
    print("扩窗后（官方口径 PB，2018-01 起）—— Top10 / rebal250 / 20bp")
    print("=" * 104)
    print(f"{'臂':10s} {'起点':11s} {'年数':>5s} {'phmed S':>8s} {'S区间':>13s} {'年化中位':>9s} "
          f"{'回撤中位':>9s} {'年度胜率':>8s} {'逐笔胜率':>8s}")
    for tag, key, mk in arms:
        fac = f[key]
        mask = mk() if mk else None
        sc = A.make_score(fac, mask)
        s0 = A.coverage_start(sc, 30)
        if s0 is None:
            print(f"{tag:10s} 有效值不足")
            continue
        rows = []
        for p in range(9):
            r = V.run(feat, sc, rebal=250, topn=10, slip=0.002,
                      offset=int(round(p * 250 / 9)), start=s0, exclude=ex)
            rows.append([r["sharpe"], r["ann"], r["mdd"], r["win_rate_trade"],
                         r["win_rate_year"], r["years"]])
        d = np.array(rows)
        m = np.median(d, axis=0)
        res["arms"][tag] = dict(start=s0, years=float(m[5]), sharpe_med=float(m[0]),
                                sharpe_min=float(d[:, 0].min()), sharpe_max=float(d[:, 0].max()),
                                ann_med=float(m[1]), mdd_med=float(m[2]),
                                win_trade_med=float(m[3]), win_year_med=float(m[4]))
        print(f"{tag:10s} {s0:11s} {m[5]:5.1f} {m[0]:8.3f} {d[:,0].min():6.2f}~{d[:,0].max():5.2f} "
              f"{m[1]:8.2%} {m[2]:8.2%} {m[4]:8.0%} {m[3]:8.1%}")

    print("\n" + "=" * 104)
    print("三关门判定（回撤 ≤35% / 年度胜率 ≥2/3 / 逐笔胜率 ≥40%）")
    print("=" * 104)
    sc = A.make_score(f["roe_pb"], None)
    s0 = A.coverage_start(sc, 30)
    for N, RB in [(10, 250), (20, 125)]:
        rows = []
        for p in range(9):
            r = V.run(feat, sc, rebal=RB, topn=N, slip=0.002,
                      offset=int(round(p * RB / 9)), start=s0, exclude=ex)
            rows.append([r["sharpe"], r["ann"], r["mdd"], r["win_rate_trade"], r["win_rate_year"]])
        m = np.median(np.array(rows), axis=0)
        g = ["PASS" if m[2] >= -0.35 else "FAIL", "PASS" if m[4] >= 2 / 3 else "FAIL",
             "PASS" if m[3] >= 0.40 else "FAIL"]
        res["gates"][f"N{N}_R{RB}"] = dict(sharpe=float(m[0]), ann=float(m[1]), mdd=float(m[2]),
                                           win_trade=float(m[3]), win_year=float(m[4]),
                                           g_mdd=g[0], g_year=g[1], g_trade=g[2])
        print(f"  N={N:2d} R={RB:3d}: 夏普 {m[0]:.3f} 年化 {m[1]:7.2%} 回撤 {m[2]:7.2%}[{g[0]}] "
              f"年度胜率 {m[4]:.0%}[{g[1]}] 逐笔胜率 {m[3]:.1%}[{g[2]}]  → "
              f"{'三关全过' if g == ['PASS']*3 else '未全过'}")

    # DSR 重算（扩窗后样本更长）
    r = V.run(feat, sc, rebal=125, topn=20, slip=0.002, offset=0, start=s0, exclude=ex)
    ret = r["equity"].pct_change().dropna()
    T = len(ret)
    g3 = float(stats.skew(ret))
    g4 = float(stats.kurtosis(ret, fisher=False))
    sr_d = float(ret.mean() / ret.std())
    denom = np.sqrt(1 - g3 * sr_d + (g4 - 1) / 4 * sr_d ** 2)
    arm_sh = np.array([v["sharpe_med"] for v in res["arms"].values()])
    var_arm = float(np.var(arm_sh, ddof=1))
    Ntr = len(arm_sh)
    sr0_d = np.sqrt(var_arm / 252.0) * ((1 - GAMMA) * zinv(1 - 1.0 / Ntr) + GAMMA * zinv(1 - 1.0 / (Ntr * np.e)))
    dsr = float(stats.norm.cdf((sr_d - sr0_d) * np.sqrt(T - 1) / denom))
    mtrl = float(1 + denom ** 2 * (zinv(0.95) / max(sr_d - sr0_d, 1e-9)) ** 2)
    res["dsr"] = dict(T=T, years=T / 250, skew=g3, kurt=g4, sr_daily=sr_d, sr_ann=sr_d * np.sqrt(252),
                      sr0_ann=float(sr0_d * np.sqrt(252)), dsr=dsr, min_trl=mtrl, n_trials=Ntr)
    print("\n" + "=" * 104)
    print("DSR 重算（扩窗后；N=试验臂数口径）")
    print("=" * 104)
    print(f"  样本 T = {T:,} 交易日（{T/250:.1f} 年）  偏度 {g3:.2f}  峰度 {g4:.2f}")
    print(f"  日频 Sharpe {sr_d:.4f}（年化 {sr_d*np.sqrt(252):.3f}）  SR0 {sr0_d:.4f}（年化 {sr0_d*np.sqrt(252):.3f}）")
    print(f"  → DSR = {dsr:.3f}    MinTRL = {mtrl:,.0f} 日（{mtrl/250:.0f} 年）")
    print(f"  对比扩窗前：T=1,381 日 / DSR 0.740 / MinTRL 9,063 日")

    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[ext] 落盘 {OUT}")


if __name__ == "__main__":
    main()
