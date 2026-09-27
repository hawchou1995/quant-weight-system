# -*- coding: utf-8 -*-
"""
2026-09-06 公众号《技术指标公式源码编写 见底信号》(指标作者 2026-09-06 21:12)
===================================================================
公式原文（通达信）:
趋势线: (C-MA(C,40))/MA(C,40)*100;
LLU:=((REF(趋势线,1)<REF(趋势线,2) AND 趋势线<-30) AND 趋势线>=REF(趋势线,1))
     OR (REF(CROSS(-30,趋势线),1) AND CROSS(趋势线,-30)) OR 趋势线=-30;
CE:=((REF(趋势线,1)<REF(趋势线,2) AND 趋势线<-20 AND 趋势线>-25) AND 趋势线>=REF(趋势线,1))
    OR (REF(CROSS(-20,趋势线),1) AND CROSS(趋势线,-20));
LUU:=((REF(趋势线,1)<REF(趋势线,2) AND 趋势线<-25 AND 趋势线>-30) AND 趋势线>=REF(趋势线,1))
    OR (REF(CROSS(-25,趋势线),1) AND CROSS(趋势线,-25));
底部快显: CROSS(-20,趋势线); 机会来临: CROSS(-25,趋势线); 等: CROSS(-30,趋势线);

翻译要点（保留作者固有语义）：
- 趋势线 = 40 日乖离率（%）
- CROSS(A,B) = A 上穿 B: (A>B) AND REF(A<=B,1)
- CROSS(-30,趋势线) = -30 上穿趋势线 = 趋势线下穿 -30（跌破）
- CROSS(趋势线,-30) = 趋势线上穿 -30（收复）
- REF(CROSS(-30,趋势线),1) AND CROSS(趋势线,-30) = 前日刚跌破 -30、今日立即收复（V 型快弹）
- 第一分支: 前一日仍在下跌 (t1<t2) AND 今日<阈值 AND 今日止跌 (t>=t1) → 低档止跌回升
- 庄现/趋势线画线部分 WAN1-WAN7 仅绘图（庄现柱状线），无交易信号，忽略

口径（项目铁律）：
- 主板限定（用户只能买主板）；严格 T-1；成本 1.15% 往返
- 基准：沪深300 同窗口 open-to-open + 全池中位数
- 四闸：n≥30 + wr≥46% + med>0 + mean>0 + ex_b>0；PASS 后分年度 ≥7/9 年正
"""
import os, time
import pandas as pd
import numpy as np

T0 = time.time()
def log(msg):
    print(f"[{time.time()-T0:7.1f}s] {msg}", flush=True)

BASE = r"D:\Documents\Workbuddy\股票基金\quant-weight-system"
CACHE = os.path.join(BASE, "v8_factor_cache.pkl")
IDX_CSV = os.path.join(BASE, "index_000300.csv")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jiandi_signal_0906_out")
os.makedirs(OUT_DIR, exist_ok=True)

BACKTEST_START = pd.Timestamp("2016-06-01")
COST = 0.00575  # 单边
HOLDS = [5, 10, 20]

def board_of(code):
    if code.startswith(("sh688", "sh689")): return "star"
    if code.startswith("sz30"): return "gem"
    if code.startswith(("sh60", "sz00", "sz002")): return "main"
    return None

def jiandi_signals(code, df):
    """返回 dict: 入市/机会/见底/快显/来临/等 6 个信号 bool 数组"""
    c = df['close']
    n = len(df)
    out = {k: np.zeros(n, dtype=bool) for k in
           ('rushi', 'jihui', 'jiandi', 'kuaixian', 'laiLin', 'deng')}
    if n < 70:
        return out
    ma40 = c.rolling(40, min_periods=40).mean()
    trend = (c - ma40) / ma40 * 100.0
    t = trend.values
    b_up = lambda a, b: (a > b) & (a.shift(1) <= b.shift(1))  # CROSS(A,B)

    # 上穿三档：趋势线上穿 -20/-25/-30（从下方收复）
    cross_20 = b_up(trend, pd.Series(-20, index=trend.index))
    cross_25 = b_up(trend, pd.Series(-25, index=trend.index))
    cross_30 = b_up(trend, pd.Series(-30, index=trend.index))
    # 下穿三档（CROSS(-20,趋势线) = -20 上穿趋势线 = 趋势线下穿 -20）
    fall_20 = b_up(pd.Series(-20, index=trend.index), trend)
    fall_25 = b_up(pd.Series(-25, index=trend.index), trend)
    fall_30 = b_up(pd.Series(-30, index=trend.index), trend)

    # 止跌回升第一分支：昨日仍在跌(REF1<REF2) AND 阈值区间 AND 今日>=昨日
    # ⚠ 2026-09-06 修复：原实现 updown[1:]=t[1:]<t[:-1] 与 stabilize[1:]=t[1:]>=t[:-1]
    #   按同一日期对齐，两者互斥 → 该分支永远 False（只留下穿后收复分支）。
    #   正确口径：updown 用「昨日<前日」（移位一天），stabilize 用「今日>=昨日」。
    t1 = np.where(np.isnan(t), 0, t)
    updown = np.zeros(n, dtype=bool)
    updown[2:] = t1[1:-1] < t1[:-2]  # 昨日<前日（i-1 < i-2）—— 与 stabilize 不同日
    stabilize = np.zeros(n, dtype=bool)
    stabilize[1:] = t1[1:] >= t1[:-1]  # 今日>=昨日（i >= i-1）

    def band_sig(lo, hi):
        """低档止跌回升: 昨日仍在跌 AND lo<-今日<hi(或<-30) AND 今日止跌"""
        if hi is None:  # 入市：<-30
            return updown & (t < -30) & stabilize
        return updown & (t > lo) & (t < hi) & stabilize

    out['rushi'] = (band_sig(None, None)
                    | (fall_30.shift(1).fillna(False) & cross_30)
                    | (np.abs(t1 + 30) < 1e-9))
    out['jihui'] = (band_sig(-30, -25) | (fall_25.shift(1).fillna(False) & cross_25))
    out['jiandi'] = (band_sig(-25, -20) | (fall_20.shift(1).fillna(False) & cross_20))
    out['kuaixian'] = cross_20.values
    out['laiLin'] = cross_25.values
    out['deng'] = cross_30.values
    for k in out:
        out[k] = np.asarray(out[k], dtype=bool)
    return out

def main():
    log("加载缓存 ...")
    cache = pd.read_pickle(CACHE)
    cache = {c: df for c, df in cache.items() if board_of(c) == "main"}
    log(f"主板限定: {len(cache)} 只")

    idx = pd.read_csv(IDX_CSV)
    idx['date'] = pd.to_datetime(idx['date'])
    idx = idx.sort_values('date').reset_index(drop=True)
    idx_open = idx.set_index('date')['open']

    all_oo = {}
    for code, df in cache.items():
        if df is None or len(df) < 30:
            continue
        d = df[['open']].copy()
        d.index.name = None
        d['date'] = d.index
        d = d.sort_values('date').reset_index(drop=True)
        d['ret'] = d['open'].pct_change()
        all_oo[code] = d[['date', 'ret']]
    bdf = pd.concat(all_oo.values(), ignore_index=True)
    med_ret = bdf.groupby('date')['ret'].median()
    med_cum = (1 + med_ret).cumprod()

    log("计算见底信号 ...")
    sig_maps = {k: {} for k in ('rushi', 'jihui', 'jiandi', 'kuaixian', 'laiLin', 'deng')}
    for code, df in cache.items():
        if df is None or len(df) < 70:
            continue
        sm = jiandi_signals(code, df)
        for k in sig_maps:
            sig_maps[k][code] = sm[k]
    for k, m in sig_maps.items():
        log(f"  {k}: 总信号 {sum(int(v.sum()) for v in m.values())}")

    def run_events(sig_map, H):
        rows = []
        for code, df in cache.items():
            if code not in sig_map or df is None or len(df) < 70:
                continue
            sig = sig_map[code]
            if not sig.any():
                continue
            d = df[['open', 'close']].copy()
            d.index.name = None
            d['date'] = d.index
            d = d.sort_values('date').reset_index(drop=True)
            opens = d['open'].values
            dates = d['date'].values
            n = len(d)
            for i in range(n):
                if not sig[i]:
                    continue
                if pd.Timestamp(dates[i]) < BACKTEST_START:
                    continue
                bi, si = i + 1, i + 1 + H
                if si >= n:
                    continue
                bo, so = opens[bi], opens[si]
                if bo <= 0 or so <= 0:
                    continue
                ret = so * (1 - COST) / (bo * (1 + COST)) - 1
                b0 = idx_open.get(pd.Timestamp(dates[bi]))
                b1 = idx_open.get(pd.Timestamp(dates[si]))
                ex_b = ret - (b1 / b0 - 1) if (b0 and b1 and b0 > 0) else np.nan
                m0 = med_cum.get(pd.Timestamp(dates[bi]))
                m1 = med_cum.get(pd.Timestamp(dates[si]))
                ex_m = ret - (m1 / m0 - 1) if (m0 and m1 and m0 > 0) else np.nan
                rows.append((dates[bi], ret, ex_b, ex_m))
        return rows

    names = {'rushi': '入市<-30', 'jihui': '机会[-30,-25]', 'jiandi': '见底[-25,-20]',
             'kuaixian': '上穿-20', 'laiLin': '上穿-25', 'deng': '上穿-30'}
    results = []
    for k, sig_map in sig_maps.items():
        for H in HOLDS:
            rows = run_events(sig_map, H)
            if len(rows) < 15:
                results.append({'signal': names[k], 'hold': H, 'n': len(rows), 'gates': 'fail(n<15)'})
                continue
            fr = np.array([r[1] for r in rows])
            ex_b = np.array([r[2] for r in rows])
            ex_m = np.array([r[3] for r in rows])
            n = len(fr)
            wr = (fr > 0).mean() * 100
            med = np.median(fr) * 100
            mean = fr.mean() * 100
            ex_b_m = np.nanmean(ex_b) * 100
            ex_m_m = np.nanmean(ex_m) * 100
            wins = fr[fr > 0]; losses = fr[fr < 0]
            pf = (wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else 0.0
            gates = {'n_ok': n >= 30, 'wr_ok': wr >= 46, 'med_ok': med > 0,
                     'mean_ok': mean > 0, 'ex_ok': ex_b_m > 0}
            pass4 = all(gates.values())
            yearly = {}
            if pass4:
                yr = {}
                for z in rows:
                    y = pd.Timestamp(z[0]).year
                    yr.setdefault(y, []).append(z[1])
                yearly = {y: (len(v), round(np.mean(v) * 100, 2), round(np.median(v) * 100, 2)) for y, v in sorted(yr.items())}
            results.append({
                'signal': names[k], 'hold': H, 'n': n, 'wr': round(wr, 2),
                'med': round(med, 3), 'mean': round(mean, 3), 'ex_b': round(ex_b_m, 3),
                'ex_m': round(ex_m_m, 3), 'pf': round(pf, 2),
                'gates': 'PASS' if pass4 else f"fail({sum(gates.values())}/5)",
                'yearly': yearly,
            })
            log(f"{names[k]} H={H}: n={n} wr={wr:.1f}% med={med:.2f}% mean={mean:.2f}% ex_b={ex_b_m:.2f}% gates={results[-1]['gates']}")

    out = pd.DataFrame(results)
    out.to_csv(os.path.join(OUT_DIR, "jiandi_signal_0906.csv"), index=False)
    pd.set_option('display.width', 250)
    pd.set_option('display.max_columns', 30)
    print(out[['signal', 'hold', 'n', 'wr', 'med', 'mean', 'ex_b', 'ex_m', 'pf', 'gates']].to_string(index=False))
    for r in results:
        if r.get('gates') == 'PASS':
            print(f"\n=== {r['signal']} H={r['hold']} 分年度 ===")
            for y, (n2, m, md) in r['yearly'].items():
                print(f"  {y}: n={n2:4d} mean={m:7.2f}% med={md:7.2f}%")
    log("完成")

if __name__ == "__main__":
    main()
