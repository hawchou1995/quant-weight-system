# -*- coding: utf-8 -*-
"""轨 II 验证块：①G3 跳过诊断 ②头部臂 50bp 压力档 ③同轮廓安慰剂。

预注册门（PRE-REGISTRATION_20260914_value_buffett.md §五）：
  L3 组合级（轨 II）：净值 vs 对照锚同口径 + 显著性 + **样本量与功效必须申报**
  安慰剂：把候选的「每日入选数轮廓」随机撒到当日合格股票上，同引擎跑 N seeds，
          real 不超过 placebo 上界即判假象（CONTEXT.md「同轮廓安慰剂」）。
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import value_lh_0914 as V           # noqa: E402
import value_arms_0914 as A         # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "value_verify_0914.json")


def main():
    feat = V.load_features()
    if "_raw_close" not in feat:
        feat["_raw_close"] = V.raw_close(feat, validate=False)
    f = A.build_factors(feat, None)
    ex = V.st_mask(feat)
    TOPN, REBAL, PHASES = 10, 250, 9

    print("=== ① G3 跳过诊断 ===")
    dv, dy = f["div_years"], f["dy"]
    m = A.gate(dv >= 4, dy > 0.01)
    cnt = m.sum(axis=1)
    print(f"  div_years 有效日数(>=30只): {(dv.notna().sum(axis=1)>=30).sum()}")
    print(f"  gate(div_years>=4 ∧ dy>1%) 每日合格数: 中位 {cnt.median():.0f} "
          f"最大 {cnt.max():.0f} 首次≥30 于 {cnt[cnt>=30].index[0].date() if (cnt>=30).any() else 'N/A'}")
    print(f"  放宽对照 gate(div_years>=3 ∧ dy>0.5%): "
          f"中位 {A.gate(dv>=3, dy>0.005).sum(axis=1).median():.0f}")
    print(f"  仅 div_years>=4: 中位 {(dv>=4).sum(axis=1).median():.0f}")
    print(f"  仅 dy>1%: 中位 {(dy>0.01).sum(axis=1).median():.0f}")

    res = {"g3_diag": {
        "gate_median": float(cnt.median()), "dy_median": float((dy > 0.01).sum(axis=1).median()),
        "dvy_median": float((dv >= 4).sum(axis=1).median())}}

    print("\n=== ② 头部臂 50bp 压力档（验收门：不劣化到不可接受） ===")
    heads = [("F_roe_pb", f["roe_pb"], None), ("F_dy", f["dy"], None),
             ("F_ep", f["ep"], None), ("G4_A5", f["roe_pb"], A.gate(f["gpm_rel"] > 0))]
    slip_tbl = {}
    for name, fac, mask in heads:
        sc = A.make_score(fac, mask)
        start = A.coverage_start(sc, TOPN * 3)
        row = {}
        for slip in (0.002, 0.005):
            r = A.run_arm(feat, sc, ex, rebal=REBAL, topn=TOPN, slip=slip,
                          phases=PHASES, start=start)
            row[f"{int(slip*10000)}bp"] = dict(phmed=r["sharpe_med"], ann=r["ann_med"],
                                               mn=r["sharpe_min"], mx=r["sharpe_max"])
        row["start"] = start
        slip_tbl[name] = row
        print(f"  {name:10s} {start}  20bp phmed {row['20bp']['phmed']:.3f} / "
              f"50bp phmed {row['50bp']['phmed']:.3f}  (Δ{row['50bp']['phmed']-row['20bp']['phmed']:+.3f})"
              f"  50bp 年化中位 {row['50bp']['ann']:.2%}")
    res["slip"] = slip_tbl

    print("\n=== ③ 同轮廓安慰剂（F_roe_pb，20 seeds × 9 相位，与 real 同相位集） ===")
    sc = A.make_score(f["roe_pb"], None)
    start = A.coverage_start(sc, TOPN * 3)
    real = A.run_arm(feat, sc, ex, rebal=REBAL, topn=TOPN, slip=0.002,
                     phases=PHASES, start=start)
    print(f"  real phmed S = {real['sharpe_med']:.3f}  年化中位 {real['ann_med']:.2%}")
    sv = sc.values.astype("float64")
    valid = np.isfinite(sv)
    ph = []
    for seed in range(20):
        r2 = np.random.default_rng(seed)
        noise = r2.random(sv.shape)
        fake = pd.DataFrame(np.where(valid, noise, np.nan), index=sc.index, columns=sc.columns)
        rr = A.run_arm(feat, fake, ex, rebal=REBAL, topn=TOPN, slip=0.002,
                       phases=PHASES, start=start)  # 相位集必须与 real 一致，否则中位数不可比
        ph.append(rr["sharpe_med"])
    ph = np.array(ph)
    pval = float((ph >= real["sharpe_med"]).mean())
    print(f"  placebo phmed S: 中位 {np.median(ph):.3f}  P90 {np.quantile(ph,0.9):.3f} "
          f"最大 {ph.max():.3f}")
    print(f"  → real 超过 placebo 上界的比例: p = {pval:.3f} "
          f"（{int((ph>=real['sharpe_med']).sum())}/{len(ph)} 个 placebo 不低于 real）")
    res["placebo"] = dict(real=float(real["sharpe_med"]), real_ann=float(real["ann_med"]),
                          placebo_median=float(np.median(ph)), placebo_p90=float(np.quantile(ph, 0.9)),
                          placebo_max=float(ph.max()), p_value=pval, seeds=len(ph))

    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[verify] 落盘 {OUT}")


if __name__ == "__main__":
    main()
