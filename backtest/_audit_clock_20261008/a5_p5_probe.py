# -*- coding: utf-8 -*-
"""A5 打板族「决定层」的同 bar 因果探针（C5 闭合）+ 阳性对照

要点：**决定 ≠ 成交**。
  · 「决定层」= 09:18 盲挂时**选哪些标的挂单** —— 修复后只读 T−1 及以前信息（观察名单、静态条件），
    不读成交那一根 bar 的开盘 ⇒ 期望 P5 = **0/3 触发**。
  · 修复**前**的实现是 `gap = o/pc − 1` 带内才建仓（用入场日那根 bar 的开盘） ⇒ 期望 P5 **全触发**
    （这是**阳性对照**，证明探针对这条口径真的有效，而不是空转通过）。

**本脚本不跑完整 A5 流程**（它需要行情数据、且会改写 `paper_state.json`，属他人运行时状态）。
它用与 A5 同形的决策函数在两行 ctx 上做协议级判定 —— 这一点在结论里明确写出，不做过度声称。

用法：`python a5_p5_probe.py` → 写 `evidence_a5_p5_probe.json`
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = r"E:\PI\投资\fleur_absorb"
if ENG not in sys.path:
    sys.path.insert(0, ENG)

from engine import audit as A  # noqa: E402

OUT = os.path.join(HERE, "evidence_a5_p5_probe.json")
BAND_LO, BAND_HI = -0.05, -0.02          # A5 带（闭区间）


def build_ctx(rows: int = 4, cols: int = 4):
    """构造两行 ctx：t=决策日（T−1），t+1=成交日（开盘落在带内）。"""
    close = np.array([[10.0, 20.0, 30.0, 40.0],
                      [10.0, 20.0, 30.0, 40.0],
                      [10.0, 20.0, 30.0, 40.0],
                      [10.0, 20.0, 30.0, 40.0]][:rows], dtype=np.float64)
    open_ = close.copy()
    for t in range(1, rows):
        open_[t] = close[t - 1] * (1.0 + (BAND_LO + BAND_HI) / 2.0)   # 带内（−3.5%）
    high = np.maximum(open_, close)
    low = np.minimum(open_, close)
    vol = np.full_like(close, 1e6)
    return dict(close=close, open=open_, high=high, low=low, volume=vol)


def decide_fixed(c, t):
    """A5 **修复后**的决定层：只用 T−1 及以前的静态条件（观察名单 + 首板静态条件）选挂单标的。

    刻意不读 `c["open"][t+1]` / `c["close"][t+1]` —— 那才是同 bar 因果。
    """
    row = c["close"][t]
    return sorted(int(j) for j in np.nonzero(np.isfinite(row) & (row > 0))[0])


def decide_prefix_bug(c, t):
    """A5 **修复前**的口径：`gap = O[t+1]/C[t] − 1` 在带内才建仓（读成交那根 bar 的开盘）。"""
    o, pc = c["open"][t + 1], c["close"][t]
    g = o / pc - 1.0
    m = np.isfinite(g) & (g >= BAND_LO - 1e-9) & (g <= BAND_HI + 1e-9)
    return sorted(int(j) for j in np.nonzero(m)[0])


def main() -> int:
    ctx = build_ctx()
    t = 2                       # 决策日 = T−1
    fill_idx = 3                # 成交日 = T

    fixed = A.probe_same_bar_causality(decide_fixed, ctx, t, fill_idx)
    bug = A.probe_same_bar_causality(decide_prefix_bug, ctx, t, fill_idx)

    ok = (fixed["ok"] is True) and (bug["ok"] is False) and bug["tripped"] != "none"
    ev = dict(
        _what="A5 打板族决定层的同 bar 因果探针（C5）＋阳性对照（证明探针非空转）",
        scope="协议级：用与 A5 同形的**决策函数**在两行 ctx 上判定；**未**跑完整 A5 流程"
              "（需行情数据、且会改写 paper_state.json —— 属他人运行时状态，不动）",
        band=[BAND_LO, BAND_HI], decide_day="T-1", fill_day="T", t=int(t), fill_idx=int(fill_idx),
        arm_fixed_after_repair=dict(desc="只读 T−1 及以前（修复后的决定层）", **fixed),
        arm_prefix_bug=dict(desc="读成交那根 bar 的开盘（修复前口径，阳性对照）", **bug),
        verdict=("修复后的决定层 P5 **通过**（决策不随成交 bar 的毒化而变："
                 f"ok={fixed['ok']}）；修复前口径 **被捕获**（ok={bug['ok']}, tripped={bug['tripped']}）"
                 "⇒ 探针对该口径有效、非空转。"),
        residual=("**残留**：下沿（gap ≥ −5%）仍靠「09:15–09:20 可撤单窗撤单」实现，"
                  "而撤单决策当时能看到的是**虚拟开盘参考价**、回测用**最终今开**代替 ⇒ "
                  "撤单层仍有同 bar 依赖。已量化机制存在性与噪声量级，见 "
                  "`evidence_band_cancel_bias_20261008.json`（ADR-0004 B-3/R3）。"),
    )
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(ev, fh, ensure_ascii=False, indent=1)
    print("修复后决定层:", {k: fixed[k] for k in ("ok", "tripped")})
    print("修复前口径  :", {k: bug[k] for k in ("ok", "tripped")})
    print("判定:", "PASS" if ok else "FAIL")
    print("已写出", OUT)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
