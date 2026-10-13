# -*- coding: utf-8 -*-
"""短线池 · **超卖伏击**（A59 主卖出 / C50 参考 / B 已否决）用**最新量化回测 agent**（fleur_absorb）重跑

口径来源（**从生产脚本原样搬**，不是自创）
------------------------------------------
`backtest/khunter_three_ver_opt_20260903.py`（9 格生产网格）
`khunter_timing_backtest.T.prep`（指标）· `khunter_all_strategies_backtest.K.SIGNALS`（15 信号）

  · 信号：15 个 KHunter 信号**任一**触发
  · 入场：`sig_any[t-1]` ∧ `RSI(14)[t-1] < 35` ∧ **熊市限定**[t-1] ⇒ **T+1 开盘买**
  · 出场：`RSI(14)[t-1] > ob`（标准 ob=55 / 激进 ob=50）⇒ **T+1 开盘卖**
         B 版另有 30% 绝对止损（`close[t-1] < entry_px×0.70`）
  · 低价过滤：入场价 `o×(1+买成本) ≥ low`（low=0/2/3）
  · 域：`is_bear = index_close < MA60`，取 **T-1** 状态（无未来函数）
  · 成本：`COST_BUY = COST_SELL = 0.00575` ⇒ 往返 **0.0115**
  · 宇宙：排除 sh688/sh689/sz30；`len ≥ 70`

数据源差异（必须披露）
----------------------
生产脚本读 `v8_factor_cache.pkl`，但它是 **pyarrow 后端 pickle**，本机**未装 pyarrow**
⇒ 原脚本在本机**跑不起来**。本次改用 `D:\\Documents\\Quant data\\data_full`（项目铁律口径），
窗口到 **2026-09-30**（cache 的 as_of 是 2026-09-23）。

三种口径（每格都跑）
--------------------
  orig_cost    : `round_trip=0.0115`，关闭成交日可成交性 → 与生产冻结对照（验证移植）
  itemized     : 分项成本（佣金含最低 5 元 / 仅卖出印花税 / 仅沪市过户费 / 流量费）
  itemized_enf : 分项成本 **+** 成交日可成交性强制（涨停/一字板/停牌 → 不成交）

两级视角
--------
  组合级  K=5 槽位（贴近真实交易者上限）→ 净值 / 年化 / 回撤 / 夏普
  交易级  K 不限（每股独立）→ 取"交易集合"，对照生产冻结 n/wr/mean；
          分项成本按**给定名义额 20 万**解析重算（避免 K 极大时仓位被摊薄、
          绝对费用吞掉收益的算术假象）；并对同一集合统计"成交日买不进/卖不出"

用法：`python short_pool_auction_backtest_v16.py`
产物：`evidence_short_pool_v16.json`、`short_pool_v16_*_{trades,equity}.csv`
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
BT = os.path.join(REPO, "backtest")
DATA = r"D:\Documents\Quant data\data_full"
IDX = os.path.join(REPO, "index_000300.csv")
ENG = r"E:\PI\投资\fleur_absorb"
for _p in (BT, ENG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import khunter_all_strategies_backtest as K  # noqa: E402
import khunter_timing_backtest as T  # noqa: E402
from engine import portfolio as PF  # noqa: E402
from engine.spec import ExecutionSpec, cost_breakdown  # noqa: E402

OUTDIR = HERE
T0 = time.time()
BACKTEST_START = pd.Timestamp("2016-06-01")
COST_SIDE = 0.00575
MAIN_RE = ("sh600", "sh601", "sh603", "sh605", "sz000", "sz001", "sz002", "sz003")
EXCL = ("sh688", "sh689", "sz30")

ARMS = [
    dict(id="A59", ver="A", ob=55, stop=0.00, low=3.0, board="主卖出（ob55 + 低价≥3元）"),
    dict(id="C50", ver="C", ob=50, stop=0.00, low=3.0, board="参考（ob50 + 低价≥3元）"),
    dict(id="B59s30", ver="B", ob=55, stop=0.30, low=3.0, board="已否决（ob55 + 30%止损）"),
]
MODES = [
    dict(id="orig_cost", cost="round_trip", enforce=False,
         label="原口径复现（往返 1.15% · 不判可成交性）"),
    dict(id="itemized", cost="itemized", enforce=False, label="新 agent · 分项成本"),
    dict(id="itemized_enf", cost="itemized", enforce=True,
         label="新 agent · 分项成本 + 强制成交日可成交性"),
]


def log(m):
    print("[%7.1fs] %s" % (time.time() - T0, m), flush=True)


# ------------------------------------------------------------------ 规格
def build_spec(arm, mode):
    cfg = dict(
        name="short_pool_%s_%s" % (arm["id"], mode["id"]),
        market="CN_A",
        account=dict(initial_cash=1000000, currency="CNY"),
        # apply_top_n=False：生产口径**没有**「每日最多取 N 个信号」的横截面上限
        # （`khunter_three_ver_opt_20260903.py` 是逐股独立状态机）。若设 True+top_n=5，
        # 引擎会把每个信号日截到 5 笔 —— 实测导致 L2=315/404（缺 89 笔，97.8% 落在共振日，
        # 且都是高收益笔，均值 +4.47%）。仓位上限一律交给 `rebalance.max_positions`（=K）控制。
        signal=dict(top_n=5, timing="t1_open", apply_top_n=False),
        rebalance=dict(max_positions=5, slot_allocation="largest_remainder", order_by="strength",
                       alloc_mode="split", lot_size=1, min_trade_lots=0, cash_reserve_pct=0.0,
                       single_position_limit_pct=None, empty_signal_action="hold_cash"),
        filters=dict(gap_max=None, min_list_days=70, min_amt20=None,
                     exclude_st=False, fresh_signal=False),
        risk=dict(max_hold_days=None, stop_pct=(arm["stop"] or None), stop_atr_mult=None,
                  skip_reentry_on_win=False, skip_reentry_strategies=[]),
        sizing=dict(exposure=1.0),
        execution=dict(price_basis="raw", calendar="index_000300", board="auto",
                       session=dict(fill_policy="auction_blind", silent_window="reject",
                                    enforce_fill_tradability=bool(mode["enforce"]),
                                    limit_band_ticks=1)),
        domain=dict(scheme="index_ma", line="MA60", n_domain=1, weights=[[1.0]], strategy_ids=[1]),
    )
    if mode["cost"] == "round_trip":
        cfg["cost"] = dict(mode="round_trip", round_trip_pct=2 * COST_SIDE)
    else:
        cfg["cost"] = dict(mode="itemized", commission_rate=0.0003, min_commission=5.0,
                           stamp_tax_sell=0.001, transfer_fee_sh=0.00001, flow_fee=0.1)
    return ExecutionSpec.from_dict(cfg, source=mode["id"])


# ------------------------------------------------------------------ 数据
def load_universe():
    idx = pd.read_csv(IDX)
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
    cal = [d for d in idx["date"] if d >= BACKTEST_START]
    log("日历 %d 天 %s -> %s" % (len(cal), cal[0].date(), cal[-1].date()))

    frames, syms_all, syms_main = {}, [], []
    for nm in sorted(os.listdir(DATA)):
        if not nm.endswith(".csv"):
            continue
        stem = nm[:-4]
        if stem.startswith("_") or len(stem) < 8 or not stem[2:].isdigit():
            continue
        if stem.startswith(EXCL):
            continue
        try:
            df = pd.read_csv(os.path.join(DATA, nm))
            df.columns = [c.strip().lower() for c in df.columns]
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"]).sort_values("date").set_index("date")
        except Exception:  # noqa: BLE001
            continue
        if len(df) < 70:
            continue
        try:
            frames[stem] = T.prep(df)
        except Exception:  # noqa: BLE001
            continue
        syms_all.append(stem)
        if stem[:5] in MAIN_RE:
            syms_main.append(stem)
    log("宇宙：原口径 %d 只 · 主板 %d 只" % (len(syms_all), len(syms_main)))
    return cal, frames, syms_all, syms_main, st_prev


def build_matrices(cal, frames, syms, st_prev):
    Tn, N = len(cal), len(syms)
    O = np.full((Tn, N), np.nan, dtype=np.float32)
    H = np.full((Tn, N), np.nan, dtype=np.float32)
    L = np.full((Tn, N), np.nan, dtype=np.float32)
    C = np.full((Tn, N), np.nan, dtype=np.float32)
    V = np.full((Tn, N), np.nan, dtype=np.float32)
    RSI = np.full((Tn, N), np.nan, dtype=np.float32)
    SIG = np.zeros((Tn, N), dtype=bool)
    di = {d: i for i, d in enumerate(cal)}
    bear = np.array([st_prev.get(d, "bear") == "bear" for d in cal], dtype=bool)
    posall = np.arange(Tn)
    for j, s in enumerate(syms):
        r = frames[s]
        raw = np.array([di.get(d, -1) for d in r.index], dtype=np.int64)
        m = raw >= 0
        if not m.any():
            continue
        pos = raw[m]
        rr = r.iloc[np.nonzero(m)[0]]
        for nm, arr in (("open", O), ("high", H), ("low", L), ("close", C), ("volume", V)):
            arr[pos, j] = pd.to_numeric(rr[nm], errors="coerce").to_numpy(dtype=np.float64)
        if "rsi" in rr.columns:
            RSI[pos, j] = pd.to_numeric(rr["rsi"], errors="coerce").to_numpy(dtype=np.float64)
        su = np.zeros(len(rr), dtype=bool)
        for _n, fn in K.SIGNALS.items():
            try:
                sv = np.asarray(fn(rr), dtype=float)
                su |= np.nan_to_num(sv, nan=0.0).astype(bool)
            except Exception:  # noqa: BLE001
                continue
        SIG[pos, j] = su
    return dict(open=O, high=H, low=L, close=C, volume=V), RSI, SIG, bear


# ------------------------------------------------------------------ 执行
def run_arm(ctx, RSI, SIG, bear, spec, arm, K):
    """RSI 出场（+可选 30% 止损）。exit_close[t] = RSI[t] > ob → 引擎 t+1 开盘卖。
    `stop_pct` 是引擎**显式参数**，必须传，否则 B 版静默退化为 A 版。
    """
    Tn = RSI.shape[0]
    # ── 入场对齐修正（2026-10-08，off-by-one 根因）──────────────────────────────
    # 生产口径：`sig_any[i-1] ∧ RSI[i-1]<35 ∧ bear[i]` → **i 日开盘买**
    #           （见 khunter_three_ver_opt_20260903.py:142-148 的 cand/rsi14_1/is_bear_arr）
    # 引擎语义：`sig[t]` → **t+1 开盘成交**
    # ⇒ 令 j = i-1：`sig[j] = SIG[j] ∧ RSI[j]<35 ∧ bear[j+1]`（同一根 bar，不再多挪一天）
    #   旧写法 `sig[1:] = SIG[:-1]` 是「自查先挪一天」，引擎又挪一天 ⇒ 净晚 1 个交易日（实测交集 0）
    bear_next = np.concatenate([bear[1:], bear[-1:]])           # bear_next[j] = bear[j+1]
    ok = SIG & np.nan_to_num(RSI < 35, nan=False) & bear_next[:, None]
    if arm["low"] and arm["low"] > 0:
        # 生产判据 = 入场价 o×(1+买成本) ≥ low；引擎成交日已知为 j+1 ⇒ 用 open[j+1] **精确**判
        fill_next = np.vstack([ctx["open"][1:], ctx["open"][-1:]])
        ok &= np.nan_to_num(fill_next * (1 + COST_SIDE) >= arm["low"], nan=False)
    sig = ok.copy()
    strat = np.where(ok, 1, 0).astype(np.int8)
    strength = np.where(ok, 1.0, 0.0).astype(np.float32)
    tradable = np.isfinite(ctx["close"]) & np.isfinite(ctx["open"]) & (ctx["open"] > 0)
    exit_close = {1: np.nan_to_num(RSI > arm["ob"], nan=False)}
    res = PF.run(spec, ctx, tradable, sig, strat, strength, bear.astype(np.int8),
                 i0=0, i1=Tn, K=K, cost_rt=spec.cost_rt, exit_close=exit_close,
                 stop_pct=(arm["stop"] or None))
    return res, ok


def summarize(dates, res):
    nav = np.asarray(res.nav_hist, dtype=float)
    v = nav[np.isfinite(nav)]
    rr = np.array([t["ret"] for t in res.trades], dtype=float) if res.trades else np.array([])
    if v.size < 2:
        return dict(n_trades=len(res.trades), ann_pct=None, mdd_pct=None, sharpe=None)
    ret = np.diff(v) / v[:-1]
    yrs = (dates[-1] - dates[0]).days / 365.25
    ann = (v[-1] / v[0]) ** (1.0 / yrs) - 1.0 if yrs > 0 and v[-1] > 0 else None
    peak = np.maximum.accumulate(v)
    mdd = float(((v - peak) / peak).min())
    sh = float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else None
    return dict(n_trades=len(res.trades),
                ann_pct=round(100 * ann, 2) if ann is not None else None,
                mdd_pct=round(100 * mdd, 2), sharpe=round(sh, 3) if sh else None,
                wr_pct=round(100 * float((rr > 0).mean()), 2) if rr.size else None,
                mean_ret_pct=round(100 * float(rr.mean()), 3) if rr.size else None,
                final_nav=round(float(v[-1]), 4))


def summarize_trade_level(res):
    rr = np.array([t["ret"] for t in res.trades], dtype=float) if res.trades else np.array([])
    if not rr.size:
        return dict(n=0)
    holds = np.array([t["days"] for t in res.trades], dtype=float)
    H = max(float(holds.mean()), 1.0)
    ann = ((1 + float(rr.mean())) ** (252 / H) - 1) * 100 if rr.mean() > -1 else -100.0
    return dict(n=int(rr.size), wr_pct=round(100 * float((rr > 0).mean()), 2),
                mean_pct=round(100 * float(rr.mean()), 3),
                med_pct=round(100 * float(np.median(rr)), 3),
                hold_med=round(float(np.median(holds)), 1),
                ann_trade_pct=round(ann, 2))


def itemized_on_trades(trades, syms, notional=200000.0):
    """同一笔交易集合，按**给定名义额**重算分项成本后的收益。

    为什么这样做：K 极大时引擎把每仓摊到 nav/K，而「最低佣金 5 元」是**绝对额**，
    会把单笔收益算成 −100%（首轮实测 mean −101%，纯算术假象）。按真实名义额 20 万重算，
    才能得到有意义的成本差。
    """
    nav_unit = 1_000_000.0   # 真实账户规模：分项里的**绝对金额**（最低佣金 5 元 / 流量费 0.1 元）靠它换算
    cfg = {"cost": dict(mode="itemized", commission_rate=0.0003, min_commission=5.0,
                        stamp_tax_sell=0.001, transfer_fee_sh=0.00001, flow_fee=0.1)}
    rets, fees = [], []
    for t in trades:
        ep, xp = float(t["entry_px"]), float(t["exit_px"])
        if not (ep > 0 and xp > 0):
            continue
        # 引擎的归一化空间：1.0 NAV = nav_unit 元。仓位 w（NAV）→ 股数 = w/价格
        w = notional / nav_unit
        sh = w / ep
        is_sh = str(syms[int(t["j"])]).startswith("sh")
        b = cost_breakdown(cfg, ep, sh, "buy", nav_unit, is_sh)
        s = cost_breakdown(cfg, xp, sh, "sell", nav_unit, is_sh)
        # 单位纪律：cost_breakdown 的 total 是**元**，而 sh*price 是 **NAV**；
        # 必须先 /nav_unit 才能相加（此前直接相加 ⇒ fee 放大 1e6 倍）。
        outlay = sh * b["actual_price"] + b["total"] / nav_unit
        proceeds = sh * s["actual_price"] - s["total"] / nav_unit
        rets.append(proceeds / outlay - 1.0)
        fees.append((b["total"] + s["total"]) / (w * nav_unit))   # 往返费用 ÷ 仓位金额
    if fees:
        _f = float(np.mean(fees)) * 100.0
        if not (0.05 <= _f <= 3.0):
            # 归一化尺度写错时（如把"股数"当 volume、把"仓位金额"当 notional_unit）这里会炸，
            # 而不是安静地吐出 fee=32759pp / mean=-528% 这种垃圾读数。
            raise ValueError(
                "itemized_on_trades：往返费用率 %.4f pp 不在合理区间 [0.05, 3.0] pp "
                "⇒ cost_breakdown 的归一化尺度传参错误" % _f)
    a = np.array(rets, dtype=float)
    return dict(n=int(a.size), notional=notional,
                mean_pct=round(100 * float(a.mean()), 3) if a.size else None,
                med_pct=round(100 * float(np.median(a)), 3) if a.size else None,
                wr_pct=round(100 * float((a > 0).mean()), 2) if a.size else None,
                fee_pp=round(100 * float(np.mean(fees)), 4) if fees else None)


def count_fill_rejections(ctx, trades, syms):
    """对同一交易集合统计「成交日不可成交」（入场买不进 / 出场卖不出）。"""
    from engine import session as S
    n_buy = n_sell = 0
    ex = []
    for t in trades:
        j = int(t["j"])
        sym = syms[j]
        for idx, side in ((int(t["entry_idx"]), "buy"), (int(t["exit_idx"]), "sell")):
            pc = ctx["close"][idx - 1, j] if idx >= 1 else np.nan
            bar = dict(open=ctx["open"][idx, j], high=ctx["high"][idx, j],
                       low=ctx["low"][idx, j], close=ctx["close"][idx, j],
                       volume=ctx["volume"][idx, j])
            ok, why = S.tradable_at_fill(bar, float(pc) if np.isfinite(pc) else None,
                                         S.board_of(sym), side)
            if not ok:
                if side == "buy":
                    n_buy += 1
                else:
                    n_sell += 1
                if len(ex) < 6:
                    ex.append(dict(sym=sym, side=side, idx=idx, why=why))
    return dict(n=len(trades), n_buy_rejected=n_buy, n_sell_rejected=n_sell, examples=ex)


def dump_trades(trades, cal, syms, path):
    """逐笔落盘（G4：`entry_date`/`exit_date` 必须是 **ISO 日期**）。

    引擎 trade dict 的 `entry_date`/`exit_date` 语义是 **cal 下标**
    （`engine/portfolio.py:178-179`：`entry_date=h["t_entry"]`），不是日期。
    本函数改写为 ISO 日期，原下标保留在 `entry_idx`/`exit_idx`。
    """
    df = pd.DataFrame(trades)
    if df.empty:
        log("  ⚠ 无逐笔可落盘：%s" % os.path.basename(path))
        return
    if "sym" not in df.columns:
        df.insert(0, "sym", [syms[int(j)] for j in df["j"]])
    df["entry_date"] = [cal[int(i)].date().isoformat() for i in df["entry_idx"]]
    df["exit_date"] = [cal[int(i)].date().isoformat() for i in df["exit_idx"]]
    df.to_csv(path, index=False, encoding="utf-8-sig")


# ------------------------------------------------------------------ 主流程
def main():
    cal, frames, syms_all, syms_main, st_prev = load_universe()
    out = dict(_what="短线池 · 超卖伏击 用 fleur_absorb（最新 agent）重跑",
               generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
               source_protocol="backtest/khunter_three_ver_opt_20260903.py",
               data_dir=DATA, n_frames=len(frames), results={})
    idf = pd.read_csv(IDX)
    idf["date"] = pd.to_datetime(idf["date"])
    idf = idf.sort_values("date").reset_index(drop=True)
    iclose = idf.set_index("date")["close"].reindex(cal).to_numpy(dtype=float)

    for uni_name, syms in (("主板（板面口径）", syms_main), ("原口径（非科创/创业）", syms_all)):
        ctx, RSI, SIG, bear = build_matrices(cal, frames, syms, st_prev)
        ctx["symbols"] = syms
        ctx["idx_close"] = iclose
        ctx["idx_ma20"] = pd.Series(iclose).rolling(20, min_periods=1).mean().to_numpy()
        ctx["idx_ma60"] = pd.Series(iclose).rolling(60, min_periods=1).mean().to_numpy()
        log("%s：矩阵 %s · 信号总数 %d" % (uni_name, ctx["close"].shape, int(SIG.sum())))
        out["results"][uni_name] = {}
        for arm in ARMS:
            # 交易集合用 round_trip（与生产同成本），以便逐笔对照冻结读数
            spec_rt = build_spec(arm, dict(id="rt", cost="round_trip", enforce=False, label=""))
            res_t, ok = run_arm(ctx, RSI, SIG, bear, spec_rt, arm, K=99999)
            tl = summarize_trade_level(res_t)
            item = itemized_on_trades(res_t.trades, syms)
            rej = count_fill_rejections(ctx, res_t.trades, syms)
            for mode in MODES:
                spec = build_spec(arm, mode)
                res_p, _ = run_arm(ctx, RSI, SIG, bear, spec, arm, K=5)
                key = "%s | %s" % (arm["id"], mode["id"])
                out["results"][uni_name][key] = dict(
                    board=arm["board"], mode_label=mode["label"],
                    portfolio=summarize(cal, res_p), trade_level=tl,
                    trade_level_itemized20w=item, fill_tradability=rej,
                    n_entry_signals=int(ok.sum()),
                    diag=dict(n_rej_limit_up=res_p.diag.get("n_rej_limit_up", 0),
                              n_rej_limit_down=res_p.diag.get("n_rej_limit_down", 0),
                              n_rej_suspended=res_p.diag.get("n_rej_suspended", 0),
                              enforce=res_p.diag.get("enforce_fill_tradability"),
                              cost_model=res_p.diag.get("cost_model")))
                p = out["results"][uni_name][key]["portfolio"]
                log("  %-24s [组合] n=%-4s ann=%-7s mdd=%-8s sharpe=%-6s"
                    % (key, p["n_trades"], p["ann_pct"], p["mdd_pct"], p["sharpe"]))
                if mode is MODES[-1]:
                    log("  %-24s [交易级·原] n=%-4s wr=%-6s mean=%-7s med=%-7s | "
                        "[交易级·分项20w] mean=%-7s wr=%-6s fee=%-6spp | 买不进=%-3s 卖不出=%-3s"
                        % ("", tl.get("n"), tl.get("wr_pct"), tl.get("mean_pct"), tl.get("med_pct"),
                           item.get("mean_pct"), item.get("wr_pct"), item.get("fee_pp"),
                           rej["n_buy_rejected"], rej["n_sell_rejected"]))
                if uni_name.startswith("主板") and arm["id"] == "A59":
                    dump_trades(res_p.trades, cal, syms,
                                os.path.join(OUTDIR, "short_pool_v16_%s_trades.csv" % mode["id"]))
                    pd.DataFrame({"date": [d.date().isoformat() for d in cal],
                                  "nav": res_p.nav_hist}).to_csv(
                        os.path.join(OUTDIR, "short_pool_v16_%s_equity.csv" % mode["id"]),
                        index=False, encoding="utf-8-sig")
            if uni_name.startswith("主板"):
                dump_trades(res_t.trades, cal, syms,
                            os.path.join(OUTDIR, "short_pool_v16_%s_tradelevel_trades.csv" % arm["id"]))
    p = os.path.join(OUTDIR, "evidence_short_pool_v16.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    log("已写出 %s" % os.path.basename(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
