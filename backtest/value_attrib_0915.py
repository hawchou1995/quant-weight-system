# -*- coding: utf-8 -*-
"""回撤归因 + 交叠调仓实测（回应三份外部方案）。

① 归因（DeepSeek 主张"没归因就是盲调"——正确，本轮补上）：
   行业分布 / 风格暴露 / 年度集中度分解 / 最大回撤期间成分
② 交叠调仓实测（Gemini 主张"12 相位交叠可把 DSR 推到 >0.95、MinTRL <8 年"）：
   跑 12 个相隔 ~21 交易日的子组合，等权合成 → 实测回撤变化与 DSR 变化
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
OUT = os.path.join(HERE, "value_attrib_0915.json")
GAMMA = 0.5772156649


def zinv(p):
    return stats.norm.ppf(p)


def dsr_of(eq, var_trials, n_trials):
    ret = eq.pct_change().dropna()
    T = len(ret)
    sr_d = float(ret.mean() / ret.std())
    g3 = float(stats.skew(ret)); g4 = float(stats.kurtosis(ret, fisher=False))
    denom = np.sqrt(1 - g3 * sr_d + (g4 - 1) / 4 * sr_d ** 2)
    sr0 = np.sqrt(var_trials / 252.0) * ((1 - GAMMA) * zinv(1 - 1.0 / n_trials)
                                         + GAMMA * zinv(1 - 1.0 / (n_trials * np.e)))
    return dict(T=T, sr_ann=sr_d * np.sqrt(252), dsr=float(stats.norm.cdf(
        (sr_d - sr0) * np.sqrt(T - 1) / denom)),
        min_trl=float(1 + denom ** 2 * (zinv(0.95) / max(sr_d - sr0, 1e-9)) ** 2))


def main():
    feat = V.load_features()
    if "_raw_close" not in feat:
        feat["_raw_close"] = V.raw_close(feat, validate=False)
    f = A.build_factors(feat, None)
    ex = V.st_mask(feat)
    sc = A.make_score(f["roe_pb"], None)
    START, N, RB = "2018-01-02", 10, 250
    res = {}

    # ============ ① 归因 ============
    print("=" * 100)
    print("① 回撤归因（冠军 F_roe_pb，Top10 年度，2018+）")
    print("=" * 100)
    ind = A.industry_of(feat)
    # 逐调仓期收集持仓
    dates_all = feat["dates"]
    keep = (dates_all >= pd.Timestamp(START))
    dates = dates_all[keep]
    scv = sc.reindex(index=dates, columns=feat["close"].columns)
    live = feat["close"].loc[dates].notna()
    scv = scv.where(live)
    reb = list(range(0, len(dates), RB))
    holds = []
    for di in reb:
        row = scv.values[di]
        ok = np.isfinite(row)
        if ok.sum() < N:
            continue
        idx = np.argsort(np.where(ok, row, np.inf))[:N]
        codes = [feat["close"].columns[i] for i in idx]
        holds.append((dates[di], codes))

    all_codes = [c for _, cs in holds for c in cs]
    ind_cnt = pd.Series([ind.get(c, "未知") for c in all_codes]).value_counts()
    tot = ind_cnt.sum()
    print(f"\n  持仓期数 {len(holds)}｜共 {tot} 个持仓位次｜行业分布 Top10：")
    for k, v in ind_cnt.head(10).items():
        print(f"    {k:12s} {v:4d} 位次  {v/tot:6.2%}")
    res["industry"] = {k: int(v) for k, v in ind_cnt.head(15).items()}
    res["n_positions"] = int(tot)

    # 风格暴露：持仓 vs 全市场的 市值/波动率/近1年涨幅
    mv = feat["total_mv"].reindex(index=dates).ffill() if "total_mv" in feat else None
    if mv is not None:
        mv = mv.where(live)
        hold_mv, all_mv = [], []
        for d, cs in holds:
            if d not in mv.index:
                continue
            r = mv.loc[d]
            hold_mv += [r.get(c) for c in cs if np.isfinite(r.get(c, np.nan))]
            all_mv += r.dropna().tolist()
        if hold_mv and all_mv:
            print(f"\n  市值(亿元) 中位：持仓 {np.median(hold_mv)/1e8:8.1f}  vs  全池 {np.median(all_mv)/1e8:8.1f}"
                  f"  → 倍数 {np.median(hold_mv)/np.median(all_mv):.2f}×")
            res["mktcap"] = dict(hold_med=float(np.median(hold_mv)), pool_med=float(np.median(all_mv)))

    # 年度集中度：剔除最好年份后的年化
    r0 = V.run(feat, sc, rebal=RB, topn=N, slip=0.002, offset=0, start=START, exclude=ex)
    by = r0["by_year"]
    print(f"\n  分年：{ {str(k.year): f'{v:.1%}' for k, v in by.items()} }")
    top2 = by.abs().nlargest(2)
    pos = by[by > 0].nlargest(2)
    keep_years = [y for y in by.index if y not in pos.index]
    eq = r0["equity"]
    sub = eq[(eq.index.year.isin([y.year for y in keep_years]))]
    if len(sub) > 2:
        yrs = (sub.index[-1] - sub.index[0]).days / 365.25
        tot_sub = sub.iloc[-1] / sub.iloc[0] - 1
        print(f"  剔除最好的两年（{[str(y.year) for y in pos.index]}）后："
              f"区间年化 {(1+tot_sub)**(1/yrs)-1:.2%}（原 {r0['ann']:.2%}）")
        res["ex_top2_years"] = dict(ann=float((1 + tot_sub) ** (1 / yrs) - 1), years=float(yrs))
    # 最大回撤期
    dd = (eq / eq.cummax()) - 1
    trough = dd.idxmin()
    peak = eq.loc[:trough].idxmax()
    print(f"  最大回撤 {dd.min():.2%}：峰 {peak.date()} → 谷 {trough.date()}（{(trough-peak).days} 天）")
    res["mdd_window"] = dict(peak=str(peak.date()), trough=str(trough.date()), mdd=float(dd.min()))
    # 该期间的对照
    for nm, c in [("沪深300", "index_000300"), ("红利ETF", "sh510880")]:
        try:
            b = V.bench(feat, c, start=str(peak.date()), end=str(trough.date()))
            print(f"    同期 {nm}: {b['total']:.2%}")
            res.setdefault("mdd_bench", {})[nm] = float(b["total"])
        except Exception:
            pass

    # ============ ② 交叠调仓实测 ============
    print("\n" + "=" * 100)
    print("② 交叠调仓实测（12 子组合 × 相隔 ~21 交易日，等权合成）——验证 Gemini 的 DSR 论断")
    print("=" * 100)
    step = max(1, RB // 12)
    subs, sub_sh = [], []
    for k in range(12):
        r = V.run(feat, sc, rebal=RB, topn=N, slip=0.002, offset=k * step, start=START, exclude=ex)
        s = r["equity"]; s = s / s.iloc[0]
        subs.append(s)
        sub_sh.append(r["sharpe"])
    S = pd.concat(subs, axis=1).ffill().dropna()
    stag = S.mean(axis=1)
    res_single = V.run(feat, sc, rebal=RB, topn=N, slip=0.002, offset=0, start=START, exclude=ex)["equity"]
    res_single = res_single / res_single.iloc[0]
    common = stag.index.intersection(res_single.index)
    stag, res_single = stag.reindex(common), res_single.reindex(common)

    def stat(s, tag):
        ret = s.pct_change().dropna()
        years = (s.index[-1] - s.index[0]).days / 365.25
        tot = s.iloc[-1] / s.iloc[0] - 1
        mdd = float(((s / s.cummax()) - 1).min())
        sh = float(ret.mean() / ret.std() * np.sqrt(252))
        print(f"  {tag:22s} 年化 {(1+tot)**(1/years)-1:7.2%}  夏普 {sh:.3f}  回撤 {mdd:7.2%}  "
              f"年化波动 {ret.std()*np.sqrt(252):6.2%}")
        return dict(ann=float((1 + tot) ** (1 / years) - 1), sharpe=sh, mdd=mdd,
                    vol=float(ret.std() * np.sqrt(252)))

    print(f"  单相位（offset=0）与交叠合成对比：")
    a = stat(res_single, "单相位（原冠军）")
    b = stat(stag, "12 相位交叠合成")
    print(f"  → 回撤改善 {a['mdd']-b['mdd']:+.2%}pp｜夏普变化 {b['sharpe']-a['sharpe']:+.3f}"
          f"｜年化变化 {b['ann']-a['ann']:+.2%}")

    var_trials = float(np.var(sub_sh, ddof=1))
    d1 = dsr_of(res_single, var_trials, 12)
    d2 = dsr_of(stag, var_trials, 12)
    print(f"\n  DSR 实测（N=12 试验口径）：")
    print(f"    单相位：T={d1['T']}  年化夏普 {d1['sr_ann']:.3f}  DSR {d1['dsr']:.3f}  MinTRL {d1['min_trl']:,.0f} 日")
    print(f"    交叠后：T={d2['T']}  年化夏普 {d2['sr_ann']:.3f}  DSR {d2['dsr']:.3f}  MinTRL {d2['min_trl']:,.0f} 日")
    print(f"  → Gemini 预言「交叠把 DSR 推到 >0.95、MinTRL <8 年」：实测 "
          f"DSR {d1['dsr']:.3f}→{d2['dsr']:.3f}（{'成立' if d2['dsr']>0.95 else '不成立'}），"
          f"MinTRL {d2['min_trl']:,.0f} 日（{'<8年' if d2['min_trl']<2000 else '仍远超 8 年'}）")
    res["stagger"] = dict(single=a, staggered=b, dsr_single=d1, dsr_stag=d2, sub_sharpes=sub_sh)

    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[attrib] 落盘 {OUT}")


if __name__ == "__main__":
    main()
