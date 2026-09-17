# -*- coding: utf-8 -*-
"""PATCH R-gold-sat-0917 补丁 2：口径回改（汇总报告矛盾句）+ CONTEXT.md 黄金词条
用法：python _patch_goldsat_0917b_docs.py --dry / 无参落盘
"""
import sys
from pathlib import Path

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
DRY = "--dry" in sys.argv
LOG = []

# ---------------- A: 汇总报告 §2.2 口径回改 ----------------
p = BASE / "backtest" / "报告-本批汇总-20260916傍晚至0917.md"
t = p.read_text(encoding="utf-8")
old = ("stage1 190 词对 / stage2 跨资产 / stage3 时间结构 38 标的（含 all-universe 对照）→ **全否**："
       "corr 下限 0.557→0.465，低相关与正收益系统性互斥，股票域内不可得。")
new = (old + "\n\n> **口径回改（2026-09-17 R-gold-sat-0917）**：「全否」是**批次口径**——"
       "stage2 跨资产 30 腿作为一族整体不过门；但**唯 `c_gold_bh`（黄金 ETF sh518880 买入持有）单腿例外**，"
       "作为「★ 特别项」单列于 `报告-未投产策略回测Top10-0917.md`（卫星层 ΔS(w10)=+0.104 过门 +0.02、"
       "分半双正、安慰剂为负），并按用户拍板**已投产**（卫星层 w=10%，轨B 内替换）。"
       "**勿据本节「全否」误杀黄金线**；book 档（需黄金年化 14.4%）确为否。")
if new.split("\n\n>")[0] == old and "R-gold-sat-0917" not in t:
    assert t.count(old) == 1, f"锚点命中 {t.count(old)} 次"
    if not DRY:
        p.write_text(t.replace(old, new), encoding="utf-8")
    LOG.append(f"  [ok] A 汇总报告口径回改 @ {p.name}")
elif "R-gold-sat-0917" in t:
    LOG.append("  [skip] A 已回改过")
else:
    raise AssertionError("A 锚点未命中")

# ---------------- B: CONTEXT.md 黄金词条 ----------------
GOLD_GLOSSARY = """

**黄金卫星（gold satellite）**:
卫星层的一种**叠加替换**形态：把轨B 的一部分权重换成黄金，`r_sat=(1−w)·r_B+w·r_gold`。当前 w = 10%（6800），
**卫星总敞口不变**。它只作用于卫星层；组合层（book，60% 主仓 + 40% 卫星）档经评估不上（盈亏平衡需黄金年化 14.4%）。
_Avoid_: 黄金配置、避险仓位（歧义——是替换不是新增敞口）

**黄金腿 / 黄金袖（gold sleeve）**:
承载黄金卫星腿的独立账本（名义 6800），持仓同时镜像进轨B 账户，使卫星 mark 逐只取价时自动计入净值。
_Avoid_: 黄金账户（易与券商实盘账户混淆——这是模拟盘账本）

**买入持有（B&H）**:
黄金腿的唯一形态：一次建仓、**永不卖出、永不回补**。实际占比随时间漂移，漂移只展示不纠正。
_Avoid_: 长期持有、定投（都不等价——本词的核心是「不回补」，与持有时长无关）

**硬伤申报（卫星档）**:
黄金卫星投产时随配置一并声明、不可省略的三条限制：① 保 ΔS≥+0.02 需黄金年化 ≈5%/年（盈亏平衡 ≈3~4%/年）；
② B&H 换手≈0 → 50bp 成本压力档**不构成**稳健性证据；③ 样本窗为黄金大牛段，样本外风险未测。
_Avoid_: 风险提示（本词指**已量化、有阈值**的三条，不是泛泛提示）
"""
p2 = BASE / "CONTEXT.md"
t2 = p2.read_text(encoding="utf-8")
if "黄金卫星（gold satellite）" in t2:
    LOG.append("  [skip] B CONTEXT 已含黄金词条")
else:
    if not DRY:
        p2.write_text(t2.rstrip("\n") + "\n" + GOLD_GLOSSARY, encoding="utf-8")
    LOG.append("  [ok] B CONTEXT.md 黄金词条 ×4")

print(("[dry] " if DRY else "[write] ") + "PATCH R-gold-sat-0917b (docs)")
print("\n".join(LOG))
