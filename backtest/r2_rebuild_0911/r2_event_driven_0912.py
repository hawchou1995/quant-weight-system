# -*- coding: utf-8 -*-
"""r2 · 41.0 事件驱动组合终验 + 安慰剂（2026-09-12）
================================================================
网格再平衡对稀疏事件信号欠采样（36 笔 vs 7288 事件）→ 改事件驱动入场：
信号收盘确认 → T+1 开盘买（≤n 只，流动性序）→ 持有 60 个交易日开盘卖。
臂位（预注册）：N∈{10,20} × 门控{开,关} × 滑点{0,20bps} = 8 臂。
安慰剂：最优臂结构 × 100 seeds 同轮廓随机信号。
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
R2 = BASE / "backtest" / "r2_rebuild_0911"
SKILL = Path(r"C:\Users\Admin\.workbuddy\plugins\marketplaces\experts\plugins"
             r"\pandaai-ai-quant-research-team\skills\skill-backtest-overfit\scripts")
sys.path.insert(0, str(R2))
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(SKILL))

import r2_portfolio_engine_0912 as E  # noqa: E402
import tdx_interp as T  # noqa: E402


def eq_returns(eqdf):
    r = eqdf["value"].pct_change().fillna(0)
    r.index = pd.to_datetime(r.index)
    return r


if __name__ == "__main__":
    t0 = time.time()
    pool, codes, gate_map, all_days = E.load_universe()

    data = json.load(open(Path(r"D:\Documents\Workbuddy\股票基金\formula_lib\formulas_66.json"), encoding="utf-8"))
    it41 = next(it for it in data["items"] if it["serial"] == 41)
    code41 = it41["select_blocks"][0]["code"]
    ast41, local41, _ = T.compile_block(code41)

    def sig41(df):
        c = df["close"].to_numpy(float); o = df["open"].to_numpy(float)
        h = df["high"].to_numpy(float); l = df["low"].to_numpy(float)
        v = df["volume"].to_numpy(float); amo = df["amount"].to_numpy(float)
        env = {"CLOSE": c, "C": c, "OPEN": o, "O": o, "HIGH": h, "H": h, "LOW": l, "L": l,
               "VOL": v, "V": v, "VOLUME": v, "AMO": amo, "AMOUNT": amo, "DRAWNULL": np.nan}
        with np.errstate(invalid="ignore", divide="ignore"):
            for nm, a in local41.items():
                env[nm] = T.ev(a, env)
            return pd.Series(np.asarray(T.ev(ast41, env), float) != 0, index=df.index)

    sig_by_code = {c: sig41(pool[c]) for c in codes}
    n_sig = int(sum(s.sum() for s in sig_by_code.values()))
    print(f"[sig41] 主板信号总数 {n_sig}", flush=True)

    arms_daily = {}
    results = []
    for n in (10, 20):
        for use_gate in (True, False):
            for slip in (0, 20):
                name = f"41.0_ev_h60_n{n}_{'gate' if use_gate else 'nogate'}_s{slip}"
                eq, tr, meta = E.run_signal_portfolio_event(
                    sig_by_code, pool, codes, gate_map, all_days,
                    hold=60, n=n, lookback=5, use_gate=use_gate, slip_bps=slip)
                s = E.summary_from_eq(eq, tr)
                s.update({"n": n, "gate": use_gate, "slip": slip, **meta})
                results.append(s)
                print(f"  [{name}] {s['total_pct']}% | 夏普 {s['sharpe']} | 回撤 {s['mdd_pct']}% | "
                      f"{s['n_trades']}笔 胜率{s['win_rate']}% | {s['pos_years']}/{s['n_years']}年正", flush=True)
                arms_daily[name] = eq_returns(eq)
                json.dump(results, open(R2 / "event_driven_0912.json", "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)

    best = max(results, key=lambda r: r["sharpe"])
    print(f"[best] {best}", flush=True)

    # 每日信号数轮廓 → 100 seeds 安慰剂
    counts = {}
    for c in codes:
        idxs = np.where(sig_by_code[c].to_numpy())[0]
        for i in idxs:
            d = sig_by_code[c].index[i]
            counts[d] = counts.get(d, 0) + 1
    act_mat = E.build_active_by_day(pool, codes, all_days)
    pl = []
    for seed in range(100):
        rsig = E.random_signals(counts, act_mat, codes, all_days, pool, seed)
        eq, tr, meta = E.run_signal_portfolio_event(
            rsig, pool, codes, gate_map, all_days,
            hold=60, n=best["n"], lookback=5, use_gate=best["gate"], slip_bps=best["slip"])
        s = E.summary_from_eq(eq, tr)
        pl.append({"seed": seed, "total_pct": s["total_pct"], "sharpe": s["sharpe"]})
        if (seed + 1) % 25 == 0:
            print(f"  seed {seed+1}/100", flush=True)
    real_total = best["total_pct"]
    placebo = {"real_total_pct": real_total,
               "placebo_max_pct": max(p["total_pct"] for p in pl),
               "placebo_mean_pct": float(np.mean([p["total_pct"] for p in pl])),
               "placebo_p95_pct": float(np.percentile([p["total_pct"] for p in pl], 95)),
               "p": sum(1 for p in pl if p["total_pct"] >= real_total) / len(pl),
               "n_seeds": len(pl)}
    json.dump({"placebo": placebo, "detail": pl},
              open(R2 / "placebo_event_0912.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"[placebo] real {real_total}% vs max {placebo['placebo_max_pct']}% "
          f"mean {placebo['placebo_mean_pct']:.1f}% → p={placebo['p']}", flush=True)

    from overfit_report import build_report
    mat_old = pd.read_csv(R2 / "factors119_daily_returns.csv", index_col=0, parse_dates=True)
    mat_new = pd.DataFrame(arms_daily)
    full = pd.concat([mat_old, mat_new], axis=1)
    sel = f"41.0_ev_h60_n{best['n']}_{'gate' if best['gate'] else 'nogate'}_s{best['slip']}"
    rep = build_report(selected_returns=full[sel].to_numpy(),
                       trials_matrix=full.to_numpy(), n_trials=full.shape[1],
                       periods_per_year=252)
    json.dump({"n_trials": int(full.shape[1]), "selected": sel, "audit": rep},
              open(R2 / "audit_r2_0912.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=str)
    print(f"[audit] n_trials={full.shape[1]} selected={sel}", flush=True)
    print(json.dumps(rep, ensure_ascii=False, default=str)[:500], flush=True)
    print(f"\n[done] {time.time()-t0:.0f}s", flush=True)
