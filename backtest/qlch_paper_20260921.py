# -*- coding: utf8 -*-
"""qlch_paper · 潜龙出海族改造策略「C1 臂」生产模拟盘（R-sharesweb-0921f）

策略：C1 = 超跌(ret20(T-1)<=-7.31%) + 低吸(T+1开盘 gap∈[-5%,-2%]) + 熊市门(HS300(T)<MA20(T))
      共有滤网：非ST / 流通市值50-200亿 / 量比>=1.2 / 换手率5-10%
来源：报告-sharesweb方向改造-超跌假设成立未达门-20260921.md
      报告-sharesweb牛熊分域与择时-熊市门臂9过9-20260921.md
      报告-sharesweb口径澄清与资金利用-20260921.md

执行时序（无前视）：
  T 收盘    → 算超跌条件(T-1口径) + 熊市门(T日HS300 vs MA20) → 候选集
  T+1 开盘  → 对每个候选算 gap=O(T+1)/C(T)-1，落在[-5%,-2%] 才买，成交价=O(T+1)
  出场 = 止盈 +15% / 止损 −20% / 上限 20 交易日（T+1 合规：入场日不可卖）
日更口径：脚本在 D 日收盘后跑，此时 D 的开/收、D-1 的收盘都已知 → 直接判定 D 日是否成交。

与 Khunter 并行（用户 2026-09-21 批准）：实测重叠——C1 信号日落入 Khunter 合格池
比例中位 0.0%、门 Jaccard 0.462 → 真分散。两账户独立记账，不互相影响。

已知缺陷（投产时明示，见预注册）：
  1. 50bp 成本门实质未过（修正 ★197 后 C1 按天等权持仓日净均仅 +0.014%，全期年化 -0.42%）
  2. 熊市门为样本内选择（OOS 2022-2026 5/5 正、衰减 23%，但仍属事后）
  3. 年化 11.78%（含国债ETF现金叠加）< 12% 毕业门
"""
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent          # quant-weight-system
BK = Path(__file__).resolve().parent                   # backtest
PANEL = BK / "kv_resonance_0913" / "panel_kv_0913.npz"
VAL = BASE / "data_fundamental" / "val_em"
NAMES = BASE / "data_full_names.json"
IDX = BASE / "index_000300.csv"
if "--variant" in sys.argv:
    os.environ["QLCH_VARIANT"] = sys.argv[sys.argv.index("--variant") + 1]
if "--maxpos" in sys.argv:
    os.environ["QLCH_MAXPOS"] = sys.argv[sys.argv.index("--maxpos") + 1]
if "--mainboard" in sys.argv:
    os.environ["QLCH_MAINBOARD"] = "1"
# R-qlch-sealed-0922：候选臂挂前向采集轨（封存集 2026-09-22 起）
if "--gate" in sys.argv:
    os.environ["QLCH_GATE"] = sys.argv[sys.argv.index("--gate") + 1]
if "--select" in sys.argv:
    os.environ["QLCH_SELECT"] = sys.argv[sys.argv.index("--select") + 1]
VARIANT = os.environ.get("QLCH_VARIANT", "C1")   # C1=基线(绝对滤网) | B4=分位带滤网
MAXPOS = int(os.environ.get("QLCH_MAXPOS", "0")) or None   # 单票权重上限 K（n>K 随机取 K）
MAINBOARD = os.environ.get("QLCH_MAINBOARD", "0") == "1"    # 只买真主板（剔科创板 688）
GATE_MA = int(os.environ.get("QLCH_GATE", "20")) or None    # 熊市门均线周期（0/空 = 无门）
SELECT = os.environ.get("QLCH_SELECT", "random")            # random | depth | gap | combo
if GATE_MA is None:
    _TAGS = "_nogate"
elif GATE_MA != 20:
    _TAGS = "_gate%d" % GATE_MA
else:
    _TAGS = ""
_STEM = "qlch_paper_state%s%s%s%s%s.json" % ("_b4" if VARIANT == "B4" else "",
                                             ("_k%d" % MAXPOS) if MAXPOS else "",
                                             "_mb" if MAINBOARD else "",
                                             _TAGS,
                                             ("_%s" % SELECT) if SELECT != "random" else "")
STATE = BK / _STEM

# ===== 策略参数（冻结，改参数须新预注册）=====
R20_MAX = -0.0731        # 池A 超跌：T-1 的 20 日收益 ≤ -7.31%
GAP_LO, GAP_HI = -0.05, -0.02   # T+1 开盘低吸区间
MCAP_LO, MCAP_HI = 50.0, 200.0  # 流通市值 亿
VR_MIN = 1.2             # 量比
TURN_LO, TURN_HI = 0.05, 0.10   # 换手率
COST_RT = 0.002          # 往返 20bp（成本档见预注册，50bp 为压力档）
CASH_CODE = "sh511010"   # 空仓期国债ETF（可选现金叠加，默认关）
USE_CASH = os.environ.get("QLCH_CASH", "0") == "1"

DRY = "--dry" in sys.argv
FORCE_DATE = None
if "--date" in sys.argv:
    FORCE_DATE = sys.argv[sys.argv.index("--date") + 1]


def log(*a):
    print("[%6.1fs]" % (time.time() - t0), *a, flush=True)


t0 = time.time()


# ---------------- 数据 ----------------
def load_all():
    z = np.load(PANEL, allow_pickle=True)
    cal = [str(x) for x in z["cal"]]
    P = {"close": z["close"].astype(np.float64), "open": z["open"].astype(np.float64),
         # 2026-09-22 R-qlch-t1exit-0922：E4 日内触发需 high/low（陷阱库 179-186）
         "high": z["high"].astype(np.float64), "low": z["low"].astype(np.float64),
         "amount": z["amount"].astype(np.float64), "mask": z["mask"].astype(bool),
         "cal": cal, "codes": [str(x) for x in z["codes"]]}
    vm = pd.concat([pd.read_csv(VAL / f, usecols=["code", "date", "float_mv"],
                                dtype={"code": str})
                    for f in ("val_em_pre2021.csv", "val_em_all.csv", "val_em_ext.csv")],
                   ignore_index=True)
    vm["code"] = vm["code"].str.zfill(6)
    vm = vm.drop_duplicates(subset=["code", "date"], keep="last")
    c2j = {c: j for j, c in enumerate(P["codes"])}
    d2i = {d: i for i, d in enumerate(cal)}
    vm["j"] = [c2j.get(("sh" + c) if c.startswith("6") else ("sz" + c), -1) for c in vm["code"]]
    vm["i"] = [d2i.get(str(d), -1) for d in vm["date"]]
    vm = vm[(vm.j >= 0) & (vm.i >= 0)]
    fm = np.full(P["close"].shape, np.nan)
    fm[vm.i.values, vm.j.values] = vm.float_mv.values
    P["float_mv"] = fm
    P["names"] = {str(k): str(v) for k, v in json.load(open(NAMES, encoding="utf-8")).items()}
    # 行业（R-dash-track-0922：候选表需要行业列）
    _ind_names = [str(x) for x in z["ind_names"]]
    _ind_id = np.asarray(z["ind_id"]).astype(np.int32)
    P["ind_map"] = {str(c): (_ind_names[_ind_id[i]] if 0 <= _ind_id[i] < len(_ind_names) else "")
                    for i, c in enumerate(P["codes"])}
    return P


def build_signals(P):
    C, O, A, M = P["close"], P["open"], P["amount"], P["mask"]
    cal, codes = P["cal"], P["codes"]
    T, N = C.shape
    sys.path.insert(0, str(BK))
    import factor_gate as FG
    prev_c = np.full_like(C, np.nan); prev_c[1:] = C[:-1]
    chg = np.where(np.isfinite(prev_c) & (prev_c > 0), C / np.where(prev_c > 0, prev_c, 1.0) - 1.0, np.nan)
    amt5 = FG.roll_trailing(A, 5, "mean")
    vr = np.where(np.isfinite(amt5) & (amt5 > 0), A / np.where(amt5 > 0, amt5, 1.0), np.nan)
    turn = np.where(np.isfinite(P["float_mv"]) & (P["float_mv"] > 0) & (C > 0),
                    A / np.where(P["float_mv"] > 0, P["float_mv"], 1.0), np.nan)
    mcap = P["float_mv"] / 1e8
    valid = M & np.isfinite(C) & (C > 0) & np.isfinite(O) & (O > 0) & np.isfinite(A) & (A > 0)
    if MAINBOARD:
        # 真主板 = sh600/601/603/605 + sz000/001/002/003（剔科创板 688）
        mb = np.zeros(N, dtype=bool)
        for j, c in enumerate(codes):
            p_, n_ = c[:2], c[2:]
            mb[j] = (p_ == "sh" and n_[:3] in ("600", "601", "603", "605")) or                     (p_ == "sz" and n_[:3] in ("000", "001", "002", "003"))
        valid = valid & mb[None, :]
    ret20 = np.full((T, N), np.nan); ret20[20:] = C[20:] / C[:-20] - 1.0
    ret20_m1 = np.full_like(ret20, np.nan); ret20_m1[1:] = ret20[:-1]
    is_st = np.zeros((T, N), dtype=bool)
    for j, c in enumerate(codes):
        if "ST" in (P["names"].get(c, "") or "").upper():
            is_st[:, j] = True
    if VARIANT == "B4":
        # B4：市值/换手 绝对区间 → 当日横截面分位带（R-qlch-filter-0921k）
        # 分位基准 = 当日全部有效股票（非自指）；量比/非ST 保持绝对
        PM = pd.DataFrame(np.where(valid, mcap, np.nan)).rank(axis=1, pct=True).values
        PT = pd.DataFrame(np.where(valid, turn, np.nan)).rank(axis=1, pct=True).values
        MCF = np.isfinite(PM) & (PM >= 0.20) & (PM <= 0.70)
        TNF = np.isfinite(PT) & (PT >= 0.40) & (PT <= 0.80)
    else:
        MCF = np.isfinite(mcap) & (mcap >= MCAP_LO) & (mcap <= MCAP_HI)
        TNF = np.isfinite(turn) & (turn >= TURN_LO) & (turn <= TURN_HI)
        # 2026-09-22 修（R-qlch-t1exit-0922 顺带发现）：C1 无分位口径，下面 `_PM, _PT = PM, PT`
        #   无条件执行 → C1 轨自 R-dash-track-0922 加列起一直 UnboundLocalError。
        #   日链标 [软] 不阻断 → 静默死亡。补 NaN 占位。
        PM = PT = np.full((T, N), np.nan)
    COMMON = ((~is_st) & MCF & np.isfinite(vr) & (vr >= VR_MIN) & TNF & valid)
    _PM, _PT = PM, PT
    OVERSOLD = COMMON & np.isfinite(ret20_m1) & (ret20_m1 <= R20_MAX)
    # 指数门：T 日 HS300 < MA20
    idx = pd.read_csv(IDX, parse_dates=["date"])
    ic = idx.close.astype(np.float64).values
    ima20 = (pd.Series(ic).rolling(GATE_MA).mean().values if GATE_MA
             else np.full(len(ic), np.nan))
    i2t = {d.strftime("%Y-%m-%d"): k for k, d in enumerate(idx.date)}
    bear = np.zeros(T, dtype=bool)
    for t, d in enumerate(cal):
        k = i2t.get(d)
        if GATE_MA is None:
            bear[t] = True
        elif k is not None and np.isfinite(ima20[k]):
            bear[t] = bool(ic[k] < ima20[k])
    # gap：O(D)/C(D-1)-1
    gap = np.full((T, N), np.nan)
    gap[1:] = O[1:] / C[:-1] - 1.0
    gap[1:] = np.where(np.isfinite(O[1:]) & (O[1:] > 0) & np.isfinite(C[:-1]) & (C[:-1] > 0),
                       gap[1:], np.nan)
    # T 日候选（T 日判定），T+1 = D 日开盘成交
    cand = OVERSOLD & bear[:, None]
    return {"cal": cal, "codes": codes, "cand": cand, "gap": gap,
            "open": O, "close": C, "high": P["high"], "low": P["low"],
            "valid": valid, "names": P["names"],
            "ind_map": P.get("ind_map", {}),
            "r20": ret20_m1, "vr": vr, "turn": turn, "mcap": mcap,
            "pm": _PM, "pt": _PT}


def state_default():
    return {"created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "strategy": "超跌低吸" + ("（B4 分位滤网）" if VARIANT == "B4" else "（绝对滤网）")
                        + (("（K=%d 单票上限）" % MAXPOS) if MAXPOS else "")
                        + ("（真主板）" if MAINBOARD else "（全池）"),
            "variant": VARIANT, "maxpos": MAXPOS,
            "cash": 0.0, "positions": [], "trades": [], "equity": [],
            "events": [], "last_run": None}


def load_state():
    if STATE.exists():
        return json.load(open(STATE, encoding="utf-8"))
    return state_default()


def save_state(st):
    st["events"] = (st.get("events") or [])[-60:]
    json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


CAND_OUT = BK / "qlch_candidates.json"


def save_candidates(D, rows):
    """今日收盘候选（等 D+1 开盘 gap 判定 → 入场）。多轨共用一份，按轨分列。"""
    cur = {}
    if CAND_OUT.exists():
        try:
            cur = json.load(open(CAND_OUT, encoding="utf-8"))
        except Exception:
            cur = {}
    key = "%s%s%s" % (VARIANT, ("_K%d" % MAXPOS) if MAXPOS else "", "_MB" if MAINBOARD else "")
    cur.setdefault("by_track", {})[key] = {
        "as_of": D, "pool": "真主板" if MAINBOARD else "全池",
        "filter": "B4 分位[.20,.70]/[.40,.80]" if VARIANT == "B4" else "绝对[50,200]亿/[5%,10%]",
        "maxpos": MAXPOS,
        "gap_window": [GAP_LO, GAP_HI],
        "n": len(rows),
        "codes": rows,
    }
    cur["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    sys.path.insert(0, str(BASE))                     # 北交所硬闸（R-no-bj-0923）：写盘前断言
    from no_bj import assert_clean as _assert_clean
    _assert_clean(cur, "qlch_candidates.json")
    json.dump(cur, open(CAND_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def main():
    P = load_all()
    S = build_signals(P)
    cal, codes, cand, gap = S["cal"], S["codes"], S["cand"], S["gap"]
    O, C, valid, names = S["open"], S["close"], S["valid"], S["names"]
    H, L = S["high"], S["low"]
    T, N = C.shape
    d2i = {d: i for i, d in enumerate(cal)}
    D = FORCE_DATE or cal[-1]
    # R-qlch-stale-0922 防复发闸：面板未延展时必须响亮失败。
    # 事故：2026-09-22 上游 revscreen_regen 因相对路径崩溃 → 面板延展未落盘 →
    #       D 停在 09-21 → 六臂全部「已在账本中 → 幂等跳过」→ 看板该段静默陈旧一天。
    #       此后「D 滞后于交易日」= 硬错误（退 3），不再进入幂等跳过分支。
    if FORCE_DATE is None and IDX.exists():
        _td = pd.read_csv(IDX, dtype={"date": str})["date"].iloc[-1]
        if D != _td:
            log("!! 面板未延展：面板末 %s != 交易日 %s —— 上游 revscreen_regen 的延展未落盘；"
                "拒绝静默陈旧，本次不产出信号（修上游后重跑）" % (D, _td))
            sys.exit(3)
    if D not in d2i:
        log("日期 %s 不在面板内（末 %s）" % (D, cal[-1])); return
    t = d2i[D]
    if t < 1:
        log("首日无法判定（需 D-1 收盘）"); return
    st = load_state()
    # 今日收盘候选（D 日收盘判定 → 等 D+1 开盘 gap 过滤后入场）
    _cand_today = np.where(cand[t])[0]
    _prevC = C[t - 1] if t >= 1 else np.full(N, np.nan)
    _imap = S.get("ind_map", {})
    _rows = []
    for j in _cand_today:
        _c = float(C[t, j]) if np.isfinite(C[t, j]) else None
        _p = float(_prevC[j]) if np.isfinite(_prevC[j]) and _prevC[j] > 0 else None
        def _g(k, nd=4):
            v = S[k][t, j] if k in S else np.nan
            return round(float(v), nd) if np.isfinite(v) else None
        _rows.append({
            "code": codes[j], "name": names.get(codes[j], ""),
            "board": "沪主板" if codes[j][:2] == "sh" else "深主板",
            "ind": _imap.get(codes[j], ""),
            "close": round(_c, 3) if _c is not None else None,
            "chg": (round(_c / _p - 1.0, 6) if (_c is not None and _p) else None),
            # 信号驱动指标（2026-09-22 用户：表格太简单，指标没体现）
            "r20": _g("r20"), "vr": _g("vr", 3), "turn": _g("turn"),
            "mcap": _g("mcap", 2), "pm": _g("pm"), "pt": _g("pt"),
        })
    # 默认按超跌深度排序（越负越前）——**仅展示排序，策略的 K=3 取法是随机的**
    _rows.sort(key=lambda r: (r.get("r20") if r.get("r20") is not None else 0.0))
    for _i, _r in enumerate(_rows, 1):
        _r["rank"] = _i
    log("今日收盘候选（D=%s，按 %s 池）：%d 只" % (D, "真主板" if MAINBOARD else "全池", len(_rows)))
    for _r in _rows[:8]:
        log("    候选 %-9s %-8s %-6s %-8s %s" % (_r["code"], str(_r["name"])[:8],
            _r["board"], _r["ind"][:6], ("%+.2f%%" % (_r["chg"] * 100)) if _r.get("chg") is not None else "—"))
    if not DRY:
        save_candidates(D, _rows)
    # ---- 幂等守卫：同一日期重复运行会把收益重复计（日链 --force 会踩到）----
    if any(e.get("date") == D for e in st.get("equity", [])):
        log("D=%s 已在账本中 → 幂等跳过（防重复计收益）" % D)
        return
    # ================= E4 出场规则（T+1 合规，R-qlch-t1exit-0922）=================
    # 原实现 =「当日开盘买 → 当日收盘卖」= T+0 回转，A 股 T+1 交割下不可执行（★198 复发）。
    # 现为：止盈 +15% / 止损 −20% / 上限 20 交易日；入场日不可卖（T+1），最早次日。
    # 日内触发用 low/high（陷阱库 179-186）：同 bar 止损优先；跳空按 open 成交；到期按收盘平仓。
    # 2026-09-23 用户授权改生产（方案 B：以「事件级配对 + 机制一致性」为依据）。
    # X0(15/-20/20) -> X4(25/-30/40)。证据：
    #   事件级同事件配对（同一次入场仅换出场）：真主板 +3.014pp/笔 full CI[+1.711,+4.272]；
    #     全池（= 在产轨 B4_K3）+3.107pp/笔 full CI[+0.838,+5.056]、val +4.504pp CI[+0.986,+6.977]。
    #   机制：止损被打掉占比 4.37% -> 1.6-2.4%；换手 16.1 -> 10.1 次/年；成本越高优势越大（S60 > P20）。
    #   ★ 组合级**未获确证**（配对 Δ日均 / Δ夏普 均不可判定；达功率门需 ~122 年样本）——本改动属"事件级+机制"决策。
    # 回滚：本行改回 0.15, -0.20, 20 即可。记录见 backtest/生产变更-qlch出场参数-20260923.md
    TP_PCT, SL_PCT, MAXHOLD = 0.25, -0.30, 40
    c2j = {c: j for j, c in enumerate(codes)}

    # ---- 1) 先处理存量持仓出场（入场日 >= t 的一律跳过 = T+1）----
    exits_today, _still = [], []
    for _p in st.get("positions", []):
        _j = c2j.get(_p["code"]); _e = d2i.get(_p.get("entry_date"))
        if _j is None or _e is None or _e >= t:
            _still.append(_p); continue
        _o, _h, _l, _c = O[t, _j], H[t, _j], L[t, _j], C[t, _j]
        _tp, _sl = _p["entry_px"] * (1 + TP_PCT), _p["entry_px"] * (1 + SL_PCT)
        _px = _why = None
        if np.isfinite(_o) and _o <= _sl:
            _px, _why = _o, "止损跳空"
        elif np.isfinite(_o) and _o >= _tp:
            _px, _why = _o, "止盈跳空"
        elif np.isfinite(_l) and _l <= _sl:
            _px, _why = _sl, "止损触发"          # 同 bar：止损优先于止盈
        elif np.isfinite(_h) and _h >= _tp:
            _px, _why = _tp, "止盈触发"
        elif (t - _e) >= MAXHOLD - 1:
            # 2026-09-23 口径对齐（用户授权）：到期日 = 入场日 + MAXHOLD − 1，即持有 ≤ MAXHOLD 个交易日。
            # 原实现为 (t-e) >= MAXHOLD → 实际持有 MAXHOLD+1 日，与回测/网格（exit_plan 的 k_eff=H-1）
            # 差一天；到期平仓占成交 47%~65%，故必须对齐（证据口径见 生产变更-qlch出场参数-20260923.md）。
            _px, _why = _c, "到期平仓"
        if _px is None or not np.isfinite(_px):
            _still.append(_p); continue
        _q = dict(_p)
        _q.update(exit_date=D, exit_px=float(_px),
                  raw_ret=float(_px) / _p["entry_px"] - 1.0,
                  net_ret=float(_px) / _p["entry_px"] - 1.0 - COST_RT,
                  hold_days=int(t - _e + 1), exit_reason=_why)
        exits_today.append(_q)
    st["positions"] = _still

    # ---- 2) 再处理今日入场（D-1 收盘判定 ∩ D 日 gap 过滤）----
    candset = np.where(cand[t - 1] & np.isfinite(gap[t])
                       & (gap[t] >= GAP_LO) & (gap[t] <= GAP_HI) & valid[t])[0]
    log("D=%s  候选(D-1超跌+熊市门) ∩ gap[%+.0f%%,%+.0f%%] = %d 只"
        % (D, GAP_LO * 100, GAP_HI * 100, len(candset)))
    _room = None if not MAXPOS else max(MAXPOS - len(st["positions"]), 0)
    newpos = []
    if candset.size and (_room is None or _room > 0):
        _idx = [int(x) for x in candset]
        if _room is not None and len(_idx) > _room:
            if SELECT == "random":
                _rng = np.random.default_rng(20260921)
                _idx = [_idx[i] for i in sorted(_rng.choice(len(_idx), size=_room, replace=False))]
            else:
                # R-qlch-sealed-0922：排序键在「入场日开盘下单时刻」全部已知，无前视
                _dd = np.nan_to_num(np.array([S["r20"][t - 1, jj] for jj in _idx], dtype=np.float64), nan=0.0)
                _gg = np.nan_to_num(np.array([gap[t, jj] for jj in _idx], dtype=np.float64), nan=0.0)
                if SELECT == "depth":
                    _key = _dd
                elif SELECT == "gap":
                    _key = _gg
                else:
                    _zz = lambda a: (a - a.mean()) / (a.std() + 1e-12)
                    _key = _zz(_dd) + _zz(_gg)
                _idx = [_idx[ii] for ii in sorted(range(len(_idx)), key=lambda ii: _key[ii])[:_room]]
        _w = (1.0 / MAXPOS) if MAXPOS else (1.0 / max(len(_idx), 1))
        for _j in _idx:
            if not np.isfinite(O[t, _j]) or O[t, _j] <= 0:
                continue
            newpos.append({"code": codes[_j], "name": names.get(codes[_j], ""),
                           "entry_date": D, "entry_px": float(O[t, _j]),
                           "gap": float(gap[t, _j]), "w": _w, "shares": 0})
    st["positions"] = st["positions"] + newpos

    # ---- 3) 净值：逐日 mark-to-market（出场日按实际成交价 + 计一次成本）----
    prevc = C[t - 1] if t >= 1 else np.full(N, np.nan)
    invested, port = 0.0, 0.0
    for _p in st["positions"]:
        _j = c2j.get(_p["code"])
        if _j is None:
            continue
        _w = _p.get("w", 0.0)
        if _p["entry_date"] == D:
            _b = _p["entry_px"]
            _x = C[t, _j] if np.isfinite(C[t, _j]) else _b
        else:
            _b = prevc[_j] if (np.isfinite(prevc[_j]) and prevc[_j] > 0) else _p["entry_px"]
            _x = C[t, _j] if np.isfinite(C[t, _j]) else _b
        if np.isfinite(_b) and _b > 0 and np.isfinite(_x):
            port += _w * (float(_x) / float(_b) - 1.0)
        invested += _w
    for _p in exits_today:
        _j = c2j.get(_p["code"])
        _b = prevc[_j] if (_j is not None and np.isfinite(prevc[_j]) and prevc[_j] > 0) else _p["entry_px"]
        port += _p.get("w", 0.0) * (_p["exit_px"] / float(_b) - 1.0 - COST_RT)
        invested += _p.get("w", 0.0)

    cashret = 0.0
    if USE_CASH:
        cf = BASE / "data_full" / (CASH_CODE + ".csv")
        if cf.exists():
            dd = pd.read_csv(cf, usecols=["date", "close"])
            m = {r.date: float(r.close) for r in dd.itertuples()}
            for k, d in enumerate(cal):
                if d == D:
                    pv = m.get(cal[k - 1]) if k > 0 else None
                    cv = m.get(d)
                    if pv and cv:
                        cashret = cv / pv - 1.0
                    break
    cash_w = max(1.0 - invested, 0.0)
    # 引擎不变量（R-extreview-0918 采纳项）：持仓权重和 > 100% 说明账本被污染或
    #   遗留持仓超限，会让净值变杠杆——不崩，但必须响。
    if invested > 1.0 + 1e-6:
        log("  ⚠ 不变量告警：持仓权重和 %.4f > 100%%（持仓 %d 只 / K=%s）——净值含杠杆，请查账本"
            % (invested, len(st["positions"]), MAXPOS))
    port += cash_w * cashret

    st.setdefault("trades", []).extend(exits_today)     # 只有真正出场的才入台账
    st["cash"] = round(cash_w, 6)
    prev_nav = st["equity"][-1]["nav"] if st.get("equity") else 1.0
    nav = prev_nav * (1.0 + port)
    st["equity"].append({"date": D, "nav": nav, "n": len(st["positions"]),
                         "port_ret": port, "cash_ret": cashret if cash_w > 1e-9 else 0.0,
                         "n_exit": len(exits_today), "n_new": len(newpos)})
    st["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if not DRY:
        save_state(st)

    for _p in newpos:
        log("  建仓 %-9s %-8s 开%.3f gap%+.2f%% w=%.3f"
            % (_p["code"], str(_p["name"])[:8], _p["entry_px"], _p["gap"] * 100, _p["w"]))
    for _p in exits_today:
        log("  出场 %-9s %-8s 开%.3f→%.3f 持%d日 [%s] 毛%+.2f%% 净%+.2f%%"
            % (_p["code"], str(_p["name"])[:8], _p["entry_px"], _p["exit_px"],
               _p["hold_days"], _p["exit_reason"], _p["raw_ret"] * 100, _p["net_ret"] * 100))
    log("持仓 %d 只（占用 %.1f%%，现金 %.1f%%）| 组合收益 %+.4f%% → nav %.6f（累计 %+.2f%%）"
        % (len(st["positions"]), invested * 100, cash_w * 100, port * 100, nav, (nav - 1) * 100))
    log("QLCH PAPER DONE [%s%s%s]（%s）" % (
        VARIANT, ("/K%d" % MAXPOS) if MAXPOS else "", "/主板" if MAINBOARD else "",
        "dry-run 未写盘" if DRY else "已写盘"))


if __name__ == "__main__":
    main()
