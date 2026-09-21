# -*- coding: utf-8 -*-
"""小步碎阳 · 状态化出场叠加（XBSY-EXIT-0921 · 2026-09-21 用户给定两条出场规则）
================================================================================
用户规则（原话）
  止盈/离场：**爆量后第二天收盘价低于开盘价，离场**
  止损：    **连续五天跌破五日线**

预注册（看任何收益数字之前固定）
--------------------------------------------------------------------------------
- 入场沿用 `xbsy_0921` 的 A_tdx（TDX 原文）信号日 → **T+1 开盘买入**
- 出场执行统一「**收盘确认 → 次日开盘卖**」（与全仓同口径）：
    · 爆量规则：爆量日 i（爆量须发生在持仓期内）→ 次日/次二日收盘<开盘 确认 → 确认日次日开盘卖
    · 破线规则：连续 5 日收盘 < MA(C,5) 确认（第 5 日收盘）→ 次日开盘卖
    · 上限 cap：未触发任何规则 → 第 cap 个持仓日**收盘**卖
- 爆量定义**用户未给**，故预注册三档并列，不择优事后挑选：
    q2 = V ≥ 2×MA(V,20) ／ q3 = V ≥ 3×MA(V,20) ／ vmax20 = V = 20日最高量
- 「后第二天」字面歧义 → 两读并列：lag=1（爆量次日）／lag=2（爆量后第二日）
- 判据同 `xbsy_0921`：超额口径为主（逐笔扣掉**同一窗口**全市场等权收益）、
  按笔+按天双给、**以 t_cluster 为准**、成本 0/20/50bp 三档、样本闸 n≥100∧活跃日≥30
- 对照：X7 = 固定持有 20 日（基准）

实现要点：两条出场规则都**与入场日无关**（只依赖当日形态），
故对每个「确认日」矩阵取**后缀最小值**得到每笔的最早出场日 → 全向量化，无逐笔循环。

用法：cd quant-weight-system && python backtest/xbsy_exit_0921.py
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

import factor_infer as FI                                   # noqa: E402
import factor_gate as FG                                    # noqa: E402
import xbsy_0921 as X                                       # noqa: E402  （复用信号/量能/滚动窗口）

OUT_JSON = str(HERE / "xbsy_exit_0921.json")
COST_TIERS = {"0bp": 0.0, "20bp": 0.0020, "50bp": 0.0050}
INF = 10 ** 9

EXIT_ARMS = {                                   # 全部预注册，不事后择优
    "X1_爆量2x_次日阴": dict(boom="q2", lag=1, ma5=False, cap=60),
    "X2_爆量3x_次日阴": dict(boom="q3", lag=1, ma5=False, cap=60),
    "X3_爆量最高量_次日阴": dict(boom="vmax20", lag=1, ma5=False, cap=60),
    "X4_连5破MA5": dict(boom=None, lag=1, ma5=True, cap=60),
    "X5_爆量阴+破线_先到": dict(boom="q2", lag=1, ma5=True, cap=60),
    "X6_爆量后第二天+破线": dict(boom="q2", lag=2, ma5=True, cap=60),
    "X7_基准_固定20日": dict(boom=None, lag=1, ma5=False, cap=20),
    "X8_爆量阴_无上限": dict(boom="q2", lag=1, ma5=False, cap=250),
}
ENTRY_ARMS = ["A_tdx", "B_fixed"]


def exit_day_matrix(O, C, V, cfg):
    """返回 NX[t,n] = 入场日之后的**最早出场日索引**（含规则与上限的原始规则日，不含 cap）。
    规则确认日 d → 次日开盘卖，故 NX 记的是「卖出所在的交易日」。"""
    T = C.shape[0]
    ar = np.arange(T, dtype=np.int64)[:, None]
    NX = np.full(C.shape, INF, dtype=np.int64)

    if cfg["boom"]:
        mav20 = X.roll_mean(V, 20)
        bm = {
            "q2": V >= 2.0 * mav20,
            "q3": V >= 3.0 * mav20,
            "vmax20": V >= X.roll_max(V, 20),
        }[cfg["boom"]]
        bm = np.where(np.isfinite(mav20), bm, False)
        Cn = np.full_like(C, np.nan); Cn[:-1] = C[1:]        # 次日收盘
        On = np.full_like(O, np.nan); On[:-1] = O[1:]        # 次日开盘
        if cfg["lag"] == 1:
            conf = bm & (Cn < On)                            # 爆量日次日为阴
            sd = np.where(conf, ar + 2, INF)                 # 确认日次日开盘卖
        else:                                                # 字面读法：爆量后第二日
            C2 = np.full_like(C, np.nan); C2[:-2] = C[2:]
            O2 = np.full_like(O, np.nan); O2[:-2] = O[2:]
            conf = bm & (C2 < O2)
            sd = np.where(conf, ar + 3, INF)
        NX = np.minimum(NX, sd)

    if cfg["ma5"]:
        ma5 = X.roll_mean(C, 5)
        below = np.where(np.isfinite(ma5), C < ma5, False)
        conf5 = X.roll_sum(below.astype(np.float64), 5) == 5   # 连续 5 日收盘 < MA5
        NX = np.minimum(NX, np.where(conf5, ar + 1, INF))

    # 后缀最小值：NX[t] = min over i ≥ t（规则与入场日无关，故一次预计算供全部入场复用）
    NX = np.minimum.accumulate(NX[::-1], axis=0)[::-1]
    return NX


def bench_same_window(P, e_arr, d_arr, chunk=8000):
    """逐笔「同一窗口」全市场等权基准：mean_n( C[d,n]/O[e,n] - 1 )，按唯一 (e,d) 对分块计算。"""
    O = P["open"].astype(np.float64)
    C = P["close"].astype(np.float64)
    M = P["mask"]
    T = C.shape[0]
    pairs, inv = np.unique(np.stack([e_arr, d_arr], axis=1), axis=0, return_inverse=True)
    bench = np.full(pairs.shape[0], np.nan)
    for s in range(0, pairs.shape[0], chunk):
        blk = pairs[s:s + chunk]
        e = blk[:, 0]; d = blk[:, 1]
        num = C[d, :] * (1.0 / np.where(O[e, :] > 0, O[e, :], np.nan)) - 1.0
        num = np.where(M[d, :] & M[e, :] & np.isfinite(num), num, np.nan)
        with np.errstate(all="ignore"):
            cnt = np.sum(np.isfinite(num), axis=1)
            sm = np.nansum(num, axis=1)
        bench[s:s + len(blk)] = np.divide(sm, cnt, out=np.full(len(blk), np.nan), where=cnt > 0)
    b = bench[inv]
    b = np.where(np.isfinite(b), b, 0.0)                      # 基准缺失按 0 计（保守，不美化）
    return b


def stats(r, day_arr, G, bench, tag):
    rec = {"n": int(r.size), "days_active": int(np.unique(day_arr).size) if r.size else 0}
    if r.size < 2:
        rec["verdict"] = "不可判定（样本不存在）"
        return rec
    ct = FI.cluster_t(r, day_arr, G)
    ex = r - bench
    dm = FI.daily_mean(r, day_arr, G)
    rec.update({
        "mean_per_trade": round(float(r.mean()), 6),
        "win_rate": round(float((r > 0).mean()), 4),
        "median_per_trade": round(float(np.median(r)), 6),
        "mean_per_day": round(float(dm.mean()), 6) if dm.size else None,
        "t_cluster": round(float(ct["t"]), 2),
        "excess_mean_per_trade": round(float(ex.mean()), 6),
        "excess_win": round(float((ex > 0).mean()), 4),
        "excess_t_cluster": round(float(FI.cluster_t(ex, day_arr, G)["t"]), 2),
        "excess_mean_per_day": round(float(FI.daily_mean(ex, day_arr, G).mean()), 6),
    })
    for t_, c in COST_TIERS.items():
        rec[f"excess_mean_{t_}"] = round(float(ex.mean() - c), 6)
        rec[f"excess_t_cluster_{t_}"] = round(float(FI.cluster_t(ex - c, day_arr, G)["t"]), 2)
    rec["sample_gate"] = "PASS" if (rec["n"] >= 100 and rec["days_active"] >= 30) else "不可判定"
    return rec


def run_exit(P, V, SIG, cfg, G):
    O = P["open"].astype(np.float64)
    C = P["close"].astype(np.float64)
    M = P["mask"]
    T = C.shape[0]
    day_idx, stk = np.nonzero(SIG & M)
    e = day_idx + 1
    ok = e < T
    day_idx, stk, e = day_idx[ok], stk[ok], e[ok]
    buy = O[e, stk]
    ok = np.isfinite(buy) & (buy > 0)
    day_idx, stk, e, buy = day_idx[ok], stk[ok], e[ok], buy[ok]

    cap = cfg["cap"]
    cap_d = np.minimum(e + cap - 1, T - 1)
    nx_all = exit_day_matrix(O, C, V, cfg)
    nx = nx_all[e, stk]
    use_rule = nx <= cap_d
    d = np.where(use_rule, np.minimum(nx, T - 1), cap_d)
    sell = np.where(use_rule, O[d, stk], C[cap_d, stk])
    ok = np.isfinite(sell) & (sell > 0)
    r = sell[ok] / buy[ok] - 1.0
    dayv, stkv, dv = day_idx[ok], stk[ok], d[ok]
    bench = bench_same_window(P, e[ok], dv)
    holds = dv - e[ok] + 1
    meta = {
        "hold_median": int(np.median(holds)), "hold_mean": round(float(holds.mean()), 1),
        "rule_exit_share": round(float(use_rule[ok].mean()), 4),
        "cap_exit_share": round(float(1 - use_rule[ok].mean()), 4),
    }
    return r, dayv, bench, meta, T


def main():
    t0 = time.time()
    print("=" * 104)
    print("小步碎阳 · 状态化出场叠加（XBSY-EXIT-0921）· 入口 A_tdx（TDX 原文）")
    print("=" * 104)
    P = FG.load_panel(X.PANEL)
    D = np.load(X.PANEL, allow_pickle=True)
    codes, cal = D["codes"], D["cal"]
    T, N = P["close"].shape
    V = X.load_volume([str(c) for c in codes], [str(d) for d in cal])
    arms_sig = X.build_arms(P, V)
    print(f"面板 {T} 日 × {N} 只 | {cal[0]} → {cal[-1]}")

    out = {"entry": "A_tdx", "arms": {}, "elapsed_s": None,
           "note": "超额=逐笔扣同一窗口全市场等权收益；出场确认于收盘、次日开盘卖；cap 到期按收盘卖"}

    hdr = (f"  {'出场配置':<24}{'笔数':>8}{'持仓中位':>9}{'规则出场%':>10}{'胜率':>7}"
           f"{'按笔均值':>10}{'超额均值':>10}{'t_cluster':>10}{'超额t_cl':>10}"
           f"{'超额20bp':>10}{'超额50bp':>10}")
    print("\n" + "-" * 104)
    print("出场臂 × 入场 A_tdx（超额口径为主）")
    print("-" * 104)
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    SIG = arms_sig["A_tdx"]
    for name, cfg in EXIT_ARMS.items():
        r, dayv, bench, meta, G = run_exit(P, V, SIG, cfg, T)
        rec = stats(r, dayv, G, bench, name)
        rec["cfg"] = cfg
        rec.update(meta)
        out["arms"][name] = rec
        if rec.get("n", 0) < 2:
            print(f"  {name:<24} 不可判定（样本不存在）")
            continue
        print(f"  {name:<24}{rec['n']:>8}{meta['hold_median']:>9}{meta['rule_exit_share']:>10.1%}"
              f"{rec['win_rate']:>7.1%}{rec['mean_per_trade']:>10.4f}"
              f"{rec['excess_mean_per_trade']:>10.4f}{rec['t_cluster']:>10.2f}"
              f"{rec['excess_t_cluster']:>10.2f}{rec['excess_mean_20bp']:>10.4f}"
              f"{rec['excess_mean_50bp']:>10.4f}")

    # 入场臂敏感性：换 B_fixed 入场跑两条主出场配置
    print("\n" + "-" * 104)
    print("入场臂敏感性（同一出场规则换入场信号）")
    print("-" * 104)
    for en in ENTRY_ARMS:
        for xname in ("X5_爆量阴+破线_先到", "X7_基准_固定20日"):
            r, dayv, bench, meta, G = run_exit(P, V, arms_sig[en], EXIT_ARMS[xname], T)
            rec = stats(r, dayv, G, bench, xname)
            rec["entry"] = en
            out["arms"][f"{en}__{xname}"] = rec
            print(f"  {en:<10}+{xname:<24} n={rec.get('n', 0):>7} 持仓中位={meta['hold_median']:>4} "
                  f"超额均值={rec.get('excess_mean_per_trade', float('nan')):+.4f} "
                  f"超额t_cl={rec.get('excess_t_cluster', float('nan')):>6.2f} "
                  f"超额50bp={rec.get('excess_mean_50bp', float('nan')):+.4f}")

    out["elapsed_s"] = round(time.time() - t0, 1)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n结果已落盘 {OUT_JSON}（{out['elapsed_s']}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
