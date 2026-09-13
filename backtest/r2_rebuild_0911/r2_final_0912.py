# -*- coding: utf-8 -*-
"""r2 · 幸存信号组合级验证 + 安慰剂 + 审计（2026-09-12）
================================================================
输入：es66_survivors.csv（事件级过闸名单）+ survivors_daily_counts.npz
流程（预注册）：
  A) 若零幸存者 → 直接零候选关闭结案（Q4 边界），仅做结论输出。
  B) 幸存者（按净 edge 降序最多取 5 个）各跑组合臂：
     N∈{10,20} × 门控{开,关} × hold=其事件窗 k × L=5 × 流动性排序 = 4 臂/信号
  C) 对最优臂做 100-seeds 同轮廓随机信号安慰剂（零假设：real ≤ placebo max → 判假象）
  D) 全部臂收益矩阵 → overfit_report（DSR/PBO/Haircut/MinTRL），n_trials 如实申报
输出：r2_rebuild_0911/portfolio66_0912.json / placebo_0912.json / audit_r2_0912.json
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
import v8_selector as V  # noqa: E402


def eq_returns(eqdf):
    r = eqdf["value"].pct_change().fillna(0)
    r.index = pd.to_datetime(r.index)
    return r


if __name__ == "__main__":
    t0 = time.time()
    surv = pd.read_csv(R2 / "es66_survivors.csv", dtype={"key": str})
    surv = surv.sort_values("net115_pct", ascending=False)
    if len(surv) == 0:
        verdict = {"verdict": "ZERO_CANDIDATE_CLOSED",
                   "note": "事件级过闸为空（净115>0 且胜率/样本门槛不过）→ 按预注册边界关闭 66 公式重建线"}
        json.dump(verdict, open(R2 / "portfolio66_0912.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("[closed]", verdict["note"], flush=True)
        sys.exit(0)

    top = surv.drop_duplicates("key").head(5)
    print(f"[survivors] {len(surv)} 行 → top {len(top)}: {top['key'].tolist()}", flush=True)

    pool, codes, gate_map, all_days = E.load_universe()
    ks_map = {r["key"]: int(r["k"]) for _, r in top.iterrows()}

    # 幸存信号逐股矩阵：用与事件研究同一 eval（从编译回执重编译对应块）
    import tdx_interp as T
    data = json.load(open(Path(r"D:\Documents\Workbuddy\股票基金\formula_lib\formulas_66.json"), encoding="utf-8"))
    need = set(top["key"])
    sigs = {}
    for it in data["items"]:
        ctx = "\n".join(b["code"] for b in it.get("blocks", []))
        for vi, b in enumerate(it.get("select_blocks", [])):
            key = f"{it['serial']}.{vi}"
            if key not in need:
                continue
            cand = b["code"]
            head = cand.strip()[:4].upper()
            if head.startswith(("AND", "OR", "NOT")) or (cand.strip()[:1] in "+-*/(<>="):
                cand = (b.get("label") or "").replace("：", ":").strip() + "\n" + cand
            try:
                ast, local, _ = T.compile_block(cand)
            except NotImplementedError:
                ast, local, _ = T.compile_block(ctx + "\n" + cand)
            sigs[key] = (ast, local)

    def eval_key(key, df):
        ast, local = sigs[key]
        c = df["close"].to_numpy(float); o = df["open"].to_numpy(float)
        h = df["high"].to_numpy(float); l = df["low"].to_numpy(float)
        v = df["volume"].to_numpy(float); amo = df["amount"].to_numpy(float)
        env = {"CLOSE": c, "C": c, "OPEN": o, "O": o, "HIGH": h, "H": h, "LOW": l, "L": l,
               "VOL": v, "V": v, "VOLUME": v, "AMO": amo, "AMOUNT": amo, "DRAWNULL": np.nan}
        with np.errstate(invalid="ignore", divide="ignore"):
            for nm, a in local.items():
                if not nm.startswith("__anon"):
                    env[nm] = T.ev(a, env)
            return pd.Series(np.asarray(T.ev(ast, env), float) != 0, index=df.index)

    arms_daily = {}
    results = []
    for _, row in top.iterrows():
        key = row["key"]
        k = int(row["k"])
        sig_by_code = {c: eval_key(key, pool[c]) for c in codes}
        for n in (10, 20):
            for use_gate in (True, False):
                name = f"{key}_h{k}_n{n}_{'gate' if use_gate else 'nogate'}"
                eq, tr, meta = E.run_signal_portfolio(
                    sig_by_code, pool, codes, gate_map, all_days,
                    hold=k, n=n, lookback=5, use_gate=use_gate, slip_bps=0)
                s = E.summary_from_eq(eq, tr)
                s.update({"key": key, "k": k, "n": n, "gate": use_gate, **meta})
                results.append(s)
                print(f"  [{name}] {s['total_pct']}% | 夏普 {s['sharpe']} | "
                      f"回撤 {s['mdd_pct']}% | {s['n_trades']}笔 胜率{s['win_rate']}%", flush=True)
                arms_daily[name] = eq_returns(eq)
                json.dump(results, open(R2 / "portfolio66_0912.json", "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)

    # C) 安慰剂：取最优臂结构
    best = max(results, key=lambda r: r["sharpe"])
    z = np.load(R2 / "survivors_daily_counts.npz", allow_pickle=True)
    dates_all = list(z["dates"])
    key0 = best["key"]
    counts = pd.Series(z[key0], index=pd.to_datetime(dates_all))
    counts = counts[counts > 0]
    print(f"[placebo] 最优臂 {key0} → 同轮廓随机信号 100 seeds", flush=True)
    act_mat = E.build_active_by_day(pool, codes, all_days)
    k0 = best["k"]; n0 = best["n"]; g0 = best["gate"]
    pl = []
    for seed in range(100):
        rsig = E.random_signals(counts.to_dict(), act_mat, codes, all_days, pool, seed)
        eq, tr, meta = E.run_signal_portfolio(
            rsig, pool, codes, gate_map, all_days,
            hold=k0, n=n0, lookback=5, use_gate=g0, slip_bps=0)
        s = E.summary_from_eq(eq, tr)
        pl.append({"seed": seed, "total_pct": s["total_pct"], "sharpe": s["sharpe"]})
        if (seed + 1) % 25 == 0:
            print(f"  seed {seed+1}/100", flush=True)
    pl_max = max(p["total_pct"] for p in pl)
    real_total = best["total_pct"]
    pval = sum(1 for p in pl if p["total_pct"] >= real_total) / len(pl)
    placebo = {"key": key0, "real_total_pct": real_total, "placebo_max_pct": pl_max,
               "placebo_p": pval, "n_seeds": len(pl),
               "placebo_mean": float(np.mean([p["total_pct"] for p in pl])),
               "placebo_p95": float(np.percentile([p["total_pct"] for p in pl], 95))}
    json.dump({"placebo": placebo, "detail": pl},
              open(R2 / "placebo_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[placebo] real {real_total}% vs placebo max {pl_max}% → p={pval}", flush=True)

    # D) 审计（臂矩阵：31 F119 + 组合臂 + 择时 3 = n_trials 如实）
    from overfit_report import build_report
    mat_old = pd.read_csv(R2 / "factors119_daily_returns.csv", index_col=0, parse_dates=True)
    mat_new = pd.DataFrame({k: v for k, v in arms_daily.items()})
    full = pd.concat([mat_old, mat_new], axis=1)
    sel = best["key"] and f"{best['key']}_h{best['k']}_n{best['n']}_{'gate' if best['gate'] else 'nogate'}"
    if sel in full.columns:
        rep = build_report(selected_returns=full[sel].to_numpy(),
                           trials_matrix=full.to_numpy(), n_trials=full.shape[1],
                           periods_per_year=252)
    else:
        rep = {"note": "selected not in matrix"}
    json.dump({"n_trials": int(full.shape[1]), "selected": sel, "audit": rep},
              open(R2 / "audit_r2_0912.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=str)
    print(f"[audit] n_trials={full.shape[1]} selected={sel}", flush=True)
    print(json.dumps(rep, ensure_ascii=False, default=str)[:600], flush=True)
    print(f"\n[done] {time.time()-t0:.0f}s", flush=True)
