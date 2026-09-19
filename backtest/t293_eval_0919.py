# -*- coding: utf-8 -*-
"""R-topic293 统一求值器（单遍，替代 O(n²) 的旧 evaluate）。

修正的旧实现缺陷：每个臂都 `to_dict("records")` + 每次 `list(d.index)` →
21k 行 × 48 臂 = 百万次 O(1300) 调用 → 要跑几小时。本器只做一遍：
  ① 每只票的日线索引只取一次（dict: code → (dates, open[], close[])）
  ② 每个 (执行价, 出场, 成本档) 只算一遍 → 4 基线只是对同一批收益做子集聚合

用法：python t293_eval_0919.py <rows.csv> <out.json> <标签>
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t293_l2_real_list_0919 import daily, roundtrip_cost  # noqa: E402
from factor_infer import cluster_t, naive_t, daily_mean  # noqa: E402

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
_IDX = {}


def code_idx(code):
    """code → (dates list, open array, close array, date→pos) 只建一次。"""
    if code in _IDX:
        return _IDX[code]
    d = daily(code)
    if d is None:
        _IDX[code] = None
        return None
    dates = d.index.tolist()
    _IDX[code] = (dates, d["open"].to_numpy(), d["close"].to_numpy(), {x: i for i, x in enumerate(dates)})
    return _IDX[code]


STEPS = {"t1o": ("open", 1), "t1c": ("close", 1), "t3o": ("open", 3), "t5o": ("open", 5)}


def rets_for(rows, xcol, ykind):
    """返回 np.array 毛收益（未扣成本），对齐 rows 顺序；不可算为 nan。"""
    kind, step = STEPS[ykind]
    out = np.full(len(rows), np.nan)
    for i, x in enumerate(rows):
        ci = code_idx(x["code"])
        if ci is None:
            continue
        dates, op, cl, pos = ci
        j = pos.get(x["date"])
        if j is None:
            continue
        if xcol == "p1500" and not (x.get("p1500") and x["p1500"] > 0):
            continue
        entry_den = float(cl[j]) * (x[xcol] / x["p1500"]) if x["p1500"] else np.nan
        if not np.isfinite(entry_den) or entry_den <= 0:
            continue
        if kind == "close":
            k = j + step
            if k >= len(cl):
                continue
            out[i] = float(cl[k]) / entry_den - 1
        else:
            k = j + step
            if k >= len(op):
                continue
            out[i] = float(op[k]) / entry_den - 1
    return out


def stats(arr, day_idx, G, tier_cost):
    net = arr - tier_cost
    c = cluster_t(net, day_idx, G)
    nv = naive_t(net)
    dm = daily_mean(net, day_idx, G)
    return {"n": int(net.size), "mean_pct": float(net.mean() * 100),
            "med_pct": float(np.median(net) * 100), "win": float((net > 0).mean() * 100),
            "t_naive": float(nv["t"]), "t_cluster": float(c["t"]), "n_eff": int(dm.size),
            "mean_daily_pct": float(dm.mean() * 100), "win_daily": float((dm > 0).mean() * 100),
            "sum_pct": float(net.sum() * 100)}


def evaluate(rows_csv, out_json, tag, exits=("t1o", "t1c", "t3o", "t5o"), xcols=("p1445", "p1500")):
    df = pd.read_csv(rows_csv, dtype={"code": str, "date": str})
    df["code"] = df["code"].str.zfill(6)
    if "pass" not in df.columns:
        df["pass"] = df["F1"] & df["F2"] & (~df["limit"])
    rows = df.to_dict("records")
    day_list = sorted(df["date"].unique())
    dmap = {d: k for k, d in enumerate(day_list)}
    didx = np.array([dmap[r["date"]] for r in rows])
    G = len(day_list)

    masks = {
        "B0_裸名单全买": np.ones(len(rows), bool),
        "B1_仅F1": df["F1"].to_numpy(),
        "B2_仅Top1": np.zeros(len(rows), bool),
        "A_全规则": np.zeros(len(rows), bool),
    }
    # Top1：按日取 g 最大（B2 全体；A 仅通过者）
    order = df.sort_values(["date", "g"], ascending=[True, False]).index.to_numpy()
    seen = set()
    for i in order:
        d = rows[i]["date"]
        if d in seen:
            continue
        seen.add(d)
        masks["B2_仅Top1"][i] = True
    sub = df[df["pass"]].sort_values(["date", "g"], ascending=[True, False])
    seen2 = set()
    for i in sub.index.to_numpy():
        d = rows[i]["date"]
        if d in seen2:
            continue
        seen2.add(d)
        masks["A_全规则"][i] = True

    arms = {}
    for xcol in xcols:
        for yk in exits:
            gross = rets_for(rows, xcol, yk)
            ok = np.isfinite(gross)
            for tier in ("20bp", "50bp"):
                c = roundtrip_cost(tier)
                for bname, m in masks.items():
                    sel = ok & m
                    if sel.sum() < 5:
                        continue
                    arms[f"{bname}|{tier}|{'买14:45' if xcol == 'p1445' else '买15:00'}|"
                         f"{ {'t1o':'T+1开盘卖','t1c':'T+1收盘卖','t3o':'T+3开盘卖','t5o':'T+5开盘卖'}[yk] }"] = \
                        stats(gross[sel], didx[sel], G, c)
    # 分年（仅主口径 A/B0 × 买14:45 × T+1收盘/开盘 × 20bp）
    years = {}
    for xcol in ("p1445",):
        for yk in ("t1o", "t1c"):
            gross = rets_for(rows, xcol, yk)
            ok = np.isfinite(gross)
            yr = np.array([r["date"][:4] for r in rows])
            for bname, m in masks.items():
                for y in sorted(set(yr)):
                    sel = ok & m & (yr == y)
                    if sel.sum() >= 5:
                        net = gross[sel] - roundtrip_cost("20bp")
                        years[f"{bname}|{yk}|{y}"] = {"n": int(sel.sum()),
                                                      "mean_pct": float(net.mean() * 100),
                                                      "win": float((net > 0).mean() * 100)}
    out = {"tag": tag, "n_rows": len(rows), "n_days": G, "arms": arms, "years": years,
           "funnel": {"F1": int(df["F1"].sum()), "F1F2": int((df["F1"] & df["F2"]).sum()),
                      "pass": int(df["pass"].sum()),
                      "days_with_pick": int(df[df["pass"]]["date"].nunique()),
                      "days": G}}
    Path(out_json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n===== {tag}｜{len(rows)} 行 / {G} 日｜F1 过 {out['funnel']['F1']}｜"
          f"F1+F2 过 {out['funnel']['F1F2']}｜全规则过 {out['funnel']['pass']}｜"
          f"有票日 {out['funnel']['days_with_pick']} =====")
    print(f"  {'基线':<14}{'档':<6}{'执行':<9}{'出场':<11}{'n':>6}{'笔均%':>8}{'中位%':>8}"
          f"{'胜率%':>7}{'t_naive':>8}{'t_cluster':>10}{'n_eff':>7}{'日胜率%':>8}")
    for k, v in arms.items():
        b, t, x, y = k.split("|")
        print(f"  {b:<14}{t:<6}{x:<9}{y:<11}{v['n']:>6}{v['mean_pct']:>8.3f}{v['med_pct']:>8.3f}"
              f"{v['win']:>7.1f}{v['t_naive']:>8.2f}{v['t_cluster']:>10.2f}{v['n_eff']:>7}"
              f"{v['win_daily']:>8.1f}")
    print(f"\n  --- 分年（买14:45 · 20bp）---")
    for k, v in years.items():
        b, yk, y = k.split("|")
        print(f"    {b:<14}{yk:<5}{y}  n={v['n']:>4}  笔均 {v['mean_pct']:>7.3f}%  胜率 {v['win']:>5.1f}%")
    return out


if __name__ == "__main__":
    csv, out, tag = sys.argv[1], sys.argv[2], sys.argv[3]
    evaluate(csv, out, tag)
