# -*- coding: utf-8 -*-
"""
UZI-Skill 规则提取 → v8 因子注入回测
=====================================
从 UZI stock_features.py 提取纯 OHLCV 可回测因子（v8 现有四因子之外）：
- F_MA_BULL  均线多头排列（MA5>MA10>MA20>MA60，UZI ma_bull_aligned）
- F_STAGE2   Stage 2 阶段确认（价格>MA200 且 MA30 斜率上行，Weinstein 阶段模型）
- F_WILLR    Williams %R（-80 以下超卖、-20 以上超买）
- F_OBV      OBV 趋势向上（20 日 OBV 斜率）
注入 v8 打分网格，对比基线夏普 0.817
"""
import os
import sys, json, time, math
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v8_selector as V


def add_uzi_factors(df: pd.DataFrame) -> pd.DataFrame:
    """在 compute_factors_full 基础上追加 UZI 因子列"""
    d = df.copy()
    c = d["close"]
    # F_MA_BULL：MA5>MA10>MA20>MA60 多头排列（1/0）
    ma5 = c.rolling(5).mean()
    ma10 = c.rolling(10).mean()
    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(60).mean()
    d["ma_bull"] = ((ma5 > ma10) & (ma10 > ma20) & (ma20 > ma60)).astype(int)
    # F_STAGE2：价格>MA200 且 MA30 上行（Weinstein Stage 2）
    ma30 = c.rolling(30).mean()
    ma200 = c.rolling(200).mean()
    d["stage2"] = ((c > ma200) & (ma30 > ma30.shift(20))).astype(int)
    # F_WILLR：Williams %R = (HHV14 - C) / (HHV14 - LLV14) * -100
    hh14 = d["high"].rolling(14).max()
    ll14 = d["low"].rolling(14).min()
    willr = (hh14 - c) / (hh14 - ll14).replace(0, np.nan) * -100
    d["willr"] = willr.fillna(-50)
    # F_OBV：OBV 20 日斜率 > 0
    obv = (np.sign(c.diff()).fillna(0) * d["volume"].fillna(0)).cumsum()
    d["obv_up"] = (obv > obv.shift(20)).astype(int)
    return d


def score_row_uzi(r, w_mom=0.35, w_trend=0.25, w_aroon=0.20, w_vp=0.20,
                  w_uzi=0.0, uzi_col="ma_bull"):
    """在 v8 四因子基础上叠加 UZI 因子（0-100 归一）"""
    s = V.score_row(r, w_mom, w_trend, w_aroon, w_vp)
    # 用 w_uzi 从四因子中按比例让渡权重
    scale = 1.0 - w_uzi
    s = s * scale
    if w_uzi > 0:
        v = r.get(uzi_col, 0)
        s += w_uzi * (100 if v else 0)
    return s


def run_v8_uzi(top_n=25, hold_days=42, use_timing=True,
               w_mom=0.35, w_trend=0.25, w_aroon=0.20, w_vp=0.20,
               w_uzi=0.0, uzi_col="ma_bull", stop_loss=0.20,
               min_price=2.0, max_vol=0.60, pool=None):
    """v8 主循环 + UZI 因子（复用 v8_enhance2 逻辑）"""
    import v8_enhance2 as E
    # 扩展因子池：给 pool 里的每只 df 追加 UZI 列（缓存一次）
    global _uzi_pool
    if _uzi_pool is None:
        _uzi_pool = {}
        for code, df in pool.items():
            try:
                _uzi_pool[code] = add_uzi_factors(df)
            except Exception:
                _uzi_pool[code] = df
    p2 = _uzi_pool
    # 用 E.run_v8_single_timing，但需要传入自定义打分——直接内嵌一个变体
    return run_v8_single_timing_uzi(p2, top_n, hold_days, use_timing,
                                    w_mom, w_trend, w_aroon, w_vp,
                                    w_uzi, uzi_col, stop_loss, min_price, max_vol)


_uzi_pool = None


def run_v8_single_timing_uzi(pool, top_n, hold_days, use_timing,
                             w_mom, w_trend, w_aroon, w_vp,
                             w_uzi, uzi_col, stop_loss, min_price, max_vol):
    import v8_selector as VV
    idx = VV.load_index(200).set_index("date")
    in_market_map = idx["in_market"].to_dict()
    data = pool
    all_days = [d for d in idx.index if VV.START <= str(d.date()) <= VV.END]
    rebal_days = set(all_days[::hold_days])
    cash = 1_000_000.0
    holdings, entry_price, entry_date = {}, {}, {}
    equity_curve, trades = [], []
    pending_sell, pending_buy = set(), []
    last_close = {}
    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_timing else True
        if stop_loss and holdings:
            for code in list(holdings.keys()):
                ddf = data.get(code)
                if ddf is None or day not in ddf.index:
                    continue
                px = ddf.loc[day, "close"]
                if not pd.isna(px) and px <= entry_price[code] * (1 - stop_loss):
                    pending_sell.add(code)
        if pending_sell or pending_buy:
            open_px = {}
            for code in list(pending_sell) + [c for c, _ in pending_buy]:
                ddf = data.get(code)
                if ddf is not None and day in ddf.index:
                    open_px[code] = ddf.loc[day, "open"]
            for code in list(pending_sell):
                if code not in holdings:
                    continue
                px = open_px.get(code)
                if px is None or pd.isna(px) or px <= 0:
                    continue
                sh = holdings.pop(code)
                tax = sh * px * VV.SELL_TAX
                proceeds = sh * px * (1 - VV.COMMISSION) - tax
                pnl = proceeds - sh * entry_price[code] * (1 + VV.COMMISSION)
                trades.append({"entry_date": str(entry_date[code].date()), "exit_date": dstr,
                               "side": "long", "size": sh, "entry_price": round(entry_price[code], 4),
                               "exit_price": round(px, 4), "pnl": round(pnl, 2),
                               "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                               "holding_bars": (day - entry_date[code]).days,
                               "symbol": code, "symbol_name": code, "display_symbol": code})
                cash += proceeds
            if pending_buy:
                port_value = cash
                for code, sh in holdings.items():
                    if last_close.get(code):
                        port_value += sh * last_close[code]
                per_target = port_value / top_n
                for code, _score in pending_buy:
                    if code in holdings:
                        continue
                    px = open_px.get(code)
                    if px is None or pd.isna(px) or px <= 0:
                        continue
                    target_shares = int(per_target / (px * (1 + VV.COMMISSION)))
                    target_shares = (target_shares // VV.LOT) * VV.LOT
                    if target_shares > 0 and target_shares * px * (1 + VV.COMMISSION) <= cash:
                        cash -= target_shares * px * (1 + VV.COMMISSION)
                        holdings[code] = target_shares
                        entry_price[code] = px
                        entry_date[code] = day
            pending_sell = set()
            pending_buy = []
        if day in rebal_days and di < len(all_days) - 1:
            if not in_market:
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
                    if pd.isna(r["amt20"]) or r["amt20"] < 5e6:
                        continue
                    if max_vol and not pd.isna(r["vol20"]) and r["vol20"] > max_vol:
                        continue
                    if r["close"] < min_price:
                        continue
                    candidates[code] = score_row_uzi(r, w_mom, w_trend, w_aroon, w_vp, w_uzi, uzi_col)
                if candidates:
                    ranked = sorted(candidates.items(), key=lambda kv: -kv[1])[:top_n]
                    keep = {c for c, _ in ranked}
                    pending_sell = {c for c in holdings if c not in keep}
                    pending_buy = ranked
                else:
                    pending_sell = set(holdings.keys())
                    pending_buy = []
        port_value = cash
        for code, sh in holdings.items():
            ddf = data.get(code)
            if ddf is not None and day in ddf.index:
                px = ddf.loc[day, "close"]
                if not pd.isna(px):
                    port_value += sh * px
                    last_close[code] = px
        equity_curve.append({"date": dstr, "value": round(port_value, 2)})
    if holdings:
        last_day = all_days[-1]
        for code, sh in holdings.items():
            ddf = data.get(code)
            if ddf is None or last_day not in ddf.index:
                continue
            px = ddf.loc[last_day, "close"]
            if pd.isna(px) or px <= 0:
                continue
            tax = sh * px * VV.SELL_TAX
            proceeds = sh * px * (1 - VV.COMMISSION) - tax
            pnl = proceeds - sh * entry_price[code] * (1 + VV.COMMISSION)
            trades.append({"entry_date": str(entry_date[code].date()), "exit_date": str(last_day.date()),
                           "side": "long", "size": sh, "entry_price": round(entry_price[code], 4),
                           "exit_price": round(px, 4), "pnl": round(pnl, 2),
                           "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                           "holding_bars": (last_day - entry_date[code]).days,
                           "symbol": code, "symbol_name": code, "display_symbol": code})
            cash += proceeds
        holdings = {}
    return pd.DataFrame(equity_curve), trades


if __name__ == "__main__":
    pool = V.load_pool()
    print(f"池: {len(pool)} 只\n")

    def run_case(label, **kw):
        t0 = time.time()
        eq, trades = run_v8_uzi(pool=pool, **kw)
        s = V.summary(eq, trades)
        s["seconds"] = round(time.time() - t0, 0)
        s["label"] = label
        print(f"[{label}] {s['seconds']}s | 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% "
              f"| 回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']}", flush=True)
        return s

    results = {}
    BASE_KW = dict(top_n=25, hold_days=42, use_timing=True, stop_loss=0.20,
                   min_price=2.0, max_vol=0.60)

    # 基线（无 UZI 因子，复现 G5_Top25）
    results["U0_基线"] = run_case("U0_基线", **BASE_KW)

    # UZI 因子注入：权重 10% / 20% / 30%
    for col in ["ma_bull", "stage2", "obv_up"]:
        for wu in [0.10, 0.20, 0.30]:
            results[f"U_{col}_{int(wu*100)}%"] = run_case(f"U_{col}_{int(wu*100)}%",
                **BASE_KW, w_uzi=wu, uzi_col=col)

    # WillR 超卖反转加分（willr < -80 → 加分 20 分制）
    # 特殊处理：willr 是连续值，用阈值
    def run_willr(label, **kw):
        t0 = time.time()
        eq, trades = run_willr_custom(pool, **kw)
        s = V.summary(eq, trades)
        s["seconds"] = round(time.time() - t0, 0)
        s["label"] = label
        print(f"[{label}] {s['seconds']}s | 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% "
              f"| 回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 胜率 {s['win_rate_pct']}% | 交易 {s['total_trades']}", flush=True)
        return s

    # WillR 单独跑（用 ma_bull 权重 0 对照）
    for wu in [0.10, 0.20]:
        results[f"U_willr_{int(wu*100)}%"] = run_case(f"U_willr_{int(wu*100)}%",
            **BASE_KW, w_uzi=wu, uzi_col="willr_neg")

    with open("v8_uzi_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n===== UZI 因子网格汇总（按夏普排序）=====")
    for k, v in sorted(results.items(), key=lambda kv: -(kv[1].get("sharpe") or 0)):
        better = "✅>基线" if (v.get("sharpe") or 0) > 0.817 else ""
        print(f"{k:<20} 收益 {v.get('total_return_pct')}% | 回撤 {v.get('max_drawdown_pct')}% | 夏普 {v.get('sharpe')} | 交易 {v.get('total_trades')} {better}")