# -*- coding: utf-8 -*-
"""Aroon 穷举续跑 2：基于 _aroon_exhaust.py 生成的 aroon_exhaust_results.json
Stage B 在强度精调处崩了（score_row[5] 越界，已修），本脚本：
  ① 补测 A65/A70 邻域（M75/M80/M85 附近 + M70/M90 端点）
  ② A70_M80 / A65_M80 / A65_M90 三个候选的强度 fac 与封顶 cap 精调
  ③ OOS 三段稳健性（2016-2019 / 2020-2021 / 2022-2026）对基线 + top3 候选
产出：aroon_exhaust_results.json（合并）+ aroon_oos.json
"""
import os, sys, time, json
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import v8_selector as V
import _aroon_inhibit_exp as X

OUT = BASE / "aroon_exhaust_results.json"
data = json.load(open(OUT, encoding="utf-8"))
BASELINE = data["baseline"]
RESULTS = data["results"]
seen = {(r["label"], r.get("fac"), r.get("cap")) for r in RESULTS}


def metric(label, **kw):
    t0 = time.time()
    eq, tr = X.run_auto_inhibit(**kw)
    s = V.summary(eq, tr)
    row = {"label": label, **kw,
           "total_return_pct": float(s["total_return_pct"]),
           "annual_return_pct": float(s["annual_return_pct"]),
           "max_drawdown_pct": float(s["max_drawdown_pct"]),
           "sharpe": float(s["sharpe"]),
           "win_rate_pct": float(s["win_rate_pct"]),
           "total_trades": int(s["total_trades"]),
           "secs": int(time.time() - t0)}
    RESULTS.append(row)
    json.dump({"baseline": BASELINE, "results": RESULTS, "oos": data.get("oos"), "best": data.get("best"), "top3": data.get("top3")},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return row


def score_row(row):
    b = BASELINE
    rel_ret = row["total_return_pct"] - b["total_return_pct"]
    rel_dd = row["max_drawdown_pct"] - b["max_drawdown_pct"]
    rel_sh = row["sharpe"] - b["sharpe"]
    eligible = rel_ret > 0 and rel_dd >= 0 and rel_sh >= 0
    composite = rel_ret + 40 * rel_sh + 1.5 * rel_dd
    return rel_ret, rel_dd, rel_sh, eligible, composite


def fmt(row):
    b = BASELINE
    rr, rd, rs, elig, comp = score_row(row)
    tag = "✅" if elig else "·"
    return (f"{row['label']:22s} 收益{row['total_return_pct']:+7.1f}%(Δ{rr:+6.1f}) "
            f"回撤{row['max_drawdown_pct']:+6.2f}%(Δ{rd:+5.2f}) 夏普{row['sharpe']:.3f}(Δ{rs:+.3f}) "
            f"胜率{row['win_rate_pct']:.1f}% 交易{row['total_trades']} 综合{comp:+6.1f} {tag}")


def run_if_new(label, **kw):
    key = (label, kw.get("fac"), kw.get("cap"))
    if key in seen:
        return None
    r = metric(label, **kw)
    seen.add(key)
    print(fmt(r), flush=True)
    return r


if __name__ == "__main__":
    t_all = time.time()
    print(f"已存 {len(RESULTS)} 组，续跑补充网格 + OOS", flush=True)

    # ---------- ① 高阈值邻域补测（A65/A70 的 M70/M75/M80/M85/M90）----------
    print("== ① 高阈值邻域补测 ==", flush=True)
    for a in [60, 65, 70, 75]:
        for m in [0.70, 0.75, 0.80, 0.85, 0.90]:
            label = f"A{a}_M{int(m*100)}"
            r = run_if_new(label, aroon_th=a, mom_th=m, fac=0.6)
            if r is None:
                pass

    # ---------- ② 首选候选强度/封顶精调 ----------
    print("== ② 强度/封顶精调 ==", flush=True)
    for (a, m) in [(70, 0.80), (65, 0.80), (65, 0.90), (70, 0.75), (60, 0.85)]:
        for fac in [0.4, 0.5, 0.7, 0.8]:
            run_if_new(f"A{a}_M{int(m*100)}_fac{int(fac*10)}", aroon_th=a, mom_th=m, fac=fac)
        for capv in [45, 50, 55, 59]:
            run_if_new(f"A{a}_M{int(m*100)}_cap{capv}", aroon_th=a, mom_th=m, cap=True)

    # ---------- 汇总 top 候选 ----------
    candidates = [r for r in RESULTS if r.get("aroon_th") is not None]
    scored = []
    for r in candidates:
        rr, rd, rs, elig, comp = score_row(r)
        scored.append((r, rr, rd, rs, elig, comp))
    elig_all = [x for x in scored if x[4]]
    print(f"\n有效组(收益↑&回撤不恶化&夏普↑): {len(elig_all)}/{len(scored)}", flush=True)
    elig_all.sort(key=lambda x: -x[5])
    print("Top6（综合分）:", flush=True)
    for r, rr, rd, rs, elig, comp in elig_all[:6]:
        print(f"  {r['label']:20s} 收益{r['total_return_pct']:+.1f}% 回撤{r['max_drawdown_pct']:+.2f}% "
              f"夏普{r['sharpe']:.3f} 胜率{r['win_rate_pct']:.1f}% 综合{comp:+.1f}", flush=True)
    top3 = [x[0] for x in elig_all[:3]]
    best = top3[0] if top3 else max(scored, key=lambda x: x[5])[0]
    print(f"全局最优: {best['label']}", flush=True)

    # ---------- ③ OOS 三段稳健性 ----------
    print("\n== ③ OOS 三段稳健性 ==", flush=True)
    oos_segs = [("2016-2019", "2016-01-04", "2019-12-31"),
                ("2020-2021", "2020-01-02", "2021-12-31"),
                ("2022-2026", "2022-01-04", "2026-08-17")]
    oos_out = {}
    cand_list = [{"label": "baseline", "kw": {}, "sel": 0}] + \
                [{"label": r["label"], "kw": {k: r[k] for k in ("aroon_th", "mom_th", "fac", "cap") if k in r}, "sel": i+1}
                 for i, r in enumerate([best] + (top3[1:] if len(top3) > 1 else []))]
    for cand in cand_list:
        key = cand["label"]
        oos_out[key] = {}
        for seg, s_, e_ in oos_segs:
            t0 = time.time()
            if cand["kw"].get("aroon_th") is not None:
                eq, tr = X.run_auto_inhibit(aroon_th=cand["kw"]["aroon_th"], mom_th=cand["kw"]["mom_th"],
                                            start=s_, end=e_, fac=cand["kw"].get("fac"), cap=cand["kw"].get("cap", False))
            else:
                eq, tr = X.run_auto_inhibit(start=s_, end=e_)
            s = V.summary(eq, tr)
            oos_out[key][seg] = {"total_return_pct": float(s["total_return_pct"]),
                                 "max_drawdown_pct": float(s["max_drawdown_pct"]),
                                 "sharpe": float(s["sharpe"]), "win_rate_pct": float(s["win_rate_pct"]),
                                 "total_trades": int(s["total_trades"]), "secs": int(time.time() - t0)}
            print(f"  {key:22s} {seg}: 收益{s['total_return_pct']:+.1f}% 回撤{s['max_drawdown_pct']:+.2f}% "
                  f"夏普{s['sharpe']:.3f} 胜率{s['win_rate_pct']:.1f}%", flush=True)

    # OOS relative vs baseline per segment
    oos_rel = {}
    for key in oos_out:
        oos_rel[key] = {}
        for seg in [x[0] for x in oos_segs]:
            oos_rel[key][seg] = {
                "d_ret": round(oos_out[key][seg]["total_return_pct"] - oos_out["baseline"][seg]["total_return_pct"], 2),
                "d_dd": round(oos_out[key][seg]["max_drawdown_pct"] - oos_out["baseline"][seg]["max_drawdown_pct"], 2),
                "d_sharpe": round(oos_out[key][seg]["sharpe"] - oos_out["baseline"][seg]["sharpe"], 3),
            }
            print(f"    vs基线 {seg}: Δ收益{oos_rel[key][seg]['d_ret']:+.1f}% Δ回撤{oos_rel[key][seg]['d_dd']:+.2f} Δ夏普{oos_rel[key][seg]['d_sharpe']:+.3f}", flush=True)

    # 稳健性判定：候选在 3 段中收益↑ 且 夏普↑ 的段数（越接近 3 越稳健）
    print("\n== 稳健性判定（3 段中『收益↑且夏普↑』的段数）==", flush=True)
    for key in oos_out:
        if key == "baseline":
            continue
        good = sum(1 for seg in [x[0] for x in oos_segs]
                   if oos_rel[key][seg]["d_ret"] > 0 and oos_rel[key][seg]["d_sharpe"] > 0)
        dd_bad = sum(1 for seg in [x[0] for x in oos_segs] if oos_rel[key][seg]["d_dd"] < 0)
        print(f"  {key:22s}: 3 段中 {good}/3 段收益+夏普双升；{dd_bad} 段回撤恶化", flush=True)

    json.dump({"baseline": BASELINE, "results": RESULTS, "oos": oos_out, "oos_rel": oos_rel,
               "best": best["label"], "top3": [r["label"] for r in top3],
               "elapsed_min": round((time.time() - t_all) / 60, 1)},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"oos": oos_out, "oos_rel": oos_rel},
              open(BASE / "aroon_oos.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n完成，总耗时 {time.time()-t_all:.0f}s", flush=True)
