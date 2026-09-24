# -*- coding: utf-8 -*-
"""
KHunter 全策略回测（15 策略，不含已测的底部趋势拐点）
方法：单股内部向量化（个股自身日历，避免面板法对齐伪影）
执行：信号 T 日收盘确认 → T+1 开盘买入 → 持有 H=5/10/20 收盘卖出
成本：1.15% 往返（项目铁律）
四闸（用户口径 9/1）：胜率>40% + 中位>0 + 均值>0 + 超额>0（vs 全池等权同期）
"""
import pandas as pd
import numpy as np
import time, json, os, sys

T0 = time.time()
def log(msg):
    print(f"[{time.time()-T0:7.1f}s] {msg}", flush=True)

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "v8_factor_cache.pkl")  # 2026-09-24 云端可移植
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "khunter_all_out")  # 2026-09-24 云端可移植
os.makedirs(OUT_DIR, exist_ok=True)

BACKTEST_START = pd.Timestamp("2016-06-01")
HOLDS = [5, 10, 20]
COST = 0.0115
WIN_RATE_MIN = 0.40  # 用户口径：胜率>40%
STOCK_LIMIT = int(os.environ.get("STOCK_LIMIT", "0"))  # 0=全量，>0=冒烟测试

# 2026-09-24 修复：诊断容器（原先失败/空集策略被静默丢弃，summary 中整行缺失）
SIG_ERR = {}

# ---------- 指标 ----------
def calc_indicators(d):
    """d: 正序 DataFrame（date/open/high/low/close/volume），返回加指标列"""
    r = d.copy()
    c, h, l, v = r['close'], r['high'], r['low'], r['volume']
    # 均线
    for n in (5, 10, 20, 25, 30, 60):
        r[f'ma{n}'] = c.rolling(n, min_periods=1).mean()
    # 均量
    r['vol_ma5'] = v.rolling(5, min_periods=1).mean()
    r['vol_ma60'] = v.rolling(60, min_periods=1).mean()
    # 前5日均量（shift1 排除当日）
    r['vol_ma5_prev'] = v.shift(1).rolling(5, min_periods=1).mean()
    # 涨跌幅
    r['pct'] = c.pct_change()
    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    r['dif'] = ema12 - ema26
    r['dea'] = r['dif'].ewm(span=9, adjust=False).mean()
    r['macd'] = r['dif'] - r['dea']
    # KDJ
    llv = l.rolling(9, min_periods=1).min()
    hhv = h.rolling(9, min_periods=1).max()
    rsv = ((c - llv) / (hhv - llv).replace(0, np.nan) * 100).fillna(50)
    r['K'] = rsv.ewm(alpha=1/3, adjust=False).mean()
    r['D'] = r['K'].ewm(alpha=1/3, adjust=False).mean()
    r['J'] = 3 * r['K'] - 2 * r['D']
    # RSI(14) 简单平均
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=1).mean()
    r['rsi'] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    # BOLL
    r['boll_mid'] = c.rolling(20, min_periods=1).mean()
    r['boll_std'] = c.rolling(20, min_periods=1).std()
    r['boll_upper'] = r['boll_mid'] + 2 * r['boll_std']
    r['boll_lower'] = r['boll_mid'] - 2 * r['boll_std']
    r['boll_width'] = r['boll_upper'] - r['boll_lower']
    # 前60日最高（阻力位）
    r['res_60'] = h.shift(1).rolling(60, min_periods=1).max()   # 2026-09-24 修复：前60日（不含当日）
    # 前40日最低
    r['low_40'] = l.rolling(40, min_periods=1).min()
    # 前20日最低
    r['low_20'] = l.rolling(20, min_periods=1).min()
    # 前20日最低 MACD
    r['macd_20min'] = r['macd'].rolling(20, min_periods=1).min()
    # 前20日最低 RSI
    r['rsi_20min'] = r['rsi'].rolling(20, min_periods=1).min()
    return r

def rolling_trend_ok(close, window=20, min_r2=0.5):
    """向量化滚动趋势判断：斜率>0 且 R²≥min_r2。
    替代 rolling.apply(polyfit)（每窗口一次 polyfit 太慢）。
    推导：窗口内 x=0..w-1，x_var=w(w²-1)/12，x_mean=(w-1)/2；
    cov = Σ(j-c_t)·y_j = Σj·y_j - c_t·Σy_j，c_t = t-w+1+x_mean（t=窗口末位置）。
    """
    n = len(close)
    pos = np.arange(n, dtype=float)
    sum_y = close.rolling(window, min_periods=window).sum()
    sum_y2 = (close ** 2).rolling(window, min_periods=window).sum()
    sum_jy = (pos * close).rolling(window, min_periods=window).sum()
    x_var = window * (window ** 2 - 1) / 12.0
    x_mean = (window - 1) / 2.0
    c_t = pos - window + 1 + x_mean
    cov = sum_jy - c_t * sum_y
    slope = cov / x_var
    y_var = sum_y2 - sum_y ** 2 / window
    r2 = np.where(y_var > 0, slope ** 2 * x_var / y_var, 0.0)
    return (slope > 0) & (r2 >= min_r2)

# ---------- 15 策略信号（正序，返回布尔 Series，True=当日收盘确认信号） ----------
def sig_golden_cross_not_green(r):
    """金叉不绿：MACD 水上金叉 + 绿柱≤3 + 布林张口扩大"""
    cross = (r['dif'] > r['dea'] * 1.2) & (r['dif'].shift(1) <= r['dea'].shift(1))
    dif_ok = r['dif'].shift(1) > 0
    dea_ok = r['dea'].shift(1) > 0
    # 金叉前连续绿柱数 ≤3（从金叉日往前数 macd<0 的连续天数）
    green = r['macd'] < 0
    green_run = green.groupby((~green).cumsum()).cumcount() + 1
    green_ok = green_run.shift(1).fillna(0) <= 3
    boll_ok = r['boll_width'] > r['boll_width'].shift(1)
    return cross & dif_ok & dea_ok & green_ok & boll_ok

def sig_golden_triangle(r):
    """黄金三角：MA5/MA10/MA20 三金叉 + 多头排列"""
    a = (r['ma5'] > r['ma10']) & (r['ma5'].shift(1) <= r['ma10'].shift(1))
    b = (r['ma5'] > r['ma20']) & (r['ma5'].shift(1) <= r['ma20'].shift(1))
    c = (r['ma10'] > r['ma20']) & (r['ma10'].shift(1) <= r['ma20'].shift(1))
    # 最近3日内有 A/B/C
    a3 = a.rolling(3, min_periods=1).max().astype(bool)
    b3 = b.rolling(3, min_periods=1).max().astype(bool)
    c_today = c  # C 点必须在今天
    # C 点涨幅 ≥1%
    c_gain = r['pct'] >= 0.01
    # C 点量比 ≥1.1（当日量/前5日均量）
    c_vol = r['volume'] / r['vol_ma5_prev'].replace(0, np.nan) >= 1.1
    # 多头排列
    bull = (r['ma5'] >= r['ma10']) & (r['ma10'] >= r['ma20']) & (r['ma20'] >= r['ma60'])
    return c_today & a3 & b3 & c_gain & c_vol & bull

def sig_immortal_guidance(r):
    """仙人指路：T-1~T-3 冲高回落信号日 + 今日反包"""
    # 信号日条件（T-1~T-3）：冲高≥8% + 上影线≥4% + 量≥1.5倍 + MA5>MA10>MA20
    prev_close = r['close'].shift(1)
    surge = (r['high'] - prev_close) / prev_close >= 0.08
    upper_shadow = np.where(r['close'] > r['open'], r['high'] - r['close'], r['high'] - r['open'])
    shadow_ratio = upper_shadow / r['high'].replace(0, np.nan)
    vol_ok = r['volume'] / r['vol_ma5_prev'].replace(0, np.nan) >= 1.5
    ma_bull = (r['ma5'] > r['ma10']) & (r['ma10'] > r['ma20'])
    sig_day = surge & (shadow_ratio >= 0.04) & vol_ok & ma_bull
    # 最近3日内有信号日
    sig3 = sig_day.rolling(3, min_periods=1).max().astype(bool)
    # 今日收盘 > MA5
    above_ma5 = r['close'] > r['ma5']
    # 今日收盘 ≥ 信号日上影线50%位置（近似：用最近3日最高价的一半）
    # 简化：今日收盘 ≥ 最近3日 (high+close)/2 的最小值
    upper50 = ((r['high'] + r['close']) / 2).rolling(3, min_periods=1).min()
    anti = r['close'] >= upper50
    # 20日趋势：斜率>0 且 R²≥0.5（向量化）
    trend = rolling_trend_ok(r['close'], 20, 0.5)
    return sig3 & above_ma5 & anti & trend

def sig_limit_up_pullback(r):
    """涨停回马枪：涨停后回调企稳"""
    lu = (r['pct'] >= 0.095) & (r['volume'] / r['vol_ma5_prev'].replace(0, np.nan) >= 2.2)
    # 最近6日内有涨停
    lu6 = lu.rolling(6, min_periods=1).max().astype(bool)
    # 涨停日收盘价（最近6日内最后一个涨停日）
    lu_close = r['close'].where(lu).ffill(limit=5)
    # 涨停后回调：今日距涨停日 1-9 天
    days_since = np.where(lu, 0, np.nan)
    # 用 rolling 计算距最近涨停的天数
    lu_idx = pd.Series(np.where(lu, np.arange(len(r)), np.nan), index=r.index)
    days_since = (np.arange(len(r)) - lu_idx.ffill()).fillna(99)
    days_ok = (days_since >= 1) & (days_since <= 9)
    # 回调幅度 0-15%（涨停收盘到今日最低）
    pullback = (lu_close - r['low']) / lu_close
    pb_ok = (pullback >= 0) & (pullback <= 0.15)
    # 收盘不破涨停收盘 95% 且不超 105%
    close_ok = (r['close'] >= lu_close * 0.95) & (r['close'] <= lu_close * 1.05)
    # 有缩量日（≤涨停量 50%）——近似：今日量 ≤ 涨停日量 50%
    lu_vol = r['volume'].where(lu).ffill(limit=5)
    shrink = r['volume'] <= lu_vol * 0.5
    # 至少一日收盘 < 涨停收盘
    lower = r['close'] < lu_close
    return lu6 & days_ok & pb_ok & close_ok & shrink & lower

def sig_limit_up_sideways(r):
    """涨停横盘：涨停后横盘 + 突破信号"""
    lu = (r['pct'] >= 0.095) & (r['volume'] / r['vol_ma5_prev'].replace(0, np.nan) >= 1.8)
    lu10 = lu.rolling(10, min_periods=1).max().astype(bool)
    lu_close = r['close'].where(lu).ffill(limit=9)
    lu_idx = pd.Series(np.where(lu, np.arange(len(r)), np.nan), index=r.index)
    days_since = (np.arange(len(r)) - lu_idx.ffill()).fillna(99)
    days_ok = (days_since >= 1) & (days_since <= 10)
    # 横盘区间：最高≤涨停价108%，最低≥涨停价95%
    high_ok = r['high'] <= lu_close * 1.08
    low_ok = r['low'] >= lu_close * 0.95
    # 收盘≥涨停收盘 99%
    close_ok = r['close'] >= lu_close * 0.99
    # 有缩量日（≤涨停量 70%）
    lu_vol = r['volume'].where(lu).ffill(limit=9)
    shrink = r['volume'] <= lu_vol * 0.7
    # 今日上涨 + 量≥昨日 1.3 倍
    up = r['close'] > r['close'].shift(1)
    vol_up = r['volume'] / r['volume'].shift(1).replace(0, np.nan) >= 1.3
    # KDJ 金叉（K<20）或 MACD 金叉
    kdj_cross = (r['K'] > r['D']) & (r['K'].shift(1) <= r['D'].shift(1)) & (r['K'] < 20)
    macd_cross = (r['dif'] > r['dea']) & (r['dif'].shift(1) <= r['dea'].shift(1))
    return lu10 & days_ok & high_ok & low_ok & close_ok & shrink & up & vol_up & (kdj_cross | macd_cross)

def sig_morning_star(r):
    """启明星：三根 K 线底部反转"""
    body = (r['close'] - r['open']).abs() / r['open'].replace(0, np.nan)
    first_bear = (r['close'] < r['open']) & (body > 0.03)  # 前日长阴
    second_small = body <= body.shift(1) * 0.3  # 昨日小实体（≤前日实体30%）
    third_bull = (r['close'] > r['open']) & (r['pct'] > 0.05) & (r['close'] > r['ma5'])  # 今日长阳
    vol_ok = r['volume'] / r['volume'].shift(1).replace(0, np.nan) >= 1.5
    return first_bear.shift(2) & second_small.shift(1) & third_bull & vol_ok

def sig_multi_golden_cross(r):
    """多金叉共振：MA/KDJ/MACD 三金叉共振"""
    ma_cross = (r['ma5'] > r['ma20']) & (r['ma5'].shift(1) <= r['ma20'].shift(1))
    kdj_cross = (r['K'] > r['D']) & (r['K'].shift(1) <= r['D'].shift(1))
    macd_cross = (r['dif'] > r['dea']) & (r['dif'].shift(1) <= r['dea'].shift(1))
    ma3 = ma_cross.rolling(3, min_periods=1).max().astype(bool)
    kdj3 = kdj_cross.rolling(3, min_periods=1).max().astype(bool)
    macd3 = macd_cross.rolling(3, min_periods=1).max().astype(bool)
    # 三信号时间差 ≤1 天（近似：都在最近3日内）
    close_ok = (r['close'] > r['ma5']) & (r['close'] > r['ma20'])
    vol_ok = r['volume'] / r['vol_ma5'].replace(0, np.nan) >= 1.0
    return ma3 & kdj3 & macd3 & close_ok & vol_ok

def sig_multi_party_cannon(r):
    """多方炮：两阳夹一阴"""
    body = (r['close'] - r['open']).abs()
    first_bull = (r['close'] > r['open']) & (r['pct'] >= 0.03)  # 前前日阳线
    second_bear = (r['close'] < r['open']) & (body <= body.shift(1) * 0.5)  # 前日阴线小实体
    # 回调 ≤ 第一根涨幅 50%
    fallback = (r['close'].shift(1) - r['close']) / (r['close'].shift(2) - r['open'].shift(2)).replace(0, np.nan)
    fallback_ok = fallback <= 0.5
    second_vol = r['volume'] <= r['volume'].shift(1) * 0.8  # 前日缩量
    third_bull = (r['close'] > r['open']) & (r['pct'] >= 0.03) & (r['close'] > r['close'].shift(2))  # 今日阳线突破
    third_vol = r['volume'] > r['volume'].shift(2)  # 今日放量
    ma_ok = r['close'] > r['ma20']
    return first_bull.shift(2) & second_bear.shift(1) & fallback_ok.shift(1) & second_vol.shift(1) & third_bull & third_vol & ma_ok

def sig_resistance_breakout(r):
    """阻力位突破：放量长阳突破60日高点"""
    surge = (r['pct'] >= 0.09) & (r['volume'] / r['vol_ma5_prev'].replace(0, np.nan) >= 2.2)
    breakout = surge & (r['close'] >= r['res_60'])
    # 最近3日内有突破
    b3 = breakout.rolling(3, min_periods=1).max().astype(bool)
    # 突破日与阻力高点日间隔 ≥30 天（近似：突破日收盘 ≥ 前60日最高，且前30日最高 < 突破收盘）
    gap_ok = r['high'].shift(1).rolling(30, min_periods=1).max() < r['close']   # 2026-09-24 修复：不含当日
    # 突破后回踩不破阻力 98%（近似：今日最低 ≥ 前60日最高 98%）
    pullback_ok = r['low'] >= r['res_60'] * 0.98
    # 均线多头
    ma_bull = (r['ma5'] > r['ma10']) & (r['ma10'] > r['ma20'])
    return b3 & gap_ok & pullback_ok & ma_bull

def sig_strategy_2560(r):
    """2560战法：突破MA25 + 量线金叉"""
    price_break = (r['close'] > r['ma25']) & (r['close'].shift(1) <= r['ma25'].shift(1))
    vol_cross = (r['vol_ma5'] > r['vol_ma60']) & (r['vol_ma5'].shift(1) <= r['vol_ma60'].shift(1))
    above_ma10 = r['close'] > r['ma10']
    gain = r['pct'] >= 0.05
    vol_ok = r['volume'] / r['vol_ma5'].replace(0, np.nan) >= 1.2
    return price_break & vol_cross & above_ma10 & gain & vol_ok

def sig_strong_wash(r):
    """强势洗盘弱转强：大阳+放量阴洗盘+反包+持续强势"""
    big = (r['pct'] >= 0.08) & (r['close'] > r['open']) & (r['volume'] / r['vol_ma5_prev'].replace(0, np.nan) >= 1.5)
    big6 = big.rolling(6, min_periods=1).max().astype(bool)
    # 次日放量阴线
    wash = big.shift(1) & (r['close'] < r['open']) & (r['volume'] >= r['volume'].shift(1) * 1.2)
    # 3日内反包阳线（收盘>大阳收盘 或 >洗盘开盘）
    big_close = r['close'].where(big).ffill(limit=5)
    reversal = (r['close'] > r['open']) & ((r['close'] > big_close) | (r['close'] > r['open'].shift(1)))
    rev3 = reversal.rolling(3, min_periods=1).max().astype(bool)
    # 反包后至今收盘都在大阳线上方（≤5天）
    strong = r['close'] > big_close
    return big6 & wash & rev3 & strong

def sig_trend_acceleration(r):
    """趋势加速拐点：上升趋势 + 放量长阳 + 距低点近 + 回调有支撑"""
    surge = (r['pct'] >= 0.08) & (r['volume'] / r['vol_ma5_prev'].replace(0, np.nan) >= 2.0)
    s5 = surge.rolling(5, min_periods=1).max().astype(bool)
    # 20日上升趋势（斜率>0, R²>0.5，向量化）
    trend = rolling_trend_ok(r['close'], 20, 0.5)
    # 长阳起涨点距40日最低点 ≤15%
    dist = (r['close'].shift(1) - r['low_40']) / r['low_40'].replace(0, np.nan)
    dist_ok = dist <= 0.15
    # 长阳后回调不破长阳开盘（近似：今日最低 ≥ 最近5日开盘最小值）
    open5 = r['open'].rolling(5, min_periods=1).min()
    support_ok = r['low'] >= open5
    return s5 & trend & dist_ok & support_ok

def sig_trend_resonance(r):
    """趋势共振反转：RSI 突破 + 均线金叉 + MACD 金叉"""
    rsi_break = (r['rsi'] >= 50) & (r['rsi'].shift(1) < 50) & (r['rsi_20min'] <= 30)
    rsi3 = rsi_break.rolling(3, min_periods=1).max().astype(bool)
    ma_cross = (r['ma5'] > r['ma20']) & (r['ma5'].shift(1) <= r['ma20'].shift(1))
    ma3 = ma_cross.rolling(3, min_periods=1).max().astype(bool)
    macd_cross = (r['dif'] > r['dea']) & (r['dif'].shift(1) <= r['dea'].shift(1))
    macd3 = macd_cross.rolling(3, min_periods=1).max().astype(bool)
    return rsi3 & ma3 & macd3

def sig_trend_start(r):
    """趋势起点：MACD金叉 + 布林上穿中轨 + 阳线 + 站上MA5 + 放量"""
    macd_cross = (r['dif'] > r['dea']) & (r['dif'].shift(1) <= r['dea'].shift(1)) & (r['dif'] > 0)
    boll_cross = (r['close'] > r['boll_mid']) & (r['close'].shift(1) <= r['boll_mid'].shift(1))
    bullish = r['close'] > r['open']
    above_ma5 = r['close'] > r['ma5']
    vol_ok = r['volume'] > r['vol_ma5'] * 1.2
    return macd_cross & boll_cross & bullish & above_ma5 & vol_ok

def sig_w_bottom(r):
    """W底：双底 + 颈线突破 + 趋势确认"""
    # 双底：最近40日内两低点价差≤3%，间隔>10天（近似：40日最低与次低）
    # 简化：40日最低点与20日最低点接近（价差≤3%），且间隔>10天
    low40 = r['low_40']
    low20 = r['low_20']
    bottom_ok = (low20 / low40.replace(0, np.nan) - 1).abs() <= 0.03
    # 颈线 = 两低点之间最高点（近似：40日最高）
    neckline = r['high'].shift(1).rolling(40, min_periods=1).max()   # 2026-09-24 修复：前40日（不含当日）
    # 最近5日内放量突破：涨幅>8% + 量≥1.2倍 + 收盘≥颈线101% + 前日收盘<颈线
    surge = (r['pct'] > 0.08) & (r['volume'] / r['vol_ma5_prev'].replace(0, np.nan) >= 1.2)
    break_ok = surge & (r['close'] >= neckline * 1.01) & (r['close'].shift(1) < neckline)
    b5 = break_ok.rolling(5, min_periods=1).max().astype(bool)
    # 今日 MA10>MA30
    ma_ok = r['ma10'] > r['ma30']
    # 突破后收盘不破颈线 98%
    support_ok = r['close'] >= neckline * 0.98
    # L1 前有 20% 以上下跌（近似：40日最高 ≥ 40日最低 × 1.2）
    decline_ok = r['high'].rolling(40, min_periods=1).max() >= low40 * 1.2
    return bottom_ok & b5 & ma_ok & support_ok & decline_ok

SIGNALS = {
    'golden_cross_not_green': sig_golden_cross_not_green,
    'golden_triangle': sig_golden_triangle,
    'immortal_guidance': sig_immortal_guidance,
    'limit_up_pullback': sig_limit_up_pullback,
    'limit_up_sideways': sig_limit_up_sideways,
    'morning_star': sig_morning_star,
    'multi_golden_cross': sig_multi_golden_cross,
    'multi_party_cannon': sig_multi_party_cannon,
    'resistance_breakout': sig_resistance_breakout,
    'strategy_2560': sig_strategy_2560,
    'strong_wash': sig_strong_wash,
    'trend_acceleration': sig_trend_acceleration,
    'trend_resonance': sig_trend_resonance,
    'trend_start': sig_trend_start,
    'w_bottom': sig_w_bottom,
}

# ---------- 主流程 ----------
def main():
    log("加载缓存 ...")
    cache = pd.read_pickle(CACHE)
    log(f"股票数: {len(cache)}")

    # 全池等权基准（用于超额）：每只股票日收益，取全市场日截面均值
    log("计算全池基准 ...")
    all_ret = {}
    for code, df in cache.items():
        if df is None or len(df) < 30:
            continue
        d = df[['open', 'high', 'low', 'close', 'volume']].copy()
        d.index.name = None
        d['date'] = d.index
        d = d.sort_values('date', ascending=True).reset_index(drop=True)
        d['ret'] = d['close'].pct_change()
        all_ret[code] = d[['date', 'ret']]
    bench_df = pd.concat(all_ret.values(), ignore_index=True)
    bench = bench_df.groupby('date')['ret'].mean()
    bench_cum = (1 + bench).cumprod()
    log(f"基准日数: {len(bench)}")

    # 逐股扫描：预排序一次 + 向量化前向收益 + 15 策略信号
    log("逐股扫描 15 策略信号 + 预计算前向收益 ...")
    events = {name: [] for name in SIGNALS}  # name -> [(code, pos)]
    fwd_cache = {}  # code -> {'fwd': {H: np.array}, 'bcum': np.array}
    n_stock = 0
    for code, df in cache.items():
        if STOCK_LIMIT and n_stock >= STOCK_LIMIT:
            break
        if df is None or len(df) < 70:
            continue
        d = df[['open', 'high', 'low', 'close', 'volume']].copy()
        d.index.name = None
        d['date'] = d.index
        d = d.sort_values('date', ascending=True).reset_index(drop=True)
        r = calc_indicators(d)
        n = len(d)
        # 预计算前向收益（向量化，位置 i 对应 T 日收盘确认）
        fwd = {}
        for H in HOLDS:
            arr = np.full(n, np.nan)
            m = n - H
            if m > 0:
                e = d['open'].values[1:m + 1]      # T+1 开盘
                x = d['close'].values[H:m + H]     # T+H 收盘
                arr[:m] = np.where(e > 0, x / e - 1 - COST, np.nan)  # 停牌 open=0 → NaN
            fwd[H] = arr
        # 个股日历上的基准累计净值（用于超额）
        bcum = bench_cum.reindex(d['date'].values).values
        fwd_cache[code] = {'fwd': fwd, 'bcum': bcum}
        # 15 策略信号
        for name, fn in SIGNALS.items():
            try:
                sig = fn(r)
            except Exception as ex:              # 2026-09-24 修复：不再静默丢弃
                SIG_ERR.setdefault(name, []).append((code, repr(ex)))
                continue
            if not sig.any():
                continue
            idx = np.where(sig.values & (r['date'].values >= BACKTEST_START))[0]
            for i in idx:
                events[name].append((code, int(i)))
        n_stock += 1
        if n_stock % 500 == 0:
            log(f"  {n_stock} 只")

    log("计算四闸 ...")
    results = {}
    for name, evs in events.items():
        results[name] = []
        if not evs:
            continue
        for H in HOLDS:
            fr = []
            ex = []
            for code, i in evs:
                rec = fwd_cache[code]
                fwd = rec['fwd'][H]
                if i >= len(fwd) or np.isnan(fwd[i]):
                    continue
                fr.append(fwd[i])
                bc = rec['bcum']
                if i + H < len(bc) and not (np.isnan(bc[i]) or np.isnan(bc[i + H])) and bc[i] > 0:
                    ex.append(fwd[i] - (bc[i + H] / bc[i] - 1))
            if not fr:
                results[name].append({'hold': H, 'n': 0})
                continue
            fr = np.array(fr)
            ex = np.array(ex) if ex else np.array([0.0])
            n = len(fr)
            wr = (fr > 0).mean() * 100
            med = np.median(fr) * 100
            mean = fr.mean() * 100
            ex_mean = ex.mean() * 100
            sharpe = fr.mean() / fr.std() if fr.std() > 0 else 0
            passed = (wr > WIN_RATE_MIN * 100) and (med > 0) and (mean > 0) and (ex_mean > 0)
            results[name].append({
                'hold': H, 'n': n, 'win_rate': round(wr, 2), 'median': round(med, 3),
                'mean': round(mean, 3), 'excess_mean': round(ex_mean, 3),
                'sharpe': round(sharpe, 3), 'pass': passed
            })

    # 输出
    log("=" * 100)
    rows = []
    for name, res in results.items():
        for r in res:
            rows.append({'strategy': name, **r})
            if r['n'] > 0:
                log(f"  {name:24s} H{r['hold']:2d} n={r['n']:6d} wr={r['win_rate']:5.2f}% med={r['median']:7.3f}% mean={r['mean']:7.3f}% excess={r['excess_mean']:7.3f}% sharpe={r['sharpe']:6.3f} {'✅' if r['pass'] else '❌'}")

    df_out = pd.DataFrame(rows)
    df_out.to_csv(os.path.join(OUT_DIR, 'khunter_all_strategies_summary.csv'), index=False)
    with open(os.path.join(OUT_DIR, 'khunter_all_strategies_results.json'), 'w', encoding='utf-8') as f:
        json.dump({name: res for name, res in results.items()}, f, ensure_ascii=False, indent=1, default=str)

    # 2026-09-24 修复：诊断输出（原先失败/空集策略被静默丢弃，summary 中整行缺失、不报错）
    # 空集判定 = 全池 0 事件（不是逐股无信号 —— 后者对多数策略是常态）
    _EMPTY_LIST = sorted(n for n in SIGNALS if not events.get(n))
    if SIG_ERR or _EMPTY_LIST:
        log("信号诊断：")
        for _n in _EMPTY_LIST:
            log(f"    空集（全池 0 信号）：{_n}")
        for _n, _errs in sorted(SIG_ERR.items()):
            log(f"    异常（{len(_errs)} 只股票，示例 {_errs[0][0]}）：{_n} → {_errs[0][1]}")
    with open(os.path.join(OUT_DIR, 'khunter_all_strategies_diagnostics.json'), 'w', encoding='utf-8') as f:
        json.dump({'empty': _EMPTY_LIST,
                   'errors': {k: v[:5] for k, v in SIG_ERR.items()},
                   'note': '2026-09-24 修复前这些策略被 except/any() 静默丢弃，summary 中整行缺失'},
                  f, ensure_ascii=False, indent=1, default=str)
    log("完成")


if __name__ == "__main__":
    main()