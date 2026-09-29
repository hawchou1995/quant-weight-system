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
  · **资金时序（2026-09-27 修正，E-15）**：同一交易日内「先入场（09:25，只能用开盘前已有现金）
    → 后出场（15:00 收盘结算）」；修正前为「先出场→再入场」，等于同一笔资本在同一天被使用两次，
    对高资金占用档（低 KSLOT）显著高估收益。缺陷顺序保留为 order="exit_first" 仅供审计复现。
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
              TP=0.02, COST_SIDE=0.000346, SHADOW_START="2016-01-01", WORST_CASE_WIPEOUT=True,
              # 【校准 2026-09-29】生产默认（E-22 A+C）：现名过滤只剔在售票 + 代理加钉板计数
              STP_CNT=3, STNOW_LIVE_ONLY=True, STNOW_OFF=False,
              LD_N=0, STOP=0.0)
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


def sim_portfolio(recs, cal, syms, F, K, KSLOT, cost_side, start=None, order="entry_first"):
    """组合记账（预注册 §1.5–10）。order 指定**同一交易日内的资金时序**：
      · "entry_first"（默认，正确口径）：09:25 先入场（只能用开盘前已有现金）→ 15:00 后出场结算；
      · "exit_first"（2026-09-27 前的缺陷实现，仅供审计复现，见 E-15）：先出场再入场
        ⇒ 同一笔资本在同一天被使用两次（用当天尚未卖出的持仓资金建仓）。
    """
    T = len(cal)
    jof = {s: j for j, s in enumerate(syms)}
    C = F["C"]
    by_entry = {}
    for r in recs:                                  # recs 顺序 = (信号日升序, 复合分降序)
        by_entry.setdefault(r["entry_date"], []).append(r)
    nav = np.full(T, np.nan)
    depl = np.full(T, np.nan)
    cash, pos, n_in = 1.0, [], 0
    def do_entry(t, d):                              # 入场（09:25，只能用开盘前已有现金）
        nonlocal cash, n_in
        if not (start is None or d >= start):
            return
        for r in by_entry.get(d, [])[:K]:            # recs 顺序 = 复合分降序
            if len(pos) >= KSLOT:
                break
            if any(q["sym"] == r["sym"] for q in pos):
                continue                              # 同一标的持仓期内不重复买入
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

    def do_exit(d):                                  # 出场（15:00 收盘价结算）
        nonlocal cash
        for p in list(pos):
            if p["exit_date"] == d:
                cash += p["shares"] * p["exit_px"] * (1.0 - cost_side)
                pos.remove(p)

    for t in range(T):
        d = cal[t]
        if order == "entry_first":                   # 正确：先入场（09:25）→ 后出场（15:00）
            do_entry(t, d)
            do_exit(d)
        else:                                        # 缺陷顺序（仅供审计复现，见 E-15）
            do_exit(d)
            do_entry(t, d)
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
        # 【勘误 E-22 · 2026-09-29 用户批准 A+C】三条对照臂（判据变更的读数留档）：
        #   stp_A_off    = 关掉 A（退回只看「最大绝对日收益≤5.6%」的旧代理）
        #   stnow_all_C  = 关掉 C（现名过滤作用于全量 = v1.5 行为，会误剔 228/253 只退市股）
        #   v15_both_off = A/C 全关 + 现名全量剔 = v1.5 等价（历史对照基线）
        # 三值语义（2026-09-29 修）：STNOW_OFF=True→不用现名过滤；LIVE_ONLY=False→v1.5 全量剔
        ("v15_stnow", {"STNOW_LIVE_ONLY": False, "STP_CNT": 0}, None),   # v1.5 等价：全量剔现名 + 无 A
        ("stnow_off", {"STNOW_OFF": True, "STP_CNT": 0}, None),          # E-19 等价：不用现名过滤 + 无 A
        ("stp_A_off", {"STP_CNT": 0}, None),                            # 只关 A
        ("stnow_full_A", {"STNOW_LIVE_ONLY": False}, None),              # 全量剔现名 + A（C 关）
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
                             "单边成本 COST_SIDE（买 entry×(1+c)、卖 exit×(1−c)）；"



                             "资金时序 = 先入场（09:25，用开盘前现金）→ 后出场（15:00）"

                             "（2026-09-27 修正 T+0 资金时序，见勘误 E-15；旧实现为先出场后入场）"),
                   panel=dict(T=int(F["C"].shape[0]), N=int(F["C"].shape[1]), names_loaded=done),
                   variants=res, subwindow_2018=sub)
    (outdir / "evidence_sensitivity.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                                     encoding="utf-8")

    # ---- 看板「回测参考卡」主指标带读数（_bt_ref_card 读的字段名）----
    bs = sub.get("base") or {}
    if bs:
        yb_ = bs.get("yearly") or {}
        def seg_ann(years):
            tt, nn = 1.0, 0
            for y in years:
                if y in yb_ and yb_[y] is not None:
                    tt *= (1 + yb_[y] / 100.0); nn += 1
            return ((tt ** (1.0 / nn)) - 1) * 100 if nn else 0.0
        pv0 = res["base"]["metrics"]["ann"]
        pv1 = res["P1_0.005"]["metrics"]["ann"]
        pv2 = res["P1_0.02"]["metrics"]["ann"]
        lag = res["lag_VA"]["metrics"]["ann"]
        fwd = res["fwd_VA"]["metrics"]["ann"]
        t1821 = seg_ann(["2018", "2019", "2020", "2021"])
        t2226 = seg_ann(["2022", "2023", "2024", "2025", "2026"])
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
                f"止盈+2%（未达标 T+2 尾盘）/ 成本 6.92bp 往返 / 池 = 现存 5,189 ＋ 退市 253 = 5,442（含退市股）。"
                f"**资金时序（2026-09-27 修正，勘误 E-15）**：同一交易日内 = 先入场（09:25，只能用开盘前已有现金）"
                f"→ 后出场（15:00 收盘结算）；旧实现为「先出场→再入场」，等于用当天尚未卖出的持仓资金建仓，"
                f"**同一笔资本在同一天被使用两次**。修正后：全窗年化 +47.17%（旧序 +47.77%）、最大回撤 -26.81%"
                f"（旧序 −29.13%）、夏普 2.19。低 KSLOT 档被高估得多得多（KSLOT=4 全窗 +189.75% → +76.61%）。"
                f"**KSLOT 是集中度旋钮而非杠杆**：笔数 / 胜率 / 单笔净均 / 单笔中位随 KSLOT 完全不变（选股完全相同），"
                f"变的只是单票权重（KSLOT=4 ⇒ 1/4；KSLOT=20 ⇒ 1/20）；修正后两档资金占用已接近（42.8% vs {bs.get('deploy_pct', 0.0):.1f}%）。"
                f"集中在前 4 名把全窗年化从 +47.17% 抬到 +76.61%，代价是回撤从 -26.81% 放大到 -33.63%（夏普 2.29）。"
                f"**年化不可线性外推**：单票 ≤ 该股 ADV×1% ⇒ 账户容量约 101 万元。"
                f"**10 万本金口径**（整手 100 股 ＋ 买卖两端最低佣金 5 元/笔）：KSLOT=20 ⇒ 全窗 +40.77%/年、"
                f"KSLOT=4 ⇒ +49.09%/年（val 2022+ 段 +91.72%）；10 万不受容量约束（ADV 上限仅偶发触发）。"
                f"**板块限定的代价（用户 2026-09-27 决定只买主板）**：同一面板、同一记账规则下全池 vs 主板 —— "
                f"全窗年化 +69.37% vs +47.17%（**22.20pp**）、夏普 2.79 vs 2.19、"
                f"最大回撤 -28.88% vs **-26.81%（改善 -2.07pp）**、净胜率 63.14% vs 60.63%、"
                f"单笔净均 +0.5574% vs +0.4028%；2018+ 年化 +101.16% vs +63.86%。"
                f"选股集合仅 **55.5% 重合**（Jaccard 0.384）—— 横截面 z 在候选池内标准化，缩池后标准分整体改变。"
                f"**结论：主板限定是用年化换回撤，风险调整后更差（夏普 0.60）。**逐项读数见 evidence_t0_audit.json。"
                f"**参数敏感性**（同一次运行、同一口径，全窗）：P1（低开下限）是唯一窄甜点（0.5%→{pv1:+.2f}% / "
                f"1%→{pv0:+.2f}% / 2%→{pv2:+.2f}%）；其余参数单调或不敏感，逐项见 evidence_sensitivity.json。"
                f"**未来函数**：量能特征滞后 1 日 {lag:+.2f}%、取未来 1 日 {fwd:+.2f}%，**均低于现值 {pv0:+.2f}%**、"
                f"降幅方向对称 ⇒ 否证而非嫌疑。**幸存者偏差**：已含 253 只退市股（不含时年化虚高 15.15pp）。"
                f"**数据源口径**：双源交叉（新浪 vs 腾讯，19,813 对）>5% 分歧 0.000%、>0.5% 为 5.189%；偏差为**单边台阶**"
                f"（前复权因子史差异），单只最差 ≤1.95%。**残留风险**：该差异时变、会在跳变日注入伪收益；本策略只用比率"
                f"（C[t]/C[t−20]、O[t+1]/C[t]），常数级水平差相消，故未触发熔断，但无法靠双源交叉消除。"
                f"**⚠ 时段依赖（2026-09-27 证伪测试披露）**：本卡 2018+ 年化被**训练段占据**。分窗实测（带内池 350,394 笔 / "
                f"2,119 天，选股增量不受资金时序影响）：train 2018-2021 复合分前 10 +0.469%/日（选股额外 +0.298pp）；"
                f"val 2022-2026 低开池均值 **−0.004%/日（裸「低开反弹」已归零）**、复合分前 10 +0.309%/日（选股额外 "
                f"**+0.329pp，未衰减**）⇒ 收益已**全部来自选股**（缩量＋低成交额＋超跌）。"
                f"修正后同口径分窗组合读数（主板 KSLOT=20）：2018-2021 段 {t1821:+.2f}%/年、2022-2026 段 {t2226:+.2f}%/年。"
                f"**前瞻预期请锚定 val 段 {t2226:+.2f}%/年（旧序读数为 +50~56%）**，不要用全窗或本卡的 2018+ 年化。"
                f"详见 backtest/报告-缺陷-T+0资金时序-20260927.md。"
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
