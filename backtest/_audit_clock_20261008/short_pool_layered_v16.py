# -*- coding: utf-8 -*-
"""短线分层（4 宇宙 × A59/C50）在 fleur_absorb 上重算 —— **修正版**

背景：原 `evidence_layered_v16.json`（2026-10-08 15:18）**没有留下产出脚本**，
属不可复跑产物。本文件把它固化成可复跑脚本，并带上本轮的 **off-by-one 对齐修正**
（见 `short_pool_auction_backtest_v16.py:run_arm` 的入场对齐注释）。

口径（与生产 `khunter_three_ver_opt_20260903.py` 同一套，不是自创）
------------------------------------------------------------------
  · 15 信号任一 ∧ `RSI(14)[i-1]<35` ∧ **熊市[i]**（入场日 regime）⇒ **i 日开盘买**
  · 出场 `RSI(14)[i-1] > ob` ⇒ i 日开盘卖（A59: ob=55 主卖出 / C50: ob=50 参考）
  · 低价过滤：入场价 `o×(1+买成本) ≥ 3 元`（**精确**，用成交日 open 判）
  · 域：`index_close < MA60` 取 **T-1** 状态（无未来函数）
  · 起点 2016-06-01；数据 `D:\\Documents\\Quant data\\data_full`（前复权）
  · **含存活偏差**（退市股已被数据源剔除，独立项，未在本轮处理）

四个宇宙（`excluded` = ETF/LOF/北交所/指数）
--------------------------------------------
  纯主板    sh600/601/603/605 + sz000/001/002/003
  纯创业板  sz30*
  纯科创板  sh688*/sh689*
  股票一体  上述三者并集

两级读数：组合级（K=5 槽位，真实交易者可承受）与交易级（K 不限，对照生产冻结 n/wr/mean）。

用法：`python short_pool_layered_v16.py`
产物：`evidence_layered_v16.json` + `layered_<宇宙>_<臂>_tradelevel_trades.csv`（ISO 日期，可复算）
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import short_pool_auction_backtest_v16 as A  # noqa: E402

OUTDIR = HERE
T0 = time.time()
MAIN_RE = ("sh600", "sh601", "sh603", "sh605", "sz000", "sz001", "sz002", "sz003")
BOARD_LABEL = {"A59": "主卖出（ob55+低价≥3）", "C50": "参考（ob50+低价≥3）"}
ARMS = [dict(id="A59", ob=55, stop=0.00, low=3.0), dict(id="C50", ob=50, stop=0.00, low=3.0)]
UNIVERSES = {
    "纯主板": lambda s: s[:5] in MAIN_RE,
    "纯创业板": lambda s: s.startswith("sz30"),
    "纯科创板": lambda s: s.startswith(("sh688", "sh689")),
    "股票一体": lambda s: (s[:5] in MAIN_RE) or s.startswith(("sz30", "sh688", "sh689")),
}


def log(m):
    print("[%7.1fs] %s" % (time.time() - T0, m), flush=True)


def regime_and_cal():
    """本模块自算交易日历与 T-1 域状态（避免 `A.load_universe()` 把 5000+ 只票白载一遍）。"""
    idx = pd.read_csv(A.IDX)
    idx["date"] = pd.to_datetime(idx["date"])
    idx = idx.sort_values("date").reset_index(drop=True)
    idx["ma20"] = idx["close"].rolling(20, min_periods=1).mean()
    idx["ma60"] = idx["close"].rolling(60, min_periods=1).mean()
    st = {}
    for r in idx.itertuples(index=False):
        st[r.date] = "bear" if r.close < r.ma60 else ("bull" if r.close > r.ma20 else "weak")
    st_prev, prev = {}, "bear"
    for d in sorted(st):
        st_prev[d] = prev
        prev = st[d]
    cal = [d for d in idx["date"] if d >= A.BACKTEST_START]
    return cal, st_prev


def load_all_frames(cal, st_prev):
    """载入**全板块**股票（auction 的 loader 会剔除创业/科创，分层需要它们）。"""
    frames, syms = {}, []
    for nm in sorted(os.listdir(A.DATA)):
        if not nm.endswith(".csv"):
            continue
        stem = nm[:-4]
        if stem.startswith("_") or len(stem) < 8 or not stem[2:].isdigit():
            continue
        # 只收沪深股票（主板/创业/科创）——ETF/LOF/北交所/指数自动被排除
        if not (stem[:5] in MAIN_RE or stem.startswith(("sz30", "sh688", "sh689"))):
            continue
        try:
            df = pd.read_csv(os.path.join(A.DATA, nm))
            df.columns = [c.strip().lower() for c in df.columns]
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"]).sort_values("date").set_index("date")
        except Exception:  # noqa: BLE001
            continue
        if len(df) < 70:
            continue
        try:
            frames[stem] = A.T.prep(df)
        except Exception:  # noqa: BLE001
            continue
        syms.append(stem)
    log("全板块股票 %d 只" % len(syms))
    return cal, frames, syms, st_prev


def main():
    cal, st_prev = regime_and_cal()
    _cal_r, frames, syms_all, _sp_r = load_all_frames(cal, st_prev)
    assert _cal_r == cal and _sp_r is st_prev
    idf = pd.read_csv(A.IDX)
    idf["date"] = pd.to_datetime(idf["date"])
    idf = idf.sort_values("date").reset_index(drop=True)
    iclose = idf.set_index("date")["close"].reindex(cal).to_numpy(dtype=float)

    ev = dict(_what="① 短线分层在 fleur_absorb 上重算（**修正版**：入场同 bar 对齐）",
              generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
              abolished="旧 shortsplit_* 含未来函数，build_dual_system.py:899-901 判定作废",
              protocol="15信号任一 ∧ RSI[i-1]<35 ∧ 熊市[i] → i 日开盘买；RSI[i-1]>ob → i 日开盘卖；低价≥3元",
              data_note=("data_full 前复权；**含存活偏差**（退市股已剔除）"
                         "；本轮已修正移植 off-by-one（引擎成交日曾晚 1 个交易日）"),
              excluded="ETF/LOF/北交所/指数",
              universes={}, results={})
    for uni, pred in UNIVERSES.items():
        syms = [s for s in syms_all if pred(s)]
        ev["universes"][uni] = dict(n_symbols=len(syms), rule="见 docstring 四宇宙定义")
        if not syms:
            log("%s：0 只，跳过" % uni)
            continue
        ctx, RSI, SIG, bear = A.build_matrices(cal, frames, syms, st_prev)
        ctx["symbols"] = syms
        ctx["idx_close"] = iclose
        ctx["idx_ma20"] = pd.Series(iclose).rolling(20, min_periods=1).mean().to_numpy()
        ctx["idx_ma60"] = pd.Series(iclose).rolling(60, min_periods=1).mean().to_numpy()
        log("%s：%d 只 · 矩阵 %s · 信号 %d" % (uni, len(syms), ctx["close"].shape, int(SIG.sum())))
        ev["results"][uni] = {}
        for arm in ARMS:
            spec_rt = A.build_spec(arm, dict(id="rt", cost="round_trip", enforce=False, label=""))
            res_t, ok = A.run_arm(ctx, RSI, SIG, bear, spec_rt, arm, K=99999)
            tl = A.summarize_trade_level(res_t)
            item = A.itemized_on_trades(res_t.trades, syms)
            rej = A.count_fill_rejections(ctx, res_t.trades, syms)
            port = {}
            for mode in A.MODES:
                if mode["id"] == "itemized":
                    continue                      # 分层表只留 orig_cost 与 itemized_enf 两档
                spec = A.build_spec(arm, mode)
                res_p, _ = A.run_arm(ctx, RSI, SIG, bear, spec, arm, K=5)

                port[mode["id"]] = A.summarize(cal, res_p)
            ev["results"][uni][arm["id"]] = dict(
                board=BOARD_LABEL[arm["id"]], trade_level=tl,
                trade_level_itemized20w=item, fill_tradability=rej,
                portfolio=port, n_entry_signals=int(ok.sum()))
            A.dump_trades(res_t.trades, cal, syms,
                          os.path.join(OUTDIR, "layered_%s_%s_tradelevel_trades.csv" % (uni, arm["id"])))
            log("  %-4s [交易级] n=%-4s wr=%-6s mean=%-7s | [组合·原] ann=%-7s mdd=%-8s | "
                "[组合·分项 enf] ann=%-7s mdd=%-8s | 买不进=%s"
                % (arm["id"], tl.get("n"), tl.get("wr_pct"), tl.get("mean_pct"),
                   port["orig_cost"]["ann_pct"], port["orig_cost"]["mdd_pct"],
                   port["itemized_enf"]["ann_pct"], port["itemized_enf"]["mdd_pct"],
                   rej["n_buy_rejected"]))
    p = os.path.join(OUTDIR, "evidence_layered_v16.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(ev, fh, ensure_ascii=False, indent=1)
    log("已写出 %s" % os.path.basename(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
