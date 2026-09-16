# -*- coding: utf-8 -*-
"""优化挖掘第二轮：①N×rebal 交互 ②双冠军合并 ③市场闸门（沪深300 vs MA200）。"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import value_lh_0914 as V           # noqa: E402
import value_arms_0914 as A         # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "value_opt2_0914.json")
PHASES = 9


def phase_stats(feat, sc, ex, rebal, topn, slip, start):
    rows = []
    for p in range(PHASES):
        off = int(round(p * rebal / PHASES))
        r = V.run(feat, sc, rebal=rebal, topn=topn, slip=slip, offset=off,
                  start=start, exclude=ex)
        rows.append(dict(offset=off, ann=r["ann"], sharpe=r["sharpe"], mdd=r["mdd"],
                         win_trade=r["win_rate_trade"], total=r["total"]))
    df = pd.DataFrame(rows)
    return dict(sharpe_med=float(df.sharpe.median()), ann_med=float(df.ann.median()),
                mdd_med=float(df.mdd.median()), win_med=float(df.win_trade.median()),
                sharpe_min=float(df.sharpe.min()), sharpe_max=float(df.sharpe.max()),
                phases=rows)


def main():
    feat = V.load_features()
    if "_raw_close" not in feat:
        feat["_raw_close"] = V.raw_close(feat, validate=False)
    f = A.build_factors(feat, None)
    ex = V.st_mask(feat)
    res = {}
    sc_pb = A.make_score(f["roe_pb"], None)
    start = A.coverage_start(sc_pb, 30)

    print("=" * 92)
    print("① N × rebal 交互（F_roe_pb，20bp）")
    print("=" * 92)
    print(f"{'N':>4s} {'rebal':>6s} {'phmed S':>8s} {'年化中位':>9s} {'回撤中位':>9s} {'逐笔胜率':>9s}  {'相位下界':>8s}")
    grid = {}
    for N in (5, 10, 20):
        for rb in (125, 250):
            st = phase_stats(feat, sc_pb, ex, rb, N, 0.002, start)
            grid[f"N{N}_R{rb}"] = st
            print(f"{N:>4d} {rb:>6d} {st['sharpe_med']:>8.3f} {st['ann_med']:>8.2%} "
                  f"{st['mdd_med']:>8.2%} {st['win_med']:>8.2%}  {st['sharpe_min']:>8.3f}")
    res["interaction"] = grid

    print("\n" + "=" * 92)
    print("② 双冠军合并（F_roe_pb Top10 年度 与 G3_E4 Top10 年度，各半仓）")
    print("=" * 92)
    sc_e4 = A.make_score(f["dy"], A.gate(f["div_years"] >= 4, f["dy"] > 0.01))
    s_e4 = A.coverage_start(sc_e4, 30)
    r1 = V.run(feat, sc_pb, rebal=250, topn=10, slip=0.002, offset=0, start=start, exclude=ex)
    r2 = V.run(feat, sc_e4, rebal=250, topn=10, slip=0.002, offset=0, start=s_e4, exclude=ex)
    common = r1["equity"].index.intersection(r2["equity"].index)
    e1 = r1["equity"].reindex(common).ffill()
    e2 = r2["equity"].reindex(common).ffill()
    n1, n2 = e1 / e1.iloc[0], e2 / e2.iloc[0]
    corr = n1.pct_change().corr(n2.pct_change())
    comb = 0.5 * n1 + 0.5 * n2
    ret = comb.pct_change().dropna()
    yrs = (common[-1] - common[0]).days / 365.25
    tot = comb.iloc[-1] - 1
    mdd = ((comb / comb.cummax()) - 1).min()
    sh = ret.mean() / ret.std() * np.sqrt(252)
    print(f"  窗口交集 {common[0].date()}~{common[-1].date()}（{yrs:.1f} 年）")
    print(f"  ρ(日收益) = {corr:.3f}")
    print(f"  冠军单跑：年化 {r1['ann']:.2%} 夏普 {r1['sharpe']:.3f} 回撤 {r1['mdd']:.2%}")
    print(f"  亚军单跑：年化 {r2['ann']:.2%} 夏普 {r2['sharpe']:.3f} 回撤 {r2['mdd']:.2%}")
    print(f"  等权合并：年化 {((1+tot)**(1/yrs)-1):.2%} 夏普 {sh:.3f} 回撤 {mdd:.2%}")
    res["combo"] = dict(rho=float(corr), ann=float((1 + tot) ** (1 / yrs) - 1), sharpe=float(sh),
                        mdd=float(mdd), years=float(yrs),
                        a1=dict(ann=r1["ann"], sharpe=r1["sharpe"], mdd=r1["mdd"]),
                        a2=dict(ann=r2["ann"], sharpe=r2["sharpe"], mdd=r2["mdd"]))

    print("\n" + "=" * 92)
    print("③ 市场闸门（沪深300 收盘 < MA200 → 空仓；F_roe_pb Top10 年度）")
    print("=" * 92)
    hs = pd.read_csv(os.path.join(V.ROOT, "index_000300.csv"), dtype={"date": str})
    hs["date"] = pd.to_datetime(hs["date"])
    hs = hs.set_index("date")["close"].astype(float).sort_index()
    ma = hs.rolling(200).mean()
    off_mask = (hs < ma)                      # True = 闸门关闭
    off_daily = off_mask.reindex(feat["dates"]).ffill().fillna(False).values
    gmask = pd.DataFrame(np.repeat(off_daily[:, None], feat["close"].shape[1], axis=1),
                         index=feat["dates"], columns=feat["close"].columns)
    ex_gate = ex | gmask
    st_off = phase_stats(feat, sc_pb, ex, 250, 10, 0.002, start)
    st_on = phase_stats(feat, sc_pb, ex_gate, 250, 10, 0.002, start)
    print(f"  无闸门 ：phmed S {st_off['sharpe_med']:.3f}  年化中位 {st_off['ann_med']:.2%}  "
          f"回撤中位 {st_off['mdd_med']:.2%}  下界 {st_off['sharpe_min']:.3f}")
    print(f"  挂闸门 ：phmed S {st_on['sharpe_med']:.3f}  年化中位 {st_on['ann_med']:.2%}  "
          f"回撤中位 {st_on['mdd_med']:.2%}  下界 {st_on['sharpe_min']:.3f}")
    print(f"  Δ：S {st_on['sharpe_med']-st_off['sharpe_med']:+.3f}  "
          f"年化 {st_on['ann_med']-st_off['ann_med']:+.2%}  回撤 {st_on['mdd_med']-st_off['mdd_med']:+.2%}")
    res["gate"] = dict(off=st_off, on=st_on)

    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[opt2] 落盘 {OUT}")


if __name__ == "__main__":
    main()
