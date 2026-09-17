# -*- coding: utf-8 -*-
"""PATCH R-gold-sat-0917：黄金卫星叠加投产（2026-09-17 用户拍板按 grill 推荐）
=============================================================================
改动面（4 个既有文件，全部精确锚点替换 + 断言命中数）：
  P1 backtest/satellite_cfg.py        追加黄金常量（权重/标的/名义/股票袖预算）
  P2 backtest/build_satellite_pool.py 轨B 计划金额改用股票袖预算（CAP_B−黄金）——展示口径
  P3 daily_refresh.py                 插入「黄金卫星模拟盘 gold_sat_paper[软]」步骤（在 satellite_paper 之前）+ git 白名单
  P4 build_dual_system.py             插入黄金卫星卡 _gold_sat_card()/GOLD_SAT_CARD 并挂进视图 A
  P5 changelog.md                     置顶 v5.13.5 条目

不改 backtest/satellite_paper_0914.py：黄金腿以「镜像持仓」方式落在 satellite_paper_b.json，
其 mark 循环本就逐只 load_px(code) 取价 → 黄金市值自动进轨B 净值，零逻辑改动。

用法：python _patch_goldsat_0917.py --dry     # 只报告命中，不写
      python _patch_goldsat_0917.py           # 落盘
"""
import sys
from pathlib import Path

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
DRY = "--dry" in sys.argv
LOG = []


def patch(path, anchor, repl, tag, expect=1):
    t = path.read_text(encoding="utf-8")
    n = t.count(anchor)
    assert n == expect, f"[{tag}] 锚点命中 {n} 次（期望 {expect}） @ {path.name}"
    if anchor in ("__APPEND__",):
        raise AssertionError("use append()")
    t = t.replace(anchor, repl, expect)
    if not DRY:
        path.write_text(t, encoding="utf-8")
    LOG.append(f"  [ok] {tag} @ {path.name}")
    return t


def append(path, text, tag, guard):
    t = path.read_text(encoding="utf-8")
    if guard in t:
        LOG.append(f"  [skip] {tag}（已存在 {guard}）")
        return
    if not DRY:
        path.write_text(t.rstrip("\n") + "\n" + text, encoding="utf-8")
    LOG.append(f"  [ok] {tag} @ {path.name}")


# ---------------- P1 satellite_cfg.py ----------------
GOLD_CFG = '''

# ---- 黄金卫星叠加（R-gold-sat-0917 · 2026-09-17 用户拍板按 grill 推荐投产）----
# 证据：backtest/verify_gold_sat_0917.json（独立复验）+ backtest/lowcorr_stage2_crossasset_0916.json（stage2 全枚举）
# 卫星层 ΔS(w10)=+0.104（采纳门 +0.02，同窗 100% 轨B 基准）；分半 h1/h2 双正；安慰剂（同权重换现金）为负。
# 黄金腿 = sh518880 买入持有（c_gold_bh phmed 1.002 / 0 笔交易；择时臂 c_gold_mom 仅 0.757 → 不采纳）。
# 只做卫星层：book 档（60% FB3+40% 轨B）盈亏平衡需黄金年化 14.4% → 硬伤，不上。
GOLD_CODE = "sh518880"                  # 黄金ETF华安（data_full/sh518880.csv 在位）
GOLD_W = 0.10                           # 黄金占卫星（轨B）权重
GOLD_NOTIONAL = round(CAP_B * GOLD_W)   # 6800 = 黄金袖名义资金
STOCK_BUDGET_B = CAP_B - GOLD_NOTIONAL  # 61200 = 轨B 股票袖预算（卫星总敞口仍 = CAP_B，不超配）
GOLD_MODE = "buy_hold"                  # 买入持有、永不卖出；永不回补（漂移仅看板展示）
'''
append(BASE / "backtest" / "satellite_cfg.py", GOLD_CFG, "P1 黄金常量", "GOLD_CODE")

# ---------------- P2 build_satellite_pool.py ----------------
patch(BASE / "backtest" / "build_satellite_pool.py",
      "from satellite_cfg import CAP_A, CAP_B, ROLE_A, ROLE_B, REBASED  # 单一来源（R-single-track-0915）",
      "from satellite_cfg import (CAP_A, CAP_B, ROLE_A, ROLE_B, REBASED,  # 单一来源（R-single-track-0915）\n"
      "                          STOCK_BUDGET_B, GOLD_CODE, GOLD_W, GOLD_NOTIONAL)  # R-gold-sat-0917",
      "P2a import 股票袖预算")

patch(BASE / "backtest" / "build_satellite_pool.py",
      '        "amount": round(CAP_B / n_b),',
      '        "amount": round(STOCK_BUDGET_B / n_b),   # R-gold-sat-0917：轨B 股票袖预算（68000−6800），黄金另计',
      "P2b 轨B 计划金额")

patch(BASE / "backtest" / "build_satellite_pool.py",
      '''        "bt": {"total": 22.87, "ann": 22.87, "mdd": -22.0, "sharpe": 1.30,''',
      '''        "gold_overlay": {"code": GOLD_CODE, "name": "黄金ETF华安", "w": GOLD_W,
                         "notional": GOLD_NOTIONAL, "stock_budget": STOCK_BUDGET_B,
                         "mode": "买入持有（B&H）· 永不回补",
                         "note": "卫星层 ΔS(w10)=+0.104 过门（+0.02）；只做卫星层，book 档不上"},
        "bt": {"total": 22.87, "ann": 22.87, "mdd": -22.0, "sharpe": 1.30,''',
      "P2c 轨B 黄金元信息")

# ---------------- P3 daily_refresh.py ----------------
GOLD_STEP = '''    # 黄金卫星叠加模拟盘（R-gold-sat-0917 · 2026-09-17 用户拍板投产）：轨B 内划出 10%（6800）
    # 买入 sh518880 买入持有（B&H），并把黄金腿镜像成轨B 的一个 position。**必须在 satellite_paper 之前**
    # ——satellite_paper 的 mark 循环会逐只 load_px(code) 取价 → 黄金市值自动进轨B 净值（总敞口保持 CAP_B）。
    # [软]=失败不阻断主链；--skip-gold 跳过。
    ("黄金卫星模拟盘 gold_sat_paper[软]", ["backtest/gold_sat_paper.py"], "--skip-gold" in sys.argv),
'''
patch(BASE / "daily_refresh.py",
      '    ("双卫星模拟盘 satellite_paper", ["backtest/satellite_paper_0914.py"], False),',
      GOLD_STEP + '    ("双卫星模拟盘 satellite_paper", ["backtest/satellite_paper_0914.py"], False),',
      "P3a 插入黄金步骤")

patch(BASE / "daily_refresh.py",
      '                          "backtest/satellite_paper_init.json", "backtest/turn_shadow_state.json",',
      '                          "backtest/satellite_paper_init.json", "backtest/turn_shadow_state.json",\n'
      '                          "backtest/gold_sat_paper.json", "backtest/gold_sat_paper.py",\n'
      '                          "backtest/shadow_ret20.py", "backtest/engine_anchor.json",\n'
      '                          "backtest/shadow_ret20/ledger.csv", "backtest/shadow_ret20/state.json",\n'
      '                          "backtest/shadow_ret20/daily_metrics.jsonl",',
      "P3b git 白名单")

# ---------------- P4 build_dual_system.py ----------------
CARD_CODE = '''

# 黄金卫星叠加卡（R-gold-sat-0917 · 2026-09-17 用户拍板投产）
# 数据源：backtest/gold_sat_paper.json（daily_refresh「黄金卫星模拟盘」软步骤产出）
def _gold_sat_card():
    import json as _js
    try:
        _g = _js.loads((BASE / "backtest" / "gold_sat_paper.json").read_text(encoding="utf-8"))
        _m = _g.get("meta", {})
        _nh = _g.get("nav_history", [])
        _notional = float(_m.get("notional") or 6800.0)
        _last = _nh[-1] if _nh else {}
        _nav = float(_last.get("nav") or _notional)
        _ret = (_nav / _notional - 1) * 100
        _share = float(_last.get("share") or 0.0) * 100
        _lots = int(sum(float(p.get("shares", 0)) for p in (_g.get("positions") or {}).values()) // 100)
        _stat = "运行中" if _nh else "待建仓"
        _cold = "#10b981" if _ret >= 0 else "#ef4444"
        _flags = "；".join(_m.get("hard_flags") or [])
        return (f'<div class="card" id="gold-sat-card">'
                f'<h2>🥇 黄金卫星叠加（轨B 内 10% · sh518880 买入持有） <span class="badge badge-auto">2026-09-17 投产 · 只做卫星层</span></h2>'
                f'<div class="kpis">'
                f'<div class="kpi"><div class="l">黄金袖净值</div><div class="v">{_nav / _notional:.4f}</div><div class="s">名义 {_notional:.0f} · {_lots} 手</div></div>'
                f'<div class="kpi"><div class="l">累计收益</div><div class="v" style="color:{_cold}">{_ret:+.2f}%</div><div class="s">B&H · 无卖出</div></div>'
                f'<div class="kpi"><div class="l">实际占比</div><div class="v">{_share:.1f}%</div><div class="s">目标 10% · 永不回补</div></div>'
                f'<div class="kpi"><div class="l">状态</div><div class="v">{_stat}</div><div class="s">信号 {_m.get("signal_date", "—")} → T+1 开盘</div></div>'
                f'</div>'
                f'<div class="sub">叠加式 <code>r_sat=(1−w)·r_B+w·r_gold</code>，w=10%，<b>替换</b>轨B 的 10%（卫星总敞口仍 68000，不超配）· 黄金腿 = 518880 买入持有、永不卖出 · 卫星层 ΔS(w10) = <b>+0.104</b>（采纳门 +0.02）· 分半 h1/h2 双正</div>'
                f'<div class="sub" style="color:#b45309">⚠ 硬伤申报：{_flags}</div>'
                f'<div class="sub" style="color:var(--faint)">账本 backtest/gold_sat_paper.json；黄金腿已镜像进轨B 账户（卫星 mark 逐只取价自动计入净值）。每日链内刷新。</div>'
                f'</div>')
    except Exception as _e:
        return (f'<div class="card" id="gold-sat-card"><h2>🥇 黄金卫星叠加</h2>'
                f'<div class="sub">gold_sat_paper.json 未生成（{_e}）→ 运行 backtest/gold_sat_paper.py</div></div>')

GOLD_SAT_CARD = _gold_sat_card()
'''
patch(BASE / "build_dual_system.py",
      "SHADOW_RET20_CARD = _shadow_ret20_card()",
      "SHADOW_RET20_CARD = _shadow_ret20_card()" + CARD_CODE,
      "P4a 黄金卡定义")

patch(BASE / "build_dual_system.py",
      "{SAT_PAPER_B_CARD}\n{FUND_PAPER_CARD}",
      "{SAT_PAPER_B_CARD}\n{GOLD_SAT_CARD}\n{FUND_PAPER_CARD}",
      "P4b 黄金卡挂载")

# ---------------- P5 changelog.md ----------------
_cl = BASE / "changelog.md"
_ct = _cl.read_text(encoding="utf-8")
if "v5.13.5" in _ct:
    LOG.append("  [skip] P5 changelog（已存在 v5.13.5）")
else:
    _lines = _ct.splitlines(keepends=True)
    _hdr = 1 if _lines and _lines[0].lstrip().startswith("#") else 0
    _entry = ("\n## v5.13.5（2026-09-17）黄金卫星叠加投产（轨B 内 10% · sh518880 买入持有）\n"
              "- **投产**（用户拍板按 grill 推荐）：卫星层 w=10%，`r_sat=(1−w)·r_B+w·r_gold`，**替换**轨B 的 10%"
              "（卫星总敞口仍 68000，不超配）；黄金腿 518880 **买入持有、永不卖出**。\n"
              "- 新增 `backtest/gold_sat_paper.py`（黄金袖账本 `backtest/gold_sat_paper.json`）+ `satellite_cfg.py` "
              "黄金常量（`GOLD_W/GOLD_NOTIONAL/STOCK_BUDGET_B`）+ 每日链新步骤（软，在 satellite_paper 之前）"
              "+ 看板「🥇 黄金卫星叠加」卡。\n"
              "- 实现要点：黄金腿以**镜像持仓**落进 `satellite_paper_b.json`，卫星 mark 逐只取价自动计入净值 → "
              "`satellite_paper_0914.py` **零逻辑改动**。\n"
              "- 证据：卫星层 ΔS(w10)=+0.104（门 +0.02）、分半双正、安慰剂为负；`verify_gold_sat_0917.json` 独立复验。\n"
              "- **硬伤申报**：卫星档保 ΔS≥+0.02 需黄金年化 ≈5%/年；B&H 换手≈0 故 50bp 档不构成成本证据；"
              "样本窗 2021-08→2026-09 为黄金大牛段，样本外未测。book 档（需黄金 14.4%/年）不上。\n")
    _lines.insert(_hdr, _entry)
    if not DRY:
        _cl.write_text("".join(_lines), encoding="utf-8")
    LOG.append("  [ok] P5 changelog v5.13.5")

print(("[dry] " if DRY else "[write] ") + "PATCH R-gold-sat-0917")
print("\n".join(LOG))
