# -*- coding: utf-8 -*-
"""Aroon 高位抑制回测敏感性（v9 体系，2026-08-18）
背景：海川智能 300720 8 连阳末端 Aroon=24（高位回落预警）但 mom/trend/vp 全满 → 总分 84.8 满仓追高 → -9.05%。
提案：aroon_osc < aroon_th 且 mom_12_1(年动量) > mom_th 时抑制（乘因子 或 封顶 59 不入买入）。
敏感性网格：≥7/9 组正向且无回撤恶化才投产（沿用 v6 铁律）。
对比基线：v9_auto_summary = +839.63% / 胜率 48.1% / 回撤 -10.93% / 夏普 1.715 / 183 笔。
用法：python explore_aroon_inhibit.py
"""
import os, sys, time, math, json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import v8_selector as V
import v9_auto as A


def run_auto_inhibit(aroon_th=None, mom_th=None, fac=0.6, cap=False, **kw):
    """基于 v9_auto.run_auto 的 Aroon 抑制变体（移除累计置信 biass 一致）"""
    import v9_auto as MA
    pool_all = MA.pool_all
    top_n = kw.get("top_n", 4); hold_days = kw.get("hold_days", 21)
    pool_size = kw.get("pool_size", 25); stop_loss = kw.get("stop_loss", 0.10)
    cash0 = kw.get("cash0", 500000); slippage_bps = kw.get("slippage_bps", 0)
    mom_min = kw.get("mom_min", 0.15); score_min = kw.get("score_min", 60)
    use_timing = kw.get("use_timing", True); sell_score = kw.get("sell_score", 0)
    dynamic = kw.get("dynamic", False); rsi_max = kw.get("rsi_max", None)
    ma_window = kw.get("ma_window", 200); perm = kw.get("perm", "all")

    idx = V.load_index(200).set_index('date')
    idx['idx_vol'] = idx['close'].pct_change().rolling(20).std() * math.sqrt(252)
    idx_vol = idx['idx_vol'].to_dict()
    idx['ma_t'] = idx['close'].rolling(ma_window).mean()
    in_market_map = {d: bool(pd.notna(r['ma_t']) and r['close'] > r['ma_t']) for d, r in idx.iterrows()}
    all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
    rebal_days = set(all_days[::hold_days])
    cash = cash0
    holdings, ep, ed, peak = {}, {}, {}, {}
    eq, trades = [], []
    ps, pb = set(), []
    last_close = {}
    auto_pool = {}

    def _get(code):
        d = auto_pool.get(code)
        if d is None:
            d = pool_all.get(code)
        return d

    for di, day in enumerate(all_days):
        dstr = str(day.date())
        in_market = in_market_map.get(day, False) if use_timing else True
        if holdings:
            for code in list(holdings.keys()):
                ddf = _get(code)
                if ddf is None or day not in ddf.index: continue
                px = ddf.loc[day, 'close']
                if pd.isna(px) or px <= 0: continue
                if code not in peak or px > peak[code]: peak[code] = px
                if stop_loss and px <= peak[code] * (1 - stop_loss): ps.add(code)
        if ps or pb:
            open_px = {}
            for code in list(ps) + [c for c, _ in pb]:
                ddf = _get(code)
                if ddf is not None and day in ddf.index: open_px[code] = ddf.loc[day, 'open']
            for code in list(ps):
                if code not in holdings: continue
                px = open_px.get(code)
                if px is None or pd.isna(px) or px <= 0: continue
                px = px * (1 - slippage_bps / 10000)
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
                scale = 1.0
                budget = port_value * scale / top_n
                for code, _sc in sorted(pb, key=lambda kv: -kv[1]):
                    if len(holdings) >= top_n: break
                    if code in holdings: continue
                    px = open_px.get(code)
                    if px is None or pd.isna(px) or px <= 0: continue
                    px = px * (1 + slippage_bps / 10000)
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
                ps = set(holdings.keys()); pb = []
            else:
                thresh_now = score_min
                cand = []
                for code, ddf in pool_all.items():
                    if not A.board_filter(code, perm): continue
                    if day not in ddf.index: continue
                    r = ddf.loc[day]
                    if pd.isna(r['close']) or r['close'] <= 0 or pd.isna(r['mom_12_1']): continue
                    if r['close'] < 2.0: continue
                    if pd.isna(r['amt20']) or r['amt20'] < 5e6: continue
                    if r['mom_12_1'] < mom_min: continue
                    if pd.isna(r['ma200_pos']) or r['ma200_pos'] <= 0: continue
                    try:
                        sc = float(V.score_row(r))
                    except Exception:
                        continue
                    # ===== Aroon 高位抑制注入 =====
                    if aroon_th is not None and mom_th is not None:
                        _a = r.get('aroon_osc')
                        _m = r.get('mom_12_1')
                        if not pd.isna(_a) and not pd.isna(_m):
                            if float(_a) < aroon_th and float(_m) > mom_th:
                                if cap:
                                    sc = min(sc, 59.0)   # 封顶不入买入
                                else:
                                    sc *= fac          # 抑制因子
                    if sc < thresh_now: continue
                    cand.append((code, sc))
                cand.sort(key=lambda kv: -kv[1])
                auto_pool = {c: pool_all[c] for c, _ in cand[:pool_size]}
                ranked = cand[:top_n]
                keep = {c for c, _ in ranked}
                ps = {c for c in holdings if c not in keep}
                if sell_score:
                    for code in list(holdings.keys()):
                        ddf = _get(code)
                        if ddf is not None and day in ddf.index:
                            sc_now = V.score_row(ddf.loc[day])
                            if sc_now < sell_score: ps.add(code)
                pb = cand
        pv = cash
        for code, sh in holdings.items():
            ddf = _get(code)
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
    # 基线复现
    t0 = time.time()
    eq0, tr0 = run_auto_inhibit(aroon_th=None, mom_th=None)
    s0 = V.summary(eq0, tr0)
    base = {'total_return_pct': s0['total_return_pct'], 'win_rate_pct': s0['win_rate_pct'],
            'annual_return_pct': s0['annual_return_pct'], 'max_drawdown_pct': s0['max_drawdown_pct'],
            'sharpe': s0['sharpe'], 'total_trades': s0['total_trades']}
    print(f"基线: {time.time()-t0:.0f}s {json.dumps(base)}", flush=True)
    json.dump({'label': 'baseline', 'summary': {k: float(v) for k, v in base.items()}},
              open(BASE / 'aroon_baseline.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    # 敏感性网格
    cases = [
        ('A30_M800_fac06', dict(aroon_th=30, mom_th=0.80, fac=0.6)),
        ('A30_M800_cap59', dict(aroon_th=30, mom_th=0.80, cap=True)),
        ('A40_M800_fac06', dict(aroon_th=40, mom_th=0.80, fac=0.6)),
        ('A40_M800_cap59', dict(aroon_th=40, mom_th=0.80, cap=True)),
        ('A50_M800_fac06', dict(aroon_th=50, mom_th=0.80, fac=0.6)),
        ('A50_M800_cap59', dict(aroon_th=50, mom_th=0.80, cap=True)),
        ('A40_M1000_fac06', dict(aroon_th=40, mom_th=1.00, fac=0.6)),
        ('A50_M1000_fac06', dict(aroon_th=50, mom_th=1.00, fac=0.6)),
        ('A40_M060_fac06', dict(aroon_th=40, mom_th=0.60, fac=0.6)),
    ]
    res = []
    for label, kw in cases:
        t0 = time.time()
        eq, tr = run_auto_inhibit(**kw)
        s = V.summary(eq, tr)
        row = {'label': label, **kw,
               'total_return_pct': float(s['total_return_pct']), 'win_rate_pct': float(s['win_rate_pct']),
               'annual_return_pct': float(s['annual_return_pct']), 'max_drawdown_pct': float(s['max_drawdown_pct']),
               'sharpe': float(s['sharpe']), 'total_trades': int(s['total_trades']), 'secs': int(time.time()-t0)}
        res.append(row)
        rel_t = row['total_return_pct'] - base['total_return_pct']
        rel_dd = row['max_drawdown_pct'] - base['max_drawdown_pct']
        ok = 'PASS' if (rel_t > 0 and rel_dd >= 0) else 'FAIL'
        print(f"{label}: {row['secs']}s 收益{row['total_return_pct']:+.1f}%(Δ{rel_t:+.1f}) 回撤{row['max_drawdown_pct']:+.2f}%(Δ{rel_dd:+.2f}) "
              f"夏普{row['sharpe']:.2f} 胜率{row['win_rate_pct']:.1f}% 交易{row['total_trades']} [{ok}]", flush=True)
    json.dump(res, open(BASE / 'aroon_sensitivity.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    pos = sum(1 for r in res if r['total_return_pct'] > base['total_return_pct'] and r['max_drawdown_pct'] >= base['max_drawdown_pct'])
    print(f"结论：{pos}/{len(res)} 组正向且无回撤恶化 → {'≥7/9 达标，可投产' if pos >= 7 else '未达投产门槛'}")
