# -*- coding: utf-8 -*-
"""
A5 打板 · 胜率提升探索第三轮（2026-09-02 晚）
=================================================
第一轮（zt 过滤+出场）12 全 FAIL：长持出场 med 崩
第二轮（gap 分档）5 全 FAIL：深度低开是毒药但幅度不足
第三轮假设：胜率杠杆 = 首板质量过滤 × 快出场（tp_t2 保留、不动出场）
            + 唯一被法医+多轮验证的方向：避免深度低开的毒药
扫描：
  Q1  首板日量能（vol[T-1]/ma20 量均）> 1.5 倍 → 放量首板
  Q2  首板日量能 < 1.5 倍 → 缩量首板（对比）
  Q3  首板日收盘位置 rel_pos[T-2] ≤ 0.3（低位首板）
  Q4  首板日量能 1.5-4 倍（适度放量）—— 验证 U 型假设
  Q5  浅低开 + 放量（G1∩Q1 组合）—— 两杠杆叠加
  出场一律 tp_t2 8% 基准
输出：a5_zt_fusion_out/a5_quality.json
"""
import os, sys, json, time
import pandas as pd
import numpy as np

BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
sys.path.insert(0, BASE)
import strategy_absorb_ev3_a5_absorb as base

OUT_DIR = os.path.join(BASE, "backtest", "a5_zt_fusion_out")
os.makedirs(OUT_DIR, exist_ok=True)
START, END = "2016-01-01", "2026-08-28"
SPLIT = pd.Timestamp("2021-01-01")
t0 = time.time()
def log(msg):
    print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

# 配置：gap 区间 × 首板质量
CONFIGS = {
    "Q1_放量1.5":  {'g': (-0.05, -0.02), 'q': 'vol15'},
    "Q2_缩量1.5":  {'g': (-0.05, -0.02), 'q': 'vol_lt15'},
    "Q3_低位rp03": {'g': (-0.05, -0.02), 'q': 'rp03'},
    "Q4_放量1.5_4x": {'g': (-0.05, -0.02), 'q': 'vol15_4x'},
    "Q5_浅低开_放量": {'g': (-0.035, -0.02), 'q': 'vol15'},
    "Q6_浅低开_缩量": {'g': (-0.035, -0.02), 'q': 'vol_lt15'},
}


def run_cfg(d, names, hs300, cfg):
    glo, ghi = cfg['g']
    q = cfg['q']
    sigs = []
    for code, df in d.items():
        if not base.is_pool_code(code):
            continue
        if base.is_st_name(names.get(code, '')):
            continue
        df = df[(df.index >= START) & (df.index <= END)]
        if len(df) < 60:
            continue
        feat = base.compute_features(df, code)
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
        # 量能比率：当日量 / 前20日均量
        vr = np.full(n, np.nan)
        for i in range(20, n):
            m = vol[i-20:i].mean()
            vr[i] = vol[i] / m if m > 0 else np.nan
        for T in range(2, n):
            if vol[T] <= 0 or open_[T] <= 0 or prev_close[T] <= 0:
                continue
            if is_yz[T]:
                continue
            if not (is_zt[T-1] and not is_zt[T-2] and not is_yz[T-1]):
                continue
            gap = open_[T] / prev_close[T] - 1
            if not (glo <= gap <= ghi):
                continue
            rp = rel_pos[T-1]
            if rp > 0.5:
                continue
            if amt[T-1] < 5e7:
                continue
            # 首板质量过滤（用 T-1 首板日）
            v = vr[T-1]
            r0 = rel_pos[T-2] if T >= 2 and rel_pos[T-2] == rel_pos[T-2] else None
            if q == 'vol15':
                if not (v == v and v > 1.5):
                    continue
            elif q == 'vol_lt15':
                if not (v == v and v <= 1.5):
                    continue
            elif q == 'vol15_4x':
                if not (v == v and 1.5 <= v <= 4.0):
                    continue
            elif q == 'rp03':
                if not (r0 is not None and r0 <= 0.3):
                    continue
            entry_px = open_[T]
            exit_bar, exit_px, reason = base.apply_tp_t2(df, feat, T, entry_px)
            raw_ret = exit_px / entry_px - 1
            net_ret = (1 + raw_ret) * (1 - base.COST_BUY) * (1 - base.COST_SELL) - 1
            sigs.append({'code': code, 'gap': gap, 'buy_date': dates[T],
                         'sell_date': dates[exit_bar], 'net_ret': net_ret, 'raw_ret': raw_ret,
                         'exit_reason': reason, 'hold_days': int(exit_bar - T)})
    rets = np.array([s['net_ret'] for s in sigs])
    bench = []
    for s in sigs:
        try:
            b0, b1 = hs300.loc[s['buy_date']], hs300.loc[s['sell_date']]
            bench.append(b1 / b0 - 1)
        except KeyError:
            bench.append(np.nan)
    bench = np.array(bench)
    out = {'n': int(len(rets)),
           'win_rate': float((rets > 0).mean() * 100) if len(rets) else None,
           'mean_net': float(rets.mean() * 100) if len(rets) else None,
           'median_net': float(np.median(rets) * 100) if len(rets) else None,
           'excess_mean': float(rets.mean() * 100 - np.nanmean(bench) * 100) if len(rets) and len(bench) else None,
           'excess_median': float(np.median(rets) * 100 - np.nanmedian(bench) * 100) if len(rets) and len(bench) else None,
           'avg_hold': float(np.mean([s['hold_days'] for s in sigs])) if sigs else None}
    def stats_of(sub):
        if len(sub) < 8:
            return None
        a = np.array(sub)
        return {'n': int(len(a)), 'wr': round(float((a > 0).mean() * 100), 2),
                'med': round(float(np.median(a) * 100), 3), 'mean': round(float(a.mean() * 100), 3)}
    h1 = [s['net_ret'] for s in sigs if pd.Timestamp(s['buy_date']) < SPLIT]
    h2 = [s['net_ret'] for s in sigs if pd.Timestamp(s['buy_date']) >= SPLIT]
    out['h1'] = stats_of(h1)
    out['h2'] = stats_of(h2)
    yearly = {}
    for s in sigs:
        y = s['buy_date'][:4]
        yearly.setdefault(y, []).append(s['net_ret'])
    yres = {}
    for y, rs in sorted(yearly.items()):
        a = np.array(rs)
        yres[y] = {'n': int(len(a)), 'mean': round(float(a.mean() * 100), 3), 'wr': round(float((a > 0).mean() * 100), 1)}
    out['yearly'] = yres
    return out


def gate4(s):
    if not s or s['n'] < 30:
        return False
    if s['win_rate'] <= 40:
        return False
    if s['median_net'] <= 0:
        return False
    if s['mean_net'] <= 0:
        return False
    if s['excess_median'] is None or s['excess_mean'] is None:
        return False
    if s['excess_median'] <= 0 and s['excess_mean'] <= 0:
        return False
    return True


def main():
    log("加载 pkl ...")
    d = pd.read_pickle(base.PKL)
    names = json.load(open(base.NAMES_JSON, encoding='utf-8'))
    hs300 = base.load_hs300()
    results = {}
    for k, cfg in CONFIGS.items():
        log(f"跑 {k} ...")
        results[k] = run_cfg(d, names, hs300, cfg)
    with open(os.path.join(OUT_DIR, "a5_quality.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False)
    rows = []
    for k, s in results.items():
        rows.append({'cfg': k, 'n': s['n'], 'wr': round(s['win_rate'], 1) if s['win_rate'] is not None else None,
                     'med': round(s['median_net'], 3) if s['median_net'] is not None else None,
                     'mean': round(s['mean_net'], 3) if s['mean_net'] is not None else None,
                     'ex_m': round(s['excess_median'], 3) if s['excess_median'] is not None else None,
                     'h1_n': s['h1']['n'] if s['h1'] else 0, 'h1_wr': s['h1']['wr'] if s['h1'] else 0,
                     'h1_med': s['h1']['med'] if s['h1'] else 0,
                     'h2_n': s['h2']['n'] if s['h2'] else 0, 'h2_wr': s['h2']['wr'] if s['h2'] else 0,
                     'h2_med': s['h2']['med'] if s['h2'] else 0,
                     'gate4': 'PASS' if gate4(s) else 'FAIL'})
    pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, "a5_quality_summary.csv"), index=False, encoding="utf-8-sig")
    log("完成 ✅")
    for r in rows:
        print(f"{r['cfg']:14s} n={r['n']:5d} wr={r['wr']:6.1f}% med={r['med']:+.2f}% mean={r['mean']:+.2f}% "
              f"ex_m={r['ex_m']:+.2f}%  h1={r['h1_n']}/{r['h1_wr']}%/{r['h1_med']:+.2f}%  "
              f"h2={r['h2_n']}/{r['h2_wr']}%/{r['h2_med']:+.2f}% 四闸={r['gate4']}")


if __name__ == "__main__":
    main()
