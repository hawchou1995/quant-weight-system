# -*- coding: utf-8 -*-
"""
六类指标加权打分模块（移植自 quant-weight-system v1.4）
=====================================================
指标权重配置：趋势30 / 动能25 / 量能15 / 超买超卖15 / 风控10 / 研报5
每类 0-100 分，总分 = Σ(类分×权重) ∈ [0,100]
操作档位（v1.4 target_cap 稳健仓位模型）：
  ≥75 满仓加仓 ｜ 60-74 轻仓加仓 ｜ 45-59 观望 ｜ 30-44 减至半仓 ｜ <30 清仓
  单次调整上限 CAP_PCT=50%（稳健增强：目标制 + 单次上限）
置信度：覆盖率≥80% 且方向一致≥75% → 高；覆盖率<60% → 低；其余中
数据溯源：K 线 = A 级（交易所撮合）；研报情报 = B 级（人工分级）
窗口说明：监控 raw_kline 通常 50 根 → 60 日回撤退化为可用窗口、MA120 不参与（USE_MID_MA=False），
          置信度会如实反映数据覆盖情况。
"""
import math, statistics

# ---- 权重配置（专家先验，规格书 v1 决策 D5 + 二期 37 只验证结论）----
WEIGHTS = {
    "trend": 0.30,     # 趋势类（MA位置/ADX/20日动量）
    "momentum": 0.25,  # 动能类（MACD/当日涨跌）
    "volume": 0.15,    # 量能类（量比/量价配合）
    "osc": 0.15,       # 超买超卖类（RSI/KDJ三重过滤）
    "risk": 0.10,      # 风控类（ATR波动/回撤距离）
    "news": 0.05,      # 研报情报类（L1-L4）
}
USE_MID_MA = False     # 二期验证：MA30/MA120 生产双输，默认关闭

# ---- v3（2026-08-12 回测选型）：布林带位置分——唯一采纳项（27池 +138.63% vs 基线 +132.47%，回撤 13.91% 更低、胜率 89.4% 更高、换手减半）----
# 其余 v3 候选（均线三线/共振补丁/牛熊系数）回测数据否决（收益净损），保留在 _quant_weight_ref/weight_system_backtest_v3.py 可回溯，不进生产。
USE_BOLL_POS = True    # 布林带 %B 位置分并入超买超卖类（RSI45/KDJ30/布林25）

# ---- v4（2026-08-12 回测选型）：量价三件套补丁式——采纳（27池 +141.54% vs v3 +138.63%，回撤 13.84% 更低、胜率 91.6% 更高、换手 0.787% 更低）----
# 地量见底/天量见顶（双确认+位置门控）+ 纯量价背离 + RSI背离(量能验证)，全部补丁式 ±10；
# 与 v3 共振补丁本质区别：量价背离是 20 日极值低频事件，换手率不升反降（0.845%→0.787%）。
USE_EXTREME_VOL = True # v4-1 地量见底/天量见顶（量比<0.6且20日量新低=地量；>2.5且20日量新高=天量；位置门控）
USE_PDV = True         # v4-2 纯量价背离（价创20日新高量未同步=顶背离-10；价创新低量未同步缩=底背离+10）
USE_RSI_DIV = True     # v4-3 RSI背离+量能验证（价新高RSI高点变矮=顶背离；价新低RSI低点抬高=底背离；缩量/放量加权）
SCORE_MODE = "patch"   # "patch"=补丁式±10（v4 选型）/ "evidence"=分支内 cap/floor
PDV_BONUS = 10.0
RSIDIV_BONUS = 10.0

# ---- v5（2026-08-12 回测选型）：恐贪指数 FG 动态门槛——采纳「恐惧机会」方向（27池 +142.40% vs v4 +141.54%，夏普 1.672 最高、胜率 92.1% 最高、换手 0.778% 最低）----
# 推文「积极信号在积累，指标持续向好+期权策略」（东胜小猢狲 2026-08-07）恐贪指数吸收：
# 沪深300 日K衍生 5 维（动量/趋势/波动率/回撤/量能）滚动分位归一化 W=250 → FG ∈ [0,100]
# FG_MODE="opportunistic"（恐惧机会）：恐惧区（FG<50）加仓门槛下移、清仓阈值上移 = 逆向抄底；
# "defensive"（恐惧防御）回测否决（胜率 85.0%）。FG 第 7 维权重回测收益最高但回撤恶化 5.1pct，暂缓。
USE_FG_DYNAMIC = True  # v5-1 FG 动态门槛（替代三档离散门禁的市场情绪层）
FG_MODE = "opportunistic"
FG_W = 250             # 滚动分位窗口
FG_WINDOW = 20         # 分维子窗口
FG_K_BUY = 6.0         # 加仓门槛斜率
FG_K_SELL = 5.0        # 清仓阈值斜率
FG_BUY_CLAMP = (50.0, 78.0)
FG_SELL_CLAMP = (22.0, 42.0)

# ---- 操作阈值（总分 0-100；市场状态调节：weak 时加仓门槛上移、清仓阈值上移）----
BUY_STRONG = 75
BUY_WEAK = 60
SELL_WEAK = 40
SELL_STRONG = 30

# 市场状态调节（市场测温 skill 启示：弱势市场提高加仓门槛、提早减仓；强势市场适度收敛）
MARKET_ADJUST = {
    "strong": {"BUY_WEAK": 58, "SELL_STRONG": 28},  # 大盘强（沪深300>MA20且偏离>+2%）：门槛略松
    "normal": {"BUY_WEAK": 62, "SELL_STRONG": 30},  # 中性：默认门槛
    "weak": {"BUY_WEAK": 65, "SELL_STRONG": 35},    # 大盘弱势（沪深300<MA20）：加仓需≥65，清仓提前到<35
}

# ---- v1.4 仓位模型（稳健增强：目标制+单次上限 50%）----
POSITION_MODEL = "target_cap"
CAP_PCT = 0.50

# ---- 置信度规则 ----
CONF_HIGH_COV = 0.80
CONF_LOW_COV = 0.60
CONF_AGREE = 0.75

# ---- 数据溯源 ----
PROVENANCE = {
    "kline": {"name": "通达信 K 线（tdx-connector）", "level": "A", "note": "交易所撮合数据"},
    "news": {"name": "研报情报.json（vault 投研 L1-L4）", "level": "B", "note": "人工分级"},
}

NEWS_SCORE = {"L1": 70.0, "L2": 50.0, "L3": 30.0, "L4": 20.0}


def _clip(x):
    return max(0.0, min(100.0, float(x)))


class Row:
    """轻量行对象：从监控序列计算权重系统所需指标，字段名与 weight_system_backtest 对齐。"""
    pass


def compute_indicators(closes, highs, lows, vols):
    """向量化指标计算（短窗口适配版）。返回指标 dict 列表（每根K线一条）。"""
    n = len(closes)
    out = []
    # 预计算序列
    def sma(vals, w, i):
        if i + 1 < w:
            return float("nan")
        return statistics.mean(vals[i + 1 - w:i + 1])
    def ema_series(vals, span):
        k = 2 / (span + 1)
        e, res = None, []
        for v in vals:
            e = v if e is None else v * k + e * (1 - k)
            res.append(e)
        return res
    ma20s = [sma(closes, 20, i) for i in range(n)]
    def stddev(vals, w, i):
        if i + 1 < w:
            return float("nan")
        window = vals[i + 1 - w:i + 1]
        return statistics.pstdev(window)
    std20s = [stddev(closes, 20, i) for i in range(n)]
    boll_pcts = []
    for i in range(n):
        if math.isnan(ma20s[i]) or math.isnan(std20s[i]) or std20s[i] == 0:
            boll_pcts.append(float("nan"))
        else:
            up = ma20s[i] + 2 * std20s[i]
            dn = ma20s[i] - 2 * std20s[i]
            boll_pcts.append((closes[i] - dn) / (up - dn))
    ema12 = ema_series(closes, 12)
    ema26 = ema_series(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = ema_series(dif, 9)
    # KDJ
    ks, ds, js = [], [], []
    k_prev = d_prev = 50.0
    for i in range(n):
        lo9 = min(lows[max(0, i - 8):i + 1]) if lows else closes[i]
        hi9 = max(highs[max(0, i - 8):i + 1]) if highs else closes[i]
        rsv = 50.0 if hi9 == lo9 else (closes[i] - lo9) / (hi9 - lo9) * 100
        k = 2 / 3 * k_prev + 1 / 3 * rsv
        d = 2 / 3 * d_prev + 1 / 3 * k
        ks.append(k); ds.append(d); js.append(3 * k - 2 * d)
        k_prev, d_prev = k, d
    # ATR(14)（无高低价时用收盘价退化）
    atrs = []
    prev_c = closes[0]
    tr_prev = None
    for i in range(n):
        h = highs[i] if highs else closes[i]
        l = lows[i] if lows else closes[i]
        c = closes[i]
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        atrs.append(tr if tr_prev is None else (tr_prev * 13 + tr) / 14)
        tr_prev = atrs[-1]
        prev_c = c
    # RSI(14) Wilder
    rsis = []
    ag = al = 0.0
    for i in range(n):
        if i == 0:
            delta = 0.0
        else:
            delta = closes[i] - closes[i - 1]
        g = max(delta, 0.0); l_ = max(-delta, 0.0)
        if i < 14:
            ag += g / 14; al += l_ / 14
        else:
            ag = (ag * 13 + g) / 14
            al = (al * 13 + l_) / 14
        rs = ag / al if al > 0 else float("inf")
        rsis.append(100.0 if rs == float("inf") else 100 - 100 / (1 + rs))
    # ADX(14)（无高低价时用收盘价退化）
    adxs = []
    plus_dm_s = minus_dm_s = tr14_s = 0.0
    for i in range(n):
        if i == 0:
            plus_dm_s = minus_dm_s = tr14_s = 0.0
            adxs.append(float("nan"))
            continue
        hi_prev = highs[i - 1] if highs else closes[i - 1]
        lo_prev = lows[i - 1] if lows else closes[i - 1]
        hi = highs[i] if highs else closes[i]
        lo = lows[i] if lows else closes[i]
        up = hi - hi_prev
        dn = lo_prev - lo
        plus_dm = up if (up > dn and up > 0) else 0.0
        minus_dm = dn if (dn > up and dn > 0) else 0.0
        tr = max(hi - lo, abs(hi - closes[i - 1]), abs(lo - closes[i - 1]))
        if i <= 14:
            plus_dm_s += plus_dm; minus_dm_s += minus_dm; tr14_s += tr
        else:
            plus_dm_s = plus_dm_s - plus_dm_s / 14 + plus_dm
            minus_dm_s = minus_dm_s - minus_dm_s / 14 + minus_dm
            tr14_s = tr14_s - tr14_s / 14 + tr
        pdi = 100 * plus_dm_s / tr14_s if tr14_s > 0 else 0.0
        mdi = 100 * minus_dm_s / tr14_s if tr14_s > 0 else 0.0
        dx = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0.0
        if i == 14:
            adxs.append(dx)
        elif i > 14:
            adxs.append((adxs[-1] * 13 + dx) / 14)
        else:
            adxs.append(float("nan"))
    # 量比（当日量/前5日均量）
    for i in range(n):
        r = Row()
        r.close = closes[i]
        r.volume = vols[i]
        r.high = highs[i] if highs else closes[i]
        r.low = lows[i] if lows else closes[i]
        r.ma20 = ma20s[i]
        r.ma20_dev = (closes[i] / ma20s[i] - 1) * 100 if not math.isnan(ma20s[i]) else float("nan")
        r.pct_chg = (closes[i] / closes[i - 1] - 1) * 100 if i > 0 else 0.0
        w = 20 if len(closes) >= 60 else max(5, len(closes) - 1)  # 60日回撤退化窗口
        hi_w = max(closes[max(0, i + 1 - w):i + 1]) if i + 1 >= 2 else closes[i]
        r.dd60 = (closes[i] / hi_w - 1) * 100
        r.atr_pct = atrs[i] / closes[i] * 100
        r.dif = dif[i]; r.dea = dea[i]
        r.macd_hist = (dif[i] - dea[i]) * 2
        r.boll_pct = boll_pcts[i]
        r.k = ks[i]; r.d = ds[i]; r.j = js[i]
        r.rsi = rsis[i]
        r.adx = adxs[i]
        r.mom20 = (closes[i] / closes[max(0, i - 20)] - 1) * 100 if i >= 20 else float("nan")
        if i >= 5 and vols[i] > 0:
            v5 = statistics.mean(vols[i - 5:i])
            r.vol_ratio = vols[i] / v5 if v5 > 0 else float("nan")
        else:
            # 当日无成交量（早盘竞价占位/停牌）→ 数据缺失：量能类中性打分、看板显示"—"（不误报 0）
            r.vol_ratio = float("nan")
        # ---- v4 量价候选列（极值/背离）----
        if i >= 20:
            win_v = vols[i - 19:i + 1]
            r.vol_low20 = (vols[i] == min(win_v)) and vols[i] > 0
            r.vol_high20 = (vols[i] == max(win_v)) and vols[i] > 0
            r.vol_max19 = max(vols[i - 19:i]) if i >= 20 else float("nan")
            r.vol_min19 = min(vols[i - 19:i]) if i >= 20 else float("nan")
            r.px_high20 = closes[i] >= max(closes[i - 19:i + 1])
            r.px_low20 = closes[i] <= min(closes[i - 19:i + 1])
            r.rsi_max19 = max(rsis[i - 19:i]) if i >= 20 and not any(math.isnan(x) for x in rsis[i - 19:i]) else float("nan")
            r.rsi_min19 = min(rsis[i - 19:i]) if i >= 20 and not any(math.isnan(x) for x in rsis[i - 19:i]) else float("nan")
        else:
            r.vol_low20 = r.vol_high20 = False
            r.vol_max19 = r.vol_min19 = r.rsi_max19 = r.rsi_min19 = float("nan")
            r.px_high20 = r.px_low20 = False
        out.append(r)
    return out


def score_trend(row):
    s = 0.0
    if not math.isnan(row.ma20):
        if row.close > row.ma20:
            s += 40 if row.ma20_dev < 15 else 30
        else:
            s += 10 if row.ma20_dev > -8 else 0
    else:
        s += 20
    if USE_MID_MA:
        pass  # 二期结论：生产双输，不启用
    if not math.isnan(row.adx):
        if row.adx >= 25: s += 30
        elif row.adx >= 20: s += 22
        elif row.adx >= 15: s += 12
        else: s += 4
    else:
        s += 15
    if not math.isnan(row.mom20):
        if row.mom20 > 8: s += 30
        elif row.mom20 > 0: s += 22
        elif row.mom20 > -8: s += 12
        else: s += 4
    else:
        s += 15
    return _clip(s)


def score_momentum(row):
    s = 0.0
    if not math.isnan(row.dif) and not math.isnan(row.dea):
        if row.dif > row.dea:
            s += 40 if row.dif > 0 else 30
        else:
            s += 12 if row.dif > 0 else 4
    else:
        s += 25
    if not math.isnan(row.pct_chg):
        atr_norm = row.atr_pct if not math.isnan(row.atr_pct) else 3.0
        if row.pct_chg >= 0:
            s += 30 if row.pct_chg >= 2 else 22
        else:
            if row.pct_chg <= -2.5 * max(atr_norm, 1.5):
                s += 0
            elif row.pct_chg <= -1 * atr_norm:
                s += 8
            else:
                s += 15
    else:
        s += 15
    if not math.isnan(row.macd_hist):
        s += 20 if row.macd_hist > 0 else 6
    else:
        s += 10
    return _clip(s)


def _vol_parts(row, is_fund=False):
    """v4 量能类子分明细：返回 (量比分, 量价配合分, extreme标记, pdv标记)。
    与 score_volume(v4) 完全一致，供 evaluate 暴露到看板「量能分解」列。"""
    if is_fund or math.isnan(row.vol_ratio):
        return 50.0, 0.0, None, None, 0.0
    vr = row.vol_ratio
    dd = row.dd60 if not math.isnan(row.dd60) else -50.0
    high_zone = dd > -12
    low_zone = dd < -15
    s_vr = 0.0
    extreme_tag = None
    extreme_adjust = 0.0
    if USE_EXTREME_VOL:
        is_di = bool(row.vol_low20) and vr < 0.6 and low_zone
        is_tian = bool(row.vol_high20) and vr > 2.5 and high_zone
        if is_di:
            extreme_adjust = +15.0; extreme_tag = "地量见底"
        elif is_tian:
            extreme_adjust = -15.0; extreme_tag = "天量见顶"
    if 1.2 <= vr <= 1.8: s_vr = 50
    elif 0.9 <= vr < 1.2: s_vr = 38
    elif 1.8 < vr <= 2.5: s_vr = 40
    elif vr > 2.5: s_vr = 25 + extreme_adjust
    elif 0.6 <= vr < 0.9: s_vr = 25 + extreme_adjust
    else: s_vr = 12 + extreme_adjust
    s_pv = 0.0
    if not math.isnan(row.pct_chg):
        if row.pct_chg > 0 and vr >= 1.0: s_pv = 50
        elif row.pct_chg > 0 and vr < 1.0: s_pv = 30
        elif row.pct_chg <= 0 and vr >= 1.5:
            s_pv = 8 if high_zone else 20
        elif row.pct_chg <= 0 and vr >= 1.0:
            s_pv = 20 if high_zone else 30
        else:
            s_pv = 35
    else:
        s_pv = 25
    pdv_tag = None
    pdv_adjust = 0.0
    if USE_PDV:
        px_high = bool(row.px_high20) and not math.isnan(row.vol_max19)
        px_low = bool(row.px_low20) and not math.isnan(row.vol_min19)
        if px_high and row.vol_max19 > 0 and row.volume < row.vol_max19 * 0.9:
            pdv_tag = "价量顶背离"
            pdv_adjust = -PDV_BONUS if SCORE_MODE == "patch" else 0.0
        elif px_low and row.vol_min19 > 0 and row.volume > row.vol_min19 * 1.1:
            pdv_tag = "价量底背离"
            pdv_adjust = +PDV_BONUS if SCORE_MODE == "patch" else 0.0
    return s_vr, s_pv, extreme_tag, pdv_tag, pdv_adjust


def score_volume(row, is_fund=False):
    s_vr, s_pv, _, pdv_tag, pdv_adjust = _vol_parts(row, is_fund)
    s = s_vr + s_pv + pdv_adjust
    # evidence 模式：背离通过 cap/floor 生效（patch 模式已由 pdv_adjust 处理）
    if SCORE_MODE != "patch" and pdv_tag == "价量顶背离":
        s = min(s, 30.0)
    elif SCORE_MODE != "patch" and pdv_tag == "价量底背离":
        s = max(s, 45.0)
    return _clip(s)


def _boll_score(row):
    """布林带 %B 位置分（v3 选型，2026-08-12）：>1 上轨外超买低分、<0 下轨外超卖高分、0.5 中位中分。
    与回测引擎 _boll_score 完全一致：30/25/22/15/15/5。"""
    b = row.boll_pct if hasattr(row, "boll_pct") else float("nan")
    if b is None or math.isnan(b):
        return 12.5
    if b >= 1.0: return 5.0
    if b >= 0.8: return 15.0
    if b >= 0.5: return 22.0
    if b >= 0.2: return 15.0
    if b >= 0.0: return 25.0
    return 30.0


def _osc_parts(row):
    """v3 选型版子分明细：返回 (rsi分, kdj分, boll分)，与 score_osc(v3) 完全一致。
    供 evaluate 暴露到看板/报告，展示「超买超卖」类的内部构成。"""
    rsi_part = 0.0
    if not math.isnan(row.rsi):
        rsi = row.rsi
        if rsi < 20: rsi_part = 40
        elif rsi < 30: rsi_part = 36
        elif rsi < 50: rsi_part = 30
        elif rsi < 70: rsi_part = 45
        elif rsi < 80: rsi_part = 30
        else: rsi_part = 9
    else:
        rsi_part = 22
    # v4-3 RSI 背离 + 量能验证（素材 37/38 篇：顶背离缩量更可信/底背离放量更靠谱）
    if USE_RSI_DIV and not math.isnan(row.rsi):
        px_high = bool(row.px_high20) and not math.isnan(row.rsi_max19)
        px_low = bool(row.px_low20) and not math.isnan(row.rsi_min19)
        vr = row.vol_ratio if not math.isnan(row.vol_ratio) else 1.0
        if px_high and row.rsi < row.rsi_max19:
            # 顶背离：价新高但 RSI 高点变矮；缩量更可信 → 惩罚更深
            if SCORE_MODE == "patch":
                rsi_part -= RSIDIV_BONUS + (5.0 if vr < 1.0 else 0.0)
            else:
                rsi_part = min(rsi_part, 22.0)
        elif px_low and row.rsi > row.rsi_min19:
            # 底背离：价新低但 RSI 低点抬高；放量更可信 → 奖励更多
            if SCORE_MODE == "patch":
                rsi_part += RSIDIV_BONUS + (5.0 if vr > 1.0 else 0.0)
            else:
                rsi_part = max(rsi_part, 36.0)
    k, dd, adx, mh = row.k, row.d, row.adx, row.macd_hist
    kdj_part = 0.0
    if not any(math.isnan(x) for x in [k, dd]):
        if dd < 30:
            if not math.isnan(adx) and adx >= 20 and not math.isnan(mh) and mh > 0:
                kdj_part = 30 if k > dd else 18
            else:
                kdj_part = 11
        elif dd > 70:
            if not math.isnan(adx) and adx >= 20 and not math.isnan(mh) and mh < 0:
                kdj_part = 3
            else:
                kdj_part = 9
        else:
            kdj_part = 16
    else:
        kdj_part = 15
    return rsi_part, kdj_part, _boll_score(row)


def score_osc(row):
    s = 0.0
    if USE_BOLL_POS:
        # v3 选型版：RSI(45) + KDJ过滤(30) + 布林位置(25)
        s = sum(_osc_parts(row))
        return _clip(s)
    # v2 原版：RSI(60) + KDJ过滤(40)
    if not math.isnan(row.rsi):
        rsi = row.rsi
        if rsi < 20: s += 55
        elif rsi < 30: s += 50
        elif rsi < 50: s += 42
        elif rsi < 70: s += 60
        elif rsi < 80: s += 40
        else: s += 12
    else:
        s += 30
    k, dd, adx, mh = row.k, row.d, row.adx, row.macd_hist
    if not any(math.isnan(x) for x in [k, dd]):
        if dd < 30:
            if not math.isnan(adx) and adx >= 20 and not math.isnan(mh) and mh > 0:
                s += 40 if k > dd else 25
            else:
                s += 15
        elif dd > 70:
            if not math.isnan(adx) and adx >= 20 and not math.isnan(mh) and mh < 0:
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
    if not math.isnan(row.atr_pct):
        ap = row.atr_pct
        if 1.5 <= ap <= 4.5: s += 50
        elif 0.8 <= ap < 1.5 or 4.5 < ap <= 7: s += 35
        else: s += 18
    else:
        s += 25
    if not math.isnan(row.dd60):
        if row.dd60 > -5: s += 50
        elif row.dd60 > -12: s += 35
        elif row.dd60 > -20: s += 20
        else: s += 6
    else:
        s += 25
    return _clip(s)


def score_news(news_level):
    """研报情报类：L1 看多 70 / L2 观望 50 / L3 谨慎 30 / L4 看空 20 / 无 50"""
    return NEWS_SCORE.get(news_level, 50.0)


def compute_total_score(row, news_level, is_fund=False):
    st = score_trend(row)
    sm = score_momentum(row)
    sv = score_volume(row, is_fund=is_fund)
    so = score_osc(row)
    sr = score_risk(row)
    sn = score_news(news_level)
    total = (st * WEIGHTS["trend"] + sm * WEIGHTS["momentum"] + sv * WEIGHTS["volume"]
             + so * WEIGHTS["osc"] + sr * WEIGHTS["risk"] + sn * WEIGHTS["news"])
    comp = {"trend": st, "momentum": sm, "volume": sv, "osc": so, "risk": sr, "news": sn, "total": _clip(total)}
    conf = compute_confidence(comp, is_fund=is_fund)
    return comp["total"], comp, conf


def compute_confidence(comp, is_fund=False):
    cats = ["trend", "momentum", "volume", "osc", "risk", "news"]
    directional = 0
    agree = 0
    for c in cats:
        v = comp.get(c, 50)
        if c == "volume" and is_fund:
            continue
        if c == "news" and v == 50.0:
            continue
        if c == "risk" and v == 50.0:
            continue
        directional += 1
        if v >= 60 or v <= 40:
            agree += 1
    coverage = directional / len(cats)
    agree_ratio = agree / directional if directional > 0 else 0.0
    if coverage >= CONF_HIGH_COV and agree_ratio >= CONF_AGREE:
        level = "高"
    elif coverage < CONF_LOW_COV:
        level = "低"
    else:
        level = "中"
    return {"level": level, "coverage": round(coverage, 2),
            "directional_cats": directional, "agree_ratio": round(agree_ratio, 2)}


def action_tier(total, market_state="normal", bw_override=None, ss_override=None):
    """精细档位 + 稳健加减仓份额口径（v1.4 target_cap：目标制 + 单次上限 50%）
    market_state: strong/normal/weak——weak 时轻仓加仓门槛 62→65、清仓阈值 30→35；strong 时 62→58、28。
    bw_override/ss_override: v5 FG 动态门槛覆盖（恐惧机会方向）。"""
    adj = MARKET_ADJUST.get(market_state, MARKET_ADJUST["normal"])
    bw = bw_override if bw_override is not None else adj["BUY_WEAK"]
    ss = ss_override if ss_override is not None else adj["SELL_STRONG"]
    share = f"单次最多调整 {CAP_PCT * 100:.0f}% 仓位"
    if bw_override is not None:
        share += f"（FG 恐惧机会动态门槛：加仓≥{bw:.0f}/清仓&lt;{ss:.0f}）"
    elif market_state == "weak":
        share += "（市场弱势防御态）"
    elif market_state == "strong":
        share += "（市场强势态）"
    if total >= BUY_STRONG:
        return "满仓加仓", f"满仓加仓（≥{BUY_STRONG} 分，{share}）"
    if total >= bw:
        return "轻仓加仓", f"轻仓加仓（{bw}-{BUY_STRONG - 1} 分，{share}）"
    if total < ss:
        return "清仓", f"清仓（<{ss} 分，{share}）"
    if total < SELL_WEAK:
        return "减至半仓", f"减至半仓（{ss}-{SELL_WEAK - 1} 分，{share}）"
    return "观望", "维持现状（45-59 分）"


def compute_fg(closes, highs=None, lows=None, vols=None):
    """恐贪指数 FG：沪深300 日K衍生 5 维（动量/趋势/波动率/回撤/量能）滚动分位归一化 W=250。
    与回测引擎 _quant_weight_ref/weight_system_backtest_v5_fg.py 的 build_fg_index 完全一致。
    返回 {fg: 0-100, dims: {d1..d5}}；数据不足时 fg=None。
    """
    n = len(closes)
    if n < 60:
        return {"fg": None, "dims": None}
    import math as _m
    def sma(vals, w, i):
        if i + 1 < w:
            return float("nan")
        return statistics.mean(vals[i + 1 - w:i + 1])
    def pctrank_win(vals, i, w, lo=None, hi=None):
        """当前值在过去 w 窗口内的百分位 0-100。"""
        lo = lo if lo is not None else max(0, i + 1 - w)
        window = vals[lo:i + 1]
        if len(window) < max(30, w // 4):
            return float("nan")
        return (sum(1 for x in window if x <= vals[i]) / len(window)) * 100
    mom20 = [closes[i] / closes[max(0, i - FG_WINDOW)] - 1 if i >= FG_WINDOW else float("nan") for i in range(n)]
    ma20s = [sma(closes, FG_WINDOW, i) for i in range(n)]
    ma20_dev = [(closes[i] / ma20s[i] - 1) if not _m.isnan(ma20s[i]) else float("nan") for i in range(n)]
    rets = [closes[i] / closes[i - 1] - 1 if i > 0 else 0.0 for i in range(n)]
    def stddev(vals, w, i):
        if i + 1 < w:
            return float("nan")
        return statistics.pstdev(vals[i + 1 - w:i + 1])
    vol20 = []
    for i in range(n):
        sd = stddev(rets, FG_WINDOW, i)
        vol20.append(sd * _m.sqrt(252) * 100 if not _m.isnan(sd) else float("nan"))
    hi_win = [max(closes[max(0, i + 1 - FG_W):i + 1]) for i in range(n)]
    dd = [closes[i] / hi_win[i] - 1 for i in range(n)]
    vrs = []
    for i in range(n):
        v = vols[i] if vols else None
        if v is None or v <= 0 or i < FG_WINDOW:
            vrs.append(float("nan"))
        else:
            v5 = statistics.mean(vols[i - FG_WINDOW:i])
            vrs.append(v / v5 if v5 > 0 else float("nan"))
    p1 = [pctrank_win(mom20, i, FG_W) for i in range(n)]
    p2 = [pctrank_win(ma20_dev, i, FG_W) for i in range(n)]
    p3 = [100 - pctrank_win(vol20, i, FG_W) if not _m.isnan(vol20[i]) else float("nan") for i in range(n)]
    p4 = [pctrank_win(dd, i, FG_W) for i in range(n)]
    p5 = [pctrank_win(vrs, i, FG_W) if not _m.isnan(vrs[i]) else float("nan") for i in range(n)]
    last = n - 1
    if any(_m.isnan(x) for x in (p1[last], p2[last], p3[last], p4[last], p5[last])):
        return {"fg": None, "dims": None}
    fg = (p1[last] + p2[last] + p3[last] + p4[last] + p5[last]) / 5.0
    return {"fg": round(fg, 1),
            "dims": {"d1_mom": round(p1[last], 1), "d2_trend": round(p2[last], 1),
                     "d3_vol": round(p3[last], 1), "d4_dd": round(p4[last], 1),
                     "d5_volratio": round(p5[last], 1)}}


def fg_dynamic_thresholds(fg, market_state="normal"):
    """FG 动态门槛：恐惧机会方向（opportunistic）——恐惧区门槛下移（更易加仓）、清仓阈值上移。
    返回 (bw_eff, ss_eff)。"""
    adj = MARKET_ADJUST.get(market_state, MARKET_ADJUST["normal"])
    bw, ss = adj["BUY_WEAK"], adj["SELL_STRONG"]
    if not USE_FG_DYNAMIC or fg is None:
        return bw, ss
    dev = (50.0 - fg) / 50.0   # 恐惧(FG<50)→dev>0
    sign = 1.0 if FG_MODE == "defensive" else -1.0
    bw = bw + sign * FG_K_BUY * dev
    ss = ss + sign * FG_K_SELL * dev
    bw = max(FG_BUY_CLAMP[0], min(FG_BUY_CLAMP[1], bw))
    ss = max(FG_SELL_CLAMP[0], min(FG_SELL_CLAMP[1], ss))
    return bw, ss


def evaluate(closes, highs, lows, vols, news_level=None, is_fund=False, market_state="normal", fg=None):
    """对外接口：返回 {total, comp, conf, action, action_desc, provenance, market_state, fg_info}"""
    inds = compute_indicators(closes, highs, lows, vols)
    row = inds[-1]
    total, comp, conf = compute_total_score(row, news_level, is_fund=is_fund)
    # v5 FG 动态门槛：恐惧机会方向——恐惧区加仓门槛下移、清仓阈值上移
    bw_eff, ss_eff = fg_dynamic_thresholds(fg, market_state)
    act, desc = action_tier(total, market_state, bw_override=bw_eff, ss_override=ss_eff)
    fg_info = {"fg": fg, "bw_eff": round(bw_eff, 1), "ss_eff": round(ss_eff, 1),
               "mode": FG_MODE if (USE_FG_DYNAMIC and fg is not None) else None}
    osc_detail = None
    vol_detail = None
    if USE_BOLL_POS:
        rsi_p, kdj_p, boll_p = _osc_parts(row)
        b = row.boll_pct if hasattr(row, "boll_pct") else None
        # RSI 背离标记（与 _osc_parts 内判断一致）
        rsi_div_tag = None
        if USE_RSI_DIV and not math.isnan(row.rsi):
            px_high = bool(row.px_high20) and not math.isnan(row.rsi_max19)
            px_low = bool(row.px_low20) and not math.isnan(row.rsi_min19)
            if px_high and row.rsi < row.rsi_max19:
                rsi_div_tag = "RSI顶背离"
            elif px_low and row.rsi > row.rsi_min19:
                rsi_div_tag = "RSI底背离"
        osc_detail = {
            "rsi": round(rsi_p, 1), "kdj": round(kdj_p, 1), "boll": round(boll_p, 1),
            "boll_pct": round(b, 4) if (b is not None and b == b) else None,
            "rsi_div": rsi_div_tag,
        }
    # 量能类明细（v4 量价三件套）
    s_vr, s_pv, extreme_tag, pdv_tag, _ = _vol_parts(row, is_fund)
    vr = row.vol_ratio if not math.isnan(row.vol_ratio) else None
    vol_detail = {
        "vr": round(vr, 2) if vr is not None else None,
        "vr_score": round(s_vr, 1), "pv_score": round(s_pv, 1),
        "extreme": extreme_tag, "pdv": pdv_tag,
    }
    return {
        "total": round(total, 1), "comp": {k: round(v, 1) for k, v in comp.items()},
        "osc_detail": osc_detail,
        "vol_detail": vol_detail,
        "conf": conf, "action": act, "action_desc": desc, "market_state": market_state,
        "fg_info": fg_info,
        "provenance": {
            "kline": {"name": PROVENANCE["kline"]["name"], "level": PROVENANCE["kline"]["level"]},
            "news": None if news_level is None else {"name": PROVENANCE["news"]["name"], "level": PROVENANCE["news"]["level"], "level_tag": news_level},
            "window": len(closes),
            "note": "60日回撤按可用窗口退化计算；MA120 不参与（USE_MID_MA=False）；量价配合已做高低位区分（A3）",
        },
        "weights": WEIGHTS,
    }
