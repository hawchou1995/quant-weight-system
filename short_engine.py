# -*- coding: utf-8 -*-
"""短线监控体系 v1（股票/ETF/基金统一引擎）
============================================
信号设计（从知识库素材提炼，区别于中长线四因子）：
- 短线动量 30%：20d 累计收益（短期强势，量化指南针 20d/60d 动量）
- 量价共振 25%：5 日量比（当日量/5日均量，放量上涨）
- 通道突破 25%：唐奇安 20 日高点突破位置（tb 开拓者策略）
- 波动适配 20%：20d 波动率反选（低波优选，量化指南针波动率因子）
市况门控：沪深300 > MA20 才开仓（短线只做强势市，底信号教训：熊市主场策略会大回撤）
轮动：TopN × 周期 H（5/10/20 日）穷举
股票/ETF 用 data_full OHLC，基金用净值（无成交量 → 量价因子退化为 0，动量/通道/波动仍有效）
"""
import sys, json, time, math
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
sys.path.insert(0, str(BASE))
import v8_selector as V

START = V.START
END = V.END

# ---------------- 因子 ----------------
def short_factors(df):
    """短线四因子（向量化，返回 DataFrame）"""
    d = df.copy()
    c = d["close"]
    d["mom20"] = c / c.shift(20) - 1                       # 20d 动量
    d["mom60"] = c / c.shift(60) - 1                       # 60d 动量（辅助）
    d["vr5"] = d["volume"].rolling(5).mean() / d["volume"].rolling(20).mean().replace(0, np.nan)  # 5日量比
    d["ret5"] = c / c.shift(5) - 1
    d["vp"] = ((d["ret5"] > 0) & (d["vr5"] > 1)).astype(int)  # 放量上涨
    # 唐奇安 20 日突破
    hi20 = d["high"].rolling(20).max().shift(1)
    lo20 = d["low"].rolling(20).min().shift(1)
    d["dnc"] = ((c - lo20) / (hi20 - lo20).replace(0, np.nan)).clip(0, 1)  # 通道位置 0-1
    # 波动率（20d 年化）
    d["vol20"] = d["ret5"].rolling(20).std() * math.sqrt(252)
    d["amt20"] = d["amount"].rolling(20).mean()
    return d

def short_score(r, reversal=False):
    """短线综合分：动量30 + 量价25 + 通道25 + 波动20（0-100）
    reversal=True 时 20d 动量反转为短期反转（A 股个股短线反转有效，动量无效）"""
    s = 0.0
    # 动量 30：20d 收益 0-15% 线性（反转版 = -mom20）
    if not np.isnan(r["mom20"]):
        m = r["mom20"] if not reversal else -r["mom20"]
        s += 30 * max(0.0, min(1.0, m / 0.15))
    # 量价 25：放量上涨给 15，量比增强 10
    s += 15 * (1 if r["vp"] else 0)
    if not np.isnan(r["vr5"]):
        s += 10 * max(0.0, min(1.0, (r["vr5"] - 0.5) / 2.0))
    # 通道 25：唐奇安位置
    if not np.isnan(r["dnc"]):
        s += 25 * r["dnc"]
    # 波动 20：低波优选（年化 20%-80% 线性反比）
    if not np.isnan(r["vol20"]):
        s += 20 * max(0.0, min(1.0, 1 - (r["vol20"] - 0.20) / 0.60))
    return s

# ---------------- 池 ----------------
def load_stock_pool():
    pool = {}
    for f in sorted((BASE / "data_full").glob("*.csv")):
        code = f.stem
        if code.startswith(("bj", "sh5", "sz1")):
            continue
        try:
            df = pd.read_csv(f, dtype={"date": str})
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            if len(df) < 400:
                continue
            pool[code] = short_factors(df).set_index("date")
        except Exception:
            continue
    return pool

def load_etf_pool():
    pool = {}
    for f in sorted((BASE / "data_full").glob("*.csv")):
        code = f.stem
        if not (code.startswith("sh5") or code.startswith("sz1")):
            continue
        try:
            df = pd.read_csv(f, dtype={"date": str})
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            if len(df) < 400:
                continue
            pool[code] = short_factors(df).set_index("date")
        except Exception:
            continue
    return pool

def load_fund_pool(limit=None):
    """基金净值池（fund_nav_cache，无成交量 → 量价=0，动量/通道/波动有效）"""
    pool = {}
    files = sorted((BASE / "fund_nav_cache").glob("*.csv"))
    if limit:
        files = files[:limit]
    for f in files:
        code = f.stem
        try:
            df = pd.read_csv(f, dtype={"净值日期": str})
            s = pd.Series(pd.to_numeric(df["单位净值"], errors="coerce").values,
                          index=pd.to_datetime(df["净值日期"])).dropna()
            if len(s) < 400:
                continue
            d = pd.DataFrame({"open": s.values, "high": s.values, "low": s.values,
                              "close": s.values, "volume": 0.0, "amount": 0.0}, index=s.index)
            pool[code] = short_factors(d)
        except Exception:
            continue
    return pool

# ---------------- 回测主循环 ----------------
def run_short(pool, top_n=10, hold_days=10, score_min=50, cash0=1_000_000,
              use_market=True, ma_win=20, min_px=1.0, min_amt=2e6, fund_mode=False,
              reversal=False):
    """短线轮动回测：T 日收盘打分 → T+1 开盘换仓；市况门控（沪深300>MA）"""
    idx = V.load_index(ma_win).set_index("date")
    in_market_map = idx["in_market"].to_dict()
    all_days = [d for d in idx.index if START <= str(d.date()) <= END]
    rebal_days = set(all_days[::hold_days])
    cash = cash0
    holdings, entry_price, entry_date = {}, {}, {}
    equity_curve, trades = [], []
    last_close = {}
    pending_sell, pending_buy = set(), []

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_market else True
        if pending_sell or pending_buy:
            open_px = {}
            for code in list(pending_sell) + [c for c, _ in pending_buy]:
                ddf = pool.get(code)
                if ddf is not None and day in ddf.index:
                    open_px[code] = ddf.loc[day, "close"] if fund_mode else ddf.loc[day, "open"]
            for code in list(pending_sell):
                if code not in holdings:
                    continue
                px = open_px.get(code)
                if px is None or pd.isna(px) or px <= 0:
                    continue
                sh = holdings.pop(code)
                tax = sh * px * V.SELL_TAX
                proceeds = sh * px * (1 - V.COMMISSION) - tax
                pnl = proceeds - sh * entry_price[code] * (1 + V.COMMISSION)
                trades.append({"entry_date": str(entry_date[code].date()), "exit_date": dstr,
                               "pnl": round(pnl, 2), "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                               "holding_bars": (day - entry_date[code]).days, "symbol": code})
                cash += proceeds
            if pending_buy:
                port_value = cash
                for code, sh in holdings.items():
                    if last_close.get(code):
                        port_value += sh * last_close[code]
                per_target = port_value / len(pending_buy)
                for code, _sc in pending_buy:
                    if code in holdings:
                        continue
                    px = open_px.get(code)
                    if px is None or pd.isna(px) or px <= 0:
                        continue
                    sh = int(per_target / (px * (1 + V.COMMISSION)))
                    if fund_mode:
                        sh = int(sh / 100) * 100  # 基金净值近似整百份
                    if sh > 0 and sh * px * (1 + V.COMMISSION) <= cash:
                        cash -= sh * px * (1 + V.COMMISSION)
                        holdings[code] = sh
                        entry_price[code] = px
                        entry_date[code] = day
            pending_sell, pending_buy = set(), []
        if day in rebal_days and di < len(all_days) - 1:
            if not in_market:
                pending_sell = set(holdings.keys())
                pending_buy = []
            else:
                cand = []
                for code, ddf in pool.items():
                    if day not in ddf.index:
                        continue
                    r = ddf.loc[day]
                    if pd.isna(r["close"]) or r["close"] <= 0 or pd.isna(r["mom20"]):
                        continue
                    if r["close"] < min_px:
                        continue
                    if not fund_mode and (pd.isna(r["amt20"]) or r["amt20"] < min_amt):
                        continue
                    sc = short_score(r, reversal=reversal)
                    if sc < score_min:
                        continue
                    cand.append((code, sc))
                cand.sort(key=lambda kv: -kv[1])
                ranked = cand[:top_n]
                keep = {c for c, _ in ranked}
                pending_sell = {c for c in holdings if c not in keep}
                pending_buy = ranked
        port_value = cash
        for code, sh in holdings.items():
            ddf = pool.get(code)
            px = None
            if ddf is not None and day in ddf.index:
                px = ddf.loc[day, "close"]
                if not pd.isna(px) and px > 0:
                    last_close[code] = px
                else:
                    px = last_close.get(code)
            else:
                px = last_close.get(code)
            if px:
                port_value += sh * px
        equity_curve.append({"date": dstr, "value": round(port_value, 2)})
    # 期末平仓
    if holdings:
        last_day = all_days[-1]
        for code, sh in holdings.items():
            ddf = pool.get(code)
            px = None
            if ddf is not None and last_day in ddf.index:
                px = ddf.loc[last_day, "close"]
            if px is None or pd.isna(px) or px <= 0:
                px = last_close.get(code)
            if px is None or px <= 0:
                continue
            tax = sh * px * V.SELL_TAX
            proceeds = sh * px * (1 - V.COMMISSION) - tax
            pnl = proceeds - sh * entry_price[code] * (1 + V.COMMISSION)
            trades.append({"entry_date": str(entry_date[code].date()), "exit_date": str(last_day.date()),
                           "pnl": round(pnl, 2), "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                           "holding_bars": (last_day - entry_date[code]).days, "symbol": code})
    eq = pd.DataFrame(equity_curve)
    return eq, trades

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="stock", choices=["stock", "etf", "fund"])
    ap.add_argument("--limit", type=int, default=0, help="fund 池限制数量（调试）")
    args = ap.parse_args()

    t0 = time.time()
    if args.asset == "stock":
        pool = load_stock_pool()
    elif args.asset == "etf":
        pool = load_etf_pool()
    else:
        pool = load_fund_pool(args.limit or None)
    print(f"{args.asset} 池: {len(pool)} 只 ({time.time()-t0:.0f}s)", flush=True)

    # 穷举：TopN × 周期 × 门槛
    grid = []
    for top_n in [5, 8, 10, 15]:
        for hold in [5, 10, 20]:
            for score_min in [40, 50, 60]:
                grid.append((top_n, hold, score_min))
    res = {}
    out_file = BASE / f"short_{args.asset}_results.json"
    for i, (top_n, hold, smin) in enumerate(grid):
        try:
            eq, tr = run_short(pool, top_n=top_n, hold_days=hold, score_min=smin,
                               fund_mode=(args.asset == "fund"))
            s = V.summary(eq, tr)
            key = f"T{top_n}_H{hold}_S{smin}"
            res[key] = s
            print(f"[{i+1}/{len(grid)}] {key}: 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% | 回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 交易 {s['total_trades']}", flush=True)
            # 即时保存（防中途退出丢结果）
            json.dump({k: {kk: float(vv) for kk, vv in v.items()} for k, v in res.items()},
                      open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[{i+1}/{len(grid)}] T{top_n}_H{hold}_S{smin} ERR: {e}", flush=True)
    best = max(res.items(), key=lambda kv: kv[1]["sharpe"]) if res else (None, {})
    print(f"\nBEST {args.asset}: {best[0]} {best[1]}")
    json.dump({k: {kk: float(vv) for kk, vv in v.items()} for k, v in res.items()},
              open(out_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
