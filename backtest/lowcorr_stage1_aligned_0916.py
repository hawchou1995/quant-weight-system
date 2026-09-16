# -*- coding: utf-8 -*-
"""低相关策略挖掘 · 阶段1（对齐版）：用**生产冻结引擎**跑 2 因子全枚举
=================================================================
预注册（用户「按推荐」+「默认」）：
  · 低相关判据：与轨B（冻结 13 因子）**日收益相关 ≤ 0.30**（样本内筛选；入选者须样本外复验）
  · 候选空间：本地面板原子因子（ALL 全键，20-30 个）**2 因子全枚举**，等权 z 复合（不拟合权重）
  · 验收闸：相位中位夏普 ≥ **0.80** ∧ slip50 档 ≥ **0.60** ∧ corr_B ≤ **0.30**（**闸门保持不动**）
    + **额外报告「相对基线比」** = 候选 phmed ÷ 轨B phmed
  · 排序：阶段2 按组合层夏普提升（本阶段先按 phmed）
口径：**完全复用生产冻结引擎**（oss_super_combo_0913.py 前缀的 ALL/ELIG3/sign/composite/run_engine），
      Top20、20 日调仓、CASH0=17 万、slip 主档/50bp 档、calm=True（与官方口径一致）。
产物：backtest/lowcorr_stage1_aligned_0916.json
用法：python backtest/lowcorr_stage1_aligned_0916.py [--max-pairs N]
"""
import argparse
import itertools
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OSS = BASE / "backtest" / "oss_0913"
RES = BASE / "backtest" / "lowcorr_stage1_aligned_0916.json"
PHASES = [0, 4, 8, 12, 16]
N_TOP = 20
GATES = {"phmed_sharpe": 0.80, "slip50_sharpe": 0.60, "corr_to_B": 0.30}
OFFICIAL_B = {"phmed_sharpe": 1.151, "off0_ann_pct": 22.87}   # 冻结文件 super_combo_0913.json 记载

t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

# ---- 生产冻结引擎前缀（与 diff_super_repro_0915.py 同姿势）----
src = (OSS / "oss_super_combo_0913.py").read_text(encoding="utf-8")
exec(src.split("comp = composite()")[0])
log(f"冻结引擎载入 | 原子因子 {len(ALL)} | ELIG3 日均 {float(ELIG3.sum(axis=1).mean()):.0f} 只 | picked {len(picked)}")

import numpy as np  # noqa: E402  (exec 后确保可用)

FACTORS = sorted(ALL)


def mk_comp(keys):
    """等权 z 复合（与冻结 composite 同约定：域内归一、clip ±3、覆盖率 >0.4）"""
    num = np.zeros((ND, NC)); den = np.zeros((ND, NC))
    for k in keys:
        a = np.where(ELIG3, ALL[k] * sign[k], np.nan)
        mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
        z = np.clip((a - mu) / (sd + 1e-12), -3, 3)
        ok = np.isfinite(z)
        num += np.where(ok, z, 0.0); den += np.where(ok, 1.0, 0.0)
    return np.where(den > 0.4 * len(keys), num / np.maximum(den, 1e-9), np.nan)


def eval_comp(comp):
    """5 相位 + slip50 + 返回 off0 收益序列（供相关性）"""
    sh = []
    r0 = None
    for off in PHASES:
        r = run_engine(comp, N_TOP, offset=off)
        sh.append(float(r["sharpe"]))
        if off == 0:
            r0 = r
    s50 = run_engine(comp, N_TOP, offset=0, slip=0.0050)
    return {"phmed_sharpe": float(np.median(sh)), "sharpe_min": float(min(sh)), "sharpe_max": float(max(sh)),
            "off0_total_pct": float(r0["total"]) * 100, "off0_ann_pct": float(r0["ann"]) * 100,
            "off0_mdd_pct": float(r0["mdd"]) * 100, "off0_trades": int(r0["n_trades"]),
            "slip50_sharpe": float(s50["sharpe"]),
            "rets0": r0["equity"].pct_change().dropna()}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--max-pairs", type=int, default=0)
    a = ap.parse_args()

    # ---- 基线：冻结 13 因子 ----
    b = eval_comp(composite())
    log(f"[baseline] 轨B(冻结) phmed S={b['phmed_sharpe']:.3f} | off0 年化 {b['off0_ann_pct']:.2f}% | "
        f"slip50 S={b['slip50_sharpe']:.3f} | 官方记载 phmed {OFFICIAL_B['phmed_sharpe']}/off0 {OFFICIAL_B['off0_ann_pct']}%")
    if abs(b["phmed_sharpe"] - OFFICIAL_B["phmed_sharpe"]) > 0.15 and abs(b["off0_ann_pct"] - OFFICIAL_B["off0_ann_pct"]) > 3:
        log(f"[ABORT] 基线与官方记载不符（phmed {b['phmed_sharpe']:.3f} vs {OFFICIAL_B['phmed_sharpe']}, "
            f"off0 {b['off0_ann_pct']:.2f}% vs {OFFICIAL_B['off0_ann_pct']}%）→ 口径未对齐，拒绝出结论")
        sys.exit(2)
    rB = b["rets0"]

    pairs = list(itertools.combinations(FACTORS, 2))
    if a.max_pairs:
        pairs = pairs[:a.max_pairs]
    log(f"[enum] 2 因子全枚举 {len(pairs)} 组 × ({len(PHASES)} 相位 + slip50)")
    rows = []
    for i, ks in enumerate(pairs, 1):
        try:
            r = eval_comp(mk_comp(list(ks)))
        except Exception as e:
            log(f"  [skip] {ks}: {str(e)[:70]}"); continue
        r0 = r.pop("rets0")
        n = min(len(r0), len(rB))
        r["corr_B"] = float(np.corrcoef(r0.to_numpy()[-n:], rB.to_numpy()[-n:])[0, 1])
        r["rel_to_B"] = float(r["phmed_sharpe"] / b["phmed_sharpe"])
        r["factors"] = list(ks)
        r["pass"] = bool(r["phmed_sharpe"] >= GATES["phmed_sharpe"]
                         and r["slip50_sharpe"] >= GATES["slip50_sharpe"]
                         and r["corr_B"] <= GATES["corr_to_B"])
        rows.append(r)
        if i % 10 == 0 or i == len(pairs):
            RES.write_text(json.dumps({"gates": GATES, "baseline": {k: v for k, v in b.items() if k != "rets0"},
                                       "factors": FACTORS, "n_eval": len(rows), "rows": rows},
                                      ensure_ascii=False), encoding="utf-8")
            best = max(rows, key=lambda x: x["phmed_sharpe"])
            log(f"  [{i}/{len(pairs)}] 过闸 {sum(x['pass'] for x in rows)} | 最佳 phmed {best['phmed_sharpe']:.3f}"
                f"（相对基线 {best['rel_to_B']:.2f}×）{best['factors']} corr {best['corr_B']:.2f}")
    passed = sorted([x for x in rows if x["pass"]], key=lambda x: -x["phmed_sharpe"])
    log(f"\n[done] 评估 {len(rows)} 组 | **过闸 {len(passed)} 组**（闸门 {GATES}）")
    for x in passed[:15]:
        log(f"  ✅ {x['factors']} | phmed {x['phmed_sharpe']:.3f}（{x['rel_to_B']:.2f}×基线）| slip50 {x['slip50_sharpe']:.3f} | "
            f"corrB {x['corr_B']:.3f} | off0 年化 {x['off0_ann_pct']:.1f}% 回撤 {x['off0_mdd_pct']:.1f}%")
    # 低相关单独看（不论是否过性能闸）
    lowc = sorted([x for x in rows if x["corr_B"] <= GATES["corr_to_B"]], key=lambda x: -x["phmed_sharpe"])
    log(f"\n[低相关子集] corr_B ≤ 0.30 的共 {len(lowc)} 组，其 phmed 前 10：")
    for x in lowc[:10]:
        log(f"  · {x['factors']} corr {x['corr_B']:.3f} | phmed {x['phmed_sharpe']:.3f}（{x['rel_to_B']:.2f}×）| slip50 {x['slip50_sharpe']:.3f}")


if __name__ == "__main__":
    main()
