# -*- coding: utf-8 -*-
"""r2 · 分域最后一块未测格子：熊域 × Aroon 单因子（2026-09-12）
================================================================
分域 IC 解剖发现：aroon_osc 是唯一三域全正 IC 的因子，且熊域最强
（bear +0.0625, t=3.40；weak +0.0556；strong +0.0279）。T3 的熊域腿当时用
反向选股（placebo FAIL），「熊域 × Aroon」从未被组合级测试过。
臂位（预注册 4 臂）：N∈{10,20} × 最长持有∈{20,40} 个交易日；
入场：仅 regime==bear 日（T+1 开盘买，Aroon Top-N，amt20≥5e6、价≥2）；
退出：regime 离开熊域（次日开盘清仓）或持有到期，先到先出。
滑点：0 基线（最优臂补 20bps）。成本：佣金/印花税内建。
安慰剂：熊域日随机选 10 只同结构，100 seeds（零假设地板 = r2 解剖的 −0.26%/20日）。
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
import v8_selector as V  # noqa: E402

COMM = V.COMMISSION
TAX = V.SELL_TAX


def main():
    t0 = time.time()
    pool = V.load_pool(use_cache=True)
    codes = [c for c in pool if c.startswith(("sh60", "sz00"))]
    idx = V.load_index(250).set_index("date")
    ma20 = idx["close"].rolling(20, min_periods=20).mean()
    ma250 = idx["close"].rolling(250, min_periods=250).mean()
    regime = np.where(idx["close"] < ma250, "bear",
                      np.where(idx["close"] < ma20, "weak", "strong"))
    regime_s = pd.Series(regime, index=idx.index)
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    day_pos = {d: i for i, d in enumerate(all_days)}

    # 预取
    arr = {}
    for code in codes:
        df = pool[code]
        aro = df["aroon_osc"].to_numpy(float)
        o = df["open"].to_numpy(float)
        c = df["close"].to_numpy(float)
        amt = df["amt20"].to_numpy(float)
        pos = np.array([day_pos.get(d, -1) for d in df.index], dtype=np.int64)
        arr[code] = (aro, o, c, amt, pos, df.index)

    def run(n, max_hold, slip=0, seed=None, random_mode=False):
        rng = np.random.default_rng(seed) if seed is not None else None
        cash = cash0 = 1_000_000.0
        holdings, ep, ed, epos = {}, {}, {}, {}
        eq, trades, last_close = [], [], {}
        for di, day in enumerate(all_days):
            dom = regime_s.get(day)
            # 卖出
            for code in list(holdings.keys()):
                df = pool[code]
                held = di - epos[code]
                exited = (dom != "bear") or (held >= max_hold)
                if not exited or day not in df.index:
                    continue
                px = df.at[day, "open"]
                if not np.isfinite(px) or px <= 0:
                    continue
                sh = holdings.pop(code)
                px_eff = px * (1 - slip / 10000)
                proceeds = sh * px_eff * (1 - COMM) - sh * px_eff * TAX
                trades.append((px_eff / ep[code] - 1) * 100)
                cash += proceeds
            # 买入（仅熊域）
            if dom == "bear":
                cand = []
                for code in codes:
                    aro, o, c, amt, pos, dates = arr[code]
                    k = dates.get_loc(day) if day in dates else -1
                    if k < 1 or k + 1 >= len(dates):
                        continue
                    if not np.isfinite(aro[k]) or not np.isfinite(amt[k]) or amt[k] < 5e6:
                        continue
                    if not np.isfinite(c[k]) or c[k] < 2.0:
                        continue
                    cand.append((code, aro[k] if not random_mode else 0.0, amt[k]))
                if random_mode and len(cand) > n:
                    pick_idx = rng.choice(len(cand), size=n, replace=False)
                    cand = [cand[i] for i in pick_idx]
                else:
                    cand.sort(key=lambda kv: -kv[1])
                budget_total = cash + sum(sh * (last_close.get(cc) or ep[cc]) for cc, sh in holdings.items())
                budget = budget_total / n
                for code, _a, _amt in cand:
                    if len(holdings) >= n:
                        break
                    if code in holdings:
                        continue
                    aro, o, c, amt, pos, dates = arr[code]
                    k = dates.get_loc(day)
                    px = o[k + 1]
                    if not np.isfinite(px) or px <= 0:
                        continue
                    px_eff = px * (1 + slip / 10000)
                    n_lots = int(budget / (px_eff * 100 * (1 + COMM)))
                    if n_lots < 1:
                        continue
                    sh = n_lots * 100
                    cost = sh * px_eff * (1 + COMM)
                    if cost > cash:
                        n_lots = int(cash / (px_eff * 100 * (1 + COMM)))
                        if n_lots < 1:
                            continue
                        sh = n_lots * 100
                        cost = sh * px_eff * (1 + COMM)
                    cash -= cost
                    holdings[code] = sh
                    ep[code] = px_eff
                    ed[code] = dates[k + 1]
                    epos[code] = di + 1
            pv = cash
            for code, sh in holdings.items():
                aro, o, c, amt, pos, dates = arr[code]
                k = dates.get_loc(day) if day in dates else -1
                if k >= 0 and np.isfinite(c[k]) and c[k] > 0:
                    last_close[code] = c[k]
                px = last_close.get(code)
                if px:
                    pv += sh * px
            eq.append({"date": str(day.date()), "value": pv})
        eqdf = pd.DataFrame(eq)
        eqdf["date"] = pd.to_datetime(eqdf["date"])
        eqdf = eqdf.set_index("date")
        r = eqdf["value"].pct_change().fillna(0)
        total = eqdf["value"].iloc[-1] / eqdf["value"].iloc[0] - 1
        dd = (eqdf["value"] / eqdf["value"].cummax() - 1).min()
        sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
        wins = [t for t in trades if t > 0]
        return {"total_pct": round(total * 100, 2), "ann_pct": round(((1 + total) ** (252 / max(1, len(r))) - 1) * 100, 2),
                "mdd_pct": round(dd * 100, 1), "sharpe": round(float(sharpe), 3),
                "n_trades": len(trades),
                "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0}

    res = {"arms": []}
    for n in (10, 20):
        for mh in (20, 40):
            s = run(n, mh)
            s.update({"n": n, "max_hold": mh})
            res["arms"].append(s)
            print(f"  [bear×aroon n{n} h{mh}] {s['total_pct']}% | 年化 {s['ann_pct']}% | "
                  f"回撤 {s['mdd_pct']}% | 夏普 {s['sharpe']} | {s['n_trades']}笔 胜率{s['win_rate']}%", flush=True)
    best = max(res["arms"], key=lambda r: r["sharpe"])
    s2 = run(best["n"], best["max_hold"], slip=20)
    print(f"  [最优臂+20bps] {s2['total_pct']}% | 夏普 {s2['sharpe']}", flush=True)
    res["best_slip20"] = s2

    # 安慰剂：熊域随机选 10 只（同结构），100 seeds
    pl = []
    for seed in range(100):
        s = run(10, 20, seed=seed + 1, random_mode=True)
        pl.append(s["total_pct"])
    real_best = max(a["total_pct"] for a in res["arms"])
    res["placebo"] = {"real_best_pct": real_best,
                      "placebo_mean_pct": round(float(np.mean(pl)), 2),
                      "placebo_max_pct": round(float(np.max(pl)), 2),
                      "placebo_p95_pct": round(float(np.percentile(pl, 95)), 2),
                      "p": round(sum(1 for p in pl if p >= real_best) / len(pl), 2),
                      "n_seeds": 100}
    print(f"[placebo] real_best {real_best}% vs mean {res['placebo']['placebo_mean_pct']}% "
          f"max {res['placebo']['placebo_max_pct']}% → p={res['placebo']['p']}", flush=True)
    json.dump(res, open(R2 / "bear_aroon_0912.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"[done] {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
