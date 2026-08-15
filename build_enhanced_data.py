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

# ---------------- 池 ----------------
pool = L.build_pool(verbose=False)
pool_all = A.pool_all
def get_pool_df(k):
    ddf = pool.get(k)
    if ddf is None:
        ddf = pool_all.get(k)
    return ddf
idx = V.load_index(200).set_index('date')
all_days = [d for d in idx.index if V.START <= str(d.date()) <= V.END]
rebal21 = [d for d in all_days[::21]]
prev_rebal = [d for d in rebal21 if d < all_days[-1]][-2]   # 上次完整再平衡（档位变化对比）
last_day = all_days[-1]                                     # 08-14

ALL_CODES = ['300502','300308','600498','601138','002463','002384','600183','300476','603986',
             '002185','605358','603228','603339','000636','605189','600403','002879','600162','000759','002474',
             '159516','515880','516150','560390','159841',
             '600641','688082','688549','601208','603078','603083','603186','603773','603989','688143']

# ---------------- 标的详情 ----------------
# 交易历史（两体系）
tr_auto = pd.read_csv(BASE / "v9_auto_trades.csv")
tr_lite = pd.read_csv(BASE / "v8_lite_trades.csv")

details = {}
for c in ALL_CODES:
    k = ("sh" if c.startswith(("6", "5")) else "sz") + c
    ddf = get_pool_df(k)
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
        "code": c, "key": k, "name": names.get(k, c),
        "board": "ETF" if k.startswith(("sh5", "sz1")) else ("创业板" if c.startswith("30") else ("科创板" if k.startswith("sh688") else "主板")),
        "industry": INDUSTRY.get(c, "—"), "biz": BIZ.get(c, "—"),
        "px": round(px, 2), "chg": round(chg, 2) if chg is not None else None,
        "ret_1y": round(ret_1y, 1) if ret_1y is not None else None,
        "score": round(sc_now, 1), "score_prev": round(sc_prev, 1) if sc_prev is not None else None,
        "tier": tier(sc_now), "tier_prev": tier(sc_prev) if sc_prev is not None else None,
        "factors": fs, "rsi": round(rsi, 1),
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
    "meta": {"as_of": "2026-08-14", "generated": "2026-08-15 21:00"},
    "nav": [["overview", "📊", "监控总览"], ["sys-auto", "🅰️", "普适版"], ["sys-lite", "🅱️", "个人版"], ["table", "📋", "标的监控表"]],
    "monitor_reports": [
        {"code": c, "name": d["name"], "tier": d["tier"]}
        for c, d in sorted(details.items(), key=lambda kv: -kv[1]["score"])
    ],
    "systems": {
        "v9_auto": {"label": "v9-auto 普适版", "badge": "全市场自动池 · 无人工选池",
                     "summary": s_auto, "equity": [round(float(x), 2) for x in v_auto]},
        "v8_lite": {"label": "v8-lite 个人版", "badge": "固定自选池 25 只 · Top4 轮动",
                     "summary": s_lite, "equity": [round(float(x), 2) for x in v_lite]},
    },
    "details": details,
    "reports": reports,
}
js = "window.ENH = " + json.dumps(out, ensure_ascii=False) + ";"
(BASE / "enhanced_data.js").write_text(js, encoding="utf-8")
print(f"enhanced_data.js 生成: {len(details)} 只标的 + 2 体系 + {len(reports)} 篇报告 ({(BASE/'enhanced_data.js').stat().st_size/1024:.0f} KB)")
print(f"  自选池: {len([c for c in ALL_CODES[:25] if c in details])}/25 | v9 Top10: {len([c for c in ALL_CODES[25:] if c in details])}/10")
