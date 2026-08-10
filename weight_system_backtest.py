# -*- coding: utf-8 -*-
"""
综合指标权重系统回测脚本（v1.0）
=============================
策略：六类指标打分加权合成（趋势30/动能25/量能15/超买超卖15/风控10/研报5），
总分 0-100 映射加仓/减仓/观望三档操作（含仓位档位），T 日收盘出信号，T+1 开盘执行。

指标层：
- MA20/MA5/MA10：趋势位置
- ATR(14)：波动率自适应阈值（S1/S2 优化）
- MACD(12,26,9)：趋势动能
- KDJ(9,3,3)：超买超卖（三重质量过滤：位置/趋势/动能）
- RSI(14)：超买超卖（相对强弱指标，>80 超买 <20 超卖）
- ADX(14)：趋势强度（震荡市降权）
- 量能比：当日成交量/5日均量

执行规则：
- 信号 T 日收盘计算，T+1 开盘执行（防未来函数）
- A股 T+1：当日买入不可当日卖出；100 股整手
- 费用：佣金万 2.5 双边 + 印花税千 0.5 卖出（ETF 免印花税）
- 期末强制平仓

基线对比：买入持有 vs 旧 S1-S7 规则 vs 新权重系统
"""

import pandas as pd
import numpy as np
import json, os, sys, math
from datetime import datetime

# ---------------------------------------------------------------------------
# 0. 标的池（19 只，与 agentos 网站 2026-08-10 报告一致）
# ---------------------------------------------------------------------------
UNIVERSE = [
    # code, name, type, market, 研报情报(L1看多/L3谨慎/None)
    ("300502", "新易盛", "股票", "sz", "L3"),
    ("300308", "中际旭创", "股票", "sz", "L1"),
    ("159516", "半导体设备ETF", "ETF", "sz", None),
    ("600498", "烽火通信", "股票", "sh", None),
    ("601138", "工业富联", "股票", "sh", None),
    ("002463", "沪电股份", "股票", "sz", None),
    ("002384", "东山精密", "股票", "sz", None),
    ("600183", "生益科技", "股票", "sh", None),
    ("300476", "胜宏科技", "股票", "sz", "L1"),
    ("603986", "兆易创新", "股票", "sh", None),
    ("515880", "通信ETF", "ETF", "sh", None),
    ("516150", "稀土ETF嘉实", "ETF", "sh", None),
    ("560390", "电网设备ETF易方达", "ETF", "sh", None),
    ("008254", "华宝致远混合C", "基金", "jj", None),
    ("018036", "长城新能源车股C", "基金", "jj", None),
    ("002891", "华夏移动互联CNY", "基金", "jj", None),
    ("024239", "华夏全球QDII C", "基金", "jj", None),
    ("014002", "浦银智能科技C", "基金", "jj", None),
    ("020900", "天弘通信设备C", "基金", "jj", None),
]

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# 权重（专家先验，规格书 v1 决策 D5）
WEIGHTS = {
    "trend": 0.30,     # 趋势类（MA位置/ADX/20日动量）
    "momentum": 0.25,  # 动能类（MACD/当日涨跌）
    "volume": 0.15,    # 量能类（量比/量价配合）
    "osc": 0.15,       # 超买超卖类（RSI/KDJ过滤后）
    "risk": 0.10,      # 风控类（ATR波动/回撤距离）
    "news": 0.05,      # 研报情报类（L1-L3）
}

# 实验开关（2026-08-10 晚 37 只验证结论，见 vault research-量化权重素材吸收-20260810 §4）
# USE_MID_MA = True 时趋势类加入 MA30/MA120 位置加分（v1.2 实验：弱领域减亏但强趋势标的收益受损，
# 19 标的池 220.3%→215.0%、回撤 18.8%→19.3%——生产环境双输，默认关闭）
USE_MID_MA = False

# 操作阈值（总分 0-100）
BUY_STRONG = 75   # >=75 标准加仓（仓位升至 100%）
BUY_WEAK = 60     # 60-74 轻仓加仓（仓位 50%）
HOLD_UPPER = 60
HOLD_LOWER = 45   # 45-59 观望
SELL_WEAK = 40    # 40-44 减仓（仓位降至 50%）
SELL_STRONG = 30  # <30 清仓

# ---- v1.3 可配置开关（默认关闭，行为与 v1.2 完全一致）----
DEADBAND_LO = 55  # 死区下限：总分在此区间视为观望（防止临界抖动）
DEADBAND_HI = 65  # 死区上限
USE_DEADBAND = False      # True = 55-65 分区间一律观望（不触发轻仓加/减半仓）
USE_REVERSAL_ONLY = False  # True = 仅加减反转才生成信号；同向档位变化（半仓↔满仓）不动作

# ---- v1.4 仓位模型（默认 target_cap = 稳健增强：目标制+单次上限 50%，2026-08-10 用户拍板）----
POSITION_MODEL = "target_cap"  # "target"=目标仓位制(v1.2基线) | "incremental"=增量步进 | "target_cap"=目标制+上限(默认)
STEP_PCT = 0.20                # 模型A增量步长：加仓=总资产×STEP_PCT，减仓=持有市值×STEP_PCT
CAP_PCT = 0.50                 # 模型B单次调整上限：每次执行最多调整 CAP_PCT 仓位（稳健增强）

BACKTEST_START = "2025-01-01"
BACKTEST_END = "2026-08-07"
INITIAL_CASH = 1_000_000.0
COMMISSION = 0.00025   # 万 2.5 双边
SELL_TAX = 0.0005      # 印花税卖出千 0.5（仅股票）
LOT = 100              # A股整手


# ---------------------------------------------------------------------------
# 1. 数据加载与清洗
# ---------------------------------------------------------------------------
def load_data(code: str) -> pd.DataFrame:
    path = os.path.join(DATA_DIR, f"{code}.csv")
    df = pd.read_csv(path)
    df["date"] = df["date"].astype(str).str.replace(r"(\d{4})(\d{2})(\d{2})", r"\1-\2-\3", regex=True)
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 2. 指标计算（向量化）
# ---------------------------------------------------------------------------
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    # MA（v1.2：新增 MA30 中期趋势、MA120 牛熊分界——素材「均线口诀」反哺）
    d["ma5"] = d["close"].rolling(5).mean()
    d["ma10"] = d["close"].rolling(10).mean()
    d["ma20"] = d["close"].rolling(20).mean()
    d["ma30"] = d["close"].rolling(30).mean()
    d["ma120"] = d["close"].rolling(120).mean()
    # ATR(14)
    prev_close = d["close"].shift(1)
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - prev_close).abs(),
        (d["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    d["atr_pct"] = d["atr"] / d["close"] * 100  # ATR 相对价格百分比
    # MACD(12,26,9)
    ema12 = d["close"].ewm(span=12, adjust=False).mean()
    ema26 = d["close"].ewm(span=26, adjust=False).mean()
    d["dif"] = ema12 - ema26
    d["dea"] = d["dif"].ewm(span=9, adjust=False).mean()
    d["macd_hist"] = (d["dif"] - d["dea"]) * 2
    # KDJ(9,3,3)
    low9 = d["low"].rolling(9).min()
    high9 = d["high"].rolling(9).max()
    rsv = (d["close"] - low9) / (high9 - low9) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    dd = k.ewm(alpha=1 / 3, adjust=False).mean()
    d["k"] = k
    d["d"] = dd
    d["j"] = 3 * k - 2 * dd
    # RSI(14)（相对强弱指标，Wilder 平滑）
    delta = d["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    d["rsi"] = (100 - 100 / (1 + rs)).fillna(100)
    # ADX(14)
    up_move = d["high"].diff()
    down_move = -d["low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr_s = tr.ewm(alpha=1 / 14, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=d.index).ewm(alpha=1 / 14, adjust=False).mean() / tr_s.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=d.index).ewm(alpha=1 / 14, adjust=False).mean() / tr_s.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    d["adx"] = dx.ewm(alpha=1 / 14, adjust=False).mean()
    # 量能比：当日量 / 5日均量
    vol_ma5 = d["volume"].rolling(5).mean()
    d["vol_ratio"] = d["volume"] / vol_ma5.replace(0, np.nan)
    # 当日涨跌幅
    d["pct_chg"] = d["close"].pct_change() * 100
    # MA20 偏离
    d["ma20_dev"] = (d["close"] - d["ma20"]) / d["ma20"] * 100
    # 20日动量
    d["mom20"] = d["close"] / d["close"].shift(20) * 100 - 100
    # 60日回撤（距 60 日高点）
    d["high60"] = d["close"].rolling(60).max()
    d["dd60"] = (d["close"] / d["high60"] - 1) * 100
    return d


# ---------------------------------------------------------------------------
# 3. 六类打分（每类 0-100，总分 = Σ(类分×权重)）
# ---------------------------------------------------------------------------
def _clip(x):
    return max(0.0, min(100.0, float(x)))


def score_trend(row):
    """趋势类：MA 位置 40 + ADX 30 + 20日动量 30（USE_MID_MA=True 时并入 MA30/MA120）"""
    s = 0.0
    # MA 位置（0-40）
    if not np.isnan(row["ma20"]):
        if row["close"] > row["ma20"]:
            s += 40 if row["ma20_dev"] < 15 else 30  # 远离 MA20 适度减分（超买）
        else:
            s += 10 if row["ma20_dev"] > -8 else 0   # 深破位 0 分
    else:
        s += 20
    # 中期趋势（0-10，实验开关）：30日线看趋势 + 120日线看底牌
    if USE_MID_MA:
        if not np.isnan(row["ma30"]) and row["close"] > row["ma30"]:
            s += 5
        if not np.isnan(row["ma120"]) and row["close"] > row["ma120"]:
            s += 5
    # ADX 趋势强度（0-30）
    if not np.isnan(row["adx"]):
        if row["adx"] >= 25:
            s += 30
        elif row["adx"] >= 20:
            s += 22
        elif row["adx"] >= 15:
            s += 12
        else:
            s += 4  # ADX<15 无趋势，低分
    else:
        s += 15
    # 20日动量（0-30）
    if not np.isnan(row["mom20"]):
        if row["mom20"] > 8:
            s += 30
        elif row["mom20"] > 0:
            s += 22
        elif row["mom20"] > -8:
            s += 12
        else:
            s += 4
    else:
        s += 15
    return _clip(s)


def score_momentum(row):
    """动能类：MACD 状态 50 + 当日涨跌 30 + MACD柱动能 20"""
    s = 0.0
    # MACD 状态（0-50）
    if not np.isnan(row["dif"]) and not np.isnan(row["dea"]):
        if row["dif"] > row["dea"]:
            s += 40 if row["dif"] > 0 else 30
        else:
            s += 12 if row["dif"] > 0 else 4
    else:
        s += 25
    # 当日涨跌（0-30）——S1/S4 优化为 ATR 自适应
    if not np.isnan(row["pct_chg"]):
        atr_norm = row["atr_pct"] if not np.isnan(row["atr_pct"]) else 3.0
        if row["pct_chg"] >= 0:
            s += 30 if row["pct_chg"] >= 2 else 22
        else:
            # 大跌阈值 ATR 自适应：≤ -2.5×ATR% 视为 S1
            if row["pct_chg"] <= -2.5 * max(atr_norm, 1.5):
                s += 0
            elif row["pct_chg"] <= -1 * atr_norm:
                s += 8
            else:
                s += 15
    else:
        s += 15
    # MACD 柱动能（0-20）
    if not np.isnan(row["macd_hist"]):
        s += 20 if row["macd_hist"] > 0 else 6
    else:
        s += 10
    return _clip(s)


def score_volume(row, is_fund=False):
    """量能类：量比 50 + 量价配合 50；基金无量能退化为中性 50"""
    if is_fund or np.isnan(row["vol_ratio"]):
        return 50.0
    s = 0.0
    vr = row["vol_ratio"]
    # 量比（0-50）
    if 1.2 <= vr <= 1.8:
        s += 50
    elif 0.9 <= vr < 1.2:
        s += 38
    elif 1.8 < vr <= 2.5:
        s += 40  # 放量过大，警惕
    elif vr > 2.5:
        s += 25
    elif 0.6 <= vr < 0.9:
        s += 25
    else:
        s += 12
    # 量价配合（0-50）：涨+量增 高分；跌+放量 低分（S3 逻辑）
    if not np.isnan(row["pct_chg"]):
        if row["pct_chg"] > 0 and vr >= 1.0:
            s += 50
        elif row["pct_chg"] > 0 and vr < 1.0:
            s += 30
        elif row["pct_chg"] <= 0 and vr >= 1.5:
            s += 8  # 放量下跌
        elif row["pct_chg"] <= 0 and vr >= 1.0:
            s += 20
        else:
            s += 35  # 缩量回调
    else:
        s += 25
    return _clip(s)


def score_osc(row):
    """超买超卖类：RSI 60 + KDJ(过滤后) 40"""
    s = 0.0
    # RSI(14)（0-60）
    if not np.isnan(row["rsi"]):
        rsi = row["rsi"]
        if rsi < 20:
            s += 55   # 超卖（但未确认反转，略低于强势区）
        elif rsi < 30:
            s += 50
        elif rsi < 50:
            s += 42   # 中性偏弱，修复中
        elif rsi < 70:
            s += 60   # 强势健康区（未超买）
        elif rsi < 80:
            s += 40   # 偏热
        else:
            s += 12   # 超买 ≥80
    else:
        s += 30
    # KDJ 三重过滤后（0-40）
    k, dd, adx, macd_hist = row["k"], row["d"], row["adx"], row["macd_hist"]
    if not any(np.isnan(x) for x in [k, dd]):
        # 过滤1 位置：仅 D<30 或 D>70 计入
        if dd < 30:
            # 过滤2 趋势：ADX≥20 且价在 MA20 上；过滤3 动能：MACD 柱为正
            if not np.isnan(adx) and adx >= 20 and not np.isnan(macd_hist) and macd_hist > 0:
                s += 40 if k > dd else 25  # 金叉且向上 高分；仅低位未金叉 中分
            else:
                s += 15  # 低位但无确认，弱信号
        elif dd > 70:
            if not np.isnan(adx) and adx >= 20 and not np.isnan(macd_hist) and macd_hist < 0:
                s += 4   # 高位死叉确认，极低分
            else:
                s += 12
        else:
            s += 22  # 中位区不产生方向性信号（KDJ 无效信号集中区，不给分）
    else:
        s += 20
    return _clip(s)


def score_risk(row):
    """风控类：ATR 波动适中 50 + 距 60 日高点回撤 50"""
    s = 0.0
    # ATR 波动（0-50）：适中 1.5-4.5% 最佳
    if not np.isnan(row["atr_pct"]):
        ap = row["atr_pct"]
        if 1.5 <= ap <= 4.5:
            s += 50
        elif 0.8 <= ap < 1.5 or 4.5 < ap <= 7:
            s += 35
        else:
            s += 18
    else:
        s += 25
    # 回撤距离（0-50）：距 60 日高点回撤小 高分，深回撤低分
    if not np.isnan(row["dd60"]):
        if row["dd60"] > -5:
            s += 50
        elif row["dd60"] > -12:
            s += 35
        elif row["dd60"] > -20:
            s += 20
        else:
            s += 6
    else:
        s += 25
    return _clip(s)


def score_news(row, news_level):
    """研报情报类：L1 看多 70 / L2 中性 50 / L3 谨慎 30 / 无情报 50"""
    if news_level == "L1":
        return 70.0
    if news_level == "L3":
        return 30.0
    return 50.0


def compute_total_score(row, news_level, is_fund=False):
    st = score_trend(row)
    sm = score_momentum(row)
    sv = score_volume(row, is_fund=is_fund)
    so = score_osc(row)
    sr = score_risk(row)
    sn = score_news(row, news_level)
    total = (
        st * WEIGHTS["trend"] + sm * WEIGHTS["momentum"] + sv * WEIGHTS["volume"]
        + so * WEIGHTS["osc"] + sr * WEIGHTS["risk"] + sn * WEIGHTS["news"]
    )
    comp = {"trend": st, "momentum": sm, "volume": sv, "osc": so, "risk": sr, "news": sn, "total": total}
    conf = compute_confidence(comp, is_fund=is_fund)
    return _clip(total), comp, conf


def compute_confidence(comp, is_fund=False):
    """置信度机械判定（方法论要点 3，源自市场测温 skill 借鉴）：
    - 覆盖率：方向性有效的类别数 / 6。退化类（基金 volume 固定 50、无研报 news 固定 50）
      不计入方向证据；但 coverage 按「有数据的类」计，数据缺失才降覆盖率。
    - 方向一致：高分（>=60）或低分（<=40）类在方向性有效类中的占比。
    - 规则：覆盖率 >=80% 且方向一致 >=75% => 高；覆盖率 <60% => 低；其余中。
    """
    cats = ["trend", "momentum", "volume", "osc", "risk", "news"]
    directional = 0
    agree = 0
    for c in cats:
        v = comp.get(c, 50)
        if c == "volume" and is_fund:
            continue          # 基金无量能：退化中性，不参与方向
        if c == "news" and v == 50.0:
            continue          # 无研报情报：中性，不参与方向
        if c == "risk" and v == 50.0:
            continue          # 退化中性（理论上 risk 总有值，防御）
        directional += 1
        if v >= 60 or v <= 40:
            agree += 1
    coverage = directional / len(cats)
    agree_ratio = agree / directional if directional > 0 else 0.0
    if coverage >= 0.80 and agree_ratio >= 0.75:
        level = "高"
    elif coverage < 0.60:
        level = "低"
    else:
        level = "中"
    return {
        "level": level,
        "coverage": round(coverage, 2),
        "directional_cats": directional,
        "agree_ratio": round(agree_ratio, 2),
    }


# ---------------------------------------------------------------------------
# 4. 旧 S1-S7 规则（基线，v1.1 硬阈值 + ATR 自适应优化版）
# ---------------------------------------------------------------------------
def old_s1s7_signal(row, is_fund=False):
    """返回 1=加仓 0=观望 -1=减仓（优化版：S1/S2 ATR 自适应）"""
    if np.isnan(row["ma20"]):
        return 0
    pct = row["pct_chg"] if not np.isnan(row["pct_chg"]) else 0
    vr = row["vol_ratio"] if not np.isnan(row["vol_ratio"]) else 0
    dev = row["ma20_dev"] if not np.isnan(row["ma20_dev"]) else 0
    atr_norm = row["atr_pct"] if not np.isnan(row["atr_pct"]) else 3.0
    # 减仓信号（任一命中）
    s1 = pct <= -2.5 * max(atr_norm, 1.5)          # S1 ATR 自适应大跌
    # S2 ATR 修正破位：v1.1 加固定下限 -6%，防低波动阴跌股（ATR 小→阈值过松）永不触发
    s2_break = min(-1.5 * max(atr_norm, 1.0), -6.0)
    s2 = (row["close"] < row["ma20"]) and (dev <= s2_break)  # S2 破位（ATR 自适应 + 固定下限）
    s3 = (pct < 0) and (vr >= 1.5) and not is_fund  # S3 放量下跌
    if s1 or s2 or s3:
        return -1
    # 加仓信号（全部满足）
    s4 = pct > 0
    s5 = row["close"] > row["ma20"]
    s6 = dev <= 8
    s7 = (vr >= 1.2) or (pct >= 2) if not is_fund else (pct >= 2)
    if s4 and s5 and s6 and s7:
        return 1
    return 0


# ---------------------------------------------------------------------------
# 5. 回测引擎（信号 T 日收盘 → T+1 开盘执行）
# ---------------------------------------------------------------------------
def run_backtest(df, news_level, is_fund=False, strategy="weight"):
    """strategy: weight=权重系统 / s1s7=旧规则 / bh=买入持有"""
    d = compute_indicators(df)
    cash = INITIAL_CASH
    position = 0
    entry_price = 0.0
    entry_date = None
    entry_bar = -1
    pending_action = None  # 待执行动作: ("buy", target_pos) / ("sell", target_pos)
    equity_curve = []
    trade_history = []
    target_pct = 0.0  # 目标仓位比例 0/0.5/1.0
    last_dir = None   # v1.3 反转才动：上一交易方向（"buy"/"sell"）

    for i in range(len(d)):
        row = d.iloc[i]
        date = row["date"]
        open_p, close_p = row["open"], row["close"]
        if pd.isna(close_p) or pd.isna(open_p):
            value = cash + position * close_p if not pd.isna(close_p) else cash + position * (entry_price or 0)
            equity_curve.append({"date": str(date.date()), "value": round(value, 2)})
            continue
        in_eval = date >= pd.Timestamp(BACKTEST_START)
        indicators_ready = not pd.isna(row["ma20"]) and not pd.isna(row["rsi"])

        # ---- 1. 执行昨日待执行动作（T+1 开盘）----
        if pending_action is not None and in_eval:
            action, amount = pending_action
            pending_action = None
            # A股 T+1：当日买入不可当日卖（执行日即信号日+1，天然满足，但保险检查）
            if action == "buy":
                if POSITION_MODEL == "target":
                    # v1.2 基线（逐字原版）：目标股数 - 当前股数，现金不足整笔跳过
                    target_value = amount * INITIAL_CASH
                    target_shares = int(target_value / (open_p * (1 + COMMISSION)))
                    target_shares = (target_shares // LOT) * LOT
                    add_size = target_shares - position  # 只补差额，避免覆盖已有仓位
                    if add_size > 0:
                        cost = add_size * open_p * (1 + COMMISSION)
                        if cost <= cash:
                            cash -= cost
                            if position == 0:
                                entry_price = open_p
                                entry_date = date
                                entry_bar = i
                            position += add_size
                else:
                    # 模型A incremental / 模型B target_cap：市值差驱动
                    if POSITION_MODEL == "incremental":
                        total_assets = cash + position * open_p
                        add_value = total_assets * amount          # 加仓额 = 总资产 × STEP_PCT
                    else:  # target_cap
                        target_value = amount * INITIAL_CASH
                        cur_value = position * open_p
                        cap_value = max(0.0, target_value - cur_value)
                        add_value = min(cap_value, CAP_PCT * INITIAL_CASH)  # 单次上限
                    add_shares = int(add_value / (open_p * (1 + COMMISSION)))
                    add_shares = (add_shares // LOT) * LOT
                    add_size = min(add_shares, int(cash / (open_p * (1 + COMMISSION))) // LOT * LOT)
                    if add_size > 0:
                        cost = add_size * open_p * (1 + COMMISSION)
                        if cost <= cash:
                            cash -= cost
                            if position == 0:
                                entry_price = open_p
                                entry_date = date
                                entry_bar = i
                            position += add_size
            elif action == "sell":
                if POSITION_MODEL == "target":
                    # v1.2 基线（逐字原版）：目标股数差值
                    target_value = amount * INITIAL_CASH
                    target_shares = int(target_value / open_p)
                    target_shares = (target_shares // LOT) * LOT
                    sell_size = position - target_shares
                else:
                    # 模型A incremental / 模型B target_cap：市值差驱动
                    if POSITION_MODEL == "incremental":
                        sell_value = position * open_p * amount      # 减仓额 = 持有市值 × STEP_PCT
                    else:  # target_cap
                        target_value = amount * INITIAL_CASH
                        cur_value = position * open_p
                        cap_value = max(0.0, cur_value - target_value)
                        sell_value = min(cap_value, CAP_PCT * INITIAL_CASH)  # 单次上限
                    sell_shares = int(sell_value / open_p)
                    sell_shares = (sell_shares // LOT) * LOT
                    sell_size = min(sell_shares, position)
                if sell_size > 0:
                    tax = sell_size * open_p * SELL_TAX if not is_fund else 0.0
                    proceeds = sell_size * open_p * (1 - COMMISSION) - tax
                    pnl = proceeds - sell_size * entry_price * (1 + COMMISSION)
                    pnl_pct = (open_p / entry_price - 1) * 100 if entry_price else 0
                    trade_history.append({
                        "entry_date": str(entry_date.date()) if entry_date else "",
                        "exit_date": str(date.date()),
                        "side": "long",
                        "size": sell_size,
                        "entry_price": round(entry_price, 4),
                        "exit_price": round(open_p, 4),
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "holding_bars": i - entry_bar if entry_bar >= 0 else 0,
                        "symbol": "",
                    })
                    cash += proceeds
                    position -= sell_size
                    if position == 0:
                        entry_price = 0.0
                        entry_date = None
                        entry_bar = -1

        # ---- 2. 生成今日信号（收盘后确认，明日执行）----
        if in_eval and indicators_ready:
            if strategy == "weight":
                _, comp, _conf = compute_total_score(row, news_level, is_fund=is_fund)
                total = comp["total"]
                if POSITION_MODEL == "incremental":
                    # 模型A：增量步进——方向驱动，幅度由 STEP_PCT 控制
                    if total >= BUY_WEAK:
                        pending_action = ("buy", STEP_PCT)   # 加仓方向：加总资产 STEP_PCT
                    elif total < SELL_WEAK:
                        pending_action = ("sell", STEP_PCT)  # 减仓方向：减持有份额 STEP_PCT
                    else:
                        pending_action = None
                else:
                    # 模型B/target：目标仓位制（≥75→100% / 60-74→50% / 40-44→50% / <30→0）
                    if total >= BUY_STRONG:
                        pending_action = ("buy", 1.0)  # 满仓
                    elif total >= BUY_WEAK:
                        pending_action = ("buy", 0.5)  # 半仓
                    elif total < SELL_STRONG:
                        pending_action = ("sell", 0.0)  # 清仓
                    elif total < SELL_WEAK:
                        pending_action = ("sell", 0.5)  # 减至半仓
                    else:
                        pending_action = None  # 观望
                # v1.3 死区：55-65 区间一律观望（默认关，优先级高于模型分支）
                if USE_DEADBAND and DEADBAND_LO <= total < DEADBAND_HI:
                    pending_action = None
                # v1.3 反转才动：同向档位变化不动作（默认关）
                if USE_REVERSAL_ONLY and pending_action is not None:
                    cur_dir = "buy" if pending_action[0] == "buy" else "sell"
                    if last_dir is None:
                        last_dir = cur_dir  # 首次信号直接执行
                    elif cur_dir == last_dir:
                        pending_action = None  # 同向微调忽略
                    else:
                        last_dir = cur_dir      # 方向反转，执行并更新
            elif strategy == "s1s7":
                sig = old_s1s7_signal(row, is_fund=is_fund)
                if sig == 1:
                    pending_action = ("buy", 1.0)
                elif sig == -1:
                    pending_action = ("sell", 0.0)
                else:
                    pending_action = None
            else:  # buy-and-hold
                if position == 0:
                    pending_action = ("buy", 1.0)
                else:
                    pending_action = None

        # ---- 3. 记录权益（收盘市值）----
        if in_eval:
            value = cash + position * close_p
            equity_curve.append({"date": str(date.date()), "value": round(value, 2)})

    # ---- 期末强制平仓 ----
    if position > 0 and equity_curve:
        last = d.iloc[-1]
        price = last["close"]
        tax = position * price * SELL_TAX if not is_fund else 0.0
        proceeds = position * price * (1 - COMMISSION) - tax
        pnl = proceeds - position * entry_price * (1 + COMMISSION)
        pnl_pct = (price / entry_price - 1) * 100 if entry_price else 0
        trade_history.append({
            "entry_date": str(entry_date.date()) if entry_date else "",
            "exit_date": str(last["date"].date()),
            "side": "long",
            "size": position,
            "entry_price": round(entry_price, 4),
            "exit_price": round(price, 4),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "holding_bars": len(d) - 1 - entry_bar if entry_bar >= 0 else 0,
            "symbol": "",
        })
        cash += proceeds
        position = 0

    return equity_curve, trade_history


# ---------------------------------------------------------------------------
# 6. 汇总指标
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
    # 最大回撤
    roll_max = eq["value"].cummax()
    dd = (eq["value"] / roll_max - 1) * 100
    max_dd = abs(dd.min())
    # 夏普
    rets = eq["value"].pct_change().dropna()
    sharpe = (rets.mean() / rets.std() * math.sqrt(252)) if rets.std() > 0 and len(rets) > 1 else None
    # 胜率
    wins = sum(1 for t in trade_history if t["pnl"] > 0)
    win_rate = wins / len(trade_history) * 100 if trade_history else 0
    return {
        "total_return_pct": round(total_ret, 2),
        "annual_return_pct": round(annual_ret, 2) if annual_ret != -100 else -100.0,
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "win_rate_pct": round(win_rate, 1),
        "total_trades": len(trade_history),
    }


def main():
    results = {}
    all_trades = []
    combined_equity = {}

    for code, name, typ, market, news_level in UNIVERSE:
        df = load_data(code)
        is_fund = typ == "基金"
        print(f"== {code} {name} ({typ}) bars={len(df)} range={df['date'].iloc[0].date()}~{df['date'].iloc[-1].date()}")

        eq_w, tr_w = run_backtest(df, news_level, is_fund, strategy="weight")
        eq_b, tr_b = run_backtest(df, news_level, is_fund, strategy="bh")
        eq_s, tr_s = run_backtest(df, news_level, is_fund, strategy="s1s7")

        sum_w = compute_summary(eq_w, tr_w)
        sum_b = compute_summary(eq_b, tr_b)
        sum_s = compute_summary(eq_s, tr_s)

        # 归一化权益（从 100 开始，便于组合对比）
        norm = []
        if eq_w:
            base = eq_w[0]["value"]
            for p in eq_w:
                norm.append({"date": p["date"], "value": round(100 * p["value"] / base, 4)})
        for t in tr_w:
            t["symbol"] = f"{code}"
            t["symbol_name"] = name
            t["display_symbol"] = f"{name} ({code})"
        all_trades.extend(tr_w)

        results[code] = {
            "name": name, "type": typ, "market": market, "news_level": news_level,
            "weight": sum_w, "buyhold": sum_b, "s1s7": sum_s,
            "equity_norm": norm, "trades": tr_w,
        }
        # 组合等权累计（用归一化净值，各标的同权重）
        for p in norm:
            combined_equity.setdefault(p["date"], []).append(p["value"])

    # ---- 组合净值（等权）----
    combo = []
    for date in sorted(combined_equity.keys()):
        vals = combined_equity[date]
        combo.append({"date": date, "value": round(sum(vals) / len(vals), 4)})

    out = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "window": {"start": BACKTEST_START, "end": BACKTEST_END},
        "weights": WEIGHTS,
        "thresholds": {"BUY_STRONG": BUY_STRONG, "BUY_WEAK": BUY_WEAK,
                       "HOLD_LOWER": HOLD_LOWER, "SELL_WEAK": SELL_WEAK, "SELL_STRONG": SELL_STRONG},
        "results": results,
        "combined_equity": combo,
        "combined_summary": compute_summary(combo, all_trades),
    }

    with open("weight_system_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # ---- 标准三件套导出 ----
    # 用组合净值作为 equity（等权组合视角），trades 用全部交易
    equity_csv = combo
    trade_rows = all_trades
    combo_summary = compute_summary(combo, trade_rows)
    with open("weight_system_equity.csv", "w", encoding="utf-8") as f:
        f.write("date,value\n")
        for p in combo:
            f.write(f"{p['date']},{p['value']}\n")
    import csv
    with open("weight_system_trades.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["entry_date", "exit_date", "side", "size", "entry_price", "exit_price",
                    "pnl", "pnl_pct", "holding_bars", "symbol", "symbol_name", "display_symbol"])
        for t in trade_rows:
            w.writerow([t.get(k, "") for k in
                        ["entry_date", "exit_date", "side", "size", "entry_price", "exit_price",
                         "pnl", "pnl_pct", "holding_bars", "symbol", "symbol_name", "display_symbol"]])
    with open("weight_system_summary.json", "w", encoding="utf-8") as f:
        json.dump({
            "meta": {
                "strategy_name": "综合指标权重系统 v1.0（19标的等权组合）",
                "symbol": "19标的等权组合",
                "start": BACKTEST_START, "end": BACKTEST_END,
                "initial_cash": 100.0, "window_start_value": 100.0,
                "final_value": combo[-1]["value"] if combo else None,
                "market": "china_a", "generated_at": out["generated_at"],
            },
            "summary": combo_summary,
        }, f, ensure_ascii=False, indent=2)

    # ---- 控制台摘要 ----
    print("\n" + "=" * 90)
    print(f"{'标的':<16}{'类型':<6}{'权重系统':>14}{'买入持有':>12}{'旧S1-S7':>12}")
    print("-" * 90)
    for code, r in results.items():
        w, b, s = r["weight"], r["buyhold"], r["s1s7"]
        print(f"{r['name']}({code}):".ljust(16) + f"{r['type']:<6}"
              + f"{w.get('total_return_pct', 0):>10.1f}%".rjust(14)
              + f"{b.get('total_return_pct', 0):>10.1f}%".rjust(12)
              + f"{s.get('total_return_pct', 0):>10.1f}%".rjust(12))
    print("-" * 90)
    cs = out["combined_summary"]
    print(f"组合(等权): 总收益 {cs.get('total_return_pct')}% | 年化 {cs.get('annual_return_pct')}% "
          f"| 最大回撤 {cs.get('max_drawdown_pct')}% | 夏普 {cs.get('sharpe')} | 胜率 {cs.get('win_rate_pct')}%")
    print("已生成: weight_system_results.json / _equity.csv / _trades.csv / _summary.json")


if __name__ == "__main__":
    main()
