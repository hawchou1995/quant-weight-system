# -*- coding: utf-8 -*-
"""
Top1 交付（逐年净值曲线 + 事件清单）+ 与生产「超跌低开低吸」(qlch B4_K3) 对比
================================================================================
Side A：K>=2 见底共振 + 当日共振家数>=20 + 固定持 5 日（T+1 开盘买 → +5 日开盘卖）｜成本单边 0.575%/0.10%
Side B：qlch 生产口径（B4 分位滤网 + 熊市门 MA20 + ret20(T-1)<=-7.31% ；T+1 低开 gap∈[-5%,-2%] 开盘买；
        E2 出场 = 次日收盘卖）｜直接 import qlch_paper_20260921 复用其 load_all/build_signals（零口径漂移）
窗口：2016-06-01 → 2026-09-23（两侧一致）
"""
import os, sys, time, json
from collections import defaultdict
import numpy as np, pandas as pd

T0 = time.time()
def log(m): print(f"[{time.time()-T0:7.1f}s] {m}", flush=True)

BASE = r'D:\Documents\Workbuddy\股票基金\quant-weight-system'
BK = os.path.join(BASE, 'backtest')
OUT = os.path.join(BK, 'jiandi_top_grid_0924_out')
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, BK)

BS = pd.Timestamp('2016-06-01')
W_LO, W_HI = '2016-06-01', '2026-09-23'
COST_S1, COST_S2 = 0.00575, 0.00100   # 单边口径；S2=生产档 20bp 往返

NAMES = json.load(open(os.path.join(BASE, 'data_full_names.json'), encoding='utf-8'))
def nm(code):
    return NAMES.get(code) or NAMES.get(code[2:]) or ''

def net(bo, so, c):
    return so * (1 - c) / (bo * (1 + c)) - 1

def stats(rets):
    r = np.asarray(rets, float); r = r[np.isfinite(r)]
    wins, losses = r[r > 0], r[r < 0]
    return dict(n=int(len(r)), mean=round(float(r.mean()) * 100, 3),
                med=round(float(np.median(r)) * 100, 3), wr=round(float((r > 0).mean()) * 100, 2),
                avg_win=round(float(wins.mean()) * 100, 3) if len(wins) else None,
                avg_loss=round(float(losses.mean()) * 100, 3) if len(losses) else None,
                pf=round(float(wins.mean() / abs(losses.mean())), 2) if len(wins) and len(losses) else None)

# =============== 交易日基准（HS300） ===============
idx = pd.read_csv(os.path.join(BASE, 'index_000300.csv'))
idx['date'] = pd.to_datetime(idx['date']); idx = idx.sort_values('date').reset_index(drop=True)
idx = idx[(idx['date'] >= W_LO) & (idx['date'] <= W_HI)]
hs = idx.set_index('date')['close']
TRADING_DAYS = len(hs)
YEARS = (pd.Timestamp(W_HI) - pd.Timestamp(W_LO)).days / 365.25

# =============== Side A：Top1 ===============
import jiandi_signal_0906 as JG
raw = pd.read_pickle(os.path.join(BASE, 'v8_factor_cache.pkl'))
cache = {c: df.sort_index() for c, df in raw.items() if df is not None and JG.board_of(c) == 'main'}
SIG_KEYS = ('rushi', 'jihui', 'jiandi', 'kuaixian', 'laiLin', 'deng')
k2 = []; res_daily = defaultdict(int)
for code, df in cache.items():
    if len(df) < 70: continue
    sm = JG.jiandi_signals(code, df)
    sig6 = np.stack([np.asarray(sm[k], bool) for k in SIG_KEYS], axis=1)
    cnt6 = sig6.sum(axis=1)
    o = df['open'].to_numpy(); c = df['close'].to_numpy(); n = len(df); dates = df.index
    bad = (~np.isfinite(o)) | (~np.isfinite(c)) | (o <= 0) | (c <= 0)
    for i in np.where(cnt6 >= 2)[0]:
        if dates[i] < BS: continue
        res_daily[dates[i]] += 1
        B = i + 1
        if B >= n or bad[B]: continue
        k2.append((dates[i], code, B, bad))
log(f"Side A: K>=2 事件池 {len(k2)}")
A_events = []
for sd, code, B, bad in k2:
    if res_daily[sd] < 20: continue
    df = cache[code]; n = len(df); sell = B + 5
    if sell >= n or bad[B:sell + 1].any(): continue
    bo = float(df['open'].iloc[B]); so = float(df['open'].iloc[sell])
    A_events.append((sd, code, B, sell, int(res_daily[sd]), bo, so))
log(f"Side A Top1（阈>=20, N=5）事件 = {len(A_events)}")
retsA_s1 = [net(bo, so, COST_S1) for *_x, bo, so in A_events]
retsA_s2 = [net(bo, so, COST_S2) for *_x, bo, so in A_events]
A_s1, A_s2 = stats(retsA_s1), stats(retsA_s2)
log(f"Side A @S1(0.575%): {A_s1}")
log(f"Side A @S2(0.10%):  {A_s2}")

# ---- Top1 事件清单
rowsA = []
for k, (sd, code, B, sell, rc, bo, so) in enumerate(A_events, 1):
    dts = cache[code].index
    rowsA.append(dict(seq=k, code=code, name=nm(code), signal_date=str(sd)[:10],
                      buy_date=str(dts[B])[:10], sell_date=str(dts[sell])[:10],
                      buy_px=round(bo, 3), sell_px=round(so, 3),
                      ret_s1_pct=round(float(net(bo, so, COST_S1)) * 100, 3), res_count=rc))
pd.DataFrame(rowsA).to_csv(os.path.join(OUT, 'top1_events_0924.csv'), index=False, encoding='utf-8-sig')
log("SAVED top1_events_0924.csv (%d 行)" % len(rowsA))

# ---- Top1 NAV（S1）+ 年度
daily = defaultdict(list)
for sd, code, B, sell, rc, bo, so in A_events:
    df = cache[code]; o = df['open'].to_numpy(); c = df['close'].to_numpy(); dts = df.index
    daily[dts[B]].append(c[B] / o[B] - 1 - COST_S1)
    for kk in range(B + 1, sell):
        daily[dts[kk]].append(c[kk] / c[kk - 1] - 1)
    daily[dts[sell]].append(o[sell] / c[sell - 1] - 1 - COST_S1)
s_ = pd.Series({d: float(np.mean(v)) for d, v in daily.items()}).sort_index()
full = pd.date_range(s_.index[0], s_.index[-1], freq='B')
s_ = s_.reindex(full, fill_value=0.0)
nav = (1 + s_).cumprod()
pd.DataFrame({'date': nav.index.astype(str), 'nav': nav.values}).to_csv(
    os.path.join(OUT, 'top1_nav_daily_0924.csv'), index=False, encoding='utf-8-sig')
nav_tot = float(nav.iloc[-1] - 1)
span = (nav.index[-1] - nav.index[0]).days / 365.25
nav_cagr = (nav.iloc[-1]) ** (1 / span) - 1
nav_dd = float((nav / nav.cummax() - 1).min())
nav_sh = float(s_.mean() / s_.std() * np.sqrt(252))
log(f"Top1 NAV: total={nav_tot*100:.2f}% cagr={nav_cagr*100:.2f}% maxdd={nav_dd*100:.2f}% sharpe={nav_sh:.3f}")
yr_rows = []
for y in range(2016, 2027):
    m_ = nav.index.year == y
    if not m_.any(): continue
    ny = nav[m_]
    prev = nav[nav.index < ny.index[0]]
    base = float(prev.iloc[-1]) if len(prev) else 1.0
    yrets = [net(bo, so, COST_S1) for sd, code, B, sell, rc, bo, so in A_events if pd.Timestamp(sd).year == y]
    yr_rows.append(dict(year=y, nav_ret_pct=round(float(ny.iloc[-1] / base - 1) * 100, 2),
                        nav_end=round(float(ny.iloc[-1]), 4),
                        year_maxdd_pct=round(float((ny / ny.cummax() - 1).min()) * 100, 2),
                        n_events=len(yrets),
                        mean_pct=round(float(np.mean(yrets)) * 100, 2) if yrets else None,
                        med_pct=round(float(np.median(yrets)) * 100, 2) if yrets else None,
                        wr_pct=round(float((np.array(yrets) > 0).mean()) * 100, 1) if yrets else None))
pd.DataFrame(yr_rows).to_csv(os.path.join(OUT, 'top1_yearly_0924.csv'), index=False, encoding='utf-8-sig')
log("SAVED top1_yearly_0924.csv")
for r in yr_rows:
    log("  %d: nav %+6.2f%% end=%.4f maxdd %+6.2f%% | 事件 %4d 均 %+5.2f%% 中 %+5.2f%% 胜 %.0f%%" % (
        r['year'], r['nav_ret_pct'], r['nav_end'], r['year_maxdd_pct'],
        r['n_events'], r['mean_pct'] or 0, r['med_pct'] or 0, r['wr_pct'] or 0))

# ---- 图
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.family'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    fig, ax = plt.subplots(2, 1, figsize=(12, 6.6), sharex=True, gridspec_kw={'height_ratios': [3, 1]})
    hsn = hs.reindex(nav.index).ffill(); hsn = hsn / hsn.iloc[0]
    ax[0].plot(nav.index, nav.values, label='Top1 净值（共振≥20 · N=5 · 单边0.575%）', color='#c0392b', lw=1.7)
    ax[0].plot(hsn.index, hsn.values, label='沪深300（归一）', color='#7f8c8d', lw=1.2, alpha=0.85)
    ax[0].legend(loc='upper left'); ax[0].grid(alpha=0.25)
    ax[0].set_title('超跌信号共振 Top1 · 逐年净值曲线（2016-06 → 2026-09 · 等权 NAV · 事件级全参与）')
    ddn = nav / nav.cummax() - 1
    ax[1].fill_between(ddn.index, ddn.values * 100, 0, color='#c0392b', alpha=0.35)
    ax[1].grid(alpha=0.25); ax[1].set_ylabel('回撤 %')
    fig.tight_layout(); fig.savefig(os.path.join(OUT, 'top1_nav_0924.png'), dpi=130)
    log("SAVED top1_nav_0924.png")
except Exception as e:
    log(f"CHART FAILED: {e}")

# =============== Side B：qlch 生产口径 ===============
os.environ.setdefault('QLCH_VARIANT', 'B4')
import qlch_paper_20260921 as Q
Pq = Q.load_all(); Sq = Q.build_signals(Pq)
cal, codesq, cand, gap = Sq['cal'], Sq['codes'], Sq['cand'], Sq['gap']
Oq, Cq, validq = Sq['open'], Sq['close'], Sq['valid']
Tq, Nq = Cq.shape
log(f"qlch 面板: {Tq} x {Nq}, {cal[0]} -> {cal[-1]}")
B_events = []
cand_days = set(); buy_days = set(); n_cand_tot = 0; buy_day_counts = defaultdict(int)
for t in range(1, Tq - 1):
    if cal[t] < W_LO: continue
    if cal[t] > W_HI: break
    cT = cand[t - 1]
    if cT.any() and cal[t - 1] >= W_LO:
        cand_days.add(cal[t])
        n_cand_tot += int(cT.sum())
    row = cT & np.isfinite(gap[t]) & (gap[t] >= Q.GAP_LO) & (gap[t] <= Q.GAP_HI) & validq[t]
    for j in np.where(row)[0]:
        bo, so = float(Oq[t, j]), float(Cq[t + 1, j])
        if not (np.isfinite(bo) and np.isfinite(so)) or bo <= 0 or so <= 0: continue
        B_events.append((cal[t], codesq[j], bo, so))
        buy_days.add(cal[t]); buy_day_counts[cal[t]] += 1
log(f"Side B qlch: 候选(T日) 合计 {n_cand_tot}（{len(cand_days)} 个候选日）；成交事件 {len(B_events)}")
retsB_s1 = [net(bo, so, COST_S1) for _d, _c, bo, so in B_events]
retsB_s2 = [net(bo, so, COST_S2) for _d, _c, bo, so in B_events]
B_s1, B_s2 = stats(retsB_s1), stats(retsB_s2)
log(f"Side B @S1(0.575%): {B_s1}")
log(f"Side B @S2(0.10%):  {B_s2}")

# =============== 对比 ===============
codesA = set(c for _sd, c, _B, _s, _r, _b, _o in A_events)
codesB = set(c for _d, c, _b, _o in B_events)
inter = codesA & codesB
jac = len(inter) / max(len(codesA | codesB), 1)
pairsA = set((c, str(sd)[:10]) for sd, c, _B, _s, _r, _b, _o in A_events)
# 我方事件级 (code, buy_date)
pairsA2 = set((c, str(cache[c].index[B])[:10]) for _sd, c, B, _s, _r, _b, _o in A_events)
pairsB = set((c, d) for d, c, _b, _o in B_events)
common_pairs = pairsA2 & pairsB
A_in_B = sum(1 for _sd, c, *_x in A_events if c in codesB) / max(len(A_events), 1)
B_in_A = sum(1 for _d, c, *_x in B_events if c in codesA) / max(len(B_events), 1)
yB = defaultdict(int); mB = defaultdict(list)
for d, c, bo, so in B_events:
    yB[d[:4]] += 1; mB[d[:4]].append(net(bo, so, COST_S1))
buyday_over3 = sum(1 for d, n_ in buy_day_counts.items() if n_ > 3)

cmpout = dict(
    window=[W_LO, W_HI],
    sideA=dict(name='Top1 超跌信号共振（阈>=20, N=5, 开盘卖）', events=len(A_events),
               events_per_year=round(len(A_events) / YEARS, 1),
               events_per_trading_day=round(len(A_events) / TRADING_DAYS, 3),
               unique_codes=len(codesA), stats_S1=A_s1, stats_S2=A_s2,
               nav_total=round(nav_tot * 100, 2), nav_cagr=round(nav_cagr * 100, 2),
               nav_maxdd=round(nav_dd * 100, 2), nav_sharpe=round(nav_sh, 3)),
    sideB=dict(name='qlch 超跌低开低吸（B4+熊市门, T+1低开买, E2次日收盘卖）', events=len(B_events),
               candidates=n_cand_tot, cand_days=len(cand_days), buy_days=len(buy_days),
               events_per_year=round(len(B_events) / YEARS, 1),
               events_per_trading_day=round(len(B_events) / TRADING_DAYS, 3),
               unique_codes=len(codesB), stats_S1=B_s1, stats_S2=B_s2,
               buy_days_gt3=dict(n=buyday_over3, note='生产 K=3 槽位在这些日会随机取 3'),
               yearly={y: [yB[y], round(float(np.mean(mB[y])) * 100, 2),
                           round(float(np.median(mB[y])) * 100, 2)] for y in sorted(yB)}),
    overlap=dict(unique_intersection=len(inter), jaccard=round(jac, 4),
                 A_event_code_in_B_pct=round(A_in_B * 100, 2),
                 B_event_code_in_A_pct=round(B_in_A * 100, 2),
                 same_code_same_buy_date=len(common_pairs),
                 same_signal_date=len(pairsA & set((c, d) for d, c, _b, _o in B_events))),
    notes=[
        '两侧成本均为单边口径的乘法式：S1=0.575%（本格基准）/ S2=0.10%（=qlch 生产档 20bp 往返）',
        'qlch 官方对照（X4 出场时代, 20bp）：事件级全集 n=3881 / 均值 +9.29% / 中位 +9.89% / 胜率 69.9%；本次为 E2 出场口径复算',
        'qlch 复算为「全部合格事件」（不含 K=3 槽位/现金 ETF 叠加）；生产组合级子集另有取中率折损（X4 时代 ~3.7%）',
        'Side A 为事件级全参与等权 NAV（阈值≥20 的口径内全体）'])
with open(os.path.join(OUT, 'top1_vs_qlch_0924.json'), 'w', encoding='utf-8') as fh:
    json.dump(cmpout, fh, ensure_ascii=False, indent=1, default=str)
log("SAVED top1_vs_qlch_0924.json")
print('===== 对比摘要 =====')
print(json.dumps(cmpout, ensure_ascii=False, indent=1, default=str)[:3000])
