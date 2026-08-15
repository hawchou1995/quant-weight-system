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

names = json.load(open(BASE / "data_full_names.json", encoding="utf-8"))

# 行业映射（模板 v6 口径自选池 + westock profile v9 Top10）
INDUSTRY = {
    '516150': '稀土', '002474': '软件服务', '600162': '地产服务', '560390': '电网设备',
    '603339': '冷链设备', '515880': '通信', '600498': '通信设备', '601138': '电子制造',
    '600403': '煤炭', '000636': 'MLCC', '600183': '覆铜板', '603228': 'PCB',
    '300476': 'PCB', '024239': 'QDII科技', '159516': '半导体设备', '018036': '新能源车',
    '002891': '移动互联', '605358': '半导体硅片', '605189': '纺织印染', '008254': 'QDII混合',
    '300502': '光模块', '014002': '智能科技', '603986': '半导体', '002384': '电子制造',
    '002463': 'PCB', '002185': '半导体封测', '000759': '商业零售', '300308': '光模块',
    '002879': '电线电缆', '159841': '证券',
    '600641': '电子', '688082': '电子', '688549': '电子', '601208': '基础化工',
    '603078': '电子', '603083': '通信', '603186': '电子', '603773': '电子',
    '603989': '电子', '688143': '通信',
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
}

# 基金名称（data_hist 净值，data_full_names 无基金名）
FUND_NAMES = {
    '008254': '华宝致远混合C', '018036': '长城新能源车股C', '002891': '华夏移动互联CNY',
    '024239': '华夏全球QDII C', '014002': '浦银智能科技C', '020900': '天弘通信设备C',
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
def svg_radar(comp, score, size=104):
    """六角雷达，与模板 monitor/render_dashboard.py svg_radar_light 一致"""
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
        lx, ly = pt(R * 1.22, angles[i])
        anchor = "middle"
        if abs(math.cos(angles[i])) > 0.7:
            anchor = "start" if lx > cx else "end"
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" style="fill:var(--radar-label)" font-size="8" text-anchor="{anchor}" font-weight="600">{labels[i]}</text>')
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

# 普适版自动池：按权限分层，从全市场 v9 规则各取 Top10（main 主板10 / gem 主板+创业板10 / star 全A 10）
def v9_rank_by_perm(perm, top_n=10, mom_min=0.25, score_min=65, rsi_max=85):
    """v9 完整筛池规则（与 run_auto 一致），按权限取 TopN"""
    cand = []
    for code, ddf in A.pool_all.items():
        if not A.board_filter(code, perm):
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

V9_MAIN = v9_rank_by_perm("main", 10)   # 主板 10 只
V9_GEM  = v9_rank_by_perm("gem", 10)    # 主板+创业板 10 只
V9_STAR = v9_rank_by_perm("star", 10)   # 全A 10 只
# 普适版 ETF Top10（全市场 ETF 四因子打分，无权限限制）
_etf_pool = json.load(open(BASE / "etf_top_pool.json", encoding="utf-8"))
V9_ETF = [x["code"] for x in _etf_pool["top"][:10]]
# 普适版基金 Top10（全市场基金净值打分，无权限限制；从缓存读，若不存在则回退用户 6 只）
_fund_pool_f = BASE / "fund_top_pool.json"
if _fund_pool_f.exists():
    _fund_pool = json.load(open(_fund_pool_f, encoding="utf-8"))
    V9_FUND = [x["code"] for x in _fund_pool["top"][:10]]
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
    elif c in V9_ETF:
        ddf = load_etf_df(c)               # 普适版 ETF：data_full sh5/sz1
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
    details[c] = {
        "code": c, "key": k, "name": FUND_NAMES.get(c, names.get(k, c)),
        "pool": POOL_TAG.get(c, "v8"),   # v8=个人版自选池 / v9=普适版自动池
        "perm": PERM_OF.get(c, "main"),  # main/gem/star/etf/fund 权限档
        "board": ("基金" if (c in FUNDS or c in V9_FUND) else ("ETF" if (k.startswith(("sh5", "sz1")) or c in V9_ETF) else ("创业板" if c.startswith("30") else ("科创板" if k.startswith("sh688") else "主板")))),
        "industry": INDUSTRY.get(c, "—"), "biz": BIZ.get(c, "—"),
        "px": round(px, 2), "chg": round(chg, 2) if chg is not None else None,
        "ret_1y": round(ret_1y, 1) if ret_1y is not None else None,
        "score": round(sc_now, 1), "score_prev": round(sc_prev, 1) if sc_prev is not None else None,
        "tier": tier(sc_now), "tier_prev": tier(sc_prev) if sc_prev is not None else None,
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
