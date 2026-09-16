# -*- coding: utf-8 -*-
"""S1 机制精细分解（R-structure-S1-0915）：调仓周期 F × 交叠相位数 P × 行业上限 K 的真最优面。

动机：此前两个割裂测试结论冲突 ——
  · opt 轮 rebal 扫描（无 K=1）：125→0.646 / 250→0.583 / 500→0.401（半年最好）
  · structure 分解（K=1）：月度 0.177 / 年度 0.475（年度最好）
  ⇒ 说明 F 存在**内部最优**，不是"越低换手越好"。本脚本做真二维面把它钉死。

载体：真实因子 roe_pb（S2 已证明结构效应只对慢变量载体成立）
口径：全A主板排ST/退 ｜ Top15 ｜ 20bp ｜ 2018+ ｜ T+1 开盘
"""
import gc
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import value_lh_0914 as V               # noqa: E402
import value_arms_0914 as A             # noqa: E402
import industry_cap as IC               # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "value_s1_0915.json")
START, SLIP, N_TOP = "2018-01-02", 0.002, 15


def main():
    feat = V.load_features()
    if "_raw_close" not in feat:
        feat["_raw_close"] = V.raw_close(feat, validate=False)
    f = A.build_factors(feat, None)
    ex = V.st_mask(feat)
    cols = list(feat["close"].columns)
    ind = A.industry_of(feat)
    gid, _ = IC.encode_keys([ind.get(c) for c in cols])
    base = A.make_score(f["roe_pb"], None)
    keep = feat["dates"] >= pd.Timestamp(START)
    scs = base.loc[keep]
    fill = scs.rank(axis=1, pct=True, ascending=False) + 1000
    rows = scs.values

    def one(offset, rebal, cap):
        arr = np.full(rows.shape, np.nan, dtype="float32")
        for di in range(offset, len(scs), rebal):
            pick = IC.select_with_cap(rows[di], gid, N_TOP, cap)
            for ri, ci in enumerate(pick):
                arr[di, ci] = ri
        cs = pd.DataFrame(arr, index=scs.index, columns=scs.columns)
        r = V.run(feat, cs.fillna(fill), rebal=rebal, topn=N_TOP, slip=SLIP,
                  offset=offset, start=START, exclude=ex)
        del cs, arr; gc.collect()
        return r

    def score_cfg(rebal, phases, cap):
        sh, an, dd = [], [], []
        for k in range(phases):
            o = int(round(k * rebal / phases)) if phases > 1 else 0
            r = one(o, rebal, cap)
            sh.append(r["sharpe"]); an.append(r["ann"]); dd.append(r["mdd"])
        return dict(sharpe=float(np.median(sh)), ann=float(np.median(an)),
                    mdd=float(np.median(dd)), smin=float(np.min(sh)), smax=float(np.max(sh)),
                    phases=phases, rebal=rebal, cap=cap)

    res = {}
    print("=" * 104)
    print("S1 · 调仓周期 F × 交叠相位数 P 真二维面（行业上限 K=1，roe_pb，Top15，2018+）")
    print("=" * 104)
    print(f"{'F':>5s} | " + " | ".join(f"P={p:<2d} 夏普/年化" for p in (1, 6, 12, 24)))
    Fs = (21, 60, 125, 250)
    Ps = (1, 6, 12, 24)
    for F in Fs:
        line = f"{F:>5d} | "
        for P in Ps:
            r = score_cfg(F, P, 1)
            res[f"F{F}_P{P}_K1"] = r
            line += f"{r['sharpe']:.3f}/{r['ann']:6.2%} | "
        print(line, flush=True)

    best = max(res.values(), key=lambda r: r["sharpe"])
    print(f"\n  二维面最优：F={best['rebal']} P={best['phases']} → 夏普 {best['sharpe']:.3f} 年化 {best['ann']:.2%} 回撤 {best['mdd']:.2%}")
    print(f"  参照：现产口径 F=250 P=12 K=1 → 夏普 {res['F250_P12_K1']['sharpe']:.3f}")

    print("\n" + "=" * 104)
    print(f"行业上限 K 扫描（固定在最优 F={best['rebal']} P={best['phases']}）")
    print("=" * 104)
    for K in (1, 2, 3, 999):
        r = score_cfg(best["rebal"], best["phases"], K)
        res[f"K{K}_at_best"] = r
        tag = "∞（无上限）" if K == 999 else str(K)
        print(f"  K={tag:>8s}  夏普 {r['sharpe']:.3f}  年化 {r['ann']:7.2%}  回撤 {r['mdd']:8.2%}  "
              f"相位 {r['smin']:.2f}~{r['smax']:.2f}", flush=True)

    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[s1] 落盘 {OUT}")


if __name__ == "__main__":
    main()
