# -*- coding: utf-8 -*-
"""小步碎阳 · 组合层回测（XBSY-PORT-0921 · 2026-09-21 用户要年化/胜率/夏普/回撤）
================================================================================
为什么必须有这一层
--------------------------------------------------------------------------------
事件级（`xbsy_0921`/`xbsy_exit_0921`）只能给「每笔均值 / 超额 / 聚类 t」。
年化、夏普、回撤是**资金曲线**的函数 → 必须定「同时持多少只、钱怎么分、超额信号怎么取舍」，
也就是必须先过**容量门**（★196）：信号日均 92 笔 × 持仓中位 23 日 ≈ 2,100 并发仓位，
17 万本金下每仓 81 元 → 佣金最低 5 元 = 620bp/单边。**故必须设并发上限。**

预注册（看任何收益数字之前固定）
--------------------------------------------------------------------------------
- 本金 170,000 元；**并发上限 MAX_POS = 20**（→ 每仓 8,500 元 → 佣金约 6bp/单边，与 20bp 成本档自洽）
- 每日新仓预算 = min(可用现金, 前一日净值 / MAX_POS)（等权、不追高杠杆）
- 入场：T 日收盘信号 → **T+1 开盘买入**（成交价 = 开盘×(1+20bp 滑点)+佣金 2.5bp/最低 5 元）
- 出场：规则确认 → **次日开盘卖**（开盘×(1−20bp)）；上限到期 → **当收盘卖**（收盘×(1−20bp)）
- 排序键三档并列（**不事后择优**）：
    · 量比升序（V / MA(V,20) 最小优先）—— 最贴「碎步」本意
    · 随机（种子 20260921，每日在当日候选中随机取）—— 校准用
    · 代码序（确定性对照，无信息）
- 出场规则两档并列：X2（爆量≥3×MA(V,20)+次日阴，cap60）／ X7（固定 20 日）
- MAX_POS=10 作为密度敏感性
- 判据：年化 / 夏普（日收益×√242）/ 最大回撤（净值口径）/ 胜率（**按笔净成本 + 按天**双给）
- 成本双档：20bp（基准）/ 50bp（压力）

用法：cd quant-weight-system && python backtest/xbsy_port_0921.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

import factor_gate as FG                                    # noqa: E402
import xbsy_0921 as X                                       # noqa: E402
import xbsy_exit_0921 as E                                  # noqa: E402

OUT_JSON = str(HERE / "xbsy_port_0921.json")
NAV0 = 170000.0
SLIP = 0.0020
COMM, MIN_COMM = 0.00025, 5.0
CAP20 = dict(boom="q3", lag=1, ma5=False, cap=60)           # X2
CAP20F = dict(boom=None, lag=1, ma5=False, cap=20)          # X7 基准


def simulate(P, V, SIG, ratio, cfg, rank_key, max_pos, slip=SLIP, comm=COMM, min_comm=MIN_COMM):
    """事件驱动组合层：并发上限 + 等权 + T+1 开盘执行。返回净值序列与成交记录。"""
    O = P["open"].astype(np.float64)
    C = P["close"].astype(np.float64)
    M = P["mask"]
    T, N = C.shape
    NX = E.exit_day_matrix(O, C, V, cfg)

    cand_by_day = {}                                         # 信号日 t → 候选股票数组（T+1 开盘买）
    for t in range(T - 1):
        idx = np.nonzero(SIG[t] & M[t])[0]
        if idx.size:
            cand_by_day[t] = idx

    cash = NAV0
    positions = {}                                           # code → dict(shares, cost, sell_day, sell_at)
    nav_hist = np.full(T, np.nan)
    trades = []
    rng = np.random.default_rng(20260921)

    for t in range(T):
        # 1) 开盘卖（规则出场）
        for code in [c for c, p in positions.items() if p["sell_day"] == t and p["sell_at"] == "open"]:
            p = positions.pop(code)
            px = O[t, code]
            if not np.isfinite(px) or px <= 0:
                px = C[t, code]
            if not np.isfinite(px) or px <= 0:
                continue
            sell_px = px * (1 - slip)
            amt = sell_px * p["shares"]
            cash += amt - max(amt * comm, min_comm)
            trades.append({"code": code, "in": p["date"], "out": t,
                           "ret": sell_px / p["px"] - 1 - 2 * comm})
        # 2) 开盘买（信号日 t-1）
        idx = cand_by_day.get(t - 1)
        if idx is not None:
            free = max_pos - len(positions)
            if free > 0:
                avail = np.array([i for i in idx if i not in positions and np.isfinite(O[t, i]) and O[t, i] > 0])
                if avail.size:
                    if rank_key == "量比升序":
                        key = ratio[t - 1, avail]
                        key = np.where(np.isfinite(key), key, np.inf)
                        order = avail[np.argsort(key, kind="stable")]
                    elif rank_key == "随机":
                        order = rng.permutation(avail)
                    else:
                        order = avail
                    budget_nav = nav_hist[t - 1] if np.isfinite(nav_hist[t - 1]) else NAV0
                    for i in order[:free]:
                        budget = min(cash, budget_nav / max_pos)
                        px = O[t, i] * (1 + slip)
                        shares = int(budget // (px * 100)) * 100
                        if shares < 100:
                            continue
                        amt = shares * px
                        fee = max(amt * comm, min_comm)
                        if amt + fee > cash:
                            continue
                        cash -= amt + fee
                        sd = int(NX[t, i])
                        cap_d = min(t + cfg["cap"], T - 1)
                        if sd <= cap_d:
                            positions[i] = dict(shares=shares, px=px, date=t, sell_day=sd, sell_at="open")
                        else:
                            positions[i] = dict(shares=shares, px=px, date=t, sell_day=cap_d, sell_at="close")
        # 3) 收盘卖（上限到期）
        for code in [c for c, p in positions.items() if p["sell_day"] == t and p["sell_at"] == "close"]:
            p = positions.pop(code)
            px = C[t, code]
            if not np.isfinite(px) or px <= 0:
                continue
            sell_px = px * (1 - slip)
            amt = sell_px * p["shares"]
            cash += amt - max(amt * comm, min_comm)
            trades.append({"code": code, "in": p["date"], "out": t,
                           "ret": sell_px / p["px"] - 1 - 2 * comm})
        # 4) 净值
        mv = 0.0
        for code, p in positions.items():
            px = C[t, code]
            if np.isfinite(px):
                mv += p["shares"] * px
        nav_hist[t] = cash + mv

    return nav_hist, trades


def metrics(nav, dates, trades, tag):
    nav = np.asarray(nav, dtype=np.float64)
    nav = nav[np.isfinite(nav)]
    if nav.size < 30:
        return {"tag": tag, "verdict": "不可判定"}
    r = nav[1:] / nav[:-1] - 1
    yrs = nav.size / 242.0
    cagr = (nav[-1] / nav[0]) ** (1 / yrs) - 1
    sharpe = float(np.mean(r) / np.std(r, ddof=1) * np.sqrt(242)) if np.std(r, ddof=1) > 0 else float("nan")
    peak = np.maximum.accumulate(nav)
    mdd = float((nav / peak - 1).min())
    rets = np.array([t["ret"] for t in trades]) if trades else np.array([])
    holds = np.array([t["out"] - t["in"] for t in trades]) if trades else np.array([])
    return {
        "tag": tag, "days": int(nav.size), "years": round(yrs, 2),
        "total_return": round(float(nav[-1] / nav[0] - 1), 4),
        "cagr": round(float(cagr), 4), "sharpe": round(sharpe, 3), "max_drawdown": round(mdd, 4),
        "n_trades": int(rets.size),
        "win_rate_per_trade": round(float((rets > 0).mean()), 4) if rets.size else None,
        "mean_per_trade": round(float(rets.mean()), 5) if rets.size else None,
        "win_rate_per_day": round(float((r > 0).mean()), 4),
        "hold_median": int(np.median(holds)) if holds.size else None,
        "final_nav": round(float(nav[-1]), 0),
    }


def simulate_unlimited(P, V, SIG, cfg, slip=SLIP, comm=COMM, min_comm=MIN_COMM):
    """**不设资金上限**：全部信号都吃，等权，不设并发上限。
    构造：每日「活跃持仓」的当日收益取等权平均 → 逐日复利成净值。
    ⚠ 该构造隐含「每日把全部持仓再平衡回等权」（无限资金下的理想化口径），
      **未计每日再平衡的换手成本** —— 故这一项对成本是乐观的，需与上表对照看。
    成本仍按真实价量计：入场 开盘×(1+20bp)+佣金、出场 开盘/收盘×(1−20bp)+佣金。
    """
    O = P["open"].astype(np.float64)
    C = P["close"].astype(np.float64)
    M = P["mask"]
    T, N = C.shape
    NX = E.exit_day_matrix(O, C, V, cfg)

    day_idx, stk = np.nonzero(SIG & M)
    e = day_idx + 1
    ok = e < T
    day_idx, stk, e = day_idx[ok], stk[ok], e[ok]
    buy_px = O[e, stk] * (1 + slip)
    ok = np.isfinite(buy_px) & (buy_px > 0)
    day_idx, stk, e, buy_px = day_idx[ok], stk[ok], e[ok], buy_px[ok]

    cap_d = np.minimum(e + cfg["cap"], T - 1)
    nx = NX[e, stk]
    rule = nx <= cap_d
    d = np.where(rule, np.minimum(nx, T - 1), cap_d)
    sell_px = np.where(rule, O[d, stk] * (1 - slip), C[d, stk] * (1 - slip))
    ok = np.isfinite(sell_px) & (sell_px > 0)
    stk, e, d, buy_px, sell_px, rule = (stk[ok], e[ok], d[ok], buy_px[ok], sell_px[ok], rule[ok])

    active_end = np.where(rule, d - 1, d)                    # 开盘卖 → 最后活跃日 = d-1
    active_end = np.maximum(active_end, e)
    L = active_end - e + 1
    L = np.maximum(L, 1)
    tot = int(L.sum())
    idx = np.arange(tot)
    starts = np.concatenate([[0], np.cumsum(L)[:-1]])
    rep_st = np.repeat(starts, L)
    day_flat = idx - rep_st + np.repeat(e, L)
    stk_flat = np.repeat(stk, L)
    L_flat = np.repeat(L, L)
    is_first = (idx - rep_st) == 0
    is_last = (idx - rep_st) == (L_flat - 1)

    val = C[day_flat, stk_flat]
    val = np.where(is_last, np.repeat(sell_px, L), val)
    prev = np.where(day_flat == np.repeat(e, L), np.repeat(buy_px, L),
                    C[np.maximum(day_flat - 1, 0), stk_flat])
    r = val / prev - 1.0
    okr = np.isfinite(r) & (prev > 0)
    s = np.zeros(T); c = np.zeros(T)
    np.add.at(s, day_flat[okr], r[okr])
    np.add.at(c, day_flat[okr], 1.0)
    rp = np.divide(s, c, out=np.zeros(T), where=c > 0)

    # 佣金：按**每仓名义 8,500 元**（= NAV0/20，与上表 20 仓口径一致）计 → 最低 5 元 = 5.9bp/单边。
    # ⚠ 首版误用「1 手(100股)」作每笔名义 → 最低 5 元变成 50bp/单边，多扣约 90bp 往返（已修）。
    NOT = NAV0 / 20.0
    fee_side = max(NOT * comm, min_comm) / NOT
    day_flat_e = day_flat[is_first & okr]
    np.add.at(s, day_flat_e, -fee_side)
    np.add.at(c, day_flat_e, 0.0)
    day_flat_x = day_flat[is_last & okr]
    np.add.at(s, day_flat_x, -fee_side)
    with np.errstate(all="ignore"):
        rp = np.divide(s, c, out=np.zeros(T), where=c > 0)

    nav = NAV0 * np.cumprod(1 + rp)
    trade_ret = sell_px / buy_px - 1 - 2 * fee_side            # 逐笔口径（供胜率）
    trades = []
    meta = {"avg_concurrency": round(float(c[c > 0].mean()), 1) if (c > 0).any() else 0.0,
            "max_concurrency": int(c.max()), "n_signal_events": int(stk.size),
            "days_with_positions": int((c > 0).sum()),
            "win_rate_per_trade": round(float((trade_ret > 0).mean()), 4),
            "mean_per_trade": round(float(trade_ret.mean()), 5),
            "median_per_trade": round(float(np.median(trade_ret)), 5)}
    return nav, trades, meta


def main():
    t0 = time.time()
    print("=" * 104)
    print("小步碎阳 · 组合层（XBSY-PORT-0921）· 并发上限 + 等权 + T+1 开盘执行")
    print("=" * 104)
    P = FG.load_panel(X.PANEL)
    D = np.load(X.PANEL, allow_pickle=True)
    codes, cal = D["codes"], D["cal"]
    T, N = P["close"].shape
    V = X.load_volume([str(c) for c in codes], [str(d) for d in cal])
    SIG = X.build_arms(P, V)["A_tdx"]
    mav20 = X.roll_mean(V, 20)
    ratio = np.where(np.isfinite(mav20) & (mav20 > 0), V / mav20, np.nan)
    print(f"面板 {T} 日 × {N} 只 | {cal[0]} → {cal[-1]} | 信号 A_tdx n={int(SIG.sum())}")

    # 沪深300 同窗 B&H 对照
    idx = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
    idx = idx[(idx["date"] >= str(cal[0])) & (idx["date"] <= str(cal[-1]))]
    hs = idx["close"].to_numpy(dtype=np.float64)
    hs_nav = NAV0 * hs / hs[0]
    print(f"沪深300 同窗：{hs[0]:.0f} → {hs[-1]:.0f}")

    runs = [
        ("X2爆量3x+次日阴 · 量比升序 · 20仓", CAP20, "量比升序", 20, SLIP),
        ("X2爆量3x+次日阴 · 随机 · 20仓", CAP20, "随机", 20, SLIP),
        ("X2爆量3x+次日阴 · 代码序 · 20仓", CAP20, "代码序", 20, SLIP),
        ("X7固定20日 · 量比升序 · 20仓", CAP20F, "量比升序", 20, SLIP),
        ("X7固定20日 · 随机 · 20仓", CAP20F, "随机", 20, SLIP),
        ("X2爆量3x+次日阴 · 量比升序 · 10仓", CAP20, "量比升序", 10, SLIP),
        ("X2爆量3x+次日阴 · 量比升序 · 20仓 · 50bp", CAP20, "量比升序", 20, 0.0050),
        # 机制检验（非择优）：仓位上限是否就是瓶颈？佣金「最低 5 元」在 200 仓时=59bp/单边，模拟器会如实算进去
        ("X2爆量3x+次日阴 · 量比升序 · 50仓", CAP20, "量比升序", 50, SLIP),
        ("X2爆量3x+次日阴 · 量比升序 · 100仓", CAP20, "量比升序", 100, SLIP),
        ("X2爆量3x+次日阴 · 量比升序 · 200仓", CAP20, "量比升序", 200, SLIP),
        ("X2爆量3x+次日阴 · 随机 · 200仓", CAP20, "随机", 200, SLIP),
    ]
    out = {"nav0": NAV0, "span": [str(cal[0]), str(cal[-1])], "runs": {}, "hs300": None}
    bm = metrics(hs_nav, idx["date"].tolist(), [], "沪深300 B&H")
    out["hs300"] = bm
    print("\n" + "-" * 104)
    print(f"  {'组合配置':<42}{'年化':>9}{'夏普':>8}{'最大回撤':>10}{'按笔胜率':>9}"
          f"{'按天胜率':>9}{'笔数':>8}{'末期净值':>11}")
    print("  " + "-" * 100)
    print(f"  {'沪深300 买入持有（对照）':<42}{bm['cagr']:>9.2%}{bm['sharpe']:>8.3f}"
          f"{bm['max_drawdown']:>10.2%}{'—':>9}{bm['win_rate_per_day']:>9.1%}"
          f"{0:>8}{bm['final_nav']:>11,.0f}")
    for tag, cfg, rk, mp, sl in runs:
        nav, trades = simulate(P, V, SIG, ratio, cfg, rk, mp, slip=sl)
        m = metrics(nav, cal, trades, tag)
        out["runs"][tag] = m
        print(f"  {tag:<42}{m['cagr']:>9.2%}{m['sharpe']:>8.3f}{m['max_drawdown']:>10.2%}"
              f"{(m['win_rate_per_trade'] or 0):>9.1%}{m['win_rate_per_day']:>9.1%}"
              f"{m['n_trades']:>8}{m['final_nav']:>11,.0f}")

    print("\n" + "-" * 104)
    print("★ 不设资金上限（全吃信号 · 等权 · 无并发上限）—— 用户 2026-09-21 指定")
    print("-" * 104)
    hdr2 = (f"  {'无限资金配置':<34}{'年化':>8}{'夏普':>8}{'最大回撤':>10}{'按笔胜率':>9}"
            f"{'按天胜率':>9}{'每笔均值':>10}{'平均并发':>10}{'末期净值':>11}")
    print(hdr2)
    print("  " + "-" * (len(hdr2) - 2))
    UNL = [("X1 爆量≥2x + 次日阴", dict(boom="q2", lag=1, ma5=False, cap=60)),
           ("X2 爆量≥3x + 次日阴", CAP20),
           ("X8 爆量≥2x + 不设上限", dict(boom="q2", lag=1, ma5=False, cap=250)),
           ("X4 连5日破MA5（你的止损）", dict(boom=None, lag=1, ma5=True, cap=60)),
           ("X5 爆量阴 + 破线（先到）", dict(boom="q2", lag=1, ma5=True, cap=60)),
           ("X7 固定 20 日（对照）", CAP20F)]
    for tag, cfg in UNL:
        nav, _, meta = simulate_unlimited(P, V, SIG, cfg)
        m = metrics(nav, cal, [], f"无限资金 · {tag}")
        m.update(meta)
        out["runs"][f"无限资金 · {tag}"] = m
        print(f"  {tag:<34}{m['cagr']:>8.2%}{m['sharpe']:>8.3f}{m['max_drawdown']:>10.2%}"
              f"{meta['win_rate_per_trade']:>9.1%}{m['win_rate_per_day']:>9.1%}"
              f"{meta['mean_per_trade']:>10.4f}{meta['avg_concurrency']:>10,.0f}{m['final_nav']:>11,.0f}")
    print(f"  {'沪深300 买入持有（对照）':<34}{bm['cagr']:>8.2%}{bm['sharpe']:>8.3f}"
          f"{bm['max_drawdown']:>10.2%}{'—':>9}{bm['win_rate_per_day']:>9.1%}{'—':>10}"
          f"{'—':>10}{bm['final_nav']:>11,.0f}")

    out["elapsed_s"] = round(time.time() - t0, 1)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n结果已落盘 {OUT_JSON}（{out['elapsed_s']}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
