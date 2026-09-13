# -*- coding: utf-8 -*-
"""纳次H × 止盈止损组合矩阵（2026-09-12）
================================================================
用户提案：纳次H 风险预警 + 黄金分割等止盈止损策略搭配。
载体：A=流动性10只月度中性载体（无信号，测退出纯效应）；B=五条规则成长追高载体（ADR-0005）。
退出变体（全部 T+1 开盘，叠加在基线上）：
  E0 基线：MA20破位 + 硬止损8% + 最大持有60日
  E1 = E0 + 个股纳次H止盈（该股触发 GR1|GR2|FH → 次日开盘卖）
  E2 = E0 + 组合级 breadth q95 清仓（扩展窗分位，r1 口径）
  E3 = E0 + 黄金分割 0.382 回撤止盈
  E4 = E0 + 黄金分割 0.500
  E5 = E0 + 黄金分割 0.618
  E6 = E1 + E2
  E7 = E1 + E3(0.5)
黄金分割止盈：持仓期高点 H、低点 L（均自入场收盘起算），仅当 H>ep×1.05（有浮盈）且
  close ≤ H − φ×(H−L) 时离场。
成本：佣金 2.5bp×2 + 印花税 5bp + 滑点 20bps（双侧）；另有 0 滑点对照在报告解读。
"""
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
DATA = BASE / "data_full"
R2 = BASE / "backtest" / "r2_rebuild_0911"
START = pd.Timestamp("2021-01-04")
COMM, TAX, SLIP = 0.00025, 0.0005, 0.0020
CASH0 = 1_000_000.0
MAX_POS = 5
AVAIL = {"0331": (4, 30), "0630": (8, 31), "0930": (10, 31), "1231": (4, 30)}

t0 = time.time()


def avail_date(period):
    y, md = int(str(period)[:4]), str(period)[4:]
    m, d = AVAIL[md]
    return pd.Timestamp(y + (1 if md == "1231" else 0), m, d)


# ---------- 基本面（载体B用，ADR-0005 口径） ----------
q = pd.read_csv(BASE / "data_fundamental" / "yjbb_quarterly.csv", dtype={"股票代码": str})
q["股票代码"] = q["股票代码"].str.strip()
q = q[q["股票代码"].str.match(r"^(000|001|002|003|600|601|603|605)")].copy()
q["is_st"] = q["股票简称"].astype(str).str.contains("ST", na=False)
q["rev_yoy"] = pd.to_numeric(q["营业总收入-同比增长"], errors="coerce")
q["np"] = pd.to_numeric(q["净利润-净利润"], errors="coerce")
q["gm"] = pd.to_numeric(q["销售毛利率"], errors="coerce")
q["avail"] = q["REPORT_PERIOD"].astype(str).map(avail_date)
q = q.sort_values(["股票代码", "REPORT_PERIOD"])
q["gm_chg"] = q.groupby("股票代码")["gm"].diff(4)
FUND, ST_SET = {}, {}
for code, g in q.groupby("股票代码"):
    FUND[code] = list(zip(g["avail"], g["REPORT_PERIOD"], g["rev_yoy"], g["np"], g["gm_chg"]))
    ST_SET[code] = set(g.loc[g["is_st"], "REPORT_PERIOD"])

idx = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
idx["date"] = pd.to_datetime(idx["date"])
idx = idx.set_index("date").sort_index()
ALL_DAYS = [d for d in idx.index if START <= d]
ND = len(ALL_DAYS)
ALL_D64 = np.array(ALL_DAYS, dtype="datetime64[ns]")
HS300_TOTAL = (idx.loc[ALL_DAYS, "close"].iloc[-1] / idx.loc[ALL_DAYS, "close"].iloc[0] - 1) * 100

# breadth（r1 产物）
bd = pd.read_csv(BASE / "backtest" / "naci_sentiment_0911_out" / "breadth_daily.csv", parse_dates=["date"]).set_index("date")
b3 = bd["breadth"].reindex(idx.index).ffill().rolling(3, min_periods=3).mean()
q95 = b3.expanding(min_periods=250).quantile(0.95)
BREADTH_ON = (b3 > q95).fillna(False)          # 组合级清仓触发
breadth_map = BREADTH_ON.reindex(ALL_DAYS).fillna(False).to_numpy()

# ---------- 行情 + 个股纳次H RISK ----------
YZ_ALL = (lambda ic: ic["close"] / ic["close"].rolling(60).mean())(
    pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
    .pipe(lambda d: (d.__setitem__("date", pd.to_datetime(d["date"])), d.set_index("date").sort_index())[1]))
codes, stock = [], {}
for f in sorted(DATA.glob("*.csv")):
    code = f.stem
    if not (code.startswith("sh60") or code.startswith("sz00")):
        continue
    try:
        df = pd.read_csv(f, usecols=["date", "open", "close", "high", "low",
                                     "volume", "amount"], dtype={"date": str})
    except Exception:
        continue
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < 420:
        continue
    c = df["close"].to_numpy(float)
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    v = df["volume"].to_numpy(float)
    amo = df["amount"].to_numpy(float)
    ma20 = pd.Series(c).rolling(20, min_periods=20).mean().to_numpy()
    amt20 = pd.Series(amo).rolling(20, min_periods=20).mean().to_numpy()
    # 纳次H（r1 忠实口径）
    vc = v * c

    def wavg(x, y, n):
        a = pd.Series(x).rolling(n, min_periods=n).sum().to_numpy()
        b = pd.Series(y).rolling(n, min_periods=n).sum().to_numpy()
        out = np.full(len(y), np.nan)
        np.divide(a, b, out=out, where=b > 0)
        return out

    jx = wavg(vc, v, 60); jx20 = wavg(vc, v, 20); jx120 = wavg(vc, v, 120)
    ma60 = pd.Series(c).rolling(60, min_periods=60).mean().to_numpy()
    llv60 = pd.Series(c).rolling(60, min_periods=60).min().to_numpy()
    ma5v = pd.Series(v).rolling(5, min_periods=5).mean().to_numpy()
    yz = YZ_ALL.reindex(df["date"]).to_numpy(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        jj = np.where(v > 0, amo / (v * 100.0), np.nan)
        gr1 = (c > jx20 * 1.17) & (c > jx * 1.3) & (c > ma60 * 1.25) & (c > jj * 1.01)
        gr2 = (c > llv60 * 1.5) & (c > ma60 * 1.3) & (c > jx * 1.35) & (np.abs(h - c) <= 0.01)
        co = c > o
        every2 = co.copy(); every2[1:] &= co[:-1]
        fh = (c > jx * 1.25 * yz) & every2 & (c > jx120 * 1.4) & (v > ma5v * 1.2)
        risk = gr1 | gr2 | fh
    d64 = df["date"].to_numpy(dtype="datetime64[ns]")
    gpos = np.searchsorted(ALL_D64, d64)
    gvalid = (gpos < ND) & (ALL_D64[np.minimum(gpos, ND - 1)] == d64)
    gpos = np.where(gvalid, gpos, 0)
    rowof = np.full(ND, -1, np.int32)
    rows = np.where(gvalid)[0]
    rowof[gpos[rows]] = rows
    amt20f = np.where(np.isfinite(amt20), amt20, 0)
    stock[code] = dict(o=o, c=c, ma20=ma20, risk=risk, rowof=rowof, first180=df["date"].iloc[0] + pd.Timedelta(days=180),
                       dates64=d64, amt20=amt20f)
    codes.append(code)
print(f"[load] {len(codes)} 只 + 纳次H RISK ({time.time()-t0:.0f}s)", flush=True)

LIQ_RANK = sorted(codes, key=lambda cc: -np.nanmax(stock[cc]["amt20"]))


def fund_state(code6, day64):
    recs = FUND.get(code6)
    if not recs:
        return None
    lo, hi, best = 0, len(recs) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if np.datetime64(recs[mid][0]) <= day64:
            best = recs[mid]; lo = mid + 1
        else:
            hi = mid - 1
    return best


def run(entry="A", exits=("base",), gold_phi=0.5, slip=SLIP, seed=0):
    rng = np.random.default_rng(seed)
    cash = CASH0
    holdings = {}   # code -> dict
    pending_sell, pending_buy, last_close = {}, [], {}
    trades_ep, trades_ed, trades_ed_last = {}, {}, {}
    eq, trades, reason_cnt = [], [], {}
    rebal_i = 0
    for di in range(ND):
        day = ALL_DAYS[di]
        d64 = ALL_D64[di]
        # 卖出
        for code in list(pending_sell.keys()):
            if code not in holdings:
                pending_sell.pop(code, None); continue
            s = stock[code]
            k = s["rowof"][di]
            if k < 0:
                continue
            px = s["o"][k] * (1 - slip)
            sh = holdings.pop(code)["sh"]
            cash += sh * px * (1 - COMM) - sh * px * TAX
            ret_pct = (px / trades_ep.pop(code) - 1) * 100
            trades.append(ret_pct)
            r = pending_sell.pop(code)
            reason_cnt[r] = reason_cnt.get(r, 0) + 1
            trades_ed_last.pop(code, None)
        # 买入
        for code in pending_buy:
            if len(holdings) >= MAX_POS or code in holdings or code in pending_sell:
                continue
            s = stock[code]
            k = s["rowof"][di]
            if k <= 0:
                continue
            px_prev = s["c"][k - 1]
            px_raw = s["o"][k]
            if not np.isfinite(px_prev) or px_raw >= px_prev * 1.097:
                continue
            px = px_raw * (1 + slip)
            pv = cash + sum(h["sh"] * last_close.get(cc, h["ep"]) for cc, h in holdings.items())
            budget = pv / MAX_POS
            nl = int(min(budget, cash) / (px * 100 * (1 + COMM)))
            if nl < 1:
                continue
            sh = nl * 100
            cost = sh * px * (1 + COMM)
            if cost > cash:
                nl = int(cash / (px * 100 * (1 + COMM)))
                if nl < 1:
                    continue
                sh = nl * 100
                cost = sh * px * (1 + COMM)
            cash -= cost
            holdings[code] = {"sh": sh, "ep": px, "H": px, "L": px, "di": di, "period": None}
            trades_ep[code] = px; trades_ed[code] = di; trades_ed_last[code] = di
            last_close[code] = px
        pending_buy = []
        breadth_hit = breadth_map[di] if "breadth" in exits else False
        # 收盘检查
        for code, h in list(holdings.items()):
            s = stock[code]
            k = s["rowof"][di]
            if k < 0:
                continue
            c = s["c"][k]
            last_close[code] = c
            h["H"] = max(h["H"], c); h["L"] = min(h["L"], c)
            reason = ""
            if "breadth" in exits and breadth_hit:
                reason = "breadth清仓"
            elif c <= h["ep"] * 0.92:
                reason = "硬止损-8%"
            elif np.isfinite(s["ma20"][k]) and c < s["ma20"][k]:
                reason = "MA20破位"
            elif di - h["di"] >= 60:
                reason = "满60日"
            elif "naci" in exits and s["risk"][k]:
                reason = "纳次H个股止盈"
            elif f"gold" in exits:
                phi = gold_phi
                if h["H"] > h["ep"] * 1.05 and (h["H"] - h["L"]) > 0:
                    lvl = h["H"] - phi * (h["H"] - h["L"])
                    if c <= lvl:
                        reason = f"黄金分割{phi}止盈"
            elif "gres382" in exits and c >= h["ep"] * 1.382:
                reason = "涨幅阻力+38.2%止盈"
            elif "gres618" in exits and c >= h["ep"] * 1.618:
                reason = "涨幅阻力+61.8%止盈"
            if reason and code not in pending_sell:
                pending_sell[code] = reason
        # 买入信号
        if len(holdings) < MAX_POS:
            if entry.startswith("D"):
                dd_th = 0.382 if "382" in entry else 0.618
                if di % 20 == rebal_i:
                    cands = []
                    for cc in LIQ_RANK:
                        if cc in holdings or cc in pending_sell:
                            continue
                        s = stock[cc]
                        k = s["rowof"][di]
                        if k < 260 or s["amt20"][k] < 5e6 or not np.isfinite(s["c"][k]) or s["c"][k] < 2:
                            continue
                        hh252 = stock_hh[cc][k]
                        if not np.isfinite(hh252) or s["c"][k] > hh252 * (1 - dd_th):
                            continue
                        cands.append(cc)
                    pending_buy = cands[:MAX_POS - len(holdings)]
            elif entry == "A":
                if di % 20 == rebal_i:
                    cands = []
                    for cc in LIQ_RANK:
                        if cc in holdings or cc in pending_sell:
                            continue
                        s = stock[cc]
                        k = s["rowof"][di]
                        if k < 1 or s["amt20"][k] < 5e6 or not np.isfinite(s["c"][k]) or s["c"][k] < 2:
                            continue
                        cands.append(cc)
                    pending_buy = cands[:MAX_POS - len(holdings)]
            else:  # B: 五条规则
                cands = []
                for code, s in stock.items():
                    if code in holdings or code in pending_sell:
                        continue
                    k = s["rowof"][di]
                    if k < 260:
                        continue
                    if np.datetime64(s["dates64"][k]) < np.datetime64(s["first180"]):
                        continue
                    st = fund_state(code[2:], d64)
                    if not st or code in ST_SET.get(code[2:], set()):
                        continue
                    _, period, rev_yoy, np_, gm_chg = st
                    c0 = s["c"][k]
                    hh = pd.Series(c0).rolling if False else None
                    # 252 日高（用 stock 慢速版：直接 rolling 已有？无 → 用 min-periods 快查）
                    hh = stock_hh[code][k] if code in stock_hh else np.nan
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
        pv = cash
        for code, h in holdings.items():
            pv += h["sh"] * last_close.get(code, h["ep"])
        eq.append(pv)
    eq = np.array(eq)
    r = np.diff(eq) / eq[:-1]
    total = eq[-1] / eq[0] - 1
    ann = (1 + total) ** (252 / max(1, len(eq))) - 1
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0
    wins = [t for t in trades if t > 0]; losses = [t for t in trades if t <= 0]
    return {"total_pct": round(total * 100, 2), "ann_pct": round(ann * 100, 2),
            "mdd_pct": round(dd * 100, 1), "sharpe": round(sharpe, 3),
            "n_trades": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "payoff": round(float(np.mean(wins) / abs(np.mean(losses))), 2) if wins and losses else None,
            "reasons": reason_cnt}


LIMIT_UP_GUARD = 1.097
# 252 日高预查表（载体B条件③）
stock_hh = {}
for code in codes:
    s = stock[code]
    stock_hh[code] = pd.Series(s["c"]).rolling(252, min_periods=252).max().to_numpy()

if __name__ == "__main__":
    t0 = time.time()
    out = {"A": {}, "B": {}}
    variants = [
        ("E0基线", ("base",), 0.5),
        ("E1+纳次H个股", ("base", "naci"), 0.5),
        ("E2+breadth清仓", ("base", "breadth"), 0.5),
        ("E3+黄金0.382", ("base", "gold"), 0.382),
        ("E4+黄金0.500", ("base", "gold"), 0.500),
        ("E5+黄金0.618", ("base", "gold"), 0.618),
        ("E6=纳次H+breadth", ("base", "naci", "breadth"), 0.5),
        ("E7=纳次H+黄金0.5", ("base", "naci", "gold"), 0.500),
    ]
    for entry in (os.environ.get("R2_ENTRY", "A,B").split(",")):
        for name, ex, phi in variants:
            r = run(entry=entry, exits=ex, gold_phi=phi)
            r["variant"] = name
            out[entry][name] = r
            print(f"[{entry}/{name}] {r['total_pct']}% | 年化 {r['ann_pct']}% | 回撤 {r['mdd_pct']}% | "
                  f"夏普 {r['sharpe']} | {r['n_trades']}笔 胜率{r['win_rate']}%", flush=True)
            json.dump(out, open(R2 / "naci_exit_0912.json", "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
    out["benchmark_HS300_pct"] = round(HS300_TOTAL, 2)
    print(f"[基准 HS300] {HS300_TOTAL:.1f}% | 总耗时 {time.time()-t0:.0f}s", flush=True)
