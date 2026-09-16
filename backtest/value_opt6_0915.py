# -*- coding: utf-8 -*-
"""用已验证的 industry_cap 纯函数重跑 N2（行业上限）——地基修复后的真值。

对照目的：老脚本 value_opt4/opt5 出现"两条等价路径不同结果"（16.09%/−35.74%
vs 15.32%/−42.29%）。本脚本用单测通过的纯函数重算，并显式验证**两条 key 构造
路径结果逐位一致**（若一致 → 老差异来自集成层，非算法）。
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
OUT = os.path.join(HERE, "value_opt6_0915.json")
START, RB, SLIP = "2018-01-02", 250, 0.002
FIN = {"银行", "非银金融", "房地产"}


def main():
    feat = V.load_features()
    if "_raw_close" not in feat:
        feat["_raw_close"] = V.raw_close(feat, validate=False)
    f = A.build_factors(feat, None)
    ex = V.st_mask(feat)
    cols = list(feat["close"].columns)
    ind = A.industry_of(feat)
    base = A.make_score(f["roe_pb"], None)
    keep = feat["dates"] >= pd.Timestamp(START)
    dates = feat["dates"][keep]
    scs = base.loc[dates]
    fill = scs.rank(axis=1, pct=True, ascending=False) + 1000

    # 行业编码（路径A：原始行业名；路径B：带前缀）—— 用于交叉验证一致性
    gidA, _ = IC.encode_keys([ind.get(c) for c in cols])
    gidB, _ = IC.encode_keys([f"IND:{ind.get(c)}" for c in cols])
    fin_mask = np.array([ind.get(c) in FIN for c in cols], dtype=bool)

    def build(offset, topn, cap, gid, avoid_fin=False, excl=None):
        arr = np.full(scs.values.shape, np.nan, dtype="float32")
        rows = scs.values
        for di in range(offset, len(scs), RB):
            row = rows[di].copy()
            if avoid_fin:
                row = np.where(fin_mask, np.nan, row)
            if excl is not None:
                row = np.where(excl[di], np.nan, row)
            pick = IC.select_with_cap(row, gid, topn, cap)
            for ri, ci in enumerate(pick):
                arr[di, ci] = ri
        return pd.DataFrame(arr, index=scs.index, columns=scs.columns)

    def stag(tag, **kw):
        subs = []
        for k in range(12):
            o = k * 20
            cs = build(o, **kw)
            r = V.run(feat, cs.fillna(fill), rebal=RB, topn=kw.get("topn", 10),
                      slip=SLIP, offset=o, start=START, exclude=ex)
            s = r["equity"]
            subs.append(s / s.iloc[0])
            del cs
        S = pd.concat(subs, axis=1).ffill().dropna()
        st = S.mean(axis=1)
        rr = st.pct_change().dropna()
        yrs = (st.index[-1] - st.index[0]).days / 365.25
        tot = st.iloc[-1] - 1
        dd = (st / st.cummax()) - 1
        yr = st.resample("YE").last().pct_change().dropna()
        rec = dict(tag=tag, ann=float((1 + tot) ** (1 / yrs) - 1),
                   sharpe=float(rr.mean() / rr.std() * np.sqrt(252)),
                   mdd=float(dd.min()), win_year=float((yr > 0).mean()),
                   trough=str(dd.idxmin().date()))
        gc.collect()
        return rec

    print("=" * 104)
    print("地基修复后重跑 · 12 相位交叠（k*20）｜2018+ / 20bp")
    print("=" * 104)
    res = {}

    # ① 交叉验证：两条 key 路径必须逐位一致
    a = build(0, 10, 1, gidA); b = build(0, 10, 1, gidB)
    same = np.array_equal(a.notna().values, b.notna().values)
    print(f"  ① 交叉验证（行业名 vs 带前缀）选择集逐位一致：{'PASS' if same else 'FAIL'}")
    res["cross_check"] = bool(same)
    del a, b; gc.collect()

    for tag, kw in [
        ("A0 K=1 N=10（基线）", dict(topn=10, cap=1, gid=gidA)),
        ("A1 K=1 N=15", dict(topn=15, cap=1, gid=gidA)),
        ("A2 K=1 N=20", dict(topn=20, cap=1, gid=gidA)),
        ("A3 K=1 N=10 + 剔金融地产", dict(topn=10, cap=1, gid=gidA, avoid_fin=True)),
    ]:
        r = stag(tag, **kw)
        res[tag] = r
        print(f"  {tag:26s} 年化 {r['ann']:7.2%}  夏普 {r['sharpe']:.3f}  "
              f"回撤 {r['mdd']:8.2%}  年度胜率 {r['win_year']:4.0%}  谷 {r['trough']}", flush=True)

    # ② 无上限对照（K→∞ 等价于纯 roe_pb 排序），验证上限确实在起作用
    r = stag("对照：无行业上限(cap=999)", topn=10, cap=999, gid=gidA)
    res["无上限对照"] = r
    print(f"  {'对照：无行业上限(cap=999)':26s} 年化 {r['ann']:7.2%}  夏普 {r['sharpe']:.3f}  "
          f"回撤 {r['mdd']:8.2%}  年度胜率 {r['win_year']:4.0%}  谷 {r['trough']}", flush=True)

    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[opt6] 落盘 {OUT}")


if __name__ == "__main__":
    main()
