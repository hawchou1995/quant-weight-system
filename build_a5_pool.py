# -*- coding: utf-8 -*-
"""
A5_tp8t2 实验系统 → 看板数据桥（2026-08-28 投产，双轨方案 v1.1）
读 打板系统A5实验_20260827/paper_state.json → 生成 a5_pool.js（window.A5_POOL）

设计要点：
- 单一数据源：直接读打板目录，不复制；A5 模拟盘状态由 paper_daban_a5.py 维护
- 回避清单：无状态每日全市场扫描，复用 paper_daban_a5.scan_avoid_list 保证与扫描器口径逐位一致
- 验证门基准（2026-08-28 修正）：**全部信号口径**（46.1%/-0.17%/21.5%）——
  模拟盘扫描器无每日≤5/情绪门控逻辑，实际执行=全部信号，基准与执行必须同口径
- 回测数据：全部信号 n=1116 + 组合信号 n=625 + 组合净值 -72.2%（如实展示）

用法：python build_a5_pool.py     （收盘管道 refresh_daily.py 第 6 步调用）
输出：a5_pool.js（window.A5_POOL）
"""
import os, sys, json, glob, time
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
A5_DIR = r"D:/Documents/Workbuddy/股票基金/打板系统A5实验_20260827"
sys.path.insert(0, A5_DIR)
import paper_daban_a5 as P  # 复用 read_tail/compute_tail_features/scan_avoid_list/is_pool_code

# ---------- 技术指标（观察/回避/持仓表展示，2026-08-28 用户需求） ----------
def rsi14(close):
    """RSI14（与 build_short_pool.rsi14 同口径）"""
    close = np.asarray(close, dtype=float)
    d = np.diff(close)
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    if len(up) < 14:
        return None
    au = up[-14:].mean(); ad = dn[-14:].mean()
    if ad == 0:
        return 100.0 if au > 0 else 50.0
    rs = au / ad
    return float(100 - 100 / (1 + rs))


def tech_indicators(code):
    """对单只标的算技术指标（读 Quant data 全量 K 线尾部）：
    chg 当日涨跌幅%、ret_1y 近一年(≈250 交易日)涨跌幅%、rsi14、量比(当日量/5日均量)、
    ma5_dev 收盘价偏离 MA5%。返回 dict 或 None（数据不足）。"""
    try:
        import pandas as pd
        f = os.path.join(P.DATA_DIR, code + ".csv")
        if not os.path.exists(f):
            return None
        df = pd.read_csv(f, usecols=["date", "close", "volume"])
        close = df["close"].dropna().astype(float)
        vol = df["volume"].dropna().astype(float)
        if len(close) < 15:
            return None
        out = {}
        out["chg"] = round(float(close.iloc[-1] / close.iloc[-2] - 1) * 100, 2) if len(close) >= 2 else None
        if len(close) >= 251:
            out["ret_1y"] = round(float(close.iloc[-1] / close.iloc[-251] - 1) * 100, 1)
        else:
            out["ret_1y"] = round(float(close.iloc[-1] / close.iloc[0] - 1) * 100, 1)
        out["rsi"] = round(rsi14(close.values), 1)
        if len(vol) >= 6:
            vr = float(vol.iloc[-1] / vol.iloc[-6:-1].mean())
            out["vr"] = round(vr, 2)
        else:
            out["vr"] = None
        ma5 = float(close.iloc[-5:].mean()) if len(close) >= 5 else None
        out["ma5_dev"] = round((float(close.iloc[-1]) / ma5 - 1) * 100, 1) if ma5 else None
        # F3 空间因子（9/3 过闸族）：距 60 日最高收盘的空间%（回测口径 (hi-close)/hi≥0.2 → ≥20）
        if len(close) >= 60:
            hi60 = float(close.iloc[-60:].max())
            out["dist_high60"] = round((hi60 - float(close.iloc[-1])) / hi60 * 100, 1) if hi60 > 0 else None
        else:
            out["dist_high60"] = None
        return out
    except Exception:
        return None


def market_board(code):
    """按代码判定市场板块（2026-08-28 用户需求：与 v9/短线池共用同一分类标准——board=主板/创业板/科创板）：
    主板（沪 600/601/603/605 + 深 000/001/002/003，±10%）、创业板（300/301，±20%）、
    科创板（688/689，±20%）、北交所（8/4/92，±30%）。code 形如 sh600345 / sz001309 / bj830799。"""
    if not code or len(code) < 8:
        return "—"
    pref, num = code[:2], code[2:]
    if not num.isdigit():
        return "—"
    if pref == "sh":
        if num.startswith(("600", "601", "603", "605")):
            return "主板"
        if num.startswith(("688", "689")):
            return "科创板"
        return "沪市"
    if pref == "sz":
        if num.startswith(("000", "001", "002", "003")):
            return "主板"
        if num.startswith(("300", "301")):
            return "创业板"
        return "深市"
    if pref == "bj":
        return "北交所"
    return "—"


def enrich_indicators(items):
    """给观察/回避/持仓列表每项附加技术指标字段（chg/ret_1y/rsi/vr/ma5_dev）+ 市场板块 board"""
    for it in items:
        code = it.get("code", "")
        if not code:
            continue
        it["board"] = market_board(code)
        t = tech_indicators(code)
        if t:
            it.update(t)
    return items


# 验证门基准（全部信号口径，与 paper_daban_a5.py report() 一致；来源 optimize_daban_v1_2026-08-27.json A5_tp8t2.all）
BENCH = {
    "win_rate": 46.1,      # 全部信号胜率
    "mean_net": -0.17,     # 全部信号均值净收益 %
    "tp_ratio": 21.5,      # 全部信号 tp 出场占比 %
    "n": 1116,
}
# 回测完整数据（展示用，来源 optimize_daban_v1_2026-08-27.json A5_tp8t2）
BACKTEST = {
    "all": {"label": "全部信号", "n": 1116, "win_rate": 46.1, "mean_net": -0.17,
            "mean_zero": 0.99, "median": -0.63, "pl_ratio": 1.10, "tp_ratio": 21.5, "avg_hold": 1.06},
    "comb": {"label": "组合信号(≤5/去重/门控)", "n": 625, "win_rate": 45.0, "mean_net": 0.11,
             "mean_zero": 1.27, "tp_ratio": 22.4},
    "port": {"label": "组合净值(等权复利)", "total_return": -72.2, "annual": -27.4,
             "max_dd": -91.4, "sharpe": -0.11, "days": 1004},
}


def load_state():
    f = os.path.join(A5_DIR, "paper_state.json")
    with open(f, encoding="utf-8") as fp:
        return json.load(fp)


def scan_avoid():
    """重算当日回避清单（与扫描器同数据同口径，5s 扫 4435 文件）"""
    names = P.load_names()
    ind_map = P.load_industry()
    feats = {}
    for f in glob.glob(os.path.join(P.DATA_DIR, "*.csv")):
        code = os.path.basename(f)[:-4]
        if not P.is_pool_code(code):
            continue
        if P.is_st_name(names.get(code, "")):
            continue
        rows, at_start = P.read_tail(f)
        if rows is None or len(rows) < 60:
            continue
        feats[code] = P.compute_tail_features(rows, code)
    dates = sorted({d for feat in feats.values() for d in feat["dates"]})
    if not dates:
        return [], None
    D = dates[-1]
    return P.scan_avoid_list(feats, names, ind_map, D), D


def gate_status(stats, n_closed):
    """验证门三闸状态：PASS/观察/FAIL（全部信号基准）"""
    gates = {}
    if n_closed < 30:
        gates["verdict"] = f"信号不足 {n_closed}/30，继续积累"
        for k in ("wr", "mn", "tp"):
            gates[k] = {"status": "waiting", "note": f"{n_closed}/30"}
        return gates
    wr = stats["win_rate"]
    mn = stats["mean_net"]
    tp = stats["tp_ratio"]
    gates["wr"] = {"status": "PASS" if 35 <= wr <= 55 else "FAIL",
                   "note": f"{wr:.1f}%（闸 [35%,55%]）"}
    gates["mn"] = {"status": "PASS" if mn > -0.5 else "FAIL",
                   "note": f"{mn:+.2f}%（闸 >-0.5%）"}
    gates["tp"] = {"status": "PASS" if 12 <= tp <= 32 else "FAIL",
                   "note": f"{tp:.1f}%（闸 [12%,32%]）"}
    if all(g["status"] == "PASS" for g in (gates["wr"], gates["mn"], gates["tp"])):
        gates["verdict"] = "✅ 三闸全过 → 边缘确认，可考虑小仓位实盘（单笔≤1%，总仓≤5%）"
    else:
        failed = [k for k in ("wr", "mn", "tp") if gates[k]["status"] == "FAIL"]
        gates["verdict"] = f"⚠ 未过闸（{', '.join(failed)}）→ 继续观察"
    if mn < -1.0:
        gates["verdict"] += " ｜ ⛔ 均值<-1% → 边缘证伪，建议停止"
    return gates


def build():
    t0 = time.time()
    state = load_state()
    # 回避清单（无状态重算）
    avoid, avoid_d = scan_avoid()
    # 模拟盘统计
    closed = [p for p in state.get("positions", []) if p.get("status") == "closed"]
    open_pos = [p for p in state.get("positions", []) if p.get("status") == "open"]
    # 已平仓列表补板块（渲染「已平仓」表板块列，与三清单同标准）
    for p in closed:
        p["board"] = market_board(p.get("code", ""))
    stats = {"n": len(closed), "win_rate": None, "mean_net": None, "mean_raw": None,
             "tp_ratio": None, "nav": state.get("equity", [{}])[-1].get("nav", 1.0) if state.get("equity") else 1.0}
    if closed:
        rets = np.array([p.get("net_ret", 0) for p in closed])
        raw = np.array([p.get("raw_ret", 0) for p in closed])
        stats.update({
            "win_rate": float((rets > 0).mean() * 100),
            "mean_net": float(rets.mean() * 100),
            "mean_raw": float(raw.mean() * 100),
            "tp_ratio": float(np.mean([p.get("exit_reason") == "tp" for p in closed]) * 100),
        })
    gate = gate_status(stats, len(closed))

    # 技术指标附加（2026-08-28 用户需求：当日涨跌幅/近一年/RSI/量比/MA5偏离）
    watchlist = enrich_indicators(state.get("watchlist", []))
    avoid = enrich_indicators(avoid)
    positions = enrich_indicators(open_pos)

    out = {
        "as_of": state.get("last_scan", "—"),
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "bench": BENCH,
        "backtest": BACKTEST,
        "watchlist": watchlist,
        "avoid": avoid,
        "avoid_as_of": avoid_d,
        "positions": positions,
        "closed": closed,
        "stats": stats,
        "gate": gate,
        "equity": state.get("equity", []),
        # 盘中 patch 标记（2026-08-28）：update_intraday_dashboard.py 盘中重写 a5_pool.js 时置 intraday=True
        "intraday": False,
    }
    with open(os.path.join(BASE, "a5_pool.js"), "w", encoding="utf-8") as f:
        f.write("window.A5_POOL = " + json.dumps(out, ensure_ascii=False) + ";")
    print(f"✅ a5_pool.js 已生成（as_of={out['as_of']} · 观察清单 {len(out['watchlist'])} 只 · "
          f"回避清单 {len(avoid)} 只 · 持仓 {len(open_pos)} · 已平仓 {len(closed)} · "
          f"验证 {gate['verdict']} · 耗时 {time.time()-t0:.0f}s）")
    return out


if __name__ == "__main__":
    build()
