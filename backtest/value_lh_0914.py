# -*- coding: utf-8 -*-
"""轨 II · 长周期价值回测引擎（巴菲特价值投资 A 股可行性 · R-buffett-value-0915）

设计（预注册 PRE-REGISTRATION_20260914_value_buffett.md）：
  - 持有期/调仓：`rebal` 交易日（250 ≈ 年度；可扫相位 offset）
  - 池：全 A 主板（sh60*/sz00*），ST/退 过滤口径可切（name_hist.csv 逐日时点简称，PIT 安全）
  - 计分：外部注入 `score_fn(feat) -> DataFrame(date×code)`，值越小越优先（排名语义）
  - 执行：T 收盘算分 → T+1 开盘成交（无未来函数）；等权 TopN
  - 成本：佣金 2.5bp（最低 5 元）+ 卖出印花税 10bp + 滑点 slip（默认 20bp）
  - 基准：沪深300 / 中证红利(sz000922) / 300价值(sz000919) / 红利ETF(sh510880)

特征层（本文件 build_features 产出，落盘 `value_lh_0914.pkl`）：
  close / open / pb / pe / total_mv / float_mv / dy_ttm（TTM 股息率）/ dy_years5（近 5 年分红年数）
  / roe_q（PIT 季频 ROE）/ gpm_q（PIT 毛利率）/ ocfps_q（PIT 每股经营现金流）/ rev_yoy_q / np_yoy_q / st_mask

用法：
  python value_lh_0914.py build          # 构建特征缓存（约 1-2 分钟）
  python value_lh_0914.py smoke          # 冒烟：股息率 Top10 年度调仓 2016-2026
"""
import os
import pickle
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # quant-weight-system/
DATA = os.path.join(ROOT, "data_full")
FUND = os.path.join(ROOT, "data_fundamental")
OUT = os.path.join(ROOT, "backtest", "value_lh_0914.pkl")

COMM_RATE = 0.00025      # 佣金 2.5bp
COMM_MIN = 5.0           # 最低 5 元
SELL_TAX = 0.001         # 印花税 10bp
CAPITAL = 1_000_000.0    # 回测本金（研究口径；生产 17 万另测）


# ---------------------------------------------------------------- 特征层
def _stock_files(main_board_only=True):
    out = []
    for f in os.listdir(DATA):
        if not f.endswith(".csv"):
            continue
        c = f[:-4]
        if main_board_only:
            if not (re.match(r"^sh60", c) or re.match(r"^sz00", c)):
                continue
        else:
            if not (re.match(r"^sh6", c) or re.match(r"^sz0", c)):
                continue
        out.append((c, os.path.join(DATA, f)))
    return sorted(out)


def _load_matrices(files, field, min_rows=400):
    """→ DataFrame(index=date, columns=code)。CSV 为前复权。"""
    ser = {}
    for code, path in files:
        try:
            df = pd.read_csv(path, usecols=["date", field], dtype={"date": str})
        except Exception:
            continue
        if len(df) < min_rows:
            continue
        s = pd.Series(pd.to_numeric(df[field], errors="coerce").values,
                      index=pd.to_datetime(df["date"]))
        ser[code] = s
    m = pd.DataFrame(ser)
    return m.sort_index()


def _load_val(files, field):
    """东财 val_em（2021-01 起）+ pre2021 补拉（2018-01 起）→ DataFrame(date×code)。

    2026-09-15 扩容：fetch_val_em_pre2021.py 补拉 2018-01-02~2020-12-31（2,875 票 / 197 万行），
    官方口径估值窗口由 5.7 年扩至 8.7 年。
    """
    parts = []
    for f in [f"{FUND}/val_em/val_em_all.csv", f"{FUND}/val_em/val_em_pre2021.csv"]:
        if os.path.exists(f):
            parts.append(pd.read_csv(f, usecols=["code", "date", field], dtype={"code": str}))
    df = pd.concat(parts, ignore_index=True).drop_duplicates(subset=["code", "date"])
    df["code"] = df["code"].str.zfill(6)
    codes = {c[-6:]: c for c, _ in files}
    df = df[df["code"].isin(codes)]
    df["col"] = df["code"].map(codes)
    m = df.pivot_table(index="date", columns="col", values=field, aggfunc="last")
    m.index = pd.to_datetime(m.index)
    return m.sort_index()


def _load_name_hist(files):
    """逐日简称 → ST/退 掩码（PIT）。缺该日简称则向后填充。"""
    nh = pd.read_csv(f"{FUND}/name_hist.csv", dtype={"code": str},
                     usecols=["code", "TRADE_DATE", "SECURITY_NAME_ABBR"])
    nh["TRADE_DATE"] = pd.to_datetime(nh["TRADE_DATE"]).dt.normalize()
    codes = {c[-6:]: c for c, _ in files}
    nh = nh[nh["code"].isin(codes)]
    nh["col"] = nh["code"].map(codes)
    pv = nh.pivot_table(index="TRADE_DATE", columns="col",
                        values="SECURITY_NAME_ABBR", aggfunc="last")
    return pv.sort_index()


def _load_dividend(files):
    """分红事件 → TTM 股息率 + 近 5 年分红年数（PIT：按除权除息日生效）。
    注意：`col` = 价格矩阵的列名（带 sh/sz 前缀），后续一律按 `col` 对齐。"""
    ev = pd.read_csv(f"{FUND}/dividend/dividend_events.csv", dtype={"code": str})
    ev["code"] = ev["code"].str.zfill(6)
    ev["dps"] = pd.to_numeric(ev["dps"], errors="coerce")
    ev["ex_date"] = pd.to_datetime(ev["ex_date"], errors="coerce")
    if "progress" in ev.columns:
        ev = ev[ev["progress"].astype(str).str.contains("实施", na=False)]
    ev = ev.dropna(subset=["ex_date", "dps"])
    codes = {c[-6:]: c for c, _ in files}
    ev = ev[ev["code"].isin(codes)].copy()
    ev["col"] = ev["code"].map(codes)
    return ev


def _load_yjbb(files):
    """季频财务（PIT：法定披露截止日，沿用 ADR-0005 口径）。

    2026-09-15 扩容：合并 yjbb_ext_2016_2019.csv（本轮补拉，16 期）→ 季频面板从
    2020Q1 回溯到 2016Q1，使 ROE/毛利率/经营现金流/营收净利同比可覆盖轨 II 全窗口。
    """
    parts = []
    for f in [f"{FUND}/yjbb_quarterly.csv", f"{FUND}/yjbb_ext_2016_2019.csv"]:
        if os.path.exists(f):
            parts.append(pd.read_csv(f, dtype={"股票代码": str}, encoding="utf-8-sig"))
    y = pd.concat(parts, ignore_index=True).drop_duplicates(
        subset=["股票代码", "REPORT_PERIOD"], keep="first")
    y["code"] = y["股票代码"].str.zfill(6)
    codes = {c[-6:]: c for c, _ in files}
    y = y[y["code"].isin(codes)].copy()
    y["col"] = y["code"].map(codes)
    rp = y["REPORT_PERIOD"].astype(str)
    y["rp"] = pd.to_datetime(rp, format="%Y%m%d", errors="coerce")
    # 法定披露截止日（ADR-0005）：Q1→4/30、H1→8/31、Q3→10/31、FY→次年4/30
    def _deadline(d):
        if pd.isna(d):
            return pd.NaT
        m, yy = d.month, d.year
        return {3: pd.Timestamp(yy, 4, 30), 6: pd.Timestamp(yy, 8, 31),
                9: pd.Timestamp(yy, 10, 31), 12: pd.Timestamp(yy + 1, 4, 30)}.get(m, pd.NaT)
    y["pub"] = y["rp"].map(_deadline)
    y = y.dropna(subset=["pub"])
    return y


def _q_panel(y, field):
    """季度字段 → 按公告日生效、前向填充到日频（date×code 矩阵）。"""
    sub = y[["pub", "col", field]].dropna()
    m = sub.pivot_table(index="pub", columns="col", values=field, aggfunc="last")
    return m.sort_index()


def build_features():
    files = _stock_files(main_board_only=True)
    print(f"[build] 主板文件 {len(files)} 个")
    close = _load_matrices(files, "close")
    open_ = _load_matrices(files, "open")
    MIN_DATE = pd.Timestamp("2014-01-01")   # 长周期回测最早 2016 起，留 2 年预热
    close = close[close.index >= MIN_DATE]
    open_ = open_[open_.index >= MIN_DATE]
    print(f"[build] close {close.shape} / open {open_.shape}（≥{MIN_DATE.date()}）")

    feat = {
        "close": close.astype("float32"),
        "open": open_.astype("float32"),
        "dates": close.index,
        "codes": list(close.columns),
    }
    try:
        feat["pb"] = _load_val(files, "pb_mrq").astype("float32")
        feat["pe"] = _load_val(files, "pe_ttm").astype("float32")
        feat["total_mv"] = _load_val(files, "total_mv").astype("float32")
        print(f"[build] val_em pb/pe/mv: {feat['pb'].shape} {feat['pb'].index.min().date()}~{feat['pb'].index.max().date()}")
    except Exception as e:
        print(f"[build] val_em 载入失败（非致命）：{type(e).__name__} {e}")

    try:
        nh = _load_name_hist(files)
        feat["name_hist"] = nh
        print(f"[build] name_hist {nh.shape}")
    except Exception as e:
        print(f"[build] name_hist 失败：{e}")

    ev = _load_dividend(files)
    feat["div_events"] = ev
    print(f"[build] 分红事件（主板）{len(ev)} 条 / {ev['code'].nunique()} 只")

    try:
        y = _load_yjbb(files)
        for field, key in [("净资产收益率", "roe_q"), ("销售毛利率", "gpm_q"),
                           ("每股经营现金流量", "ocfps_q"), ("营业总收入-同比增长", "rev_yoy_q"),
                           ("净利润-同比增长", "np_yoy_q")]:
            feat[key] = _q_panel(y, field).astype("float32")
        print(f"[build] yjbb 面板 roe {feat['roe_q'].shape}")
    except Exception as e:
        print(f"[build] yjbb 失败：{e}")

    # 预计算 ST/退 掩码（bool），避免把 4.4M 字符串表塞进缓存（内存事故教训）
    nh = feat.pop("name_hist", None)
    if nh is not None:
        nhr = nh.reindex(feat["dates"]).ffill().astype(str)
        feat["mask_st"] = nhr.apply(lambda c: c.str.contains("ST|退", na=False)).astype(bool)
        feat["mask_tui"] = nhr.apply(lambda c: c.str.contains("退", na=False)).astype(bool)
        del nhr
        print(f"[build] 掩码预计算完成 ST/退={feat['mask_st'].values.mean():.4f}")

    with open(OUT, "wb") as f:
        pickle.dump(feat, f, protocol=4)
    print(f"[build] 落盘 {OUT} ({os.path.getsize(OUT)/1e6:.0f}MB)")
    return feat


def load_features():
    with open(OUT, "rb") as f:
        return pickle.load(f)


# ---------------------------------------------------------------- 派生因子
def raw_close(feat, validate=True):
    """用分红/送转事件反推**不复权**收盘价。

    原理：前复权价满足 raw(d) = qfq(d) / f_adj(d)，其中
          f_adj(d) = Π_{e>d} ratio_e，ratio_e = P_after/P_before = (1 - dy_e) / (1 + sz_e)
          （标准除权公式，忽略配股；dy=东财报告股息率、sz=每股送转比例）
    验证：与 val_em 的不复权 close 在 2021+ 重叠段对拍。
    """
    close = feat["close"]
    ev = feat["div_events"].copy()
    ev["dy_reported"] = pd.to_numeric(ev["dy_reported"], errors="coerce")
    ev["sz_ratio"] = pd.to_numeric(ev.get("sz_ratio"), errors="coerce").fillna(0.0)
    if "progress" in ev.columns:
        ev = ev[ev["progress"].astype(str).str.contains("实施", na=False)]
    ev = ev.dropna(subset=["ex_date"])
    ev = ev[ev["dy_reported"].notna() & (ev["dy_reported"] < 0.5)]
    cover = ev.groupby("code").size()
    print(f"[raw_close] 可用事件 {len(ev)} 条 / {cover.size} 只"
          f"（中位 {cover.median():.0f} 条/只）")

    d64 = feat["dates"].values.astype("datetime64[D]")
    out = close.astype("float32").copy()
    for code, g in ev.groupby("col"):
        if code not in close.columns:
            continue
        g = g.sort_values("ex_date")
        ex = g["ex_date"].values.astype("datetime64[D]")
        ratio = ((1.0 - g["dy_reported"].values) / (1.0 + g["sz_ratio"].values))
        ratio = np.clip(ratio, 0.3, 1.5)
        suf = np.concatenate([np.cumprod(ratio[::-1])[::-1], [1.0]])
        i = np.searchsorted(ex, d64, side="right")
        f = suf[i]
        out[code] = (close[code].values / f).astype("float32")

    if validate:
        try:
            v = pd.read_csv(f"{FUND}/val_em/val_em_all.csv",
                            usecols=["code", "date", "close"], dtype={"code": str})
            v["code"] = v["code"].str.zfill(6)
            codes = {c[-6:]: c for c in close.columns}
            v = v[v["code"].isin(codes)]
            v["col"] = v["code"].map(codes)
            vp = v.pivot_table(index="date", columns="col", values="close", aggfunc="last")
            vp.index = pd.to_datetime(vp.index)
            common = out.index.intersection(vp.index)
            a = out.loc[common]
            b = vp.loc[common]
            rel = ((a - b).abs() / b).replace([np.inf, -np.inf], np.nan)
            med = rel.stack().median()
            p90 = rel.stack().quantile(0.90)
            print(f"[raw_close] 与 val_em 不复权价对拍（{len(common)} 日）："
                  f"中位相对误差 {med:.4%}，P90 {p90:.4%}")
        except Exception as e:
            print(f"[raw_close] 对拍失败：{type(e).__name__} {e}")
    return out


def ttm_dividend_yield(feat, use_raw=True):
    """TTM 股息率 = 近 365 天已除权 dps 之和 ÷ 当日收盘（默认用重建的不复权价）。"""
    dates = feat["dates"]
    denom = feat["_raw_close"] if use_raw and "_raw_close" in feat else feat["close"]
    ev = feat["div_events"]
    d64 = dates.values.astype("datetime64[D]")
    ttm = pd.DataFrame(0.0, index=dates, columns=denom.columns, dtype="float32")
    for code, g in ev.groupby("col"):
        if code not in denom.columns:
            continue
        g = g.sort_values("ex_date")
        ex = g["ex_date"].values.astype("datetime64[D]")
        csum = np.concatenate([[0.0], np.nancumsum(g["dps"].values)])
        hi = np.searchsorted(ex, d64, side="right")
        lo = np.searchsorted(ex, d64 - np.timedelta64(365, "D"), side="right")
        ttm[code] = csum[hi] - csum[lo]
    return (ttm / denom).replace([np.inf, -np.inf], np.nan)


def dividend_year_count(feat, years=5):
    """近 N 个自然年中有现金分红的年数（PIT：按除权除息日归属年份）。"""
    close, dates = feat["close"], feat["dates"]
    ev = feat["div_events"]
    yr = dates.year.values
    all_years = list(np.unique(yr))
    out = pd.DataFrame(np.nan, index=dates, columns=close.columns, dtype="float32")
    for code, g in ev.groupby("col"):
        if code not in close.columns:
            continue
        yrs_hit = set(pd.Series(g["ex_date"]).dt.year.tolist())
        # 修正：先按"自然年 → 近 N 年窗口内命中数"建映射，再按日映射（原实现只写了数组前 13 位）
        ymap = {}
        for i, y in enumerate(all_years):
            back = all_years[max(0, i - years + 1): i + 1]
            ymap[y] = len([yy for yy in back if yy in yrs_hit])
        out[code] = pd.Series(yr, index=dates).map(ymap).values.astype("float32")
    return out


def st_mask(feat):
    """True = 应剔除（含 ST/*ST/退）；优先用 build 期预计算的 bool 缓存。"""
    if "mask_st" in feat:
        return feat["mask_st"]
    nh = feat["name_hist"].reindex(feat["dates"]).ffill()
    return nh.astype(str).apply(
        lambda col: col.str.contains("ST|退", na=False, regex=True)).astype(bool)


def st_tui_mask(feat):
    if "mask_tui" in feat:
        return feat["mask_tui"]
    nh = feat["name_hist"].reindex(feat["dates"]).ffill()
    return nh.astype(str).apply(
        lambda col: col.str.contains("退", na=False)).astype(bool)


# ---------------------------------------------------------------- 回测引擎
def run(feat, score, rebal=250, topn=10, slip=0.002, offset=0,
        start=None, end=None, exclude=None, capital=CAPITAL, verbose=False):
    """score: date×code 的排名分（**小者优先**）；exclude: 布尔矩阵（True=剔除）。"""
    dates_all = feat["dates"]
    lo = pd.Timestamp(start) if start else dates_all[0]
    hi = pd.Timestamp(end) if end else dates_all[-1]
    keep = (dates_all >= lo) & (dates_all <= hi)
    dates = dates_all[keep]
    close = feat["close"].loc[keep]
    open_ = feat["open"].loc[keep]

    sc = score.reindex(index=dates, columns=close.columns)
    if exclude is not None:
        ex = exclude.reindex(index=dates, columns=close.columns).fillna(True).astype(bool)
        sc = sc.where(~ex)
    live = close.notna() & open_.notna()
    sc = sc.where(live)

    px = close.values.astype("float64")
    op = open_.values.astype("float64")
    scv = sc.values.astype("float64")
    nd, nc = px.shape

    rebal_idx = list(range(offset, nd, rebal))
    rebal_set = set(rebal_idx)
    cash = capital
    hold = {}          # code_idx -> shares
    entry = {}         # code_idx -> 买入成本价（含滑点）
    trade_pnl = []     # 每笔平仓收益率（逐笔胜率分母）
    period_eq = []     # 每个调仓日的组合市值（期间胜率分母）
    equity = np.full(nd, np.nan)
    trades = 0
    prev_val = capital

    for di in range(nd):
        # 每日估值
        val = cash
        for ci, sh in hold.items():
            p = px[di, ci]
            val += sh * (p if np.isfinite(p) else 0.0)
        equity[di] = val

        if di not in rebal_set or di + 1 >= nd:
            continue
        # T 日收盘算分 → T+1 开盘成交
        row = scv[di]
        ok = np.isfinite(row)
        if ok.sum() < topn:
            continue
        idx = np.argsort(np.where(ok, row, np.inf))[:topn]
        targets = set(idx.tolist())
        period_eq.append(equity[di])

        # 先卖（不在目标里的）：T+1 开盘
        for ci in list(hold.keys()):
            if ci in targets:
                continue
            p = op[di + 1, ci]
            if not np.isfinite(p):
                p = px[di, ci]
            if not np.isfinite(p):     # 停牌且无有效价 → 留仓不卖
                continue
            sh = hold.pop(ci)
            gross = sh * p * (1 - slip)
            fee = max(gross * COMM_RATE, COMM_MIN) + gross * SELL_TAX
            cash += gross - fee
            trades += 1
            ec = entry.pop(ci, np.nan)
            if np.isfinite(ec) and ec > 0:
                trade_pnl.append((p * (1 - slip) * (1 - SELL_TAX)) / ec - 1.0)

        # 再买（等权目标）
        need = [ci for ci in targets if ci not in hold]
        if need and np.isfinite(cash) and cash > 0:
            slot = cash / len(need)
            for ci in need:
                p = op[di + 1, ci]
                if not np.isfinite(p) or p <= 0:
                    continue
                sh = int(slot / (p * (1 + slip)) / 100) * 100
                if sh < 100:
                    continue
                gross = sh * p * (1 + slip)
                fee = max(gross * COMM_RATE, COMM_MIN)
                if gross + fee > cash:
                    continue
                cash -= gross + fee
                hold[ci] = sh
                entry[ci] = p * (1 + slip)
                trades += 1

        if verbose and di % (rebal * 4) == 0:
            print(f"  di={di} {dates[di].date()} val={equity[di]:,.0f} hold={len(hold)}")

    eq = pd.Series(equity, index=dates)
    ret = eq.pct_change().dropna()
    years = (dates[-1] - dates[0]).days / 365.25
    total = eq.iloc[-1] / capital - 1
    ann = (1 + total) ** (1 / years) - 1 if years > 0 else np.nan
    sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else np.nan
    mdd = ((eq / eq.cummax()) - 1).min()
    by = eq.resample("YE").last().pct_change()
    if len(eq.resample("YE").last()) > 0:
        by.iloc[0] = eq.resample("YE").last().iloc[0] / capital - 1
    # ---- 三口径胜率（2026-09-15 补：原实现无胜率，验收面不完整）
    tp = np.asarray(trade_pnl, dtype=float)
    tp = tp[np.isfinite(tp)]
    pe = np.asarray(period_eq, dtype=float)
    per = pe[1:] / pe[:-1] - 1.0 if len(pe) > 1 else np.array([])
    per = per[np.isfinite(per)]
    wins, los = tp[tp > 0], tp[tp <= 0]
    byv = by.dropna()
    return dict(total=total, ann=ann, sharpe=sharpe, mdd=mdd, trades=trades,
                years=years, equity=eq, by_year=byv,
                win_rate_trade=float((tp > 0).mean()) if len(tp) else np.nan,
                win_rate_period=float((per > 0).mean()) if len(per) else np.nan,
                win_rate_year=float((byv > 0).mean()) if len(byv) else np.nan,
                n_closed=int(len(tp)), n_period=int(len(per)),
                avg_win=float(wins.mean()) if len(wins) else np.nan,
                avg_loss=float(los.mean()) if len(los) else np.nan,
                profit_factor=float(wins.sum() / abs(los.sum())) if len(los) and los.sum() != 0 else np.nan)


def bench(feat, code, start=None, end=None, capital=CAPITAL):
    """基准净值（buy&hold，前复权）。指数文件在仓库根（index_*.csv），个股/ETF 在 data_full。"""
    path = os.path.join(DATA, f"{code}.csv")
    if not os.path.exists(path):
        path = os.path.join(ROOT, f"{code}.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"基准文件缺失：{code}")
    df = pd.read_csv(path, dtype={"date": str})
    s = pd.Series(pd.to_numeric(df["close"], errors="coerce").values,
                  index=pd.to_datetime(df["date"])).sort_index()
    if start:
        s = s[s.index >= pd.Timestamp(start)]
    if end:
        s = s[s.index <= pd.Timestamp(end)]
    eq = s / s.iloc[0] * capital
    years = (s.index[-1] - s.index[0]).days / 365.25
    ret = eq.pct_change().dropna()
    total = eq.iloc[-1] / capital - 1
    return dict(total=total, ann=(1 + total) ** (1 / years) - 1 if years > 0 else np.nan,
                sharpe=ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else np.nan,
                mdd=((eq / eq.cummax()) - 1).min(), equity=eq, years=years)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if cmd == "build":
        build_features()
    elif cmd == "smoke":
        feat = load_features()
        print("[smoke] 构造 TTM 股息率…")
        dy = ttm_dividend_yield(feat)
        print(f"[smoke] dy_ttm 覆盖 {dy.notna().sum().sum():,} 格，"
              f"最新日有效 {dy.iloc[-1].notna().sum()} 只")
        ex = st_mask(feat)
        sc = -dy          # 小者优先 → 股息率大者优先
        for tag, mask in [("排ST/退", ex), ("仅排退", st_tui_mask(feat))]:
            r = run(feat, sc, rebal=250, topn=10, slip=0.002, exclude=mask)
            print(f"[smoke] {tag} rebal250 Top10: total={r['total']:.2%} ann={r['ann']:.2%} "
                  f"sharpe={r['sharpe']:.3f} mdd={r['mdd']:.2%} trades={r['trades']} "
                  f"years={r['years']:.1f}")
            print("        分年:", {str(k.year): f"{v:.1%}" for k, v in r["by_year"].items()})
        for c in ["index_000300", "sz000922", "sz000919", "sh510880"]:
            try:
                b = bench(feat, c)
                print(f"[bench] {c}: total={b['total']:.2%} ann={b['ann']:.2%} "
                      f"sharpe={b['sharpe']:.3f} mdd={b['mdd']:.2%}")
            except Exception as e:
                print(f"[bench] {c} 失败 {type(e).__name__}")
