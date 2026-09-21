# -*- coding: utf-8 -*-
"""「触发即清仓」反向阀实现 + 网格（XBSY-FLAT-0921 · 用户 2026-09-21 要求补）
================================================================================
背景
--------------------------------------------------------------------------------
XBSY-VALVE-0921 里的 A1c/A2c/A3c 三档「触发即清仓」**未实现**（只过滤了入场，没写强制平仓），
读数与不清仓档逐位相同 = 重复行（第十七章缺陷③）。本脚本补上那个模拟器。

新增模拟器语义（`sim_rank_flat`）
--------------------------------------------------------------------------------
在 `ABL.sim_rank` 基础上增加 `valve_ok[t]`（**t 日收盘**判定）：
  valve_ok[t] == False  → **t+1 开盘**：① 全部持仓无条件平仓 ② 不开新仓
  valve_ok[t] == True   → 正常（规则出场 / 上限到期 / 开盘买）
其余口径与既有模拟器完全一致（滑点 20bp/边、佣金 2.5bp 最低 5 元、整手、等权、排序键）。

预注册
--------------------------------------------------------------------------------
- 清仓族：A1c（沪深300>MA20）/ A2c（>MA60）/ A3c（>MA250） × B 族 7 档 = **21 格**
- 对照：同 (A,B) 的**不清仓**档（XBSY-VALVE-0921 已测，直接读旧 JSON）
- 随机清仓对照：**同样清仓日数**的随机交易日，**50 次** → 得噪声地板（清仓族是否超随机）
- 判据（全过才算「清仓有增量」）：
  ① 相对**同阀不清仓**档：最大回撤改善 ≥5pp 或 夏普改善 ≥0.05
  ② 回撤改善 ≥ 随机清仓对照的最大改善
  ③ 年化 ≥ 沪深300 同窗 +2.46%
- 配置同前：入场 A_tdx；出场 爆量≥2×MA(V,20)+次日阴线(cap250)；17 万/20 仓；排序键 代码序；
  主板面板 2016-01-04 → 2026-09-18

用法：cd quant-weight-system && python backtest/xbsy_flat_0921.py
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
import xbsy_exit_0921 as E                                  # noqa: E402
import xbsy_port_0921 as PORT                               # noqa: E402
import xbsy_abl_0921 as ABL                                 # noqa: E402
import xbsy_valve_0921 as VLV                               # noqa: E402

OUT_JSON = str(HERE / "xbsy_flat_0921.json")
CFG = dict(boom="q2", lag=1, ma5=False, ma10=False, cap=250)
NAV0, NSLOT = 170000.0, 20
DRAWS = 50
SEED = 20260921
HS300_CAGR = 0.0246


def sim_rank_flat(P, V, SIG, keymat, desc, cfg, max_pos, valve_ok, seed=SEED):
    """ABL.sim_rank + 强制清仓：valve_ok[t]==False → t+1 开盘全平且不开新仓。"""
    O = P["open"].astype(np.float64)
    C = P["close"].astype(np.float64)
    M = P["mask"]
    T, N = C.shape
    NX = E.exit_day_matrix(O, C, V, cfg)

    cand = {}
    for t in range(T - 1):
        idx = np.nonzero(SIG[t] & M[t])[0]
        if idx.size:
            cand[t] = idx

    cash = NAV0
    pos = {}
    nav_hist = np.full(T, np.nan)
    trades = []
    rng = np.random.default_rng(seed)
    forced = 0

    for t in range(T):
        flat_today = (t >= 1) and (not bool(valve_ok[t - 1]))     # 前一日收盘阀失败 → 今开盘全平
        # 1) 开盘卖：规则出场 + （若阀失败）强制全部
        exits = [x for x, p in pos.items() if (p["sell_day"] == t and p["sell_at"] == "open")]
        if flat_today:
            exits = list(pos.keys())                              # 全部持仓（含原定收盘出场的）
        for c in exits:
            p = pos.pop(c)
            px = O[t, c] if (np.isfinite(O[t, c]) and O[t, c] > 0) else C[t, c]
            if not (np.isfinite(px) and px > 0):
                continue
            sp = px * (1 - PORT.SLIP)
            amt = sp * p["shares"]
            cash += amt - max(amt * PORT.COMM, PORT.MIN_COMM)
            trades.append({"in": p["date"], "out": t, "ret": sp / p["px"] - 1 - 2 * PORT.COMM,
                           "forced": bool(flat_today)})
            if flat_today:
                forced += 1
        # 2) 开盘买（阀失败当日不开新仓）
        idx = cand.get(t - 1)
        if idx is not None and not flat_today:
            free = max_pos - len(pos)
            if free > 0:
                av = np.array([i for i in idx if i not in pos
                               and np.isfinite(O[t, i]) and O[t, i] > 0])
                if av.size:
                    if keymat is None:
                        order = av
                    else:
                        k = keymat[t - 1, av]
                        k = np.where(np.isfinite(k), k, np.inf if not desc else -np.inf)
                        order = av[np.argsort(-k if desc else k, kind="stable")]
                    navp = nav_hist[t - 1] if np.isfinite(nav_hist[t - 1]) else NAV0
                    for i in order[:free]:
                        budget = min(cash, navp / max_pos)
                        px = O[t, i] * (1 + PORT.SLIP)
                        sh = int(budget // (px * 100)) * 100
                        if sh < 100:
                            continue
                        amt = sh * px
                        fee = max(amt * PORT.COMM, PORT.MIN_COMM)
                        if amt + fee > cash:
                            continue
                        cash -= amt + fee
                        sd = int(NX[t, i]); capd = min(t + cfg["cap"], T - 1)
                        pos[i] = dict(shares=sh, px=px, date=t,
                                      sell_day=sd if sd <= capd else capd,
                                      sell_at="open" if sd <= capd else "close")
        # 3) 收盘卖（上限到期；阀失败已被开盘全平覆盖，此处自然为空）
        for c in [x for x, p in pos.items() if p["sell_day"] == t and p["sell_at"] == "close"]:
            p = pos.pop(c)
            px = C[t, c]
            if not (np.isfinite(px) and px > 0):
                continue
            sp = px * (1 - PORT.SLIP)
            amt = sp * p["shares"]
            cash += amt - max(amt * PORT.COMM, PORT.MIN_COMM)
            trades.append({"in": p["date"], "out": t, "ret": sp / p["px"] - 1 - 2 * PORT.COMM,
                           "forced": False})
        mv = 0.0
        for c, p in pos.items():
            px = C[t, c]
            if np.isfinite(px):
                mv += p["shares"] * px
        nav_hist[t] = cash + mv
    return nav_hist, trades, forced


def main():
    t0 = time.time()
    print("=" * 120)
    print("「触发即清仓」反向阀（XBSY-FLAT-0921）· 17 万/20 仓 · 主板 2016-2026")
    print("=" * 120)
    P = FG.load_panel(X.PANEL)
    D = np.load(X.PANEL, allow_pickle=True)
    codes, cal = D["codes"], D["cal"]
    VLV.cal_ref = [str(x) for x in cal]
    V = X.load_volume([str(c) for c in codes], VLV.cal_ref)
    T, N = P["close"].shape
    SIG0 = X.build_arms(P, V)["A_tdx"]
    F = VLV.build_factors(P, V)
    IX = VLV.idx_factors(VLV.cal_ref)
    print(f"面板 {T} 日 × {N} 只 | 基线信号 {int(SIG0.sum()):,}")

    VALVES = {"A1c hs300>MA20·清仓": IX["above20"],
              "A2c hs300>MA60·清仓": IX["above60"],
              "A3c hs300>MA250·清仓": IX["above250"]}
    BASEKEY = {"A1c hs300>MA20·清仓": "A1 hs300>MA20", "A2c hs300>MA60·清仓": "A2 hs300>MA60",
               "A3c hs300>MA250·清仓": "A3 hs300>MA250"}
    B = {"B0 无阀": np.ones((T, N), dtype=bool),
         "B1 个股波动率<中位": np.where(np.isfinite(F["vol20"]),
                                       F["vol20"] < np.nanmedian(F["vol20"], axis=1)[:, None], False),
         "B2 乖离MA20≤10%": np.where(np.isfinite(F["dev20"]), F["dev20"] <= 10.0, False),
         "B3 20日涨幅≤50%": np.where(np.isfinite(F["ret20"]), F["ret20"] <= 0.50, False),
         "B4 MA20>MA60": np.where(np.isfinite(F["ma60"]), F["ma20"] > F["ma60"], False),
         "B5 RSI14≤70": np.where(np.isfinite(F["rsi"]), F["rsi"] <= 70.0, False),
         "B6 收盘≥5元": np.where(np.isfinite(F["C"]), F["C"] >= 5.0, False)}

    PORT.NAV0 = NAV0
    nav_b, tr_b = ABL.sim_rank(P, V, SIG0, None, False, CFG, NSLOT)
    mb = PORT.metrics(nav_b, VLV.cal_ref, tr_b, "base")
    print(f"基线（无阀）: 年化 {mb['cagr']:+.2%}  夏普 {mb['sharpe']:.3f}  回撤 {mb['max_drawdown']:.2%}  "
          f"笔数 {mb['n_trades']}")
    old = json.load(open(HERE / "xbsy_valve_0921.json", encoding="utf-8"))["grid"]
    out = {"base": mb, "cells": {}, "control": {}, "notes": [
        "清仓实现=valve_ok[t]==False → t+1 开盘全平且不开新仓（收盘判定）",
        f"随机清仓对照 {DRAWS} 次/阀，同清仓日数"]}

    print("\n" + "-" * 120)
    print("① 清仓族 3 × 7 = 21 格（并与同阀不清仓档对比）")
    print("-" * 120)
    hdr = (f"  {'阀':<22}{'个股阀':<20}{'笔数':>6}{'强制平':>7}{'年化':>9}{'夏普':>8}{'最大回撤':>10}"
           f"{'Δ夏普':>8}{'Δ回撤':>9}  对照档(不清仓)")
    print(hdr); print("  " + "-" * (len(hdr) - 2))
    rows = []
    for vname, ok in VALVES.items():
        for bname, bmask in B.items():
            SIG = SIG0 & np.repeat(np.asarray(ok, dtype=bool)[:, None], N, axis=1) & bmask
            if int(SIG.sum()) < 50:
                continue
            nav, tr, forced = sim_rank_flat(P, V, SIG, None, False, CFG, NSLOT, ok)
            m = PORT.metrics(nav, VLV.cal_ref, tr, "x")
            ref = old.get(f"{BASEKEY[vname]}|{bname}")
            d_sh = (m["sharpe"] - ref["sharpe"]) if ref else None
            d_md = (m["max_drawdown"] - ref["max_drawdown"]) if ref else None
            rec = {**m, "forced_sells": forced, "ref_sharpe": ref["sharpe"] if ref else None,
                   "ref_mdd": ref["max_drawdown"] if ref else None,
                   "d_sharpe": round(d_sh, 4) if d_sh is not None else None,
                   "d_mdd": round(d_md, 4) if d_md is not None else None}
            out["cells"][f"{vname}|{bname}"] = rec
            rows.append((vname, bname, rec))
            print(f"  {vname:<22}{bname:<20}{m['n_trades']:>6}{forced:>7}{m['cagr']:>9.2%}"
                  f"{m['sharpe']:>8.3f}{m['max_drawdown']:>10.2%}"
                  f"{d_sh:>+8.3f}{d_md:>+9.2%}  {ref['sharpe']:.3f}/{ref['max_drawdown']:.2%}")

    print("\n" + "-" * 120)
    print(f"② 随机清仓对照（{DRAWS} 次/阀，同清仓日数）—— 噪声地板")
    print("-" * 120)
    rng = np.random.default_rng(SEED)
    for vname, ok in VALVES.items():
        nclear = int((~np.asarray(ok, dtype=bool)).sum())
        bmask = np.ones((T, N), dtype=bool)
        SIG = SIG0 & np.repeat(np.asarray(ok, dtype=bool)[:, None], N, axis=1)
        nav, tr, _ = sim_rank_flat(P, V, SIG, None, False, CFG, NSLOT, ok)
        m = PORT.metrics(nav, VLV.cal_ref, tr, "x")
        cand_days = np.arange(1, T)
        ds, dm = [], []
        for _ in range(DRAWS):
            pick = rng.choice(cand_days, size=min(nclear, cand_days.size), replace=False)
            rok = np.ones(T, dtype=bool); rok[pick] = False
            nav2, tr2, _ = sim_rank_flat(P, V, SIG, None, False, CFG, NSLOT, rok)
            m2 = PORT.metrics(nav2, VLV.cal_ref, tr2, "x")
            ds.append(m2["sharpe"]); dm.append(m2["max_drawdown"])
        ds, dm = np.array(ds), np.array(dm)
        rec = {"n_clear_days": nclear, "sharpe_max": round(float(ds.max()), 4),
               "sharpe_mean": round(float(ds.mean()), 4),
               "imp_max": round(float(dm.max() - mb["max_drawdown"]), 4),
               "mdd_mean": round(float(dm.mean()), 4),
               "pct_sharpe_ge_structured": round(float((ds >= m["sharpe"]).mean()), 4)}
        out["control"][vname] = {**rec, "structured_sharpe": m["sharpe"],
                                 "structured_mdd": m["max_drawdown"]}
        print(f"  {vname:<22} 清仓日 {nclear:>4}  随机夏普 均值 {ds.mean():.3f} 最大 {ds.max():.3f}"
              f"  → 结构化 {m['sharpe']:.3f}  超随机比例 {1-rec['pct_sharpe_ge_structured']:.0%}")
        print(f"  {'':<22} 随机回撤 均值 {dm.mean():.2%} 最好 {dm.max():.2%}"
              f"  → 随机最大改善 {rec['imp_max']:+.2%}")

    thr_imp = max(v["imp_max"] for v in out["control"].values())
    thr_sh = max(v["sharpe_max"] for v in out["control"].values())
    print("\n" + "-" * 120)
    print("③ 三重门（①相对同阀不清仓：Δ回撤≥5pp 或 Δ夏普≥0.05 ②超随机清仓最大值 ③年化≥沪深300）")
    print("-" * 120)
    print(f"  随机清仓门槛：最大改善 {thr_imp:+.2%} | 最大夏普 {thr_sh:.3f}")
    passed = []
    for vname, bname, r in rows:
        g1 = (r["d_mdd"] is not None and r["d_mdd"] >= 0.05) or (r["d_sharpe"] is not None and r["d_sharpe"] >= 0.05)
        g2 = (r["d_mdd"] is not None and r["d_mdd"] >= thr_imp) or r["sharpe"] >= thr_sh
        g3 = r["cagr"] >= HS300_CAGR
        if g1 and g2 and g3:
            passed.append((vname, bname, r))
    if passed:
        for v, b, r in sorted(passed, key=lambda x: -x[2]["sharpe"]):
            print(f"  ✅ {v} | {b}  年化 {r['cagr']:+.2%} 夏普 {r['sharpe']:.3f} 回撤 {r['max_drawdown']:.2%}"
                  f" Δ夏普 {r['d_sharpe']:+.3f} Δ回撤 {r['d_mdd']:+.2%} 笔数 {r['n_trades']}")
    else:
        print("  ❌ 无格通过三重门")
    out["passed"] = [f"{v}|{b}" for v, b, _ in passed]
    out["thresholds"] = {"imp": thr_imp, "sharpe": thr_sh}

    out["elapsed_s"] = round(time.time() - t0, 1)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n结果已落盘 {OUT_JSON}（{out['elapsed_s']}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())