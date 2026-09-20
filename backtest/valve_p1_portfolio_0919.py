# -*- coding: utf-8 -*-
"""打板线组合级（预注册第四条）：每日 Top1（14:30 涨幅最高）vs 当日等权平均，空仓计 0。

两个实现要点（都是我第一版的错，别回退）：
1. **等权 = 当日全部候选的收益平均**，不是"取中位那一只"（第一版写成 sub.iloc[len//2]，
   导致 Top1 与"等权"不可比）
2. **年化必须按日历跨度折算**：抽样日非连续（43 天 / 2.2 年），若按 G/244 折算会虚高约 6 倍
   （第一版 370%/1590% 即此错误）
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t293_eval_0919 import rets_for  # noqa: E402
from t293_l2_real_list_0919 import roundtrip_cost, limit_pct  # noqa: E402

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest"


def day_stats(df, tier):
    rows = df.to_dict("records")
    r = rets_for(rows, "p1445", "t1o")
    tmp = pd.DataFrame({"code": df["code"].values, "date": df["date"].values,
                        "g": df["g"].values, "r": r})
    out = {}
    for d, sub in tmp.groupby("date"):
        sub = sub.sort_values("g", ascending=False)
        out[d] = {"top1": float(sub["r"].iloc[0]) - roundtrip_cost(tier),
                  "ew": float(sub["r"].mean()) - roundtrip_cost(tier), "n": int(len(sub))}
    return out


if __name__ == "__main__":
    print("=== 打板线组合级（全市场 14:30 ≥9.5% ｜ 可成交子集 ｜ 抽样 43 日 ｜ 次日开盘卖）===")
    df = pd.read_csv(OUT / "t293_P1_hi_rows.csv", dtype={"code": str, "date": str})
    df["code"] = df["code"].str.zfill(6)
    lim = np.array([limit_pct(c) for c in df["code"]])
    df = df[~(df["p1445"].to_numpy() >= df["pc"].to_numpy() * (1 + lim) - 1e-3)].copy()
    days = sorted(df["date"].unique())
    years = (pd.Timestamp(days[-1]) - pd.Timestamp(days[0])).days / 365.25
    print(f"  抽样 {len(days)} 天（{days[0]} → {days[-1]}，跨度 {years:.2f} 年）；"
          f"可成交候选 {len(df)} 条；每日候选中位 {int(np.median(df.groupby('date').size()))} 只")
    print(f"\n  {'方法':<10}{'成本':<6}{'单日均值%':>10}{'胜率%':>7}{'累计%':>9}{'折年化%':>9}"
          f"{'抽样夏普':>9}{'抽样回撤%':>10}")
    res = {}
    for tier in ("20bp", "50bp"):
        st = day_stats(df, tier)
        for key, name in (("top1", "Top1最强"), ("ew", "当日等权")):
            rr = np.array([st[d][key] for d in days])
            nav = np.cumprod(1 + rr)
            ann = nav[-1] ** (1 / years) - 1
            r2 = np.diff(nav) / nav[:-1]
            sh = r2.mean() / r2.std() * np.sqrt(244) if r2.std() > 0 else np.nan
            mdd = float((nav / np.maximum.accumulate(nav) - 1).min())
            print(f"  {name:<10}{tier:<6}{rr.mean()*100:>10.3f}{(rr>0).mean()*100:>7.1f}"
                  f"{(nav[-1]-1)*100:>9.1f}{ann*100:>9.1f}{sh:>9.2f}{mdd*100:>10.2f}")
            res[f"{name}_{tier}"] = {"mean_day_pct": float(rr.mean() * 100),
                                     "win_day": float((rr > 0).mean() * 100),
                                     "total_pct": float((nav[-1] - 1) * 100),
                                     "ann_calendar_pct": float(ann * 100),
                                     "sharpe_sampled": float(sh), "mdd_sampled": float(mdd * 100)}
    a = res["Top1最强_20bp"]; b = res["当日等权_20bp"]
    print(f"\n  Δ（Top1 − 当日等权，20bp）：折算年化 {a['ann_calendar_pct']-b['ann_calendar_pct']:+.2f}pp → "
          f"{'取最强一只【更差】，应走等权/多票' if a['ann_calendar_pct'] < b['ann_calendar_pct'] else '取最强一只更优'}")
    print(f"  50bp 档：Top1 折算年化 {res['Top1最强_50bp']['ann_calendar_pct']:+.2f}% ｜ "
          f"当日等权 {res['当日等权_50bp']['ann_calendar_pct']:+.2f}%")
    out = {"arms": res, "sampled_days": len(days), "span_years": round(years, 2),
           "note": "抽样日口径；年化按日历跨度折算；抽样夏普/回撤只作同口径相对比较，不作绝对业绩申报"}
    (OUT / "valve_p1_portfolio.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("落盘 valve_p1_portfolio.json")
