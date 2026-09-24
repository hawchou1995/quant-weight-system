#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""左侧捡漏 · 单日信号入口（bt520 双簿框架「纯左侧簿」逐字移植 · 自包含）

策略定义（ADR-0010 D5/D9）：bt520「纯左侧簿（主簿关闭）· 槽位5」= KB=5 · wB=1.0
  · wB = 1.0 → Book A（520 战法 ∪ 海龟）资金权重 0 = 主簿关闭，只买左侧簿。
  · KB = 5   → 左侧簿 5 个槽位。

================================================================================
规则来源（冻结库 `E:/PI/投资/bt520_turtle_regime/`，**只读**；本文件不 import 该目录）
逐条对应 file:line，全部原样移植：
================================================================================
R1  股票池（主板，含复权断裂剔除）
    · 池 = sh600/601/603/605 + sz000/001/002/003            [build_panel.py:40 MAIN_RE]
    · 剔复权断裂 4 只 {600733,000509,600165,000670}         [build_panel.py:41 BROKEN_ADJ]
    · 北交所/创业板/科创板由前缀白名单天然排除；盘后按代码排序 [build_panel.py:83-93]
R2  日历与对齐
    · 日历 = 沪深300 交易日 ∩ [2016-01-04, as_of]           [build_panel.py:37 WARM_START, 59-66]
    · 个股行不在日历内 → 丢弃；缺失日 = NaN 空位            [build_panel.py:117-127]
    · close/open ≤0 或 NaN → 视为缺失（high/low/amount 原样）[build_panel.py:134-135]
R3  可交易域 tradable = finite(close) & nvalid>=250 & amt20>=2e7 & ~st_like
    · nvalid = 日历内有效收盘的累计计数                     [build_panel.py:137-138; strategies.py:165-172]
    · amt20  = amount 20 日简单均值（rolling, min_periods=20）[build_panel.py:143]
    · st_like（ST-PIT 探针）= maxabs60 ∈ [0.047, 0.0505]，其中
      maxabs60 = |日收益率| 的 20 日最大（min_periods=20）   [build_panel.py:144-150 ST_BAND/ST_HIT/ST_WIN]
R4  左侧入场信号 LS_E（Book B 的 E 指标）
    · DD20 = close / rolling_max(close,20) − 1（20 日最高收盘，**含当日**，min_periods=20）
                                                            [run_r16_yearly.py:81-82]
    · LS_E = DD20 ≤ −0.08（逐字沿用）                        [run_r16_yearly.py:82]
    · **不过 fresh()（新鲜触发）**：LS_E 原样入队             [run_r16_yearly.py:92 传 LS_E；对照 strategies.py:209-213]
R5  抢槽排序键 strength = max(520 腿强度, 海龟系统二强度)（float32）[run_r16_yearly.py:68 STG]
    · 520 腿强度 = clip(1 − PLD/8.0, 0, 1)，PLD=(C−MA20)/MA20×100
      （8.0 = 宽放档 pld；本排序键取 tier=宽放/var=no_vol 的强度）
                                        [run_r16_yearly.py:60,68; strategies.py:35 TIERS, 105, 130-131]
    · 海龟二腿强度 = clip((C/前55日最高 − 1)/0.05, 0, 1)，
      前55日最高 = shift(rolling_max(H,55), 1)（不含当日）
                                        [run_r16_yearly.py:63,68; strategies.py:153,157-159]
    · 抢槽顺序 = strength 降序，同值按列序（= 代码字典序）升序
      （np.lexsort((idx, -stv))，列序 = sorted(文件名)）      [engine.py:279-281]
R6  槽位与仓位（wB=1.0 分支）
    · K = KB = 5；域权重表 W_LEFT 全域 (1.00, 0.00)          [run_r16_yearly.py:71,92]
    · 最大余数法：ideal=[1.0×5, 0] → slots=(5,0)（5 槽全给左侧簿）[engine.py:160-172]
    · 单笔金额 = NAV(t−1)/5（现金驱动、无杠杆、分数股）       [engine.py:156,195-197]
    · 总持仓 ≤ 5；已持仓票跳过；每票每根 K 线只买一次         [engine.py:183,185]
R7  买点：T 日收盘出信号 → T+1 开盘成交
    · 成交价 = T+1 的 open；open 非有限/≤0 → 跳过            [engine.py:187-189]
    · 追高上限 gap_max = 0.05：open/前收 − 1 > 0.05 → 跳过   [engine.py:190-194; run_r16_yearly.py:39]
    · 买入成本 = max(0.0086%, 5元/(本金×单笔占比))            [engine.py:201-206; run_r16_yearly.py:37]
    · 本金 1,000,000 元                                      [run_r16_yearly.py:37]
R8  止损：**无**（左侧簿 strat 号 = STRAT_520 = 1）
    · stop 仅在 s_id == STUR(2) 且 use_stop_2 时按 ATR 生成；本配置 use_stop_1=False、
      stop_pct=None、strat=1 → 全程 stop=None，挂单式止损对左侧簿不生效
                                        [engine.py:128-134, 209-214; run_r16_yearly.py:93-94]
    · skip_on_win 只作用于海龟腿                         [engine.py:118-119, 285-287]
R9  出场（T 日收盘标记 → T+1 开盘成交）
    · RSI14 > 75 指标出场：RSI = 100 − 100/(1+gain/loss)，
      gain = ΔC.clip(lower=0).rolling(14, min_periods=1).mean()（**简单平均，非 Wilder**），
      loss = (−ΔC.clip(upper=0)).rolling(14, min_periods=1).mean()；
      loss==0 → 置 NaN → RSI=NaN → **不出场**
                                        [run_r16_yearly.py:74-80; engine.py:240-243]
    · 到期平仓：持有满 max_hold=60 个交易日              [engine.py:249-252; run_r16_yearly.py:93]
    · 通道出场 exit_close 对 strat=1 为 None → 左侧簿无死叉/通道出场
                                        [run_r16_yearly.py:67; engine.py:244-248]
    · exposure=ones / nav_cb=None / early_exit=None → 均不生效
                                        [run_r16_yearly.py:72; engine.py:150-155, 253-270]
R10 成本（真实口径）
    · 佣金 0.0086%/边，**最低 5 元/笔**（本金 100 万 → 门槛 = 单笔 < 58,140 元）
    · 印花税（卖出单边，PIT 分段）：2023-08-28 起 0.05%，此前 0.10%；过户费 0
                                        [run_r16_yearly.py:37-38; engine.py:96-102, 201-205]
R11 年化日历 244 日                                        [run_r16_yearly.py:39; engine.py:305]

冻结留痕（移植时点 sha256，只作来源锚定，不在运行时读取 E: 盘）：
  engine.py        656c6f4982f6465858e68cc59976549c5f13a0de383110c217ac6f592d58700b
  strategies.py    c927d1f036a6717c25bd8226b8be9f494c8c835f730b6473fa73999c0a1f3133
  run_r16_yearly.py 745a147ba4ddb0c238743f75899ce659af52f1a695aa5082408a83e3f9bb298d
  build_panel.py   328848133da41da98a46ede32b79177d7bbe1c36ab4a539556fd8ed3e886b361

================================================================================
本入口的职责边界（不越界声明）
================================================================================
· 只做**入场侧单日判定**：给定 as_of 收盘，输出 T+1 开盘的候选池 / 跟踪池 /
  （关闭状态的）模拟盘账本。**不重做组合回测**：全期与留出段读数见
  `backtest/zuoce_jianlou_backtest.json`（来源 = 冻结库 out_r16 + `backtest/bt520_holdout_0924.json`）。
· T+1 开盘的 gap_max 过滤、现金约束、已持仓跳过都要等 T+1 数据 → 本入口只标
  「待 T+1 开盘判定」，绝不预支成交。
· ADR-0010 D4/D9：留出测试未过门（A1 不通过）→ 只上回测数据、**不开模拟盘**。
  故 `zuoce_jianlou_paper_state.json` 恒为 `trading_enabled=false` /
  `gate="holdout_gate_failed"`（留出段复测门已跑完且未通过），不建仓、不产生净值、不写权益曲线。
· 移植保真度（如实声明）：冻结库面板把价格存为 float32（build_panel.py:101-106），
  本入口直接读 data_full 的 CSV 原始 float64。阈值边界（DD20 恰在 −8%、
  ST 探针恰在 4.7%/5.05%）理论上可有极少数分歧；已用 panel.npz 做过逐格对照，
  结果写在产物的 `replication` 段（不隐藏、不放宽）。
· 数据口径：REPO 根 `data_full/{pre}{code}.csv`（= 冻结库同一份
  `D:/Documents/Quant data/data_full`，REPO 内为符号链接）+ `index_000300.csv`
  + `data_full_names.json`，**不依赖 164MB 全史面板**。

CLI：
  python backtest/zuoce_jianlou_daily.py [--date YYYY-MM-DD] [--dry-run] [--out-json]
    --date      默认取本地数据最新交易日（index_000300.csv 最后一个日历日）
    --dry-run   只算不落盘（幂等性/口径自检用）
    --out-json  打印机读摘要 JSON（替代人类可读摘要）
  退出码：0 成功 / 2 用法或日期错误 / 1 运行失败
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

# ── 路径（本文件位于 REPO/backtest/）────────────────────────────────────────
BASE = Path(__file__).resolve().parents[1]
DATA_DIR = BASE / "data_full"
INDEX_CSV = BASE / "index_000300.csv"
NAMES_JSON = BASE / "data_full_names.json"
POOL_JS = BASE / "zuoce_jianlou_pool.js"
TRACK_JS = BASE / "zuoce_jianlou_track.js"
PAPER_STATE = BASE / "backtest" / "zuoce_jianlou_paper_state.json"

RULE_VERSION = "zuoce-jianlou.leftbook.bt520.v1"
FROZEN_DIR = "E:/PI/投资/bt520_turtle_regime"

# ── 冻结常量（逐条对应 docstring 的 file:line，不得私改）────────────────────
MAIN_PREFIXES = ("sh600", "sh601", "sh603", "sh605", "sz000", "sz001", "sz002", "sz003")
BROKEN_ADJ = {"600733", "000509", "600165", "000670"}
WARM_START = "2016-01-04"
MIN_LIST_DAYS = 250
AMT_MIN = 2.0e7
ST_BAND = 0.0505
ST_HIT = 0.047
ST_WIN = 20
DD_TH = -0.08
K_B = 5
W_B = 1.0
MAX_HOLD = 60
GAP_MAX = 0.05
RSI_WIN = 14
RSI_EXIT = 75.0
ANN_DAYS = 244.0
COMM = 0.000086
COMM_MIN = 5.0
CAPITAL = 1_000_000.0
STAMP_NEW, STAMP_OLD, STAMP_DAY = 0.0005, 0.001, "2023-08-28"
STRAT_520 = 1          # 左侧簿信号沿用的 strat 号（run_r16_yearly.py:84-85）
DETAILS_MAX = 2000     # 明细上限（超出只写汇总 + 显式 overflow，绝不静默丢票）
WIN = 90               # 尾部“日历位置”窗口：>57 即可覆盖 prev_high55+shift(1) 与 20 日窗

STRATEGY = "左侧捡漏"
STRATEGY_KEY = "zuoce_jianlou"
GATE = "holdout_gate_failed"
# 来源：backtest/bt520_holdout_0924.json 的 verdict.total == "不通过"
#   A1 中位年化 wB=1.0 −8.24% / wB=0.8 −5.13%（均 < 0）
#   A2 单路径年化 wB=1.0 −6.59% / wB=0.8 −4.08%（均 < 0）
#   A3 −22.06%（> −40%）通过；A4 全样本 +9.91% 过 / 留出段 −3.59% 不过；A5 成本×3 +10.70% 通过
# 判定规则 = A1–A5 全满足才通过 ⇒ 总判定不通过 ⇒ 不开模拟盘。


# 移植时点的逐格对照记录（人工核对用；不是每日重算）——见 --out-json 的 replication 字段
REPLICATION_RECORD = {
    "check": "cell-parity vs 冻结库 panel.npz @2026-09-22（逐票 ls_e / tradable 比对）",
    "status": "pending_first_run",
    "note": "首次跑通后由 backtest 侧人工核对回填；本字段只记录移植时点结论，不参与每日计算。",
}

DOMAIN_LABEL = {-1: "不可判定", 0: "熊", 1: "弱牛", 2: "强牛"}


# ══════════════════════════════════════════════════════════════════════════
# 数据层
# ══════════════════════════════════════════════════════════════════════════
def load_calendar():
    """沪深300 日历 ∩ [WARM_START, 末]（build_panel.py:37,59-66）；返回 dates/close/MA 表"""
    if not INDEX_CSV.exists():
        raise SystemExit("缺 %s（R2：日历基准）" % INDEX_CSV)
    idx = pd.read_csv(INDEX_CSV, encoding="utf-8-sig")
    idx["date"] = idx["date"].astype(str)
    idx = idx[idx["date"] >= WARM_START].reset_index(drop=True)
    if idx.empty:
        raise SystemExit("index_000300.csv 在 %s 之后无数据" % WARM_START)
    dates = idx["date"].tolist()
    close = idx["close"].to_numpy(dtype=np.float64)

    def _ma(n):
        return pd.Series(close).rolling(n, min_periods=n).mean().to_numpy()

    maes = {n: _ma(n) for n in (20, 60, 120, 250)}   # build_panel.py:71-78
    return dates, close, maes


def regime_state_3(close, maes):
    """T−1 沪深300 三域状态（2 强牛 / 1 弱牛 / 0 熊 / −1 不可判定）
    [strategies.py:176-198, ma_line='MA60', n_domain=3]
    **纯展示**：W_LEFT 全域 (1.00,0.00)，牛熊域对纯左侧簿的槽位分配无影响
    （run_r16_yearly.py:71）。"""
    n = len(close)
    st = np.zeros(n, dtype=int)
    if n < 2:
        return st
    c1 = np.concatenate([[np.nan], close[:-1]])
    m20 = np.concatenate([[np.nan], maes[20][:-1]])
    m60 = np.concatenate([[np.nan], maes[60][:-1]])
    st[(c1 > m60) & (c1 <= m20)] = 1
    st[(c1 > m20)] = 2
    st[~np.isfinite(m60)] = -1
    return st


def iter_codes(data_dir=DATA_DIR):
    """主板池按代码字典序（= 冻结库面板的列序 build_panel.py:83-93）"""
    out = []
    for f in sorted(os.listdir(data_dir)):
        if not f.endswith(".csv") or len(f) < 12:
            continue
        if f[:5] not in MAIN_PREFIXES:                 # R1
            continue
        code = f[:-4]
        if code[2:8] in BROKEN_ADJ:                    # R1
            continue
        out.append((code, data_dir / f))
    return out


def compute_cells(as_of, cal_idx):
    """逐票算 as_of 的判定量（对齐日历 + 尾部窗口滚动，等价于全史面板的末列取值）。

    返回 (cells, diag)；cells[code] 含 ls_e / tradable / dd20 / strength 等。
    对齐/rolling 语义与冻结库逐位一致：
      · 位置网格 = 日历（个股缺行 = NaN 空位）           [build_panel.py:117-127]
      · rolling(n, min_periods=n) → 窗口内必须有 n 个非 NaN 值 [与 pandas 面板同法]
    """
    t = cal_idx[as_of]
    cells = {}
    read_fail = []
    for code, path in iter_codes():
        try:
            df = pd.read_csv(path, usecols=["date", "open", "high", "low", "close", "amount"],
                             encoding="utf-8-sig")
        except Exception as e:   # 与 build_panel.py:111-115 同法：失败登记，不静默跳过
            read_fail.append("%s: %s" % (code, e))
            continue

        dt = df["date"].astype(str).to_numpy()
        pos = np.fromiter((cal_idx.get(d, -1) for d in dt), dtype=np.int64, count=len(dt))
        keep = pos >= 0
        if not keep.any():
            continue
        pos = pos[keep]
        ordr = np.argsort(pos, kind="stable")
        pos = pos[ordr]
        o = df["open"].to_numpy(dtype=np.float64)[keep][ordr]
        h = df["high"].to_numpy(dtype=np.float64)[keep][ordr]
        c = df["close"].to_numpy(dtype=np.float64)[keep][ordr]
        a = df["amount"].to_numpy(dtype=np.float64)[keep][ordr]

        # R2：open/close ≤0 或 NaN → 缺失（high/low/amount 原样，与 build_panel.py:134-135 一致）
        c = np.where(np.isfinite(c) & (c > 0), c, np.nan)
        o = np.where(np.isfinite(o) & (o > 0), o, np.nan)
        # R3：有效收盘累计到 as_of（build_panel.py:137-138 的逐日累计口径；
        #     不得计入学 as_of 之后的行，否则历史日期回看会失真）
        nvalid = int(np.count_nonzero(np.isfinite(c) & (pos <= t)))          # R3

        # 尾部窗口（只覆盖 t 之前的位置；rolling 末值 = 全史末值）
        lo = max(0, t - (WIN - 1))
        sel = (pos >= lo) & (pos <= t)      # 只用 as_of 及其之前的行（as_of<t 时排除未来行）
        n = t - lo + 1
        Cw = np.full(n, np.nan)
        Hw = np.full(n, np.nan)
        Aw = np.full(n, np.nan)
        Ow = np.full(n, np.nan)
        Cw[pos[sel] - lo] = c[sel]
        Hw[pos[sel] - lo] = h[sel]
        Aw[pos[sel] - lo] = a[sel]
        Ow[pos[sel] - lo] = o[sel]

        S = pd.Series(Cw)
        mx = float(S.rolling(20, min_periods=20).max().iloc[-1])           # R4 DD20 分母
        ma20 = float(S.rolling(20, min_periods=20).mean().iloc[-1])        # R5 520 腿
        amt20 = float(pd.Series(Aw).rolling(20, min_periods=20).mean().iloc[-1])          # R3 [build_panel.py:143]
        prev_high55 = float(pd.Series(Hw).rolling(55, min_periods=55).max().shift(1).iloc[-1])  # R5 [strategies.py:153]
        ret = S / S.shift(1) - 1.0                                        # = pct_change(fill_method=None)
        maxabs60 = float(ret.abs().rolling(ST_WIN, min_periods=ST_WIN).max().iloc[-1])    # R3 [build_panel.py:144-145]
        delta = S.diff()
        gain = delta.clip(lower=0).rolling(RSI_WIN, min_periods=1).mean()                 # R9 [run_r16_yearly.py:77]
        loss = (-delta.clip(upper=0)).rolling(RSI_WIN, min_periods=1).mean()              # R9 [run_r16_yearly.py:78]
        rsi = float((100.0 - 100.0 / (1.0 + gain / loss.replace(0, np.nan))).iloc[-1])    # R9 [run_r16_yearly.py:79]

        c_now = float(S.iloc[-1])
        prev_c = float(S.iloc[-2]) if n >= 2 else float("nan")
        o_now = float(Ow[-1])

        def _fin(*xs):
            return all(np.isfinite(x) for x in xs)

        dd20 = (c_now / mx - 1.0) if (_fin(c_now, mx) and mx > 0) else float("nan")
        ls_e = bool(_fin(dd20) and dd20 <= DD_TH)                          # R4
        st_like = bool(_fin(maxabs60) and (ST_HIT <= maxabs60 <= ST_BAND))  # R3 [build_panel.py:147-150]
        tradable = bool(_fin(c_now) and nvalid >= MIN_LIST_DAYS
                        and _fin(amt20) and amt20 >= AMT_MIN and not st_like)   # R3

        pld = ((c_now - ma20) / ma20 * 100.0) if (_fin(c_now, ma20) and ma20 > 0) else float("nan")
        s520 = float(np.clip(1.0 - pld / 8.0, 0.0, 1.0)) if _fin(pld) else 0.0   # R5 宽放 pld=8.0
        stur = float(np.clip((c_now / prev_high55 - 1.0) / 0.05, 0.0, 1.0)) \
            if (_fin(c_now, prev_high55) and prev_high55 > 0) else 0.0          # R5 海龟二
        strength = float(np.maximum(np.float32(s520), np.float32(stur)))        # R5 float32 口径
        chg = ((c_now / prev_c - 1.0) * 100.0) if (_fin(c_now, prev_c) and prev_c > 0) else float("nan")

        cells[code] = dict(code=code, close=c_now, open=o_now, prev_close=prev_c,
                           nvalid=nvalid, amt20=amt20, maxabs60=maxabs60, st_like=st_like,
                           dd20=dd20, rsi14=rsi, ma20=ma20, prev_high55=prev_high55,
                           strength=strength, s520=s520, stur=stur,
                           ls_e=ls_e, tradable=tradable, chg=chg)

    diag = dict(n_universe=len(cells) + len(read_fail), n_cells=len(cells),
                n_read_fail=len(read_fail), read_fail=read_fail[:20])
    return cells, diag


def _r(x, nd=4):
    """固定精度（幂等产物：不落无界浮点）"""
    if x is None:
        return None
    x = float(x)
    if not np.isfinite(x):
        return None
    return round(x, nd)


def snapshot(as_of, cal, close, maes, names):
    """as_of 收盘 → 候选池/跟踪池（含 rules 逐条覆盖诊断）"""
    cal_idx = {d: i for i, d in enumerate(cal)}
    if as_of not in cal_idx:
        raise ValueError("as_of=%s 不在沪深300日历内（%s → %s）" % (as_of, cal[0], cal[-1]))
    t = cal_idx[as_of]
    cells, diag = compute_cells(as_of, cal_idx)

    n_tradable = sum(1 for c in cells.values() if c["tradable"])
    n_ls = sum(1 for c in cells.values() if c["ls_e"])
    pool = [c for c in cells.values() if (c["ls_e"] and c["tradable"])]     # R4∩R3 = engine pending 条件
    pool.sort(key=lambda c: (-c["strength"], c["code"]))                   # R5 抢槽序
    for i, c in enumerate(pool):
        c["rank"] = i + 1
        c["in_slots"] = bool(i < K_B)                                      # R6 5 槽

    reg = regime_state_3(close, maes)
    dom = int(reg[t]) if 0 <= t < len(reg) else -1
    return dict(as_of=as_of, cells=cells, pool=pool, diag=diag,
                n_tradable=n_tradable, n_ls=n_ls, n_slots_used=min(K_B, len(pool)),
                domain=dom, domain_label=DOMAIN_LABEL.get(dom, "—"),
                calendar_days=len(cal), calendar_first=cal[0], calendar_last=cal[-1])


# ══════════════════════════════════════════════════════════════════════════
# 产物构造（schema 与 short_pool.js / a5_pool.js 同构：顶层 as_of + details + 分组）
# ══════════════════════════════════════════════════════════════════════════
def _cfg():
    return dict(KB=K_B, wB=W_B, book="纯左侧簿（Book B，主簿关闭）", K=K_B,
                entry="E · DD20 ≤ −8%（close/max(close,20)−1，含当日）",
                exit="RSI14 > 75 指标出场 / 持有满 60 交易日",
                no_stop=True, gap_max=GAP_MAX, max_hold=MAX_HOLD, ann_days=int(ANN_DAYS),
                cost="佣金0.0086%/边·最低5元/笔·印花税卖出单边PIT(2023-08-28起0.05%)",
                capital_yuan=CAPITAL)


def build_pool_obj(snap, names):
    pool = snap["pool"]
    det = {}
    for c in pool[:DETAILS_MAX]:
        code = c["code"]
        det[code[2:8]] = {
            "code": code, "code6": code[2:8], "key": code[2:8],
            "name": names.get(code, ""), "board": "主板", "pool": STRATEGY_KEY,
            "rank": c["rank"], "in_slots": c["in_slots"],
            "px": _r(c["close"], 3), "chg": _r(c["chg"], 2),
            "dd20": _r(c["dd20"] * 100.0, 2), "strength": _r(c["strength"], 6),
            "rsi14": _r(c["rsi14"], 2), "ma20": _r(c["ma20"], 3),
            "prev_high55": _r(c["prev_high55"], 3),
            "amt20_yi": _r(c["amt20"] / 1e8, 3), "nvalid": int(c["nvalid"]),
            "has_open": bool(np.isfinite(c["open"])),
            "planned_exec": "T+1 开盘（须过 gap_max=5% 追高过滤）",
        }
    ordered = [c["code"] for c in pool]
    overflow = 0
    codes6 = [c[2:8] for c in ordered[:DETAILS_MAX]]
    if len(pool) > DETAILS_MAX:
        overflow = len(pool) - DETAILS_MAX
    return {
        "as_of": snap["as_of"],
        "strategy": STRATEGY,
        "strategy_key": STRATEGY_KEY,
        "book": "纯左侧簿（bt520 Book B / 主簿关闭）",
        "config": _cfg(),
        "rule_version": RULE_VERSION,
        "source": {
            "frozen_lib": FROZEN_DIR,
            "rules": "engine.py / strategies.py / run_r16_yearly.py / build_panel.py（sha256 见脚本头）",
            "data": "data_full/{pre}{code}.csv + index_000300.csv + data_full_names.json（REPO 根）",
            "universe": "仅主板（sh600/601/603/605 + sz000/001/002/003，剔复权断裂 4 只）",
            "note": "本池为 REPO data_full 逐票日线重算结果，非全史面板缓存（两者同源）。",
        },
        "replication": REPLICATION_RECORD,
        "counts": {
            "universe": snap["diag"]["n_universe"],
            "read_fail": snap["diag"]["n_read_fail"],
            "tradable": snap["n_tradable"],
            "ls_e": snap["n_ls"],
            "pool": len(pool),
            "slots": K_B, "slots_used": snap["n_slots_used"],
            "details": len(det), "details_overflow": overflow,
        },
        "regime": {"domain": snap["domain"], "label": snap["domain_label"],
                   "note": "纯展示：W_LEFT 全域 (1.00,0.00)，牛熊域对纯左侧簿槽位无影响"},
        "details": det,
        "tiers": {"主板": codes6},
        "picks": codes6[:K_B],
        "reserve": codes6[K_B:K_B + 5],
        "trading_enabled": False,
        "gate": GATE,
        "note": ("入场只在 T+1 开盘成交（gap_max=5% 过滤 + 现金约束），本文件为 T 日收盘的候选池；"
                 "模拟盘未开（ADR-0010 D4/D9：留出测试未过门）→ 见 backtest/zuoce_jianlou_paper_state.json。"
                 + ("｜池超出 %d 只，details 只列前 %d（按 strength），其余见 tiers['主板']。"
                    % (overflow, DETAILS_MAX) if overflow else "")),
    }


def build_track_obj(snap, names):
    """跟踪池：可买（槽位内候选）+ 备选；持仓/退出需 T+1 后逐日复算，模拟盘未开 → 恒空"""
    as_of = snap["as_of"]
    pool = snap["pool"]

    def _row(c, status, planned):
        return {
            "code": c["code"], "code6": c["code"][2:8], "name": names.get(c["code"], ""),
            "board": "主板", "pool": STRATEGY_KEY, "rank": c["rank"], "status": status,
            "signal_date": as_of, "in_pool_since": as_of, "entry_date": None,
            "entry_planned": planned, "in_slots": bool(c["in_slots"]),
            "px": _r(c["close"], 3), "chg": _r(c["chg"], 2), "dd20": _r(c["dd20"] * 100.0, 2),
            "strength": _r(c["strength"], 6), "rsi14": _r(c["rsi14"], 2), "ma20": _r(c["ma20"], 3),
            "prev_high55": _r(c["prev_high55"], 3), "amt20_yi": _r(c["amt20"] / 1e8, 3),
            "nvalid": int(c["nvalid"]), "has_open": bool(np.isfinite(c["open"])),
        }

    entries = [_row(c, "可买（槽位内·待 T+1 开盘判定 gap_max=5%）",
                    "T+1 开盘（%s 之后下一交易日；open/前收−1 > 5%% 则跳过）" % as_of)
               for c in pool[:K_B]]
    reserve = [_row(c, "备选（槽位已满，仅有票序无仓位）", "仅在槽位空出时按票序递补")
               for c in pool[K_B:K_B + 5]]
    return {
        "as_of": as_of,
        "strategy": STRATEGY,
        "strategy_key": STRATEGY_KEY,
        "book": "纯左侧簿（bt520 Book B / 主簿关闭）",
        "rule_version": RULE_VERSION,
        "config": _cfg(),
        "trading_enabled": False,
        "gate": GATE,
        "entries": entries,
        "reserve": reserve,
        "holdings": [],
        "exits": [],
        "counts": {
            "pool": len(pool), "entries": len(entries), "reserve": len(reserve),
            "holdings": 0, "exits": 0, "slots": K_B, "slots_used": snap["n_slots_used"],
        },
        "note": ("跟踪池 = T 日收盘候选（前 %d 进槽位，单笔=NAV/%d）；成交在 T+1 开盘，"
                 "持仓与出场（RSI14>75 或满 %d 交易日）须在 T+1 之后逐日复算。"
                 "模拟盘未开（gate=%s）→ holdings/exits 恒空，本文件不含任何伪造净值。"
                 % (K_B, K_B, MAX_HOLD, GATE)),
        "source": "backtest/zuoce_jianlou_daily.py · data_full 逐票日线重算",
    }


def build_state_obj(snap):
    """模拟盘账本：恒 trading_enabled=false / gate=holdout_gate_failed（不开仓、不记净值）"""
    pool = snap["pool"]
    sig = [c["code"][2:8] for c in pool]
    watch = [c["code"][2:8] for c in pool[:K_B]]
    return {
        "strategy": STRATEGY,
        "strategy_key": STRATEGY_KEY,
        "book": "纯左侧簿（bt520 Book B / 主簿关闭）",
        "as_of": snap["as_of"],
        "rule_version": RULE_VERSION,
        "config": _cfg(),
        "trading_enabled": False,
        "gate": GATE,
        "gate_note": ("ADR-0010 D4/D9/D11：留出段（2016-01-04→2017-12-29）复测门**已跑完且未通过**"
                      "（bt520_holdout_0924.json verdict.total=不通过；A1 −8.24% / A2 −6.59% 为负） → 只上回测数据，"
                      "不开模拟盘、不写净值。每次运行恒写 trading_enabled=false。"),
        "capital": None, "cash": None, "nav": None, "nav_as_of": None,
        "equity": [], "positions": [], "closed": [],
        "pending": {"signal_date": snap["as_of"], "exec": "T+1 开盘", "gap_max": GAP_MAX,
                    "orders": [], "note": "未开仓 → 无委托（slot 权重=NAV/%d）" % K_B},
        "signals": sig,
        "watch": watch,
        "counts": {"signals": len(sig), "watch": len(watch),
                   "positions": 0, "closed": 0, "orders": 0},
        "note": ("模拟盘未开（gate=%s）。signals/watch 仅为当日候选与槽位内名单，不代表持仓；"
                 "净值/持仓一律 null/[] 而非填充值。" % GATE),
        "source": "backtest/zuoce_jianlou_daily.py",
    }


# ══════════════════════════════════════════════════════════════════════════
# 写盘（原子 + LF；产物幂等：无时间戳、键排序、固定精度）
# ══════════════════════════════════════════════════════════════════════════
def _dump(obj):
    """确定性 JSON：键排序 + 无空格 + 禁 NaN（NaN → 抛错，不产出非法 JSON）"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_" + path.name, suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_js(path, varname, obj, header):
    head = "// %s\n" % header if header else ""
    _write_text(path, head + "window.%s = %s;\n" % (varname, _dump(obj)))


def write_json(path, obj):
    _write_text(path, _dump(obj) + "\n")


def load_names():
    """data_full_names.json（键为带前缀代码，如 sz000001）；缺失/损坏 → 空表（不阻断）"""
    if not NAMES_JSON.exists():
        return {}
    try:
        raw = json.loads(NAMES_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            nm = v.get("name") or v.get("名称") or ""
        else:
            nm = v
        out[str(k)] = str(nm) if nm is not None else ""
    return out


def latest_calendar_day():
    if not INDEX_CSV.exists():
        return None
    idx = pd.read_csv(INDEX_CSV, encoding="utf-8-sig")
    idx["date"] = idx["date"].astype(str)
    idx = idx[idx["date"] >= WARM_START]
    return None if idx.empty else str(idx["date"].iloc[-1])


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════
def main(argv=None):
    ap = argparse.ArgumentParser(prog="zuoce_jianlou_daily",
                                 description="左侧捡漏 · 单日信号入口（bt520 纯左侧簿 KB=5 / wB=1.0）")
    ap.add_argument("--date", default=None, metavar="YYYY-MM-DD",
                    help="as_of 交易日；默认 = 本地数据（index_000300.csv）最新交易日")
    ap.add_argument("--dry-run", action="store_true", help="只计算，不写任何产物")
    ap.add_argument("--out-json", action="store_true", help="打印机器可读摘要 JSON")
    a = ap.parse_args(argv)

    try:
        as_of = a.date or latest_calendar_day()
    except Exception as e:
        print("[ERR] 读取 %s 失败: %s" % (INDEX_CSV, e), file=sys.stderr)
        return 1
    if not as_of:
        print("[ERR] 无法确定 as_of：index_000300.csv 无 %s 之后数据" % WARM_START, file=sys.stderr)
        return 2

    try:
        cal, idx_close, maes = load_calendar()
    except SystemExit as e:
        print("[ERR] %s" % e, file=sys.stderr)
        return 2
    if as_of not in set(cal):
        print("[ERR] --date %s 不在沪深300日历 [%s → %s] 内（R2）"
              % (as_of, cal[0], cal[-1]), file=sys.stderr)
        return 2

    names = load_names()
    try:
        snap = snapshot(as_of, cal, idx_close, maes, names)
        pool_obj = build_pool_obj(snap, names)
        track_obj = build_track_obj(snap, names)
        state_obj = build_state_obj(snap)
    except Exception as e:
        print("[ERR] 计算失败: %r" % (e,), file=sys.stderr)
        return 1

    written = []
    if not a.dry_run:
        try:
            write_js(POOL_JS, "ZUOCE_POOL", pool_obj,
                     "左侧捡漏 · 选股池（自动生成·勿手改）as_of=%s rule_version=%s" % (as_of, RULE_VERSION))
            write_js(TRACK_JS, "ZUOCE_TRACK", track_obj,
                     "左侧捡漏 · 跟踪池（自动生成·勿手改）as_of=%s rule_version=%s" % (as_of, RULE_VERSION))
            write_json(PAPER_STATE, state_obj)
        except Exception as e:
            print("[ERR] 写盘失败: %r" % (e,), file=sys.stderr)
            return 1
        written = [str(POOL_JS), str(TRACK_JS), str(PAPER_STATE)]

    top3 = [{"code": d["code"], "code6": d["code6"], "name": d["name"],
             "px": d["px"], "dd20": d["dd20"], "strength": d["strength"]}
            for d in track_obj["entries"][:3]]
    summary = {
        "as_of": as_of, "strategy": STRATEGY, "strategy_key": STRATEGY_KEY,
        "rule_version": RULE_VERSION, "dry_run": bool(a.dry_run),
        "calendar": {"first": cal[0], "last": cal[-1], "days": len(cal)},
        "counts": pool_obj["counts"], "slots_used": snap["n_slots_used"],
        "regime": {"domain": snap["domain"], "label": snap["domain_label"]},
        "top3": top3, "paper_state_path": str(PAPER_STATE), "written": written,
        "trading_enabled": False, "gate": GATE, "replication": REPLICATION_RECORD,
    }
    if a.out_json:
        print(_dump(summary))
        return 0

    # ── 人类可读摘要 ─────────────────────────────────────────────────────
    c = pool_obj["counts"]
    print("左侧捡漏 · 单日信号（bt520 纯左侧簿 KB=%d / wB=%.1f）" % (K_B, W_B))
    print("  as_of            : %s" % as_of)
    print("  日历             : %s → %s（%d 交易日，R2）" % (cal[0], cal[-1], len(cal)))
    print("  数据             : universe=%d 读失败=%d | tradable=%d | LS_E=%d"
          % (c["universe"], c["read_fail"], c["tradable"], c["ls_e"]))
    print("  选股池成员数     : %d（LS_E ∩ tradable）｜槽位 %d 已用 %d｜备选 %d"
          % (c["pool"], K_B, c["slots_used"], len(track_obj["reserve"])))
    print("  明细             : %d 只%s"
          % (c["details"], ("（超出 %d 只未列明细，见 tiers['主板']）" % c["details_overflow"])
             if c["details_overflow"] else ""))
    print("  域状态           : %s（纯展示：W_LEFT 全域 (1.00,0.00)，不影响左侧簿槽位）"
          % snap["domain_label"])
    if track_obj["entries"]:
        for i, d in enumerate(track_obj["entries"], 1):
            print("    #%d %s %-6s 收盘=%s  DD20=%s%%  强度=%s  → T+1 开盘（gap_max=5%%）"
                  % (i, d["code6"], d["name"] or "—", d["px"], d["dd20"], d["strength"]))
    else:
        print("    （空池：as_of 无满足 R4∩R3 的票；空池不是错误，不递补、不放宽口径）")
    print("  账本             : %s" % PAPER_STATE)
    print("  trading_enabled  : false（gate=%s；ADR-0010 D4/D9 留出门未过 → 不开仓）" % GATE)
    if a.dry_run:
        print("  [dry-run] 未写盘（以上仅为目标路径）")
    else:
        for p in written:
            print("  已写             : %s" % p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
