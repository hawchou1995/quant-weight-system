# -*- coding: utf-8 -*-
"""A2｜B4 反向阀 · 100 次随机对照 + 分年拆解（XBSY-VALVE2-0921 · 用户 2026-09-21 批准）
================================================================================
复验对象（XBSY-VALVE-0921 唯一「三维同时改善」的格，登记为线索）
--------------------------------------------------------------------------------
A2｜B4 = **沪深300 > MA60**（大盘层，阀不过 → 不开新仓）
       ∧ **个股 MA20 > MA60**（个股层，回避空头排列）
配置：入场 A_tdx（TDX 原文）；出场 爆量≥2×MA(V,20)+次日阴线（cap250）；
      17 万本金 / 20 仓（每仓 8,500）；排序键 = 代码序；主板面板 2016-01-04 → 2026-09-18（10.76 年）

首轮读数（10 次对照）：年化 +5.76% / 夏普 0.405 / 回撤 −24.79% / 893 笔
                        基线 +4.58% / 0.334 / −34.01% / 1,164 笔；沪深300 +2.46% / 0.224 / −45.60%
首轮结论：Δ夏普 t=+0.23 不显著；回撤改善 +9.22pp **低于**随机上限 +14.50pp → 不能判定。

本轮命题与预注册
--------------------------------------------------------------------------------
**P1 结构匹配的对照**：A2 是**日级**闸（整日不开新仓）。只匹配"剔除的信号笔数"不公平 ——
故设两族对照，各 **100 次**：
  C1（信号级）：随机剔除**同笔数**的信号（100 次）
  C2（交易日级）：随机剔除**同天数**的交易日上的全部信号（100 次）← 与 A2 结构匹配
**P2 判据（预注册，全过才算「超随机」）**：
  ① 最大回撤改善 ≥ C1 与 C2 两个分布**最大值**（即比随机的最好水平还好）
  ② Δ夏普 ≥ 两个分布最大值
  ③ 年化 ≥ 沪深300 同窗 +2.46%
**P3 分年拆解**：A2｜B4 vs 基线 vs 沪深300，逐年收益与年内回撤（看是否靠个别年份）

用法：cd quant-weight-system && python backtest/xbsy_valve2_0921.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

import factor_gate as FG                                    # noqa: E402
import xbsy_0921 as X                                       # noqa: E402
import xbsy_port_0921 as PORT                               # noqa: E402
import xbsy_abl_0921 as ABL                                 # noqa: E402
import xbsy_valve_0921 as VLV                               # noqa: E402

OUT_JSON = str(HERE / "xbsy_valve2_0921.json")
CFG = dict(boom="q2", lag=1, ma5=False, ma10=False, cap=250)
NAV0, NSLOT = 170000.0, 20
DRAWS = 100
SEED = 20260921
HS300_CAGR = 0.0246


def sim(P, V, SIG, max_pos=NSLOT, nav0=NAV0):
    PORT.NAV0 = nav0
    nav, tr = ABL.sim_rank(P, V, SIG, None, False, CFG, max_pos)
    return nav, PORT.metrics(nav, VLV.cal_ref, tr, "x")


def main():
    t0 = time.time()
    print("=" * 118)
    print("A2｜B4 反向阀 · 100 次结构匹配随机对照（XBSY-VALVE2-0921）")
    print("=" * 118)
    P = FG.load_panel(X.PANEL)
    D = np.load(X.PANEL, allow_pickle=True)
    codes, cal = D["codes"], D["cal"]
    VLV.cal_ref = [str(x) for x in cal]
    V = X.load_volume([str(c) for c in codes], VLV.cal_ref)
    T, N = P["close"].shape
    SIG0 = X.build_arms(P, V)["A_tdx"]
    F = VLV.build_factors(P, V)
    IX = VLV.idx_factors(VLV.cal_ref)
    assert list(codes) and T == len(VLV.cal_ref)

    A2 = np.repeat(np.asarray(IX["above60"], dtype=bool)[:, None], N, axis=1)
    B4 = np.where(np.isfinite(F["ma60"]), F["ma20"] > F["ma60"], False)
    SIGV = SIG0 & A2 & B4
    print(f"面板 {T} 日 × {N} 只 | 基线信号 {int(SIG0.sum()):,} | 加阀后 {int(SIGV.sum()):,} "
          f"| 剔除 {(1 - SIGV.sum()/SIG0.sum()):.1%}")

    nav_b, mb = sim(P, V, SIG0)
    nav_v, mv = sim(P, V, SIGV)
    print(f"\n基线   ：年化 {mb['cagr']:+.2%}  夏普 {mb['sharpe']:.3f}  回撤 {mb['max_drawdown']:.2%}  "
          f"胜率 {(mb['win_rate_per_trade'] or 0):.1%}  笔数 {mb['n_trades']}")
    print(f"A2｜B4：年化 {mv['cagr']:+.2%}  夏普 {mv['sharpe']:.3f}  回撤 {mv['max_drawdown']:.2%}  "
          f"胜率 {(mv['win_rate_per_trade'] or 0):.1%}  笔数 {mv['n_trades']}")
    imp_mdd = mv["max_drawdown"] - mb["max_drawdown"]
    d_sharpe = mv["sharpe"] - mb["sharpe"]
    print(f"改善   ：Δ回撤 {imp_mdd:+.2%}   Δ夏普 {d_sharpe:+.3f}")

    # ---- 结构匹配的对照 ----
    rng = np.random.default_rng(SEED)
    flat = np.nonzero(SIG0.ravel())[0]
    k_sig = int(SIG0.sum() - SIGV.sum())
    days_blocked = int((~IX["above60"] & (SIG0.sum(axis=1) > 0)).sum())
    days_with_sig = int((SIG0.sum(axis=1) > 0).sum())
    print(f"\n对照参数：剔除信号 {k_sig:,} 笔 | A2 阻塞交易日 {days_blocked} 天"
          f"（有信号交易日共 {days_with_sig} 天，占 {days_blocked/days_with_sig:.1%}）")

    out = {"base": mb, "valve": mv, "imp_mdd": round(imp_mdd, 4), "d_sharpe": round(d_sharpe, 3),
           "k_sig": k_sig, "days_blocked": days_blocked, "draws": DRAWS, "controls": {}, "by_year": {}}

    for tag in ("C1_信号级", "C2_交易日级"):
        ds, dm, dd, dsh = [], [], [], []
        for b in range(DRAWS):
            if tag == "C1_信号级":
                rm = rng.choice(flat, size=k_sig, replace=False)
                s = SIG0.copy().ravel(); s[rm] = False
                S = s.reshape(SIG0.shape)
            else:
                cand = np.nonzero(SIG0.sum(axis=1) > 0)[0]
                dd_ = rng.choice(cand, size=min(days_blocked, cand.size), replace=False)
                S = SIG0.copy(); S[dd_, :] = False
            _, m = sim(P, V, S)
            ds.append(m["cagr"]); dm.append(m["max_drawdown"]); dsh.append(m["sharpe"])
            dd.append(m["max_drawdown"])
        a_mdd, a_cagr, a_sh = np.array(dm), np.array(ds), np.array(dsh)
        rec = {"n": DRAWS,
               "mdd_min": round(float(a_mdd.min()), 4), "mdd_max": round(float(a_mdd.max()), 4),
               "mdd_mean": round(float(a_mdd.mean()), 4),
               "imp_max": round(float(a_mdd.max() - mb["max_drawdown"]), 4),
               "sharpe_max": round(float(a_sh.max()), 4), "sharpe_mean": round(float(a_sh.mean()), 4),
               "cagr_max": round(float(a_cagr.max()), 4), "cagr_mean": round(float(a_cagr.mean()), 4),
               "pct_mdd_better_than_valve": round(float((a_mdd <= mv["max_drawdown"]).mean()), 4),
               "pct_sharpe_better_than_valve": round(float((a_sh >= mv["sharpe"]).mean()), 4)}
        out["controls"][tag] = rec
        print(f"\n{tag}（{DRAWS} 次）")
        print(f"  回撤：最小 {rec['mdd_min']:.2%}  最大 {rec['mdd_max']:.2%}  均值 {rec['mdd_mean']:.2%}"
              f"  → 最大改善 {rec['imp_max']:+.2%}")
        print(f"  夏普：最大 {rec['sharpe_max']:.3f}  均值 {rec['sharpe_mean']:.3f}"
              f"  年化：最大 {rec['cagr_max']:+.2%}  均值 {rec['cagr_mean']:+.2%}")
        print(f"  随机对照中 回撤 ≤ A2｜B4 的比例 {rec['pct_mdd_better_than_valve']:.0%}"
              f" | 夏普 ≥ A2｜B4 的比例 {rec['pct_sharpe_better_than_valve']:.0%}")

    thr_imp = max(v["imp_max"] for v in out["controls"].values())
    thr_sh = max(v["sharpe_max"] for v in out["controls"].values())
    g1 = imp_mdd >= thr_imp
    g2 = mv["sharpe"] >= thr_sh
    g3 = mv["cagr"] >= HS300_CAGR
    print("\n" + "-" * 118)
    print("判据（预注册三重门，须同时超过 C1/C2 两族的**最大值**）")
    print("-" * 118)
    print(f"  ① Δ回撤 {imp_mdd:+.2%} ≥ 两族最大改善 {thr_imp:+.2%} ? {'✓' if g1 else '✗'}")
    print(f"  ② Δ夏普 {mv['sharpe']:.3f} ≥ 两族最大夏普 {thr_sh:.3f} ? {'✓' if g2 else '✗'}")
    print(f"  ③ 年化 {mv['cagr']:+.2%} ≥ 沪深300 {HS300_CAGR:+.2%} ? {'✓' if g3 else '✗'}")
    print(f"  ⇒ 结论：{'超随机，可采纳' if (g1 and g2 and g3) else '不能证明超随机 → 不采纳'}")
    out["gates"] = {"g1": bool(g1), "g2": bool(g2), "g3": bool(g3),
                    "thr_imp": round(thr_imp, 4), "thr_sharpe": round(thr_sh, 4),
                    "verdict": "超随机" if (g1 and g2 and g3) else "不能证明超随机"}

    # ---- 分年拆解 ----
    print("\n" + "-" * 118)
    print("分年拆解：A2｜B4 vs 基线 vs 沪深300")
    print("-" * 118)
    nv = pd.Series(nav_v, index=pd.to_datetime(VLV.cal_ref))
    nb = pd.Series(nav_b, index=pd.to_datetime(VLV.cal_ref))
    ic = IX["c"]
    hs = pd.Series(NAV0 * ic / ic[0], index=pd.to_datetime(VLV.cal_ref))
    print(f"  {'年份':<7}{'A2|B4':>10}{'年内回撤':>10}{'基线':>10}{'年内回撤':>10}{'沪深300':>10}")
    for y in sorted(set(nv.index.year)):
        gv, gb, gh = nv[nv.index.year == y], nb[nb.index.year == y], hs[hs.index.year == y]
        rv = gv.iloc[-1] / gv.iloc[0] - 1; rb = gb.iloc[-1] / gb.iloc[0] - 1
        rh = gh.iloc[-1] / gh.iloc[0] - 1
        dv = float((gv / gv.cummax() - 1).min()); db = float((gb / gb.cummax() - 1).min())
        out["by_year"][str(y)] = {"valve": round(float(rv), 4), "valve_mdd": round(dv, 4),
                                  "base": round(float(rb), 4), "base_mdd": round(db, 4),
                                  "hs300": round(float(rh), 4)}
        print(f"  {y:<7}{rv:>10.2%}{dv:>10.2%}{rb:>10.2%}{db:>10.2%}{rh:>10.2%}")
    win = sum(1 for v in out["by_year"].values() if v["valve"] > v["base"])
    print(f"\n  A2｜B4 优于基线的年份：{win}/{len(out['by_year'])}")

    out["elapsed_s"] = round(time.time() - t0, 1)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"结果已落盘 {OUT_JSON}（{out['elapsed_s']}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
