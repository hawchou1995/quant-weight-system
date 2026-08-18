# -*- coding: utf-8 -*-
"""mom_th 敏感性（A80 固定 · v9 全量池 · 2016-2026）
背景：烽火 08-18 mom=0.774 <0.8 未触发 Aroon 过滤（69.4 未压）。验证把 mom_th 从 0.8
      降到 0.75 能否覆盖 mom∈[0.75,0.8) 次高动量追高标、且不回撤恶化。
网格：mom_th ∈ {0.60,0.65,0.70,0.75,0.78,0.80,0.85,0.90}（aroon_th=80, fac=0.6 固定）
判定：对比当前生产口径 A80_M80(=0.8)，看 0.75 档收益/回撤/夏普是否接近或更优 + OOS 三段
产出：aroon_mom_sens.json
"""
import os, sys, time, json
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import v8_selector as V
import _aroon_inhibit_exp as X

OUT = BASE / "aroon_mom_sens.json"
SEGS = [("2016-2019", "2016-01-04", "2019-12-31"),
        ("2020-2021", "2020-01-02", "2021-12-31"),
        ("2022-2026", "2022-01-04", "2026-08-17")]


def run(label, start, end, mom_th, aroon_th=80):
    t0 = time.time()
    eq, tr = X.run_auto_inhibit(aroon_th=aroon_th, mom_th=mom_th, start=start, end=end)
    s = V.summary(eq, tr)
    return {"label": label, "mom_th": mom_th, "aroon_th": aroon_th,
            "total_return_pct": float(s["total_return_pct"]),
            "annual_return_pct": float(s["annual_return_pct"]),
            "max_drawdown_pct": float(s["max_drawdown_pct"]),
            "sharpe": float(s["sharpe"]), "win_rate_pct": float(s["win_rate_pct"]),
            "total_trades": int(s["total_trades"]), "secs": int(time.time() - t0)}


if __name__ == "__main__":
    GRID = [0.60, 0.65, 0.70, 0.75, 0.78, 0.80, 0.85, 0.90]
    print("== 全样本 2016-2026（A80 固定 × mom_th 网格）==", flush=True)
    full = {}
    for m in GRID:
        r = run(f"A80_M{int(m*100)}", "2016-01-04", "2026-08-17", m)
        full[m] = r
        print(f"  A80_M{int(m*100)}: 收益{r['total_return_pct']:+8.1f}% 回撤{r['max_drawdown_pct']:+6.2f}% "
              f"夏普{r['sharpe']:.3f} 胜率{r['win_rate_pct']:.1f}% 交易{r['total_trades']} [{r['secs']}s]", flush=True)
    json.dump({"full": full}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 择优：收益最优 + 当前生产 0.8 + 待验证 0.75
    b_cur = full[0.80]
    print(f"\n当前生产 A80_M80: 收益{b_cur['total_return_pct']:+.1f}% 回撤{b_cur['max_drawdown_pct']:+.2f}% 夏普{b_cur['sharpe']:.3f}", flush=True)
    picks = [0.75, 0.78, 0.80, 0.70]
    # 也加入收益最优档
    best_m = max(GRID, key=lambda m: full[m]["total_return_pct"])
    if best_m not in picks:
        picks.append(best_m)
    picks = sorted(set(picks))

    print("\n== OOS 三段（picks）==", flush=True)
    oos = {}
    for m in picks:
        oos[m] = {}
        for seg, s_, e_ in SEGS:
            r = run(f"A80_M{int(m*100)}", s_, e_, m)
            oos[m][seg] = r
            print(f"  A80_M{int(m*100)} {seg}: 收益{r['total_return_pct']:+7.1f}% 回撤{r['max_drawdown_pct']:+6.2f}% "
                  f"夏普{r['sharpe']:.3f} 胜率{r['win_rate_pct']:.1f}% 交易{r['total_trades']}", flush=True)
    print()
    print("== vs 当前 0.8 判定 ==", flush=True)
    for m in picks:
        if m == 0.80:
            continue
        good = 0; dd_bad = 0
        for seg, _, _ in SEGS:
            d_ret = oos[m][seg]["total_return_pct"] - oos[0.80][seg]["total_return_pct"]
            d_sh = oos[m][seg]["sharpe"] - oos[0.80][seg]["sharpe"]
            d_dd = oos[m][seg]["max_drawdown_pct"] - oos[0.80][seg]["max_drawdown_pct"]
            if d_ret > 0 and d_sh > 0: good += 1
            if d_dd < 0: dd_bad += 1
            print(f"  A80_M{int(m*100)} vs M80 {seg}: Δ收益{d_ret:+6.1f} Δ夏普{d_sh:+.3f} Δ回撤{d_dd:+.2f}")
        print(f"  → A80_M{int(m*100)}: {good}/3 段收益+夏普双升, {dd_bad} 段回撤恶化")

    # 全样本相对 0.8
    for m in GRID:
        if m == 0.80:
            continue
        d_ret = full[m]["total_return_pct"] - full[0.80]["total_return_pct"]
        d_dd = full[m]["max_drawdown_pct"] - full[0.80]["max_drawdown_pct"]
        d_sh = full[m]["sharpe"] - full[0.80]["sharpe"]
        print(f"  全样本 A80_M{int(m*100)} vs M80: Δ收益{d_ret:+.1f} Δ回撤{d_dd:+.2f} Δ夏普{d_sh:+.3f}")

    json.dump({"full": full, "oos": oos}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n完成 → {OUT.name}", flush=True)
