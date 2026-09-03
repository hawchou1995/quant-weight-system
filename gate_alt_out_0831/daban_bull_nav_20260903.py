# -*- coding: utf-8 -*-
"""
打板融合 · 牛市过闸 10 组配置净值重跑（2026-09-03）
====================================================
用户问：牛市战法过闸了？胜率、年化、回撤、夏普多少？
原 daban_fusion_0901.py 只有 per-trade 统计（event_stats），无净值序列。
本脚本复用其数据加载/候选构建/出场机制/组合构建（每日≤5+板块去重+情绪门控），
只跑 10 个牛市过闸配置（gate.bull_all=True），从 bull_port 信号构建
「日频等权再平衡」组合净值，输出：年化 / 最大回撤 / 夏普 / 胜率 / 均值 / 中位 / PF。

NAV 口径：
  - 每笔信号：entry 日 open 买入（付买成本）→ 出场日按出场价卖出（付卖成本）
  - 持仓期间逐日 mark-to-market（close 序列），组合日收益 = 当日所有持仓的日收益均值
  - 无持仓日 = 现金（0 收益）；净值区间 = 首笔牛市入场日 ~ 末笔出场日
  - 基准 = hs300 同期买入持有
输出：gate_alt_out_0831/daban_bull_nav_20260903.csv（指标表）
      gate_alt_out_0831/daban_bull_nav_20260903.json（净值序列+交易明细）
"""
import pandas as pd
import numpy as np
import json, os, glob, time, sys

sys.path.insert(0, r"D:/Documents/Workbuddy/股票基金/打板系统v1回测_20260827")
from backtest_daban_v1 import (compute_features, is_pool_code, is_st_name, load_names,
                               load_industry, load_hs300, COST_BUY, COST_SELL,
                               START, END, DATA_DIR)

PRE = 10
POST = 8
OUT = r"D:/Documents/Workbuddy/股票基金/quant-weight-system/gate_alt_out_0831"

# ============ 牛市过闸 10 组（来自 daban_fusion_0901.json gate.bull_all=True） ============
BULL_CFGS = [
    # (name, glo, ghi, mask, mech, tp, sl, time_stop, max_hold)
    ('G2_低开-7~-3.5%_M3低位+空间_X1_tp8t2',   -0.07, -0.035, ['F2_low', 'F3_room'], 'tp_t2', 0.08, None, 2, 2),
    ('G2_低开-7~-3.5%_M8一进二量能_X1_tp8t2',  -0.07, -0.035, ['F2_low', 'F5_vol'],  'tp_t2', 0.08, None, 2, 2),
    ('G2_低开-7~-3.5%_M9低位+空间+封板_X1_tp8t2', -0.07, -0.035, ['F2_low', 'F3_room', 'F4_seal'], 'tp_t2', 0.08, None, 2, 2),
    ('G3_低开-3.5~-2%_M3低位+空间_X1_tp8t2',   -0.035, -0.02, ['F2_low', 'F3_room'], 'tp_t2', 0.08, None, 2, 2),
    ('G3_低开-3.5~-2%_M3低位+空间_X3_tp5sl7',  -0.035, -0.02, ['F2_low', 'F3_room'], 'tp_sl', 0.05, 0.07, 3, 5),
    ('G3_低开-3.5~-2%_M9低位+空间+封板_X1_tp8t2', -0.035, -0.02, ['F2_low', 'F3_room', 'F4_seal'], 'tp_t2', 0.08, None, 2, 2),
    ('G3_低开-3.5~-2%_M9低位+空间+封板_X3_tp5sl7', -0.035, -0.02, ['F2_low', 'F3_room', 'F4_seal'], 'tp_sl', 0.05, 0.07, 3, 5),
    ('G6_中高开5~7%_M6低位+换手+空间_X1_tp8t2', 0.05, 0.07, ['F2_low', 'F1_turn', 'F3_room'], 'tp_t2', 0.08, None, 2, 2),
    ('G6_中高开5~7%_M7全因子_X1_tp8t2',        0.05, 0.07, ['F2_low', 'F1_turn', 'F3_room', 'F4_seal'], 'tp_t2', 0.08, None, 2, 2),
    ('G6_中高开5~7%_M7全因子_X5_t1',           0.05, 0.07, ['F2_low', 'F1_turn', 'F3_room', 'F4_seal'], 't1_close', None, None, 1, 1),
]

FACTOR_DEFS = {
    'F1_turn': lambda c: 1.5 <= c['turn_ratio'] <= 4.0,
    'F2_low':  lambda c: c['rel_pos'] is not None and c['rel_pos'] < 0.5,
    'F3_room': lambda c: c['dist_high'] >= 0.2,
    'F4_seal': lambda c: not c['is_zha_prev'],
    'F5_vol':  lambda c: c['vol_ratio'] >= 0.3,
}

def build_regime(hs300_close):
    s = hs300_close.sort_index()
    ma20 = s.rolling(20).mean()
    reg = {}
    for d in s.index:
        if np.isnan(ma20.get(d, np.nan)):
            reg[d] = 'bear'
        else:
            reg[d] = 'bull' if s[d] > ma20[d] else 'bear'
    return reg

def apply_exit_mech(ctx, entry_px, mech, tp=None, sl=None, time_stop=3, max_hold=5):
    closes = ctx['close']; highs = ctx['high']; n_ctx = len(closes)
    if n_ctx < 2:
        return None
    if mech == 't1_close':
        for T in range(1, min(3, n_ctx)):
            if ctx['is_zt'][T]:
                continue
            return T, closes[T], 'ts'
        T = min(2, n_ctx - 1)
        return T, closes[T], 'force'
    if mech == 't2_close':
        for T in range(2, min(4, n_ctx)):
            if ctx['is_zt'][T]:
                continue
            return T, closes[T], 'ts'
        T = min(3, n_ctx - 1)
        return T, closes[T], 'force'
    if mech == 'ma5':
        pre = ctx.get('pre_close', [])
        ma5 = []
        for t in range(n_ctx):
            if t >= 4:
                ma5.append(np.mean(closes[t-4:t+1]))
            else:
                need = 4 - t
                if len(pre) >= need:
                    window = pre[-need:] + closes[:t+1]
                    ma5.append(np.mean(window))
                else:
                    ma5.append(np.nan)
        for T in range(1, min(max_hold + 1, n_ctx)):
            if ctx['is_zt'][T]:
                continue
            if ma5[T] == ma5[T] and closes[T] < ma5[T]:
                return T, closes[T], 'ts'
        T = min(max_hold, n_ctx - 1)
        return T, closes[T], 'force'
    if mech in ('tp_t1', 'tp_t2'):
        tp_px = entry_px * (1 + tp) if tp else None
        last = 1 if mech == 'tp_t1' else 2
        for T in range(1, last + 1):
            if T >= n_ctx:
                break
            if ctx['is_zt'][T]:
                continue
            if tp_px is not None and highs[T] >= tp_px:
                return T, tp_px, 'tp'
            return T, closes[T], 'ts'
        T = min(last, n_ctx - 1)
        return T, closes[T], 'force'
    tp_px = entry_px * (1 + tp) if tp else None
    sl_px = entry_px * (1 - sl) if sl else None
    for T in range(1, min(max_hold + 1, n_ctx)):
        if ctx['is_zt'][T]:
            continue
        if tp_px is not None and highs[T] >= tp_px:
            return T, tp_px, 'tp'
        if sl_px is not None and closes[T] < sl_px:
            return T, closes[T], 'sl'
        if T >= time_stop:
            return T, closes[T], 'ts'
    T = min(max_hold, n_ctx - 1)
    return T, closes[T], 'force'

def _mk_cand(df, feat, T, code, nm, ind, gap, rel_pos, amt, vol_ratio, dist_high, turn_ratio, is_zha_prev):
    e0 = max(0, T - PRE)
    e1 = min(T + POST + 1, len(df))
    pre_close = df['close'].values[e0:T].tolist()
    return {
        'code': code, 'name': nm, 'ind': ind,
        'entry_bar': T, 'entry_px': float(df['open'].values[T]),
        'buy_date': df['date'].values[T], 'gap': float(gap),
        'rel_pos': float(rel_pos) if rel_pos == rel_pos else None,
        'amt': float(amt), 'vol_ratio': float(vol_ratio),
        'dist_high': float(dist_high), 'turn_ratio': float(turn_ratio),
        'is_zha_prev': bool(is_zha_prev),
        'ctx': {
            'open': df['open'].values[T:e1].tolist(),
            'high': df['high'].values[T:e1].tolist(),
            'low': df['low'].values[T:e1].tolist(),
            'close': df['close'].values[T:e1].tolist(),
            'prev_close': feat['prev_close'][T:e1].tolist(),
            'is_zt': feat['is_zt'][T:e1].tolist(),
            'dates': df['date'].values[T:e1].tolist(),
            'pre_close': pre_close,
        }
    }

def mask_filter(c, mask):
    for f in mask:
        if not FACTOR_DEFS[f](c):
            return False
    return True

def build_nav(sigs, hs300_close):
    """从信号列表构建日频等权组合净值。返回 (nav_df, metrics)"""
    if not sigs:
        return None, None
    # 每笔信号的逐日收益路径
    daily = {}  # date -> list of returns
    for s in sigs:
        ctx = s['ctx']; closes = ctx['close']; dates = ctx['dates']
        eb = s['exit_rel']
        entry_px = s['entry_px']; exit_px = s['exit_px']
        if eb < 1 or len(closes) <= eb:
            continue
        # day 0: 买入日（open 成交 + 买成本），mark-to-market 到当日 close
        r0 = closes[0] / entry_px * (1 - COST_BUY) - 1
        daily.setdefault(dates[0], []).append(r0)
        for k in range(1, eb):
            if closes[k-1] > 0:
                daily.setdefault(dates[k], []).append(closes[k] / closes[k-1] - 1)
        # 出场日：按出场价卖出（付卖成本）
        if eb >= 1 and closes[eb-1] > 0:
            re = exit_px / closes[eb-1] * (1 - COST_SELL) - 1
            daily.setdefault(dates[eb], []).append(re)
    if not daily:
        return None, None
    dts = sorted(daily)
    port_ret = np.array([np.mean(daily[d]) for d in dts])
    nav = np.cumprod(1 + port_ret)
    # 基准：同期 hs300 买入持有
    b0 = hs300_close.loc[dts[0]]; b1 = hs300_close.loc[dts[-1]]
    bench_ret = b1 / b0 - 1
    # 指标
    n_days = len(dts)
    years = n_days / 252
    ann = nav[-1] ** (1 / years) - 1 if years > 0 and nav[-1] > 0 else -1.0
    mdd = float((1 - nav / np.maximum.accumulate(nav)).max())
    sharpe = port_ret.mean() / port_ret.std() * np.sqrt(252) if port_ret.std() > 0 else 0.0
    return {
        'dates': dts, 'nav': nav.tolist(), 'daily_ret': port_ret.tolist(),
        'n_days': n_days, 'years': round(years, 2),
        'ann': float(ann), 'max_dd': float(mdd), 'sharpe': float(sharpe),
        'bench_ret': float(bench_ret), 'nav_end': float(nav[-1]),
        'excess_ann': float(ann - bench_ret),
    }

def main():
    t0 = time.time()
    names = load_names()
    ind_map = load_industry()
    hs300 = load_hs300()
    regime = build_regime(hs300)
    files = sorted(glob.glob(os.path.join(DATA_DIR, '*.csv')))
    pool = [f for f in files if is_pool_code(os.path.basename(f)[:-4])]
    pool2 = [f for f in pool if not is_st_name(names.get(os.path.basename(f)[:-4], ''))]
    print(f'pool: {len(pool2)}', flush=True)

    # ============ pass 1: 候选信号 ============
    print('pass1: 读数据 + 缓存候选信号...', flush=True)
    cands = []
    for fi, f in enumerate(pool2):
        code = os.path.basename(f)[:-4]
        try:
            df = pd.read_csv(f, usecols=['date', 'open', 'high', 'low', 'close', 'volume'])
        except Exception:
            continue
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['open', 'high', 'low', 'close']).reset_index(drop=True)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        df = df[(df['date'] >= START) & (df['date'] <= END)].reset_index(drop=True)
        if len(df) < 70:
            continue
        feat = compute_features(df, code)
        nm = names.get(code, code)
        ind = ind_map.get(code, '其他')
        open_ = df['open'].values; close = df['close'].values; vol = df['volume'].values
        prev_close = feat['prev_close']; is_zt = feat['is_zt']
        is_yz = feat['is_yz']; is_zha = feat['is_zha']
        rel_pos = feat['rel_pos']; amt = feat['amt']
        n = len(df)
        vol_ma5 = pd.Series(vol).rolling(5, min_periods=1).mean().values
        hi60 = pd.Series(close).rolling(60, min_periods=30).max().values
        for T in range(2, n):
            if vol[T] <= 0 or open_[T] <= 0 or prev_close[T] <= 0:
                continue
            if is_yz[T]:
                continue
            gap = open_[T] / prev_close[T] - 1
            if not (is_zt[T-1] and not is_zt[T-2] and not is_yz[T-1]):
                continue
            if not (-0.09 <= gap <= 0.11):
                continue
            rp = rel_pos[T-1]
            dh = (hi60[T-1] - close[T-1]) / hi60[T-1] if hi60[T-1] > 0 else 0.0
            tr = vol[T-1] / vol_ma5[T-1] if vol_ma5[T-1] > 0 else 1.0
            vr = vol[T] / vol[T-1] if vol[T-1] > 0 else 0.0
            cands.append(_mk_cand(df, feat, T, code, nm, ind, gap, rp,
                                  amt[T-1], vr, dh, tr, is_zha[T-1]))
        if (fi + 1) % 1000 == 0:
            print(f'  {fi+1}/{len(pool2)}, cands {len(cands)}', flush=True)
    print(f'  cands: {len(cands)}', flush=True)

    # ============ pass 2: 情绪周期 ============
    print('pass2: 情绪周期...', flush=True)
    senti = {}
    for fi, f in enumerate(pool2):
        code = os.path.basename(f)[:-4]
        try:
            df = pd.read_csv(f, usecols=['date', 'open', 'high', 'low', 'close', 'volume'])
        except Exception:
            continue
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['open', 'high', 'low', 'close']).reset_index(drop=True)
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        df = df[(df['date'] >= START) & (df['date'] <= END)].reset_index(drop=True)
        if len(df) < 60:
            continue
        feat = compute_features(df, code)
        for i in range(1, len(df)):
            d = df['date'].values[i]
            if feat['is_zt'][i]:
                s = senti.setdefault(d, {'zt': 0, 'lb': 0, 'zha': 0})
                s['zt'] += 1
                s['lb'] = max(s['lb'], int(feat['boards'][i]))
            elif feat['is_zha'][i]:
                s = senti.setdefault(d, {'zt': 0, 'lb': 0, 'zha': 0})
                s['zha'] += 1
    for d, s in senti.items():
        tot = s['zt'] + s['zha']
        s['zpl'] = s['zha'] / tot if tot > 0 else 0
    print(f'  senti days: {len(senti)}', flush=True)

    # ============ 跑 10 个牛市配置 ============
    strat_prio = {'sb': 0}
    results = {}
    for cname, glo, ghi, mask, mech, tp, sl, ts, mh in BULL_CFGS:
        t1 = time.time()
        sigs = []
        for c in cands:
            if not (glo <= c['gap'] <= ghi):
                continue
            if not mask_filter(c, mask):
                continue
            ex = apply_exit_mech(c['ctx'], c['entry_px'], mech, tp, sl, ts, mh)
            if ex is None:
                continue
            eb, spx, reason = ex
            raw_ret = spx / c['entry_px'] - 1
            net_ret = (1 + raw_ret) * (1 - COST_BUY) * (1 - COST_SELL) - 1
            sigs.append({'code': c['code'], 'name': c['name'], 'ind': c['ind'], 'strat': 'sb',
                         'buy_date': c['buy_date'], 'sell_date': c['ctx']['dates'][eb],
                         'raw_ret': raw_ret, 'net_ret': net_ret, 'hold_days': int(eb),
                         'exit_reason': reason, 'entry_px': c['entry_px'], 'exit_px': spx,
                         'exit_rel': eb, 'ctx': c['ctx'], 'gap': c['gap']})
        # 组合构建（每日≤5 + 板块去重 + 情绪门控）—— 与原脚本一致
        by_day = {}
        for s in sigs:
            by_day.setdefault(s['buy_date'], []).append(s)
        port_sigs = []
        for d, ds in by_day.items():
            sent = senti.get(d, {'zt': 99, 'lb': 9, 'zpl': 0})
            gate_bad = (sent['zt'] < 20) or (sent['lb'] < 2) or (sent['zpl'] > 0.5)
            cap = 2 if gate_bad else 5
            ds.sort(key=lambda s: (strat_prio.get(s['strat'], 9), s['gap']))
            seen_ind = set()
            picked = []
            for s in ds:
                if s['ind'] in seen_ind:
                    continue
                seen_ind.add(s['ind'])
                picked.append(s)
                if len(picked) >= cap:
                    break
            port_sigs.extend(picked)
        bull_port = [s for s in port_sigs if regime.get(s['buy_date'], 'bear') == 'bull']
        bull_all = [s for s in sigs if regime.get(s['buy_date'], 'bear') == 'bull']
        # 净值（组合口径）
        nav_info = build_nav(bull_port, hs300)
        # 事件统计（对照原 JSON）
        def estats(sl):
            if not sl:
                return {'n': 0}
            r = np.array([s['net_ret'] for s in sl])
            bench = []
            for s in sl:
                try:
                    b0, b1 = hs300.loc[s['buy_date']], hs300.loc[s['sell_date']]
                    bench.append(b1 / b0 - 1)
                except KeyError:
                    bench.append(np.nan)
            bench = np.array(bench)
            wins = r[r > 0]; losses = r[r < 0]
            pf = (wins.mean() / abs(losses.mean())) if len(losses) > 0 and losses.mean() != 0 else np.inf
            return {'n': int(len(r)), 'mean': float(r.mean()), 'median': float(np.median(r)),
                    'win_rate': float((r > 0).mean()),
                    'pl_ratio': float(pf) if np.isfinite(pf) else None,
                    'excess': float(r.mean() - np.nanmean(bench)) if len(bench) else None,
                    'avg_hold': float(np.mean([s['hold_days'] for s in sl]))}
        st_all = estats(bull_all)
        st_port = estats(bull_port)
        results[cname] = {
            'event_all': st_all, 'event_port': st_port,
            'nav': nav_info,
            'n_bull_all': len(bull_all), 'n_bull_port': len(bull_port),
        }
        if nav_info:
            print(f"[{cname}] 牛port n={len(bull_port)} wr={st_port['win_rate']*100:.1f}% "
                  f"mean={st_port['mean']*100:.2f}% | 年化={nav_info['ann']*100:.1f}% "
                  f"回撤={nav_info['max_dd']*100:.1f}% 夏普={nav_info['sharpe']:.2f} "
                  f"基准={nav_info['bench_ret']*100:.1f}% ({time.time()-t1:.0f}s)", flush=True)
        else:
            print(f"[{cname}] 无净值（牛port 空）", flush=True)

    # ============ 汇总落盘 ============
    rows = []
    for cname, r in results.items():
        st = r['event_port']; nv = r['nav']
        rows.append({
            'cfg': cname,
            'n': st['n'], 'wr': round(st['win_rate'] * 100, 1),
            'mean': round(st['mean'] * 100, 2), 'med': round(st['median'] * 100, 2),
            'excess': round(st['excess'] * 100, 2) if st.get('excess') is not None else None,
            'pf': round(st['pl_ratio'], 2) if st.get('pl_ratio') is not None else None,
            'avg_hold': round(st['avg_hold'], 1) if st.get('avg_hold') is not None else None,
            'ann': round(nv['ann'] * 100, 2) if nv else None,
            'max_dd': round(nv['max_dd'] * 100, 2) if nv else None,
            'sharpe': round(nv['sharpe'], 2) if nv else None,
            'nav_end': round(nv['nav_end'], 3) if nv else None,
            'bench_ret': round(nv['bench_ret'] * 100, 2) if nv else None,
            'excess_ann': round(nv['excess_ann'] * 100, 2) if nv else None,
            'years': nv['years'] if nv else None,
        })
    out_df = pd.DataFrame(rows)
    out_df.to_csv(os.path.join(OUT, 'daban_bull_nav_20260903.csv'), index=False, encoding='utf-8-sig')
    with open(os.path.join(OUT, 'daban_bull_nav_20260903.json'), 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, default=str)
    print('\n===== 打板牛市过闸 10 组 · 组合净值指标（牛port 口径）=====')
    print(out_df.to_string(index=False))
    print(f'\nDONE in {time.time()-t0:.0f}s')

if __name__ == '__main__':
    main()
