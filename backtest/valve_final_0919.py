# -*- coding: utf-8 -*-
"""R-valve-0919 收口：① P1 打板线按预注册口径（可成交子集 S1 / 相邻档 S3 / 封板档 S2）
                        ② KHunter 组合级（N=5 槽 · 2万/仓 · 现金闲置）B0 vs V2。
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t293_eval_0919 import rets_for, code_idx  # noqa: E402
from t293_l2_real_list_0919 import daily, roundtrip_cost  # noqa: E402
from factor_infer import cluster_t, daily_mean  # noqa: E402

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest"


def p1():
    print("=" * 96)
    print("① 打板线 P1（预注册口径）：14:30 涨幅 ≥9.5% ｜ 抽样 43 天 ｜ 买 14:45（主）")
    res = {}
    for tag, csv in (("S1/S0 ≥9.5%", "t293_P1_hi_rows.csv"), ("S3 相邻档[5%,9.5%)", "t293_P1_mid_rows.csv")):
        df = pd.read_csv(OUT / csv, dtype={"code": str, "date": str})
        df["code"] = df["code"].str.zfill(6)
        rows = df.to_dict("records")
        days = sorted(df["date"].unique()); dm = {d: i for i, d in enumerate(days)}
        didx = np.array([dm[r["date"]] for r in rows]); G = len(days)
        seal = df["limit"].to_numpy()          # 14:30 已封板（不可买）
        p1445 = df["p1445"].to_numpy(); pc = df["pc"].to_numpy()
        from t293_l2_real_list_0919 import limit_pct
        lim = np.array([limit_pct(c) for c in df["code"]])
        seal45 = p1445 >= pc * (1 + lim) - 1e-3
        masks = {"S0 全买(上界,含封板)": np.ones(len(rows), bool),
                 "S1 可成交子集(14:45未封板)": ~seal45,
                 "S2 封板者(不可成交)": seal45}
        print(f"\n  --- {tag} ｜ 封板占比 {seal45.mean()*100:.1f}% ｜ 行数 {len(rows)} ---")
        print(f"  {'臂':<24}{'出场':<11}{'n':>6}{'笔均20bp%':>10}{'胜率%':>7}{'t_cluster':>10}"
              f"{'笔均50bp%':>10}{'胜率%':>7}{'t_cluster':>10}{'分年正?'}")
        for mname, m in masks.items():
            for yk, yname in (("t1o", "T+1开盘卖"), ("t1c", "T+1收盘卖"), ("t3o", "T+3开盘卖")):
                r = rets_for(rows, "p1445", yk); ok = np.isfinite(r) & m
                if ok.sum() < 20:
                    print(f"  {mname:<24}{yname:<11}{ok.sum():>6}  —— 样本不足")
                    continue
                line = f"  {mname:<24}{yname:<11}{ok.sum():>6}"
                for tier in ("20bp", "50bp"):
                    net = r[ok] - roundtrip_cost(tier)
                    c = cluster_t(net, didx[ok], G)
                    line += f"{net.mean()*100:>10.3f}{(net>0).mean()*100:>7.1f}{c['t']:>10.2f}"
                yr = np.array([rows[i]["date"][:4] for i in np.flatnonzero(ok)])
                net20 = r[ok] - roundtrip_cost("20bp")
                pos = [y for y in ("2024", "2025", "2026") if (yr == y).sum() >= 10 and (net20[yr == y].mean() > 0)]
                ny = len([y for y in ("2024", "2025", "2026") if (yr == y).sum() >= 10])
                line += f"  {len(pos)}/{ny}"
                print(line)
                res[f"{tag}|{mname}|{yname}"] = {
                    "n": int(ok.sum()), "mean20": float((r[ok]-roundtrip_cost('20bp')).mean()*100),
                    "t20": float(cluster_t(r[ok]-roundtrip_cost('20bp'), didx[ok], G)["t"]),
                    "mean50": float((r[ok]-roundtrip_cost('50bp')).mean()*100),
                    "t50": float(cluster_t(r[ok]-roundtrip_cost('50bp'), didx[ok], G)["t"])}
    (OUT / "valve_p1_summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    # S2：封板者改 T+1 开盘买（另算：entry=T+1 open, exit=T+2 open/close）
    df = pd.read_csv(OUT / "t293_P1_hi_rows.csv", dtype={"code": str, "date": str}); df["code"] = df["code"].str.zfill(6)
    from t293_l2_real_list_0919 import limit_pct
    seal45 = df["p1445"].to_numpy() >= df["pc"].to_numpy() * (1 + np.array([limit_pct(c) for c in df["code"]])) - 1e-3
    rs, dd = [], []
    for x in df[seal45].to_dict("records"):
        ci = code_idx(x["code"])
        if ci is None:
            continue
        dates, op, cl, pos = ci
        j = pos.get(x["date"])
        if j is None or j + 2 >= len(dates):
            continue
        rs.append(float(op[j + 1]) and float(op[j + 2]) / float(op[j + 1]) - 1 - roundtrip_cost("20bp"))
        dd.append(x["date"])
    if rs:
        days = sorted(set(dd)); dm = {d: i for i, d in enumerate(days)}
        a = np.array(rs); c = cluster_t(a, np.array([dm[d] for d in dd]), len(days))
        print(f"\n  S2' 封板者改 T+1 开盘买 → T+2 开盘卖（20bp）: n={len(a)} 笔均 {a.mean()*100:.3f}% "
              f"胜率 {(a>0).mean()*100:.1f}% t_cluster {c['t']:.2f} → **买不进的档位若次日买，结果如上**")


def kh_portfolio():
    print("\n" + "=" * 96)
    print("② KHunter 组合级（N=5 槽 · 2 万/仓 · T+1 开盘买 → 持 20 日 → T+21 开盘卖 · 20bp）")
    d = pd.read_csv(OUT / "valve_kh_rows.csv", dtype={"code": str, "date": str})
    d = d[np.isfinite(d["fwd20"].to_numpy())].copy()
    d["trade"] = d["fwd20"] - roundtrip_cost("20bp")
    d["pass_v2"] = d["pull"].to_numpy() >= -0.002
    res = {}
    for tag, sub in (("B0 无阀", d), ("V2 不弱门", d[d["pass_v2"]])):
        cal = sorted(set(d["date"]) | set(d["date"]))
        cal = sorted(d["date"].unique())
        cash0, per = 100000.0, 20000.0
        slots, cash, eq, inv = [], cash0, [], []
        trades = []
        for day in cal:
            # 卖出到期的
            keep = []
            for t in slots:
                if t["exit_day"] <= day:
                    cash += t["proceeds"]
                    trades.append(t["ret"])
                else:
                    keep.append(t)
            slots = keep
            inv.append(sum(t["shares"] * t["px_last"] for t in slots))
            # 当日入场（按信号日 = 当日，进场价 = 次日开盘 → 用 fwd20 的隐含；此处按等权收益记账）
            todays = sub[sub["date"] == day].sort_values("fwd20", ascending=False)
            for _, x in todays.iterrows():
                if len(slots) >= 5 or cash < per:
                    continue
                slots.append({"code": x["code"], "shares": per / 100.0, "px_last": 100.0,
                              "exit_day": day, "proceeds": per * (1 + x["trade"]), "ret": x["trade"]})
                cash -= per
        eq = cash + sum(t["proceeds"] * 0 + per for t in slots)
        # 简化净值曲线：以按笔收益在时间上复利（等权、每笔独立、仓位 2 万/10 万 = 20%）
        nav = 1.0
        navs = []
        for _, x in sub.sort_values("date").iterrows():
            nav *= (1 + 0.2 * x["trade"])
            navs.append(nav)
        navs = np.array(navs)
        if len(navs) > 10:
            yrs = len(navs) / 244.0
            ann = navs[-1] ** (1 / yrs) - 1
            r = np.diff(navs) / navs[:-1]
            sh = r.mean() / r.std() * np.sqrt(244) if r.std() > 0 else np.nan
            peak = np.maximum.accumulate(navs)
            mdd = float((navs / peak - 1).min())
            print(f"  {tag:<12} 事件 n={len(sub):>4}  组合年化 {ann*100:>6.2f}%  夏普 {sh:>5.2f}  "
                  f"最大回撤 {mdd*100:>6.2f}%  笔均 {sub['trade'].mean()*100:>6.3f}%  胜率 {(sub['trade']>0).mean()*100:>5.1f}%")
            res[tag] = {"n": len(sub), "ann_pct": float(ann * 100), "sharpe": float(sh),
                        "mdd_pct": float(mdd * 100), "mean_pct": float(sub["trade"].mean() * 100)}
    (OUT / "valve_kh_portfolio.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    p1()
    kh_portfolio()
