# -*- coding: utf-8 -*-
"""r2 · 幸存信号组合引擎 + 随机安慰剂（2026-09-12）
================================================================
供 66 公式幸存信号（事件型）做组合级验证：
  组合：信号后 L 日内为候选 → 按 amt20 流动性降序取 N 只等权 → 持有 hold 日 →
        T+1 开盘执行；可选 MA200 市况门控（门关=不新开仓）。
  安慰剂：按幸存信号的「每日信号数轮廓」把信号随机撒到当日有成交的股票上，
        同引擎 100 seeds → real vs placebo max/quantile（T3/C5 同款零假设）。
纪律：N/hold/L/门控为预注册网格；n_trials 如实入审计。
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
sys.path.insert(0, str(BASE))
import v8_selector as V  # noqa: E402

COMM = V.COMMISSION       # 2.5bp
TAX = V.SELL_TAX          # 5bp


def load_universe():
    pool = V.load_pool(use_cache=True)
    codes = [c for c in pool if c.startswith(("sh60", "sz00"))]
    idx = V.load_index(200).set_index("date")
    gate_map = idx["in_market"].to_dict()
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    return pool, codes, gate_map, all_days


def run_signal_portfolio(sigs, pool, codes, gate_map, all_days, hold=20, n=10,
                         lookback=5, use_gate=True, slip_bps=0, cash0=1_000_000.0,
                         min_amt=5e6, min_px=2.0):
    """sigs: {code: pd.Series(bool, index=date)}；返回 (eq_df, trades, meta)"""
    idx_pos = {d: i for i, d in enumerate(all_days)}
    # 预取数组
    arr = {}
    for code in codes:
        df = pool[code]
        if code not in sigs:
            continue
        s = sigs[code].reindex(df.index).fillna(False).to_numpy(bool)
        o = df["open"].to_numpy(float)
        c = df["close"].to_numpy(float)
        amt = df["amt20"].to_numpy(float)
        pos_ok = df["ma200_pos"].to_numpy(float)
        dpos = np.array([idx_pos.get(d, -1) for d in df.index], dtype=np.int64)
        arr[code] = (s, o, c, amt, pos_ok, dpos, df.index)
    cash = cash0
    holdings = {}   # code -> shares
    ep = {}
    ed = {}
    eq, trades = [], []
    last_close = {}
    recent = {}     # code -> last signal day index (in all_days)
    t0 = time.time()
    for di, day in enumerate(all_days):
        dstr = str(day.date())
        # 1) 挂单执行（T-1 收盘决策 → 今日开盘成交）
        if holdings:
            for code in list(holdings.keys()):
                a = arr.get(code)
                if a is None:
                    continue
                s, o, c, amt, pos_ok, dpos, dates = a
                j = dpos[di] if di < len(dpos) else -1
                # 找到今日在该股票 df 中的位置
                k = dates.get_loc(day) if day in dates else -1
                if k < 0:
                    px = last_close.get(code)
                else:
                    px = o[k] if np.isfinite(o[k]) and o[k] > 0 else last_close.get(code)
                if px is None or px <= 0 or not np.isfinite(px):
                    continue
                sh = holdings.pop(code)
                px_eff = px * (1 - slip_bps / 10000)
                tax = sh * px_eff * TAX
                proceeds = sh * px_eff * (1 - COMM) - tax
                pnl = proceeds - sh * ep[code] * (1 + COMM)
                trades.append({"pnl": pnl, "pnl_pct": (px_eff / ep[code] - 1) * 100,
                               "entry": str(ed[code].date()), "exit": dstr, "code": code})
                cash += proceeds
        # 2) 再平衡日：选股
        if di % hold == 0:
            ok = (not use_gate) or gate_map.get(day, False)
            if ok:
                cand = []
                for code in codes:
                    a = arr.get(code)
                    if a is None:
                        continue
                    s, o, c, amt, pos_ok, dpos, dates = a
                    k = dates.get_loc(day) if day in dates else -1
                    if k < lookback:
                        continue
                    if not s[max(0, k - lookback + 1):k + 1].any():
                        continue
                    if not np.isfinite(c[k]) or c[k] < min_px:
                        continue
                    if not np.isfinite(amt[k]) or amt[k] < min_amt:
                        continue
                    cand.append((code, amt[k]))
                cand.sort(key=lambda kv: -kv[1])
                picks = cand[:n]
                if picks:
                    port_value = cash + sum(sh * (last_close.get(cc, ep[cc])) for cc, sh in holdings.items())
                    budget = port_value / n
                    for code, _amt in picks:
                        if code in holdings or len(holdings) >= n:
                            continue
                        a = arr[code]
                        s, o, c_, amt, pos_ok, dpos, dates = a
                        k = dates.get_loc(day) if day in dates else -1
                        nk = k + 1
                        if nk >= len(dates):
                            continue
                        px = o[nk]
                        if not np.isfinite(px) or px <= 0:
                            continue
                        px_eff = px * (1 + slip_bps / 10000)
                        n_lots = int(budget / (px_eff * 100 * (1 + COMM)))
                        if n_lots < 1:
                            continue
                        sh = n_lots * 100
                        cost = sh * px_eff * (1 + COMM)
                        if cost > cash:
                            n_lots = int(cash / (px_eff * 100 * (1 + COMM)))
                            if n_lots < 1:
                                continue
                            sh = n_lots * 100
                            cost = sh * px_eff * (1 + COMM)
                        cash -= cost
                        holdings[code] = sh
                        ep[code] = px_eff
                        ed[code] = dates[nk]
        # 3) 净值
        pv = cash
        for code, sh in holdings.items():
            px = last_close.get(code)
            a = arr.get(code)
            if a is not None:
                s, o, c, amt, pos_ok, dpos, dates = a
                k = dates.get_loc(day) if day in dates else -1
                if k >= 0 and np.isfinite(c[k]) and c[k] > 0:
                    last_close[code] = c[k]
            px = last_close.get(code)
            if px:
                pv += sh * px
        eq.append({"date": dstr, "value": pv})
    eqdf = pd.DataFrame(eq)
    eqdf["date"] = pd.to_datetime(eqdf["date"])
    eqdf = eqdf.set_index("date")
    meta = {"n_trades": len(trades), "runtime_sec": round(time.time() - t0, 1)}
    return eqdf, trades, meta


def run_signal_portfolio_event(sig_by_code, pool, codes, gate_map, all_days,
                               hold=60, n=10, lookback=5, use_gate=True, slip_bps=0,
                               cash0=1_000_000.0, min_amt=5e6, min_px=2.0):
    """事件驱动模式：信号收盘确认 → T+1 开盘买入（持仓未满 n 即补）→ 持有 hold 个交易日
    开盘卖出。候选=近 lookback 日内触发信号；按 amt20 流动性降序。"""
    day_pos = {d: i for i, d in enumerate(all_days)}
    # 预计算：每日候选（信号在 [d-lookback, d-1] 触发的股票，按流动性降序）
    cand_by_day = {i: [] for i in range(len(all_days))}
    amt_of = {}
    for code in codes:
        df = pool[code]
        if code not in sig_by_code:
            continue
        s = sig_by_code[code].reindex(df.index).fillna(False).to_numpy(bool)
        amt = df["amt20"].to_numpy(float)
        c = df["close"].to_numpy(float)
        pos = np.array([day_pos.get(d, -1) for d in df.index], dtype=np.int64)
        ok = s & np.isfinite(amt) & (amt >= min_amt) & np.isfinite(c) & (c >= min_px) & (pos >= 0)
        for k in np.where(ok)[0]:
            for off in range(1, lookback + 1):   # 信号次日起的 lookback 窗口内可买
                di = int(pos[k]) + off
                if di < len(all_days):
                    cand_by_day[di].append((code, float(amt[k])))
    for di in cand_by_day:
        cand_by_day[di].sort(key=lambda kv: -kv[1])

    cash = cash0
    holdings = {}
    ep, ed, epos = {}, {}, {}
    eq, trades = [], []
    last_close = {}
    for di, day in enumerate(all_days):
        dstr = str(day.date())
        # 1) 卖出：持有满 hold 个交易日的仓位今日开盘卖
        for code in list(holdings.keys()):
            if di - epos[code] >= hold:
                df = pool[code]
                if day in df.index:
                    px = df.at[day, "open"]
                else:
                    px = last_close.get(code)
                if px is None or not np.isfinite(px) or px <= 0:
                    continue
                sh = holdings.pop(code)
                px_eff = px * (1 - slip_bps / 10000)
                tax = sh * px_eff * TAX
                proceeds = sh * px_eff * (1 - COMM) - tax
                trades.append({"pnl": proceeds - sh * ep[code] * (1 + COMM),
                               "pnl_pct": (px_eff / ep[code] - 1) * 100,
                               "entry": str(ed[code].date()), "exit": dstr, "code": code})
                cash += proceeds
        # 2) 买入：今日开盘可买昨日及以前 lookback 日内的信号股（T+1 语义）
        if (not use_gate) or gate_map.get(day, False):
            budget_total = cash + sum(sh * (last_close.get(cc) or ep[cc]) for cc, sh in holdings.items())
            budget = budget_total / n
            for code, _amt in cand_by_day.get(di, []):
                if len(holdings) >= n:
                    break
                if code in holdings:
                    continue
                df = pool[code]
                if day not in df.index:
                    continue
                px = df.at[day, "open"]
                if not np.isfinite(px) or px <= 0:
                    continue
                px_eff = px * (1 + slip_bps / 10000)
                n_lots = int(budget / (px_eff * 100 * (1 + COMM)))
                if n_lots < 1:
                    continue
                sh = n_lots * 100
                cost = sh * px_eff * (1 + COMM)
                if cost > cash:
                    n_lots = int(cash / (px_eff * 100 * (1 + COMM)))
                    if n_lots < 1:
                        continue
                    sh = n_lots * 100
                    cost = sh * px_eff * (1 + COMM)
                cash -= cost
                holdings[code] = sh
                ep[code] = px_eff
                ed[code] = day
                epos[code] = di
        # 3) 净值
        pv = cash
        for code, sh in holdings.items():
            df = pool[code]
            if day in df.index:
                cc = df.at[day, "close"]
                if np.isfinite(cc) and cc > 0:
                    last_close[code] = cc
            px = last_close.get(code)
            if px:
                pv += sh * px
        eq.append({"date": dstr, "value": pv})
    eqdf = pd.DataFrame(eq)
    eqdf["date"] = pd.to_datetime(eqdf["date"])
    return eqdf.set_index("date"), trades, {"n_trades": len(trades)}


def summary_from_eq(eqdf, trades):
    r = eqdf["value"].pct_change().fillna(0)
    total = eqdf["value"].iloc[-1] / eqdf["value"].iloc[0] - 1
    yrs = (1 + r).groupby(r.index.year).prod() - 1
    ann = (1 + total) ** (252 / max(1, len(r))) - 1
    dd = (eqdf["value"] / eqdf["value"].cummax() - 1).min()
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0.0
    wins = [t for t in trades if t["pnl"] > 0]
    return {"total_pct": round(total * 100, 2), "ann_pct": round(ann * 100, 2),
            "mdd_pct": round(dd * 100, 1), "sharpe": round(float(sharpe), 3),
            "n_trades": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "pos_years": int((yrs > 0).sum()), "n_years": int(len(yrs))}


def build_active_by_day(pool, codes, all_days):
    """一次性预计算：每日有成交的主板股票列表（安慰剂撒点用）"""
    day_pos = {d: i for i, d in enumerate(all_days)}
    n = len(all_days)
    act_mat = np.zeros((n, len(codes)), dtype=bool)
    for j, code in enumerate(codes):
        df = pool[code]
        v = df["volume"].to_numpy(float)
        pos = np.array([day_pos.get(d, -1) for d in df.index], dtype=np.int64)
        ok = (pos >= 0) & (v > 0)
        act_mat[pos[ok], j] = True
    return act_mat


def random_signals(counts_by_day, act_mat, codes, all_days, pool, seed):
    """把每日信号数随机撒到当日有成交的股票（零假设：同信号强度随机选股）"""
    rng = np.random.default_rng(seed)
    day_pos = {d: i for i, d in enumerate(all_days)}
    sig_lists = {}
    for day, n_sig in counts_by_day.items():
        di = day_pos.get(day)
        if di is None or n_sig <= 0:
            continue
        elig = np.where(act_mat[di])[0]
        if len(elig) == 0:
            continue
        picks = rng.choice(elig, size=min(n_sig, len(elig)), replace=False)
        for j in picks:
            sig_lists.setdefault(codes[j], []).append(day)
    out = {}
    for code, days in sig_lists.items():
        idx = pool[code].index
        dayset = set(days)
        out[code] = pd.Series([d in dayset for d in idx], index=idx)
    return out
