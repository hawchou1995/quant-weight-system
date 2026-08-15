# -*- coding: utf-8 -*-
"""
综合指标权重系统回测引擎 v5（2026-08-12 · 恐贪指数 FG 吸收候选）
================================================================
基线 = v4 生产版（权重甲 + 布林位置分 + 量价三件套 patch）。
v5 新增推文「积极信号在积累，指标持续向好+期权策略」（东胜小猢狲 2026-08-07）
核心指标吸收评估：
1. USE_FG_GATE     分指数恐贪指标（FG，Fear & Greed）→ 市场状态层动态门槛
                   推文方法论：各指数日K线衍生 5 维 + 滚动分位归一化（W=250日），输出 0-100 恐贪值
                   本引擎用沪深300（000300）OHLCV 计算 5 维 FG：
                   D1 动量 / D2 趋势 / D3 波动率 / D4 回撤 / D5 量能，等权滚动分位归一化
2. USE_FG_WEIGHT   FG 作为第 7 维指标直接进入总分（权重从现有六类挤出 5%）
3. USE_FG_DYNAMIC  FG 连续值动态调节 BUY_WEAK / SELL_STRONG（替代三档离散门禁）
                   方向由 FG_MODE 决定："defensive"=恐惧防御（门槛上移）/ "opportunistic"=恐惧机会（门槛下移）
4. 期权仪表盘指标（TV 分位 / 万份作多概率 / IV-IVV）：数据源不可得（需期权链历史），
   本引擎不吸收进回测，仅任务 2 可视化借鉴 —— 结论标注「待数据源接入」
杠杆第 7 维（两融分位）：历史两融余额数据源不可得，标注「待数据源接入」。
验收标准（27 池等权组合）：收益 ≥ v4 基线 +141.54% 且最大回撤 ≤ 20%。
运行：python weight_system_backtest_v5_fg.py
输出：weight_system_v5_fg_results.json（多实验对比）
"""
import pandas as pd
import numpy as np
import json
import os
import math
from datetime import datetime

# ---------------------------------------------------------------------------
# 0. 领域池（与 v2 一致）
# ---------------------------------------------------------------------------
SECTOR_POOL = {
    "AI算力": [("300502", "新易盛", "股票", "sz", None), ("300308", "中际旭创", "股票", "sz", "L1"),
               ("600498", "烽火通信", "股票", "sh", None)],
    "半导体": [("603986", "兆易创新", "股票", "sh", None), ("688981", "中芯国际", "股票", "sh", None),
               ("002185", "华天科技", "股票", "sz", None)],
    "PCB电子": [("002463", "沪电股份", "股票", "sz", None), ("600183", "生益科技", "股票", "sh", None),
                ("603228", "景旺电子", "股票", "sh", None)],
    "白酒": [("600519", "贵州茅台", "股票", "sh", None), ("000858", "五粮液", "股票", "sz", None),
             ("000568", "泸州老窖", "股票", "sz", None)],
    "银行": [("601398", "工商银行", "股票", "sh", None), ("600036", "招商银行", "股票", "sh", None),
             ("000001", "平安银行", "股票", "sz", None)],
    "新能源": [("300750", "宁德时代", "股票", "sz", None), ("002594", "比亚迪", "股票", "sz", None),
               ("300274", "阳光电源", "股票", "sz", None)],
    "医药": [("600276", "恒瑞医药", "股票", "sh", None), ("603259", "药明康德", "股票", "sh", None),
             ("300760", "迈瑞医疗", "股票", "sz", None)],
    "资源能源": [("601088", "中国神华", "股票", "sh", None), ("601225", "陕西煤业", "股票", "sh", None),
                 ("601899", "紫金矿业", "股票", "sh", None)],
    "消费": [("600887", "伊利股份", "股票", "sh", None), ("603288", "海天味业", "股票", "sh", None),
             ("002714", "牧原股份", "股票", "sz", None)],
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DATA_TMP_DIR = os.path.join(BASE_DIR, "data_tmp")

# ---- 权重候选（专家先验，grill Q10 三候选）----
WT_A = {"trend": 0.30, "momentum": 0.25, "volume": 0.15, "osc": 0.15, "risk": 0.10, "news": 0.05}
WT_B = {"trend": 0.32, "momentum": 0.26, "volume": 0.14, "osc": 0.13, "risk": 0.10, "news": 0.05}
WT_C = {"trend": 0.33, "momentum": 0.25, "volume": 0.15, "osc": 0.13, "risk": 0.08, "news": 0.06}

# ---- 操作阈值（与 v2 一致）----
BUY_STRONG = 75
BUY_WEAK = 62
SELL_WEAK = 40
SELL_STRONG = 30
MARKET_ADJUST = {
    "strong": {"BUY_WEAK": 58, "SELL_STRONG": 28},
    "normal": {"BUY_WEAK": 62, "SELL_STRONG": 30},
    "weak": {"BUY_WEAK": 65, "SELL_STRONG": 35},
}

# ---- v3 增量开关（基线 = v3 选型：仅布林位置分；其余默认关）----
USE_MARKET_GATE = True      # v2 市场状态三档门禁（保留）
USE_AGGRESSIVE_STRONG = True  # v2 实验4 强势进攻增强（保留，已验证通过）
USE_A3 = True               # v2 量价位置区分（保留）
USE_MA_TRIPLE = False       # v3-1 均线 5/20/60 三线状态分（回测否决，默认关）
USE_BOLL_POS = True         # v3-2 布林带 %B 位置分（唯一采纳项）
USE_RESO_PATCH = False      # v3-3 三重指标共振补丁（回测否决 -16.9pct，默认关）
USE_BULL_BEAR = False       # v3-4 轻牛熊系数（回测否决 -1.8pct，默认关）

# ---- v4 量价强化开关（候选，实验矩阵覆盖）----
USE_EXTREME_VOL = False     # v4-1 地量见底/天量见顶（双确认+位置门控）
USE_PDV = False             # v4-2 纯量价背离（价量 20 日极值背离）→ volume 类
USE_RSI_DIV = False         # v4-3 RSI 背离 + 量能验证 → osc 类
SCORE_MODE = "evidence"     # "patch"=补丁式±10 / "evidence"=分支内 cap/floor
PDV_BONUS = 10.0            # 量价背离补丁式幅度
RSIDIV_BONUS = 10.0         # RSI 背离补丁式幅度

# ---- v5 恐贪指数 FG 开关（推文「积极信号在积累」吸收候选）----
USE_FG_GATE = False         # v5-1 FG 市场情绪动态门槛（替代三档离散门禁）
USE_FG_WEIGHT = False       # v5-2 FG 作为第 7 维权重（从六类挤出 5%）
USE_FG_DYNAMIC = False      # v5-3 FG 连续动态调节 BUY_WEAK/SELL_STRONG
FG_MODE = "defensive"       # "defensive"=恐惧防御（门槛上移）/ "opportunistic"=恐惧机会（门槛下移）
FG_W = 250                  # 滚动分位窗口（推文 W=250）
FG_WINDOW = 20              # 分维子窗口（动量/波动/量能）
FG_WEIGHT = 0.05            # FG 第 7 维权重（从六类等比例挤出）
FG_K_BUY = 6.0              # FG 动态门槛斜率：BUY_WEAK ± 系数×(50-FG)/50
FG_K_SELL = 5.0             # FG 动态门槛斜率：SELL_STRONG ± 系数×(50-FG)/50
FG_BUY_CLAMP = (50.0, 78.0)  # 动态 BUY_WEAK 钳位
FG_SELL_CLAMP = (22.0, 42.0) # 动态 SELL_STRONG 钳位

# ---- v3 参数 ----
RESO_BONUS = 10.0           # 共振同向加分（3 信号全同向）
RESO_PENALTY = 10.0         # 共振分歧减分（≤1 信号同向）
BB_MA20_LO, BB_MA20_HI = 0.95, 1.05   # MA20 系数范围
BB_YR_BULL, BB_YR_BEAR = 1.08, 0.92   # 年线牛/熊系数
BB_DEV_CAP = 5.0            # 沪深300 偏离截断（±5%）

# ---- 回测区间与费用（与 v2 一致）----
BACKTEST_START = "2024-01-01"
BACKTEST_END = "2026-08-07"
INITIAL_CASH = 1_000_000.0
COMMISSION = 0.00025
SELL_TAX = 0.0005
LOT = 100
CAP_PCT = 0.50


# ---------------------------------------------------------------------------
# 1. 数据加载（与 v2 一致）
# ---------------------------------------------------------------------------
def load_data(code: str) -> pd.DataFrame:
    for d in (DATA_DIR, DATA_TMP_DIR):
        p = os.path.join(d, f"{code}.csv")
        if os.path.exists(p):
            df = pd.read_csv(p)
            df["date"] = pd.to_datetime(df["date"])
            for c in ["open", "high", "low", "close"]:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            return df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    raise FileNotFoundError(f"{code}.csv not found in data/ or data_tmp/")


def load_index(code: str) -> pd.DataFrame:
    p = os.path.join(DATA_TMP_DIR, f"index_{code}.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p)
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    return df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)


def load_index_full(code: str) -> pd.DataFrame:
    """加载完整 OHLCV 指数（用于 FG 恐贪 5 维计算）。"""
    p = os.path.join(DATA_TMP_DIR, f"index_{code}_full.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p)
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    return df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 2. 指标计算（v2 + ma60 + 布林带）
# ---------------------------------------------------------------------------
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["ma5"] = d["close"].rolling(5).mean()
    d["ma10"] = d["close"].rolling(10).mean()
    d["ma20"] = d["close"].rolling(20).mean()
    d["ma60"] = d["close"].rolling(60).mean()
    # 布林带(20, 2)
    std20 = d["close"].rolling(20).std()
    d["boll_up"] = d["ma20"] + 2 * std20
    d["boll_dn"] = d["ma20"] - 2 * std20
    d["boll_pct"] = (d["close"] - d["boll_dn"]) / (d["boll_up"] - d["boll_dn"]).replace(0, np.nan)
    prev_close = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - prev_close).abs(),
                    (d["low"] - prev_close).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    d["atr_pct"] = d["atr"] / d["close"] * 100
    ema12 = d["close"].ewm(span=12, adjust=False).mean()
    ema26 = d["close"].ewm(span=26, adjust=False).mean()
    d["dif"] = ema12 - ema26
    d["dea"] = d["dif"].ewm(span=9, adjust=False).mean()
    d["macd_hist"] = (d["dif"] - d["dea"]) * 2
    low9 = d["low"].rolling(9).min()
    high9 = d["high"].rolling(9).max()
    rsv = (d["close"] - low9) / (high9 - low9) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d["k"] = k
    d["d"] = k.ewm(alpha=1 / 3, adjust=False).mean()
    d["j"] = 3 * k - 2 * d["d"]
    delta = d["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    d["rsi"] = (100 - 100 / (1 + rs)).fillna(100)
    up_move = d["high"].diff()
    down_move = -d["low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr_s = tr.ewm(alpha=1 / 14, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=d.index).ewm(alpha=1 / 14, adjust=False).mean() / tr_s.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=d.index).ewm(alpha=1 / 14, adjust=False).mean() / tr_s.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    d["adx"] = dx.ewm(alpha=1 / 14, adjust=False).mean()
    vol_ma5 = d["volume"].rolling(5).mean()
    d["vol_ratio"] = d["volume"] / vol_ma5.replace(0, np.nan)
    d["pct_chg"] = d["close"].pct_change() * 100
    d["ma20_dev"] = (d["close"] - d["ma20"]) / d["ma20"] * 100
    d["mom20"] = d["close"] / d["close"].shift(20) * 100 - 100
    d["high60"] = d["close"].rolling(60).max()
    d["dd60"] = (d["close"] / d["high60"] - 1) * 100
    # ---- v4 量价候选列（极值/背离）----
    vol_ma20 = d["volume"].rolling(20).mean()
    d["vol_low20"] = (d["volume"] == d["volume"].rolling(20).min()) & (d["volume"] > 0)   # 20日量新低
    d["vol_high20"] = (d["volume"] == d["volume"].rolling(20).max()) & (d["volume"] > 0)  # 20日量新高
    d["vol_max19"] = d["volume"].shift(1).rolling(19).max()   # 前19日最高量（不含当日）
    d["vol_min19"] = d["volume"].shift(1).rolling(19).min()   # 前19日最低量
    d["px_high20"] = d["close"] >= d["close"].rolling(20).max()  # 价创20日新高
    d["px_low20"] = d["close"] <= d["close"].rolling(20).min()   # 价创20日新低
    d["rsi_max19"] = d["rsi"].shift(1).rolling(19).max()      # 前19日 RSI 高点
    d["rsi_min19"] = d["rsi"].shift(1).rolling(19).min()      # 前19日 RSI 低点
    rets = d["close"].pct_change()
    d["vol20_ann"] = rets.rolling(20).std() * math.sqrt(252)
    return d


# ---------------------------------------------------------------------------
# 3. 六类打分（v2 + v3 增量）
# ---------------------------------------------------------------------------
def _clip(x):
    return max(0.0, min(100.0, float(x)))


def _ma_triple_score(row):
    """均线 5/20/60 三线状态：多头排列高、空头排列低、纠缠中分（知识库：5日强弱/20日方向/60日大势）。"""
    if any(np.isnan(x) for x in (row["ma5"], row["ma20"], row["ma60"])):
        return 12.5
    if row["ma5"] > row["ma20"] > row["ma60"]:
        return 25.0
    if row["ma5"] < row["ma20"] < row["ma60"]:
        return 0.0
    # 部分纠缠：按 5>20 与 20>60 的个数给分
    n_up = (row["ma5"] > row["ma20"]) + (row["ma20"] > row["ma60"])
    return 8.0 if n_up == 1 else 16.0


def score_trend(row):
    if USE_MA_TRIPLE:
        s = 0.0
        if not np.isnan(row["ma20"]):
            if row["close"] > row["ma20"]:
                s += 30 if row["ma20_dev"] < 15 else 22
            else:
                s += 8 if row["ma20_dev"] > -8 else 0
        else:
            s += 15
        if not np.isnan(row["adx"]):
            if row["adx"] >= 25: s += 25
            elif row["adx"] >= 20: s += 18
            elif row["adx"] >= 15: s += 10
            else: s += 3
        else:
            s += 12
        if not np.isnan(row["mom20"]):
            if row["mom20"] > 8: s += 20
            elif row["mom20"] > 0: s += 15
            elif row["mom20"] > -8: s += 8
            else: s += 3
        else:
            s += 10
        s += _ma_triple_score(row)
        return _clip(s)
    # 原 v2 逻辑（无三线）
    s = 0.0
    if not np.isnan(row["ma20"]):
        if row["close"] > row["ma20"]:
            s += 40 if row["ma20_dev"] < 15 else 30
        else:
            s += 10 if row["ma20_dev"] > -8 else 0
    else:
        s += 20
    if not np.isnan(row["adx"]):
        if row["adx"] >= 25: s += 30
        elif row["adx"] >= 20: s += 22
        elif row["adx"] >= 15: s += 12
        else: s += 4
    else:
        s += 15
    if not np.isnan(row["mom20"]):
        if row["mom20"] > 8: s += 30
        elif row["mom20"] > 0: s += 22
        elif row["mom20"] > -8: s += 12
        else: s += 4
    else:
        s += 15
    return _clip(s)


def score_momentum(row):
    s = 0.0
    if not np.isnan(row["dif"]) and not np.isnan(row["dea"]):
        if row["dif"] > row["dea"]:
            s += 40 if row["dif"] > 0 else 30
        else:
            s += 12 if row["dif"] > 0 else 4
    else:
        s += 25
    if not np.isnan(row["pct_chg"]):
        atr_norm = row["atr_pct"] if not np.isnan(row["atr_pct"]) else 3.0
        if row["pct_chg"] >= 0:
            s += 30 if row["pct_chg"] >= 2 else 22
        else:
            if row["pct_chg"] <= -2.5 * max(atr_norm, 1.5):
                s += 0
            elif row["pct_chg"] <= -1 * atr_norm:
                s += 8
            else:
                s += 15
    else:
        s += 15
    if not np.isnan(row["macd_hist"]):
        s += 20 if row["macd_hist"] > 0 else 6
    else:
        s += 10
    return _clip(s)


def score_volume(row):
    if np.isnan(row["vol_ratio"]):
        return 50.0
    s = 0.0
    vr = row["vol_ratio"]
    dd = row["dd60"] if not np.isnan(row["dd60"]) else -50.0
    high_zone = dd > -12
    low_zone = dd < -15
    # v4-1 地量见底/天量见顶（双确认 + 位置门控）→ 直接调整量比分档
    extreme_adjust = 0.0
    if USE_EXTREME_VOL:
        is_di = bool(row["vol_low20"]) and vr < 0.6 and low_zone      # 低位地量 = 见底候选
        is_tian = bool(row["vol_high20"]) and vr > 2.5 and high_zone  # 高位天量 = 见顶候选
        if is_di:
            extreme_adjust = +15.0
        elif is_tian:
            extreme_adjust = -15.0
    if 1.2 <= vr <= 1.8: s += 50
    elif 0.9 <= vr < 1.2: s += 38
    elif 1.8 < vr <= 2.5: s += 40
    elif vr > 2.5: s += 25 + extreme_adjust
    elif 0.6 <= vr < 0.9: s += 25 + extreme_adjust
    else: s += 12 + extreme_adjust
    if not np.isnan(row["pct_chg"]):
        if row["pct_chg"] > 0 and vr >= 1.0:
            s += 50
        elif row["pct_chg"] > 0 and vr < 1.0:
            s += 30
        elif row["pct_chg"] <= 0 and vr >= 1.5:
            s += 8 if (USE_A3 and high_zone) else 20
        elif row["pct_chg"] <= 0 and vr >= 1.0:
            s += 20 if (USE_A3 and high_zone) else 30
        else:
            s += 35
    else:
        s += 25
    # v4-2 纯量价背离（价创20日极值但量未同步）→ volume 类
    if USE_PDV:
        px_high = bool(row["px_high20"]) and not np.isnan(row["vol_max19"])
        px_low = bool(row["px_low20"]) and not np.isnan(row["vol_min19"])
        if px_high and row["volume"] < row["vol_max19"] * 0.9:
            # 价创新高但量未同步（顶背离）
            if SCORE_MODE == "patch":
                s -= PDV_BONUS
            else:
                s = min(s, 30.0)
        elif px_low and row["volume"] > row["vol_min19"] * 1.1:
            # 价创新低但量未同步缩（底背离：抛压衰竭）
            if SCORE_MODE == "patch":
                s += PDV_BONUS
            else:
                s = max(s, 45.0)
    return _clip(s)


def _boll_score(row):
    """布林带 %B 位置：>1 超买（高位风险低分）、<0 超卖（低位机会高分）、0.5 中位中分。"""
    b = row["boll_pct"]
    if np.isnan(b):
        return 12.5
    if b >= 1.0: return 5.0
    if b >= 0.8: return 15.0
    if b >= 0.5: return 22.0
    if b >= 0.2: return 15.0
    if b >= 0.0: return 25.0
    return 30.0   # 跌破下轨（超卖区）


def score_osc(row):
    if USE_BOLL_POS:
        rsi_part = 0.0
        if not np.isnan(row["rsi"]):
            rsi = row["rsi"]
            if rsi < 20: rsi_part = 40
            elif rsi < 30: rsi_part = 36
            elif rsi < 50: rsi_part = 30
            elif rsi < 70: rsi_part = 45
            elif rsi < 80: rsi_part = 30
            else: rsi_part = 9
        else:
            rsi_part = 22
        # v4-3 RSI 背离 + 量能验证（素材 37/38 篇：顶背离缩量更可信/底背离放量更靠谱）
        if USE_RSI_DIV and not np.isnan(row["rsi"]):
            px_high = bool(row["px_high20"]) and not np.isnan(row["rsi_max19"])
            px_low = bool(row["px_low20"]) and not np.isnan(row["rsi_min19"])
            vr = row["vol_ratio"] if not np.isnan(row["vol_ratio"]) else 1.0
            if px_high and row["rsi"] < row["rsi_max19"]:
                # 顶背离：价新高但 RSI 高点变矮；缩量更可信 → 惩罚更深
                if SCORE_MODE == "patch":
                    rsi_part -= RSIDIV_BONUS + (5.0 if vr < 1.0 else 0.0)
                else:
                    rsi_part = min(rsi_part, 22.0)
            elif px_low and row["rsi"] > row["rsi_min19"]:
                # 底背离：价新低但 RSI 低点抬高；放量更可信 → 奖励更多
                if SCORE_MODE == "patch":
                    rsi_part += RSIDIV_BONUS + (5.0 if vr > 1.0 else 0.0)
                else:
                    rsi_part = max(rsi_part, 36.0)
        s = rsi_part
        k, dd, adx, macd_hist = row["k"], row["d"], row["adx"], row["macd_hist"]
        if not any(np.isnan(x) for x in [k, dd]):
            if dd < 30:
                if not np.isnan(adx) and adx >= 20 and not np.isnan(macd_hist) and macd_hist > 0:
                    s += 30 if k > dd else 18
                else:
                    s += 11
            elif dd > 70:
                if not np.isnan(adx) and adx >= 20 and not np.isnan(macd_hist) and macd_hist < 0:
                    s += 3
                else:
                    s += 9
            else:
                s += 16
        else:
            s += 15
        s += _boll_score(row)
        return _clip(s)
    # 原 v2 逻辑（无布林）
    s = 0.0
    if not np.isnan(row["rsi"]):
        rsi = row["rsi"]
        if rsi < 20: s += 55
        elif rsi < 30: s += 50
        elif rsi < 50: s += 42
        elif rsi < 70: s += 60
        elif rsi < 80: s += 40
        else: s += 12
    else:
        s += 30
    k, dd, adx, macd_hist = row["k"], row["d"], row["adx"], row["macd_hist"]
    if not any(np.isnan(x) for x in [k, dd]):
        if dd < 30:
            if not np.isnan(adx) and adx >= 20 and not np.isnan(macd_hist) and macd_hist > 0:
                s += 40 if k > dd else 25
            else:
                s += 15
        elif dd > 70:
            if not np.isnan(adx) and adx >= 20 and not np.isnan(macd_hist) and macd_hist < 0:
                s += 4
            else:
                s += 12
        else:
            s += 22
    else:
        s += 20
    return _clip(s)


def score_risk(row):
    s = 0.0
    if not np.isnan(row["atr_pct"]):
        ap = row["atr_pct"]
        if 1.5 <= ap <= 4.5: s += 50
        elif 0.8 <= ap < 1.5 or 4.5 < ap <= 7: s += 35
        else: s += 18
    else:
        s += 25
    if not np.isnan(row["dd60"]):
        if row["dd60"] > -5: s += 50
        elif row["dd60"] > -12: s += 35
        elif row["dd60"] > -20: s += 20
        else: s += 6
    else:
        s += 25
    return _clip(s)


def score_news(news_level):
    if news_level == "L1": return 70.0
    if news_level == "L3": return 30.0
    return 50.0


def reso_patch(row):
    """三重指标共振补丁：MACD柱>0 / K>D / close>ma20 同向度 → 趋势/动能 ±分。"""
    if not USE_RESO_PATCH:
        return 0.0, 0.0
    bulls = 0
    valid = 0
    if not np.isnan(row["macd_hist"]):
        valid += 1
        bulls += 1 if row["macd_hist"] > 0 else 0
    if not any(np.isnan(x) for x in (row["k"], row["d"])):
        valid += 1
        bulls += 1 if row["k"] > row["d"] else 0
    if not np.isnan(row["ma20"]):
        valid += 1
        bulls += 1 if row["close"] > row["ma20"] else 0
    if valid < 3:
        return 0.0, 0.0
    if bulls == 3:
        return RESO_BONUS, RESO_BONUS
    if bulls == 2:
        return RESO_BONUS / 2, RESO_BONUS / 2
    return -RESO_PENALTY, -RESO_PENALTY


def compute_total_score(row, news_level, weights, bb_coef=None):
    st = score_trend(row)
    sm = score_momentum(row)
    sv = score_volume(row)
    so = score_osc(row)
    sr = score_risk(row)
    sn = score_news(news_level)
    # v3-3 共振补丁（乘在类别分上，clip 后生效）
    rt, rm = reso_patch(row)
    st = _clip(st + rt)
    sm = _clip(sm + rm)
    # v3-4 轻牛熊系数：只乘进攻类（趋势/动能/量能），风控/超买超卖/研报恒 1.0
    if USE_BULL_BEAR and bb_coef is not None:
        st = _clip(st * bb_coef)
        sm = _clip(sm * bb_coef)
        sv = _clip(sv * bb_coef)
    total = (st * weights["trend"] + sm * weights["momentum"] + sv * weights["volume"]
             + so * weights["osc"] + sr * weights["risk"] + sn * weights["news"])
    comp = {"trend": st, "momentum": sm, "volume": sv, "osc": so, "risk": sr, "news": sn, "total": total}
    return _clip(total), comp


# ---------------------------------------------------------------------------
# 4. 市场状态 + 牛熊系数
# ---------------------------------------------------------------------------
def _rolling_pctrank(series: pd.Series, window: int) -> pd.Series:
    """滚动分位归一化（W=window）：返回 0-100，表示当前值在过去 window 内的百分位。"""
    out = series.rolling(window, min_periods=max(30, window // 4)).apply(
        lambda x: float((x[-1] >= x).mean()) * 100, raw=True)
    return out


def build_fg_index(index_df: pd.DataFrame) -> dict:
    """分指数恐贪指标 FG（推文方法论：日K线衍生 5 维 + 滚动分位归一化 W=250）。
    5 维（等权）：
      D1 动量：20 日收益率在窗口内的分位（涨多=贪婪）
      D2 趋势：收盘价相对 MA20 偏离在窗口内的分位（强势=贪婪）
      D3 波动率：20 日年化波动率分位（低波=平静=贪婪，高波=恐慌）→ 用 100-分位
      D4 回撤：距窗口高点的回撤分位（接近高点=贪婪）
      D5 量能：量比（当日量/20日均量）分位（放量=贪婪）
    输出 {date_str: fg(0-100)}，FG=50 中性，<45 恐惧区，>55 贪婪区。
    """
    if index_df is None or len(index_df) < FG_W // 2:
        return {}
    d = index_df.copy()
    d["mom20"] = d["close"].pct_change(FG_WINDOW) * 100
    d["ma20"] = d["close"].rolling(FG_WINDOW).mean()
    d["ma20_dev"] = (d["close"] - d["ma20"]) / d["ma20"] * 100
    rets = d["close"].pct_change()
    d["vol20"] = rets.rolling(FG_WINDOW).std() * math.sqrt(252) * 100
    d["hi_win"] = d["close"].rolling(FG_W).max()
    d["dd"] = (d["close"] / d["hi_win"] - 1) * 100
    vol_ma20 = d["volume"].rolling(FG_WINDOW).mean()
    d["vol_ratio"] = d["volume"] / vol_ma20.replace(0, np.nan)
    d["p1"] = _rolling_pctrank(d["mom20"], FG_W)
    d["p2"] = _rolling_pctrank(d["ma20_dev"], FG_W)
    d["p3"] = 100 - _rolling_pctrank(d["vol20"], FG_W)   # 低波=高 FG
    d["p4"] = _rolling_pctrank(d["dd"], FG_W)
    d["p5"] = _rolling_pctrank(d["vol_ratio"], FG_W)
    d["fg"] = d[["p1", "p2", "p3", "p4", "p5"]].mean(axis=1)
    out = {}
    for _, r in d.iterrows():
        if np.isnan(r["fg"]):
            continue
        out[str(r["date"].date())] = round(float(r["fg"]), 1)
    return out


def build_market_state(index_df: pd.DataFrame) -> dict:
    if index_df is None or len(index_df) < 30:
        return {}
    df = index_df.copy()
    df["ma20"] = df["close"].rolling(20).mean()
    df["dev"] = (df["close"] - df["ma20"]) / df["ma20"] * 100
    out = {}
    for _, r in df.iterrows():
        if np.isnan(r["ma20"]):
            continue
        if r["close"] > r["ma20"] and r["dev"] > 2.0:
            out[str(r["date"].date())] = "strong"
        elif r["close"] < r["ma20"]:
            out[str(r["date"].date())] = "weak"
        else:
            out[str(r["date"].date())] = "normal"
    return out


def build_bull_bear_coef(index_df: pd.DataFrame) -> dict:
    """轻牛熊系数：{date_str: coef}，coef = MA20偏离连续系数 × 年线两档（0.95~1.05 × 0.92/1.08）。"""
    if index_df is None or len(index_df) < 260:
        return {}
    df = index_df.copy()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma250"] = df["close"].rolling(250).mean()
    df["dev"] = (df["close"] - df["ma20"]) / df["ma20"] * 100
    out = {}
    for _, r in df.iterrows():
        if np.isnan(r["ma20"]):
            continue
        dev_capped = max(-BB_DEV_CAP, min(BB_DEV_CAP, r["dev"]))
        ma20_coef = 1.0 + dev_capped / BB_DEV_CAP * (BB_MA20_HI - 1.0)  # ±5% → 1.05/0.95
        yr_coef = BB_YR_BULL if (not np.isnan(r["ma250"]) and r["close"] > r["ma250"]) else BB_YR_BEAR
        out[str(r["date"].date())] = round(ma20_coef * yr_coef, 4)
    return out


# ---------------------------------------------------------------------------
# 5. 回测引擎（v2 + 牛熊系数传入）
# ---------------------------------------------------------------------------
def run_backtest(df, news_level, market_state=None, bb_coef=None, weights=None, strategy="weight", fg_state=None):
    weights = weights or WT_A
    d = compute_indicators(df)
    cash = INITIAL_CASH
    position = 0
    entry_price = 0.0
    entry_date = None
    entry_bar = -1
    pending_action = None
    equity_curve = []
    trade_history = []
    turnover_value = 0.0
    eval_start = pd.Timestamp(BACKTEST_START)
    eval_end = pd.Timestamp(BACKTEST_END)

    for i in range(len(d)):
        row = d.iloc[i]
        date = row["date"]
        open_p, close_p = row["open"], row["close"]
        date_str = str(date.date())
        if pd.isna(close_p) or pd.isna(open_p):
            value = cash + position * close_p if not pd.isna(close_p) else cash + position * (entry_price or 0)
            if eval_start <= date <= eval_end:
                equity_curve.append({"date": date_str, "value": round(value, 2)})
            continue
        in_eval = eval_start <= date <= eval_end
        indicators_ready = not pd.isna(row["ma20"]) and not pd.isna(row["rsi"])

        if USE_MARKET_GATE and market_state:
            ms = market_state.get(date_str, "normal")
            bw = MARKET_ADJUST[ms]["BUY_WEAK"]
            ss = MARKET_ADJUST[ms]["SELL_STRONG"]
        else:
            bw, ss = BUY_WEAK, SELL_STRONG
        # v5-3 FG 连续动态门槛（替代三档离散）：恐惧区门槛上移（防御）/ 下移（机会）
        if (USE_FG_DYNAMIC or USE_FG_GATE) and fg_state:
            fg = fg_state.get(date_str, 50.0)
            dev = (50.0 - fg) / 50.0   # 恐惧(FG<50)→dev>0；贪婪(FG>50)→dev<0
            sign = 1.0 if FG_MODE == "defensive" else -1.0
            bw = bw + sign * FG_K_BUY * dev
            ss = ss + sign * FG_K_SELL * dev
            bw = max(FG_BUY_CLAMP[0], min(FG_BUY_CLAMP[1], bw))
            ss = max(FG_SELL_CLAMP[0], min(FG_SELL_CLAMP[1], ss))
        if USE_AGGRESSIVE_STRONG and market_state and market_state.get(date_str, "") == "strong":
            bs_eff, sw_eff = 70, 35
        else:
            bs_eff, sw_eff = BUY_STRONG, SELL_WEAK

        if pending_action is not None and in_eval:
            action, amount = pending_action
            pending_action = None
            if action == "buy":
                target_value = amount * INITIAL_CASH
                cur_value = position * open_p
                cap_value = max(0.0, target_value - cur_value)
                add_value = min(cap_value, CAP_PCT * INITIAL_CASH)
                add_shares = int(add_value / (open_p * (1 + COMMISSION)))
                add_shares = (add_shares // LOT) * LOT
                add_size = min(add_shares, int(cash / (open_p * (1 + COMMISSION))) // LOT * LOT)
                if add_size > 0:
                    cost = add_size * open_p * (1 + COMMISSION)
                    if cost <= cash:
                        cash -= cost
                        turnover_value += cost
                        if position == 0:
                            entry_price = open_p
                            entry_date = date
                            entry_bar = i
                        position += add_size
            elif action == "sell":
                target_value = amount * INITIAL_CASH
                cur_value = position * open_p
                cap_value = max(0.0, cur_value - target_value)
                sell_value = min(cap_value, CAP_PCT * INITIAL_CASH)
                sell_shares = int(sell_value / open_p)
                sell_shares = (sell_shares // LOT) * LOT
                sell_size = min(sell_shares, position)
                if sell_size > 0:
                    tax = sell_size * open_p * SELL_TAX
                    proceeds = sell_size * open_p * (1 - COMMISSION) - tax
                    pnl = proceeds - sell_size * entry_price * (1 + COMMISSION)
                    pnl_pct = (open_p / entry_price - 1) * 100 if entry_price else 0
                    trade_history.append({
                        "entry_date": str(entry_date.date()) if entry_date else "",
                        "exit_date": date_str, "side": "long", "size": sell_size,
                        "entry_price": round(entry_price, 4), "exit_price": round(open_p, 4),
                        "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
                        "holding_bars": i - entry_bar if entry_bar >= 0 else 0, "symbol": "",
                    })
                    cash += proceeds
                    turnover_value += proceeds
                    position -= sell_size
                    if position == 0:
                        entry_price = 0.0
                        entry_date = None
                        entry_bar = -1

        if in_eval and indicators_ready:
            if strategy == "weight":
                coef = bb_coef.get(date_str) if (USE_BULL_BEAR and bb_coef) else None
                total, _ = compute_total_score(row, news_level, weights, bb_coef=coef)
                if USE_FG_WEIGHT and fg_state:
                    fg = fg_state.get(date_str, 50.0)
                    # 推文语境「积极信号在积累」= 恐惧区视为逆向机会，fg_score = 100 - fg
                    fg_score = 100.0 - fg
                    six = sum(weights.values())
                    scale = six / (six + FG_WEIGHT) if (six + FG_WEIGHT) > 0 else 1.0
                    total = total * scale + fg_score * FG_WEIGHT
                if total >= bs_eff:
                    pending_action = ("buy", 1.0)
                elif total >= bw:
                    pending_action = ("buy", 0.5)
                elif total < ss:
                    pending_action = ("sell", 0.0)
                elif total < sw_eff:
                    pending_action = ("sell", 0.5)
                else:
                    pending_action = None
            elif strategy == "bh":
                if position == 0:
                    pending_action = ("buy", 1.0)
                else:
                    pending_action = None

        if in_eval:
            value = cash + position * close_p
            equity_curve.append({"date": date_str, "value": round(value, 2)})

    if position > 0 and equity_curve:
        eval_rows = d[(d["date"] >= eval_start) & (d["date"] <= eval_end)]
        last = eval_rows.iloc[-1]
        price = last["close"]
        tax = position * price * SELL_TAX
        proceeds = position * price * (1 - COMMISSION) - tax
        pnl = proceeds - position * entry_price * (1 + COMMISSION)
        pnl_pct = (price / entry_price - 1) * 100 if entry_price else 0
        trade_history.append({
            "entry_date": str(entry_date.date()) if entry_date else "",
            "exit_date": str(last["date"].date()), "side": "long", "size": position,
            "entry_price": round(entry_price, 4), "exit_price": round(price, 4),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
            "holding_bars": len(d) - 1 - entry_bar if entry_bar >= 0 else 0, "symbol": "",
        })
        cash += proceeds
        turnover_value += proceeds
        position = 0

    return equity_curve, trade_history, turnover_value


# ---------------------------------------------------------------------------
# 6. 汇总指标（与 v2 一致）
# ---------------------------------------------------------------------------
def compute_summary(equity_curve, trade_history, initial=INITIAL_CASH):
    if not equity_curve:
        return {}
    eq = pd.DataFrame(equity_curve)
    eq["value"] = pd.to_numeric(eq["value"])
    start_v = eq.iloc[0]["value"]
    end_v = eq.iloc[-1]["value"]
    total_ret = (end_v / start_v - 1) * 100
    n_days = max(len(eq) - 1, 1)
    annual_ret = ((end_v / start_v) ** (252 / n_days) - 1) * 100 if end_v > 0 else -100
    roll_max = eq["value"].cummax()
    dd = (eq["value"] / roll_max - 1) * 100
    max_dd = abs(dd.min())
    rets = eq["value"].pct_change().dropna()
    sharpe = (rets.mean() / rets.std() * math.sqrt(252)) if rets.std() > 0 and len(rets) > 1 else None
    wins = sum(1 for t in trade_history if t["pnl"] > 0)
    win_rate = wins / len(trade_history) * 100 if trade_history else 0
    avg_hold = np.mean([t["holding_bars"] for t in trade_history]) if trade_history else 0
    return {
        "total_return_pct": round(total_ret, 2),
        "annual_return_pct": round(annual_ret, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "win_rate_pct": round(win_rate, 1),
        "total_trades": len(trade_history),
        "avg_holding_bars": round(float(avg_hold), 1),
    }


# ---------------------------------------------------------------------------
# 7. 主流程（多实验对比）
# ---------------------------------------------------------------------------
def run_experiment(name, weights, switches, market_state, bb_coef, fg_state=None):
    """单实验：27 池全跑，返回组合汇总。switches 临时覆盖全局开关。"""
    global USE_MA_TRIPLE, USE_BOLL_POS, USE_RESO_PATCH, USE_BULL_BEAR
    global USE_EXTREME_VOL, USE_PDV, USE_RSI_DIV, SCORE_MODE
    global USE_FG_GATE, USE_FG_WEIGHT, USE_FG_DYNAMIC, FG_MODE
    old = (USE_MA_TRIPLE, USE_BOLL_POS, USE_RESO_PATCH, USE_BULL_BEAR,
           USE_EXTREME_VOL, USE_PDV, USE_RSI_DIV, SCORE_MODE,
           USE_FG_GATE, USE_FG_WEIGHT, USE_FG_DYNAMIC, FG_MODE)
    USE_MA_TRIPLE = switches.get("ma_triple", USE_MA_TRIPLE)
    USE_BOLL_POS = switches.get("boll_pos", USE_BOLL_POS)
    USE_RESO_PATCH = switches.get("reso_patch", USE_RESO_PATCH)
    USE_BULL_BEAR = switches.get("bull_bear", USE_BULL_BEAR)
    USE_EXTREME_VOL = switches.get("extreme_vol", USE_EXTREME_VOL)
    USE_PDV = switches.get("pdv", USE_PDV)
    USE_RSI_DIV = switches.get("rsi_div", USE_RSI_DIV)
    SCORE_MODE = switches.get("score_mode", SCORE_MODE)
    USE_FG_GATE = switches.get("fg_gate", USE_FG_GATE)
    USE_FG_WEIGHT = switches.get("fg_weight", USE_FG_WEIGHT)
    USE_FG_DYNAMIC = switches.get("fg_dynamic", USE_FG_DYNAMIC)
    FG_MODE = switches.get("fg_mode", FG_MODE)

    results = {}
    all_trades = []
    combined_equity = {}
    total_turnover = 0.0
    for sector, members in SECTOR_POOL.items():
        for code, nm, typ, market, news_level in members:
            df = load_data(code)
            eq_w, tr_w, turo = run_backtest(df, news_level, market_state, bb_coef, weights, strategy="weight", fg_state=fg_state)
            eq_b, tr_b, _ = run_backtest(df, news_level, market_state, bb_coef, weights, strategy="bh", fg_state=fg_state)
            sum_w = compute_summary(eq_w, tr_w)
            sum_b = compute_summary(eq_b, tr_b)
            norm = []
            if eq_w:
                base = eq_w[0]["value"]
                for p in eq_w:
                    norm.append({"date": p["date"], "value": round(100 * p["value"] / base, 4)})
            for t in tr_w:
                t["symbol"] = code
                t["symbol_name"] = nm
            all_trades.extend(tr_w)
            total_turnover += turo
            results[code] = {"sector": sector, "name": nm, "weight": sum_w, "buyhold": sum_b}
            for p in norm:
                combined_equity.setdefault(p["date"], []).append(p["value"])

    combo = []
    for date in sorted(combined_equity.keys()):
        vals = combined_equity[date]
        combo.append({"date": date, "value": round(sum(vals) / len(vals), 4)})
    combo_summary = compute_summary(combo, all_trades)
    n_symbols = sum(len(v) for v in SECTOR_POOL.values())
    avg_daily_turnover = total_turnover / max(len(combo), 1) / (n_symbols * INITIAL_CASH) * 100

    # 恢复开关
    (USE_MA_TRIPLE, USE_BOLL_POS, USE_RESO_PATCH, USE_BULL_BEAR,
     USE_EXTREME_VOL, USE_PDV, USE_RSI_DIV, SCORE_MODE,
     USE_FG_GATE, USE_FG_WEIGHT, USE_FG_DYNAMIC, FG_MODE) = old
    return {
        "name": name, "weights": weights, "switches": switches,
        "combo_summary": combo_summary,
        "avg_daily_turnover_pct": round(float(avg_daily_turnover), 3),
        "combo_equity": combo,
        "trades": all_trades,
        "per_symbol": {c: {"name": r["name"], "sector": r["sector"],
                           "ret": r["weight"].get("total_return_pct"),
                           "dd": r["weight"].get("max_drawdown_pct"),
                           "bh": r["buyhold"].get("total_return_pct")} for c, r in results.items()},
    }


def main():
    print(f"v5 FG 恐贪吸收回测：{BACKTEST_START} ~ {BACKTEST_END}，27 标的 × 9 领域")
    idx = load_index("000300")
    market_state = build_market_state(idx) if USE_MARKET_GATE else {}
    bb_coef = build_bull_bear_coef(idx)
    ms_counts = {k: list(market_state.values()).count(k) for k in ["strong", "normal", "weak"]}
    idx_full = load_index_full("000300")
    fg_state = build_fg_index(idx_full) if idx_full is not None else {}
    fg_vals = list(fg_state.values())
    print(f"市场状态分布：{ms_counts}；牛熊系数可用天数：{len(bb_coef)}")
    if fg_vals:
        print(f"FG 恐贪可用天数：{len(fg_state)}；FG 均值 {np.mean(fg_vals):.1f} / 区间 [{min(fg_vals):.0f}, {max(fg_vals):.0f}]")
    else:
        print("FG 不可用")

    BASE = {"ma_triple": False, "boll_pos": True, "reso_patch": False, "bull_bear": False,
            "extreme_vol": True, "pdv": True, "rsi_div": True, "score_mode": "patch"}
    experiments = [
        ("基线v4生产版", WT_A, dict(BASE)),
        ("FG门禁·恐惧防御", WT_A, {**BASE, "fg_gate": True, "fg_mode": "defensive"}),
        ("FG门禁·恐惧机会", WT_A, {**BASE, "fg_gate": True, "fg_mode": "opportunistic"}),
        ("FG第7维权重", WT_A, {**BASE, "fg_weight": True}),
        ("FG动态门槛·防御", WT_A, {**BASE, "fg_dynamic": True, "fg_mode": "defensive"}),
        ("FG动态门槛·机会", WT_A, {**BASE, "fg_dynamic": True, "fg_mode": "opportunistic"}),
        ("FG动态防御+第7维", WT_A, {**BASE, "fg_dynamic": True, "fg_mode": "defensive", "fg_weight": True}),
    ]

    import csv as _csv
    out_dir = os.path.join(BASE_DIR, "v5_fg_out")
    os.makedirs(out_dir, exist_ok=True)
    out_exps = []
    for name, wt, sw in experiments:
        print(f"\n=== 实验：{name} ===")
        exp = run_experiment(name, wt, sw, market_state, bb_coef, fg_state=fg_state)
        cs = exp["combo_summary"]
        print(f"  组合：+{cs['total_return_pct']}% / 回撤 {cs['max_drawdown_pct']}% / "
              f"夏普 {cs['sharpe']} / 胜率 {cs['win_rate_pct']}% / {cs['total_trades']} 笔 / 换手 {exp['avg_daily_turnover_pct']}%")
        safe = name.replace("/", "_").replace("·", "_").replace("+", "p")
        with open(os.path.join(out_dir, f"eq_{safe}.csv"), "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(["date", "value"])
            for row in exp["combo_equity"]:
                w.writerow([row["date"], row["value"]])
        with open(os.path.join(out_dir, f"tr_{safe}.csv"), "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            keys = ["entry_date", "exit_date", "side", "size", "entry_price", "exit_price",
                    "pnl", "pnl_pct", "holding_bars", "symbol", "symbol_name"]
            w.writerow(keys)
            for t in exp["trades"]:
                w.writerow([t.get(k, "") for k in keys])
        # 摘要中附 equity 路径供 dashboard 使用
        exp["equity_csv"] = os.path.join(out_dir, f"eq_{safe}.csv")
        exp["trades_csv"] = os.path.join(out_dir, f"tr_{safe}.csv")
        out_exps.append(exp)

    out = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "window": {"start": BACKTEST_START, "end": BACKTEST_END},
        "pool": "27标的×9领域等权组合",
        "baseline_note": "v4 生产版基线：+141.54% / 回撤 13.84% / 胜率 91.6% / 155 笔 / 换手 0.787%",
        "acceptance": "收益 ≥ +141.54% 且最大回撤 ≤ 20%；换手不显著恶化",
        "fg_method": "推文「积极信号在积累」恐贪指数：沪深300 日K衍生 5 维（动量/趋势/波动率/回撤/量能）滚动分位归一化 W=250",
        "experiments": out_exps,
    }
    with open("weight_system_v5_fg_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n已输出 weight_system_v5_fg_results.json")


if __name__ == "__main__":
    main()
