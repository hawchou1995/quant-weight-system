# -*- coding: utf-8 -*-
"""factorcombo_0913 十六组合严格复测（主板含退市 3340 票 / 2021-01-04 起 / 真实成本 20bps 滑点）
符号+配置来自 gates_all.json（原会话扫描值与重算值），wmode=ic/icir 统一按等权 z 复测（声明差异）。
审计口径：ADR-0001（T+1 开盘）/ADR-0007（信息集）。"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
START = pd.Timestamp("2021-01-04")
t0 = time.time()

codes = []
mat = {}
for f in sorted((BASE / "data_full").glob("*.csv")):
    c = f.stem
    if not (c.startswith("sh60") or c.startswith("sz00")):
        continue
    d = pd.read_csv(f, usecols=["date", "open", "high", "low", "close", "volume", "amount"], dtype={"date": str})
    d["date"] = pd.to_datetime(d["date"])
    d = d[d["date"] >= START].sort_values("date")
    if len(d) < 120:
        continue
    codes.append(c[2:])
    mat[c[2:]] = d.set_index("date")
codes = sorted(codes)
ALL_DAYS = sorted(set().union(*[set(m.index) for m in mat.values()]))
day_ix = {d: i for i, d in enumerate(ALL_DAYS)}
ND, NS = len(ALL_DAYS), len(codes)
cix = {c: i for i, c in enumerate(codes)}
O = np.full((ND, NS), np.nan); H = np.full((ND, NS), np.nan)
L = np.full((ND, NS), np.nan); C = np.full((ND, NS), np.nan)
V = np.full((ND, NS), np.nan); A = np.full((ND, NS), np.nan)
FIRST = np.full(NS, -1, dtype=int)
for code in codes:
    m = mat[code]; j = cix[code]
    ii = m.index.map(day_ix)
    O[ii, j] = m["open"].to_numpy(); H[ii, j] = m["high"].to_numpy()
    L[ii, j] = m["low"].to_numpy(); C[ii, j] = m["close"].to_numpy()
    V[ii, j] = m["volume"].to_numpy(); A[ii, j] = m["amount"].to_numpy()
    FIRST[j] = ii.min()
print(f"[load] {NS} 票 {ND} 日 ({time.time()-t0:.0f}s)", flush=True)


def roll_mean(x, n):
    return pd.DataFrame(x).rolling(n, min_periods=n).mean().to_numpy()


PC = np.full((ND, NS), np.nan); PC[1:] = C[:-1]
TR = np.nanmax(np.stack([H - L, np.abs(H - PC), np.abs(L - PC)]), axis=0)
FACTORS = {
    "ln_amt20": np.log(np.maximum(roll_mean(A, 20), 1e3)),
    "atr20": roll_mean(TR, 20) / C,
    "amp20": roll_mean((H - L) / PC, 20),
    "vol20": roll_mean(V, 20),
    "vol_ratio": V / roll_mean(V, 5),
    "vr5_20": roll_mean(V, 5) / roll_mean(V, 20),
    "vr20_60": roll_mean(V, 20) / roll_mean(V, 60),
    "intraday20": roll_mean(C / O - 1, 20),
    "pvc20": pd.DataFrame(C).rolling(20, min_periods=20).corr(pd.DataFrame(V)).to_numpy(),
    "apvc20": pd.DataFrame(A).rolling(20, min_periods=20).corr(pd.DataFrame(C)).to_numpy(),
        "ret20": roll_mean(C / C - 1, 1) if False else np.vstack([np.full((20, NS), np.nan), C[20:] / C[:-20] - 1]),
    "ret60": np.vstack([np.full((60, NS), np.nan), C[60:] / C[:-60] - 1]),
}
print(f"[factors] 12 个完成 ({time.time()-t0:.0f}s)", flush=True)


def run(signs, topn, rebal, slip=0.002, offset=0):
    comp = np.zeros((ND, NS))
    for (fname, sg) in zip(signs[0], signs[1]):
        a = FACTORS[fname] * sg
        mu = np.nanmean(a, axis=1, keepdims=True)
        sd = np.nanstd(a, axis=1, keepdims=True)
        z = np.clip((a - mu) / np.where(sd > 0, sd, 1), -3, 3)
        comp += np.nan_to_num(z, nan=0)
    valid = np.isfinite(C)
    comp = np.where(valid, comp, np.nan)
    cash, eq, hold, n_tr = 1e6, [], {}, 0
    for di in range(ND):
        for code in [c for c, h in hold.items() if h.get("sell_flag")]:
            j = cix[code]
            if np.isnan(O[di, j]) or O[di, j] <= 0:
                continue
            px_o = O[di, j] * (1 - slip)
            h = hold.pop(code)
            sh = h["sh"]
            cash += sh * px_o - max(sh * px_o * 0.00025, 5) - sh * px_o * 0.001
            n_tr += 1
        if di % rebal == offset and di > 120:
            sc = comp[di]
            ok = np.where(np.isfinite(sc))[0]
            ok = [j for j in ok[np.argsort(-sc[ok])][:topn]
                  if np.isfinite(O[di, j]) and O[di, j] >= 2 and di - FIRST[j] >= 180]
            tgt = {codes[j] for j in ok}
            for code, h in hold.items():
                if code not in tgt and not h.get("sell_flag"):
                    h["sell_flag"] = True
            pv = cash + sum(h["sh"] * (C[di, cix[c]] if np.isfinite(C[di, cix[c]]) else h["ep"]) for c, h in hold.items())
            for j in ok:
                code = codes[j]
                if code in hold:
                    continue
                px_o = O[di, j]
                pc = C[di - 1, j]
                if not np.isfinite(px_o) or not np.isfinite(pc) or px_o >= pc * 1.097:
                    continue
                nl = int((min(pv / topn, cash) - 5) / (px_o * 100 * 1.00025))
                if nl < 1:
                    continue
                sh = nl * 100
                cost = sh * px_o * (1 + slip) + max(sh * px_o * 0.00025, 5)
                if cost > cash:
                    continue
                cash -= cost
                hold[code] = {"sh": sh, "ep": px_o * (1 + slip), "sell_flag": False}
        pv = cash + sum(h["sh"] * (C[di, cix[c]] if np.isfinite(C[di, cix[c]]) else h["ep"]) for c, h in hold.items())
        eq.append(pv)
    eq = np.array(eq)
    r = np.diff(eq) / eq[:-1]
    tot = eq[-1] / 1e6 - 1
    return {"total": tot * 100, "ann": ((1 + tot) ** (252 / max(1, len(eq))) - 1) * 100,
            "mdd": ((eq / np.maximum.accumulate(eq) - 1).min()) * 100,
            "sharpe": float(np.nanmean(r) / np.nanstd(r) * np.sqrt(252)) if np.nanstd(r) > 0 else 0,
            "n_trades": n_tr, "eq": eq}


if __name__ == "__main__":
    targets = json.load(open("_replicate_list_0913.json", encoding="utf-8"))
    out = {}
    for r in targets:
        names = [s.split("_")[0] + "_" + s.split("_", 1)[1] if False else s for s in r["subset"]]
        signs = (r["subset"], r["signs"])
        cfg = r["cfg"]
        res = run(signs, cfg["topn"], cfg["rebal"])
        eq = res.pop("eq")
        res["phase_sharpes"] = [run(signs, cfg["topn"], cfg["rebal"], offset=o)["sharpe"] for o in (5, 15, 30, 45)] if cfg["rebal"] >= 20 else None
        key = r["name"]
        out[key] = {"cfg": cfg, "orig_recomputed": r["recomputed"], "replica": res}
        ph = res.get("phase_sharpes")
        phs = f"| 相位中位 {np.median(ph):.3f} 区间 [{min(ph):.2f},{max(ph):.2f}]" if ph else ""
        print(f"[{key}] {res['total']:.1f}% | 年化 {res['ann']:.1f}% | 回撤 {res['mdd']:.1f}% | 夏普 {res['sharpe']:.3f} "
              f"(原重算 {r['recomputed']['sharpe']:.3f}) {phs}", flush=True)
        json.dump(out, open(BASE / "backtest" / "factorcombo_replica_0913.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, default=str)
    print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
