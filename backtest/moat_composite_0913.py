# -*- coding: utf-8 -*-
"""护城河复合分 · 主板 Top10 月度轮动（《资产底牌》五维护城河量化，窗口 2021-01-04 起）
信息集审计（ADR-0007）：ROE_TTM=PB/PE（T 日收盘）、毛利率/营收同比按 REPORT_PERIOD+法定披露日 PIT、total_mv T 日可得。
复合分 = z(ROE) + z(毛利率) - z(毛利率4季波动) + z(营收同比连续正季数)"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
START = pd.Timestamp("2021-01-04")
t0 = time.time()

# ---- 1. 估值日频（ROE_TTM = PB/PE, mv）----
v = pd.read_csv(BASE / "data_fundamental" / "val_em" / "val_em_all.csv", dtype={"code": str})
v["date"] = pd.to_datetime(v["date"])
v = v[v["date"] >= START].copy()
v["roe_ttm"] = np.where((v["pe_ttm"] > 0) & (v["pb_mrq"] > 0), v["pb_mrq"] / v["pe_ttm"] * 100, np.nan)
v = v[v["total_mv"] >= 2e9]  # ≥20 亿排壳票
print(f"[val] {v['code'].nunique()} 票 {len(v):,} 行 ({time.time()-t0:.0f}s)", flush=True)

# ---- 2. yjbb 季频 PIT ----
y = pd.read_csv(BASE / "data_fundamental" / "yjbb_quarterly.csv", dtype={"股票代码": str})
y = y.rename(columns={"股票代码": "code", "销售毛利率": "gp", "营业总收入-同比增长": "rev_yoy",
                      "净资产收益率": "roe_q", "REPORT_PERIOD": "rp"})
y["code"] = y["code"].str.zfill(6)
y["rp"] = y["rp"].astype(str)
def legal_date(rp):  # 法定披露截止日（ADR-0005 口径）
    q = rp[4:6]
    yr = int(rp[:4])
    return {"03": f"{yr}-04-30", "06": f"{yr}-08-31", "09": f"{yr}-10-31", "12": f"{yr+1}-04-30"}[q]
y["pit"] = pd.to_datetime(y["rp"].map(legal_date))
y["gp"] = pd.to_numeric(y["gp"], errors="coerce")
y["rev_yoy"] = pd.to_numeric(y["rev_yoy"], errors="coerce")
y = y.sort_values(["code", "pit"])
y["gp_roll"] = y.groupby("code")["gp"].transform(lambda s: s.rolling(4, min_periods=3).std())
y["pos_streak"] = y.groupby("code")["rev_yoy"].transform(lambda s: (s > 0).astype(int).groupby(s.index).cummax().groupby((s <= 0).cumsum()).cumsum())
print(f"[yjbb] {y['code'].nunique()} 票 ({time.time()-t0:.0f}s)", flush=True)

def pit_snapshot(day):
    """截至 day 的最近已披露季报因子（法定日 PIT）"""
    yy = y[y["pit"] <= day]
    if yy.empty:
        return pd.DataFrame()
    return yy.groupby("code").tail(1).set_index("code")

# ---- 3. 月度轮动回测 ----
DAYS = sorted(v["date"].unique())
day_ts = pd.DatetimeIndex(DAYS)
cix = {c: i for i, c in enumerate(sorted(v["code"].unique()))}
codes_u = sorted(v["code"].unique())
NS = len(codes_u)

roe_mat = v.pivot_table(index="date", columns="code", values="roe_ttm")
roe_mat = roe_mat.reindex(columns=codes_u)
mv_mat = v.pivot_table(index="date", columns="code", values="total_mv").reindex(columns=codes_u)
ROE = roe_mat.reindex(day_ts, fill_value=np.nan).to_numpy()
MV = mv_mat.reindex(day_ts, fill_value=np.nan).to_numpy()
print(f"[matrix] {ROE.shape} ({time.time()-t0:.0f}s)", flush=True)

# data_full 前复权价
OPEN = np.full((len(DAYS), NS), np.nan)
CLOSE = np.full((len(DAYS), NS), np.nan)
FIRST = np.full(NS, -1, dtype=int)
for f in sorted((BASE / "data_full").glob("*.csv")):
    c = f.stem
    if not (c.startswith("sh60") or c.startswith("sz00")):
        continue
    code = c[2:]  # 纯 6 位，与 cix 键一致（⚠ 第五次前缀坑：东财 code 无 sh./sz. 前缀）
    if code not in cix:
        continue
    j = cix[code]
    d = pd.read_csv(f, usecols=["date", "open", "close"], dtype={"date": str})
    d["date"] = pd.to_datetime(d["date"])
    d = d.set_index("date").sort_index()
    d = d.reindex(day_ts)
    OPEN[:, j] = d["open"].to_numpy()
    CLOSE[:, j] = d["close"].to_numpy()
    fv = d["close"].first_valid_index()
    if fv is not None:
        FIRST[j] = day_ts.get_loc(fv)
print(f"[px] ({time.time()-t0:.0f}s)", flush=True)

# 季频因子快照逐月缓存
mo_keys = sorted({d.strftime("%Y-%m") for d in day_ts})
pit_cache = {}
for m in mo_keys:
    last = max(d for d in day_ts if d.strftime("%Y-%m") <= m)
    pit_cache[m] = pit_snapshot(last)
print(f"[pit] {len(pit_cache)} 月快照 ({time.time()-t0:.0f}s)", flush=True)


def zsc(a):
    m, s = np.nanmean(a), np.nanstd(a)
    return (a - m) / s if s > 0 else np.zeros_like(a)


def run(offset=0, rebal=20, slip=0.002):
    cash, eq, reasons, hold = 1e6, [], {}, {}
    last_m = None
    score_row = np.full(NS, np.nan)
    for di in range(len(DAYS)):
        d = day_ts[di]
        m = d.strftime("%Y-%m")
        if m != last_m:  # 每月首个交易日更新复合分
            last_m = m
            pit = pit_cache.get(m)
            sc = np.full(NS, np.nan)
            if pit is not None and not pit.empty:
                for code, r in pit.iterrows():
                    if code in cix:
                        sc[cix[code]] = 1.0
                roe_s = np.where(np.isfinite(ROE[di]), ROE[di], np.nan)
                gp_v = np.full(NS, np.nan); gv_v = np.full(NS, np.nan); st_v = np.full(NS, np.nan)
                for code, r in pit.iterrows():
                    if code in cix:
                        j = cix[code]
                        gp_v[j] = r["gp"]; gv_v[j] = r["gp_roll"]; st_v[j] = r["pos_streak"]
                comp = (np.nan_to_num(zsc(roe_s), nan=0) + np.nan_to_num(zsc(gp_v), nan=0)
                        - np.nan_to_num(zsc(gv_v), nan=0) + np.nan_to_num(zsc(st_v), nan=0))
                valid = np.isfinite(roe_s) | np.isfinite(gp_v)
                comp = np.where(valid, comp, np.nan)
                score_row = comp   # ⚠ 必须写回全局（此前赋给局部 sc 导致永不买入）
        # 昨日挂单成交
        for code in [c for c, h in hold.items() if h.get("sell_flag")]:
            j = cix[code]
            if np.isnan(OPEN[di, j]) or OPEN[di, j] <= 0:
                continue
            px_o = OPEN[di, j] * (1 - slip)
            h = hold.pop(code)
            sh = h["sh"]
            cash += sh * px_o - max(sh * px_o * 0.00025, 5) - sh * px_o * 0.001
            rsn = h.get("reason") or "调仓"
            reasons[rsn] = reasons.get(rsn, 0) + 1
        # 调仓（每月 rebal 日 + offset）
        d_i = di % rebal
        if di % rebal == offset and di > 250:
            sc = score_row
            ok = np.where(np.isfinite(sc))[0]
            ok = [j for j in ok[np.argsort(-sc[ok])][:10]
                  if np.isfinite(OPEN[di, j]) and OPEN[di, j] >= 2 and di - FIRST[j] >= 180]
            tgt = {ALL := codes_u[j] for j in ok}
            for code, h in hold.items():
                if code not in tgt and not h.get("sell_flag"):
                    h["sell_flag"] = True
                    h["reason"] = "调仓"
            pv = cash + sum(h["sh"] * (CLOSE[di, cix[c]] if np.isfinite(CLOSE[di, cix[c]]) else h["ep"]) for c, h in hold.items())
            for j in ok:
                code = codes_u[j]
                if code in hold:
                    continue
                px_o = OPEN[di, j]
                pc = CLOSE[di - 1, j]
                if not np.isfinite(px_o) or not np.isfinite(pc) or px_o >= pc * 1.097:
                    continue
                nl = int((min(pv / 10, cash) - 5) / (px_o * 100 * 1.00025))
                if nl < 1:
                    continue
                sh = nl * 100
                cost = sh * px_o * (1 + slip) + max(sh * px_o * 0.00025, 5)
                if cost > cash:
                    continue
                cash -= cost
                hold[code] = {"sh": sh, "ep": px_o * (1 + slip), "sell_flag": False}
        pv = cash + sum(h["sh"] * (CLOSE[di, cix[c]] if np.isfinite(CLOSE[di, cix[c]]) else h["ep"]) for c, h in hold.items())
        eq.append(pv)
    eq = np.array(eq)
    r = np.diff(eq) / eq[:-1]
    tot = eq[-1] / 1e6 - 1
    return {"total": tot * 100, "ann": ((1 + tot) ** (252 / len(eq)) - 1) * 100,
            "mdd": ((eq / np.maximum.accumulate(eq) - 1).min()) * 100,
            "sharpe": float(np.nanmean(r) / np.nanstd(r) * np.sqrt(252)), "reasons": reasons, "eq": eq}


if __name__ == "__main__":
    out = {}
    r0 = run()
    r0.pop("eq")
    out["护城河月频slip20"] = r0
    print(f"[护城河复合分 月频 slip20] {r0['total']:.1f}% | 年化 {r0['ann']:.1f}% | 回撤 {r0['mdd']:.1f}% | 夏普 {r0['sharpe']:.3f}", flush=True)
    ph = [run(offset=o)["total"] for o in (2, 6, 10, 14, 18)]
    out["_phase"] = ph
    print(f"[相位] off0 {r0['total']:.1f}% | 中位 {np.median(ph):.1f}% | 区间 [{min(ph):.0f},{max(ph):.0f}]", flush=True)
    # 分年度
    days = pd.DatetimeIndex(DAYS)
    s = pd.Series(run()["eq"], index=days)
    yearly = {y: round(float(g.iloc[-1] / g.iloc[0] - 1) * 100, 1) for y, g in s.groupby(s.index.year)}
    out["_yearly"] = yearly
    print(f"[分年度] {yearly}", flush=True)
    json.dump(out, open(BASE / "backtest" / "moat_composite_0913.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=str)
    print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
