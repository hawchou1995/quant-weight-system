# -*- coding: utf-8 -*-
"""audit_orderflow_099_20260928.py — 核实「挂单 前收×0.99」与「以开盘价成交」是否等价

问题（用户提出）：缩量超跌定义的是**挂单 0.99×前收 买入**，但看板上写的是**开盘竞价原价买入**。

核实口径（只读，不改任何生产文件）：
  · 信号/资格池 = 冻结脚本 oos_run.py 原样运行（**复用 hpdk_candidates 的 replay/features**，同一把尺子）
  · 「资格池」= 把低开带放宽到不约束（P1=-1.0 / P2=+10.0，K 不限）后当日通过 elig 的全部标的，按复合分降序
  · 挂单价 L = round(前收 × 0.99, 2)（与 watch_next.py 的 limit_099 同式、同 2 位小数取整）

三种开盘情形（T+1 相对 T 收的开盘跳空 gap = O(t+1)/C(t) − 1）：
  A) gap ≤ −3%          → 09:15–09:20 按虚拟开盘价**撤单**（现行流程已覆盖）
  B) −3% < gap ≤ −1%    → 集合竞价**以开盘价成交**（= 模型口径，现行流程已覆盖）
  C) gap > −1%          → **集合竞价不会成交**（限价 0.99 高于开盘价）……
                         但委托**仍留在盘口**；若当日 low ≤ L 则**盘中以 L 成交** ← 模型假设完全不成交
                         现行流程**没有**针对 C 的撤单步骤（只有"跌幅>3%"那一条）

对 C 且盘中触及的委托，按 v1.3 出场口径（止盈 +2%：T+2 开/高触发，否则 T+2 尾盘）计算**假想净收益**，
用来说明这个缺口是"无害的冗余"还是"真会亏钱的漏口"。

用法: python audit_orderflow_099_20260928.py [--cache DIR] [--out FILE]
"""
import argparse
import json
import os
import pathlib
import sys
import time

import numpy as np

D = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(D))
import hpdk_candidates as HC  # noqa: E402   （复用：load_mod / get_panel / replay / features / zs）

COST_SIDE = 0.000346
TP = 0.02
TOPKS = (10, 20)


def log(*a):
    print(*a, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.environ.get("PI_SCRATCH_DIR") or str(D))
    ap.add_argument("--out", default=str(D / "evidence_orderflow_099_20260928.json"))
    a = ap.parse_args()
    t0 = time.time()
    cache = pathlib.Path(a.cache)

    mod = HC.load_mod()
    sha = mod.FROZEN_SHA
    log("[spec] oos_run.py SHA256 = %s" % sha)
    cal, syms, F = HC.get_panel(mod, cache)          # HC 版只返回 3 个值（无 done）
    T, N = F["C"].shape
    done = int(np.sum(np.any(np.isfinite(F["C"]) & (F["C"] > 0), axis=0)))
    log("[panel] T=%d N=%d names_loaded=%d" % (T, N, done))
    jof = {s: j for j, s in enumerate(syms)}

    # ---- 资格池（低开带放宽）：同一把尺子 ----
    # ⚠ HC.replay 会**就地** mod.P.update(overrides) 且不重置 → 两次调用之间必须显式复位 BASE_P，
    #   否则「冻结」那次会继承上一次的放宽带（hpdk_candidates.py 自己是 frozen 先跑、wide 后跑，故无此问题）。
    WIDE_P1 = getattr(HC, "WIDE_P1", -1.0)
    WIDE_P2 = getattr(HC, "WIDE_P2", 10.0)
    BASE_P = dict(P1=0.01, P2=0.03, K=10, KSLOT=20, MINAMT=2e7, MINPX=3.0, LISTED=250,
                  TP=TP, COST_SIDE=COST_SIDE, SHADOW_START="2016-01-01",
                  WORST_CASE_WIPEOUT=True, MAINBOARD=True,
                  VOLBR_MIN=0.0, VOLBR_MAX=1e9, RR_MIN=0.0,
                 # 【勘误 E-22 · 2026-09-29】原写 STNOW_OFF=True（= 当时的默认「不用现名过滤」）。
                 # E-22 后默认 = 「现名过滤只作用于在售票 + 代理加 5% 钉板计数」⇒ 若继续写
                 # STNOW_OFF=True 会**反转语义**（完全关掉现名过滤），使本审计与生产口径不一致。
                 # 故改为显式跟随新默认：STNOW_OFF=False + STNOW_LIVE_ONLY=True + STP_CNT=3。
                 STNOW_OFF=False, STNOW_LIVE_ONLY=True, STP_CNT=3)

    def run(tag, ov):
        mod.P.clear(); mod.P.update(BASE_P)
        return HC.replay(mod, cache, tag, ov, F, done, start="2016-01-01")

    frozen = run("audit99_frozen", {})                                   # 先跑冻结（K=10、带内）
    wide = run("audit99_wide", {"P1": WIDE_P1, "P2": WIDE_P2, "K": 10 ** 9})   # 再放宽取资格池
    log("[replay] 冻结信号 %d 条 / 资格池 %d 条（%.0fs）" % (len(frozen), len(wide), time.time() - t0))

    FZ = dict(P1=0.01, P2=0.03, K=10, KSLOT=20, MINAMT=2e7, MINPX=3.0, LISTED=250,
              TP=TP, COST_SIDE=COST_SIDE)
    ft = HC.features(F, FZ)
    GAP, VALID = ft["GAP"], ft["VALID"]
    O, H, L, C = F["O"], F["H"], F["L"], F["C"]
    cix = {d: i for i, d in enumerate(cal)}

    by_day_w = {}
    for r in wide:
        by_day_w.setdefault(r["signal_date"], []).append(r["sym"])

    # ---- 同尺子锚点：冻结信号 = 资格池内「带内子集」按复合分降序的前 K ----
    anchor = dict(days_compared=0, days_bitwise_equal=0, mismatches=[])
    for d, pk in sorted({r["signal_date"]: None for r in frozen}.items())[-25:]:
        i = cix.get(d)
        if i is None:
            continue
        g = GAP[i]
        cand = [s for s in by_day_w.get(d, []) if np.isfinite(g[jof[s]]) and -0.03 <= g[jof[s]] <= -0.01]
        if not cand:
            continue
        amt = np.array([ft["AMT20"][i, jof[s]] for s in cand])
        vbr = np.array([ft["VOLBR"][i, jof[s]] for s in cand])
        r20 = np.array([ft["RET20"][i, jof[s]] for s in cand])
        with np.errstate(all="ignore"):
            comp = HC.zs(-np.log(amt)) + HC.zs(-np.log(vbr)) + HC.zs(-r20)
        mine = [cand[q] for q in np.argsort(-comp)[:10]]
        theirs = [r["sym"] for r in frozen if r["signal_date"] == d][:10]
        anchor["days_compared"] += 1
        if mine == theirs:
            anchor["days_bitwise_equal"] += 1
        elif len(anchor["mismatches"]) < 5:
            anchor["mismatches"].append(dict(date=d, mine=mine[:5], theirs=theirs[:5]))
    log("[anchor] 冻结 top-10 vs 本脚本复算：%d/%d 日完全一致"
        % (anchor["days_bitwise_equal"], anchor["days_compared"]))

    # ---- 三情形分桶 ----
    def bucket(g):
        if not np.isfinite(g):
            return "invalid"
        if g <= -0.03:
            return "A_deep_cancel"          # 深低开 → 现行流程撤单
        if g <= -0.01:
            return "B_inband_fill"          # 带内 → 竞价以开盘价成交
        return "C_shallow_stays"            # 低开不足/高开 → 竞价不成交，委托留存

    rows = []
    for d, lst in by_day_w.items():
        i = cix.get(d)
        if i is None or i + 2 >= T:
            continue
        for rank, s in enumerate(lst):
            j = jof.get(s)
            if j is None:
                continue
            g = float(GAP[i, j]) if np.isfinite(GAP[i, j]) else float("nan")
            bk = bucket(g)
            rec = dict(date=d, sym=s, rank=rank, gap_pct=round(g * 100, 3) if np.isfinite(g) else None,
                       bucket=bk)
            if bk == "C_shallow_stays":
                c0 = float(C[i, j])
                lim = round(c0 * 0.99, 2)                       # 与 watch_next.limit_099 同式
                lo = float(L[i + 1, j]); hi = float(H[i + 1, j]); o1 = float(O[i + 1, j])
                rec["limit_099"] = lim
                rec["touched"] = bool(np.isfinite(lo) and lo > 0 and lo <= lim)
                if rec["touched"]:
                    entry = lim
                    tp_lv = entry * (1.0 + TP)
                    o2, h2, c2 = float(O[i + 2, j]), float(H[i + 2, j]), float(C[i + 2, j])
                    if np.isfinite(c2) and c2 > 0:
                        if np.isfinite(o2) and o2 >= tp_lv:
                            ex, src = o2, "tp_open"
                        elif np.isfinite(h2) and h2 >= tp_lv:
                            ex, src = tp_lv, "tp_high"
                        else:
                            ex, src = c2, "t2_close"
                        rec["net_pct"] = round((ex * (1 - COST_SIDE) / (entry * (1 + COST_SIDE)) - 1) * 100, 4)
                        rec["exit_src"] = src
                    else:
                        rec["net_pct"] = -100.0
                        rec["exit_src"] = "wipeout"
            rows.append(rec)

    def summarize(sel):
        n = len(sel)
        if n == 0:
            return dict(n=0)
        cnt = {k: sum(1 for r in sel if r["bucket"] == k)
               for k in ("A_deep_cancel", "B_inband_fill", "C_shallow_stays", "invalid")}
        cset = [r for r in sel if r["bucket"] == "C_shallow_stays"]
        touched = [r for r in cset if r.get("touched")]
        rets = np.array([r["net_pct"] for r in touched if r.get("net_pct") is not None], float)
        return dict(n=n,
                    A_deep_cancel=cnt["A_deep_cancel"], A_pct=round(100 * cnt["A_deep_cancel"] / n, 2),
                    B_inband_fill=cnt["B_inband_fill"], B_pct=round(100 * cnt["B_inband_fill"] / n, 2),
                    C_shallow_stays=cnt["C_shallow_stays"], C_pct=round(100 * cnt["C_shallow_stays"] / n, 2),
                    invalid=cnt["invalid"],
                    C_touched=len(touched),
                    C_touched_pct_of_C=round(100 * len(touched) / max(1, len(cset)), 2),
                    C_touched_pct_of_all=round(100 * len(touched) / n, 2),
                    C_fill_net_mean_pct=round(float(rets.mean()), 4) if rets.size else None,
                    C_fill_net_med_pct=round(float(np.median(rets)), 4) if rets.size else None,
                    C_fill_win_rate=round(float(100 * (rets > 0).mean()), 2) if rets.size else None,
                    C_fill_worst_pct=round(float(rets.min()), 4) if rets.size else None)

    out = dict(all=summarize(rows))
    for k in TOPKS:
        out["top%d" % k] = summarize([r for r in rows if r["rank"] < k])

    # 按年看 C 的占比（是否随时间变化）
    yr = {}
    for r in rows:
        yr.setdefault(r["date"][:4], []).append(r)
    yearly = {y: dict(n=len(v),
                      C_pct=round(100 * sum(1 for r in v if r["bucket"] == "C_shallow_stays") / len(v), 2),
                      B_pct=round(100 * sum(1 for r in v if r["bucket"] == "B_inband_fill") / len(v), 2))
              for y, v in sorted(yr.items())}

    payload = dict(generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                   purpose="核实「挂单 前收×0.99」与「以开盘价成交」是否等价；量化缺口情形 C",
                   frozen_script_sha256=sha, panel=dict(T=T, N=N, names_loaded=done),
                   cost_side=COST_SIDE, tp=TP,
                   limit_rule="round(前收 × 0.99, 2)（与 watch_next.py limit_099 同式）",
                   anchor=anchor, summary=out, yearly=yearly,
                   samples_C=[r for r in rows if r["bucket"] == "C_shallow_stays" and r.get("touched")][:12],
                   runtime_sec=round(time.time() - t0, 1))
    pathlib.Path(a.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    log("\n[锚点] 冻结 top-10 复算一致 %d/%d 日" % (anchor["days_bitwise_equal"], anchor["days_compared"]))
    log("\n%-10s %8s %7s %7s %7s %7s %8s %8s %8s" % (
        "集合", "样本", "A深低开%", "B带内%", "C浅低开%", "C触发%", "C触发占比%", "假想净均%", "假想胜率%"))
    for tag, s in out.items():
        log("%-10s %8d %7s %7s %7s %7s %8s %8s %8s" % (
            tag, s["n"], s.get("A_pct"), s.get("B_pct"), s.get("C_pct"),
            s.get("C_touched_pct_of_C"), s.get("C_touched_pct_of_all"),
            s.get("C_fill_net_mean_pct"), s.get("C_fill_win_rate")))
    log("\n[年度] C 占比 / B 占比：")
    for y, v in yearly.items():
        log("   %s  n=%-7d C=%-6s%%  B=%-6s%%" % (y, v["n"], v["C_pct"], v["B_pct"]))
    log("[wrote] %s (%.0fs)" % (a.out, time.time() - t0))


if __name__ == "__main__":
    main()
