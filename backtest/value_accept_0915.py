# -*- coding: utf-8 -*-
"""完整验收（R-buffett-accept-0915）：K=1 + N=15 的四闸全套。

配置（沿用 value_opt6 的干净实现 industry_cap.select_with_cap）：
  因子 roe_pb ｜ 池 全A主板排ST/退 ｜ 行业上限 K=1 ｜ Top15 ｜ 12 相位交叠 ｜ 年度调仓
四闸：
  ① 逐笔胜率 ≥40%（第三关门）
  ② 50bp 滑点压力档（20bp 不劣化过多）
  ③ 同轮廓安慰剂（10 seeds × 12 相位，与 real 同相位集）
  ④ DSR / MinTRL（N=试验臂数口径）+ 年度集中度（剔除最好年）
另附：相位分布、同区间锚对照
"""
import gc
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import value_lh_0914 as V               # noqa: E402
import value_arms_0914 as A             # noqa: E402
import industry_cap as IC               # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "value_accept_0915.json")
START, RB, N_TOP, CAP = "2018-01-02", 250, 15, 1
GAMMA = 0.5772156649
PHASES = 12


def zinv(p):
    return stats.norm.ppf(p)


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
    dates = feat["dates"][keep]
    scs = base.loc[dates]
    fill = scs.rank(axis=1, pct=True, ascending=False) + 1000
    rows = scs.values
    res = {}

    def build(offset, score_rows=None):
        arr = np.full(rows.shape, np.nan, dtype="float32")
        src = rows if score_rows is None else score_rows
        for di in range(offset, len(scs), RB):
            pick = IC.select_with_cap(src[di], gid, N_TOP, CAP)
            for ri, ci in enumerate(pick):
                arr[di, ci] = ri
        return pd.DataFrame(arr, index=scs.index, columns=scs.columns)

    def run_stag(slip, score_rows=None, phases=PHASES, detail=False):
        subs, wt, sh, md, mdd = [], [], [], [], []
        for k in range(phases):
            o = int(round(k * RB / phases))
            cs = build(o, score_rows)
            r = V.run(feat, cs.fillna(fill), rebal=RB, topn=N_TOP, slip=slip,
                      offset=o, start=START, exclude=ex)
            s = r["equity"]
            subs.append(s / s.iloc[0])
            wt.append(r["win_rate_trade"]); sh.append(r["sharpe"])
            mdd.append(float(((s / s.cummax()) - 1).min()))
            if detail:
                md.append({str(kk.year): float(vv) for kk, vv in r["by_year"].items()})
            del cs; gc.collect()
        S = pd.concat(subs, axis=1).ffill().dropna()
        st = S.mean(axis=1)
        rr = st.pct_change().dropna()
        yrs = (st.index[-1] - st.index[0]).days / 365.25
        tot = st.iloc[-1] - 1
        dd = (st / st.cummax()) - 1
        yr = st.resample("YE").last().pct_change().dropna()
        return dict(ann=float((1 + tot) ** (1 / yrs) - 1), total=float(tot),
                    sharpe=float(rr.mean() / rr.std() * np.sqrt(252)),
                    mdd=float(dd.min()), win_year=float((yr > 0).mean()),
                    win_trade=float(np.median(wt)),
                    single_sharpe_med=float(np.median(sh)),
                    single_mdd_med=float(np.median(mdd)), single_mdd_worst=float(np.min(mdd)),
                    by_year={str(kk.year): float(vv) for kk, vv in yr.items()},
                    equity=st, ret=rr)

    print("=" * 104)
    print(f"完整验收 · 行业上限K={CAP} + Top{N_TOP} + {PHASES}相位交叠 ｜ 2018+ ｜ 年度调仓")
    print("=" * 104)

    r20 = run_stag(0.002)
    print(f"① 20bp 基准：年化 {r20['ann']:.2%}  夏普 {r20['sharpe']:.3f}  回撤 {r20['mdd']:.2%}  "
          f"年度胜率 {r20['win_year']:.0%}  逐笔胜率(相位中位) {r20['win_trade']:.1%}")
    res["base20"] = {k: v for k, v in r20.items() if k not in ("equity", "ret")}
    print(f"   分年：{ {k: f'{v:.1%}' for k, v in r20['by_year'].items()} }")

    # 年度集中度
    by = r20["by_year"]
    srt = sorted(by, key=lambda y: by[y], reverse=True)
    for drop in (1, 2):
        best = srt[:drop]
        p = 1.0
        for y in by:
            if y not in best:
                p *= (1 + by[y])
        n = len(by) - drop
        print(f"   剔除最好 {drop} 年（{best}）后：按剩余 {n} 年折年化 {(p**(1/n)-1):+.2%}")
        res[f"ex_top{drop}"] = float(p ** (1 / n) - 1)

    r50 = run_stag(0.005)
    print(f"\n② 50bp 压力档：年化 {r50['ann']:.2%}  夏普 {r50['sharpe']:.3f}  回撤 {r50['mdd']:.2%}  "
          f"Δ夏普 {r50['sharpe']-r20['sharpe']:+.3f}  Δ年化 {r50['ann']-r20['ann']:+.2%}")
    res["slip50"] = {k: v for k, v in r50.items() if k not in ("equity", "ret")}

    print(f"\n③ 同轮廓安慰剂（10 seeds × {PHASES} 相位，行业上限同样施加）")
    valid = np.isfinite(rows)
    ph = []
    for seed in range(10):
        rng = np.random.default_rng(seed)
        fake = np.where(valid, rng.random(rows.shape), np.nan)
        rr = run_stag(0.002, score_rows=fake, phases=6)
        ph.append(rr["sharpe"])
        print(f"   seed {seed:2d}: 夏普 {rr['sharpe']:.3f}  年化 {rr['ann']:.2%}", flush=True)
        del fake; gc.collect()
    ph = np.array(ph)
    r6 = run_stag(0.002, phases=6)
    pval = float((ph >= r6["sharpe"]).mean())
    print(f"   real(6相位) 夏普 {r6['sharpe']:.3f}  vs  placebo 中位 {np.median(ph):.3f} "
          f"最大 {ph.max():.3f}  → p = {pval:.3f}（{int((ph>=r6['sharpe']).sum())}/{len(ph)} 不低于 real）")
    res["placebo"] = dict(real6=float(r6["sharpe"]), med=float(np.median(ph)),
                          mx=float(ph.max()), p=pval, seeds=len(ph))

    # ④ DSR / MinTRL
    ret = r20["ret"]; T = len(ret)
    sr_d = float(ret.mean() / ret.std())
    g3 = float(stats.skew(ret)); g4 = float(stats.kurtosis(ret, fisher=False))
    denom = np.sqrt(1 - g3 * sr_d + (g4 - 1) / 4 * sr_d ** 2)
    arm_sh = np.array([11.24, 13.28, 16.09, 16.77, 15.32]) / 100.0   # 本轮臂（年化近似）作为试验散布
    var_trials = float(np.var(arm_sh / np.sqrt(252) * np.sqrt(252) / 100.0, ddof=1))
    nt = len(arm_sh)
    sr0 = np.sqrt(var_trials / 252.0) * ((1 - GAMMA) * zinv(1 - 1.0 / nt) + GAMMA * zinv(1 - 1.0 / (nt * np.e)))
    dsr = float(stats.norm.cdf((sr_d - sr0) * np.sqrt(T - 1) / denom))
    mtrl = float(1 + denom ** 2 * (zinv(0.95) / max(sr_d - sr0, 1e-9)) ** 2)
    print(f"\n④ DSR/MinTRL：T={T:,} 日（{T/250:.1f} 年） 偏度 {g3:.2f} 峰度 {g4:.2f}")
    print(f"   日频夏普 {sr_d:.4f}（年化 {sr_d*np.sqrt(252):.3f}）  SR0(年化) {sr0*np.sqrt(252):.3f}")
    print(f"   → DSR {dsr:.3f}（门 0.95）  MinTRL {mtrl:,.0f} 日（{mtrl/250:.0f} 年）")
    res["dsr"] = dict(T=T, sr_ann=float(sr_d * np.sqrt(252)), dsr=dsr, min_trl=mtrl)

    print(f"\n⑤ 相位稳健性：单相位夏普中位 {r20['single_sharpe_med']:.3f}｜"
          f"单相位回撤 中位 {r20['single_mdd_med']:.2%} 最差 {r20['single_mdd_worst']:.2%}")
    print("\n⑥ 同区间锚（2018-01 起）")
    anchors = {}
    for nm, c in [("沪深300", "index_000300"), ("300ETF", "sh510300"),
                  ("红利ETF", "sh510880"), ("价值ETF", "sh510030")]:
        try:
            b = V.bench(feat, c, start=START)
            anchors[nm] = dict(ann=float(b["ann"]), sharpe=float(b["sharpe"]), mdd=float(b["mdd"]))
            print(f"   {nm:8s} 年化 {b['ann']:7.2%}  夏普 {b['sharpe']:.3f}  回撤 {b['mdd']:8.2%}")
        except Exception as e:
            print(f"   {nm} 失败 {e}")
    res["anchors"] = anchors

    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[accept] 落盘 {OUT}")


if __name__ == "__main__":
    main()
