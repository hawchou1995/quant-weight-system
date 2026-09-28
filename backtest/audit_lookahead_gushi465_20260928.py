# -*- coding: utf-8 -*-
"""audit_lookahead_gushi465_20260928.py — 未来函数核查（依 gushi.in/topic/465 五维清单）的可执行证据

产出两类**可判定**证据：

  P 段｜阳性对照（证明核查方法有分辨力）
    · P-hpdk：候选排序替换为「按**已实现**收益降序取前 K」（= 偷看未来）→ 组合读数应显著改善。
    · P-qlch：同法（keys = −已实现收益）。
    若偷看未来**没有**带来改善，说明本套核查无分辨力，结论不可用。

  Q 段｜「当前名称 ST/退市」这一**跨期信息**的量化（清单维度③选股 / 维度⑤样本泄露）
    · hpdk `~STNOW`：当前名称含 ST/退 ⇒ 剔除**全部历史**。实测该筛子剔掉 253 只退市股中的 228 只。
    · qlch `is_st`：同一份当前名称快照。
    量化方式：用**临时探针副本 / 运行期包装**去掉该筛子后重跑（**绝不修改任何冻结脚本原文件**）。

只读原文件；探针副本写在会话 scratch。
用法: python audit_lookahead_gushi465_20260928.py --out evidence_lookahead_audit_20260928.json
"""
import argparse, hashlib, importlib.util, json, os, pathlib, sys, time
import numpy as np
import pandas as pd

R = pathlib.Path(__file__).resolve().parents[1]
HPDK = R / "backtest" / "hengpan_fangliang_dikai_0925"
sys.path.insert(0, str(HPDK))
sys.path.insert(0, str(R / "backtest"))
import x2_sens as X                                       # noqa: E402

LOG = []
def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); LOG.append(s)


def names_and_dead():
    N = json.loads((R / "data_full_names.json").read_text(encoding="utf-8"))
    DEAD = R / "backtest/_delisted_universe/delisted_bars.csv.gz"
    dead = set(pd.read_csv(DEAD)["sym"].unique().tolist()) if DEAD.exists() else set()
    return N, dead


def flagged(s, N):
    nm = (N.get(s, "") or "").upper()
    return ("ST" in nm) or ("退" in nm)


# ============================ hpdk ============================
def hpdk_parts(cache):
    out = {}
    N, dead = names_and_dead()
    mod = X.load_mod()
    sha0 = mod.FROZEN_SHA
    oos_src = (HPDK / "oos_run.py").read_bytes()
    log("[hpdk] 冻结脚本 SHA = %s（审计前后均须不变）" % sha0[:16])
    cal, syms, F, done = X.get_panel(mod, cache, True)
    K, KSLOT, COST = int(X.BASE_P["K"]), int(X.BASE_P["KSLOT"]), float(X.BASE_P["COST_SIDE"])

    recs0, _ = X.run_variant(mod, cache, cal, F, done, "audit_base", None, None)
    m0 = X.sim_portfolio(recs0, cal, syms, F, K, KSLOT, COST, start="2018-01-01")
    out["A1_base_2018plus"] = dict(n_trades=len(recs0), **{k: m0[k] for k in
        ("ann", "mdd", "sharpe", "n_entries", "deploy_pct")})
    log("  A1 基线 %d 笔 → 2018+ 年化 %+.2f%% / MDD %.2f%% / 夏普 %s / 入场 %d"
        % (len(recs0), m0["ann"], m0["mdd"], m0["sharpe"], m0["n_entries"]))

    # P：前瞻对照
    by = {}
    for r in recs0:
        by.setdefault(r["entry_date"], []).append(r)
    oracle = [x for d in sorted(by) for x in sorted(by[d], key=lambda z: -z["ret_pct"])[:K]]
    mo = X.sim_portfolio(oracle, cal, syms, F, K, KSLOT, COST, start="2018-01-01")
    out["P_oracle_sort"] = dict(n_trades=len(oracle), **{k: mo[k] for k in
        ("ann", "mdd", "sharpe", "n_entries", "deploy_pct")},
        delta_ann=round(mo["ann"] - m0["ann"], 4), delta_sharpe=round(mo["sharpe"] - m0["sharpe"], 4))
    log("  P1 排序型前瞻对照（按已实现收益排序取前 K）→ 2018+ 年化 %+.2f%%（Δ %+.2fpp）/ 夏普 %s（Δ %+.3f）"
        % (mo["ann"], mo["ann"] - m0["ann"], mo["sharpe"], mo["sharpe"] - m0["sharpe"]))
    log("     ↳ 说明：K=10 而 KSLOT=20 ⇒ 组合**几乎不受选股约束**（每日候选约 10 只、槽位 20），"
        "故排序型前瞻对照的分辨力天然很弱——这本身是一条读数。")

    # P2 价格型前瞻对照（决定性分辨力检验）：把入场价换成「入场日最低价」（实盘不可得）
    jof = {str(x): j for j, x in enumerate(syms)}
    cio = {d: i for i, d in enumerate(cal)}
    L = F["L"]
    recs_low = []
    n_sub = 0
    for r in recs0:
        q = dict(r)
        j = jof.get(r["sym"]); t = cio.get(r["entry_date"])
        if j is not None and t is not None:
            lo = float(L[t, j])
            if np.isfinite(lo) and lo > 0:
                q["entry_open"] = lo; n_sub += 1
        recs_low.append(q)
    ml = X.sim_portfolio(recs_low, cal, syms, F, K, KSLOT, COST, start="2018-01-01")
    out["P2_oracle_entry_low"] = dict(n_trades=len(recs_low), n_price_substituted=n_sub,
        **{k: ml[k] for k in ("ann", "mdd", "sharpe", "n_entries", "deploy_pct")},
        delta_ann=round(ml["ann"] - m0["ann"], 4), delta_sharpe=round(ml["sharpe"] - m0["sharpe"], 4))
    log("  P2 价格型前瞻对照（入场价换成入场日**最低价**）→ 2018+ 年化 %+.2f%%（Δ %+.2fpp）/ 夏普 %s（Δ %+.3f）"
        % (ml["ann"], ml["ann"] - m0["ann"], ml["sharpe"], ml["sharpe"] - m0["sharpe"]))

    # Q：临时探针副本，去掉 ~STNOW
    txt = oos_src.decode("utf-8")
    old = "return (~STP[t]) & (~STNOW) & (C[t] >= 3.0)"
    new = "return (~STP[t]) & np.ones(N, dtype=bool) & (C[t] >= 3.0)   # 审计探针：去掉「当前名称」筛子"
    assert txt.count(old) == 1, "探针锚点不唯一：%d" % txt.count(old)
    probe = pathlib.Path(os.environ["PI_SCRATCH_DIR"]) / "oos_run_nostnow_probe.py"
    t2 = txt.replace(old, new)
    # 探针位于 scratch，需把 R 重写为绝对路径（否则相对 __file__ 解析错位）
    oldR = "R = pathlib.Path(__file__).resolve().parents[2]"
    assert t2.count(oldR) == 1, "R 锚点不唯一"
    t2 = t2.replace(oldR, 'R = pathlib.Path(r"%s")   # 审计探针：绝对路径' % str(R).replace("\\", "/"))
    probe.write_text(t2, encoding="utf-8")
    X.OOS = probe                                  # 仅本进程内改 X.OOS（原文件未动）
    mod_p = X.load_mod()
    recs_n, _ = X.run_variant(mod_p, cache, cal, F, done, "audit_nostnow", None, None)
    mn = X.sim_portfolio(recs_n, cal, syms, F, K, KSLOT, COST, start="2018-01-01")
    out["Q_stnow_off_2018plus"] = dict(n_trades=len(recs_n), **{k: mn[k] for k in
        ("ann", "mdd", "sharpe", "n_entries", "deploy_pct")},
        delta_ann=round(mn["ann"] - m0["ann"], 4), delta_sharpe=round(mn["sharpe"] - m0["sharpe"], 4))
    log("  Q  去掉「当前名称」筛子 → %d 笔 → 2018+ 年化 %+.2f%%（Δ %+.2fpp）/ MDD %.2f%% / 夏普 %s（Δ %+.3f）"
        % (len(recs_n), mn["ann"], mn["ann"] - m0["ann"], mn["mdd"], mn["sharpe"], mn["sharpe"] - m0["sharpe"]))

    # 作用域统计
    psyms = [str(x) for x in syms]
    pdead = [s for s in psyms if s in dead]
    recs_nsyms = {r["sym"] for r in recs0}
    out["stnow_scope"] = dict(
        panel_cols=len(psyms), dead_in_panel=len(pdead),
        dead_flagged_by_current_name=sum(1 for s in pdead if flagged(s, N)),
        dead_still_eligible=sum(1 for s in pdead if not flagged(s, N)),
        trades_on_dead_syms=sum(1 for r in recs0 if r["sym"] in dead),
        distinct_dead_syms_traded=len({r["sym"] for r in recs0 if r["sym"] in dead}),
        traded_syms_flagged_by_current_name=sum(1 for s in recs_nsyms if flagged(s, N)),
        dead_flagged_trades_lost=sum(1 for r in recs_n if r["sym"] in dead and flagged(r["sym"], N)))
    log("  Q  面板退市成员 %d；被当前名称剔除 %d；仍可选 %d；基线成交涉及退市股 %d 笔/%d 只；去掉筛子后新增退市股成交 %d 笔"
        % (out["stnow_scope"]["dead_in_panel"], out["stnow_scope"]["dead_flagged_by_current_name"],
           out["stnow_scope"]["dead_still_eligible"], out["stnow_scope"]["trades_on_dead_syms"],
           out["stnow_scope"]["distinct_dead_syms_traded"], out["stnow_scope"]["dead_flagged_trades_lost"]))

    X.OOS = HPDK / "oos_run.py"
    sha1 = hashlib.sha256((HPDK / "oos_run.py").read_bytes()).hexdigest()
    out["frozen_sha"] = dict(before=sha0, after=sha1, unchanged=bool(sha0 == sha1),
                             bytes_unchanged=bool(oos_src == (HPDK / "oos_run.py").read_bytes()))
    log("  ✓ 冻结脚本未变：%s" % out["frozen_sha"]["unchanged"])
    return out


# ============================ qlch ============================
def qlch_parts():
    import qlch_topk_depth_20260928 as T
    out = {}
    N, _ = names_and_dead()
    cost = T.COST_RT
    D0 = T.build(False, cost, 9.99, -0.99, 2, case="A")
    base, _, _, _, _ = T.run_arm(D0, "random", T.K0, cost)
    out["B1_base_allpool_20bp"] = dict(train_n=base["train"]["n"], train_cagr=base["train"]["cagr"],
                                       train_sharpe=base["train"]["sharpe"], train_mdd=base["train"]["mdd"],
                                       full_cagr=base["full"]["cagr"], full_sharpe=base["full"]["sharpe"])
    log("[qlch] B1 基线（全池/20bp/现行 E2）训练窗 年化 %+.2f%% 夏普 %.3f 笔数 %d"
        % (base["train"]["cagr"], base["train"]["sharpe"], base["train"]["n"]))
    Dor = {**D0, "keys": -np.asarray(D0["ret"], dtype=float)}
    orc, _, _, _, _ = T.run_arm(Dor, "depth", T.K0, cost)
    out["P_oracle_sort"] = dict(train_cagr=orc["train"]["cagr"], train_sharpe=orc["train"]["sharpe"],
                                train_mdd=orc["train"]["mdd"],
                                delta_train_cagr=round(orc["train"]["cagr"] - base["train"]["cagr"], 4),
                                delta_train_sharpe=round(orc["train"]["sharpe"] - base["train"]["sharpe"], 4))
    log("[qlch][P] 前瞻对照（按已实现收益排序）→ 训练窗 年化 %+.2f%%（Δ %+.2fpp）夏普 %.3f（Δ %+.3f）"
        % (orc["train"]["cagr"], orc["train"]["cagr"] - base["train"]["cagr"],
           orc["train"]["sharpe"], orc["train"]["sharpe"] - base["train"]["sharpe"]))

    _orig_loader = T.load_engine
    def patched_loader(mb):
        eng = _orig_loader(mb)
        _o = eng.load_all
        def la():
            P = dict(_o()); P["names"] = {}; return P
        eng.load_all = la
        return eng
    T.load_engine = patched_loader
    Dn = T.build(False, cost, 9.99, -0.99, 2, case="A")
    T.load_engine = _orig_loader
    nn, _, _, _, _ = T.run_arm(Dn, "random", T.K0, cost)
    out["Q_current_name_st_off"] = dict(
        cand_with=D0["n_used"], cand_without=Dn["n_used"],
        train_n_with=base["train"]["n"], train_n_without=nn["train"]["n"],
        train_cagr_with=base["train"]["cagr"], train_cagr_without=nn["train"]["cagr"],
        train_sharpe_with=base["train"]["sharpe"], train_sharpe_without=nn["train"]["sharpe"],
        delta_train_cagr=round(nn["train"]["cagr"] - base["train"]["cagr"], 4),
        delta_train_sharpe=round(nn["train"]["sharpe"] - base["train"]["sharpe"], 4))
    log("[qlch][Q] 去掉「当前名称 ST」筛子 → 候选 %d→%d 笔；训练窗 年化 %+.2f%%（Δ %+.2fpp）夏普 %.3f（Δ %+.3f）"
        % (D0["n_used"], Dn["n_used"], nn["train"]["cagr"], nn["train"]["cagr"] - base["train"]["cagr"],
           nn["train"]["sharpe"], nn["train"]["sharpe"] - base["train"]["sharpe"]))
    z = np.load(str(R / "backtest/kv_resonance_0913/panel_kv_0913.npz"), allow_pickle=True)
    codes = [str(x) for x in z["codes"]]
    out["current_name_scope"] = dict(panel_cols=len(codes),
                                     flagged_by_current_name=sum(1 for c in codes if flagged(c, N)))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default=None)
    a = ap.parse_args(); t0 = time.time()
    cache = pathlib.Path(os.environ.get("PI_SCRATCH_DIR", ".")) / "x1cache"
    res = dict(meta=dict(script=pathlib.Path(__file__).name,
                         run_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                         source="https://gushi.in/topic/465（未来函数排查清单 · 五维）"), hpdk={}, qlch={})
    log("=== A：hpdk（st-hpdk 冻结规格）===")
    res["hpdk"] = hpdk_parts(cache)
    log("")
    log("=== B：qlch（生产口径 B4_K3+MA20 / 现行 E2 持 2 日）===")
    res["qlch"] = qlch_parts()
    res["elapsed_sec"] = round(time.time() - t0, 1)
    log(""); log("总耗时 %.1f s" % res["elapsed_sec"])
    if a.out:
        pathlib.Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        log("[out] %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
