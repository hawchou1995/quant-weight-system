# -*- coding: utf-8 -*-
"""过门臂完整验收面 + 优化挖掘（R-buffett-opt-0915）。

用户问：①过门臂的胜率/年化/回撤/夏普等值是多少？②在基础上挖掘优化可能。

口径：轨 II（年度再平衡、全 A 主板、T+1 开盘、ST/退 PIT 过滤）
  胜率三口径：逐笔（个股平仓）/ 调仓期（组合期间收益）/ 年度
优化轴（避免已证伪维度：不做固定阈值止盈止损、不测 ROE 水平值/护城河水平值）：
  A 持仓数 N ∈ {5,10,20,30}
  B 调仓周期 rebal ∈ {125,250,500}
  C 复合结构：roe_pb × {无 gate / 分红持续≥3年 / 毛利率>行业中位 / 分红持续+低换手过滤}
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import value_lh_0914 as V           # noqa: E402
import value_arms_0914 as A         # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "value_opt_0914.json")
PHASES = 9


def metrics(r, tag, start, slip):
    return dict(tag=tag, start=start, slip=slip,
                total=r["total"], ann=r["ann"], sharpe=r["sharpe"], mdd=r["mdd"],
                win_trade=r["win_rate_trade"], win_period=r["win_rate_period"],
                win_year=r["win_rate_year"], n_closed=r["n_closed"], n_period=r["n_period"],
                avg_win=r["avg_win"], avg_loss=r["avg_loss"], pf=r["profit_factor"],
                trades=r["trades"],
                by_year={str(k.year): float(v) for k, v in r["by_year"].items()})


def phase_stats(feat, sc, ex, rebal, topn, slip, start):
    rows = []
    for p in range(PHASES):
        off = int(round(p * rebal / PHASES))
        r = V.run(feat, sc, rebal=rebal, topn=topn, slip=slip, offset=off,
                  start=start, exclude=ex)
        rows.append(dict(offset=off, ann=r["ann"], sharpe=r["sharpe"], mdd=r["mdd"],
                         win_trade=r["win_rate_trade"], win_period=r["win_rate_period"],
                         total=r["total"]))
    df = pd.DataFrame(rows)
    return dict(phases=rows,
                sharpe_med=float(df.sharpe.median()), ann_med=float(df.ann.median()),
                mdd_med=float(df.mdd.median()),
                win_trade_med=float(df.win_trade.median()),
                win_period_med=float(df.win_period.median()),
                sharpe_min=float(df.sharpe.min()), sharpe_max=float(df.sharpe.max()))


def main():
    feat = V.load_features()
    if "_raw_close" not in feat:
        feat["_raw_close"] = V.raw_close(feat, validate=False)
    f = A.build_factors(feat, None)
    ex = V.st_mask(feat)

    res = {"full_metrics": {}, "opt_N": {}, "opt_rebal": {}, "opt_combo": {}}

    # ── ① 过门臂完整验收面（off0 详报 + 相位中位）
    print("=" * 96)
    print("① 过门臂完整验收面（年度再平衡 Top10 / 20bp）")
    print("=" * 96)
    for tag, fac, mask in [
        ("F_roe_pb（ROE÷PB 票息）", f["roe_pb"], None),
        ("G3_E4（近5年分红≥4年 ∧ dy>1%）", f["dy"], A.gate(f["div_years"] >= 4, f["dy"] > 0.01)),
    ]:
        sc = A.make_score(fac, mask)
        start = A.coverage_start(sc, 30)
        r0 = V.run(feat, sc, rebal=250, topn=10, slip=0.002, offset=0, start=start, exclude=ex)
        st = phase_stats(feat, sc, ex, 250, 10, 0.002, start)
        res["full_metrics"][tag] = dict(off0=metrics(r0, tag, start, 0.002), phases=st)
        print(f"\n▎{tag}   窗口 {start} ~ 2026-09  （{r0['years']:.1f} 年）")
        print(f"  ┌ off0（相位 0）──────────────────────────────────────────────┐")
        print(f"  │ 总收益 {r0['total']:>9.2%}   年化 {r0['ann']:>7.2%}   夏普 {r0['sharpe']:.3f}   回撤 {r0['mdd']:>7.2%} │")
        print(f"  │ 逐笔胜率 {r0['win_rate_trade']:>6.2%}（n={r0['n_closed']}）  期间胜率 {r0['win_rate_period']:>6.2%}"
              f"（n={r0['n_period']}）  年度胜率 {r0['win_rate_year']:>6.2%} │")
        print(f"  │ 均盈 {r0['avg_win']:>7.2%}  均亏 {r0['avg_loss']:>7.2%}  盈亏比(PF) {r0['profit_factor']:.3f}"
              f"  成交 {r0['trades']} 笔 │")
        print(f"  │ 9 相位中位：夏普 {st['sharpe_med']:.3f}（{st['sharpe_min']:.2f}~{st['sharpe_max']:.2f}）"
              f"  年化 {st['ann_med']:>7.2%}  回撤 {st['mdd_med']:>7.2%}  逐笔胜率 {st['win_trade_med']:.2%} │")
        print(f"  └──────────────────────────────────────────────────────────┘")
        print("  分年:", {k: f"{v:.1%}" for k, v in list(r0["by_year"].items())})

    # ── ② N 敏感度（F_roe_pb）
    print("\n" + "=" * 96)
    print("② 优化轴 A：持仓数 N（F_roe_pb，rebal=250，20bp）")
    print("=" * 96)
    sc = A.make_score(f["roe_pb"], None)
    start = A.coverage_start(sc, 30)
    print(f"{'N':>4s} {'phmed S':>8s} {'年化中位':>9s} {'回撤中位':>9s} {'逐笔胜率':>9s} {'期间胜率':>9s} {'off0年化':>9s}")
    for N in (5, 10, 20, 30):
        st = phase_stats(feat, sc, ex, 250, N, 0.002, start)
        r0 = V.run(feat, sc, rebal=250, topn=N, slip=0.002, offset=0, start=start, exclude=ex)
        res["opt_N"][N] = dict(phases=st, off0=metrics(r0, f"N={N}", start, 0.002))
        print(f"{N:>4d} {st['sharpe_med']:>8.3f} {st['ann_med']:>8.2%} {st['mdd_med']:>8.2%} "
              f"{st['win_trade_med']:>8.2%} {st['win_period_med']:>8.2%} {r0['ann']:>8.2%}")

    # ── ③ 调仓周期敏感度
    print("\n" + "=" * 96)
    print("③ 优化轴 B：调仓周期 rebal（F_roe_pb，Top10，20bp）")
    print("=" * 96)
    print(f"{'rebal':>6s} {'phmed S':>8s} {'年化中位':>9s} {'回撤中位':>9s} {'逐笔胜率':>9s} {'期间胜率':>9s} {'期间数':>7s}")
    for rb in (125, 250, 500):
        st = phase_stats(feat, sc, ex, rb, 10, 0.002, start)
        r0 = V.run(feat, sc, rebal=rb, topn=10, slip=0.002, offset=0, start=start, exclude=ex)
        res["opt_rebal"][rb] = dict(phases=st, off0=metrics(r0, f"rebal={rb}", start, 0.002))
        print(f"{rb:>6d} {st['sharpe_med']:>8.3f} {st['ann_med']:>8.2%} {st['mdd_med']:>8.2%} "
              f"{st['win_trade_med']:>8.2%} {st['win_period_med']:>8.2%} {r0['n_period']:>7d}")

    # ── ④ 复合结构
    print("\n" + "=" * 96)
    print("④ 优化轴 C：复合结构（主序=ROE÷PB，gate 为与门；Top10 / rebal=250 / 20bp）")
    print("=" * 96)
    combos = [
        ("C0 无 gate（基线）", None),
        ("C1 ∨ 分红持续≥3年", A.gate(f["div_years"] >= 3)),
        ("C2 ∨ 毛利率>行业中位", A.gate(f["gpm_rel"] > 0)),
        ("C3 ∨ 分红持续≥3年 ∧ 分红率≤60%", A.gate(f["div_years"] >= 3, f["payout"] <= 0.6)),
    ]
    print(f"{'结构':34s} {'phmed S':>8s} {'年化中位':>9s} {'回撤中位':>9s} {'逐笔胜率':>9s} {'合格数中位':>10s}")
    for tag, mask in combos:
        scc = A.make_score(f["roe_pb"], mask)
        s0 = A.coverage_start(scc, 30)
        if s0 is None:
            print(f"{tag:34s} 有效值不足，跳过")
            continue
        st = phase_stats(feat, scc, ex, 250, 10, 0.002, s0)
        r0 = V.run(feat, scc, rebal=250, topn=10, slip=0.002, offset=0, start=s0, exclude=ex)
        elig = int(scc.notna().sum(axis=1).median()) if mask is None else int(mask.sum(axis=1).median())
        res["opt_combo"][tag] = dict(start=s0, phases=st, off0=metrics(r0, tag, s0, 0.002), elig_med=elig)
        print(f"{tag:34s} {st['sharpe_med']:>8.3f} {st['ann_med']:>8.2%} {st['mdd_med']:>8.2%} "
              f"{st['win_trade_med']:>8.2%} {elig:>10d}")

    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[opt] 落盘 {OUT}")


if __name__ == "__main__":
    main()
