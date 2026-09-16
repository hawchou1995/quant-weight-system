# -*- coding: utf-8 -*-
"""tongzhou_factors_0916.py —— 同舟 MCP 可转因子：构造 + 冻结引擎回测

数据来源（真实调用落盘）：backtest/tz_data/ff_page{1,2}.json
  ← fin_data__get_industry_fund_flow_series（申万一级 31 行业 × 日频主力资金流）
  覆盖硬边界：2024-01-02 起（服务端数据源起点，与 limit/start_date 无关，已实测）

口径（强制统一，与生产冻结引擎一致）：
  universe = 主板 sh60*/sz00*（oss_panel_0913 即主板）
  ELIG3    = asts_0916/ELIG3.npy（冻结：成交额≥300万 & 非ST & 上市≥150日 & 价>2元）
  引擎     = 逐字抽取 oss_0913/oss_super_combo_0913.py 的 run_engine 段 exec
  相位     = 5 相位 0/4/8/12/16；成本 20bp(生产)/50bp(压力)
  轨B      = asts_0916/comp_base.npy（冻结 composite），其 off0 日收益 = base_equity_off0.csv
  自检     = 轨B off0 年化必须 == 22.87%，否则 abort

PIT 申报：
  · 资金流为「当日盘后」汇总口径 → T 日决策用 ≤T 值；供应商若为 T+1 汇总则 T 值实际不可得，
    已加 `_lag1` 变体（全序列滞后 1 交易日）作边界检验。
  · 行业映射用本地 stock_industry.json（申万一级，2026-08-20 快照，非 PIT；L1 级别漂移极小）。

用途：python tongzhou_factors_0916.py [build|ic|arms|placebo|all]
"""
import numpy as np, pandas as pd, json, os, sys, time, math, gc, argparse

BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
BT = os.path.join(BASE, "backtest")
TZD = os.path.join(BT, "tz_data")
OUT = os.path.join(BT, "tongzhou_factors_0916.json")
SUPER = os.path.join(BT, "oss_0913", "oss_super_combo_0913.py")
PH5 = [0, 4, 8, 12, 16]
T0 = time.time()
sys.path.insert(0, BT)


def log(*a): print(f"[{time.time()-T0:7.1f}s]", *a, flush=True)


def jdump(o, p):
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(o, fh, ensure_ascii=False, indent=1, default=float)


# ════════════════════ 0. 引擎装载（冻结源码段）════════════════════
def load_engine():
    import _asts_panel_mmap_0916 as MP
    P = MP.load_mmap("oss_panel_0913.pkl")
    codes = np.asarray(P["codes"])
    bad = [c for c in codes if not (str(c).startswith("60") or str(c).startswith("00"))]
    assert not bad, f"非主板代码 {bad[:5]}"
    ND, NC = np.asarray(P["close"]).shape
    E = dict(np=np, pd=pd, math=math, cal=np.asarray(P["cal"]),
             WARMUP=150, F=20, ND=ND, NC=NC,
             CASH0=170_000.0, COMM=0.00025, TAX=0.0005, SLIP=0.0020, SLIP_STRESS=0.0050, MIN_COMM=5.0,
             O=np.asarray(P["open"], dtype=np.float64),
             close_ff=pd.DataFrame(np.asarray(P["close"])).ffill().to_numpy(),
             ELIG3=np.load(os.path.join(BT, "asts_0916", "ELIG3.npy")),
             volpct=np.load(os.path.join(BT, "asts_0916", "volpct.npy")),
             sc1000=np.load(os.path.join(BT, "asts_0916", "sc1000.npy")),
             ma20sc=np.load(os.path.join(BT, "asts_0916", "ma20sc.npy")))
    src = open(SUPER, encoding="utf-8").read()
    exec(src[src.index("def run_engine("):src.index("comp = composite()")], E)
    return P, E


# ════════════════════ 1. 资金流面板 → 行业日频矩阵 ════════════════════
def load_flow_daily():
    rows = {}
    for pg in (1, 2):
        f = os.path.join(TZD, f"ff_page{pg}.json")
        if not os.path.exists(f):
            continue
        d = json.load(open(f, encoding="utf-8"))
        for code, s in d["series"].items():
            for p in s["points"]:
                rows.setdefault(p["trade_date"], {})[s["name"]] = p
    df = pd.DataFrame({dt: {ind: v["net_inflow_to_turnover_ratio"] for ind, v in m.items()}
                       for dt, m in rows.items()}).T.sort_index()
    amt = pd.DataFrame({dt: {ind: v["main_net_inflow_amount"] for ind, v in m.items()}
                        for dt, m in rows.items()}).T.sort_index()
    return df, amt


def build_factors():
    import _asts_panel_mmap_0916 as MP
    P = MP.load_mmap("oss_panel_0913.pkl")
    cal = list(map(str, np.asarray(P["cal"])))
    codes = [str(c) for c in np.asarray(P["codes"])]
    flow, amt = load_flow_daily()
    log(f"flow panel: {flow.shape[0]} 交易日 × {flow.shape[1]} 行业 "
        f"| {flow.index[0]}..{flow.index[-1]}")
    flow = flow.reindex(cal)
    amt = amt.reindex(cal)
    ind = json.load(open(os.path.join(BASE, "stock_industry.json"), encoding="utf-8"))["map"]
    smap = pd.Series({c: ind.get(c, "") for c in codes})
    hit = float((smap.isin(flow.columns)).mean())
    log(f"行业映射命中: {hit*100:.1f}% 标的（{int(smap.isin(flow.columns).sum())}/{len(codes)}）")

    def to_stock(indmat):
        """行业日频矩阵 → 个股矩阵（同行业取同值）"""
        cols = [smap.get(c, "") for c in codes]
        idx = {n: i for i, n in enumerate(indmat.columns)}
        take = np.array([idx.get(n, -1) for n in cols])
        out = np.full((len(cal), len(codes)), np.nan, dtype=np.float32)
        ok = take >= 0
        out[:, ok] = indmat.to_numpy(dtype=np.float32)[:, take[ok]]
        return out

    F = {}
    F["flow20"] = to_stock(flow.rolling(20, min_periods=15).sum())          # 20日累计净流入/成交额
    F["flow5"] = to_stock(flow.rolling(5, min_periods=4).sum())             # 5日
    F["flow_acc"] = to_stock(flow.rolling(5, min_periods=4).sum()
                             - flow.rolling(20, min_periods=15).sum() / 4.0)  # 加速度(近5日 vs 20日均速)
    F["amt20"] = to_stock(np.log1p(amt.rolling(20, min_periods=15).sum().abs()))  # 额口径稳健性对照
    for k in list(F):
        F[k + "_lag1"] = np.vstack([np.full((1, F[k].shape[1]), np.nan), F[k][:-1]])  # T+1 汇总边界检验
    np.savez_compressed(os.path.join(TZD, "tz_factors_0916.npz"),
                        **{k: v for k, v in F.items()}, cal=np.array(cal), codes=np.array(codes))
    cov = {}
    for k, v in F.items():
        fin = np.isfinite(v)
        dc = fin.any(axis=1)
        xs = np.flatnonzero(dc)
        cov[k] = {"cells_finite": int(fin.sum()), "frac": round(float(fin.mean()), 4),
                  "first_date": cal[xs[0]] if len(xs) else None,
                  "last_date": cal[xs[-1]] if len(xs) else None,
                  "cols_covered": int(fin.any(axis=0).sum())}
        log(f"  {k:14s} 首个可用 {cov[k]['first_date']} | 覆盖 {cov[k]['frac']*100:.1f}% 单元格")
    jdump(cov, os.path.join(TZD, "tz_factor_coverage_0916.json"))
    log("factors saved -> tz_data/tz_factors_0916.npz")
    return F, cov


# ════════════════════ 2. 评估 ════════════════════
def shr(r):
    r = pd.Series(r).dropna()
    return float(r.mean() / (r.std() + 1e-12) * np.sqrt(244)) if len(r) > 5 else np.nan


def rank_ic(mat, ELIG, fwdH):
    a = np.where(ELIG & np.isfinite(mat) & np.isfinite(fwdH), mat, np.nan)
    r = pd.DataFrame(a).rank(axis=1).to_numpy()
    zy = pd.DataFrame(np.where(ELIG & np.isfinite(fwdH), fwdH, np.nan)).rank(axis=1).to_numpy()
    zf = r - np.nanmean(r, axis=1, keepdims=True); zz = zy - np.nanmean(zy, axis=1, keepdims=True)
    zf = zf / (np.nanstd(zf, axis=1, keepdims=True) + 1e-12)
    zz = zz / (np.nanstd(zz, axis=1, keepdims=True) + 1e-12)
    both = np.isfinite(zf) & np.isfinite(zz); n = both.sum(axis=1)
    ic = np.where(n > 50, np.nansum(np.where(both, zf * zz, 0), axis=1) / np.maximum(n, 1), np.nan)
    v = ic[np.isfinite(ic)]
    return float(v.mean()), float(v.mean() / (v.std() + 1e-12)), ic


def zcombo(mats, ELIG, weights=None):
    """加权 z 组合；某因子缺失时按可得权重归一（= 该行退化为可得因子本身）"""
    ND, NC = next(iter(mats.values())).shape
    if weights is None:
        weights = {k: 1.0 for k in mats}
    num = np.zeros((ND, NC), dtype=np.float64); den = np.zeros((ND, NC), dtype=np.float64)
    for k, m in mats.items():
        a = np.where(ELIG & np.isfinite(m), m, np.nan)
        mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
        z = np.clip((a - mu) / (sd + 1e-12), -3, 3)
        ok = np.isfinite(z)
        num += np.where(ok, z * weights[k], 0.0); den += np.where(ok, weights[k], 0.0)
    return np.where(den > 0.4, num / np.maximum(den, 1e-9), np.nan)


def seg_metrics(eq, start_date=None):
    """从净值序列（含空仓段）在指定起始日之后重算指标"""
    e = eq.dropna()
    if start_date is not None:
        e = e[e.index >= pd.Timestamp(start_date)]
    if len(e) < 30:
        return {}
    r = e.pct_change().dropna()
    yrs = len(e) / 244.0
    return dict(ann=float((e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1),
                sharpe=shr(r), mdd=float((e / e.cummax() - 1).min()),
                n_days=int(len(e)), start=str(e.index[0].date()), end=str(e.index[-1].date()))


def eval_arm(comp, E, track_ret, name, avail_start=None):
    run_engine = E["run_engine"]
    cal = E["cal"]
    out = {"name": name, "avail_start": avail_start}
    eq0 = None
    for tag, slip in [("s20", 0.0020), ("s50", 0.0050)]:
        shs, anns, eqs, mdds = [], [], [], []
        for off in PH5:
            m = run_engine(comp, 20, offset=off, slip=slip)
            shs.append(float(m["sharpe"])); anns.append(float(m["ann"])); mdds.append(float(m["mdd"])); eqs.append(m["equity"])
        out[tag] = dict(sharpe_ph5=shs, ann_ph5=anns,
                        phmed_sharpe=float(np.median(shs)), phmed_ann=float(np.median(anns)),
                        phmin=float(np.min(shs)), phmed_mdd=float(np.median(mdds)))
        if avail_start:  # 因子可用窗内重算
            sm = [seg_metrics(e, avail_start) for e in eqs]
            out[tag]["availwin"] = dict(
                phmed_sharpe=float(np.median([x["sharpe"] for x in sm])),
                phmed_ann=float(np.median([x["ann"] for x in sm])),
                phmed_mdd=float(np.median([x["mdd"] for x in sm])),
                sharpe_ph5=[x["sharpe"] for x in sm], window=sm[0].get("start"))
        out[tag]["off0_ann"] = anns[0]; out[tag]["off0_sharpe"] = shs[0]
        if tag == "s20":
            eq0 = eqs[0]
    m0 = run_engine(comp, 20, offset=0)
    out["off0_full"] = dict(ann=float(m0["ann"]), sharpe=float(m0["sharpe"]), mdd=float(m0["mdd"]),
                            win=float(m0["win"]), n=int(m0["n_trades"]),
                            by_year={str(k): float(v) for k, v in m0["by_year"].items()})
    r = eq0.pct_change().dropna()
    j = r.index.intersection(track_ret.index)
    out["corr_B_off0"] = float(np.corrcoef(r.reindex(j), track_ret.reindex(j))[0, 1]) if len(j) > 60 else np.nan
    if avail_start:
        r2 = r[r.index >= pd.Timestamp(avail_start)]
        j2 = r2.index.intersection(track_ret.index)
        out["corr_B_availwin"] = float(np.corrcoef(r2.reindex(j2), track_ret.reindex(j2))[0, 1]) if len(j2) > 60 else np.nan
    half = len(r) // 2
    out["halves"] = dict(h1_sharpe=shr(r.iloc[:half]), h2_sharpe=shr(r.iloc[half:]),
                         h1_end=str(r.index[half - 1].date()), h2_start=str(r.index[half].date()))
    out["same_sign"] = bool(out["halves"]["h1_sharpe"] > 0 and out["halves"]["h2_sharpe"] > 0)
    # 闸门（沿用 asts_0916 冻结口径：低相关新臂）
    out["gate"] = dict(corr_ok=bool(out["corr_B_off0"] <= 0.30),
                       phmed_ok=bool(out["s20"]["phmed_sharpe"] >= 0.5),
                       s50_ok=bool(out["s50"]["phmed_sharpe"] >= 0.3),
                       halves_ok=bool(out["same_sign"]))
    out["gate"]["PASS"] = bool(all(out["gate"][k] for k in ("corr_ok", "phmed_ok", "s50_ok", "halves_ok")))
    out["gate"]["note"] = "传统四闸（低相关新臂口径, asts_0916）; 是否投产另需 vs 轨B 增量判读"
    return out


# ════════════════════ 3. 主流程 ════════════════════
def load_all():
    P, E = load_engine()
    z = np.load(os.path.join(TZD, "tz_factors_0916.npz"), allow_pickle=True)
    F = {k: z[k] for k in z.files if k not in ("cal", "codes")}
    base = np.load(os.path.join(BT, "asts_0916", "comp_base.npy"))
    be = pd.read_csv(os.path.join(BT, "asts_0916", "base_equity_off0.csv"))
    be.columns = [c.strip() for c in be.columns]
    dcol = "date" if "date" in be.columns else be.columns[0]
    ecol = "equity" if "equity" in be.columns else be.columns[1]
    be[dcol] = pd.to_datetime(be[dcol])
    track = be.set_index(dcol)[ecol].pct_change().dropna()
    # 自检
    m = E["run_engine"](base, 20, 0)
    assert round(m["ann"] * 100, 2) == 22.87, f"BASELINE REPRO FAILED {m['ann']*100}"
    log("BASELINE REPRO OK off0 ann=%.2f%% S=%.2f" % (m["ann"] * 100, m["sharpe"]))
    return P, E, F, base, track


def stage_ic(E, F, P):
    import _asts_panel_mmap_0916 as MP
    ELIG = E["ELIG3"]
    O = E["O"]; ND, NC = O.shape
    fwd = np.full((ND, NC), np.nan)
    fwd[:ND - 1 - 20] = O[21:] / O[1:ND - 20] - 1
    rows = {}
    for k, v in F.items():
        ic, icir, icv = rank_ic(v.astype(np.float64), ELIG, fwd)
        v2 = icv[np.isfinite(icv)]
        # 因子可用窗内 IC
        cal = E["cal"]; av = np.flatnonzero(np.isfinite(v).any(axis=1))
        if len(av):
            sub = icv[av[0]:]
            sub = sub[np.isfinite(sub)]
        else:
            sub = np.array([])
        rows[k] = dict(ic=ic, icir=icir, ic_n=int(np.isfinite(icv).sum()),
                       ic_first_half=float(np.mean(v2[:len(v2)//2])) if len(v2) else None,
                       ic_second_half=float(np.mean(v2[len(v2)//2:])) if len(v2) else None,
                       ic_availwin=float(np.mean(sub)) if len(sub) else None,
                       icir_availwin=float(np.mean(sub)/(np.std(sub)+1e-12)) if len(sub) else None)
        log(f"  IC {k:16s} full={ic:+.4f} icir={icir:+.3f} | availwin ic={rows[k]['ic_availwin']:+.4f} "
            f"icir={rows[k]['icir_availwin']:+.3f}")
    return rows


def stage_arms(E, F, base, track, avail_start=None):
    ELIG = E["ELIG3"]
    res = {}
    # 轨B 基线（同窗对照）
    res["trackB_base"] = eval_arm(base, E, track, "轨B(冻结composite)", avail_start)
    # 单因子臂（IC 定向符号）
    signs = {}
    for k in ["flow20", "flow5", "flow_acc", "amt20", "flow20_lag1", "flow5_lag1"]:
        v = F[k].astype(np.float64)
        ic, icir, _ = rank_ic(v, ELIG, F["flow20_lag1"].astype(np.float64) * 0 + _fwd(E))
        signs[k] = 1.0 if ic >= 0 else -1.0
        log(f"  sign[{k}] = {signs[k]:+.0f} (IC {ic:+.4f})")
    for k in ["flow20", "flow5", "flow_acc", "flow20_lag1"]:
        comp = zcombo({k: F[k].astype(np.float64) * signs[k]}, ELIG)
        res[f"single_{k}"] = eval_arm(comp, E, track, f"单因子 {k}", avail_start)
        log(f"  ARMED single {k}: phmed S={res[f'single_{k}']['s20']['phmed_sharpe']:+.3f} "
            f"corrB={res[f'single_{k}']['corr_B_off0']:+.3f} "
            f"availwin S={res[f'single_{k}']['s20']['availwin']['phmed_sharpe']:+.3f}")
    # 与轨B 等权混合（增量资金口径：B 缺席时自动退化为 B 本身）
    for k in ["flow20", "flow5", "flow_acc"]:
        comp = zcombo({"base": base.astype(np.float64), k: F[k].astype(np.float64) * signs[k]}, ELIG)
        res[f"blend50_{k}"] = eval_arm(comp, E, track, f"轨B 50% + {k} 50%", avail_start)
        log(f"  ARMED blend {k}: phmed S={res[f'blend50_{k}']['s20']['phmed_sharpe']:+.3f} "
            f"corrB={res[f'blend50_{k}']['corr_B_off0']:+.3f} "
            f"availwin S={res[f'blend50_{k}']['s20']['availwin']['phmed_sharpe']:+.3f}")
    return res, signs


def _fwd(E):
    O = E["O"]; ND, NC = O.shape
    f = np.full((ND, NC), np.nan)
    f[:ND - 1 - 20] = O[21:] / O[1:ND - 20] - 1
    return f


def stage_placebo(E, F, track):
    """标签置换安慰剂：行业→个股映射随机打乱 12 次，看单因子臂得分的分布下界"""
    ELIG = E["ELIG3"]
    base_codes = F["flow20"].shape
    rng = np.random.default_rng(20260916)
    shs = []
    for i in range(12):
        perm = rng.permutation(base_codes[1])
        v = F["flow20"][:, perm].astype(np.float64)
        comp = zcombo({"p": v}, ELIG)
        m = E["run_engine"](comp, 20, offset=0)
        shs.append(float(m["sharpe"]))
        log(f"  placebo {i+1}/12 S={shs[-1]:+.3f}")
    return {"n": len(shs), "sharpe_off0": shs, "mean": float(np.mean(shs)), "median": float(np.median(shs)),
            "p95": float(np.percentile(shs, 95)), "max": float(np.max(shs))}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", nargs="?", default="all")
    a = ap.parse_args()
    out = {}
    if os.path.exists(OUT):
        out = json.load(open(OUT, encoding="utf-8"))
    if a.stage in ("build", "all"):
        log("== build factors =="); F, cov = build_factors(); out["coverage"] = cov
        jdump(out, OUT); log(f"SAVED {OUT}")
    if a.stage in ("all", "ic", "arms", "placebo"):
        P, E, F, base, track = load_all()
        fin = np.isfinite(F["flow20"]).any(axis=1)
        av = str(E["cal"][np.flatnonzero(fin)[0]]) if fin.any() else None
        if a.stage in ("ic", "all"):
            log("== IC =="); out["ic"] = stage_ic(E, F, P)
        if a.stage in ("arms", "all"):
            log(f"== arms (因子可用窗起 {av}) ==")
            res, signs = stage_arms(E, F, base, track, av)
            out["arms"] = res; out["signs"] = signs
        if a.stage == "placebo":
            log("== placebo =="); out["placebo"] = stage_placebo(E, F, track)
        jdump(out, OUT)
        log(f"SAVED {OUT}")
