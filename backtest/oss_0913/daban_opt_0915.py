# -*- coding: utf-8 -*-
"""打板族（A5）优化轮 · 阶段0 口径修复 + 轴①②③（预注册 R-daban-opt-0915）
阶段0：amt = amount（真实）>0 为准，否则回退 vol×close；重做基线并对照旧口径
轴①：TP 细扫 {6,7,8,9,10,12}% × {tp_t2, tp_t1}
轴②：因子筛选/排序（aroon_osc/mom_12_1/ma200_pos/ret20/vp_confirm/amt20 + ADX14 + 成交额分位）
轴③：情绪真开关（涨停家数/连板高度/炸板率 + hs300>MA20），双向阈值
门：n≥30 ∧ wr>40% ∧ med>0 ∧ mean>0 ∧ excess>0（excess vs HS300 同期）+ 前后半(2023-01-01) + 分年度
输出：backtest/oss_0913/daban_opt_0915.json
"""
import os, sys, json, time
import numpy as np, pandas as pd

sys.path.insert(0, r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
import strategy_absorb_ev3_a5_absorb as A5

t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)


d = pd.read_pickle(A5.PKL)
names = json.load(open(A5.NAMES_JSON, encoding='utf-8'))
hs300 = A5.load_hs300()
log(f"pkl {len(d)} 只 | hs300 {len(hs300)}")

CFG = dict(gap_lo=-0.05, gap_hi=-0.02, rp_max=0.5, amt_min=5e7)
SPLIT = "2023-01-01"
TP_GRID = [0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.12]  # 4/5% 为网格边界修正案（原文 6% 为界，中位呈单调趋势需找拐点）
FAC_COLS = ["aroon_osc", "mom_12_1", "ma200_pos", "ret20", "vp_confirm", "amt20"]

# ---------- 情绪序列（轴③，用全池非ST 日频聚合） ----------
MASTER = pd.DatetimeIndex(sorted(hs300.index))
pos_of = {dt: i for i, dt in enumerate(MASTER)}
N_M = len(MASTER)
n_zt = np.zeros(N_M); n_touch = np.zeros(N_M); n_break = np.zeros(N_M)
lb_max = np.zeros(N_M)
fallback_days = 0; fallback_cells = 0; total_cells = 0


def adx14(df):
    h = df['high'].values.astype(float); l = df['low'].values.astype(float); c = df['close'].values.astype(float)
    n = len(c)
    pc = np.empty(n); pc[0] = np.nan; pc[1:] = c[:-1]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    up = h - np.roll(h, 1); dn = np.roll(l, 1) - l
    up[0] = np.nan; dn[0] = np.nan
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = np.full(n, np.nan); sp = np.full(n, np.nan); sn = np.full(n, np.nan)
    if n > 15:
        atr[14] = np.nansum(tr[1:15]); sp[14] = np.nansum(pdm[1:15]); sn[14] = np.nansum(ndm[1:15])
        for i in range(15, n):
            atr[i] = atr[i-1] - atr[i-1] / 14 + tr[i]
            sp[i] = sp[i-1] - sp[i-1] / 14 + pdm[i]
            sn[i] = sn[i-1] - sn[i-1] / 14 + ndm[i]
    with np.errstate(all='ignore'):
        pdi = 100 * sp / np.where(atr > 0, atr, np.nan)
        ndi = 100 * sn / np.where(atr > 0, atr, np.nan)
        dx = 100 * np.abs(pdi - ndi) / np.where((pdi + ndi) > 0, pdi + ndi, np.nan)
    adx = np.full(n, np.nan)
    if n > 28:
        adx[27] = np.nanmean(dx[14:28])
        for i in range(28, n):
            adx[i] = (adx[i-1] * 13 + dx[i]) / 14
    return adx


rows = []
for code, df0 in d.items():
    if not A5.is_pool_code(code) or A5.is_st_name(names.get(code, '')):
        continue
    df = df0[(df0.index >= A5.START) & (df0.index <= A5.END)]
    if len(df) < 60:
        continue
    feat = A5.compute_features(df, code)
    thr = A5.limit_thr(code)
    op = df['open'].values; cl = df['close'].values; hi = df['high'].values; vol = df['volume'].values
    amt = df['amount'].values.astype(float) if 'amount' in df.columns else np.full(len(df), np.nan)
    total_cells += len(df)
    fb = ~np.isfinite(amt) | (amt <= 0)
    fallback_cells += int(fb.sum())
    amt_c = np.where(fb, vol * cl, amt)          # 阶段0 口径：真实 amount 优先
    if fb.any():
        fallback_days += int(fb.sum())
    aro = df['aroon_osc'].values if 'aroon_osc' in df.columns else np.full(len(df), np.nan)
    mom = df['mom_12_1'].values if 'mom_12_1' in df.columns else np.full(len(df), np.nan)
    m200 = df['ma200_pos'].values if 'ma200_pos' in df.columns else np.full(len(df), np.nan)
    r20 = df['ret20'].values if 'ret20' in df.columns else np.full(len(df), np.nan)
    vpc = df['vp_confirm'].values if 'vp_confirm' in df.columns else np.full(len(df), np.nan)
    amt20v = df['amt20'].values if 'amt20' in df.columns else np.full(len(df), np.nan)
    adx = adx14(df)
    dates = df.index.strftime('%Y-%m-%d')
    n = len(df)
    is_zt, is_yz, prev_close, rel_pos = feat['is_zt'], feat['is_yz'], feat['prev_close'], feat['rel_pos']
    # ---- 情绪聚合（轴③） ----
    dt_idx = np.array([pos_of.get(pd.Timestamp(x), -1) for x in df.index])
    okm = dt_idx >= 0
    for k in np.where(okm)[0]:
        i = dt_idx[k]
        if is_zt[k]:
            n_zt[i] += 1
        touch = hi[k] >= prev_close[k] * (1 + thr) * 0.9995 if np.isfinite(prev_close[k]) else False
        if touch:
            n_touch[i] += 1
            if not is_zt[k]:
                n_break[i] += 1
    # 连板高度：该股连续涨停（close 口径）计数
    streak = 0
    for k in range(n):
        if is_zt[k]:
            streak += 1
            if okm[k]:
                i = dt_idx[k]
                if streak > lb_max[i]:
                    lb_max[i] = streak
        else:
            streak = 0
    # ---- 事件扫描 ----
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
        if not np.isfinite(rel_pos[T-1]) or rel_pos[T-1] > CFG['rp_max']:
            continue
        if not np.isfinite(amt_c[T-1]) or amt_c[T-1] < CFG['amt_min']:
            continue
        ep = op[T]
        hi60 = np.nanmax(cl[max(0, T-1-59):T]) if T >= 60 else np.nan
        dh = (hi60 - cl[T-1]) / hi60 if np.isfinite(hi60) and hi60 > 0 else np.nan
        r = dict(code=code, buy=dates[T], gap=float(gap),
                 f_aro=aro[T-1], f_mom=mom[T-1], f_m200=m200[T-1], f_r20=r20[T-1],
                 f_vpc=vpc[T-1], f_amt20=amt20v[T-1], f_adx=adx[T-1], f_dh=float(dh),
                 amt20_T1=amt20v[T-1], rp=float(rel_pos[T-1]), amt_c=float(amt_c[T-1]))
        # 基准出场
        eb, px, why = A5.apply_tp_t2(df, feat, T, ep)
        r['base_net'] = (px / ep) * (1 - A5.COST_BUY) * (1 - A5.COST_SELL) - 1
        r['base_why'] = why
        r['base_sell'] = dates[eb]
        # 轴①：tp 网格 × 两形态
        for tpv in TP_GRID:
            for form in ("tp_t2", "tp_t1"):
                tp_px = ep * (1 + tpv)
                if form == "tp_t2":
                    eb2, px2, _ = A5.apply_tp_t2(df, feat, T, ep, tp=tpv)
                else:
                    if is_zt[T+1]:
                        TT = min(T + 2, n - 1)
                        eb2, px2 = TT, cl[TT]
                    elif hi[T+1] >= tp_px:
                        eb2, px2 = T + 1, tp_px
                    else:
                        eb2, px2 = T + 1, cl[T + 1]
                r[f'tp{int(tpv*100)}_{form}'] = (px2 / ep) * (1 - A5.COST_BUY) * (1 - A5.COST_SELL) - 1
        # 情绪（T-1）
        if okm[T-1]:
            i = dt_idx[T-1]
            r['s_zt'] = n_zt[i]; r['s_lb'] = lb_max[i]
            r['s_zpl'] = (n_break[i] / n_touch[i]) if n_touch[i] > 0 else np.nan
        r['s_gate'] = np.nan
        rows.append(r)

E = pd.DataFrame(rows)
log(f"事件 {len(E)} 笔 | amount 回退格数 {fallback_cells}/{total_cells} = {fallback_cells/max(total_cells,1):.2%}")

# hs300 闸门（PIT：T-1 收盘）—— hs300 索引为字符串日期
ma20 = hs300.rolling(20, min_periods=15).mean()
gate_open = (hs300 > ma20)
E['s_gate'] = [1.0 if bool(gate_open.get(b, False)) else 0.0 for b in E.buy]


def stats(sub, col):
    f = sub[col].values
    if len(f) < 1:
        return None
    bench = []
    for _, s in sub.iterrows():
        try:
            bench.append(hs300.loc[s['E0_sell']] / hs300.loc[s['buy']] - 1)
        except Exception:
            bench.append(np.nan)
    b = np.nanmean(bench) if len(bench) else np.nan
    h1 = sub[sub.buy < SPLIT][col]; h2 = sub[sub.buy >= SPLIT][col]
    return dict(n=len(f), mean=float(np.nanmean(f)), med=float(np.median(f)), wr=float((f > 0).mean()),
                ex=float(np.nanmean(f) - b) if np.isfinite(b) else None,
                h1_med=float(np.median(h1)) if len(h1) > 8 else None,
                h2_med=float(np.median(h2)) if len(h2) > 8 else None)


def gates(s):
    if s is None:
        return "----"
    g = [s['n'] >= 30, s['wr'] > 0.40, s['med'] > 0, s['mean'] > 0, s['ex'] is not None and s['ex'] > 0]
    return "/".join("P" if x else "F" for x in g)


def line(tag, s):
    if s is None:
        return f"{tag:26s} n=0"
    return (f"{tag:26s} n={s['n']:5d} mean={s['mean']*100:+.2f}% med={s['med']*100:+.2f}% wr={s['wr']*100:.1f}% "
            f"ex={0 if s['ex'] is None else s['ex']*100:+.2f}% | h1 {0 if s['h1_med'] is None else s['h1_med']*100:+.2f}/{0 if s['h2_med'] is None else s['h2_med']*100:+.2f} | 闸 {gates(s)}")


# 基础字段：E0_sell（基准卖出日）——bench 用它
E['E0_sell'] = E['base_sell']
out = {}

# ---------- 阶段0 基线 ----------
E['year'] = E.buy.str[:4]
b0 = stats(E, 'base_net')
out['baseline'] = dict(new=b0, old_note="旧口径(vol×close) n=1493 / mean -0.209% / wr 46.3% / tp 21.1%",
                       fallback_share=fallback_cells / max(total_cells, 1),
                       tp_share=float((E.base_why == 'tp').mean()))
log("阶段0 新基线: " + line("BASE(amount修正)", b0))
log(f"  tp 占比 {out['baseline']['tp_share']*100:.1f}% | 回退格占比 {out['baseline']['fallback_share']*100:.2f}%")

# ---------- 轴① TP 细扫 ----------
out['tp_scan'] = {}
log("=== 轴① TP 细扫 ===")
for tpv in TP_GRID:
    for form in ("tp_t2", "tp_t1"):
        col = f"tp{int(tpv*100)}_{form}"
        s = stats(E, col)
        out['tp_scan'][col] = s
        log("  " + line(col, s))

# ---------- 轴② 因子筛选 ----------
out['factor_screen'] = {}
log("=== 轴② 因子筛选（三分位 + 极值阈值）===")
for fc in ["f_aro", "f_mom", "f_m200", "f_r20", "f_vpc", "f_amt20", "f_adx"]:
    v = E[fc]
    if v.notna().sum() < 100:
        log(f"  {fc}: 覆盖不足 ({v.notna().sum()})")
        out['factor_screen'][fc] = {"note": f"覆盖不足 {int(v.notna().sum())}"}
        continue
    q = v.quantile([0.2, 1/3, 2/3, 0.8])
    out['factor_screen'][fc] = {}
    for tag, msk in (
        ("low20", v <= q[0.2]), ("low33", v <= q[1/3]), ("mid", (v > q[1/3]) & (v <= q[2/3])),
        ("high67", v > q[2/3]), ("high80", v >= q[0.8]),
    ):
        s = stats(E[msk.fillna(False)], 'base_net')
        out['factor_screen'][fc][tag] = s
        log("  " + line(f"{fc} {tag}", s))

# ---------- 轴② 排序臂 ----------
out['factor_rank'] = {}
log("=== 轴② 排序臂（日频取前1/前2）===")
for fc, asc in [("f_aro", False), ("f_mom", False), ("f_m200", False), ("f_r20", False),
                ("f_vpc", False), ("f_amt20", False), ("f_adx", True)]:
    sub = E[E[fc].notna()].copy()
    sub['rk'] = sub.groupby('buy')[fc].rank(ascending=asc, method='first')
    for k in (1, 2):
        sel = sub[sub.rk <= k]
        s = stats(sel, 'base_net')
        out['factor_rank'][f"{fc}_top{k}"] = s
        log("  " + line(f"{fc} top{k}", s))

# ---------- 轴③ 情绪真开关 ----------
out['sentiment_gates'] = {}
log("=== 轴③ 情绪真开关 ===")
for sc in ["s_zt", "s_lb", "s_zpl"]:
    v = E[sc]
    if v.notna().sum() < 100:
        log(f"  {sc} 覆盖不足")
        continue
    q = v.quantile([0.2, 0.8])
    for tag, msk in ((f"{sc}≥p80", v >= q[0.8]), (f"{sc}≤p20", v <= q[0.2])):
        s = stats(E[msk.fillna(False)], 'base_net')
        out['sentiment_gates'][tag] = s
        log("  " + line(tag, s))
for tag, msk in (("hs300>MA20(开)", E.s_gate == 1), ("hs300≤MA20(关)", E.s_gate == 0)):
    s = stats(E[msk], 'base_net')
    out['sentiment_gates'][tag] = s
    log("  " + line(tag, s))

out['meta'] = dict(n_events=len(E), fallback_share=fallback_cells / max(total_cells, 1),
                   split=SPLIT, window=[A5.START, A5.END], amt_mode="amount>0 else vol*close")
E.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "daban_events_0915.csv"), index=False)
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "daban_opt_0915.json"), "w",
                    encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved daban_opt_0915.json + daban_events_0915.csv")
