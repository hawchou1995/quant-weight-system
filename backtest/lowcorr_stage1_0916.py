# -*- coding: utf-8 -*-
"""低相关策略挖掘 · 阶段1：2 因子全枚举（2026-09-16 预注册口径）
=================================================================
预注册（用户「按推荐」拍板，禁止事后调参）：
  Q1 低相关判据：与轨B（SUPER 冻结 13 因子）**日收益相关 ≤ 0.30**（样本内筛选，入选后须样本外复验）
  Q2 候选空间：现成面板 factorlab_0913/panel_0913.pkl + oss_0913/oss_panel_0913.pkl 的原子因子，
     **2 因子全枚举**（等权 z 复合，不拟合权重）；3 因子只对过闸者做三元扩展（下一阶段）
  Q3 验收闸：相位中位夏普 ≥ 0.80 且 slip50 档 ≥ 0.60 且 与轨B 相关 ≤ 0.30；
     组合层（60% FB3 + 40% 候选）夏普提升 ≥ +0.02 且 Calmar 不降（组合层与安慰剂在阶段2 做）
  Q4 排序：按**组合层夏普提升**（阶段2）；阶段1 先按「相位中位夏普」筛
  Q5 GitHub 挖掘另线进行；本脚本只用本地面板（零新增数据成本）
口径：主板+创业板(同 track B 面板)、T 收盘选股 → T+1 开盘等权换仓、Top20、20 日调仓、成本 20bp/边（稳健档 50bp）
产物：backtest/lowcorr_stage1_0916.json（全量结果）+ 屏幕 Top 榜
用法：python backtest/lowcorr_stage1_0916.py [--max-pairs N]
"""
import argparse
import itertools
import json
import pickle
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import numpy as np
import pandas as pd

OUT = BASE / "backtest"
OSS = OUT / "oss_0913"
FL = OUT / "factorlab_0913"
RES = OUT / "lowcorr_stage1_0916.json"

GATES = {"phmed_sharpe": 0.80, "slip50_sharpe": 0.60, "corr_to_B": 0.30}
TOPN, REBAL, PHASES = 20, 20, [0, 4, 8, 12, 16]
WARMUP = 150

# ---------------------------------------------------------------- 面板
with open(OSS / "super_combo_0913.json", encoding="utf-8") as fh:
    META = json.load(fh)["meta"]
PICKED, WEIGHTS, SIGN = META["picked"], META["weights"], META["sign"]
with open(OSS / "oss_panel_0913.pkl", "rb") as fh:
    P = pickle.load(fh)
with open(FL / "panel_0913.pkl", "rb") as fh:
    FP = pickle.load(fh)

cal = [str(d)[:10] for d in P["cal"]]
codes = list(P["codes"])
ND, NC = P["close"].shape
E = P["ext"]; FD = FP["factors"]
O = P["open"].astype(np.float64); H = P["high"].astype(np.float64)
L = P["low"].astype(np.float64); C = P["close"].astype(np.float64)
V = P["vol"].astype(np.float64); AMT = P["amt"].astype(np.float64); st = P["st_mask"]
ATTN = E["atr14"].astype(np.float64); J = E["kdj_j"].astype(np.float64)
ZW = E["z_white"].astype(np.float64); ZY = E["z_yellow"].astype(np.float64)
close_ff = pd.DataFrame(C).ffill().to_numpy()
amt20 = pd.DataFrame(AMT).rolling(20, min_periods=15).mean().to_numpy()
hist_n = np.cumsum(np.isfinite(O), axis=0)


def _roll(a, w, mp):
    return pd.DataFrame(a).rolling(w, min_periods=mp).mean().to_numpy()


with np.errstate(all="ignore"):
    lo20 = pd.DataFrame(L).rolling(20, min_periods=15).min().to_numpy()
    hi20 = pd.DataFrame(H).rolling(20, min_periods=15).max().to_numpy()
    hi120 = pd.DataFrame(H).rolling(120, min_periods=80).max().to_numpy()
    sig20 = pd.DataFrame(close_ff).rolling(20, min_periods=20).std(ddof=0).to_numpy()
    Cprev = np.vstack([np.full((1, NC), np.nan), close_ff[:-1]])
    TR = np.maximum.reduce([H - L, np.abs(H - Cprev), np.abs(L - Cprev)])
    tr20 = pd.DataFrame(TR).rolling(20, min_periods=20).mean().to_numpy()
    v5 = _roll(V, 5, 5); v20 = _roll(V, 20, 20)
    lo60 = pd.DataFrame(L).rolling(60, min_periods=40).min().to_numpy()
    up90 = pd.DataFrame(H).rolling(90, min_periods=60).max().shift(1).to_numpy()
    bbi = E["bbi"].astype(np.float64)
    ALL = {
        "neg_j": -J, "shrink": -(v5 / v20), "low_lift": (lo20 / lo60 - 1) * 100,
        "neg_dbbi": -np.abs(E["dist_bbi"].astype(np.float64)),
        "neg_dyel": -np.abs(E["dist_yellow"].astype(np.float64)),
        "wy_ratio": (ZW / ZY - 1) * 100, "neg_sspace": -((close_ff / lo20 - 1) * 100),
        "pspace": (hi20 / close_ff - 1) * 100, "dd120": (close_ff / hi120 - 1) * 100,
        "slope_bbi": (bbi / pd.DataFrame(bbi).shift(3).to_numpy() - 1) * 100,
        "sqz_ratio": -(sig20 / tr20), "neg_atrp": -(ATTN / close_ff) * 100,
        "brk90": (close_ff / up90 - 1) * 100, "neg_vr": -(v5 / v20),
    }
for k in ("amount20", "size_rev", "amp20", "ret60", "bp", "size_ep"):
    if k in FD:
        ALL[k] = FD[k].astype(np.float64)
FACTORS = sorted(ALL)

ELIG = (np.isfinite(O) & np.isfinite(C) & (amt20 >= 3e6) & (~st[None, :]) & (hist_n >= WARMUP) & (C > 2.0))


def composite(keys):
    """等权 z 复合（域内归一、clip ±3、覆盖率>0.4）"""
    num = np.zeros((ND, NC)); den = np.zeros((ND, NC))
    for k in keys:
        a = np.where(ELIG, ALL[k], np.nan)
        mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
        z = np.clip((a - mu) / (sd + 1e-12), -3, 3)
        ok = np.isfinite(z)
        num += np.where(ok, z, 0.0); den += np.where(ok, 1.0, 0.0)   # ⚠ np.where 三参齐全（两参=ValueError，冒烟测试逮到）
    return np.where(den > 0.4 * len(keys), num / np.maximum(den, 1e-9), np.nan)


def simulate(COMP, slip, offset, topn=TOPN, rebal=REBAL):
    """调仓制组合级模拟（与 industry_cap_ab_0914 同口径）"""
    cash, hold, eqs = 1e6, {}, []
    for di in range(WARMUP, ND):
        if (di - offset) % rebal:
            continue
        row = COMP[di]
        ok = np.where(ELIG[di] & np.isfinite(row))[0]
        if ok.size == 0:
            continue
        tgt = set(ok[np.argsort(-row[ok])[:topn]].tolist())
        for j in list(hold):
            if j in tgt:
                continue
            o = O[di, j]
            if not np.isfinite(o) or o <= 0:
                continue
            px = o * (1 - slip); sh = hold.pop(j)
            cash += sh * px - max(sh * px * 0.00025, 5) - sh * px * 0.0010
        for j in tgt:
            if j in hold:
                continue
            o = O[di, j]; pc = C[di - 1, j]
            if not np.isfinite(o) or not np.isfinite(pc) or o <= 0 or o >= pc * 1.097:
                continue
            nl = int((min(cash / max(len(tgt - set(hold)), 1), cash) - 5) / (o * 100 * (1 + 0.00025)))
            if nl < 1:
                continue
            sh = nl * 100.0
            cost = sh * o * (1 + slip) + max(sh * o * 0.00025, 5)
            if cost > cash:
                continue
            cash -= cost; hold[j] = sh
        eqs.append(cash + sum(h * C[di, j] for j, h in hold.items() if np.isfinite(C[di, j])))
    if len(eqs) < 5:
        return None
    eq = np.array(eqs) / 1e6
    r = np.diff(eq) / eq[:-1]
    return {"sharpe": float(np.mean(r) / (np.std(r) + 1e-12) * np.sqrt(244.0 / rebal)),
            "total_pct": float((eq[-1] - 1) * 100), "rets": r.tolist()}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--max-pairs", type=int, default=0)
    a = ap.parse_args()
    t0 = time.time()
    print(f"[setup] 因子 {len(FACTORS)} 个 → 2 因子全枚举 C({len(FACTORS)},2) = "
          f"{len(FACTORS)*(len(FACTORS)-1)//2} 组 | 面板 {ND}×{NC}", flush=True)

    # 轨B 基准（冻结 13 因子 ICIR 权重）
    num = np.zeros((ND, NC)); den = np.zeros((ND, NC))
    for k in PICKED:
        a_ = np.where(ELIG, ALL[k] * SIGN[k], np.nan)
        mu = np.nanmean(a_, axis=1, keepdims=True); sd = np.nanstd(a_, axis=1, keepdims=True)
        z = np.clip((a_ - mu) / (sd + 1e-12), -3, 3); ok = np.isfinite(z)
        num += np.where(ok, z * WEIGHTS[k], 0.0); den += np.where(ok, WEIGHTS[k], 0.0)
    COMP_B = np.where(den > 0.4 * sum(WEIGHTS.values()), num / np.maximum(den, 1e-9), np.nan)
    base0 = simulate(COMP_B, 0.0020, 0)
    print(f"[baseline] 轨B(冻结13因子) off0 夏普 {base0['sharpe']:.3f} 收益 {base0['total_pct']:.1f}%", flush=True)
    # ⚠ 2026-09-16 预注册硬断言：官方 track_b.bt = 夏普 1.3 / 年间 22.87%（相位中位 1.151）。
    #   本 harness 若复现不出官方量级，说明与生产引擎口径不一致 → **必须先对齐再跑枚举**，
    #   否则 435 组的分数与生产不同尺度，闸门（phmed≥0.8）失去意义。
    if base0["sharpe"] < 1.0:
        print("[ABORT] 基线夏普 %.3f < 1.0（官方 1.3）→ 口径未对齐，拒绝在错误尺度上跑枚举。" % base0["sharpe"], flush=True)
        print("        下一步：改用生产冻结引擎（backtest/oss_0913/oss_super_prod_0913.py 的 simulate/口径）复算基线。", flush=True)
        sys.exit(2)
    rB = np.array(base0["rets"])

    pairs = list(itertools.combinations(FACTORS, 2))
    if a.max_pairs:
        pairs = pairs[:a.max_pairs]
    rows = []
    for i, ks in enumerate(pairs, 1):
        try:
            COMP = composite(list(ks))
            per = [simulate(COMP, 0.0020, off) for off in PHASES]
            if any(p is None for p in per):
                continue
            sh = [p["sharpe"] for p in per]
            s50 = simulate(COMP, 0.0050, 0)
            r0 = np.array(per[0]["rets"])
            n = min(len(r0), len(rB))
            corr = float(np.corrcoef(r0[-n:], rB[-n:])[0, 1])
            rows.append({"factors": list(ks), "phmed_sharpe": float(np.median(sh)),
                         "sharpe_min": float(min(sh)), "sharpe_max": float(max(sh)),
                         "off0_total_pct": float(per[0]["total_pct"]),
                         "slip50_sharpe": float(s50["sharpe"]) if s50 else None,
                         "corr_B": corr,
                         "pass": bool(np.median(sh) >= GATES["phmed_sharpe"]
                                      and (s50 and s50["sharpe"] >= GATES["slip50_sharpe"])
                                      and corr <= GATES["corr_to_B"])})
        except Exception as e:
            print(f"  [skip] {ks}: {str(e)[:60]}", flush=True)
        if i % 20 == 0:
            best = max(rows, key=lambda r: r["phmed_sharpe"]) if rows else None
            print(f"  [{i}/{len(pairs)}] {time.time()-t0:.0f}s | 已评 {len(rows)} | 过闸 "
                  f"{sum(r['pass'] for r in rows)} | 当前最优 phmed {best['phmed_sharpe']:.3f} {best['factors'] if best else ''}", flush=True)
            RES.write_text(json.dumps({"gates": GATES, "baseline_B": {"sharpe": base0["sharpe"], "total_pct": base0["total_pct"]},
                                       "factors": FACTORS, "n_eval": len(rows), "rows": rows}, ensure_ascii=False), encoding="utf-8")
    RES.write_text(json.dumps({"gates": GATES, "baseline_B": {"sharpe": base0["sharpe"], "total_pct": base0["total_pct"]},
                               "factors": FACTORS, "n_eval": len(rows), "rows": rows}, ensure_ascii=False), encoding="utf-8")
    passed = [r for r in rows if r["pass"]]
    passed.sort(key=lambda r: -r["phmed_sharpe"])
    print(f"\n[done] {time.time()-t0:.0f}s | 评估 {len(rows)} 组 | **过闸 {len(passed)} 组**（闸门 {GATES}）")
    for r in passed[:12]:
        print(f"  ✅ {r['factors']} | phmed {r['phmed_sharpe']:.3f} | slip50 {r['slip50_sharpe']:.3f} | "
              f"corrB {r['corr_B']:.3f} | off0 {r['off0_total_pct']:.1f}%")


if __name__ == "__main__":
    main()
