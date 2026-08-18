# -*- coding: utf-8 -*-
"""Aroon 中长线系统参数穷举（v9 体系 · 全量池 · 2016-01-04 起 · 2026-08-17 止）
目标：在 aroon_th(低位预警阈值) × mom_th(年动量阈值) × 抑制强度(fac/cap) 三维空间
      穷举扫描，找出相比基线（无抑制）收益/回撤/夏普综合最优的参数组，并做样本外稳健性。

两阶段：
  Stage A 粗扫（fac=0.6 固定）：aroon_th ∈ {15,25,35,45,55,65} × mom_th ∈ {0.5..1.1}
  Stage B 细扫：在 StageA 全局最优 (aroon,mom) 邻域 ±5 / ±0.05，以及强度 fac ∈ {0.3..0.9} 与 cap
  Stage C OOS 稳健性：最优 top3 参数分三段（2016-2019/2020-2021/2022-2026）与基线同区间对比

选优标准（v6 铁律改造）：
  eligibility = 收益↑ 且 回撤不恶化(rel_dd>=0) 且 夏普↑；composite = rel_ret + 40*rel_sharpe + 1.5*rel_dd
用法：python _aroon_exhaust.py
"""
import os, sys, time, json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import v8_selector as V
import _aroon_inhibit_exp as X   # 复用 run_auto_inhibit (+start/end 支持)

OUT = BASE / "aroon_exhaust_results.json"

RESULTS = []          # list of dict
BASELINE = None


def metric(label, **kw):
    """run + summarize，返回 dict"""
    t0 = time.time()
    eq, tr = X.run_auto_inhibit(**kw)
    s = V.summary(eq, tr)
    row = {
        "label": label, **kw,
        "total_return_pct": float(s["total_return_pct"]),
        "annual_return_pct": float(s["annual_return_pct"]),
        "max_drawdown_pct": float(s["max_drawdown_pct"]),
        "sharpe": float(s["sharpe"]),
        "win_rate_pct": float(s["win_rate_pct"]),
        "total_trades": int(s["total_trades"]),
        "secs": int(time.time() - t0),
    }
    RESULTS.append(row)
    # 增量保存
    json.dump({"baseline": BASELINE, "results": RESULTS},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return row


def score_row(row):
    """综合评分：相对基线的增量"""
    b = BASELINE
    rel_ret = row["total_return_pct"] - b["total_return_pct"]
    rel_dd = row["max_drawdown_pct"] - b["max_drawdown_pct"]
    rel_sh = row["sharpe"] - b["sharpe"]
    eligible = rel_ret > 0 and rel_dd >= 0 and rel_sh >= 0
    composite = rel_ret + 40 * rel_sh + 1.5 * rel_dd
    return rel_ret, rel_dd, rel_sh, eligible, composite


def fmt_row(row):
    b = BASELINE
    rel_ret, rel_dd, rel_sh, elig, comp = score_row(row)
    tag = "✅" if elig else "·"
    return (f"{row['label']:22s} 收益{row['total_return_pct']:+7.1f}%(Δ{rel_ret:+6.1f}) "
            f"回撤{row['max_drawdown_pct']:+6.2f}%(Δ{rel_dd:+5.2f}) 夏普{row['sharpe']:.3f}(Δ{rel_sh:+.3f}) "
            f"胜率{row['win_rate_pct']:.1f}% 交易{row['total_trades']} 综合{comp:+6.1f} {tag}")


if __name__ == "__main__":
    t_all = time.time()
    # ---------- 基线 ----------
    eq0, tr0 = X.run_auto_inhibit(aroon_th=None, mom_th=None)
    s0 = V.summary(eq0, tr0)
    BASELINE = {"label": "baseline", "total_return_pct": float(s0["total_return_pct"]),
                "annual_return_pct": float(s0["annual_return_pct"]),
                "max_drawdown_pct": float(s0["max_drawdown_pct"]),
                "sharpe": float(s0["sharpe"]), "win_rate_pct": float(s0["win_rate_pct"]),
                "total_trades": int(s0["total_trades"])}
    json.dump({"baseline": BASELINE, "results": []}, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"基线: {json.dumps(BASELINE)}", flush=True)

    # ---------- Stage A 粗扫 ----------
    print("== Stage A：aroon × mom 粗扫（fac=0.6）==", flush=True)
    for ath in [15, 25, 35, 45, 55, 65]:
        for mth in [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1]:
            label = f"A{ath}_M{int(mth*100)}"
            try:
                r = metric(label, aroon_th=ath, mom_th=mth, fac=0.6)
            except Exception as e:
                print(f"{label} ERR {e}", flush=True); continue
            print(fmt_row(r), flush=True)
    # 一轮额外的 cap 对照（A45/A55 处 cap59）
    for ath in [35, 45, 55]:
        for mth in [0.6, 0.8]:
            label = f"A{ath}_M{int(mth*100)}_cap59"
            try:
                r = metric(label, aroon_th=ath, mom_th=mth, cap=True)
            except Exception as e:
                print(f"{label} ERR {e}", flush=True); continue
            print(fmt_row(r), flush=True)

    # ---------- 选出 StageA 最优（eligible 里 composite 最高；无 eligible 取 composite 前二）----------
    def ranked():
        return [r for r in RESULTS if r.get("aroon_th") is not None]
    ra = ranked()
    scored = []
    for r in ra:
        rel_ret, rel_dd, rel_sh, elig, comp = score_row(r)
        scored.append((r, rel_ret, rel_dd, rel_sh, elig, comp))
    elig_ok = [x for x in scored if x[4]]
    pool = elig_ok if elig_ok else scored
    pool.sort(key=lambda x: -x[5])
    top2 = pool[:2]
    print(f"StageA 最优区域: {[t[0]['label'] for t in top2]}", flush=True)

    # ---------- Stage B 细扫（最优邻域 + 强度/封顶精调）----------
    print("== Stage B：邻域细扫 + 强度/封顶 ==", flush=True)
    for rr, *_ in top2:
        base_a, base_m = rr["aroon_th"], rr["mom_th"]
        for a in [base_a - 5, base_a, base_a + 5]:
            if a < 10 or a > 70: continue
            for m in [round(base_m - 0.05, 2), base_m, round(base_m + 0.05, 2)]:
                if m < 0.4 or m > 1.2: continue
                lbl = f"A{a}_M{int(m*100)}"
                if not any(x["label"] == lbl and x.get("fac") == 0.6 for x in RESULTS):
                    try:
                        r = metric(lbl, aroon_th=a, mom_th=m, fac=0.6)
                        print(fmt_row(r), flush=True)
                    except Exception as e:
                        print(f"{lbl} ERR {e}", flush=True)
        # 强度粗调（最佳 fac/cap 用当前窗口 feature）
        best_lbl = max(((x for x in RESULTS if x.get("aroon_th") == base_a and x.get("mom_th") == base_m and x.get("fac") == 0.6)),
                       key=lambda x: score_row(x)[4])
        ba, bm = best_lbl["aroon_th"], best_lbl["mom_th"]
        for fac in [0.3, 0.4, 0.5, 0.7, 0.8, 0.9]:
            lbl = f"A{ba}_M{int(bm*100)}_fac{int(fac*10)}"
            try:
                r = metric(lbl, aroon_th=ba, mom_th=bm, fac=fac)
                print(fmt_row(r), flush=True)
            except Exception as e:
                print(f"{lbl} ERR {e}", flush=True)
        for capv in [50, 55, 59]:
            lbl = f"A{ba}_M{int(bm*100)}_cap{capv}"
            if not any(x["label"] == lbl for x in RESULTS):
                try:
                    r = metric(lbl, aroon_th=ba, mom_th=bm, cap=True)
                    print(fmt_row(r), flush=True)
                except Exception as e:
                    print(f"{lbl} ERR {e}", flush=True)

    # ---------- 汇总全局最优 ----------
    allsc = []
    for r in ranked():
        rel_ret, rel_dd, rel_sh, elig, comp = score_row(r)
        allsc.append((r, rel_ret, rel_dd, rel_sh, elig, comp))
    elig_all = [x for x in allsc if x[4]]
    print("\n== 汇总 ==", flush=True)
    print(f"有效组(收益↑&回撤不恶化&夏普↑): {len(elig_all)}/{len(allsc)}", flush=True)
    if elig_all:
        elig_all.sort(key=lambda x: -x[5])
        best = elig_all[0][0]
        print(f"全局最优: {best['label']} 收益{best['total_return_pct']:+.1f}% "
              f"回撤{best['max_drawdown_pct']:+.2f}% 夏普{best['sharpe']:.3f} "
              f"胜率{best['win_rate_pct']:.1f}% 交易{best['total_trades']}", flush=True)
        top3 = [x[0] for x in elig_all[:3]]
    else:
        best = max(allsc, key=lambda x: x[5])[0]
        print(f"无严格有效组；兜底最优: {best['label']}", flush=True)
        top3 = [x[0] for x in sorted(allsc, key=lambda x: -x[5])[:3]]

    # ---------- Stage C：样本外稳健性（OOS 三段）----------
    print("\n== Stage C：OOS 三段稳健性 ==", flush=True)
    oos_segs = [("2016-2019", "2016-01-04", "2019-12-31"),
                ("2020-2021", "2020-01-02", "2021-12-31"),
                ("2022-2026", "2022-01-04", "2026-08-17")]
    oos_out = {}
    for cand in [{"label": "baseline", "kw": {}}] + [{"label": r["label"], "kw": {k: r[k] for k in ("aroon_th", "mom_th", "fac", "cap") if k in r}} for r in top3]:
        key = cand["label"]
        oos_out[key] = {}
        for seg, s_, e_ in oos_segs:
            kw = dict(cand["kw"]); kw["start"] = s_; kw["end"] = e_
            t0 = time.time()
            if kw.get("aroon_th") is not None:
                eq, tr = X.run_auto_inhibit(aroon_th=kw["aroon_th"], mom_th=kw["mom_th"],
                                            start=s_, end=e_, fac=kw.get("fac"), cap=kw.get("cap", False))
            else:
                eq, tr = X.run_auto_inhibit(start=s_, end=e_)
            s = V.summary(eq, tr)
            oos_out[key][seg] = {"total_return_pct": float(s["total_return_pct"]),
                                 "max_drawdown_pct": float(s["max_drawdown_pct"]),
                                 "sharpe": float(s["sharpe"]), "win_rate_pct": float(s["win_rate_pct"]),
                                 "total_trades": int(s["total_trades"]), "secs": int(time.time() - t0)}
            print(f"  {key:22s} {seg}: 收益{s['total_return_pct']:+.1f}% 回撤{s['max_drawdown_pct']:+.2f}% "
                  f"夏普{s['sharpe']:.3f} 胜率{s['win_rate_pct']:.1f}%", flush=True)
        # 相对基线该段对比
        for seg in [x[0] for x in oos_segs]:
            doff = oos_out[key][seg]["max_drawdown_pct"] - oos_out["baseline"][seg]["max_drawdown_pct"]
            print(f"    vs 基线 {seg} Δ回撤{doff:+.2f}", flush=True)
    json.dump({"baseline": BASELINE, "results": RESULTS, "oos": oos_out, "best": best["label"] if best else None,
               "top3": [r["label"] for r in top3], "elapsed_min": round((time.time()-t_all)/60, 1)},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n完成，总耗时 {(time.time()-t_all)/60:.1f} min → {OUT.name}", flush=True)
