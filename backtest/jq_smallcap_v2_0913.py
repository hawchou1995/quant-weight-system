# -*- coding: utf-8 -*-
"""聚宽国九小市值 · 主板移植版 v2（东财估值数据直读，窗口 2021-01-04 起）
域：总市值 10~100 亿（聚宽 valuation.market_cap 口径）· 排序：总市值升序 Top10 等权
调仓：周频(5日)/月频(20日) × 滑点 20/50bps；成本：佣金 2.5bp+印税 10bp+最低 5 元
退出：调仓全换（忠实移植）；附加 LLV20 阶梯止损变体
审计：排序键 total_mv 为 T 日收盘口径（ADR-0007 ✓）；相位扫描（ADR-0006 闸）"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
VAL = BASE / "data_fundamental" / "val_em" / "val_em_all.csv"
OUTJ = BASE / "backtest" / "jq_smallcap_0913.json"
START = pd.Timestamp("2021-01-04")

t0 = time.time()
v = pd.read_csv(VAL, dtype={"code": str})
v["date"] = pd.to_datetime(v["date"])
v = v[v["date"] >= START]
v["mv_yi"] = v["total_mv"] / 1e8
v = v[(v["mv_yi"] >= 10) & (v["mv_yi"] <= 100)]
print(f"[域] {v['code'].nunique()} 票 {len(v):,} 行 ({time.time()-t0:.0f}s)", flush=True)

# data_full 前复权价（收益口径）+ 上市首日（新股过滤）
px = {}
for f in sorted((BASE / "data_full").glob("*.csv")):
    c = f.stem
    if not (c.startswith("sh60") or c.startswith("sz00")):
        continue
    code = c[2:]  # 纯 6 位（第六次前缀坑修复）
    d = pd.read_csv(f, usecols=["date", "open", "close"], dtype={"date": str})
    d["date"] = pd.to_datetime(d["date"])
    px[code] = d.set_index("date").sort_index()
ALL_CODES = sorted(v["code"].unique())
DAYS = np.array(sorted(v["date"].unique()))
print(f"[days] {len(DAYS)} ({time.time()-t0:.0f}s)", flush=True)

# 矩阵
cix = {c: i for i, c in enumerate(ALL_CODES)}
fix = {d: i for i, d in enumerate(DAYS)}
ND, NS = len(DAYS), len(ALL_CODES)
MV = np.full((ND, NS), np.nan)
OPEN = np.full((ND, NS), np.nan)
CLOSE = np.full((ND, NS), np.nan)
FIRST = np.full(NS, -1, dtype=int)
sub = v[["code", "date", "mv_yi"]]
i_arr = sub["date"].map(fix).to_numpy()
j_arr = sub["code"].map(cix).to_numpy()
MV[i_arr, j_arr] = sub["mv_yi"].to_numpy()
for code in ALL_CODES:
    j = cix[code]
    p = px[code].reindex(pd.DatetimeIndex(DAYS))
    OPEN[:, j] = p["open"].to_numpy()
    CLOSE[:, j] = p["close"].to_numpy()
    first_idx = p["close"].first_valid_index()
    if first_idx is not None:
        FIRST[j] = fix[first_idx]
print(f"[matrix] {ND}×{NS} ({time.time()-t0:.0f}s)", flush=True)


def run(rebal, slip, stop_llv=None, offset=0):
    cash, eq, trades, reasons = 1e6, [], [], {}
    hold = {}
    for di in range(ND):
        # 昨日挂单 → 今日开盘成交
        for code in [c for c, h in hold.items() if h.get("sell_flag")]:
            j = cix[code]
            if np.isnan(OPEN[di, j]) or OPEN[di, j] <= 0:
                continue
            px_o = OPEN[di, j] * (1 - slip)
            sh = hold.pop(code)["sh"]
            cash += sh * px_o - max(sh * px_o * 0.00025, 5) - sh * px_o * 0.001
            ep = hold.get(code, {}).get("ep", px_o)
            trades.append(0)
            rsn = hold.get(code, {}).get("reason") or "调仓"
            reasons[rsn] = reasons.get(rsn, 0) + 1
        # 收盘检查（止损挂单）
        if stop_llv is not None:
            for code, h in hold.items():
                if h.get("sell_flag"):
                    continue
                j = cix[code]
                c = CLOSE[di, j]
                if not np.isfinite(c):
                    continue
                k0 = max(0, di - stop_llv)
                llv = np.nanmin(CLOSE[k0:di, j]) if di > 0 else np.nan
                if np.isfinite(llv) and c < llv:
                    h["sell_flag"] = True
                    h["reason"] = f"LLV{stop_llv}止损"
        # 调仓信号
        if di % rebal == offset and di > 250:
            row = MV[di]
            ok = np.where(np.isfinite(row))[0]
            ok = [j for j in ok[np.argsort(row[ok])][:10]
                  if di - FIRST[j] >= 180 and np.isfinite(OPEN[di, j]) and OPEN[di, j] >= 2]
            tgt = {ALL_CODES[j] for j in ok}
            for code, h in hold.items():
                if code not in tgt and not h.get("sell_flag"):
                    h["sell_flag"] = True
                    h["reason"] = "调仓"
            pv = cash + sum(h["sh"] * (CLOSE[di, cix[c]] if np.isfinite(CLOSE[di, cix[c]]) else h["ep"]) for c, h in hold.items())
            for j in ok:
                code = ALL_CODES[j]
                if code in hold:
                    continue
                px_o = OPEN[di, j]
                prev_close = CLOSE[di - 1, j]
                if not np.isfinite(px_o) or px_o < 2 or not np.isfinite(prev_close) or px_o >= prev_close * 1.097:
                    continue
                budget = min(pv / 10, cash)
                nl = int((budget - 5) / (px_o * 100 * 1.00025))
                if nl < 1:
                    continue
                sh = nl * 100
                cost = sh * px_o * (1 + slip) + max(sh * px_o * 0.00025, 5)
                if cost > cash:
                    continue
                cash -= cost
                hold[code] = {"sh": sh, "ep": px_o * (1 + slip), "sell_flag": False}
        pv = cash + sum(h["sh"] * (CLOSE[di, cix[c]] if np.isfinite(CLOSE[di, cix[c]]) else h["ep"]) for c, h in hold.items())
        eq.append(pv)
    eq = np.array(eq)
    r = np.diff(eq) / eq[:-1]
    tot = eq[-1] / 1e6 - 1
    ann = (1 + tot) ** (252 / max(1, len(eq))) - 1
    return {"total": tot * 100, "ann": ann * 100, "mdd": ((eq / np.maximum.accumulate(eq) - 1).min()) * 100,
            "sharpe": float(np.nanmean(r) / np.nanstd(r) * np.sqrt(252)) if np.nanstd(r) > 0 else 0,
            "reasons": reasons}


if __name__ == "__main__":
    out = {}
    for rebal, tag in ((5, "周频"), (20, "月频")):
        for slip in (0.002, 0.005):
            r = run(rebal, slip)
            out[f"{tag}_slip{int(slip*1e4)}"] = r
            print(f"[{tag} slip{int(slip*1e4)}bps] {r['total']:.1f}% | 年化 {r['ann']:.1f}% | 回撤 {r['mdd']:.1f}% | 夏普 {r['sharpe']:.3f}", flush=True)
    # 相位审计（月频 slip20，6 相位）
    ph = [run(20, 0.002, offset=o)["total"] for o in (0, 4, 8, 12, 16)]
    out["_phase_monthly_slip20"] = ph
    print(f"[相位 月频slip20] off0 {ph[0]:.1f}% | 中位 {np.median(ph):.1f}% | 区间 [{min(ph):.0f},{max(ph):.0f}]", flush=True)
    r = run(20, 0.002, stop_llv=20)
    out["月频_slip20_LLV20止损"] = r
    print(f"[月频+LLV20止损] {r['total']:.1f}% | 回撤 {r['mdd']:.1f}% | 夏普 {r['sharpe']:.3f}", flush=True)
    # 分年度（月频 slip20）
    r0 = run(20, 0.002)
    json.dump(out, open(OUTJ, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
    print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
