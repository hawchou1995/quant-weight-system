# -*- coding: utf-8 -*-
"""r2 · 多策略共振 + 行业中性反转 双实验（2026-09-12）
================================================================
用户质询：「多策略共振测过吗？」——未测过，本轮补。
共振（AND 双条件，方向均来自 r2 解剖的正向发现）：
  C1: vol20 ≤ 横截面 p30（低波，vol20 负 IC）AND aroon_osc ≥ p70（三域正 IC）
  排序：z(aroon) − z(vol20) 降序取 N
行业中性反转（IC 矩阵：ret20 三域负 IC → 反向暴露；申万一级内中性化）：
  N1: 行业内 ret20 升序 z 分最低，全市场取最低且单行业 ≤2 只
臂位（各自预注册）：N∈{10,20} × hold∈{20,40}；T+1 开盘；佣金/印花税内建。
检查（T3 教训）：入选股市值代理（close×流动性序位）与行业分布——排除规模/行业暴露假 edge。
安慰剂：①同宇宙随机 100 seeds（总体地板）②共振实验另加「同过滤集随机」100 seeds
（检验共振排序是否超越过滤本身）。
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

COMM, TAX = V.COMMISSION, V.SELL_TAX
REB = (20, 40)
NS = (10, 20)


def main():
    t0 = time.time()
    pool = V.load_pool(use_cache=True)
    codes = [c for c in pool if c.startswith(("sh60", "sz00"))]
    ind_map = json.load(open(BASE / "stock_industry.json", encoding="utf-8"))["map"]
    idx = V.load_index(250).set_index("date")
    ma20i = idx["close"].rolling(20, min_periods=20).mean()
    ma250 = idx["close"].rolling(250, min_periods=250).mean()
    regime = pd.Series(np.where(idx["close"] < ma250, "bear",
                                np.where(idx["close"] < ma20i, "weak", "strong")),
                       index=idx.index)
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    reb_days = {h: set(all_days[::h]) for h in REB}

    # 一次性预取截面（全部日）：因子、卫生过滤、行业
    t1 = time.time()
    cross = {}   # day -> dict with arrays
    for di, day in enumerate(all_days):
        recs = []
        for code in codes:
            df = pool[code]
            if day not in df.index:
                continue
            k = df.index.get_loc(day)
            if k < 60:
                continue
            c = df["close"]
            if not np.isfinite(c.iloc[k]) or c.iloc[k] < 2.0:
                continue
            amt = df["amt20"].iloc[k] if "amt20" in df else np.nan
            if not np.isfinite(amt) or amt < 5e6:
                continue
            vol = df["vol20"].iloc[k] if "vol20" in df else np.nan
            aro = df["aroon_osc"].iloc[k] if "aroon_osc" in df else np.nan
            ret20 = c.iloc[k] / c.iloc[k - 20] - 1 if k >= 20 else np.nan
            recs.append((code, vol, aro, ret20, amt))
        if recs:
            cross[day] = recs
        if di % 260 == 0:
            print(f"  [cross] {di} ({time.time()-t1:.0f}s)", flush=True)
    print(f"[cross] {len(cross)} 日有截面 ({time.time()-t1:.0f}s)", flush=True)

    def zscore(vals):
        v = np.array(vals, float)
        m, s = np.nanmean(v), np.nanstd(v)
        return (v - m) / s if s > 0 else v * 0

    def picks_consensus(day, n):
        recs = cross.get(day, [])
        if len(recs) < 30:
            return []
        vols = zscore([r[1] for r in recs])
        aros = zscore([r[2] for r in recs])
        nv = np.nanquantile([r[1] for r in recs], 0.30)
        na = np.nanquantile([r[2] for r in recs], 0.70)
        scored = []
        for (code, vol, aro, ret20, amt), zv, za in zip(recs, vols, aros):
            if np.isfinite(vol) and np.isfinite(aro) and vol <= nv and aro >= na:
                scored.append((code, za - zv))
        scored.sort(key=lambda x: -x[1])
        return [c for c, _ in scored[:n]]

    def picks_indneutral(day, n):
        recs = cross.get(day, [])
        if len(recs) < 30:
            return []
        rets = np.array([r[3] for r in recs], float)
        inds = [ind_map.get(c[2:], "其他") for c, *_ in [(r[0],) for r in recs]]
        dfz = pd.DataFrame({"code": [r[0] for r in recs], "ret": rets, "ind": inds})
        dfz = dfz[dfz["ret"].notna()]
        dfz["z"] = dfz.groupby("ind")["ret"].transform(lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0)
        dfz = dfz.sort_values("z")
        out, cnt = [], {}
        for _, r in dfz.iterrows():
            if cnt.get(r["ind"], 0) >= 2:
                continue
            out.append(r["code"])
            cnt[r["ind"]] = cnt.get(r["ind"], 0) + 1
            if len(out) >= n:
                break
        return out

    def run_portfolio(pick_fn, n, hold, slip=0):
        cash = cash0 = 1_000_000.0
        holdings, ep, epos, last_close = {}, {}, {}, {}
        eq0 = None
        trades = []
        pick_cache = {}
        for di, day in enumerate(all_days):
            for code in list(holdings.keys()):
                held = di - epos[code]
                if held >= hold and day in pool[code].index:
                    px = pool[code].at[day, "open"]
                    if np.isfinite(px) and px > 0:
                        sh = holdings.pop(code)
                        px_eff = px * (1 - slip / 10000)
                        cash += sh * px_eff * (1 - COMM) - sh * px_eff * TAX
                        trades.append((px_eff / ep[code] - 1) * 100)
            if day in reb_days[hold]:
                if day not in pick_cache:
                    pick_cache[day] = pick_fn(day, n)
                picks = pick_cache[day]
                if picks:
                    bt = cash + sum(sh * (last_close.get(cc) or ep[cc]) for cc, sh in holdings.items())
                    budget = bt / n
                    for code in picks:
                        if len(holdings) >= n or code in holdings:
                            continue
                        df = pool[code]
                        if day not in df.index:
                            continue
                        k = df.index.get_loc(day)
                        if k + 1 >= len(df.index):
                            continue
                        px = df["open"].iloc[k + 1]
                        if not np.isfinite(px) or px <= 0:
                            continue
                        px_eff = px * (1 + slip / 10000)
                        nl = int(budget / (px_eff * 100 * (1 + COMM)))
                        if nl < 1:
                            continue
                        sh = nl * 100
                        cost = sh * px_eff * (1 + COMM)
                        if cost > cash:
                            nl = int(cash / (px_eff * 100 * (1 + COMM)))
                            if nl < 1:
                                continue
                            sh = nl * 100
                            cost = sh * px_eff * (1 + COMM)
                        cash -= cost
                        holdings[code] = sh
                        ep[code] = px_eff
                        epos[code] = di + 1
            pv = cash
            for code, sh in holdings.items():
                df = pool[code]
                if day in df.index:
                    cc = df["close"].loc[day]
                    if np.isfinite(cc) and cc > 0:
                        last_close[code] = cc
                px = last_close.get(code)
                if px:
                    pv += sh * px
            if eq0 is None:
                eq0 = pv
        return (pv / eq0 - 1) * 100, trades

    rng_global = np.random.default_rng(7)

    def summary(total, trades, name):
        wins = [t for t in trades if t > 0]
        rec = {"name": name, "total_pct": round(total, 2), "n_trades": len(trades),
               "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0}
        print(f"  [{name}] {rec['total_pct']}% | {rec['n_trades']}笔 胜率{rec['win_rate']}%", flush=True)
        return rec

    out = {"consensus": [], "indneutral": [], "placebo": {}}

    print("== 共振（低波×Aroon） ==", flush=True)
    for n in NS:
        for h in REB:
            tot, tr = run_portfolio(picks_consensus, n, h)
            out["consensus"].append(summary(tot, tr, f"consensus_n{n}_h{h}"))

    print("== 行业中性反转 ==", flush=True)
    for n in NS:
        for h in REB:
            tot, tr = run_portfolio(picks_indneutral, n, h)
            out["indneutral"].append(summary(tot, tr, f"indneutral_n{n}_h{h}"))

    # 安慰剂①：同宇宙随机（h20, n10）100 seeds
    print("== 安慰剂：同宇宙随机 ==", flush=True)
    pl1 = []
    for seed in range(100):
        rng = np.random.default_rng(1000 + seed)
        def pf(day, n, rng=rng):
            recs = cross.get(day, [])
            if len(recs) < n:
                return []
            idxs = rng.choice(len(recs), size=n, replace=False)
            return [recs[i][0] for i in idxs]
        tot, _ = run_portfolio(pf, 10, 20)
        pl1.append(tot)
    out["placebo"]["universe_rand_mean"] = round(float(np.mean(pl1)), 2)
    out["placebo"]["universe_rand_max"] = round(float(np.max(pl1)), 2)
    print(f"  宇宙随机 mean {out['placebo']['universe_rand_mean']}% max {out['placebo']['universe_rand_max']}%", flush=True)

    # 安慰剂②：同过滤集随机（共振过滤后的池子里随机选，检验排序增量）
    print("== 安慰剂：共振过滤集内随机 ==", flush=True)
    pl2 = []
    for seed in range(100):
        rng = np.random.default_rng(2000 + seed)
        def pf(day, n, rng=rng):
            recs = cross.get(day, [])
            if len(recs) < 30:
                return []
            vols = [r[1] for r in recs]
            aros = [r[2] for r in recs]
            nv = np.nanquantile(vols, 0.30)
            na = np.nanquantile(aros, 0.70)
            poolf = [r[0] for r in recs if np.isfinite(r[1]) and np.isfinite(r[2]) and r[1] <= nv and r[2] >= na]
            if len(poolf) < n:
                return []
            idxs = rng.choice(len(poolf), size=n, replace=False)
            return [poolf[i] for i in idxs]
        tot, _ = run_portfolio(pf, 10, 20)
        pl2.append(tot)
    out["placebo"]["filtered_rand_mean"] = round(float(np.mean(pl2)), 2)
    out["placebo"]["filtered_rand_max"] = round(float(np.max(pl2)), 2)
    print(f"  过滤集随机 mean {out['placebo']['filtered_rand_mean']}% max {out['placebo']['filtered_rand_max']}%", flush=True)

    # 规模暴露检查（T3 教训）：共振入选股 vs 宇宙的中位 close
    sample_days = all_days[::40]
    pc, uc = [], []
    for day in sample_days:
        pk = picks_consensus(day, 10)
        for c in pk:
            df = pool[c]
            if day in df.index:
                pc.append(df["close"].loc[day])
        for r in cross.get(day, []):
            uc.append(float(pool[r[0]]["close"].loc[day]) if r[0] in pool else np.nan)
    out["exposure"] = {"consensus_median_close": round(float(np.nanmedian(pc)), 2),
                       "universe_median_close": round(float(np.nanmedian(uc)), 2)}
    print(f"[exposure] 共振入选中位价 {out['exposure']['consensus_median_close']} vs 宇宙 {out['exposure']['universe_median_close']}", flush=True)

    json.dump(out, open(R2 / "consensus_neutral_0912.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"[done] {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
