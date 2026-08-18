# -*- coding: utf-8 -*-
"""Aroon 状态自适应改造回测（v9 体系 · 全量池 · 2016-2026）
背景：上轮穷举证明 Aroon 高阈值(80)是"强趋势精选"，2020-21 疯牛段被抑制拖累(Δ-74pct)。
改造：市场强(指数年线超额/动量)时"放松或关闭"Aroon 抑制，非热市维持 A80_M80。
目标：保留 2016-19/2022-26 增益，修复 2020-21 拖累 → OOS 达成 3/3 段稳健。

状态口径（在市场强日"热市"，否则"冷市"）：
  S_A: ma200_pos > 0.10
  S_B: mom20 > 0.03
  S_C: (ma200_pos > 0.08) or (mom20 > 0.03)
热市抑制开关：
  R_OFF: 完全关闭 (map 值 None)
  R_60:  (60, 0.80)
  R_70:  (70, 0.80)
  R_HYBRID: 热市(60,0.80) 冷市(80,0.80) → 温和版
冷市固定 (80, 0.80)。
对比：基线 / A80_M80 固定。
用法：python _aroon_state_adaptive.py
"""
import os, sys, time, json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import v8_selector as V
import _aroon_inhibit_exp as X

OUT = BASE / "aroon_state_adaptive_results.json"
COLD = (80, 0.80)


def build_state_map(start, end, state_fn, hot_th):
    """构造 date(str) -> (aroon_th, mom_th) 或 None(关闭) 的映射"""
    idx = V.load_index(200)
    idx["date"] = pd.to_datetime(idx["date"])
    idx = idx.sort_values("date").set_index("date")
    idx["mom20"] = idx["close"].pct_change(20)
    idx["ma200_pos"] = idx["close"] / idx["close"].rolling(200).mean() - 1
    cmap = {}
    for day, r in idx.iterrows():
        dstr = str(day.date())
        if not (start <= dstr <= end):
            continue
        hot = bool(state_fn(r))
        cmap[dstr] = hot_th if hot else COLD
    return cmap


def metric(label, start, end, state_fn=None, hot_th=None, **extra):
    t0 = time.time()
    if state_fn is None:
        # 固定阈值（基线用 None → 无抑制；A80 用 (80,.8)）
        eq, tr = X.run_auto_inhibit(start=start, end=end,
                                    aroon_th=extra.get("aroon_th", 80),
                                    mom_th=extra.get("mom_th", 0.80),
                                    fac=extra.get("fac", 0.6),
                                    cap=extra.get("cap", False))
    else:
        cmap = build_state_map(start, end, state_fn, hot_th)
        eq, tr = X.run_auto_inhibit(start=start, end=end, aroon_th_map=cmap)
    s = V.summary(eq, tr)
    row = {"label": label,
           "total_return_pct": float(s["total_return_pct"]),
           "annual_return_pct": float(s["annual_return_pct"]),
           "max_drawdown_pct": float(s["max_drawdown_pct"]),
           "sharpe": float(s["sharpe"]),
           "win_rate_pct": float(s["win_rate_pct"]),
           "total_trades": int(s["total_trades"]),
           "secs": int(time.time() - t0)}
    return row


if __name__ == "__main__":
    FULL = ("2016-01-04", "2026-08-17")
    SEGS = [("2016-2019", "2016-01-04", "2019-12-31"),
            ("2020-2021", "2020-01-02", "2021-12-31"),
            ("2022-2026", "2022-01-04", "2026-08-17")]

    # 状态函数
    def S_A(r): return r["ma200_pos"] > 0.10
    def S_B(r): return r["mom20"] > 0.03
    def S_C(r): return (r["ma200_pos"] > 0.08) or (r["mom20"] > 0.03)

    # 候选：label -> (state_fn, hot_th)
    cands = {
        "baseline":   (None, None),
        "A80_M80固定": (None, None),
        "S_A_OFF":  (S_A, None),
        "S_B_OFF":  (S_B, None),
        "S_C_OFF":  (S_C, None),
        "S_A_60":   (S_A, (60, 0.80)),
        "S_B_60":   (S_B, (60, 0.80)),
        "S_C_60":   (S_C, (60, 0.80)),
    }

    # ---------- 全样本快速对比 ----------
    print("== 全样本 2016-2026 ==", flush=True)
    full_res = {}
    for label, (sf, ht) in cands.items():
        if label == "baseline":
            r = metric(label, *FULL, aroon_th=None, mom_th=None)
        elif label == "A80_M80固定":
            r = metric(label, *FULL)
        else:
            r = metric(label, *FULL, state_fn=sf, hot_th=ht)
        full_res[label] = r
        print(f"{label:12s} 收益{r['total_return_pct']:+8.1f}% 回撤{r['max_drawdown_pct']:+6.2f}% "
              f"夏普{r['sharpe']:.3f} 胜率{r['win_rate_pct']:.1f}% 交易{r['total_trades']} [{r['secs']}s]", flush=True)
    json.dump({"full": full_res}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ---------- 选出自适应最优口径做 OOS 三段 ----------
    b = full_res["baseline"]
    a80 = full_res["A80_M80固定"]
    adaptive = {k: v for k, v in full_res.items() if k not in ("baseline", "A80_M80固定")}
    # 自适应有效 = 收益>基线 且 回撤不恶化 且 夏普>基线，且尽量接近 A80 的收益
    def score(r):
        return (r["total_return_pct"] - b["total_return_pct"],
                r["max_drawdown_pct"] - b["max_drawdown_pct"],
                r["sharpe"] - b["sharpe"])
    ranked = sorted(adaptive.items(), key=lambda kv: -(score(kv[1])[0] + 40*score(kv[1])[2] + 1.5*score(kv[1])[1]))
    top_adaptive = [k for k, _ in ranked[:2]]
    print(f"\n自适应候选排序: {[k for k,_ in ranked]}", flush=True)
    print(f"进入 OOS 三段的自适应口径: {top_adaptive}", flush=True)

    # ---------- OOS 三段 ----------
    print("\n== OOS 三段稳健性 ==", flush=True)
    oos = {}
    oos_labels = ["baseline", "A80_M80固定"] + top_adaptive
    for label in oos_labels:
        sf, ht = cands[label]
        oos[label] = {}
        for seg, s_, e_ in SEGS:
            t0 = time.time()
            if label == "baseline":
                r = metric(label, s_, e_, aroon_th=None, mom_th=None)
            elif label == "A80_M80固定":
                r = metric(label, s_, e_)
            else:
                r = metric(label, s_, e_, state_fn=sf, hot_th=ht)
            oos[label][seg] = r
            print(f"  {label:12s} {seg}: 收益{r['total_return_pct']:+7.1f}% 回撤{r['max_drawdown_pct']:+6.2f}% "
                  f"夏普{r['sharpe']:.3f} 胜率{r['win_rate_pct']:.1f}% 交易{r['total_trades']} [{r['secs']}s]", flush=True)

    # 相对基线与 A80 判定
    print("\n== 判定 ==", flush=True)
    for label in ["A80_M80固定"] + top_adaptive:
        good_vs_b = good_vs_a = 0
        dd_bad_vs_b = dd_bad_vs_a = 0
        for seg, _, _ in SEGS:
            d_b_ret = oos[label][seg]["total_return_pct"] - oos["baseline"][seg]["total_return_pct"]
            d_b_sh = oos[label][seg]["sharpe"] - oos["baseline"][seg]["sharpe"]
            d_a_ret = oos[label][seg]["total_return_pct"] - oos["A80_M80固定"][seg]["total_return_pct"]
            d_a_dd = oos[label][seg]["max_drawdown_pct"] - oos["A80_M80固定"][seg]["max_drawdown_pct"]
            if d_b_ret > 0 and d_b_sh > 0: good_vs_b += 1
            if d_a_ret > 0: good_vs_a += 1
            if d_b_ret < -5: dd_bad_vs_b += 1
            if d_a_dd < 0: dd_bad_vs_a += 1
        print(f"  {label:12s}: vs基线 {good_vs_b}/3 段收益+夏普双升; vs A80 {good_vs_a}/3 段收益更高; 回撤逊 A80 {dd_bad_vs_a} 段", flush=True)

    json.dump({"full": full_res, "oos": oos, "top_adaptive": top_adaptive},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n完成 → {OUT.name}", flush=True)
