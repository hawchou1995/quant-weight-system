# -*- coding: utf-8 -*-
"""x1_overlap.py — ① 重复度对比：横盘低开·两日（新） vs 超跌低开低吸（qlch 生产轨 B4_K3）

设计原则（本项目已有 9 次口径翻车记录，故本脚本**不重写任何一套策略逻辑**）：
  · 新策略 = 冻结脚本 backtest/hengpan_fangliang_dikai_0925/oos_run.py 的信号逻辑。
    做法：import 该模块 → 把 STATE_F/TRADES_F/REPORT_F 重定向到缓存目录 → 把模块级 P 字典的
    SHADOW_START 前移、K 放大 → 调用其 main() 重放全窗口。**脚本文件字节零修改，SHA256 不变。**
    main() 内 `for j, sc in picks` 按复合分降序 append，故同一信号日内的记录顺序 = 复合分降序：
    前 10 条 = 实际选股（pick 集），全部 = 入场条件集合（cand 集）——同一代码路径，无口径漂移。
  · qlch = 生产脚本 backtest/qlch_paper_20260921.py 的 load_all() + build_signals()。
    环境 VARIANT=B4 / MAXPOS=3 / 全池(不传 --mainboard) / 熊市门 MA20，与日链第 29 步（在产轨）同参。
    出场（生产现行 TP=9.99 / SL=-0.99 / MAXHOLD=2）：固定持有 2 个交易日，不设止盈止损。
    再通过两次**运行期**常量改写拆出中间掩码（不改文件）：
      GATE_MA=None            → bear 全 True → 得 OVERSOLD = COMMON & ret20(T−1) ≤ −7.31%
      GATE_MA=None, R20_MAX=∞ → 得 COMMON（qlch 的全部共有滤网，不含超跌门槛）

⚠ 分母陷阱（本脚本刻意处理）：新策略候选 56.5 万条 vs qlch 3,896 条（145 倍差距）。
  因此「qlch 候选有 X% 落在新策略候选里」会被**分母膨胀**污染，不能当撞车证据。
  故另设 M20–M22：只在**两带交集 gap∈[−3%,−2%]** 内做**匹配分母**的入场条件重叠比较。

判据阈值在 THR 中**先冻结**，算完指标再套，不做事后调整。

用法: python x1_overlap.py [--cache DIR] [--no-cache] [--outdir DIR]
"""
import os, json, argparse, pathlib, importlib.util, time
import numpy as np
import pandas as pd

R = pathlib.Path(__file__).resolve().parents[2]
OUT = R / "backtest/hengpan_fangliang_dikai_0925"
OOS = OUT / "oos_run.py"
QLCH = R / "backtest/qlch_paper_20260921.py"
IDX = R / "index_000300.csv"

WIN_LO, WIN_HI = "2018-02-02", "2026-09-24"
QLCH_GAP_LO, QLCH_GAP_HI = -0.05, -0.02
NEW_GAP_LO, NEW_GAP_HI = -0.03, -0.01
BAND_LO, BAND_HI = -0.03, -0.02                 # 两带交集 = 真正冲突子区间
QLCH_MAXPOS, NEW_K = 3, 10

# ==================== 判据阈值（先冻结） ====================
THR = {
    "ov_cand_to_A": (0.30, 0.10),           # |A∩B| / |A|
    "ov_cand_to_B": (0.30, 0.10),           # |A∩B| / |B|
    "jaccard_cand": (0.20, 0.06),           # |A∩B| / |A∪B|
    "obs_over_baseline": (3.0, 1.5),        # 成交级同日 Jaccard / 随机基线
    "cond_ov": (0.30, 0.10),                # M22 匹配分母条件重叠（Jaccard，带内）← 主判据
}
LEVEL = {2: "高", 1: "中", 0: "低"}


def lvl(v, key):
    hi, mid = THR[key]
    return 2 if v >= hi else (1 if v >= mid else 0)


def log(*a):
    print(*a, flush=True)


# ==================== 新策略信号（复用冻结脚本，零修改） ====================
def build_new_signals(cache, use_cache=True):
    f = cache / "new_signals.json"
    if use_cache and f.exists():
        log("[cache] 新策略信号 ← %s" % f)
        return json.loads(f.read_text(encoding="utf-8"))
    log("[build] 复用冻结 oos_run.py（重定向输出 + 运行期前移；文件字节零修改）…")
    t0 = time.time()
    spec = importlib.util.spec_from_file_location("oos_run_replay", OOS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sha_before = mod.FROZEN_SHA
    mod.STATE_F = cache / "_replay_state.json"
    mod.TRADES_F = cache / "_replay_trades.jsonl"
    mod.REPORT_F = cache / "_replay_report.json"
    mod.P["SHADOW_START"] = "2016-01-01"
    mod.P["K"] = 10 ** 9
    mod.main()
    assert sha_before == mod.FROZEN_SHA, "冻结脚本 SHA 被改动！"
    recs = [json.loads(x) for x in mod.TRADES_F.read_text(encoding="utf-8").splitlines() if x.strip()]
    log("[build] 新策略候选 %d 条（%.1fs）" % (len(recs), time.time() - t0))
    out = dict(sha256=sha_before, n=len(recs),
               rows=[dict(signal_date=x["signal_date"], entry_date=x["entry_date"], sym=x["sym"],
                          gap=x["gap_pct"] / 100.0, entry_open=x["entry_open"], ret_pct=x["ret_pct"])
                     for x in recs])
    f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


# ==================== qlch 信号（复用生产脚本） ====================
def load_qlch(cache, use_cache=True):
    npr = cache / "qlch_signals_v2.npz"
    if use_cache and npr.exists():
        log("[cache] qlch 信号 ← %s" % npr)
        z = np.load(npr, allow_pickle=True)
        return dict(cal=[str(x) for x in z["cal"]], codes=[str(x) for x in z["codes"]],
                    cand=z["cand"], oversold=z["oversold"], common=z["common"], gap=z["gap"],
                    valid=z["valid"], O=z["O"], C=z["C"], vr=z["vr"], r20=z["r20"])
    log("[build] 复用 qlch 生产脚本（VARIANT=B4 / MAXPOS=3 / 全池 / 熊市门 MA20）…")
    t0 = time.time()
    os.environ["QLCH_VARIANT"] = "B4"
    os.environ["QLCH_MAXPOS"] = "3"
    os.environ.pop("QLCH_MAINBOARD", None)
    os.environ.pop("QLCH_GATE", None)
    spec = importlib.util.spec_from_file_location("qlch_prod", QLCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (mod.VARIANT, mod.MAXPOS, mod.MAINBOARD, mod.GATE_MA) == ("B4", 3, False, 20), \
        "qlch 生产环境未生效：%r" % ((mod.VARIANT, mod.MAXPOS, mod.MAINBOARD, mod.GATE_MA),)
    P = mod.load_all()
    prod = mod.build_signals(P)                     # 生产口径：OVERSOLD & bear
    _g, _r = mod.GATE_MA, mod.R20_MAX
    mod.GATE_MA = None
    nog = mod.build_signals(P)                      # bear 全 True → OVERSOLD
    mod.R20_MAX = 1e9
    comm = mod.build_signals(P)                     # 无门 + 门槛取消 → COMMON
    mod.GATE_MA, mod.R20_MAX = _g, _r
    cand, oversold, common = prod["cand"], nog["cand"], comm["cand"]
    assert not (cand & ~oversold).any(), "cand 必须 ⊆ OVERSOLD"
    assert not (oversold & ~common).any(), "OVERSOLD 必须 ⊆ COMMON"
    cal = [str(d) for d in prod["cal"]]
    codes = [str(c) for c in prod["codes"]]
    gap = np.asarray(prod["gap"], dtype=np.float64)
    vr = np.asarray(prod["vr"], dtype=np.float64)
    r20 = np.asarray(prod["r20"], dtype=np.float64)
    valid = np.asarray(prod["valid"], dtype=bool)
    O = np.asarray(prod["open"], dtype=np.float64)
    C = np.asarray(prod["close"], dtype=np.float64)
    log("[build] qlch 面板 T=%d N=%d（%.1fs）" % (len(cal), len(codes), time.time() - t0))
    np.savez_compressed(npr, cal=np.array(cal, dtype=object), codes=np.array(codes, dtype=object),
                        cand=cand, oversold=oversold, common=common,
                        gap=gap.astype(np.float32), valid=valid,
                        O=O.astype(np.float32), C=C.astype(np.float32),
                        vr=vr.astype(np.float32), r20=r20.astype(np.float32))
    return dict(cal=cal, codes=codes, cand=cand, oversold=oversold, common=common, gap=gap,
                valid=valid, O=O, C=C, vr=vr, r20=r20)


def hs300_bear(cal, ma=20):
    """沪深300(T) < MA20(T)——与 qlch 生产 build_signals 同定义。"""
    idx = pd.read_csv(IDX, parse_dates=["date"])
    ic = idx.close.astype(np.float64).values
    ima = pd.Series(ic).rolling(ma).mean().values
    i2t = {d.strftime("%Y-%m-%d"): k for k, d in enumerate(idx.date)}
    out = np.zeros(len(cal), dtype=bool)
    for t, d in enumerate(cal):
        k = i2t.get(d)
        if k is not None and np.isfinite(ima[k]):
            out[t] = bool(ic[k] < ima[k])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.environ.get("PI_SCRATCH_DIR") or ".")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--outdir", default=None)
    a = ap.parse_args()
    cache = pathlib.Path(a.cache); cache.mkdir(parents=True, exist_ok=True)
    uc = not a.no_cache
    outdir = pathlib.Path(a.outdir) if a.outdir else OUT
    outdir.mkdir(parents=True, exist_ok=True)

    NEW = build_new_signals(cache, uc)
    Q = load_qlch(cache, uc)
    log("新策略冻结脚本 SHA256 = %s  候选 %d 条" % (NEW["sha256"], NEW["n"]))

    qcal, qcodes = Q["cal"], Q["codes"]
    qlut = {d: i for i, d in enumerate(qcal)}
    qc2j = {c: j for j, c in enumerate(qcodes)}
    qgap, qcand, qvalid, qO, qC = Q["gap"], Q["cand"], Q["valid"], Q["O"], Q["C"]
    inwin = {d for d in qcal if WIN_LO <= d <= WIN_HI}

    # ---------- 新策略：买日聚合（日内顺序 = 复合分降序） ----------
    new_rows = [r for r in NEW["rows"] if WIN_LO <= r["entry_date"] <= WIN_HI]
    new_by_day, new_gap = {}, {}
    for r in new_rows:
        new_by_day.setdefault(r["entry_date"], []).append(r["sym"])
        new_gap[(r["entry_date"], r["sym"])] = r["gap"]
    B_cand = set(new_gap)
    B_pick_by_day = {d: set(ss[:NEW_K]) for d, ss in new_by_day.items()}
    B_pick = {(d, s) for d, ss in B_pick_by_day.items() for s in ss}
    log("新策略：买日 %d · 候选 %d · 选股(K=%d) %d" % (len(new_by_day), len(B_cand), NEW_K, len(B_pick)))

    # ---------- qlch：买日聚合（cand[t-1] ∩ gap[t]∈带 ∩ valid[t]） ----------
    A_by_day, A_gap = {}, {}
    for t in range(1, len(qcal)):
        d = qcal[t]
        if d not in inwin:
            continue
        g = qgap[t]
        rows = np.nonzero(qcand[t - 1] & np.isfinite(g) & (g >= QLCH_GAP_LO) & (g <= QLCH_GAP_HI)
                          & qvalid[t])[0]
        for j in rows:
            if np.isfinite(qO[t, j]) and qO[t, j] > 0:
                A_by_day.setdefault(d, []).append(qcodes[j])
                A_gap[(d, qcodes[j])] = float(g[j])
    A_cand = set(A_gap)

    # ---------- qlch K=3 槽位成交模拟（复刻生产循环；从面板起点起跑，只在窗内计入） ----------
    A_pick_by_day, pos = {}, []
    for t in range(1, len(qcal)):
        d = qcal[t]
        pos = [p for p in pos if (t - p) < 1]                  # MAXHOLD−1 = 1 → 次日收盘出场
        if d not in inwin:
            continue
        room = QLCH_MAXPOS - len(pos)
        if room <= 0:
            continue
        cd = list(A_by_day.get(d, []))
        if not cd:
            continue
        if len(cd) > room:
            rng = np.random.default_rng(20260921)              # 与生产 SELECT=random 同种子
            cd = [cd[i] for i in sorted(rng.choice(len(cd), size=room, replace=False).tolist())]
        for s in cd:
            pos.append(t)
        A_pick_by_day[d] = set(cd)
    A_pick = {(d, s) for d, ss in A_pick_by_day.items() for s in ss}
    log("qlch：买日 %d · 候选 %d · 槽位成交(K=%d) %d"
        % (len(A_by_day), len(A_cand), QLCH_MAXPOS, len(A_pick)))

    # ---------- 核心重合（全集口径；受分母膨胀影响，需与 M20–M22 并读） ----------
    inter_cand = A_cand & B_cand
    inter_pick = A_pick & B_pick
    days_A, days_B = set(A_by_day), set(new_by_day)
    common_days = days_A & days_B
    ov_A = len(inter_cand) / max(1, len(A_cand))
    ov_B = len(inter_cand) / max(1, len(B_cand))
    jac = len(inter_cand) / max(1, len(A_cand | B_cand))

    # ---------- 匹配分母：两带交集 gap∈[−3%,−2%] 内的**入场条件**重叠 ----------
    A_cond = {}
    for t in range(1, len(qcal)):
        d = qcal[t]
        if d not in inwin:
            continue
        g = qgap[t]
        rows = np.nonzero(Q["common"][t - 1] & np.isfinite(g) & (g >= BAND_LO) & (g <= BAND_HI)
                          & qvalid[t])[0]
        for j in rows:
            if np.isfinite(qO[t, j]) and qO[t, j] > 0:
                A_cond[(d, qcodes[j])] = float(g[j])
    B_cond = {k: v for k, v in new_gap.items() if BAND_LO <= v <= BAND_HI}
    inter_cond = set(A_cond) & set(B_cond)
    cond_to_A = len(inter_cond) / max(1, len(A_cond))
    cond_to_B = len(inter_cond) / max(1, len(B_cond))
    cond_jac = len(inter_cond) / max(1, len(A_cond | B_cond))

    # ---------- 拆解：为何撞/不撞 ----------
    bear = hs300_bear(qcal)
    assert np.array_equal(Q["oversold"] & bear[:, None], qcand), "沪深300 熊市门重算与生产不一致"
    bear_map = {d: bool(bear[i]) for d, i in qlut.items()}

    def q_ov_prev(d, sym):
        i = qlut.get(d); j = qc2j.get(sym)
        return bool(i is not None and i >= 1 and j is not None and Q["oversold"][i - 1, j])

    n_B = max(1, len(B_cand))
    b_oversold = sum(1 for (d, s) in B_cand if q_ov_prev(d, s))
    b_bear = sum(1 for (d, _s) in B_cand if bear_map.get(d, False))
    b_deep = sum(1 for (d, s) in B_cand if BAND_LO <= new_gap[(d, s)] <= BAND_HI)
    a_deep = sum(1 for (d, s) in A_cand if BAND_LO <= A_gap[(d, s)] <= BAND_HI)
    a_days_bear = sum(1 for d in days_A if bear_map.get(d, False))
    b_days_bear = sum(1 for d in days_B if bear_map.get(d, False))

    # ---------- 成交级同日 Jaccard + 随机基线（同日同分母） ----------
    both_pick_days = sorted(d for d in common_days if A_pick_by_day.get(d) and B_pick_by_day.get(d))
    obs = [len(A_pick_by_day[d] & B_pick_by_day[d]) / max(1, len(A_pick_by_day[d] | B_pick_by_day[d]))
           for d in both_pick_days]
    obs_jac_day = float(np.mean(obs)) if obs else 0.0
    rng = np.random.default_rng(20260921)
    REPS = 400
    base_acc = []
    for d in both_pick_days:
        ac, bc = list(A_by_day[d]), list(B_pick_by_day[d])
        ka, kb = min(QLCH_MAXPOS, len(ac)), min(NEW_K, len(bc))
        vals = []
        for _ in range(REPS):
            sa = {ac[i] for i in rng.choice(len(ac), size=ka, replace=False).tolist()}
            sb = {bc[i] for i in rng.choice(len(bc), size=kb, replace=False).tolist()}
            vals.append(len(sa & sb) / max(1, len(sa | sb)))
        base_acc.append(float(np.mean(vals)))
    base_jac_day = float(np.mean(base_acc)) if base_acc else 0.0
    ratio = (obs_jac_day / base_jac_day) if base_jac_day > 1e-12 else float("inf")

    # ---------- 队列毛收益相关性（同池同价：两套信号都用 qlch 面板定价，只差选股） ----------
    def cohort_returns(by_day):
        out = {}
        for d, syms in by_day.items():
            i = qlut.get(d)
            if i is None or i + 1 >= len(qcal):
                continue
            vals = []
            for s in syms:
                j = qc2j.get(s)
                if j is None:
                    continue
                if np.isfinite(qO[i, j]) and qO[i, j] > 0 and np.isfinite(qC[i + 1, j]) and qC[i + 1, j] > 0:
                    vals.append(qC[i + 1, j] / qO[i, j] - 1.0)
            if vals:
                out[d] = float(np.mean(vals))
        return out

    q_ret = cohort_returns(A_by_day)
    n_ret = cohort_returns({d: sorted(v) for d, v in B_pick_by_day.items()})
    both = sorted(set(q_ret) & set(n_ret))
    pear = spear = None
    if len(both) >= 30:
        xa = np.array([q_ret[d] for d in both]); xb = np.array([n_ret[d] for d in both])
        if np.std(xa) > 0 and np.std(xb) > 0:
            pear = float(np.corrcoef(xa, xb)[0, 1])
            sp = pd.Series(xa).corr(pd.Series(xb), method="spearman")
            spear = float(sp) if np.isfinite(sp) else None

    # ---------- 因子画像：两套成交标的在信号日的因子中位数（同面板同索引） ----------
    def prof(picks, arr):
        vals = []
        for (d, s) in picks:
            i = qlut.get(d); j = qc2j.get(s)
            if i is None or j is None or i < 1:
                continue
            v = arr[i - 1, j]
            if np.isfinite(v):
                vals.append(float(v))
        if not vals:
            return dict(n=0, med=None)
        return dict(n=len(vals), med=round(float(np.median(vals)), 5))

    profile = {
        "ret20_med": {"new_k10": prof(B_pick, Q["r20"]), "qlch_k3": prof(A_pick, Q["r20"])},
        "volbr_med": {"new_k10": prof(B_pick, Q["vr"]), "qlch_k3": prof(A_pick, Q["vr"])},
    }

    M = {
        "window": [WIN_LO, WIN_HI],
        "new_script_sha256": NEW["sha256"],
        "qlch_prod_spec": {"variant": "B4", "maxpos": 3, "mainboard": False, "gate_ma": 20,
                           "gap_band": [QLCH_GAP_LO, QLCH_GAP_HI],
                           "exit": "TP=9.99/SL=-0.99/MAXHOLD=2 → 固定持 2 交易日"},
        "new_spec": {"gap_band": [NEW_GAP_LO, NEW_GAP_HI], "K": NEW_K,
                     "band_intersection": [BAND_LO, BAND_HI]},
        "calib": {"days_in_window_with_panel": len(inwin),
                  "days_qlch_no_signal": len(inwin - days_A)},
        "thresholds": {k: list(v) for k, v in THR.items()},
        "sets": {"A_cand_qlch": len(A_cand), "B_cand_new": len(B_cand),
                 "A_pick_qlch_k3": len(A_pick), "B_pick_new_k10": len(B_pick),
                 "A_days": len(days_A), "B_days": len(days_B), "common_days": len(common_days),
                 "inter_cand": len(inter_cand), "inter_pick": len(inter_pick),
                 "A_cond_band": len(A_cond), "B_cond_band": len(B_cond),
                 "inter_cond_band": len(inter_cond)},
        "M1_ov_cand_to_A": round(ov_A, 6),
        "M2_ov_cand_to_B": round(ov_B, 6),
        "M3_jaccard_cand": round(jac, 6),
        "M4_day_cov_A_to_B": round(len(common_days) / max(1, len(days_A)), 6),
        "M5_day_cov_B_to_A": round(len(common_days) / max(1, len(days_B)), 6),
        "M6_ov_pick_to_A": round(len(inter_pick) / max(1, len(A_pick)), 6),
        "M7_ov_pick_to_B": round(len(inter_pick) / max(1, len(B_pick)), 6),
        "M8_pick_jaccard_day_obs": round(obs_jac_day, 6),
        "M9_pick_jaccard_day_random": round(base_jac_day, 6),
        "M10_obs_over_baseline": round(ratio, 4) if np.isfinite(ratio) else None,
        "M11_new_in_qlch_oversold": round(b_oversold / n_B, 6),
        "M12_new_on_bear_days": round(b_bear / n_B, 6),
        "M13_new_deepgap_2to3pct": round(b_deep / n_B, 6),
        "M14_qlch_deepgap_2to3pct": round(a_deep / max(1, len(A_cand)), 6),
        "M15_qlch_days_in_bear": round(a_days_bear / max(1, len(days_A)), 6),
        "M16_new_days_in_bear": round(b_days_bear / max(1, len(days_B)), 6),
        "M17_cohort_ret_pearson": None if pear is None else round(pear, 4),
        "M18_cohort_ret_spearman": None if spear is None else round(spear, 4),
        "M19_cond_ov_to_A": round(cond_to_A, 6),
        "M20_cond_ov_to_B": round(cond_to_B, 6),
        "M21_cond_jaccard_band": round(cond_jac, 6),
        "M22_cond_ov_max": round(max(cond_to_A, cond_to_B), 6),
        "n_days_for_corr": len(both),
        "n_days_for_pick_jaccard": len(both_pick_days),
        "factor_profile": profile,
    }
    M["levels"] = {k: LEVEL[lvl(M[k], key)] for k, key in
                   (("M1_ov_cand_to_A", "ov_cand_to_A"), ("M2_ov_cand_to_B", "ov_cand_to_B"),
                    ("M3_jaccard_cand", "jaccard_cand"), ("M22_cond_ov_max", "cond_ov"))}
    if M["M10_obs_over_baseline"] is not None:
        M["levels"]["M10_obs_over_baseline"] = LEVEL[lvl(M["M10_obs_over_baseline"], "obs_over_baseline")]
    overall = max((LEVEL_REV[v] for v in M["levels"].values()), default=0)
    M["verdict_level"] = LEVEL[overall]
    M["verdict_basis"] = ("主判据 = M22 匹配分母条件重叠 max(→A, →B) = %.4f（%s）；"
                          "成交级 M10 实测/随机 = %s；全项最高级 → 综合 = %s"
                          % (M["M22_cond_ov_max"], M["levels"]["M22_cond_ov_max"],
                             M["M10_obs_over_baseline"], M["verdict_level"]))
    M["examples_inter_pick"] = sorted(list(inter_pick))[:40]
    M["examples_inter_cond"] = sorted(list(inter_cond))[:30]

    (outdir / "evidence_overlap.json").write_text(json.dumps(M, ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
    log(json.dumps({k: v for k, v in M.items() if not k.startswith("examples")},
                   ensure_ascii=False, indent=1))
    log("x1_overlap.py DONE")
    return M


LEVEL_REV = {"高": 2, "中": 1, "低": 0}

if __name__ == "__main__":
    main()
