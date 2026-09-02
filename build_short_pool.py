# -*- coding: utf-8 -*-
"""短线信号标的池（v5.10）：全市场最新交易日短线分 Top 池
================================================================
- 股票：反转版短线分 Top10（全市场 data_full）
- 基金：动量版短线分 Top10（fund_nav_cache，与回测同池）
- （2026-08-17 用户决策：ETF 表现不佳，短线池去 ETF）
输出：short_pool.js（window.SHORT_POOL）+ short_pool.json
详情复用 80 只 details 的行业/名称（命中），未命中用兜底；雷达六类 = 短线因子
"""
import os
import sys, json, math, re, time
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import short_engine as S
import industry_pool as IP   # 2026-08-20：统一行业池（消灭「综合」兜底）

# 名称
NAMES = json.load(open(BASE / "data_full_names.json", encoding="utf-8"))
# 现有 80 只详情（复用行业/名称）
JS = open(BASE / "enhanced_data.js", encoding="utf-8").read()
ENH = json.loads(JS[len("window.ENH = "):-1])
EXIST = ENH["details"]

# 基金名（akshare；2026-08-31 修复：akshare 拉取失败时回退本地 fund_list.csv 缓存）
def fund_names():
    try:
        import akshare as ak
        df = ak.fund_name_em()
        return dict(zip(df["基金代码"], df["基金简称"]))
    except Exception:
        pass
    try:
        import csv
        d = {}
        with open(BASE / "fund_list.csv", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                d[row["基金代码"]] = row["基金简称"]
        return d
    except Exception:
        return {}

# 行业兜底（ETF 按名称关键词 → 申万一级）
ETF_IND_KEY = [
    ("半导体", "电子"), ("芯片", "电子"), ("电子", "电子"), ("通信", "通信"), ("5G", "通信"),
    ("证券", "非银金融"), ("银行", "银行"), ("保险", "非银金融"), ("房地产", "房地产"),
    ("医药", "医药生物"), ("生物", "医药生物"), ("医疗", "医药生物"), ("创新药", "医药生物"),
    ("新能源", "电力设备"), ("电池", "电力设备"), ("光伏", "电力设备"), ("碳中和", "环保"),
    ("稀土", "有色金属"), ("有色", "有色金属"), ("黄金", "有色金属"), ("钢铁", "钢铁"),
    ("煤炭", "煤炭"), ("化工", "基础化工"), ("材料", "基础化工"), ("军工", "国防军工"),
    ("国防", "国防军工"), ("机械", "机械设备"), ("机器人", "机械设备"), ("汽车", "汽车"),
    ("消费", "食品饮料"), ("食品", "食品饮料"), ("白酒", "食品饮料"), ("农业", "农林牧渔"),
    ("传媒", "传媒"), ("游戏", "传媒"), ("计算机", "计算机"), ("软件", "计算机"),
    ("人工智能", "计算机"), ("数据", "计算机"), ("云计算", "计算机"), ("电力", "公用事业"),
    ("家电", "家用电器"), ("纺织", "纺织服饰"), ("港股", "综合"), ("纳指", "综合"),
    ("标普", "综合"), ("中证", "综合"), ("沪深300", "综合"), ("上证", "综合"), ("MSCI", "综合"),
    ("红利", "综合"), ("价值", "综合"), ("质量", "综合"), ("成长", "综合"), ("宽基", "综合"),
    ("全指", "综合"), ("深证", "综合"), ("创业板", "综合"), ("科创", "综合"), ("500", "综合"),
    ("1000", "综合"), ("2000", "综合"),
]

def etf_ind(name):
    for kw, ind in ETF_IND_KEY:
        if kw in name:
            return ind
    return "综合"


def ind_by_name(nm):
    """按名称关键词归具体行业（2026-08-19：基金不再一律「综合」；识别不出才落综合）"""
    if not nm:
        return "综合"
    F = [
        ("QDII", "海外股票"), ("全球", "海外股票"), ("海外", "海外股票"), ("纳指", "海外科技"),
        ("港股", "港股"), ("恒生", "港股"),
        ("医药", "医药生物"), ("生物", "医药生物"), ("医疗", "医药生物"), ("创新药", "医药生物"),
        ("半导体", "电子"), ("芯片", "电子"), ("电子", "电子"), ("光电", "电子"), ("科技", "电子"), ("信息", "电子"),
        ("通信", "通信"), ("5G", "通信"),
        ("计算机", "计算机"), ("软件", "计算机"), ("数据", "计算机"), ("人工智能", "计算机"),
        ("新能源", "电力设备"), ("光伏", "电力设备"), ("锂", "电力设备"), ("储能", "电力设备"), ("电池", "电力设备"),
        ("军工", "国防军工"), ("国防", "国防军工"), ("航天", "国防军工"),
        ("机械", "机械设备"), ("装备", "机械设备"), ("机器人", "机械设备"),
        ("汽车", "汽车"), ("电动", "汽车"),
        ("化工", "基础化工"), ("材料", "基础化工"), ("新材料", "基础化工"),
        ("有色金属", "有色金属"), ("有色", "有色金属"), ("稀土", "有色金属"),
        ("煤炭", "煤炭"), ("能源", "煤炭"),
        ("消费", "食品饮料"), ("食品", "食品饮料"), ("白酒", "食品饮料"), ("饮料", "食品饮料"),
        ("家电", "家用电器"), ("农业", "农林牧渔"), ("养殖", "农林牧渔"),
        ("银行", "银行"), ("证券", "非银金融"), ("保险", "非银金融"), ("金融", "非银金融"),
        ("地产", "房地产"), ("环保", "环保"), ("公用", "环保"), ("水务", "环保"),
        ("传媒", "传媒"), ("游戏", "传媒"), ("互联网", "传媒"),
        ("纺织", "纺织服饰"), ("服装", "纺织服饰"),
        ("电商", "商贸零售"), ("零售", "商贸零售"), ("商业", "商贸零售"),
        ("旅游", "社会服务"), ("酒店", "社会服务"), ("服务", "社会服务"),
        ("钢铁", "钢铁"), ("建筑", "建筑装饰"), ("建材", "建筑材料"),
        ("均衡", "均衡配置"), ("灵活", "均衡配置"), ("混", "均衡配置"), ("成长", "成长风格"),
        ("价值", "价值龙头"), ("蓝筹", "蓝筹价值"), ("国企", "国企改革"), ("改革", "国企改革"),
        ("量化", "量化优选"), ("龙头", "价值龙头"), ("产业", "新兴成长"), ("新兴", "新兴成长"),
    ]
    for kw, ind in F:
        if kw in nm:
            return ind
    return "综合"

# 短线池股票行业映射（申万一级；Top10 常见标的补全）
STK_IND = {
    "002033": "社会服务", "002636": "电子", "601890": "国防军工", "000768": "国防军工",
    "300388": "环保", "002030": "医药生物", "600251": "农林牧渔", "600261": "家用电器",
    "000850": "纺织服饰", "600397": "国防军工", "600353": "电子", "300814": "电子",
    "603083": "通信", "688143": "通信", "603186": "电子", "603078": "电子",
    "601208": "基础化工", "603989": "电子", "603773": "电子", "300903": "电子",
    "301328": "电子", "300907": "机械设备", "300985": "汽车", "301373": "环保",
    "301396": "计算机", "301018": "家用电器", "300489": "电子", "300566": "电子",
    "688300": "电子", "688432": "电子", "688530": "电子", "688392": "机械设备",
    "688020": "电子", "688519": "电子", "688167": "机械设备",
    # 2026-08-18 补全（Wind 主营档案 / 申万一级；此前 fallback「综合」导致板块无法辨识）
    "002556": "农林牧渔",   # 辉隆股份：化肥/农药农资分销（农业综合）
    "601952": "农林牧渔",   # 苏垦农发：稻麦种植/大米/食用油
    "600168": "环保",       # 武汉控股：污水处理/供水（水务及水治理）
    "601156": "交通运输",   # 东航物流：航空速运/跨境电商物流
    "601099": "非银金融",   # 太平洋：证券（券商经纪/资管/投行）
    "600523": "汽车",       # 贵航股份：汽车零部件（雨刮/散热器/车锁）
    "600081": "汽车",       # 东风科技：汽车零部件（仪表/制动/汽车电子）
    "600817": "环保",       # 宇通重工：环卫设备/工程机械（环保设备）
    "300012": "社会服务",   # 华测检测：第三方检测认证
    "300375": "汽车",       # 鹏翎股份：汽车橡胶管路/密封件
    "603858": "医药生物",   # 步长制药：心脑血管中成药（中药）
}

def board_of(code):
    if code.startswith(("sh60", "sz00", "sz002")):
        return "主板"
    if code.startswith("sz30"):
        return "创业板"
    if code.startswith(("sh688", "sh689")):
        return "科创板"
    if code.startswith(("sh5", "sz1")):
        return "ETF"
    return "基金"

def comp_short(r, board):
    """短线六类（雷达）：趋势=MA2多头 / 动能=mom20 / 量能=vr5 / 超买=RSI反 / 风控=低波 / 研报=0"""
    def clip(x, lo, hi):
        return max(lo, min(hi, x))
    trend = 100 * (1 if (not np.isnan(r.get("ma2", np.nan)) and r["close"] > r["ma2"]) else 0)
    mom = r["mom20"] if not np.isnan(r["mom20"]) else 0
    if board == "股票":
        mom = -mom  # 反转版
    momentum = clip(50 + mom * 300, 5, 100)
    vr = r["vr5"] if not np.isnan(r["vr5"]) else 1.0
    volume = clip(50 + (vr - 1) * 80, 5, 100)
    rsi = r.get("rsi")
    osc = clip(100 - (rsi - 50) * 2, 5, 100) if rsi is not None and not np.isnan(rsi) else 50
    vol = r["vol20"] if not np.isnan(r["vol20"]) else 0.5
    risk = clip(100 - (vol - 0.2) / 0.6 * 100, 5, 100)
    return {"trend": round(trend, 1), "momentum": round(momentum, 1), "volume": round(volume, 1),
            "osc": round(osc, 1), "risk": round(risk, 1), "news": 0.0}

def svg_radar(comp, score, size=120):
    """六角雷达（与模板一致）"""
    cx = cy = size / 2
    R = size * 0.36
    cats = ["trend", "momentum", "volume", "osc", "risk", "news"]
    labels = ["趋势", "动能", "量能", "超买", "风控", "研报"]
    angles = [math.radians(i * 60 - 90) for i in range(6)]
    def pt(r, ang):
        return (cx + r * math.cos(ang), cy + r * math.sin(ang))
    parts = []
    for ring in [0.25, 0.5, 0.75, 1.0]:
        pts = " ".join(f"{pt(R*ring, a)[0]:.1f},{pt(R*ring, a)[1]:.1f}" for a in angles)
        parts.append(f'<polygon points="{pts}" fill="none" style="stroke:var(--radar-ring)" stroke-width="1"/>')
    for a in angles:
        x0, y0 = pt(0, a); x1, y1 = pt(R, a)
        parts.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" style="stroke:var(--radar-ring)" stroke-width="1"/>')
    col = "var(--radar-good)" if score >= 60 else ("var(--radar-warn)" if score >= 45 else "var(--radar-bad)")
    vals = [comp.get(c, 0) for c in cats]
    pts = " ".join(f"{pt(R*max(3, min(100, v))/100, angles[i])[0]:.1f},{pt(R*max(3, min(100, v))/100, angles[i])[1]:.1f}" for i, v in enumerate(vals))
    parts.append(f'<polygon points="{pts}" fill="{col}" fill-opacity="0.18" stroke="{col}" stroke-width="1.5"/>')
    for i, v in enumerate(vals):
        xr, yr = pt(R * max(3, min(100, v)) / 100, angles[i])
        parts.append(f'<circle cx="{xr:.1f}" cy="{yr:.1f}" r="2.5" fill="{col}"/>')
        lx, ly = pt(R * 1.42, angles[i])
        dy = 4 if i == 0 else (-2 if i == 3 else 3)
        parts.append(f'<text x="{lx:.1f}" y="{ly + dy:.1f}" style="fill:var(--radar-label)" font-size="9" text-anchor="middle" font-weight="600">{labels[i]}</text>')
    return (f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" style="flex:0 0 auto">'
            + "".join(parts) + f'<text x="{cx}" y="{cy + 4}" style="fill:{col}" font-size="15" font-weight="700" text-anchor="middle">{score:.0f}</text></svg>')

def tier_of(sc):
    if sc >= 75: return "满仓加仓"
    if sc >= 60: return "轻仓加仓"
    if sc >= 45: return "观望"
    if sc >= 30: return "减至半仓"
    return "清仓"

def buy_tier(sc, board=None):
    """短线买入口径（信号池专用）：基金 S30 / 股票 S55 即买 → 两态买入档
    2026-08-31 生产接入：门槛随资产类型（基金 S30 / 股票 S55），避免分 30-49 基金入池却显示「不买」"""
    if sc >= 60: return "强买入"
    if board == "基金":
        return "买入" if sc >= FUND_SCORE_MIN else "不买"
    return "买入" if sc >= STOCK_SCORE_MIN else "不买"

# ⚠ 2026-08-31 生产接入（修正引擎 T+1 口径最优配置）：
#   基金 = pathA T10/H10/S30 slip5（唯一过四闸，+241.2%/夏普0.872/胜率55.4%）→ 门槛 S50→S30
#   股票 = T10/H15/S55 反转纯轮动（72 组唯一正收益 +23.42%，实验口径未过四闸）→ 门槛 S50→S55
STOCK_SCORE_MIN = 55
FUND_SCORE_MIN = 30

# ⚠ 2026-09-01 生产接入 v2（regime 感知，修正引擎 T+1 口径网格最优）：
#   股票 H6 三态（强弱阈值 0.02）：强牛=基线权重 S55 / 弱牛=防守权重(20,20,30,30) S55 / 熊=清仓
#     → 夏普 0.406→0.641、收益 73.86%→149.27%、回撤 -40.03%→-28.29%、胜率 45.8%→52.1%
#   基金 FB3 牛熊（熊市极防守 T3S45 低波开仓，非清仓）：
#     牛=动量重(40,0,30,30) S30 Top10 / 熊=低波重(25,0,30,45) S45 Top3
#     → 夏普 0.867→1.247（破 1.0 达成用户目标）、收益 243.84%→642.13%、胜率 55.0%→56.4%、9/11 年正
#   ⚠ 基金熊市开仓与股票相反（股票熊市开仓 -64% 回撤灾难，基金熊市防守开仓 +398pp 增益）——
#     机制：基金池熊市 T3S45 低波选中的是避险型基金（债/红利/货币），吃到避险行情
STOCK_SCORE_MIN = 55
FUND_SCORE_MIN = 30
# ⚠ 2026-09-01 多策略命中回避（用户拍板「做回避」）：
#   回测（backtest/multi_strategy_resonance_0901.py，20 策略 M1-M20，成本 1.15% 已扣）：
#     命中数≥3 组收益单调恶化（H10 hit1 均值 -0.59% → hit9 -1.63%），多策略共振过度 = 反向信号
#   → 生产引擎：股票命中≥3 剔除出买入池（不参与 Top10 排序）。默认开启，可置 False 关闭。
#   注：仅作用于股票买入池；基金（净值数据）与跟踪池卖出信号不受影响。
ENABLE_HIT_AVOID = True
HIT_AVOID_THRESHOLD = 3

# H6 三态：沪深300 20d 动量 > 0.02 = 强牛（进攻权重），≤ 0.02 且 >MA20 = 弱牛（防守权重）
IDX_MOM20_STRONG = 0.02
ENABLE_F3 = False  # 9/1 裁决：F3 缩量企稳为增强候选，验证门前默认关闭（恢复双创信号可比性）
STOCK_W_STRONG = (30, 25, 25, 20)   # 强牛：基线权重
STOCK_W_WEAK = (20, 20, 30, 30)     # 弱牛：防守权重（回撤 -30.7% vs 基线 -40.03%，胜率 +6.1pp）
# FB3 基金牛熊：牛=动量重(40,0,30,30) / 熊=低波重(25,0,30,45)
FUND_W_BULL = (40, 0, 30, 30)       # 牛：动量重（量价退化，0 权重）
FUND_W_BEAR = (25, 0, 30, 45)       # 熊：低波重（避险型基金优先）
FUND_S_BEAR = 45                    # 熊：更严门槛 S45
FUND_TOP_BEAR = 3                   # 熊：更少标的 Top3

def _buyable(d):
    """可买入判定（跟踪池/回溯/历史补偿共用）：股票 S55 / 基金 S30（2026-08-31 对齐最优配置）"""
    sc = d.get("short_score") or 0
    if d.get("board") == "基金":
        return sc >= FUND_SCORE_MIN
    return sc >= STOCK_SCORE_MIN

def rsi14(close):
    d = close.diff()
    up = d.clip(lower=0).rolling(14).mean()
    dn = (-d.clip(upper=0)).rolling(14).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def _hit_count(ddf, as_of=None, mkt_med_pct=None):
    """单只股票在信号日的 20 策略命中数（2026-09-01 命中回避用）。
    信号定义复刻 backtest/multi_strategy_resonance_0901.py（M1-M20，逐条一致）；
    该文件是模块级执行脚本（import 即跑全量回测），不能 import，故在此内联。
    mkt_med_pct = 信号日全市场涨跌幅中位数（S1 跨截面条件；None 时该条件视为不满足）。
    命中≥3 = 多策略共振过度（回测收益单调恶化）→ 生产引擎反向过滤（回避）。"""
    df = ddf.loc[:as_of] if as_of is not None else ddf
    if len(df) < 60:
        return 0
    close = df["close"]; openp = df["open"]; high = df["high"]; low = df["low"]
    volume = df["volume"]; amount = df["amount"]
    def _ma(x, n): return x.rolling(n, min_periods=n).mean()
    ma5 = _ma(close, 5); ma10 = _ma(close, 10); ma20 = _ma(close, 20)
    ma30 = _ma(close, 30); ma40 = _ma(close, 40); ma60 = _ma(close, 60)
    vol_ma5 = _ma(volume, 5); vol_ma20 = _ma(volume, 20)
    vol_ratio = volume / vol_ma5
    pct = close.pct_change() * 100
    amplitude = (high - low) / close.shift(1) * 100
    atr10 = pct.abs().rolling(10, min_periods=10).mean()
    high60 = high.rolling(60, min_periods=60).max()
    low60 = low.rolling(60, min_periods=60).min()
    high10 = high.rolling(10, min_periods=10).max()
    low10 = low.rolling(10, min_periods=10).min()
    drawdown60 = (close - high60) / high60 * 100
    def _rsi(x, n=6):
        diff = x.diff()
        gain = diff.clip(lower=0); loss = -diff.clip(upper=0)
        ag = gain.rolling(n, min_periods=n).mean(); al = loss.rolling(n, min_periods=n).mean()
        rs = ag / al.replace(0, np.nan)
        return (100 - 100 / (1 + rs)).fillna(100)
    rsi6 = _rsi(close, 6)
    def _ema(x, n): return x.ewm(span=n, adjust=False).mean()
    ema12 = _ema(close, 12); ema26 = _ema(close, 26)
    dif = ema12 - ema26; dea = _ema(dif, 9)
    low9 = low.rolling(9, min_periods=9).min(); high9 = high.rolling(9, min_periods=9).max()
    rsv = (close - low9) / (high9 - low9).replace(0, np.nan) * 100
    k = rsv.ewm(com=2, adjust=False).mean(); d = k.ewm(com=2, adjust=False).mean(); j = 3 * k - 2 * d
    boll_mid = _ma(close, 20); boll_std = close.rolling(20, min_periods=20).std()
    boll_up = boll_mid + 2 * boll_std; boll_low = boll_mid - 2 * boll_std
    ret5 = close.pct_change(5) * 100; ret60 = close.pct_change(60) * 100
    amt_2e = amount >= 2e8
    listed_days = close.notna().cumsum()
    i = -1
    def _v(s):
        v = s.iloc[i]
        return bool(v) if not pd.isna(v) else False
    hits = 0
    # M1 海龟60日新高
    if _v(close >= high60): hits += 1
    # M2 平台突破
    breakthrough = (close >= ma60) & (ma60 > openp) & (pct >= 2) & (close > openp) & (vol_ratio >= 2) & amt_2e
    breakthrough_any = breakthrough.rolling(60, min_periods=1).max().astype(bool)
    dev = (ma60 - close) / ma60
    dev_ok = (dev > -0.05) & (dev < 0.20)
    dev_ok_60 = dev_ok.rolling(60, min_periods=1).min().astype(bool)
    if _v(breakthrough_any & dev_ok_60): hits += 1
    # M3 持续上涨
    ma30_0 = ma30.shift(30); ma30_10 = ma30.shift(20); ma30_20 = ma30.shift(10)
    if _v((ma30_0 < ma30_20) & (ma30_20 < ma30_10) & (ma30_10 < ma30) & (ma30 > 1.2 * ma30_0)): hits += 1
    # M4 低ATR成长
    if _v((listed_days >= 250) & (high10 / low10 > 1.1) & (atr10 <= 10)): hits += 1
    # M5 放量跌停
    if _v((pct <= -9.5) & amt_2e & (vol_ratio >= 4)): hits += 1
    # M6 放量上涨
    if _v((pct >= 2) & (close > openp) & amt_2e & (vol_ratio >= 2)): hits += 1
    # S1 8步选股法简化
    vol_ladder = (volume.shift(4) <= volume.shift(3)) & (volume.shift(3) <= volume.shift(2)) & (volume.shift(2) <= volume.shift(1)) & (volume.shift(1) <= volume)
    ma_rising = (ma5 > ma5.shift(1)) & (ma10 > ma10.shift(1)) & (ma20 > ma20.shift(1))
    ma_bull = (ma5 > ma10) & (ma10 > ma20) & (close > ma20)
    _med_ok = (pct > mkt_med_pct) if mkt_med_pct is not None else False
    if _v((pct >= 3) & (pct <= 5) & (vol_ratio > 1) & vol_ladder & ma_bull & ma_rising & _med_ok): hits += 1
    # Y2 高成长动量简化
    if _v((pct >= 2) & (pct <= 9.9) & (vol_ratio >= 1.5)): hits += 1
    # Y5 放量突破
    if _v((vol_ratio >= 2.0) & (pct >= 1) & (pct <= 7) & (amplitude >= 3)): hits += 1
    # Q3 60日箱体突破
    box_range = (high60 - low60) / low60 * 100
    box_pos = (close - low60) / (high60 - low60).replace(0, np.nan)
    if _v((box_range <= 25) & (box_pos >= 0.90) & (vol_ratio >= 1.8) & (close > ma20) & (ret5 <= 15)): hits += 1
    # Q4 大跌回撤磨底反转
    vol5 = volume.rolling(5, min_periods=5).mean()
    vol_5_20 = vol5 / vol_ma20
    dist_ma20 = (close - ma20) / ma20 * 100
    if _v((drawdown60 <= -25) & (amplitude.rolling(5, min_periods=5).mean() <= 3.5) & (vol_5_20 <= 0.7) & (dist_ma20.abs() <= 5) & (pct >= 1) & (pct <= 5) & (vol_ratio >= 1.2) & (vol_ratio <= 3.0)): hits += 1
    # Q5 主力悄悄吸筹简化
    ma_not_aligned = ~((ma20 > ma40) & (ma40 > ma60))
    if _v((ret5 >= -4) & (ret5 <= 4) & (vol_ratio >= 0.6) & (vol_ratio <= 1.8) & (pct >= -3) & (pct <= 4) & (dist_ma20.abs() <= 6) & ma_not_aligned): hits += 1
    # D1 MA金叉
    if _v((ma5 > ma10) & (ma5.shift(1) <= ma10.shift(1))): hits += 1
    # D2 MACD金叉
    if _v((dif > dea) & (dif.shift(1) <= dea.shift(1))): hits += 1
    # D3 RSI超卖
    if _v((rsi6 < 30) & (rsi6.shift(1) >= 30)): hits += 1
    # D4 放量突破
    if _v((vol_ratio > 2.0) & (pct > 3)): hits += 1
    # D5 布林反弹
    if _v((low <= boll_low) & (close > boll_low)): hits += 1
    # D6 KDJ金叉
    if _v((j > k) & (j.shift(1) <= k.shift(1))): hits += 1
    # D7 多指标共振
    if _v((ma5 > ma10) & (dif > dea) & (vol_ratio > 1.2) & (pct > 0)): hits += 1
    return hits

def calc_signals(as_of=None):
    """计算短线信号池（as_of=指定信号日，默认最新交易日）；返回 (out, sigs)，不写文件"""
    t0 = __import__("time").time()
    fnames = fund_names()
    print(f"基金名 {len(fnames)} 只 ({time.time()-t0:.0f}s)", flush=True)
    global sig_stock, sig_etf, sig_fund
    sig_stock, sig_etf, sig_fund = {}, {}, {}

    # 0) 市况门控（2026-08-19 接入实盘，与回测口径一致）：沪深300 > MA20 才开新仓；
    #    门控关闭时清空股票买入信号（不进新仓），基金池不受门控（与回测引擎 use_market 一致）。
    _idx = S.V.load_index(20)
    _idx = _idx.set_index("date")
    _gate_day = pd.Timestamp(as_of) if as_of is not None else _idx.index[-1]
    _in_mkt = bool(_idx.loc[:_gate_day]["in_market"].iloc[-1]) if _gate_day in _idx.index else True
    _idx_last = _idx.loc[:_gate_day]
    _gate_close = float(_idx_last["close"].iloc[-1]) if len(_idx_last) else None
    _gate_ma = float(_idx_last["ma"].iloc[-1]) if len(_idx_last) else None
    market_gate = {"open": _in_mkt, "as_of": str(_gate_day.date()),
                   "idx_close": round(_gate_close, 2) if _gate_close else None,
                   "idx_ma20": round(_gate_ma, 2) if _gate_ma else None}
    print(f"市况门控(沪深300>MA20): {'✅ 开' if _in_mkt else '❌ 关（不开新仓，池内走卖出信号）'} 收盘{_gate_close:.0f} vs MA20 {_gate_ma:.0f} ({time.time()-t0:.0f}s)", flush=True)

    # 1) 股票反转：按权限分层各取 Top10（主板/创业板/科创板，2026-08-17 用户决策）
    stock_pool = S.load_stock_pool()
    # 2026-08-27 修复：全市场最新交易日基准（停牌股新鲜度校验用）。
    # 002274 华昌化工 08-26 起停牌，as_of=None 时 iloc[-1] 会取 08-25 旧数据评分入池（65.2 强买入），
    # 看板显示旧价格误导。load_stock_pool 的 10 自然日阈值只挡「死数据」，挡不住短期停牌股。
    _mkt_max = max(df.index[-1] for df in stock_pool.values()) if stock_pool else None
    rows_by_board = {"主板": [], "创业板": [], "科创板": []}
    def _is_suspended(_ddf, _r):
        """停牌判定（2026-09-01 修复）：除「日期落后 >1 自然日」外，补「最新行零成交/零价」判定。
        背景：002274 华昌化工 08-26 起停牌，但 data_full/sz002274.csv 被塞了一行假的 08-31 全零行
        （open/high/low/volume 全为 0，close=6.47 复用旧收盘），导致其 index[-1]=08-31 与 _mkt_max 相等、
        diff_days=0 → 旧的「>1 天新鲜度」判定永不触发，华昌该标停牌却漏标。零行（无成交量、开盘=0）
        即代表当日无成交、处于停牌/未复牌状态，须标记 suspended。
        注意：不能只用 close<=0 判定——停牌序列常见「close 沿用上一交易日」，故以 volume==0 为主判据，
        辅以 open/low/high==0 兜底（部分源数据缺失成交量时用价格方判）。"""
        try:
            _last = _ddf.iloc[-1]
            _vol = _last.get("volume")
            _opn = _last.get("open")
            _lohi = _last.get("high", _last.get("low"))
            # 零成交量（primary）或 开/高/低 全为 0（辅）→ 当日无实质成交
            if _vol is not None and float(_vol) == 0:
                return True
            if _opn is not None and float(_opn) == 0:
                return True
            if _lohi is not None and float(_lohi) == 0:
                return True
        except Exception:
            pass
        # 日期落后全市场最新交易日 >1 自然日（原逻辑保留）
        if _mkt_max is not None and (_mkt_max - _ddf.index[-1]).days > 1:
            return True
        return False
    def _susp_sig(_code, _ddf, _r):
        """停牌股信号数据（suspended 标记，供跟踪池渲染；不参与买入信号池）。
        2026-08-27 用户反馈：持仓股（如 002274 华昌化工）停牌期间仍需跟踪卖出信号，
        删除跟踪池=过度修复；标记 suspended，前端显示「⏸ 停牌·复牌后跟踪」。"""
        _nm = NAMES.get(_code, _code[-6:])
        if "ST" in _nm or _nm.startswith("S") or "退" in _nm or _r["close"] <= 1.5:
            return
        _sc = S.short_score(_r, reversal=True, weights=STOCK_W_WEAK, mask=(1, 1, 1, 1))
        if pd.isna(_sc):
            return
        sig_stock[_code[-6:]] = {"name": _nm, "px": round(float(_r["close"]), 2),
                                  "chg": round(float(_r["close"] / _ddf["close"].iloc[-2] - 1) * 100, 2),
                                  "score": round(float(_sc), 1), "tier": "停牌",
                                  "ma5_above": None, "suspended": True,
                                  "suspend_since": str(_ddf.index[-1].date())}

    # 2026-09-01 H6 三态：沪深300 20d 动量 > 0.02 = 强牛（进攻权重）/ ≤0.02 且 >MA20 = 弱牛（防守权重）
    # 回测（修正引擎 T+1，F3 过滤）：夏普 0.406→0.641、收益 73.86%→149.27%、回撤 -40.03%→-28.29%、胜率 45.8%→52.1%
    _idx_m20 = float(_idx.loc[:_gate_day]["close"].iloc[-1] / _idx.loc[:_gate_day]["close"].iloc[-21] - 1) \
        if len(_idx.loc[:_gate_day]) >= 21 else 0.0
    _stk_strong = _in_mkt and _idx_m20 > IDX_MOM20_STRONG
    _stk_w = STOCK_W_STRONG if _stk_strong else STOCK_W_WEAK
    print(f"股票 regime: {'强牛' if _stk_strong else ('弱牛' if _in_mkt else '熊市清仓')} (idx mom20={_idx_m20*100:.1f}%) 权重{_stk_w}", flush=True)

    # 2026-09-01 多策略命中回避：S1 需信号日全市场涨跌幅中位数（跨截面，与回测 market_med 口径一致）
    _mkt_med_pct = None
    if ENABLE_HIT_AVOID:
        _pct_list = []
        for _c, _ddf in stock_pool.items():
            if len(_ddf) < 2:
                continue
            if as_of is not None:
                _sub = _ddf.loc[:as_of]
                if len(_sub) < 2:
                    continue
                _pct_list.append(float(_sub["close"].iloc[-1] / _sub["close"].iloc[-2] - 1) * 100)
            else:
                _pct_list.append(float(_ddf["close"].iloc[-1] / _ddf["close"].iloc[-2] - 1) * 100)
        _mkt_med_pct = float(np.median(_pct_list)) if _pct_list else None
        print(f"命中回避: 信号日全市场涨跌幅中位数 {_mkt_med_pct:.2f}% (n={len(_pct_list)})", flush=True)

    _hit_avoided = 0

    for code, ddf in stock_pool.items():
        if as_of is not None:
            if as_of not in ddf.index:
                # 2026-08-27 修复：as_of 分支停牌股同样保留信号数据（供跟踪池渲染）。
                # 002274 华昌化工 08-26 起停牌，as_of=08-27 时无当日数据被 continue 跳过，
                # 但持仓股停牌期间仍需跟踪卖出信号 → 标记 suspended 供前端显示「停牌·复牌后跟踪」。
                # 2026-09-01 修复：改用 _is_suspended（日期落后 OR 零量/零价），避免零量假行漏标。
                if _is_suspended(ddf, ddf.iloc[-1]):
                    _susp_sig(code, ddf, ddf.iloc[-1])
                continue
            r = ddf.loc[as_of]
        else:
            r = ddf.iloc[-1]
            # 2026-08-27 修复：停牌股新鲜度校验——数据日期落后全市场最新交易日 >1 自然日则跳过
            # （停牌股不可交易，短线信号无意义；正常标的当日回填滞后 ≤1 日不受影响）
            # 2026-09-01 修复：改用 _is_suspended（日期落后 OR 零量/零价），零量假行（002274 08-31）不漏标。
            if _is_suspended(ddf, r):
                _susp_sig(code, ddf, r)
                continue
        if pd.isna(r["close"]) or r["close"] <= 0 or pd.isna(r["mom20"]):
            continue
        nm = NAMES.get(code, code[-6:])
        if "ST" in nm or nm.startswith("S") or "退" in nm:
            continue
        if r["close"] < 1.5:   # 退市股/仙股过滤
            continue
        # 2026-08-25 方案A（用户拍板）：流动性硬过滤——20日均成交额 < 3000万 剔除
        # 回测验证（short_engine.run_short reversal=True，T10_H10_S50）：min_amt 2e6→3e7
        #   收益 Δ+13.45pct、夏普 Δ+0.087、胜率 +0.7pct；稳健性 3 组参数 2/3 显著正、5e7 档 3/3 正。
        # 单日放量冲榜但平时流动性差的标的（如 605158 amt20 仅 141 万）不再入池。
        if pd.isna(r.get("amt20", np.nan)) or r["amt20"] < 3e7:
            continue
        # 2026-08-31 剪藏因子 F3 缩量企稳（Obsidian 剪藏「李韩薇短线低吸」+「龙回头」提炼）：
        #   V < MA(V,5) 且 MA(V,5) < MA(V,10) —— 缩量企稳后放量启动
        #   回测 A/B（修正引擎 T+1）：股票反转基线 +23.42%/夏普0.216 → F3 +129.02%/夏普0.57/回撤-29.22%
        #   ⚠ 实验口径：年化 8.12% 未达四闸 10% 门槛，登记增强候选，模拟盘验证门通过前不改生产权重
        #   ⚠ 9/1 归因裁决：硬编码生产路径导致创业板 8→0 / 科创板 1→0 信号清零（线上对照 10/10/10），
        #     与注释「验证门前不改生产」意图冲突 → 改为 ENABLE_F3=False 默认关闭（恢复双创可比性）；
        #     验证门通过后置 True 重新启用。8/31 审计：修正引擎下短线股票整体无正收益配置，
        #     双创清零会进一步剥夺观察样本，关闭 F3 不影响已过闸结论（该结论本身即负）。
        if ENABLE_F3:
            if pd.isna(r.get("vma5", np.nan)) or pd.isna(r.get("vma10", np.nan)) \
               or not (r["volume"] < r["vma5"] and r["vma5"] < r["vma10"]):
                continue
        sc = S.short_score(r, reversal=True, weights=_stk_w, mask=(1, 1, 1, 1))
        if pd.isna(sc):
            continue
        bd = board_of(code)
        if bd not in rows_by_board:
            continue
        # 2026-09-01 多策略命中回避：命中≥3 剔除（回测：命中数≥3 收益单调恶化，共振过度=反向信号）。
        # 仅对 sc≥55 候选计算（sc<55 本就不入池，避免全市场 5000+ 只的指标计算开销）。
        if ENABLE_HIT_AVOID and float(sc) >= STOCK_SCORE_MIN:
            _hc = _hit_count(ddf, as_of, _mkt_med_pct)
            if _hc >= HIT_AVOID_THRESHOLD:
                _hit_avoided += 1
                continue
        rows_by_board[bd].append((code, float(sc), r, ddf))
        _tail2 = ddf.loc[:as_of] if as_of is not None else ddf
        sig_stock[code[-6:]] = {"name": nm, "px": round(float(r["close"]), 2),
                                "chg": round(float(r["close"] / (_tail2["close"].iloc[-2] if as_of else ddf["close"].iloc[-2]) - 1) * 100, 2),
                                "score": round(float(sc), 1), "tier": tier_of(float(sc)),
                                "ma5_above": bool(not pd.isna(r.get("ma5", np.nan)) and r["close"] > r["ma5"])}
    for bd in ("主板", "创业板", "科创板"):
        rows_by_board[bd].sort(key=lambda kv: -kv[1])
        # 2026-08-17 用户决策：只保留买入信号（分≥50），不足 10 只不凑数；超 10 只封顶 Top10
        # 2026-08-20 用户决策：市况门控改为「仅提醒」——门控关闭不再清空股票池，
        #   权重分≥50 照常入池展示（仅供参考，非买入指令），由前端标题横幅提醒。
        # 2026-08-31 生产接入：门槛 S50→S55（对齐修正引擎唯一正收益配置 T10/H15/S55 反转）
        rows_by_board[bd] = [kv for kv in rows_by_board[bd] if kv[1] >= STOCK_SCORE_MIN][:10]
        print(f"股票[{bd}] 买入信号 {len(rows_by_board[bd])} 只（分≥{STOCK_SCORE_MIN}，不凑数）({time.time()-t0:.0f}s)", flush=True)
    if ENABLE_HIT_AVOID and _hit_avoided:
        print(f"命中回避: 剔除命中≥{HIT_AVOID_THRESHOLD} 的股票 {_hit_avoided} 只（多策略共振过度，反向过滤）", flush=True)
    stock_top_main = rows_by_board["主板"]
    stock_top_gem  = rows_by_board["创业板"]
    stock_top_star = rows_by_board["科创板"]
    stock_top = stock_top_main + stock_top_gem + stock_top_star

    # 2) ETF 动量 Top10（2026-08-17 用户决策移除：ETF 表现不佳，短线池去 ETF）
    etf_top = []

    # 3) 基金动量 Top10（2026-09-01 FB3 牛熊 regime：牛=动量重 S30 Top10 / 熊=低波重 S45 Top3）
    # 回测（修正引擎 T+1，slip5）：牛动量+熊极防守 → 夏普 1.247（破 1.0）/收益 642.13%/胜率 56.4%/9/11 年正
    #   vs 生产基线（熊清仓）夏普 0.867/243.84% —— 基金熊市防守开仓 +398pp 增益（股票相反，熊市清仓）
    fund_pool = S.load_fund_pool(3000)
    frows = []
    _fw = FUND_W_BULL if _in_mkt else FUND_W_BEAR
    _fsmin = FUND_SCORE_MIN if _in_mkt else FUND_S_BEAR
    for code, ddf in fund_pool.items():
        if as_of is not None:
            # 2026-08-27 修复：基金净值 T+1 公布（as_of=最新交易日时净值只到 T-1），
            # 严格 loc[as_of] 会全跳过致基金池 0 只；改取 as_of 前最近一天（与 _tail2 口径一致）
            _sub = ddf.loc[:as_of]
            if len(_sub) == 0:
                continue
            r = _sub.iloc[-1]
        else:
            r = ddf.iloc[-1]
        if pd.isna(r["close"]) or r["close"] <= 0 or pd.isna(r["mom20"]):
            continue
        sc = S.short_score(r, reversal=False, weights=_fw, mask=(1, 1, 1, 1))
        if pd.isna(sc):
            continue
        frows.append((code, float(sc), r, ddf))
        _tail2 = ddf.loc[:as_of] if as_of is not None else ddf
        sig_fund[code[-6:]] = {"name": fnames.get(code[-6:], code[-6:]), "px": round(float(r["close"]), 4),
                               "chg": round(float(r["close"] / (_tail2["close"].iloc[-2] if as_of else ddf["close"].iloc[-2]) - 1) * 100, 2),
                               "score": round(float(sc), 1), "tier": tier_of(float(sc)),
                               "ma5_above": bool(not pd.isna(r.get("ma5", np.nan)) and r["close"] > r["ma5"])}
    frows.sort(key=lambda kv: -kv[1])
    # 2026-08-17 用户决策：基金同样只保留买入信号（分≥50），不凑数
    # 2026-08-31 生产接入：门槛 S50→S30（对齐 pathA 最优 T10/H10/S30 slip5，唯一过四闸）
    # 2026-09-01 FB3：牛市 S30 Top10 / 熊市 S45 Top3（极防守，低波重）
    _ftop = FUND_TOP_BEAR if not _in_mkt else 10
    fund_top = [kv for kv in frows if kv[1] >= _fsmin][:_ftop]
    print(f"基金池 买入信号 {len(fund_top)} 只（{'牛' if _in_mkt else '熊'}: 分≥{_fsmin} Top{_ftop}，权重{_fw}，不凑数）({time.time()-t0:.0f}s)", flush=True)

    # 详情构建
    details = {}
    for code, sc, r, ddf in stock_top + etf_top + fund_top:
        bare = code[-6:]
        board = board_of(code)
        key = code
        # 名称/行业：优先复用 80 只 details
        ex = EXIST.get(bare)
        if ex:
            name = ex["name"]
            # 2026-08-20：统一行业池（池内已有行业直接采用；落「综合」则用统一池重判）
            industry = ex["industry"] if ex["industry"] not in ("综合", "") else IP.industry_of(bare, name)
        else:
            name = NAMES.get(code, bare)
            if board == "ETF":
                industry = IP.industry_of(bare, name)
            elif board == "基金":
                fnn = fnames.get(bare, NAMES.get(code, bare))
                industry = IP.fund_industry(fnn)   # 2026-08-20：基金用主题/风格（不套申万一级）
                name = fnn
            else:
                industry = IP.industry_of(bare, name)   # 2026-08-20：统一行业池，不再落「综合」
        px = float(r["close"])
        _tail = ddf.loc[:as_of] if as_of is not None else ddf
        chg = float(_tail["close"].iloc[-1] / _tail["close"].iloc[-2] - 1) * 100 if len(_tail) >= 2 else None
        ret_1y = float(px / _tail["close"].iloc[-252] - 1) * 100 if len(_tail) > 252 else None
        rsi = float(rsi14(_tail["close"]).iloc[-1]) if len(_tail) > 20 else None
        comp = comp_short(r, "股票" if board in ("主板", "创业板", "科创板") else board)
        radar = svg_radar(comp, sc)
        details[bare] = {
            "code": bare, "key": key, "name": name, "pool": "short", "perm": "short",
            "board": board, "industry": industry, "biz": "—",
            "px": round(px, 2), "chg": round(chg, 2) if chg is not None else None,
            "ret_1y": round(ret_1y, 1) if ret_1y is not None else None,
            "score": round(sc, 1), "score_prev": None,
            "tier": buy_tier(sc, board), "tier_prev": None,
            "short_score": round(sc, 1), "short_tier": buy_tier(sc, board),
            "factors": {"mom": round(r.get("mom20", 0) * 100, 1) if not pd.isna(r.get("mom20", np.nan)) else None,
                        "vr": round(float(r.get("vr5", 1)), 2) if not pd.isna(r.get("vr5", np.nan)) else None,
                        "trend": comp["trend"], "volume": comp["volume"],
                        "osc": comp["osc"], "risk": comp["risk"]},
            "comp": comp, "radar_svg": radar,
            "rsi": round(rsi, 1) if rsi is not None else None,
            "kline": [], "factor_hist": [], "trades": {"v9_auto": [], "v8_lite": []},
        }
    order = {"主板": [c[-6:] for c, _, _, _ in stock_top_main],
             "创业板": [c[-6:] for c, _, _, _ in stock_top_gem],
             "科创板": [c[-6:] for c, _, _, _ in stock_top_star],
             "基金": [c[-6:] for c, _, _, _ in fund_top]}
    # 2026-08-20 用户决策：市况门控改为「仅提醒」——门控关闭不再清空股票池。
    # 股票标的分≥50 照常入池展示（供参考，非买入指令），打 gate_closed 标记供前端标题/行级提醒；
    # 基金不受门控（不加标记）。跟踪池安全口径「不开新仓·仅跟踪」由下方 ⑤ 保持。
    if not _in_mkt:
        for _c in [c[-6:] for c, _, _, _ in stock_top]:
            if _c in details:
                details[_c]["gate_closed"] = True
        print(f"市况门控关闭：短线股票池 {len(stock_top)} 只标 gate_closed=仅提醒（照常入池供参考，非买入指令；跟踪池走安全口径）", flush=True)
    # 2026-08-17 修复：as_of 取股票数据最新交易日（主口径），基金净值 T-1 单独标注
    _stock_tail = max((ddf.index[-1] for ddf in stock_pool.values() if len(ddf)), default=None)
    _fund_tail = max((ddf.index[-1] for ddf in fund_pool.values() if len(ddf)), default=None)
    _eff = as_of if as_of is not None else (str(_stock_tail.date()) if _stock_tail is not None else "—")
    out = {"as_of": _eff, "fund_as_of": str(_fund_tail.date()) if _fund_tail is not None else _eff,
           "details": details, "tiers": order, "market_gate": market_gate}
    sigs = {"as_of": out["as_of"], "stock": sig_stock, "etf": sig_etf, "fund": sig_fund}
    return out, sigs, stock_pool, fund_pool


def build(as_of=None):
    """计算并写文件（short_pool.js / short_signals.js / short_pool.json）"""
    out, sigs, stock_pool, fund_pool = calc_signals(as_of)
    # ---- 自动跟踪池（2026-08-18 用户需求：与中长线一致，隔日入池 + 三时间）-----
    # 上方表格可买入标的（强买入/买入，分≥50）上榜次日收盘无条件转正式跟踪（30 天后自动移除 exit=entry+30）。
    # ⚠ 2026-08-19 用户拍板：进标的池=默认全买 → 必须跟踪卖出信号 → 隔日无论是否仍在榜一律转正式入池；
    # 新上榜先入 track_pending_short（待确认，不入正式池、不参与信号），下个收盘无条件转正式（entry=确认日）；
    # 每次转正式/重新上榜刷新【入池 entry / 跟踪 last_seen / 出池 exit=entry+30】三时间。
    try:
        _old_full = json.load(open(BASE / "short_pool.json", encoding="utf-8"))
    except Exception:
        _old_full = {}
    old = _old_full.get("track", {}) or {}            # 旧正式池
    old_pending = _old_full.get("track_pending_short", {}) or {}
    today = time.strftime("%Y-%m-%d")
    track = dict(old)                                 # 正式跟踪（已确认 ≥1 个收盘）
    pending = dict(old_pending)                       # 待确认（隔日入池候选）
    def _exit(_e):
        return str((pd.Timestamp(_e) + pd.Timedelta(days=30)).date())
    # 迁移：旧正式池成员补 exit/status/last_seen/type（新字段；pool 兜底推断 type）
    for _c, _rec in list(track.items()):
        _rec.setdefault("exit", _exit(_rec.get("entry", today)))
        _rec.setdefault("status", "active")
        _rec.setdefault("last_seen", _rec.get("last_seen") or today)
        if _rec.get("type") is None:
            _rec["type"] = "fund" if _rec.get("pool") == "基金" else "stock"
    _old_tiers = _old_full.get("tiers", {}) or {}
    _old_codes = {_c for _cs in _old_tiers.values() for _c in _cs}
    _today_codes = {c for c, d in out["details"].items() if _buyable(d)}
    # ① 回溯上次构建的池：昨天在池且可买入、今天掉出的标的，按上次 as_of 补录正式池（用户场景：8/14 第一位 8/17 掉出仍可跟踪）
    for _bd, _codes in _old_tiers.items():
        for _c in _codes:
            if _c not in track and _c not in pending:
                _od = (_old_full.get("details", {}) or {}).get(_c, {})
                if _buyable(_od):
                    _e0 = _old_full.get("as_of") or today
                    track[_c] = {"entry": _e0, "last_seen": _e0, "exit": _exit(_e0), "status": "active",
                                 "pool": _bd, "type": "fund" if _bd == "基金" else "stock"}
    # ② 当前池可买入标的
    for code, d in out["details"].items():
        if not _buyable(d):
            continue
        _bd = d.get("board", "")
        _snap = {"name": d.get("name"), "px": d.get("px"), "chg": d.get("chg"),
                 "score": d.get("short_score"), "tier": d.get("short_tier") or d.get("tier"),
                 "pool": _bd, "type": "fund" if _bd == "基金" else "stock", "date": today}
        rec = track.get(code)
        if rec is not None:
            # 已在正式池：持续在池 → 保持 entry，仅刷新 last_seen（若本次是重新上榜即上次不在池 → 刷新入口）
            if code not in _old_codes:
                rec["entry"] = today                   # 重新上榜：重新计时 30 天
                rec["exit"] = _exit(today)
            rec["last_seen"] = today
            rec["status"] = "active"
            rec["pool"] = _bd
            rec["type"] = _snap["type"]
            rec["last"] = _snap
            track[code] = rec
            pending.pop(code, None)
        else:
            pe = pending.get(code)
            if pe is not None:
                # 昨在 pending 且今仍在池 → 转正式（entry=今日确认收盘日）
                _entry = today
                track[code] = {"entry": _entry, "last_seen": today, "exit": _exit(_entry), "status": "active",
                               "pool": _bd, "type": _snap["type"], "first_seen": pe.get("first_seen", today),
                               "last": _snap}
                pending.pop(code, None)
            else:
                # 全新上榜 → 入 pending（今日不入正式池、不参与信号，隔日无条件转正）
                pending[code] = {"entry_candidate": today, "first_seen": today,
                                 "pool": _bd, "type": _snap["type"], "last": _snap}
    # ②' 老 pending → 正式：隔日无论是否仍在榜一律转正式（2026-08-19 用户拍板：
    #     进标的池=默认全买 → 必须跟踪卖出信号 → 掉榜也须入池跟踪）
    for code in list(old_pending.keys()):
        if code in track:
            continue
        if code not in pending:
            continue                        # 已在 ② 中今日在池处理并转过正式
        pe = pending[code]
        _pd_ = pe.get("pool", "")
        _ps_ = pe.get("last") or {"name": code, "pool": _pd_}
        track[code] = {"entry": today, "last_seen": today, "exit": _exit(today), "status": "active",
                       "pool": _pd_, "type": pe.get("type") or ("fund" if _pd_ == "基金" else "stock"),
                       "first_seen": pe.get("first_seen", today), "last": _ps_}
        pending.pop(code, None)
    # ③ 一次性历史补偿：跟踪功能上线前（8/14 池）出现过的可买入标的，直接入正式池（历史事实，entry=2026-08-14）
    if not _old_full.get("_backfilled_0814"):
        try:
            _hist_out, _, _, _ = calc_signals(as_of="2026-08-14")
            for _c, _d in _hist_out["details"].items():
                if _buyable(_d) and _c not in track:
                    track[_c] = {"entry": "2026-08-14", "last_seen": "2026-08-14", "exit": _exit("2026-08-14"), "status": "active",
                                 "pool": _d.get("board", ""), "type": "fund" if _d.get("board") == "基金" else "stock"}
            out["_backfilled_0814"] = True
            print(f"8/14 池历史补偿完成，正式跟踪池累计 {len(track)} 只、待确认 {len(pending)} 只", flush=True)
        except Exception as _e:
            print("8/14 池历史补偿失败:", _e, flush=True)
    # ④ pending 兜底：只按 30 天到期清理；不再因「今日不在池」清除（隔日已无条件转正式的标的不该滞留 pending；
    #     留在 pending 里的标的只有「今日新上榜待明日转正」的，强制保留以便隔日入池跟踪卖出）
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=30)
    pending = {c: v for c, v in pending.items() if pd.Timestamp(v.get("entry_candidate", today)) > cutoff}
    track = {c: v for c, v in track.items() if pd.Timestamp(v.get("entry", today)) > cutoff}
    # ⑥ 刷新全部正式跟踪成员快照（2026-08-24 修复：掉出今日榜的跟踪标的 last 停留在最后信号日，
    #    看板显示旧涨跌——典型：600508 上海能源 08-24 涨停(+10.02%)但跟踪池仍显示 08-21 的 +2.05%）。
    #    在池标的由 ② 已刷新；掉榜标的回 stock_pool/fund_pool 按最新收盘重算 px/chg/score/tier。
    #    与 v9 跟踪池（build_enhanced_data.py ⑥ _snap_from_data）同构；底层数据无最新行时保留旧快照。
    def _ref_snap(_c, _rec):
        _d = out["details"].get(_c)
        if _d:
            return {"name": _d.get("name"), "px": _d.get("px"), "chg": _d.get("chg"),
                    "score": _d.get("short_score"), "tier": _d.get("short_tier") or _d.get("tier"),
                    "pool": _d.get("board"), "type": "fund" if _d.get("board") == "基金" else "stock",
                    "date": today}
        _is_fund = _rec.get("pool") == "基金"
        _k = ("sh" if _c.startswith(("6", "5")) else "sz") + _c
        _df = fund_pool.get(_c) if _is_fund else stock_pool.get(_k)
        if _df is None or len(_df) == 0:
            _df = fund_pool.get(_c) if _is_fund else None   # 兜底：误判的基金/数据缺失
        if _df is None or len(_df) == 0:
            return None
        if as_of is not None:
            if as_of not in _df.index:
                return None
            _r = _df.loc[as_of]
            _cls = _df["close"].loc[:as_of]
        else:
            _r = _df.iloc[-1]
            _cls = _df["close"]
        _px = float(_r["close"])
        if pd.isna(_px) or _px <= 0:
            return None
        _chg = float(_cls.iloc[-1] / _cls.iloc[-2] - 1) * 100 if len(_cls) >= 2 else None
        _sc = float(S.short_score(_r, reversal=not _is_fund))
        if pd.isna(_sc):
            return None
        _old_last = _rec.get("last") or {}
        return {"name": NAMES.get(_k, _old_last.get("name") or _c),
                "px": round(_px, 2), "chg": round(_chg, 2) if _chg is not None else None,
                "score": round(_sc, 1), "tier": buy_tier(_sc, _rec.get("pool")),
                "pool": _rec.get("pool"), "type": "fund" if _is_fund else "stock",
                "date": str(_df.index[-1].date())}
    _refreshed = 0
    _dropped_dead = 0
    _stale_cutoff = str((pd.Timestamp(today) - pd.Timedelta(days=20)).date())
    for _c, _rec in list(track.items()):
        if _rec.get("last") and str(_rec["last"].get("date", "")) == today:
            continue                          # ②/②' 今日已刷新（在池/转正式）
        _old_date = str((_rec.get("last") or {}).get("date", ""))
        _snap = _ref_snap(_c, _rec)
        if _snap:
            _sd = str(_snap.get("date", ""))
            # 死数据/退市股：股票数据停在多年前（如 600317 营口港 2021 退市）→ 移出跟踪，
            # 与 v9 maintain_track_v9 剔 ST/退市口径一致；基金净值 T-2 内属正常，不剔。
            if _rec.get("type") == "stock" and _sd and _sd < _stale_cutoff:
                del track[_c]
                print(f"  剔除死数据跟踪成员 {_c} {_snap.get('name', _c)}（数据日期 {_sd}，疑似退市/停更）", flush=True)
                _dropped_dead += 1
                continue
            _rec["last"] = _snap
            _refreshed += 1
        elif _rec.get("type") == "stock" and _old_date and _old_date < _stale_cutoff:
            # 池内已无该股数据（新鲜度过滤剔出）且旧快照早于阈值 → 一并移出跟踪
            del track[_c]
            print(f"  剔除死数据跟踪成员 {_c} {_old_date}（全量池已无数据，疑似退市/停更）", flush=True)
            _dropped_dead += 1
    if _refreshed:
        print(f"短线跟踪池快照刷新 {_refreshed} 只（掉榜成员回全量池重算 px/chg）", flush=True)
    if _dropped_dead:
        print(f"短线跟踪池剔除死数据/退市成员 {_dropped_dead} 只", flush=True)
    # ⑤ 市况门控关闭口径统一（2026-08-19 修复：门控关闭后跟踪池股票档位不得显示「买入」
    #    误导可追——已入池标的仅保留卖出信号跟踪，档位改写「不开新仓·仅跟踪」，score 保留）
    if not out.get("market_gate", {}).get("open", True):
        for _rec in list(track.values()) + list(pending.values()):
            if _rec.get("type") != "stock":
                continue
            _last = _rec.get("last")
            if isinstance(_last, dict) and _last.get("tier"):
                _last["tier"] = "不开新仓·仅跟踪"
                _last["gate_closed"] = True
            _rec["gate_closed"] = True
        print(f"市况门控关闭：跟踪池股票档位改写「不开新仓·仅跟踪」（{sum(1 for r in track.values() if r.get('type')=='stock')} 只正式 + {sum(1 for r in pending.values() if r.get('type')=='stock')} 只待确认）", flush=True)
    out["track"] = track
    out["track_pending_short"] = pending
    json.dump(out, open(BASE / "short_pool.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    with open(BASE / "short_pool.js", "w", encoding="utf-8") as f:
        f.write("window.SHORT_POOL = " + json.dumps(out, ensure_ascii=False) + ";")
    with open(BASE / "short_signals.js", "w", encoding="utf-8") as f:
        f.write("window.SHORT_SIGNALS = " + json.dumps(sigs, ensure_ascii=False) + ";")
    print(f"全市场信号 {len(sig_stock)}+{len(sig_fund)} 只 → short_signals.js（2026-08-17 去 ETF）", flush=True)
    print(f"自动跟踪 {len(track)} 只（可买入标的，30 天过期移除）", flush=True)

if __name__ == "__main__":
    import time
    time = __import__("time")
    import argparse
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--as-of", default=None, help="信号日 YYYY-MM-DD（默认最新交易日）")
    _args = _ap.parse_args()
    build(as_of=_args.as_of)