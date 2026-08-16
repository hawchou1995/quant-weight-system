# -*- coding: utf-8 -*-
"""
基金回撤控制 v5：三路全试（用户确认）
- A 路：个股净值回撤止损（T+1 赎回）10/15/20%
- B 路：组合熔断即时清仓（修复 v4 bug：触发后次日立即赎回，不等再平衡日）10/15/20%
- C 路：择时收紧 MA100（vs 基线 MA200）
- 组合：nav_stop + circuit + MA100
成交口径升级：T 日净值触发/排名 → T+1 日净值成交（场外基金真实规则，更保守）
基线也按 T+1 重跑，保证对比公平
"""
import sys, json, time, math
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import v8_selector as V

CACHE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统/fund_nav_cache")
START, END = "2016-01-04", "2026-08-14"

t0 = time.time()
navs = {}
for f in CACHE.glob("*.csv"):
    code = f.stem
    try:
        df = pd.read_csv(f, dtype={"净值日期": str})
        s = pd.Series(pd.to_numeric(df["单位净值"], errors="coerce").values,
                      index=pd.to_datetime(df["净值日期"])).dropna()
        if len(s) >= 250:
            navs[code] = s
    except Exception:
        continue
print(f"净值池: {len(navs)} 只 ({(time.time()-t0)/60:.1f}min)", flush=True)

# 指数择时：沪深300 close > MA{window}
idx = V.load_index(200).set_index("date")
idx = idx[~idx.index.duplicated(keep="last")].sort_index()
idx["ma200"] = idx["close"].rolling(200).mean()
idx["ma100"] = idx["close"].rolling(100).mean()


_ma_cache = {}

def build_market_map(window=200):
    if window in _ma_cache:
        return _ma_cache[window]
    ma = idx["close"].rolling(window).mean()
    m = {}
    for d, c in idx["close"].items():
        mv = ma.get(d)
        if pd.notna(mv) and c > mv:
            m[d] = True
        else:
            m[d] = False
    _ma_cache[window] = m
    return m


all_days_all = sorted(set().union(*[set(s.index) for s in navs.values()]))
all_days_all = [d for d in all_days_all if START <= str(d.date()) <= END]
print(f"交易日: {len(all_days_all)} 天, 末日 {all_days_all[-1].date()}", flush=True)


def run_fund_v5(top_n=10, hold_days=126, ma_window=200,
                nav_stop=None, circuit=None, slippage_bps=0):
    """T+1 成交；nav_stop=个股净值回撤止损；circuit=组合熔断即时清仓"""
    in_market_map = build_market_map(ma_window)
    rebal = set(all_days_all[::hold_days])
    cash = 1_000_000.0
    holdings, entry_price, entry_date = {}, {}, {}
    peak_nav = {}            # 个股峰值净值（nav_stop 用）
    equity_curve, trades = [], []
    pending_sell, pending_buy = set(), []
    last_nav = {}
    peak_port = 1_000_000.0
    circuit_on = False

    for di, day in enumerate(all_days_all):
        dstr = str(day.date())
        im = in_market_map.get(day, False)

        # ---- 1. 执行昨日挂单（T+1 成交：今日净值）----
        if pending_sell or pending_buy:
            for code in list(pending_sell):
                if code not in holdings:
                    continue
                px = navs[code].get(day)
                if px is None or pd.isna(px) or px <= 0:
                    px = last_nav.get(code)
                if px is None:
                    continue
                px = px * (1 - slippage_bps / 10000)
                sh = holdings.pop(code)
                peak_nav.pop(code, None)
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
                per = port_value / top_n
                for code in pending_buy:
                    if code in holdings:
                        continue
                    px = navs[code].get(day)
                    if px is None or pd.isna(px) or px <= 0:
                        px = last_nav.get(code)
                    if px is None:
                        continue
                    px = px * (1 + slippage_bps / 10000)
                    sh = int(per / px)
                    if sh > 0 and sh * px <= cash:
                        cash -= sh * px
                        holdings[code] = sh
                        entry_price[code] = px
                        entry_date[code] = day
                        peak_nav[code] = px
            pending_sell = set()
            pending_buy = []

        # ---- 2. 今日触发判断（次日执行）----
        # 组合市值 + 峰值
        port_value = cash
        for code, sh in holdings.items():
            px = navs[code].get(day)
            if px is not None and px > 0:
                port_value += sh * px
                last_nav[code] = px
            elif last_nav.get(code):
                port_value += sh * last_nav[code]
        if port_value > peak_port:
            peak_port = port_value

        # 个股净值回撤止损（相对持有期峰值）
        if nav_stop and holdings:
            for code in list(holdings.keys()):
                px = navs[code].get(day)
                if px is None or pd.isna(px) or px <= 0:
                    continue
                if px > peak_nav.get(code, px):
                    peak_nav[code] = px
                if px <= peak_nav[code] * (1 - nav_stop):
                    pending_sell.add(code)
        # 组合熔断（触发 → 次日全部赎回；指数转多即恢复）
        if circuit and holdings and (port_value / peak_port - 1) < -circuit:
            circuit_on = True
            for code in list(holdings.keys()):
                pending_sell.add(code)
        if circuit_on and im:
            circuit_on = False
            peak_port = port_value

        # ---- 3. 再平衡日收盘排名（次日执行）----
        if day in rebal and di < len(all_days_all) - 1:
            if not im or circuit_on:
                pending_sell = set(holdings.keys())
                pending_buy = []
            else:
                scores = {}
                for code, s in navs.items():
                    if day not in s.index:
                        continue
                    px = s.get(day); px_old = s.get(day - pd.Timedelta(days=126))
                    if px is None or pd.isna(px) or px <= 0 or px_old is None or pd.isna(px_old) or px_old <= 0:
                        continue
                    mom = px / px_old - 1
                    if mom <= 0:
                        continue
                    px_3m = s.get(day - pd.Timedelta(days=63))
                    mom3 = px / px_3m - 1 if px_3m is not None and px_3m > 0 else 0
                    scores[code] = mom * 0.7 + mom3 * 0.3
                if scores:
                    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:top_n]
                    keep = {c for c, _ in ranked}
                    pending_sell = {c for c in holdings if c not in keep}
                    pending_buy = [c for c, _ in ranked]
                else:
                    pending_sell = set(holdings.keys())
                    pending_buy = []

        equity_curve.append({"date": dstr, "value": round(port_value, 2)})

    # 期末平仓
    if holdings:
        last_day = all_days_all[-1]
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
    return pd.DataFrame(equity_curve), trades


def summ(eq, tr):
    v = pd.to_numeric(eq["value"]).values
    if len(v) < 2 or v[0] <= 0:
        return {}
    total = (v[-1] / v[0] - 1) * 100
    days = (pd.to_datetime(eq["date"].iloc[-1]) - pd.to_datetime(eq["date"].iloc[0])).days
    yrs = days / 365.25
    annual = ((v[-1] / v[0]) ** (1 / yrs) - 1) * 100
    ret = pd.Series(v).pct_change().dropna()
    sharpe = ret.mean() / ret.std() * math.sqrt(252) if len(ret) > 5 and ret.std() > 0 else 0
    dd = (v / np.maximum.accumulate(v) - 1) * 100
    win = sum(1 for t in tr if t.get("pnl", 0) > 0) / len(tr) * 100 if tr else 0
    return {"total_return_pct": round(total, 2), "annual_return_pct": round(annual, 2),
            "max_drawdown_pct": round(dd.min(), 2), "sharpe": round(sharpe, 3),
            "win_rate_pct": round(win, 1), "total_trades": len(tr)}


if __name__ == "__main__":
    results = {}
    def run_case(label, **kw):
        t0c = time.time()
        eq, tr = run_fund_v5(**kw)
        s = summ(eq, tr)
        flag = "✅回撤达标" if (s.get("max_drawdown_pct") or -99) > -25 else ""
        print(f"[{label}] {time.time()-t0c:.0f}s | 收益 {s.get('total_return_pct')}% | "
              f"年化 {s.get('annual_return_pct')}% | 回撤 {s.get('max_drawdown_pct')}% | "
              f"夏普 {s.get('sharpe')} | 胜率 {s.get('win_rate_pct')}% | 交易 {s.get('total_trades')} {flag}",
              flush=True)
        return s

    # 基线（T+1 口径，MA200，无止损）
    results["V0_基线"] = run_case("V0_基线", top_n=10, hold_days=126, ma_window=200)
    # A 路：个股净值回撤止损
    for ns in [0.10, 0.15, 0.20]:
        results[f"V1_navstop{int(ns*100)}"] = run_case(f"V1_navstop{int(ns*100)}",
                                                       top_n=10, hold_days=126, ma_window=200, nav_stop=ns)
    # B 路：组合熔断即时清仓（修复版）
    for cc in [0.10, 0.15, 0.20]:
        results[f"V2_circuit{int(cc*100)}"] = run_case(f"V2_circuit{int(cc*100)}",
                                                       top_n=10, hold_days=126, ma_window=200, circuit=cc)
    # C 路：择时收紧 MA100
    results["V3_ma100"] = run_case("V3_ma100", top_n=10, hold_days=126, ma_window=100)
    # 组合
    results["V4_ns15_c15"] = run_case("V4_ns15_c15", top_n=10, hold_days=126, ma_window=200,
                                      nav_stop=0.15, circuit=0.15)
    results["V5_ns15_ma100"] = run_case("V5_ns15_ma100", top_n=10, hold_days=126, ma_window=100,
                                        nav_stop=0.15)
    results["V6_ns20_c20_ma100"] = run_case("V6_ns20_c20_ma100", top_n=10, hold_days=126, ma_window=100,
                                            nav_stop=0.20, circuit=0.20)

    json.dump(results, open("v8_fund_v5_results.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n=== 汇总（按回撤排序）===")
    for k, v in sorted(results.items(), key=lambda kv: kv[1].get("max_drawdown_pct", -99), reverse=True):
        flag = "✅" if (v.get("max_drawdown_pct") or -99) > -25 else ""
        print(f"{k:<18} 收益 {v.get('total_return_pct')}% | 年化 {v.get('annual_return_pct')}% | "
              f"回撤 {v.get('max_drawdown_pct')}% | 夏普 {v.get('sharpe')} | 胜率 {v.get('win_rate_pct')}% {flag}")