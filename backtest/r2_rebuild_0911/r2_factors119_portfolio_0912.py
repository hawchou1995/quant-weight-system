# -*- coding: utf-8 -*-
"""r2 · 119 篇排序因子族 → 主板组合级网格回测（2026-09-12）
================================================================
Grill R1 根决策：素材驱动、分散等权 N=10~20、hold=20/40/60 网格、主板。
分拣来源：r2_rebuild_0911/catalog119_factors.json（242 信号中可直接实现的排序因子族）。

预注册因子集（4 族，源自文章 3/31/43/49/82/101/105 的可日线化核心）：
  F1 回归动量×R²  momr2_W = (exp(slope*250)-1)*R²，W∈{60,120} 对数收盘对时间 OLS（文章3/43/101）
  F2 低价动量     91 日涨幅，仅 close<5 元（文章49）
  F3 趋势斜率     20 日收盘 OLS 斜率（文章82，>0 才入选）
  F4 经典动量     mom_12_1（12-1月，对照组，v8_selector 既有）
引擎：v9_auto.run_auto（T+1 开盘、佣金/印花税内建、amt20≥5e6、价≥2、主板 perm），
     V.score_row 注入因子分；门控=MA200（现行生产语义，门关=低位稳拿）。
臂位：4 族 × hold∈{20,40,60} × N∈{10,20} = 24 臂 + 生产四因子对照 1 臂 = 25 臂（如实入审计）。
成本敏感性留给幸存者（滑点 0 基线 + 幸存者补 20bps）。
输出：r2_rebuild_0911/factors119_portfolio.json / factors119_daily_returns.csv
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
R2 = BASE / "backtest" / "r2_rebuild_0911"
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "backtest"))

import v8_selector as V  # noqa: E402
import v9_auto  # noqa: E402

HOLDS = (20, 40, 60)
NS = (10, 20)
SLIP = 0


def _roll_reg(y: np.ndarray, W: int):
    """滚动 OLS：返回 (slope_per_bar, corr)，长度同 y，前 W-1 为 NaN"""
    from numpy.lib.stride_tricks import sliding_window_view
    t = np.arange(W, dtype=float)
    tm = t.mean()
    tvar = ((t - tm) ** 2).sum()          # Σ(t-tm)²
    st = np.sqrt(tvar / W)                # t 的总体标准差
    out_b = np.full(len(y), np.nan)
    out_c = np.full(len(y), np.nan)
    if len(y) < W:
        return out_b, out_c
    win = sliding_window_view(y, W)       # (n-W+1, W)
    finite = np.isfinite(win).all(axis=1)
    cov = np.full(win.shape[0], np.nan)
    sy = np.full(win.shape[0], np.nan)
    if finite.any():
        w = win[finite]
        cov[finite] = (w @ t) / W - tm * w.mean(axis=1)
        sy[finite] = w.std(axis=1, ddof=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        b = W * cov / tvar
        corr = cov / (st * sy)
    out_b[W - 1:] = b
    out_c[W - 1:] = corr
    return out_b, out_c


def add_factor_columns(pool, codes):
    t0 = time.time()
    for code in codes:
        df = pool[code]
        c = df["close"].to_numpy(float)
        lr = np.log(c)
        for W in (60, 120):
            b, corr = _roll_reg(lr, W)
            with np.errstate(invalid="ignore"):
                df[f"f_momr2_{W}"] = (np.exp(np.clip(b * 250, -50, 50)) - 1) * corr ** 2
        c_s = pd.Series(c)
        # ⚠ 必须落 ndarray：RangeIndex Series 赋给 DatetimeIndex df 会整列对齐成 NaN
        mom91 = (c_s / c_s.shift(91) - 1).to_numpy()
        mom91 = np.where(np.isfinite(mom91) & (c < 5.0), mom91, np.nan)
        df["f_lowmom91"] = mom91
        b20, _ = _roll_reg(c, 20)
        df["f_slope20"] = b20
    print(f"[factors] 因子列注入 {len(codes)} 只 ({time.time()-t0:.0f}s)", flush=True)


def make_score(col):
    def _sr(r):
        v = r.get(col, np.nan)
        if col == "f4_mom121":
            v = r.get("mom_12_1", np.nan)
        if pd.isna(v):
            return -1e9
        return float(v)
    return _sr


def run_arm(pool, score_col, hold, n, name):
    orig = V.score_row
    V.score_row = make_score(score_col)
    try:
        t = time.time()
        eq, tr = v9_auto.run_auto(top_n=n, hold_days=hold, pool_size=max(25, n),
                                  mom_min=-1.0, score_min=0, stop_loss=0.08,
                                  ma_window=200, perm="main", slippage_bps=SLIP)
        el = time.time() - t
    finally:
        V.score_row = orig
    s = V.summary(eq, tr)
    rec = {"name": name, "total_return_pct": round(s["total_return_pct"], 2),
           "annual_return_pct": round(s["annual_return_pct"], 2),
           "max_drawdown_pct": round(s["max_drawdown_pct"], 2),
           "sharpe": round(s["sharpe"], 3), "win_rate_pct": round(s["win_rate_pct"], 1),
           "n_trades": s["total_trades"], "runtime_sec": round(el, 1)}
    print(f"  [{name}] {rec['total_return_pct']}% | 夏普 {rec['sharpe']} | "
          f"回撤 {rec['max_drawdown_pct']}% | {rec['n_trades']}笔", flush=True)
    e = pd.to_numeric(eq.iloc[:, 0], errors="coerce").pct_change().fillna(0)
    e.index = pd.to_datetime(e.index)
    return rec, e


if __name__ == "__main__":
    import os
    t0 = time.time()
    # ⚠ v9_auto 在 import 时已自持 pool_all（独立加载）——因子列必须注入这一份
    pool = v9_auto.pool_all
    main_codes = [c for c in pool if c.startswith(("sh60", "sz00"))]
    add_factor_columns(pool, main_codes)

    ONLY = os.environ.get("R2_ONLY", "").strip()
    arms = [("F0_prod四因子对照", "__prod__", None)] if not ONLY else []
    for col, fam in [("f_momr2_60", "F1_momr2W60"), ("f_momr2_120", "F1_momr2W120"),
                     ("f_lowmom91", "F2_lowmom91"), ("f_slope20", "F3_slope20"),
                     ("f4_mom121", "F4_mom121")]:
        if ONLY and not fam.startswith(ONLY):
            continue
        for h in HOLDS:
            for n in NS:
                arms.append((f"{fam}_h{h}_n{n}", col, (h, n)))
    for col, fam in [("f_momr2_60", "F1_momr2W60"), ("f_momr2_120", "F1_momr2W120"),
                     ("f_lowmom91", "F2_lowmom91"), ("f_slope20", "F3_slope20"),
                     ("f4_mom121", "F4_mom121")]:
        for h in HOLDS:
            for n in NS:
                arms.append((f"{fam}_h{h}_n{n}", col, (h, n)))

    arms_daily = {}
    results = []
    for name, col, cfg in arms:
        if cfg is None:  # 生产四因子对照：默认 score_row
            t = time.time()
            eq, tr = v9_auto.run_auto(top_n=3, hold_days=21, pool_size=25,
                                      mom_min=0.20, score_min=60, stop_loss=0.08,
                                      ma_window=200, perm="main", slippage_bps=SLIP)
            s = V.summary(eq, tr)
            rec = {"name": name, "total_return_pct": round(s["total_return_pct"], 2),
                   "annual_return_pct": round(s["annual_return_pct"], 2),
                   "max_drawdown_pct": round(s["max_drawdown_pct"], 2),
                   "sharpe": round(s["sharpe"], 3), "win_rate_pct": round(s["win_rate_pct"], 1),
                   "n_trades": s["total_trades"], "runtime_sec": round(time.time() - t, 1)}
            print(f"  [{name}] {rec['total_return_pct']}% | 夏普 {rec['sharpe']}", flush=True)
            e = pd.to_numeric(eq.iloc[:, 0], errors="coerce").pct_change().fillna(0)
            e.index = pd.to_datetime(e.index)
        else:
            h, n = cfg
            rec, e = run_arm(pool, col, h, n, name)
        arms_daily[name] = e
        results.append(rec)
        json.dump(results, open(R2 / "factors119_portfolio.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

    mat = pd.DataFrame(arms_daily)
    mat.index.name = "date"
    mat.to_csv(R2 / "factors119_daily_returns.csv", encoding="utf-8")
    print(f"\n[done] {len(results)} 臂 {time.time()-t0:.0f}s → factors119_portfolio.json", flush=True)
