# -*- coding: utf-8 -*-
"""优化第二轮（R-buffett-opt2-0915）：行业中性化 × 交叠调仓 × 波动率倒数加权。

依据（value_attrib_0915.json 归因）：
  ① 金融地产合计 16.7% → 行业集中是回撤来源之一
  ② 最大回撤期（2018-01~2020-04，−58.45%）同期沪深300 仅 −6.61% → **回撤是个股/行业驱动，不是 beta**
  ③ 单相位年化 5.90% vs 9 相位中位 16.30% → 相位散布过大，必须交叠表达

臂位设计（用户 Q1-Q3 拍板）：
  BASE    : roe_pb 全市场排序（等权，原冠军）
  N1      : 行业内相对票息 = roe_pb − 同行业中位数
  N2      : 行业上限 K=2（同行业最多 2 只）
  N3      : 行业内分位（行业内 rank → 全市场排序）
  W1      : BASE + 波动率倒数加权
  N1+W1   : 行业内相对 + 波动率倒数加权
评估标准：**12 相位交叠合成**（Q2 新标准）+ 单相位 9 档中位对照
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import value_lh_0914 as V           # noqa: E402
import value_arms_0914 as A         # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "value_opt4_0915.json")
START, RB, SLIP = "2018-01-02", 250, 0.002
PB_CUT = 0.35          # 回撤门
WY_CUT = 2 / 3         # 年度胜率门
WT_CUT = 0.40          # 逐笔胜率门


# ---------------------------------------------------------------- 带权重的完整再平衡引擎
def run_w(feat, score, weight_fn=None, rebal=RB, topn=10, slip=SLIP, offset=0,
          start=START, exclude=None, capital=1_000_000.0):
    """按目标权重整体再平衡（与原引擎的区别：原引擎只补差额买入，本函数每期回到目标权重）。"""
    dates_all = feat["dates"]
    keep = dates_all >= pd.Timestamp(start)
    dates = dates_all[keep]
    close = feat["close"].loc[keep]
    open_ = feat["open"].loc[keep]
    sc = score.reindex(index=dates, columns=close.columns)
    if exclude is not None:
        ex = exclude.reindex(index=dates, columns=close.columns).fillna(True).astype(bool)
        sc = sc.where(~ex)
    sc = sc.where(close.notna() & open_.notna())
    px, op = close.values.astype("float64"), open_.values.astype("float64")
    scv = sc.values.astype("float64")
    nd = len(dates)
    reb_set = set(range(offset, nd, rebal))
    hold, cash = {}, capital
    eq = np.full(nd, np.nan)
    trades, trade_pnl, period_eq = 0, [], []
    for di in range(nd):
        val = cash + sum(sh * (px[di, ci] if np.isfinite(px[di, ci]) else 0.0)
                         for ci, sh in hold.items())
        eq[di] = val
        if di not in reb_set or di + 1 >= nd:
            continue
        row = scv[di]
        ok = np.isfinite(row)
        if ok.sum() < topn:
            continue
        idx = np.argsort(np.where(ok, row, np.inf))[:topn]
        codes = idx.tolist()
        period_eq.append(val)
        w = weight_fn(di, codes) if weight_fn else np.full(len(codes), 1.0 / len(codes))
        w = np.asarray(w, dtype=float)
        w = w / w.sum() if w.sum() > 0 else np.full(len(codes), 1.0 / len(codes))
        tv = {ci: val * w[k] for k, ci in enumerate(codes)}
        # 卖出（不在目标或需减仓）
        for ci in list(hold.keys()):
            p = op[di + 1, ci]
            if not np.isfinite(p):
                p = px[di, ci]
            if not np.isfinite(p):
                continue
            cur = hold[ci] * p
            tgt = tv.get(ci, 0.0)
            if cur - tgt <= max(0.01 * cur, 500):
                continue
            sellv = (cur - tgt) / (1 - slip)
            sh_s = int(sellv / p / 100) * 100
            if sh_s <= 0 or sh_s > hold[ci]:
                continue
            sh_s = min(sh_s, hold[ci])
            gross = sh_s * p * (1 - slip)
            fee = max(gross * V.COMM_RATE, V.COMM_MIN) + gross * V.SELL_TAX
            cash += gross - fee
            hold[ci] -= sh_s
            if hold[ci] <= 0:
                hold.pop(ci)
            trades += 1
            if ci not in hold:
                trade_pnl.append(0.0)   # 占位，逐笔口径另算（见下）
        # 买入（补到目标）
        for ci in codes:
            p = op[di + 1, ci]
            if not np.isfinite(p) or p <= 0:
                continue
            cur = hold.get(ci, 0) * p
            tgt = tv[ci]
            if tgt - cur <= max(0.01 * tgt, 500) or cash <= 0:
                continue
            buyv = min(tgt - cur, cash) / (1 + slip)
            sh_b = int(buyv / p / 100) * 100
            if sh_b < 100:
                continue
            gross = sh_b * p * (1 + slip)
            fee = max(gross * V.COMM_RATE, V.COMM_MIN)
            if gross + fee > cash:
                sh_b = int((cash - V.COMM_MIN) / (p * (1 + slip)) / 100) * 100
                if sh_b < 100:
                    continue
                gross = sh_b * p * (1 + slip)
                fee = max(gross * V.COMM_RATE, V.COMM_MIN)
            cash -= gross + fee
            hold[ci] = hold.get(ci, 0) + sh_b
            trades += 1
    s = pd.Series(eq, index=dates)
    ret = s.pct_change().dropna()
    yrs = (dates[-1] - dates[0]).days / 365.25
    tot = s.iloc[-1] / capital - 1
    yr = s.resample("YE").last().pct_change().dropna()
    return dict(total=float(tot), ann=float((1 + tot) ** (1 / yrs) - 1),
                sharpe=float(ret.mean() / ret.std() * np.sqrt(252)),
                mdd=float(((s / s.cummax()) - 1).min()), trades=trades,
                win_year=float((yr > 0).mean()), equity=s, years=yrs)


def eval_stag(feat, score, weight_fn=None, tag=""):
    """12 相位交叠合成（Q2 新标准）+ 单相位 9 档中位。"""
    step = max(1, RB // 12)
    subs = []
    for k in range(12):
        r = run_w(feat, score, weight_fn, offset=k * step)
        s = r["equity"]; subs.append(s / s.iloc[0])
    S = pd.concat(subs, axis=1).ffill().dropna()
    stag = S.mean(axis=1)
    ret = stag.pct_change().dropna()
    yrs = (stag.index[-1] - stag.index[0]).days / 365.25
    tot = stag.iloc[-1] - 1
    yr = stag.resample("YE").last().pct_change().dropna()
    single = []
    for p in range(9):
        r = run_w(feat, score, weight_fn, offset=int(round(p * RB / 9)))
        single.append(r["sharpe"])
    return dict(tag=tag, ann=float((1 + tot) ** (1 / yrs) - 1), total=float(tot),
                sharpe=float(ret.mean() / ret.std() * np.sqrt(252)),
                mdd=float(((stag / stag.cummax()) - 1).min()),
                win_year=float((yr > 0).mean()), by_year={str(k.year): float(v) for k, v in yr.items()},
                single_sharpe_med=float(np.median(single)), single_min=float(min(single)),
                single_max=float(max(single)))


def main():
    import gc
    feat = V.load_features()
    for k in list(feat.keys()):
        if hasattr(feat[k], "dtypes") and getattr(feat[k], "values", None) is not None                 and feat[k].values.dtype == "float64":
            feat[k] = feat[k].astype("float32")
    if "_raw_close" not in feat:
        feat["_raw_close"] = V.raw_close(feat, validate=False)
    # 清掉引擎不需要的键，压内存
    for k in ["open", "pe", "total_mv", "float_mv", "pb"]:
        pass
    f = A.build_factors(feat, None)
    for k in list(f.keys()):
        if f[k] is not None and hasattr(f[k], "values") and f[k].values.dtype == "float64":
            f[k] = f[k].astype("float32")
    ex = V.st_mask(feat)
    ind = A.industry_of(feat)
    cols = feat["close"].columns
    grp = pd.Series({c: ind.get(c) for c in cols})
    res = {}
    rp = f["roe_pb"]

    def wfn_factory(vol20):
        def wfn(di, codes):
            d = sc_ref[0].index[di]
            v = vol20.loc[:d].iloc[-1].reindex([cols[i] for i in codes]).values
            fin = np.isfinite(v) & (v > 0)
            fill = np.nanmedian(v[fin]) if fin.any() else 1.0
            v = np.where(fin, v, fill)
            return 1.0 / v
        return wfn

    sc_ref = [None]
    vol20 = feat["close"].pct_change().rolling(20).std()

    print("=" * 108)
    print("优化第二轮 · 12 相位交叠合成（Q2 新标准）｜Top10 / 年度 / 20bp / 2018+")
    print("=" * 108)
    print(f"{'臂':26s} {'年化':>8s} {'夏普':>7s} {'回撤':>8s} {'年度胜率':>8s} "
          f"{'单相位中位':>10s} {'单相位区间':>14s}")

    def emit(tag, sc, w=None):
        sc_ref[0] = sc
        r = eval_stag(feat, sc, w, tag)
        res[tag] = r
        print(f"{tag:26s} {r['ann']:8.2%} {r['sharpe']:7.3f} {r['mdd']:8.2%} {r['win_year']:8.0%} "
              f"{r['single_sharpe_med']:10.3f} {r['single_min']:6.2f}~{r['single_max']:5.2f}", flush=True)
        gc.collect()

    # BASE
    emit("BASE roe_pb 等权", A.make_score(rp, None))
    # N1 行业内相对票息
    med = rp.T.groupby(grp).transform("median").T.astype("float32")
    emit("N1 行业内相对票息", A.make_score(rp - med, None))
    del med; gc.collect()
    # N3 行业内分位
    ir = rp.T.groupby(grp).rank(pct=True).T.astype("float32")
    emit("N3 行业内分位", A.make_score(ir, None))
    del ir; gc.collect()
    # N2 行业上限 K=2
    within = rp.T.groupby(grp).rank(ascending=False, method="first").T
    pen = within.where(within <= 2, within * 100).astype("float32")
    emit("N2 行业上限K=2", A.make_score(rp - pen * 1e-6, None))
    del within, pen; gc.collect()
    # W1 BASE + 波动率倒数加权
    w1 = wfn_factory(vol20)
    emit("W1 BASE+波动率倒数加权", A.make_score(rp, None), w1)
    # N1 + W1
    med2 = rp.T.groupby(grp).transform("median").T.astype("float32")
    emit("N1W1 相对票息+波动率加权", A.make_score(rp - med2, None), w1)
    del med2; gc.collect()

    print("")
    print("=" * 108)
    print("三关门（回撤 ≤35% / 年度胜率 ≥2/3）—— 逐笔胜率口径需引擎扩展，此处只判前两门")
    print("=" * 108)
    for tag, r in res.items():
        g1 = "PASS" if r["mdd"] >= -PB_CUT else "FAIL"
        g2 = "PASS" if r["win_year"] >= WY_CUT else "FAIL"
        print(f"  {tag:26s} 回撤 {r['mdd']:8.2%}[{g1}]  年度胜率 {r['win_year']:5.0%}[{g2}]  "
              f"→ {'两门全过' if g1 == g2 == 'PASS' else '未过'}")

    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n[opt4] 落盘 {OUT}")


if __name__ == "__main__":
    main()
