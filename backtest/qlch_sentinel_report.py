# -*- coding: utf-8 -*-
"""R-qlch-sentinel-0923 · X4 出场参数前向哨兵（只读 · 只可否决）

预注册：backtest/PRE-REGISTRATION_20260923_qlch_sentinel.md
- 只读生产账本；不写账本、不改参数、不并入日更链
- 判定规则 V1/V2/V3（冻结）；V4 诊断
用法：python backtest/qlch_sentinel_report.py [--quiet]
产物：backtest/qlch_sentinel_state.json（每日追加一行快照）
"""
import argparse, json, sys, time
from pathlib import Path
import numpy as np

BK = Path(__file__).resolve().parent
LEDGER = BK / "qlch_paper_state_b4_k3.json"
STATE = BK / "qlch_sentinel_state.json"
PREREG = "backtest/PRE-REGISTRATION_20260923_qlch_sentinel.md"
BT = {"mean_net_pct": 9.292, "mdd_pct": -40.99, "val_cagr_pct": 10.49, "stop_share_pct": 2.7}
V = {"V1_min_trades": 20, "V2_mdd_mult": 1.5, "V3_min_days": 60, "V3_cagr_floor": -5.0, "V4_stop_mult": 2.0}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--quiet", action="store_true"); a = ap.parse_args()
    if not LEDGER.exists():
        print("[sentinel] 账本不存在：%s" % LEDGER); return
    st = json.load(open(LEDGER, encoding="utf-8"))
    eq = st.get("equity", []); tr = st.get("trades", [])
    nav = np.array([e.get("nav", 1.0) for e in eq], dtype=float)
    rets = np.array([t.get("net_ret", 0.0) for t in tr], dtype=float)
    days = max(len(nav) - 1, 0)
    mdd = float((nav / np.maximum.accumulate(nav) - 1.0).min() * 100) if nav.size else 0.0
    mean_pct = float(rets.mean() * 100) if rets.size else float("nan")
    stop = sum(1 for t in tr if str(t.get("exit_reason", "")).startswith("止损"))
    exp_ = sum(1 for t in tr if str(t.get("exit_reason", "")).startswith("到期"))
    snap = {"date": eq[-1]["date"] if eq else None, "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "n_trades": int(rets.size), "days": int(days),
            "mean_net_pct": None if rets.size == 0 else round(mean_pct, 4),
            "wr_pct": None if rets.size == 0 else round(float((rets > 0).mean()) * 100, 2),
            "mean_hold": None if not tr else round(float(np.mean([t.get("hold_days", 0) for t in tr])), 2),
            "cum_ret_pct": round(float(nav[-1] - 1.0) * 100, 4) if nav.size else 0.0,
            "mdd_pct": round(mdd, 3),
            "stop_share_pct": round(100.0 * stop / rets.size, 2) if rets.size else None,
            "expiry_share_pct": round(100.0 * exp_ / rets.size, 2) if rets.size else None}
    trig = []
    if snap["n_trades"] >= V["V1_min_trades"] and snap["mean_net_pct"] is not None and snap["mean_net_pct"] <= 0:
        trig.append("V1 单笔均值 ≤ 0（n=%d）" % snap["n_trades"])
    if snap["mdd_pct"] <= V["V2_mdd_mult"] * BT["mdd_pct"]:
        trig.append("V2 回撤 %.2f%% ≤ %.2f%%（回测×1.5）" % (snap["mdd_pct"], V["V2_mdd_mult"] * BT["mdd_pct"]))
    if days >= V["V3_min_days"] and nav.size > 1:
        yrs = max(days / 244.0, 1e-9)
        cagr = ((nav[-1] / nav[0]) ** (1.0 / yrs) - 1.0) * 100 if nav[0] > 0 else 0.0
        snap["cagr_pct"] = round(cagr, 3)
        if cagr <= V["V3_cagr_floor"]:
            trig.append("V3 年化 %.2f%% ≤ %.1f%%（≥%d 交易日）" % (cagr, V["V3_cagr_floor"], V["V3_min_days"]))
    else:
        snap["cagr_pct"] = None
    snap["V4_diag_stop_share_mult"] = (round(snap["stop_share_pct"] / BT["stop_share_pct"], 2)
                                       if snap["stop_share_pct"] is not None and BT["stop_share_pct"] else None)
    snap["triggered"] = trig
    snap["verdict"] = ("复核:" + " / ".join(trig)) if trig else (
        "记录中（未达判定条件：n_trades=%d/%d, days=%d/%d）" % (snap["n_trades"], V["V1_min_trades"],
                                                              days, V["V3_min_days"]))
    snaps = []
    if STATE.exists():
        try: snaps = json.load(open(STATE, encoding="utf-8")).get("snapshots", [])
        except Exception: snaps = []
    snaps.append(snap)
    json.dump({"prereg": PREREG, "bt_ref": BT, "rules": V, "snapshots": snaps},
              open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not a.quiet:
        print("[sentinel] %s | 笔数 %s | 交易日 %s | 单笔均值 %s | 累计 %s%% | 回撤 %s%% | 止损占比 %s%% | 到期占比 %s%%"
              % (snap["date"], snap["n_trades"], snap["days"], snap["mean_net_pct"], snap["cum_ret_pct"],
                 snap["mdd_pct"], snap["stop_share_pct"], snap["expiry_share_pct"]))
        print("[sentinel] 判定：%s" % snap["verdict"])


if __name__ == "__main__":
    main()