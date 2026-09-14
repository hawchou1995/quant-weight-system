# -*- coding: utf-8 -*-
"""短线系统因子/权重穷举（2026-09-14，用户拍板 Q1-Q5）
A 线（打分制四因子权重×mask，口径=short_score 公式原样，不改内部公式）：
  L1: 权重 {等权, 生产强牛(25,20,25,30), 生产弱牛(20,20,30,30), 原版(30,25,25,20), 反转等权} × mask 全 16 × reversal 2 = 160 臂
  L2: L1 Top3 配置 × 步长 20% 单纯形全枚举（56 向量 × 2 reversal）= 336 臂（上限裁剪）
  对照: Dirichlet 随机权重 300（同池）
  回测: 向量化分段（每 H=15 日一期，T 收盘选 Top10 → T+1 开盘买 → T+1+H 开盘卖；成本 1.15%/期；申报与 run_short 事件引擎的差异）
B 线（KHunter 链增强）见独立脚本（本脚本先交付 A 线 + 威科夫新因子的过滤测试）
禁止改因子内部公式（Q4 拍板）。
"""
import numpy as np, pandas as pd, pickle, json, time, math, itertools
from pathlib import Path

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
COST = 0.0115
TOP_N = 10
H = 15
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

with open(OUT / "oss_panel_0913.pkl", "rb") as fh:
    P = pickle.load(fh)
cal = P["cal"]; codes = P["codes"]; st_mask = P["st_mask"]
ND, NC = P["close"].shape
O = P["open"].astype(np.float64); Hm = P["high"].astype(np.float64)
Lm = P["low"].astype(np.float64); C = P["close"].astype(np.float64)
V = P["vol"].astype(np.float64); AMT = P["amt"].astype(np.float64)
close_ff = pd.DataFrame(C).ffill().to_numpy()

# ---- 因子（与 short_factors 公式逐条一致；仅加"威科夫超买热度"新因子用于 B 测试）----
Cm = pd.DataFrame(close_ff)
mom20 = (Cm / Cm.shift(20) - 1).to_numpy()
ret5 = (Cm / Cm.shift(5) - 1).to_numpy()
vr5 = (pd.DataFrame(V).rolling(5).mean() / pd.DataFrame(V).rolling(20).mean().replace(0, np.nan)).to_numpy()
vp = ((ret5 > 0) & (vr5 > 1)).astype(float)
hi20s = pd.DataFrame(Hm).rolling(20).max().shift(1).to_numpy()
lo20s = pd.DataFrame(Lm).rolling(20).min().shift(1).to_numpy()
with np.errstate(all="ignore"):
    dnc = np.clip((close_ff - lo20s) / (hi20s - lo20s), 0, 1)
vol20 = (pd.DataFrame(ret5).rolling(20).std() * math.sqrt(252)).to_numpy()
mid = Cm.rolling(20).mean()
sd = Cm.rolling(20).std()
with np.errstate(all="ignore"):
    bw = (2 * sd / mid).to_numpy()
    ret1 = Cm.pct_change().to_numpy()
# 威科夫新因子: 超买热度 = 近5日(单日涨>5% 且 vr5>1.5)计数
big_up = ((ret1 > 0.05) & (vr5 > 1.5)).astype(float)
over5 = pd.DataFrame(big_up).rolling(5, min_periods=3).sum().to_numpy()
log("factors built")

# ---- elig（生产 _mk_cfg: min_amt=3e7; min_px=1.0; 剔ST/退）----
_nh = pd.read_csv(BASE / "data_fundamental" / "name_hist.csv", dtype={"code": str}).sort_values("TRADE_DATE").groupby("code").tail(1)
_name = _nh.set_index("code")["SECURITY_NAME_ABBR"].astype(str)
RISK = set(_name[_name.str.contains("ST") | _name.str.contains("退")].index)
risk_mask = np.array([c in RISK for c in codes])
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
hist_n = np.cumsum(np.isfinite(O), axis=0)
ELIG = (np.isfinite(O) & np.isfinite(C) & (amt20 >= 3e7) & (~risk_mask[None, :])
        & (hist_n >= 150) & (C >= 1.0))

# ---- 分段收益面板: 每段 seg_ret[t] = O[t+1+H]/O[t+1]-1（T=t 选股, t+1 开盘买, 持 H 日）----
o1 = np.full((ND, NC), np.nan)
o1[:ND-1] = O[1:]           # o1[t] = O[t+1]
oH = np.full((ND, NC), np.nan)
oH[:ND-(H+1)] = O[H+1:]     # oH[t] = O[t+H+1]
with np.errstate(all="ignore"):
    seg = oH / o1 - 1  # [t] = T=t 选股后持有的段收益
# 自检: 段收益非零比例（防错位 bug 复发）
_chk = seg[20]
log(f"seg 自检: t=20 非NaN比例={np.isfinite(_chk).mean():.3f} 非零比例={np.nanmean(np.abs(_chk)>1e-9):.3f}")
assert np.nanmean(np.abs(_chk) > 1e-9) > 0.5, "seg 构造错位（段收益近零）"

def seg_returns(score, top_n=TOP_N, cost=COST):
    """向量化分段：每 H 日取 score TopN（elig 内）→ 段收益均值 - 成本 → 净值"""
    n_seg = (ND - 1 - H) // H
    seg_rs = []
    for s in range(n_seg):
        t = s * H
        ok = ELIG[t] & np.isfinite(score[t])
        cand = np.flatnonzero(ok)
        if len(cand) == 0:
            seg_rs.append(0.0); continue
        # 剔除当日涨停（不可买, 与生产近似）
        prev = close_ff[t - 1] if t > 0 else close_ff[t]
        ok2 = cand[np.where(np.isfinite(prev[cand]), O[t + 1][cand] < prev[cand] * 1.098, True)]
        if len(ok2) == 0:
            seg_rs.append(0.0); continue
        ordj = ok2[np.argsort(-score[t][ok2])][:top_n]
        r = seg[t][ordj]
        r = r[np.isfinite(r)]
        seg_rs.append(float(np.mean(r)) - cost if len(r) else 0.0)
    arr = np.array(seg_rs)
    eq = np.cumprod(1 + arr)
    if len(eq) == 0: return dict(sharpe=0, ann=0, total=0, n_seg=0)
    yrs = len(arr) * H / 244.0
    total = float(eq[-1] - 1)
    ann = (eq[-1]) ** (1 / yrs) - 1 if yrs > 0 and eq[-1] > 0 else -1
    sharpe = float(np.mean(arr) / (np.std(arr) + 1e-12) * np.sqrt(244 / H))
    mdd = float((eq / np.maximum.accumulate(eq) - 1).min())
    by_year = {}
    # 年度收益（按段起点年份）
    for y in sorted(set(cal[s * H][:4] for s in range(n_seg))):
        idxs = [s for s in range(n_seg) if cal[s * H][:4] == y]
        if idxs:
            by_year[y] = float(np.prod(1 + arr[idxs]) - 1)
    return dict(sharpe=sharpe, ann=float(ann), total=total, mdd=mdd, n_seg=n_seg, by_year=by_year)

# ---- 打分矩阵（short_score 公式原样向量化）----
def score_of(weights, mask, reversal):
    w = [max(0.0, float(x)) for x in weights]
    m = [1 if x else 0 for x in mask]
    tot = sum(wi for wi, mi in zip(w, m) if mi)
    if tot <= 0: return np.zeros((ND, NC))
    S = np.zeros((ND, NC))
    if m[0]:
        mom = -mom20 if reversal else mom20
        S += w[0] * np.clip(np.where(np.isfinite(mom), mom, 0) / 0.15, 0, 1)
    if m[1]:
        f = 15 / 25 * np.where(np.isfinite(vp), vp, 0)
        f += 10 / 25 * np.clip((np.where(np.isfinite(vr5), vr5, np.nan) - 0.5) / 2.0, 0, 1)
        S += w[1] * np.where(np.isfinite(f), f, 0)
    if m[2]:
        S += w[2] * np.where(np.isfinite(dnc), dnc, 0)
    if m[3]:
        f = np.clip(1 - (np.where(np.isfinite(vol20), vol20, np.nan) - 0.20) / 0.60, 0, 1)
        S += w[3] * np.where(np.isfinite(f), f, 0)
    return S / tot * 100

# ---- L1: 5 权重 × 16 mask × 2 reversal = 160 ----
WL1 = {
    "equal": (25, 25, 25, 25),
    "prod_strong": (25, 20, 25, 30),
    "prod_weak": (20, 20, 30, 30),
    "orig": (30, 25, 25, 20),
    "rev_equal": (25, 25, 25, 25),
}
log("=== L1: 5×16×2 = 160 臂 ===")
rows = []
for wn, w in WL1.items():
    for mask in itertools.product([0, 1], repeat=4):
        if sum(mask) == 0: continue
        for rev in ([True] if wn == "rev_equal" else [False, True]):
            sc = score_of(w, mask, rev)
            r = seg_returns(sc)
            rows.append(dict(phase="L1", wname=wn, weights=list(w), mask=list(mask), reversal=rev, **r))
rows.sort(key=lambda r: -r["sharpe"])
for r in rows[:10]:
    log(f"L1 {r['wname']:11s} mask={r['mask']} rev={int(r['reversal'])} | S={r['sharpe']:.3f} ann={r['ann']*100:+.2f}% mdd={r['mdd']*100:.1f}% tot={r['total']*100:+.1f}%")
log(f"L1 done: {len(rows)} 臂, 最优 S={rows[0]['sharpe']:.3f}")

# ---- L2: Top3 (mask,reversal) × 步长20% 单纯形 56 向量 ----
from scipy.special import comb as ncomb
log("=== L2: 单纯形步长 20%（C(8,3)=56 向量）===")
simplex = []
for a in range(0, 101, 20):
    for b in range(0, 101 - a, 20):
        for c in range(0, 101 - a - b, 20):
            d = 100 - a - b - c
            simplex.append((a, b, c, d))
log(f"simplex 向量数: {len(simplex)}")
top3 = rows[:3]
l2 = []
for cfg in top3:
    for wv in simplex:
        sc = score_of(wv, cfg["mask"], cfg["reversal"])
        r = seg_returns(sc)
        l2.append(dict(phase="L2", base=dict(mask=cfg["mask"], reversal=cfg["reversal"], wname=cfg["wname"]),
                       weights=list(wv), **r))
l2.sort(key=lambda r: -r["sharpe"])
for r in l2[:10]:
    log(f"L2 base={r['base']['wname']} mask={r['base']['mask']} rev={int(r['base']['reversal'])} w={r['weights']} | S={r['sharpe']:.3f} ann={r['ann']*100:+.2f}%")
log(f"L2 done: {len(l2)} 臂, 最优 S={l2[0]['sharpe']:.3f}")

# ---- 随机 Dirichlet 对照 300 ----
log("=== 对照: Dirichlet 随机权重 300 ===")
rng = np.random.default_rng(7)
best_mask = rows[0]["mask"]; best_rev = rows[0]["reversal"]
ctrl = []
for i in range(300):
    wv = tuple(int(x) for x in (rng.dirichlet([1, 1, 1, 1]) * 100))
    wv = (wv[0], wv[1], wv[2], 100 - wv[0] - wv[1] - wv[2])
    if wv[3] < 0: continue
    sc = score_of(wv, best_mask, best_rev)
    r = seg_returns(sc)
    ctrl.append(r["sharpe"])
    if (i + 1) % 100 == 0: log(f"  ctrl {i+1} t={time.time()-t0:.0f}s")
ctrl = np.array(ctrl)
log(f"对照: median={np.median(ctrl):.3f} p90={np.percentile(ctrl,90):.3f} max={ctrl.max():.3f}")
log(f"最优 L2 S={l2[0]['sharpe']:.3f} 在对照分布的分位: {(ctrl < l2[0]['sharpe']).mean()*100:.1f}%")

# ---- B 线预览: 威科夫超买热度过滤（在最优打分基础上）----
log("=== B 线: 超买热度过滤（最优配置 + over5 阈值）===")
best = l2[0]
for th in [0, 1, 2, 3]:
    sc = score_of(best["weights"], best["base"]["mask"], best["base"]["reversal"])
    if th > 0:
        sc = np.where((over5 < th) | ~np.isfinite(over5), sc, np.nan)  # over5>=th 排除
    r = seg_returns(sc)
    log(f"over5<{th} 过滤: S={r['sharpe']:.3f} ann={r['ann']*100:+.2f}% mdd={r['mdd']*100:.1f}%")

out = dict(meta=dict(window="2021-01-04~2026-09-11", pool=f"{NC} 主板", top_n=TOP_N, hold=H, cost=COST,
                     n_trials=len(rows) + len(l2) + 300, note="分段向量化口径（申报与 run_short 事件引擎差异）"),
           L1=rows[:40], L2=l2[:40], ctrl=dict(median=float(np.median(ctrl)), p90=float(np.percentile(ctrl, 90)),
           max=float(ctrl.max()), best_l2=l2[0]["sharpe"], best_l2_pct=float((ctrl < l2[0]["sharpe"]).mean()*100)))
json.dump(out, open(OUT / "short_exhaust_0914.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
log("saved short_exhaust_0914.json DONE")
