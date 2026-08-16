# -*- coding: utf-8 -*-
"""股票分层回测：中长线（v9_auto MA150_SL55 参数）+ 短线（v3 反转+MA5 参数）
================================================================================
按板块互斥分层：all（一体）/ main_only（纯主板）/ gem_only（纯创业板）/ star_only（纯科创板）
输出：v9split_<group>_summary.json + v9split_<group>_equity.csv
      shortsplit_<group>_summary.json + shortsplit_<group>_equity.csv
"""
import sys, json, time
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
sys.path.insert(0, str(BASE))
import v9_auto as A
import v8_selector as V
import short_engine as S
import numpy as np

GROUPS = [
    ("all",       "股票一体 · 全A"),
    ("main_only", "纯主板"),
    ("gem_only",  "纯创业板"),
    ("star_only", "纯科创板"),
]

# 中长线参数（v9_opt_final 最优 MA150_SL55：+825%/夏普1.577）
V9_KW = dict(top_n=3, mom_min=0.25, score_min=65, stop_loss=0.055,
             use_timing=True, ma_window=150, cash0=500000)


def v9_split(slip=0):
    suffix = f"_slip{slip}" if slip else ""
    for group, label in GROUPS:
        t0 = time.time()
        kw = dict(V9_KW)
        if slip:
            kw["slippage_bps"] = slip
        eq, tr = A.run_auto(perm=group, **kw)
        s = V.summary(eq, tr)
        out = {"strategy": f"v9_split_{group}", "label": label,
               "params": "T3/m25/s65/SL5.5/MA150 择时" + (f" · 含{slip}bps滑点" if slip else ""),
               "slippage_bps": slip, "summary": s}
        json.dump(out, open(BASE / f"v9split_{group}{suffix}_summary.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        eq.to_csv(BASE / f"v9split_{group}{suffix}_equity.csv", index=False)
        print(f"中长线[{group}] {label}: 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% | "
              f"回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 交易 {s['total_trades']} ({time.time()-t0:.0f}s)", flush=True)


def _rev(r, reversal=False):
    """股票短线反转版评分（v3 最优参数同款）"""
    s = 0.0
    if not np.isnan(r["mom20"]):
        s += 30 * max(0.0, min(1.0, (-r["mom20"]) / 0.15))
    s += 15 * (1 if r["vp"] else 0)
    if not np.isnan(r["vr5"]):
        s += 10 * max(0.0, min(1.0, (r["vr5"] - 0.5) / 2.0))
    if not np.isnan(r["dnc"]):
        s += 25 * r["dnc"]
    if not np.isnan(r["vol20"]):
        s += 20 * max(0.0, min(1.0, 1 - (r["vol20"] - 0.20) / 0.60))
    return s


def _board_ok(code, group):
    if group == "all":
        return not (code.startswith(("sh900", "sz200", "bj")))
    if group == "main_only":
        return code.startswith(("sh60", "sz00", "sz002"))
    if group == "gem_only":
        return code.startswith("sz30")
    if group == "star_only":
        return code.startswith(("sh688", "sh689"))
    return False


def short_split():
    # 股票池按板块分组建池（v5.11.7 滑点稳健参数：T10/H10/S55 反转 + MA5，含 20bps 滑点）
    t0 = time.time()
    all_pool = S.load_stock_pool()
    print(f"全股票池 {len(all_pool)} 只 ({time.time()-t0:.0f}s)", flush=True)
    for group, label in GROUPS:
        pool = {c: d for c, d in all_pool.items() if _board_ok(c, group)}
        print(f"短线[{group}] {label}: 池 {len(pool)} 只", flush=True)
        S.short_score = _rev  # 反转版
        t1 = time.time()
        eq, tr = S.run_short(pool, top_n=10, hold_days=10, score_min=55,
                             ma5_exit=True, ma_win=30, slippage_bps=20)
        s = V.summary(eq, tr)
        out = {"strategy": f"shortsplit_{group}", "label": label,
               "params": "T10/H10/S55 反转+MA5/MA30门控 · 含20bps滑点", "slippage_bps": 20, "summary": s}
        json.dump(out, open(BASE / f"shortsplit_{group}_summary.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        eq.to_csv(BASE / f"shortsplit_{group}_equity.csv", index=False)
        print(f"短线[{group}] {label}: 收益 {s['total_return_pct']}% | 年化 {s['annual_return_pct']}% | "
              f"回撤 {s['max_drawdown_pct']}% | 夏普 {s['sharpe']} | 交易 {s['total_trades']} ({time.time()-t1:.0f}s)", flush=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="all", choices=["v9", "short", "all"])
    ap.add_argument("--slip", type=int, default=0, help="滑点 bps（中长线 v9 模式）")
    args = ap.parse_args()
    if args.mode in ("v9", "all"):
        v9_split(slip=args.slip)
    if args.mode in ("short", "all"):
        short_split()
