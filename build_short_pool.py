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

# 名称
NAMES = json.load(open(BASE / "data_full_names.json", encoding="utf-8"))
# 现有 80 只详情（复用行业/名称）
JS = open(BASE / "enhanced_data.js", encoding="utf-8").read()
ENH = json.loads(JS[len("window.ENH = "):-1])
EXIST = ENH["details"]

# 基金名（akshare）
def fund_names():
    try:
        import akshare as ak
        df = ak.fund_name_em()
        return dict(zip(df["基金代码"], df["基金简称"]))
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

def buy_tier(sc):
    """短线买入口径（信号池专用）：回测 score≥50 即买 → 两态买入档"""
    if sc >= 60: return "强买入"
    if sc >= 50: return "买入"
    return "不买"

def rsi14(close):
    d = close.diff()
    up = d.clip(lower=0).rolling(14).mean()
    dn = (-d.clip(upper=0)).rolling(14).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

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
    rows_by_board = {"主板": [], "创业板": [], "科创板": []}
    for code, ddf in stock_pool.items():
        if as_of is not None:
            if as_of not in ddf.index:
                continue
            r = ddf.loc[as_of]
        else:
            r = ddf.iloc[-1]
        if pd.isna(r["close"]) or r["close"] <= 0 or pd.isna(r["mom20"]):
            continue
        nm = NAMES.get(code, code[-6:])
        if "ST" in nm or nm.startswith("S") or "退" in nm:
            continue
        if r["close"] < 1.5:   # 退市股/仙股过滤
            continue
        sc = S.short_score(r, reversal=True)
        if pd.isna(sc):
            continue
        bd = board_of(code)
        if bd not in rows_by_board:
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
        # 2026-08-19 市况门控：门控关闭 → 清空股票买入信号（不开新仓），与回测口径一致
        if _in_mkt:
            rows_by_board[bd] = [kv for kv in rows_by_board[bd] if kv[1] >= 50][:10]
        else:
            rows_by_board[bd] = []
        print(f"股票[{bd}] 买入信号 {len(rows_by_board[bd])} 只（分≥50，不凑数）({time.time()-t0:.0f}s)", flush=True)
    stock_top_main = rows_by_board["主板"]
    stock_top_gem  = rows_by_board["创业板"]
    stock_top_star = rows_by_board["科创板"]
    stock_top = stock_top_main + stock_top_gem + stock_top_star

    # 2) ETF 动量 Top10（2026-08-17 用户决策移除：ETF 表现不佳，短线池去 ETF）
    etf_top = []

    # 3) 基金动量 Top10
    fund_pool = S.load_fund_pool(3000)
    frows = []
    for code, ddf in fund_pool.items():
        if as_of is not None:
            if as_of not in ddf.index:
                continue
            r = ddf.loc[as_of]
        else:
            r = ddf.iloc[-1]
        if pd.isna(r["close"]) or r["close"] <= 0 or pd.isna(r["mom20"]):
            continue
        sc = S.short_score(r, reversal=False)
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
    fund_top = [kv for kv in frows if kv[1] >= 50][:10]
    print(f"基金池 买入信号 {len(fund_top)} 只（分≥50，不凑数）({time.time()-t0:.0f}s)", flush=True)

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
            industry = ex["industry"]
        else:
            name = NAMES.get(code, bare)
            if board == "ETF":
                industry = etf_ind(name)
            elif board == "基金":
                fnn = fnames.get(bare, NAMES.get(code, bare))
                industry = ind_by_name(fnn)   # 2026-08-19：基金不再一律「综合」，按真实基金名归主题/风格
                name = fnn
            else:
                industry = STK_IND.get(bare, "综合")
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
            "tier": buy_tier(sc), "tier_prev": None,
            "short_score": round(sc, 1), "short_tier": buy_tier(sc),
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
    # 2026-08-17 修复：as_of 取股票数据最新交易日（主口径），基金净值 T-1 单独标注
    _stock_tail = max((ddf.index[-1] for ddf in stock_pool.values() if len(ddf)), default=None)
    _fund_tail = max((ddf.index[-1] for ddf in fund_pool.values() if len(ddf)), default=None)
    _eff = as_of if as_of is not None else (str(_stock_tail.date()) if _stock_tail is not None else "—")
    out = {"as_of": _eff, "fund_as_of": str(_fund_tail.date()) if _fund_tail is not None else _eff,
           "details": details, "tiers": order, "market_gate": market_gate}
    sigs = {"as_of": out["as_of"], "stock": sig_stock, "etf": sig_etf, "fund": sig_fund}
    return out, sigs


def build(as_of=None):
    """计算并写文件（short_pool.js / short_signals.js / short_pool.json）"""
    out, sigs = calc_signals(as_of)
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
    _today_codes = {c for c, d in out["details"].items() if (d.get("short_score") or 0) >= 50}
    # ① 回溯上次构建的池：昨天在池且可买入、今天掉出的标的，按上次 as_of 补录正式池（用户场景：8/14 第一位 8/17 掉出仍可跟踪）
    for _bd, _codes in _old_tiers.items():
        for _c in _codes:
            if _c not in track and _c not in pending:
                _od = (_old_full.get("details", {}) or {}).get(_c, {})
                if (_od.get("short_score") or 0) >= 50:
                    _e0 = _old_full.get("as_of") or today
                    track[_c] = {"entry": _e0, "last_seen": _e0, "exit": _exit(_e0), "status": "active",
                                 "pool": _bd, "type": "fund" if _bd == "基金" else "stock"}
    # ② 当前池可买入标的
    for code, d in out["details"].items():
        if (d.get("short_score") or 0) < 50:
            continue
        _bd = d.get("board", "")
        _snap = {"name": d.get("name"), "score": d.get("short_score"), "tier": d.get("short_tier") or d.get("tier"),
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
            _hist_out, _ = calc_signals(as_of="2026-08-14")
            for _c, _d in _hist_out["details"].items():
                if (_d.get("short_score") or 0) >= 50 and _c not in track:
                    track[_c] = {"entry": "2026-08-14", "last_seen": "2026-08-14", "exit": _exit("2026-08-14"), "status": "active",
                                 "pool": _d.get("board", ""), "type": "fund" if _d.get("board") == "基金" else "stock"}
            out["_backfilled_0814"] = True
            print(f"8/14 池历史补偿完成，正式跟踪池累计 {len(track)} 只、待确认 {len(pending)} 只", flush=True)
        except Exception as _e:
            print("8/14 池历史补偿失败:", _e, flush=True)
    # ④ pending 兜底：只按 30 天到期清理；不再因「今日不在池」清除（隔日已无条件转正式的标的不该滞留 pending；
    #     留在 pending 的只有「今日新上榜待明日转正」的，强制保留以便隔日入池跟踪卖出）
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=30)
    pending = {c: v for c, v in pending.items() if pd.Timestamp(v.get("entry_candidate", today)) > cutoff}
    track = {c: v for c, v in track.items() if pd.Timestamp(v.get("entry", today)) > cutoff}
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