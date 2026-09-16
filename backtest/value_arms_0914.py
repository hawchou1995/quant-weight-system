# -*- coding: utf-8 -*-
"""轨 II 臂位执行器：把判据表里"本机可算"的条目转成因子，跑长周期组合级回测。

判据来源：
  D:/Tools/cache/ima_kb/buffett/criteria_cn.md（70 条，中文语料 45 篇）
  D:/Tools/cache/ima_kb/buffett/criteria_en.md（79 条，英文股东信 25 封）
口径：见 backtest/PRE-REGISTRATION_20260914_value_buffett.md（轨 II = H250 年度再平衡）
锚：沪深300（index_000300）/ 红利ETF（sh510880）/ 价值ETF（sh510030）/ 300ETF（sh510300）
    ⚠ data_full 的 sz000922 / sz000919 是**个股**（佳电股份/金陵药业），不是指数——勿用（trap）
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import value_lh_0914 as V  # noqa: E402

OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "value_arms_0914.json")


# ---------------------------------------------------------------- 因子库
def load_bs_val(feat):
    """baostock 全 A 估值（2015 起，含退市）→ date×code 三矩阵。"""
    d = os.path.join(V.FUND, "baostock_val2")
    if not os.path.isdir(d):
        return None
    frames = {"close": {}, "pb": {}, "pe": {}}
    n = 0
    for f in os.listdir(d):
        if not f.endswith(".csv"):
            continue
        code = "sh" + f[2:-4] if f.startswith("sh.") else "sz" + f[2:-4]
        if code not in feat["close"].columns:
            continue
        try:
            df = pd.read_csv(os.path.join(d, f), dtype={"date": str})
        except Exception:
            continue
        if len(df) < 400:
            continue
        idx = pd.to_datetime(df["date"])
        for k, col in [("close", "close"), ("pb", "pbMRQ"), ("pe", "peTTM")]:
            frames[k][code] = pd.Series(pd.to_numeric(df[col], errors="coerce").values, index=idx)
        n += 1
    if n < 100:
        return None
    print(f"[bs] 载入 baostock 估值 {n} 只")
    return {k: pd.DataFrame(v).sort_index().reindex(feat["dates"]).astype("float32")
            for k, v in frames.items()}


def val_from_fundamentals(feat, raw, validate=True):
    """用「不复权价 + 每股净资产/每股收益」构造 2016+ 的 PB/PE。

    数据源：yjbb_quarterly.csv（2020Q1+） + yjbb_ext_2016_2019.csv（2016-2019，本轮补拉）
    PIT：法定披露截止日（ADR-0005）——该接口的「最新公告日期」对历史期已失真，一律不用。
    PE 用 TTM EPS：先把累计 EPS 差分成单季，再取近 4 季滚动和。
    验证：2021+ 与东财 val_em 的 PB 对拍。
    """
    import numpy as _np
    parts = []
    for f in [f"{V.FUND}/yjbb_quarterly.csv", f"{V.FUND}/yjbb_ext_2016_2019.csv"]:
        if os.path.exists(f):
            parts.append(pd.read_csv(f, dtype={"股票代码": str}, encoding="utf-8-sig"))
    if not parts:
        return None, None
    y = pd.concat(parts, ignore_index=True)
    y["code"] = y["股票代码"].astype(str).str.zfill(6)
    codes = {c[-6:]: c for c in feat["close"].columns}
    y = y[y["code"].isin(codes)].copy()
    y["col"] = y["code"].map(codes)
    y["rp"] = pd.to_datetime(y["REPORT_PERIOD"].astype(str), format="%Y%m%d", errors="coerce")
    y["bps"] = pd.to_numeric(y["每股净资产"], errors="coerce")
    y["eps_cum"] = pd.to_numeric(y["每股收益"], errors="coerce")
    y = y.dropna(subset=["rp"]).sort_values(["col", "rp"])
    prev = y.groupby("col")["eps_cum"].shift(1)
    prev_rp = y.groupby("col")["rp"].shift(1)
    same_year = (y["rp"].dt.year == prev_rp.dt.year).values
    y["eps_q"] = _np.where(y["rp"].dt.month.values == 3, y["eps_cum"],
                           _np.where(same_year, y["eps_cum"] - prev, y["eps_cum"]))
    y["eps_ttm"] = y.groupby("col")["eps_q"].transform(
        lambda s: s.rolling(4, min_periods=4).sum())

    def _dl(d):
        if pd.isna(d):
            return pd.NaT
        m, yy = d.month, d.year
        return {3: pd.Timestamp(yy, 4, 30), 6: pd.Timestamp(yy, 8, 31),
                9: pd.Timestamp(yy, 10, 31), 12: pd.Timestamp(yy + 1, 4, 30)}.get(m, pd.NaT)
    y["pub"] = y["rp"].map(_dl)
    y = y.dropna(subset=["pub"])
    bps = y.pivot_table(index="pub", columns="col", values="bps", aggfunc="last").sort_index()
    ttm = y.pivot_table(index="pub", columns="col", values="eps_ttm", aggfunc="last").sort_index()
    bps = bps.reindex(feat["dates"]).ffill().reindex(columns=feat["close"].columns)
    ttm = ttm.reindex(feat["dates"]).ffill().reindex(columns=feat["close"].columns)
    pb = (raw / bps).where(bps > 0)
    pe = (raw / ttm).where(ttm > 0)
    if validate:
        try:
            v = pd.read_csv(f"{V.FUND}/val_em/val_em_all.csv",
                            usecols=["code", "date", "pb_mrq"], dtype={"code": str})
            v["code"] = v["code"].str.zfill(6)
            cm = {c[-6:]: c for c in feat["close"].columns}
            v = v[v["code"].isin(cm)]
            v["col"] = v["code"].map(cm)
            vp = v.pivot_table(index="date", columns="col", values="pb_mrq", aggfunc="last")
            vp.index = pd.to_datetime(vp.index)
            common = pb.index.intersection(vp.index)
            a = pb.loc[common].reindex(columns=vp.columns)
            b = vp.loc[common]
            rel = ((a - b).abs() / b).replace([_np.inf, -_np.inf], _np.nan)
            print(f"[val-fund] 构造 PB 覆盖 {(pb.notna().sum(axis=1) >= 100).sum()} 日；"
                  f"与 val_em 对拍（{len(common)} 日 2021+）中位相对误差 {rel.stack().median():.2%}，"
                  f"P90 {rel.stack().quantile(0.9):.2%}")
        except Exception as e:
            print(f"[val-fund] 对拍失败 {type(e).__name__} {e}")
    return pb.astype("float32"), pe.astype("float32")


def industry_of(feat):
    """6 位码 → 申万一级（stock_industry.json），列名统一为带前缀 code。"""
    p = os.path.join(os.path.dirname(V.ROOT), "quant-weight-system", "stock_industry.json")
    p = os.path.join(V.ROOT, "stock_industry.json")
    try:
        m = json.load(open(p, encoding="utf-8"))["map"]
    except Exception as e:
        print(f"[ind] 行业表缺失 {e}")
        return {}
    return {c: m.get(c[-6:]) for c in feat["close"].columns}


def q_daily(feat, key):
    """季频面板（按公告日）→ 日频前向填充。"""
    if key not in feat:
        return None
    m = feat[key].reindex(feat["dates"]).ffill()
    return m.reindex(columns=feat["close"].columns)


def build_factors(feat, bs=None, val_override=None):
    f = {}
    close = feat["close"]
    # --- 估值分母：优先 baostock（2016+），否则 val_em（2021+），否则重建不复权价
    if val_override is not None:
        raw = feat.get("_raw_close", V.raw_close(feat, validate=False))
        pb, pe = val_override
    elif bs is not None:
        raw = bs["close"]
        pb = bs["pb"]
        pe = bs["pe"]
    else:
        raw = feat.get("_raw_close", V.raw_close(feat, validate=False))
        pb = feat["pb"].reindex(feat["dates"]).ffill() if "pb" in feat else None
        pe = feat["pe"].reindex(feat["dates"]).ffill() if "pe" in feat else None

    f["raw_close"] = raw
    # --- A/B 估值族
    f["dy"] = V.ttm_dividend_yield(feat, use_raw=True)
    if pb is not None:
        f["bp"] = (1.0 / pb.replace(0, np.nan))
    if pe is not None:
        f["ep"] = (1.0 / pe.replace(0, np.nan)).where(pe > 0)
    # --- 质量族（yjbb，PIT=公告日）
    roe = q_daily(feat, "roe_q")
    gpm = q_daily(feat, "gpm_q")
    ocfps = q_daily(feat, "ocfps_q")
    rev_yoy = q_daily(feat, "rev_yoy_q")
    np_yoy = q_daily(feat, "np_yoy_q")
    f["roe"] = roe
    f["gpm"] = gpm
    f["rev_yoy"] = rev_yoy
    # ROE ÷ PB（B5「股权债券票息」）
    if pb is not None and roe is not None:
        f["roe_pb"] = roe / pb.replace(0, np.nan) / 100.0
    # 毛利率 − 行业中位数（A5）
    ind = industry_of(feat)
    if gpm is not None and ind:
        grp = pd.Series({c: ind.get(c) for c in gpm.columns})
        med = gpm.T.groupby(grp).transform("median").T if False else None
        # 按日分组中位数：对每行按行业求中位（向量化）
        cols = gpm.columns
        g = grp.reindex(cols)
        med_df = pd.DataFrame(index=gpm.index, columns=cols, dtype="float32")
        for name, sub in g.groupby(g).groups.items():
            cols_ = list(sub)
            if pd.isna(name) or len(cols_) < 3:
                continue
            med = gpm[cols_].median(axis=1).values
            med_df[cols_] = np.repeat(med[:, None], len(cols_), axis=1)
        f["gpm_rel"] = gpm - med_df
    # 连续 N 季 ROE ≥ 阈值（A12 变体）：用季频面板（numpy 递推，避免 pandas 只读数组）
    if roe is not None and "roe_q" in feat:
        qm = feat["roe_q"].reindex(feat["dates"]).ffill().reindex(columns=feat["close"].columns)
        v = qm.values.astype("float64")
        nanm = np.isnan(v)
        hit = (v >= 12)
        run = np.zeros(v.shape[1])
        out = np.zeros_like(v)
        for i in range(v.shape[0]):
            run = np.where(nanm[i], run, np.where(hit[i], run + 1, 0))
            out[i] = run
        f["roe_streak"] = pd.DataFrame(out, index=qm.index, columns=qm.columns).astype("float32")
    # 近 5 年分红年数（E4）
    f["div_years"] = V.dividend_year_count(feat, years=5)
    # 分红率 = dps / EPS（B9/D16）
    if "每股收益" in open(f"{V.FUND}/yjbb_quarterly.csv", encoding="utf-8").readline():
        y = pd.read_csv(f"{V.FUND}/yjbb_quarterly.csv", dtype={"股票代码": str},
                        usecols=["股票代码", "每股收益", "REPORT_PERIOD"])
        y["col"] = "sh" + y["股票代码"].str.zfill(6)
        y.loc[~y["col"].isin(close.columns), "col"] = "sz" + y["股票代码"].str.zfill(6)
        y["rp"] = pd.to_datetime(y["REPORT_PERIOD"].astype(str), format="%Y%m%d", errors="coerce")
        eps = y.pivot_table(index="rp", columns="col", values="每股收益", aggfunc="last")
        eps = eps.reindex(feat["dates"]).ffill().reindex(columns=close.columns)
        ev = feat["div_events"]
        d64 = feat["dates"].values.astype("datetime64[D]")
        ttm = pd.DataFrame(0.0, index=feat["dates"], columns=close.columns, dtype="float32")
        for c, gg in ev.groupby("col"):
            if c not in close.columns:
                continue
            gg = gg.sort_values("ex_date")
            ex = gg["ex_date"].values.astype("datetime64[D]")
            cs = np.concatenate([[0.0], np.nancumsum(gg["dps"].values)])
            hi = np.searchsorted(ex, d64, side="right")
            lo = np.searchsorted(ex, d64 - np.timedelta64(365, "D"), side="right")
            ttm[c] = cs[hi] - cs[lo]
        f["payout"] = (ttm / eps.replace(0, np.nan)).where((eps > 0) & (ttm > 0))
        f["ocf_eps"] = (ocfps / eps.replace(0, np.nan)).where(eps > 0) if ocfps is not None else None
    # 统一列对齐（2026-09-15 修）：val_em/baostock 用的是 3469 只全清单，价格矩阵过滤后为 3402 只，
    # 两矩阵做算术会按列取并集导致膨胀（实测 roe_pb 3459 列 vs close 3402 → groupby 崩）
    cc = feat["close"].columns
    for k, v in list(f.items()):
        if isinstance(v, pd.DataFrame):
            f[k] = v.reindex(columns=cc)
    return f


# ---------------------------------------------------------------- 臂定义
def arm_scores(f, keys, masks=None):
    """返回 {臂名: (score, 说明)}；score 小者优先（用 -值 或 rank 分位）。"""
    out = {}
    for name, expr in keys.items():
        out[name] = expr
    return out


def run_arm(feat, score, exclude, rebal=250, topn=10, slip=0.002, phases=9, start="2016-01-01"):
    """相位扫描：offset 0..rebal 均匀取样；返回 phmed 与相位表。"""
    res = []
    for p in range(phases):
        off = int(round(p * rebal / phases))
        r = V.run(feat, score, rebal=rebal, topn=topn, slip=slip, offset=off,
                  start=start, exclude=exclude)
        res.append(dict(offset=off, ann=r["ann"], sharpe=r["sharpe"], mdd=r["mdd"],
                        total=r["total"], trades=r["trades"]))
    sh = [x["sharpe"] for x in res]
    an = [x["ann"] for x in res]
    return dict(phases=res, sharpe_med=float(np.median(sh)), sharpe_min=float(np.min(sh)),
                sharpe_max=float(np.max(sh)), ann_med=float(np.median(an)),
                ann_min=float(np.min(an)), ann_max=float(np.max(an)))


def coverage_start(fac, need, min_uniq=5):
    """因子起算日：既要有效值 >= need，**又要有足够截面离散度**（min_uniq 个不同取值）。

    加离散度条件的原因：分红类因子在数据起点前全为 0（等值），rank 排名退化为按列序
    → 等价于随机选股，会污染该段净值（2026-09-14 自查发现）。
    """
    v = fac.notna().sum(axis=1)
    u = fac.nunique(axis=1)
    ok = v[(v >= need) & (u >= min_uniq)]
    return ok.index[0].strftime("%Y-%m-%d") if len(ok) else None


def make_score(fac, mask=None):
    """高分优先 → 分数=降序分位（小者优先）。mask 外的置 NaN。"""
    x = fac.where(mask) if mask is not None else fac
    return x.rank(axis=1, pct=True, ascending=False)


def combo_score(primary, secondary, w=0.3):
    """主因子 + 次因子并列打破：整数因子（如 div_years∈0..5）rank 大量并值，
    若不做二级排序，argsort 会退化为**按列序（代码序）取前 N**——等于把交易所/代码段
    偷偷变成选择规则（2026-09-14 自查发现）。此处以次因子权重 w<1 保证主序不失真。
    """
    r1 = primary.rank(axis=1, pct=True, ascending=False)
    r2 = secondary.rank(axis=1, pct=True, ascending=False)
    return r1 + w * r2


def gate(*conds):
    m = None
    for c in conds:
        m = c if m is None else (m & c)
    return m


if __name__ == "__main__":
    feat = V.load_features()
    if "_raw_close" not in feat:
        feat["_raw_close"] = V.raw_close(feat, validate=True)
    bs = load_bs_val(feat)
    print(f"[main] baostock 估值 {'可用' if bs else '不可用（回退 val_em 2021+）'}")
    f = build_factors(feat, bs)
    print("[main] 因子构建完成:", sorted(k for k, v in f.items() if v is not None))

    base_ex = V.st_mask(feat)
    TOPN, REBAL, PHASES, SLIP = 10, 250, 9, 0.002

    # 估值分位（用于与门）
    pe_pct = f["pe"].rank(axis=1, pct=True) if f.get("pe") is not None else None
    pe_pct = pe_pct.reindex(columns=feat["close"].columns) if pe_pct is not None else None

    arms = []
    for name in ["dy", "bp", "ep", "roe_pb", "roe", "gpm_rel", "roe_streak", "payout"]:
        if f.get(name) is not None:
            arms.append((f"F_{name}", f[name], None, None))
    if f.get("div_years") is not None and f.get("dy") is not None:
        arms.append(("F_div_years(并列按dy破)", combo_score(f["div_years"], f["dy"]),
                     None, "分红年数为主序、股息率为次序（消除整数并值→代码序偏置）"))
    # 结构族（与门）——判据原文见 criteria_cn.md
    if f.get("roe") is not None and f.get("payout") is not None and f.get("dy") is not None:
        m = gate(f["roe"] >= 12, f["payout"] <= 0.5, f["dy"] > 0.005)
        arms.append(("G1_E3lite(ROE>=12∧分红率<=50%∧dy>0)", f["dy"], m, "E3 价值投资改进版降级（缺流动比率/FCF）"))
    if f.get("roe") is not None and pe_pct is not None and f.get("roe_pb") is not None:
        m = gate(f["roe"] >= 15, pe_pct < 0.5)
        arms.append(("G2_B4(ROE>=15∧PE分位<50%)", f["roe_pb"], m, "B4 以合理价格买优秀公司"))
    if f.get("div_years") is not None and f.get("dy") is not None:
        m = gate(f["div_years"] >= 4, f["dy"] > 0.01)
        arms.append(("G3_E4(近5年分红>=4年∧dy>1%)", f["dy"], m, "E4 高股息（行业中性未加）"))
    if f.get("gpm_rel") is not None and f.get("roe_pb") is not None:
        m = gate(f["gpm_rel"] > 0)
        arms.append(("G4_A5(毛利率>行业中位)", f["roe_pb"], m, "A5 护城河代理 × 票息"))

    res = {}
    print("")
    print(f"{'臂':46s} {'起点':11s} {'phmed S':>8s} {'相位区间':>14s} {'年化中位':>9s}")
    for name, fac, mask, note in arms:
        sc = make_score(fac, mask)
        need = TOPN * 3
        start = coverage_start(sc, need)
        if start is None:
            print(f"{name:46s} 有效值不足，跳过")
            continue
        r = run_arm(feat, sc, base_ex, rebal=REBAL, topn=TOPN, slip=SLIP,
                    phases=PHASES, start=start)
        r["start"] = start
        r["note"] = note
        res[name] = r
        print(f"{name:46s} {start:11s} {r['sharpe_med']:8.3f} "
              f"{r['sharpe_min']:6.2f}~{r['sharpe_max']:5.2f} {r['ann_med']:8.2%}", flush=True)

    anchors = {}
    for nm, c in [("沪深300", "index_000300"), ("红利ETF", "sh510880"),
                  ("价值ETF", "sh510030"), ("300ETF", "sh510300")]:
        try:
            b = V.bench(feat, c, start="2016-01-01")
            anchors[nm] = {k: b[k] for k in ("total", "ann", "sharpe", "mdd")}
        except Exception as e:
            anchors[nm] = {"err": str(e)[:60]}
    print("")
    print("[锚] 2016-01-01 起（注：sz000922/sz000919 是个股，已弃用）")
    for nm, a in anchors.items():
        if "err" in a:
            print(f"  {nm}: {a['err']}")
        else:
            print(f"  {nm:8s} ann={a['ann']:.2%} S={a['sharpe']:.3f} mdd={a['mdd']:.2%}")

    json.dump({"arms": res, "anchors": anchors, "config": dict(
        topn=TOPN, rebal=REBAL, phases=PHASES, slip=SLIP, window="per-arm auto")},
        open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("")
    print(f"[main] 落盘 {OUT_JSON}")
