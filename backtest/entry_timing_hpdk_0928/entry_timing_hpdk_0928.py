# -*- coding: utf-8 -*-
r"""entry_timing_hpdk_0928.py — 「缩量超跌 / 横盘低开·两日」(st-hpdk) 入场时点变体实测

问题：把「09:25 集合竞价挂单买入（= 买日开盘价成交）」改成「开盘后等一段时间再买」，
      是否真能少亏 / 提高期望？

只读纪律：
  · 信号集 = 冻结脚本 backtest/hengpan_fangliang_dikai_0925/oos_run.py（SHA256 0b61a4bb…）原样运行产出；
    本脚本对 oos_run.py 只做**运行期**干预（改模块级 P / 输出文件路径），不落盘、不改字节、不写生产产物。
  · 组合记账 = 复刻 x2_sens.sim_portfolio 的冻结规则（预注册 §1.5–10）：复合分降序取前 K；
    单票 = min(前一日净值/KSLOT, 可用现金)；KSLOT 并发上限；持仓期内不重复买；逐日收盘盯市；
    资金时序 entry_first（先入场 09:25 → 后出场 15:00；勘误 E-15）；单边成本 COST_SIDE。
  · 只改「入场时点 / 入场价」这一个旋钮。出场规则不变（止盈 +2%：T+2 日 open>=TP 按 open、
    否则 high>=TP 按 TP 成交；未达标 T+2 尾盘；不止损），只把 TP 阈值随新入场价重算。
  · 价格运算保留 float32（与冻结脚本同 dtype），避免 TP 触发判定的浮点边界漂移。

臂：
  A0  基线：买日(T+1)开盘价成交（09:25 挂单）
  A1  等一整天：买日(T+1)收盘价成交（尾盘再买）
  A2_x 限价挂单：挂 买日开盘价×(1−x)，x∈{0.5,1.0,1.5,2.0}%；当日 low ≤ 挂单价 → 成交于挂单价；否则弃单
  A3  路径统计（解释性）：信号集在买日的 (close−open)/open、(low−open)/open、(high−open)/open 分布

窗口 2018-01-02 ~ 2026-09-24（entry_date ≥ 2018-01-01）· 主板 · KSLOT=20 与 KSLOT=4 各一档。

用法：
  python entry_timing_hpdk_0928.py --cache "C:\...\x3cache" [--outdir <dir>]
"""
import argparse, importlib.util, json, math, os, pathlib, time
import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
R = HERE.parents[1]                      # project root
OOS = R / "backtest" / "hengpan_fangliang_dikai_0925" / "oos_run.py"
ANN = 244.0
START = "2018-01-01"
# 【勘误 E-22 · 2026-09-29】跟随新冻结 SHA（v1.7）；旧值 0b61a4bbce100ed6（v1.6 · E-19）留档
SHA_PREFIX = "2351eb9d42acc62e"   # v1.7a；旧值 7d14d27e(v1.7) / 0b61a4bb(v1.6) 留档
X_LADDER = (0.005, 0.010, 0.015, 0.020)

P_FROZEN = dict(P1=0.01, P2=0.03, K=10, KSLOT=20, MINAMT=2e7, MINPX=3.0, LISTED=250, TP=0.02,
                COST_SIDE=0.000346, SHADOW_START="2016-01-01", WORST_CASE_WIPEOUT=True,
                MAINBOARD=True,
              # 【校准 2026-09-29】改跟随生产默认（E-22 A+C）；旧写 STNOW_OFF=True 在新 3 值语义下
              # = 完全不用现名过滤（与生产不一致）。
              STP_CNT=3, STNOW_LIVE_ONLY=True, STNOW_OFF=False)

ARMSPEC = [("A0_开盘价(基线)", "A0", None), ("A1_买日收盘价", "A1", None)] + \
          [("A2_挂%.1f%%" % (x * 100), "A2", x) for x in X_LADDER]
ARM_ORDER = [a[0] for a in ARMSPEC]

# 同尺子锚点：evidence_sensitivity.json 的 subwindow_2018（2018-01-02~2026-09-24，主板，v1.6）
# 【勘误 E-22 · 2026-09-29】锚点随新冻结口径（v1.7 · A+C）更新；旧值留档：
#   v1.6：2018+ KSLOT20 ann=63.90 mdd=-27.41 sharpe=2.53 win=60.94 mean=0.4341 n=21146 ne=20473 dep=48.42
#         KSLOT4 ann=105.55 mdd=-30.16 sharpe=2.86 ne=4236 dep=49.94 ；全窗 47.30/-27.41/2.15/24492/23656/41.59
ANCHOR_2018 = {
    20: dict(ann=62.70, mdd=-26.80, sharpe=2.51, win_rate=60.64, mean_per_trade=0.4234,
            n_trades=21157, n_entries=20495, deploy_pct=48.45),
    4: dict(ann=106.16, mdd=-30.13, sharpe=2.86, n_trades=21157, n_entries=4238, deploy_pct=49.95),
}
ANCHOR_FULL = dict(ann=46.40, mdd=-26.80, sharpe=2.13, n_trades=24502, n_entries=23675, deploy_pct=41.61)


def log(*a):
    print(*a, flush=True)


def load_mod():
    spec = importlib.util.spec_from_file_location("oos_run_entry", OOS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_panel(mod, cache):
    f = pathlib.Path(cache) / "panel_oos.npz"
    cal, live, dead = mod.load_universe()
    syms = live + dead
    if f.exists():
        z = np.load(f, allow_pickle=True)
        if list(z["syms"]) == syms and list(z["cal"]) == cal:
            log("[cache] 面板 <- %s  (T=%d N=%d done=%d)" % (f, z["C"].shape[0], z["C"].shape[1], int(z["done"])))
            return cal, syms, {k: z[k] for k in ("O", "H", "L", "C", "V", "A")}, int(z["done"]), str(f)
        log("[cache] 缓存与当前 universe 不符 -> 重建")
    t0 = time.time()
    F, done = mod.build(cal, syms)
    log("[build] T=%d N=%d done=%d (%.1fs)" % (F["C"].shape[0], F["C"].shape[1], done, time.time() - t0))
    return cal, syms, F, done, "rebuilt(no-cache)"


def frozen_signals(mod, cal, syms, F, done, scratch):
    """原样跑冻结脚本 main()，只在运行期替换 P 与输出路径。返回逐笔信号记录（信号级，KSLOT 无关）。"""
    mod.P.clear(); mod.P.update(P_FROZEN)
    scratch = pathlib.Path(scratch); scratch.mkdir(parents=True, exist_ok=True)
    mod.STATE_F = scratch / "_entry_timing_state.json"
    mod.TRADES_F = scratch / "_entry_timing_trades.jsonl"
    mod.REPORT_F = scratch / "_entry_timing_report.json"
    for p in (mod.STATE_F, mod.TRADES_F, mod.REPORT_F):
        if p.exists(): p.unlink()
    mod.build = lambda _c, _s: (F, done)
    mod.main()
    recs = [json.loads(x) for x in mod.TRADES_F.read_text(encoding="utf-8").splitlines() if x.strip()]
    recs.sort(key=lambda r: r["signal_date"])          # 稳定排序：保持「信号日升序 + 复合分降序」
    log("[signals] %d 笔信号 (%s ~ %s)" % (len(recs), recs[0]["signal_date"], recs[-1]["signal_date"]))
    return recs


def ret_of(entry, x, c):
    """与 oos_run._ret_of 同式同 dtype（entry/x 为 float32 时全程 float32）。"""
    return -100.0 if x == 0 else (x * (1 - c) / (entry * (1 + c)) - 1) * 100


def exit_of(tb, j, entry, cal, O, H, C, T, tp):
    """冻结出场规则 v1.3（oos_run.py L183–202），TP 阈值 = entry×(1+tp)。entry 为该臂入场价（float32）。"""
    ex_t = tb + 1
    if ex_t >= T:
        return None
    exC, usedC, flagC = C[ex_t, j], ex_t, 0
    if not (np.isfinite(exC) and exC > 0):
        for k in range(ex_t + 1, min(ex_t + 6, T)):
            c = C[k, j]
            if np.isfinite(c) and c > 0:
                exC, usedC, flagC = c, k, 1
                break
        else:
            exC, usedC, flagC = np.float32(0.0), ex_t, 2      # worst case wipeout
    tp_lv = entry * (1.0 + tp)
    o2, h2 = O[ex_t, j], H[ex_t, j]
    if np.isfinite(h2) and h2 > 0 and np.isfinite(o2):
        if o2 >= tp_lv:
            return dict(exit_date=cal[ex_t], exit_px=o2, exit_flag=0, tp_hit=1)
        if h2 >= tp_lv:
            return dict(exit_date=cal[ex_t], exit_px=tp_lv, exit_flag=0, tp_hit=1)
    return dict(exit_date=cal[usedC], exit_px=exC, exit_flag=flagC, tp_hit=0)


def build_arm(recs, cal, syms, F, kind, x, P):
    """把冻结信号集映射到某入场时点臂的逐笔记录（含未成交/弃单）。"""
    O, H, C, L = F["O"], F["H"], F["C"], F["L"]
    T = C.shape[0]
    ci = {d: i for i, d in enumerate(cal)}
    si = {s: j for j, s in enumerate(syms)}
    cost = float(P["COST_SIDE"]); tp = float(P["TP"])
    out = []
    for r in recs:
        t = ci.get(r["signal_date"])
        if t is None:
            continue
        tb = t + 1
        if tb >= T:
            continue
        j = si[r["sym"]]
        o1, l1, c1, h1 = O[tb, j], L[tb, j], C[tb, j], H[tb, j]
        d = dict(signal_date=r["signal_date"], entry_date=cal[tb], sym=r["sym"],
                 base_entry_px=round(float(o1), 4), base_ret_pct=r["ret_pct"], base_tp=int(r.get("tp_hit", 0)),
                 open=round(float(o1), 4), low=round(float(l1), 4), high=round(float(h1), 4), close=round(float(c1), 4))
        filled, reason, entry, lim = 1, None, None, None
        if kind == "A0":
            entry = o1
        elif kind == "A1":
            if np.isfinite(c1) and c1 > 0:
                entry = c1
            else:
                filled, reason = 0, "买日收盘价缺失（无法尾盘成交）"
        else:
            lim = (o1 * (1.0 - x)) if (np.isfinite(o1) and o1 > 0) else np.float32(np.nan)
            d["limit_px"] = round(float(lim), 4) if np.isfinite(lim) else None
            if not (np.isfinite(o1) and o1 > 0):
                filled, reason = 0, "买日开盘价缺失"
            elif not (np.isfinite(l1) and l1 > 0):
                filled, reason = 0, "买日最低价缺失（无法判定成交）"
            elif l1 <= lim:
                entry = lim
            else:
                filled, reason = 0, "未触及挂单价"
        d["filled"] = filled
        d["nofill_reason"] = reason
        if filled and (not (np.isfinite(entry) and entry > 0)):
            filled = 0; d["filled"] = 0; d["nofill_reason"] = "入场价非正"; entry = None
        if filled:
            ex = exit_of(tb, j, entry, cal, O, H, C, T, tp)
            if ex is None:
                d["filled"] = 0; d["nofill_reason"] = "窗口末尾无法了结"; d["entry_px"] = round(float(entry), 4)
            else:
                d["entry_px"] = round(float(entry), 4)
                d.update(exit_date=ex["exit_date"], exit_px=round(float(ex["exit_px"]), 4),
                         tp_hit=int(ex["tp_hit"]), exit_flag=int(ex["exit_flag"]),
                         ret_pct=round(float(ret_of(entry, ex["exit_px"], cost)), 4),
                         gross_pct=round(float(ex["exit_px"] / entry - 1) * 100, 4))
        else:
            d["entry_px"] = None
            # 诊断用（不可执行的分解项）：假如成交在该臂价位，出场会怎样
            px = lim if kind == "A2" else (c1 if (np.isfinite(c1) and c1 > 0) else None)
            if px is not None and np.isfinite(px) and px > 0:
                ex = exit_of(tb, j, px, cal, O, H, C, T, tp)
                if ex is not None:
                    d["hypo_entry_px"] = round(float(px), 4)
                    d["hypo_ret_pct"] = round(float(ret_of(px, ex["exit_px"], cost)), 4)
                    d["hypo_tp_hit"] = int(ex["tp_hit"])
        out.append(d)
    return out


def sim_portfolio(recs, cal, syms, F, K, KSLOT, cost_side, start=None, order="entry_first"):
    """复刻 x2_sens.sim_portfolio（冻结记账）。filled=0 的弃单不占槽位、不动现金。"""
    T = len(cal)
    jof = {s: j for j, s in enumerate(syms)}
    C = F["C"]
    by_entry = {}
    for r in recs:
        if not r.get("filled", 1):
            continue
        by_entry.setdefault(r["entry_date"], []).append(r)
    nav = np.full(T, np.nan)
    depl = np.full(T, np.nan)
    cash, pos, n_in = 1.0, [], 0
    ex_r = []          # 组合真实成交（实际占槽位）的逐笔净收益

    def do_entry(t, d):
        nonlocal cash, n_in
        if not (start is None or d >= start):
            return
        for r in by_entry.get(d, [])[:K]:
            if len(pos) >= KSLOT:
                break
            if any(q["sym"] == r["sym"] for q in pos):
                continue
            navprev = nav[t - 1] if (t > 0 and np.isfinite(nav[t - 1])) else 1.0
            alloc = min(navprev / KSLOT, cash)
            if alloc <= 1e-12:
                break
            px = r["entry_px"]
            if px is None or not (np.isfinite(px) and px > 0):
                continue
            cash -= alloc
            pos.append(dict(sym=r["sym"], shares=alloc / (px * (1.0 + cost_side)), entry_px=px,
                            exit_date=r["exit_date"], exit_px=r["exit_px"]))
            n_in += 1

    def do_exit(d):
        nonlocal cash
        for p in list(pos):
            if p["exit_date"] == d:
                cash += p["shares"] * p["exit_px"] * (1.0 - cost_side)
                pos.remove(p)
                ex_r.append(float((p["exit_px"] * (1.0 - cost_side) / (p["entry_px"] * (1.0 + cost_side)) - 1) * 100))

    for t in range(T):
        d = cal[t]
        if order == "entry_first":
            do_entry(t, d); do_exit(d)
        else:
            do_exit(d); do_entry(t, d)
        mv = 0.0
        for p in pos:
            j = jof.get(p["sym"]); c = C[t, j] if j is not None else np.nan
            if not (np.isfinite(c) and c > 0):
                c = p["entry_px"]
            mv += p["shares"] * c
        nav[t] = cash + mv
        depl[t] = (mv / nav[t]) if nav[t] > 0 else np.nan
    idx_all = [i for i in range(T) if start is None or cal[i] >= start]
    if not idx_all:
        return None, None, None
    i0 = idx_all[0]
    nav = nav.copy(); nav[i0] = 1.0
    v = nav[idx_all]
    if v.size < 30 or not np.all(np.isfinite(v)):
        return None, None, None
    nd = len(v) - 1
    ann = (v[-1] / v[0]) ** (ANN / nd) - 1
    pk = np.maximum.accumulate(v)
    mdd = float((v / pk - 1).min())
    dr = v[1:] / v[:-1] - 1
    sd = dr.std(ddof=1)
    r_in = [r for r in recs if r.get("filled", 1) and r.get("ret_pct") is not None and (start is None or r["entry_date"] >= start)]
    rets = np.array([r["ret_pct"] for r in r_in], float)
    yrs = {}
    for i in idx_all:
        yrs.setdefault(cal[i][:4], []).append(i)
    yret = {}
    for y, ii in sorted(yrs.items()):
        j0 = ii[0] - 1
        base = nav[j0] if (j0 >= 0 and np.isfinite(nav[j0])) else 1.0
        yret[y] = round(float(nav[ii[-1]] / base - 1) * 100, 2)
    dd = depl[idx_all]
    m = dict(ann=round(ann * 100, 2), mdd=round(mdd * 100, 2),
             sharpe=None if sd == 0 else round(float(dr.mean() / sd * math.sqrt(ANN)), 2),
             win_rate=round(float(100 * (rets > 0).mean()), 2) if rets.size else None,
             mean_per_trade=round(float(rets.mean()), 4) if rets.size else None,
             med_per_trade=round(float(np.median(rets)), 4) if rets.size else None,
             n_trades=int(rets.size), n_entries=int(n_in),
             deploy_pct=round(float(np.nanmean(dd)) * 100, 2),
             exec_n=int(len(ex_r)),
             exec_mean=round(float(np.mean(ex_r)), 4) if ex_r else None,
             exec_med=round(float(np.median(ex_r)), 4) if ex_r else None,
             exec_win=round(float(100 * np.mean([x > 0 for x in ex_r])), 2) if ex_r else None,
             neg_years=int(sum(1 for x in yret.values() if x < 0)), n_years=len(yret), yearly=yret,
             window=[cal[i0], cal[idx_all[-1]]], order=order)
    return m, nav, idx_all


def event_stats(recs, start=START):
    r_all = [r for r in recs if r["entry_date"] >= start]
    fl = [r for r in r_all if r.get("filled", 1) and r.get("ret_pct") is not None]
    nf = [r for r in r_all if not r.get("filled", 1)]

    def blk(rows, key="ret_pct", tpkey="tp_hit"):
        a = np.array([r[key] for r in rows if r.get(key) is not None], float)
        if not a.size:
            return dict(n=0)
        return dict(n=int(a.size), mean=round(float(a.mean()), 4), med=round(float(np.median(a)), 4),
                    win=round(float(100 * (a > 0).mean()), 2),
                    p05=round(float(np.percentile(a, 5)), 4), p95=round(float(np.percentile(a, 95)), 4),
                    tp_hit_pct=round(float(100 * np.mean([r.get(tpkey, 0) for r in rows])), 2))
    days = sorted({r["entry_date"] for r in r_all})
    days_fl = sorted({r["entry_date"] for r in fl})
    return dict(n_signals=len(r_all), n_filled=len(fl), n_nofill=len(nf),
                fill_rate_pct=round(100 * len(fl) / max(1, len(r_all)), 2),
                days_with_signal=len(days), days_with_fill=len(days_fl),
                days_zero_fill=len(days) - len(days_fl),
                share_days_zero_fill_pct=round(100 * (len(days) - len(days_fl)) / max(1, len(days)), 2),
                filled=blk(fl), filled_at_base_price=blk(fl, "base_ret_pct", "base_tp"),
                nofill_base=blk(nf, "base_ret_pct", "base_tp"), nofill_hypo=blk(nf, "hypo_ret_pct", "hypo_tp_hit"))


def a3_path_stats(recs, cal, syms, F, start=START):
    O, H, C, L = F["O"], F["H"], F["C"], F["L"]
    ci = {d: i for i, d in enumerate(cal)}; si = {s: j for j, s in enumerate(syms)}
    rows = []
    for r in recs:
        if r["entry_date"] < start:
            continue
        tb = ci[r["signal_date"]] + 1
        j = si[r["sym"]]
        o1 = float(O[tb, j])
        if not (np.isfinite(o1) and o1 > 0):
            continue
        rows.append((float(C[tb, j]) / o1 - 1.0, float(L[tb, j]) / o1 - 1.0, float(H[tb, j]) / o1 - 1.0))
    a = np.array(rows, float)

    def d(x):
        x = x[np.isfinite(x)]
        return dict(n=int(x.size), mean=round(float(x.mean()) * 100, 4), med=round(float(np.median(x)) * 100, 4),
                    p05=round(float(np.percentile(x, 5)) * 100, 4), p25=round(float(np.percentile(x, 25)) * 100, 4),
                    p75=round(float(np.percentile(x, 75)) * 100, 4), p95=round(float(np.percentile(x, 95)) * 100, 4),
                    share_neg_pct=round(float(100 * (x < 0).mean()), 2))
    out = dict(n=len(a), close_vs_open=d(a[:, 0]), low_vs_open=d(a[:, 1]), high_vs_open=d(a[:, 2]), touch_pct={})
    for x in X_LADDER:
        out["touch_pct"]["low_le_-%.1f%%" % (x * 100)] = round(float(100 * np.mean(a[:, 1] <= -x)), 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.environ.get("PI_SCRATCH_DIR") or ".")
    ap.add_argument("--scratch", default=os.environ.get("PI_SCRATCH_DIR") or ".")
    ap.add_argument("--outdir", default=str(HERE))
    a = ap.parse_args()
    outdir = pathlib.Path(a.outdir); outdir.mkdir(parents=True, exist_ok=True)

    mod = load_mod()
    sha = mod.FROZEN_SHA
    log("冻结脚本 %s" % OOS)
    log("冻结脚本 SHA256 = %s" % sha)
    assert sha.startswith(SHA_PREFIX), "冻结脚本 SHA 变了：%s" % sha
    cal, syms, F, done, panel_src = load_panel(mod, a.cache)
    recs = frozen_signals(mod, cal, syms, F, done, a.scratch)
    assert mod.FROZEN_SHA == sha, "运行期冻结脚本 SHA 被改动！"

    A0L = ARM_ORDER[0]
    K = int(P_FROZEN["K"]); cost = float(P_FROZEN["COST_SIDE"])
    ev, port, navs, trades_all = {}, {}, {}, {}
    for label, kind, x in ARMSPEC:
        tr = build_arm(recs, cal, syms, F, kind, x, P_FROZEN)
        trades_all[label] = tr
        ev[label] = event_stats(tr)
        port[label] = {}
        for ks in (20, 4):
            m, nav, idx = sim_portfolio(tr, cal, syms, F, K, ks, cost, start=START)
            port[label]["KSLOT_%d" % ks] = m
            navs["%s|KSLOT_%d" % (label, ks)] = (nav, idx)
        m20e, _, _ = sim_portfolio(tr, cal, syms, F, K, 20, cost, start=START, order="exit_first")
        m4e, _, _ = sim_portfolio(tr, cal, syms, F, K, 4, cost, start=START, order="exit_first")
        port[label]["KSLOT_20_exitfirst_sens"] = m20e
        port[label]["KSLOT_4_exitfirst_sens"] = m4e
        log("[arm] %-16s 成交率 %6.2f%%  n=%6d  单笔净均 %+8.4f%%  2018+年化 %s" %
            (label, ev[label]["fill_rate_pct"], ev[label]["n_filled"], (ev[label]["filled"].get("mean") or 0.0),
             port[label]["KSLOT_20"]["ann"] if port[label]["KSLOT_20"] else None))

    m_full, _, _ = sim_portfolio(trades_all[A0L], cal, syms, F, K, 20, cost, start=None)
    anchors = {"anchor_source": "backtest/hengpan_fangliang_dikai_0925/evidence_sensitivity.json (subwindow_2018 / base)",
               "checked": {}}
    ok = True
    for ks, ref in ANCHOR_2018.items():
        got = port["A0_开盘价(基线)"]["KSLOT_%d" % ks]
        for k, v in ref.items():
            g = got[k] if got else None
            good = (g is not None) and (int(g) == int(v) if isinstance(v, int) else abs(float(g) - float(v)) <= 0.011)
            ok = ok and good
            anchors["checked"]["KSLOT_%d.%s" % (ks, k)] = dict(got=g, expect=v, pass_=bool(good))
    for k, v in ANCHOR_FULL.items():
        g = m_full[k]
        good = (g is not None) and (int(g) == int(v) if isinstance(v, int) else abs(float(g) - float(v)) <= 0.011)
        ok = ok and good
        anchors["checked"]["FULLWINDOW.%s" % k] = dict(got=g, expect=v, pass_=bool(good))
    # 出场复刻自检：A0 的逐笔 ret_pct 必须与冻结脚本写出的 ret_pct 逐笔一致
    a0 = [r for r in trades_all["A0_开盘价(基线)"] if r.get("ret_pct") is not None and r.get("base_ret_pct") is not None]
    dmax = max(abs(r["ret_pct"] - r["base_ret_pct"]) for r in a0) if a0 else None
    anchors["exit_replication_max_abs_diff_pct"] = dmax
    anchors["exit_replication_ok"] = (dmax == 0)
    ok = ok and (dmax == 0)
    anchors["all_pass"] = bool(ok)
    log("同尺子锚点 %s（A0 逐笔 ret 复刻最大偏差 = %s）" % ("全部通过" if ok else "!! 有不通过项", dmax))
    for k, v in anchors["checked"].items():
        if not v["pass_"]:
            log("   FAIL %s got=%s expect=%s" % (k, v["got"], v["expect"]))

    a3 = a3_path_stats(recs, cal, syms, F)
    a3_win = a3_path_stats(recs, cal, syms, F, start="2015-01-01")
    log("[A3 2018+] n=%d close-vs-open 均 %+.4f%% 中位 %+.4f%% 为负 %.2f%% | low-vs-open 均 %+.4f%% 中位 %+.4f%% | H-O 均 %+.4f%%" %
        (a3["n"], a3["close_vs_open"]["mean"], a3["close_vs_open"]["med"], a3["close_vs_open"]["share_neg_pct"],
         a3["low_vs_open"]["mean"], a3["low_vs_open"]["med"], a3["high_vs_open"]["mean"]))

    base20 = port["A0_开盘价(基线)"]["KSLOT_20"]; base4 = port["A0_开盘价(基线)"]["KSLOT_4"]
    deltas = {}
    for label in ARM_ORDER[1:]:
        deltas[label] = {}
        for ks, b in ((20, base20), (4, base4)):
            g = port[label]["KSLOT_%d" % ks]
            if g is None or b is None:
                continue
            deltas[label]["KSLOT_%d" % ks] = dict(
                d_ann_pp=round(g["ann"] - b["ann"], 2), d_mdd_pp=round(g["mdd"] - b["mdd"], 2),
                d_sharpe=round((g["sharpe"] or 0) - (b["sharpe"] or 0), 2),
                d_n_entries=int(g["n_entries"] - b["n_entries"]),
                d_deploy_pp=round(g["deploy_pct"] - b["deploy_pct"], 2),
                d_mean_bp=round((g["mean_per_trade"] - b["mean_per_trade"]) * 100, 2))

    payload = dict(
        _what="「缩量超跌 / 横盘低开·两日」(st-hpdk) 入场时点变体实测（只读生产；2026-09-28）",
        frozen_script=str(OOS), frozen_script_sha256=sha, frozen_sha_prefix_expect=SHA_PREFIX,
        params=P_FROZEN, ann_factor=ANN, window_start=START,
        sim_rule=("复刻 x2_sens.sim_portfolio（预注册 §1.5–10）: 复合分降序取前 K；单票=min(前一日净值/KSLOT,可用现金)；"
                  "KSLOT 并发上限；持仓期内不重复买；逐日收盘盯市；单边成本 %g；资金时序 entry_first（E-15）；弃单不占槽位。" % cost),
        panel=dict(source=panel_src, T=int(F["C"].shape[0]), N=int(F["C"].shape[1]), names_loaded=done),
        entry_rule={l: ("买日(T+1)开盘价成交（09:25 挂单）" if k == "A0" else
                        "买日(T+1)收盘价成交（尾盘再买）" if k == "A1" else
                        "挂 买日开盘价×(1−%.1f%%)，当日 low≤挂单价→成交于挂单价，否则弃单" % (x * 100))
                    for l, k, x in ARMSPEC},
        exit_rule="不变：止盈 +2%（T+2 日 open≥TP 按 open，否则 high≥TP 按 TP 成交），未达标 T+2 尾盘；不止损；TP 阈值随该臂入场价重算",
        cost_side=cost, cost_roundtrip_bp=round(cost * 2 * 1e4, 2),
        arms=port, event_stats=ev, deltas_vs_A0=deltas,
        path_stats_A3_2018=a3, path_stats_A3_fullwindow=a3_win, anchors=anchors,
        known_limits=[
            "日线口径：只有买日 open/high/low/close 四个锚点，不知道「日内最低/最高发生的时刻」→ 无法建模「10:30 之后再市价买」这类具体延后时点；"
            "A1 是端点（尾盘），A2 是用 low 判定的挂单型（日线下唯一可近似的中途低吸方式）。",
            "A1 的成交价按买日收盘价 = 模型假设（真实尾盘市价单成交价≈收盘但不等于收盘，有跟踪误差）。",
            "A2 只判「价格是否触及」，未建模成交量/排队/封板堵单/部分成交（按全额成交假设）→ 成交率是乐观上界。",
            "A2 未建模「挂单在开盘价下方，若当日 low 恰等于挂单价但尾盘封死」的排队风险。",
            "出场规则沿用冻结 v1.3（止盈用到 T+2 当日 high），属既有口径、非本次新增假设。",
            "A1/A2 的 TP 阈值随新入场价下移（+2% 目标不变，绝对价位更低）→ 止盈命中率上升是规则内生的，不是新增优势。",
            "窗口 2018-01-02~2026-09-24 为样本内（前向 OOS 自 2026-09-28 起，样本 = 0）。",
            "资金时序：主表统一 entry_first（与冻结基线同规则，便于归因）；A1 的尾盘买入在现实中可与同日尾盘卖出共用资金，"
            "已附 exit_first 敏感性列（KSLOT=4 档差异最大）。",
        ],
        commands=dict(run='python backtest/entry_timing_hpdk_0928/entry_timing_hpdk_0928.py --cache "<panel cache dir>" --scratch "$env:PI_SCRATCH_DIR"'),
    )
    (outdir / "entry_timing_hpdk_0928_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    ids = navs["A0_开盘价(基线)|KSLOT_20"][1]
    cols_nav = sorted(navs.keys())
    lines = ["date," + ",".join(cols_nav)]
    for i in ids:
        row = [cal[i]]
        for c in cols_nav:
            nv = navs[c][0][i]
            row.append(("%.6f" % nv) if np.isfinite(nv) else "")
        lines.append(",".join(row))
    (outdir / "entry_timing_hpdk_0928_equity.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    cols = ["arm", "signal_date", "entry_date", "sym", "filled", "nofill_reason", "limit_px", "entry_px",
            "exit_date", "exit_px", "tp_hit", "ret_pct", "base_ret_pct", "hypo_entry_px", "hypo_ret_pct"]
    tlines = [",".join(cols)]
    for label in ARM_ORDER:
        for r in trades_all[label]:
            if r["entry_date"] < START:
                continue
            vals = [label if c == "arm" else r.get(c) for c in cols]
            tlines.append(",".join("" if v is None else str(v) for v in vals))
    (outdir / "entry_timing_hpdk_0928_trades.csv").write_text("\n".join(tlines) + "\n", encoding="utf-8")

    log("=" * 122)
    log("%-16s %-6s %9s %9s %8s %8s %10s %10s %9s %9s %8s" %
        ("臂", "KSLOT", "成交率%", "年化%", "MDD%", "夏普", "单笔净均%", "单笔净中%", "净胜率%", "笔数", "占用%"))
    for label in ARM_ORDER:
        for ks in (20, 4):
            m = port[label]["KSLOT_%d" % ks]
            if m is None:
                log("%-16s %-6d (空)" % (label, ks)); continue
            log("%-16s %-6d %9.2f %+9.2f %8.2f %8s %+10.4f %+10.4f %9.2f %9d %8.2f" %
                (label, ks, ev[label]["fill_rate_pct"], m["ann"], m["mdd"], m["sharpe"],
                 m["mean_per_trade"], m["med_per_trade"], m["win_rate"], m["n_trades"], m["deploy_pct"]))
    log("产物 -> %s" % outdir)
    log("entry_timing_hpdk_0928.py DONE  anchors_all_pass=%s" % anchors["all_pass"])
    return payload


if __name__ == "__main__":
    main()
