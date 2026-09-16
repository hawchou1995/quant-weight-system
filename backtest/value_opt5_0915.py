# -*- coding: utf-8 -*-
"""优化第三轮（R-buffett-opt3-0915）：回应三份方案的降回撤主张。

臂位（全部在 N2 行业上限 K=1 + 12 相位交叠 的统一标准下）：
  A0  基线 K=1（N=10）
  A1  K=1 + N=15                    ← 三份方案共同主张
  A2  K=1 + N=20
  A3  K=1 + 剔除金融地产（银行/非银/房地产）  ← Gemini/DeepSeek 主张
  A4  K=1 + 风险簇上限（60日相关>0.7 视为同簇，每簇≤1）← ChatGPT 头号主张
  A5  K=1 + 剔金融地产 + N=15（组合拳）

另：A0 的**单相位回撤分布**（DeepSeek 质疑"−35.74% 是平滑幻觉"）
"""
import gc
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import value_lh_0914 as V           # noqa: E402
import value_arms_0914 as A         # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "value_opt5_0915.json")
START, RB, SLIP, TOPN = "2018-01-02", 250, 0.002, 10
FIN = {"银行", "非银金融", "房地产"}


def _greedy(scs, grp, key_fn, capfn, topn, offset, rebal=RB):
    """通用贪心选择：按 scs 升序（小=优）遍历，逐只判断是否允许入选。"""
    arr = np.full(scs.values.shape, np.nan, dtype="float32")
    rows = scs.values
    for di in range(offset, len(scs), rebal):
        row = rows[di]
        ok = np.isfinite(row)
        if ok.sum() < topn:
            continue
        order = np.argsort(np.where(ok, row, np.inf))
        cnt, pick = {}, []
        for ci in order:
            if not np.isfinite(row[ci]):
                break
            keys = key_fn(di, ci)
            if any(cnt.get(k, 0) >= capfn(k) for k in keys):
                continue
            for k in keys:
                cnt[k] = cnt.get(k, 0) + 1
            pick.append(ci)
            if len(pick) == topn:
                break
        for ri, ci in enumerate(pick):
            arr[di, ci] = ri
    return pd.DataFrame(arr, index=scs.index, columns=scs.columns)


def corr_cluster_key(feat, cols, topn_cand=60, win=120, thr=0.70):
    """返回 key_fn(di, ci) -> [行业键, 簇键]（簇用贪心并查在候选集内构建）。"""
    ret = feat["close"].pct_change()
    cache = {}

    def key_fn(di, ci):
        return [f"IND:{cols[ci]}", f"CL:{cache.get(di, {}).get(ci, ci)}"]

    def build(di, cand):
        if di in cache:
            return
        d = ret.index[di]
        sub = ret.loc[:d].tail(win)[[cols[c] for c in cand]]
        if len(sub) < 30:
            cache[di] = {}
            return
        C = sub.corr().values
        lab, nxt = {}, 0
        for i, ci in enumerate(cand):
            if ci in lab:
                continue
            lab[ci] = nxt
            for j in range(i + 1, len(cand)):
                cj = cand[j]
                if cj in lab:
                    continue
                if np.isfinite(C[i, j]) and C[i, j] > thr:
                    lab[cj] = nxt
            nxt += 1
        cache[di] = lab
        if len(cache) > 30:
            cache.pop(next(iter(cache)))
    return key_fn, build


def eval_stag(feat, build_score_fn, tag, phases=12):
    """build_score_fn(offset) -> score DataFrame（逐相位重算选择）。"""
    subs, shs, mdds = [], [], []
    for k in range(phases):
        o = int(round(k * RB / phases))
        sc = build_score_fn(o)
        r = V.run(feat, sc, rebal=RB, topn=TOPN, slip=SLIP, offset=o, start=START, exclude=EX)
        s = r["equity"]; subs.append(s / s.iloc[0])
        shs.append(r["sharpe"]); mdds.append(float(((s / s.cummax()) - 1).min()))
        del sc; gc.collect()
    S = pd.concat(subs, axis=1).ffill().dropna()
    stag = S.mean(axis=1)
    ret = stag.pct_change().dropna()
    yrs = (stag.index[-1] - stag.index[0]).days / 365.25
    tot = stag.iloc[-1] - 1
    yr = stag.resample("YE").last().pct_change().dropna()
    return dict(tag=tag, ann=float((1 + tot) ** (1 / yrs) - 1),
                sharpe=float(ret.mean() / ret.std() * np.sqrt(252)),
                mdd=float(((stag / stag.cummax()) - 1).min()),
                win_year=float((yr > 0).mean()),
                single_mdd_med=float(np.median(mdds)), single_mdd_min=float(np.min(mdds)),
                single_mdd_max=float(np.max(mdds)), single_sharpe_med=float(np.median(shs)),
                single_mdd_all=mdds)


print("=" * 110)
print("优化第三轮 · 统一标准：N2 行业上限 K=1 + 12 相位交叠｜2018+ / 20bp")
print("=" * 110)

feat = V.load_features()
if "_raw_close" not in feat:
    feat["_raw_close"] = V.raw_close(feat, validate=False)
f = A.build_factors(feat, None)
EX = V.st_mask(feat)
cols = list(feat["close"].columns)
ind = A.industry_of(feat)
grp = pd.Series({c: ind.get(c) for c in cols})
base = A.make_score(f["roe_pb"], None)
keep = feat["dates"] >= pd.Timestamp(START)
dates = feat["dates"][keep]
scs = base.loc[dates]
fill = scs.rank(axis=1, pct=True, ascending=False) + 1000

k_ind = lambda di, ci: [f"IND:{cols[ci]}"]                     # 行业上限 K=1
cap_1 = lambda k: 1
key_cl, build_cl = corr_cluster_key(feat, cols)

res = {}


def run_arm(tag, key_fn, capfn, build=None, topn=TOPN):
    def bf(o):
        if build:
            for di in range(o, len(scs), RB):
                row = scs.values[di]
                ok = np.isfinite(row)
                if ok.sum() < topn:
                    continue
                cand = list(np.argsort(np.where(ok, row, np.inf))[:60])
                build(di, cand)
        cs = _greedy(scs, grp, key_fn, capfn, topn, o)
        return cs.fillna(fill)
    r = eval_stag(feat, bf, tag)
    res[tag] = r
    print(f"{tag:34s} 年化 {r['ann']:7.2%}  夏普 {r['sharpe']:.3f}  交叠回撤 {r['mdd']:8.2%}  "
          f"年度胜率 {r['win_year']:4.0%}  |单相位回撤 中位 {r['single_mdd_med']:7.2%} "
          f"最差 {r['single_mdd_min']:7.2%}", flush=True)
    return r


run_arm("A0 K=1（N=10，基线）", k_ind, cap_1)
gc.collect()
run_arm("A1 K=1 + N=15", k_ind, cap_1, topn=15)
gc.collect()
run_arm("A2 K=1 + N=20", k_ind, cap_1, topn=20)
gc.collect()

# A3 剔除金融地产：把这三个行业的 score 置 NaN（=不可选）
ex_fin = EX.copy()
if "ind" in feat:
    pass
fin_mask = pd.DataFrame(False, index=feat["dates"], columns=cols)
for c in cols:
    if ind.get(c) in FIN:
        fin_mask[c] = True


def bf_fin(o):
    cs = _greedy(scs, grp, k_ind, cap_1, TOPN, o)
    cs = cs.mask(fin_mask.loc[dates])
    return cs.fillna(fill)


r = eval_stag(feat, bf_fin, "A3 K=1 + 剔除金融地产")
res["A3 K=1 + 剔除金融地产"] = r
print(f"{'A3 K=1 + 剔除金融地产':34s} 年化 {r['ann']:7.2%}  夏普 {r['sharpe']:.3f}  交叠回撤 {r['mdd']:8.2%}  "
      f"年度胜率 {r['win_year']:4.0%}  |单相位回撤 中位 {r['single_mdd_med']:7.2%} 最差 {r['single_mdd_min']:7.2%}", flush=True)
gc.collect()
run_arm("A4 K=1 + 风险簇上限1(相关>0.7)", key_cl, cap_1, build=build_cl)
gc.collect()

json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n[opt5] 落盘 {OUT}")
