# -*- coding: utf-8 -*-
"""QuantZone Barra 风格因子 × 主板月度轮动回测（2021 起，窗口与 E0/FB3 一致）
单因子双向（multi-trial 申报）+ 经济先验方向复合分（聪明的β 组合）。
审计：Barra 日频因子 T 日可得（ADR-0007 ✓）；相位扫描（ADR-0006 ✓）。"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
QZ = BASE / "data_fundamental" / "quantzone"
START = pd.Timestamp("2021-01-04")
t0 = time.time()

FACTORS = ["risk_fac_book_to_price", "risk_fac_earnings_yield", "risk_fac_profitability",
           "risk_fac_earnings_quality", "risk_fac_momentum", "risk_fac_residual_volatility",
           "risk_fac_size", "risk_fac_growth"]
# 经济先验方向（+1 做多高值 / -1 做多低值）
DIRS = {"risk_fac_book_to_price": 1, "risk_fac_earnings_yield": 1, "risk_fac_profitability": 1,
        "risk_fac_earnings_quality": 1, "risk_fac_momentum": 1, "risk_fac_residual_volatility": -1,
        "risk_fac_size": -1, "risk_fac_growth": 1}

# ---- 因子截面（月度最后交易日）----
month_ends = {}
for fac in FACTORS:
    f = QZ / f"{fac}.csv"
    if not f.exists():
        print(f"[missing] {fac}")
        continue
    d = pd.read_csv(f, dtype={"ukey": str})
    d["date"] = pd.to_datetime(d["date"])
    d = d[d["date"] >= START]
    d = d[d["ukey"].str.startswith(("60", "00"))]  # 主板
    me = d.groupby(d["date"].dt.to_period("M"))["date"].max()
    d_me = d[d["date"].isin(set(me))]
    month_ends[fac] = d_me.set_index(["date", "ukey"])["value"]
    print(f"[{fac}] {d['ukey'].nunique()} 票 月截面 {len(d_me):,} 行 ({time.time()-t0:.0f}s)", flush=True)

facs = [f for f in FACTORS if f in month_ends]
panel = pd.concat(month_ends, names=["factor", "date", "ukey"])
wide = panel.unstack("factor")
months = sorted(pd.Index(wide.index.get_level_values("date")).unique())
codes_u = sorted(set(wide.index.get_level_values("ukey")))
cix = {c: i for i, c in enumerate(codes_u)}
F = np.full((len(months), len(codes_u), len(facs)), np.nan)
for mi, m in enumerate(months):
    sub = wide.loc[m]
    for fi, fac in enumerate(facs):
        if fac in sub.columns:
            col = sub[fac]
            jj = col.index.map(cix).to_numpy()
            F[mi, jj[np.isfinite(jj)], fi] = col.to_numpy()[np.isfinite(jj)]
NS_ = len(codes_u)
print(f"[panel] {len(months)} 月 × {NS_} 票 × {len(facs)} 因子 ({time.time()-t0:.0f}s)", flush=True)

# ---- 价格矩阵 ----
day_ts = pd.bdate_range(months[0], months[-1])
OPEN = np.full((len(day_ts), NS_), np.nan)
CLOSE = np.full((len(day_ts), NS_), np.nan)
FIRST = np.full(NS_, -1, dtype=int)
for f in sorted((BASE / "data_full").glob("*.csv")):
    c = f.stem
    if not (c.startswith("sh60") or c.startswith("sz00")):
        continue
    code = c[2:]
    if code not in cix:
        continue
    j = cix[code]
    d = pd.read_csv(f, usecols=["date", "open", "close"], dtype={"date": str})
    d["date"] = pd.to_datetime(d["date"])
    d = d.set_index("date").sort_index().reindex(day_ts)
    OPEN[:, j] = d["open"].to_numpy()
    CLOSE[:, j] = d["close"].to_numpy()
    fv = d["close"].first_valid_index()
    if fv is not None:
        FIRST[j] = day_ts.get_loc(fv)
m_end_idx = {m: int(np.max(np.where(day_ts <= m)[0])) for m in months}
print(f"[px] {len(day_ts)} 日 ({time.time()-t0:.0f}s)", flush=True)


def zsc(a):
    m, s = np.nanmean(a), np.nanstd(a)
    return (a - m) / s if s > 0 else np.zeros_like(a)


def run(directions, rebal=20, slip=0.002, offset=0, topk=10):
    cash, eq, hold, reasons = 1e6, [], {}, {}
    month_ptr = -1
    for di in range(len(day_ts)):
        d = day_ts[di]
        for code in [c for c, h in hold.items() if h.get("sell_flag")]:
            j = cix[code]
            if np.isnan(OPEN[di, j]) or OPEN[di, j] <= 0:
                continue
            px_o = OPEN[di, j] * (1 - slip)
            h = hold.pop(code)
            sh = h["sh"]
            cash += sh * px_o - max(sh * px_o * 0.00025, 5) - sh * px_o * 0.001
        if d.month != day_ts[max(0, di - 1)].month or di == 0:
            month_ptr += 1
        mi = min(month_ptr, len(months) - 1)
        if di > 250 and di % rebal == offset:
            Fm = F[mi]
            comp = np.zeros(NS_)
            for fi, fac in enumerate(facs):
                dv = directions[fac] if isinstance(directions, dict) else directions
                comp = comp + np.nan_to_num(zsc(Fm[:, fi]) * dv, nan=0)
            valid = np.isfinite(Fm).any(axis=1)
            comp = np.where(valid, comp, np.nan)
            ok = np.where(np.isfinite(comp))[0]
            ok = [j for j in ok[np.argsort(-comp[ok])][:topk]
                  if np.isfinite(OPEN[di, j]) and OPEN[di, j] >= 2 and di - FIRST[j] >= 180]
            tgt = {codes_u[j] for j in ok}
            for code, h in hold.items():
                if code not in tgt and not h.get("sell_flag"):
                    h["sell_flag"] = True
            pv = cash + sum(h["sh"] * (CLOSE[di, cix[c]] if np.isfinite(CLOSE[di, cix[c]]) else h["ep"]) for c, h in hold.items())
            for j in ok:
                code = codes_u[j]
                if code in hold:
                    continue
                px_o = OPEN[di, j]
                pc = CLOSE[di - 1, j]
                if not np.isfinite(px_o) or not np.isfinite(pc) or px_o >= pc * 1.097:
                    continue
                nl = int((min(pv / topk, cash) - 5) / (px_o * 100 * 1.00025))
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
    return {"total": tot * 100, "ann": ((1 + tot) ** (252 / max(1, len(eq))) - 1) * 100,
            "mdd": ((eq / np.maximum.accumulate(eq) - 1).min()) * 100,
            "sharpe": float(np.nanmean(r) / np.nanstd(r) * np.sqrt(252)) if np.nanstd(r) > 0 else 0}


if __name__ == "__main__":
    out = {"_n_trials": len(facs) * 2 + 1 + 5}
    for fac in facs:
        for dv, tag in ((1, "多高值"), (-1, "多低值")):
            r = run({f: (dv if f == fac else 0) for f in facs})
            out[f"{fac}_{tag}"] = r
            print(f"[{fac.replace('risk_fac_', '')} {tag}] {r['total']:.1f}% | 年化 {r['ann']:.1f}% | 回撤 {r['mdd']:.1f}% | 夏普 {r['sharpe']:.3f}", flush=True)
    rc = run(DIRS)
    out["复合_聪明的β"] = rc
    print(f"[复合 聪明的β] {rc['total']:.1f}% | 年化 {rc['ann']:.1f}% | 回撤 {rc['mdd']:.1f}% | 夏普 {rc['sharpe']:.3f}", flush=True)
    ph = [run(DIRS, offset=o)["total"] for o in (2, 6, 10, 14, 18)]
    out["_phase"] = ph
    print(f"[相位 复合] off0 {rc['total']:.1f}% | 中位 {np.median(ph):.1f}% | 区间 [{min(ph):.0f},{max(ph):.0f}]", flush=True)
    json.dump(out, open(BASE / "backtest" / "qz_barra_0913.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
    print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
