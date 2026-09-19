# -*- coding: utf-8 -*-
"""KHunter 组合级（真口径）：N=5 槽 · 2 万/仓 · T+1 开盘买 → 持 20 交易日 → 第 21 日开盘卖 ·
逐日 mark 净值（用不复权/前复权自洽：只用 data_full 前复权价做全程记账）· 整手 · 现金闲置如实计入。

对照：B0 无阀 vs V2（信号日尾盘回落 >0.2% 者次日不买 → 不满仓）。
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest"
DATA_FULL = BASE / "data_full"
CASH0, PER_SLOT, N_SLOTS, HOLD = 100000.0, 20000.0, 5, 20
COMM, TAX, SLIP, MIN_COMM = 0.00025, 0.0005, 0.0020, 5.0


def px(code, kind="open"):
    pre = "sh" if code[0] in "659" else "sz"
    f = DATA_FULL / f"{pre}{code}.csv"
    if not f.exists():
        return None
    d = pd.read_csv(f, dtype={"date": str})[["date", kind]].set_index("date").sort_index()
    return d[kind]


def sim(rows, tag):
    codes = sorted(set(rows["code"]))
    pxo = {c: px(c, "open") for c in codes}
    pxc = {c: px(c, "close") for c in codes}
    cal = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})["date"].tolist()
    byday = {}
    for x in rows.to_dict("records"):
        byday.setdefault(x["date"], []).append(x)
    pos, cash, navs, dates = [], CASH0, [], []
    n_trades, skipped_cash, skipped_slots = 0, 0, 0
    for di in range(1, len(cal)):
        d, prev = cal[di], cal[di - 1]
        # 出场（到期日 = 入场后第 20 个交易日 → 此处按持仓计数简化：holding_days>=HOLD 时在当日开盘卖）
        keep = []
        for p in pos:
            p["held"] += 1
            if p["held"] >= HOLD:
                s = pxc[p["code"]]
                if s is not None and d in s.index:
                    sell_px = float(pxo[p["code"]][d]) * (1 - SLIP)
                    amt = p["sh"] * sell_px
                    cash += amt - max(amt * COMM, MIN_COMM) - amt * TAX
                    n_trades += 1
                else:
                    keep.append(p)      # 停牌顺延
            else:
                keep.append(p)
        pos = keep
        # 入场（信号日 = prev，执行 = 当日开盘）
        for x in byday.get(prev, []):
            o = pxo.get(x["code"])
            if o is None or d not in o.index:
                continue
            buy = float(o[d]) * (1 + SLIP)
            if buy <= 0:
                continue
            if len(pos) >= N_SLOTS:
                skipped_slots += 1
                continue
            lots = int(np.floor(min(PER_SLOT, cash) / (buy * 100)))
            if lots < 1:
                skipped_cash += 1
                continue
            amt = lots * 100 * buy
            fee = max(amt * COMM, MIN_COMM)
            if amt + fee > cash:
                lots -= 1
                if lots < 1:
                    skipped_cash += 1
                    continue
                amt = lots * 100 * buy
                fee = max(amt * COMM, MIN_COMM)
            cash -= (amt + fee)
            pos.append({"code": x["code"], "sh": lots * 100, "held": 0})
        mv = 0.0
        for p in pos:
            s = pxc[p["code"]]
            mv += p["sh"] * (float(s[d]) if s is not None and d in s.index else 0.0)
        navs.append(cash + mv)
        dates.append(d)
    nav = pd.Series(navs, index=pd.to_datetime(dates))
    nav = nav[nav.index >= pd.Timestamp("2021-01-04")]
    ret = nav.pct_change().dropna()
    yrs = len(nav) / 244.0
    ann = (nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1
    sh = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    mdd = float((nav / nav.cummax() - 1).min())
    invest = []
    # 现金闲置率：重放一次记录 invested 比例
    print(f"  {tag:<14} 期末净值 {nav.iloc[-1]/CASH0:>6.3f}  年化 {ann*100:>6.2f}%  夏普 {sh:>5.2f}  "
          f"最大回撤 {mdd*100:>6.2f}%  成交 {n_trades:>4} 笔  因满仓跳过 {skipped_slots} 因现金不足跳过 {skipped_cash}")
    return {"ann_pct": float(ann * 100), "sharpe": float(sh), "mdd_pct": float(mdd * 100),
            "n_trades": n_trades, "skipped_slots": skipped_slots, "skipped_cash": skipped_cash,
            "final_nav": float(nav.iloc[-1] / CASH0)}


if __name__ == "__main__":
    d = pd.read_csv(OUT / "valve_kh_rows.csv", dtype={"code": str, "date": str})
    d = d[np.isfinite(d["fwd20"].to_numpy())].copy()
    res = {}
    print("=== KHunter 组合级（真口径：N=5 · 2万/仓 · 持 20 日 · 20bp 滑点 · 整手 · 17万→10万起点对比用 10 万）===")
    res["B0 无阀"] = sim(d, "B0 无阀")
    res["V2 不弱门"] = sim(d[d["pull"] >= -0.002], "V2 不弱门")
    (OUT / "valve_kh_portfolio.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    b, v = res["B0 无阀"], res["V2 不弱门"]
    print(f"\n  Δ年化 {v['ann_pct']-b['ann_pct']:+.2f}pp ｜ Δ夏普 {v['sharpe']-b['sharpe']:+.3f} ｜ "
          f"Δ回撤 {v['mdd_pct']-b['mdd_pct']:+.2f}pp")
    print("  门槛（Q5）：Δ年化 ≥ −1pp 且（Δ夏普 ≥ +0.02 或 回撤改善 ≥ 3pp）→ "
          f"{'PASS' if (v['ann_pct']-b['ann_pct'] >= -1) and (v['sharpe']-b['sharpe'] >= 0.02 or v['mdd_pct']-b['mdd_pct'] >= 3) else 'FAIL'}")
