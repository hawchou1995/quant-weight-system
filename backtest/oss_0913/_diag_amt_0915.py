# -*- coding: utf-8 -*-
"""诊断：1491（旧）vs 1059（新）事件数差异来源——amt 口径 × rel_pos NaN 处理 2×2"""
import sys, time
import numpy as np, pandas as pd
sys.path.insert(0, r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
import strategy_absorb_ev3_a5_absorb as A5

t0 = time.time()
d = pd.read_pickle(A5.PKL)
import json as _json
names = _json.load(open(A5.NAMES_JSON, encoding='utf-8'))
CFG = dict(gap_lo=-0.05, gap_hi=-0.02, rp_max=0.5, amt_min=5e7)

from collections import defaultdict
cnt = defaultdict(lambda: defaultdict(int))

for code, df0 in d.items():
    if not A5.is_pool_code(code) or A5.is_st_name(names.get(code, '')):
        continue
    df = df0[(df0.index >= A5.START) & (df0.index <= A5.END)]
    if len(df) < 60:
        continue
    feat = A5.compute_features(df, code)
    op = df['open'].values; cl = df['close'].values; vol = df['volume'].values
    a = df['amount'].values.astype(float)
    vc = (vol * cl).astype(float)
    ac = np.where(np.isfinite(a) & (a > 0), a, vc)
    years = df.index.year.values
    is_zt, is_yz, prev_close, rel_pos = feat['is_zt'], feat['is_yz'], feat['prev_close'], feat['rel_pos']
    n = len(df)
    for T in range(2, n - 3):
        if vol[T] <= 0 or op[T] <= 0 or prev_close[T] <= 0:
            continue
        if is_yz[T]:
            continue
        if not (is_zt[T-1] and not is_zt[T-2] and not is_yz[T-1]):
            continue
        gap = op[T] / prev_close[T] - 1
        if not (CFG['gap_lo'] <= gap <= CFG['gap_hi']):
            continue
        rp = rel_pos[T-1]
        rp_ok_strict = np.isfinite(rp) and rp <= CFG['rp_max']      # 我方：NaN 剔除
        rp_ok_loose = not (rp > CFG['rp_max'])                       # 旧方：NaN 通过
        if not rp_ok_loose:
            continue
        y = int(years[T-1] if True else years[T])
        amt_old = vc[T-1]; amt_new = ac[T-1]
        if not np.isfinite(amt_old) or not np.isfinite(amt_new):
            continue
        # 记录 4 个变体（在 rp 宽松通过的前提下）
        if amt_old >= CFG['amt_min']:
            cnt[y]['V1_old_looseRp'] += 1
            if not np.isfinite(rp):
                cnt[y]['V1_nan_rp'] += 1
        if amt_old >= CFG['amt_min'] and rp_ok_strict:
            cnt[y]['V2_old_strictRp'] += 1
        if amt_new >= CFG['amt_min']:
            cnt[y]['V3_new_looseRp'] += 1
        if amt_new >= CFG['amt_min'] and rp_ok_strict:
            cnt[y]['V4_new_strictRp'] += 1

print(f"[{time.time()-t0:.0f}s] year | V1 旧口径宽松rp | V2 旧+严格rp | V3 新口径宽松rp | V4 新+严格rp(我方) | V1中NaN_rp")
tot = defaultdict(int)
for y in sorted(cnt):
    r = cnt[y]
    print(f"{y} | {r['V1_old_looseRp']:4d} | {r['V2_old_strictRp']:4d} | {r['V3_new_looseRp']:4d} | {r['V4_new_strictRp']:4d} | {r['V1_nan_rp']:3d}")
    for k in r:
        tot[k] += r[k]
print("TOTAL |", dict(tot))
