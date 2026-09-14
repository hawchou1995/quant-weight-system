# -*- coding: utf-8 -*-
"""轨A（冷门低波 Top10/60d）+ 轨B（SUPER 13因子 Top20/月频）行业集中度约束实验
=================================================================
预注册（2026-09-14 grill 拍板）：
  Q1 三轨都测（本脚本=轨A/轨B；轨C 见 industry_cap_fund_0914.py）
  Q2 用 stock_industry.json 的申万一级（37 类）作为行业键；无标签（缺映射）者各自独立计数
  Q3 扫 N∈{1,2,3}（同行业最多 N 只），对照 N=0
  Q4 池=各自生产口径（轨A 主板 data_full；轨B 冻结面板）
  Q5 先去重后约束（股票轨无份额问题，直接排序后套约束）
  Q6 先出数据再拍板
口径：T 日收盘选股 → T+1 开盘等权换仓；成本 = 每边 slip（主档 20bp，稳健 50bp）
相位：轨A rebal=60 → offsets 0/12/24/36/48；轨B rebal=20 → offsets 0/4/8/12/16（ADR-0006）
产物：backtest/industry_cap_ab_0914.json
用法：python backtest/industry_cap_ab_0914.py --track A|B|both
"""
import argparse
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import numpy as np
import pandas as pd

OUT = BASE / "backtest" / "industry_cap_ab_0914.json"
IND = json.load(open(BASE / "stock_industry.json", encoding="utf-8"))["map"]   # 6位 → 申万一级


def ind_of_sym(sym):
    return IND.get(sym[2:]) if len(sym) > 6 else IND.get(sym)


def pick_top(codes, scores, top_n, N, reverse):
    """按分数排序取 top_n，同行业最多 N 只（N=0=不约束）。reverse=True=分数越大越好"""
    order = sorted(zip(codes, scores), key=lambda kv: -kv[1] if reverse else kv[1])
    if not N:
        return [c for c, _ in order[:top_n]]
    picked, cnt = [], {}
    for c, _ in order:
        ind = ind_of_sym(c)
        if ind:
            if cnt.get(ind, 0) >= N:
                continue
            cnt[ind] = cnt.get(ind, 0) + 1
        picked.append(c)
        if len(picked) >= top_n:
            break
    return picked


def simulate(codes, O, C, comp_by_day, cal, h, offset, topn, N, slip,
             fee_b=0.00025, tax_s=0.0010, warmup=120, reverse=True):
    """调仓制组合级模拟（复刻 backtest/fwd_check_0913.run_rot 口径）：
    di%h==offset 调仓；榜内保留（强者恒持，不重买）；新名按 pv/topn 槽位买入；涨停不追；
    成本 = 每边 slip + 佣金 2.5bp(最低5元) + 卖出印花税 10bp。返回 (总收益%, 年化%, 回撤%, 夏普, 调仓数)"""
    cix = {c: j for j, c in enumerate(codes)}
    cash, hold, eqs = 1e6, {}, []
    n_reb = 0
    reb_idx = [i for i in range(warmup, len(cal)) if (i - offset) % h == 0]
    for di in reb_idx:
        # 估值（按当日收盘）
        pv = cash + sum(hh["sh"] * C[di, cix[c]] for c, hh in hold.items() if np.isfinite(C[di, cix[c]]))
        day = cal[di]
        cs, scs = comp_by_day.get(day, (None, None))
        if not cs:
            eqs.append(pv); continue
        sc_arr = np.asarray(scs)
        order = np.argsort(-sc_arr if reverse else sc_arr)   # 轨A=双低 rank 和（越小越优）
        keep, seen = set(), {}
        for j in order:
            c = cs[j]
            ind = ind_of_sym(c)
            if N and ind:                     # ⚠ N=0 = 不约束（曾漏此判断 → 对照臂一只未买）
                if seen.get(ind, 0) >= N:
                    continue
                seen[ind] = seen.get(ind, 0) + 1
            keep.add(c)
            if len(keep) >= topn:
                break
        # 卖出非目标（开盘价）
        for c in list(hold):
            j = cix[c]
            if c in keep:
                continue
            o = O[di, j]
            if not np.isfinite(o) or o <= 0:
                continue
            px = o * (1 - slip)
            sh = hold.pop(c)["sh"]
            cash += sh * px - max(sh * px * fee_b, 5) - sh * px * tax_s
        # 买入新名（槽位 = pv/topn，涨停不追）
        for c in list(keep):
            if c in hold:
                continue
            j = cix[c]
            o = O[di, j]; pc = C[di - 1, j]
            if not np.isfinite(o) or o <= 0 or not np.isfinite(pc) or o >= pc * 1.097:
                continue
            nl = int((min(pv / topn, cash) - 5) / (o * 100 * (1 + fee_b)))
            if nl < 1:
                continue
            sh = nl * 100
            cost = sh * o * (1 + slip) + max(sh * o * fee_b, 5)
            if cost > cash:
                continue
            cash -= cost
            hold[c] = {"sh": sh}
        n_reb += 1
        pv2 = cash + sum(hh["sh"] * C[di, cix[c]] for c, hh in hold.items() if np.isfinite(C[di, cix[c]]))
        eqs.append(pv2)
    if len(eqs) < 3:
        return dict(total=0.0, annual=0.0, mdd=0.0, sharpe=0.0, rebs=n_reb)
    eq = np.array(eqs) / 1e6
    r = np.diff(eq) / eq[:-1]
    yrs = h * len(r) / 244.0
    mdd = float((eq / np.maximum.accumulate(eq) - 1).min()) * 100
    sharpe = float(np.mean(r) / (np.std(r) + 1e-12) * np.sqrt(244.0 / h))
    return dict(total=(eq[-1] - 1) * 100, annual=((eq[-1]) ** (1 / max(yrs, 1e-9)) - 1) * 100,
                mdd=mdd, sharpe=sharpe, rebs=n_reb)


# ------------------------------------------------------------------ 轨A
def build_track_a():
    t0 = time.time()
    closes, opens, amts, highs, lows = {}, {}, {}, {}, {}
    for f in sorted((BASE / "data_full").glob("*.csv")):
        sym = f.stem
        if not (sym.startswith("sh60") or sym.startswith("sz00")):
            continue
        try:
            d = pd.read_csv(f, dtype={"date": str})
            if len(d) < 180:
                continue
            d = d[d["date"] >= "2015-06-01"].set_index("date").sort_index()   # 留 6 个月预热
            if len(d) < 180:
                continue
            closes[sym] = d["close"]; opens[sym] = d["open"]
            amts[sym] = d["amount"]; highs[sym] = d["high"]; lows[sym] = d["low"]
        except Exception:
            continue
    CL = pd.DataFrame(closes); OP = pd.DataFrame(opens); AM = pd.DataFrame(amts)
    HI = pd.DataFrame(highs); LO = pd.DataFrame(lows)
    amt20 = AM.rolling(20, min_periods=15).mean()
    prev = CL.shift(1)
    TR = np.maximum.reduce([(HI - LO).to_numpy(), (HI - prev).abs().to_numpy(), (LO - prev).abs().to_numpy()])
    atr20 = pd.DataFrame(TR, index=CL.index, columns=CL.columns).rolling(20, min_periods=20).mean() / CL
    hist_n = CL.notna().cumsum()
    score = np.log(amt20.where(amt20 > 0)).rank(axis=1) + atr20.rank(axis=1)   # 越小越优
    cal = [str(d) for d in CL.index]
    opens_i = {c: {i: OP[c].iloc[i] for i in range(len(cal)) if np.isfinite(OP[c].iloc[i])} for c in OP.columns}
    # 逐调仓日候选（只算会用到的相位日，提速 ~10x）
    need = set()
    for off in (0, 12, 24, 36, 48):
        need.update(i for i in range(len(cal)) if i > 120 and (i - off) % 60 == 0)
    score_by_day = {}
    S = score.to_numpy(); C = CL.to_numpy(); H = hist_n.to_numpy(); A2 = amt20.to_numpy()
    cols = list(CL.columns)
    for i in sorted(need):
        d = cal[i]
        row = S[i]; ok = np.isfinite(row) & np.isfinite(C[i]) & (C[i] >= 2) & np.isfinite(A2[i]) & (A2[i] > 0) & (H[i] >= 180)
        jj = np.where(ok)[0]
        score_by_day[d] = ([cols[j] for j in jj], [float(row[j]) for j in jj])
    print(f"[轨A] 面板 {CL.shape[0]} 天 × {CL.shape[1]} 只 ({time.time()-t0:.0f}s)", flush=True)
    return cal, OP.to_numpy(float), CL.to_numpy(float), list(CL.columns), score_by_day


# ------------------------------------------------------------------ 轨B
def build_track_b():
    t0 = time.time()
    OSS = BASE / "backtest" / "oss_0913"
    META = json.load(open(OSS / "super_combo_0913.json", encoding="utf-8"))["meta"]
    PICKED, WEIGHTS, SIGN = META["picked"], META["weights"], META["sign"]
    import pickle
    with open(OSS / "oss_panel_0913.pkl", "rb") as fh:
        P = pickle.load(fh)
    with open(BASE / "backtest" / "factorlab_0913" / "panel_0913.pkl", "rb") as fh:
        FP = pickle.load(fh)
    cal = [str(d)[:10] for d in P["cal"]]
    codes = list(P["codes"]); ND, NC = P["close"].shape
    E = P["ext"]; FD = FP["factors"]
    O = P["open"].astype(np.float64); H = P["high"].astype(np.float64)
    L = P["low"].astype(np.float64); C = P["close"].astype(np.float64)
    V = P["vol"].astype(np.float64); AMT = P["amt"].astype(np.float64); st = P["st_mask"]
    ATTN = E["atr14"].astype(np.float64); J = E["kdj_j"].astype(np.float64)
    ZW = E["z_white"].astype(np.float64); ZY = E["z_yellow"].astype(np.float64)
    close_ff = pd.DataFrame(C).ffill().to_numpy()
    amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
    hist_n = np.cumsum(np.isfinite(O), axis=0)
    lo20 = pd.DataFrame(L).rolling(20, min_periods=15).min().to_numpy()
    hi20 = pd.DataFrame(H).rolling(20, min_periods=15).max().to_numpy()
    hi120 = pd.DataFrame(H).rolling(120, min_periods=80).max().to_numpy()
    sig20 = pd.DataFrame(close_ff).rolling(20, min_periods=20).std(ddof=0).to_numpy()
    Cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
    with np.errstate(all="ignore"):
        TR = np.maximum.reduce([H - L, np.abs(H - Cprev), np.abs(L - Cprev)])
        tr20 = pd.DataFrame(TR).rolling(20, min_periods=20).mean().to_numpy()
        v5 = pd.DataFrame(V).rolling(5, min_periods=5).mean().to_numpy()
        v20 = pd.DataFrame(V).rolling(20, min_periods=20).mean().to_numpy()
        lo60 = pd.DataFrame(L).rolling(60, min_periods=40).min().to_numpy()
        up90 = pd.DataFrame(H).rolling(90, min_periods=60).max().shift(1).to_numpy()
        ALL = {"neg_j": -J, "shrink": -(v5 / v20), "low_lift": (lo20 / lo60 - 1) * 100,
               "neg_dbbi": -np.abs(E["dist_bbi"].astype(np.float64)),
               "neg_dyel": -np.abs(E["dist_yellow"].astype(np.float64)),
               "wy_ratio": (ZW / ZY - 1) * 100, "neg_sspace": -((close_ff / lo20 - 1) * 100),
               "pspace": (hi20 / close_ff - 1) * 100, "dd120": (close_ff / hi120 - 1) * 100,
               "slope_bbi": (E["bbi"].astype(np.float64) / pd.DataFrame(E["bbi"].astype(np.float64)).shift(3).to_numpy() - 1) * 100,
               "sqz_ratio": -(sig20 / tr20), "neg_atrp": -(ATTN / close_ff) * 100,
               "brk90": (close_ff / up90 - 1) * 100, "neg_vr": -(v5 / v20)}
    for k in ["amount20", "size_rev", "amp20", "ret60", "bp", "size_ep"]:
        ALL[k] = FD[k].astype(np.float64)
    ELIG = (np.isfinite(O) & np.isfinite(C) & (amt20 >= 3e6) & (~st[None, :]) & (hist_n >= 150) & (C > 2.0))
    num = np.zeros((ND, NC)); den = np.zeros((ND, NC))
    for k in PICKED:
        a = np.where(ELIG, ALL[k] * SIGN[k], np.nan)
        mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
        z = np.clip((a - mu) / (sd + 1e-12), -3, 3)
        ok = np.isfinite(z)
        num += np.where(ok, z * WEIGHTS[k], 0.0); den += np.where(ok, WEIGHTS[k], 0.0)
    COMP = np.where(den > 0.4 * sum(WEIGHTS.values()), num / np.maximum(den, 1e-9), np.nan)
    opens_i = {codes[j]: {i: O[i, j] for i in range(ND) if np.isfinite(O[i, j])} for j in range(NC)}
    score_by_day = {}
    for i, d in enumerate(cal):
        ok = ELIG[i] & np.isfinite(COMP[i])
        jj = np.where(ok)[0]
        score_by_day[d] = ([codes[j] for j in jj], [float(COMP[i, j]) for j in jj])
    print(f"[轨B] 面板 {ND} 天 × {NC} 只 ({time.time()-t0:.0f}s)", flush=True)
    return cal, O, C, codes, score_by_day


def run_track(name, cal, panels, sbd, rebal, top_n, phases, warmup, O, C, codes, reverse=True):
    res = {}
    for N in (0, 1, 2, 3):
        rows = []
        for off in phases:
            r = simulate(codes, O, C, sbd, cal, rebal, off, top_n, N, 0.0020, warmup=warmup, reverse=reverse)
            rows.append(dict(offset=off, **r))
            print(f"  [{name}] N={N} off={off:<3} 收益 {r['total']:>8.1f}%  年化 {r['annual']:>5.1f}%  "
                  f"夏普 {r['sharpe']:>5.2f}  回撤 {r['mdd']:>6.1f}%  调仓 {r['rebs']}", flush=True)
        sh = [x["sharpe"] for x in rows]
        res[f"N{N}_slip20"] = dict(phases=rows, sharpe_med=float(np.median(sh)),
                                  total_med=float(np.median([x["total"] for x in rows])),
                                  sharpe_min=float(min(sh)), sharpe_max=float(max(sh)))
        print(f"  → [{name}] N={N} 相位中位：夏普 {np.median(sh):.3f} [{min(sh):.3f},{max(sh):.3f}]，"
              f"收益中位 {np.median([x['total'] for x in rows]):.1f}%", flush=True)
    for N in (0, 1, 2, 3):
        r = simulate(codes, O, C, sbd, cal, rebal, phases[0], top_n, N, 0.0050, warmup=warmup, reverse=reverse)
        res.setdefault(f"N{N}_slip50", {})["off0"] = r
        print(f"  [{name}] N={N} slip50 off0: 收益 {r['total']:.1f}% 夏普 {r['sharpe']:.3f}", flush=True)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", default="both", choices=["A", "B", "both"])
    a = ap.parse_args()
    out = json.load(open(OUT, encoding="utf-8")) if OUT.exists() else {"prereg": {
        "N_grid": [0, 1, 2, 3], "industry": "stock_industry.json 申万一级（37 类）",
        "cost": "每边 slip（主档 20bp / 稳健 50bp）", "note": "T 收盘选股 → T+1 开盘等权换仓"}}
    t0 = time.time()
    if a.track in ("A", "both"):
        cal, O, C, codes, sbd = build_track_a()
        warm = next((i for i, d in enumerate(cal) if d >= "2021-01-04"), 0) + 120   # 三轨统一 2021 起（生产口径）
        out["track_A"] = dict(rebal=60, top_n=10, phases=[0, 12, 24, 36, 48],
                              runs=run_track("轨A", cal, None, sbd, 60, 10, [0, 12, 24, 36, 48], warm, O, C, codes,
                                             reverse=False))   # 双低 rank 和：越小越优
    if a.track in ("B", "both"):
        cal, O, C, codes, sbd = build_track_b()
        warm = next((i for i, d in enumerate(cal) if d >= "2021-01-04"), 0) + 120   # 三轨统一 2021 起
        out["track_B"] = dict(rebal=20, top_n=20, phases=[0, 4, 8, 12, 16],
                              runs=run_track("轨B", cal, None, sbd, 20, 20, [0, 4, 8, 12, 16], warm, O, C, codes))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[done] {time.time()-t0:.0f}s → {OUT.name}")


if __name__ == "__main__":
    main()
