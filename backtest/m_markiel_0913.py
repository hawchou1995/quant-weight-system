# -*- coding: utf-8 -*-
"""M 组：马尔基尔/绿角范式 A 股实证（2016-01 ~ 2026-09）
M1 全股 B&H（沪深300 一次性买入持有）
M2 月定投（每月首个交易日固定金额买入沪深300，金额加权收益）
M3 60/40 股债年度再平衡（沪深300 × 国债指数 000012）
M4 100/0 年度再平衡（对照）
对照：FB3-H20 2000 池（733.38%/21.95%）已投产基金线
信息集：全部指数收盘价，T 日可得，无前视（ADR-0007 闸）。"""
import numpy as np
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

def load(code, parts=()):
    dfs = []
    for f in [f"index_{code}.csv"] + [f"index_{code}_part{i}.csv" for i in parts]:
        d = pd.read_csv(BASE / f, dtype={"date": str})
        d["date"] = pd.to_datetime(d["date"])
        dfs.append(d.set_index("date")["close"])
    return pd.concat(dfs).sort_index().loc[lambda s: ~s.index.duplicated()]

hs = load("000300").loc["2016-01-01":]
gz = load("000012", parts=(2,)).loc["2016-01-01":]
idx = hs.index.intersection(gz.index)
hs, gz = hs.reindex(idx).ffill(), gz.reindex(idx).ffill()
print(f"窗口 {idx[0].date()} ~ {idx[-1].date()} 交易日 {len(idx)}")
print(f"沪深300 区间涨幅 {hs.iloc[-1]/hs.iloc[0]-1:+.1%} | 国债指数 {gz.iloc[-1]/gz.iloc[0]-1:+.1%}")

out = {}
years = (idx[-1] - idx[0]).days / 365.25

# M1 全股 B&H
out["M1_全股BH"] = {"total": (hs.iloc[-1] / hs.iloc[0] - 1) * 100,
                    "ann": ((hs.iloc[-1] / hs.iloc[0]) ** (1 / years) - 1) * 100,
                    "mdd": ((hs / hs.cummax() - 1).min()) * 100}

# M2 月定投（每月首个交易日 1 万元）
months = hs.groupby(hs.index.to_period("M")).apply(lambda g: g.index[0])
invested, units = 0.0, 0.0
for d in months:
    invested += 10000
    units += 10000 / hs.loc[d]
m2_total = (units * hs.iloc[-1]) / invested - 1
# 金额加权年化（IRR 近似：月供年金公式反解）
n = len(months)
r_m = np.linspace(-0.02, 0.05, 7001)
fv = np.array([sum(10000 * (1 + r) ** ((idx[-1] - d).days / 30.44) for d in months) for r in r_m])
target = units * hs.iloc[-1]
r_irr = r_m[np.argmin(np.abs(fv - target))]
out["M2_月定投"] = {"total": m2_total * 100, "ann_irr": (1 + r_irr) ** 12 - 1 if False else ((1 + r_irr) ** 12 - 1) * 100,
                    "invested": invested / 10000, "final": units * hs.iloc[-1] / 10000}

# M3 60/40 年度再平衡
def rebalance(w_eq):
    v_eq, v_bd, eq_v = 1e6 * w_eq, 1e6 * (1 - w_eq), []
    r_eq, r_bd = hs.pct_change().fillna(0), gz.pct_change().fillna(0)
    for d in idx[1:]:
        i = idx.get_loc(d)
        v_eq *= 1 + r_eq.loc[d]; v_bd *= 1 + r_bd.loc[d]
        if d.month == 12 and d != idx[-1]:
            nxt = idx[i + 1]
            if nxt.year != d.year:  # 年末最后交易日再平衡
                tot = v_eq + v_bd
                v_eq, v_bd = tot * w_eq, tot * (1 - w_eq)
        eq_v.append(v_eq + v_bd)
    s = pd.Series(eq_v, index=idx[1:])
    return s

s6040 = rebalance(0.6)
out["M3_6040再平衡"] = {"total": (s6040.iloc[-1] / 1e6 - 1) * 100,
                        "ann": ((s6040.iloc[-1] / 1e6) ** (1 / years) - 1) * 100,
                        "mdd": ((s6040 / s6040.cummax() - 1).min()) * 100}
s100 = rebalance(1.0)
out["M4_全股年度再平衡"] = {"total": (s100.iloc[-1] / 1e6 - 1) * 100,
                            "ann": ((s100.iloc[-1] / 1e6) ** (1 / years) - 1) * 100,
                            "mdd": ((s100 / s100.cummax() - 1).min()) * 100}

out["_对照_FB3H20_2000池"] = {"total": 733.38, "ann": 21.95, "mdd": -27.03, "sharpe": 1.316}
out["_对照_HS300_BH"] = {"total": out["M1_全股BH"]["total"], "ann": out["M1_全股BH"]["ann"]}

for k, v in out.items():
    if not k.startswith("_"):
        print(k, {kk: round(vv, 2) for kk, vv in v.items()})

import json
json.dump(out, open(BASE / "backtest" / "m_markiel_0913.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
