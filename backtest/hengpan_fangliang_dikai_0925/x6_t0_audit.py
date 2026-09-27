# -*- coding: utf-8 -*-
"""x6_t0_audit.py - T+0 资金时序缺陷审计（2026-09-27，勘误 E-15 / E-16）

背景
----
x2_sens.py::sim_portfolio 原实现按「同一交易日内先出场（T+2 收盘）→ 再入场（T+2 开盘）」执行，
等于**用当天尚未卖出的持仓资金建仓 = 同一笔资本在同一天被使用两次**。
正确顺序 = 先入场（09:25，只能用开盘前已有现金）→ 后出场（15:00 收盘结算）。
该顺序错误对**高资金占用档（低 KSLOT）**高估最严重（全池 KSLOT=4 全窗 +249.67% → +90.62%），
对 KSLOT=20（占用约 42%）影响很小（全池 +72.59% → +69.37%；主板 +47.77% → +47.17%）。

本脚本做四件事（全部可复算）
--------------------------
A) 双序对拍：同一份逐笔记录按 exit_first / entry_first 两种记账分别算 NAV。
   exit_first 必须**逐位复现**冻结读数 ⇒ 证明修正只动资金时序、不动选股逻辑与参数。
B) 修正前后读数表：主板（生产口径 P[MAINBOARD]=True）/ 全池 × KSLOT∈{4,6,10,20,30}
   × 窗口 {全窗, 2018+, 2022+}。
C) 「10 万真钱口径」阶梯：本金 100,000 元、整手 100 股、最低佣金 5 元/笔、单票 ≤ ADV20×1%。
   并以**口径等价性检验**（把该实现退化为归一化口径后必须与 x2_sens.sim_portfolio 一致）
   证明两个独立实现的记账同源。
D) 对照实现偏差量化：fixt0 风格实现含 `out > cash: continue` 判据，而 out 与 cash 在「现金恰为
   约束」时相差 6.9e-18（纯浮点残差）⇒ 会凭空拒单。此段量化笔数与收益偏差，说明为何本次
   修正的权威读数取自 x2_sens 而非 fixt0。

用法: python x6_t0_audit.py [--cache DIR] [--out FILE]
"""
import os, sys, json, math, time, hashlib, argparse, pathlib
import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
R = HERE.parents[1]
sys.path.insert(0, str(HERE))
import x2_sens as X                                      # noqa: E402

ANN = 244.0
KS_LADDER = (4, 6, 10, 20, 30)
WINDOWS = (("full", None), ("w2018", "2018-01-01"), ("w2022", "2022-01-01"))
ARMS = (("mainboard", {"MAINBOARD": True}, "主板（生产口径）"),
        ("allpool", {"MAINBOARD": False}, "全池（含退市股）"))


def metrics(nav, cal, idx, cap, entries, dep_all, extra=None):
    v = nav[idx]
    nd = len(v) - 1
    ann = (v[-1] / v[0]) ** (ANN / nd) - 1
    pk = np.maximum.accumulate(v)
    mdd = float((v / pk - 1).min())
    dr = v[1:] / v[:-1] - 1
    sd = dr.std(ddof=1)
    d = dict(ann=round(float(ann) * 100, 4), mdd=round(mdd * 100, 4),
             sharpe=None if sd == 0 else round(float(dr.mean() / sd * math.sqrt(ANN)), 3),
             n_entries=int(entries), n_days=int(len(idx)),
             per_day=round(entries / len(idx), 3),
             deploy_pct=round(float(np.mean([dep_all[i] for i in idx])) * 100, 3),
             window=[cal[idx[0]], cal[idx[-1]]], mult=round(float(v[-1] / v[0]), 6))
    if extra:
        d.update(extra)
    return d


def sim_money(recs, cal, syms, F, K, KSLOT, cost, cap, start=None, order="entry_first",
              lot=True, capv_pct=0.01, amt20=None, min_comm=5.0, ghost_guard=False):
    """独立实现的组合记账（不调用 x2_sens.sim_portfolio）。
    lot=False + capv_pct=0 + min_comm=0 + cap=1.0  ⇒ 应与 x2_sens.sim_portfolio 口径等价。
    ghost_guard=True              ⇒ 复现 fixt0 风格的 `out > cash: continue` 判据。
    """
    T = len(cal)
    jof = {s: j for j, s in enumerate(syms)}
    C = F["C"]
    by = {}
    for r in recs:
        if start is None or r["entry_date"] >= start:
            by.setdefault(r["entry_date"], []).append(r)
    nav = np.full(T, np.nan)
    cash = float(cap)
    pos, ne, nlf, ncap, nghost = [], 0, 0, 0, 0
    dep = np.zeros(T)

    def do_entry(t, d):
        nonlocal cash, ne, nlf, ncap, nghost
        for r in by.get(d, [])[:K]:
            if len(pos) >= KSLOT:
                break
            if any(q["sym"] == r["sym"] for q in pos):
                continue
            px = r["entry_open"]
            if not (np.isfinite(px) and px > 0):
                continue
            navprev = nav[t - 1] if (t > 0 and np.isfinite(nav[t - 1])) else float(cap)
            alloc = min(navprev / KSLOT, cash)
            if capv_pct and amt20 is not None:
                j = jof.get(r["sym"])
                a = amt20[t, j] if j is not None else np.nan
                if np.isfinite(a) and a > 0:
                    lim = float(a) * capv_pct
                    if lim < alloc:
                        ncap += 1
                        alloc = lim
            if alloc <= 1e-9:
                continue
            # 真实支出 = 成交金额 + max(成交金额×费率, 最低佣金)；股数须使总支出 ≤ 预算
            if lot:
                sh = math.floor(alloc / (px * (1.0 + cost)) / 100.0) * 100
                while sh >= 100:
                    gross = sh * px
                    out = gross + (max(gross * cost, min_comm) if min_comm else gross * cost)
                    if out <= alloc:
                        break
                    sh -= 100
                if sh < 100:
                    nlf += 1
                    continue
            else:
                sh = alloc / (px * (1.0 + cost))
                if min_comm:
                    gross = sh * px
                    out = gross + max(gross * cost, min_comm)
                else:
                    # 与 fixt0.py 同式（单次乘法）——幽灵拒单对照的计数对末位浮点极敏感，
                    # 必须逐位复现该式，否则 out > cash 的判定会整批翻转（见报告 §D）。
                    out = sh * px * (1.0 + cost)
            if ghost_guard and out > cash:
                nghost += 1
                continue
            if out > cash + 1e-9:
                continue
            cash -= out
            pos.append(dict(sym=r["sym"], sh=sh, xd=r["exit_date"], xp=r["exit_px"] or 0.0, ep=px))
            ne += 1

    def do_exit(d):
        nonlocal cash
        for p in list(pos):
            if p["xd"] == d:
                pr = p["sh"] * p["xp"]
                cash += pr - (max(pr * cost, min_comm) if min_comm else pr * cost)
                pos.remove(p)

    for t in range(T):
        d = cal[t]
        if order == "entry_first":
            do_entry(t, d)
            do_exit(d)
        else:
            do_exit(d)
            do_entry(t, d)
        mv = 0.0
        for p in pos:
            j = jof.get(p["sym"])
            c = C[t, j] if j is not None else np.nan
            if not (np.isfinite(c) and c > 0):
                c = p["ep"]
            mv += p["sh"] * c
        nav[t] = float(cash + mv)
        dep[t] = (mv / nav[t]) if nav[t] > 0 else 0.0
    idx = [i for i in range(T) if (start is None or cal[i] >= start) and np.isfinite(nav[i])]
    i0 = idx[0]
    nav[i0] = float(cap)
    return metrics(nav, cal, idx, cap, ne, dep,
                   dict(n_lot_fail=nlf, n_cap_bind=ncap, n_ghost_skip=nghost))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.environ.get("PI_SCRATCH_DIR") or ".")
    ap.add_argument("--out", default=str(HERE / "evidence_t0_audit.json"))
    a = ap.parse_args()
    cache = pathlib.Path(a.cache)
    if not cache.exists():
        cache = pathlib.Path(os.environ["PI_SCRATCH_DIR"]) / "x1cache"
    mod = X.load_mod()
    sha = mod.FROZEN_SHA
    print("冻结脚本 SHA256 = %s" % sha, flush=True)
    cal, syms, F, done = X.get_panel(mod, cache, True)
    assert mod.FROZEN_SHA == sha, "冻结脚本 SHA 被改动！"
    COST = float(X.BASE_P["COST_SIDE"])
    K = int(X.BASE_P["K"])
    VALID = (F["C"] > 0) & np.isfinite(F["C"])
    AMT20 = pd.DataFrame(np.where(VALID, F["A"], np.nan)).rolling(20, min_periods=10).mean().to_numpy()
    print("面板 T=%d N=%d names_loaded=%d cost=%.6f" % (F["C"].shape[0], F["C"].shape[1], done, COST), flush=True)

    out = dict(meta=dict(script="x6_t0_audit.py",
                         script_sha256=hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
                         frozen_script_sha256=sha, generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                         panel=dict(T=int(F["C"].shape[0]), N=int(F["C"].shape[1])),
                         cost_side=COST, K=K, kslots=list(KS_LADDER),
                         windows=dict(WINDOWS), ann_factor=ANN,
                         sim_rule=("先入场（09:25，只用开盘前现金）→ 后出场（15:00 收盘结算）；"
                                   "单票 = min(前一日净值/KSLOT, 可用现金)；最多 KSLOT 只并发；"
                                   "同一标的持仓期内不重复买入；逐日收盘盯市。"
                                   "exit_first = 2026-09-27 前的缺陷顺序，仅供审计复现（E-15）"),
                         money_rule=("10 万真钱口径：本金 100,000 元、整手 100 股、买卖各收 6.92bp、"
                                     "买卖两端各最低佣金 5 元/笔、单票上限 = ADV20×1%")),
                A_dual_order={}, B_money_ladder={}, C_equivalence={}, D_ghost_ref={}, checks=[])

    recs_by_arm = {}
    for key, ov, label in ARMS:
        tag = "t0_" + key
        print("[arm] %s MAINBOARD=%s" % (label, ov["MAINBOARD"]), flush=True)
        recs, P = X.run_variant(mod, cache, cal, F, done, tag, ov, None)
        recs_by_arm[key] = recs
        out["A_dual_order"][key] = dict(label=label, n_trades=len(recs),
                                        n_signal_days=len({r["signal_date"] for r in recs}),
                                        by_window={})
        for wname, st in WINDOWS:
            out["A_dual_order"][key]["by_window"][wname] = {}
            for ks in KS_LADDER:
                row = {}
                for od in ("exit_first", "entry_first"):
                    row[od] = X.sim_portfolio(recs, cal, syms, F, K, ks, COST, start=st, order=od)
                row["delta_ann"] = round(row["entry_first"]["ann"] - row["exit_first"]["ann"], 4)
                out["A_dual_order"][key]["by_window"][wname][str(ks)] = row
                print("  A %-9s %-6s KSLOT=%2d exit_first %+8.2f%% (dep %5.2f%%) → entry_first %+8.2f%% "
                      "(dep %5.2f%%) Δann %+7.2fpp"
                      % (key, wname, ks, row["exit_first"]["ann"], row["exit_first"]["deploy_pct"],
                         row["entry_first"]["ann"], row["entry_first"]["deploy_pct"], row["delta_ann"]), flush=True)

    print("[C] 口径等价性：独立实现（归一化退化）vs x2_sens.sim_portfolio", flush=True)
    worst = 0.0
    for key, ov, label in ARMS:
        recs = recs_by_arm[key]
        out["C_equivalence"][key] = {}
        for wname, st in WINDOWS:
            for ks in (4, 20):
                ref = X.sim_portfolio(recs, cal, syms, F, K, ks, COST, start=st, order="entry_first")
                mine = sim_money(recs, cal, syms, F, K, ks, COST, 1.0, start=st, order="entry_first",
                                 lot=False, capv_pct=0.0, amt20=None, min_comm=0.0)
                d = round(mine["ann"] - ref["ann"], 6)
                worst = max(worst, abs(d))
                out["C_equivalence"][key]["%s_kslot%d" % (wname, ks)] = dict(
                    ref_ann=ref["ann"], indep_ann=mine["ann"], delta_pp=d,
                    ref_ne=ref["n_entries"], indep_ne=mine["n_entries"],
                    same_entries=bool(ref["n_entries"] == mine["n_entries"]))
                print("   %-9s %-6s KSLOT=%2d ref %+8.4f%% indep %+8.4f%% Δ %+.6fpp ne %d/%d %s"
                      % (key, wname, ks, ref["ann"], mine["ann"], d, ref["n_entries"], mine["n_entries"],
                         "OK" if ref["n_entries"] == mine["n_entries"] else "MISMATCH"), flush=True)
    out["checks"].append(dict(name="C_equivalence_max_abs_delta_pp", value=round(worst, 6),
                              limit=0.01, passed=bool(worst <= 0.01)))

    print("[B] 10 万真钱口径阶梯（本金 100,000 / 整手 / 最低佣金 5 元 / 单票 ≤ ADV20×1%%）", flush=True)
    CAP10W = 100000.0
    for key, ov, label in ARMS:
        recs = recs_by_arm[key]
        out["B_money_ladder"][key] = dict(label=label, capital=CAP10W, by_window={})
        for wname, st in WINDOWS:
            out["B_money_ladder"][key]["by_window"][wname] = {}
            for ks in KS_LADDER:
                m = sim_money(recs, cal, syms, F, K, ks, COST, CAP10W, start=st, order="entry_first",
                              lot=True, capv_pct=0.01, amt20=AMT20, min_comm=5.0)
                m_ef = sim_money(recs, cal, syms, F, K, ks, COST, CAP10W, start=st, order="exit_first",
                                 lot=True, capv_pct=0.01, amt20=AMT20, min_comm=5.0)
                out["B_money_ladder"][key]["by_window"][wname][str(ks)] = dict(entry_first=m, exit_first=m_ef)
                print("   B %-9s %-6s KSLOT=%2d 年化 %+8.2f%% MDD %7.2f%% 夏普 %5s 入场 %5d 日均 %.2f 只 "
                      "占用 %5.2f%%（旧序 %+8.2f%%）"
                      % (key, wname, ks, m["ann"], m["mdd"], m["sharpe"], m["n_entries"], m["per_day"],
                         m["deploy_pct"], m_ef["ann"]), flush=True)

    print("[D] 对照实现偏差：fixt0 风格 `out > cash: continue`（浮点残差 6.9e-18）", flush=True)
    for key, ov, label in ARMS:
        recs = recs_by_arm[key]
        for wname, st in WINDOWS:
            auth = X.sim_portfolio(recs, cal, syms, F, K, 20, COST, start=st, order="entry_first")
            g = sim_money(recs, cal, syms, F, K, 20, COST, 1.0, start=st, order="entry_first",
                          lot=False, capv_pct=0.0, amt20=None, min_comm=0.0, ghost_guard=True)
            out["D_ghost_ref"]["%s_%s_kslot20" % (key, wname)] = dict(
                auth_ann=auth["ann"], ghost_ann=g["ann"], delta_pp=round(g["ann"] - auth["ann"], 4),
                auth_ne=auth["n_entries"], ghost_ne=g["n_entries"],
                skipped=int(auth["n_entries"] - g["n_entries"]))
            print("   D %-9s %-6s 权威 ne=%5d ann %+8.2f%% | 含幽灵拒单 ne=%5d ann %+8.2f%% | 少 %3d 笔 Δann %+.2fpp"
                  % (key, wname, auth["n_entries"], auth["ann"], g["n_entries"], g["ann"],
                     auth["n_entries"] - g["n_entries"], g["ann"] - auth["ann"]), flush=True)

    out["checks"].append(dict(name="D_ghost_reproduced", value=out["D_ghost_ref"]["mainboard_full_kslot20"]["skipped"],
                              expect_gt=0,
                              passed=bool(out["D_ghost_ref"]["mainboard_full_kslot20"]["skipped"] > 0)))
    pathlib.Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[out] %s" % a.out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
