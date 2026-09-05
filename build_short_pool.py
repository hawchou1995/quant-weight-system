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
# 2026-09-02 用户拍板：短线战法全量池选股改用 KHunter 信号 + RSI 择时（主板限定，全窗口），弃用旧战法（反转打分）
# 回测证据：KHunter 信号 + RSI_T-1<35 超卖买 + 主板限定 + 全窗口（牛熊一致开仓）
#   = 四闸(ex_m)过 26 格：ob75/osl35/none n=653 wr62.5% med+5.82% ex_m+9.77%；ob75/osl40/none n=1639 ex_m+9.08%
#   = 信号稀疏（每18天1只）→ 事件独立口径（有信号就买，无需 top4 组合）
# ⚠ 2026-09-03 生产切换（用户拍板「直接切换，两版都部署」）：ob75 → A 版 ob55 + C 版参考 ob50 + 低价过滤 ≥3 元
#   回测证据（khunter_three_ver_opt_20260903.py，9 格 = A/B/C × {无/2元/3元}，回归门与 v8 原值逐位一致）：
#     A_ob55+low3: n=408 wr65.9 每笔年化63.5% 夏普1.184 pf1.07 | 资金池N5 年化5.54% 回撤19.90% 夏普0.372 | 2024 +1.33%
#     C_ob50+low3: n=408 wr63.5 每笔年化81.4% 夏普1.430 pf1.20 | 资金池N5 年化4.98% 回撤19.45% 夏普0.352 | 2024 +2.47%
#     B(+30%止损)+low3 全灭（池年化 0.27%）→ 剔除；时间止损同样否决（tstop20 2024 更差）
#   部署语义：入场规则唯一（信号+RSI<35+熊市+收盘≥3元，A/C 同入口）；A 版 RSI>55 为主卖出；
#   C 版 RSI>50 作并行参考卖出（sell_c 字段/看板双版本展示），模拟盘 A/C 双轨前向对决后定稿
# ⚠ 2026-09-03 23:15 牛熊分域投产（Phase 10 HYBRIDv2 定稿 · total+68.5% 牛熊独立双过闸）：
#   🐻 熊市（hs300<MA60）：osl35 / low3 / ob55(A 主) / ob50(C 参考) / hold25 = 生产现状 + hold25
#   🌞 牛市（>MA20 且非熊）：osl30 / 无低价 / ob75(A 主) / ob50(C 参考) / hold25 = 定稿式参数
#   ⚠ 回测铁律（Phase 10 v1 失败教训）：熊市绝不 split 放宽（osl40 → n 520 低质量信号 total -11.1%）
#   改回「牛市也开仓」依据：8/9/3 Phase 10 HYBRIDv2 = n=296 wr61% med+2.46% total+68.5% 牛熊独立过闸；「牛市 38 组扫描全灭」已废止（原为含 ST + 单一 osl35 口径）
# 弃用旧战法证据：反转打分(S55)修正后主板 -35.65%/全市场 -41.67% 均负期望
ENABLE_KHUNTER = True
KHUNTER_RSI_BUY = 35     # 熊市买入：RSI_T-1 < 35（生产现状保留）
KHUNTER_RSI_BUY_BULL = 30  # 牛市买入：RSI_T-1 < 30（定稿式 osl30，2026-09-03 牛熊分域投产）
KHUNTER_RSI_BUY_WEAK = 32  # 弱牛回调买入：RSI_T-1 < 32（2026-09-04 弱牛域专项 OSL32 投产，回测组合 total 68.49%→79.96%）
KHUNTER_RSI_SELL = 55    # 熊市 A 版卖出：RSI_T-1 > 55（生产现状保留）
KHUNTER_RSI_SELL_BULL = 75  # 牛市 A 版卖出：RSI_T-1 > 75（定稿式 ob75，2026-09-03 牛熊分域投产）
KHUNTER_RSI_SELL_WEAK = 80  # 弱牛回调 A 版卖出：RSI_T-1 > 80（2026-09-04 弱牛域专项 ob80 投产，与 OSL32 同批定稿）
KHUNTER_RSI_SELL_C = 50  # C 版卖出参考：RSI_T-1 > 50（牛熊统一，激进 OB50，双版本并行部署，sell_c 展示）
KHUNTER_LOW_PRICE = 3.0  # 低价过滤（仅熊市）：确认日收盘 ≥ 3 元（2026-09-03 接入；low3 回测：夏普 0.727→1.184、2024 灾年转正）
KHUNTER_LOW_PRICE_BULL = None  # 牛市低价过滤：无（定稿式 low3 伤后半 med +0.85%→-0.31% 破线）
KHUNTER_LOW_PRICE_WEAK = None  # 弱牛回调低价过滤：无（2026-09-04 OSL32 定稿：弱牛域开不设低价，与牛市同口径）

def _khunter_sig(ddf, as_of=None, regime=None):
    """KHunter 信号计算（2026-09-02 用户拍板）：生产在「今日 T 收盘后」运行，明日 T+1 开盘执行。
    回测口径精确对齐（khunter_fusion_s1b_bear.py, 修正引擎 T+1 铁律）：
      回测语义：执行日 T 开盘 ⟺ 确认日「T-1 信号命中 AND T-1 RSI<35」同天成立；
      生产映射：执行日 = 明天 T+1 → 确认日 = 今日 T → 检查今日 sig_any[T] + 今日 RSI
    ddf = short_engine 的因子 df（含 date index）；as_of=历史回溯日（as_of 当日即「今日 T」）；
    regime: 'bear'/'bull'/'weak_bull'（2026-09-03 牛熊分域投产：A 卖出阈值 熊 55 / 牛 75；None=旧统一 55）
    返回字典：{hit: 确认日信号命中, rsi_now: 确认日 RSI（买入/卖出判定）, rsi_t1: T-1 RSI(展示),
               sell1: 确认日 RSI>分域 A 卖出阈值, c_sell: 确认日 RSI>KHUNTER_RSI_SELL_C(C50),
               hits: 确认日命中信号名单}"""
    try:
        import sys as _sys
        if str(BASE / "backtest") not in _sys.path:
            _sys.path.insert(0, str(BASE / "backtest"))
        import khunter_all_strategies_backtest as _K
        import khunter_timing_backtest as _T
        d = ddf[['open', 'high', 'low', 'close', 'volume']].copy()
        d.index.name = None
        d['date'] = d.index
        d = d.sort_values('date').reset_index(drop=True)
        # as_of 截断：只用到 as_of 当日的全部数据（与主循环 r = ddf.loc[as_of] 口径一致）
        if as_of is not None:
            _cut = pd.Timestamp(as_of)
            d = d[d['date'] <= _cut].reset_index(drop=True)
            if len(d) < 2:
                return {"hit": False, "rsi_t1": None, "rsi_now": None, "sell1": False, "c_sell": False, "hits": []}
        r = _T.prep(d)
        sig_any = np.zeros(len(d), dtype=bool)
        for _name, _fn in _K.SIGNALS.items():
            try:
                _sv = _fn(r)
                if _sv.any():
                    sig_any |= _sv.values
            except Exception:
                continue
        # 今日 T 视角（生产：今日收盘确认 → 明日开盘执行 = 回测「执行日=确认日+1」）
        i = len(d) - 1
        if i < 1:
            return {"hit": False, "rsi_t1": None, "rsi_now": None, "sell1": False, "c_sell": False, "hits": []}
        rsi_now = r['rsi'].iloc[i]      # 确认日 T RSI（买入判定 rsi_now<35；卖出判定 rsi_now>75）
        rsi_t1 = r['rsi'].iloc[i - 1]   # T-1 RSI（仅展示参考）
        hit_now = bool(sig_any[i])      # 确认日 T 信号命中
        hit_names = []
        if hit_now:
            for _name, _fn in _K.SIGNALS.items():
                try:
                    _sv = _fn(r)
                    if bool(_sv.iloc[i]):
                        hit_names.append(_name)
                except Exception:
                    continue
        return {"hit": hit_now,
                "rsi_t1": (float(rsi_t1) if not pd.isna(rsi_t1) else None),
                "rsi_now": (float(rsi_now) if not pd.isna(rsi_now) else None),
                "sell1": (bool(rsi_now > (KHUNTER_RSI_SELL_WEAK if regime == "weak_bull" else (KHUNTER_RSI_SELL_BULL if regime in ("bull", "weak_bull") else KHUNTER_RSI_SELL))) if not pd.isna(rsi_now) else False),
                "c_sell": (bool(rsi_now > KHUNTER_RSI_SELL_C) if not pd.isna(rsi_now) else False),
                "hits": hit_names}
    except Exception:
        return {"hit": False, "rsi_t1": None, "rsi_now": None, "sell1": False, "c_sell": False, "hits": []}
# ⚠ 2026-09-02 生产接入 v3（牛熊独立配置网格 shortpool_bull_grid_0902 最优，用户指令「牛市用牛市参数」）：
#   牛市子集四闸 PASS 配置 = S2_t4_h15_s50：权重(25,20,25,30) + 关动量 mask(0,1,1,1) + 门槛 S50
#     → 牛市 med -0.10%(基线) → +0.23%(PASS)，mean +1.41%、超额 +1.14%、n=225（全市场 top4 口径）
#   ⚠ 口径差异（17:00 补跑 shortpool_board_engine_0902 每板配额验证）：
#     网格 PASS 是「全市场自由选 top4」的精选效应；生产每板 Top10 结构穷举 56 配置全 fail
#     （最好 med -0.16%）→ 生产结构下短线股票牛市无过闸配置（与修正引擎「短线股票无可投产配置」一致）
#     → 本接入定位 = 方向性改善 + 观察项（每板口径 med -0.64%→-0.33%、mean +1.15%→+3.02%、双创信号恢复满额）
#   熊市 24 配置全 fail（最好 med -0.14%）→ 短线引擎熊市无 edge，维持清仓（生产现状正确）
#   市值因子：牛市 <1亿 小票 PASS（med +0.83%），量级单调递减；熊市全量级 fail → 小票偏好列观察项
STOCK_W_STRONG = (25, 20, 25, 30)   # 强牛：网格牛市最优权重（原基线 (30,25,25,20)）
STOCK_MASK_STRONG = (0, 1, 1, 1)    # 强牛：关动量（网格牛市最优掩码；量价+通道+低波）
STOCK_SCORE_MIN_STRONG = 50         # 强牛：S50（网格 S50>S55>S60 单调）
STOCK_W_WEAK = (20, 20, 30, 30)     # 弱牛：防守权重（回撤 -30.7% vs 基线 -40.03%，胜率 +6.1pp）
# FB3 基金牛熊：牛=动量重(40,0,30,30) / 熊=低波重(25,0,30,45)
FUND_W_BULL = (40, 0, 30, 30)       # 牛：动量重（量价退化，0 权重）
FUND_W_BEAR = (25, 0, 30, 45)       # 熊：低波重（避险型基金优先）
FUND_S_BEAR = 45                    # 熊：更严门槛 S45
FUND_TOP_BEAR = 3                   # 熊：更少标的 Top3

def _buyable(d):
    """可买入判定（跟踪池/回溯/历史补偿共用）：
    2026-09-02 用户拍板：KHunter 主信号（主板信号+RSI<35）= 唯一股票买入来源；
    旧战法（反转打分 S55）已全量弃用（负期望）→ 不再构成买入依据；基金 S30 不受影响"""
    # KHunter 信号命中 + RSI<35 → 可买入（主信号，事件独立），不受旧战法分数门槛约束
    _kh = d.get("khunter") or {}
    if _kh.get("sig") and _kh.get("buy"):
        return True
    sc = d.get("short_score") or 0
    if d.get("board") == "基金":
        return sc >= FUND_SCORE_MIN
    return False   # 股票旧战法已弃用：非 KHunter 主信号不可买入

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
    # ⚠ 2026-09-03 23:15 牛熊分域投产（Phase 10 HYBRIDv2 定稿 · total+68.5% 牛熊独立双过闸）：
    #   原 B1「熊市限定（hs300<MA60 才可买）」→ 升级为「牛熊分域」：
    #     🐻 熊市（<MA60）：osl35+low3+ob55（=原生产现状参数）
    #     🌞 牛市（>MA20）：osl30+无low+ob75（=定稿式参数）
    #     🌙 弱牛回调（MA20 下/MA60 上）：不开仓
    #   依据：Phase 10 HYBRIDv2 n=296 wr61% med+2.46% total+68.5% 牛熊独立双过闸 + 周一验 8 正年；
    #   原「38 组牛市扫描 0 过门」（khunter_bull_sweep_delivery_20260903.md）已废止——含 ST + 单一 osl35 口径下得出，
    #   剔 ST + 分域 osl30 后牛市子集 n=39 wr61.5% med+3.20% 过闸（Phase 10）
    # 豁免逻辑（9/2）保留不动：_buy_ok 含牛熊分域门控 → 弱牛/强牛按分域处理，豁免集为空，无冲突
    _idx60 = S.V.load_index(60)
    _idx60 = _idx60.set_index("date")
    _bear60 = bool(not _idx60.loc[:_gate_day]["in_market"].iloc[-1]) if _gate_day in _idx60.index else False
    market_gate["bear60"] = _bear60
    print(f"熊市限定(hs300<MA60, 回测口径): {'🐻 熊市（KHunter 可买入）' if _bear60 else '🌞 非熊（KHunter 不开新仓）'} ({time.time()-t0:.0f}s)", flush=True)

    # ② 市场情绪只读元数据（2026-09-05 接入）：从 market_breadth.js 透传涨停封单强度等特征，
    #    advisory-only —— 仅供观察，不参与 1100 行门控判定。
    try:
        _mb = json.loads(re.search(r"window\.MARKET_BREADTH\s*=\s*(\{.*?\});", (BASE/"market_breadth.js").read_text(encoding="utf-8"), re.S).group(1))
        _sent = _mb.get("sentiment") or {}
        market_gate["sentiment"] = {"zone": _sent.get("sentiment_zone", _sent.get("zone", "—")), "zt_ratio": _sent.get("zt_ratio"), "broken_rate": _sent.get("broken_rate"), "seal_yi": _sent.get("total_seal_yi"), "lianban_max": _sent.get("lianban_max", 0), "note": "advisory-only（不参与门控判定，仅供观察）"}
    except Exception:
        market_gate["sentiment"] = {"note": "market_breadth.js 缺失/解析失败", "source": "unavailable"}

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
    # 2026-09-02 生产接入 v3：强牛用网格牛市最优（关动量 mask + S50 门槛），弱牛保持全 mask + S55
    _stk_mask = STOCK_MASK_STRONG if _stk_strong else (1, 1, 1, 1)
    _stk_smin = STOCK_SCORE_MIN_STRONG if _stk_strong else STOCK_SCORE_MIN
    print(f"股票 regime: {'强牛' if _stk_strong else ('弱牛' if _in_mkt else '熊市清仓')} (idx mom20={_idx_m20*100:.1f}%) 权重{_stk_w} mask{_stk_mask} 门槛{_stk_smin}", flush=True)

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
    # 2026-09-03 生产切换：KHunter 事件收集（主板限定；主信号=信号+RSI<35+收盘≥3元，卖出=A55 主/C50 参考）
    khunter_buy = []      # (code, info)：信号命中（含 buy_ok 判定）
    khunter_sell = []     # code：A 版 RSI>55 独立卖出信号（回测 event_days = entry_ok | sell_vec）
    khunter_sell_c = []   # code：C 版 RSI>50 参考卖出（2026-09-03 双版本部署）

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
        sc = S.short_score(r, reversal=True, weights=_stk_w, mask=_stk_mask)
        if pd.isna(sc):
            continue
        bd = board_of(code)
        if bd not in rows_by_board:
            continue
        # 2026-09-01 多策略命中回避：命中≥3 剔除（回测：命中数≥3 收益单调恶化，共振过度=反向信号）。
        # 仅对 sc≥门槛 候选计算（sc<门槛 本就不入池，避免全市场 5000+ 只的指标计算开销）。
        if ENABLE_HIT_AVOID and float(sc) >= _stk_smin:
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
        # 2026-09-02 用户拍板：KHunter 信号层（主板限定+RSI 超卖择时，弃用旧战法）
        # ⚠ 2026-09-03 生产切换（用户拍板）：A 版卖出 RSI>55 + 低价过滤确认日收盘≥3元；C 版卖出 RSI>50 参考并行
        # ⚠ 2026-09-03 23:15 牛熊分域投产（HYBRIDv2 定稿 · total+68.5% 牛熊独立双过闸）：
        #   🐻 熊市（hs300<MA60）：osl35+low3+ob55(A)/ob50(C) —— 生产现状参数
        #   🌞 牛市（>MA20 且非熊）：osl30+无low+ob75(A)/ob50(C) —— 定稿式参数
        #   🌙 弱牛回调（MA20 下/MA60 上）：⚠ 2026-09-04 弱牛域专项投产 → osl32+无low+ob80(A)/ob50(C)+hold15
        #     （用户拍板「直接上 OSL32」；回测组合 total 68.49%→79.96% dd -22.45% 不变 夏普 0.397→0.435；
        #      弱牛 n=28 wr57% med+2.95%，近四闸（n<30），年度集中 2022 +80.9% 主要贡献，2026 -1.9% 警示——样本小，观察）
        # 注意：KHunter 信号计算较重（15 个信号函数），只对主板 bd 计算（产品只能买主板）
        # 主信号口径=回测 ortho：T 日信号命中 + 信号日 RSI<阈值 + [熊市低价] + [牛熊分域] → 明日开盘买入（事件独立，稀疏）
        # 卖出 = 分域 A 版主卖出（熊 RS>55/牛 RS>75/弱牛 RS>80） / C 版 RSI>50 参考（独立信号，买卖事件各自独立；卖出不受牛熊限定）
        if ENABLE_KHUNTER and bd == "主板":
            # ---- 牛熊分域判定（Phase 10 HYBRIDv2）----（先判定 regime，再传入信号函数）
            _kh_is_bear = bool(_bear60)          # hs300<MA60
            _kh_is_bull_mkt = bool(_in_mkt)      # hs300>MA20（弱牛/强牛）
            _kh_regime = "bear" if _kh_is_bear else ("bull" if _kh_is_bull_mkt else "weak_bull")
            _kinfo = _khunter_sig(ddf, as_of, regime=_kh_regime)
            _kh_osl = KHUNTER_RSI_BUY if _kh_is_bear else (
                KHUNTER_RSI_BUY_BULL if _kh_is_bull_mkt else KHUNTER_RSI_BUY_WEAK)
            _kh_low = KHUNTER_LOW_PRICE if _kh_is_bear else (
                KHUNTER_LOW_PRICE_BULL if _kh_is_bull_mkt else KHUNTER_LOW_PRICE_WEAK)
            _kh_ok_buy = (_kh_osl is not None and _kinfo["rsi_now"] is not None
                          and _kinfo["rsi_now"] < _kh_osl
                          and (_kh_low is None or r["close"] >= _kh_low)
                          and True)  # 2026-09-04 弱牛域投产：三态全开（熊 B35 / 牛 B30 / 弱牛 W32），去掉 (_kh_is_bear or _kh_is_bull_mkt) 限制
            if _kinfo["hit"]:
                sig_stock[code[-6:]]["khunter"] = {
                    "sig": True,
                    "rsi_t1": _kinfo["rsi_t1"],
                    "rsi_now": _kinfo["rsi_now"],
                    "buy": bool(_kh_ok_buy),
                    "sell": _kinfo["sell1"],
                    "c_sell": _kinfo["c_sell"],
                    "low_ok": bool(r["close"] >= KHUNTER_LOW_PRICE),
                    "regime": "bear" if _kh_is_bear else ("bull" if _kh_is_bull_mkt else "weak_bull"),
                    "hits": _kinfo["hits"],
                }
                # ⚠ 2026-09-04 修复（grill Q1）：KHunter 主信号 tier 覆盖必须同步到 sig_stock（short_signals.js 数据源）
                # 原缺陷：覆盖只做了 details（838 行），sig_stock 仍按旧战法 tier_of(score) →
                # 跟踪池 renderWatch 读 SHORT_SIGNALS 显示「清仓」，与池子「买入」矛盾。
                # 语义与 details 一致：sig + buy → tier=「买入」（score 保留旧战法分仅参考）。
                if _kh_ok_buy:
                    sig_stock[code[-6:]]["tier"] = "买入"
                # 事件收集（主信号判定：分域 RSI 阈值 + 分域低价 + 分域门控）
                _buy_ok = bool(_kh_ok_buy)
                khunter_buy.append((code, _kinfo, _buy_ok, float(sc), r, ddf))
            if _kinfo["sell1"]:
                # A 版分域卖出信号：熊 RSI>55 / 牛 RSI>75 / 弱牛 RSI>80（独立于选股信号；回测 event_days = entry_ok | sell_vec）
                _sell_note = (f"RSI>{KHUNTER_RSI_SELL_WEAK} 弱牛超买卖出（A 版独立信号）" if _kh_regime == "weak_bull"
                              else (f"RSI>{KHUNTER_RSI_SELL_BULL} 牛超买卖出（A 版独立信号）" if _kh_regime == "bull"
                                    else f"RSI>{KHUNTER_RSI_SELL} 熊超买卖出（A 版独立信号）"))
                sig_stock[code[-6:]]["khunter"] = {
                    "sig": bool(_kinfo["hit"]), "rsi_t1": _kinfo["rsi_t1"], "rsi_now": _kinfo["rsi_now"],
                    "buy": False, "sell": True, "c_sell": _kinfo["c_sell"],
                    "hits": _kinfo["hits"],
                    "note": _sell_note,
                }
                khunter_sell.append(code)
            # C 版 RSI>50 卖出集 = 完整超集（RSI>50 全收，非 A 未触发窄带）；
            # sig_stock 记录仅当 A55 未写时补（A 记录已含 c_sell 字段）
            if _kinfo["c_sell"] and not ((sig_stock.get(code[-6:]) or {}).get("khunter") or {}).get("sell"):
                sig_stock[code[-6:]]["khunter"] = {
                    "sig": bool(_kinfo["hit"]), "rsi_t1": _kinfo["rsi_t1"], "rsi_now": _kinfo["rsi_now"],
                    "buy": False, "sell": False, "c_sell": True,
                    "hits": _kinfo["hits"],
                    "note": f"RSI>{KHUNTER_RSI_SELL_C} 参考卖出（C 版，A55 未触发）",
                }
            if _kinfo["c_sell"]:
                khunter_sell_c.append(code)
        # ⚠ 2026-09-04 修复（用户反馈：002364 激进版档位/建议空白）：
        #   若 khunter 三大写入分支（信号命中 / A55 卖出 / C50 卖出）都未进入，则 khunter 字段整体缺失，
        #   前端 renderWatch 的 C 版判定 kh.c_sell===false 对 undefined 无效 → 激进版显示「—」。
        #   修复：主板池内每只候选都兜底写入 khunter 字段（hit/RSI/卖出全 False），保证前端双版本始终可判定。
        if ("khunter" not in (sig_stock.get(code[-6:]) or {})):
            sig_stock[code[-6:]]["khunter"] = {
                "sig": False, "rsi_t1": _kinfo["rsi_t1"], "rsi_now": _kinfo["rsi_now"],
                "buy": False, "sell": False, "c_sell": False,
                "hits": [],
                "note": "无信号（KHunter 未见命中/RSI 未超卖）",
            }
    # 按板块列表初始化（2026-09-02 用户拍板：KHunter 主信号 + 弃用旧战法）
    # 主信号 = 主板 KHunter 15 信号命中 + 信号日 RSI<35（超卖买入，回测 ob75/osl35 全窗口最优）
    # 信号观察 = 主板 KHunter 命中但 RSI≥35（未触发买入，等待后续信号日）
    # 旧战法（反转打分）已弃用：主板 -35.65% / 全市场 -41.67% 均负期望（四闸铁律）→ 全部删除，不再展示
    # ⚠ 2026-09-02 用户拍板「旧战法全剔」：候选/仅观察（旧战法分数 Top10）不再计算展示；
    #   rows_by_board 旧战法分数仅保留 KHunter 命中股票的 score 参考字段，排序筛选不再入池。
    if ENABLE_HIT_AVOID and _hit_avoided:
        print(f"命中回避: 剔除命中≥{HIT_AVOID_THRESHOLD} 的股票 {_hit_avoided} 只（多策略共振过度，反向过滤）", flush=True)

    # ════ 2026-09-02 用户拍板：KHunter 主信号（弃用旧战法；事件独立口径）════
    # 回测（khunter_fusion_s1b_bear.py, S1B_BOARD=main, S1B_BEAR=0 全窗口修正引擎 T+1）：
    #   ob75/osl35/none n=653 wr62.5% med+5.82% ex_m+9.77%（四闸过）；ob75/osl40 n=1639 ex_m+9.08%
    #   vs 旧战法反转打分：主板 -35.65% / 全市场 -41.67% → 弃用
    # 口径：T 日收盘信号确认 + 信号日 RSI<35 → T+1 开盘买入；信号稀疏（~1/18天）→ 事件独立（有信号就买）
    kh_main = []      # 主信号（可买入）：hit & 信号日 RSI<35（主板）
    kh_watch = []     # 信号观察：hit & RSI≥35（信号已确认，未达超卖，不触发买入）
    for _kf in sorted(khunter_buy, key=lambda kv: (kv[1].get("rsi_now") or 99)):
        _code, _info, _buy_ok, _sc, _r, _ddf = _kf
        if _buy_ok:
            kh_main.append((_code, _sc, _r, _ddf))
        else:
            kh_watch.append((_code, _sc, _r, _ddf))
    print(f"KHunter 主信号（主板·信号日RSI<35）: {len(kh_main)} 只 → {'、'.join(c[0] for c in kh_main) or '（今日无信号——事件驱动，稀疏性预期内）'}", flush=True)
    print(f"KHunter 信号观察（已命中·RSI≥35 未触发）: {len(kh_watch)} 只 → {'、'.join(c[0] for c in kh_watch) or '—'}", flush=True)

    # ════ 2026-09-02 用户拍板：旧战法全剔（不含任何观察/候选展示）════
    # 主信号 = KHunter 买入信号（事件独立口径，无 top4 排序——信号即买，稀缺即稀缺）
    # 旧战法候选/每板块 Top10 全部删除：rows_by_board 与 cand_by_board 不再用于展示。
    stock_top4 = kh_main  # 主信号 = KHunter 主板买入信号（替代旧全市场 top4）
    print(f"主信号 KHunter: {len(stock_top4)} 只（主板·信号日RSI<35，事件独立）({time.time()-t0:.0f}s)", flush=True)

    # 候选/观察（旧战法）全部清空——用户拍板「旧战法全剔」
    cand_by_board = {"主板": [], "创业板": [], "科创板": []}
    # stock_top_main = KHunter 主信号（不再并入旧战法候选）
    stock_top_main = list(stock_top4)
    stock_top_gem  = []
    stock_top_star = []
    # 主信号 = KHunter 主板买入信号（覆盖原三板块合并列表；无候选）
    stock_top = stock_top4
    print(f"主板展示（主信号 {len(stock_top4)} 只，无旧战法候选）: {'、'.join(c[0] for c in stock_top_main) or '—'} ({time.time()-t0:.0f}s)", flush=True)

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

    # 详情构建（2026-09-02 用户拍板：主信号 KHunter + 基金池，旧战法候选全剔）
    details = {}
    _all_disp = stock_top + etf_top + fund_top
    _top4_codes_set = {c for c, _, _, _ in stock_top4}
    # 旧战法候选已全剔 → 不再需要 _cand_codes 收集（无额外详情）
    _cand_codes = []
    _all_disp = _all_disp + _cand_codes
    for code, sc, r, ddf in _all_disp:
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
            # 2026-09-02 用户拍板：主信号=KHunter 主板信号（事件独立），旧战法候选全剔
            # 主信号 details 附带 khunter 信号信息（hits/rsi/buy/sell）供前端渲染
            "pick": "top4" if code in _top4_codes_set else None,
            "khunter": (sig_stock.get(bare, {}) or {}).get("khunter"),
        }
        # 2026-09-02 KHunter 主信号档位覆盖（用户拍板「弃用旧战法」）：
        # 主信号（sig+buy）判定口径 = 信号命中 + 信号日 RSI<35（回测 ob75/osl35 事件独立，无强度区分），
        # 与旧战法反转分 tier 无关 —— 旧战法分低（<55）时 buy_tier 会显示「不买」，与主信号 badge 自相矛盾。
        # 统一覆盖为「买入」：score 字段保留旧战法分供参考，但档位/建议动作走 KHunter 主信号语义。
        _kh_d = details[bare].get("khunter")
        if _kh_d and _kh_d.get("sig") and _kh_d.get("buy"):
            details[bare]["tier"] = "买入"
            details[bare]["short_tier"] = "买入"
    order = {"主板": [c[-6:] for c, _, _, _ in stock_top_main],
             "创业板": [c[-6:] for c, _, _, _ in stock_top_gem],
             "科创板": [c[-6:] for c, _, _, _ in stock_top_star],
             "基金": [c[-6:] for c, _, _, _ in fund_top]}
    # 2026-09-02 用户拍板：主信号结构输出（供前端标签与备注渲染）
    _top4_list = [c[-6:] for c, _, _, _ in stock_top4]
    _cand_list = {"主板": [], "创业板": [], "科创板": []}   # 旧战法候选已全剔
    _kmeta = {
        "sig": True,
        "buy": len(kh_main) > 0,
        "sell": khunter_sell,
        "sell_c": khunter_sell_c,
        "buy_n": len(kh_main),
        "watch_n": len(kh_watch),
        "watch": [c[-6:] for c, _, _, _ in kh_watch],
        "ver": {"buy_rsi": KHUNTER_RSI_BUY, "buy_rsi_bull": KHUNTER_RSI_BUY_BULL,
                "buy_rsi_weak": KHUNTER_RSI_BUY_WEAK,
                "sell_a": KHUNTER_RSI_SELL, "sell_a_bull": KHUNTER_RSI_SELL_BULL,
                "sell_a_weak": KHUNTER_RSI_SELL_WEAK,
                "sell_c": KHUNTER_RSI_SELL_C, "low": KHUNTER_LOW_PRICE,
                "low_bull": KHUNTER_LOW_PRICE_BULL, "low_weak": KHUNTER_LOW_PRICE_WEAK},
        "note_sell": f"卖出=A版分域（熊 RSI>{KHUNTER_RSI_SELL} / 牛 RSI>{KHUNTER_RSI_SELL_BULL} / 弱牛 RSI>{KHUNTER_RSI_SELL_WEAK}）/ C版参考 RSI>{KHUNTER_RSI_SELL_C}（独立信号，不计入买入）",
        "hybrid": True,
    }
    _sel_meta = {
        "top4": _top4_list,
        "candidates": _cand_list,
        "khunter": _kmeta,
        "note": "主信号=KHunter 15 策略信号+信号日分域RSI（🐻熊市&lt;35+低价≥3元+ob55 / 🌞牛市(&gt;MA20)&lt;30+无低价+ob75 / 🌙弱牛回调(MA20下/MA60上)&lt;32+无低价+ob80；HYBRIDv2+弱牛域 2026-09-04 定稿）；旧战法反转分已全量弃用（负期望：主板 -35.65%/全市场 -41.67%），不再展示",
        "label": {"top4": "🎯 KHunter 主信号"},
    }
    # 2026-08-20 用户决策：市况门控改为「仅提醒」——门控关闭不再清空股票池。
    # 股票标的分≥50 照常入池展示（供参考，非买入指令），打 gate_closed 标记供前端标题/行级提醒；
    # 基金不受门控（不加标记）。跟踪池安全口径「不开新仓·仅跟踪」由下方 ⑤ 保持。
    # 2026-09-02 豁免：KHunter 主信号不受门控（用户拍板「熊市选股同样考虑全主板」；
    #   回测 khunter_fusion_s1b_bear.py S1B_BEAR=0 全窗口 ob75/osl35/none n=653 wr62.5% med+5.82% ex_m+9.77% 四闸过，
    #   none 组 26 格全过——RSI<35 超卖择时自身承担风险过滤，熊市开仓反而更优 n+45%）；
    #   旧战法候选/跟踪池非 KHunter 成员仍按「仅提醒」处理。
    _kh_main_set = {c[-6:] for c, _, _, _ in kh_main}
    if not _in_mkt:
        _gated = 0
        for _c in [c[-6:] for c, _, _, _ in stock_top]:
            if _c in details:
                if _c in _kh_main_set:
                    continue              # KHunter 主信号豁免（回测全窗口证据）
                details[_c]["gate_closed"] = True
                _gated += 1
        print(f"市况门控关闭：短线股票池 {_gated} 只标 gate_closed=仅提醒（KHunter 主信号 {len(_kh_main_set)} 只豁免·回测全窗口过闸；照常入池供参考，非买入指令；跟踪池走安全口径）", flush=True)
    # 2026-08-17 修复：as_of 取股票数据最新交易日（主口径），基金净值 T-1 单独标注
    _stock_tail = max((ddf.index[-1] for ddf in stock_pool.values() if len(ddf)), default=None)
    _fund_tail = max((ddf.index[-1] for ddf in fund_pool.values() if len(ddf)), default=None)
    _eff = as_of if as_of is not None else (str(_stock_tail.date()) if _stock_tail is not None else "—")
    out = {"as_of": _eff, "fund_as_of": str(_fund_tail.date()) if _fund_tail is not None else _eff,
           "details": details, "tiers": order, "market_gate": market_gate,
           "sel_meta": _sel_meta}
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
    # 2026-09-02 豁免：KHunter 主信号成员同样免于改写（回测全窗口证据：熊市开仓四闸过）。
    # 豁免集 = sel_meta.top4（= stock_top4 = kh_main，主信号 codes，跨函数可用）。
    if not out.get("market_gate", {}).get("open", True):
        _kh_gate_exempt = set(out.get("sel_meta", {}).get("top4", []))
        for _c, _rec in list(track.items()) + list(pending.items()):
            if _rec.get("type") != "stock":
                continue
            if _c in _kh_gate_exempt:
                continue
            _last = _rec.get("last")
            if isinstance(_last, dict) and _last.get("tier"):
                _last["tier"] = "不开新仓·仅跟踪"
                _last["gate_closed"] = True
            _rec["gate_closed"] = True
        print(f"市况门控关闭：跟踪池股票档位改写「不开新仓·仅跟踪」（{sum(1 for r in track.values() if r.get('type')=='stock')} 只正式 + {sum(1 for r in pending.values() if r.get('type')=='stock')} 只待确认；KHunter 主信号豁免 {len(_kh_gate_exempt)} 只）", flush=True)
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