# -*- coding: utf-8 -*-
"""v9-auto：绝对规则自动池 + 池内持仓（无人工选池的普适体系）"""
import os
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import math
import v8_selector as V

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
pool_all = V.load_pool()


def get_ddf(auto_pool, code):
    ddf = auto_pool.get(code)
    if ddf is None:
        ddf = pool_all.get(code)
    return ddf


def board_filter(code, perm="all"):
    """交易权限过滤（A 股板块权限）：
    perm='main' 沪深主板(sh60/sz00)      —— 新开户即可
    perm='gem'  主板+创业板(sz30)        —— 2年经验+10万资产
    perm='star' 主板+创业板+科创板(sh688)—— 2年经验+50万资产
    perm='all'  全部 A 股                 —— 含 B 股剔除
    互斥分层（v5.9 分层回测用）：
    perm='main_only' 纯主板(sh60/sz00/sz002)
    perm='gem_only'  纯创业板(sz30)
    perm='star_only' 纯科创板(sh688/sh689)
    """
    if code.startswith("sh900") or code.startswith("sz200"):
        return False  # B 股：普通 A 股账户不可买
    if perm == "main_only":
        return code.startswith(("sh60", "sz00", "sz002"))
    if perm == "gem_only":
        return code.startswith("sz30")
    if perm == "star_only":
        return code.startswith(("sh688", "sh689"))
    if perm == "all":
        return True
    if code.startswith(("sh60", "sz00")):
        return True
    if perm == "gem" and code.startswith("sz30"):
        return True
    if perm == "star" and (code.startswith("sz30") or code.startswith("sh688") or code.startswith("sh689")):
        return True
    return False


def run_auto(top_n=4, hold_days=21, pool_size=25, stop_loss=0.10, cash0=500000, slippage_bps=0, hot_filter=0.0,
             mom_min=0.15, score_min=60, use_timing=True, sell_score=0,
             dynamic=False, rsi_max=None, ma_window=200, vol_target=None, perm="all", ma60_gate=False,
             regime=False, timing=None, weak_bull_pos=1.0, weak_bull_score_min=0):
    """v9-auto 引擎（2026-09-08 分域+择时扩展）：
    regime=True  → 牛熊分域（与短线 KHunter 同口径，T-1 收盘确认）：
        熊市 = hs300 close < MA250 → 不开仓（维持现状清仓语义）
        弱牛 = MA250 上 / MA20 下 → 仓位 ×weak_bull_pos + score 门槛提升 weak_bull_score_min
        强牛 = MA250 上 / MA20 上 → 正常
    timing       → 市场级择时（指数层面，非个股 RSI）：
        'ma_resonance' 指数 MA20>MA60>MA250 多头排列才开仓
        'aroon'        指数 Aroon(25) 上行（Up>Down）才开仓
        'volume'       指数量比<1（缩量）+ 20日波动率<60日（收缩）才开仓
        'mom_slope'    指数 20 日动量斜率（mom20 的 5 日变化>0）才开仓
        'ma_aroon'     MA 共振 + Aroon 双条件
    默认 regime=False/timing=None → 与旧版行为完全一致（基线可复现）。
    """
    idx = V.load_index(200).set_index('date')
    idx['idx_vol'] = idx['close'].pct_change().rolling(20).std() * math.sqrt(252)
    idx_vol = idx['idx_vol'].to_dict()
    idx['ma_t'] = idx['close'].rolling(ma_window).mean()
    if ma60_gate:   # 2026-09-08：加 MA60 日线约束（指数需同时站上 ma_window 与 MA60 才开仓）
        idx['ma60x'] = idx['close'].rolling(60).mean()
        in_market_map = {d: bool(pd.notna(r['ma_t']) and r['close'] > r['ma_t']
                                 and pd.notna(r['ma60x']) and r['close'] > r['ma60x'])
                         for d, r in idx.iterrows()}
    else:
        in_market_map = {d: bool(pd.notna(r['ma_t']) and r['close'] > r['ma_t']) for d, r in idx.iterrows()}
    # ---- 2026-09-08 分域 + 择时（默认关闭，不影响基线）----
    regime_map, timing_map = {}, {}
    if regime:
        idx['ma20x'] = idx['close'].rolling(20).mean()
        idx['ma250x'] = idx['close'].rolling(250).mean()
        for d, r in idx.iterrows():
            if pd.isna(r['ma250x']) or pd.isna(r['ma20x']):
                regime_map[d] = 'bear'   # 数据不足按熊市保守处理
            elif r['close'] < r['ma250x']:
                regime_map[d] = 'bear'
            elif r['close'] < r['ma20x']:
                regime_map[d] = 'weak'
            else:
                regime_map[d] = 'strong'
    if timing:
        # ⚠ 2026-09-09 修复：ma20x/ma250x 原先只在 regime=True 分支创建，
        #    单独开 timing（regime=False）时 KeyError → 此处按需自建（幂等，生产默认 timing=None 零影响）
        if 'ma20x' not in idx.columns:
            idx['ma20x'] = idx['close'].rolling(20).mean()
        if 'ma250x' not in idx.columns:
            idx['ma250x'] = idx['close'].rolling(250).mean()
        if timing in ('ma_resonance', 'ma_aroon'):
            idx['ma60x'] = idx['close'].rolling(60).mean()
            _res = (idx['ma20x'] > idx['ma60x']) & (idx['ma60x'] > idx['ma250x'])
        if timing in ('aroon', 'ma_aroon'):
            _hi = idx['high'].rolling(26).apply(lambda x: int(np.argmax(x)), raw=True)
            _lo = idx['low'].rolling(26).apply(lambda x: int(np.argmin(x)), raw=True)
            _up = 100.0 * (25 - _hi) / 25.0
            _dn = 100.0 * (25 - _lo) / 25.0
            _aroon_ok = _up > _dn
        if timing == 'volume':
            _vr = idx['volume'].rolling(5).mean() / idx['volume'].rolling(20).mean().replace(0, np.nan)
            _v20 = idx['close'].pct_change().rolling(20).std() * math.sqrt(252)
            _v60 = idx['close'].pct_change().rolling(60).std() * math.sqrt(252)
            _vol_ok = (_vr < 1.0) & (_v20 < _v60)
        if timing == 'mom_slope':
            _m20 = idx['close'] / idx['close'].shift(20) - 1.0
            _slope = _m20 - _m20.shift(5)
            _mom_ok = _slope > 0
        for d, r in idx.iterrows():
            ok = True
            if timing in ('ma_resonance', 'ma_aroon'):
                ok = ok and bool(pd.notna(r['ma20x']) and pd.notna(r['ma60x']) and pd.notna(r['ma250x']) and _res.get(d, False))
            if timing in ('aroon', 'ma_aroon'):
                ok = ok and bool(_aroon_ok.get(d, False))
            if timing == 'volume':
                ok = ok and bool(_vol_ok.get(d, False))
            if timing == 'mom_slope':
                ok = ok and bool(_mom_ok.get(d, False))
            timing_map[d] = ok
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    rebal_days = set(all_days[::hold_days])
    cash = cash0
    holdings, ep, ed, peak = {}, {}, {}, {}
    eq, trades = [], []
    ps, pb = set(), []
    pending_scale = 1.0   # 2026-09-08：弱牛域仓位缩放（决策日定，T+1 执行日生效）
    last_close = {}
    auto_pool = {}
    _pending_stop = set()   # 2026-09-10 修复未来函数：T 日收盘触发 → T+1 开盘成交（原为同日 ps.add→open[T]）
    for di, day in enumerate(all_days):
        dstr = str(day.date())
        if _pending_stop:   # >>> DEFER STOP FLUSH（与前日收盘触发的止损合并，用今日 open 成交）
            ps |= _pending_stop
            _pending_stop = set()
        in_market = in_market_map.get(day, False) if use_timing else True
        if regime:
            in_market = in_market and regime_map.get(day, 'bear') != 'bear'
        if timing:
            in_market = in_market and timing_map.get(day, False)
        if holdings:
            for code in list(holdings.keys()):
                ddf = get_ddf(auto_pool, code)
                if ddf is None or day not in ddf.index: continue
                px = ddf.loc[day, 'close']
                if pd.isna(px) or px <= 0: continue
                if code not in peak or px > peak[code]: peak[code] = px
                if stop_loss and px <= peak[code] * (1 - stop_loss): _pending_stop.add(code)
        if ps or pb:
            open_px = {}
            for code in list(ps) + [c for c, _ in pb]:
                ddf = get_ddf(auto_pool, code)
                if ddf is not None and day in ddf.index: open_px[code] = ddf.loc[day, 'open']
            for code in list(ps):
                if code not in holdings: continue
                px = open_px.get(code)
                if px is None or pd.isna(px) or px <= 0: continue
                px = px * (1 - slippage_bps / 10000)   # 卖出滑点
                sh = holdings.pop(code); peak.pop(code, None)
                tax = sh * px * V.SELL_TAX
                proceeds = sh * px * (1 - V.COMMISSION) - tax
                pnl = proceeds - sh * ep[code] * (1 + V.COMMISSION)
                trades.append({'entry_date': str(ed[code].date()), 'exit_date': dstr, 'side': 'long', 'size': sh,
                               'entry_price': round(ep[code],4), 'exit_price': round(px,4), 'pnl': round(pnl,2),
                               'pnl_pct': round((px/ep[code]-1)*100,2), 'holding_bars': (day-ed[code]).days,
                               'symbol': code, 'symbol_name': code, 'display_symbol': code})
                cash += proceeds
            if pb:
                port_value = cash
                for code, sh in holdings.items():
                    if last_close.get(code): port_value += sh * last_close[code]
                scale = pending_scale   # 2026-09-08：弱牛域仓位缩放（决策日已定）
                if vol_target:
                    v = idx_vol.get(day)
                    if v is not None and not pd.isna(v) and v > 0:
                        scale = scale * max(0.3, min(1.0, vol_target / v))
                budget = port_value * scale / top_n
                # 自动补位：按分数降序遍历完整候选，买得起就买，最多 top_n 只
                for code, _sc in sorted(pb, key=lambda kv: -kv[1]):
                    if len(holdings) >= top_n:
                        break
                    if code in holdings: continue
                    px = open_px.get(code)
                    if px is None or pd.isna(px) or px <= 0: continue
                    px = px * (1 + slippage_bps / 10000)   # 买入滑点
                    lot = 100
                    n_lots = int(budget / (px * lot * (1 + V.COMMISSION)))
                    if n_lots < 1: continue
                    target_shares = n_lots * lot
                    cost = target_shares * px * (1 + V.COMMISSION)
                    if cost > cash:
                        n_lots = int(cash / (px * lot * (1 + V.COMMISSION)))
                        target_shares = n_lots * lot
                        cost = target_shares * px * (1 + V.COMMISSION)
                    if target_shares > 0 and cost <= cash:
                        cash -= cost
                        holdings[code] = target_shares
                        ep[code] = px; ed[code] = day; peak[code] = px
            ps = set(); pb = []
        if day in rebal_days and di < len(all_days) - 1:
            if not in_market:
                # 2026-09-09：低位稳拿（hold-only）——门控关时保留持仓、不新开仓。
                # 依据：门控重验 H2_MA200_低位稳拿 total +315.55%/夏普 0.876/mdd -28.73%
                #      vs 原全清仓 +218.38%/0.739/-28.72%（+97.17pp、夏普+0.137、回撤持平）；
                #      右尾敏感性剔 top1/3/5 每档均优。亦与生产链路语义对齐
                #      （build_enhanced_data.py / build_dual_system.py 中 in_market 不参与清仓，
                #       卖出仅由 off_board 掉榜5日 / sell_signal score<50 驱动）。
                ps = set(); pb = []
                pending_scale = 1.0
            else:
                thresh_now = score_min
                if dynamic:
                    v_now = idx_vol.get(day)
                    if v_now is not None and not pd.isna(v_now):
                        thresh_now = max(55.0, min(75.0, score_min + (v_now - 0.20) * 200))
                # 2026-09-08：弱牛域 → 仓位缩放 + score 门槛提升
                regime_now = regime_map.get(day, 'strong') if regime else 'strong'
                pending_scale = weak_bull_pos if regime_now == 'weak' else 1.0
                if regime_now == 'weak' and weak_bull_score_min:
                    thresh_now = max(thresh_now, weak_bull_score_min)
                cand = []
                for code, ddf in pool_all.items():
                    if not board_filter(code, perm): continue
                    if day not in ddf.index: continue
                    r = ddf.loc[day]
                    if pd.isna(r['close']) or r['close'] <= 0 or pd.isna(r['mom_12_1']): continue
                    if r['close'] < 2.0: continue
                    if pd.isna(r['amt20']) or r['amt20'] < 5e6: continue
                    if r['mom_12_1'] < mom_min: continue
                    if pd.isna(r['ma200_pos']) or r['ma200_pos'] <= 0: continue
                    if hot_filter > 0:
                        # 不过热过滤（文章7：MA5/MA120<1.35 且首次多头排列+20日冷却）
                        _ma5 = ddf['close'].rolling(5).mean().loc[day]
                        _ma120 = ddf['close'].rolling(120).mean().loc[day]
                        _ma20 = ddf['close'].rolling(20).mean().loc[day]
                        _ma60 = ddf['close'].rolling(60).mean().loc[day]
                        if pd.isna(_ma5) or pd.isna(_ma120) or _ma120 <= 0:
                            continue
                        if _ma5 / _ma120 > hot_filter:
                            continue   # 过热剔除
                        if _ma5 > _ma20 > _ma60 > _ma120:
                            _prev = ddf.loc[:day].tail(21).head(1)
                            if len(_prev) and not pd.isna(_prev['close'].iloc[0]):
                                _pma5 = _prev['close'].iloc[0]  # 简化：冷却由轮动周期天然控制
                    sc = V.score_row(r)
                    if sc < thresh_now: continue
                    if rsi_max and 'rsi' in ddf.columns and not pd.isna(ddf['rsi'].iloc[pos]) and ddf['rsi'].iloc[pos] > rsi_max:
                        continue
                    cand.append((code, sc))
                cand.sort(key=lambda kv: -kv[1])
                auto_pool = {c: pool_all[c] for c, _ in cand[:pool_size]}
                ranked = cand[:top_n]
                keep = {c for c, _ in ranked}
                ps = {c for c in holdings if c not in keep}
                if sell_score:
                    for code in list(holdings.keys()):
                        ddf = get_ddf(auto_pool, code)
                        if ddf is not None and day in ddf.index:
                            sc_now = V.score_row(ddf.loc[day])
                            if sc_now < sell_score:
                                ps.add(code)
                pb = cand   # 完整达标候选（买入自动补位，TopN 买不起时用下一名补上）
        pv = cash
        for code, sh in holdings.items():
            ddf = get_ddf(auto_pool, code)
            px = None
            if ddf is not None and day in ddf.index:
                px = ddf.loc[day, 'close']
                if not pd.isna(px) and px > 0: last_close[code] = px
                else: px = last_close.get(code)
            else: px = last_close.get(code)
            if px: pv += sh * px
        eq.append({'date': dstr, 'value': round(pv, 2)})
    if holdings:
        last_day = all_days[-1]
        for code, sh in holdings.items():
            px = last_close.get(code)
            if px is None or px <= 0: continue
            tax = sh * px * V.SELL_TAX
            proceeds = sh * px * (1 - V.COMMISSION) - tax
            pnl = proceeds - sh * ep[code] * (1 + V.COMMISSION)
            trades.append({'entry_date': str(ed[code].date()), 'exit_date': str(last_day.date()), 'side': 'long', 'size': sh,
                           'entry_price': round(ep[code],4), 'exit_price': round(px,4), 'pnl': round(pnl,2),
                           'pnl_pct': round((px/ep[code]-1)*100,2), 'holding_bars': (last_day-ed[code]).days,
                           'symbol': code, 'symbol_name': code, 'display_symbol': code})
            cash += proceeds
        holdings = {}
    return pd.DataFrame(eq), trades


if __name__ == "__main__":
    # 邻域冲刺：T3_SL8 附近
    cases = [
        ('T3_m20_s60_SL8', dict(top_n=3, mom_min=0.20, score_min=60, stop_loss=0.08)),
        ('T3_m25_s60_SL8', dict(top_n=3, mom_min=0.25, score_min=60, stop_loss=0.08)),
        ('T3_m20_s65_SL8', dict(top_n=3, mom_min=0.20, score_min=65, stop_loss=0.08)),
        ('T3_m25_s65_SL7', dict(top_n=3, mom_min=0.25, score_min=65, stop_loss=0.07)),
        ('T3_m25_s65_SL9', dict(top_n=3, mom_min=0.25, score_min=65, stop_loss=0.09)),
        ('T2_m25_s65_SL8', dict(top_n=2, mom_min=0.25, score_min=65, stop_loss=0.08)),
        ('T3_m30_s65_SL8', dict(top_n=3, mom_min=0.30, score_min=65, stop_loss=0.08)),
    ]
    import json
    res = {}
    for label, kw in cases:
        t0 = time.time()
        eq, tr = run_auto(**kw)
        s = V.summary(eq, tr)
        flag = '✅' if s['sharpe'] >= 1.0 and s['max_drawdown_pct'] > -30 and s['annual_return_pct'] >= 10 else ''
        print(f'{label}: {time.time()-t0:.0f}s | 收益 {s["total_return_pct"]}% | 年化 {s["annual_return_pct"]}% | 回撤 {s["max_drawdown_pct"]}% | 夏普 {s["sharpe"]} | 胜率 {s["win_rate_pct"]}% | 交易 {s["total_trades"]} {flag}', flush=True)
        res[label] = s
    json.dump(res, open(BASE / 'v9_auto_results.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)