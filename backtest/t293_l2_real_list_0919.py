# -*- coding: utf-8 -*-
"""R-topic293 Stage 2：忠实臂 L2 —— 平台真实「两点半」名单 48 行上应用原帖规则。

口径（见 PRE-REGISTRATION_20260919_topic293.md）：
  F1: g = P1430/P_prevclose − 1 ∈ [1%, 3%)
  F2: P1445 ≥ P1430 × 0.998
  S : 通过者取 g 最大（并列取代码序）
  入场：T 日 14:45（主）/ 15:00（替代）；出场：T+1 开盘（主）/ T+1 收盘 / T+3 开盘 / T+5 开盘
  收益换算（复权口径）：ret_gross = A_open_{T+1} × p1500_T / (A_close_T × p1445_T) − 1
     A = 前复权日线（data_full）；p = 不复权分时（pytdx）。同日内 k_T 恒定，故用当日比值换算。
  成本：往返 = 2×(滑点+佣金) + 印花；20bp 档 50bp、50bp 档 110bp（17 万单票 → 最低佣金 5 元不生效）
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t293_minute_0919 import pv  # noqa: E402

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
DATA_FULL = BASE / "data_full"
SLIP = {"20bp": 0.0020, "50bp": 0.0050}
COMM, STAMP = 0.00025, 0.0005


def roundtrip_cost(tier):
    return 2 * (SLIP[tier] + COMM) + STAMP


_daily_cache = {}


def daily(code6):
    """前复权日线（data_full），返回 DataFrame(index=date str, open/close)"""
    if code6 in _daily_cache:
        return _daily_cache[code6]
    pre = "sh" if code6[0] in "659" else ("sz" if code6[0] in "0123" else "bj")
    f = DATA_FULL / f"{pre}{code6}.csv"
    d = None
    if f.exists():
        d = pd.read_csv(f, dtype={"date": str})[["date", "open", "close"]]
        d = d.drop_duplicates("date").set_index("date").sort_index()
    _daily_cache[code6] = d
    return d


def limit_pct(code6):
    return 0.20 if code6[:2] in ("30", "68") else 0.10


def run_l2():
    rows = []
    for f in ("backtest/gushi_data/picks_0913.jsonl", "backtest/gushi_data/picks_daily.jsonl"):
        for ln in (BASE / f).read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                if "两点半" in str(r.get("strategy", "")):
                    rows.append(r)
    print(f"L2 名单：{len(rows)} 行 / {len(set(r['date'] for r in rows))} 个交易日")

    recs, miss = [], 0
    for r in rows:
        code, ds = str(r["stock_code"]).zfill(6), r["date"]
        di = int(ds.replace("-", ""))
        m = pv(code, di)
        if not m or not m.get("prev_close"):
            miss += 1
            print(f"  跳过（无分时）{ds} {code} {r['stock_name']}")
            continue
        d = daily(code)
        if d is None or ds not in d.index:
            miss += 1
            print(f"  跳过（无日线）{ds} {code}")
            continue
        pc = m["prev_close"]
        g = m["p1430"] / pc - 1
        f1 = 1.0 <= g * 100 < 3.0
        f2 = m["p1445"] >= m["p1430"] * 0.998
        f3 = m["p1430"] >= pc * (1 + limit_pct(code)) - 1e-6      # 涨跌停守卫：14:30 已封板不可买
        recs.append({"date": ds, "code": code, "name": r["stock_name"], "g": g,
                     "F1": f1, "F2": f2, "limit": f3, "pass": bool(f1 and f2 and not f3),
                     "p1430": m["p1430"], "p1445": m["p1445"], "p1500": m["p1500"], "pc": pc})
    df = pd.DataFrame(recs)
    df.to_csv(BASE / "backtest" / "t293_l2_rows.csv", index=False, encoding="utf-8")
    print(f"取到分时 {len(df)} 行，缺 {miss} 行\n")

    print("=== L2 逐行（g=14:30 涨幅；F1=带内；F2=不回落；limit=封板）===")
    for _, x in df.sort_values(["date", "g"], ascending=[True, False]).iterrows():
        mark = "✔通过" if x["pass"] else ("✗带外" if not x["F1"] else ("✗回落" if not x["F2"] else "✗封板"))
        print(f"  {x['date']} {x['code']} {x['name'][:6]:<7} g={x['g']*100:6.2f}% "
              f"F1={'Y' if x['F1'] else 'n'} F2={'Y' if x['F2'] else 'n'} {mark}")

    # 组合：按日选 Top1
    byday = df[df["pass"]].sort_values(["date", "g"], ascending=[True, False]).groupby("date").head(1)
    print(f"\n=== L2 组合：{len(byday)} 天有票 / {df['date'].nunique()} 天名单 → 空仓 "
          f"{(df['date'].nunique()-len(byday))/df['date'].nunique()*100:.0f}% ===")

    out = {}
    for tier in ("20bp", "50bp"):
        c = roundtrip_cost(tier)
        for xcol, xname in (("p1445", "买14:45"), ("p1500", "买15:00")):
            for hold, yname in ((1, "T+1开盘卖"), (1.5, "T+1收盘卖"), (3, "T+3开盘卖"), (5, "T+5开盘卖")):
                rs, days = [], []
                for _, x in byday.iterrows():
                    d = daily(x["code"])
                    idx = list(d.index)
                    if x["date"] not in idx:
                        continue
                    i = idx.index(x["date"])
                    j = i + (1 if hold == 1 else (3 if hold == 3 else 5))
                    k = i + 1
                    if k >= len(idx):
                        continue
                    A_close_T = float(d["close"].iloc[i])
                    entry_A = A_close_T * (x[xcol] / x["p1500"])
                    if yname == "T+1收盘卖":
                        exit_A = float(d["close"].iloc[k])
                    else:
                        if k + (j - k) >= len(idx):
                            continue
                        exit_A = float(d["open"].iloc[k + (j - k)])
                    gross = exit_A / entry_A - 1
                    rs.append(gross - c)
                    days.append(x["date"])
                if rs:
                    arr = np.array(rs)
                    out[f"{tier}|{xname}|{yname}"] = {
                        "n": len(arr), "mean_pct": float(arr.mean() * 100),
                        "med_pct": float(np.median(arr) * 100),
                        "win": float((arr > 0).mean() * 100),
                        "sum_pct": float(arr.sum() * 100)}
    print(f"\n=== L2 组合收益（往返成本已扣；n 为交易日数）===")
    print(f"  {'档位':<6}{'执行':<9}{'出场':<12}{'n':>3}{'笔均%':>9}{'中位%':>9}{'胜率%':>8}{'累计%':>10}")
    for k, v in out.items():
        t, x, y = k.split("|")
        print(f"  {t:<6}{x:<9}{y:<12}{v['n']:>3}{v['mean_pct']:>9.3f}{v['med_pct']:>9.3f}"
              f"{v['win']:>8.1f}{v['sum_pct']:>10.2f}")
    (BASE / "backtest" / "t293_l2_summary.json").write_text(
        json.dumps({"byday": byday.to_dict("records"), "results": out}, ensure_ascii=False, indent=1,
                   default=str), encoding="utf-8")
    print(f"\n落盘：backtest/t293_l2_rows.csv / t293_l2_summary.json")


if __name__ == "__main__":
    run_l2()
