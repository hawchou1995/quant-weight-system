# -*- coding: utf-8 -*-
"""小市值回撤归因 + 《小市值策略三种模式》移植回测（微信 weRJ7GkjQ，2026-09-13）
归因：月频 slip20 基线的回撤窗口/分年度/持仓特征。
三模式：模式一 纯市值排序（已测基线）｜模式二 市值+流动性双排序｜模式三 市值+趋势过滤｜组合+LLV20。"""
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
MA20 = np.full((ND, NS), np.nan)
FIRST = np.full(NS, -1, dtype=int)
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
    a20 = d["amount"].rolling(20, min_periods=20).mean()
    m20 = d["close"].rolling(20, min_periods=20).mean()
    d = d.reindex(day_ts)
    OPEN[:, j] = d["open"].to_numpy()
    CLOSE[:, j] = d["close"].to_numpy()
    AMT20[:, j] = a20.reindex(day_ts).to_numpy()
    MA20[:, j] = m20.reindex(day_ts).to_numpy()
    fv = d["close"].first_valid_index()
    if fv is not None:
        FIRST[j] = day_ts.get_loc(fv)
print(f"[load] {ND}×{NS} ({time.time()-t0:.0f}s)", flush=True)


def run(mode, rebal=20, slip=0.002, stop_llv=None, offset=0, npos=10):
    """mode: 'pure'(纯市值) | 'liq'(市值+流动性双排序) | 'trend'(市值+趋势过滤) | 'liq_trend'"""
    cash, eq, reasons, hold = 1e6, [], {}, {}
    for di in range(ND):
        for code in [c for c, h in hold.items() if h.get("sell_flag")]:
            j = cix[code]
            if np.isnan(OPEN[di, j]) or OPEN[di, j] <= 0:
                continue
            px_o = OPEN[di, j] * (1 - slip)
            h = hold.pop(code)
            sh = h["sh"]
            cash += sh * px_o - max(sh * px_o * 0.00025, 5) - sh * px_o * 0.001
            rsn = h.get("reason") or "调仓"
            reasons[rsn] = reasons.get(rsn, 0) + 1
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
                    h["reason"] = f"LLV{stop_llv}"
        if di % rebal == offset and di > 250:
            row = MV[di]
            cand = np.where(np.isfinite(row))[0]
            cand = [j for j in cand[np.argsort(row[cand])][:30]
                    if di - FIRST[j] >= 180 and np.isfinite(OPEN[di, j]) and OPEN[di, j] >= 2
                    and np.isfinite(AMT20[di, j]) and AMT20[di, j] >= 3e6]
            if mode in ("liq", "liq_trend"):
                cand = sorted(cand, key=lambda j: -(AMT20[di, j] if np.isfinite(AMT20[di, j]) else 0))[:npos]
            if mode in ("trend", "liq_trend"):
                cand = [j for j in cand if np.isfinite(MA20[di, j]) and CLOSE[di, j] > MA20[di, j]]
            picks = cand[:npos]
            tgt = {codes_u[j] for j in picks}
            for code, h in hold.items():
                if code not in tgt and not h.get("sell_flag"):
                    h["sell_flag"] = True
                    h["reason"] = "调仓"
            pv = cash + sum(h["sh"] * (CLOSE[di, cix[c]] if np.isfinite(CLOSE[di, cix[c]]) else h["ep"]) for c, h in hold.items())
            w = 1.0 / npos
            for j in picks:
                code = codes_u[j]
                if code in hold:
                    continue
                px_o = OPEN[di, j]
                pc = CLOSE[di - 1, j]
                if not np.isfinite(px_o) or not np.isfinite(pc) or px_o >= pc * 1.097:
                    continue
                nl = int((min(pv * w, cash) - 5) / (px_o * 100 * 1.00025))
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
            "sharpe": float(np.nanmean(r) / np.nanstd(r) * np.sqrt(252)), "reasons": reasons, "eq": eq,
            "days": [str(d)[:10] for d in day_ts]}


if __name__ == "__main__":
    out = {}
    # 归因：基线（模式一）回撤窗口
    r1 = run("pure")
    eqs = pd.Series(r1.pop("eq"), index=day_ts)
    dd = eqs / eqs.cummax() - 1
    trough = dd.idxmin()
    peak = eqs.loc[:trough].idxmax()
    rec = dd.loc[trough:]
    rec_end = rec[rec >= -0.001].index.min() if (rec >= -0.001).any() else None
    print(f"[归因 模式一] 峰 {peak.date()} → 谷 {trough.date()}（回撤 {dd.min()*100:.1f}%）→ 修复 {rec_end.date() if rec_end is not None else '未修复'}", flush=True)
    yearly_dd = {str(y): round(float((g / g.cummax() - 1).min()) * 100, 1) for y, g in eqs.groupby(eqs.index.year)}
    print(f"[分年回撤] {yearly_dd}", flush=True)
    out["归因"] = {"peak": str(peak.date()), "trough": str(trough.date()), "yearly_mdd": yearly_dd}
    out["模式一_纯市值"] = {k: v for k, v in r1.items() if k != "days"}

    for name, mode, kw in (("模式二_市值+流动性", "liq", {}),
                           ("模式三_市值+趋势过滤", "trend", {}),
                           ("模式五_二+LLV20", "liq", dict(stop_llv=20)),
                           ("模式六_二+三+LLV20", "liq_trend", dict(stop_llv=20))):
        r = run(mode, **kw)
        eqx = r.pop("eq")
        out[name] = {k: v for k, v in r.items() if k != "days"}
        print(f"[{name}] {r['total']:.1f}% | 年化 {r['ann']:.1f}% | 回撤 {r['mdd']:.1f}% | 夏普 {r['sharpe']:.3f} | {r['reasons']}", flush=True)
        out[name + "_eq"] = [float(x) for x in eqx]
    json.dump(out, open(BASE / "backtest" / "jq_smallcap_modes_0913.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=str)
    print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
