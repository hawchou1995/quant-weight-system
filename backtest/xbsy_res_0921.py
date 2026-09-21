# -*- coding: utf-8 -*-
"""小步碎阳 · 共振标记 + 缩量大跌入场（XBSY-RES-0921 · 用户 2026-09-21「按你推荐」锁定口径）
================================================================================
锁定口径（grill Round 1 全部按推荐签批）
--------------------------------------------------------------------------------
Q1 宇宙：股票 = 主板(60/00) + 创业板(30) + 科创板(68)，**剔北交所**；ETF = 全部场内 ETF（1580）
Q2 指数：**沪深300**（`index_000300.csv`，链上日更）
Q3 「指数放量中阳线」：涨幅 ≥ 1.0% 且 收 > 开 且 量比(V/MA(V,20)) ≥ 1.2
Q4 「共振」：同日 个股阳线 且 个股涨幅 ≥ 指数涨幅 且 个股量比 ≥ 1.0
   ⚠ 第二臂「申万一级行业指数同步放量中阳」= **不做**：环境内**不存在行业指数行情序列**
     （只有 `stock_industry.json` 映射，无行情）→ 记「不可判定」，不臆造
Q5 缩量大跌（**两臂不叠**，因叠加后今日 0 只）：
   臂甲 = 跌幅 ≤ −3% 且 量比 ≤ 0.8
   臂乙 = 连续 3 日下跌 且 成交量逐日递减（「越跌越缩」，不设跌幅门）
Q6 入场：T 收盘确认 → **T+1 开盘买**（全库同口径）；另跑 **T 日收盘买** 对照（仅缩量甲臂）
Q7 出场：**爆量 ≥2×MA(V,20) + 次日阴线 → 次日开盘卖**（cap 250）；对照 = 固定 20 日
Q8 窗口：**2024-10-16 → 2026-09-18**（剔 9.26 行情及其余波；面板自 2024-01-01 起做预热）
Q9 过滤：剔 **ST**（名含 ST）+ **上市 < 60 交易日**；成本 = 滑点 20bp/边 + 佣金 2.5bp(最低 5 元)
   资金口径双跑：**20 仓**（每仓 = NAV0/20 = 8,500 元，量比升序）与 **无限资金**（全吃·等权·无上限）
Q10 三臂并列：共振单臂 / 缩量单臂 / **共振标记后 N 日内出现缩量甲**（N ∈ {5,10,20}）——
   ⚠ 共振（指数放量中阳日）与缩量大跌**在同一天对同一只票结构互斥**，故「双条件」只能是**时序**形态
   （先标记、后触发），不存在同日的「共振∧缩量」臂

判据：年化 / 夏普 / 最大回撤 / 胜率（按笔 + 按天）；样本闸 n≥100 ∧ 活跃日≥30 否则记「不可判定」。
窗口仅 1.9 年 → **样本天然偏短**，所有结论须按短窗标注。

用法：cd quant-weight-system && python backtest/xbsy_res_0921.py
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

import xbsy_0921 as X                                       # noqa: E402  roll_sum/roll_mean/roll_max
import xbsy_exit_0921 as E                                  # noqa: E402  exit_day_matrix
import xbsy_port_0921 as PORT                               # noqa: E402  simulate / simulate_unlimited / metrics

OUT_JSON = str(HERE / "xbsy_res_0921.json")
START = "2024-10-16"
PANEL_FROM = "2024-01-01"
WARMUP = 60
EXIT_BOOM = dict(boom="q2", lag=1, ma5=False, ma10=False, cap=250)
EXIT_FIX20 = dict(boom=None, lag=1, ma5=False, ma10=False, cap=20)


def universe():
    codes = []
    for f in sorted((BASE / "data_full").glob("*.csv")):
        c = f.stem
        p = c[2:]
        if p.startswith(("60", "00", "30", "68")) or p.startswith(("51", "56", "58", "15", "16")):
            codes.append(c)
    return codes


def build_panel(codes, cal):
    """面板：open/close/volume + mask（≥WARMUP 个有效行 且 成交量>0）"""
    T, N = len(cal), len(codes)
    O = np.full((T, N), np.nan, dtype=np.float32)
    C = np.full((T, N), np.nan, dtype=np.float32)
    V = np.full((T, N), np.nan, dtype=np.float32)
    ci = {d: i for i, d in enumerate(cal)}
    miss = 0
    for j, c in enumerate(codes):
        f = BASE / "data_full" / f"{c}.csv"
        try:
            d = pd.read_csv(f, dtype={"date": str}, usecols=["date", "open", "close", "volume"])
        except Exception:
            miss += 1
            continue
        d = d[d["date"] >= PANEL_FROM]
        if d.empty:
            miss += 1
            continue
        idx = np.fromiter((ci.get(x, -1) for x in d["date"]), dtype=np.int64, count=len(d))
        ok = idx >= 0
        O[idx[ok], j] = d["open"].to_numpy(np.float32)[ok]
        C[idx[ok], j] = d["close"].to_numpy(np.float32)[ok]
        V[idx[ok], j] = d["volume"].to_numpy(np.float32)[ok]
    valid = np.isfinite(C) & np.isfinite(O) & (np.nan_to_num(V, nan=0.0) > 0)
    cum = np.cumsum(valid, axis=0)
    mask = valid & (cum >= WARMUP)
    return {"open": O, "close": C, "mask": mask}, V, miss


def names_map():
    nm = {}
    try:
        t = open(BASE / "short_signals.js", encoding="utf-8").read()
        S = json.loads(t[t.find("=") + 1:].strip().rstrip(";"))
        for grp in ("stock", "etf", "fund"):
            for k, v in (S.get(grp) or {}).items():
                if v.get("name"):
                    nm[k] = v["name"]
    except Exception:
        pass
    return nm


def main():
    t0 = time.time()
    print("=" * 118)
    print("小步碎阳 · 共振标记 + 缩量大跌入场（XBSY-RES-0921）· 窗口 " + START + " → 2026-09-18")
    print("=" * 118)
    idxall = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
    cal = [d for d in idxall["date"] if d >= PANEL_FROM]
    codes = universe()
    nm = names_map()
    print(f"宇宙 {len(codes)} 只（主板/创业板/科创板/ETF，剔北交所）| 名称覆盖 {sum(1 for c in codes if c[2:] in nm)} 只")
    P, V, miss = build_panel(codes, cal)
    T, N = P["close"].shape
    print(f"面板 {T} 日 × {N} 只（{cal[0]} → {cal[-1]}）| 缺数据 {miss} 只 | 域门可交易率 {P['mask'].mean():.3f}")

    # ---- ST 过滤（名含 ST）+ ETF 免判 ----
    st_cols = []
    unknown = 0
    for j, c in enumerate(codes):
        p = c[2:]
        if p.startswith(("51", "56", "58", "15", "16")):
            continue
        n = nm.get(p)
        if n is None:
            unknown += 1
            continue
        if "ST" in n.upper():
            st_cols.append(j)
    if st_cols:
        P["mask"][:, st_cols] = False
    print(f"ST 剔除 {len(st_cols)} 只 | 名称未知（无法判 ST）{unknown} 只 ← 残留风险，已声明")

    # ---- 指数序列对齐 ----
    idx = idxall[idxall["date"] >= PANEL_FROM].reset_index(drop=True)
    assert list(idx["date"]) == list(cal), "指数与面板日历不一致"
    ic = idx["close"].to_numpy(float)
    io = idx["open"].to_numpy(float)
    iv = idx["volume"].to_numpy(float)
    ipct = np.full(T, np.nan); ipct[1:] = (ic[1:] / ic[:-1] - 1) * 100
    ivma = pd.Series(iv).rolling(20).mean().to_numpy()
    ivr = iv / ivma
    i_boom = (ipct >= 1.0) & (ic > io) & (ivr >= 1.2)      # 指数放量中阳线
    print(f"指数放量中阳线 {int(i_boom.sum())} 次（窗口内）| 最近 3 次："
          f"{[cal[i] for i in np.nonzero(i_boom)[0][-3:]]}")

    # ---- 个股量价 ----
    O = P["open"].astype(np.float64)
    C = P["close"].astype(np.float64)
    pct = np.full((T, N), np.nan); pct[1:] = (C[1:] / C[:-1] - 1) * 100
    vma20 = X.roll_mean(V, 20)
    with np.errstate(all="ignore"):
        vr = V / vma20
    yang = C > O

    # ---- 三/四臂 ----
    boom_day = np.repeat(i_boom[:, None], N, axis=1)
    A = boom_day & yang & (pct >= np.repeat(ipct[:, None], N, axis=1)) & (vr >= 1.0)
    A = A & np.isfinite(pct) & np.isfinite(vr)
    B = (pct <= -3.0) & (vr <= 0.8) & np.isfinite(vr)
    d3 = (C < np.vstack([np.full((1, N), np.nan), C[:-1]]))          # 今日跌
    dn1 = np.vstack([np.full((2, N), np.nan), C[:-2]])               # 前一日
    dn2 = np.vstack([np.full((3, N), np.nan), C[:-3]])               # 前二日
    dn3 = np.vstack([np.full((4, N), np.nan), C[:-4]])
    # 连跌 3 日：C[t]<C[t-1]<C[t-2]<C[t-3]
    c1 = np.vstack([np.full((1, N), np.nan), C[:-1]])
    c2 = np.vstack([np.full((2, N), np.nan), C[:-2]])
    c3 = np.vstack([np.full((3, N), np.nan), C[:-3]])
    down3 = (C < c1) & (c1 < c2) & (c2 < c3)
    v1 = np.vstack([np.full((1, N), np.nan), V[:-1]])
    v2 = np.vstack([np.full((2, N), np.nan), V[:-2]])
    vol_dec = (V < v1) & (v1 < v2)
    Cm = down3 & vol_dec & np.isfinite(V)

    # 共振标记（前 1..N 日内出现过）→ 当日缩量甲触发
    Aprev = np.vstack([np.zeros((1, N), dtype=bool), A.astype(bool)[:-1]])
    arms = {"A_共振当日": A.astype(bool), "B_缩量大跌甲": B.astype(bool),
            "C_越跌越缩乙": Cm.astype(bool)}
    for w in (5, 10, 20):
        arms[f"D_共振标记后{w}日内缩量大跌"] = B.astype(bool) & (X.roll_sum(Aprev.astype(float), w) > 0)

    # ---- 窗口截断：仅 2024-10-16 起可入场 ----
    s_i = cal.index(START)
    for k in arms:
        s = arms[k].copy()
        s[:s_i] = False
        arms[k] = s

    print("\n① 样本闸（窗口内，ST 与上市<60 已剔）")
    out = {"span": [START, "2026-09-18"], "panel": [cal[0], cal[-1]], "sample": {}, "runs": {},
           "notes": ["行业指数臂=不可判定（无行业指数行情序列）",
                     "共振∧缩量同日对同一票结构互斥 → 双条件只能是时序形态（D 臂）",
                     f"ST 剔除 {len(st_cols)} 只；名称未知 {unknown} 只无法判 ST"]}
    for k, S in arms.items():
        per = S.sum(axis=1)
        act = int((per > 0).sum())
        med = float(np.median(per[per > 0])) if act else 0.0
        gate = "PASS" if int(S.sum()) >= 100 and act >= 30 else "不可判定"
        out["sample"][k] = {"n_sig": int(S.sum()), "days_active": act, "median_per_day": round(med, 1),
                            "uniq": int(S.any(axis=0).sum()), "gate": gate}
        print(f"  {k:<28} 信号 {int(S.sum()):>7,}  活跃日 {act:>4}  日中位 {med:>6.1f}  "
              f"标的 {int(S.any(axis=0).sum()):>5}  样本闸 {gate}")

    # 沪深300 对照（窗口内）
    hs = ic[s_i:]
    hsd = [str(x) for x in idx["date"][s_i:]]
    bm = PORT.metrics(PORT.NAV0 * hs / hs[0], hsd, [], "沪深300")
    out["hs300"] = bm

    mavr = np.where(np.isfinite(vma20) & (vma20 > 0), V / vma20, np.nan)

    for mode in ("无限资金", "20仓"):
        print("\n" + "-" * 118)
        print(f"② {mode}（出场：爆量阴线 = E1 / 固定 20 日 = E2）")
        print("-" * 118)
        hdr = (f"  {'入场臂':<28}{'出场':<6}{'年化':>8}{'夏普':>8}{'最大回撤':>10}"
               f"{'按笔胜率':>9}{'按天胜率':>9}{'笔数':>7}{'平均并发':>9}{'末期净值':>10}")
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))
        for k, S in arms.items():
            for en, cfg in (("E1", EXIT_BOOM), ("E2", EXIT_FIX20)):
                try:
                    if mode == "无限资金":
                        nav, _, meta = PORT.simulate_unlimited(P, V, S, cfg)
                        m = PORT.metrics(nav, cal, [], k)
                        m.update(meta)
                        wr = meta["win_rate_per_trade"]; nt = meta["n_signal_events"]
                        conc = meta["avg_concurrency"]
                    else:
                        nav, tr = PORT.simulate(P, V, S, mavr, cfg, "量比升序", 20)
                        m = PORT.metrics(nav, cal, tr, k)
                        wr = m["win_rate_per_trade"] or 0.0; nt = m["n_trades"]; conc = 20
                except Exception as e:
                    print(f"  {k:<28}{en:<6} ERROR {str(e)[:50]}")
                    continue
                row = {"mode": mode, "exit": en, **m}
                out["runs"][f"{mode} · {k} · {en}"] = row
                flag = "" if (out["sample"][k]["gate"] == "PASS") else "  ⚠样本不可判定"
                print(f"  {k:<28}{en:<6}{m['cagr']:>8.2%}{m['sharpe']:>8.3f}{m['max_drawdown']:>10.2%}"
                      f"{wr:>9.1%}{m['win_rate_per_day']:>9.1%}{nt:>7}{conc:>9,.0f}"
                      f"{m['final_nav']:>10,.0f}{flag}")
        print(f"  {'沪深300 买入持有（对照）':<28}{'—':<6}{bm['cagr']:>8.2%}{bm['sharpe']:>8.3f}"
              f"{bm['max_drawdown']:>10.2%}{'—':>9}{bm['win_rate_per_day']:>9.1%}{'—':>7}{'—':>9}"
              f"{bm['final_nav']:>10,.0f}")

    out["elapsed_s"] = round(time.time() - t0, 1)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n结果已落盘 {OUT_JSON}（{out['elapsed_s']}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
