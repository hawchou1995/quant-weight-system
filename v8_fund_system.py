# -*- coding: utf-8 -*-
"""
基金动量选基回测系统（独立于股票/ETF）
========================================
1. 拉取全市场股票型/混合型基金净值（东财 fund_open_fund_info_em）
2. 动量选基：6 月净值动量打分 TopN，月度轮动
3. 净值型标的：无 OHLC，直接用单位净值序列
目标：夏普 >1、回撤 <30%
"""
import sys, os, json, time, csv, math
from pathlib import Path
import numpy as np
import pandas as pd
import akshare as ak

BASE = Path(__file__).parent
CACHE = BASE / "fund_nav_cache"
CACHE.mkdir(exist_ok=True)
START = "2016-01-04"
END = "2026-08-14"


def fetch_fund_list():
    """全市场场外基金列表 → 过滤股票型/混合型"""
    df = ak.fund_name_em()
    # 基金类型过滤：股票型/混合型
    mask = df["基金类型"].str.contains("股票|混合", na=False)
    return df[mask][["基金代码", "基金简称", "基金类型"]].reset_index(drop=True)


def fetch_nav(code, force=False):
    """单只基金净值（带缓存）"""
    cache_file = CACHE / f"{code}.csv"
    if cache_file.exists() and not force:
        try:
            df = pd.read_csv(cache_file, dtype={"净值日期": str})
            if len(df) > 100:
                return df
        except Exception:
            pass
    try:
        df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
        if df is None or df.empty:
            return None
        df.to_csv(cache_file, index=False)
        return df
    except Exception:
        return None


def run_fund_momentum(fund_list, top_n=10, hold_days=21, mom_days=126,
                      min_history=250, min_amt_nav=0.5):
    """基金动量选基回测
    fund_list: [{code, name}]
    每月末按 6 月净值动量选 TopN，等权持有
    """
    # 预加载全部净值
    navs = {}  # code -> Series(date -> nav)
    print(f"拉取 {len(fund_list)} 只基金净值...", flush=True)
    t0 = time.time()
    for i, row in fund_list.iterrows():
        code = row["基金代码"]
        df = fetch_nav(code)
        if df is None or len(df) < min_history:
            continue
        s = pd.Series(pd.to_numeric(df["单位净值"], errors="coerce").values,
                      index=pd.to_datetime(df["净值日期"])).dropna()
        navs[code] = s
        if (i + 1) % 200 == 0:
            print(f"  [{i+1}/{len(fund_list)}] 已加载 {len(navs)} 只 ({time.time()-t0:.0f}s)", flush=True)
    print(f"净值池: {len(navs)} 只 ({time.time()-t0:.0f}s)", flush=True)

    # 交易日序列
    all_days = sorted(set().union(*[set(s.index) for s in navs.values()]))
    all_days = [d for d in all_days if START <= str(d.date()) <= END]
    rebal_days = set(all_days[::hold_days])

    cash = 1_000_000.0
    holdings = {}  # code -> shares
    entry_price = {}
    entry_date = {}
    equity_curve = []
    trades = []
    pending_sell = set()
    pending_buy = []
    last_nav = {}

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        # 执行挂单（净值型按当日净值成交，近似次日确认）
        if pending_sell or pending_buy:
            for code in list(pending_sell):
                if code not in holdings:
                    continue
                px = navs[code].get(day)
                if px is None or pd.isna(px) or px <= 0:
                    px = last_nav.get(code)
                if px is None:
                    continue
                sh = holdings.pop(code)
                pnl = sh * (px - entry_price[code])
                trades.append({"entry_date": str(entry_date[code].date()), "exit_date": dstr,
                               "side": "long", "size": sh, "entry_price": round(entry_price[code], 4),
                               "exit_price": round(px, 4), "pnl": round(pnl, 2),
                               "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                               "holding_bars": (day - entry_date[code]).days,
                               "symbol": code, "symbol_name": code, "display_symbol": code})
                cash += sh * px
            if pending_buy:
                port_value = cash
                for code, sh in holdings.items():
                    if last_nav.get(code):
                        port_value += sh * last_nav[code]
                per_target = port_value / top_n
                for code in pending_buy:
                    if code in holdings:
                        continue
                    px = navs[code].get(day)
                    if px is None or pd.isna(px) or px <= 0:
                        px = last_nav.get(code)
                    if px is None:
                        continue
                    target_shares = int(per_target / px)
                    if target_shares > 0 and target_shares * px <= cash:
                        cash -= target_shares * px
                        holdings[code] = target_shares
                        entry_price[code] = px
                        entry_date[code] = day
            pending_sell = set()
            pending_buy = []

        # 再平衡日：按动量选基
        if day in rebal_days and di < len(all_days) - 1:
            scores = {}
            for code, s in navs.items():
                if day not in s.index:
                    continue
                px = s.get(day)
                px_old = s.get(day - pd.Timedelta(days=mom_days))
                if px is None or pd.isna(px) or px <= 0:
                    continue
                if px_old is None or pd.isna(px_old) or px_old <= 0:
                    continue
                mom = px / px_old - 1
                if mom <= 0:
                    continue  # 绝对动量过滤
                # 附加 3 月动量
                px_3m = s.get(day - pd.Timedelta(days=63))
                if px_3m is not None and not pd.isna(px_3m) and px_3m > 0:
                    mom3 = px / px_3m - 1
                else:
                    mom3 = 0
                scores[code] = mom * 0.7 + mom3 * 0.3
            if scores:
                ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:top_n]
                keep = {c for c, _ in ranked}
                pending_sell = {c for c in holdings if c not in keep}
                pending_buy = [c for c, _ in ranked]
            else:
                pending_sell = set(holdings.keys())
                pending_buy = []

        # mark-to-market
        port_value = cash
        for code, sh in holdings.items():
            px = navs[code].get(day)
            if px is not None and not pd.isna(px) and px > 0:
                port_value += sh * px
                last_nav[code] = px
            elif last_nav.get(code):
                port_value += sh * last_nav[code]
        equity_curve.append({"date": dstr, "value": round(port_value, 2)})

        if (di + 1) % 500 == 0:
            print(f"  [{di+1}/{len(all_days)}] {dstr} 市值 {port_value:,.0f} 持仓 {len(holdings)}", flush=True)

    # 期末平仓
    if holdings:
        last_day = all_days[-1]
        for code, sh in holdings.items():
            px = navs[code].get(last_day) or last_nav.get(code)
            if px is None:
                continue
            pnl = sh * (px - entry_price[code])
            trades.append({"entry_date": str(entry_date[code].date()), "exit_date": str(last_day.date()),
                           "side": "long", "size": sh, "entry_price": round(entry_price[code], 4),
                           "exit_price": round(px, 4), "pnl": round(pnl, 2),
                           "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                           "holding_bars": (last_day - entry_date[code]).days,
                           "symbol": code, "symbol_name": code, "display_symbol": code})
            cash += sh * px
        holdings = {}
    return pd.DataFrame(equity_curve), trades, len(navs)


def summary(eq, trades):
    v = pd.to_numeric(eq["value"]).values
    if len(v) < 2 or v[0] <= 0:
        return {}
    total = (v[-1] / v[0] - 1) * 100
    days = (pd.to_datetime(eq["date"].iloc[-1]) - pd.to_datetime(eq["date"].iloc[0])).days
    years = days / 365.25
    annual = ((v[-1] / v[0]) ** (1 / years) - 1) * 100 if years > 0 else 0
    ret = pd.Series(v).pct_change().dropna()
    sharpe = ret.mean() / ret.std() * math.sqrt(252) if len(ret) > 5 and ret.std() > 0 else 0
    dd = (v / np.maximum.accumulate(v) - 1) * 100
    mdd = dd.min()
    win = sum(1 for t in trades if t.get("pnl", 0) > 0) / len(trades) * 100 if trades else 0
    return {"total_return_pct": round(total, 2), "annual_return_pct": round(annual, 2),
            "max_drawdown_pct": round(mdd, 2), "sharpe": round(sharpe, 3),
            "win_rate_pct": round(win, 1), "total_trades": len(trades)}


if __name__ == "__main__":
    print("== 1/3 基金列表 ==", flush=True)
    fund_list = fetch_fund_list()
    print(f"股票/混合型基金: {len(fund_list)} 只", flush=True)
    fund_list.to_csv(BASE / "fund_list.csv", index=False)

    print("== 2/3 动量选基回测 ==", flush=True)
    t0 = time.time()
    for top_n in [5, 10, 20]:
        eq, trades, n_pool = run_fund_momentum(fund_list, top_n=top_n, hold_days=21)
        s = summary(eq, trades)
        flag = "✅" if (s.get("sharpe") or 0) >= 1.0 and (s.get("max_drawdown_pct") or -99) > -30 else ""
        print(f"[基金 Top{top_n}] 收益 {s.get('total_return_pct')}% | 年化 {s.get('annual_return_pct')}% "
              f"| 回撤 {s.get('max_drawdown_pct')}% | 夏普 {s.get('sharpe')} | 胜率 {s.get('win_rate_pct')}% | 交易 {s.get('total_trades')} {flag}", flush=True)
        eq.to_csv(BASE / f"v8_fund_top{top_n}_equity.csv", index=False)
        with open(BASE / f"v8_fund_top{top_n}_trades.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            keys = ["entry_date", "exit_date", "side", "size", "entry_price", "exit_price",
                    "pnl", "pnl_pct", "holding_bars", "symbol", "symbol_name", "display_symbol"]
            w.writerow(keys)
            for t in trades:
                w.writerow([t.get(k, "") for k in keys])
        with open(BASE / f"v8_fund_top{top_n}_summary.json", "w", encoding="utf-8") as f:
            json.dump({"meta": {"strategy_name": f"v8 基金动量选基 Top{top_n}",
                                "symbol": f"全市场权益基金动量选基 Top{top_n}", "start": START, "end": END,
                                "initial_cash": 1000000.0, "market": "china_a"},
                       "summary": s}, f, ensure_ascii=False, indent=2)
    print(f"总耗时 {(time.time()-t0)/60:.1f} 分钟", flush=True)
