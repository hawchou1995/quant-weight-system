# -*- coding: utf-8 -*-
"""
见底信号共振 × 高点警示「顶」离场 × 参数网格回测（JIANDI-TOP-GRID-0924）
================================================================================
策略（用户 2026-09-24 确认口径）：
- 入场：《见底信号》6 信号（入市/机会/见底/快显/来临/等）同日 >=K 共振，K in {2, 3}
- 离场：a)《高点警示》「顶」信号（收盘确认 -> 次日开盘卖）；b) 固定持有 N 日到期（open[B+N] 卖）；
        先到者离场；不设其他止盈止损。
- 执行：信号 T 收盘确认 -> T+1 开盘买入（B=T+1）；两段式记账（buy open->close / mid close->close / sell 前收->open）
- 成本：单边 0.575%（基准，= 09-06 家族口径）与 0.2%（敏感性）
- 口径：主板（board_of=='main'）、2016-06-01 起、日线；四闸（n>=30/wr>=46%/med>0/mean>0/ex_b>0）+ 分年 + 等权 NAV
- 信号来源（可溯源）：
    《见底信号》公众号「指标作者」2026-09-06（实现同源复用 backtest/jiandi_signal_0906.py）
    《高点警示》公众号「指标作者」2026-09-05（本脚本首次实现；PEAKBARS「顶A/风险区」为未来函数类，剔除）
- 沿用家族口径的未处理项（报告中披露）：未剔除 ST/停牌次日、未剔除涨停/一字板买入
"""
import json
import os
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

T0 = time.time()


def log(msg):
    print(f"[{time.time()-T0:7.1f}s] {msg}", flush=True)


HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)  # QWS 根（2026-09-24 云端可移植口径）
CACHE = os.path.join(BASE, "v8_factor_cache.pkl")
IDX_CSV = os.path.join(BASE, "index_000300.csv")
OUT_DIR = os.path.join(HERE, "jiandi_top_grid_0924_out")
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, HERE)
import jiandi_signal_0906 as JG  # noqa: E402

BACKTEST_START = pd.Timestamp("2016-06-01")
KS = [2, 3]
NS = [1, 2, 3, 5, 10, 20]  # 1/2/3/5=主网格（用户口径）；10/20=补充诊断（看「顶」离场何时开始触发）
COSTS = [0.00575, 0.002]
SIG_KEYS = ("rushi", "jihui", "jiandi", "kuaixian", "laiLin", "deng")
SIG_CN = {"rushi": "入市", "jihui": "机会", "jiandi": "见底",
          "kuaixian": "快显", "laiLin": "来临", "deng": "等"}


def add_ding(df):
    """《高点警示》「顶」= CROSS(短势,长势) AND REF(长势,1)>80（作者原式）。
    WAN1=(C-LLV(L,18))/(HHV(H,18)-LLV(L,18))*100；WAN2=SMA(WAN1,9,1)；WAN3=SMA(WAN2,3,1)
    长势=3*WAN2-2*WAN3；短势=EMA(WAN2,3)
    """
    c, h, l = df["close"], df["high"], df["low"]
    llv = l.rolling(18, min_periods=18).min()
    hhv = h.rolling(18, min_periods=18).max()
    wan1 = (c - llv) / (hhv - llv).replace(0, np.nan) * 100
    wan2 = wan1.ewm(alpha=1 / 9, adjust=False).mean()
    wan3 = wan2.ewm(alpha=1 / 3, adjust=False).mean()
    chang = 3 * wan2 - 2 * wan3
    duan = wan2.ewm(span=3, adjust=False).mean()
    cross = (duan > chang) & (duan.shift(1) <= chang.shift(1))
    return (cross & (chang.shift(1) > 80)).fillna(False).to_numpy()


def main():
    log("加载缓存 ...")
    raw = pd.read_pickle(CACHE)
    cache = {}
    for c, df in raw.items():
        if df is None or JG.board_of(c) != "main":
            continue
        cache[c] = df.sort_index()
    log(f"主板限定: {len(cache)} 只")
    lasts = [df.index[-1] for df in cache.values() if len(df) > 0]
    firsts = [df.index[0] for df in cache.values() if len(df) > 0]
    log(f"数据覆盖: {min(firsts)} -> {max(lasts)}")

    idx = pd.read_csv(IDX_CSV)
    idx["date"] = pd.to_datetime(idx["date"])
    idx = idx.sort_values("date").reset_index(drop=True)
    idx_open = idx.set_index("date")["open"]
    all_oo = []
    for code, df in cache.items():
        if len(df) < 30:
            continue
        all_oo.append(pd.DataFrame({"date": df.index.to_numpy(),
                                    "ret": df["open"].pct_change().to_numpy()}))
    bdf = pd.concat(all_oo, ignore_index=True)
    med_ret = bdf.groupby("date")["ret"].median()
    med_cum = (1 + med_ret).cumprod()
    log(f"基准构建完成（中位累计 {len(med_cum)} 日）")

    log("计算信号（见底 x6 + 高点警示「顶」）...")
    events = {(K, N): [] for K in KS for N in NS}
    comp2 = defaultdict(int)
    n_sig_total = 0
    n_ding_total = 0
    n_dropped = 0
    for code, df in cache.items():
        if len(df) < 70:
            continue
        sm = JG.jiandi_signals(code, df)
        sig6 = np.stack([np.asarray(sm[k], dtype=bool) for k in SIG_KEYS], axis=1)
        cnt = sig6.sum(axis=1)
        if not cnt.any():
            continue
        ding = add_ding(df)
        opens = df["open"].to_numpy()
        closes = df["close"].to_numpy()
        bad = (~np.isfinite(opens)) | (~np.isfinite(closes)) | (opens <= 0) | (closes <= 0)
        dates = df.index
        n = len(df)
        n_sig_total += int(cnt.astype(bool).sum())
        n_ding_total += int(ding.sum())
        for K in KS:
            for i in np.where(cnt >= K)[0]:
                if dates[i] < BACKTEST_START:
                    continue
                B = i + 1
                if B >= n or bad[B]:
                    continue
                if K == 2:
                    combo = "+".join(SIG_CN[SIG_KEYS[j]] for j in range(6) if sig6[i, j])
                    comp2[combo] += 1
                for N in NS:
                    sell, reason = B + N, "cap"
                    for d in range(B, min(B + N, n)):
                        if ding[d]:
                            sell, reason = d + 1, "top"
                            break
                    if sell >= n or bad[B:sell + 1].any():
                        n_dropped += 1
                        continue
                    events[(K, N)].append((dates[i], code, B, sell, reason))
    log(f"信号合计: 见底6信号日 {n_sig_total}; 「顶」{n_ding_total}; 丢弃事件 {n_dropped}")
    for (K, N), evs in sorted(events.items()):
        log(f"  K>={K} N={N}: {len(evs)} 事件")
    log(f"K=2 共振构成 top: {sorted(comp2.items(), key=lambda x: -x[1])[:12]}")

    def make_rows(evs, cost):
        rows = []
        for sig_dt, code, B, sell, reason in evs:
            df = cache[code]
            bo = df["open"].iloc[B]
            so = df["open"].iloc[sell]
            ret = so * (1 - cost) / (bo * (1 + cost)) - 1
            b0 = idx_open.get(df.index[B])
            b1 = idx_open.get(df.index[sell])
            ex_b = ret - (b1 / b0 - 1) if (b0 is not None and b1 is not None and b0 > 0) else np.nan
            m0 = med_cum.get(df.index[B])
            m1 = med_cum.get(df.index[sell])
            ex_m = ret - (m1 / m0 - 1) if (m0 is not None and m1 is not None and m0 > 0) else np.nan
            rows.append((sig_dt, ret, ex_b, ex_m, reason, sell - B))
        return rows

    def agg(rows):
        fr = np.array([r[1] for r in rows], dtype=float)
        ex_b = np.array([r[2] for r in rows], dtype=float)
        ex_m = np.array([r[3] for r in rows], dtype=float)
        n = len(fr)
        wr = (fr > 0).mean() * 100
        med = np.median(fr) * 100
        mean = fr.mean() * 100
        ex_b_m = np.nanmean(ex_b) * 100
        ex_m_m = np.nanmean(ex_m) * 100
        wins = fr[fr > 0]
        losses = fr[fr < 0]
        pf = (wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else 0.0
        gates = {"n_ok": n >= 30, "wr_ok": wr >= 46, "med_ok": med > 0,
                 "mean_ok": mean > 0, "ex_ok": ex_b_m > 0}
        res = {"n": n, "wr": round(wr, 2), "med": round(med, 3), "mean": round(mean, 3),
               "ex_b": round(ex_b_m, 3), "ex_m": round(ex_m_m, 3), "pf": round(pf, 2),
               "gates": "PASS" if all(gates.values()) else f"fail({sum(gates.values())}/5)",
               "gate_detail": gates}
        yr = defaultdict(list)
        for r in rows:
            yr[pd.Timestamp(r[0]).year].append(r[1])
        res["yearly"] = {y: [len(v), round(float(np.mean(v)) * 100, 2), round(float(np.median(v)) * 100, 2)]
                         for y, v in sorted(yr.items())}
        tops = [r for r in rows if r[4] == "top"]
        res["top_exit_n"] = len(tops)
        res["top_exit_share"] = round(len(tops) / max(n, 1), 4)
        res["avg_hold"] = round(float(np.mean([r[5] for r in rows])), 2)
        hh = defaultdict(int)
        for r in rows:
            hh[r[5]] += 1
        res["hold_hist"] = {str(k): v for k, v in sorted(hh.items())}
        return res

    def nav_stats(evs, cost):
        daily = defaultdict(list)
        for sig_dt, code, B, sell, reason in evs:
            df = cache[code]
            o = df["open"].to_numpy()
            c = df["close"].to_numpy()
            dts = df.index
            daily[dts[B]].append(c[B] / o[B] - 1 - cost)
            for k in range(B + 1, sell):
                daily[dts[k]].append(c[k] / c[k - 1] - 1)
            daily[dts[sell]].append(o[sell] / c[sell - 1] - 1 - cost)
        if not daily:
            return None
        s = pd.Series({d: float(np.mean(v)) for d, v in daily.items()}).sort_index()
        full = pd.date_range(s.index[0], s.index[-1], freq="B")
        s = s.reindex(full, fill_value=0.0)
        nav = (1 + s).cumprod()
        worst = s.nsmallest(3)
        span = (nav.index[-1] - nav.index[0]).days / 365.25
        dd = (nav / nav.cummax() - 1).min()
        sharpe = s.mean() / s.std() * np.sqrt(252) if s.std() > 0 else 0.0
        return {"nav_worst3": [[str(d)[:10], round(float(v), 4)] for d, v in worst.items()],
                "nav_total": round((nav.iloc[-1] - 1) * 100, 2),
                "nav_cagr": round(((nav.iloc[-1]) ** (1 / max(span, 1e-9)) - 1) * 100, 2),
                "nav_maxdd": round(dd * 100, 2),
                "nav_sharpe": round(sharpe, 3)}

    results = []
    for K in KS:
        for N in NS:
            evs = events[(K, N)]
            for cost in COSTS:
                rows = make_rows(evs, cost)
                if len(rows) < 15:
                    results.append({"K": K, "N": N, "cost": cost, "n": len(rows),
                                    "gates": "fail(n<15)"})
                    continue
                r = agg(rows)
                r.update({"K": K, "N": N, "cost": cost})
                st = nav_stats(evs, cost)
                if st:
                    r.update(st)
                results.append(r)
                log(f"K>={K} N={N} cost={cost:.4f}: n={r['n']} wr={r['wr']}% med={r['med']}% "
                    f"mean={r['mean']}% ex_b={r['ex_b']}% pf={r['pf']} gates={r['gates']} "
                    f"top_share={r.get('top_exit_share')} nav_cagr={r.get('nav_cagr')}%")

    flat = [{k: v for k, v in r.items() if k not in ("yearly", "hold_hist", "gate_detail")}
            for r in results]
    pd.DataFrame(flat).to_csv(os.path.join(OUT_DIR, "jiandi_top_grid_0924.csv"),
                              index=False, encoding="utf-8-sig")
    meta = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "task": "JIANDI-TOP-GRID-0924 见底信号共振 x 高点警示「顶」离场 x 参数网格",
        "entry_rule": "《见底信号》6 信号同日 >=K 共振（K in {2,3}）",
        "exit_rule": "「顶」信号次日开盘 或 固定持有 N 日到期（open[B+N]），先到者离场；无其他止盈止损",
        "signals_src": {
            "bottom": "《技术指标公式源码编写 见底信号》公众号-指标作者 2026-09-06（同源复用 backtest/jiandi_signal_0906.py）",
            "top": "《技术指标公式源码编写 高点警示》公众号-指标作者 2026-09-05（顶=CROSS(短势,长势) AND REF(长势,1)>80；顶A/PEAKBARS 已剔除）"},
        "execution": "信号 T 收盘确认 -> T+1 开盘买；两段式记账；主板(sh60/sz00)、2016-06-01 起、日线",
        "cost": "单边 0.575% 基准 / 0.2% 敏感性（含滑点）",
        "universe_n": len(cache),
        "data_first": str(min(firsts)), "data_last": str(max(lasts)),
        "n_sig_days_6": n_sig_total, "n_ding_days": n_ding_total, "n_dropped": n_dropped,
        "k2_composition_top": dict(sorted(comp2.items(), key=lambda x: -x[1])[:30]),
        "notes": ["未剔除 ST/涨停/一字板（沿用家族口径）",
                  "「顶A/风险区」基于 PEAKBARS=未来函数类，不可回测 -> 剔除",
                  "NAV=等权重叠（同日多事件取均收益），与 09-06 家族 opt_grid 口径一致"],
        "results": results,
    }
    with open(os.path.join(OUT_DIR, "jiandi_top_grid_0924.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1, default=str)
    log("SAVED " + OUT_DIR)
    tbl = pd.DataFrame(flat)
    if "gates" in tbl:
        cols = [c for c in ["K", "N", "cost", "n", "wr", "med", "mean", "ex_b", "pf", "gates",
                            "top_exit_share", "avg_hold", "nav_cagr", "nav_maxdd", "nav_sharpe"] if c in tbl]
        pd.set_option("display.width", 250)
        print(tbl[cols].to_string(index=False))
    log("完成")


if __name__ == "__main__":
    main()
