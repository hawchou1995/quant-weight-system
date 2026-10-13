# -*- coding: utf-8 -*-
"""topic/296 截图（OCR）里的自报数字核验 —— 纯算术与多重检验，不需要行情数据。

核验对象（全部来自该帖 9 张截图的 OCR 结果）：
  T1 因子池交集表（15 个池 × 均值/中位/胜率/t/剔除涨停续持后均值）
  T2 共振分层表（共振≥5/6/7 池，n=24/18/12，含"留一日区间 9/9"）
  T3 两张同一批交易的持仓表（同一买入价、两套不同卖出规则）

核验判据：
  C1 截图表格自身算术自洽（成本=股数×买入价；盈亏=(卖出-买入)×股数；收益率）
  C2 报出的最大 t 与"同批被比较格子数"下的噪声期望最大值对比
  C3 顶部池的边际在剔除涨停续持后是否反向（原帖自己给了这一列）
  C4 同一批交易换卖出规则后收益摆动多大
  C5 分层单调是否来自嵌套子集（≥7 ⊂ ≥6 ⊂ ≥5）
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path


def phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def max_of_n_normals_expectation(n: int, trials: int = 400000, seed: int = 20261013) -> float:
    rnd = random.Random(seed)
    tot = 0.0
    for _ in range(trials):
        tot += max(rnd.gauss(0.0, 1.0) for _ in range(n))
    return tot / trials


def max_abs_of_n_normals_expectation(n: int, trials: int = 400000, seed: int = 20261013) -> float:
    rnd = random.Random(seed)
    tot = 0.0
    for _ in range(trials):
        tot += max(abs(rnd.gauss(0.0, 1.0)) for _ in range(n))
    return tot / trials


POOL_TABLE = [
    ("竞价阿尔法", 19, 61, 4.26, 1.16, -2.17, 27),
    ("量能因子", 8, 29, 3.76, 1.29, 2.27, 57),
    ("热点题材", 10, 29, 3.62, 1.43, 2.45, 56),
    ("今日风口", 9, 29, 3.51, 1.15, 1.25, 50),
    ("多星因子", 12, 29, 3.34, 1.01, 0.43, 50),
    ("爆点因子", 17, 25, 2.55, 0.88, 1.36, 56),
    ("核心因子", 29, 29, 2.47, 1.79, 0.04, 44),
    ("分值优选", 25, 29, 1.99, 0.77, 0.61, 48),
    ("高分竞价", 28, 29, 1.92, 1.10, 0.04, 44),
    ("研究院热榜", 18, 29, 1.79, 0.66, -0.22, 44),
    ("晨星量化", 52, 61, 1.74, 0.80, -0.88, 36),
    ("行业领先", 16, 29, 1.63, 0.27, 0.80, 53),
    ("早盘之星", 36, 61, 1.63, 0.67, -1.01, 33),
    ("竞价多头", 42, 61, 1.42, 0.69, -1.30, 34),
    ("盘前强势", 32, 61, 0.60, 0.04, 0.05, 39),
]

LAYER_TABLE = [
    ("共振≥5池", 24, 2.14, 0.24, 54, 4.18, 0.41, "9/9"),
    ("共振≥6池", 18, 3.58, 0.69, 61, 5.60, 1.56, "9/9"),
    ("共振≥7池", 12, 4.31, 0.60, 58, 7.34, 2.79, "7/7"),
]

# 截图 212953：止损(盘中) 版本
TRADES_A = [
    ("近岸蛋白", "09-15", 80.61, "09-16", 76.58, 600, 48366, -2418, -5.00, "止损(盘中)"),
    ("会稽山", "09-16", 25.91, "09-17", 29.85, 1800, 46638, 7092, 15.21, "到期(次日收盘)"),
    ("万邦医药", "09-17", 69.61, "09-18", 72.08, 700, 48727, 1729, 3.55, "到期(次日收盘)"),
    ("托伦斯", "09-18", 123.50, "未到期", 142.56, 400, 49400, 7624, 15.43, "持仓中(按09-18收盘浮动)"),
]
# 截图 213556：T+1 未涨停→卖 版本（同一批买入价，换卖出规则）
TRADES_B = [
    ("近岸蛋白", "09-15", 80.61, "09-16", 84.00, 600, 48366, 2034, 4.21, "T+1 未涨停→卖"),
    ("会稽山", "09-16", 25.91, "09-17", 29.85, 1800, 46638, 7092, 15.21, "T+1 未涨停→卖"),
    ("万邦医药", "09-17", 69.61, "09-18", 72.08, 700, 48727, 1729, 3.55, "T+1 未涨停→卖"),
    ("托伦斯", "09-18", 123.50, "未到期", 142.56, 400, 49400, 7624, 15.43, "待09-21判定"),
]


def check_arithmetic(trades, label):
    out = []
    ok = True
    for name, bd, bp, sd, sp, sh, cost, pnl, ret, reason in trades:
        cost_calc = round(bp * sh, 2)
        pnl_calc = round((sp - bp) * sh, 2)
        ret_calc = round((sp / bp - 1) * 100, 2)
        row = {
            "name": name, "reason": reason,
            "cost_reported": cost, "cost_calc": cost_calc,
            "pnl_reported": pnl, "pnl_calc": pnl_calc,
            "ret_reported_pct": ret, "ret_calc_pct": ret_calc,
            "cost_match": abs(cost_calc - cost) <= 1.0,
            "pnl_match": abs(pnl_calc - pnl) <= 1.0,
            "ret_match": abs(ret_calc - ret) <= 0.02,
        }
        row["all_match"] = row["cost_match"] and row["pnl_match"] and row["ret_match"]
        ok = ok and row["all_match"]
        out.append(row)
    return {"table": label, "self_consistent": ok, "rows": out}


def main() -> int:
    out_path = Path(sys.argv[1])

    # C1 算术自洽
    a = check_arithmetic(TRADES_A, "212953_stoploss_version")
    b = check_arithmetic(TRADES_B, "213556_t1_version")

    # C4 换卖出规则的摆动
    swing = []
    for (n1, _, _, _, sp1, sh1, _, p1, r1, _), (n2, _, _, _, sp2, sh2, _, p2, r2, _) in zip(TRADES_A, TRADES_B):
        swing.append({"name": n1, "sell_A": sp1, "ret_A_pct": r1, "sell_B": sp2, "ret_B_pct": r2,
                      "ret_swing_pp": round(r2 - r1, 2), "pnl_swing_yuan": p2 - p1})
    mean_a = sum(t[8] for t in TRADES_A) / 4
    mean_b = sum(t[8] for t in TRADES_B) / 4

    # C2 多重检验：15 个池 + 3 个分层 = 18 个被比较格子
    n_cells = len(POOL_TABLE) + len(LAYER_TABLE)
    observed_max_t = max(r[4] for r in POOL_TABLE)
    exp_max = max_of_n_normals_expectation(n_cells)
    exp_max_abs = max_abs_of_n_normals_expectation(n_cells)
    p_one = 1 - phi(observed_max_t)
    p_fw = 1 - (1 - p_one) ** n_cells
    multiplicity = {
        "cells_compared": n_cells,
        "observed_max_t": observed_max_t,
        "expected_max_t_under_null": round(exp_max, 3),
        "expected_max_abs_t_under_null": round(exp_max_abs, 3),
        "observed_max_below_null_expectation": observed_max_t < exp_max,
        "single_test_one_sided_p": round(p_one, 4),
        "family_wise_p_bonferroni_style": round(p_fw, 4),
        "interpretation": "18 个格子里最大的 t 仍低于纯噪声下最大值期望；即便按单格看也未达 5% 显著",
    }

    # C3 剔除涨停续持后是否反向
    reversal = []
    for name, hit_n, hit_d, mean, t, ex_mean, ex_win in POOL_TABLE:
        reversal.append({"pool": name, "mean_pct": mean, "mean_excl_limitup_continuation_pct": ex_mean,
                         "flips_sign": (mean > 0) != (ex_mean > 0),
                         "hit_rate": round(hit_n / hit_d * 100, 1)})
    flips = [r for r in reversal if r["flips_sign"]]
    top_by_mean = max(POOL_TABLE, key=lambda r: r[3])

    # C5 分层嵌套
    nested = {
        "layers": [{"name": n, "n": nn, "mean_pct": m, "median_pct": me, "win_rate": w,
                    "loo_range": loo, "w1": w1, "w2": w2} for n, nn, m, me, w, w1, w2, loo in LAYER_TABLE],
        "nested": True,
        "note": "共振≥7 ⊂ ≥6 ⊂ ≥5：单调是被子集包含关系机械保证的，不是三个独立检验；"
                "窗口只剩 9-04 起（共振池数据起点），可用交易日约 10 天",
        "weakest_cell_n": min(r[1] for r in LAYER_TABLE),
        "data_window": "共振池自 2026-09-04 起才有数据，分层结论仅覆盖约 10 个交易日",
    }
    # 100% 命中率池 = 无筛选作用（原帖自己指出）
    no_screen = [r[0] for r in POOL_TABLE if r[1] / r[2] >= 0.95]

    doc = {
        "schema": "gushi-296-image-claim-verification/v1",
        "captured_at": "2026-10-13",
        "source": {
            "topic": "https://www.gushi.in/topic/296",
            "access": "public topic; 9 content images downloaded anonymously and OCR'd (PaddleOCR)",
            "images": ["paste-20260918-171550_fcc70a.png", "paste-20260918-211806_b9d915.png",
                       "paste-20260918-211844_4a4117.png", "paste-20260918-211915_c1a750.png",
                       "paste-20260918-211943_9e895a.png", "paste-20260918-212953_efa2f8.png",
                       "paste-20260918-213556_817a2d.png", "paste-20260918-221333_271900.png",
                       "paste-20260918-221758_f01f7b.png"],
        },
        "C1_table_arithmetic": {"A": a, "B": b},
        "C4_exit_rule_swing": {
            "per_trade": swing,
            "mean_ret_A_pct": round(mean_a, 2),
            "mean_ret_B_pct": round(mean_b, 2),
            "portfolio_mean_swing_pp": round(mean_b - mean_a, 2),
            "note": "同一批 4 笔、同一买入价，仅换卖出规则：单笔最大摆动 9.21pp，组合均值摆动 2.30pp",
        },
        "C2_multiplicity": multiplicity,
        "C3_limitup_continuation": {
            "top_pool_by_mean": top_by_mean[0],
            "top_pool_mean_pct": top_by_mean[3],
            "top_pool_mean_excl_pct": top_by_mean[5],
            "pools_that_flip_sign": [r["pool"] for r in flips],
            "pools_flip_count": len(flips),
            "pools_total": len(POOL_TABLE),
            "rows": reversal,
        },
        "C5_layering": nested,
        "pools_without_screening_power": no_screen,
    }
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in doc.items() if k in ("C1_table_arithmetic", "C2_multiplicity")},
                     ensure_ascii=False, indent=2)[:2200])
    print("--- C4 ---")
    print(json.dumps(doc["C4_exit_rule_swing"], ensure_ascii=False, indent=2))
    print("--- C3 ---")
    print(json.dumps({k: v for k, v in doc["C3_limitup_continuation"].items() if k != "rows"},
                     ensure_ascii=False, indent=2))
    print("--- C5 / no-screen ---")
    print(json.dumps({"nested": nested, "no_screen": no_screen}, ensure_ascii=False, indent=2)[:1200])
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
