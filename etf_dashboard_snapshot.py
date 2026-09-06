# -*- coding: utf-8 -*-
"""
ETF 动量轮动（冻结模型）看板快照生成器
========================================
为网页看板提供「ETF 动量轮动 + 组合层波动率缩放」的实时快照：
- 当前信号状态（20日动量排名 / top1 / top2 / 缩放 / 目标权重）
- 模拟盘持仓（etf_paper_state.json）
- 回测证据（etf_momentum_volscale_0906.csv 冻结配置 12%/20日）
产出：dist/etf_dashboard_snapshot.json（构建器读取）
"""
import os, sys, json
from pathlib import Path
import pandas as pd
import numpy as np

BASE = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
sys.path.insert(0, str(BASE / "backtest"))
from etf_momentum_20d_0906 import CORE, load_etf, CASH_ANN
from etf_momentum_volscale_0906 import run_volscale

DATA_DIR = BASE / "data_full"
OUT = BASE / "dist" / "etf_dashboard_snapshot.json"
NAMES = {}
_names_f = BASE / "data_full_names.json"
if _names_f.exists():
    NAMES = json.loads(_names_f.read_text(encoding="utf-8"))

TARGET_VOL = 0.12
VOL_WIN = 20
LOOKBACK = 20
COST = 0.001


def main():
    prices = {c: load_etf(c) for c in CORE}
    prices = {c: d for c, d in prices.items() if d is not None and len(d) > LOOKBACK + 5}

    # 1. 回测证据（冻结配置权威值：从回测 CSV 读取，避免自算口径偏离）
    bt = {}
    bt_csv = BASE / "backtest" / "etf_rotation_out" / "etf_momentum_volscale_0906.csv"
    if bt_csv.exists():
        btdf = pd.read_csv(bt_csv)
        row = btdf[(btdf.target_vol == TARGET_VOL) & (btdf.vol_win == VOL_WIN) & (btdf.cost == COST)]
        if len(row):
            r = row.iloc[0]
            bt = {
                "total": round(float(r["total"]), 4),
                "annual": float(r["annual"]),
                "max_dd": float(r["max_dd"]),
                "sharpe": float(r["sharpe"]),
                "wr": float(r["wr"]),
                "pos_years": int(r["pos_years"]),
                "excess_ann": float(r["excess_ann"]),
                "dd_imp_pp": float(r["dd_imp_pp"]),
                "avg_scale": float(r["avg_scale"]),
                "n_trades": int(r["n_trades"]),
                "seg_annual": float(r["seg_annual"]) if pd.notna(r["seg_annual"]) else None,
                "seg_max_dd": float(r["seg_max_dd"]) if pd.notna(r["seg_max_dd"]) else None,
                "seg_sharpe": float(r["seg_sharpe"]) if pd.notna(r["seg_sharpe"]) else None,
                "seg_wr": float(r["seg_wr"]) if pd.notna(r["seg_wr"]) else None,
            }

    # 2. 信号状态：最近月调仓信号日（月末最后交易日）的结论 + 最近交易日参考排名
    all_idx = None
    for c, d in prices.items():
        all_idx = d.index if all_idx is None else all_idx.intersection(d.index)
    all_idx = all_idx.sort_values()
    last_dt = all_idx[-1] if all_idx is not None else None

    # 最近调仓信号日 = 数据范围内最后一个「月末最后交易日」
    month = all_idx.to_period("M")
    groups = {}
    for dt, m in zip(all_idx, month):
        groups.setdefault(m, []).append(dt)
    rebal_days = [days[-1] for m, days in groups.items()]
    rebal_days = pd.DatetimeIndex(sorted(set(rebal_days)))
    sig_days = [d for d in rebal_days if d <= last_dt]
    sig_dt = sig_days[-1] if sig_days else None

    def _signal_at(dt):
        """在 dt 日（信号日收盘视角）计算动量排名与缩放"""
        moms = {}
        for c, d in prices.items():
            if dt not in d.index:
                continue
            pos = d.index.get_loc(dt)
            if pos < LOOKBACK:
                continue
            moms[c] = float(d["close"].iloc[pos] / d["close"].iloc[pos - LOOKBACK] - 1)
        ranked = sorted(moms.items(), key=lambda x: -x[1])
        res = {"rank": [{"code": c, "name": NAMES.get(c, c), "mom": round(m * 100, 2)} for c, m in ranked],
               "top1": None, "top2": None, "scale": None, "weights": {}, "empty": None, "note": ""}
        if len(ranked) >= 2:
            top1, top2 = ranked[0][0], ranked[1][0]
            res["top1"], res["top2"] = top1, top2
            if ranked[0][1] < 0:
                res["empty"] = True
                res["weights"] = {}
                res["scale"] = 0.0
                res["note"] = "绝对动量保护：Top1 20日动量 < 0 → 全空仓（货基）"
            else:
                res["empty"] = False
                rets = None
                for c in (top1, top2):
                    d = prices[c]
                    pos = d.index.get_loc(dt)
                    lo = max(0, pos - VOL_WIN)
                    closes = d["close"].iloc[lo:pos + 1]
                    r = closes.pct_change().dropna() * 0.5
                    rets = r if rets is None else rets + r
                rv = rets.std(ddof=1) * np.sqrt(252) if rets is not None and len(rets.dropna()) >= 5 else None
                scale = min(1.0, max(0.25, TARGET_VOL / rv)) if rv and rv > 0 else 1.0
                res["scale"] = round(scale, 3)
                res["weights"] = {top1: round(scale * 0.5, 4), top2: round(scale * 0.5, 4)}
                res["note"] = f"实现波动率 {rv*100:.1f}%/年 → 缩放 {scale*100:.0f}%"
        return res

    sig = {"as_of": str(last_dt.date()) if last_dt is not None else None,
           "sig_date": str(sig_dt.date()) if sig_dt is not None else None}
    sig.update(_signal_at(sig_dt) if sig_dt is not None else _signal_at(last_dt) if last_dt is not None else {})
    sig["rank_ref"] = _signal_at(last_dt)["rank"] if last_dt is not None else []
    sig["note"] += f"（信号日 {sig.get('sig_date')}）"

    # 3. 模拟盘状态
    paper = {"nav": None, "px_chg": None, "positions": [], "pending": None,
             "last_date": None, "start": None, "cum": None}
    sf = BASE / "etf_paper_state.json"
    if sf.exists():
        st = json.loads(sf.read_text(encoding="utf-8"))
        nh = st.get("nav_history", [])
        paper["last_date"] = nh[-1]["date"] if nh else None
        paper["start"] = st.get("start")
        if nh:
            paper["nav"] = round(nh[-1]["nav"], 2)
            paper["cum"] = round((nh[-1]["nav"] / 100000.0 - 1) * 100, 2)
            if len(nh) >= 2:
                paper["px_chg"] = round((nh[-1]["nav"] / nh[-2]["nav"] - 1) * 100, 3)
        paper["positions"] = [{"code": p["code"], "name": NAMES.get(p["code"], p["code"]),
                               "shares": p["shares"], "entry_px": p.get("entry_px"),
                               "last_close": p.get("last_close"),
                               "weight": round(p.get("weight", 0) * 100, 2)} for p in st.get("positions", [])]
        paper["pending"] = st.get("pending")

    snap = {"bt": bt, "sig": sig, "paper": paper, "generated_at": str(pd.Timestamp.now())}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ ETF 看板快照已生成: {OUT}")
    print(f"   数据截至 {sig['as_of']} · Top1={sig['top1']} · Top2={sig['top2']} · 缩放={sig['scale']} · 空仓={sig['empty']}")
    print(f"   模拟盘: NAV {paper['nav']} · 累计 {paper['cum']}% · 持仓 {len(paper['positions'])} 只 · {paper['last_date']}")


if __name__ == "__main__":
    main()
