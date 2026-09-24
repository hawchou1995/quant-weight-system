# -*- coding: utf-8 -*-
"""
打板族源码吸收回测（2026-08-29）——A5 基准复现 + 注入吸收点对比
源码吸收点（聚宽2025）：
  ① 低开区间收窄 3-4%（首板低开 v1 / 终极版通道2 / 混合 sbdk 均用 3-4%）
  ② 相对位置收紧 rp≤0.3（终极版通道1 用 0.3，A5 用 0.5）
  ③ 左压过滤：首板日量能 > 前100日最大量×0.9（弱转强/混合策略核心过滤）
  ④ 成交额下限 1亿（首板低开 v1 用 1亿，A5 用 5000万）
  ⑤ 平开/微高开通道 0-1% + rp≤0.3（终极版通道1 全新形态，A5 无）
口径 = A5 基准逐位一致：涨停=主板≥9.5%/创业板≥19.5%，一字板排除，
  rel_pos = close 60日窗口，amt = volume×close，出场 tp_t2 8%（T+1/T+2 冲高止盈，
  否则收盘卖，涨停顺延），成本买 0.525%/卖 0.625%，超额=沪深300 同期。
数据：v8_factor_cache.pkl（5329 只，2016-01 起）
输出：strategy_absorb_out_0829/ev3_a5_absorb.json
"""
import pandas as pd
import numpy as np
import json, os, time

BASE = os.path.dirname(os.path.abspath(__file__))  # 2026-09-24 云端可移植（原写死 D:/…，本机解析恒等；保持 str 供 os.path.join）
PKL = os.path.join(BASE, "v8_factor_cache.pkl")
NAMES_JSON = os.path.join(BASE, "data_full_names.json")
HS300_CSV = os.path.join(BASE, "index_000300.csv")
OUT_DIR = os.path.join(BASE, "strategy_absorb_out_0829")
START, END = "2016-01-01", "2026-08-28"

COST_BUY, COST_SELL = 0.00525, 0.00625


def is_pool_code(code):
    if code.startswith('bj'):
        return False
    c = code[2:]
    if not c.isdigit():
        return False
    return c.startswith(('600', '601', '603', '605', '000', '001', '002', '003', '300', '301'))


def is_st_name(name):
    if not name:
        return False
    n = str(name).strip()
    if 'ST' in n.upper() or '退' in n:
        return True
    return n.startswith('S')


def limit_thr(code):
    c = code[2:]
    return 0.195 if c.startswith(('300', '301')) else 0.095


def load_hs300():
    df = pd.read_csv(HS300_CSV)
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
    return df.set_index('date')['close']


def compute_features(df, code):
    thr = limit_thr(code)
    close = df['close'].values
    open_ = df['open'].values
    high = df['high'].values
    low = df['low'].values
    vol = df['volume'].values
    n = len(df)
    prev_close = np.empty(n); prev_close[0] = np.nan; prev_close[1:] = close[:-1]
    ret = close / prev_close - 1
    is_zt = ret >= thr
    is_yz = (open_ == high) & (high == low) & (low == close) & is_zt
    # rel_pos 60日 close 窗口（与 A5 基准 compute_features 一致）
    rel_pos = np.full(n, np.nan)
    if n >= 60:
        c_series = pd.Series(close)
        lo = c_series.rolling(60, min_periods=60).min().values
        hi = c_series.rolling(60, min_periods=60).max().values
        rp = np.where(hi > lo, (close - lo) / (hi - lo), 0.5)
        rel_pos[59:] = rp[59:]
    amt = vol * close
    return {'prev_close': prev_close, 'ret': ret, 'is_zt': is_zt, 'is_yz': is_yz,
            'rel_pos': rel_pos, 'amt': amt}


def apply_tp_t2(df, feat, entry_bar, entry_px, tp=0.08):
    """tp_t2：T+1/T+2 日内 high≥entry×1.08 → tp；否则收盘卖 ts；涨停顺延；T+2 强平"""
    n = len(df)
    high = df['high'].values
    close = df['close'].values
    is_zt = feat['is_zt']
    tp_px = entry_px * (1 + tp)
    for T in range(entry_bar + 1, min(entry_bar + 3, n)):
        if is_zt[T]:
            continue
        if high[T] >= tp_px:
            return T, tp_px, 'tp'
        return T, close[T], 'ts'
    T = min(entry_bar + 2, n - 1)
    return T, close[T], 'force'


def run_cfg(d, names, hs300, cfg):
    """单配置扫描。cfg: dict(gap_lo,gap_hi,rp_max,amt_min,left_press,chan2)"""
    sigs = []
    for code, df in d.items():
        if not is_pool_code(code):
            continue
        if is_st_name(names.get(code, '')):
            continue
        df = df[(df.index >= START) & (df.index <= END)]
        if len(df) < 60:
            continue
        feat = compute_features(df, code)
        open_ = df['open'].values
        close = df['close'].values
        vol = df['volume'].values
        dates = df.index.strftime('%Y-%m-%d')
        prev_close = feat['prev_close']
        is_zt = feat['is_zt']
        is_yz = feat['is_yz']
        rel_pos = feat['rel_pos']
        amt = feat['amt']
        n = len(df)
        gap_lo, gap_hi = cfg['gap_lo'], cfg['gap_hi']
        rp_max, amt_min = cfg['rp_max'], cfg['amt_min']
        left_press = cfg.get('left_press', False)
        # 左压预计算：首板日前100日最大量（shift(1) 排除首板日自身量能）
        maxv100 = np.full(n, np.nan)
        if left_press and n > 100:
            v_series = pd.Series(vol)
            maxv100 = v_series.shift(1).rolling(100, min_periods=100).max().values
        for T in range(2, n):
            if vol[T] <= 0 or open_[T] <= 0 or prev_close[T] <= 0:
                continue
            if is_yz[T]:
                continue
            if not (is_zt[T-1] and not is_zt[T-2] and not is_yz[T-1]):
                continue
            gap = open_[T] / prev_close[T] - 1
            if cfg.get('chan2'):  # 平开/微高开通道
                if not (0.0 <= gap <= 0.01):
                    continue
            else:
                if not (gap_lo <= gap <= gap_hi):
                    continue
            rp = rel_pos[T-1]
            # 与原版 A5 基准一致：NaN 视为通过（NaN>max 为 False），仅过滤确定超限
            if rp > rp_max:
                continue
            if amt[T-1] < amt_min:
                continue
            if left_press and maxv100[T-1] == maxv100[T-1] and vol[T-1] <= maxv100[T-1] * 0.9:
                continue
            entry_px = open_[T]
            exit_bar, exit_px, reason = apply_tp_t2(df, feat, T, entry_px)
            raw_ret = exit_px / entry_px - 1
            net_ret = (1 + raw_ret) * (1 - COST_BUY) * (1 - COST_SELL) - 1
            sigs.append({'code': code, 'gap': gap, 'buy_date': dates[T],
                         'sell_date': dates[exit_bar], 'net_ret': net_ret, 'raw_ret': raw_ret,
                         'exit_reason': reason, 'hold_days': int(exit_bar - T)})
    # 统计
    rets = np.array([s['net_ret'] for s in sigs])
    raws = np.array([s['raw_ret'] for s in sigs])
    bench = []
    for s in sigs:
        try:
            b0, b1 = hs300.loc[s['buy_date']], hs300.loc[s['sell_date']]
            bench.append(b1 / b0 - 1)
        except KeyError:
            bench.append(np.nan)
    bench = np.array(bench)
    yearly = {}
    for s in sigs:
        y = s['buy_date'][:4]
        yearly.setdefault(y, []).append(s['net_ret'])
    yres = {}
    for y, rs in sorted(yearly.items()):
        a = np.array(rs)
        yres[y] = {'n': int(len(a)), 'mean': float(a.mean()), 'win_rate': float((a > 0).mean())}
    return {
        'n': int(len(rets)),
        'mean_net': float(rets.mean()) if len(rets) else None,
        'median_net': float(np.median(rets)) if len(rets) else None,
        'win_rate': float((rets > 0).mean()) if len(rets) else None,
        'mean_raw': float(raws.mean()) if len(raws) else None,
        'excess_mean': float(rets.mean() - np.nanmean(bench)) if len(rets) and len(bench) else None,
        'excess_median': float(np.median(rets) - np.nanmedian(bench)) if len(rets) and len(bench) else None,
        'tp_ratio': float(np.mean([s['exit_reason'] == 'tp' for s in sigs])) if sigs else None,
        'avg_hold': float(np.mean([s['hold_days'] for s in sigs])) if sigs else None,
        'yearly': yres,
    }


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    print('load pkl...')
    d = pd.read_pickle(PKL)
    names = json.load(open(NAMES_JSON, encoding='utf-8'))
    hs300 = load_hs300()
    print(f'cache {len(d)} codes, hs300 {len(hs300)} days')

    cfgs = {
        # 基准复现（验证 n≈1116 / 46.1% / -0.17%）
        'R0_A5基准': {'gap_lo': -0.05, 'gap_hi': -0.02, 'rp_max': 0.5, 'amt_min': 5e7, 'left_press': False},
        # ① 低开区间收窄 3-4%
        'R1_低开3-4pct': {'gap_lo': -0.04, 'gap_hi': -0.03, 'rp_max': 0.5, 'amt_min': 5e7, 'left_press': False},
        # ② 相对位置收紧 0.3
        'R2_rp0.3': {'gap_lo': -0.05, 'gap_hi': -0.02, 'rp_max': 0.3, 'amt_min': 5e7, 'left_press': False},
        # ③ 左压过滤
        'R3_左压': {'gap_lo': -0.05, 'gap_hi': -0.02, 'rp_max': 0.5, 'amt_min': 5e7, 'left_press': True},
        # ④ 成交额≥1亿
        'R4_成交额1亿': {'gap_lo': -0.05, 'gap_hi': -0.02, 'rp_max': 0.5, 'amt_min': 1e8, 'left_press': False},
        # 组合：①+②（低开3-4% + rp≤0.3）
        'R5_低开3-4_rp0.3': {'gap_lo': -0.04, 'gap_hi': -0.03, 'rp_max': 0.3, 'amt_min': 5e7, 'left_press': False},
        # 组合：全部吸收点
        'R6_全吸收': {'gap_lo': -0.04, 'gap_hi': -0.03, 'rp_max': 0.3, 'amt_min': 1e8, 'left_press': True},
        # ⑤ 平开/微高开通道（全新形态）
        'R7_平开通道': {'gap_lo': 0.0, 'gap_hi': 0.01, 'rp_max': 0.3, 'amt_min': 5e7, 'left_press': False, 'chan2': True},
        # ⑤b 平开通道 + 左压
        'R8_平开_左压': {'gap_lo': 0.0, 'gap_hi': 0.01, 'rp_max': 0.3, 'amt_min': 5e7, 'left_press': True, 'chan2': True},
    }
    out = {'meta': {'date': '2026-08-29', 'data': 'v8_factor_cache.pkl', 'start': START, 'end': END,
                    'cost': {'buy': COST_BUY, 'sell': COST_SELL},
                    'exit': 'tp_t2 8% (T+1/T+2 冲高止盈, 否则收盘, 涨停顺延)',
                    'excess': '沪深300 同期'}, 'results': {}}
    for name, cfg in cfgs.items():
        r = run_cfg(d, names, hs300, cfg)
        out['results'][name] = r
        m = r
        print(f"\n=== {name} ===")
        if m['n']:
            print(f"n={m['n']:,} mean_net={m['mean_net']*100:+.2f}% med={m['median_net']*100:+.2f}% "
                  f"wr={m['win_rate']*100:.1f}% raw={m['mean_raw']*100:+.2f}% "
                  f"excess={m['excess_mean']*100:+.2f}% tp={m['tp_ratio']*100:.0f}% hold={m['avg_hold']:.1f}d")
            gates = [m['win_rate'] >= 0.46, m['median_net'] > 0, m['mean_net'] > 0, m['excess_mean'] > 0]
            print(f"  四闸(46%/med>0/mean>0/excess>0): {'/'.join('P' if g else 'F' for g in gates)}")
        else:
            print("  无信号")
    json.dump(out, open(os.path.join(OUT_DIR, 'ev3_a5_absorb.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f"\nDONE {time.time()-t0:.0f}s -> ev3_a5_absorb.json")


if __name__ == '__main__':
    main()
