# -*- coding: utf-8 -*-
"""audit_launch12_20260928.py — 《上线前 12 项检查》审计（gushi.in/topic/468）
对象 = 「缩量超跌」(st-hpdk, 原「横盘低开·两日」)

只读审计：不改生产口径（oos_run.py 字节零修改 + SHA 校验）、不写封存集、不碰 backtest/clip_absorb_0925/。
同尺子锚定：
  ① 本脚本的组合记账 = x2_sens.sim_portfolio 的超集（逐项对拍，必须逐位相同才允许用于新结论）；
  ② 对拍 evidence_sensitivity.json 的 base 臂已发布读数。
用法: python audit_launch12_20260928.py [--cache DIR]
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import time
from collections import Counter

import numpy as np
import pandas as pd

R = pathlib.Path(__file__).resolve().parents[2]
OUT = R / "backtest/hengpan_fangliang_dikai_0925"
FROZEN_SHA_EXPECT = "2351eb9d42acc62e35049d47785e755ff9ce5a0a60d178e90c7baa83f47800a2"   # v1.7a（E-22 + 开关语义修复）；v1.7=7d14d27e…；v1.6=0b61a4bb…   # v1.7（E-22 A+C）；v1.6 = 0b61a4bb…；v1.5 = b3748ca3…
ANN = 244.0
MET_KEYS = ("ann", "mdd", "sharpe", "win_rate", "mean_per_trade", "med_per_trade",
            "n_trades", "n_entries", "deploy_pct")


def log(*a):
    print(*a, flush=True)


def load_x2():
    sys.path.insert(0, str(OUT))
    import x2_sens
    return x2_sens


# ---------------------------------------------------------------- 扩展版组合记账
def sim_ext(recs, cal, syms, F, K, KSLOT, cost_side, order="entry_first"):
    """x2_sens.sim_portfolio 的**超集**：同一循环，另回传 NAV 序列 / 占用率 / 逐笔明细。
    指标计算与返回字段与 x2_sens.sim_portfolio 完全一致（用于逐位对拍）。"""
    T = len(cal)
    jof = {s: j for j, s in enumerate(syms)}
    C = F["C"]
    by_entry = {}
    for r in recs:
        by_entry.setdefault(r["entry_date"], []).append(r)
    nav = np.full(T, np.nan)
    depl = np.full(T, np.nan)
    cash, pos, n_in = 1.0, [], 0
    trades = []
    skip_dup = skip_slot = skip_nofund = 0

    def do_entry(t, d):
        nonlocal cash, n_in, skip_dup, skip_slot, skip_nofund
        for r in by_entry.get(d, [])[:K]:
            if len(pos) >= KSLOT:
                skip_slot += 1
                break
            if any(q["sym"] == r["sym"] for q in pos):
                skip_dup += 1
                continue
            navprev = nav[t - 1] if (t > 0 and np.isfinite(nav[t - 1])) else 1.0
            alloc = min(navprev / KSLOT, cash)
            if alloc <= 1e-12:
                skip_nofund += 1
                break
            px = r["entry_open"]
            if not (np.isfinite(px) and px > 0):
                continue
            cash -= alloc
            pos.append(dict(sym=r["sym"], shares=alloc / (px * (1.0 + cost_side)),
                            entry_px=px, exit_date=r["exit_date"], exit_px=r["exit_px"],
                            t_in=t, alloc=alloc, nav_prev=navprev, rec=r))
            n_in += 1

    def do_exit(t, d):
        nonlocal cash
        for p in list(pos):
            if p["exit_date"] == d:
                proceeds = p["shares"] * p["exit_px"] * (1.0 - cost_side)
                cash += proceeds
                pos.remove(p)
                trades.append(dict(sym=p["sym"], j=jof.get(p["sym"]), t_in=p["t_in"], t_out=t,
                                   entry_date=cal[p["t_in"]], exit_date=d,
                                   entry_px=p["entry_px"], exit_px=p["exit_px"],
                                   alloc=p["alloc"], nav_prev=p["nav_prev"],
                                   weight=round(p["alloc"] / p["nav_prev"], 6) if p["nav_prev"] else None,
                                   pnl=proceeds - p["alloc"],
                                   ret_pct=p["rec"]["ret_pct"], tp_hit=int(p["rec"].get("tp_hit", 0)),
                                   exit_flag=int(p["rec"].get("exit_flag", 0)),
                                   gap_pct=p["rec"].get("gap_pct")))

    for t in range(T):
        d = cal[t]
        if order == "entry_first":
            do_entry(t, d)
            do_exit(t, d)
        else:
            do_exit(t, d)
            do_entry(t, d)
        mv = 0.0
        for p in pos:
            j = jof.get(p["sym"])
            c = C[t, j] if j is not None else np.nan
            if not (np.isfinite(c) and c > 0):
                c = p["entry_px"]
            mv += p["shares"] * c
        nav[t] = cash + mv
        depl[t] = (mv / nav[t]) if nav[t] > 0 else np.nan

    idx_all = list(range(T))
    i0 = idx_all[0]
    nav[i0] = 1.0
    v = nav[idx_all]
    if v.size < 30 or not np.all(np.isfinite(v)):
        return None
    nd = len(v) - 1
    ann = (v[-1] / v[0]) ** (ANN / nd) - 1
    pk = np.maximum.accumulate(v)
    mdd = float((v / pk - 1).min())
    dr = v[1:] / v[:-1] - 1
    sd = dr.std(ddof=1)
    rets = np.array([r["ret_pct"] for r in recs], float)
    yret, yrs = {}, {}
    for i in idx_all:
        yrs.setdefault(cal[i][:4], []).append(i)
    for y, ii in sorted(yrs.items()):
        j0 = ii[0] - 1
        base = nav[j0] if (j0 >= 0 and np.isfinite(nav[j0])) else 1.0
        yret[y] = round(float(nav[ii[-1]] / base - 1) * 100, 2)
    neg = sum(1 for x in yret.values() if x < 0)
    dd = depl[idx_all]
    metrics = dict(ann=round(ann * 100, 2), mdd=round(mdd * 100, 2),
                   sharpe=None if sd == 0 else round(float(dr.mean() / sd * np.sqrt(ANN)), 2),
                   win_rate=round(float(100 * (rets > 0).mean()), 2) if rets.size else None,
                   mean_per_trade=round(float(rets.mean()), 4) if rets.size else None,
                   med_per_trade=round(float(np.median(rets)), 4) if rets.size else None,
                   n_trades=int(rets.size), n_entries=int(n_in),
                   deploy_pct=round(float(np.nanmean(dd)) * 100, 2),
                   neg_years=int(neg), n_years=len(yret), yearly=yret,
                   window=[cal[i0], cal[idx_all[-1]]])
    return dict(metrics=metrics, nav=nav, depl=depl, trades=trades,
                skip=dict(dup=skip_dup, slot=skip_slot, nofund=skip_nofund),
                cash=cash, open_pos=len(pos))


# ---------------------------------------------------------------- 行情分层
def regime_series(F, syms):
    C = F["C"]
    MB = np.array([(s[:2] == "sh" and s[2:5] in ("600", "601", "603", "605")) or
                   (s[:2] == "sz" and s[2:5] in ("000", "001", "002", "003")) for s in syms])
    r1 = np.full(C.shape, np.nan, dtype=np.float64)
    r1[1:] = C[1:] / np.where(C[:-1] > 0, C[:-1], np.nan) - 1.0
    r1 = np.where(MB[None, :], r1, np.nan)
    r1[~np.isfinite(r1)] = np.nan
    with np.errstate(all="ignore"):
        med = np.nanmedian(r1, axis=1)
    med = np.where(np.isfinite(med), med, 0.0)
    idx = np.cumprod(1.0 + med)
    ma60 = pd.Series(idx).rolling(60, min_periods=40).mean().to_numpy()
    ma60_prev = np.concatenate([[np.nan], ma60[:-1]])
    bull = (idx >= ma60) & (ma60 > ma60_prev)
    bear = (idx < ma60) & (ma60 < ma60_prev)
    regime = np.where(bull, "bull", np.where(bear, "bear", "range")).astype(object)
    idx5 = np.full(len(idx), np.nan)
    idx5[5:] = idx[5:] / idx[:-5] - 1.0
    crush = idx5 <= -0.05
    return regime, crush, idx, ma60


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.environ.get("PI_SCRATCH_DIR") or str(OUT))
    a = ap.parse_args()
    CACHE = pathlib.Path(a.cache)
    CACHE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    x2 = load_x2()
    mod = x2.load_mod()
    sha = mod.FROZEN_SHA
    assert sha == FROZEN_SHA_EXPECT, "冻结脚本 SHA 不符：%s" % sha
    log("[spec] oos_run.py SHA256 = %s" % sha)
    cal, syms, F, done = x2.get_panel(mod, CACHE)
    log("[panel] T=%d N=%d names_loaded=%d (%.0fs)" % (len(cal), len(syms), done, time.time() - t0))
    recs, P = x2.run_variant(mod, CACHE, cal, F, done, "lb12base")
    K, KSLOT, cs = int(P["K"]), int(P["KSLOT"]), float(P["COST_SIDE"])
    log("[recs] %d 笔" % len(recs))

    # ---- 锚点 1：本脚本扩展记账 vs x2_sens.sim_portfolio ----
    m_x2 = x2.sim_portfolio(recs, cal, syms, F, K, KSLOT, cs)
    ext20 = sim_ext(recs, cal, syms, F, K, KSLOT, cs)
    ext4 = sim_ext(recs, cal, syms, F, K, 4, cs)
    anchor_self = {k: [ext20["metrics"][k], m_x2[k]] for k in MET_KEYS}
    bad = [k for k in MET_KEYS if ext20["metrics"][k] != m_x2[k]]
    assert not bad, "扩展记账与 sim_portfolio 不一致: %s" % bad
    log("[anchor] 扩展记账 vs sim_portfolio 逐项一致 ✓")

    # ---- 锚点 2：vs evidence_sensitivity.json base 臂 ----
    ev = json.loads((OUT / "evidence_sensitivity.json").read_text(encoding="utf-8"))
    m_pub = ev["variants"]["base"]["metrics"]
    anchor_pub = {k: [m_x2[k], m_pub[k]] for k in MET_KEYS}
    bad2 = [k for k in MET_KEYS if m_x2[k] != m_pub[k]]
    log("[anchor] vs evidence_sensitivity.base: %s" % ("逐项一致 ✓" if not bad2 else "差异 %s" % bad2))

    # ---- 通用量 ----
    O, H, L, C, A = F["O"], F["H"], F["L"], F["C"], F["A"]
    T = len(cal)
    tix = {d: i for i, d in enumerate(cal)}
    AMT20 = pd.DataFrame(np.where(A > 0, A, np.nan)).rolling(20, min_periods=10).mean().to_numpy()
    regime, crush, ridx, rma60 = regime_series(F, syms)
    regime_entry = np.array([regime[tix[r["entry_date"]]] for r in recs], dtype=object)

    def trade_diag(ext):
        out = []
        for tr in ext["trades"]:
            j, te, tx = tr["j"], tr["t_in"], tr["t_out"]
            if j is None:
                continue
            lo = L[te:tx + 1, j]
            lo = lo[np.isfinite(lo) & (lo > 0)]
            mae = float(lo.min() / tr["entry_px"] - 1.0) if lo.size else None
            # 入场日无法成交（开盘涨停）
            gap_e = None
            if te >= 1 and np.isfinite(C[te - 1, j]) and C[te - 1, j] > 0:
                gap_e = float(O[te, j] / C[te - 1, j] - 1.0)
            # 出场日跌停锁死
            locked = None
            if tx >= 1 and np.isfinite(C[tx - 1, j]) and C[tx - 1, j] > 0:
                ch = float(C[tx, j] / C[tx - 1, j] - 1.0)
                locked = bool(ch <= -0.095 and abs(float(H[tx, j]) - float(L[tx, j])) < 1e-9)
            cap1 = None
            if np.isfinite(AMT20[te, j]):
                cap1 = float(AMT20[te, j]) * 0.01
            out.append(dict(tr, mae=mae, gap_entry=gap_e, exit_locked=locked,
                            cap1=cap1, regime=regime[te], crush=bool(crush[te])))
        return out

    d20 = trade_diag(ext20)
    d4 = trade_diag(ext4)

    # ---- 止损反事实（近似：先判止损后判止盈，T+1 日不可卖）----
    def stop_analysis(diag, stop, cost_side=cs):
        rets, n_hit = [], 0
        for tr in diag:
            j, te, tx, ep = tr["j"], tr["t_in"], tr["t_out"], tr["entry_px"]
            lvl = ep * (1.0 + stop)
            fill = None
            for t in range(te + 1, tx + 1):
                low = L[t, j]
                if np.isfinite(low) and low <= lvl:
                    o = O[t, j]
                    fill = min(lvl, float(o)) if (np.isfinite(o) and o > 0) else lvl
                    break
            if fill is None:
                rets.append(tr["ret_pct"])
            else:
                n_hit += 1
                rets.append((fill * (1 - cost_side) / (ep * (1 + cost_side)) - 1.0) * 100)
        rets = np.array(rets, float)
        return dict(stop_pct=round(stop * 100, 2), n_trigger=int(n_hit),
                    trigger_pct=round(100 * n_hit / max(1, len(rets)), 2),
                    mean=round(float(rets.mean()), 4), median=round(float(np.median(rets)), 4),
                    win_rate=round(float(100 * (rets > 0).mean()), 2), worst=round(float(rets.min()), 4))

    stops = [stop_analysis(d4, s) for s in (-0.03, -0.05, -0.08, -0.10)]

    # ---- 风控红线（在组合净值序列上）----
    def redlines(ext, tag):
        nav = ext["nav"]
        dr = nav[1:] / nav[:-1] - 1.0
        n_d3 = int((dr <= -0.03).sum())
        i3 = np.nonzero(dr <= -0.03)[0]
        fwd5 = []
        for i in i3:
            k = min(i + 5, len(nav) - 1)
            fwd5.append(float(nav[k] / nav[i + 1] - 1) * 100)
        wk = {}
        for i, d in enumerate(cal):
            y, w, _ = dt.date.fromisoformat(d).isocalendar()
            wk.setdefault((y, w), []).append(i)
        wret = []
        for kws, ii in wk.items():
            if len(ii) >= 2:
                wret.append(float(nav[ii[-1]] / nav[ii[0] - 1] - 1) * 100 if ii[0] >= 1 else 0.0)
        wret = np.array(wret)
        n_w8 = int((wret <= -8.0).sum())
        # 连亏（按出场日排序的已了结交易）
        seq = [t["ret_pct"] for t in sorted(ext["trades"], key=lambda x: (x["t_out"], x["sym"]))]
        streak = mx = 0
        ge5 = 0
        for x in seq:
            if x < 0:
                streak += 1
                mx = max(mx, streak)
                if streak == 5:
                    ge5 += 1
            else:
                streak = 0
        return dict(config=tag, n_days=int(len(dr)),
                    daily_drop3_n=n_d3, daily_drop3_per_year=round(n_d3 / (len(dr) / ANN), 2),
                    daily_drop3_median_fwd5_pct=round(float(np.median(fwd5)), 2) if fwd5 else None,
                    daily_drop3_mean_fwd5_pct=round(float(np.mean(fwd5)), 2) if fwd5 else None,
                    weekly_drop8_n=n_w8, weekly_drop8_per_year=round(n_w8 / (len(wret) / 48.0), 2),
                    max_consec_loss=int(mx), n_streak_ge5=int(ge5))

    rl4, rl20 = redlines(ext4, "KSLOT=4"), redlines(ext20, "KSLOT=20")

    # ---- 成本 ----
    def cost_variant(mult, kslot):
        mm = sim_ext(recs, cal, syms, F, K, kslot, cs * mult)["metrics"]
        return dict(mult=mult, ann=mm["ann"], mdd=mm["mdd"], sharpe=mm["sharpe"],
                    mean_per_trade=mm["mean_per_trade"], win_rate=mm["win_rate"])
    cost_tab = [cost_variant(m, 4) for m in (0.0, 1.0, 2.0, 3.0)]
    cost_tab20 = [cost_variant(m, 20) for m in (0.0, 1.0, 2.0, 3.0)]
    gross = [( (tr["exit_px"] / tr["entry_px"] - 1.0) * 100) for tr in d4]
    net = [tr["ret_pct"] for tr in d4]
    gross = np.array(gross, float)
    net = np.array(net, float)
    cost_stats = dict(n=len(net), gross_mean=round(float(gross.mean()), 4), net_mean=round(float(net.mean()), 4),
                      drag_per_trade_pp=round(float((gross - net).mean()), 4),
                      roundtrip_cost_pct=round(2 * cs * 100, 4),
                      gross_win_rate=round(float(100 * (gross > 0).mean()), 2),
                      net_win_rate=round(float(100 * (net > 0).mean()), 2),
                      coverage_ratio=round(float(net.mean() / (2 * cs * 100)), 2))

    # ---- 仓位/容量 ----
    def pos_stats(diag, kslot):
        w = np.array([t["weight"] for t in diag if t["weight"]], float)
        caps = np.array([t["cap1"] * kslot for t in diag if t["cap1"]], float)
        alloc = np.array([t["alloc"] for t in diag], float)
        return dict(config="KSLOT=%d" % kslot, n=len(diag),
                    weight_target=round(1.0 / kslot, 4),
                    weight_max=round(float(w.max()), 4), weight_median=round(float(np.median(w)), 4),
                    alloc_median=round(float(np.median(alloc)), 4),
                    account_cap_yuan=dict(p10=round(float(np.percentile(caps, 10)), 0),
                                          median=round(float(np.median(caps)), 0),
                                          p90=round(float(np.percentile(caps, 90)), 0)),
                    max_concurrent_est=int(max(1, round(float(np.nanmax(ext4["depl"])) * kslot))))
    pos_tab = [pos_stats(d4, 4), pos_stats(d20, 20)]

    # ---- 行情分层 ----
    def by_regime(diag, depl_arr, tag):
        out = {}
        for g in ("bull", "bear", "range"):
            sel = [t for t in diag if t["regime"] == g]
            r = np.array([t["ret_pct"] for t in sel], float)
            out[g] = dict(n=len(sel), mean=round(float(r.mean()), 4) if r.size else None,
                          win_rate=round(float(100 * (r > 0).mean()), 2) if r.size else None,
                          worst=round(float(r.min()), 4) if r.size else None)
        days = {g: int((regime == g).sum()) for g in ("bull", "bear", "range")}
        dep = {g: round(float(np.nanmean(depl_arr[regime == g])) * 100, 2) for g in ("bull", "bear", "range")}
        idle = depl_arr < 1e-9
        idle_by_reg = {g: int((idle & (regime == g)).sum()) for g in ("bull", "bear", "range")}
        crush_sel = [t for t in diag if t["crush"]]
        rc = np.array([t["ret_pct"] for t in crush_sel], float)
        return dict(config=tag, trades=out, days=days,
                    deploy_pct_by_regime=dep,
                    idle_days=int(idle.sum()), idle_pct=round(100 * float(idle.mean()), 2),
                    idle_days_by_regime=idle_by_reg,
                    crush_days=int(crush.sum()),
                    crush_idle_days=int((idle & crush).sum()),
                    crush_trades_n=len(crush_sel),
                    crush_mean=round(float(rc.mean()), 4) if rc.size else None,
                    crush_worst=round(float(rc.min()), 4) if rc.size else None)

    reg_tab = [by_regime(d4, ext4["depl"], "KSLOT=4"), by_regime(d20, ext20["depl"], "KSLOT=20")]

    # ---- 可成交性 ----
    def fillability(diag):
        gaps = np.array([t["gap_entry"] for t in diag if t["gap_entry"] is not None], float)
        locked = sum(1 for t in diag if t["exit_locked"])
        return dict(n=len(diag),
                    entry_limit_up_n=int((gaps >= 0.095).sum()),
                    entry_limit_up_pct=round(100 * float((gaps >= 0.095).mean()), 2),
                    entry_gap_median_pct=round(float(np.median(gaps) * 100), 3),
                    exit_locked_down_n=int(locked),
                    exit_locked_down_pct=round(100.0 * locked / max(1, len(diag)), 2))

    fill = fillability(d4)

    # ---- 持仓窗口 / 出场构成 ----
    hold = np.array([t["t_out"] - t["t_in"] for t in d4], float)
    tp = np.array([t["tp_hit"] for t in d4], float)
    flg = Counter(t["exit_flag"] for t in d4)
    mae = np.array([t["mae"] for t in d4 if t["mae"] is not None], float)
    exit_struct = dict(hold_days_median=float(np.median(hold)), hold_days_max=int(hold.max()),
                       tp_hit_pct=round(100 * float(tp.mean()), 2),
                       exit_flag_dist={str(k): int(v) for k, v in flg.items()},
                       mae_median_pct=round(float(np.median(mae) * 100), 2),
                       mae_p10_pct=round(float(np.percentile(mae, 10) * 100), 2),
                       mae_worst_pct=round(float(mae.min() * 100), 2),
                       trades_below_m5_pct=round(100 * float((mae <= -0.05).mean()), 2),
                       trades_below_m8_pct=round(100 * float((mae <= -0.08).mean()), 2))

    # ---- 静态件（②⑤⑦⑩⑫）----
    def fstat(p):
        p = R / p
        return dict(path=str(p.relative_to(R)), exists=p.exists(),
                    size=p.stat().st_size if p.exists() else None)
    static = {k: fstat(v) for k, v in {
        "冻结规格 oos_run.py": "backtest/hengpan_fangliang_dikai_0925/oos_run.py",
        "预注册": "backtest/PRE-REGISTRATION_20260926_hengpan_dikai_oos.md",
        "挂单清单工具": "backtest/hengpan_fangliang_dikai_0925/watch_next.py",
        "模拟盘引擎": "backtest/hengpan_fangliang_dikai_0925/hpdk_paper.py",
        "模拟盘状态": "backtest/hengpan_fangliang_dikai_0925/hpdk_paper.json",
        "挂单 CSV": "backtest/hengpan_fangliang_dikai_0925/orderlist_2026-09-24.csv",
        "T+0 勘误证据": "backtest/hengpan_fangliang_dikai_0925/evidence_t0_audit.json",
        "词汇表": "CONTEXT.md",
        "ADR-0010": "docs/adr/0010-short-board-new-strategies-onboarding.md",
    }.items()}
    prereg_txt = (R / "backtest/PRE-REGISTRATION_20260926_hengpan_dikai_oos.md").read_text(encoding="utf-8")
    errata = sorted(set(__import__("re").findall(r"E-\d+", prereg_txt)))
    oos_rep = json.loads((OUT / "oos_report.json").read_text(encoding="utf-8")) if (OUT / "oos_report.json").exists() else {}
    forward = dict(rep_verdict=oos_rep.get("verdict"), acc_n=(oos_rep.get("acceptance") or {}).get("n"),
                   shadow_start=oos_rep.get("shadow_start"), last_data_date=oos_rep.get("last_data_date"),
                   tp_hit_pct=oos_rep.get("tp_hit_pct"), gates=oos_rep.get("gates"))

    payload = dict(
        generated_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        topic="https://gushi.in/topic/468 《从模拟盘到实盘：上线前必须完成的 12 项检查》",
        object="缩量超跌 (st-hpdk)",
        frozen_script_sha256=sha, params=P, panel=dict(T=T, N=len(syms), names_loaded=done),
        anchors=dict(self_ext_vs_x2=anchor_self, ext_vs_x2_diff=bad,
                     vs_sensitivity_base=anchor_pub, sensitivity_diff=bad2,
                     sensitivity_file_generated=ev.get("sim_rule")),
        headline=dict(kslot4=ext4["metrics"], kslot20=ext20["metrics"]),
        cost=cost_stats, cost_table_k4=cost_tab, cost_table_k20=cost_tab20,
        position=pos_tab, regime=reg_tab, fillability=fill, exit_structure=exit_struct,
        stops=stops, redlines=[rl4, rl20], static=static,
        prereg_errata=errata, forward_oos=forward,
        skip=dict(k4=ext4["skip"], k20=ext20["skip"]),
        runtime_sec=round(time.time() - t0, 1))

    evf = OUT / "evidence_launch12_20260928.json"
    evf.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    log("[wrote] %s (%.0f B)" % (evf.name, evf.stat().st_size))

    # ---- 摘要 ----
    log("\n== 锚点 ==  扩展记账 vs sim_portfolio: %s ; vs evidence_sensitivity.base: %s"
        % ("一致" if not bad else bad, "一致" if not bad2 else bad2))
    log("== 头条 == KSLOT=4  ann=%.2f%%  mdd=%.2f%%  sharpe=%s  胜率=%s%%  单笔均=%s%%  笔数=%d  占用=%.2f%%"
        % (ext4["metrics"]["ann"], ext4["metrics"]["mdd"], ext4["metrics"]["sharpe"],
           ext4["metrics"]["win_rate"], ext4["metrics"]["mean_per_trade"],
           ext4["metrics"]["n_trades"], ext4["metrics"]["deploy_pct"]))
    log("          KSLOT=20 ann=%.2f%%  mdd=%.2f%%  sharpe=%s  胜率=%s%%  单笔均=%s%%  笔数=%d  占用=%.2f%%"
        % (ext20["metrics"]["ann"], ext20["metrics"]["mdd"], ext20["metrics"]["sharpe"],
           ext20["metrics"]["win_rate"], ext20["metrics"]["mean_per_trade"],
           ext20["metrics"]["n_trades"], ext20["metrics"]["deploy_pct"]))
    log("== 成本 == %s" % json.dumps(cost_stats, ensure_ascii=False))
    log("== 成本敏感(KSLOT=4) == %s" % json.dumps(cost_tab, ensure_ascii=False))
    log("== 仓位/容量 == %s" % json.dumps(pos_tab, ensure_ascii=False))
    log("== 行情分层 == %s" % json.dumps(reg_tab, ensure_ascii=False))
    log("== 可成交性 == %s" % json.dumps(fill, ensure_ascii=False))
    log("== 出场结构 == %s" % json.dumps(exit_struct, ensure_ascii=False))
    log("== 止损反事实(KSLOT=4) == %s" % json.dumps(stops, ensure_ascii=False))
    log("== 风控红线 == %s" % json.dumps([rl4, rl20], ensure_ascii=False))
    log("== 前向 OOS == %s" % json.dumps(forward, ensure_ascii=False))
    log("== 预注册勘误 == %s" % errata)
    log("[done] %.0fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
