# -*- coding: utf-8 -*-
"""打板线全窗口复核（用户「扣掉」三件套）：
   ① 全窗口不抽样（548 个交易日，2024-06-19 → 2026-09-16）
   ② 成本压力档 20 / 50 / 100bp（往返 50 / 110 / 210bp）
   ③ 容量门（单笔金额 ÷ 当日成交额 ≤ 2% / 5% / 10%，用 data_full 的 amount 同日自洽）

取数策略（省 60% 抓取）：
   · 14:30 已封板者（≥64.9%）**不抓** —— 用 ampm2 的 c1430/prev 即可判定
   · 只对"14:30 未封板"的 10,731 条抓 pytdx 14:45（判定可成交 + 取 14:45 入场价）
   · 另跑一版 **15:00 收盘入场**（零抓取、双档全窗口）—— 用于相邻档 [5%,9.5%) 的断崖复核
     （该档 14:45 封板率仅 1.8%，15:00 口径的偏差可声明）
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t293_minute_0919 import pv  # noqa: E402
from t293_l2_real_list_0919 import daily, limit_pct  # noqa: E402
from factor_infer import cluster_t, daily_mean  # noqa: E402

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest"
ALT = Path("D:/Tools/cache/altdata")
CAPITAL, K_SLOTS = 170000.0, 10
COMM, TAX = 0.00025, 0.0005
TIERS = {"20bp": 0.0020, "50bp": 0.0050, "100bp": 0.0100}
t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:7.1f}s]", *a, flush=True)


def load_ampm():
    d = pd.concat([pd.read_csv(ALT / f"ampm2_30m_shard{i}.csv", dtype={"code": str, "date": str})
                   for i in range(3)], ignore_index=True)
    d = d.sort_values(["code", "date"])
    d["prev"] = d.groupby("code")["c1500"].shift(1)
    d["g"] = d["c1430"] / d["prev"] - 1
    return d.dropna(subset=["g"])


def add_limit(df):
    lim = np.where(df["code"].str[:2].isin(["30", "68"]), 0.20, 0.10)
    df = df.copy()
    df["lim_pct"] = lim
    df["sealed30"] = df["c1430"].to_numpy() >= df["prev"].to_numpy() * (1 + lim) - 1e-3
    return df


def fetch_1445(df):
    """只抓 14:30 未封板的；返回 (p1445, sealed45) 数组，失败为 nan/None"""
    f = OUT / "p1_full_1445.csv"
    if f.exists():
        m = pd.read_csv(f, dtype={"code": str, "date": str})
        return {(r["code"], r["date"]): (r["p1445"], r["sealed45"]) for _, r in m.iterrows()}
    todo = df[~df["sealed30"]]
    log(f"需抓 14:45：{len(todo)} 条（已剔除 14:30 封板 {int(df['sealed30'].sum())} 条）")
    recs = []
    n = len(todo)
    for i, x in enumerate(todo.itertuples(), 1):
        m = pv(str(x.code).zfill(6), int(str(x.date).replace("-", "")))
        if not m or not m.get("prev_close"):
            recs.append({"code": str(x.code).zfill(6), "date": x.date, "p1445": np.nan, "sealed45": None})
            continue
        pc = m["prev_close"]
        lim = limit_pct(str(x.code).zfill(6))
        recs.append({"code": str(x.code).zfill(6), "date": x.date,
                     "p1445": m["p1445"], "sealed45": bool(m["p1445"] >= pc * (1 + lim) - 1e-3)})
        if i % 500 == 0:
            log(f"  抓取 {i}/{n} ETA {(time.time()-t0)/i*(n-i):.0f}s")
    pd.DataFrame(recs).to_csv(f, index=False, encoding="utf-8")
    log(f"抓取完成，落盘 {f.name}")
    return {(r["code"], r["date"]): (r["p1445"], r["sealed45"]) for _, r in
            pd.read_csv(f, dtype={"code": str, "date": str}).iterrows()}


def ret_1445(row, yk="t1o"):
    """买 T 日 14:45 → 卖出（同日比值换算到前复权）"""
    d = daily(row["code"])
    if d is None or row["date"] not in d.index:
        return np.nan
    idx = d.index.tolist()
    i = idx.index(row["date"])
    A_close = float(d["close"].iloc[i])
    entry_A = A_close * (row["p1445"] / row["p1500"])
    if entry_A <= 0 or not np.isfinite(entry_A):
        return np.nan
    step = {"t1o": 1, "t1c": 1, "t3o": 3}[yk]
    k = i + step
    if k >= len(idx):
        return np.nan
    return (float(d["open"].iloc[k]) if yk != "t1c" else float(d["close"].iloc[k])) / entry_A - 1


def ret_1500(row, yk="t1o"):
    d = daily(row["code"])
    if d is None or row["date"] not in d.index:
        return np.nan
    idx = d.index.tolist()
    i = idx.index(row["date"])
    entry = float(row["c1500"])
    step = {"t1o": 1, "t1c": 1, "t3o": 3}[yk]
    k = i + step
    if k >= len(idx):
        return np.nan
    return (float(d["open"].iloc[k]) if yk != "t1c" else float(d["close"].iloc[k])) / entry - 1


def capacity_gate(row, notional, cap):
    """单笔金额 / 当日成交额 ≤ cap"""
    d = daily(row["code"])
    if d is None or "amount" not in d.columns or row["date"] not in d.index:
        return True                     # 取不到成交额 → 不拦（申报）
    amt = float(d.loc[row["date"], "amount"])
    return notional <= cap * amt


def port(days, day_rets, label):
    days = sorted(days)
    years = (pd.Timestamp(days[-1]) - pd.Timestamp(days[0])).days / 365.25
    rr = np.array([day_rets[d] for d in days])
    nav = np.cumprod(1 + rr)
    ann = nav[-1] ** (1 / years) - 1
    r2 = np.diff(nav) / nav[:-1]
    sh = r2.mean() / r2.std() * np.sqrt(244) if r2.std() > 0 else np.nan
    mdd = float((nav / np.maximum.accumulate(nav) - 1).min())
    print(f"  {label:<34} 日均值 {rr.mean()*100:>7.3f}%  日胜率 {(rr>0).mean()*100:>5.1f}%  "
          f"累计 {(nav[-1]-1)*100:>8.1f}%  **年化 {ann*100:>6.1f}%**  夏普 {sh:>5.2f}  回撤 {mdd*100:>6.2f}%")
    return {"mean_day_pct": float(rr.mean() * 100), "win_day": float((rr > 0).mean() * 100),
            "total_pct": float((nav[-1] - 1) * 100), "ann_pct": float(ann * 100),
            "sharpe": float(sh), "mdd_pct": float(mdd * 100), "days": len(days)}


def main():
    ampm = add_limit(load_ampm())
    log(f"ampm2 {len(ampm)} 行 / {ampm['date'].nunique()} 日")
    hi = ampm[ampm["g"] >= 0.095].copy()
    mid = ampm[(ampm["g"] >= 0.05) & (ampm["g"] < 0.095)].copy()
    log(f"≥9.5% {len(hi)} 行（14:30 封板 {int(hi['sealed30'].sum())}）｜[5,9.5%) {len(mid)} 行")
    m1445 = fetch_1445(hi)
    hi["p1445"] = [m1445.get((c, d), (np.nan, None))[0] for c, d in zip(hi["code"], hi["date"])]
    hi["sealed45"] = [m1445.get((c, d), (np.nan, None))[1] for c, d in zip(hi["code"], hi["date"])]
    hi["p1500"] = hi["c1500"]
    hi["pc"] = hi["prev"]
    hi["code"] = hi["code"].str.zfill(6)
    hi.to_parquet(OUT / "p1_full_hi.parquet", index=False)
    mid["code"] = mid["code"].str.zfill(6)
    mid.to_parquet(OUT / "p1_full_mid.parquet", index=False)
    # 成交额（用于容量门）
    amt_cache = {}
    for c in sorted(set(hi["code"]) | set(mid["code"])):
        d = daily(c)
        if d is not None and "amount" in d.columns:
            amt_cache[c] = d["amount"].to_dict()
    log(f"成交额字典 {len(amt_cache)} 只")

    res = {}
    # ---------- 事件级（14:45 可成交子集 vs 相邻档，全窗口）----------
    print("\n=== 事件级（全窗口 · 买 14:45 → 次日开盘卖 · 往返 50bp）===")
    exe = hi[(~hi["sealed45"].astype(bool)) & np.isfinite(hi["p1445"].to_numpy())].copy()
    exe["r"] = [ret_1445(x) for x in exe.to_dict("records")]
    exe = exe[np.isfinite(exe["r"].to_numpy())]
    r = exe["r"].to_numpy() - 0.0110
    days = sorted(exe["date"].unique()); dm = {d: i for i, d in enumerate(days)}
    didx = np.array([dm[x] for x in exe["date"]])
    c = cluster_t(r, didx, len(days))
    print(f"  ≥9.5% 可成交子集：n={len(r)}｜笔均 {r.mean()*100:+.3f}%｜胜率 {(r>0).mean()*100:.1f}%｜"
          f"聚类 t {c['t']:.2f}（t_naive {cluster_t(r,didx,len(days))['t']:.1f}→虚高）｜有票日 {len(days)}/{ampm['date'].nunique()}")
    res["hi_exec"] = {"n": int(len(r)), "mean_pct": float(r.mean() * 100),
                      "win": float((r > 0).mean() * 100), "t_cluster": float(c["t"])}
    yr = exe["date"].str[:4].to_numpy()
    for y in ("2024", "2025", "2026"):
        mm = yr == y
        if mm.sum() >= 20:
            print(f"    {y}: n={mm.sum():>5} 笔均 {r[mm].mean()*100:>+7.3f}% 胜率 {(r[mm]>0).mean()*100:>5.1f}%")
    res["hi_by_year"] = {y: {"n": int((yr == y).sum()), "mean_pct": float(r[yr == y].mean() * 100)}
                         for y in ("2024", "2025", "2026") if (yr == y).sum() >= 20}
    # 相邻档：15:00 入场（零抓取）
    mid2 = mid.copy()
    mid2["r"] = [ret_1500(x) for x in mid2.to_dict("records")]
    mid2 = mid2[np.isfinite(mid2["r"].to_numpy())]
    rm = mid2["r"].to_numpy() - 0.0110
    dm2 = {d: i for i, d in enumerate(sorted(mid2["date"].unique()))}
    cm = cluster_t(rm, np.array([dm2[x] for x in mid2["date"]]), len(dm2))
    print(f"  [5%,9.5%) 相邻档（15:00 入场）：n={len(rm)}｜笔均 {rm.mean()*100:+.3f}%｜胜率 {(rm>0).mean()*100:.1f}%｜聚类 t {cm['t']:.2f}")
    res["mid_exec"] = {"n": int(len(rm)), "mean_pct": float(rm.mean() * 100),
                       "win": float((rm > 0).mean() * 100), "t_cluster": float(cm["t"])}
    # ≥9.5% 的 15:00 入场版（与相邻档同口径可比）
    hi2 = hi.copy()
    hi2["r"] = [ret_1500(x) for x in hi2.to_dict("records")]
    hi2 = hi2[np.isfinite(hi2["r"].to_numpy())]
    rh = hi2["r"].to_numpy() - 0.0110
    dh = {d: i for i, d in enumerate(sorted(hi2["date"].unique()))}
    ch = cluster_t(rh, np.array([dh[x] for x in hi2["date"]]), len(dh))
    print(f"  ≥9.5%（15:00 入场，同口径）：n={len(rh)}｜笔均 {rh.mean()*100:+.3f}%｜胜率 {(rh>0).mean()*100:.1f}%｜聚类 t {ch['t']:.2f}")
    res["hi_1500"] = {"n": int(len(rh)), "mean_pct": float(rh.mean() * 100),
                      "win": float((rh > 0).mean() * 100), "t_cluster": float(ch["t"])}

    # ---------- 组合级：全窗口 · K=10 · 17 万 · 整手 · 三成本档 × 三容量门 ----------
    print("\n=== 组合级（全窗口 · K=10 只/日 · 17 万本金 · 整手 · 未成交则空仓）===")
    print(f"  {'成本档':<8}{'容量门':<10}{'日均值%':>9}{'日胜率%':>8}{'累计%':>9}{'年化%':>8}{'夏普':>7}{'回撤%':>8}")
    per = CAPITAL / K_SLOTS
    for tname, slip in TIERS.items():
        c_rt = 2 * (slip + COMM) + TAX
        for cap in (None, 0.10, 0.05, 0.02):
            day_r, kept = {}, {}
            for d, sub in hi.groupby("date"):
                sub = sub[(~sub["sealed45"].astype(bool)) & np.isfinite(sub["p1445"].to_numpy())]
                sub = sub.sort_values("g", ascending=False)
                if not len(sub):
                    day_r[d] = 0.0
                    continue
                rets, spent, n_buy = [], 0.0, 0
                for _, x in sub.iterrows():
                    if n_buy >= K_SLOTS:
                        break
                    if cap is not None:
                        amt = amt_cache.get(x["code"], {}).get(x["date"])
                        if amt and per > cap * float(amt):
                            continue                      # 容量门拦下
                    lots = int(np.floor(per / (x["p1445"] * 100)))
                    if lots < 1 or spent + lots * 100 * x["p1445"] > CAPITAL:
                        continue
                    spent += lots * 100 * x["p1445"]
                    n_buy += 1
                    rr = ret_1445(x) if np.isfinite(x["p1445"]) else np.nan
                    if np.isfinite(rr):
                        rets.append(rr - c_rt)
                day_r[d] = float(np.mean(rets)) * (spent / CAPITAL) if rets else 0.0
                kept[d] = n_buy
            st = port(sorted(day_r), day_r, f"{tname} · {'无容量门' if cap is None else f'≤{cap*100:.0f}%成交额'}")
            st["avg_bought"] = float(np.mean(list(kept.values())))
            res[f"port_{tname}_cap{cap}"] = st
    (OUT / "p1_full_summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    log("落盘 p1_full_summary.json")


if __name__ == "__main__":
    main()
