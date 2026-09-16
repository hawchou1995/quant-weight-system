# -*- coding: utf-8 -*-
"""Pareto 对照 · B 配置分年（R-buffett-opt5b-0916，用户 2026-09-16 指定）：
B = F125 · P6 · K2 · N15（S1 真最优面上的夏普点）——补其分年与年度集中度；
同 F/P 的 K1 作参考基准（S1 K 扫描的对照行）；A（F250P12K1N15）的分年直接取 value_accept_0915.json。
口径与 S1 一致：roe_pb｜全A主板排ST/退｜Top15｜20bp｜2018+。
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
OUT = os.path.join(HERE, "value_opt9_bcase_0916.json")
START, SLIP, N_TOP = "2018-01-02", 0.002, 15


def main():
    np.seterr(all="ignore")
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
    dates = feat["dates"][keep]
    scs = base.loc[dates]
    fill = scs.rank(axis=1, pct=True, ascending=False) + 1000
    rows = scs.values

    def run(tag, rebal, phases, cap):
        subs, shs, mdds = [], [], []
        for k in range(phases):
            o = int(round(k * rebal / phases))
            arr = np.full(rows.shape, np.nan, dtype="float32")
            for di in range(o, len(scs), rebal):
                pick = IC.select_with_cap(rows[di], gid, N_TOP, cap)
                for ri, ci in enumerate(pick):
                    arr[di, ci] = ri
            cs = pd.DataFrame(arr, index=scs.index, columns=scs.columns)
            r = V.run(feat, cs.fillna(fill), rebal=rebal, topn=N_TOP, slip=SLIP,
                      offset=o, start=START, exclude=ex)
            s = r["equity"]
            subs.append(s / s.iloc[0])
            shs.append(r["sharpe"]); mdds.append(float(((s / s.cummax()) - 1).min()))
            del cs; gc.collect()
        S = pd.concat(subs, axis=1).ffill().dropna()
        st = S.mean(axis=1)
        rr = st.pct_change().dropna()
        yrs = (st.index[-1] - st.index[0]).days / 365.25
        tot = st.iloc[-1] / st.iloc[0] - 1
        yr = st.resample("YE").last().pct_change().dropna()
        by = {str(kk.year): float(vv) for kk, vv in yr.items()}
        srt = sorted(by, key=lambda y: by[y], reverse=True)
        exdrop = {}
        for drop in (1, 2):
            best = srt[:drop]
            p = 1.0
            for y in by:
                if y not in best:
                    p *= (1 + by[y])
            exdrop[f"ex_top{drop}"] = float(p ** (1 / (len(by) - drop)) - 1)
        rec = dict(tag=tag, ann=float((1 + tot) ** (1 / yrs) - 1),
                   sharpe=float(rr.mean() / rr.std() * np.sqrt(252)),
                   mdd=float(((st / st.cummax()) - 1).min()),
                   win_year=float((yr > 0).mean()),
                   single_sharpe_med=float(np.median(shs)),
                   single_mdd_med=float(np.median(mdds)), single_mdd_worst=float(np.min(mdds)),
                   by_year=by, **exdrop)
        print(f"{tag:22s} 年化 {rec['ann']:7.2%}  夏普 {rec['sharpe']:.3f}  回撤 {rec['mdd']:8.2%}  "
              f"剔顶1 {rec['ex_top1']:+.2%}  剔顶2 {rec['ex_top2']:+.2%}", flush=True)
        print(f"   分年: { {k: f'{v:+.1%}' for k, v in by.items()} }", flush=True)
        return rec

    print("=" * 100)
    print("Pareto 分年对照 · F125×P6（B 配置及其 K1 对照）｜2018+ / 20bp")
    print("=" * 100)
    res = {}
    res["K2_F125P6"] = run("B: K2 F125 P6 N15", 125, 6, 2)
    res["K1_F125P6"] = run("K1 F125 P6 N15（参照）", 125, 6, 1)

    # A（验收配置）分年：直接取 accept JSON
    try:
        acc = json.load(open(os.path.join(HERE, "value_accept_0915.json"), encoding="utf-8"))
        res["A_F250P12K1_accept"] = acc["base20"]
        print(f"{'A: F250P12K1（accept）':22s} 年化 {acc['base20']['ann']:7.2%}  夏普 {acc['base20']['sharpe']:.3f}  "
              f"回撤 {acc['base20']['mdd']:8.2%}  剔顶1 {acc['ex_top1']:+.2%}  剔顶2 {acc['ex_top2']:+.2%}")
        print(f"   分年: { {k: f'{v:+.1%}' for k, v in acc['base20']['by_year'].items()} }")
    except Exception as e:
        print("accept 读取失败:", e)

    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[opt9] 落盘 {OUT}")


if __name__ == "__main__":
    main()
