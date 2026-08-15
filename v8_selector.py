# -*- coding: utf-8 -*-
"""
v8 中长线权重看板引擎 v2（从零搭建 · 截面选股 + 市场择时）
========================================================
v2 修正：
- 因子预计算（全历史向量化一次，主循环 O(1) 取数）
- T+1 执行：再平衡日 T 收盘算因子/排名 → T+1 开盘执行（无未来函数）
- 买入用 T+1 开盘价，卖出用 T+1 开盘价；整手、T+1 卖出约束
目标：全量池 2016-2026 夏普 ≥0.8、最大回撤 ≤30%
"""
import os, sys, json, math, time, csv
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = BASE / "data_full"
INDEX_FILE = BASE / "index_000300.csv"
START = "2016-01-04"
END = "2026-08-14"

COMMISSION = 0.00025
SELL_TAX = 0.0005
LOT = 100
REBALANCE_DAYS = 21


# ---------------- 指数择时 ----------------
def load_index(ma: int = 200):
    df = pd.read_csv(INDEX_FILE, dtype={"date": str})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["ma"] = df["close"].rolling(ma).mean()
    df["in_market"] = df["close"] > df["ma"]
    return df


# ---------------- 因子（全历史向量化一次）----------------
def compute_factors_full(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c = d["close"]
    d["mom_12_1"] = c.shift(21) / c.shift(21 + 252) - 1
    d["ma200_pos"] = c / c.rolling(200).mean() - 1
    ar_period = 25
    hi_idx = d["high"].rolling(ar_period + 1).apply(lambda x: int(np.argmax(x)), raw=True)
    lo_idx = d["low"].rolling(ar_period + 1).apply(lambda x: int(np.argmin(x)), raw=True)
    d["aroon_osc"] = ((100 * (ar_period - hi_idx) / ar_period) - (100 * (ar_period - lo_idx) / ar_period)).fillna(0)
    d["ret20"] = c / c.shift(20) - 1
    vol_ma5 = d["volume"].rolling(5).mean()
    vol_ma20 = d["volume"].rolling(20).mean()
    d["vol_ratio"] = vol_ma5 / vol_ma20.replace(0, np.nan)
    d["vp_confirm"] = ((d["ret20"] > 0) & (d["vol_ratio"] > 1)).astype(int)
    d["vol20"] = d["ret20"].rolling(20).std() * math.sqrt(252)
    d["amt20"] = d["amount"].rolling(20).mean()
    return d


def score_row(r, w_mom=0.35, w_trend=0.25, w_aroon=0.20, w_vp=0.20):
    s = 0.0
    if not np.isnan(r["mom_12_1"]):
        s += w_mom * max(0.0, min(1.0, r["mom_12_1"] / 0.20)) * 100
    if not np.isnan(r["ma200_pos"]):
        s += w_trend * max(0.0, min(1.0, r["ma200_pos"] / 0.30)) * 100
    a = max(-100.0, min(100.0, r["aroon_osc"]))
    s += w_aroon * ((a + 100) / 200) * 100
    s += w_vp * (100 if r["vp_confirm"] else 0)
    return s


# ---------------- 回测 ----------------
def load_pool(use_cache=True):
    """预计算全量池因子（带 pickle 缓存）"""
    cache_file = BASE / "v8_factor_cache.pkl"
    if use_cache and cache_file.exists():
        t0 = time.time()
        data = pd.read_pickle(cache_file)
        print(f"加载因子缓存 {len(data)} 只 ({time.time()-t0:.0f}s)", flush=True)
        return data
    print("预计算全量池因子（一次）...", flush=True)
    data = {}   # code -> df (date index: open/close + factors)
    t0 = time.time()
    for f in sorted(DATA_DIR.glob("*.csv")):
        code = f.stem
        if code.startswith(("sh5", "sz1", "bj")):
            continue
        try:
            df = pd.read_csv(f, dtype={"date": str})
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            if len(df) < 400:
                continue
            df = compute_factors_full(df)
            df = df.set_index("date")
            data[code] = df
        except Exception:
            continue
    if use_cache:
        pd.to_pickle(data, cache_file)
    print(f"标的池 {len(data)} 只，预计算 {(time.time()-t0)/60:.1f} 分钟", flush=True)
    return data


def run_v8(top_n=20, w_mom=0.35, w_trend=0.25, w_aroon=0.20, w_vp=0.20,
           use_timing=True, min_amt=5e6, max_vol=None, hold_days=21,
           pool=None, drawdown_circuit=None, vol_target=None, ma_fast=50):
    """v8 回测主循环
    drawdown_circuit: 组合回撤熔断（如 0.15 = 净值从高点回撤 15% 强制清仓，新高后才恢复）
    vol_target: 波动率目标仓位（年化，如 0.15；仓位 = vol_target / 近20日年化波动，上限 1.0）
    ma_fast: 快线均线（择时用双均线：close > ma_fast 且 > ma200）
    """
    idx = load_index(200)
    idx = idx.set_index("date")
    idx["ma_fast"] = idx["close"].rolling(ma_fast).mean()
    in_market_map = idx["in_market"].to_dict()
    fast_map = (idx["close"] > idx["ma_fast"]).to_dict()

    data = pool if pool is not None else load_pool()

    all_days = [d for d in idx.index if START <= str(d.date()) <= END]
    rebal_days = set(all_days[::hold_days])

    cash = 1_000_000.0
    holdings = {}       # code -> shares
    entry_price = {}
    entry_date = {}
    equity_curve = []
    trades = []
    pending_sell = set()   # 再平衡日收盘后：清仓名单（次日开盘执行）
    pending_buy = []       # 再平衡日收盘后：买入名单（次日开盘执行，等权目标）
    last_close = {}
    peak = 1_000_000.0    # 组合净值峰值（回撤熔断基准）
    circuit_active = False  # 熔断中（清仓后等指数转多再入场）

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        # 择时：双均线（close > ma_fast 且 > ma200）
        in_market = (in_market_map.get(day, False) and fast_map.get(day, False)) if use_timing else True

        # ---- 执行 T-1 挂单（用今日开盘价）----
        if pending_sell or pending_buy:
            open_px = {}
            for code in list(pending_sell) + [c for c, _ in pending_buy]:
                ddf = data.get(code)
                if ddf is not None and day in ddf.index:
                    open_px[code] = ddf.loc[day, "open"]
            # 先卖（T+1 允许卖）
            for code in list(pending_sell):
                if code not in holdings:
                    continue
                px = open_px.get(code)
                if px is None or pd.isna(px) or px <= 0:
                    continue
                sh = holdings.pop(code)
                tax = sh * px * SELL_TAX
                proceeds = sh * px * (1 - COMMISSION) - tax
                pnl = proceeds - sh * entry_price[code] * (1 + COMMISSION)
                trades.append({
                    "entry_date": str(entry_date[code].date()), "exit_date": dstr,
                    "side": "long", "size": sh,
                    "entry_price": round(entry_price[code], 4), "exit_price": round(px, 4),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                    "holding_bars": (day - entry_date[code]).days,
                    "symbol": code, "symbol_name": code, "display_symbol": code,
                })
                cash += proceeds
            # 再买（等权）
            if pending_buy:
                port_value = cash
                for code, sh in holdings.items():
                    px = last_close.get(code)
                    if px:
                        port_value += sh * px
                # 波动率目标仓位：指数近 20 日年化波动 vs 目标，仓位系数 0.2~1.0
                scale = 1.0
                if vol_target:
                    idx_ret = idx["close"].pct_change().rolling(20).std() * math.sqrt(252)
                    cur_vol = idx_ret.loc[day] if day in idx_ret.index else 0.2
                    if not pd.isna(cur_vol) and cur_vol > 0:
                        scale = max(0.2, min(1.0, vol_target / cur_vol))
                per_target = port_value * scale / top_n
                for code, _score in pending_buy:
                    if code in holdings:
                        continue
                    px = open_px.get(code)
                    if px is None or pd.isna(px) or px <= 0:
                        continue
                    target_shares = int(per_target / (px * (1 + COMMISSION)))
                    target_shares = (target_shares // LOT) * LOT
                    if target_shares > 0 and target_shares * px * (1 + COMMISSION) <= cash:
                        cash -= target_shares * px * (1 + COMMISSION)
                        holdings[code] = target_shares
                        entry_price[code] = px
                        entry_date[code] = day
            pending_sell = set()
            pending_buy = []

        # ---- 再平衡日收盘后：计算排名，挂单次日执行 ----
        if day in rebal_days and di < len(all_days) - 1:
            # 回撤熔断检查（用当日收盘组合市值）
            port_value_now = cash
            for code, sh in holdings.items():
                ddf = data.get(code)
                if ddf is not None and day in ddf.index:
                    px = ddf.loc[day, "close"]
                    if not pd.isna(px):
                        port_value_now += sh * px
            if port_value_now > peak:
                peak = port_value_now
            if drawdown_circuit and holdings and (port_value_now / peak - 1) < -drawdown_circuit:
                circuit_active = True
            # 熔断恢复：指数转多 且 净值回升至峰值 97% 以上
            if circuit_active and in_market and (port_value_now / peak - 1) >= -0.03:
                circuit_active = False
                peak = port_value_now  # 重置峰值，重新计回撤
            if not in_market or circuit_active:
                pending_sell = set(holdings.keys())
                pending_buy = []
            else:
                candidates = {}
                for code, ddf in data.items():
                    if day not in ddf.index:
                        continue
                    r = ddf.loc[day]
                    if pd.isna(r["close"]) or r["close"] <= 0 or pd.isna(r["mom_12_1"]):
                        continue
                    if pd.isna(r["amt20"]) or r["amt20"] < min_amt:
                        continue
                    if max_vol and not pd.isna(r["vol20"]) and r["vol20"] > max_vol:
                        continue
                    if r["close"] < 1.0:
                        continue
                    candidates[code] = score_row(r, w_mom, w_trend, w_aroon, w_vp)
                if candidates:
                    ranked = sorted(candidates.items(), key=lambda kv: -kv[1])[:top_n]
                    keep = {c for c, _ in ranked}
                    pending_sell = {c for c in holdings if c not in keep}
                    pending_buy = ranked
                else:
                    pending_sell = set(holdings.keys())
                    pending_buy = []

        # ---- 每日 mark-to-market ----
        port_value = cash
        for code, sh in holdings.items():
            ddf = data.get(code)
            if ddf is not None and day in ddf.index:
                px = ddf.loc[day, "close"]
                if not pd.isna(px):
                    port_value += sh * px
                    last_close[code] = px
        equity_curve.append({"date": dstr, "value": round(port_value, 2)})

        if (di + 1) % 400 == 0:
            print(f"  [{di+1}/{len(all_days)}] {dstr} 市值 {port_value:,.0f} 持仓 {len(holdings)}", flush=True)

    # 期末平仓（末日收盘）
    if holdings:
        last_day = all_days[-1]
        for code, sh in holdings.items():
            ddf = data.get(code)
            if ddf is None or last_day not in ddf.index:
                continue
            px = ddf.loc[last_day, "close"]
            if pd.isna(px) or px <= 0:
                continue
            tax = sh * px * SELL_TAX
            proceeds = sh * px * (1 - COMMISSION) - tax
            pnl = proceeds - sh * entry_price[code] * (1 + COMMISSION)
            trades.append({
                "entry_date": str(entry_date[code].date()), "exit_date": str(last_day.date()),
                "side": "long", "size": sh,
                "entry_price": round(entry_price[code], 4), "exit_price": round(px, 4),
                "pnl": round(pnl, 2),
                "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                "holding_bars": (last_day - entry_date[code]).days,
                "symbol": code, "symbol_name": code, "display_symbol": code,
            })
            cash += proceeds
        holdings = {}

    eq = pd.DataFrame(equity_curve)
    return eq, trades


def summary(eq: pd.DataFrame, trades: list):
    v = pd.to_numeric(eq["value"]).values
    total = (v[-1] / v[0] - 1) * 100
    days = (pd.to_datetime(eq["date"].iloc[-1]) - pd.to_datetime(eq["date"].iloc[0])).days
    years = days / 365.25
    annual = ((v[-1] / v[0]) ** (1 / years) - 1) * 100 if v[0] > 0 else 0
    ret = pd.Series(v).pct_change().dropna()
    sharpe = ret.mean() / ret.std() * math.sqrt(252) if ret.std() > 0 else 0
    dd = (v / np.maximum.accumulate(v) - 1) * 100
    mdd = dd.min()
    win = sum(1 for t in trades if t.get("pnl", 0) > 0) / len(trades) * 100 if trades else 0
    return {
        "total_return_pct": round(total, 2),
        "annual_return_pct": round(annual, 2),
        "max_drawdown_pct": round(mdd, 2),
        "sharpe": round(sharpe, 3),
        "win_rate_pct": round(win, 1),
        "total_trades": len(trades),
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--top_n", type=int, default=20)
    ap.add_argument("--timing", type=int, default=1)
    ap.add_argument("--hold", type=int, default=21)
    ap.add_argument("--out", default="v8")
    args = ap.parse_args()

    t0 = time.time()
    eq, trades = run_v8(top_n=args.top_n, use_timing=bool(args.timing), hold_days=args.hold)
    s = summary(eq, trades)
    print(f"\nv8 Top{args.top_n} 择时={bool(args.timing)} | 耗时 {(time.time()-t0)/60:.1f} 分钟")
    print(f"总收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% | 回撤 {s['max_drawdown_pct']}% "
          f"| 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']}")
    pref = f"v8_top{args.top_n}_{'timing' if args.timing else 'notiming'}"
    eq.to_csv(BASE / f"{pref}_equity.csv", index=False)
    with open(BASE / f"{pref}_trades.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        keys = ["entry_date", "exit_date", "side", "size", "entry_price", "exit_price",
                "pnl", "pnl_pct", "holding_bars", "symbol", "symbol_name", "display_symbol"]
        w.writerow(keys)
        for t in trades:
            w.writerow([t.get(k, "") for k in keys])
    with open(BASE / f"{pref}_summary.json", "w", encoding="utf-8") as f:
        json.dump({"meta": {"strategy_name": f"v8 Top{args.top_n} 中长线权重看板",
                            "symbol": f"全量池截面选股 Top{args.top_n}",
                            "start": START, "end": END, "initial_cash": 1_000_000.0,
                            "window_start_value": float(eq["value"].iloc[0]),
                            "final_value": float(eq["value"].iloc[-1]), "market": "china_a"},
                   "summary": s}, f, ensure_ascii=False, indent=2)
    print(f"已输出: {pref}_equity.csv / _trades.csv / _summary.json")
