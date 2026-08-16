# -*- coding: utf-8 -*-
"""短线信号标的池（v5.10）：全市场最新交易日短线分 Top 池
================================================================
- 股票：反转版短线分 Top10（全市场 data_full）
- ETF：动量版短线分 Top10（全市场 sh5/sz1）
- 基金：动量版短线分 Top10（fund_nav_cache，与回测同池）
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

    # 1) 股票反转 Top10（剔除 ST/*ST/S 股——反转信号选到 ST = 接飞刀）
    stock_pool = S.load_stock_pool()
    rows = []
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
        rows.append((code, float(sc), r, ddf))
        _tail2 = ddf.loc[:as_of] if as_of is not None else ddf
        sig_stock[code[-6:]] = {"name": nm, "px": round(float(r["close"]), 2),
                                "chg": round(float(r["close"] / (_tail2["close"].iloc[-2] if as_of else ddf["close"].iloc[-2]) - 1) * 100, 2),
                                "score": round(float(sc), 1), "tier": tier_of(float(sc)),
                                "ma5_above": bool(not pd.isna(r.get("ma5", np.nan)) and r["close"] > r["ma5"])}
    rows.sort(key=lambda kv: -kv[1])
    print(f"股票池 {len(stock_pool)} 只 → 反转分 Top10（剔 ST/退市 {len(stock_pool)-len(rows)} 只）({time.time()-t0:.0f}s)", flush=True)
    stock_top = rows[:10]

    # 2) ETF 动量 Top10
    etf_pool = S.load_etf_pool()
    erows = []
    for code, ddf in etf_pool.items():
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
        erows.append((code, float(sc), r, ddf))
        _tail2 = ddf.loc[:as_of] if as_of is not None else ddf
        sig_etf[code[-6:]] = {"name": NAMES.get(code, code[-6:]), "px": round(float(r["close"]), 2),
                              "chg": round(float(r["close"] / (_tail2["close"].iloc[-2] if as_of else ddf["close"].iloc[-2]) - 1) * 100, 2),
                              "score": round(float(sc), 1), "tier": tier_of(float(sc)),
                              "ma5_above": bool(not pd.isna(r.get("ma5", np.nan)) and r["close"] > r["ma5"])}
    erows.sort(key=lambda kv: -kv[1])
    print(f"ETF 池 {len(etf_pool)} 只 → 动量分 Top10 ({time.time()-t0:.0f}s)", flush=True)
    etf_top = erows[:10]

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
    print(f"基金池 {len(fund_pool)} 只 → 动量分 Top10 ({time.time()-t0:.0f}s)", flush=True)
    fund_top = frows[:10]

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
                industry = "综合"
                name = fnames.get(bare, bare)
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
    order = {"股票": [c[-6:] for c, _, _, _ in stock_top],
             "ETF": [c[-6:] for c, _, _, _ in etf_top],
             "基金": [c[-6:] for c, _, _, _ in fund_top]}
    _eff = as_of if as_of is not None else str(ddf.index[-1].date())
    out = {"as_of": _eff, "details": details, "tiers": order}
    sigs = {"as_of": out["as_of"], "stock": sig_stock, "etf": sig_etf, "fund": sig_fund}
    return out, sigs


def build(as_of=None):
    """计算并写文件（short_pool.js / short_signals.js / short_pool.json）"""
    out, sigs = calc_signals(as_of)
    json.dump(out, open(BASE / "short_pool.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    with open(BASE / "short_pool.js", "w", encoding="utf-8") as f:
        f.write("window.SHORT_POOL = " + json.dumps(out, ensure_ascii=False) + ";")
    with open(BASE / "short_signals.js", "w", encoding="utf-8") as f:
        f.write("window.SHORT_SIGNALS = " + json.dumps(sigs, ensure_ascii=False) + ";")
    print(f"全市场信号 {len(sig_stock)}+{len(sig_etf)}+{len(sig_fund)} 只 → short_signals.js", flush=True)

if __name__ == "__main__":
    import time
    time = __import__("time")
    import argparse
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--as-of", default=None, help="信号日 YYYY-MM-DD（默认最新交易日）")
    _args = _ap.parse_args()
    build(as_of=_args.as_of)