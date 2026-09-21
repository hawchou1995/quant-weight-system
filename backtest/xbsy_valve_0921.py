# -*- coding: utf-8 -*-
"""小步碎阳 + 爆量阴线出场 · 反向阀网格（XBSY-VALVE-0921 · 用户 2026-09-21 要求）
================================================================================
问题：「小步碎阳 + 爆量阴线出场」唯一的优势维度是**回撤**（−39.89% vs 沪深300 −45.60%），
      加反向阀能否**进一步降回撤**？

「反向阀」两个读法并列不合并（惯例）：
  A 族 = **大盘层反向阀**（择时闸：阀不过 → 不开新仓）
  B 族 = **个股层反向阀**（回避名单：该票被回避）

基线（上一轮口径 A 实测，不改口径）
--------------------------------------------------------------------------------
入场 = A_tdx（TDX 原文小步碎阳）；出场 = 爆量 ≥2×MA(V,20) + 次日阴线 → 次日开盘卖（cap 250）
本金 17 万 / 20 仓（每仓 8,500 元）；排序键 = **代码序**（无信息、无逆向选择）
主板面板 2604 日 × 4087 只（2016-01-04 → 2026-09-18）
基线读数：年化 +7.25% / 夏普 0.351 / 最大回撤 −39.89% / 按笔胜率 42.5% / 1,132 笔
沪深300 同窗：年化 +2.46% / 夏普 0.224 / 回撤 −45.60% / t(按日) 0.73

预注册网格
--------------------------------------------------------------------------------
A 族（大盘层，10 档）
  A0 无阀 ／ A1 沪深300>MA20 ／ A2 >MA60 ／ A3 >MA250（牛熊线）
  A4 20日动量>0 ／ A5 20日波动率<全历史中位 ／ A6 单日跌幅≤−2% 后 5 日不开新仓
  A1c/A2c/A3c = 同 A1/A2/A3，但**触发即清仓**（阀不过 → 不开新仓 + 已有持仓次日开盘全平）
B 族（个股层，7 档）
  B0 无阀 ／ B1 20日波动率<当日横截面中位 ／ B2 |收盘/MA20−1|≤10%
  B3 20日涨幅≤50%（不追高）／ B4 MA20>MA60（不空头）／ B5 RSI14≤70（不超买）
  B6 收盘≥5 元（低价/微盘代理回避）
网格 = 10 × 7 = **70 格**（槽位 20）；敏感性 = 最优 3 格 × 槽位 50（本金 42.5 万）

随机对照（噪声地板，必跑）
--------------------------------------------------------------------------------
每个阻塞率桶（大盘阀 / 个股阀 / 组合阀）各跑 **10 次随机阀**：随机剔除**同数量的信号**。
→ 得 Δ回撤 / Δ年化 / Δ夏普 的分布 → **取 5 分位作门槛**（即随机阀能做到的"最好"水平）。

判据（三重门，全过才算真降回撤）
--------------------------------------------------------------------------------
① 回撤改善 ≥ 5pp（≤ −34.89%）
② Δ回撤 超过随机对照 5 分位（即比随机阀的最好水平还低）
③ 年化 ≥ 沪深300 同窗 +2.46%（不许拿收益换回撤）

未测（数据缺失，如实声明）：**市值阀**（市值历史序列未定位）、**涨停家数闸**（`market_breadth.js`
只有单日快照 `points:1`，无历史序列）。

用法：cd quant-weight-system && python backtest/xbsy_valve_0921.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

import factor_gate as FG                                    # noqa: E402
import xbsy_0921 as X                                       # noqa: E402
import xbsy_port_0921 as PORT                               # noqa: E402
import xbsy_abl_0921 as ABL                                 # noqa: E402

OUT_JSON = str(HERE / "xbsy_valve_0921.json")
CFG = dict(boom="q2", lag=1, ma5=False, ma10=False, cap=250)
NAV0, NSLOT = 170000.0, 20
BASE_MDD, BASE_CAGR = -0.3989, 0.0725
HS300_CAGR = 0.0246
CTRL_DRAWS = 10
SEED = 20260921


def rsi14(C):
    dp = np.full_like(C, np.nan)
    dp[1:] = C[1:] - C[:-1]
    up = np.where(dp > 0, dp, 0.0)
    dn = np.where(dp < 0, -dp, 0.0)
    au = X.roll_mean(up, 14)
    ad = X.roll_mean(dn, 14)
    with np.errstate(all="ignore"):
        rs = au / np.where(ad > 0, ad, np.nan)
        r = 100.0 - 100.0 / (1.0 + rs)
    return np.where(np.isfinite(ad) & (ad == 0), 100.0, r)


def build_factors(P, V):
    C = P["close"].astype(np.float64)
    O = P["open"].astype(np.float64)
    pct = np.full_like(C, np.nan); pct[1:] = (C[1:] / C[:-1] - 1) * 100
    ma5, ma20, ma60 = X.roll_mean(C, 5), X.roll_mean(C, 20), X.roll_mean(C, 60)
    vma20 = X.roll_mean(V, 20)
    with np.errstate(all="ignore"):
        vr = V / vma20
    m20 = X.roll_mean(pct, 20)
    v20 = X.roll_mean(pct ** 2, 20) - m20 ** 2
    vol20 = np.sqrt(np.where(v20 > 0, v20, np.nan))
    ret20 = np.full_like(C, np.nan); ret20[20:] = C[20:] / C[:-20] - 1
    dev20 = np.where(np.isfinite(ma20) & (ma20 > 0), np.abs(C / ma20 - 1) * 100, np.nan)
    return dict(C=C, O=O, pct=pct, ma5=ma5, ma20=ma20, ma60=ma60, vr=vr,
                vol20=vol20, ret20=ret20, dev20=dev20, rsi=rsi14(C))


def idx_factors(cal):
    ix = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
    ix = ix[(ix["date"] >= cal[0]) & (ix["date"] <= cal[-1])].reset_index(drop=True)
    assert list(ix["date"]) == list(cal)
    c = ix["close"].to_numpy(float); o = ix["open"].to_numpy(float)
    p = np.full(len(c), np.nan); p[1:] = (c[1:] / c[:-1] - 1) * 100
    ma20 = pd.Series(c).rolling(20).mean().to_numpy()
    ma60 = pd.Series(c).rolling(60).mean().to_numpy()
    ma250 = pd.Series(c).rolling(250).mean().to_numpy()
    m20 = pd.Series(p).rolling(20).mean().to_numpy()
    v20 = np.sqrt((pd.Series(p ** 2).rolling(20).mean() - pd.Series(p).rolling(20).mean() ** 2).clip(lower=0))
    vol_med = np.nanmedian(v20)
    T = len(c)
    shut = np.zeros(T, dtype=bool)                      # A6：单日跌幅≤−2% 后 5 日不开新仓
    for i in np.nonzero(p <= -2.0)[0]:
        shut[i + 1:i + 6] = True
    return {"c": c, "p": p, "above20": c > ma20, "above60": c > ma60, "above250": c > ma250,
            "mom_pos": m20 > 0, "lowvol": v20 < vol_med, "shut": shut}


def metrics_of(P, V, SIG, max_pos=NSLOT, nav0=NAV0):
    PORT.NAV0 = nav0
    nav, tr = ABL.sim_rank(P, V, SIG, None, False, CFG, max_pos)
    m = PORT.metrics(nav, cal_ref, tr, "x")
    return m, len(tr)


cal_ref = None


def main():
    global cal_ref
    t0 = time.time()
    print("=" * 120)
    print("反向阀网格（XBSY-VALVE-0921）· 入场 A_tdx + 爆量阴线出场 · 17 万 / 20 仓 · 主板 2016-2026")
    print("=" * 120)
    P = FG.load_panel(X.PANEL)
    D = np.load(X.PANEL, allow_pickle=True)
    codes, cal = D["codes"], D["cal"]
    cal_ref = [str(x) for x in cal]
    V = X.load_volume([str(c) for c in codes], cal_ref)
    T, N = P["close"].shape
    SIG0 = X.build_arms(P, V)["A_tdx"]
    F = build_factors(P, V)
    IX = idx_factors(cal_ref)
    print(f"面板 {T} 日 × {N} 只 | 基线信号 {int(SIG0.sum()):,}")

    base, nb = metrics_of(P, V, SIG0)
    print(f"基线（无阀）：年化 {base['cagr']:+.2%}  夏普 {base['sharpe']:.3f}  回撤 {base['max_drawdown']:.2%}  "
          f"按笔胜率 {(base['win_rate_per_trade'] or 0):.1%}  笔数 {nb}")

    # ---- A 族 / B 族 阀矩阵 ----
    row = lambda v: np.repeat(np.asarray(v, dtype=bool)[:, None], N, axis=1)
    A = {"A0 无阀": np.ones((T, N), dtype=bool),
         "A1 hs300>MA20": row(IX["above20"]),
         "A2 hs300>MA60": row(IX["above60"]),
         "A3 hs300>MA250": row(IX["above250"]),
         "A4 20日动量>0": row(IX["mom_pos"]),
         "A5 20日波动率<中位": row(IX["lowvol"]),
         "A6 跌幅≤-2%后5日": row(~IX["shut"])}
    with np.errstate(all="ignore"):
        vol_med_col = np.nanmedian(F["vol20"], axis=1)[:, None]
    B = {"B0 无阀": np.ones((T, N), dtype=bool),
         "B1 个股波动率<中位": np.where(np.isfinite(F["vol20"]), F["vol20"] < vol_med_col, False),
         "B2 乖离MA20≤10%": np.where(np.isfinite(F["dev20"]), F["dev20"] <= 10.0, False),
         "B3 20日涨幅≤50%": np.where(np.isfinite(F["ret20"]), F["ret20"] <= 0.50, False),
         "B4 MA20>MA60": np.where(np.isfinite(F["ma60"]), F["ma20"] > F["ma60"], False),
         "B5 RSI14≤70": np.where(np.isfinite(F["rsi"]), F["rsi"] <= 70.0, False),
         "B6 收盘≥5元": np.where(np.isfinite(F["C"]), F["C"] >= 5.0, False)}
    # 清仓形态（A1c/A2c/A3c）：阀不过时，除不开新仓外，已有持仓次日开盘全平
    ACS = {"A1c hs300>MA20·清仓": IX["above20"], "A2c hs300>MA60·清仓": IX["above60"],
           "A3c hs300>MA250·清仓": IX["above250"]}

    out = {"base": {**base, "n_trades": nb}, "grid": {}, "control": {}, "notes": [
        "市值阀未测（市值历史序列未定位）", "涨停家数闸未测（market_breadth.js 仅单日快照 points:1）",
        f"随机对照 {CTRL_DRAWS} 次/桶，阈值取 5 分位"]}
    rows = []

    print("\n" + "-" * 120)
    print("① 网格 70 格（A 族 7 无清仓档 × B 族 7 档）+ 清仓形态 3 档 × B 族 7 档")
    print("-" * 120)
    hdr = (f"  {'大盘阀':<22}{'个股阀':<20}{'笔数':>6}{'年化':>9}{'夏普':>8}{'最大回撤':>10}"
           f"{'Δ回撤':>9}{'按笔胜率':>9}{'门①':>5}{'门③':>5}")
    print(hdr); print("  " + "-" * (len(hdr) - 2))

    def run_cell(aname, bname, sig):
        m, nt = metrics_of(P, V, sig)
        return m, nt

    for aname, amask in A.items():
        for bname, bmask in B.items():
            sig = SIG0 & amask & bmask
            if int(sig.sum()) < 50:
                continue
            m, nt = run_cell(aname, bname, sig)
            d_mdd = m["max_drawdown"] - base["max_drawdown"]
            g1 = d_mdd >= 0.05   # d_mdd = mdd − base_mdd；改善=回撤变小=变大（趋近 0）
            g3 = m["cagr"] >= HS300_CAGR
            rec = {**m, "n_trades": nt, "d_mdd": round(d_mdd, 4), "gate1": bool(g1), "gate3": bool(g3),
                   "n_sig": int(sig.sum())}
            out["grid"][f"{aname}|{bname}"] = rec
            rows.append((aname, bname, rec))
            print(f"  {aname:<22}{bname:<20}{nt:>6}{m['cagr']:>9.2%}{m['sharpe']:>8.3f}"
                  f"{m['max_drawdown']:>10.2%}{d_mdd:>9.2%}{(m['win_rate_per_trade'] or 0):>9.1%}"
                  f"{'过' if g1 else '否':>5}{'过' if g3 else '否':>5}")

    for aname, ok in ACS.items():
        for bname, bmask in B.items():
            sig = SIG0 & row(ok) & bmask
            if int(sig.sum()) < 50:
                continue
            m, nt = run_cell(aname, bname, sig)
            d_mdd = m["max_drawdown"] - base["max_drawdown"]
            g1 = d_mdd >= 0.05   # d_mdd = mdd − base_mdd；改善=回撤变小=变大（趋近 0）
            g3 = m["cagr"] >= HS300_CAGR
            rec = {**m, "n_trades": nt, "d_mdd": round(d_mdd, 4), "gate1": bool(g1), "gate3": bool(g3),
                   "n_sig": int(sig.sum()), "variant": "清仓"}
            out["grid"][f"{aname}|{bname}"] = rec
            rows.append((aname, bname, rec))
            print(f"  {aname:<22}{bname:<20}{nt:>6}{m['cagr']:>9.2%}{m['sharpe']:>8.3f}"
                  f"{m['max_drawdown']:>10.2%}{d_mdd:>9.2%}{(m['win_rate_per_trade'] or 0):>9.1%}"
                  f"{'过' if g1 else '否':>5}{'过' if g3 else '否':>5}")

    # ---- 随机对照：噪声地板（每个阻塞率桶 10 次）----
    print("\n" + "-" * 120)
    print(f"② 随机对照（噪声地板）：每桶 {CTRL_DRAWS} 次同阻塞数随机剔除")
    print("-" * 120)
    rng = np.random.default_rng(SEED)
    flat = np.nonzero(SIG0.ravel())[0]
    buckets = {"大盘阀~A1": SIG0 & ~A["A1 hs300>MA20"],
               "个股阀~B4": SIG0 & ~B["B4 MA20>MA60"],
               "组合阀~A1B4": SIG0 & ~A["A1 hs300>MA20"] & ~B["B4 MA20>MA60"]}
    for bname, sigb in buckets.items():
        keep = int(sigb.sum())
        drops = []
        for _ in range(CTRL_DRAWS):
            k = len(flat) - keep
            rm = rng.choice(flat, size=k, replace=False)
            s = SIG0.copy().ravel(); s[rm] = False
            m, _ = metrics_of(P, V, s.reshape(SIG0.shape))
            drops.append(m["max_drawdown"] - base["max_drawdown"])
        d = np.array(drops)
        q05, q50 = float(np.percentile(d, 5)), float(np.median(d))
        out["control"][bname] = {"draws": CTRL_DRAWS, "blocked": int(len(flat) - keep),
                                 "keep": keep, "q05": round(q05, 4), "median": round(q50, 4),
                                 "min": round(float(d.min()), 4), "max": round(float(d.max()), 4)}
        print(f"  {bname:<16} 保留信号 {keep:>8,}  Δ回撤：5分位 {q05:+.2%}  中位 {q50:+.2%}  "
              f"最差 {d.min():+.2%}  最好 {d.max():+.2%}")

    # ---- 三重门汇总 ----
    print("\n" + "-" * 120)
    print("③ 三重门筛选（①Δ回撤≤−5pp ②超随机对照 5 分位 ③年化≥沪深300 +2.46%）")
    print("-" * 120)
    thr_imp = max(-v["min"] for v in out["control"].values())   # 随机阀能达到的**最大**改善
    passed = []
    for aname, bname, rec in rows:
        if rec["gate1"] and rec["gate3"] and rec["d_mdd"] >= thr_imp:
            passed.append((aname, bname, rec))
    print(f"  随机阀最大改善（≈P95，取最严）= +{thr_imp:.2%} → 阀须 ≥ 此值")
    if passed:
        for a, b, r in sorted(passed, key=lambda x: x[2]["d_mdd"]):
            print(f"  ✅ {a} | {b}  年化 {r['cagr']:+.2%} 夏普 {r['sharpe']:.3f} "
                  f"回撤 {r['max_drawdown']:.2%} Δ回撤 {r['d_mdd']:+.2%} 笔数 {r['n_trades']}")
    else:
        print("  ❌ 无格通过三重门")
    out["passed"] = [f"{a}|{b}" for a, b, _ in passed]
    out["ctrl_threshold_improve"] = round(thr_imp, 4)

    # 最优 3 格 → 槽位 50 敏感性
    top = sorted(rows, key=lambda x: x[2]["max_drawdown"])[:3]
    print("\n  敏感性（最优 3 格 · 槽位 50 / 本金 42.5 万）：")
    for a, b, _ in top:
        amask = A[a] if a in A else row(ACS[a])
        sig = SIG0 & amask & B[b]
        m, nt = metrics_of(P, V, sig, max_pos=50, nav0=425000.0)
        out["grid"][f"SLOT50|{a}|{b}"] = {**m, "n_trades": nt}
        print(f"    {a} | {b}  年化 {m['cagr']:+.2%} 夏普 {m['sharpe']:.3f} 回撤 {m['max_drawdown']:.2%} 笔数 {nt}")

    out["elapsed_s"] = round(time.time() - t0, 1)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n结果已落盘 {OUT_JSON}（{out['elapsed_s']}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
