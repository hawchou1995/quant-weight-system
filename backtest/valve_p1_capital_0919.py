# -*- coding: utf-8 -*-
"""打板线可投产口径复核：17 万本金 · 整手 · 每日最多 N 只 · 20bp · 次日开盘卖。

上一轮 +25.8%/年 的隐含假设是"当日等权买全部候选（中位 20 只/日）"—— 按 17 万本金、
每只等额只能分 8500 元，会撞**整手墙**（项目已有实测：轨B 850/只 → 年化 7.47%）。
本脚本按真实资金重算，并给出「最多买 K 只」的 K 敏感性。
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t293_eval_0919 import rets_for, code_idx  # noqa: E402
from t293_l2_real_list_0919 import limit_pct, daily  # noqa: E402

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest"
CAPITAL = 170000.0
COMM, TAX, SLIP, MIN_COMM = 0.00025, 0.0005, 0.0020, 5.0
COST = 2 * (SLIP + COMM) + TAX        # 往返 50bp（20bp 档）


def lots_for(budget, px):
    n = int(np.floor(min(budget, 1e12) / (px * (1 + SLIP) * 100)))
    return n * 100, n * 100 * px * (1 + SLIP) + max(n * 100 * px * (1 + SLIP) * COMM, MIN_COMM)


def run(df, tier, K, order="g"):
    """当日最多买 K 只（按 g 降序）；整手；钱不够就少买；返回按天序列。"""
    rows = df.to_dict("records")
    r = rets_for(rows, "p1445", "t1o")
    tmp = pd.DataFrame({"code": df["code"].values, "date": df["date"].values,
                        "g": df["g"].values, "r": r})
    c = COST if tier == "20bp" else 2 * (0.005 + COMM) + TAX
    day_ret, bought, n_days_with = [], [], []
    for d, sub in sorted(tmp.groupby("date"), key=lambda kv: kv[0]):
        sub = sub.sort_values(order, ascending=False).head(K)
        per = CAPITAL / K
        spent, rets = 0.0, []
        for _, x in sub.iterrows():
            ci = code_idx(x["code"])
            if ci is None:
                continue
            px = float(x["r"] if False else 0)  # 占位
            # 入场价用 T+1 开盘（出场口径为 T+1 开盘卖 → 实为买入当日尾盘、次日开盘卖；
            # 但 r 的收益是 "买T日14:45→卖T+1开盘"，故这里仓位按 CAPITAL/K 等额分配即可，
            # 整手约束用 14:45 价估算一手成本
            p1445 = None
            from t293_minute_0919 import pv
            m = pv(x["code"], int(d.replace("-", "")))
            if not m:
                continue
            p1445 = m["p1445"]
            sh, cost = lots_for(per, p1445)
            if sh <= 0 or spent + cost > CAPITAL:
                continue
            spent += cost
            rets.append(x["r"] - c)
        if rets:
            day_ret.append(float(np.mean(rets)) * (spent / CAPITAL))    # 按实际投入比例缩放
            bought.append(len(rets))
        else:
            day_ret.append(0.0)
            bought.append(0)
    days = sorted(tmp["date"].unique())
    rr = np.array(day_ret)
    years = (pd.Timestamp(days[-1]) - pd.Timestamp(days[0])).days / 365.25
    nav = np.cumprod(1 + rr)
    ann = nav[-1] ** (1 / years) - 1
    print(f"  K={K:<3}{tier:<6} 日均值 {rr.mean()*100:>7.3f}%  胜率 {(rr>0).mean()*100:>5.1f}%  "
          f"日均买入 {np.mean(bought):>4.1f} 只  累计 {(nav[-1]-1)*100:>7.1f}%  "
          f"**折算年化 {ann*100:>6.1f}%**  抽样夏普 {(np.diff(nav)/nav[:-1]).mean()/max((np.diff(nav)/nav[:-1]).std(),1e-12)*np.sqrt(244):>6.2f}")


if __name__ == "__main__":
    print("=== 打板线 · 17 万本金 · 整手 · 每日最多 K 只 · 次日开盘卖（金额按实际投入比例缩放）===")
    print("（候选已剔除 14:45 封板者；抽样 39 天 / 2.04 年）")
    df = pd.read_csv(OUT / "t293_P1_hi_rows.csv", dtype={"code": str, "date": str})
    df["code"] = df["code"].str.zfill(6)
    lim = np.array([limit_pct(c) for c in df["code"]])
    df = df[~(df["p1445"].to_numpy() >= df["pc"].to_numpy() * (1 + lim) - 1e-3)].copy()
    print(f"  每日可成交候选中位 {int(np.median(df.groupby('date').size()))} 只 ｜ 每只等额预算 = 17万/K\n")
    for K in (5, 8, 10, 20):
        for tier in ("20bp",):
            run(df, tier, K)
    print("\n  说明：'折算年化'按日历跨度折算；整手墙会随 K 变小而减轻（17万/5=3.4万/只 → 高价票也买得起一手）；")
    print("  K 越大越接近「当日等权」上界，但越受整手与单只最小资金约束。")
