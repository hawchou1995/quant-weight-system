# -*- coding: utf-8 -*-
"""价值线残余臂（R-buffett-opt4-0916）：三份外部方案中尚未落地的项，统一口径补齐。

统一配置（对齐 value_accept_0915 的验收口径）：
  roe_pb ｜ 全A主板排ST/退 ｜ 行业上限 K=1 ｜ Top15 ｜ 12 相位交叠 ｜ 年度调仓 F=250 ｜ 2018+ / 20bp

臂位：
  V0 基准复跑（应与 accept base20 ≈ 年化 13.97% / 夏普 0.541 / 回撤 −30.83% 对齐）
  V1 V0 + 组合级回撤状态机（月度观测：DD≤−10%→70%、≤−15%→40%、恢复对称；换手成本 30bp×|Δw|）
       ← ChatGPT ③「组合自身异常损失 → 降暴露」；项目内同类"回撤阶梯减仓"仅在轨A测过（有害），价值线未测
  V2 V0 + 相关簇去重（trailing 120 日 pairwise corr>0.7 与已选任一 → 跳过；含阻塞计数）
       ← ChatGPT ①「相关性簇/风格簇去重」；opt5 A4 存疑"从未生效"，本轮带计数重测
  V3 V0 + 剔市值后20%（total_mv 截面分位 ≤p20 剔除）← Gemini EXP-3 的微盘部分
  V4 静态 70/30（30% 现金零收益）← DeepSeek D 的确定性缩放

未测（边界申报，不跑）：
  · 扣非 ROE（yjbb_quarterly 无扣非字段 → 需新数据源）
  · IF/IC 对冲（本项目无期货数据）
  · 目标波动仓位缩放（立项书已列"已证伪·禁测"）
"""
import gc
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import value_lh_0914 as V               # noqa: E402
import value_arms_0914 as A             # noqa: E402
import industry_cap as IC               # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "value_opt7_0916.json")
START, RB, TOPN, CAP, SLIP, PHASES = "2018-01-02", 250, 15, 1, 0.002, 12
DD_TH = (0.10, 0.15)
DD_LV = (0.70, 0.40)
DD_COST = 0.003          # 每次暴露变动的换手成本（30bp × |Δw|）


def stats_from_eq(st, ret):
    yrs = (st.index[-1] - st.index[0]).days / 365.25
    tot = st.iloc[-1] / st.iloc[0] - 1
    dd = (st / st.cummax()) - 1
    yr = st.resample("YE").last().pct_change().dropna()
    return dict(ann=float((1 + tot) ** (1 / yrs) - 1), total=float(tot),
                sharpe=float(ret.mean() / ret.std() * np.sqrt(252)),
                mdd=float(dd.min()), win_year=float((yr > 0).mean()))


def dd_overlay(eq, th=DD_TH, lv=DD_LV, cost=DD_COST):
    """组合级回撤状态机（月度观测，PIT：用当月前的已实现净值）：
    DD>−10% → 100%；−15%<DD≤−10% → 70%；DD≤−15% → 40%。对称恢复。成本 30bp/Δw。"""
    r = eq.pct_change().fillna(0.0)
    idx = r.index
    vals = r.values
    outs = np.empty_like(vals)
    exp = 1.0
    scaled = 1.0
    peak = 1.0
    switches = 0
    cost_total = 0.0
    exp_hist = []
    prev_month = None
    for i in range(len(vals)):
        m = (idx[i].year, idx[i].month)
        c = 0.0
        if prev_month is not None and m != prev_month:
            dd = scaled / peak - 1
            newexp = lv[1] if dd <= -th[1] else (lv[0] if dd <= -th[0] else 1.0)
            if newexp != exp:
                c = cost * abs(newexp - exp)
                cost_total += c
                switches += 1
                exp = newexp
        outs[i] = vals[i] * exp - c
        scaled *= (1 + outs[i])
        peak = max(peak, scaled)
        exp_hist.append(exp)
        prev_month = m
    se = pd.Series(scaled_curve(outs), index=idx)
    rec = stats_from_eq(se, pd.Series(outs, index=idx))
    eh = np.array(exp_hist)
    rec.update(switches=switches, cost_total=float(cost_total),
               avg_exp=float(eh.mean()),
               t_100=float((eh >= 0.999).mean()), t_70=float(((eh > 0.5) & (eh < 0.999)).mean()),
               t_40=float((eh <= 0.5).mean()))
    return rec, se


def scaled_curve(outs):
    out = np.empty(len(outs))
    v = 1.0
    for i, x in enumerate(outs):
        v *= (1 + x)
        out[i] = v
    return out


def main():
    np.seterr(all="ignore")
    feat = V.load_features()
    if "_raw_close" not in feat:
        feat["_raw_close"] = V.raw_close(feat, validate=False)
    f = A.build_factors(feat, None)
    ex = V.st_mask(feat)
    cols = list(feat["close"].columns)
    ind = A.industry_of(feat)
    gid, _ = IC.encode_keys([ind.get(c) for c in cols])
    base = A.make_score(f["roe_pb"], None)
    keep = feat["dates"] >= pd.Timestamp(START)
    dates = feat["dates"][keep]
    scs = base.loc[dates]
    fill = scs.rank(axis=1, pct=True, ascending=False) + 1000
    rows = scs.values
    ret_all = feat["close"].pct_change()
    mv = feat.get("total_mv")
    if mv is not None:
        mv = mv.reindex(columns=cols)

    res = {}

    def run_stag(tag, builder):
        subs, shs, mdds = [], [], []
        for k in range(PHASES):
            o = int(round(k * RB / PHASES))
            cs = builder(o)
            r = V.run(feat, cs.fillna(fill), rebal=RB, topn=TOPN, slip=SLIP,
                      offset=o, start=START, exclude=ex)
            s = r["equity"]
            subs.append(s / s.iloc[0])
            shs.append(r["sharpe"]); mdds.append(float(((s / s.cummax()) - 1).min()))
            del cs; gc.collect()
        S = pd.concat(subs, axis=1).ffill().dropna()
        st = S.mean(axis=1)
        rec = stats_from_eq(st, st.pct_change().dropna())
        rec.update(single_sharpe_med=float(np.median(shs)),
                   single_mdd_med=float(np.median(mdds)), single_mdd_worst=float(np.min(mdds)))
        print(f"{tag:30s} 年化 {rec['ann']:7.2%}  夏普 {rec['sharpe']:.3f}  回撤 {rec['mdd']:8.2%}  "
              f"年度胜率 {rec['win_year']:4.0%}", flush=True)
        return rec, st

    # ---------- V0 基准 ----------
    def build_v0(o):
        arr = np.full(rows.shape, np.nan, dtype="float32")
        for di in range(o, len(scs), RB):
            pick = IC.select_with_cap(rows[di], gid, TOPN, CAP)
            for ri, ci in enumerate(pick):
                arr[di, ci] = ri
        return pd.DataFrame(arr, index=scs.index, columns=scs.columns)

    print("=" * 104)
    print("value_opt7 · 残余臂｜K=1 N=15 12相位 F=250｜2018+ / 20bp")
    print("=" * 104)
    r0, eq0 = run_stag("V0 基准（K=1 N=15）", build_v0)
    res["V0"] = r0

    # ---------- V1 组合级回撤状态机（叠加在 V0 聚合净值上，PIT） ----------
    r1, eq1 = dd_overlay(eq0)
    print(f"{'V1 V0+回撤状态机':30s} 年化 {r1['ann']:7.2%}  夏普 {r1['sharpe']:.3f}  回撤 {r1['mdd']:8.2%}  "
          f"| 切换 {r1['switches']} 次 成本 {r1['cost_total']:.2%} 均暴露 {r1['avg_exp']:.2f}")
    res["V1"] = r1

    # ---------- V2 相关簇去重 ----------
    blocks = {"ind": 0, "corr": 0, "sel": 0}

    def build_v2(o):
        arr = np.full(rows.shape, np.nan, dtype="float32")
        for di in range(o, len(scs), RB):
            row = rows[di]
            ok = np.isfinite(row)
            if ok.sum() < TOPN:
                continue
            cand = list(np.argsort(np.where(ok, row, np.inf))[:60])
            d = scs.index[di]
            sub = ret_all.loc[:d].tail(120)[[cols[c] for c in cand]]
            C = sub.corr().values
            pos_of = {c: i for i, c in enumerate(cand)}
            picked, used_ind = [], set()
            for ci in cand:
                if not np.isfinite(row[ci]):
                    break
                ind_ = ind.get(cols[ci])
                if ind_ in used_ind:
                    blocks["ind"] += 1
                    continue
                i = pos_of[ci]
                hit = False
                for cj in picked:
                    j = pos_of[cj]
                    if np.isfinite(C[i, j]) and C[i, j] > 0.70:
                        hit = True
                        break
                if hit:
                    blocks["corr"] += 1
                    continue
                used_ind.add(ind_)
                picked.append(ci)
                if len(picked) == TOPN:
                    break
            blocks["sel"] += len(picked)
            for ri, ci in enumerate(picked):
                arr[di, ci] = ri
        return pd.DataFrame(arr, index=scs.index, columns=scs.columns)

    r2, _ = run_stag("V2 V0+相关簇去重(120d>0.7)", build_v2)
    print(f"   约束阻塞计数：行业 {blocks['ind']} / 相关 {blocks['corr']} | 选中合计 {blocks['sel']}")
    r2.update(blocks=dict(blocks))
    res["V2"] = r2

    # ---------- V3 剔市值后 20% ----------
    if mv is None:
        print("V3 跳过：feat 无 total_mv")
        res["V3"] = {"skip": "no total_mv"}
    else:
        def build_v3(o):
            arr = np.full(rows.shape, np.nan, dtype="float32")
            for di in range(o, len(scs), RB):
                row = rows[di].copy()
                d = scs.index[di]
                mrow = mv.loc[:d].iloc[-1].values
                okm = np.isfinite(mrow) & np.isfinite(row)
                if okm.sum() < 30:
                    continue
                rk = pd.Series(np.where(okm, mrow, np.nan)).rank(pct=True).values
                row = np.where(np.isfinite(row) & (rk > 0.20), row, np.nan)
                pick = IC.select_with_cap(row, gid, TOPN, CAP)
                for ri, ci in enumerate(pick):
                    arr[di, ci] = ri
            return pd.DataFrame(arr, index=scs.index, columns=scs.columns)

        r3, _ = run_stag("V3 V0+剔市值后20%", build_v3)
        res["V3"] = r3

    # ---------- V4 静态 70/30 ----------
    rr0 = eq0.pct_change().fillna(0.0)
    eq4 = pd.Series(scaled_curve(rr0.values * 0.70), index=rr0.index)
    r4 = stats_from_eq(eq4, rr0 * 0.70)
    print(f"{'V4 静态70/30(30%现金)':30s} 年化 {r4['ann']:7.2%}  夏普 {r4['sharpe']:.3f}  回撤 {r4['mdd']:8.2%}")
    res["V4"] = r4

    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
    print(f"\n[opt7] 落盘 {OUT}")


if __name__ == "__main__":
    main()
