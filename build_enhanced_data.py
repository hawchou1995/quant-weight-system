# -*- coding: utf-8 -*-
"""增强数据准备：30 只标的详情（因子拆分/当日涨跌/档位变化/K线/交易历史）+ 两体系 KPI/曲线"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
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
    # ---- 个人版基金 ----
    '008254': '综合', '018036': '电力设备', '002891': '传媒', '024239': '综合',
    '014002': '电子', '020900': '通信',
    # ---- 普适版基金（按投资方向归申万一级，均衡型归综合）----
    '000742': '综合', '001060': '机械设备', '001198': '综合', '001411': '电子',
    '001470': '综合', '001723': '综合', '001759': '综合', '002051': '电子',
    '002163': '综合', '002289': '综合',
    # ---- ETF（按跟踪指数主题归申万一级，宽基归综合）----
    '159516': '电子', '515880': '通信', '516150': '有色金属', '159841': '非银金融',
    '560390': '电力设备', '159502': '医药生物', '513290': '医药生物', '159513': '综合',
    '512990': '综合', '159517': '综合', '515160': '综合', '159655': '综合',
    '159620': '综合', '561950': '综合', '159703': '基础化工',
}
BIZ = {
    '600641': '集成电路/光伏核心装备', '688082': '半导体清洗设备', '688549': '电子湿化学品/特气',
    '601208': '绝缘材料/化工新材料', '603078': '湿电子化学品', '603083': 'ICT终端(光模块/交换机)',
    '603186': '覆铜板/复合材料', '603773': 'FPD光电玻璃精加工', '603989': '电容器及材料', '688143': '光纤环/惯性导航',
    '300502': '光模块', '300308': '光模块', '600498': '光通信设备', '601138': '服务器代工/AI硬件',
    '002463': 'PCB(高多层)', '002384': '精密制造/PCB', '600183': '覆铜板', '300476': 'PCB',
    '603986': '存储芯片', '002185': '半导体封测', '605358': '半导体硅片', '603228': 'PCB',
    '603339': '集装箱/冷链装备', '000636': 'MLCC', '605189': '染整', '600403': '煤炭',
    '002879': '电缆附件', '600162': '园区地产', '000759': '商超零售', '002474': '软件',
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

# 基金名称（data_hist/fund_nav_cache 净值，data_full_names 无基金名；普适版基金为全市场 Top10）
FUND_NAMES = {
    '008254': '华宝致远混合C', '018036': '长城新能源车股C', '002891': '华夏移动互联CNY',
    '024239': '华夏全球QDII C', '014002': '浦银智能科技C', '020900': '天弘通信设备C',
    '000742': '国泰新经济混合A', '001060': '前海开源高端装备A', '001198': '东方惠新混合A',
    '001411': '诺安创新驱动A', '001470': '融通通鑫混合', '001723': '华商新动力A',
    '001759': '嘉实成长增强混合', '002051': '诺安创新驱动C', '002163': '东方惠新混合C',
    '002289': '华商改革创新股票A',
}

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

# 个人版自选池：用户原始固定池（20 股 + 5 ETF = v8_lite 口径，不动） + 6 只基金
MAIN_CODES = ['300502','300308','600498','601138','002463','002384','600183','300476','603986',
              '002185','605358','603228','603339','000636','605189','600403','002879','600162','000759','002474']
ETFS = ['159516','515880','516150','560390','159841']
FUNDS = ['008254','018036','002891','024239','014002','020900']

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
        sc = V.score_row(r)
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
# 普适版 ETF Top10（避开个人版 5 只 ETF）
_etf_pool = json.load(open(BASE / "etf_top_pool.json", encoding="utf-8"))
V9_ETF = [x["code"] for x in _etf_pool["top"] if x["code"] not in ETFS][:10]
# 普适版基金 Top10（避开个人版 6 只基金；从缓存读）
_fund_pool_f = BASE / "fund_top_pool.json"
if _fund_pool_f.exists():
    _fund_pool = json.load(open(_fund_pool_f, encoding="utf-8"))
    V9_FUND = [x["code"] for x in _fund_pool["top"] if x["code"] not in FUNDS][:10]
else:
    V9_FUND = FUNDS[:]
# 普适版分层清单（股票按权限 + ETF + 基金，供监控表按类型/权限过滤）
V9_TIERS = {
    "main": [k[-6:] for k in V9_MAIN],
    "gem":  [k[-6:] for k in V9_GEM],
    "star": [k[-6:] for k in V9_STAR],
    "etf":  V9_ETF,
    "fund": V9_FUND,
}
# 普适版监控池全集（分层，不去重——同一标的多档出现属正常）
V9_CODES = V9_TIERS["main"] + V9_TIERS["gem"] + V9_TIERS["star"] + V9_TIERS["etf"] + V9_TIERS["fund"]

# 权限映射：main=主板 / gem=创业板 / star=科创板 / etf / fund
PERM_OF = {}
for c in MAIN_CODES: PERM_OF[c] = "main"
for c in ETFS:       PERM_OF[c] = "etf"
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
for c in ALL_CODES:
    k = ("sh" if c.startswith(("6", "5")) else "sz") + c
    if c in FUNDS:
        ddf = load_hist_df(c)              # 个人版基金：data_hist 净值
    elif c in V9_FUND:
        ddf = load_fund_cache_df(c)        # 普适版基金：fund_nav_cache 净值
    elif c in V9_ETF or c in ETFS:
        ddf = load_etf_df(c)               # 普适版/个人版 ETF：data_full sh5/sz1
        if ddf is None:
            ddf = load_hist_df(c)          # fallback：data_hist 净值
    else:
        ddf = get_pool_df(k)               # 股票：data_full
    if ddf is None or len(ddf) == 0:
        continue
    # 最新收盘（08-14 或该标的最新）
    eff = ddf.index[-1]
    r = ddf.loc[eff]
    px = float(r["close"])
    if pd.isna(px) or px <= 0:
        continue
    sc = float(V.score_row(r))
    # 当日涨跌幅（最后两日）
    chg = float(ddf["close"].iloc[-1] / ddf["close"].iloc[-2] - 1) * 100 if len(ddf) >= 2 else None
    # 近一年
    ret_1y = float(px / ddf["close"].iloc[-252] - 1) * 100 if len(ddf) > 252 else None
    # 档位（本次 vs 上次再平衡）
    sc_now = sc
    sc_prev = None
    if prev_rebal in ddf.index:
        sc_prev = float(V.score_row(ddf.loc[prev_rebal]))
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
        fh.append({"d": str(dt.date()), "score": round(float(V.score_row(rr)), 1),
                   "mom": round(float(rr["mom_12_1"]) * 100, 1)})
    # 交易历史（两体系）
    th_auto = tr_auto[tr_auto["symbol"] == k]
    th_lite = tr_lite[tr_lite["symbol"] == k]
    def tlist(df):
        return [{"e": str(x["entry_date"]), "x": str(x["exit_date"]),
                 "pct": round(float(x["pnl_pct"]), 1), "days": int(x["holding_bars"])}
                for _, x in df.iterrows()]
    _board = ("基金" if (c in FUNDS or c in V9_FUND) else ("ETF" if (k.startswith(("sh5", "sz1")) or c in V9_ETF) else ("创业板" if c.startswith("30") else ("科创板" if k.startswith("sh688") else "主板"))))
    _industry = ETF_INDUSTRY.get(c) or INDUSTRY.get(c)
    if not _industry:
        _industry = "综合"   # 统一体系兜底：一律归「综合」，不分板块各玩各的
    # 短线分（v5.8）：同一标的池的短线视角——股票用反转版、ETF/基金用动量版（v2/v3 回测验证）
    _sf = SH.short_factors(ddf)
    _sr = _sf.iloc[-1]
    short_sc = float(SH.short_score(_sr, reversal=(_board in ("主板", "创业板", "科创板"))))
    short_tier = tier(short_sc)
    details[c] = {
        "code": c, "key": k, "name": FUND_NAMES.get(c, names.get(k, c)),
        "pool": POOL_TAG.get(c, "v8"),   # v8=个人版自选池 / v9=普适版自动池
        "perm": PERM_OF.get(c, "main"),  # main/gem/star/etf/fund 权限档
        "board": _board,
        "industry": _industry, "biz": BIZ.get(c, "—"),
        "px": round(px, 2), "chg": round(chg, 2) if chg is not None else None,
        "ret_1y": round(ret_1y, 1) if ret_1y is not None else None,
        "score": round(sc_now, 1), "score_prev": round(sc_prev, 1) if sc_prev is not None else None,
        "tier": tier(sc_now), "tier_prev": tier(sc_prev) if sc_prev is not None else None,
        "short_score": round(short_sc, 1), "short_tier": short_tier,
        "factors": fs, "comp": comp, "radar_svg": radar_svg, "rsi": round(rsi, 1),
        "kline": kline, "factor_hist": fh,
        "trades": {"v9_auto": tlist(th_auto), "v8_lite": tlist(th_lite)},
    }

# ---------------- 两体系 KPI/曲线 ----------------
def load_curve(f):
    df = pd.read_csv(BASE / f)
    v = df["value"].astype(float).values
    return v / v[0] * 100

s_auto = json.load(open(BASE / "v9_auto_summary.json", encoding="utf-8"))["summary"]
s_lite = json.load(open(BASE / "v8_lite_summary.json", encoding="utf-8"))["summary"]

v_auto = load_curve("v9_auto_equity.csv")
v_lite = load_curve("v8_lite_equity.csv")

# 历史报告列表
REPORTS_DIR = Path("D:/Documents/Obsidian/WorkBuddy/wiki/02-投资研究-Investment")
reports = sorted([f.name for f in REPORTS_DIR.glob("research-*.md")], reverse=True)

out = {
    "meta": {"as_of": "2026-08-14", "generated": "2026-08-15 23:20", "overlap": OVERLAP,
             "v9_tiers": V9_TIERS},
    "nav": [["overview", "📊", "监控总览"], ["sys-auto", "🅰️", "普适版"], ["sys-lite", "🅱️", "个人版"], ["table", "📋", "标的监控表"]],
    "monitor_reports": [
        {"code": c, "name": d["name"], "tier": d["tier"]}
        for c, d in sorted(details.items(), key=lambda kv: -kv[1]["score"])
    ],
    "systems": {
        "v9_auto": {"label": "普适版", "badge": "全市场自动池 · 无人工选池",
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
