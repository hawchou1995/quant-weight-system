# -*- coding: utf-8 -*-
"""
KHunter 模拟盘（A/C 双轨）看板快照生成器
==========================================
为网页看板提供 KHunter 优化配置模拟盘（实盘前验证）的实时快照：
- A 轨：熊市出场 RSI>55（默认配置，khunter_paper_state.json）
- C 轨：熊市出场 RSI>50（激进版，khunter_paper_state_c.json）
- 回测证据（khunter_all_strategies_results.json —— 15 策略基础信号）
产出：dist/khunter_paper_snapshot.json（构建器读取）
"""
import os, sys, json
from pathlib import Path
import pandas as pd

BASE = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
OUT = BASE / "dist" / "khunter_paper_snapshot.json"

NAMES = {}
_names_f = BASE / "data_full_names.json"
if _names_f.exists():
    NAMES = json.loads(_names_f.read_text(encoding="utf-8"))

# 生产口径（与 khunter_paper_20260903.py 一致）
INIT_CAP = 100000.0
RSI_BUY = 35
RSI_BUY_BULL = 30
RSI_BUY_WEAK = 32
LOW_PRICE = 3.0
N_SLOTS = 5
POS_SIZE = 20000.0
HOLD_MAX = 25
COST = 0.00575


def _load_track(state_file):
    """读取单个模拟盘轨道的状态，提取持仓/净值/交易统计"""
    track = {"track": None, "nav": None, "cum": None, "px_chg": None,
             "last_date": None, "start": None, "positions": [], "cash": None,
             "pending_buys": [], "pending_sells": [], "n_trades": 0,
             "trades": [], "note": ""}
    if not state_file.exists():
        track["note"] = "状态文件不存在"
        return track
    st = json.loads(state_file.read_text(encoding="utf-8"))
    track["start"] = st.get("start")
    nh = st.get("nav_history", [])
    if nh:
        track["last_date"] = nh[-1]["date"]
        track["nav"] = round(nh[-1]["nav"], 2)
        track["cum"] = round((nh[-1]["nav"] / INIT_CAP - 1) * 100, 2)
        if len(nh) >= 2:
            track["px_chg"] = round((nh[-1]["nav"] / nh[-2]["nav"] - 1) * 100, 3)
    track["cash"] = round(st.get("cash", 0), 2)
    track["positions"] = []
    for p in st.get("positions", []):
        _px = p.get("last_close") or p.get("entry_px") or 0
        _entry = p.get("entry_px") or 0
        _pl_pct = round((_px / _entry - 1) * 100, 2) if _entry and _px else None
        track["positions"].append({
            "code": p.get("code"), "name": NAMES.get(p.get("code"), p.get("code")),
            "shares": p.get("shares"), "entry_px": _entry,
            "last_close": p.get("last_close"), "entry_date": p.get("entry_date"),
            "hold_days": p.get("hold_days", 0), "rsi_entry": p.get("rsi_entry"),
            "pl_pct": _pl_pct,
        })
    track["pending_buys"] = st.get("pending_buys", [])
    track["pending_sells"] = st.get("pending_sells", [])
    track["trades"] = st.get("trades", [])
    track["n_trades"] = len(track["trades"])
    track["hold_over_codes"] = st.get("hold_over_codes", [])
    return track


def main():
    # 1. A/C 双轨状态
    a = _load_track(BASE / "khunter_paper_state.json")
    a["track"] = "A"
    a["note"] = "熊市出场 RSI>55 · 沪深300<MA60 熊市限定 · RSI<35 超卖买入 · 收盘≥3元 · 最多5仓×¥20,000"
    c = _load_track(BASE / "khunter_paper_state_c.json")
    c["track"] = "C"
    c["note"] = "熊市出场 RSI>50（较 A 版早离场）· 其余与 A 轨相同"

    # 2. 回测证据（15 策略基础信号 3 实现版本：v8 原值 / hold10 / hold20）
    bt = {}
    bt_json = BASE / "backtest" / "khunter_all_out" / "khunter_all_strategies_results.json"
    if bt_json.exists():
        d = json.loads(bt_json.read_text(encoding="utf-8"))
        # 汇总：各策略各自最优（按 mean 排序取 hold 最优）→ 一个代表行
        rows = []
        for sname, arr in d.items():
            if not arr:
                continue
            best = max(arr, key=lambda x: (x.get("mean") or -99))
            rows.append({
                "strategy": sname,
                "hold": best.get("hold"),
                "n": best.get("n"),
                "win_rate": best.get("win_rate"),
                "mean": best.get("mean"),
                "median": best.get("median"),
                "excess_mean": best.get("excess_mean"),
                "sharpe": best.get("sharpe"),
                "pass": best.get("pass"),
            })
        bt = {"n_strategies": len(d), "rows": rows,
              "note": "各策略=自身最优持有期；mean>0 且 sharpe>0 才为 PASS（四闸口径）"}
    else:
        bt = {"n_strategies": 0, "rows": [], "note": "回测结果文件不存在"}

    # 3. 生产口径摘要
    config = {
        "rsi_buy": RSI_BUY, "rsi_buy_bull": RSI_BUY_BULL, "rsi_buy_weak": RSI_BUY_WEAK,
        "low_price": LOW_PRICE, "n_slots": N_SLOTS, "pos_size": POS_SIZE,
        "hold_max": HOLD_MAX, "cost": COST, "init_cap": INIT_CAP,
    }

    snap = {"config": config, "tracks": {"A": a, "C": c}, "bt": bt,
            "generated_at": str(pd.Timestamp.now())}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ KHunter 模拟盘快照已生成: {OUT}")
    for k, t in (("A", a), ("C", c)):
        print(f"   {k}轨: NAV {t['nav']} · 累计 {t['cum']}% · 持仓 {len(t['positions'])} 只 · {t['last_date']}")
    print(f"   回测: {bt.get('n_strategies')} 策略 · {len(bt.get('rows', []))} 行汇总")


if __name__ == "__main__":
    main()
