# -*- coding: utf-8 -*-
"""
KHunter 三版本 × 低价过滤 全指标网格（2026-09-03 补跑，回应用户"结论只跑了标准版、回撤也没有"）
====================================================================
三版本（信号语义与 khunter_portfolio_20260903.py 一致）：
  A 标准版：熊市限定 + RSI<35 买 + OB=55 卖
  B 稳健版：A + 30% 绝对止损（close_prev < entry_px×0.70 → 次日开盘卖）
  C 激进版：熊市限定 + RSI<35 买 + OB=50 卖（更早止盈=激进）
低价过滤（disaster 网格 low3/low2 口径）：entry 日 o×(1+买成本) ≥ low 元 才入

每格输出三套口径：
  1. 交易级（与 disaster 表一致）：n/wr/med/mean/ann/sharpe/pf/hold/ex_b/ex_m + 分年
  2. 串行（每笔全仓接续，乐观上界）：mult/ann/mdd
  3. 资金池 v8 固定 N=5 仓等权 NAV（真实交易者回撤）：ann/mdd/sharpe/final/分年

输出：khunter_timing_out/khunter_three_ver_opt_20260903.csv
"""
import os, sys, time, json
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import khunter_all_strategies_backtest as K
import khunter_timing_backtest as T
import khunter_portfolio_v8_20260903 as V8   # 复用 build_nav/metrics（固定 N 仓等权）

T0 = time.time()
def log(msg):
    print(f"[{time.time()-T0:7.1f}s] {msg}", flush=True)

OUT_DIR = T.OUT_DIR
COST_BUY, COST_SELL = T.COST_BUY, T.COST_SELL
BACKTEST_START = K.BACKTEST_START
SPLIT = pd.Timestamp("2021-01-01")

# (name, ob, stop, low)  9 格 = 3 版本 × 3 低价档（0=不过滤）
CFGS = [
    ('A_x0', 55, 0.00, 0.0), ('A_x2', 55, 0.00, 2.0), ('A_x3', 55, 0.00, 3.0),
    ('B_x0', 55, 0.30, 0.0), ('B_x2', 55, 0.30, 2.0), ('B_x3', 55, 0.30, 3.0),
    ('C_x0', 50, 0.00, 0.0), ('C_x2', 50, 0.00, 2.0), ('C_x3', 50, 0.00, 3.0),
]

def full_stats(fr, ex_b, ex_m, holds):
    fr = np.asarray(fr, dtype=float)
    if len(fr) == 0:
        return None
    n = len(fr)
    wr = (fr > 0).mean() * 100
    med = np.median(fr) * 100
    mean = fr.mean() * 100
    std = fr.std()
    H = max(np.mean(holds), 1)
    sharpe = fr.mean() / std * np.sqrt(252 / H) if std > 0 else 0
    ann = ((1 + fr.mean()) ** (252 / H) - 1) * 100 if fr.mean() > -1 else -100.0
    wins = fr[fr > 0]; losses = fr[fr < 0]
    pf = (wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else (np.inf if len(wins) else 0.0)
    return {
        'n': int(n), 'wr': round(wr, 2), 'med': round(med, 3), 'mean': round(mean, 3),
        'ann_trade': round(ann, 2), 'sharpe_trade': round(sharpe, 3),
        'pf': round(pf, 2) if np.isfinite(pf) else 999.0, 'hold': round(H, 1),
        'ex_b': round(np.nanmean(ex_b) * 100, 3) if len(ex_b) else 0.0,
        'ex_m': round(np.nanmean(ex_m) * 100, 3) if len(ex_m) else 0.0,
    }

def serial_metrics(fr, dates):
    fr = np.asarray(fr, dtype=float)
    eq = 1.0; peak = 1.0; mdd = 0.0
    for r in fr:
        eq *= (1 + r); peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
    dates = pd.to_datetime(dates)
    span = (dates.max() - dates.min()).days
    ann = (eq ** (365.25 / span) - 1) * 100 if span > 0 and eq > 0 else (-100.0 if eq <= 0 else 0.0)
    return eq, ann, mdd * 100

def main():
    log("加载缓存 ...")
    cache = pd.read_pickle(K.CACHE)
    log(f"缓存 {len(cache)} 只")

    # 基准（等权/中位全市场，同 disaster 口径）
    all_ret = {}
    for code, df in cache.items():
        if df is None or len(df) < 30:
            continue
        d = df[['close']].copy()
        d.index.name = None
        d['date'] = d.index
        d = d.sort_values('date').reset_index(drop=True)
        d['ret'] = d['close'].pct_change()
        all_ret[code] = d[['date', 'ret']]
    bdf = pd.concat(all_ret.values(), ignore_index=True)
    bench = bdf.groupby('date')['ret'].mean()
    bench_cum = (1 + bench).cumprod()
    med_cum = (1 + bdf.groupby('date')['ret'].median()).cumprod()

    idx = pd.read_csv(r"D:\Documents\Workbuddy\股票基金\quant-weight-system\index_000300.csv")
    idx['date'] = pd.to_datetime(idx['date'])
    idx = idx.sort_values('date').reset_index(drop=True)
    for maw in (20, 60):
        idx[f'ma{maw}'] = idx['close'].rolling(maw, min_periods=1).mean()
    idx['is_bear'] = (idx['close'] < idx['ma60']).values
    st = {}
    for _, row in idx.iterrows():
        d = row['date']
        st[d] = 'bear' if row['is_bear'] else ('bull' if (row['close'] > idx.loc[idx['date'] == d, 'ma20'].values[0]) else 'weak')
    st_prev = {}
    prev = None
    for dt in sorted(st):
        st_prev[dt] = prev if prev is not None else 'bear'
        prev = st[dt]

    cells = {c: [] for c, *_ in CFGS}
    n_stock = 0
    for code, df in cache.items():
        if df is None or len(df) < 70:
            continue
        if code.startswith(("sh688", "sh689", "sz30")):
            continue
        d = df[['open', 'high', 'low', 'close', 'volume']].copy()
        d.index.name = None
        d['date'] = d.index
        d = d.sort_values('date').reset_index(drop=True)
        r = T.prep(d)
        n = len(d)
        opens = d['open'].values
        closes = d['close'].values
        dates = d['date'].values
        bcum = bench_cum.reindex(dates).values
        mcum = med_cum.reindex(dates).values
        st_arr = np.array([st_prev.get(pd.Timestamp(dt), 'bear') for dt in dates])
        is_bear_arr = np.array([s == 'bear' for s in st_arr])

        sig_any = np.zeros(n, dtype=bool)
        for name, fn in K.SIGNALS.items():
            try:
                sv = fn(r)
            except Exception:
                continue
            if not sv.any():
                continue
            sig_any |= sv.values
        cand = np.zeros(n, dtype=bool)
        cand[1:] = sig_any[:-1]
        cand &= dates >= BACKTEST_START

        rsi14 = r['rsi'].values
        rsi14_1 = np.concatenate([[np.nan], rsi14[:-1]])
        entry_ok_base = cand & np.nan_to_num(rsi14_1 < 35, nan=False) & is_bear_arr

        for cname, ob, stop, low in CFGS:
            sell_sig = np.nan_to_num(rsi14_1 > ob, nan=False)
            pos = False
            entry_px = 0.0
            entry_i = 0
            for i in range(1, n):
                o = opens[i]
                if o <= 0:
                    continue
                if pos:
                    do_sell = bool(sell_sig[i])
                    c_prev = closes[i - 1] if i - 1 >= 0 else np.nan
                    if not do_sell and stop > 0 and np.isfinite(c_prev):
                        do_sell = c_prev < entry_px * (1 - stop)
                    if do_sell:
                        ret = o * (1 - COST_SELL) / entry_px - 1
                        b0, b1 = bcum[entry_i], bcum[i]
                        m0, m1 = mcum[entry_i], mcum[i]
                        ex_b = ret - (b1 / b0 - 1) if (np.isfinite(b0) and np.isfinite(b1) and b0 > 0) else np.nan
                        ex_m = ret - (m1 / m0 - 1) if (np.isfinite(m0) and np.isfinite(m1) and m0 > 0) else np.nan
                        cells[cname].append({'code': code, 'entry_date': pd.Timestamp(dates[entry_i]),
                                             'entry_px': entry_px, 'exit_date': pd.Timestamp(dates[i]),
                                             'exit_px': o, 'ret': ret, 'hold': i - entry_i,
                                             'regime': st_arr[entry_i], 'ex_b': ex_b, 'ex_m': ex_m})
                        pos = False
                else:
                    if entry_ok_base[i]:
                        if low > 0 and o * (1 + COST_BUY) < low:
                            continue
                        entry_px = o * (1 + COST_BUY)
                        entry_i = i
                        pos = True
            if pos:
                ret = closes[n - 1] * (1 - COST_SELL) / entry_px - 1
                b0, b1 = bcum[entry_i], bcum[n - 1]
                m0, m1 = mcum[entry_i], mcum[n - 1]
                ex_b = ret - (b1 / b0 - 1) if (np.isfinite(b0) and np.isfinite(b1) and b0 > 0) else np.nan
                ex_m = ret - (m1 / m0 - 1) if (np.isfinite(m0) and np.isfinite(m1) and m0 > 0) else np.nan
                cells[cname].append({'code': code, 'entry_date': pd.Timestamp(dates[entry_i]),
                                     'entry_px': entry_px, 'exit_date': pd.Timestamp(dates[n - 1]),
                                     'exit_px': closes[n - 1], 'ret': ret, 'hold': n - 1 - entry_i,
                                     'regime': st_arr[entry_i], 'ex_b': ex_b, 'ex_m': ex_m})
        n_stock += 1
        if n_stock % 1000 == 0:
            log(f"  {n_stock} 只")

    log(f"扫描完成 {n_stock} 只，构建指标 ...")
    rows = []
    for cname, ob, stop, low in CFGS:
        t = cells[cname]
        if len(t) < 15:
            log(f"  {cname}: 交易太少({len(t)})跳过")
            continue
        # 落盘 trades 后回读为 tr（修复：pandas sort_values 默认 quicksort 不稳定，
        # 同日多仓 tie 顺序不确定 → v8 N 仓模型对行序敏感。文件路径双次排序收敛到
        # 与存量 khunter_portfolio_*_trades（规范 v8 口径）一致的 tie 序）
        _csv_path = os.path.join(OUT_DIR, f"khunter_threever_{cname}_trades_20260903.csv")
        pd.DataFrame(t).sort_values('entry_date').to_csv(_csv_path, index=False, encoding="utf-8-sig")
        tr = pd.read_csv(_csv_path, encoding="utf-8-sig")
        tr['entry_date'] = pd.to_datetime(tr['entry_date'])
        tr['exit_date'] = pd.to_datetime(tr['exit_date'])
        tr = tr.sort_values('entry_date').reset_index(drop=True)
        fr = np.array([x['ret'] for x in t])
        ex_b = np.array([x['ex_b'] for x in t])
        ex_m = np.array([x['ex_m'] for x in t])
        holds = np.array([x['hold'] for x in t])
        # 串行按 entry_date 时间序（跨股乱序会扭曲 peak/mdd）
        t_ord = sorted(t, key=lambda x: x['entry_date'])
        eq, s_ann, s_mdd = serial_metrics([x['ret'] for x in t_ord], [x['entry_date'] for x in t_ord])
        # 资金池 v8 N=5
        nav_s, stats = V8.build_nav(tr, cache, 5)
        if nav_s is not None:
            p_ann, p_mdd, p_sharpe, p_yearly = V8.metrics(nav_s)
            p_final = float(nav_s.iloc[-1])
        else:
            p_ann = p_mdd = p_sharpe = p_final = float('nan'); p_yearly = {}
        # 灾年 2023/2024 交易均值
        y2023 = round(float(np.mean([x['ret'] for x in t if x['entry_date'].year == 2023])) * 100, 2) if sum(1 for x in t if x['entry_date'].year == 2023) >= 5 else None
        y2024 = round(float(np.mean([x['ret'] for x in t if x['entry_date'].year == 2024])) * 100, 2) if sum(1 for x in t if x['entry_date'].year == 2024) >= 5 else None
        ver = cname.split('_')[0]
        s = full_stats(fr, ex_b, ex_m, holds)
        rows.append({
            'cfg': cname, 'ver': ver, 'ob': ob, 'stop': stop, 'low': low,
            **s, 'serial_mult': round(eq, 3), 'serial_ann': round(s_ann, 2), 'serial_mdd': round(s_mdd, 2),
            'pool_ann': round(p_ann, 2) if np.isfinite(p_ann) else None,
            'pool_mdd': round(p_mdd, 2) if np.isfinite(p_mdd) else None,
            'pool_sharpe': round(p_sharpe, 3) if np.isfinite(p_sharpe) else None,
            'pool_final': round(p_final, 3) if np.isfinite(p_final) else None,
            'pool_skipped': stats['skipped'] if stats else 0,
            'y2023': y2023, 'y2024': y2024,
            'pool_yearly': json.dumps({str(k): v for k, v in p_yearly.items()}),
        })
        log(f"  {cname}: n={s['n']} trade_ann={s['ann_trade']}% sharpe={s['sharpe_trade']} "
            f"pool(N5)ann={p_ann:.2f}% mdd={p_mdd:.2f}% sharpe={p_sharpe:.3f} | 串行ann={s_ann:.2f}% mdd={s_mdd:.2f}%")
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(OUT_DIR, "khunter_three_ver_opt_20260903.csv"), index=False, encoding="utf-8-sig")
    print("\n===== 三版本 × 低价过滤 全指标 =====")
    cols = ['cfg', 'n', 'wr', 'med', 'mean', 'ann_trade', 'sharpe_trade', 'pf', 'hold',
            'ex_b', 'serial_ann', 'serial_mdd', 'pool_ann', 'pool_mdd', 'pool_sharpe', 'pool_final',
            'y2023', 'y2024']
    print(out[cols].to_string())
    log("完成")

if __name__ == "__main__":
    main()
