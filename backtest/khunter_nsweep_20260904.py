# -*- coding: utf-8 -*-
"""
KHunter HYBRIDv2 资金利用率压力测试（2026-09-04 用户 #94）
=================================================================
用户问题：短线股票回测夏普问题 ② —— 探索资金利用率（持仓上限组合化压力测试）。
做法：HYBRIDv2 生产配置（牛定稿+熊prodA，与 phase10 完全一致）下，
      扫 max_hold（同时持仓上限 N ∈ {5, 10, 15}），统计：
        - 组合口径：total/maxdd/ann/sharpe（资金池利用率提升与否）
        - 利用率口径：日均投入市值占比 invested/nav、平均持仓数、空仓日占比
        - 基线复现：N=10 应与 phase10 HYBRIDv2（total 68.49% / sharpe 0.397）一致，先验证再采信
输出：khunter_timing_out/khunter_nsweep_20260904.csv
"""
import os, sys, time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from khunter_port_engine_0903 import (build_sig_cache, run_khunter_port, full_gate,
                                      nav_stats, load_market_state)
import khunter_timing_backtest as T

T0 = time.time()
def log(msg):
    print(f"[{time.time()-T0:7.1f}s] {msg}", flush=True)

OUT = T.OUT_DIR
NOST_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'khunter_timing_out', 'khunter_sigs_main_nost_0903.pkl')

# HYBRIDv2 生产配置（phase10 原样）
CFG = dict(ob=55, osl=35, gate='hybrid', env='uniform', hold_max=25, low_price=3.0,
           ob_bull=75, osl_bull=30, low_bull=None)
N_LIST = [5, 10, 15]

def util_stats(nav_series):
    """资金利用率：日均投入比例 invested/nav（剔 nav=0/空仓日单独统计）"""
    df = pd.DataFrame(nav_series)
    if df.empty or 'invested' not in df:
        return {}
    df['inv_ratio'] = df['invested'] / df['nav'].replace(0, np.nan)
    n = len(df)
    empty_days = int((df['npos'] == 0).sum())
    return {'days': n,
            'mean_npos': round(df['npos'].mean(), 3),
            'max_npos': int(df['npos'].max()),
            'empty_days': empty_days,
            'empty_ratio': round(empty_days / n * 100, 1),
            'mean_inv_ratio': round(df['inv_ratio'].mean() * 100, 1),
            'full_inv_days': int((df['inv_ratio'] > 0.95).sum())}

def main():
    log("加载市场状态 ...")
    idx, state_prev = load_market_state()
    log("加载剔 ST 信号缓存 ...")
    if not os.path.exists(NOST_CACHE):
        log(f"缓存不存在: {NOST_CACHE}")
        return
    sigs = build_sig_cache(None, board_only='main', cache_file=NOST_CACHE, st_skip=True)
    log(f"剔 ST 信号缓存 {len(sigs)} 只")

    rows = []
    for N in N_LIST:
        log(f"=== max_hold N={N} 运行中 ...")
        t_a = time.time()
        nav_series, trade_log = run_khunter_port(sigs, state_prev, max_hold=N,
                                                 util_track=True, **CFG)
        dt_run = time.time() - t_a
        st, s1, s2, gates = full_gate(nav_series, trade_log)
        if st is None:
            log(f"  N={N} 交易为空，跳过")
            continue
        us = util_stats(nav_series)
        # 交易级：平均持仓天数近似（entry/exit 跨度可用 trade_log 内推——引擎日志无跨度，用 n 与持仓口径交叉）
        row = {'N': N, 'run_s': round(dt_run, 1), 'n': st['n'], 'wr': st['wr'],
               'med': st['med'], 'mean': st['mean'], 'total': st['total'],
               'maxdd': st['maxdd'], 'ann': st['ann'], 'sharpe': st['sharpe'],
               'pass': gates['pass'], 'pass_half': gates['pass_half'],
               'h1_med': s1['med'] if s1 else np.nan, 'h2_med': s2['med'] if s2 else np.nan,
               **us}
        rows.append(row)
        log(f"  N={N}: total={st['total']}% maxdd={st['maxdd']}% sharpe={st['sharpe']} "
            f"pass={gates['pass']}/{gates['pass_half']} 空仓日={us.get('empty_ratio')}% "
            f"投入比={us.get('mean_inv_ratio')}% 均持仓={us.get('mean_npos')}")

    if not rows:
        log("无结果")
        return
    df = pd.DataFrame(rows)
    out_csv = os.path.join(OUT, 'khunter_nsweep_20260904.csv')
    df.to_csv(out_csv, index=False, encoding='utf-8-sig')
    log(f"已保存 {out_csv}")
    print("\n========== 汇总 ==========")
    print(df.to_string(index=False))

if __name__ == "__main__":
    main()
