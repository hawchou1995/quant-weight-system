# -*- coding: utf-8 -*-
"""R-topic293 Stage 3/4：C 臂（平台共性特征复刻的动量名单）+ L3 对照锚（全市场涨幅带）。

为什么这样定（数据约束下的可行口径，全部申报）：
- 平台两点半名单只有 48 行 → 长窗只能复刻。复刻依据 = 0913 特征反演结论：平台策略共性 =
  **高开(open_rise) + 近期强势(ret20) + 放量(量比)** → C 名单 = 每日按三特征等权 z 分 Top5。
- 14:30 涨幅用 ampm2（前复权、3195 只、2024-06-19→2026-09-16）**免抓取筛查**；只有通过 F1 的候选
  才去抓 pytdx 14:45（F2 需要）→ 把抓取量从数万降到千级。
- L3 的带内候选 28.7 万/全窗（中位 158/日）→ 逐日抓不可行 → **按每 13 个交易日抽 1 天**（≈42 天）
  的带内全集，申报为对照锚的抽样口径。
- 两臂窗口统一为 ampm2 窗口 2024-06-19 → 2026-09-16（申报：偏离预注册的 L1 2021+ 窗口，
  原因是 14:30 批量数据只到 2024-06；L1 臂已按原窗口跑过）。

用法：python t293_c_l3_0919.py --arm C|L3 [--limit N]
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
from t293_l1_proxy_0919 import stats, ret_for  # noqa: E402

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
ALT = Path("D:/Tools/cache/altdata")
t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:7.1f}s]", *a, flush=True)


def load_ampm():
    fs = sorted(ALT.glob("ampm2_30m_shard*.csv"))
    if not fs:
        raise SystemExit("缺 ampm2 分片")
    d = pd.concat([pd.read_csv(f, dtype={"code": str, "date": str}) for f in fs], ignore_index=True)
    d = d.sort_values(["code", "date"])
    d["prev"] = d.groupby("code")["c1500"].shift(1)
    d["g1430"] = d["c1430"] / d["prev"] - 1
    return d[["code", "date", "c1430", "c1500", "prev", "g1430"]].dropna()


# ---------------- C 臂：动量复刻名单 ----------------
def build_c_list(ampm, topn=5):
    """每日按 高开+量比+ret20 等权 z 取 Top5（平台四点共性特征中的三个可得项）。"""
    cache = pd.read_pickle(K.CACHE)
    rows = []
    for code, df in cache.items():
        s = code if isinstance(code, str) else str(code)
        if s[2:3] in ("4", "8"):        # 北交所剔除（平台不做）
            continue
        d = df[["open", "close"]].copy()
        d.index.name = None
        d["date"] = d.index.strftime("%Y-%m-%d")
        d = d.reset_index(drop=True)
        d["c6"] = s[2:]
        d["open_rise"] = d["open"] / d["close"].shift(1) - 1
        if "ret20" in df.columns:
            d["ret20"] = df["ret20"].values
        if "vol_ratio" in df.columns:
            d["vr"] = df["vol_ratio"].values
        rows.append(d[["c6", "date", "open_rise", "ret20", "vr"]])
    f = pd.concat(rows, ignore_index=True).dropna()
    f = f[(f["date"] >= ampm["date"].min()) & (f["date"] <= ampm["date"].max())]
    for col in ("open_rise", "ret20", "vr"):
        mu = f.groupby("date")[col].transform("mean")
        sd = f.groupby("date")[col].transform("std").replace(0, np.nan)
        f["z_" + col] = (f[col] - mu) / sd
    f = f.dropna(subset=["z_open_rise", "z_ret20", "z_vr"])
    f["score"] = f["z_open_rise"] + f["z_ret20"] + f["z_vr"]
    top = f.sort_values(["date", "score"], ascending=[True, False]).groupby("date").head(topn)
    log(f"C 名单：{len(top)} 行 / {top['date'].nunique()} 日（Top{topn}/日）")
    return top.rename(columns={"c6": "code"})[["code", "date", "score"]]


# ---------------- 通用：按日候选 → F1(免费筛查) → F2(抓 14:45) ----------------
def screen_and_fetch(cand, ampm, need_g1430=True, limit=None):
    key = ampm.set_index(["code", "date"])
    recs, fails, n = [], 0, len(cand)
    for i, x in enumerate(cand.itertuples(), 1):
        code, ds = str(x.code).zfill(6), str(x.date)
        if need_g1430:
            try:
                row = key.loc[(code, ds)]
            except KeyError:
                continue
            if not (0.01 <= float(row["g1430"]) < 0.03):
                continue          # F1 未过 → 不抓分时
        m = pv(code, int(ds.replace("-", "")))
        if not m or not m.get("prev_close"):
            fails += 1
            continue
        g = m["p1430"] / m["prev_close"] - 1
        pc = m["prev_close"]
        recs.append({"date": ds, "code": code, "g": g,
                     "F1": 1.0 <= g * 100 < 3.0,
                     "F2": m["p1445"] >= m["p1430"] * 0.998,
                     "limit": m["p1430"] >= pc * (1 + limit_pct(code)) - 1e-6,
                     "p1430": m["p1430"], "p1445": m["p1445"], "p1500": m["p1500"], "pc": pc})
        if i % 200 == 0:
            log(f"  抓取 {i}/{n}（成功 {len(recs)} 失败 {fails}）ETA {(time.time()-t0)/i*(n-i):.0f}s")
        if limit and len(recs) >= limit:
            break
    df = pd.DataFrame(recs)
    if len(df):
        df["pass"] = df["F1"] & df["F2"] & (~df["limit"])
    log(f"抓取完成：成功 {len(df)}，失败 {fails}")
    return df


def evaluate(df, out_json, tag):
    day_list = sorted(df["date"].unique())
    dmap = {d: k for k, d in enumerate(day_list)}
    arms = {}
    bases = {
        "B0_裸名单全买": df,
        "B1_仅F1": df[df["F1"]] if len(df) else df,
        "B2_仅Top1": df.sort_values(["date", "g"], ascending=[True, False]).groupby("date").head(1) if len(df) else df,
        "A_全规则": df[df["pass"]].sort_values(["date", "g"], ascending=[True, False]).groupby("date").head(1) if len(df) else df,
    }
    for bname, bdf in bases.items():
        if not len(bdf):
            continue
        for tier in ("20bp", "50bp"):
            c = roundtrip_cost(tier)
            for xcol, xname in (("p1445", "买14:45"), ("p1500", "买15:00")):
                for yk, yname in (("t1o", "T+1开盘卖"), ("t1c", "T+1收盘卖"), ("t3o", "T+3开盘卖")):
                    rs, days = [], []
                    for x in bdf.to_dict("records"):
                        d = daily(x["code"])
                        if d is None:
                            continue
                        g = ret_for(x, d, xcol, yk)
                        if g is None or not np.isfinite(g):
                            continue
                        rs.append(g - c)
                        days.append(x["date"])
                    if len(rs) < 5:
                        continue
                    arr = np.array(rs)
                    arms[f"{bname}|{tier}|{xname}|{yname}"] = {
                        "n": len(arr), **stats(arr, np.array([dmap[d] for d in days]), len(day_list))}
    out_json.write_text(json.dumps(arms, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"{tag} 全臂落盘 {out_json.name}")
    return arms


def report(arms, tag):
    print(f"\n=== {tag} 全臂（成本已扣）===")
    print(f"  {'基线':<14}{'档':<6}{'执行':<9}{'出场':<11}{'n':>6}{'笔均%':>8}{'中位%':>8}"
          f"{'胜率%':>7}{'聚类t':>8}{'n_eff':>6}{'累计%':>9}")
    for k, v in arms.items():
        b, t, x, y = k.split("|")
        print(f"  {b:<14}{t:<6}{x:<9}{y:<11}{v['n']:>6}{v['mean_pct']:>8.3f}{v['med_pct']:>8.3f}"
              f"{v['win']:>7.1f}{v['t_cluster']:>8.2f}{v['n_eff']:>6}{v['sum_pct']:>9.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=["C", "L3", "P1"])
    ap.add_argument("--topn", type=int, default=5)
    ap.add_argument("--every", type=int, default=13, help="L3 抽样：每 N 个交易日取 1 天")
    a = ap.parse_args()
    ampm = load_ampm()
    log(f"ampm2 载入 {len(ampm)} 行 / {ampm['code'].nunique()} 只 / {ampm['date'].nunique()} 日")

    if a.arm == "C":
        cand = build_c_list(ampm, a.topn)
        cand.to_csv(BASE / "backtest" / "t293_c_candidates.csv", index=False, encoding="utf-8")
        # 全量抓（不用 ampm2 免抓筛查）：否则 B0/B1/B2 基线会退化成同一集合 —— C 臂暴露的坑
        df = screen_and_fetch(cand, ampm, need_g1430=False)
        df.to_csv(BASE / "backtest" / "t293_c_rows.csv", index=False, encoding="utf-8")
        arms = evaluate(df, BASE / "backtest" / "t293_c_summary.json", "C")
        report(arms, "C 臂（动量复刻名单 2024-06→2026-09）")
    elif a.arm == "P1":
        days = sorted(ampm["date"].unique())
        pick = set(days[::a.every])
        hi = ampm[(ampm["g1430"] >= 0.095) & (ampm["date"].isin(pick))]
        mid = ampm[(ampm["g1430"] >= 0.05) & (ampm["g1430"] < 0.095) & (ampm["date"].isin(pick))]
        log(f"P1 抽样 {len(pick)} 天 → ≥9.5% 候选 {len(hi)} 行；相邻档[5%,9.5%) {len(mid)} 行")
        for nm, cc in (("P1_hi", hi), ("P1_mid", mid)):
            cand = cc[["code", "date"]]
            df = screen_and_fetch(cand, ampm, need_g1430=False)
            df.to_csv(BASE / "backtest" / f"t293_{nm}_rows.csv", index=False, encoding="utf-8")
            arms = evaluate(df, BASE / "backtest" / f"t293_{nm}_summary.json", nm)
            report(arms, f"{nm}（{'>=' if nm.endswith('hi') else '5-9.5%'} 档 · 抽样日）")
    else:
        days = sorted(ampm["date"].unique())
        pick = set(days[::a.every])
        band = ampm[(ampm["g1430"] >= 0.01) & (ampm["g1430"] < 0.03) & (ampm["date"].isin(pick))]
        log(f"L3 抽样 {len(pick)} 天 → 带内候选 {len(band)} 行")
        cand = band.rename(columns={"code": "code"})[["code", "date"]]
        df = screen_and_fetch(cand, ampm, need_g1430=False)
        df.to_csv(BASE / "backtest" / "t293_l3_rows.csv", index=False, encoding="utf-8")
        arms = evaluate(df, BASE / "backtest" / "t293_l3_summary.json", "L3")
        report(arms, "L3 对照锚（全市场涨幅带 · 抽样日）")


if __name__ == "__main__":
    main()
