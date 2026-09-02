# -*- coding: utf-8 -*-
"""
A5 打板 · 生产候选配置验证（第五轮·2026-09-02 深夜）
=====================================================
背景：第四轮 C1(C2) 组合（低位×缩量）前后半双过但年度集中不可投产。
裁决遗留：唯一有证据的边际改进 = gap 收窄 [-3.5,-2] × rp≤0.3（纯组合，未专门验证）
第五轮任务：把该组合与当前生产参数（-0.05/-0.02/rp0.5）同口径对比，确认能否落地。

配置矩阵（全部出场 tp_t2，成本 0.525%/0.625%）：
  P0_当前生产   : g=(-0.05,-0.02)  rp=0.5  vr=不限      ← 生产基线对照
  P1_收窄_rp03  : g=(-0.035,-0.02) rp=0.3  vr=不限      ← 上轮裁决·唯一边际改进（纯）
  P2_收窄_rp03缩: g=(-0.035,-0.02) rp=0.3  vr=(0,1.5]   （= C2 对照）
  P3_收窄_rp025 : g=(-0.035,-0.02) rp=0.25 vr=不限
  P4_收窄_rp02  : g=(-0.035,-0.02) rp=0.2  vr=不限
  P5_收窄_rp03缩12: g=(-0.035,-0.02) rp=0.3 vr=(0,1.2]
  P6_浅低缩量全 : g=(-0.035,-0.02) rp=0.5  vr=(0,1.5]   ← 缩量×浅低 但 rp 保持生产值

输出：a5_zt_fusion_out/a5_final_prod.json + summary.csv
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

CONFIGS = {
    "P0_当前生产":        {'g': (-0.05, -0.02),  'rp': 0.5,  'vr': (0, 999),  'name': '生产基线 g-5~-2 rp0.5'},
    "P1_收窄_rp03":       {'g': (-0.035, -0.02), 'rp': 0.3,  'vr': (0, 999),  'name': '裁决组合 g-3.5~-2 rp0.3'},
    "P2_收窄_rp03缩":     {'g': (-0.035, -0.02), 'rp': 0.3,  'vr': (0, 1.5),  'name': '同 C2 对照'},
    "P3_收窄_rp025":      {'g': (-0.035, -0.02), 'rp': 0.25, 'vr': (0, 999),  'name': 'g-3.5~-2 rp0.25'},
    "P4_收窄_rp02":       {'g': (-0.035, -0.02), 'rp': 0.2,  'vr': (0, 999),  'name': 'g-3.5~-2 rp0.2'},
    "P5_收窄_rp03缩12":   {'g': (-0.035, -0.02), 'rp': 0.3,  'vr': (0, 1.2),  'name': 'g-3.5~-2 rp0.3 vr<1.2'},
    "P6_浅低缩量全":      {'g': (-0.035, -0.02), 'rp': 0.5,  'vr': (0, 1.5),  'name': 'g-3.5~-2 rp0.5 vr<1.5'},
}


def run_cfg(d, names, hs300, cfg):
    glo, ghi = cfg['g']
    rp_max = cfg['rp']
    vr_lo, vr_hi = cfg['vr']
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
            if rp > rp_max:
                continue
            if amt[T-1] < 5e7:
                continue
            v = vr[T-1]
            if not (v == v and vr_lo < v <= vr_hi):
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
        log(f"跑 {k} ({cfg['name']}) ...")
        results[k] = run_cfg(d, names, hs300, cfg)
    with open(os.path.join(OUT_DIR, "a5_final_prod.json"), "w", encoding="utf-8") as f:
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
    pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, "a5_final_prod_summary.csv"), index=False, encoding="utf-8-sig")
    log("完成 ✅")
    for r in rows:
        print(f"{r['cfg']:18s} n={r['n']:5d} wr={r['wr']:6.1f}% med={r['med']:+.2f}% mean={r['mean']:+.2f}% "
              f"ex_m={r['ex_m']:+.2f}%  h1={r['h1_n']}/{r['h1_wr']}%/{r['h1_med']:+.2f}%  "
              f"h2={r['h2_n']}/{r['h2_wr']}%/{r['h2_med']:+.2f}% 四闸={r['gate4']}")


if __name__ == "__main__":
    main()
