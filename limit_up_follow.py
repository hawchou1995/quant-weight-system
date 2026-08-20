# -*- coding: utf-8 -*-
"""涨停次日跟随观察层（2026-08-20 新增 · 纯观察，不进主策略/主池）
=====================================================================
背景：8/20 医药板块批量涨停，反转型短线池（生产口径）抓不到"首次起爆日"。
本层做【观察】：
  1. 扫描全池 data_full 最新收盘：当日涨停的票（主板/中小板 ≥9.5%、创业板/科创板 ≥19.5%）
  2. 输出"次日观察池"：涨停票的 名称/代码/行业/板块/前日涨幅/是否连板/现价/近60日涨停次数
  3. 生成 limit_up_follow.json 供看板「⚡ 涨停次日跟随（观察）」卡片渲染
⚠ 语义：仅"观察/提醒"，不入评分主池、不下买入指令；T+1 是否可参与看次日开盘（高开>3% 不追）。
"""
import os, json, sys
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import short_engine as S

# 行业映射（复用 enhanced_data 明细行业，缺失则查申万/名称关键词）
STK_IND = {}
try:
    js = (BASE / "enhanced_data.js").read_text(encoding="utf-8")
    ENH = json.loads(js[len("window.ENH = "):-1])
    for code, d in ENH["details"].items():
        STK_IND[code] = d.get("industry", "")
except Exception:
    pass

# 增强行业关键词库（补全不够细的）
EXT_KEY = [
    # 医药
    ("药","医药生物"), ("生物","医药生物"), ("医疗","医药生物"), ("医","医药生物"),
    ("疫苗","医药生物"), ("创新药","医药生物"), ("制药","医药生物"), ("药业","医药生物"),
    ("生物制品","医药生物"), ("CRO","医药生物"), ("基因","医药生物"), ("细胞","医药生物"),
    ("检测","医药生物"), ("诊断","医药生物"), ("体外","医药生物"), ("血液","医药生物"),
    # 半导体/电子
    ("半导","电子"), ("芯片","电子"), ("集成","电子"), ("微电","电子"), ("光电","电子"),
    ("科技","计算机"), ("软件","计算机"), ("数据","计算机"), ("AI","计算机"), ("智能","计算机"),
    ("通信","通信"), ("光模块","通信"), ("光通信","通信"), ("网络","通信"),
    ("证券","非银金融"), ("保险","非银金融"), ("银行","银行"), ("地产","房地产"), ("物业","房地产"),
    ("新能源","电力设备"), ("光伏","电力设备"), ("电池","电力设备"), ("锂","电力设备"), ("储能","电力设备"),
    ("风电","电力设备"), ("电网","电力设备"), ("特高压","电力设备"),
    ("稀土","有色金属"), ("黄金","有色金属"), ("有色","有色金属"), ("铜","有色金属"), ("钴","有色金属"),
    ("化工","基础化工"), ("材料","基础化工"), ("塑料","基础化工"), ("轮胎","基础化工"),
    ("机器人","机械设备"), ("机械","机械设备"), ("装备","机械设备"), ("工业母机","机械设备"),
    ("汽车","汽车"), ("整车","汽车"), ("零部件","汽车"),
    ("军工","国防军工"), ("国防","国防军工"), ("航空","国防军工"), ("航天","国防军工"),
    ("白酒","食品饮料"), ("食品","食品饮料"), ("饮料","食品饮料"), ("乳业","食品饮料"),
    ("农业","农林牧渔"), ("养殖","农林牧渔"), ("种业","农林牧渔"), ("饲料","农林牧渔"), ("畜牧","农林牧渔"),
    ("传媒","传媒"), ("游戏","传媒"), ("出版","传媒"),
    ("纺织","纺织服饰"), ("服装","纺织服饰"), ("家纺","纺织服饰"),
    ("电力","公用事业"), ("燃气","公用事业"), ("水务","公用事业"),
    ("家电","家用电器"), ("家居","轻工制造"), ("家居","轻工制造"), ("造纸","轻工制造"), ("包装","轻工制造"),
    ("建材","建筑材料"), ("水泥","建筑材料"), ("玻璃","建筑材料"), ("钢铁","钢铁"),
    ("煤炭","煤炭"), ("石油","石油石化"), ("石化","石油石化"),
    ("零售","商贸零售"), ("商业","商贸零售"), ("百货","商贸零售"), ("免税","商贸零售"),
    ("物流","交通运输"), ("航运","交通运输"), ("港口","交通运输"), ("航空机场","交通运输"), ("海运","交通运输"),
    ("旅游","社会服务"), ("酒店","社会服务"), ("餐饮","社会服务"),
    ("美容","美容护理"), ("医美","美容护理"),
    ("综合","综合"), ("股份","综合"), ("集团","综合"),
]

def etf_ind(name):  # 兜底
    for kw, ind in EXT_KEY:
        if kw in name:
            return ind
    return "综合"

def board_of(code):
    if code.startswith(("sh688", "sh689")): return "科创板"
    if code.startswith("sz30"): return "创业板"
    if code.startswith(("sh6", "sz00", "sz002")): return "主板"
    if code.startswith(("sh5", "sz1")): return "ETF"
    return "其他"

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None, help="信号日 YYYY-MM-DD（默认 data_full 最新交易日）")
    ap.add_argument("--quotes", default=None, help="盘中 quotes json（code->{px,chg}），用当日实时价判定涨停（盘中模式）")
    args = ap.parse_args()

    pool = S.load_stock_pool()
    # 确定"信号日" = 全池最新交易日众数（若指定 day 且 quotes 则用 day 的实时价）
    from collections import Counter
    lastdays = Counter(str(ddf.index[-1].date()) for ddf in pool.values())
    as_of = args.day or lastdays.most_common(1)[0][0]
    print(f"信号日 as_of = {as_of}（data_full 众数={lastdays.most_common(1)[0][0]}，{len(lastdays)} 种尾部）", flush=True)

    # 盘中 quotes（可覆盖当日涨跌判定）
    quotes = {}
    if args.quotes:
        try:
            qd = json.load(open(args.quotes, encoding="utf-8"))
            quotes = qd.get("quotes", {})
            print(f"盘中 quotes 载入 {len(quotes)} 只（{args.quotes}）", flush=True)
        except Exception as e:
            print(f"⚠ quotes 载入失败: {e}，仅用 data_full", flush=True)

    names = {}
    try:
        import json as _j
        nmf = _j.load(open(BASE / "data_full_names.json", encoding="utf-8"))
        names = nmf
    except Exception:
        pass

    ups = []
    for code, ddf in pool.items():
        if len(ddf) < 30:
            continue
        bare = code[-6:]
        # 当日涨跌：优先盘中 quotes（--day 当日），否则 data_full 末日
        q = quotes.get(bare)
        if q is not None and args.day:
            chg = q.get("chg")
            px = q.get("px")
            if chg is None:
                continue
            chg = (chg if isinstance(chg, float) else float(chg)) / 100.0
            prev = ddf.iloc[-1]["close"]
            board = board_of(code)
            thresh = 0.195 if board in ("创业板", "科创板") else 0.095
            if chg < thresh:
                continue
            nm = names.get(bare, names.get(code, code[-6:]))
            if "ST" in str(nm).upper() or "退" in str(nm):
                continue
            ind = STK_IND.get(bare, STK_IND.get(code, "")) or etf_ind(str(nm)) or "综合"
            ups.append({"code": bare, "name": str(nm), "board": board, "industry": ind,
                        "px": round(float(px), 2), "chg": round(chg * 100, 2),
                        "streak": 1, "limit_60d": 0, "intraday": True})
            continue
        # data_full 收盘口径
        if str(ddf.index[-1].date()) != as_of:
            continue
        r = ddf.iloc[-1]
        prev = ddf.iloc[-2]
        if r["close"] <= 0 or prev["close"] <= 0:
            continue
        chg = r["close"] / prev["close"] - 1
        board = board_of(code)
        thresh = 0.195 if board in ("创业板", "科创板") else 0.095
        if chg < thresh:
            continue
        # 剔除 ST / 退市
        nm = names.get(code[-6:], names.get(code, code[-6:]))
        if "ST" in str(nm).upper() or "退" in str(nm):
            continue
        # 连板：最近 2 日是否都涨停
        y2 = ddf.iloc[-2]
        y3 = ddf.iloc[-3] if len(ddf) >= 3 else None
        prev_chg = None
        streak = 1
        if y3 is not None and y2["close"] > 0 and y3["close"] > 0:
            pc = y2["close"] / y3["close"] - 1
            if pc >= thresh:
                streak = 2
        # 近60日涨停次数
        c = ddf["close"].values
        ups60 = int((c[1:] / c[:-1] - 1 > thresh).sum()) if len(c) > 60 else int((c[1:] / c[:-1] - 1 > thresh).sum())
        ind = STK_IND.get(code[-6:], STK_IND.get(code, ""))
        if not ind:
            ind = etf_ind(str(nm))
        ups.append({
            "code": code[-6:], "name": str(nm), "board": board,
            "industry": ind or "综合",
            "px": round(float(r["close"]), 2),
            "chg": round(chg * 100, 2),
            "streak": streak, "limit_60d": ups60,
        })
    ups.sort(key=lambda x: (-x["streak"], -x["chg"]))
    print(f"当日涨停 {len(ups)} 只（阈值：主板≥9.5% / 创科≥19.5%）", flush=True)

    out = {"as_of": as_of, "note": "纯观察层：涨停次日跟随（不进评分主池、不下指令；T+1 低开或高开<3% 才考虑关注）",
           "items": ups}
    with open(BASE / "limit_up_follow.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    for u in ups[:15]:
        print(f"  {u['code']} {u['name']:<10} {u['board']} {u['industry']} +{u['chg']}% 连板{u['streak']} 近60日涨停{u['limit_60d']}")
    print(f"\n已写 limit_up_follow.json（{len(ups)} 只）")

if __name__ == "__main__":
    main()
