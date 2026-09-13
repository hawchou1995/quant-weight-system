# -*- coding: utf-8 -*-
"""五条选股规则回测（知乎@静水2008 规则，用户提供量化规格）（2026-09-12）
================================================================
规格：主板（剔 ST/上市<180日/停牌），2021-01-04 至今；买入=①盈利 ②营收同比≥40%
③收盘≥252日最高×0.98 ④新产品代理 ⑤强供求代理 同时满足；卖出=基本面恶化 +
硬止损-8% + 追踪止损-12% + 跌破MA20；T 收盘信号 → T+1 开盘；≤5 只等权（各≤20%）；
基准 HS300；滑点 0/20bps。
ADR-0005 口径降级：扣非→净利润代理；条件④缺数据未测；条件⑤合同负债缺→毛利率同比+2pp 单腿；
PIT=法定披露截止日（Q1→4/30 H1→8/31 Q3→10/31 FY→次年4/30）；ST=报告期当时简称。
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
DATA = BASE / "data_full"
R2 = BASE / "backtest" / "r2_rebuild_0911"
START = pd.Timestamp("2021-01-04")
COMM, TAX = 0.00025, 0.0005
CASH0 = 1_000_000.0
MAX_POS = 5
AVAIL = {"0331": (4, 30), "0630": (8, 31), "0930": (10, 31), "1231": (4, 30)}
HARD_STOP, TRAIL_STOP = 0.92, 0.88


def avail_date(period: str):
    """法定披露截止日 = PIT 可得日（ADR-0005：Q1→4/30 H1→8/31 Q3→10/31 FY→次年4/30）"""
    y, md = int(period[:4]), period[4:]
    m, d = AVAIL[md]
    if md == "1231":
        y += 1
    return pd.Timestamp(y, m, d)

t_load = time.time()
q = pd.read_csv(BASE / "data_fundamental" / "yjbb_quarterly.csv", dtype={"股票代码": str})
q["股票代码"] = q["股票代码"].str.strip()
q = q[q["股票代码"].str.match(r"^(000|001|002|003|600|601|603|605)")].copy()
q["is_st"] = q["股票简称"].astype(str).str.contains("ST", na=False)
for col, out in [("营业总收入-同比增长", "rev_yoy"), ("净利润-净利润", "np"), ("销售毛利率", "gm")]:
    q[out] = pd.to_numeric(q[col], errors="coerce")
q["avail"] = q["REPORT_PERIOD"].astype(str).map(avail_date)
q = q.sort_values(["股票代码", "REPORT_PERIOD"])
q["gm_yoy_chg"] = q.groupby("股票代码")["gm"].diff(4)
q["gm_down"] = q["gm_yoy_chg"] < 0
q["gm_down_2"] = q.groupby("股票代码")["gm_down"].transform(lambda s: s & s.shift(1).fillna(False))

FUND, ST_SET = {}, {}
for code, g in q.groupby("股票代码"):
    FUND[code] = list(zip(g["avail"], g["REPORT_PERIOD"], g["rev_yoy"], g["np"],
                          g["gm_yoy_chg"], g["gm_down_2"]))
    ST_SET[code] = set(g.loc[g["is_st"], "REPORT_PERIOD"])

idx = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
idx["date"] = pd.to_datetime(idx["date"])
idx = idx.set_index("date").sort_index()
ALL_DAYS = [d for d in idx.index if START <= d]
DAY_POS = {d: i for i, d in enumerate(ALL_DAYS)}

PX = {}
for f in sorted(DATA.glob("*.csv")):
    code = f.stem
    if not (code.startswith("sh60") or code.startswith("sz00")):
        continue
    try:
        df = pd.read_csv(f, usecols=["date", "open", "close"], dtype={"date": str})
    except Exception:
        continue
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < 260:
        continue
    c = df["close"].to_numpy(float)
    PX[code] = dict(
        o=df["open"].to_numpy(float), c=c,
        ma20=pd.Series(c).rolling(20, min_periods=20).mean().to_numpy(),
        hh=pd.Series(c).rolling(252, min_periods=252).max().to_numpy(),
        pos=np.array([DAY_POS.get(d, -1) for d in df["date"]], dtype=np.int64),
        dates=df["date"].to_numpy(),
        first180=np.datetime64(df["date"].iloc[0] + pd.Timedelta(days=180)),
        dates64=df["date"].to_numpy(dtype="datetime64[ns]"),
    )
print(f"[load] 基本面 {len(FUND)} 只 / 行情 {len(PX)} 只 ({time.time()-t_load:.0f}s)", flush=True)

DATES_IDX = {c: pd.DatetimeIndex(PX[c]["dates"]) for c in PX}


def find_k(a, day):
    """全局日 → 该股票 bar 序号（无当日 bar 返回 -1）"""
    i = np.searchsorted(a["dates64"], np.datetime64(day))
    if i < len(a["dates64"]) and a["dates64"][i] == np.datetime64(day):
        return i
    return -1


def fund_state(code, day64):
    recs = FUND.get(code)
    if not recs:
        return None
    lo, hi, best = 0, len(recs) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if np.datetime64(recs[mid][0]) <= day64:
            best = recs[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def day_pos_lookup(day):
    return DAY_POS[day]


def run(slip=0):
    cash = CASH0
    holdings = {}       # code -> dict(sh, ep, peak, period)
    pending_sell = {}   # code -> reason
    pending_buy = []
    last_close = {}
    trades_ep = {}
    eq, trades, reason_cnt = [], [], {}
    for day in ALL_DAYS:
        d64 = np.datetime64(day)
        # 卖出（开盘）
        for code in list(pending_sell.keys()):
            if code not in holdings:
                pending_sell.pop(code, None)
                continue
            a = PX[code]
            k = find_k(a, day)
            if k < 0:
                continue
            px_eff = a["o"][k] * (1 - slip / 10000)
            sh = holdings.pop(code)["sh"]
            cash += sh * px_eff * (1 - COMM) - sh * px_eff * TAX
            trades.append({"code": code, "exit": str(day.date()),
                           "ret_pct": (px_eff / trades_ep.pop(code) - 1) * 100,
                           "reason": pending_sell.pop(code)})
        # 买入（开盘）
        for code in pending_buy:
            if len(holdings) >= MAX_POS or code in holdings or code in pending_sell:
                continue
            a = PX[code]
            k = find_k(a, day)
            if k < 0:
                continue
            px_eff = a["o"][k] * (1 + slip / 10000)
            pv = cash + sum(s * last_close.get(cc, h["ep"]) for cc, s, h in
                            ((cc, h["sh"], h) for cc, h in holdings.items()))
            budget = pv / MAX_POS
            nl = int(min(budget, cash) / (px_eff * 100 * (1 + COMM)))
            if nl < 1:
                continue
            sh = nl * 100
            cost = sh * px_eff * (1 + COMM)
            if cost > cash:
                nl = int(cash / (px_eff * 100 * (1 + COMM)))
                if nl < 1:
                    continue
                sh = nl * 100
                cost = sh * px_eff * (1 + COMM)
            cash -= cost
            holdings[code] = {"sh": sh, "ep": px_eff, "peak": px_eff, "period": None}
            trades_ep[code] = px_eff
            last_close[code] = px_eff
        pending_buy = []

        # 收盘检查
        for code in list(holdings.keys()):
            a = PX[code]
            k = find_k(a, day)
            if k < 0:
                continue
            c = a["c"][k]
            if not np.isfinite(c):
                continue
            last_close[code] = c
            h = holdings[code]
            if c > h["peak"]:
                h["peak"] = c
            reason = ""
            st = fund_state(code[2:], d64)
            if st:
                _, period, rev_yoy, np_, _, gm_down2 = st
                if h["period"] is None:
                    h["period"] = period
                elif period != h["period"]:
                    if np.isfinite(rev_yoy) and rev_yoy < 15:
                        reason = "基本面:营收<15%"
                    elif np.isfinite(np_) and np_ <= 0:
                        reason = "基本面:转亏"
                    elif gm_down2:
                        reason = "基本面:毛利率连两季降"
                    h["period"] = period
            if not reason:
                if c <= h["ep"] * HARD_STOP:
                    reason = "硬止损-8%"
                elif c <= h["peak"] * TRAIL_STOP:
                    reason = "追踪止损-12%"
                elif np.isfinite(a["ma20"][k]) and c < a["ma20"][k]:
                    reason = "跌破MA20"
            if reason and code not in pending_sell:
                pending_sell[code] = reason
                reason_cnt[reason] = reason_cnt.get(reason, 0) + 1
        # 买入信号
        if len(holdings) < MAX_POS:
            cands = []
            for code, a in PX.items():
                if code in holdings or code in pending_sell:
                    continue
                k = find_k(a, day)
                if k < 252:
                    continue
                if a["dates64"][k] < a["first180"]:
                    continue
                st = fund_state(code[2:], d64)
                if not st or code in ST_SET.get(code[2:], set()):
                    continue
                _, period, rev_yoy, np_, gm_chg, _ = st
                c0 = a["c"][k]
                hh = a["hh"][k]
                if not (np.isfinite(rev_yoy) and rev_yoy >= 40):
                    continue
                if not (np.isfinite(np_) and np_ > 0):
                    continue
                if not (np.isfinite(hh) and c0 >= hh * 0.98):
                    continue
                if not (np.isfinite(gm_chg) and gm_chg >= 2.0):
                    continue
                cands.append((rev_yoy if np.isfinite(rev_yoy) else 0, code))
            cands.sort(reverse=True)
            pending_buy = [c for _, c in cands[:MAX_POS - len(holdings)]]
        # 净值
        pv = cash
        for code, h in holdings.items():
            pv += h["sh"] * last_close.get(code, h["ep"])
        eq.append({"date": str(day.date()), "value": pv})
    return pd.DataFrame(eq), trades, reason_cnt


def stats(eqdf, trades, name):
    eqdf = eqdf.copy()
    eqdf["date"] = pd.to_datetime(eqdf["date"])
    eqdf = eqdf.set_index("date")
    v = eqdf["value"]
    r = v.pct_change().fillna(0)
    total = v.iloc[-1] / v.iloc[0] - 1
    ann = (1 + total) ** (252 / max(1, len(v))) - 1
    dd = (v / v.cummax() - 1).min()
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
    rets = [t["ret_pct"] for t in trades if np.isfinite(t["ret_pct"])]
    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x <= 0]
    payoff = (np.mean(wins) / abs(np.mean(losses))) if wins and losses else np.nan
    y = (1 + r).groupby(r.index.year).prod() - 1
    return {"name": name, "total_pct": round(total * 100, 2), "ann_pct": round(ann * 100, 2),
            "mdd_pct": round(dd * 100, 1), "sharpe": round(float(sharpe), 3),
            "n_trades": len(trades),
            "win_rate": round(len(wins) / len(rets) * 100, 1) if rets else 0,
            "payoff": round(float(payoff), 2) if np.isfinite(payoff) else None,
            "yearly": {str(k): round(vv * 100, 1) for k, vv in y.items()}}


if __name__ == "__main__":
    t0 = time.time()
    out = {}
    for slip in (0, 20):
        tr_ep = {}
        eq, trades, reasons = run(slip)
        s = stats(eq, trades, f"slip{slip}")
        s["reasons"] = reasons
        out[f"slip{slip}"] = s
        eq.to_csv(R2 / f"5rules_eq_slip{slip}.csv", index=False, encoding="utf-8")
        pd.DataFrame(trades).to_csv(R2 / f"5rules_trades_slip{slip}.csv", index=False, encoding="utf-8")
        print(f"[slip{slip}] 总 {s['total_pct']}% | 年化 {s['ann_pct']}% | 回撤 {s['mdd_pct']}% | "
              f"夏普 {s['sharpe']} | {s['n_trades']}笔 胜率{s['win_rate']}% 盈亏比{s['payoff']}", flush=True)
        print(f"  卖出原因: {reasons}", flush=True)
        print(f"  年度: {s['yearly']}", flush=True)
    hs = (idx.loc[START:, "close"])
    bt = hs.iloc[-1] / hs.iloc[0] - 1
    out["benchmark_HS300"] = {"total_pct": round(bt * 100, 2),
                              "date_range": [str(hs.index[0].date()), str(hs.index[-1].date())]}
    print(f"[基准 HS300] {out['benchmark_HS300']['total_pct']}%", flush=True)
    json.dump(out, open(R2 / "5rules_backtest_0912.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"[done] {time.time()-t0:.0f}s", flush=True)
