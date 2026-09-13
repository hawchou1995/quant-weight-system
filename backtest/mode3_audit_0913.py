# -*- coding: utf-8 -*-
"""模式三（市值+趋势过滤）投产前审计套件：
A. MA 参数敏感性网格（10/15/20/30/40/50）——参数过拟合检验
B. 域内安慰剂：10-100 亿域随机 10 只 × 500 次（域基线漂移）
C. 滑点 30bps + 2026 崩塌段行为 + 与 FB3-H20 月收益相关性"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
VAL = BASE / "data_fundamental" / "val_em" / "val_em_all.csv"
START = pd.Timestamp("2021-01-04")
t0 = time.time()

v = pd.read_csv(VAL, dtype={"code": str})
v["date"] = pd.to_datetime(v["date"])
v = v[v["date"] >= START].copy()
v["mv_yi"] = v["total_mv"] / 1e8
v = v[(v["mv_yi"] >= 10) & (v["mv_yi"] <= 100)]
codes_u = sorted(v["code"].unique())
cix = {c: i for i, c in enumerate(codes_u)}
DAYS = np.array(sorted(v["date"].unique()))
day_ts = pd.DatetimeIndex(DAYS)
ND, NS = len(DAYS), len(codes_u)
MV = np.full((ND, NS), np.nan)
sub = v[["code", "date", "mv_yi"]]
MV[sub["date"].map({d: i for i, d in enumerate(DAYS)}).to_numpy(),
   sub["code"].map(cix).to_numpy()] = sub["mv_yi"].to_numpy()

OPEN = np.full((ND, NS), np.nan)
CLOSE = np.full((ND, NS), np.nan)
AMT20 = np.full((ND, NS), np.nan)
FIRST = np.full(NS, -1, dtype=int)
px_close = {}
for f in sorted((BASE / "data_full").glob("*.csv")):
    c = f.stem
    if not (c.startswith("sh60") or c.startswith("sz00")):
        continue
    code = c[2:]
    if code not in cix:
        continue
    j = cix[code]
    d = pd.read_csv(f, usecols=["date", "open", "close", "amount"], dtype={"date": str})
    d["date"] = pd.to_datetime(d["date"])
    d = d.set_index("date").sort_index()
    px_close[code] = d["close"]
    a20 = d["amount"].rolling(20, min_periods=20).mean()
    d = d.reindex(day_ts)
    OPEN[:, j] = d["open"].to_numpy()
    CLOSE[:, j] = d["close"].to_numpy()
    AMT20[:, j] = a20.reindex(day_ts).to_numpy()
    fv = d["close"].first_valid_index()
    if fv is not None:
        FIRST[j] = day_ts.get_loc(fv)
print(f"[load] {ND}×{NS} ({time.time()-t0:.0f}s)", flush=True)


def run(ma_p=20, rebal=20, slip=0.002, stop_llv=None, offset=0, npos=10, seed=None):
    rng = np.random.default_rng(seed) if seed is not None else None
    cash, eq, hold = 1e6, [], {}
    MA = None
    if ma_p:
        # MA_p 预计算（滚动均值 over CLOSE 列，逐列）
        MA = np.full((ND, NS), np.nan)
        cs = pd.DataFrame(CLOSE)
        MA = cs.rolling(ma_p, min_periods=ma_p).mean().to_numpy()
    for di in range(ND):
        for code in [c for c, h in hold.items() if h.get("sell_flag")]:
            j = cix[code]
            if np.isnan(OPEN[di, j]) or OPEN[di, j] <= 0:
                continue
            px_o = OPEN[di, j] * (1 - slip)
            h = hold.pop(code)
            sh = h["sh"]
            cash += sh * px_o - max(sh * px_o * 0.00025, 5) - sh * px_o * 0.001
        if stop_llv is not None:
            for code, h in hold.items():
                if h.get("sell_flag"):
                    continue
                j = cix[code]
                c = CLOSE[di, j]
                if not np.isfinite(c):
                    continue
                llv = np.nanmin(CLOSE[max(0, di - stop_llv):di, j]) if di > 0 else np.nan
                if np.isfinite(llv) and c < llv:
                    h["sell_flag"] = True
        if di % rebal == offset and di > 250:
            row = MV[di]
            cand = np.where(np.isfinite(row))[0]
            cand = [j for j in cand[np.argsort(row[cand])][:30]
                    if di - FIRST[j] >= 180 and np.isfinite(OPEN[di, j]) and OPEN[di, j] >= 2
                    and np.isfinite(AMT20[di, j]) and AMT20[di, j] >= 3e6]
            if MA is not None:
                cand = [j for j in cand if np.isfinite(MA[di, j]) and CLOSE[di, j] > MA[di, j]]
            elif rng is not None:
                cand = list(rng.choice(cand, size=min(npos, len(cand)), replace=False))
            picks = cand[:npos]
            tgt = {codes_u[j] for j in picks}
            for code, h in hold.items():
                if code not in tgt and not h.get("sell_flag"):
                    h["sell_flag"] = True
            pv = cash + sum(h["sh"] * (CLOSE[di, cix[c]] if np.isfinite(CLOSE[di, cix[c]]) else h["ep"]) for c, h in hold.items())
            for j in picks:
                code = codes_u[j]
                if code in hold:
                    continue
                px_o = OPEN[di, j]
                pc = CLOSE[di - 1, j]
                if not np.isfinite(px_o) or not np.isfinite(pc) or px_o >= pc * 1.097:
                    continue
                nl = int((min(pv / npos, cash) - 5) / (px_o * 100 * 1.00025))
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
    return {"total": tot * 100, "ann": ((1 + tot) ** (252 / len(eq)) - 1) * 100,
            "mdd": ((eq / np.maximum.accumulate(eq) - 1).min()) * 100,
            "sharpe": float(np.nanmean(r) / np.nanstd(r) * np.sqrt(252)) if np.nanstd(r) > 0 else 0,
            "eq": eq}


if __name__ == "__main__":
    out = {"_n_trials": "MA网格6 + 安慰剂500 + slip1 + 基线"}
    # A. MA 参数敏感性
    for p in (10, 15, 20, 30, 40, 50):
        r = run(ma_p=p)
        r.pop("eq")
        out[f"MA{p}"] = r
        print(f"[MA{p}] {r['total']:.1f}% | 年化 {r['ann']:.1f}% | 回撤 {r['mdd']:.1f}% | 夏普 {r['sharpe']:.3f}", flush=True)
    # C1. 滑点 30bps（MA20）
    r = run(ma_p=20, slip=0.003)
    r.pop("eq")
    out["MA20_slip30"] = r
    print(f"[MA20 slip30] {r['total']:.1f}% | 年化 {r['ann']:.1f}% | 回撤 {r['mdd']:.1f}%", flush=True)
    # B. 域内安慰剂：随机 10 只（无趋势过滤）× 500
    rng = np.random.default_rng(20260913)
    plc = []
    for it in range(500):
        r = run(ma_p=None, seed=int(rng.integers(1e9)))
        plc.append((r["sharpe"], r["total"], r["mdd"]))
    plc = np.array(plc)
    out["_placebo"] = {"n": 500, "sharpe_median": round(float(np.median(plc[:, 0])), 3),
                       "sharpe_p95": round(float(np.quantile(plc[:, 0], 0.95)), 3),
                       "total_median": round(float(np.median(plc[:, 1])), 2),
                       "total_p95": round(float(np.quantile(plc[:, 1], 0.95)), 2),
                       "mdd_median": round(float(np.median(plc[:, 2])), 1)}
    ma20_sh = out["MA20"]["sharpe"]; ma20_tot = out["MA20"]["total"]
    print(f"[安慰剂500] 夏普中位 {np.median(plc[:,0]):.3f} p95 {np.quantile(plc[:,0],0.95):.3f} | "
          f"收益中位 {np.median(plc[:,1]):.1f}% p95 {np.quantile(plc[:,1],0.95):.1f}% | "
          f"MA20 目标 夏普{ma20_sh:.3f} p={(plc[:,0]>=ma20_sh).mean():.4f} 收益{ma20_tot:.1f}% p={(plc[:,1]>=ma20_tot).mean():.4f}", flush=True)
    # C2. 与 FB3-H20 月收益相关性
    fb = pd.read_csv(BASE / "short_v3_fund_slip20_equity.csv")
    fb["date"] = pd.to_datetime(fb.iloc[:, 0])
    fb = fb.set_index("date").iloc[:, 0]
    eqs = pd.Series(run(ma_p=20)["eq"], index=day_ts)
    fm = fb.resample("ME").last().pct_change().dropna()
    sm = eqs.resample("ME").last().pct_change().dropna()
    j = fm.index.intersection(sm.index)
    corr = float(np.corrcoef(fm.loc[j], sm.loc[j])[0, 1])
    out["corr_FB3H20_monthly"] = round(corr, 3)
    print(f"[与 FB3-H20 月收益相关] {corr:.3f}", flush=True)
    # 2026 崩塌段行为（MA20 策略 2026 分年）
    y26 = eqs[eqs.index.year >= 2026]
    out["2026段"] = {"ret": round(float(y26.iloc[-1] / y26.iloc[0] - 1) * 100, 1),
                     "mdd": round(float((y26 / y26.cummax() - 1).min()) * 100, 1)}
    print(f"[2026段] {out['2026段']}", flush=True)
    json.dump(out, open(BASE / "backtest" / "mode3_audit_0913.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=str)
    print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
