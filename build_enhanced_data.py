# -*- coding: utf-8 -*-
"""增强数据准备：30 只标的详情（因子拆分/当日涨跌/档位变化/K线/交易历史）+ 两体系 KPI/曲线"""
import os
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, str(BASE))
import v8_selector as V
import v9_auto as A
import v8_lite as L
import short_engine as SH   # v5.8：details 加 short_score/short_tier（短线视角）

names = json.load(open(BASE / "data_full_names.json", encoding="utf-8"))

# 行业映射（模板 v6 口径自选池 + westock profile v9 Top10）
# ---------------- 统一行业体系（申万一级） ----------------
# 所有股票/ETF/基金共用同一套行业分类（申万一级），不再各玩各的：
# 股票按真实行业、ETF 按跟踪指数主题、基金按投资方向，宽基/均衡归「综合」
INDUSTRY = {
    # ---- 个人版股票（v8 固定池）----
    '300502': '通信', '300308': '通信', '600498': '通信', '601138': '电子',
    '002463': '电子', '002384': '电子', '600183': '电子', '300476': '电子',
    '603986': '电子', '002185': '电子', '605358': '电子', '603228': '电子',
    '603339': '机械设备', '000636': '电子', '605189': '纺织服饰', '600403': '煤炭',
    '002879': '电力设备', '600162': '房地产', '000759': '商贸零售', '002474': '计算机',
    # ---- 2026-08-18 固定池新增 ----
    '002820': '食品饮料', '002971': '基础化工', '603629': '电子',
    # ---- 2026-08-19 固定池调整：去 002463沪电/000636风华（已清仓）----
    '300806': '基础化工',   # 斯迪克（westock+Wind 双源确认申万一级=基础化工，主营功能性薄膜/电子级胶粘材料，创业板）
    # ---- 普适版股票（main/gem/star）----
    '600641': '电力设备', '601208': '基础化工', '603078': '电子', '603083': '通信',
    '603186': '电子', '603773': '电子', '603989': '电子', '600353': '电子',
    '600397': '国防军工', '603002': '基础化工',
    '300814': '电子', '300903': '电子', '301328': '电子', '300907': '机械设备',
    '300985': '汽车', '301373': '环保', '301396': '计算机', '301018': '机械设备',
    '300489': '电子', '300566': '电子',
    '688082': '电子', '688549': '电子', '688143': '通信', '688300': '电子',
    '688432': '电子', '688530': '电子', '688392': '机械设备', '688020': '电子',
    '688519': '电子', '688167': '电子',
    # ---- 2026-08-19 补全（Wind 申万一级；此前 fallback「综合」）----
    # 主板
    '002990': '计算机', '002631': '轻工制造', '002979': '机械设备', '002774': '机械设备',
    '000908': '医药生物', '000518': '医药生物', '002346': '电力设备', '001230': '环保',
    '002585': '基础化工', '002528': '计算机',
    # 创业板
    '300319': '电子', '300214': '基础化工', '301196': '基础化工', '300909': '电子',
    '301115': '社会服务', '300929': '环保', '301419': '通信', '301053': '机械设备',
    # 科创板
    '688179': '基础化工', '688449': '电子', '688419': '电子', '688045': '电子',
    '688503': '电力设备', '688112': '机械设备', '688035': '电子', '688253': '医药生物',
    '688046': '医药生物', '688131': '医药生物',
    # ---- 个人版基金 ----
    '008254': '综合', '018036': '电力设备', '002891': '传媒', '024239': '综合',
    '014002': '电子', '020900': '通信',
    # ---- 2026-08-19 基金具体化（Wind 投资类型/投向；不归「综合」）----
    # QDII/海外
    '008254': '海外股票', '024239': '海外科技',
    # 主题/风格混合
    '005005': '均衡配置', '005006': '均衡配置', '000314': '均衡配置', '002017': '均衡配置',
    '004355': '均衡配置', '002158': '均衡配置', '001796': '均衡配置', '002133': '均衡配置',
    '160916': '均衡配置', '519756': '国企改革',
    '000742': '均衡配置', '001198': '均衡配置', '001470': '均衡配置',
    '001723': '均衡配置', '001759': '均衡配置', '002163': '均衡配置', '002289': '均衡配置',
    '018975': '食品饮料', '017063': '成长风格', '016285': '价值龙头',
    '014327': '新兴成长', '519694': '蓝筹价值', '002495': '量化优选', '002496': '量化优选',
    # ---- ETF（按跟踪指数主题归申万一级，宽基归综合）----
    '159516': '电子', '515880': '通信', '516150': '有色金属', '159841': '非银金融',
    '560390': '电力设备', '159502': '医药生物', '513290': '医药生物', '159513': '综合',
    '512990': '综合', '159517': '综合', '515160': '综合', '159655': '综合',
    '159620': '综合', '561950': '综合', '159703': '基础化工',
}


def ind_by_name(nm):
    """按名称关键词把未在 INDUSTRY/ETF_INDUSTRY 映射里的标的归具体行业（2026-08-19：
    不再一律归「综合」，只识别不出才落综合）。顺序：先基金/ETF 主题，再申万行业词。"""
    if not nm:
        return "综合"
    F = [
        ("QDII", "海外股票"), ("全球", "海外股票"), ("海外", "海外股票"), ("纳指", "海外科技"),
        ("港股", "港股"), ("恒生", "港股"),
        ("医药", "医药生物"), ("生物", "医药生物"), ("医疗", "医药生物"), ("创新药", "医药生物"),
        ("电子", "电子"), ("半导体", "电子"), ("芯片", "电子"), ("光电", "电子"), ("科技", "电子"), ("信息", "电子"),
        ("通信", "通信"), ("5G", "通信"), ("光", "通信"),
        ("计算机", "计算机"), ("软件", "计算机"), ("数据", "计算机"), ("人工智能", "计算机"), ("AI", "计算机"),
        ("新能源", "电力设备"), ("光伏", "电力设备"), ("锂", "电力设备"), ("储能", "电力设备"), ("电池", "电力设备"),
        ("军工", "国防军工"), ("国防", "国防军工"), ("航天", "国防军工"),
        ("机械", "机械设备"), ("装备", "机械设备"), ("机器人", "机械设备"),
        ("汽车", "汽车"), ("电动", "汽车"),
        ("化工", "基础化工"), ("材料", "基础化工"), ("新材料", "基础化工"),
        ("有色金属", "有色金属"), ("有色", "有色金属"), ("稀土", "有色金属"),
        ("煤炭", "煤炭"), ("能源", "煤炭"),
        ("消费", "食品饮料"), ("食品", "食品饮料"), ("白酒", "食品饮料"), ("饮料", "食品饮料"),
        ("家电", "家用电器"), ("农业", "农林牧渔"), ("养殖", "农林牧渔"), ("食品饮料", "食品饮料"),
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
BIZ = {
    '600641': '集成电路/光伏核心装备', '688082': '半导体清洗设备', '688549': '电子湿化学品/特气',
    '601208': '绝缘材料/化工新材料', '603078': '湿电子化学品', '603083': 'ICT终端(光模块/交换机)',
    '603186': '覆铜板/复合材料', '603773': 'FPD光电玻璃精加工', '603989': '电容器及材料', '688143': '光纤环/惯性导航',
    '300502': '光模块', '300308': '光模块', '600498': '光通信设备', '601138': '服务器代工/AI硬件',
    '002463': 'PCB(高多层)', '002384': '精密制造/PCB', '600183': '覆铜板', '300476': 'PCB',
    '603986': '存储芯片', '002185': '半导体封测', '605358': '半导体硅片', '603228': 'PCB',
    '603339': '集装箱/冷链装备', '000636': 'MLCC', '605189': '染整', '600403': '煤炭',
    '002879': '电缆附件', '600162': '园区地产', '000759': '商超零售', '002474': '软件',
    # 2026-08-18 固定池新增
    '002820': '麻花/休闲食品', '002971': '工业气体', '603629': '服务器结构件/电子认证',
    # 2026-08-19 固定池新增
    '300806': '功能性膜材料/电子胶粘材料',
    # 权限分层新增（主板10/创业板10/科创板10）
    '300750': '动力电池', '300059': '互联网券商', '300124': '工控/伺服', '300316': '光伏设备',
    '300014': '锂电', '300223': '微处理器', '300782': '射频前端',
    '688981': '晶圆代工', '688008': '内存接口芯片', '688012': '半导体设备', '688041': 'CPU/算力',
    '688256': 'AI芯片', '688126': '硅片', '688111': '办公软件', '688036': '手机终端',
    '688599': '光伏组件', '688223': '光伏组件',
    # 基金
    '008254': 'QDII混合', '018036': '新能源车主题', '002891': '移动互联主题',
    '024239': '全球QDII', '014002': '智能科技主题', '020900': '通信设备主题',
    # 普适版新选股票/ETF/基金（补全行业）
    '600353': '电子元件', '600397': '军工装备', '300814': 'PCB', '300903': 'PCB', '301328': '连接器',
    '000742': '均衡配置', '001060': '高端装备', '001198': '灵活配置', '001411': '科技成长',
    '001470': '灵活配置', '001723': '成长混合', '001759': '成长混合', '002051': '科技成长',
    '002163': '灵活配置', '002289': '改革成长',
}

# 基金名称：base = fund_list.csv（股票/混合基金全域，含 A/C 份额全称），硬编码覆盖兜底
# （普适版基金组为全市场动量 Top10，会随选池变化，必须用全市场名称表而非写死名单）
FUND_NAMES = {}
try:
    _fl_fund = pd.read_csv(BASE / "fund_list.csv", dtype=str)
    FUND_NAMES = dict(zip(_fl_fund["基金代码"], _fl_fund["基金简称"]))
except Exception:
    print("⚠ fund_list.csv 读取失败，基金名退化为代码兜底", flush=True)
FUND_NAMES.update({
    '008254': '华宝致远混合C', '018036': '长城新能源车股C', '002891': '华夏移动互联CNY',
    '024239': '华夏全球QDII C', '014002': '浦银智能科技C', '020900': '天弘通信设备C',
    '000742': '国泰新经济混合A', '001060': '前海开源高端装备A', '001198': '东方惠新混合A',
    '001411': '诺安创新驱动A', '001470': '融通通鑫混合', '001723': '华商新动力A',
    '001759': '嘉实成长增强混合', '002051': '诺安创新驱动C', '002163': '东方惠新混合C',
    '002289': '华商改革创新股票A',
})

# ETF 行业兜底（统一申万一级；主映射在 INDUSTRY，此处仅兜底防新增 ETF 漏配）
ETF_INDUSTRY = {
    '159502': '医药生物', '513290': '医药生物', '159513': '综合',
    '512990': '综合', '159517': '综合', '515160': '综合',
    '159655': '综合', '159620': '综合', '561950': '综合',
    '159703': '基础化工', '159516': '电子', '515880': '通信', '516150': '有色金属',
    '159841': '非银金融', '560390': '电力设备',
}

def tier(sc):
    if sc >= 75: return "满仓加仓"
    if sc >= 60: return "轻仓加仓"
    if sc >= 45: return "观望"
    if sc >= 30: return "减至半仓"
    return "清仓"


# 2026-08-17 方案 A：基金组权重分改用基金动量分（short_engine 口径），档位用动量强弱命名，
# 不占用"满仓/清仓"的持仓操作语义（基金动量分预算 0-75，12m 强选入但 20d 可能偏弱）
FUND_TIER = [("动量强", 55), ("动量中", 40), ("动量弱", 25), ("动量极弱", 0)]


def fund_tier(sc):
    for t, th in FUND_TIER:
        if sc >= th:
            return t
    return "动量极弱"


def fund_mom_score(ddf, asof=None):
    """基金动量分（short_engine.short_score reversal=False：动量30+通道25+波动20，基金无量价→0）"""
    cols = ddf[["open", "high", "low", "close", "volume", "amount"]]
    if asof is not None:
        cols = cols.loc[:asof]
    fr = SH.short_factors(cols).iloc[-1]
    sc = float(SH.short_score(fr, reversal=False))
    return None if np.isnan(sc) else sc

def factor_split(r):
    """四因子拆分（与 score_row 一致）"""
    mom = max(0.0, min(1.0, r["mom_12_1"] / 0.20)) * 100 if not np.isnan(r["mom_12_1"]) else None
    trend = max(0.0, min(1.0, r["ma200_pos"] / 0.30)) * 100 if not np.isnan(r["ma200_pos"]) else None
    a = max(-100.0, min(100.0, r["aroon_osc"]))
    aroon = ((a + 100) / 200) * 100
    vp = 100 if r["vp_confirm"] else 0
    return {"mom": round(mom, 1) if mom is not None else None,
            "trend": round(trend, 1) if trend is not None else None,
            "aroon": round(aroon, 1), "vp": vp}

def rsi14(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))

# ---------------- 六类雷达图（模板风格：趋势/动能/量能/超买/风控/研报） ----------------
def svg_radar(comp, score, size=120):
    """六角雷达，与模板 monitor/render_dashboard.py svg_radar_light 一致（size 增大防标签截断）"""
    cx = cy = size / 2
    R = size * 0.34
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
        parts.append(f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" style="stroke:var(--radar-axis)" stroke-width="1"/>')
    vals = [comp.get(c, 50) for c in cats]
    if abs(comp.get("news", 0) or 0) <= 5:
        vals[5] = 50 + comp["news"] * 20
    spts = " ".join(f"{pt(R*max(3,min(100,vals[i]))/100, angles[i])[0]:.1f},{pt(R*max(3,min(100,vals[i]))/100, angles[i])[1]:.1f}" for i in range(6))
    if score >= 75: fill, stroke = "rgba(220,38,38,0.18)", "#dc2626"
    elif score >= 60: fill, stroke = "rgba(234,88,12,0.16)", "#ea580c"
    elif score >= 45: fill, stroke = "rgba(202,138,4,0.16)", "#ca8a04"
    elif score >= 30: fill, stroke = "rgba(22,163,74,0.16)", "#16a34a"
    else: fill, stroke = "rgba(2,132,199,0.16)", "#0284c7"
    parts.append(f'<polygon points="{spts}" fill="{fill}" stroke="{stroke}" stroke-width="2" stroke-linejoin="round"/>')
    for i in range(6):
        xr, yr = pt(R * max(3, min(100, vals[i])) / 100, angles[i])
        parts.append(f'<circle cx="{xr:.1f}" cy="{yr:.1f}" r="2.5" fill="{stroke}"/>')
        lx, ly = pt(R * 1.42, angles[i])
        # 标签防截断：左右标签居中显示（不贴边延伸），上下标签 y 偏移留边距
        if i in (0, 3):
            anchor = "middle"
            dy = 4 if i == 0 else -2
        else:
            anchor = "middle"
            dy = 0
        parts.append(f'<text x="{lx:.1f}" y="{ly + dy:.1f}" style="fill:var(--radar-label)" font-size="8" text-anchor="{anchor}" font-weight="600">{labels[i]}</text>')
    parts.append(f'<text x="{cx:.1f}" y="{cy+1:.1f}" style="fill:var(--radar-score)" font-size="20" font-weight="800" text-anchor="middle">{score:.1f}</text>')
    parts.append(f'<text x="{cx:.1f}" y="{cy+13:.1f}" style="fill:var(--radar-sub)" font-size="7" text-anchor="middle">总分</text>')
    return f'<svg viewBox="0 0 {size} {size}" style="width:{size}px;height:{size}px;flex:0 0 auto">{chr(10).join(parts)}</svg>'

# ---------------- 池 ----------------
pool = L.build_pool(verbose=False)
pool_all = A.pool_all
def get_pool_df(k):
    ddf = pool.get(k)
    if ddf is None:
        ddf = pool_all.get(k)
    return ddf

def load_hist_df(c):
    """基金等 data_hist 标的（净值型，无 volume）"""
    k = ("sh" if c.startswith(("6", "5")) else "sz") + c
    f = BASE / "data_hist" / f"{c}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f, dtype={"date": str})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < 250:
        return None
    return V.compute_factors_full(df).set_index("date")

def load_fund_cache_df(c):
    """全市场基金净值（fund_nav_cache，净值型）"""
    f = BASE / "fund_nav_cache" / f"{c}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f, dtype={"净值日期": str})
    s = pd.Series(pd.to_numeric(df["单位净值"], errors="coerce").values,
                  index=pd.to_datetime(df["净值日期"])).dropna()
    if len(s) < 400:
        return None
    d = pd.DataFrame({"open": s.values, "high": s.values, "low": s.values,
                      "close": s.values, "volume": 0.0, "amount": 0.0}, index=s.index)
    return V.compute_factors_full(d)

def load_etf_df(c):
    """普适版 ETF（data_full sh5/sz1）"""
    k = ("sh" if c.startswith(("5", "6")) else "sz") + c
    f = BASE / "data_full" / f"{k}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f, dtype={"date": str})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < 400:
        return None
    return V.compute_factors_full(df).set_index("date")

idx = V.load_index(200).set_index('date')
all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
rebal21 = [d for d in all_days[::21]]
prev_rebal = [d for d in rebal21 if d < all_days[-1]][-2]   # 上次完整再平衡（档位变化对比）
last_day = all_days[-1]                                     # 08-14

# 个人版自选池：用户固定池（15 股，2026-08-19 用户调整：去 002463沪电/000636风华【已清仓】+ 4 只基金【已清仓 008254/018036/002891/024239】，
# 加 300806斯迪克；2026-08-18 调整：去 002474榕基软件/300308中际旭创/300476胜宏科技/300502新易盛，加 002820桂发祥/002971和远气体/603629利通电子，
# 2026-08-18 晚间再去 002384东山精密/603986兆易创新/601138工业富联；2026-08-17 去 ETF）
MAIN_CODES = ['600498','600183','002185','605358','603228','603339','605189','600403','002879','600162','000759',
              '002820','002971','603629','300806','002463','000636']
# 2026-08-20 用户决策：固定池中/长线单独拎出独立视图 + 加回 002463沪电股份/000636风华高科 监控
# （8/19 曾因"清仓离场"从 watchlist 移除，现用户要求恢复监控；watchlist 已同步 17 只）
ETFS = []   # 2026-08-17 用户决策：去 ETF
FUNDS = []   # 2026-08-19 用户清仓全部基金（008254/018036/002891/024239）

# 普适版自动池：按板块互补分层（main 主板10 / gem 创业板10 / star 科创板10 / etf 10 / fund 10），
# 档间不重复，与个人版池也不重复——每档恰好 10 只唯一标的
def _is_board(code, board):
    """精确板块判断（股票）"""
    if board == "main":
        return code.startswith(("sh60", "sz00", "sz002"))
    if board == "gem":
        return code.startswith("sz30")
    if board == "star":
        return code.startswith(("sh688", "sh689"))
    return False

def v9_rank_board(board, top_n=10, exclude=(), mom_min=0.25, score_min=65):
    """按板块互补取 TopN（v9 规则），exclude=已占用裸代码（去重，支持 sh600xxx 与 600xxx 混用）"""
    excl = {c[-6:] for c in exclude}
    cand = []
    for code, ddf in A.pool_all.items():
        if code[-6:] in excl:
            continue
        if not _is_board(code, board):
            continue
        if last_day not in ddf.index:
            continue
        r = ddf.loc[last_day]
        if pd.isna(r['close']) or r['close'] <= 0 or pd.isna(r['mom_12_1']):
            continue
        if r['close'] < 2.0:
            continue
        if pd.isna(r['amt20']) or r['amt20'] < 5e6:
            continue
        if r['mom_12_1'] < mom_min:
            continue
        if pd.isna(r['ma200_pos']) or r['ma200_pos'] <= 0:
            continue
        sc = V.score_row_v2(r)  # 2026-08-18 A80_M80 替换：Aroon 强趋势过滤
        if sc < score_min:
            continue
        cand.append((code, sc))
    cand.sort(key=lambda kv: -kv[1])
    return [c for c, _ in cand[:top_n]]

# 个人版已占用标的（普适版避开，杜绝两表重复）
_v8_used = set(MAIN_CODES) | set(ETFS) | set(FUNDS)

# 按板块互补取 Top10（档间 + 与个人版均不重复）
V9_MAIN = v9_rank_board("main", 10, exclude=_v8_used)       # 主板 10
V9_GEM  = v9_rank_board("gem", 10, exclude=_v8_used | set(V9_MAIN))   # 创业板 10
V9_STAR = v9_rank_board("star", 10, exclude=_v8_used | set(V9_MAIN) | set(V9_GEM))  # 科创板 10
# 2026-08-17 用户决策：全池去 ETF（etf 分层移除，不再从 etf_top_pool.json 取）
V9_ETF = []
# 普适版基金 Top10（避开个人版 4 只基金；从缓存读）
_fund_pool_f = BASE / "fund_top_pool.json"
# 2026-08-19 用户决策：榜上=买入清单——基金组上榜必须达中长线买入条件（score_row_v2≥60，轻仓加仓及以上），
# 不达标不上榜、不凑数；达标几只算几只（今日 10 只基金 Aroon 深负全部 <60 → 基金组为空属正常）。
def _fund_buy_score(c):
    """基金中长线买入分（score_row_v2 @ 最新净值日）"""
    _d = load_fund_cache_df(c)
    if _d is None or len(_d) == 0:
        return None
    _r = _d.loc[_d.index[-1]]
    if pd.isna(_r["close"]) or _r["close"] <= 0:
        return None
    return float(V.score_row_v2(_r))

if _fund_pool_f.exists():
    _fund_pool = json.load(open(_fund_pool_f, encoding="utf-8"))
    _fund_qual = []
    for x in _fund_pool["top"]:
        c = x["code"]
        if c in FUNDS:
            continue
        _s = _fund_buy_score(c)
        if _s is not None and _s >= 60:
            _fund_qual.append((c, _s))
    _fund_qual.sort(key=lambda kv: -kv[1])
    V9_FUND = [c for c, _ in _fund_qual[:10]]
else:
    V9_FUND = FUNDS[:]
# 普适版分层清单（股票按权限 + 基金，供监控表按类型/权限过滤；2026-08-17 去 etf 层）
V9_TIERS = {
    "main": [k[-6:] for k in V9_MAIN],
    "gem":  [k[-6:] for k in V9_GEM],
    "star": [k[-6:] for k in V9_STAR],
    "fund": V9_FUND,
}
# 普适版监控池全集（分层，不去重——同一标的多档出现属正常）
V9_CODES = V9_TIERS["main"] + V9_TIERS["gem"] + V9_TIERS["star"] + V9_TIERS["fund"]

# 权限映射：main=主板 / gem=创业板 / star=科创板 / fund（2026-08-17 去 etf）
PERM_OF = {}
for c in MAIN_CODES: PERM_OF[c] = "main"
for c in FUNDS:      PERM_OF[c] = "fund"
# 普适版按板块映射权限（用于普适版表权限过滤）
for c in V9_CODES:
    PERM_OF[c] = ("star" if c.startswith("688") else ("gem" if c.startswith("30") else "main"))

ALL_CODES = list(dict.fromkeys(MAIN_CODES + ETFS + FUNDS + V9_CODES))   # 去重，details 每只一份
# pool 标签：用户固定池优先（600183 等重叠标的归个人版展示，普适版表经 V9_TIERS 引用其数据）
OVERLAP = sorted(set(MAIN_CODES) & set(V9_CODES))
POOL_TAG = {c: ("v8" if c in MAIN_CODES + ETFS + FUNDS else "v9") for c in ALL_CODES}

# ---------------- 标的详情 ----------------
# 交易历史（两体系）
tr_auto = pd.read_csv(BASE / "v9_auto_trades.csv")
tr_lite = pd.read_csv(BASE / "v8_lite_trades.csv")

details = {}
_eff_dates = []   # 2026-08-18 as_of 口径修复：收集池内标的实际最新交易日（池数据尾行，非 index 硬编码）
for c in ALL_CODES:
    k = ("sh" if c.startswith(("6", "5")) else "sz") + c
    if c in FUNDS:
        ddf = load_hist_df(c)              # 个人版基金：data_hist 净值
    elif c in V9_FUND:
        ddf = load_fund_cache_df(c)        # 普适版基金：fund_nav_cache 净值
    else:
        ddf = get_pool_df(k)               # 股票：data_full（2026-08-17 去 ETF）
    if ddf is None or len(ddf) == 0:
        continue
    # 最新收盘（08-14 或该标的最新）
    eff = ddf.index[-1]
    _eff_dates.append(eff)
    r = ddf.loc[eff]
    px = float(r["close"])
    if pd.isna(px) or px <= 0:
        continue
    if c in V9_FUND:
        # 2026-08-19 用户决策：基金组上榜=达中长线买入条件（score_row_v2≥60），展示口径统一为买入分/买入档位，
        # 不再用基金动量分「动量强/中/弱」档位（避免两套分数双口径混乱）；未达标基金已不入 V9_FUND。
        sc = float(V.score_row_v2(r))
        sc_prev = float(V.score_row_v2(ddf.loc[prev_rebal])) if prev_rebal in ddf.index else None
    else:
        sc = float(V.score_row_v2(r))  # 2026-08-18 A80_M80 替换：Aroon 强趋势过滤
        sc_prev = float(V.score_row_v2(ddf.loc[prev_rebal])) if prev_rebal in ddf.index else None
    # 档位（基金组同样用买入档位，2026-08-19 用户决策统一口径）
    _tier_f = tier
    sc_now = sc
    # 当日涨跌幅（最后两日）
    chg = float(ddf["close"].iloc[-1] / ddf["close"].iloc[-2] - 1) * 100 if len(ddf) >= 2 else None
    # 近一年
    ret_1y = float(px / ddf["close"].iloc[-252] - 1) * 100 if len(ddf) > 252 else None
    # 年线（MA200）偏离%（2026-08-18 口径对照：监控分看 20 日短期、池信号看年线位置，
    # 两套会给同一标的相反结论——如榕基短期反抽分高但年线下方-19.8%。页面据此展示「年线下方」依据）
    ma200_dev = None
    if not pd.isna(px) and len(ddf) >= 200:
        _m200 = ddf["close"].rolling(200).mean().iloc[-1]
        if not pd.isna(_m200) and _m200 > 0:
            ma200_dev = round((px / _m200 - 1) * 100, 1)
    # 四因子拆分（最新）
    fs = factor_split(r)
    # 六类 comp（模板口径：趋势/动能/量能/超买/风控/研报）——四因子映射 + 波动率风控 + 无研报
    vol20_raw = float(r["vol20"]) if not pd.isna(r["vol20"]) else None
    comp = {
        "trend": fs["trend"] if fs["trend"] is not None else 50,
        "momentum": fs["mom"] if fs["mom"] is not None else 50,
        "volume": fs["vp"],
        "osc": fs["aroon"],
        "risk": round(100 - min(100.0, (vol20_raw or 0.5) * 250), 1) if vol20_raw is not None else 50,
        "news": 0.0,
    }
    radar_svg = svg_radar(comp, sc_now)
    # RSI
    rsi = float(rsi14(ddf["close"]).iloc[-1])
    # K线 250 日（缩到 60 点）
    kl = ddf.tail(250)
    step = max(1, len(kl) // 60)
    kline = [{"d": str(dt.date()), "o": round(float(o), 2), "h": round(float(h), 2),
              "l": round(float(lo), 2), "c": round(float(cl), 2)}
             for dt, o, h, lo, cl in zip(kl.index[::step], kl["open"][::step], kl["high"][::step],
                                         kl["low"][::step], kl["close"][::step])]
    # 因子历史（近 250 日，缩 40 点：score/mom/trend）
    fh = []
    sub = ddf.tail(250)
    step2 = max(1, len(sub) // 40)
    for dt in sub.index[::step2]:
        rr = ddf.loc[dt]
        if pd.isna(rr["mom_12_1"]):
            continue
        fh.append({"d": str(dt.date()), "score": round(float(V.score_row_v2(rr)), 1),
                   "mom": round(float(rr["mom_12_1"]) * 100, 1)})
    # 交易历史（两体系）
    th_auto = tr_auto[tr_auto["symbol"] == k]
    th_lite = tr_lite[tr_lite["symbol"] == k]
    def tlist(df):
        return [{"e": str(x["entry_date"]), "x": str(x["exit_date"]),
                 "pct": round(float(x["pnl_pct"]), 1), "days": int(x["holding_bars"])}
                for _, x in df.iterrows()]
    _board = ("基金" if (c in FUNDS or c in V9_FUND) else ("ETF" if (k.startswith(("sh5", "sz1")) or c in V9_ETF) else ("创业板" if c.startswith("30") else ("科创板" if k.startswith("sh688") else "主板"))))
    _nm = (FUND_NAMES.get(c) if (c in FUNDS or c in V9_FUND) else None) or names.get(k, c)
    _industry = ETF_INDUSTRY.get(c) or INDUSTRY.get(c)
    if not _industry:
        _industry = ind_by_name(_nm)   # 2026-08-19：不再一律「综合」，按名称关键词归具体行业
    # 短线分（v5.8）：同一标的池的短线视角——股票用反转版、ETF/基金用动量版（v2/v3 回测验证）
    _sf = SH.short_factors(ddf)
    _sr = _sf.iloc[-1]
    short_sc = float(SH.short_score(_sr, reversal=(_board in ("主板", "创业板", "科创板"))))
    short_tier = tier(short_sc)
    details[c] = {
        "code": c, "key": k,
        # 名称按资产类型解析（2026-08-18 彻查修复）：基金名只对真基金代码生效——002474 这类
        # 股票/基金撞号（榕基软件 vs 中邮睿信增强债券A）不能对股票套用基金名
        "name": (FUND_NAMES.get(c) if (c in FUNDS or c in V9_FUND) else None) or names.get(k, c),
        "pool": POOL_TAG.get(c, "v8"),   # v8=个人版自选池 / v9=普适版自动池
        "perm": PERM_OF.get(c, "main"),  # main/gem/star/etf/fund 权限档
        "board": _board,
        "industry": _industry, "biz": BIZ.get(c, "—"),
        "px": round(px, 2), "chg": round(chg, 2) if chg is not None else None,
        "ret_1y": round(ret_1y, 1) if ret_1y is not None else None,
        "score": round(sc_now, 1), "score_prev": round(sc_prev, 1) if sc_prev is not None else None,
        "tier": _tier_f(sc_now), "tier_prev": _tier_f(sc_prev) if sc_prev is not None else None,
        "short_score": round(short_sc, 1), "short_tier": short_tier,
        "ma200_dev": round(ma200_dev, 1) if ma200_dev is not None else None,
        "factors": fs, "comp": comp, "radar_svg": radar_svg, "rsi": round(rsi, 1),
        "kline": kline, "factor_hist": fh,
        "trades": {"v9_auto": tlist(th_auto), "v8_lite": tlist(th_lite)},
    }

# ---------------- 两体系 KPI/曲线 ----------------
def load_curve(f):
    df = pd.read_csv(BASE / f)
    v = df["value"].astype(float).values
    return v / v[0] * 100


# ---------------- 全量池中/长线年跟踪池（2026-08-17 用户需求） ----------------
def maintain_track_v9():
    """上榜跟踪 1 年：v9_tiers 上榜标的自动入池。
    规则（2026-08-18 用户拍板：昨日收盘上池标的信号隔离 + 每次重新上榜刷新入池/跟踪/出池时间；
          2026-08-19 用户拍板：进标的池=默认全买 → 隔日无论是否仍在榜一律转正式，保证跟踪卖出信号）：
      新上榜/再上榜 → 当日先入 pending（不入正式池，不参与信号），下一个收盘无条件转正式入池；
      持续在池 → 保持 entry，更新 last_seen/exit；掉出池保留最后快照；entry 满 365 天 → 移除；
      每次转正式/重新上榜 → entry=确认收盘日、last_seen=今日、exit=entry+365（三个时间刷新）。
    返回 (track, pending)：track 只含正式池成员（渲染直接遍历），pending 独立字段不入正式池。"""
    today = str(_as_of_day.date())
    old, old_pending, old_tiers = {}, {}, {}
    try:
        _old = json.loads((BASE / "enhanced_data.js").read_text(encoding="utf-8")[len("window.ENH = "):-1])
        old = _old.get("track_v9", {}) or {}
        old_pending = _old.get("track_pending_v9", {}) or {}
        old_tiers = _old.get("meta", {}).get("v9_tiers", {}) or {}
    except Exception:
        pass
    today_codes = {c for codes in V9_TIERS.values() for c in codes} | set(MAIN_CODES) | set(ETFS) | set(FUNDS)
    # 2026-08-19 用户需求：中长线固定池（MAIN_CODES 15 只）并入全量池跟踪池 track_v9，
    # 统一跟踪卖出信号（掉出池也保留快照等卖出），生成时间由固定池不再独立维护跟踪而减少
    track = dict(old)
    pending = dict(old_pending)
    from datetime import timedelta
    def _exit(e):
        return str((pd.Timestamp(e) + timedelta(days=365)).date())
    # 迁移：旧 track 补齐 exit/status（新字段）
    for code, rec in list(track.items()):
        rec.setdefault("exit", _exit(rec.get("entry", today)))
        rec.setdefault("status", "active")
        rec.setdefault("last_seen", rec.get("last_seen") or today)
    # 0) 固定池/基金池标的：无条件入正式池（用户长期自选/持仓，不走 pending 待确认，
    #    保证固定池始终在 track_v9 内跟踪卖出信号；entry=今日、exit=+365，掉出 V9 榜也保留）
    for code in set(MAIN_CODES) | set(ETFS) | set(FUNDS):
        d = details.get(code, {}) or {}
        rec = track.get(code)
        snap = {"px": d.get("px"), "chg": d.get("chg"), "score": d.get("score"),
                "tier": d.get("tier"), "date": today}
        if rec is None:
            track[code] = {"entry": today, "last_seen": today, "exit": _exit(today), "status": "active",
                           "pool": d.get("board", ""), "type": "fund" if (code in FUNDS) else "stock",
                           "last": snap, "first_seen": today}
        else:
            rec["last_seen"] = today
            rec["status"] = "active"
            rec["pool"] = d.get("board", rec.get("pool", ""))
            if d:
                rec["last"] = snap
            track[code] = rec
            pending.pop(code, None)
    # 1) 今日在榜标的
    for code in today_codes:
        d = details.get(code, {}) or {}
        snap = {"px": d.get("px"), "chg": d.get("chg"), "score": d.get("score"),
                "tier": d.get("tier"), "date": today}
        rec = track.get(code)
        if rec is None:
            # 未在正式池 → pending（本次先登记，明/后一收盘确认在榜再转正）
            if d:
                pe = pending.get(code)
                if pe is None:
                    pending[code] = {"entry_candidate": today, "pool": d.get("board", ""),
                                     "last": snap, "first_seen": today}
                else:
                    pe["last"] = snap          # 已在 pending：刷新快照
        else:
            # 已在正式池 → 持续/再上榜
            was_on = code in [c for v in old_tiers.values() for c in v]
            if not was_on and str(rec.get("last_seen", "")) < today:
                rec["entry"] = today           # 掉榜后重新上榜 → 刷新入池时间
            rec["last_seen"] = today           # 更新跟踪时间
            rec["exit"] = _exit(rec.get("entry", today))  # 出池时间 = entry+365
            rec["status"] = "active"
            if d:
                rec["last"] = snap
            track[code] = rec
            pending.pop(code, None)
    # 2) 旧 pending → 正式：隔日无论是否仍在榜一律转正式
    #    （2026-08-19 用户拍板：进标的池=默认全买 → 必须跟踪卖出信号 → 掉榜也须入池跟踪）
    for code in list(old_pending.keys()):
        if code in track:
            continue
        if code not in pending:
            continue                        # 已在 1) 今日在榜处理并转过正式
        d = details.get(code, {}) or {}
        pe = pending.get(code) or old_pending[code]
        entry = today                       # 确认收盘日
        track[code] = {"entry": entry, "last_seen": today, "exit": _exit(entry),
                       "status": "active",
                       "pool": pe.get("pool", d.get("board", "")),
                       "first_seen": pe.get("first_seen", str(_as_of_day.date())),
                       "last": pe.get("last") or {"px": d.get("px"), "chg": d.get("chg"),
                                        "score": d.get("score"), "tier": d.get("tier"), "date": today}}
        pending.pop(code, None)
    # 3) 正式池中今日不在榜：保留快照、不动 entry（365 自动出池）
    # 4) 清理 entry 满 365 天（出池时间 = entry+365）与 pending 超期（7 天未确认丢弃；
    #    ⚠ 不再因「今日不在榜」清除 pending——隔日已无条件转正式，滞留 pending 的只有今日新上榜待明日转正的）
    cutoff = pd.Timestamp(last_day.date() - timedelta(days=365))
    track = {c: r for c, r in track.items()
             if pd.Timestamp(str(r.get("entry", today))) > cutoff}
    pending = {c: r for c, r in pending.items()
               if pd.Timestamp(str(r.get("entry_candidate", today))) > cutoff}
    # 5) 名称（2026-08-18 修复：掉出池标的常不在 details；资产类型按 rec.pool 判定防撞号）
    for code, rec in track.items():
        k = ("sh" if code.startswith(("6", "5")) else "sz") + code
        if rec.get("pool") == "基金":
            rec["name"] = (FUND_NAMES.get(code)
                           or (details.get(code, {}) or {}).get("name")
                           or names.get(k) or code)
        else:
            rec["name"] = (details.get(code, {}) or {}).get("name") or names.get(k, code)
    # 6) 刷新全部正式池成员快照（2026-08-19 修复：掉榜标的 last 只在离榜那天刷新，之后 px/chg 永远旧数据）。
    #    details 只含「今日在榜 + 固定池」标的，掉榜标的须回 A.pool_all（全部 data_full）/基金净值缓存重算——
    #    只要底层 data_full 有最新收盘，看板掉榜标的涨跌就跟着刷新；底层没更新时保留旧快照（数据层由 update_daily 覆盖）。
    def _snap_from_data(_c):
        _d = details.get(_c, {})
        if _d:
            return {"px": _d.get("px"), "chg": _d.get("chg"), "score": _d.get("score"),
                    "tier": _d.get("tier"), "date": today}
        _k = ("sh" if _c.startswith(("6", "5")) else "sz") + _c
        _df = A.pool_all.get(_k)
        if (_df is None or len(_df) == 0) and _c in V9_FUND:
            _df = load_fund_cache_df(_c)
        if _df is None or len(_df) == 0:
            return None
        _eff = _df.index[-1]
        _r = _df.loc[_eff]
        _px = float(_r["close"])
        if pd.isna(_px) or _px <= 0:
            return None
        _chg = float(_df["close"].iloc[-1] / _df["close"].iloc[-2] - 1) * 100 if len(_df) >= 2 else None
        _sc = float(V.score_row_v2(_r))
        _tierf = tier
        return {"px": round(_px, 2), "chg": round(_chg, 2) if _chg is not None else None,
                "score": round(_sc, 1), "tier": _tierf(_sc), "date": str(_eff.date())}
    _refreshed = 0
    for code, rec in track.items():
        _snap = _snap_from_data(code)
        if _snap:
            rec["last"] = _snap
            _refreshed += 1
    print(f"全量池中/长线跟踪池: {len(track)} 只（正式） + {len(pending)} 只（待确认，隔日入池），快照刷新 {_refreshed} 只", flush=True)
    return track, pending


_a80_json = json.load(open(BASE / "v9_auto_a80.json", encoding="utf-8"))
s_auto = _a80_json["summary"]   # 2026-08-18 v5.11.15：A80_M80 Aroon 强趋势过滤
s_lite = json.load(open(BASE / "v8_lite_summary.json", encoding="utf-8"))["summary"]

v_auto = _a80_json["eq"]   # A80_M80 equity（绝对值，直接取值）
v_lite = load_curve("v8_lite_equity.csv")

# 历史报告列表
REPORTS_DIR = Path("D:/Documents/Obsidian/WorkBuddy/wiki/02-投资研究-Investment")
reports = sorted([f.name for f in REPORTS_DIR.glob("research-*.md")], reverse=True)

# 2026-08-18 as_of 口径修复：数据截至 = 池内标的实际最新交易日（取 max(ddf.index[-1])），
# 而非 index_000300.csv 硬编码尾行（该指数文件手工维护易滞后，曾致 as_of 显示 08-17 但个股已含 08-18）
_as_of_day = max(_eff_dates) if _eff_dates else last_day
_track, _pending = maintain_track_v9()
out = {
    "meta": {"as_of": str(_as_of_day.date()), "generated": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"), "overlap": OVERLAP,
             "v9_tiers": V9_TIERS},
    "nav": [["overview", "📊", "监控总览"], ["sys-auto", "🅰️", "全量池中/长线"], ["sys-lite", "🅱️", "固定池中/长线"], ["short", "⚡", "全量池短线"], ["table", "📋", "标的监控表"]],
    "track_v9": _track, "track_pending_v9": _pending,
    "monitor_reports": [
        {"code": c, "name": d["name"], "tier": d["tier"]}
        for c, d in sorted(details.items(), key=lambda kv: -kv[1]["score"])
    ],
    "systems": {
        "v9_auto": {"label": "普适版", "badge": "全市场自动池 · 无人工选池 · Aroon强趋势过滤(A80_M80)",
                     "summary": s_auto, "equity": [round(float(x), 2) for x in v_auto]},
        "v8_lite": {"label": "个人版", "badge": "自选池 40 只 · 权限分层 · Top4 轮动",
                     "summary": s_lite, "equity": [round(float(x), 2) for x in v_lite]},
    },
    "details": details,
    "reports": reports,
}
js = "window.ENH = " + json.dumps(out, ensure_ascii=False) + ";"
(BASE / "enhanced_data.js").write_text(js, encoding="utf-8")
print(f"enhanced_data.js 生成: {len(details)} 只标的 + 2 体系 + {len(reports)} 篇报告 ({(BASE/'enhanced_data.js').stat().st_size/1024:.0f} KB)")
n_v8 = len([c for c in MAIN_CODES + ETFS + FUNDS if c in details])
n_v9 = len([c for c in V9_CODES if c in details])
print(f"  个人版自选池: {n_v8}/{len(MAIN_CODES)+len(ETFS)+len(FUNDS)} | 普适版自动池(分层去重): {n_v9}（main {len(V9_MAIN)} / gem {len(V9_GEM)} / star {len(V9_STAR)}）")