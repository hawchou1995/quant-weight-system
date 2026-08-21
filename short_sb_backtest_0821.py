# -*- coding: utf-8 -*-
"""
短线体系 阶段寻底注入回测（2026-08-21，用户任务②：短线优化可能性评估）
=====================================================================
背景：中长线 v6 引擎中阶段寻底超卖用法已通过（全样本+两段样本外均 PASS）。
短线体系（short_engine.short_score）四维=动量30(-mom20反转)/量价25(vp+vr5)/通道25(dnc)/波动20(低波)
→ **无任何超卖技术指标维度**（无 RSI/WR/CCI/KDJ），只有 -mom20 一条"伪反转"。
本回测：将阶段寻底（寻底=2*RSI5+ADX5-WR10，超卖=寻底<0）注入短线打分，
对比生产基线（T10/H10/S55·反转+MA5·20bps）看是否有增量。

验收（沿用中长线口径）：收益≥基线 且 回撤≤基线+2pct 且 换手不显著恶化。
"""
import os
import sys
import time
import json
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import short_engine as S

# ---------------- 阶段寻底开关 ----------------
USE_SB = False
SB_BONUS = 8.0


def _tdx_sma(s, n):
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


# ---------------- patch short_factors：加 sb 列 ----------------
_orig_sf = S.short_factors


def sf_patched(df):
    d = _orig_sf(df)
    c, h, l = d["close"], d["high"], d["low"]
    wan = c.shift(1)
    up = (c - wan).clip(lower=0)
    dn = (c - wan).abs()
    rsi5 = _tdx_sma(up, 5) / _tdx_sma(dn, 5).replace(0, np.nan) * 100
    tr = pd.concat([h - l, (h - wan).abs(), (l - wan).abs()], axis=1).max(axis=1)
    llu = h - h.shift(1)
    ce = l.shift(1) - l
    dmp = pd.Series(np.where((llu > 0) & (llu > ce), llu, 0.0), index=d.index).rolling(10).sum()
    dmm = pd.Series(np.where((ce > 0) & (ce > llu), ce, 0.0), index=d.index).rolling(10).sum()
    pdi = dmp * 100 / tr.replace(0, np.nan)
    mdi = dmm * 100 / tr.replace(0, np.nan)
    adx5 = (mdi - pdi).abs() / (mdi + pdi).replace(0, np.nan) * 100
    adx5 = adx5.rolling(5).mean()
    wr10 = 100 * (h.rolling(10).max() - c) / (h.rolling(10).max() - l.rolling(10).min()).replace(0, np.nan)
    d["sb"] = (2 * rsi5 + adx5 - wr10).fillna(50.0)
    return d


S.short_factors = sf_patched

# ---------------- patch short_score：超卖加分 ----------------
_orig_ss = S.short_score


def ss_patched(r, reversal=False):
    s = _orig_ss(r, reversal=reversal)
    if USE_SB:
        sb = float(r.get("sb", np.nan))
        if not np.isnan(sb) and sb < 0:
            s += SB_BONUS
    return s


S.short_score = ss_patched


def run_exp(name, kw, bonus=None):
    global USE_SB, SB_BONUS
    old = (USE_SB, SB_BONUS)
    if bonus is None:
        USE_SB, SB_BONUS = False, 0.0
    else:
        USE_SB, SB_BONUS = True, bonus
    t0 = time.time()
    try:
        eq, tr = S.run_short(pool, **kw)
    finally:
        (USE_SB, SB_BONUS) = old
    s = S.V.summary(eq, tr)
    print(f"  {name:24s} +{s['total_return_pct']:7.2f}% / 回撤 {s['max_drawdown_pct']:6.2f}% / "
          f"夏普 {s['sharpe']} / 胜率 {s['win_rate_pct']}% / {s['total_trades']} 笔 "
          f"({time.time()-t0:.0f}s)", flush=True)
    return {"name": name, **{k: s[k] for k in
            ("total_return_pct", "annual_return_pct", "max_drawdown_pct", "sharpe",
             "win_rate_pct", "total_trades")}}


if __name__ == "__main__":
    pool = S.load_stock_pool()
    print(f"短线全市场池 {len(pool)} 只加载完成", flush=True)
    kw = dict(top_n=10, hold_days=10, score_min=55, ma5_exit=True, take_profit=0.0,
              stop_loss=0.0, reversal=True, fund_mode=False, slippage_bps=20)

    experiments = [
        ("基线 反转+MA5（复现）", dict(kw), None),
        ("阶段寻底 超卖+5", dict(kw), 5.0),
        ("阶段寻底 超卖+8", dict(kw), 8.0),
        ("阶段寻底 超卖+12", dict(kw), 12.0),
    ]
    rows = []
    for name, k, bonus in experiments:
        rows.append(run_exp(name, k, bonus))

    base = rows[0]
    print("\n=== 汇总对比（相对短线基线）===", flush=True)
    for r in rows[1:]:
        d_ret = r["total_return_pct"] - base["total_return_pct"]
        d_dd = r["max_drawdown_pct"] - base["max_drawdown_pct"]
        flag = "PASS" if (d_ret > 0 and d_dd <= 2.0) else ("MARGINAL" if d_ret > 0 else "FAIL")
        print(f"  {r['name']:24s} Δ收益 {d_ret:+6.2f}  Δ回撤 {d_dd:+5.2f} → {flag}", flush=True)

    out = {"generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
           "method": "阶段寻底（寻底=2*RSI5+ADX5-WR10）超卖<0 加分注入短线 short_score",
           "pool": f"{len(pool)} 只（data_full 全市场）",
           "baseline": "T10/H10/S55 · 反转+MA5 · 20bps（生产口径）",
           "experiments": rows}
    with open(os.path.join(BASE, "short_sb_out_0821", "short_sb_results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n已输出 short_sb_out_0821/short_sb_results.json", flush=True)
