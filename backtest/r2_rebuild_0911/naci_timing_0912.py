# -*- coding: utf-8 -*-
"""纳次H 情绪沸点广度 · 独立择时线验证（2026-09-12）
================================================================
Grill R1：纳次H 独立走择时线。口径：HS300 为主板/市场贝塔代理（项目统一指数），
T 日收盘判定 → T+1 收盘执行（指数不可交易，收盘近似，仅作信号质量评估非实盘口径）。
臂位（预注册 3 臂）：
  T0 买入持有对照
  T1 breadth_ma3 > expanding q90 → 空仓（低于即回场）
  T2 同上 q95
成本：单边 0.1%（含冲击的保守近似，仅指数择时口径）。
输出：naci_timing_0912.json + naci_timing_0912.png
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BASE = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
OUT = BASE / "backtest" / "r2_rebuild_0911"
OUT.mkdir(parents=True, exist_ok=True)

idx = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
idx["date"] = pd.to_datetime(idx["date"])
idx = idx[idx["date"] >= "2016-01-04"].set_index("date").sort_index()
px = idx["close"]
ret = px.pct_change().fillna(0)

bd = pd.read_csv(BASE / "backtest" / "naci_sentiment_0911_out" / "breadth_daily.csv",
                 parse_dates=["date"]).set_index("date")
b3 = bd["breadth"].reindex(idx.index).ffill().rolling(3, min_periods=3).mean()

COST = 0.001


def run_gate(q, name):
    thr = b3.expanding(min_periods=250).quantile(q)
    in_mkt = (b3 <= thr).fillna(True)
    pos = in_mkt.shift(1).fillna(False).astype(float)   # T 收盘判定 T+1 生效
    turn = pos.diff().abs().fillna(0)
    strat = pos * ret - turn * COST
    eq = (1 + strat).cumprod()
    yrs = eq.groupby(eq.index.year).last() / eq.groupby(eq.index.year).first() - 1
    total = eq.iloc[-1] - 1
    ann = (1 + total) ** (252 / len(eq)) - 1
    dd = (eq / eq.cummax() - 1).min()
    sharpe = strat.mean() / strat.std() * np.sqrt(252) if strat.std() > 0 else 0
    days_out = int((~in_mkt).sum())
    print(f"  [{name}] 总 {total*100:.1f}% | 年化 {ann*100:.2f}% | 回撤 {dd*100:.1f}% | "
          f"夏普 {sharpe:.2f} | 空仓 {days_out}天 | 换手成本 {turn.sum()*COST*100:.1f}pp", flush=True)
    return {"name": name, "q": q, "total_pct": round(total * 100, 2),
            "ann_pct": round(ann * 100, 2), "mdd_pct": round(dd * 100, 1),
            "sharpe": round(float(sharpe), 3), "days_out": days_out,
            "yearly": {str(k): round(v * 100, 2) for k, v in yrs.items()}}


if __name__ == "__main__":
    t0 = time.time()
    res = []
    total = (px.iloc[-1] / px.iloc[0] - 1) * 100
    print(f"  [T0 B&H] 总 {total:.1f}%", flush=True)
    res.append({"name": "T0_BH", "q": None, "total_pct": round(total, 2)})
    for q in (0.90, 0.95):
        res.append(run_gate(q, f"T_q{int(q*100)}"))

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                             gridspec_kw={"height_ratios": [2, 1]})
    ax = axes[0]
    ax.plot(px.index, px / px.iloc[0], label="HS300 B&H", color="#888", lw=1.2)
    for q in (0.90, 0.95):
        thr = b3.expanding(min_periods=250).quantile(q)
        in_mkt = (b3 <= thr).fillna(True)
        pos = in_mkt.shift(1).fillna(False).astype(float)
        strat = pos * ret - pos.diff().abs().fillna(0) * COST
        eq = (1 + strat).cumprod()
        ax.plot(eq.index, eq, label=f"沸点闸门 q{int(q*100)}", lw=1.1)
    ax.set_yscale("log")
    ax.set_title("纳次H 情绪沸点广度择时 vs HS300 买入持有（对数，T+1 收盘近似，单边0.1%）")
    ax.legend(); ax.grid(alpha=0.3)
    ax = axes[1]
    ax.plot(b3.index, b3 * 100, lw=0.7, color="#1f77b4")
    thr95 = b3.expanding(min_periods=250).quantile(0.95)
    ax.plot(thr95.index, thr95 * 100, lw=0.8, color="#ff7f0e", label="expanding q95")
    ax.set_ylabel("广度 %"); ax.legend(); ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT / "naci_timing_0912.png", dpi=130)
    json.dump({"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "arms": res,
               "cost": COST, "note": "指数收盘近似执行，仅评估信号质量"},
              open(OUT / "naci_timing_0912.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"[done] {time.time()-t0:.0f}s → naci_timing_0912.json", flush=True)
