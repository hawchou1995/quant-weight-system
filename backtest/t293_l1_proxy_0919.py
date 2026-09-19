# -*- coding: utf-8 -*-
"""R-topic293 Stage 3：代理主载体 L1 = KHunter 主信号名单（2021-01-04 → 2026-09-15）。

名单定义（与生产主信号同源）：T 日 15 策略任一命中 ∧ RSI(T)<35 ∧ close(T)≥3 ∧ 主板(sh60/sz00)
  —— 不含熊市门（预注册口径），窗口自 2021-01-04（与 factorlab 面板一致）

用法：
  python t293_l1_proxy_0919.py --count      # 只数候选量（不抓分时）
  python t293_l1_proxy_0919.py --fetch      # 抓分时 + 跑全臂
  python t293_l1_proxy_0919.py --report     # 只出报告（用已抓缓存）
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import khunter_all_strategies_backtest as K  # noqa: E402
from t293_minute_0919 import pv  # noqa: E402
from t293_l2_real_list_0919 import daily, limit_pct, roundtrip_cost  # noqa: E402

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
START = "2021-01-04"
CAND = BASE / "backtest" / "t293_l1_candidates.csv"
OUTJ = BASE / "backtest" / "t293_l1_summary.json"
t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:7.1f}s]", *a, flush=True)


def build_candidates():
    if CAND.exists():
        df = pd.read_csv(CAND, dtype={"code": str, "date": str})
        log(f"候选清单读缓存：{len(df)} 行")
        return df
    cache = pd.read_pickle(K.CACHE)
    log(f"名单源 {len(cache)} 票，构造候选中…")
    rows, n_stock = [], 0
    for code, df in cache.items():
        if df is None or len(df) < 300:
            continue
        s = code if isinstance(code, str) else str(code)
        if not s.startswith(("sh60", "sz00")):      # 主板（生产口径）
            continue
        d = df[["open", "high", "low", "close", "volume"]].copy()
        d.index.name = None
        d["date"] = d.index
        d = d.sort_values("date").reset_index(drop=True)
        if len(d) < 300:
            continue
        r = K.calc_indicators(d)
        sig = pd.Series(False, index=d.index)
        for _n, _f in K.SIGNALS.items():
            try:
                sig |= _f(r).fillna(False)
            except Exception:
                pass
        ok = sig.values & (r["rsi"].values < 35) & (d["close"].values >= 3.0)
        ds = d["date"].dt.strftime("%Y-%m-%d").values
        for i in np.flatnonzero(ok):
            dt = ds[i]
            if dt < START or i + 5 >= len(d):
                continue
            rows.append({"code": s[2:], "date": dt, "close": float(d["close"].iloc[i]),
                         "rsi": float(r["rsi"].iloc[i])})
        n_stock += 1
        if n_stock % 1000 == 0:
            log(f"  扫描 {n_stock} 票，累计候选 {len(rows)}")
    out = pd.DataFrame(rows).sort_values(["date", "code"]).reset_index(drop=True)
    out.to_csv(CAND, index=False, encoding="utf-8")
    log(f"候选清单落盘：{len(out)} 行 / {out['date'].nunique()} 个交易日 / {out['code'].nunique()} 只")
    return out


def fetch_and_eval(cand, do_fetch=True):
    """对每个候选取分时 → F1/F2/涨跌停守卫 → 按日 Top1 + 三个基线。"""
    recs = []
    n = len(cand)
    fails = 0
    for i, x in enumerate(cand.itertuples(), 1):
        di = int(str(x.date).replace("-", ""))
        m = pv(str(x.code).zfill(6), di) if do_fetch else None
        if not m or not m.get("prev_close"):
            fails += 1
            continue
        pc = m["prev_close"]
        g = m["p1430"] / pc - 1
        recs.append({"date": x.date, "code": str(x.code).zfill(6), "g": g,
                     "F1": 1.0 <= g * 100 < 3.0,
                     "F2": m["p1445"] >= m["p1430"] * 0.998,
                     "limit": m["p1430"] >= pc * (1 + limit_pct(str(x.code).zfill(6))) - 1e-6,
                     "p1430": m["p1430"], "p1445": m["p1445"], "p1500": m["p1500"], "pc": pc})
        if i % 200 == 0:
            log(f"  分时进度 {i}/{n}（失败 {fails}）ETA {(time.time()-t0)/i*(n-i):.0f}s")
    df = pd.DataFrame(recs)
    df["pass"] = df["F1"] & df["F2"] & (~df["limit"])
    df.to_csv(BASE / "backtest" / "t293_l1_rows.csv", index=False, encoding="utf-8")
    log(f"分时成功 {len(df)}/{n}（缺 {fails}）")
    return df


def ret_for(x, d, xcol, ykind):
    """复权口径收益：entry_A = A_close_T × (x[xcol]/p1500)；exit 按 ykind。"""
    idx = list(d.index)
    if x["date"] not in idx:
        return None
    i = idx.index(x["date"])
    if i + 1 >= len(idx):
        return None
    entry_A = float(d["close"].iloc[i]) * (x[xcol] / x["p1500"])
    if ykind == "t1c":
        return float(d["close"].iloc[i + 1]) / entry_A - 1
    step = {"t1o": 1, "t3o": 3, "t5o": 5}[ykind]
    j = i + step
    if j >= len(idx):
        return None
    return float(d["open"].iloc[j]) / entry_A - 1


def evaluate(df, tag):
    """输出 4 基线 × 2 执行价 × 4 出场 × 2 成本档。"""
    day_list = sorted(df["date"].unique())
    dmap = {d: k for k, d in enumerate(day_list)}
    arms = {}
    # 基线定义
    base_days = {
        "B0_裸名单全买": df,
        "B1_仅F1": df[df["F1"]],
        "B2_仅Top1": df.sort_values(["date", "g"], ascending=[True, False]).groupby("date").head(1),
        "A_全规则": df[df["pass"]].sort_values(["date", "g"], ascending=[True, False]).groupby("date").head(1),
    }
    for bname, bdf in base_days.items():
        for tier in ("20bp", "50bp"):
            c = roundtrip_cost(tier)
            for xcol, xname in (("p1445", "买14:45"), ("p1500", "买15:00")):
                for yk, yname in (("t1o", "T+1开盘卖"), ("t1c", "T+1收盘卖"),
                                  ("t3o", "T+3开盘卖"), ("t5o", "T+5开盘卖")):
                    rs, days, codes = [], [], []
                    for x in bdf.to_dict("records"):
                        d = daily(x["code"])
                        if d is None:
                            continue
                        g = ret_for(x, d, xcol, yk)
                        if g is None or not np.isfinite(g):
                            continue
                        rs.append(g - c)
                        days.append(x["date"])
                        codes.append(x["code"])
                    if len(rs) < 3:
                        continue
                    arr = np.array(rs)
                    arms[f"{bname}|{tier}|{xname}|{yname}"] = {
                        "n": len(arr), **stats(arr, np.array([dmap[d] for d in days]), len(day_list)),
                        "codes": codes[:80]}
    return arms


def stats(arr, dayidx, G):
    """事件级：按笔均值/胜率 + 聚类稳健 t；按天等权均值。"""
    from factor_infer import cluster_t, naive_t, daily_mean
    c = cluster_t(arr, dayidx, G)
    nv = naive_t(arr)
    dm = daily_mean(arr, dayidx, G)
    return {"mean_pct": float(arr.mean() * 100), "med_pct": float(np.median(arr) * 100),
            "win": float((arr > 0).mean() * 100),
            "t_naive": float(nv["t"]), "t_cluster": float(c["t"]),
            "n_eff": int(len(dm)), "mean_daily_pct": float(dm.mean() * 100),
            "win_daily": float((dm > 0).mean() * 100),
            "sum_pct": float(arr.sum() * 100)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    cand = build_candidates()
    print(f"\n候选：{len(cand)} 行 / {cand['date'].nunique()} 日 / {cand['code'].nunique()} 只")
    print("每日候选数 Top10:", cand.groupby('date').size().sort_values(ascending=False).head(10).to_dict())
    print("逐年:", cand.groupby(cand['date'].str[:4]).size().to_dict())
    if a.count:
        return
    rows_file = BASE / "backtest" / "t293_l1_rows.csv"
    if a.report and rows_file.exists():
        df = pd.read_csv(rows_file, dtype={"code": str, "date": str})
    else:
        df = fetch_and_eval(cand, do_fetch=a.fetch)
    print(f"\nF1 通过 {int(df['F1'].sum())}｜F1+F2 通过 {int((df['F1']&df['F2']).sum())}"
          f"｜全规则通过 {int(df['pass'].sum())}｜有票交易日 {df[df['pass']]['date'].nunique()}")
    if a.report:
        arms = evaluate(df, "L1")
        OUTJ.write_text(json.dumps(arms, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n=== L1 全臂（成本已扣）===")
        print(f"  {'基线':<14}{'档':<6}{'执行':<9}{'出场':<11}{'n':>5}{'笔均%':>8}{'胜率%':>7}"
              f"{'聚类t':>8}{'n_eff':>6}{'累计%':>9}")
        for k, v in arms.items():
            b, t, x, y = k.split("|")
            print(f"  {b:<14}{t:<6}{x:<9}{y:<11}{v['n']:>5}{v['mean_pct']:>8.3f}{v['win']:>7.1f}"
                  f"{v['t_cluster']:>8.2f}{v['n_eff']:>6}{v['sum_pct']:>9.1f}")
        log("落盘 t293_l1_summary.json")


if __name__ == "__main__":
    main()
