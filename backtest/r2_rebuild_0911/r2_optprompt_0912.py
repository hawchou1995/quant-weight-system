# -*- coding: utf-8 -*-
"""优化版提示词回测（报告-Gemini提示词体检与优化_20260912.md §七规格，2026-09-12）
================================================================
分层买入：硬门槛（当期净利>0 & 营收同比≥REV_TH & close>MA250）+ 打分 Top5 等权
  +2 创一年新高（close>前250日收盘max）| +2 连续两期营收加速
  +1 毛利率同比改善>0（合同负债缺数据不计）| +1 研发/资本开支（缺数据不计）
  +1 近60日无涨停
  → 满分 6（7 分制缺一项，数据边界如实申报）
卖出：close<ep×(1−stop) | 下期营收同比<0 或转亏 | close<MA120 连续3日 | 持有≤MAXHOLD
执行：T 收盘信号 → T+1 开盘（开盘≈涨停放弃）；等权 ≤5 只各 20%；成本往返 1.16% 与 0 双版本。
输出：密度体检 / 收益 / 沪深300+全池等权超额 t 值 / 分年度 / 剔Top10-50 / 安慰剂500 /
     敏感性 REV{15,20,25,30}×STOP{8,10,12}×HOLD{60,90,120}。
数据边界（ADR-0005 沿用）：PIT=法定披露截止日；ST=报告期当时简称。
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
MAX_POS = 5
CASH0 = 1_000_000.0
LIMIT_UP = 1.097
AVAIL = {"0331": (4, 30), "0630": (8, 31), "0930": (10, 31), "1231": (4, 30)}

t0 = time.time()


def avail_date(period):
    y, md = int(str(period)[:4]), str(period)[4:]
    m, d = AVAIL[md]
    return pd.Timestamp(y + (1 if md == "1231" else 0), m, d)


# ---------- 基本面 ----------
q = pd.read_csv(BASE / "data_fundamental" / "yjbb_quarterly.csv", dtype={"股票代码": str})
q["股票代码"] = q["股票代码"].str.strip()
q = q[q["股票代码"].str.match(r"^(000|001|002|003|600|601|603|605)")].copy()
q["is_st"] = q["股票简称"].astype(str).str.contains("ST", na=False)
q["rev_yoy"] = pd.to_numeric(q["营业总收入-同比增长"], errors="coerce")
q["np"] = pd.to_numeric(q["净利润-净利润"], errors="coerce")
q["gm"] = pd.to_numeric(q["销售毛利率"], errors="coerce")
q["avail"] = q["REPORT_PERIOD"].astype(str).map(avail_date)
q = q.sort_values(["股票代码", "REPORT_PERIOD"])
q["rev_prev"] = q.groupby("股票代码")["rev_yoy"].shift(1)
q["gm_chg"] = q.groupby("股票代码")["gm"].diff(4)
FUND, ST_START = {}, {}
for code, g in q.groupby("股票代码"):
    FUND[code] = list(zip(g["avail"], g["REPORT_PERIOD"], g["rev_yoy"], g["rev_prev"],
                          g["np"], g["gm_chg"]))
    st_rows = g.loc[g["is_st"], "avail"]
    ST_START[code] = np.sort(st_rows.to_numpy(dtype="datetime64[ns]")) if len(st_rows) else None

# ---------- 日历 ----------
idx = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
idx["date"] = pd.to_datetime(idx["date"])
idx = idx.set_index("date").sort_index()
ALL_DAYS = [d for d in idx.index if START <= d]
ND = len(ALL_DAYS)
ALL_D64 = np.array(ALL_DAYS, dtype="datetime64[ns]")
HS300_RET = idx.loc[ALL_DAYS, "close"].pct_change().fillna(0).to_numpy()
HS300_TOTAL = (np.prod(1 + HS300_RET) - 1) * 100

# ---------- 行情 + 截面矩阵 ----------
codes, stock = [], {}
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
    if len(df) < 420:
        continue
    codes.append(code)
    c = df["close"].to_numpy(float)
    ma250 = pd.Series(c).rolling(250, min_periods=250).mean().to_numpy()
    ma120 = pd.Series(c).rolling(120, min_periods=120).mean().to_numpy()
    hh250 = pd.Series(c).rolling(250, min_periods=250).max().to_numpy()
    hh_prior = np.concatenate([[np.nan], hh250[:-1]])
    lu = np.zeros(len(c), bool)
    lu[1:] = c[1:] / c[:-1] >= LIMIT_UP
    nolu60 = pd.Series(lu.astype(float)).rolling(60, min_periods=1).sum().to_numpy() == 0
    below = (c < ma120).astype(float)
    below3 = pd.Series(below).rolling(3, min_periods=3).sum().to_numpy() >= 3
    d64 = df["date"].to_numpy(dtype="datetime64[ns]")
    gpos = np.searchsorted(ALL_D64, d64)
    gvalid = (gpos < ND) & (ALL_D64[np.minimum(gpos, ND - 1)] == d64)
    gpos = np.where(gvalid, gpos, 0)
    stock[code] = dict(c=c, o=df["open"].to_numpy(float), d64=d64, ma250=ma250, ma120=ma120,
                       hh=hh_prior, nolu60=nolu60, below3=below3, gpos=gpos, gvalid=gvalid,
                       first180=np.datetime64(df["date"].iloc[0] + pd.Timedelta(days=180)))

NS = len(codes)
print(f"[load] 行情 {NS} 只 ({time.time()-t0:.0f}s)", flush=True)

CLOSE_M = np.full((ND, NS), np.nan, np.float32)
REV_M = np.full((ND, NS), np.nan, np.float32)
NPP_M = np.full((ND, NS), np.nan, np.float32)
RPREV_M = np.full((ND, NS), np.nan, np.float32)
GMC_M = np.full((ND, NS), np.nan, np.float32)
MA250_M = np.full((ND, NS), np.nan, np.float32)
HH_M = np.full((ND, NS), np.nan, np.float32)
NOLU_M = np.zeros((ND, NS), bool)
NH_M = np.zeros((ND, NS), bool)
OK_M = np.zeros((ND, NS), bool)

STF_M = np.zeros((ND, NS), bool)
for j, code in enumerate(codes):
    s = stock[code]
    rows = np.where(s["gvalid"])[0]
    gi = s["gpos"][rows]
    n = len(s["c"])
    rev = np.full(n, np.nan); rprev = np.full(n, np.nan)
    npf = np.full(n, np.nan); gmc = np.full(n, np.nan)
    recs = FUND.get(code[2:])          # ⚠ FUND 键=裸 6 位码
    if recs:
        rr = np.searchsorted(s["d64"], np.array([r[0] for r in recs], dtype="datetime64[ns]"))
        for (avail, period, ry, rp, npv, gc), r0 in zip(recs, rr):
            if r0 < n:
                rev[r0:] = ry; rprev[r0:] = rp; npf[r0:] = npv; gmc[r0:] = gc
    st_avail = ST_START.get(code[2:])
    if st_avail is not None and len(st_avail):
        sr0 = np.searchsorted(s["d64"], st_avail)
        for r0 in sr0:
            if r0 < n:
                stf = np.zeros(n, bool); stf[r0:] = True
                STF_M[gi, j] |= stf[rows]
    CLOSE_M[gi, j] = s["c"][rows]
    REV_M[gi, j] = rev[rows]
    NPP_M[gi, j] = npf[rows]
    RPREV_M[gi, j] = rprev[rows]
    GMC_M[gi, j] = gmc[rows]
    MA250_M[gi, j] = s["ma250"][rows]
    HH_M[gi, j] = s["hh"][rows]
    NOLU_M[gi, j] = s["nolu60"][rows]
    NH_M[gi, j] = (s["c"] > s["hh"])[rows]
    OK_M[gi, j] = s["d64"][rows] >= s["first180"]

ACCEL_M = (REV_M > RPREV_M) & np.isfinite(REV_M) & np.isfinite(RPREV_M)
print(f"[mat] 截面矩阵就绪 ({time.time()-t0:.0f}s)", flush=True)


def build_gate(rev_th):
    with np.errstate(invalid="ignore"):
        return OK_M & (NPP_M > 0) & (REV_M >= rev_th) & (CLOSE_M > MA250_M) & (~STF_M)


def build_score(gate):
    with np.errstate(invalid="ignore"):
        sc = (2 * NH_M + 2 * ACCEL_M + (GMC_M > 0) + NOLU_M).astype(np.int8)
    out = np.where(gate, sc, np.int8(-100))
    return out


# 全池等权基准
_ret_m = np.vstack([np.full((1, NS), np.nan), CLOSE_M[1:] / CLOSE_M[:-1] - 1])
univ = np.nanmean(np.where(OK_M, _ret_m, np.nan), axis=1)
univ = np.nan_to_num(univ)
UNIV_TOTAL = (np.prod(1 + univ) - 1) * 100
print(f"[bench] HS300 {HS300_TOTAL:.1f}% | 全池等权 {UNIV_TOTAL:.1f}%", flush=True)

# ---------- 密度体检（预注册：日均<3 或 独立事件<300 → 终止） ----------
GATE20 = build_gate(20)
daily_n = GATE20.sum(axis=1)
events_total = int(GATE20.sum())
dens = {"daily_mean": round(float(daily_n.mean()), 1),
        "daily_median": round(float(np.median(daily_n)), 1),
        "daily_p10": round(float(np.percentile(daily_n, 10)), 1),
        "daily_p90": round(float(np.percentile(daily_n, 90)), 1),
        "events_total": events_total}
print(f"[density] {dens}", flush=True)

# ---------- 组合引擎 ----------
for _c in codes:
    _s = stock[_c]
    _ro = np.full(ND, -1, np.int32)
    _rows = np.where(_s["gvalid"])[0]
    _ro[_s["gpos"][_rows]] = _rows
    _s["rowof"] = _ro
ROW = {j: stock[c]["rowof"] for j, c in enumerate(codes)}
VAL = {j: stock[c]["gvalid"] for j, c in enumerate(codes)}


def run(gate, score, stop=0.10, maxhold=120, cost_rt=0.0116, blacklist=None):
    half = cost_rt / 2
    cash = CASH0
    holdings = {}    # j -> dict
    pending_sell, pending_buy, last_close = {}, [], {}
    trades_ep, trades_ed, trades_ed_last = {}, {}, {}
    eq, trades = [], []
    for di in range(ND):
        day64 = ALL_D64[di]
        for j in list(pending_sell.keys()):
            if j not in holdings:
                pending_sell.pop(j, None)
                continue
            s = stock[STKJ[j]]
            k = ROW[j][di]
            if k < 0:
                continue
            px = s["o"][k] * (1 - half)
            sh = holdings.pop(j)["sh"]
            cash += sh * px * (1 - COMM) - sh * px * TAX
            trades.append({"j": j, "code": STKJ[j], "exit": str(ALL_DAYS[di].date()),
                           "ret_pct": (px / trades_ep.pop(j) - 1) * 100,
                           "entry_di": trades_ed.pop(j),
                           "bars": di - trades_ed_last.pop(j)})
        for j in pending_buy:
            if len(holdings) >= MAX_POS or j in holdings or j in pending_sell:
                continue
            s = stock[STKJ[j]]
            k = ROW[j][di]
            if k <= 0:
                continue
            px_prev_c = s["c"][k - 1] if k > 0 else np.nan
            px_raw = s["o"][k]
            if not np.isfinite(px_raw) or px_raw <= 0 or not np.isfinite(px_prev_c):
                continue
            if px_raw >= px_prev_c * LIMIT_UP:
                continue   # 开盘≈涨停，放弃
            px = px_raw * (1 + half)
            pv = cash + sum(h["sh"] * last_close.get(jj, h["ep"]) for jj, h in holdings.items())
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
            holdings[j] = {"sh": sh, "ep": px, "di": di, "period": None}
            trades_ep[j] = px
            trades_ed[j] = di
            trades_ed_last[j] = di
            last_close[j] = px
        pending_buy = []
        # 收盘：持仓退出判定
        for j, h in list(holdings.items()):
            k = ROW[j][di]
            if k < 0:
                continue
            s = stock[STKJ[j]]
            c = s["c"][k]
            last_close[j] = c
            reason = ""
            if blacklist and j in blacklist and h["di"] in blacklist[j]:
                reason = "blacklist"
            elif c <= h["ep"] * (1 - stop):
                reason = "stop"
            elif di - h["di"] >= maxhold:
                reason = "maxhold"
            elif s["below3"][k]:
                reason = "ma120x3"
            else:
                recs = FUND.get(STKJ[j][2:])
                if recs:
                    lo, hi2, best = 0, len(recs) - 1, None
                    while lo <= hi2:
                        mid = (lo + hi2) // 2
                        if np.datetime64(recs[mid][0]) <= day64:
                            best = recs[mid]; lo = mid + 1
                        else:
                            hi2 = mid - 1
                    if best:
                        _, period, ry, _, npv, _ = best
                        if h["period"] is None:
                            h["period"] = period
                        elif period != h["period"]:
                            if (np.isfinite(ry) and ry < 0) or (np.isfinite(npv) and npv <= 0):
                                reason = "fund"
                            h["period"] = period
            if reason and j not in pending_sell:
                pending_sell[j] = reason
        # 买入信号：门槛内打分 Top5
        if len(holdings) < MAX_POS:
            idxs = np.where(gate[di])[0]
            if len(idxs):
                sc = score[di, idxs]
                top = idxs[np.argsort(-sc)][:MAX_POS - len(holdings)]
                pending_buy = [int(j) for j in top]
        pv = cash
        for j, h in holdings.items():
            pv += h["sh"] * last_close.get(j, h["ep"])
        eq.append(pv)
    eq = np.array(eq)
    r = np.diff(eq) / eq[:-1]
    total = eq[-1] / eq[0] - 1
    ann = (1 + total) ** (252 / max(1, len(eq))) - 1
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0
    rets = np.array([t["ret_pct"] for t in trades])
    wins = rets[rets > 0]; losses = rets[rets <= 0]
    return {"total_pct": round(total * 100, 2), "ann_pct": round(ann * 100, 2),
            "mdd_pct": round(dd * 100, 1), "sharpe": round(sharpe, 3),
            "n_trades": len(trades),
            "win_rate": round(len(wins) / len(rets) * 100, 1) if len(rets) else 0,
            "payoff": round(float(wins.mean() / abs(losses.mean())), 2) if len(wins) and len(losses) else None,
            "avg_hold_bars": round(float(np.mean([t["bars"] for t in trades])), 1) if trades else 0,
            "eq": eq, "trades": trades}


STKJ = {j: c for j, c in enumerate(codes)}


def stats_of(res, name):
    return {k: v for k, v in res.items() if k not in ("eq", "trades")}


if __name__ == "__main__":
    out = {"density": dens}
    # 主臂（1.16% 成本）
    res = run(GATE20, build_score(GATE20), stop=0.10, maxhold=120, cost_rt=0.0116)
    out["main_cost"] = stats_of(res, "main_cost")
    print(f"[main 1.16%] {out['main_cost']}", flush=True)
    # 零成本
    res0 = run(GATE20, build_score(GATE20), stop=0.10, maxhold=120, cost_rt=0.0)
    out["main_zero"] = stats_of(res0, "main_zero")
    print(f"[main 0%]   {out['main_zero']}", flush=True)

    # 日超额 t 值（对 HS300 与 全池等权）
    for tag, bret in [("hs300", HS300_RET), ("univ", univ)]:
        r = np.diff(res["eq"]) / res["eq"][:-1]
        ex = r - bret[:len(r)]
        t = ex.mean() / (ex.std(ddof=1) / np.sqrt(len(ex))) if ex.std() > 0 else 0
        out.setdefault("excess", {})[tag] = {"mean_pct": round(float(ex.mean() * 100), 4),
                                             "median_pct": round(float(np.median(ex) * 100), 4),
                                             "t": round(float(t), 2)}

    # 分年度
    dts = pd.to_datetime([d.date() for d in ALL_DAYS])
    yr = pd.Series(np.diff(res["eq"]) / res["eq"][:-1], index=dts[1:]).groupby(lambda x: x.year)
    ytab = {}
    for y, g in yr:
        cum = (1 + g).prod() - 1
        bh = (1 + HS300_RET[1:][dts[1:].year == y]).prod() - 1
        nt = sum(1 for t in res["trades"] if t["exit"].startswith(str(y)))
        ytab[str(y)] = {"ret_pct": round(cum * 100, 1), "hs300_pct": round(bh * 100, 1), "n_trades": nt}
    out["yearly"] = ytab
    print(f"[yearly] {ytab}", flush=True)

    # 稳健性：剔 Top10/50（复利链近似：每笔占用 1/5 仓位，按时间序 Π(1+ret/5)）
    def chain(trs, drop=0):
        trs2 = sorted(trs, key=lambda t: t["entry_di"])[drop if drop > 0 else 0:] if drop > 0 else trs
        if drop > 0:
            trs2 = sorted(trs, key=lambda t: -t["ret_pct"])[drop:]
            trs2 = sorted(trs2, key=lambda t: t["entry_di"])
        v = 1.0
        for t in trs2:
            v *= 1 + t["ret_pct"] / 100 / 5
        return (v - 1) * 100
    tr_all = res["trades"]
    out["chain_full_pct"] = round(chain(tr_all), 2)
    out["chain_drop_top10_pct"] = round(chain(tr_all, 10), 2)
    out["chain_drop_top50_pct"] = round(chain(tr_all, 50), 2)
    print(f"[chain] full {out['chain_full_pct']}% | drop10 {out['chain_drop_top10_pct']}% | "
          f"drop50 {out['chain_drop_top50_pct']}%", flush=True)

    json.dump(out, open(R2 / "optprompt_0912_part1.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"[part1 done] {time.time()-t0:.0f}s", flush=True)
