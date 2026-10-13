# -*- coding: utf-8 -*-
"""短线池 · 超卖伏击 —— 四臂对照：生产读数 / 引擎同口径 / 新数据 / 真实可执行成本

为什么必须四臂
--------------
上一轮我用 data_full 直跑得交易级 n=360/wr=59.4/mean=1.05，生产冻结是 n=402/wr=65.67/mean=2.456。
**差在哪必须先分离**：是移植错了，还是数据源不同？做法是把同一份生产输入
（v8_factor_cache.pkl，pyarrow 已装 D:\\Tools\\pylibs）分别用生产脚本口径与 fleur_absorb 跑，
把「引擎移植误差」与「数据源差」拆开。

四臂
----
  L1 legacy@cache     原样复刻生产状态机（逐股独立、低价值判 `o×(1+0.00575)`）
                      → 应命中冻结读数（A_x3 n=402/wr=65.67/mean=2.456）
  L2 engine@cache     同一份 cache 改由 fleur_absorb 执行 → 与 L1 之差 = **引擎移植误差**（目标 ≈0）
  L3 engine@data_full 换 data_full（更新至 2026-09-30）→ 与 L2 之差 = **数据源差**
  L4 engine@itemized+enf 分项成本 + 强制成交日可成交性 → 与 L3 之差 = **最新 agent 的真实成本修正**

口径（从 backtest/khunter_three_ver_opt_20260903.py 原样搬）
------------------------------------------------------------
  15 信号任一 · 入场 sig_any[i-1] ∧ RSI(14)[i-1]<35 ∧ 熊市[i] ⇒ **i 日开盘买**
  （注意：regime 取的是**入场日** i 的状态，不是 i-1 —— 见生产脚本 cand/entry_ok_base 两个数组的错位）
  出场 RSI(14)[i-1] > ob ⇒ i 日开盘卖；B 版加 30% 止损

用法：python short_pool_four_arms_20261008.py
产物：evidence_short_pool_four_arms.json + fourarms_*_{legacy,engine_cache,engine_datafull,engine_enf}_trades.csv
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
BT = os.path.join(REPO, "backtest")
CACHE = os.path.join(REPO, "v8_factor_cache.pkl")
IDX = os.path.join(REPO, "index_000300.csv")
DATA = r"D:\Documents\Quant data\data_full"
ENG = r"E:\PI\投资\fleur_absorb"

# ---- 导入顺序是硬要求（2026-10-08 三序探针实测）----
#   path→pandas→pyarrow : rc=0 OK  ｜ path→pyarrow→pandas : rc=0 OK
#   pandas→path→pyarrow : rc=1 "pyarrow>=13.0.0 is required for PyArrow backed StringArray" ← 必须避免
# pandas 在 **import 时**就完成 pyarrow 探测，故 pylibs 必须在 import pandas 之前入路径。
for _p in (r"D:\Tools\pylibs", BT, ENG):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pyarrow  # noqa: E402,F401   # 故意不吞异常：静默 pass 会掩盖真因（已踩过）
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import khunter_all_strategies_backtest as K  # noqa: E402
import khunter_timing_backtest as T  # noqa: E402
from engine import portfolio as PF  # noqa: E402
from engine.spec import ExecutionSpec, cost_breakdown  # noqa: E402

OUTDIR = HERE
T0 = time.time()
BACKTEST_START = pd.Timestamp("2016-06-01")
COST_SIDE = 0.00575
COST_RT = 2 * COST_SIDE
EXCL = ("sh688", "sh689", "sz30")
#: 入场对齐档位。`legacy` = 修正前写法（用于复现「共有=0」基线并留档）；
#: 默认 `fixed` = 本轮修正后的同 bar 对齐。审计脚本据此选对应产物的文件名。
ALIGN = os.environ.get("SP_ALIGN", "fixed").strip().lower()
ALIGN_SUFFIX = "" if ALIGN == "fixed" else "_LEGACYALIGN"
NAV_UNIT = 1000000.0          # = spec.account.initial_cash；引擎用它把绝对费用还原到归一化空间

ARMS = [
    dict(id="A_x3", ver="A", ob=55, stop=0.00, low=3.0,
         frozen=dict(n=402, wr=65.67, med=2.536, mean=2.456)),
    dict(id="C_x3", ver="C", ob=50, stop=0.00, low=3.0,
         frozen=dict(n=402, wr=63.68, med=2.080, mean=2.193)),
    dict(id="B_x3", ver="B", ob=55, stop=0.30, low=3.0,
         frozen=dict(n=402, wr=65.42, med=2.496, mean=2.190)),
]


def log(m):
    print("[%7.1fs] %s" % (time.time() - T0, m), flush=True)


def regime_and_bench():
    idx = pd.read_csv(IDX)
    idx["date"] = pd.to_datetime(idx["date"])
    idx = idx.sort_values("date").reset_index(drop=True)
    idx["ma20"] = idx["close"].rolling(20, min_periods=1).mean()
    idx["ma60"] = idx["close"].rolling(60, min_periods=1).mean()
    st = {}
    for r in idx.itertuples(index=False):
        st[r.date] = "bear" if r.close < r.ma60 else ("bull" if r.close > r.ma20 else "weak")
    st_prev, prev = {}, None
    for d in sorted(st):
        st_prev[d] = prev if prev is not None else "bear"
        prev = st[d]
    cal = [d for d in idx["date"] if d >= BACKTEST_START]
    return st_prev, cal


def load_frames(src):
    frames = {}
    if src == "cache":
        c = pd.read_pickle(CACHE)
        for code, df in c.items():
            if df is None or len(df) < 70 or code.startswith(EXCL):
                continue
            d = df[["open", "high", "low", "close", "volume"]].copy()
            d.index.name = None
            d["date"] = d.index
            d = d.sort_values("date").reset_index(drop=True)
            try:
                frames[code] = T.prep(d)
            except Exception:  # noqa: BLE001
                continue
    else:
        for nm in sorted(os.listdir(DATA)):
            if not nm.endswith(".csv"):
                continue
            stem = nm[:-4]
            if stem.startswith("_") or len(stem) < 8 or not stem[2:].isdigit() or stem.startswith(EXCL):
                continue
            try:
                d = pd.read_csv(os.path.join(DATA, nm))
                d.columns = [c.strip().lower() for c in d.columns]
                d["date"] = pd.to_datetime(d["date"], errors="coerce")
                d = d.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
            except Exception:  # noqa: BLE001
                continue
            if len(d) < 70:
                continue
            try:
                frames[stem] = T.prep(d)
            except Exception:  # noqa: BLE001
                continue
    return frames


def union_signals(r):
    su = np.zeros(len(r), dtype=bool)
    for _n, fn in K.SIGNALS.items():
        try:
            su |= np.nan_to_num(np.asarray(fn(r), dtype=float), nan=0.0).astype(bool)
        except Exception:  # noqa: BLE001
            continue
    return su


def legacy_state_machine(frames, st_prev, arm):
    out = []
    for code, d in frames.items():
        n = len(d)
        opens = d["open"].to_numpy(dtype=float)
        closes = d["close"].to_numpy(dtype=float)
        dates = d["date"].to_numpy()
        rsi14 = d["rsi"].to_numpy(dtype=float)
        rsi14_1 = np.concatenate([[np.nan], rsi14[:-1]])
        sig_any = union_signals(d)
        cand = np.zeros(n, dtype=bool)
        cand[1:] = sig_any[:-1]
        cand &= dates >= np.datetime64(BACKTEST_START)
        is_bear = np.array([st_prev.get(pd.Timestamp(x), "bear") == "bear" for x in dates])
        ok = cand & np.nan_to_num(rsi14_1 < 35, nan=False) & is_bear
        sell_sig = np.nan_to_num(rsi14_1 > arm["ob"], nan=False)
        pos, entry_px, entry_i = False, 0.0, 0
        for i in range(1, n):
            o = opens[i]
            if o <= 0:
                continue
            if pos:
                do_sell = bool(sell_sig[i])
                c_prev = closes[i - 1]
                if not do_sell and arm["stop"] > 0 and np.isfinite(c_prev):
                    do_sell = c_prev < entry_px * (1 - arm["stop"])
                if do_sell:
                    out.append(dict(sym=code, entry_date=pd.Timestamp(dates[entry_i]),
                                    exit_date=pd.Timestamp(dates[i]),
                                    ret=o * (1 - COST_SIDE) / entry_px - 1,
                                    days=int(i - entry_i), entry_px=entry_px, exit_px=o))
                    pos = False
            else:
                if ok[i]:
                    if arm["low"] > 0 and o * (1 + COST_SIDE) < arm["low"]:
                        continue
                    entry_px = o * (1 + COST_SIDE)
                    entry_i = i
                    pos = True
        if pos:
            out.append(dict(sym=code, entry_date=pd.Timestamp(dates[entry_i]),
                            exit_date=pd.Timestamp(dates[n - 1]),
                            ret=closes[n - 1] * (1 - COST_SIDE) / entry_px - 1,
                            days=int(n - 1 - entry_i), entry_px=entry_px, exit_px=closes[n - 1]))
    return out


def build_spec(arm, mode):
    cfg = dict(
        name="short_pool_%s_%s" % (arm["id"], mode),
        market="CN_A",
        account=dict(initial_cash=NAV_UNIT, currency="CNY"),
        # apply_top_n=False：生产口径**没有**「每日最多取 N 个信号」的横截面上限
        # （`khunter_three_ver_opt_20260903.py` 是逐股独立状态机）。设 True+top_n=5 会把每个
        # 信号日截到 5 笔 ⇒ L2=315/404（缺 89 笔，97.8% 落在共振日、均值 +4.47%）。
        # 代价：这一点曾让 L2 的 mean 被低估约 0.66pp。仓位上限交给 `rebalance.max_positions`（=K）。
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
                                    enforce_fill_tradability=(mode == "itemized_enf"),
                                    limit_band_ticks=1)),
        domain=dict(scheme="index_ma", line="MA60", n_domain=1, weights=[[1.0]], strategy_ids=[1]),
    )
    if mode == "orig":
        cfg["cost"] = dict(mode="round_trip", round_trip_pct=COST_RT)
    else:
        cfg["cost"] = dict(mode="itemized", commission_rate=0.0003, min_commission=5.0,
                           stamp_tax_sell=0.001, transfer_fee_sh=0.00001, flow_fee=0.1)
    return ExecutionSpec.from_dict(cfg, source=mode)


def engine_run(frames, st_prev, cal, arm, mode, K=99999):
    syms = list(frames.keys())
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
    for j, s in enumerate(syms):
        r = frames[s]
        raw = np.array([di.get(d, -1) for d in r["date"]], dtype=np.int64)
        m = raw >= 0
        if not m.any():
            continue
        pos = raw[m]
        rr = r.iloc[np.nonzero(m)[0]]
        for nm, arr in (("open", O), ("high", H), ("low", L), ("close", C), ("volume", V)):
            arr[pos, j] = pd.to_numeric(rr[nm], errors="coerce").to_numpy(dtype=np.float64)
        if "rsi" in rr.columns:
            RSI[pos, j] = pd.to_numeric(rr["rsi"], errors="coerce").to_numpy(dtype=np.float64)
        SIG[pos, j] = union_signals(rr)
    spec = build_spec(arm, mode)
    # ── 入场对齐（两档可选；`SP_ALIGN=legacy` 用于复现修正前「共有=0」基线）──────────
    # 生产 = `sig_any[i-1] ∧ RSI[i-1]<35 ∧ bear[i]` → i 日开盘买；引擎 = sig[t] → t+1 开盘成交。
    # fixed : 令 j=i-1 ⇒ `sig[j] = SIG[j] ∧ RSI[j]<35 ∧ bear[j+1]`（同 bar）
    # legacy: 旧写法 `sig[1:] = SIG[:-1]` —— 净晚 1 个交易日（本轮的根因）
    if ALIGN == "legacy":
        rsi_prev = np.vstack([np.full((1, N), np.nan), RSI[:-1]])
        sig = np.zeros_like(SIG)
        sig[1:] = SIG[:-1]
        ok = sig & np.nan_to_num(rsi_prev < 35, nan=False) & bear[:, None]
        if arm["low"] > 0:
            ok &= np.nan_to_num(C >= arm["low"], nan=False)
        sig = ok.copy()
    else:
        bear_next = np.concatenate([bear[1:], bear[-1:]])
        ok = SIG & np.nan_to_num(RSI < 35, nan=False) & bear_next[:, None]
        if arm["low"] > 0:
            fill_next = np.vstack([O[1:], O[-1:]])              # 精确判入场价（不再用 T 收盘近似）
            ok &= np.nan_to_num(fill_next * (1 + COST_SIDE) >= arm["low"], nan=False)
        sig = ok.copy()
    strat = np.where(ok, 1, 0).astype(np.int8)
    strength = np.where(ok, 1.0, 0.0).astype(np.float32)
    tradable = np.isfinite(C) & np.isfinite(O) & (O > 0)
    exit_close = {1: np.nan_to_num(RSI > arm["ob"], nan=False)}
    ctx = dict(open=O, high=H, low=L, close=C, volume=V, symbols=syms,
               idx_close=np.full(Tn, np.nan), idx_ma20=np.full(Tn, np.nan),
               idx_ma60=np.full(Tn, np.nan))
    res = PF.run(spec, ctx, tradable, sig, strat, strength, bear.astype(np.int8),
                 i0=0, i1=Tn, K=K, cost_rt=spec.cost_rt, exit_close=exit_close,
                 stop_pct=(arm["stop"] or None))
    return res, ok, ctx


def tl_stats(trades, label):
    rr = np.array([t["ret"] for t in trades], dtype=float)
    if not rr.size:
        return dict(label=label, n=0)
    holds = np.array([t.get("days", np.nan) for t in trades], dtype=float)
    Hm = max(float(np.nanmean(holds)), 1.0) if np.isfinite(holds).any() else 1.0
    return dict(label=label, n=int(rr.size),
                wr_pct=round(100 * float((rr > 0).mean()), 2),
                med_pct=round(100 * float(np.median(rr)), 3),
                mean_pct=round(100 * float(rr.mean()), 3),
                ann_trade_pct=(round(((1 + float(rr.mean())) ** (252 / Hm) - 1) * 100, 2)
                               if float(rr.mean()) > -1.0 else None),
                hold_med=round(float(np.nanmedian(holds)), 1))


def itemized20w(trades, notional=200000.0):
    """按引擎归一化空间正确调用 cost_breakdown：volume 传 真实股数÷nav_unit，notional_unit 传 nav_unit。
    （上一轮直接传真实股数 → amt 被放大 20 万倍 → 假的 fee=32759pp。）"""
    cfg = {"cost": dict(mode="itemized", commission_rate=0.0003, min_commission=5.0,
                        stamp_tax_sell=0.001, transfer_fee_sh=0.00001, flow_fee=0.1)}
    rets, fees = [], []
    for t in trades:
        ep, xp = float(t["entry_px"]), float(t["exit_px"])
        if not (ep > 0 and xp > 0):
            continue
        sh_real = notional / ep
        is_sh = str(t.get("sym") or "").startswith("sh")
        b = cost_breakdown(cfg, ep, sh_real / NAV_UNIT, "buy", NAV_UNIT, is_sh)
        s = cost_breakdown(cfg, xp, sh_real / NAV_UNIT, "sell", NAV_UNIT, is_sh)
        outlay = sh_real * b["actual_price"] + b["total"]
        proceeds = sh_real * s["actual_price"] - s["total"]
        rets.append(proceeds / outlay - 1.0)
        fees.append((b["total"] + s["total"]) / notional)
    a = np.array(rets, dtype=float)
    return dict(n=int(a.size), notional=notional,
                mean_pct=round(100 * float(a.mean()), 3) if a.size else None,
                med_pct=round(100 * float(np.median(a)), 3) if a.size else None,
                wr_pct=round(100 * float((a > 0).mean()), 2) if a.size else None,
                fee_pp=round(100 * float(np.mean(fees)), 4) if fees else None)



def dump_trades(trades, cal, syms, path, extra=None):
    """逐笔落盘（G4：`entry_date`/`exit_date` 必须是 **ISO 日期**，不是引擎内部时间索引）。

    引擎的 trade dict 里 `entry_date`/`exit_date` 语义是 **cal 的下标**（见
    `engine/portfolio.py:178-179`：`entry_date=h["t_entry"]`），**不是日期**。
    为免误解，本函数把这两列改写成 ISO 日期，原下标保留在 `entry_idx`/`exit_idx`。
    """
    df = pd.DataFrame(trades)
    if df.empty:
        log("  ⚠ 无逐笔可落盘：%s" % os.path.basename(path))
        return None
    if "sym" not in df.columns:
        df.insert(0, "sym", [syms[int(j)] for j in df["j"]])
    df["entry_date"] = [cal[int(i)].date().isoformat() for i in df["entry_idx"]]
    df["exit_date"] = [cal[int(i)].date().isoformat() for i in df["exit_idx"]]
    if extra:
        for k, v in extra.items():
            df[k] = v
    df.to_csv(path, index=False, encoding="utf-8-sig")
    log("  逐笔落盘 %-46s n=%s" % (os.path.basename(path), len(df)))
    return path

def main():
    st_prev, cal = regime_and_bench()
    log("日历 %d 天 %s -> %s" % (len(cal), cal[0].date(), cal[-1].date()))
    ev = dict(_what="短线池·超卖伏击 四臂对照", generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
              nav_unit=NAV_UNIT, cost_side=COST_SIDE, start=str(BACKTEST_START.date()), arms={})
    fc = load_frames("cache")
    log("cache 载入 %d 只" % len(fc))
    fd = load_frames("data_full")
    log("data_full 载入 %d 只" % len(fd))
    ev["n_cache"], ev["n_datafull"] = len(fc), len(fd)

    for arm in ARMS:
        fr = arm["frozen"]
        log("======== %s（生产冻结 n=%s wr=%s med=%s mean=%s） ========"
            % (arm["id"], fr["n"], fr["wr"], fr["med"], fr["mean"]))
        t1 = legacy_state_machine(fc, st_prev, arm)
        s1 = tl_stats(t1, "L1 生产脚本 @cache")
        log("  L1 生产脚本@cache      n=%-4s wr=%-6s med=%-7s mean=%-7s" % (s1["n"], s1["wr_pct"], s1["med_pct"], s1["mean_pct"]))
        e2, _o2, _c2 = engine_run(fc, st_prev, cal, arm, "orig")
        s2 = tl_stats(e2.trades, "L2 引擎 @cache")
        log("  L2 引擎@cache          n=%-4s wr=%-6s med=%-7s mean=%-7s" % (s2["n"], s2["wr_pct"], s2["med_pct"], s2["mean_pct"]))
        e3, _o3, _c3 = engine_run(fd, st_prev, cal, arm, "orig")
        s3 = tl_stats(e3.trades, "L3 引擎 @data_full")
        log("  L3 引擎@data_full      n=%-4s wr=%-6s med=%-7s mean=%-7s" % (s3["n"], s3["wr_pct"], s3["med_pct"], s3["mean_pct"]))
        # L4 用 **K=5**（每仓≈NAV/5≈20 万，真实交易者量级）——
        # 分项成本里"最低佣金 5 元 / 流量费 0.1 元"是**绝对金额**，K 极大时仓位被摊薄、
        # 绝对费用会吞掉收益并算出 mean<-100% 的假象（本轮已实测踩过，见 MIGRATION.md §4）。
        e4, _o4, _c4 = engine_run(fd, st_prev, cal, arm, "itemized_enf", K=5)
        s4 = tl_stats(e4.trades, "L4 引擎 @data_full·分项·可成交性（K=5 组合级）")
        s4["engine_diag"] = dict(n_rej_limit_up=e4.diag.get("n_rej_limit_up", 0),
                                 n_rej_limit_down=e4.diag.get("n_rej_limit_down", 0),
                                 n_rej_suspended=e4.diag.get("n_rej_suspended", 0),
                                 enforce=e4.diag.get("enforce_fill_tradability"))
        _nav = np.asarray(e4.nav_hist, dtype=float)
        _v = _nav[np.isfinite(_nav)]
        if _v.size > 2:
            _yrs = (cal[-1] - cal[0]).days / 365.25
            _r = np.diff(_v) / _v[:-1]
            _pk = np.maximum.accumulate(_v)
            s4["portfolio"] = dict(
                ann_pct=round(100 * ((_v[-1] / _v[0]) ** (1 / _yrs) - 1), 2),
                mdd_pct=round(100 * float(((_v - _pk) / _pk).min()), 2),
                sharpe=(round(float(_r.mean() / _r.std() * np.sqrt(252)), 3) if _r.std() > 0 else None),
                final_nav=round(float(_v[-1]), 4))
        # ---- 交易集合差异归因：L1（生产状态机）vs L2（引擎），同一份 cache ----
        _syms_c = _c2["symbols"]
        k1 = {(t["sym"], str(t["entry_date"].date())) for t in t1}
        k2 = {(_syms_c[int(t["j"])], str(cal[int(t["entry_idx"])].date())) for t in e2.trades}
        _only1 = k1 - k2
        _rmap = {x["sym"] + "|" + str(x["entry_date"].date()): x["ret"] for x in t1}
        s1["set_compare_vs_engine"] = dict(
            n_legacy=len(k1), n_engine=len(k2), n_common=len(k1 & k2),
            n_only_legacy=len(_only1), n_only_engine=len(k2 - k1),
            mean_only_legacy_pct=(round(100 * float(np.mean([_rmap[x[0] + "|" + x[1]] for x in _only1])), 3)
                                  if _only1 else None))
        log("  集合归因：共有=%s · 仅生产=%s（其均值 %s%%）· 仅引擎=%s"
            % (s1["set_compare_vs_engine"]["n_common"], s1["set_compare_vs_engine"]["n_only_legacy"],
               s1["set_compare_vs_engine"]["mean_only_legacy_pct"], s1["set_compare_vs_engine"]["n_only_engine"]))
        log("  L4 引擎·分项·可成交性   n=%-4s wr=%-6s med=%-7s mean=%-7s | 拒成交=%s"
            % (s4["n"], s4["wr_pct"], s4["med_pct"], s4["mean_pct"],
               s4["engine_diag"]["n_rej_limit_up"] + s4["engine_diag"]["n_rej_limit_down"]
               + s4["engine_diag"]["n_rej_suspended"]))
        it = itemized20w(t1)
        log("  ── 入场对齐档位 = %s（产物后缀 '%s'）" % (ALIGN, ALIGN_SUFFIX))
        log("  L1 同一集合·分项20万    n=%-4s wr=%-6s mean=%-7s fee=%spp" % (it["n"], it["wr_pct"], it["mean_pct"], it["fee_pp"]))
        ev["arms"][arm["id"]] = dict(frozen=fr, L1_legacy_cache=s1, L1_trades_itemized20w=it,
                                     L2_engine_cache=s2, L3_engine_datafull=s3, L4_engine_itemized_enf=s4)
        # L1（生产状态机）的 entry_date 本就是 Timestamp，落盘即为 ISO 日期
        pd.DataFrame(t1).to_csv(os.path.join(OUTDIR, "fourarms_%s_legacy_trades.csv" % arm["id"]),
                                index=False, encoding="utf-8-sig")
        # L2/L3/L4：引擎 trade dict 的 entry_date 是**时间索引**，必须经 dump_trades 转成 ISO 日期
        dump_trades(e2.trades, cal, _c2["symbols"],
                    os.path.join(OUTDIR, "fourarms_%s_engine_cache%s_trades.csv" % (arm["id"], ALIGN_SUFFIX)))
        dump_trades(e3.trades, cal, _c3["symbols"],
                    os.path.join(OUTDIR, "fourarms_%s_engine_datafull_trades.csv" % arm["id"]))
        dump_trades(e4.trades, cal, _c4["symbols"],
                    os.path.join(OUTDIR, "fourarms_%s_engine_enf_trades.csv" % arm["id"]))

    with open(os.path.join(OUTDIR, "evidence_short_pool_four_arms.json"), "w", encoding="utf-8") as fh:
        json.dump(ev, fh, ensure_ascii=False, indent=1)
    log("已写出 evidence_short_pool_four_arms.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
