# -*- coding: utf-8 -*-
"""打板尾盘强势线 · 模拟盘记账（R-valve-0919d 投产准备 · 步骤 2/3）

口径（与预注册/回测一致，**成本用 100bp 保守档**）：
  · 买：T 日 14:45 价 × (1 + 100bp 滑点) + 佣金 max(2.5bp, 5 元)
  · 卖：T+1 开盘价 × (1 − 100bp 滑点) − 佣金 max(2.5bp, 5 元) − 印花 5bp
  · 整手 100 股；每只预算 = 17 万 / K（K=10）；买不起一手/现金不足 → 跳过（**预算不重分配**）
  · 每日最多 K 只；不买则当日空仓（计 0）
  · 幂等：同一天重复跑不重复记（按 date 去重）

运行时刻：由 15:30 收盘链调用（T+1 当天），此时 T 的信号文件与 T+1 开盘价均已知。
产出：`backtest/tailstrong_paper.json`（cash/fills/nav_history/events）
"""
import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
HERE = Path(__file__).resolve().parent
SIG = HERE / "tailstrong_signal.json"
STATE = HERE / "tailstrong_paper.json"
DATA_FULL = BASE / "data_full"
CAPITAL, K_SLOTS = 170000.0, 10
COMM, TAX, SLIP, MIN_COMM = 0.00025, 0.0005, 0.0100, 5.0     # 100bp 保守档
t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)


def daily_px(code):
    pre = "sh" if code[0] in "659" else "sz"
    f = DATA_FULL / f"{pre}{code}.csv"
    if not f.exists():
        return None
    d = pd.read_csv(f, dtype={"date": str})[["date", "open", "close", "amount"]]
    return d.drop_duplicates("date").set_index("date").sort_index()


def next_trade_date(code, after):
    d = daily_px(code)
    if d is None:
        return None
    for dt in d.index:
        if dt > after:
            return dt
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--signal-date", default=None, help="手工指定信号日期（默认取信号文件里的）")
    a = ap.parse_args()

    if not SIG.exists():
        print(f"[跳过] 无信号文件 {SIG.name}（尚未到过信号窗口，或当日无候选）")
        return 0
    sig = json.loads(SIG.read_text(encoding="utf-8"))
    sdate = a.signal_date or sig["date"]
    cands = [c for c in sig["candidates"]][:K_SLOTS]
    if not cands:
        print(f"[跳过] {sdate} 信号为空（无通过标的 → 当日空仓，符合策略）")
        return 0

    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {
        "meta": {"started": sdate, "basis": CAPITAL, "k_slots": K_SLOTS,
                 "cost": "往返 210bp（100bp 滑点 + 佣金 2.5bp/最低5元 + 印花 5bp）",
                 "strategy": "T日14:30涨幅≥9.5% 且 14:45未封板 → 14:45买 → T+1开盘卖"},
        "cash": CAPITAL, "positions": {}, "fills": [], "events": [], "nav_history": []}
    done = {f["signal_date"] for f in st["fills"]}
    if sdate in done:
        print(f"[幂等] {sdate} 已记过（{len([f for f in st['fills'] if f['signal_date']==sdate])} 笔），跳过")
        return 0

    per = CAPITAL / K_SLOTS
    cash = float(st["cash"])
    fills, skipped = [], []
    for c in cands:
        code = c["code"]
        d = daily_px(code)
        if d is None:
            skipped.append((code, "无日线"))
            continue
        nd = next_trade_date(code, sdate)
        if nd is None:
            skipped.append((code, "无T+1交易日"))
            continue
        o1 = float(d.loc[nd, "open"])
        c0 = float(d["close"].iloc[d.index.get_loc(sdate)]) if sdate in d.index else None
        if c0 is None or c0 <= 0:
            skipped.append((code, "无T日收盘"))
            continue
        # ⚠ 复权口径（2026-09-20 修）：p1445 来自 pytdx **不复权**分时，而 o1/c0 来自 data_full **前复权**日线。
        #    直接 p1445×1.01 与 o1×0.99 相减 = 两把尺子混用，实测每笔多算 2.7pp 成本（假成本）。
        #    正解：用**同日比值**把 14:45 价换算到前复权尺子 —— 与回测口径逐位一致：
        #        entry_A = c0 × (p1445 / p1500)，sell_A = o1
        #    p1500 = T 日 15:00 收盘（信号文件里带；老信号没有则用 c0 自身 = 当天已收盘的情形）
        p1500 = float(c.get("p1500") or c0)
        entry_A = c0 * (c["p1445"] / p1500) if p1500 > 0 else c["p1445"]
        buy = entry_A * (1 + SLIP)
        sell = o1 * (1 - SLIP)
        lots = int(per // (buy * 100))
        if lots < 1:
            skipped.append((code, f"买不起一手（需 {buy*100:.0f} > 预算 {per:.0f}）"))
            continue
        gross = lots * 100 * buy
        fee_b = max(gross * COMM, MIN_COMM)
        if gross + fee_b > cash:
            lots -= 1
            if lots < 1:
                skipped.append((code, "现金不足"))
                continue
            gross = lots * 100 * buy
            fee_b = max(gross * COMM, MIN_COMM)
        proceeds = lots * 100 * sell
        fee_s = max(proceeds * COMM, MIN_COMM) + proceeds * TAX
        ret = (proceeds - fee_s) / (gross + fee_b) - 1
        cash += proceeds - fee_s - gross - fee_b
        fills.append({"signal_date": sdate, "exec_date": nd, "code": code, "name": c["name"],
                      "g1430": c["g"], "buy_px": round(buy, 4), "sell_px": round(sell, 4),
                      "shares": lots * 100, "amount": round(gross + fee_b, 2),
                      "ret": round(ret, 6), "ret_pct": round(ret * 100, 3)})
    if a.dry:
        print("\n=== DRY：不落盘 ===")
        for f in fills:
            print(f"  {f['signal_date']}→{f['exec_date']} {f['code']} {f['name'][:6]:<8} "
                  f"买 {f['buy_px']:>8.2f} 卖 {f['sell_px']:>8.2f} {f['shares']:>6}股  "
                  f"**{f['ret_pct']:+.3f}%**")
        print(f"  跳过：{skipped}")
        return 0
    st["fills"].extend(fills)
    st["events"].append({"date": sdate, "n": len(fills), "skipped": skipped,
                         "mean_ret_pct": round(sum(f["ret_pct"] for f in fills) / len(fills), 3) if fills else None})
    nav = cash
    st["nav_history"].append({"date": sdate, "exec": fills[0]["exec_date"] if fills else None,
                              "cash": round(cash, 2), "nav": round(nav, 2), "n": len(fills),
                              "mean_ret_pct": round(sum(f["ret_pct"] for f in fills) / len(fills), 3) if fills else 0.0})
    st["cash"] = round(cash, 2)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"记 {len(fills)} 笔（跳过 {len(skipped)}）→ {STATE.name}")
    for f in fills:
        print(f"  {f['signal_date']}→{f['exec_date']} {f['code']} {f['name'][:6]:<8} "
              f"买 {f['buy_px']:>8.2f} 卖 {f['sell_px']:>8.2f} {f['shares']:>6}股  {f['ret_pct']:+.3f}%")
    if skipped:
        print(f"  跳过明细：{skipped}")
    tot = sum(f["ret_pct"] for f in st["fills"])
    print(f"\n  累计 {len(st['fills'])} 笔｜笔均 {tot/len(st['fills']):+.3f}%｜"
          f"期末现金 {st['cash']:.2f} / {CAPITAL:.0f} = {st['cash']/CAPITAL-1:+.2%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
