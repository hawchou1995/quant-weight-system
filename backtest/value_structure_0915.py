# -*- coding: utf-8 -*-
"""结构效应独立课题（R-structure-0915）：用随机选股做纯基线，分解三个机制。

动机：40 seeds 安慰剂显示——在「行业上限K=1 + 等权Top15 + 年度调仓 + 12相位交叠」结构里，
      **随机选股也有中位夏普 0.474**。说明收益里有一块来自"结构"而非"因子"。
      本脚本把这套结构拆开，逐个打开，量化每个机制的独立贡献。

机制：①行业上限 K=1（分散）②12 相位交叠（相位平滑）③年度轮动（低换手）
基线：随机选股（同一合格集、同一 Top15、同一成本与执行口径）
对照：真实因子 roe_pb（同结构）
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
OUT = os.path.join(HERE, "value_structure_0915.json")
START, SLIP = "2018-01-02", 0.002
N_TOP = 15
SEEDS = 5


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
    valid = np.isfinite(rows)

    def one(score_rows, offset, rebal, cap, slip=SLIP):
        arr = np.full(rows.shape, np.nan, dtype="float32")
        for di in range(offset, len(scs), rebal):
            pick = IC.select_with_cap(score_rows[di], gid, N_TOP, cap)
            for ri, ci in enumerate(pick):
                arr[di, ci] = ri
        cs = pd.DataFrame(arr, index=scs.index, columns=scs.columns)
        r = V.run(feat, cs.fillna(fill), rebal=rebal, topn=N_TOP, slip=slip,
                  offset=offset, start=START, exclude=ex)
        del cs, arr; gc.collect()
        return r

    def agg(score_rows, phases, rebal, cap):
        subs = []
        for k in range(phases):
            o = int(round(k * rebal / phases))
            r = one(score_rows, o, rebal, cap)
            s = r["equity"]; subs.append(s / s.iloc[0])
        S = pd.concat(subs, axis=1).ffill().dropna()
        st = S.mean(axis=1)
        rr = st.pct_change().dropna()
        yrs = (st.index[-1] - st.index[0]).days / 365.25
        tot = st.iloc[-1] - 1
        return dict(ann=float((1 + tot) ** (1 / yrs) - 1),
                    sharpe=float(rr.mean() / rr.std() * np.sqrt(252)),
                    mdd=float(((st / st.cummax()) - 1).min()),
                    vol=float(rr.std() * np.sqrt(252)))

    print("=" * 108)
    print(f"结构机制分解 · 随机选股基线 × {SEEDS} seeds ｜ Top{N_TOP} ｜ 2018+ ｜ 20bp")
    print("=" * 108)
    res = {}

    configs = [
        ("① 裸基线（无K=1/单相位/年度）", dict(phases=1, rebal=250, cap=999)),
        ("② +行业上限 K=1",              dict(phases=1, rebal=250, cap=1)),
        ("③ +12相位交叠（无K=1）",        dict(phases=12, rebal=250, cap=999)),
        ("④ +K=1 +交叠（全结构）",        dict(phases=12, rebal=250, cap=1)),
        ("⑤ +K=1 +交叠 +月度调仓",        dict(phases=12, rebal=21, cap=1)),
    ]
    for tag, kw in configs:
        accs = []
        for seed in range(SEEDS):
            rng = np.random.default_rng(seed)
            fake = np.where(valid, rng.random(rows.shape), np.nan)
            accs.append(agg(fake, **kw))
            del fake; gc.collect()
        m = {k: float(np.median([a[k] for a in accs])) for k in ("ann", "sharpe", "mdd", "vol")}
        res[tag] = dict(median=m, all=accs)
        print(f"  {tag:30s} 夏普 {m['sharpe']:.3f}  年化 {m['ann']:7.2%}  "
              f"回撤 {m['mdd']:7.2%}  波动 {m['vol']:6.2%}", flush=True)

    real = agg(rows, phases=12, rebal=250, cap=1)
    res["real 因子 roe_pb（同结构）"] = dict(median=real, all=[real])
    print(f"\n  对照 {['real 因子 roe_pb（同结构）'][0]:30s} 夏普 {real['sharpe']:.3f}  年化 {real['ann']:7.2%}  "
          f"回撤 {real['mdd']:7.2%}  波动 {real['vol']:6.2%}")

    base_m = res["① 裸基线（无K=1/单相位/年度）"]["median"]
    full_m = res["④ +K=1 +交叠（全结构）"]["median"]
    k1_m = res["② +行业上限 K=1"]["median"]
    st_m = res["③ +12相位交叠（无K=1）"]["median"]
    print("\n" + "=" * 108)
    print("机制增量分解（随机基线，夏普）")
    print("=" * 108)
    print(f"  裸基线            {base_m['sharpe']:.3f}")
    print(f"  +行业上限 K=1     {k1_m['sharpe']:.3f}   → 机制① 贡献 {k1_m['sharpe']-base_m['sharpe']:+.3f}")
    print(f"  +12相位交叠       {st_m['sharpe']:.3f}   → 机制② 贡献 {st_m['sharpe']-base_m['sharpe']:+.3f}")
    print(f"  +全结构           {full_m['sharpe']:.3f}   → ①+② 合计 {full_m['sharpe']-base_m['sharpe']:+.3f}"
          f"（可加性检验：单加和 {k1_m['sharpe']-base_m['sharpe']+st_m['sharpe']-base_m['sharpe']:+.3f}）")
    print(f"  +月度调仓换年度   → 机制③（低换手）贡献 {full_m['sharpe']-res['⑤ +K=1 +交叠 +月度调仓']['median']['sharpe']:+.3f}")
    print(f"\n  因子增量（同全结构）= real {real['sharpe']:.3f} − 随机 {full_m['sharpe']:.3f} = {real['sharpe']-full_m['sharpe']:+.3f}")

    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[structure] 落盘 {OUT}")


if __name__ == "__main__":
    main()
