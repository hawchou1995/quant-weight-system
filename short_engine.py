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
import os
import sys, json, time, math
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
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
    # ---- 2026-08-31 剪藏因子（Obsidian 短线公式提炼）----
    d["vma5"] = d["volume"].rolling(5).mean()     # 5日均量（缩量企稳 F3 用）
    d["vma10"] = d["volume"].rolling(10).mean()   # 10日均量（缩量企稳 F3 用）
    # ---- v2 布林收窄因子（蜗牛量化布林收窄策略）----
    d["ma2"] = c.rolling(2).mean()                        # 2 日趋势线（BigQuant 铁律②）
    d["ma5"] = c.rolling(5).mean()                        # 5 日生命线（BigQuant 铁律①）
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    d["boll_mid"] = mid
    d["boll_bw"] = (2 * sd / mid.replace(0, np.nan))      # 布林带宽 (upper-mid)/mid = 2σ/MA20
    return d


def build_squeeze_events(pool, bw_th=0.02, vol_ratio=1.2, ma2_ok=True, min_px=1.0, min_amt=2e6):
    """布林收窄事件倒排索引：{date: [(code, vr5)]}
    事件条件（蜗牛量化策略 + BigQuant 铁律强化）：
    1) 当日 / 5日前 / 11日前 三处带宽 (upper-mid)/mid ≤ bw_th（窄轨收缩）
    2) mid 上行：mid(T) > mid(T-5)（趋势向上，原版条件）
    3) 放量：5日量比 vr5 > vol_ratio（铁律⑤ 放量涨；基金净值无量 → vol_ratio=None 跳过）
    4) 顺 2 日趋势：close > ma2（铁律②；可选）
    """
    from collections import defaultdict
    events = defaultdict(list)
    for code, ddf in pool.items():
        if "boll_bw" not in ddf.columns:
            continue
        bw = ddf["boll_bw"]
        ev = (bw <= bw_th) & (bw.shift(5) <= bw_th) & (bw.shift(11) <= bw_th)
        ev &= (ddf["boll_mid"] > ddf["boll_mid"].shift(5))
        if vol_ratio is not None and "vr5" in ddf.columns:
            ev &= (ddf["vr5"] > vol_ratio)
        if ma2_ok:
            ev &= (ddf["close"] > ddf["ma2"])
        if min_px > 0:
            ev &= (ddf["close"] >= min_px)
        if min_amt > 0 and "amt20" in ddf.columns:
            ev &= (ddf["amt20"] >= min_amt)
        idx = ddf.index[ev.values]
        for dt in idx:
            vr = ddf.loc[dt, "vr5"] if "vr5" in ddf.columns else 1.0
            events[dt].append((code, float(vr) if not pd.isna(vr) else 1.0))
    return events


def run_squeeze(pool, events, top_n=3, max_hold=3, take_profit=0.12, stop_loss=0.08,
                ma5_exit=True, use_market=True, ma_win=20, cash0=1_000_000, fund_mode=False,
                slippage_bps=0):
    """布林收窄事件驱动回测（v2）：
    T 日收盘出信号 → T+1 开盘买入（基金按当日净值）；排序=量比降序取 TopN
    卖出：止盈 / 止损 / 最多持有 max_hold 天 / MA5 生命线（收盘<MA5 就跑）"""
    idx = V.load_index(ma_win).set_index("date")
    in_market_map = idx["in_market"].to_dict()
    all_days = [d for d in idx.index if START <= str(d.date()) <= END]
    cash = cash0
    holdings, entry_price, entry_date = {}, {}, {}
    equity_curve, trades = [], []
    last_close = {}
    pending_sell, pending_buy = set(), []
    daily_signal = {}   # day -> [(code, vr)]

    def mark_sells(day, in_mkt):
        """每日卖出检查：止盈/止损/持有超期/MA5生命线/市况转弱全撤"""
        out = set()
        for code in list(holdings.keys()):
            ddf = pool.get(code)
            if ddf is None or day not in ddf.index:
                continue
            r = ddf.loc[day]
            px = r["close"]
            if pd.isna(px) or px <= 0:
                continue
            if px <= entry_price[code] * (1 - stop_loss):
                out.add(code); continue
            if take_profit and px >= entry_price[code] * (1 + take_profit):
                out.add(code); continue
            if (day - entry_date[code]).days >= max_hold:
                out.add(code); continue
            if ma5_exit and not pd.isna(r.get("ma5", np.nan)) and px < r["ma5"]:
                out.add(code); continue
        if not in_mkt:
            out |= set(holdings.keys())
        return out

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_market else True
        # 1) 先执行昨日挂单（今日开盘成交）—— 与信号日严格错开一日
        #    ⚠ 8/31 修复未来函数：原版「收盘卖出检查→当日开盘成交」信号晚于成交；现改为 T 日收盘触发 → T+1 开盘执行
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
                px = px * (1 - slippage_bps / 10000)   # 卖出滑点：实际到手价下浮
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
                for code, _vr in pending_buy:
                    if code in holdings:
                        continue
                    px = open_px.get(code)
                    if px is None or pd.isna(px) or px <= 0:
                        continue
                    sh = int(per_target / (px * (1 + V.COMMISSION)))
                    if fund_mode:
                        sh = int(sh / 100) * 100
                    if sh > 0 and sh * px * (1 + V.COMMISSION) <= cash:
                        cash -= sh * px * (1 + V.COMMISSION)
                        holdings[code] = sh
                        entry_price[code] = px
                        entry_date[code] = day
            pending_sell, pending_buy = set(), []
        # 2) 今日收盘卖出检查 → 挂明日开盘执行
        if holdings:
            pending_sell = mark_sells(day, in_market)
        # 3) 今日收盘扫信号 → 挂明日开盘执行（只用市况 OK 的日子）
        if in_market and di < len(all_days) - 1:
            cands = events.get(day, [])
            if cands:
                cands = [c for c in cands if c[0] not in holdings]
                cands.sort(key=lambda kv: -kv[1])          # 量比降序（方案② BuyOrder_VolDesc）
                daily_signal[day] = cands
                pending_buy = cands[:top_n]
        # 4) mark-to-market
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
                if pd.isna(px) or px <= 0:
                    px = None
            if px is None:
                px = last_close.get(code)
            if px is None or px <= 0:
                continue
            tax = sh * px * V.SELL_TAX
            proceeds = sh * px * (1 - V.COMMISSION) - tax
            pnl = proceeds - sh * entry_price[code] * (1 + V.COMMISSION)
            trades.append({"entry_date": str(entry_date[code].date()), "exit_date": str(last_day.date()),
                           "pnl": round(pnl, 2), "pnl_pct": round((px / entry_price[code] - 1) * 100, 2),
                           "holding_bars": (last_day - entry_date[code]).days, "symbol": code})
    return pd.DataFrame(equity_curve), trades

def short_score(r, reversal=False, weights=(30, 25, 25, 20), mask=(1, 1, 1, 1)):
    """短线综合分（0-100，权重可配 + 指标可开关）
    weights = (动量, 量价, 通道, 波动) 四因子权重
    mask    = (1/0) 对应因子是否启用；启用权重自动归一化
    reversal=True 时 20d 动量反转为短期反转（A 股个股短线反转有效，动量无效）
    -- 2026-09-01 改造：原硬编码 30/25/25/20 → 参数化，供牛熊 regime 不同配置 """
    _w = [max(0.0, float(x)) for x in weights]
    _m = [1 if x else 0 for x in mask]
    tot = sum(w for w, m in zip(_w, _m) if m)
    if tot <= 0:
        return 0.0
    s = 0.0
    # 动量 30 分量：20d 收益 0-15% 线性（反转版 = -mom20）
    if _m[0] and not np.isnan(r["mom20"]):
        m = r["mom20"] if not reversal else -r["mom20"]
        f = max(0.0, min(1.0, m / 0.15))
        s += _w[0] * f / tot * 100
    # 量价 25 分量：放量上涨给 15，量比增强 10
    if _m[1]:
        f = 15 / 25 * (1 if r["vp"] else 0)
        if not np.isnan(r["vr5"]):
            f += 10 / 25 * max(0.0, min(1.0, (r["vr5"] - 0.5) / 2.0))
        s += _w[1] * f / tot * 100
    # 通道 25 分量：唐奇安位置
    if _m[2] and not np.isnan(r["dnc"]):
        s += _w[2] * r["dnc"] / tot * 100
    # 波动 20 分量：低波优选（年化 20%-80% 线性反比）
    if _m[3] and not np.isnan(r["vol20"]):
        f = max(0.0, min(1.0, 1 - (r["vol20"] - 0.20) / 0.60))
        s += _w[3] * f / tot * 100
    return s

# ---------------- 池 ----------------
def load_stock_pool():
    pool = {}
    for f in sorted((BASE / "data_full").glob("*.csv")):
        code = f.stem
        if code.startswith(("bj", "sh5", "sz1", "sh9")):  # sh9=B股（USD计价，流动性差，剔）
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
    # 2026-08-24 修复：剔「死数据」标的——退市/改名后 data_full 停更的股票（如 600317 营口港
    #   2021 年并入辽港股份后数据停在 2021-01-14）仍会以「最新行」参与短线打分并进池/跟踪，
    #   看板显示多年前价格误导。以全市场最新交易日为基准，落后 >10 自然日的标的剔除
    #   （停牌股同剔——不可交易，短线信号无意义；正常标的当日回填滞后 ≤1 日不受影响）。
    if pool:
        _max = max(df.index[-1] for df in pool.values())
        _cut = _max - pd.Timedelta(days=10)
        pool = {c: df for c, df in pool.items() if df.index[-1] >= _cut}
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
def _mk_cfg(**kw):
    """regime 配置默认值（牛/熊各自权重/掩码/门槛）"""
    c = dict(top_n=10, hold_days=15, score_min=55, reversal=True, ma5_exit=False,
             take_profit=0.0, stop_loss=0.0, min_amt=3e7, weights=(30, 25, 25, 20),
             mask=(1, 1, 1, 1), filter_col=None, vol_target=None, rebal_buffer=0.0,
             senti_col=None)
    c.update(kw)
    return c


def run_short_regime(pool, bull_cfg=None, bear_cfg=None, cash0=1_000_000,
                     use_market=True, ma_win=20, min_px=1.0, slippage_bps=20,
                     sky_vol_filter=0, allow_bear_buy=False, fund_mode=False,
                     tier_cfg=None, idx_mom20_strong=0.03, score_fn=None):
    """短线轮动回测（regime 感知版，2026-09-01）：
    T 日收盘打分 → T+1 开盘换仓；市况门控（沪深300>MA）切换牛/熊配置：
    - 牛 regime（in_market=True）：bull_cfg 权重/掩码/门槛/标的数
    - 熊 regime（in_market=False）：bear_cfg 防守配置（低波重/更严门槛/更少标的）
      allow_bear_buy=False（默认）：熊市不开新仓只清仓（与生产一致）；
      allow_bear_buy=True：熊市用 bear_cfg 继续轮动（实验用，评估防守配置能否抗回撤）
    - vol_target（防御 sleeve，AbacusFlow 借鉴）：持仓仓位 = min(1, vol_target/组合年化波动) 等权降仓
    - filter_col：剪藏因子列硬过滤（当日=1 才入选）
    - rebal_buffer（AbacusFlow 换仓 buffer）：持仓标的分数 ≥ 榜尾分×(1-buffer) 时保留（降换手）
    - tier_cfg（三态，2026-09-01）：{strong: cfg, weak: cfg} 牛市按沪深300 20d 动量分强弱，
      强牛（mom20>idx_mom20_strong）用 strong 配置、弱牛用 weak 配置、熊市按 allow_bear_buy；
      不传则回落两态（bull_cfg/bear_cfg）
    权重/掩码参数化：weights=(动量,量价,通道,波动)，mask=(1/0) 开关对应因子
    fund_mode=True：基金净值池（open 列=close，成交用 close，量价因子退化）
    """
    idx = V.load_index(ma_win).set_index("date")
    in_market_map = idx["in_market"].to_dict()
    idx_mom20_map = (idx["close"] / idx["close"].shift(20) - 1).to_dict()
    all_days = [d for d in idx.index if START <= str(d.date()) <= END]
    bull_cfg = _mk_cfg(**(bull_cfg or {}))
    bear_cfg = _mk_cfg(**(bear_cfg or {}))
    rebal_days = set(all_days[::bull_cfg["hold_days"]])
    cash = cash0
    holdings, entry_price, entry_date = {}, {}, {}
    equity_curve, trades = [], []
    last_close = {}
    pending_sell, pending_buy = set(), []

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_market else True
        if tier_cfg is not None:
            # 三态：强牛/弱牛/熊（strong/weak 归一化补默认键）
            _strong = _mk_cfg(**(tier_cfg.get("strong") or {}))
            _weak = _mk_cfg(**(tier_cfg.get("weak") or {}))
            if not in_market:
                cfg = bear_cfg
            else:
                _m20 = idx_mom20_map.get(day, 0) or 0
                cfg = _strong if _m20 > idx_mom20_strong else _weak
        else:
            cfg = bull_cfg if in_market else bear_cfg
        # 1) 先执行昨日挂单（今日开盘成交）—— 与信号日严格错开一日
        #    ⚠ 8/31 修复未来函数：原版「收盘风控→当日开盘成交」信号晚于成交；现改为 T 日收盘触发 → T+1 开盘执行
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
                px = px * (1 - slippage_bps / 10000)   # 卖出滑点：实际到手价下浮
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
                # 防御 sleeve：波动率目标降仓（AbacusFlow 借鉴）
                vt = cfg.get("vol_target")
                if vt:
                    _rets = pd.Series([x["value"] for x in equity_curve[-30:]])
                    if len(_rets) >= 10:
                        _vol = _rets.pct_change().std() * math.sqrt(252)
                        if _vol and _vol > 0:
                            per_target = min(per_target, per_target * min(1.0, vt / _vol))
                for code, _sc in pending_buy:
                    if code in holdings:
                        continue
                    px = open_px.get(code)
                    if px is None or pd.isna(px) or px <= 0:
                        continue
                    _buy_px = px * (1 + slippage_bps / 10000)   # 买入滑点：实际成本价上浮
                    sh = int(per_target / (_buy_px * (1 + V.COMMISSION)))
                    if sh > 0 and sh * _buy_px * (1 + V.COMMISSION) <= cash:
                        cash -= sh * _buy_px * (1 + V.COMMISSION)
                        holdings[code] = sh
                        entry_price[code] = _buy_px
                        entry_date[code] = day
            pending_sell, pending_buy = set(), []
        # 2) 今日收盘风控（MA5 生命线 / 止盈 / 固定止损）→ 挂明日开盘执行
        if holdings and (cfg["ma5_exit"] or cfg["take_profit"] > 0 or cfg["stop_loss"] > 0):
            for code in list(holdings.keys()):
                ddf = pool.get(code)
                if ddf is None or day not in ddf.index:
                    continue
                r = ddf.loc[day]
                px = r["close"]
                if pd.isna(px) or px <= 0:
                    continue
                if cfg["stop_loss"] > 0 and px <= entry_price[code] * (1 - cfg["stop_loss"]):
                    pending_sell.add(code); continue
                if cfg["take_profit"] > 0 and px >= entry_price[code] * (1 + cfg["take_profit"]):
                    pending_sell.add(code); continue
                if cfg["ma5_exit"] and not pd.isna(r.get("ma5", np.nan)) and px < r["ma5"]:
                    pending_sell.add(code)
        # 3) 今日收盘选股 → 挂明日开盘执行
        if day in rebal_days and di < len(all_days) - 1:
            if not in_market and not allow_bear_buy:
                pending_sell |= set(holdings.keys())
                pending_buy = []
            else:
                cand = []
                cand_scores = {}
                for code, ddf in pool.items():
                    if day not in ddf.index:
                        continue
                    r = ddf.loc[day]
                    if pd.isna(r["close"]) or r["close"] <= 0 or pd.isna(r["mom20"]):
                        continue
                    if r["close"] < min_px:
                        continue
                    if not fund_mode and (pd.isna(r["amt20"]) or r["amt20"] < cfg["min_amt"]):
                        continue
                    fc = cfg.get("filter_col")
                    if fc is not None:
                        fv = r.get(fc)
                        if pd.isna(fv) or fv != 1:
                            continue
                    sc = short_score(r, reversal=cfg["reversal"], weights=cfg["weights"], mask=cfg["mask"])
                    if score_fn is not None:
                        sc = score_fn(r, cfg)
                    if sc < cfg["score_min"]:
                        continue
                    if sky_vol_filter > 0 and "vr5" in ddf.columns:
                        _hist = ddf.loc[:day, "vr5"]
                        if (_hist.tail(sky_vol_filter) > 5).any():
                            continue
                    cand.append((code, sc))
                    cand_scores[code] = sc
                cand.sort(key=lambda kv: -kv[1])
                ranked = cand[:cfg["top_n"]]
                keep = {c for c, _ in ranked}
                # AbacusFlow 换仓 buffer 借鉴（2026-09-01）：持仓标的若仍满足门槛且
                # 分数 ≥ 候选榜第 top_n 名分数×(1-rebal_buffer)，则保留（降换手/降成本）
                buf = cfg.get("rebal_buffer") or 0.0
                if buf > 0 and len(ranked) > 0 and len(holdings) > 0:
                    thresh = ranked[-1][1] * (1 - buf)
                    for code in list(holdings):
                        if code in keep or code not in cand_scores:
                            continue
                        if cand_scores[code] >= thresh and code in cand_scores:
                            keep.add(code)
                pending_sell |= {c for c in holdings if c not in keep}
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


def run_short(pool, top_n=10, hold_days=10, score_min=50, cash0=1_000_000,
              use_market=True, ma_win=20, min_px=1.0, min_amt=2e6, fund_mode=False,
              reversal=False, ma5_exit=False, take_profit=0.0, stop_loss=0.0,
              slippage_bps=0, sky_vol_filter=0):
    """短线轮动回测：T 日收盘打分 → T+1 开盘换仓；市况门控（沪深300>MA）
    v3 混合风控：ma5_exit=MA5生命线每日止损 / take_profit=止盈 / stop_loss=固定止损（默认关闭=纯轮动）
    slippage_bps=每边滑点/冲击成本（基点；买入价上浮、卖出价下浮；基金=T+1净值申购赎回费口径）"""
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
        # 1) 先执行昨日挂单（今日开盘成交）—— 与信号日严格错开一日
        #    ⚠ 8/31 修复未来函数：原版「收盘风控→当日开盘成交」信号晚于成交；现改为 T 日收盘触发 → T+1 开盘执行
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
                px = px * (1 - slippage_bps / 10000)   # 卖出滑点：实际到手价下浮
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
                    _buy_px = px * (1 + slippage_bps / 10000)   # 买入滑点：实际成本价上浮
                    sh = int(per_target / (_buy_px * (1 + V.COMMISSION)))
                    if fund_mode:
                        sh = int(sh / 100) * 100  # 基金净值近似整百份
                    if sh > 0 and sh * _buy_px * (1 + V.COMMISSION) <= cash:
                        cash -= sh * _buy_px * (1 + V.COMMISSION)
                        holdings[code] = sh
                        entry_price[code] = _buy_px
                        entry_date[code] = day
            pending_sell, pending_buy = set(), []
        # 2) 今日收盘风控（MA5 生命线 / 止盈 / 固定止损）→ 挂明日开盘执行
        if holdings and (ma5_exit or take_profit > 0 or stop_loss > 0):
            for code in list(holdings.keys()):
                ddf = pool.get(code)
                if ddf is None or day not in ddf.index:
                    continue
                r = ddf.loc[day]
                px = r["close"]
                if pd.isna(px) or px <= 0:
                    continue
                if stop_loss > 0 and px <= entry_price[code] * (1 - stop_loss):
                    pending_sell.add(code); continue
                if take_profit > 0 and px >= entry_price[code] * (1 + take_profit):
                    pending_sell.add(code); continue
                if ma5_exit and not pd.isna(r.get("ma5", np.nan)) and px < r["ma5"]:
                    pending_sell.add(code)
        # 3) 今日收盘选股 → 挂明日开盘执行
        if day in rebal_days and di < len(all_days) - 1:
            if not in_market:
                pending_sell |= set(holdings.keys())
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
                    if sky_vol_filter > 0 and "vr5" in ddf.columns:
                        # 天量剔除（文章8：历史天量后 T+20 胜率仅 27%）：近 N 日内出现量比>5 的天量 → 剔
                        _hist = ddf.loc[:day, "vr5"]
                        if (_hist.tail(sky_vol_filter) > 5).any():
                            continue
                    cand.append((code, sc))
                cand.sort(key=lambda kv: -kv[1])
                ranked = cand[:top_n]
                keep = {c for c, _ in ranked}
                pending_sell |= {c for c in holdings if c not in keep}
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