# -*- coding: utf-8 -*-
"""Aroon 两优化方向回测（v9 全量池 · 2016-2026）· 数据选最优
方向1：市场广度门控（上涨占比 adv10 / AD10 等）
方向2：Aroon 阈值连续偏置（按指数年线超额/10日均收益温度线性插值 aroon_th ∈ [60,80]）
对比：基线 / A80_M80 固定
产出：aroon_two_dir_results.json
"""
import os, sys, time, json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import v8_selector as V
import _aroon_inhibit_exp as X

OUT = BASE / "aroon_two_dir_results.json"
STATE = json.load(open(BASE / "_market_state.json", encoding="utf-8"))
COLD = (80, 0.80)


def build_state_map(start, end, get_temp, map_fn):
    """map_fn(temp) -> (aroon_th, mom_th) 或 None(关闭)"""
    cmap = {}
    for dstr, stx in STATE.items():
        if not (start <= dstr <= end):
            continue
        t = get_temp(stx)
        if t is None:
            cmap[dstr] = COLD
            continue
        cmap[dstr] = map_fn(t)
    return cmap


def run_kw(label, start, end, cmap=None, aroon_th=None, mom_th=None, fac=0.6):
    t0 = time.time()
    if cmap is not None:
        eq, tr = X.run_auto_inhibit(start=start, end=end, aroon_th_map=cmap)
    else:
        eq, tr = X.run_auto_inhibit(start=start, end=end, aroon_th=aroon_th,
                                    mom_th=mom_th, fac=fac)
    s = V.summary(eq, tr)
    return {"label": label, "total_return_pct": float(s["total_return_pct"]),
            "annual_return_pct": float(s["annual_return_pct"]),
            "max_drawdown_pct": float(s["max_drawdown_pct"]), "sharpe": float(s["sharpe"]),
            "win_rate_pct": float(s["win_rate_pct"]), "total_trades": int(s["total_trades"]),
            "secs": int(time.time() - t0)}


def temps():
    return {
        "idx_ma200_pos": lambda stx: stx["idx_ma200_pos"],
        "meanret10": lambda stx: stx["meanret10"],
        "adv10": lambda stx: stx["adv10"],
        "ad10": lambda stx: stx["ad10"],
    }


if __name__ == "__main__":
    FULL = ("2016-01-04", "2026-08-17")
    SEGS = [("2016-2019", "2016-01-04", "2019-12-31"),
            ("2020-2021", "2020-01-02", "2021-12-31"),
            ("2022-2026", "2022-01-04", "2026-08-17")]

    candidates = {}   # label -> dict(full_kw, oos_kw_factory)

    # ---------- 方向1：广度门控 ----------
    # D1a: adv10>0.55 → 关闭；否则 A80
    candidates["D1_adv10_OFF"] = "adv10"
    candidates["D1_ad10_OFF"] = "ad10"
    # 阈值：>0.55 关闭抑制

    # ---------- 方向2：连续偏置 ----------
    # 温度 idx_ma200_pos：aroon_th = clip(80 - k*max(0,t), 60, 80)
    # 温度 meanret10：aroon_th = clip(80 - k*max(0,t*100), 60, 80)

    # ---------- 全样本扫描 ----------
    print("== 全样本 2016-2026 ==", flush=True)
    full_res = {}
    full_res["baseline"] = run_kw("baseline", *FULL, aroon_th=None, mom_th=None)
    print(f"baseline: 收益{full_res['baseline']['total_return_pct']:+.1f}% 回撤{full_res['baseline']['max_drawdown_pct']:+.2f}% 夏普{full_res['baseline']['sharpe']:.3f} 胜率{full_res['baseline']['win_rate_pct']:.1f}%", flush=True)
    full_res["A80_M80固定"] = run_kw("A80_M80固定", *FULL, aroon_th=80, mom_th=0.8)
    print(f"A80_M80固定: 收益{full_res['A80_M80固定']['total_return_pct']:+.1f}% 回撤{full_res['A80_M80固定']['max_drawdown_pct']:+.2f}% 夏普{full_res['A80_M80固定']['sharpe']:.3f} 胜率{full_res['A80_M80固定']['win_rate_pct']:.1f}%", flush=True)

    json.dump({"partial": full_res}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    variants = []
    # D1 广度
    for key in ["adv10", "ad10"]:
        for thr, off_lbl in [(0.55, "OFF"), (0.60, "OFF")]:
            variants.append((f"D1_{key}{int(thr*100)}_{off_lbl}", ("D1", key, thr, None)))
    # D2 连续偏置（温度=idx_ma200_pos / meanret10，k=斜率）
    for tkey in ["idx_ma200_pos", "meanret10"]:
        for k in [100, 200, 333]:
            variants.append((f"D2_{tkey}_k{k}", ("D2", tkey, k, None)))

    d1_configs = {}
    d2_configs = {}
    for label, spec in variants:
        typ = spec[0]
        if typ == "D1":
            _, key, thr, _off = spec
            cmap = build_state_map(*FULL, temps()[key],
                                   lambda t: None if (t is not None and t > thr) else COLD)
            r = run_kw(label, *FULL, cmap=cmap)
            d1_configs[label] = {"key": key, "thr": thr, "cmap_built": True}
        else:
            _, tkey, k, _ = spec

            def _map(t, tkey=tkey, k=k):
                if t is None:
                    return COLD
                if tkey == "idx_ma200_pos":
                    temp = max(0.0, t)
                    ath = 80 - k * temp
                else:
                    temp = max(0.0, t * 100.0)
                    ath = 80 - k * temp
                ath = max(60.0, min(80.0, ath))
                return (round(ath), 0.80)

            cmap = build_state_map(*FULL, temps()[tkey], _map)
            r = run_kw(label, *FULL, cmap=cmap)
            d2_configs[label] = {"tkey": tkey, "k": k}
        full_res[label] = r
        print(f"{label:22s} 收益{r['total_return_pct']:+8.1f}% 回撤{r['max_drawdown_pct']:+6.2f}% 夏普{r['sharpe']:.3f} 胜率{r['win_rate_pct']:.1f}% 交易{r['total_trades']} [{r['secs']}s]", flush=True)
    json.dump({"partial": full_res}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 评分：相对基线 及 相对 A80
    b = full_res["baseline"]; a80 = full_res["A80_M80固定"]
    ranked = []
    for label in variants:
        label = label[0]
        r = full_res[label]
        # 综合分：相对A80的收益增量 + 夏普增量 - 回撤恶化
        rel_ret = r["total_return_pct"] - a80["total_return_pct"]
        rel_dd = r["max_drawdown_pct"] - a80["max_drawdown_pct"]
        rel_sh = r["sharpe"] - a80["sharpe"]
        comp = rel_ret + 40 * rel_sh + 1.5 * rel_dd
        ranked.append((label, r, rel_ret, rel_dd, rel_sh, comp))
    ranked.sort(key=lambda x: -x[5])
    print("\n综合分排序（vs A80）:", flush=True)
    for label, r, rr, rd, rs, comp in ranked:
        print(f"  {label:22s} Δ收益{rr:+6.1f} Δ回撤{rd:+5.2f} Δ夏普{rs:+.3f} 综合{comp:+6.1f}", flush=True)

    # 选 top2 做 OOS（若都不如 A80，选最接近的2个）
    top2_labels = [x[0] for x in ranked[:2]]
    print(f"进入 OOS: {top2_labels}", flush=True)

    # ---------- OOS ----------
    print("\n== OOS 三段 ==", flush=True)
    oos = {}
    for lbl in ["baseline", "A80_M80固定"] + top2_labels:
        oos[lbl] = {}
        for seg, s_, e_ in SEGS:
            if lbl == "baseline":
                r = run_kw(lbl, s_, e_, aroon_th=None, mom_th=None)
            elif lbl == "A80_M80固定":
                r = run_kw(lbl, s_, e_, aroon_th=80, mom_th=0.8)
            else:
                # 重建区间 cmap
                if lbl in d1_configs:
                    cfg = d1_configs[lbl]
                    cmap = build_state_map(s_, e_, temps()[cfg["key"]],
                                           lambda t: None if (t is not None and t > cfg["thr"]) else COLD)
                else:
                    cfg = d2_configs[lbl]
                    tkey, k = cfg["tkey"], cfg["k"]
                    def _map(t, tkey=tkey, k=k):
                        if t is None:
                            return COLD
                        temp = max(0.0, t * 100.0) if tkey == "meanret10" else max(0.0, t)
                        ath = max(60.0, min(80.0, 80 - k * temp))
                        return (round(ath), 0.80)
                    cmap = build_state_map(s_, e_, temps()[tkey], _map)
                r = run_kw(lbl, s_, e_, cmap=cmap)
            oos[lbl][seg] = r
            print(f"  {lbl:22s} {seg}: 收益{r['total_return_pct']:+7.1f}% 回撤{r['max_drawdown_pct']:+6.2f}% 夏普{r['sharpe']:.3f} 胜率{r['win_rate_pct']:.1f}% 交易{r['total_trades']} [{r['secs']}s]", flush=True)

    # 判定
    print("\n== 判定（vs 基线 / vs A80）==", flush=True)
    judge = {}
    for lbl in ["A80_M80固定"] + top2_labels:
        gb = ga = 0; db = da = 0
        for seg, _, _ in SEGS:
            dr_b = oos[lbl][seg]["total_return_pct"] - oos["baseline"][seg]["total_return_pct"]
            ds_b = oos[lbl][seg]["sharpe"] - oos["baseline"][seg]["sharpe"]
            dr_a = oos[lbl][seg]["total_return_pct"] - oos["A80_M80固定"][seg]["total_return_pct"]
            dd_a = oos[lbl][seg]["max_drawdown_pct"] - oos["A80_M80固定"][seg]["max_drawdown_pct"]
            if dr_b > 0 and ds_b > 0: gb += 1
            if dr_a > 0: ga += 1
            if dr_b < -5: db += 1
            if dd_a < 0: da += 1
        judge[lbl] = {"vs_base": gb, "vs_a80": ga, "subA80_dd": da}
        print(f"  {lbl:22s} vs基线 {gb}/3 段收益+夏普双升（{db} 段差<5）; vs A80 {ga}/3 段收益更高; 回撤逊 A80 {da} 段", flush=True)

    json.dump({"full": full_res, "oos": oos, "top2": top2_labels, "judge": judge,
               "d1_configs": d1_configs, "d2_configs": d2_configs},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n完成 → {OUT.name}", flush=True)
