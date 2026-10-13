# -*- coding: utf-8 -*-
r"""oos_run_v16_executable.py — HPDK（缩量超跌）v1.6「可执行口径」＋ v1.5「研究上界」对照（ADR-0004 · B1）

为什么另立 v1.6（**不动 v1.5**）
--------------------------------------------------------------------------
v1.5 = backtest/hengpan_fangliang_dikai_0925/oos_run.py（冻结脚本，SHA256 2351eb9d…，一个字节都不许改）
  · `signal(t)`（:166-173）用 `g = GAP[t]`（= `O[t+1]/C[t] − 1`，**次日开盘**）做筛选；
  · 同文件 :197 又按 `O[t+1][j]` 成交 ⇒ **筛选读了成交那一根 bar 的开盘** —— 同 bar 因果。
    实盘不可执行：清单要等 09:25 集合竞价撮合才知道，而挂单必须**早于** 09:25 存在。
  · 因此 v1.5 的读数只能当「研究上界」（upper bound），不能当可执行收益。

v1.6 = 本脚本（与 v1.5 **并行双跑**）
  ① 选股只用 T 日及以前：`elig(t)` ＋ 复合分 F = z(−ln AMT20) + z(−ln VOLBR) + z(−RET20)，取**分数降序前 K**。
     **不读** `GAP[t]` / `O[t+1]`（同 bar 因果取证见 audit_samebar_causality_<YYYYMMDD>.py 的双向投毒探针）。
  ② 下单动作：≤09:20 可撤单窗内**盲挂**限价 = 前收 × (1 + 带上沿) = `C[t][j] × 0.99`
     （`engine.session.blind_order_price`；`order_time = "09:18"`，`is_blind_order_admissible` 校验）。
  ③ 成交（`engine.session.blind_auction_fill`）：
       开盘 gap ∈ [−3%, −1%] → **以今开成交**（集合竞价单一价格撮合，成交价 = 今开）
       开盘 gap > −1%        → 限价没穿 ⇒ 不成交
       开盘 gap < −3%        → 实盘在 09:15–09:20 可撤单窗撤单 ⇒ 同样不算成交
                              （**这正是 v1.5 最典型的不可执行点**）
       涨停开盘 / 一字板 / 停牌 → 买不进（`engine.session.tradable_at_fill`：停牌先于涨跌停判定）
  ④ 槽位：K=10 只/日（按 T 日复合分降序抢槽）＋ KSLOT=20 并发上限 ＋ 持仓期内不重复买
     ＋ 逐日收盘盯市 ＋ 资金时序 entry_first（先入场 09:25、后出场 15:00；勘误 E-15）
     —— 记账结构复刻 x2_sens / entry_timing_hpdk_0928 的 sim_portfolio。
  ⑤ 出场：与 v1.5 主口径逐条一致（止盈 +2%：T+2 日 open ≥ TP 按 open、否则 high ≥ TP 按 TP；
     未达标 T+2 尾盘；不止损；收盘缺失顺延至多 6 日；末段最坏全损 WORST_CASE_WIPEOUT）。
  ⑥ 成本：v1.6 用**分项**（`engine.spec.cost_breakdown`）：commission_rate=0.0003 / min_commission=5.0 元 /
     stamp_tax_sell=0.001（仅卖出）/ transfer_fee_sh=0.00001（仅沪市）/ flow_fee=0.1 元每笔；
     v1.5 臂沿用其冻结单边 COST_SIDE=0.000346（原样复现）；另设「成本隔离臂 C」= v1.6 成交集 × v1.5 成本。

只读纪律
--------------------------------------------------------------------------
· oos_run.py **一个字节都不改**：importlib 载入后在**运行期**替换模块级 `P` 与 `STATE_F/TRADES_F/REPORT_F`
  （沿用 backtest/entry_timing_hpdk_0928/entry_timing_hpdk_0928.py:90-104 的既有做法），
  前后各断言一次 `FROZEN_SHA`；中间产物全部落 `--scratch`，不写生产产物。
· 复刻的 `elig/FILT` 与 v1.5 **逐行同源**；脚本会把「复刻出的 v1.5 名单」与「冻结脚本产物」逐笔对拍，
  不相等直接 fail（否则 v1.6 就是在跟一个错基线比）。另与 evidence_sensitivity.json 的 subwindow_2018 锚点对拍。

用法
--------------------------------------------------------------------------
  python oos_run_v16_executable.py --cache "$env:PI_SCRATCH_DIR"
输出
--------------------------------------------------------------------------
  oos_v16_trades.jsonl                               每笔（signal_date/entry_date/order_time/limit_px/
                                                     entry_open/band_hit/entry_reason/exit_*）
  evidence_v16_executable_compare_<YYYYMMDD>.json     三臂指标 + 归因 + 对拍 + P6 探针
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import math
import os
import pathlib
import sys
import time

import numpy as np
import pandas as pd

HERE = pathlib.Path(__file__).resolve().parent
R = HERE.parents[1]
OOS = HERE / "oos_run.py"                    # v1.5 冻结脚本（只读）
FLEUR = pathlib.Path(r"E:\PI\投资\fleur_absorb")   # 引擎（session/spec/audit 真值源）
if str(FLEUR) not in sys.path:
    sys.path.insert(0, str(FLEUR))
from engine import session as S             # noqa: E402
from engine import spec as SP               # noqa: E402
from engine import audit as AU              # noqa: E402

ANN = 244.0
SHA_PREFIX = "2351eb9d42acc62e"             # v1.7a 冻结 SHA 前缀（与 oos_state.json 一致）
SIGNAL_START = "2016-01-01"                 # 信号起算（与 x2_sens / entry_timing 同口径）
WINDOW_START = "2018-01-01"                 # 组合评价窗口（与 evidence_sensitivity.json subwindow_2018 同尺子）
BAND_LO, BAND_HI = -0.03, -0.01             # 冻结带 = [−P2, −P1] = [−3%, −1%]
ORDER_TIME = "09:18"                        # 盲挂下单时点（09:15–09:20 可撤单窗内）
COST_CFG = dict(mode="itemized", commission_rate=0.0003, min_commission=5.0,
                stamp_tax_sell=0.001, transfer_fee_sh=0.00001, flow_fee=0.1)
NOTIONAL_UNIT = 1_000_000.0                 # 「1.0 NAV」= 100 万元（分项成本里的绝对元项还原用）
K_TOP, KSLOT = 10, 20
# 同尺子锚点：evidence_sensitivity.json 的 subwindow_2018（2018-01-02~2026-09-24 · 主板 · v1.7）
ANCHOR_2018 = dict(ann=62.70, mdd=-26.80, sharpe=2.51, win_rate=60.64, mean_per_trade=0.4234,
                   n_trades=21157, n_entries=20495, deploy_pct=48.45)


def log(*a):
    print(*a, flush=True)


def sha256_of(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


# ============================================================ v1.5 冻结脚本（只读载入）
def load_mod():
    spec = importlib.util.spec_from_file_location("oos_run_v15_readonly", OOS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_panel(mod, cache):
    """面板：优先读 --cache 下的 panel_oos.npz（与 universe 一致才用），否则重建（慢）。"""
    f = pathlib.Path(cache) / "panel_oos.npz"
    cal, live, dead = mod.load_universe()
    syms = live + dead
    if f.exists():
        z = np.load(f, allow_pickle=True)
        if list(z["syms"]) == syms and list(z["cal"]) == cal:
            log("[cache] 面板 <- %s  (T=%d N=%d done=%d)" % (f, z["C"].shape[0], z["C"].shape[1], int(z["done"])))
            return cal, syms, dead, {k: z[k] for k in ("O", "H", "L", "C", "V", "A")}, int(z["done"]), str(f)
        log("[cache] 缓存与当前 universe 不符 -> 重建")
    t0 = time.time()
    F, done = mod.build(cal, syms)
    log("[build] T=%d N=%d done=%d (%.1fs)" % (F["C"].shape[0], F["C"].shape[1], done, time.time() - t0))
    return cal, syms, dead, F, done, "rebuilt(no-cache)"


def frozen_recs(mod, P_v15, F, done, scratch):
    """原样跑冻结脚本 main()（只在运行期替换 P 与三个输出路径），拿 v1.5 的逐笔信号 = 研究上界。

    与 backtest/entry_timing_hpdk_0928/entry_timing_hpdk_0928.py:90-104 同款干预；oos_run.py 字节不变。
    """
    mod.P.clear()
    mod.P.update(P_v15)
    scratch = pathlib.Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    mod.STATE_F = scratch / "_v16_v15_state.json"
    mod.TRADES_F = scratch / "_v16_v15_trades.jsonl"
    mod.REPORT_F = scratch / "_v16_v15_report.json"
    for q in (mod.STATE_F, mod.TRADES_F, mod.REPORT_F):
        if q.exists():
            q.unlink()
    mod.build = lambda _c, _s: (F, done)
    mod.main()
    recs = [json.loads(x) for x in mod.TRADES_F.read_text(encoding="utf-8").splitlines() if x.strip()]
    recs.sort(key=lambda r: r["signal_date"])       # 稳定排序：信号日升序 + 日内复合分降序
    return recs


# ============================================================ 因子与过滤件（逐行同源于 oos_run.py:63-165）
def build_factors(cal, syms, F, dead, P, with_rr=False):
    """复刻 oos_run.py main() 的因子段与过滤件。**判据一字不改** —— 改动会在 v1.5 对拍里暴露。

    `with_rr=False`：RR/ATR 只在 P["RR_MIN"]>0 时参与筛选（冻结默认 0.0 ⇒ 不生效），故按需跳过（省内存）。
    """
    T, N = F["C"].shape
    O, H, L, C, V, A = F["O"], F["H"], F["L"], F["C"], F["V"], F["A"]
    VALID = (C > 0) & np.isfinite(C) & (O > 0)
    Cv = np.where(VALID, C, np.nan)
    Vv = np.where(VALID, V, np.nan)
    Av = np.where(VALID, A, np.nan)
    AMT20 = pd.DataFrame(Av).rolling(20, min_periods=10).mean().to_numpy(dtype=np.float32)
    VMA20 = pd.DataFrame(Vv).rolling(20, min_periods=10).mean().to_numpy(dtype=np.float32)
    VMA20_prev = np.full_like(VMA20, np.nan)
    VMA20_prev[1:] = VMA20[:-1]
    del VMA20
    VOLBR = V / np.where(VMA20_prev > 0, VMA20_prev, np.nan)
    del VMA20_prev
    RET20 = np.full((T, N), np.nan, dtype=np.float32)
    RET20[20:] = Cv[20:] / Cv[:-20] - 1.0
    NV = np.cumsum(VALID, axis=0).astype(np.int32)
    RR = None
    if with_rr:
        _Cp = np.full((T, N), np.nan, dtype=np.float32)
        _Cp[1:] = C[:-1]
        _tr = np.maximum(H - L, np.maximum(np.abs(H - _Cp), np.abs(L - _Cp)))
        del _Cp
        _ATR20 = pd.DataFrame(np.where(VALID, _tr, np.nan)).rolling(20, min_periods=10).mean().to_numpy(np.float32)
        del _tr
        _ATRp = _ATR20 / np.where(C > 0, C, np.nan)
        del _ATR20
        RR = (P["TP"] / np.where(_ATRp > 0, _ATRp, np.nan)).astype(np.float32)
        del _ATRp
    return dict(O=O, H=H, L=L, C=C, V=V, A=A, VALID=VALID, AMT20=AMT20, VOLBR=VOLBR, RET20=RET20,
                NV=NV, RR=RR)


def build_filters(cal, syms, FD, dead, P):
    """复刻 oos_run.py:84-150：点时 ST 代理（STP）＋ 现名过滤三开关 ＋ 每股净资产（BPSA）＋ 主板掩码。"""
    T, N = FD["C"].shape
    C = FD["C"]
    lut = {d: i for i, d in enumerate(cal)}
    _NAMES = json.loads((R / "data_full_names.json").read_text(encoding="utf-8"))
    STNOW = np.array([(("ST" in (_NAMES.get(_s, "") or "").upper()) or ("退" in (_NAMES.get(_s, "") or "")))
                      for _s in syms], dtype=bool)
    _Cv = np.where(FD["VALID"], C, np.nan)
    _DEAD = np.array([s_ in set(dead) for s_ in syms], dtype=bool)
    _r1 = np.full((T, N), np.nan, dtype=np.float32)
    _r1[1:] = _Cv[1:] / _Cv[:-1] - 1.0
    _MX = pd.DataFrame(np.abs(_r1)).rolling(250, min_periods=60).max().to_numpy(dtype=np.float32)
    _CNT = pd.DataFrame((np.abs(_r1) >= 0.048).astype(np.float32)).rolling(250, min_periods=60).sum().to_numpy(dtype=np.float32)
    del _r1
    _NEED = int(P.get("STP_CNT", 3))
    STP = (np.isfinite(_MX) & (_MX <= 0.056) & (_CNT >= _NEED)) if _NEED > 0 else (np.isfinite(_MX) & (_MX <= 0.056))
    del _MX, _CNT
    BPSA = np.full((T, N), np.nan, dtype=np.float32)
    _bp = pd.read_csv(R / "backtest/_fundamentals/bps_quarterly.csv.gz")
    _bp["report_date"] = pd.to_datetime(_bp["report_date"], errors="coerce")
    _bp = _bp[_bp["report_date"].notna()]
    _bp["usable_from"] = (_bp["report_date"] + pd.DateOffset(months=4)).dt.strftime("%Y-%m-%d")
    _c2i = {s_: i for i, s_ in enumerate(syms)}
    for _s, _g in _bp.groupby("sym"):
        _j = _c2i.get(_s)
        if _j is None:
            continue
        _g = _g.sort_values("usable_from")
        _idx = np.array([lut.get(d, -1) for d in _g["usable_from"]], dtype=np.int64)
        _v = _g["bps"].to_numpy(dtype=np.float32)
        _ok = _idx >= 0
        _idx, _v = _idx[_ok], _v[_ok]
        if not _idx.size:
            continue
        _pos = np.searchsorted(_idx, np.arange(T), side="right") - 1
        _gd = _pos >= 0
        BPSA[_gd, _j] = _v[_pos[_gd]]
    del _bp
    _MB = np.array([(s_[:2] == "sh" and s_[2:5] in ("600", "601", "603", "605")) or
                    (s_[:2] == "sz" and s_[2:5] in ("000", "001", "002", "003"))
                    for s_ in syms], dtype=bool)
    _MBUSE = _MB if P.get("MAINBOARD", True) else np.ones(N, dtype=bool)
    return dict(STP=STP, STNOW=STNOW, _DEAD=_DEAD, BPSA=BPSA, MBUSE=_MBUSE)


def elig(FD, FL, syms, t, P):
    """资格掩码。**逐行同源于 oos_run.py:155-165**（含三个默认关闭的研究用门槛）。"""
    m = (FD["VALID"][t] & (FD["NV"][t] >= P["LISTED"]) & (FD["C"][t] >= P["MINPX"]) &
         np.isfinite(FD["AMT20"][t]) & (FD["AMT20"][t] >= P["MINAMT"]) & FILT(FL, FD, syms, t, P) & FL["MBUSE"])
    if P.get("VOLBR_MIN", 0.0) > 0:
        m = m & np.isfinite(FD["VOLBR"][t]) & (FD["VOLBR"][t] >= P["VOLBR_MIN"])
    if P.get("VOLBR_MAX", 1e9) < 1e8:
        m = m & np.isfinite(FD["VOLBR"][t]) & (FD["VOLBR"][t] <= P["VOLBR_MAX"])
    if P.get("RR_MIN", 0.0) > 0:
        m = m & np.isfinite(FD["RR"][t]) & (FD["RR"][t] >= P["RR_MIN"])
    return m


def FILT(FL, FD, syms, t, P):
    """点时 ST 代理 ＋ 股价 ≥3 元 ＋ 每股净资产 ≥3 元（报告期 +4 个月）。同源 oos_run.py:116-142。"""
    m = (~FL["STP"][t]) & (FD["C"][t] >= 3.0) & np.isfinite(FL["BPSA"][t]) & (FL["BPSA"][t] >= 3.0)
    if P.get("STNOW_OFF", False):
        pass
    elif P.get("STNOW_LIVE_ONLY", True):
        m = m & ((~FL["STNOW"]) | FL["_DEAD"])
    else:
        m = m & (~FL["STNOW"])
    return m


def zs(x):
    x = np.asarray(x, float)
    mu = np.nanmean(x)
    sd = np.nanstd(x)
    return (x - mu) / sd if np.isfinite(sd) and sd > 0 else np.zeros_like(x)


def select_v15(FD, FL, syms, t, P):
    """v1.5「研究上界」选股：同源 oos_run.py:166-173（**读 GAP[t] = 次日开盘**，不可执行）。"""
    g = np.full(FD["C"].shape[1], np.nan, dtype=np.float32)
    if t + 1 < FD["C"].shape[0]:
        cp = FD["C"][t]
        g = FD["O"][t + 1] / np.where(cp > 0, cp, np.nan) - 1.0
    b = elig(FD, FL, syms, t, P)
    m = b & np.isfinite(g) & (g <= -P["P1"]) & (g >= -P["P2"]) & np.isfinite(FD["RET20"][t]) & np.isfinite(FD["VOLBR"][t])
    ix = np.nonzero(m)[0]
    if ix.size == 0:
        return [], g
    comp = zs(-np.log(FD["AMT20"][t][ix])) + zs(-np.log(FD["VOLBR"][t][ix])) + zs(-FD["RET20"][t][ix])
    k = min(P["K"], ix.size)
    return [[int(ix[q]), float(comp[q])] for q in np.argsort(-comp)[:k]], g


def select_v16(FD, FL, syms, t, P):
    """v1.6「可执行」选股：elig ∩ 可算分 → 复合分降序前 K。

    **不读 GAP[t] / O[t+1]**：带内条件只能在成交当日 09:25 才知道，因此它不进选股、只进成交判定。
    """
    b = elig(FD, FL, syms, t, P)
    m = b & np.isfinite(FD["RET20"][t]) & np.isfinite(FD["VOLBR"][t])
    ix = np.nonzero(m)[0]
    if ix.size == 0:
        return []
    comp = zs(-np.log(FD["AMT20"][t][ix])) + zs(-np.log(FD["VOLBR"][t][ix])) + zs(-FD["RET20"][t][ix])
    k = min(P["K"], ix.size)
    return [[int(ix[q]), float(comp[q])] for q in np.argsort(-comp)[:k]]


# ============================================================ 盲挂协议（引擎 session 真值源）
def diag_v16(FD, syms, t, j):
    """v1.6 的单笔成交诊断：盲挂价 / 涨停 / 停牌 / 带外 / 带内以今开成交。"""
    O, H, L, C, V = FD["O"], FD["H"], FD["L"], FD["C"], FD["V"]
    pc = float(C[t, j])
    tb = t + 1
    o, h, l, c, v = (float(O[tb, j]), float(H[tb, j]), float(L[tb, j]), float(C[tb, j]), float(V[tb, j]))
    lim = float(S.blind_order_price(pc, BAND_HI)) if (np.isfinite(pc) and pc > 0) else float("nan")
    d = dict(prev_close=(round(pc, 4) if np.isfinite(pc) else None),
             limit_px=(round(lim, 4) if np.isfinite(lim) else None),
             entry_open=(round(o, 4) if np.isfinite(o) and o > 0 else None),
             band_hit=0, fill_px=None, reason="")
    if not (np.isfinite(pc) and pc > 0):
        d["reason"] = "无前收（无法算盲挂价）"
        return d
    ok_ord, why_ord = S.is_blind_order_admissible(ORDER_TIME, lim)
    d["order_admissible"] = bool(ok_ord)
    d["order_note"] = why_ord
    if not (np.isfinite(o) and o > 0):
        d["reason"] = "停牌/无今开（未上市或缺 bar）"
        return d
    bar = dict(open=o, high=h, low=l, close=c, volume=v)
    tr, why = S.tradable_at_fill(bar, pc, S.board_of(syms[j]), "buy")
    d["tradable"] = bool(tr)
    d["tradable_note"] = why
    if not tr:
        d["reason"] = "涨停买不进" if "涨停" in why else ("停牌" if "停牌" in why else why)
        return d
    fp, why2 = S.blind_auction_fill(pc, bar, BAND_LO, BAND_HI, side="buy")
    gap = o / pc - 1.0
    d["gap"] = round(gap * 100, 4)
    d["engine_note"] = why2
    if fp is None:
        if gap > BAND_HI + 1e-12:
            d["reason"] = "带外·上沿（开盘 gap %+.2f%% > 上沿 %+.2f%% → 限价没穿）" % (gap * 100, BAND_HI * 100)
        else:
            d["reason"] = "带外·下沿（开盘 gap %+.2f%% < 下沿 %+.2f%% → 09:15–09:20 撤单窗撤单）" % (gap * 100, BAND_LO * 100)
        d["band_bucket"] = "above_hi" if gap > BAND_HI + 1e-12 else "below_lo"
        return d
    d["fill_px"] = float(fp)
    d["band_hit"] = 1
    d["band_bucket"] = "in_band"
    d["reason"] = "带内 → 集合竞价以今开成交"
    return d


def ret_side(entry, x, c):
    """单边比例成本下的逐笔收益（%）。**与 oos_run.py:174-175 的 _ret_of 同式**。"""
    return -100.0 if x == 0 else (x * (1 - c) / (entry * (1 + c)) - 1) * 100


def exit_of(tb, j, entry, cal, O, H, C, T, tp):
    """出场（同源 oos_run.py:202-217 / entry_timing.exit_of）：止盈 +TP% / 未达标 T+2 尾盘 / 不止损。"""
    ex_t = tb + 1
    if ex_t >= T:
        return None
    exC, usedC, flagC = C[ex_t, j], ex_t, 0
    if not (np.isfinite(exC) and exC > 0):
        for k in range(ex_t + 1, min(ex_t + 6, T)):
            cc = C[k, j]
            if np.isfinite(cc) and cc > 0:
                exC, usedC, flagC = cc, k, 1
                break
        else:
            exC, usedC, flagC = np.float32(0.0), ex_t, 2      # 最坏全损
    tp_lv = entry * (1.0 + tp)
    o2, h2 = O[ex_t, j], H[ex_t, j]
    if np.isfinite(h2) and h2 > 0 and np.isfinite(o2):
        if o2 >= tp_lv:
            return dict(exit_idx=ex_t, exit_date=cal[ex_t], exit_px=float(o2), exit_flag=0, tp_hit=1)
        if h2 >= tp_lv:
            return dict(exit_idx=ex_t, exit_date=cal[ex_t], exit_px=float(tp_lv), exit_flag=0, tp_hit=1)
    return dict(exit_idx=usedC, exit_date=cal[usedC], exit_px=float(exC), exit_flag=int(flagC), tp_hit=0)


def build_v16_trades(FD, FL, cal, syms, P, signal_start):
    """v1.6：逐日选股（T 日信息）→ 盲挂 → 集合竞价成交 → 同一出场规则。返回逐笔记录。"""
    O, H, C = FD["O"], FD["H"], FD["C"]
    T = C.shape[0]
    out, cache = [], {}
    for t in range(T - 1):
        if cal[t] < signal_start:
            continue
        picks = select_v16(FD, FL, syms, t, P)
        if not picks:
            continue
        for rank, (j, comp) in enumerate(picks):
            d = diag_v16(FD, syms, t, j)
            rec = dict(signal_date=cal[t], entry_date=cal[t + 1], sym=syms[j], rank=int(rank + 1),
                       score=round(float(comp), 6), order_time=ORDER_TIME, limit_px=d["limit_px"],
                       prev_close=d["prev_close"], entry_open=d["entry_open"], band_hit=int(d["band_hit"]),
                       entry_reason=d["reason"], fill_ref="open")
            if "gap" in d:
                rec["gap_pct"] = d["gap"]
            if "band_bucket" in d:
                rec["band_bucket"] = d["band_bucket"]
            if d["fill_px"] is None:
                rec.update(filled=0, entry_px=None, exit_date=None, exit_px=None, exit_flag=None,
                           tp_hit=0, ret_pct=None, ret_pct_itemized=None)
            else:
                ex = exit_of(t + 1, j, d["fill_px"], cal, O, H, C, T, P["TP"])
                if ex is None:
                    rec.update(filled=0, entry_px=round(float(d["fill_px"]), 4), exit_date=None,
                               exit_px=None, exit_flag=None, tp_hit=0, ret_pct=None)
                    rec["entry_reason"] = rec["entry_reason"] + "；窗口末尾无法了结"
                else:
                    exx = float(ex["exit_px"])
                    rec.update(filled=1, entry_px=round(float(d["fill_px"]), 4), exit_date=ex["exit_date"],
                               exit_px=round(exx, 4), exit_flag=int(ex["exit_flag"]),
                               tp_hit=int(ex["tp_hit"]),
                               ret_pct=round(float(ret_side(d["fill_px"], exx, P["COST_SIDE"])), 4),
                               ret_pct_itemized=net_ret_notional(d["fill_px"], exx, syms[j], cost_cfg=COST_CFG))
            out.append(rec)
    return out


# ============================================================ 组合记账（结构复刻 x2_sens / entry_timing 的 sim_portfolio）
def sim(recs, cal, syms, FD, K, KSLOT, cost_side=None, cost_cfg=None, start=None,
        order="entry_first", lot=100, capital=1_000_000.0):
    """组合模拟。元空间（capital 元），返回 (metrics, nav, idx_all, entries_set, ex_r)。

    cost_side  : 单边比例成本（v1.5 口径）—— 分数股、与 entry_timing 的记账逐位同源
    cost_cfg   : 分项成本（v1.6 口径）—— **A 股 100 股整手**，费项走 engine.spec.cost_breakdown
    """
    T = len(cal)
    jof = {s: j for j, s in enumerate(syms)}
    C = FD["C"]
    by_entry = {}
    for r in recs:
        if not r.get("filled", 1):
            continue
        by_entry.setdefault(r["entry_date"], []).append(r)
    nav = np.full(T, np.nan)
    depl = np.full(T, np.nan)
    cash, pos, n_in = float(capital), [], 0
    ex_r = []
    entries = set()

    def fees(px, shares, side, sym, unit):
        return SP.cost_breakdown({"cost": cost_cfg}, px, shares, side,
                                 notional_unit=unit, is_sh=str(sym)[:2] == "sh")["total"]

    def do_entry(t, d):
        nonlocal cash, n_in
        if not ((start is None) or (d >= start)):
            return
        for r in by_entry.get(d, [])[:K]:
            if len(pos) >= KSLOT:
                break
            if any(q["sym"] == r["sym"] for q in pos):
                continue
            navprev = nav[t - 1] if (t > 0 and np.isfinite(nav[t - 1])) else float(capital)
            alloc = min(navprev / KSLOT, cash)
            if alloc <= 1e-9:
                break
            px = r.get("entry_px")
            if px is None or not (np.isfinite(px) and px > 0):
                continue
            if cost_cfg is None:
                cash -= alloc
                pos.append(dict(sym=r["sym"], shares=alloc / (px * (1.0 + cost_side)), entry_px=px,
                                entry_fee=alloc - alloc / (1.0 + cost_side),
                                exit_date=r["exit_date"], exit_px=r["exit_px"]))
            else:
                shares = math.floor(alloc / px / lot) * lot
                if shares <= 0:
                    continue
                amt = shares * px
                fee = fees(px, shares, "buy", r["sym"], 1.0)
                if amt + fee > cash:
                    break
                cash -= (amt + fee)
                pos.append(dict(sym=r["sym"], shares=shares, entry_px=px, entry_fee=fee,
                                exit_date=r["exit_date"], exit_px=r["exit_px"]))
            entries.add((r["entry_date"], r["sym"]))
            n_in += 1

    def do_exit(d):
        nonlocal cash
        for p in list(pos):
            if p["exit_date"] == d:
                px = p["exit_px"]
                if px is None or not np.isfinite(px):
                    continue
                gross = p["shares"] * px
                fee = (gross * cost_side) if cost_cfg is None else fees(px, p["shares"], "sell", p["sym"], 1.0)
                cash += gross - fee
                cost_out = p["shares"] * p["entry_px"] + p["entry_fee"]
                ex_r.append(float(((gross - fee) / cost_out - 1.0) * 100))
                pos.remove(p)

    for t in range(T):
        d = cal[t]
        if order == "entry_first":
            do_entry(t, d)
            do_exit(d)
        else:
            do_exit(d)
            do_entry(t, d)
        mv = 0.0
        for p in pos:
            j = jof.get(p["sym"])
            cc = C[t, j] if j is not None else np.nan
            if not (np.isfinite(cc) and cc > 0):
                cc = p["entry_px"]
            mv += p["shares"] * cc
        nav[t] = cash + mv
        depl[t] = (mv / nav[t]) if nav[t] > 0 else np.nan

    idx_all = [i for i in range(T) if start is None or cal[i] >= start]
    if len(idx_all) < 30:
        return None, nav, idx_all, entries, ex_r
    i0 = idx_all[0]
    nav = nav.copy()
    nav[i0] = float(capital)
    v = nav[idx_all] / float(capital)
    nd = len(v) - 1
    ann = (v[-1] / v[0]) ** (ANN / nd) - 1.0
    pk = np.maximum.accumulate(v)
    mdd = float((v / pk - 1.0).min())
    dr = v[1:] / v[:-1] - 1.0
    sd = dr.std(ddof=1)
    sig = [r for r in recs if r.get("filled", 1) and r.get("ret_pct") is not None
           and (start is None or r["entry_date"] >= start)]
    rets = np.array([r["ret_pct"] for r in sig], float)
    yearly = {}
    for i in idx_all:
        yearly.setdefault(cal[i][:4], []).append(i)
    yret = {}
    for y, ii in sorted(yearly.items()):
        j0 = ii[0] - 1
        base = nav[j0] if (j0 >= 0 and np.isfinite(nav[j0])) else float(capital)
        yret[y] = round(float(nav[ii[-1]] / base - 1.0) * 100, 2)
    m = dict(ann=round(ann * 100, 2), mdd=round(mdd * 100, 2),
             sharpe=(None if sd == 0 else round(float(dr.mean() / sd * math.sqrt(ANN)), 2)),
             win_rate=round(float(100 * (rets > 0).mean()), 2) if rets.size else None,
             mean_per_trade=round(float(rets.mean()), 4) if rets.size else None,
             med_per_trade=round(float(np.median(rets)), 4) if rets.size else None,
             n_signals=int(rets.size), n_entries=int(n_in),
             deploy_pct=round(float(np.nanmean(depl[idx_all])) * 100, 2),
             exec_n=int(len(ex_r)),
             exec_mean=round(float(np.mean(ex_r)), 4) if ex_r else None,
             exec_med=round(float(np.median(ex_r)), 4) if ex_r else None,
             exec_win=round(float(100 * np.mean([x > 0 for x in ex_r])), 2) if ex_r else None,
             n_years=len(yret), neg_years=int(sum(1 for x in yret.values() if x < 0)), yearly=yret,
             window=[cal[i0], cal[idx_all[-1]]])
    return m, nav, idx_all, entries, ex_r


def net_ret_notional(entry, exit_px, sym, notional=100000.0, lot=100, cost_cfg=None):
    """单笔**分项成本**净收益（%，名义本金 10 万元、100 股整手）—— 给「平均单笔」一栏用。"""
    if exit_px is None or not (np.isfinite(entry) and entry > 0) or not (np.isfinite(exit_px) and exit_px >= 0):
        return None
    if cost_cfg is None:
        return float((exit_px / entry - 1.0) * 100)
    shares = math.floor(notional / entry / lot) * lot
    if shares <= 0:
        return None
    amt = shares * entry
    fb = SP.cost_breakdown({"cost": cost_cfg}, entry, shares, "buy", notional_unit=1.0,
                           is_sh=str(sym)[:2] == "sh")["total"]
    gross = shares * exit_px
    fs = SP.cost_breakdown({"cost": cost_cfg}, exit_px, shares, "sell", notional_unit=1.0,
                           is_sh=str(sym)[:2] == "sh")["total"]
    return float(((gross - fs) / (amt + fb) - 1.0) * 100)


# ============================================================ 归因：v1.5 入选而 v1.6 未成交，原因是什么
def attribution(recs15, recs16, FD, FL, cal, syms, P, entries16, window_start):
    """逐笔归因 + 日内样例。口径：只在 entry_date ≥ window_start 上比。"""
    ci = {d: i for i, d in enumerate(cal)}
    si = {s: j for j, s in enumerate(syms)}
    topk_cache = {}

    def topk_of(t):
        if t not in topk_cache:
            topk_cache[t] = {syms[j] for j, _ in select_v16(FD, FL, syms, t, P)}
        return topk_cache[t]

    v15 = [r for r in recs15 if r["entry_date"] >= window_start]
    v16 = [r for r in recs16 if r["entry_date"] >= window_start]
    cnt = {}
    days = {}
    reasons = {}
    for r in v15:
        t = ci.get(r["signal_date"])
        if t is None:
            cat = "signal_date_not_in_calendar"
        else:
            d = diag_v16(FD, syms, t, si[r["sym"]])
            topk = topk_of(t)
            if r["sym"] not in topk:
                cat = "not_in_v16_topK"
            elif d["fill_px"] is None:
                rs = d["reason"]
                cat = ("limit_up_open" if "涨停" in rs else
                       "suspended" if "停牌" in rs else
                       "no_open" if "无今开" in rs else
                       "gap_above_hi" if "上沿" in rs else
                       "gap_below_lo" if "下沿" in rs else "other:" + rs)
            else:
                cat = "filled_in_v16" if (r["entry_date"], r["sym"]) in entries16 else "v16_in_band_but_no_slot"
        cnt[cat] = cnt.get(cat, 0) + 1
        days.setdefault(r["signal_date"], []).append((r["sym"], cat))
        reasons.setdefault(cat, []).append((r["signal_date"], r["sym"]))
    # v1.6 自己名单的成交原因分布（带外在这里才是主因）
    v16_cnt = {}
    for r in v16:
        rs = r["entry_reason"]
        cat = ("in_band_filled" if r["band_hit"] else
               "limit_up_open" if "涨停" in rs else
               "suspended" if "停牌" in rs else
               "no_open" if "无今开" in rs else
               "gap_above_hi" if "上沿" in rs else
               "gap_below_lo" if "下沿" in rs else "other")
        v16_cnt[cat] = v16_cnt.get(cat, 0) + 1
    ex = [k for k, v in sorted(days.items()) if all(c != "filled_in_v16" for _, c in v)][:5]
    return dict(n_v15_picks=len(v15), n_v16_picks=len(v16),
                v15_pick_fate=cnt, v16_pick_fate=v16_cnt,
                required_categories=dict(
                    带外=sum(v16_cnt.get(k, 0) for k in ("gap_above_hi", "gap_below_lo")),
                    涨停=v16_cnt.get("limit_up_open", 0),
                    停牌=v16_cnt.get("suspended", 0),
                    带内成交=v16_cnt.get("in_band_filled", 0)),
                same_category_examples={k: v[:8] for k, v in reasons.items()},
                days_where_v15_had_picks_and_v16_zero_fill=
                    {d: days[d] for d in ex})


# ============================================================ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.environ.get("PI_SCRATCH_DIR") or ".")
    ap.add_argument("--scratch", default=os.environ.get("PI_SCRATCH_DIR") or ".")
    ap.add_argument("--outdir", default=str(HERE))
    ap.add_argument("--anchor-tol", type=float, default=0.5, help="锚点容差（pp / 绝对值）")
    a = ap.parse_args()
    outdir = pathlib.Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    t00 = time.time()

    mod = load_mod()
    sha0 = mod.FROZEN_SHA
    log("冻结脚本 %s" % OOS)
    log("冻结脚本 SHA256 = %s" % sha0)
    assert sha0.startswith(SHA_PREFIX), "冻结脚本 SHA 变了（不许动 oos_run.py）：%s" % sha0
    cal, syms, dead, F, done, panel_src = load_panel(mod, a.cache)
    P = dict(mod.P)                                   # 冻结参数（只读副本）
    log("冻结参数 P = %s" % json.dumps(P, ensure_ascii=False, sort_keys=True))
    P_v15 = dict(P, SHADOW_START=SIGNAL_START, MAINBOARD=True)
    recs15 = frozen_recs(mod, P_v15, F, done, a.scratch)
    assert mod.FROZEN_SHA == sha0, "运行期冻结脚本 SHA 被改动！"
    log("[v1.5] 信号 %d 笔 (%s ~ %s)  面板=%s done=%d" %
        (len(recs15), recs15[0]["signal_date"] if recs15 else "-", recs15[-1]["signal_date"] if recs15 else "-",
         panel_src, done))

    FD = build_factors(cal, syms, F, dead, P, with_rr=(P.get("RR_MIN", 0.0) > 0))
    FL = build_filters(cal, syms, FD, dead, P)

    # ---- 对拍①：复刻出的 v1.5 名单 vs 冻结脚本产物（必须逐笔相等，否则基线是错的）
    rep = []
    for t in range(len(cal) - 1):
        if cal[t] < SIGNAL_START:
            continue
        picks, g = select_v15(FD, FL, syms, t, P)
        for j, _c in picks:
            rep.append((cal[t], syms[j], round(float(g[j]) * 100, 3)))
    fz = {(r["signal_date"], r["sym"], r["gap_pct"]) for r in recs15}
    rp = set(rep)
    missing = sorted(fz - rp)
    extra = sorted(rp - fz)
    parity = dict(replication_n=len(rep), frozen_n=len(fz), matched=len(fz & rp),
                  missing_in_replication=missing[:5], n_missing=len(missing),
                  extra_in_replication=extra[:5], n_extra=len(extra),
                  ok=bool(not missing))
    log("[对拍①] 复刻 v1.5 名单 %d 笔 vs 冻结产物 %d 笔 → 缺 %d / 多 %d" %
        (len(rep), len(fz), len(missing), len(extra)))
    assert not missing, "复刻的 elig/复合分与冻结脚本不一致（前 5：%s）" % missing[:5]

    # ---- v1.6 逐笔（可执行口径）
    recs16 = build_v16_trades(FD, FL, cal, syms, P, SIGNAL_START)
    log("[v1.6] 候选 %d 笔；带内成交候选 %d 笔" %
        (len(recs16), sum(1 for r in recs16 if r["band_hit"])))

    # ---- 三臂组合指标
    r15n = [dict(sym=r["sym"], entry_date=r["entry_date"], entry_px=r["entry_open"], exit_date=r["exit_date"],
                 exit_px=r["exit_px"], ret_pct=r["ret_pct"], filled=1) for r in recs15]
    m15, nav15, idx15, en15, ex15 = sim(r15n, cal, syms, FD, K_TOP, KSLOT, cost_side=P["COST_SIDE"],
                                        start=WINDOW_START, lot=1)
    m16, nav16, idx16, en16, ex16 = sim(recs16, cal, syms, FD, K_TOP, KSLOT, cost_cfg=COST_CFG,
                                        start=WINDOW_START, lot=100)
    mC, _, _, enC, exC = sim(recs16, cal, syms, FD, K_TOP, KSLOT, cost_side=P["COST_SIDE"],
                             start=WINDOW_START, lot=1)
    log("[臂A·v1.5 研究上界] %s" % json.dumps({k: m15[k] for k in
        ("ann", "mdd", "sharpe", "win_rate", "mean_per_trade", "n_signals", "n_entries", "deploy_pct")},
        ensure_ascii=False))
    log("[臂B·v1.6 可执行　] %s" % json.dumps({k: m16[k] for k in
        ("ann", "mdd", "sharpe", "win_rate", "mean_per_trade", "n_signals", "n_entries", "deploy_pct")},
        ensure_ascii=False))
    log("[臂C·成本隔离　　] %s" % json.dumps({k: mC[k] for k in
        ("ann", "mdd", "sharpe", "win_rate", "mean_per_trade", "n_signals", "n_entries", "deploy_pct")},
        ensure_ascii=False))

    # ---- 对拍②：同尺子锚点（evidence_sensitivity.json subwindow_2018）
    anch = {"anchor_source": "backtest/hengpan_fangliang_dikai_0925/evidence_sensitivity.json (subwindow_2018 · base 臂)",
            "note": "锚点窗口至 2026-09-24；本机数据至 2026-09-29 ⇒ 允许小差", "checked": {}}
    ok_anchor = True
    for k, want in ANCHOR_2018.items():
        got = m15.get(k) if k != "n_trades" else m15.get("n_signals")
        if got is None:
            good = False
        elif isinstance(want, int):
            good = abs(int(got) - int(want)) <= 60
        else:
            good = abs(float(got) - float(want)) <= max(a.anchor_tol, abs(float(want)) * 0.01)
        ok_anchor = ok_anchor and good
        anch["checked"][k] = dict(got=got, expect=want, pass_=bool(good))
    anch["ok"] = bool(ok_anchor)
    log("[对拍②] subwindow_2018 锚点：%s" % ("通过" if ok_anchor else "有偏差（见 evidence JSON）"))

    # ---- 逐笔净收益（分项成本 · 名义本金 10 万 · 100 股整手）与名义成本
    held = [r for r in recs16 if r["filled"] and r["exit_px"] is not None]
    nets = [net_ret_notional(r["entry_px"], r["exit_px"], r["sym"], cost_cfg=COST_CFG) for r in held]
    nets = [x for x in nets if x is not None]
    netsc = [net_ret_notional(r["entry_px"], r["exit_px"], r["sym"], cost_cfg=None) for r in held]
    netsc = [x for x in netsc if x is not None]
    trade16 = dict(n=len(nets), mean_pct=round(float(np.mean(nets)), 4) if nets else None,
                   med_pct=round(float(np.median(nets)), 4) if nets else None,
                   win_pct=round(float(100 * np.mean([x > 0 for x in nets])), 2) if nets else None,
                   tp_hit_pct=round(100 * np.mean([r["tp_hit"] for r in held]), 2) if held else None,
                   notional=100000.0, lot=100,
                   gross_mean_pct=round(float(np.mean(netsc)), 4) if netsc else None,
                   cost_drag_pp=round(float(np.mean(netsc) - np.mean(nets)), 4) if nets and netsc else None)
    log("[v1.6 逐笔] %s" % json.dumps(trade16, ensure_ascii=False))

    # ---- 归因
    attr = attribution(recs15, recs16, FD, FL, cal, syms, P, en16, WINDOW_START)
    log("[归因·v1.5 入选者的去向] %s" % json.dumps(attr["v15_pick_fate"], ensure_ascii=False))
    log("[归因·v1.6 名单的成交原因] %s" % json.dumps(attr["v16_pick_fate"], ensure_ascii=False))
    log("[归因·必需分类] %s" % json.dumps(attr["required_categories"], ensure_ascii=False))

    # ---- P6 探针（竞价下单时点可执行性）：两臂对照
    p6_16 = AU.probe_auction_order_admissibility([dict(sym=r["sym"], entry_px=r["entry_px"],
                                                       entry_open=r["entry_open"], order_time=r["order_time"],
                                                       fill_ref="open") for r in held])
    p6_15 = AU.probe_auction_order_admissibility([dict(sym=r["sym"], entry_px=r["entry_open"],
                                                       entry_open=r["entry_open"], fill_ref="open")
                                                  for r in recs15 if r["entry_date"] >= WINDOW_START])
    log("[P6] v1.6=%s" % json.dumps({k: p6_16[k] for k in ("n", "n_fill_at_open", "n_bad", "ok")}, ensure_ascii=False))
    log("[P6] v1.5=%s" % json.dumps({k: p6_15[k] for k in ("n", "n_fill_at_open", "n_bad", "ok")}, ensure_ascii=False))

    # ---- 落盘
    tf = outdir / "oos_v16_trades.jsonl"
    with tf.open("w", encoding="utf-8") as fh:
        for r in recs16:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    def arm(m):
        return None if m is None else {k: m[k] for k in
            ("ann", "mdd", "sharpe", "win_rate", "mean_per_trade", "med_per_trade", "n_signals",
             "n_entries", "deploy_pct", "exec_n", "exec_mean", "exec_med", "exec_win", "n_years",
             "neg_years", "window", "yearly")}
    rep_json = dict(
        generated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        rule_version=SP.rule_version(dict(provenance=dict(rule_version="hpdk-oos-v16-executable"),
                                          cost=COST_CFG,
                                          clock=dict(band_lo=BAND_LO, band_hi=BAND_HI, order_time=ORDER_TIME,
                                                     silent_window="09:25-09:30", cancel_window_end="09:20"))),
        frozen_script=dict(path=str(OOS.relative_to(R)).replace("\\", "/"), sha256=sha0,
                           bytes_untouched=bool(mod.FROZEN_SHA == sha0)),
        v16_script=dict(path=str(pathlib.Path(__file__).resolve().relative_to(R)).replace("\\", "/"),
                        sha256=sha256_of(pathlib.Path(__file__).resolve())),
        panel=dict(source=panel_src, T=int(FD["C"].shape[0]), N=int(FD["C"].shape[1]), names_loaded=int(done)),
        window=dict(signal_start=SIGNAL_START, portfolio_start=WINDOW_START, data_end=cal[-1]),
        band=dict(lo=BAND_LO, hi=BAND_HI, order_time=ORDER_TIME, fill_price="今开（09:25 撮合）"),
        cost=dict(v16=COST_CFG, v15=dict(mode="round_trip", side=P["COST_SIDE"], note="v1.5 冻结单边成本")),
        params=dict(P_v15=P_v15, K=K_TOP, KSLOT=KSLOT, NOTIONAL_UNIT=NOTIONAL_UNIT),
        parity=dict(replication_vs_frozen=parity, anchor_2018=anch),
        arms=dict(v15_research_upper_bound=arm(m15), v16_executable=arm(m16),
                  v16_executable_same_cost=arm(mC)),
        trade_level_v16=trade16,
        attribution=attr,
        probe_p6_auction_order_admissibility=dict(v16=p6_16, v15=p6_15),
        runtime_sec=round(time.time() - t00, 1))
    jf = outdir / ("evidence_v16_executable_compare_%s.json" % datetime.datetime.now().strftime("%Y%m%d"))
    jf.write_text(json.dumps(rep_json, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 对照表（stdout）
    log("\n=== v1.5（研究上界） vs v1.6（可执行） · K=%d KSLOT=%d · %s~%s ===" % (K_TOP, KSLOT, WINDOW_START, cal[-1]))
    log("| 口径 | 笔数(信号级) | 年化 | 最大回撤 | 夏普 | 胜率 | 平均单笔 | 实际建仓 | 平均仓位 |")
    log("|---|---|---|---|---|---|---|---|---|")
    for nm, m in (("v1.5 研究上界（v1.5 成本）", m15), ("v1.6 可执行（分项成本）", m16),
                  ("v1.6 可执行（v1.5 成本·成本隔离）", mC)):
        if m is None:
            log("| %s | — |" % nm)
            continue
        log("| %s | %d | %.2f%% | %.2f%% | %s | %.2f%% | %.4f%% | %d | %.2f%% |" %
            (nm, m["n_signals"], m["ann"], m["mdd"], m["sharpe"], m["win_rate"] or 0.0,
             m["mean_per_trade"] or 0.0, m["n_entries"], m["deploy_pct"]))
    rc2 = attr["required_categories"]
    n16 = attr["n_v16_picks"] or 1
    log("| v1.6 名单成交原因（entry_date ≥ %s，n=%d） | 带内成交 %d（%.2f%%） | 带外·上沿 %d | 带外·下沿 %d | 涨停开盘 %d | 停牌 %d |" %
        (WINDOW_START, attr["n_v16_picks"], rc2["带内成交"], 100.0 * rc2["带内成交"] / n16,
         attr["v16_pick_fate"].get("gap_above_hi", 0), attr["v16_pick_fate"].get("gap_below_lo", 0),
         rc2["涨停"], rc2["停牌"]))
    log("| v1.5 入选者（entry_date ≥ %s，n=%d）的去向 | 不在 v1.6 前 K 名单 %d | 被 v1.6 建仓 %d | 带内但无槽位 %d |" %
        (WINDOW_START, attr["n_v15_picks"], attr["v15_pick_fate"].get("not_in_v16_topK", 0),
         attr["v15_pick_fate"].get("filled_in_v16", 0),
         attr["v15_pick_fate"].get("v16_in_band_but_no_slot", 0)))
    log("| v1.6 逐笔（分项成本 · 名义 10 万 · 100 股整手） | n=%s | 净均 %s%% | 净中位 %s%% | 胜率 %s%% | 止盈占比 %s%% | 成本拖累 %s pp |" %
        (trade16["n"], trade16["mean_pct"], trade16["med_pct"], trade16["win_pct"], trade16["tp_hit_pct"],
         trade16["cost_drag_pp"]))
    log("| P6 竞价下单时点探针 | v1.6 违规 %d/%d | v1.5 违规 %d/%d（缺 order_time ⇒ 不可执行） |" %
        (p6_16["n_bad"], p6_16["n_fill_at_open"], p6_15["n_bad"], p6_15["n_fill_at_open"]))
    log("写入 %s / %s" % (tf.name, jf.name))
    log("运行 %.1fs" % (time.time() - t00))


if __name__ == "__main__":
    main()
