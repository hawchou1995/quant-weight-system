# -*- coding: utf-8 -*-
"""安慰剂扩样（R-buffett-placebo-0915）：把 p 值分辨率从 1/10 提升到 1/100。

背景：value_accept_0915 里 10 seeds 给出 p=0.100（placebo 最大 0.526 > real 0.520），
      分辨率太粗。本脚本按 --start-seed / --n-seeds 分块续跑，逐块追加到 JSON，
      最后用 --summary 汇总，避免单次调用超时。

口径（与 real 严格一致）：
  结构：行业上限 K=1 + 等权 Top15 + 年度调仓(H250) + 20bp + 排 ST/退
  相位：6 相位（与 real-6 参照一致，k*round(250/6)）
  零假设：在 real 的**合格集**内随机排序（同样施加 K=1 上限）
"""
import argparse
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
OUT = os.path.join(HERE, "value_placebo_0915.json")
START, RB, N_TOP, CAP, PHASES = "2018-01-02", 250, 15, 1, 6


def load_ctx():
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
    return feat, ex, gid, scs, fill


def run_stag(feat, ex, gid, scs, fill, slip=0.002, score_rows=None, phases=PHASES):
    rows = scs.values
    subs = []
    for k in range(phases):
        o = int(round(k * RB / phases))
        arr = np.full(rows.shape, np.nan, dtype="float32")
        src = rows if score_rows is None else score_rows
        for di in range(o, len(scs), RB):
            pick = IC.select_with_cap(src[di], gid, N_TOP, CAP)
            for ri, ci in enumerate(pick):
                arr[di, ci] = ri
        cs = pd.DataFrame(arr, index=scs.index, columns=scs.columns)
        r = V.run(feat, cs.fillna(fill), rebal=RB, topn=N_TOP, slip=slip,
                  offset=o, start=START, exclude=ex)
        s = r["equity"]
        subs.append(s / s.iloc[0])
        del cs, arr
        gc.collect()
    S = pd.concat(subs, axis=1).ffill().dropna()
    st = S.mean(axis=1)
    rr = st.pct_change().dropna()
    yrs = (st.index[-1] - st.index[0]).days / 365.25
    tot = st.iloc[-1] - 1
    return dict(sharpe=float(rr.mean() / rr.std() * np.sqrt(252)),
                ann=float((1 + tot) ** (1 / yrs) - 1),
                mdd=float(((st / st.cummax()) - 1).min()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-seed", type=int, default=0)
    ap.add_argument("--n-seeds", type=int, default=10)
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()

    store = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {"seeds": {}, "real6": None}
    feat, ex, gid, scs, fill = load_ctx()
    rows = scs.values
    valid = np.isfinite(rows)

    if a.summary:
        sh = np.array([v["sharpe"] for v in store["seeds"].values()])
        real = store["real6"]
        p = float((sh >= real).mean())
        print(f"real(6相位) = {real:.4f}")
        print(f"placebo n={len(sh)}: 中位 {np.median(sh):.4f}  P90 {np.quantile(sh,0.9):.4f}  "
              f"最大 {sh.max():.4f}  最小 {sh.min():.4f}")
        print(f"→ p = {p:.4f}（{int((sh>=real).sum())}/{len(sh)} 不低于 real）")
        store["summary"] = dict(n=len(sh), real=real, p=p, med=float(np.median(sh)),
                                p90=float(np.quantile(sh, 0.9)), mx=float(sh.max()))
        json.dump(store, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return

    if store["real6"] is None:
        r = run_stag(feat, ex, gid, scs, fill, phases=PHASES)
        store["real6"] = r["sharpe"]
        print(f"[real] 6 相位真实夏普 {r['sharpe']:.4f}  年化 {r['ann']:.2%}  回撤 {r['mdd']:.2%}", flush=True)

    for seed in range(a.start_seed, a.start_seed + a.n_seeds):
        if str(seed) in store["seeds"]:
            continue
        rng = np.random.default_rng(seed)
        fake = np.where(valid, rng.random(rows.shape), np.nan)
        r = run_stag(feat, ex, gid, scs, fill, score_rows=fake)
        store["seeds"][str(seed)] = r
        json.dump(store, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  seed {seed:3d}: 夏普 {r['sharpe']:.4f}  年化 {r['ann']:7.2%}  回撤 {r['mdd']:7.2%}", flush=True)
        del fake
        gc.collect()
    print(f"[done] 累计 {len(store['seeds'])} seeds，落盘 {OUT}")


if __name__ == "__main__":
    main()
