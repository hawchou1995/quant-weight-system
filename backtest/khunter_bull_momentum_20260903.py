# -*- coding: utf-8 -*-
"""
KHunter 牛市方向5：追涨/突破/动量（2026-09-03）
====================================================================
用户批评：4 轮扫描全是「买跌」逻辑（超卖/回调/RS 回调），牛市赚钱的正确姿势是
「追涨/突破/动量」——梁文锋/幻方在牛市赚的是动量+突破的钱，不是抄底的钱。

本方向 = 与「买跌」本质不同的入场逻辑（T-1 收盘确认 → T 开盘买入）：
  入场（仅强牛 hs300>MA20）：
    E1 20日新高突破:   c1 > max(high[T-21..T-2])
    E2 放量突破:       E1 且 vol_1 ≥ 1.5×MA5(vol)
    E3 唐奇安55:       c1 > max(high[T-56..T-2])
    E4 动量20≥10%:     ret20_1 ≥ 10%
    E5 动量20≥20%:     ret20_1 ≥ 20%
    E6 多头排列+新高:  c1>MA20_1>MA60_1 且 E1
    E7 多头排列+动量:  c1>MA20_1>MA60_1 且 ret20_1 ≥ 10%
  出场：
    X1 RSI_T-1>75（KHunter 主出场）
    X2 RSI>75 或 止盈+8%
    X3 RSI>75 或 止盈+8% 或 止损-7%
    X4 收盘跌破 MA5
  叠加：kh=要求 KHunter 15 信号命中（与生产战法同源）/ pure=纯突破不要求
口径：成本 0.575%×2、低过滤 ≥3 元、主板（剔 688/689/30）、2016-06-01 起
输出：khunter_timing_out/khunter_bull_momentum_20260903.csv
"""
import os, sys, time
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import khunter_all_strategies_backtest as K
import khunter_timing_backtest as T

T0 = time.time()
def log(msg):
    print(f"[{time.time()-T0:7.1f}s] {msg}", flush=True)

OUT_DIR = T.OUT_DIR
COST_BUY, COST_SELL = T.COST_BUY, T.COST_SELL
BACKTEST_START = K.BACKTEST_START
LOW3 = 3.0

# (name, entry_type, exit_type, need_kh)
CFGS = []
ENTRIES = [
    ('E1_新高20',   'new20'),
    ('E2_放量突破', 'vol_break'),
    ('E3_唐奇安55', 'don55'),
    ('E4_动量10',   'mom10'),
    ('E5_动量20',   'mom20'),
    ('E6_多头新高', 'trend_new20'),
    ('E7_多头动量', 'trend_mom10'),
]
EXITS = [
    ('X1_rsi75', 'rsi75'),
    ('X2_tp8',   'tp8'),
    ('X3_tp8sl7','tp8sl7'),
    ('X4_ma5',   'ma5'),
]
for ename, etype in ENTRIES:
    for xname, xtype in EXITS:
        for tag, need_kh in [('kh', True), ('pure', False)]:
            CFGS.append((f'{ename}_{xname}_{tag}', etype, xtype, need_kh))

def reg_stats(tr):
    if len(tr) < 8:
        return None
    fr = np.array([x[1] for x in tr]); ex_b = np.array([x[2] for x in tr]); ex_m = np.array([x[3] for x in tr])
    holds = np.array([x[4] for x in tr])
    n = len(fr); wr = (fr > 0).mean() * 100
    med = np.median(fr) * 100; mean = fr.mean() * 100
    std = fr.std(); H = max(np.mean(holds), 1)
    sharpe = fr.mean() / std * np.sqrt(252 / H) if std > 0 else 0
    ann = ((1 + fr.mean()) ** (252 / H) - 1) * 100 if fr.mean() > -1 else -100.0
    wins = fr[fr > 0]; losses = fr[fr < 0]
    pf = (wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else (np.inf if len(wins) else 0.0)
    eq = np.cumprod(1 + fr)
    mdd = float((1 - eq / np.maximum.accumulate(eq)).max() * 100) if n >= 10 else 0.0
    return {'n': int(n), 'wr': round(wr, 2), 'med': round(med, 3), 'mean': round(mean, 3),
            'ann': round(ann, 2), 'sharpe': round(sharpe, 3),
            'pf': round(pf, 2) if np.isfinite(pf) else 999.0, 'hold': round(H, 1),
            'ex_b': round(np.nanmean(ex_b) * 100, 3) if len(ex_b) else 0.0,
            'ex_m': round(np.nanmean(ex_m) * 100, 3) if len(ex_m) else 0.0,
            'max_dd': round(mdd, 2)}

def main():
    log("加载缓存 ...")
    cache = pd.read_pickle(K.CACHE)
    log(f"缓存 {len(cache)} 只")

    all_ret = {}
    for code, df in cache.items():
        if df is None or len(df) < 30:
            continue
        d = df[['close']].copy(); d.index.name = None
        d['date'] = d.index; d = d.sort_values('date').reset_index(drop=True)
        d['ret'] = d['close'].pct_change()
        all_ret[code] = d[['date', 'ret']]
    bdf = pd.concat(all_ret.values(), ignore_index=True)
    bench = bdf.groupby('date')['ret'].mean(); med_cum = (1 + bdf.groupby('date')['ret'].median()).cumprod()
    bench_cum = (1 + bench).cumprod()

    idx = pd.read_csv(r"D:\Documents\Workbuddy\股票基金\quant-weight-system\index_000300.csv")
    idx['date'] = pd.to_datetime(idx['date']); idx = idx.sort_values('date').reset_index(drop=True)
    idx['ma20'] = idx['close'].rolling(20, min_periods=1).mean()
    idx['ma60'] = idx['close'].rolling(60, min_periods=1).mean()
    st = {}
    for _, row in idx.iterrows():
        d = row['date']
        st[d] = 'bear' if row['close'] < row['ma60'] else ('strong' if row['close'] > row['ma20'] else 'weak')
    st_prev = {}; prev = None
    for dt in sorted(st):
        st_prev[dt] = prev if prev is not None else 'bear'
        prev = st[dt]

    cells = {c[0]: [] for c in CFGS}
    n_stock = 0
    for code, df in cache.items():
        if df is None or len(df) < 70:
            continue
        if code.startswith(("sh688", "sh689", "sz30")):
            continue
        d = df[['open', 'high', 'low', 'close', 'volume']].copy()
        d.index.name = None; d['date'] = d.index
        d = d.sort_values('date').reset_index(drop=True)
        r = T.prep(d)
        n = len(d)
        opens = d['open'].values; closes = d['close'].values; highs = d['high'].values
        vols = d['volume'].values
        dates = d['date'].values
        c1 = np.concatenate([[np.nan], closes[:-1]])
        ma20 = pd.Series(closes).rolling(20, min_periods=1).mean().values
        ma60 = pd.Series(closes).rolling(60, min_periods=1).mean().values
        ma5 = pd.Series(closes).rolling(5, min_periods=1).mean().values
        ma20_1 = np.concatenate([[np.nan], ma20[:-1]])
        ma60_1 = np.concatenate([[np.nan], ma60[:-1]])
        ma5_1 = np.concatenate([[np.nan], ma5[:-1]])
        ret20 = pd.Series(closes).pct_change(20).values
        ret20_1 = np.concatenate([[np.nan], ret20[:-1]])
        hh20 = pd.Series(highs).rolling(20, min_periods=1).max().values
        # ⚠ 新高必须排除 T-1 自身 high：前置 2 个 nan 使 hh20_1[i]=hh20[i-2]=max(high[i-21..i-2])
        #   （前置 1 个 nan 时 hh20_1[i]=hh20[i-1] 仍含 T-1 high → close>max(high[含当日]) 数学不可满足 → 零触发）
        hh20_1 = np.concatenate([[np.nan, np.nan], hh20[:-2]])
        hh55 = pd.Series(highs).rolling(55, min_periods=1).max().values
        hh55_1 = np.concatenate([[np.nan, np.nan], hh55[:-2]])
        vol_ma5 = pd.Series(vols).rolling(5, min_periods=1).mean().values
        vol_ma5_1 = np.concatenate([[np.nan], vol_ma5[:-1]])
        vol_1 = np.concatenate([[np.nan], vols[:-1]])
        bcum = bench_cum.reindex(dates).values; mcum = med_cum.reindex(dates).values
        st_arr = np.array([st_prev.get(pd.Timestamp(dt), 'bear') for dt in dates])
        is_strong_arr = st_arr == 'strong'

        hits = np.zeros(n, dtype=int)
        for name, fn in K.SIGNALS.items():
            try:
                sv = fn(r)
            except Exception:
                continue
            if sv is None:
                continue
            v = np.asarray(sv.values if hasattr(sv, 'values') else sv)
            if len(v) != n:
                continue
            hits += np.nan_to_num(v, nan=False).astype(int)
        sig_any = hits >= 1
        kh_cand = np.zeros(n, dtype=bool)
        kh_cand[1:] = sig_any[:-1]
        kh_cand &= dates >= BACKTEST_START
        rsi14_1 = np.concatenate([[np.nan], r['rsi'].values[:-1]])
        sell_hi = np.nan_to_num(rsi14_1 > 75, nan=False)

        # 入场条件（T-1 视角）
        with np.errstate(invalid='ignore', divide='ignore'):
            new20 = np.nan_to_num(c1 > hh20_1, nan=False)
            don55 = np.nan_to_num(c1 > hh55_1, nan=False)
            vol_break = new20 & np.nan_to_num(vol_1 >= 1.5 * vol_ma5_1, nan=False)
            mom10 = np.nan_to_num(ret20_1 >= 0.10, nan=False)
            mom20 = np.nan_to_num(ret20_1 >= 0.20, nan=False)
            trend = (np.nan_to_num(c1 > ma20_1, nan=False)
                     & np.nan_to_num(ma20_1 > ma60_1, nan=False))
            trend_new20 = trend & new20
            trend_mom10 = trend & mom10
        entry_map = {
            'new20': new20, 'vol_break': vol_break, 'don55': don55,
            'mom10': mom10, 'mom20': mom20, 'trend_new20': trend_new20,
            'trend_mom10': trend_mom10,
        }
        # 出场条件（T-1 视角）
        ma5_break = np.nan_to_num(c1 < ma5_1, nan=False)

        for cname, etype, xtype, need_kh in CFGS:
            entry_mask = entry_map[etype] & is_strong_arr & (dates >= BACKTEST_START)
            if need_kh:
                entry_mask = entry_mask & kh_cand
            pos = False; entry_px = 0.0; entry_i = 0
            for i in range(1, n):
                o = opens[i]
                if o <= 0:
                    continue
                if pos:
                    do_sell = bool(sell_hi[i])
                    if not do_sell and xtype in ('tp8', 'tp8sl7') and np.isfinite(o):
                        do_sell = o * (1 - COST_SELL) / entry_px - 1 >= 0.08
                    if not do_sell and xtype == 'tp8sl7' and np.isfinite(o):
                        do_sell = o * (1 - COST_SELL) / entry_px - 1 <= -0.07
                    if not do_sell and xtype == 'ma5':
                        do_sell = bool(ma5_break[i])
                    if do_sell:
                        ret = o * (1 - COST_SELL) / entry_px - 1
                        b0, b1 = bcum[entry_i], bcum[i]; m0, m1 = mcum[entry_i], mcum[i]
                        ex_b = ret - (b1 / b0 - 1) if (np.isfinite(b0) and np.isfinite(b1) and b0 > 0) else np.nan
                        ex_m = ret - (m1 / m0 - 1) if (np.isfinite(m0) and np.isfinite(m1) and m0 > 0) else np.nan
                        cells[cname].append((dates[entry_i], ret, ex_b, ex_m, i - entry_i, st_arr[entry_i], code))
                        pos = False
                else:
                    if entry_mask[i]:
                        if o * (1 + COST_BUY) < LOW3:
                            continue
                        entry_px = o * (1 + COST_BUY); entry_i = i
                        pos = True
            if pos:
                ret = closes[n - 1] * (1 - COST_SELL) / entry_px - 1
                b0, b1 = bcum[entry_i], bcum[n - 1]; m0, m1 = mcum[entry_i], mcum[n - 1]
                ex_b = ret - (b1 / b0 - 1) if (np.isfinite(b0) and np.isfinite(b1) and b0 > 0) else np.nan
                ex_m = ret - (m1 / m0 - 1) if (np.isfinite(m0) and np.isfinite(m1) and m0 > 0) else np.nan
                cells[cname].append((dates[entry_i], ret, ex_b, ex_m, n - 1 - entry_i, st_arr[entry_i], code))
        n_stock += 1
        if n_stock % 1000 == 0:
            log(f"  {n_stock} 只")
    log(f"扫描完成 {n_stock} 只")

    rows = []
    for cname, _, _, _ in CFGS:
        t = cells[cname]
        s = reg_stats(t)
        if s is None:
            print(f"{cname:28s} n<8 跳过")
            continue
        yearly = {}
        for yr in range(2016, 2027):
            yt = [x for x in t if pd.Timestamp(x[0]).year == yr]
            if len(yt) >= 5:
                yearly[yr] = round(np.mean([x[1] for x in yt]) * 100, 2)
        passed = (s['wr'] >= 40 and s['med'] > 0 and s['mean'] > 0 and (s['ex_b'] > 0 or s['ex_m'] > 0))
        rows.append({'cfg': cname, **s, 'gate': int(passed), 'yearly': str(yearly)})
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(OUT_DIR, "khunter_bull_momentum_20260903.csv"), index=False, encoding="utf-8-sig")
    print("\n===== 牛市方向5：追涨/突破/动量（仅强牛 hs300>MA20）=====")
    print(out[['cfg', 'n', 'wr', 'med', 'mean', 'ann', 'sharpe', 'pf', 'hold', 'ex_b', 'ex_m', 'max_dd', 'gate', 'yearly']].to_string())
    log("完成")

if __name__ == "__main__":
    main()
