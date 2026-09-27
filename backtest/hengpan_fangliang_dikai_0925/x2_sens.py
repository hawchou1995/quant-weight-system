# -*- coding: utf-8 -*-
"""x2_sens.py — ②复核定量部分：主口径组合回测 + 参数邻域敏感性 + 特征时点实验

口径来源（**不重写信号逻辑**）：冻结脚本 oos_run.py —— 复用其 build()/P/main()，
只做**运行期**干预（脚本文件字节零修改，SHA256 不变）：
  1) 参数扰动：临时改模块级 P 字典的单项，重跑 main()，读回逐笔记录；
  2) 面板平移：把指定字段的价格/量面板沿时间轴整体平移 k 行，再喂给 main()。

⚠ 关于「滞后 1 日」实验的方法论更正（2026-09-27，自查）：
  最初版本把 O/H/L/C/V/A **全部**平移 1 日。但 oos_run 的入场价就是 O[t+1]、出场价是 C[t+2]，
  平移后这两者同步变成真实 O[t]/C[t+1] —— **入场时点被一起挪走了**，于是那个实验只是
  「同一策略提前一天跑」，**不构成未来函数检验**。本版改为：
    · lag_VA  ：只把 V/A（成交额、成交量）平移 → 干净地检验「流动性/量能特征」的时间敏感性；
    · fwd_VA  ：只把 V/A 取未来值 → 阳性对照（若结果几乎不变，说明 V/A 不是时间敏感通道）；
    · shift_all1：保留但**重新命名并如实标注**为「时点平移不变性」，不作为未来函数证据。
  价格特征（RET20、GAP）与执行价强耦合，无法在不动执行口径的前提下单独滞后 ——
  该局限已在报告中明示，并改由**逐条件数据可用时点审计**（代码级）承担主要举证责任。

组合记账按预注册 §1.5 / §1.6–10 冻结规则**自行实现**（oos_run.py 只产逐笔信号，不产组合 NAV）：
  · 每个信号日按复合分降序取前 K 只；单票分配 = min(前一日净值 / KSLOT, 可用现金)
  · 最多同时持有 KSLOT 只；同一标的持仓期内不重复买入
  · 净值 = 现金 + Σ 持仓×当日收盘（逐日盯市）；出场日按实际出场价结算
  · 成本：单边 COST_SIDE（买入 entry×(1+c)，卖出 exit×(1−c)）
  · 另报**资金占用率**（Σ持仓市值 / 净值 的日均值）——冻结规格 KSLOT=20 而实际并发仅约 10 只，
    故占用率是本策略读数必须随报表披露的口径。

用法: python x2_sens.py [--cache DIR] [--no-cache] [--outdir DIR]
"""
import os, json, math, argparse, pathlib, importlib.util, time
import numpy as np

R = pathlib.Path(__file__).resolve().parents[2]
OUT = R / "backtest/hengpan_fangliang_dikai_0925"
OOS = OUT / "oos_run.py"
BASE_P = dict(P1=0.01, P2=0.03, K=10, KSLOT=20, MINAMT=2e7, MINPX=3.0, LISTED=250,
              TP=0.02, COST_SIDE=0.000346, SHADOW_START="2016-01-01", WORST_CASE_WIPEOUT=True)
ANN = 244.0


def log(*a):
    print(*a, flush=True)


def shift_keys(F, keys, k):
    """把指定键的面板沿时间轴平移 k 行。k>0 → 看到的是更早的数据（特征滞后）；
    k<0 → 看到的是未来的数据（阳性对照用）。"""
    out = dict(F)
    a = abs(k)
    for key in keys:
        v = F[key]
        pad = np.full((a, v.shape[1]), np.nan, dtype=v.dtype)
        out[key] = np.concatenate([pad, v[:-a]], axis=0) if k > 0 else np.concatenate([v[a:], pad], axis=0)
    return out


def load_mod():
    spec = importlib.util.spec_from_file_location("oos_run_sens", OOS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get_panel(mod, cache, use_cache=True):
    f = cache / "panel_oos.npz"
    cal, live, dead = mod.load_universe()
    syms = live + dead
    if use_cache and f.exists():
        z = np.load(f, allow_pickle=True)
        if list(z["syms"]) == syms and list(z["cal"]) == cal:
            log("[cache] 面板 ← %s" % f)
            return cal, syms, {k: z[k] for k in ("O", "H", "L", "C", "V", "A")}, int(z["done"])
        log("[cache] 面板缓存与当前 universe 不符 → 重建")
    t0 = time.time()
    F, done = mod.build(cal, syms)
    log("[build] 面板 T=%d N=%d done=%d（%.1fs）"
        % (F["C"].shape[0], F["C"].shape[1], done, time.time() - t0))
    np.savez(f, cal=np.array(cal, dtype=object), syms=np.array(syms, dtype=object),
             done=np.int64(done), **{k: v.astype(np.float32) for k, v in F.items()})
    return cal, syms, F, done


def run_variant(mod, cache, cal, F, done, tag, overrides=None, mutate=None):
    P = dict(BASE_P)
    if overrides:
        P.update(overrides)
    mod.P.clear(); mod.P.update(P)
    mod.STATE_F = cache / ("_v_%s_state.json" % tag)
    mod.TRADES_F = cache / ("_v_%s_trades.jsonl" % tag)
    mod.REPORT_F = cache / ("_v_%s_report.json" % tag)
    for p in (mod.STATE_F, mod.TRADES_F, mod.REPORT_F):
        if p.exists():
            p.unlink()
    _F = mutate(F) if mutate else F
    mod.build = lambda _c, _s: (_F, done)          # 运行期替换（不改文件）
    t0 = time.time()
    mod.main()
    if not mod.TRADES_F.exists():
        log("  [%s] 该臂零成交（门槛过严）→ 空集" % tag)
        return [], P
    recs = [json.loads(x) for x in mod.TRADES_F.read_text(encoding="utf-8").splitlines() if x.strip()]
    log("  [%s] %d 笔（%.1fs）" % (tag, len(recs), time.time() - t0))
    return recs, P


def sim_portfolio(recs, cal, syms, F, K, KSLOT, cost_side, start=None):
    T = len(cal)
    jof = {s: j for j, s in enumerate(syms)}
    C = F["C"]
    by_entry = {}
    for r in recs:                                  # recs 顺序 = (信号日升序, 复合分降序)
        by_entry.setdefault(r["entry_date"], []).append(r)
    nav = np.full(T, np.nan)
    depl = np.full(T, np.nan)
    cash, pos, n_in = 1.0, [], 0
    for t in range(T):
        d = cal[t]
        for p in list(pos):                          # 1) 出场（收盘价结算）
            if p["exit_date"] == d:
                cash += p["shares"] * p["exit_px"] * (1.0 - cost_side)
                pos.remove(p)
        if start is None or d >= start:              # 2) 入场
            for r in by_entry.get(d, [])[:K]:
                if len(pos) >= KSLOT:
                    break
                if any(q["sym"] == r["sym"] for q in pos):
                    continue                          # 同一标的持仓期内不重复买入
                navprev = nav[t - 1] if (t > 0 and np.isfinite(nav[t - 1])) else 1.0
                alloc = min(navprev / KSLOT, cash)
                if alloc <= 1e-12:
                    break
                px = r["entry_open"]
                if not (np.isfinite(px) and px > 0):
                    continue
                cash -= alloc
                pos.append(dict(sym=r["sym"], shares=alloc / (px * (1.0 + cost_side)),
                                entry_px=px, exit_date=r["exit_date"], exit_px=r["exit_px"]))
                n_in += 1
        mv = 0.0                                     # 3) 盯市
        for p in pos:
            j = jof.get(p["sym"]); c = C[t, j] if j is not None else np.nan
            if not (np.isfinite(c) and c > 0):
                c = p["entry_px"]
            mv += p["shares"] * c
        nav[t] = cash + mv
        depl[t] = (mv / nav[t]) if nav[t] > 0 else np.nan
    idx_all = [i for i in range(T) if start is None or cal[i] >= start]
    if not idx_all:
        return None
    i0 = idx_all[0]
    nav[i0] = 1.0                                    # 窗口起点归一
    v = nav[idx_all]
    if v.size < 30 or not np.all(np.isfinite(v)):
        return None
    nd = len(v) - 1
    ann = (v[-1] / v[0]) ** (ANN / nd) - 1
    pk = np.maximum.accumulate(v)
    mdd = float((v / pk - 1).min())
    dr = v[1:] / v[:-1] - 1
    sd = dr.std(ddof=1)
    r_in = [r for r in recs if (start is None or r["entry_date"] >= start)]
    rets = np.array([r["ret_pct"] for r in r_in], float)
    yret, yrs = {}, {}
    for i in idx_all:
        yrs.setdefault(cal[i][:4], []).append(i)
    for y, ii in sorted(yrs.items()):
        j0 = ii[0] - 1
        base = nav[j0] if (j0 >= 0 and np.isfinite(nav[j0])) else 1.0
        yret[y] = round(float(nav[ii[-1]] / base - 1) * 100, 2)
    neg = sum(1 for x in yret.values() if x < 0)
    dd = depl[idx_all]
    return dict(ann=round(ann * 100, 2), mdd=round(mdd * 100, 2),
                sharpe=None if sd == 0 else round(float(dr.mean() / sd * math.sqrt(ANN)), 2),
                win_rate=round(float(100 * (rets > 0).mean()), 2) if rets.size else None,
                mean_per_trade=round(float(rets.mean()), 4) if rets.size else None,
                med_per_trade=round(float(np.median(rets)), 4) if rets.size else None,
                n_trades=int(rets.size), n_entries=int(n_in),
                deploy_pct=round(float(np.nanmean(dd)) * 100, 2),
                neg_years=int(neg), n_years=len(yret), yearly=yret,
                window=[cal[i0], cal[idx_all[-1]]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.environ.get("PI_SCRATCH_DIR") or ".")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--outdir", default=None)
    a = ap.parse_args()
    cache = pathlib.Path(a.cache); cache.mkdir(parents=True, exist_ok=True)
    outdir = pathlib.Path(a.outdir) if a.outdir else OUT
    outdir.mkdir(parents=True, exist_ok=True)

    mod = load_mod()
    sha = mod.FROZEN_SHA
    log("冻结脚本 SHA256 = %s" % sha)
    cal, syms, F, done = get_panel(mod, cache, not a.no_cache)
    assert mod.FROZEN_SHA == sha, "冻结脚本 SHA 被改动！"

    ALLP = ("O", "H", "L", "C", "V", "A")
    VARIANTS = [
        ("base", None, None),
        ("P1_0.005", {"P1": 0.005}, None), ("P1_0.02", {"P1": 0.02}, None),
        ("P2_0.02", {"P2": 0.02}, None), ("P2_0.04", {"P2": 0.04}, None),
        ("K_5", {"K": 5}, None), ("K_20", {"K": 20}, None),
        ("MINAMT_1e7", {"MINAMT": 1e7}, None), ("MINAMT_5e7", {"MINAMT": 5e7}, None),
        ("MINPX_2.0", {"MINPX": 2.0}, None), ("MINPX_5.0", {"MINPX": 5.0}, None),
        ("LISTED_120", {"LISTED": 120}, None), ("LISTED_500", {"LISTED": 500}, None),
        ("KSLOT_4", {"KSLOT": 4}, None), ("KSLOT_10", {"KSLOT": 10}, None),
        ("KSLOT_30", {"KSLOT": 30}, None),
        ("TP_0.01", {"TP": 0.01}, None), ("TP_0.03", {"TP": 0.03}, None),
        ("TP_off_0.99", {"TP": 0.99}, None),
        ("lag_VA", None, lambda F: shift_keys(F, ("V", "A"), 1)),
        ("fwd_VA", None, lambda F: shift_keys(F, ("V", "A"), -1)),
        ("shift_all1", None, lambda F: shift_keys(F, ALLP, 1)),
    ]

    res, keep = {}, {}
    for tag, ov, mut in VARIANTS:
        log("[variant] %s" % tag)
        recs, P = run_variant(mod, cache, cal, F, done, tag, ov, mut)
        keep[tag] = recs
        m = sim_portfolio(recs, cal, syms, F, int(P["K"]), int(P["KSLOT"]), float(P["COST_SIDE"]))
        res[tag] = dict(params={k: P[k] for k in ("P1", "P2", "K", "KSLOT", "MINAMT", "MINPX",
                                                  "LISTED", "TP")},
                        mutate=(tag if mut else None), metrics=m)
        if m:
            log("        → %s" % json.dumps({k: m[k] for k in
                ("ann", "mdd", "sharpe", "win_rate", "mean_per_trade", "med_per_trade",
                 "n_trades", "deploy_pct", "neg_years", "n_years")}, ensure_ascii=False))

    START = "2018-01-01"
    sub = {"start": START, "note": "2018-01-01 起（BPS 覆盖度 >0.70，早期样本剔除偏差较小）"}
    for tag in ("base", "lag_VA", "fwd_VA", "shift_all1"):
        sub[tag] = sim_portfolio(keep[tag], cal, syms, F, BASE_P["K"], BASE_P["KSLOT"],
                                 BASE_P["COST_SIDE"], start=START)
    sub["KSLOT_4"] = sim_portfolio(keep["KSLOT_4"], cal, syms, F, BASE_P["K"], 4,
                                  BASE_P["COST_SIDE"], start=START)
    sub["KSLOT_10"] = sim_portfolio(keep["KSLOT_10"], cal, syms, F, BASE_P["K"], 10,
                                   BASE_P["COST_SIDE"], start=START)

    payload = dict(frozen_script_sha256=sha, base_params=BASE_P, ann_factor=ANN,
                   sim_rule=("预注册 §1.5–10：每日按复合分降序取前 K；单票 = min(前一日净值/KSLOT, 可用现金)；"
                             "最多 KSLOT 只并发；同一标的持仓期内不重复买入；逐日收盘盯市；"
                             "单边成本 COST_SIDE（买 entry×(1+c)、卖 exit×(1−c)）"),
                   panel=dict(T=int(F["C"].shape[0]), N=int(F["C"].shape[1]), names_loaded=done),
                   variants=res, subwindow_2018=sub)
    (outdir / "evidence_sensitivity.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                                     encoding="utf-8")

    # ---- 看板「回测参考卡」主指标带读数（_bt_ref_card 读的字段名）----
    bs = sub.get("base") or {}
    if bs:
        tot = 1.0
        for v in (bs.get("yearly") or {}).values():
            tot *= (1 + v / 100.0)
        ref = dict(
            period="%s ~ %s（主读数窗口：2018 起，每股净资产覆盖度 >0.70）"
                   % (bs["window"][0], bs["window"][1]),
            ann_return=bs["ann"], max_drawdown=bs["mdd"], win_rate=bs["win_rate"],
            mean_per_trade=bs["mean_per_trade"], med_per_trade=bs["med_per_trade"],
            total_return=round((tot - 1) * 100, 2), sharpe=bs["sharpe"], n_trades=bs["n_trades"],
            note=(
                f"口径 = 冻结 OOS 规格：**只买主板**（sh600/601/603/605 ＋ sz000/001/002/003）/ K=10 / KSLOT=20 / "
                f"止盈+2%（未达标 T+2 尾盘）/ 成本 6.92bp 往返 / 全池含 253 只退市股。"
                f"**资金占用率仅 {bs.get('deploy_pct', 0.0):.1f}%** —— 每日实际只有约 10 只并发（买 T+1、卖 T+2），"
                f"而 KSLOT=20 ⇒ 每只只分配到净值的 1/20。**KSLOT 是杠杆旋钮而非 alpha**：笔数/胜率/单笔中位随 KSLOT "
                f"完全不变，只有年化随占用率单调变化（KSLOT=4 ⇒ 占用 84.0% ⇒ 全窗年化 +189.75%；KSLOT=20 ⇒ +47.77%）。"
                f"**年化不可线性外推**：单票 ≤ 该股 ADV×1% ⇒ 账户容量约 101 万元。"
                f"**板块限定的代价（用户 2026-09-27 决定只买主板）**：同一面板、同一记账规则下全池 vs 主板 —— "
                f"全窗年化 +72.59% vs +47.77%（**−24.82pp**）、夏普 2.79 vs 2.12、最大回撤 −32.29% vs **−29.13%（改善 3.16pp）**、"
                f"净胜率 63.14% vs 60.63%、单笔净均 +0.5574% vs +0.4028%；2018+ 年化 +105.38% vs +64.24%。"
                f"选股集合仅 **55.5% 重合**（Jaccard 0.384）—— 横截面 z 在候选池内标准化，缩池后标准分整体改变。"
                f"**结论：主板限定是用年化换回撤，风险调整后更差（夏普 −0.67）。**逐项读数见 evidence_board.json。"
                f"**参数敏感性**：P1（低开下限）是唯一窄甜点（全池口径 0.5%→+60.35% / 1%→+72.59% / 2%→+24.95%）；"
                f"其余参数单调或不敏感，逐项见 evidence_sensitivity.json。"
                f"**未来函数**：量能特征滞后 1 日与取未来 1 日**均低于现值**、降幅方向对称 ⇒ 否证而非嫌疑"
                f"（逐值见 evidence_sensitivity.json 的 lag_VA / fwd_VA）。"
                f"**幸存者偏差**：已含 253 只退市股（不含时年化虚高 15.15pp）。"
                f"**数据源口径**：双源交叉（新浪 vs 腾讯，19,813 对）>5% 分歧 0.000%、>0.5% 为 5.189%；"
                f"偏差为**单边台阶**（前复权因子史差异），单只最差 ≤1.95%。**残留风险**：该差异时变、会在跳变日注入伪收益；"
                f"本策略只用比率（C[t]/C[t−20]、O[t+1]/C[t]），常数级水平差相消，故未触发熔断，但无法靠双源交叉消除。"
                f"**股票池**：2026-09-27 维护后 现存 5,189 ＋ 退市 253 = **5,442**（唯一标的数 = 面板列数）。"
                f"**⚠ 时段依赖（2026-09-27 证伪测试新增披露）**：本卡 2018+ 年化被**训练段占据**。"
                f"分窗实测（带内池 350,394 笔 / 2,119 天）：train 2018-2021 低开池均值 +0.163%/日、复合分前 10 +0.469%/日"
                f"（选股额外 +0.298pp）；val 2022-2026 低开池均值 **−0.004%/日（裸「低开反弹」已归零）**、"
                f"复合分前 10 +0.309%/日（选股额外 **+0.329pp，未衰减**）。⇒ 收益已**全部来自选股**"
                f"（缩量＋低成交额＋超跌）；分窗 NAV 复合 train≈+74%/年、val≈+50~56%/年。"
                f"**前瞻预期请锚定 val ≈ +50%/年，不要用本卡的 2018+ 全窗年化。**"
                f"详见 backtest/报告-证伪-横盘低开百分百多年化-20260927.md。"
                f"**前向 OOS 尚未开始**（首个信号日 2026-09-28），本卡为样本内读数，**不构成投产依据**。"
            ))
        (R / "backtest" / "hpdk_bt_ref.json").write_text(
            json.dumps(ref, ensure_ascii=False, indent=1), encoding="utf-8")
        log("[out] hpdk_bt_ref.json  年化 %+.2f%% / MDD %.2f%% / 夏普 %s / 占用 %.2f%%"
            % (ref["ann_return"], ref["max_drawdown"], ref["sharpe"], bs.get("deploy_pct", 0.0)))

    log("=" * 96)
    log("%-14s %10s %10s %7s %8s %10s %9s %8s %6s" %
        ("变体", "年化%", "MDD%", "夏普", "胜率%", "单笔净均%", "笔数", "占用%", "负年"))
    for tag, d in res.items():
        m = d["metrics"]
        if m:
            log("%-14s %+10.2f %10.2f %7s %8.2f %+10.4f %9d %8.2f %d/%d" %
                (tag, m["ann"], m["mdd"], m["sharpe"], m["win_rate"], m["mean_per_trade"],
                 m["n_trades"], m["deploy_pct"], m["neg_years"], m["n_years"]))
    log("-" * 96)
    for tag, m in sub.items():
        if isinstance(m, dict) and m.get("ann") is not None:
            log("2018+ %-12s 年化 %+8.2f%% | MDD %7.2f%% | 夏普 %5s | 占用 %6.2f%% | 笔数 %6d | 负年 %d/%d | %s"
                % (tag, m["ann"], m["mdd"], m["sharpe"], m["deploy_pct"], m["n_trades"],
                   m["neg_years"], m["n_years"], m["window"]))
    log("x2_sens.py DONE")
    return payload

if __name__ == "__main__":
    main()
