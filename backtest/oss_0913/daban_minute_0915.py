# -*- coding: utf-8 -*-
"""轴④ 首板日质量（分钟代理）+ 轴⑤ 日内路径出场三臂（R-daban-opt-0915）
数据：D:/Tools/cache/tdx_min（240 点/日）；事件 = daban_events_0915.csv 中 buy≥2024-05
口径：全部臂与「同子样本基线」对比（四闸+前后半+分年度）；PIT：轴④只用 T-1 分钟
输出：daban_minute_0915.json
"""
import os, json, sys
import numpy as np, pandas as pd

sys.path.insert(0, r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
import strategy_absorb_ev3_a5_absorb as A5

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = "D:/Tools/cache/tdx_min"
SPLIT = "2025-06-01"          # 子样本窗口的中点（2024-05~2026-08 共 ~28 个月）
E = pd.read_csv(os.path.join(HERE, "daban_events_0915.csv"))
E = E[E.buy >= "2024-05-01"].copy()
print("事件（2024-05 起）", len(E), flush=True)
d = pd.read_pickle(A5.PKL)


def minfile(code, ymd):
    f = os.path.join(CACHE, f"min_{code}_{ymd}.parquet")
    return pd.read_parquet(f) if os.path.exists(f) else None


def limit_px(pre_close, thr):
    return round(pre_close * (1 + thr) + 1e-9, 2)


rows = []
for _, r in E.iterrows():
    code = str(r['code'])
    df = d.get(code)
    if df is None:
        continue
    idx = df.index
    try:
        pos = idx.get_loc(pd.Timestamp(r['buy']))
    except KeyError:
        continue
    thr = A5.limit_thr(code)
    day = lambda off: int(idx[pos + off].strftime('%Y%m%d')) if 0 <= pos + off < len(idx) else None
    ymd_m1, ymd_0, ymd_p1, ymd_p2 = day(-1), day(0), day(1), day(2)
    entry_px = float(df['open'].values[pos])
    m0 = minfile(code, ymd_0)
    rec = dict(code=code, buy=r['buy'], base_net=r['base_net'], entry_px=entry_px,
               r20=r['f_r20'], adx=r['f_adx'], rp=r['rp'])
    # ---- 轴④：首板日（T-1） ----
    mm = minfile(code, ymd_m1)
    if mm is not None and len(mm) >= 200:
        pre_c = float(mm['pre_close'].iloc[0])
        lp = limit_px(pre_c, thr)
        p = mm['price'].values.astype(float); v = mm['vol'].values.astype(float)
        at = p >= lp - 0.005
        rec['m1_ok'] = True
        rec['t_seal'] = float(np.argmax(at)) if at.any() else np.nan      # 首次封板分钟序
        # 开板次数：封板后价格跌破涨停的次数（按分钟）
        n_open = 0; was = False
        for k in range(len(at)):
            if at[k]:
                was = True
            elif was:
                n_open += 1; was = False
        rec['n_open'] = n_open
        rec['seal_vshare'] = float(v[at].sum() / v.sum()) if v.sum() > 0 else np.nan
        rec['m1_zt'] = bool(at.any())
    else:
        rec['m1_ok'] = False
    # ---- 轴⑤：持有日（T+1/T+2）日内路径 ----
    for tag, ymd in (("p1", ymd_p1), ("p2", ymd_p2)):
        mh = minfile(code, ymd)
        if mh is not None and len(mh) >= 200:
            rec[f"{tag}_ok"] = True
            rec[f"{tag}_px"] = mh['price'].values.astype(float)
            rec[f"{tag}_pre"] = float(mh['pre_close'].iloc[0])
        else:
            rec[f"{tag}_ok"] = False
    rows.append(rec)

R = pd.DataFrame(rows)
print(f"带分钟的过程记录 {len(R)} | T-1 可得 {int(R.m1_ok.sum())} | T+1 可得 {int(R.p1_ok.sum())} | T+2 可得 {int(R.p2_ok.sum())}", flush=True)


def gates(s):
    g = [s['n'] >= 30, s['wr'] > 0.40, s['med'] > 0, s['mean'] > 0, s['ex'] is not None and s['ex'] > 0]
    return "".join("P" if x else "F" for x in g)


def stats(sub, col, base_col="base_net"):
    f = sub[col].values
    h1 = sub[sub.buy < SPLIT][col]; h2 = sub[sub.buy >= SPLIT][col]
    return dict(n=len(f), mean=float(np.mean(f)), med=float(np.median(f)), wr=float((f > 0).mean()),
                ex=float(np.mean(f) - sub[base_col].mean()) if base_col in sub else None,
                h1_med=float(np.median(h1)) if len(h1) > 8 else None,
                h2_med=float(np.median(h2)) if len(h2) > 8 else None)


def line(tag, s):
    return (f"{tag:28s} n={s['n']:4d} mean={s['mean']*100:+.2f}% med={s['med']*100:+.2f}% wr={s['wr']*100:.1f}% "
            f"ex={0 if s['ex'] is None else s['ex']*100:+.2f}% | h1/h2 {0 if s['h1_med'] is None else s['h1_med']*100:+.2f}/"
            f"{0 if s['h2_med'] is None else s['h2_med']*100:+.2f} | 闸 {gates(s)}")


out = {}

# ---------- 轴④ 首板日质量 ----------
print("\n=== 轴④ 首板日质量（分钟代理）===")
sub4 = R[R.m1_ok].copy()
if len(sub4) >= 30:
    q = sub4.t_seal.quantile([0.33, 0.67])
    out['seal'] = {}
    for tag, msk in (("早封板(t_seal≤p33)", sub4.t_seal <= q[0.33]),
                     ("晚封板(t_seal≥p67)", sub4.t_seal >= q[0.67]),
                     ("未封板(尾盘前未触板)", sub4.t_seal.isna()),
                     ("开板≥1次", sub4.n_open >= 1),
                     ("开板0次", sub4.n_open == 0),
                     ("封板期量占比≤p33", sub4.seal_vshare <= sub4.seal_vshare.quantile(0.33)),
                     ("封板期量占比≥p67", sub4.seal_vshare >= sub4.seal_vshare.quantile(0.67))):
        ss = stats(sub4[msk], 'base_net')
        out['seal'][tag] = ss
        print("  " + line(tag, ss))

# ---------- 轴⑤ 日内路径三臂 ----------
print("\n=== 轴⑤ 日内路径出场三臂（vs 同子样本基线）===")


def arm_drawdown(sub):
    """日内曾≥+2% 后自高点回撤>3% → 卖（该分钟价）；否则按基准"""
    nets = []
    for _, r in sub.iterrows():
        ep = r['entry_px']; done = False
        for tag in ("p1", "p2"):
            if not r.get(f"{tag}_ok"):
                continue
            p = r[f"{tag}_px"]
            if len(p) == 0:
                continue
            limit = limit_px(r[f"{tag}_pre"], A5.limit_thr(str(r['code'])))
            if float(np.max(p)) >= limit - 0.005:      # 涨停日不卖（与基准一致）
                continue
            runmax = np.maximum.accumulate(p)
            hit = np.where((runmax >= ep * 1.02) & (p <= runmax * 0.97))[0]
            if len(hit):
                px = float(p[hit[0]])
                nets.append((px / ep) * (1 - A5.COST_BUY) * (1 - A5.COST_SELL) - 1)
                done = True
            break
        if not done:
            nets.append(r['base_net'])
    return np.array(nets)


def arm_zhaban(sub):
    """持有日触板后跌破涨停 → 该分钟价卖；否则按基准"""
    nets = []
    for _, r in sub.iterrows():
        ep = r['entry_px']; done = False
        for tag in ("p1", "p2"):
            if not r.get(f"{tag}_ok"):
                continue
            p = r[f"{tag}_px"]
            limit = limit_px(r[f"{tag}_pre"], A5.limit_thr(str(r['code'])))
            at = p >= limit - 0.005
            if not at.any():
                break          # 未触板 → 按基准
            # 触板后开板
            after = np.where((~at) & (np.arange(len(at)) > int(np.argmax(at))))[0]
            if len(after):
                px = float(p[after[0]])
                nets.append((px / ep) * (1 - A5.COST_BUY) * (1 - A5.COST_SELL) - 1)
                done = True
            break
        if not done:
            nets.append(r['base_net'])
    return np.array(nets)


def arm_t1400(sub):
    """T+1 14:00（分钟序 180）未在涨停 → 该分钟价卖；否则按基准"""
    nets = []
    for _, r in sub.iterrows():
        ep = r['entry_px']; done = False
        if r.get("p1_ok"):
            p = r['p1_px']
            if len(p) > 180:
                limit = limit_px(r['p1_pre'], A5.limit_thr(str(r['code'])))
                if p[180] < limit - 0.005:
                    px = float(p[180])
                    nets.append((px / ep) * (1 - A5.COST_BUY) * (1 - A5.COST_SELL) - 1)
                    done = True
        if not done:
            nets.append(r['base_net'])
    return np.array(nets)


sub5 = R[R.p1_ok].copy()
for tag, fn in (("回撤止盈(+2%后回撤3%)", arm_drawdown), ("炸板即卖", arm_zhaban), ("14:00 未涨停即卖", arm_t1400)):
    nets = fn(sub5)
    tmp = sub5.copy(); tmp['v_net'] = nets
    s = stats(tmp, 'v_net')
    out[tag] = s
    print("  " + line(tag, s))
    # 触发比例
    trig = float(np.mean(np.abs(nets - sub5.base_net.values) > 1e-12))
    print(f"     触发改价比例 {trig*100:.1f}%")

json.dump(out, open(os.path.join(HERE, "daban_minute_0915.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1, default=float)
print("\nsaved daban_minute_0915.json")
