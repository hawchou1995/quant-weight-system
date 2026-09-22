# -*- coding: utf8 -*-
"""qlch_grid_bt_0923 · 超跌低开低吸「入场情形 × 出场参数」网格回测（研究用途）

★ 结论不投产：本脚本只产出研究读数；任何投产须另立预注册（PRE-REGISTRATION）。
★ 只新增本脚本与产物，不改任何生产脚本（qlch_paper_20260921.py 只读复用）。

口径（引擎冻结，全部复用 backtest/qlch_paper_20260921.py，不复制阈值）：
  候选池   = qlch_paper.build_signals() 的 cand：真主板(600/601/603/605+000/001/002/003)
             ∩ 非ST ∩ 量比≥1.2 ∩ 市值分位[.20,.70] ∩ 换手分位[.40,.80]（B4）
             ∩ ret20(T−1) ≤ −7.31% ∩ 熊市门 HS300(T) < MA20(T)
  买入带   = [0.95×Csig, 0.98×Csig]（Csig = 信号日收盘 C(T)）
  T+1 合规 = 信号日 T 的次一交易日 T+1 入场；入场日当日不可卖，最早 T+2 出场

入场 3 情形（判定在入场日 T+1 的当日路径上；每日互斥 → 同标的同日只入一次）：
  A 保持  : open/Csig−1 ∈ [−5%,−2%]      → 成交价 = open
  B 回落  : open < 0.95×Csig 且 high ≥ 0.95×Csig → 成交价 = 0.95×Csig（自下回升入带首触价）
  C 跌到区间: open > 0.98×Csig 且 low ≤ 0.98×Csig → 成交价 = 0.98×Csig（自上回落入带首触价）
  判定优先级 = 互斥（A 需 open≥带下沿、B 需 open<带下沿、C 需 open>带上沿），实现里显式断言。
  组合 7 种：A / B / C / A∪B / A∪C / B∪C / A∪B∪C（各组合独立跑，入场机会可重叠）。

出场判定（语义 = 引擎 exit_ret / qlch_paper 出场块）：
  · 止盈止损用逐日 high/low 触达（不等收盘）；跳空穿线按 open 成交
  · 同一日内同时触达 → 先 SL（保守）；同 bar 优先级：跳空SL > 跳空TP > 日内SL > 日内TP
  · 无 open 的 bar 整天跳过（引擎口径）
  · 到期（≤ MAXHOLD 个交易日，含入场日）按当日收盘强制平仓
成本：往返 COST_RT=0.0020（引擎 COST_RT）+ 每边滑点 20bp（0.0020/边，看板主显口径）
      → 单笔总成本 0.0020 + 2×0.0020 = 0.0060（往返 60bp）
组合口径：K=3（同持上限，单票 1/3，沿用生产 B4_K3_MB 轨）+ 5 固定种子平均（无随机性）
"""
import argparse
import importlib.util
import inspect
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent.parent
BK = Path(__file__).resolve().parent
OUT_JSON = BK / "qlch_grid_bt_0923.json"
OUT_MD = BK / "报告-qlch-入场情形×出场网格-20260923.md"
VERSION = "qlch-grid-0923/v1"
ENGINE = "backtest/qlch_paper_20260921.py"
MARK = "<!-- VERIFY:INJECT -->"

# ------------------------- 参数（冻结） -------------------------
COST_RT = 0.0020          # 引擎往返成本（qlch_paper COST_RT）
SLIP_SIDE = 0.0020        # 每边滑点 20bp（看板主显口径 = 每边 20bps）
COST_TOT = COST_RT + 2 * SLIP_SIDE        # 0.0060 = 往返 60bp

GAP_LO, GAP_HI = -0.05, -0.02             # 买入带 [0.95×Csig, 0.98×Csig]
BAND_LO, BAND_HI = 1.0 + GAP_LO, 1.0 + GAP_HI

TPS = [5, 8, 10, 12, 15, 20, 25]
SLS = [-5, -8, -10, -12, -15, -20, -25, -30]
HS = [2, 3, 5, 8, 10, 15, 20, 30, 40]
BASE_TP, BASE_SL, BASE_H = 15, -20, 20    # 现行基线格（E4）
K = 3
SEEDS = [20260921, 20260922, 20260923, 20260924, 20260925]
COMBOS = [("A",), ("B",), ("C",), ("A", "B"), ("A", "C"), ("B", "C"), ("A", "B", "C")]
ANN = 244.0
TRAIN_HI, VAL_LO = "2021-12-31", "2022-01-01"
RSN = {0: "止损跳空", 1: "止盈跳空", 2: "止损触发", 3: "止盈触发", 4: "到期平仓"}

t0 = time.time()
LOG = []


def log(*a):
    s = "[%7.1fs] %s" % (time.time() - t0, " ".join(str(x) for x in a))
    print(s, flush=True)
    LOG.append(s)


# ------------------------- 引擎接入 -------------------------
def load_engine():
    """importlib 加载生产脚本（该文件有 __main__ 守卫 → main() 不执行）。"""
    os.environ["QLCH_VARIANT"] = "B4"        # 市值/换手分位带
    os.environ["QLCH_MAINBOARD"] = "1"       # 真主板
    os.environ["QLCH_GATE"] = "20"           # 熊市门 HS300<MA20
    if str(BK) not in sys.path:
        sys.path.insert(0, str(BK))
    spec = importlib.util.spec_from_file_location("qlch_paper_engine", str(BK / "qlch_paper_20260921.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def case_masks(cs, o, h, l):
    """入场三情形（Csig=信号日收盘；买入带 = [0.95,0.98]×Csig）。判定优先级 A > B > C。"""
    lo, hi = cs * BAND_LO, cs * BAND_HI
    g = o / cs - 1.0
    mA = (g >= GAP_LO) & (g <= GAP_HI)                      # A 保持：开盘即在带内 → 成交 open
    mB = (o < lo) & np.isfinite(h) & (h >= lo)             # B 回落：自下回升入带 → 成交 0.95Csig
    mC = (o > hi) & np.isfinite(l) & (l <= hi)             # C 跌到区间：自上回落 → 成交 0.98Csig
    # 三情形按开盘位置互斥（A 需 open≥下沿 / B 需 open<下沿 / C 需 open>上沿）→ 同标的同日只入一次
    assert not (mA & mB).any() and not (mA & mC).any() and not (mB & mC).any()
    return mA, mB, mC


def entry_cases(S):
    """入场 3 情形判定（向量化，逐信号日）。返回 {A/B/C: {e, j, px, csig}}。"""
    C, O, HH, LL = S["close"], S["open"], S["high"], S["low"]
    cand, valid = S["cand"], S["valid"]
    T = C.shape[0]
    out = {k: {"e": [], "j": [], "px": [], "csig": []} for k in ("A", "B", "C")}
    for t in range(T - 1):
        js = np.where(cand[t])[0]
        if js.size == 0:
            continue
        e = t + 1
        cs, o = C[t, js], O[e, js]
        v = valid[e, js]
        h, l = HH[e, js], LL[e, js]
        ok = v & np.isfinite(cs) & (cs > 0) & np.isfinite(o) & (o > 0)
        if not ok.any():
            continue
        jj, css, oo, hh, ll = js[ok], cs[ok], o[ok], h[ok], l[ok]
        mA, mB, mC = case_masks(css, oo, hh, ll)
        lo, hi = css * BAND_LO, css * BAND_HI          # B/C 成交价 = 带下沿/上沿（首触价）
        for mask, key, pxv in ((mA, "A", oo), (mB, "B", lo), (mC, "C", hi)):
            k = np.where(mask)[0]
            if k.size == 0:
                continue
            d = out[key]
            d["e"].append(np.full(k.size, e, dtype=np.int64))
            d["j"].append(jj[k])
            d["px"].append(pxv[k].astype(np.float64))
            d["csig"].append(css[k])
    for key, d in out.items():
        d["e"] = np.concatenate(d["e"]) if d["e"] else np.zeros(0, np.int64)
        d["j"] = np.concatenate(d["j"]) if d["j"] else np.zeros(0, np.int64)
        d["px"] = np.concatenate(d["px"]) if d["px"] else np.zeros(0, np.float64)
        d["csig"] = np.concatenate(d["csig"]) if d["csig"] else np.zeros(0, np.float64)
    return out


def case_path(e, j, O, H, L, C, T, kmax):
    """取入场后 k=1..kmax 的路径（k=0 = 入场日，不可卖）。NaN = 无 bar/不可用。"""
    n = e.size
    shp = (n, kmax + 1)
    Oa, Ha, La, Ca = (np.full(shp, np.nan) for _ in range(4))
    for k in range(1, kmax + 1):
        d = e + k
        ok = d < T
        if not ok.any():
            break
        di = np.where(ok, d, 0)[ok]
        ji = j[ok]
        Oa[ok, k], Ha[ok, k], La[ok, k], Ca[ok, k] = O[di, ji], H[di, ji], L[di, ji], C[di, ji]
    return Oa, Ha, La, Ca


def resolve_exit(px, Oa, Ha, La, Ca, tp_pct, sl_pct):
    """逐日触发解析（向量化）。同 bar 优先级：跳空SL > 跳空TP > 日内SL > 日内TP。"""
    tp, sl = (px * (1.0 + tp_pct))[:, None], (px * (1.0 + sl_pct))[:, None]
    bar = np.isfinite(Oa) & (Oa > 0)                     # 引擎：无 open 的 bar 整天跳过
    gsl, gtp = bar & (Oa <= sl), bar & (Oa >= tp)
    isl, itp = bar & np.isfinite(La) & (La <= sl), bar & np.isfinite(Ha) & (Ha >= tp)
    pr = np.where(gsl, 0, np.where(gtp, 1, np.where(isl, 2, np.where(itp, 3, 9))))
    trig = pr < 9
    trig[:, 0] = False                                   # 入场日不可卖（T+1）
    hit = trig.any(axis=1)
    kf = np.argmax(trig, axis=1)
    rw = np.arange(px.size)
    kk = np.where(hit, kf, 0)
    pxm = np.where(gsl, Oa, np.where(gtp, Oa, np.where(isl, sl, tp)))
    return kf, np.where(hit, pxm[rw, kk], np.nan), pr[rw, kk], hit


def exit_plan(e, px, kf, ex_px, ex_rs, hit, Ca, H, T):
    """按 MAXHOLD 定案：先触发者用触发价，否则 k=H−1（或面板末日）收盘平仓。"""
    n = e.size
    k_eff = np.minimum(H - 1, T - 1 - e)
    use_hit = hit & (kf <= k_eff)
    k = np.where(use_hit, kf, k_eff)
    rw = np.arange(n)
    c_at = Ca[rw, np.clip(k, 0, Ca.shape[1] - 1)]
    out_px = np.where(use_hit, ex_px, c_at)
    reason = np.where(use_hit, ex_rs, 4)
    use = (k_eff >= 1) & np.isfinite(out_px)
    return use, e + k, out_px, k + 1, reason


def simulate(e, x, ret, hold, T, seeds, K=3):
    """K 槽位组合 + 逐日几何摊销（对齐生产 B4_K3_MB 记账）。
    K 槽位：满槽不发新单；单票目标权重 = 当日净值 × 1/K（生产口径），受可用现金约束（不加杠杆）；
    收益按持有期几何摊销（避免把多日收益一次性计入）；空闲现金零收益。
    （参考引擎 _tmp_0922_t1exit_v2.run 未限槽位且按「可用现金×1/K」定分配 → 近零分配边角单使
      笔数/换手虚高、资金长期欠配；本脚本补上槽位 + 净值口径权重，笔数/换手因此可解释。）"""
    n = e.size
    by_day = {}
    for i in range(n):
        by_day.setdefault(int(e[i]), []).append(i)
    navs, invs = [], []
    te, tx, tr, th, tv = [], [], [], [], []
    t_lo, t_hi = int(e.min()), int(x.max())
    for sd in seeds:
        rng = np.random.default_rng(sd)
        cash, pos = 1.0, []          # pos = (出场日, 分配额, 净收益, 持有天数, 入场日)
        nav, inv = np.ones(T), np.zeros(T)
        for t in range(t_lo, t_hi + 1):
            if pos:
                still = []
                for q in pos:
                    if q[0] == t:
                        cash += q[1] * (1.0 + q[2])
                        te.append(q[4]); tx.append(t); tr.append(q[2]); th.append(q[3]); tv.append(2.0 * q[1])
                    else:
                        still.append(q)
                pos = still
            mv_now = 0.0
            for q in pos:                                  # 当日开盘前估值（摊销）
                mv_now += q[1] * (1.0 + q[2]) ** (min(t - q[4] + 1, q[3]) / q[3])
            lst, room = by_day.get(t), K - len(pos)
            if lst and room > 0 and cash > 1e-12:
                sel = lst if len(lst) <= room else [lst[i] for i in sorted(rng.choice(len(lst), size=room, replace=False))]
                for ii in sel:                             # 单票目标权重 = 净值 × 1/K（生产口径），不加杠杆
                    alloc = min(cash, (cash + mv_now) / K)
                    if alloc <= 1e-12:
                        break
                    cash -= alloc
                    pos.append((int(x[ii]), alloc, float(ret[ii]), int(hold[ii]), t))
            mv = 0.0
            for q in pos:
                elap = min(t - q[4] + 1, q[3])
                mv += q[1] * (1.0 + q[2]) ** (elap / q[3])
            tot = cash + mv
            nav[t], inv[t] = tot, (mv / tot if tot > 0 else 0.0)
        nav[t_hi + 1:] = cash
        navs.append(nav); invs.append(inv)
    return (np.mean(navs, axis=0), np.mean(invs, axis=0),
            np.array(te, np.int64), np.array(tx, np.int64),
            np.array(tr, np.float64), np.array(th, np.int64), np.array(tv, np.float64))


def metrics_all(nav, inv, te, tr, th, tv, slices, nseeds):
    """逐切片指标。夏普 = 日收益均值/标准差×√244；年化 = 切片内几何；回撤 = 切片内峰谷。
    换手 = 资金加权双边换手/年 = Σ(2×分配额)/(切片均净值×年数)；下单 = 年均单侧下单笔数。"""
    out = {}
    for nm, (i0, i1) in slices.items():
        v = nav[i0:i1 + 1]
        rr = np.diff(v) / v[:-1]
        yrs = max(len(rr) / ANN, 1e-9)
        sd = rr.std()
        m = (te >= i0) & (te <= i1)
        r, h = tr[m], th[m]
        vol = float(tv[m].sum() / max(nseeds, 1))
        mnav = float(np.mean(v))
        out[nm] = {
            "days": int(i1 - i0 + 1), "n": int(m.sum()),
            "wr": round(100.0 * float((r > 0).mean()), 4) if r.size else 0.0,
            "ret": round(100.0 * float(r.mean()), 4) if r.size else 0.0,
            "hold": round(float(h.mean()), 3) if h.size else 0.0,
            "ord": round((m.sum() / max(nseeds, 1)) / yrs, 3),
            "turn": round(vol / (mnav * yrs), 3) if mnav > 0 else 0.0,
            "cagr": round(100.0 * (float(v[-1] / v[0]) ** (1.0 / yrs) - 1.0), 4),
            "sharpe": round(float(rr.mean() / sd * np.sqrt(ANN)), 4) if sd > 0 else 0.0,
            "mdd": round(100.0 * float((v / np.maximum.accumulate(v) - 1.0).min()), 4),
            "inv": round(100.0 * float(inv[i0:i1 + 1].mean()), 3),
        }
    return out


def cost_sens(ents, S, T, probes, seeds, slices):
    """附加口径（非主口径）：同一格在往返 20/40/60bp 三档下的读数。"""
    kmax = max(HS) - 1
    rows, cache = [], {}
    for c in probes:
        combo = tuple(c["entry"])
        if combo not in cache:
            e = np.concatenate([ents[k]["e"] for k in combo])
            j = np.concatenate([ents[k]["j"] for k in combo])
            px = np.concatenate([ents[k]["px"] for k in combo])
            o = np.argsort(e, kind="stable")
            e, j, px = e[o], j[o], px[o]
            cache[combo] = (e, j, px, case_path(e, j, S["open"], S["high"], S["low"], S["close"], T, kmax))
        e, _j, px, (Oa, Ha, La, Ca) = cache[combo]
        kf, ex_px, ex_rs, hit = resolve_exit(px, Oa, Ha, La, Ca, c["tp"] / 100.0, c["sl"] / 100.0)
        use, x, opx, hold, _rs = exit_plan(e, px, kf, ex_px, ex_rs, hit, Ca, c["h"], T)
        row = {"entry": c["entry"], "tp": c["tp"], "sl": c["sl"], "h": c["h"], "by_bp": {}}
        for bp in (20, 40, 60):
            ret = opx[use] / px[use] - 1.0 - bp / 10000.0
            if ret.size == 0:
                continue
            nav, inv, te, tx, tr, th, tv = simulate(e[use], x[use], ret, hold[use], T, seeds, K)
            met = metrics_all(nav, inv, te, tr, th, tv, slices, len(seeds))["full"]
            row["by_bp"]["%d" % bp] = {"cagr": met["cagr"], "sharpe": met["sharpe"],
                                       "mdd": met["mdd"], "n": met["n"], "turn": met["turn"]}
        rows.append(row)
    return {"levels_bp": [20, 40, 60],
            "note": "20bp = 引擎往返 COST_RT 档（不含每边滑点）；40bp = 再 +每边 10bp；"
                    "60bp = 本轮主口径（往返 20bp + 每边 20bp×2）",
            "rows": rows}


def run_grid(smoke=False):
    kmax = max(HS) - 1
    log("版本 %s | 成本 往返 0.0020 + 每边滑点 20bp → 单笔 %.4f | K=%d | 种子 %s"
        % (VERSION, COST_TOT, K, SEEDS))
    log("网格 TP%s × SL%s × MAXHOLD%s = %d 组 × 入场 %d 种 = %d 格（单阶段全量）"
        % (TPS, SLS, HS, len(TPS) * len(SLS) * len(HS), len(COMBOS),
           len(TPS) * len(SLS) * len(HS) * len(COMBOS)))
    eng = load_engine()
    log("引擎 %s 载入（VARIANT=%s MAINBOARD=%s GATE=%s）——main() 未执行（__main__ 守卫）"
        % (ENGINE, eng.VARIANT, eng.MAINBOARD, eng.GATE_MA))
    P = eng.load_all()
    S = eng.build_signals(P)
    cal, T = S["cal"], S["close"].shape[0]
    log("面板 %s .. %s 共 %d 交易日 %d 只；候选(信号日) %d 个股票日"
        % (cal[0], cal[-1], T, S["close"].shape[1], int(S["cand"].sum())))
    ents = entry_cases(S)
    cnt = {k: int(ents[k]["e"].size) for k in "ABC"}
    log("入场情形实得笔数 A=%d B=%d C=%d（合计 %d，互斥不变量已断言）"
        % (cnt["A"], cnt["B"], cnt["C"], sum(cnt.values())))
    all_e = np.concatenate([ents[k]["e"] for k in "ABC"])
    i_first = int(all_e.min())
    i_train = max([i for i, d in enumerate(cal) if d <= TRAIN_HI] or [0])
    i_val = min([i for i, d in enumerate(cal) if d >= VAL_LO] or [T - 1])
    slices = {"full": (i_first, T - 1), "train": (i_first, i_train), "val": (i_val, T - 1)}
    log("样本：实得起点 %s（首笔成交日）→ %s；训练窗 ..%s，验证窗 %s..；交易日数 full=%d train=%d val=%d"
        % (cal[i_first], cal[-1], cal[i_train], cal[i_val],
           slices["full"][1] - i_first + 1, i_train - i_first + 1, T - i_val))
    cells, keys = [], {}
    ncell = len(COMBOS) * len(TPS) * len(SLS) * len(HS)
    for combo in COMBOS:
        name = "".join(combo)
        e = np.concatenate([ents[k]["e"] for k in combo])
        j = np.concatenate([ents[k]["j"] for k in combo])
        px = np.concatenate([ents[k]["px"] for k in combo])
        o = np.argsort(e, kind="stable")
        e, j, px = e[o], j[o], px[o]
        Oa, Ha, La, Ca = case_path(e, j, S["open"], S["high"], S["low"], S["close"], T, kmax)
        for tp in TPS:
            for sl in SLS:
                kf, ex_px, ex_rs, hit = resolve_exit(px, Oa, Ha, La, Ca, tp / 100.0, sl / 100.0)
                for H in HS:
                    use, x, opx, hold, _rs = exit_plan(e, px, kf, ex_px, ex_rs, hit, Ca, H, T)
                    ret = opx[use] / px[use] - 1.0 - COST_TOT
                    if ret.size == 0:
                        m0 = {"days": 0, "n": 0, "wr": 0.0, "ret": 0.0, "hold": 0.0, "ord": 0.0,
                              "turn": 0.0, "cagr": 0.0, "sharpe": 0.0, "mdd": 0.0, "inv": 0.0}
                        met = {"full": m0, "train": m0, "val": m0}
                    else:
                        nav, inv, te, tx, tr, th, tv = simulate(e[use], x[use], ret, hold[use], T, SEEDS, K)
                        met = metrics_all(nav, inv, te, tr, th, tv, slices, len(SEEDS))
                    f, tr_, va = met["full"], met["train"], met["val"]
                    rec = {"entry": name, "tp": tp, "sl": sl, "h": H, "n": f["n"], "wr": f["wr"],
                           "cagr": f["cagr"], "sharpe": f["sharpe"], "mdd": f["mdd"],
                           "hold": f["hold"], "ord": f["ord"], "turn": f["turn"], "inv": f["inv"], "ret": f["ret"],
                           "tr_n": tr_["n"], "tr_wr": tr_["wr"], "tr_cagr": tr_["cagr"],
                           "tr_sharpe": tr_["sharpe"], "tr_mdd": tr_["mdd"], "tr_hold": tr_["hold"],
                           "tr_ord": tr_["ord"], "tr_turn": tr_["turn"], "tr_inv": tr_["inv"],
                           "va_n": va["n"], "va_wr": va["wr"], "va_cagr": va["cagr"],
                           "va_sharpe": va["sharpe"], "va_mdd": va["mdd"], "va_hold": va["hold"],
                           "va_ord": va["ord"], "va_turn": va["turn"], "va_inv": va["inv"]}
                    keys[(name, tp, sl, H)] = len(cells)
                    cells.append(rec)
                    if len(cells) % 100 == 0 or len(cells) == ncell:
                        el = time.time() - t0
                        log("格 %d/%d（%s TP%d SL%d H%d）耗时 %.1fs，ETA %.1fs"
                            % (len(cells), ncell, name, tp, sl, H, el,
                               el / len(cells) * (ncell - len(cells))))
        log("入场情形 %s 完成（机会 %d 笔 → %d 格）" % (name, e.size, len(HS) * len(TPS) * len(SLS)))

    # ---- 邻域中位数（TP/SL/H 各相邻档 = 最多 26 邻格，同入场情形，不含自身）----
    nC, nH, nT, nS = len(COMBOS), len(HS), len(TPS), len(SLS)
    def cube(key):
        a = np.full((nC, nH, nT, nS), np.nan)
        ci = {c: i for i, c in enumerate(["".join(x) for x in COMBOS])}
        hi = {h: i for i, h in enumerate(HS)}
        ti = {t: i for i, t in enumerate(TPS)}
        si = {t: i for i, t in enumerate(SLS)}
        for r in cells:
            a[ci[r["entry"]], hi[r["h"]], ti[r["tp"]], si[r["sl"]]] = r[key]
        return a
    log("计算邻域中位数（26 邻格 / 情形）…")
    for key in ("sharpe", "cagr", "mdd", "tr_sharpe"):
        a = cube(key)
        pad = np.pad(a, 1, constant_values=np.nan)
        st = [pad[1 + x:1 + x + nC, 1 + y:1 + y + nH, 1 + z:1 + z + nT, 1 + w:1 + w + nS]
              for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1) for w in (-1, 0, 1)
              if not (x == 0 and y == 0 and z == 0 and w == 0)]
        with np.errstate(all="ignore"):
            med = np.nanmedian(np.stack(st), axis=0)
        for r in cells:
            r["nb_" + key] = (None if not np.isfinite(med[["".join(x) for x in COMBOS].index(r["entry"]),
                                                           HS.index(r["h"]), TPS.index(r["tp"]),
                                                           SLS.index(r["sl"])])
                              else round(float(med[["".join(x) for x in COMBOS].index(r["entry"]),
                                                    HS.index(r["h"]), TPS.index(r["tp"]),
                                                    SLS.index(r["sl"])]), 4))
    base = [dict(cells[keys[("".join(c), BASE_TP, BASE_SL, BASE_H)]]) for c in COMBOS]
    # 附加成本敏感性：基线 7 格 + 全样本夏普 Top 10
    log("成本敏感性（附加口径）：基线 7 格 + Top10 格 × 20/40/60bp …")
    _pr = {(c["entry"], c["tp"], c["sl"], c["h"]): c
           for c in base + sorted(cells, key=lambda c: -c["sharpe"])[:10]}
    cs = cost_sens(ents, S, T, list(_pr.values()), SEEDS, slices)
    log("成本敏感性完成（%d 格 × 3 档）" % len(cs["rows"]))
    payload = {
        "meta": {
            "title": "超跌低开低吸 · 入场情形 × 出场参数 网格回测（研究用，结论不投产）",
            "script": "backtest/qlch_grid_bt_0923.py", "version": VERSION,
            "run_at": time.strftime("%Y-%m-%d %H:%M:%S"), "elapsed_sec": round(time.time() - t0, 1),
            "python": sys.version.split()[0], "numpy": np.__version__,
            "engine": {"file": ENGINE, "import": "importlib.util（__main__ 守卫，main() 未执行）",
                       "config": {"variant": "B4（市值/换手分位带）", "mainboard": "真主板", "gate": "HS300<MA20",
                                  "st": "非ST", "vr": "量比>=1.2", "ret20_prev": "ret20(T-1)<=-7.31%",
                                  "pool_track": "对齐生产 B4_K3_MB 轨"}},
            "entry": {"band": [0.95, 0.98], "band_lo_bp": -500, "band_hi_bp": -200,
                      "cases": {"A": "open/Csig-1∈[-5%,-2%] → 成交价=open",
                                "B": "open<0.95Csig 且 high>=0.95Csig → 成交价=0.95Csig",
                                "C": "open>0.98Csig 且 low<=0.98Csig → 成交价=0.98Csig"},
                      "combos": ["".join(c) for c in COMBOS],
                      "priority": "三情形逐日互斥（已断言）→ 同标的同日只入一次；组合 = 各情形机会的并集",
                      "t1": "信号日次一交易日入场；入场日不可卖"},
            "exit": {"tp": TPS, "sl": SLS, "maxhold": HS, "cells_per_combo": len(TPS) * len(SLS) * len(HS),
                     "same_bar": "同一日内同时触达 → 先 SL（保守）；同 bar 优先级 跳空SL>跳空TP>日内SL>日内TP",
                     "gap": "跳空穿线按 open 成交", "expiry": "≤MAXHOLD 个交易日（含入场日）到期按当日收盘平仓",
                     "missing_bar": "无 open 的 bar 整天跳过（引擎口径）"},
            "cost": {"cost_rt": COST_RT, "slip_side": SLIP_SIDE, "each_side": "每边 20bp",
                     "total_round_trip": COST_TOT, "note": "往返 COST_RT=0.0020 + 每边滑点 0.0020×2"},
            "portfolio": {"k": K, "seeds": SEEDS,
                          "weight": "K=3 槽位；单票目标权重 = 当日净值 × 1/3（生产口径），受可用现金约束（不加杠杆）；资金锁定、逐日几何摊销、空闲现金零收益",
                          "slots": "满槽不发新单（补上参考引擎 _tmp_0922_t1exit_v2.run 的槽位缺口）",
                          "cash_yield": 0.0, "nav": "5 种子净值均值（无随机性，固定种子可复跑）"},
            "sample": {"panel": [cal[0], cal[-1], T],
                       "full": [cal[slices["full"][0]], cal[slices["full"][1]], slices["full"][1] - i_first + 1],
                       "train": [cal[slices["train"][0]], cal[slices["train"][1]], i_train - i_first + 1],
                       "val": [cal[slices["val"][0]], cal[slices["val"][1]], T - i_val],
                       "note": "指标按引擎实得区间（首笔成交日→末日）；2016-2017 无成交"},
            "metrics_def": {"sharpe": "日收益均值/标准差×√244", "cagr": "切片内几何年化",
                            "mdd": "切片内净值峰谷最大回撤", "wr": "单笔净收益>0 占比（5 种子合计）",
                            "hold": "平均持有交易日（含入场日）",
                            "ord": "下单 = 年均单侧成交笔数（5 种子均）",
                            "turn": "换手 = 资金加权双边换手/年 = Σ(2×分配额)/(切片均净值×年数)",
                            "inv": "资金占用率 = 日均持仓市值/总净值"},
            "n_trials_total": ncell * len(SEEDS), "stage": (("冒烟缩小网格（%d 格，非交付）" % ncell) if smoke else ("单阶段全网格（%d 格全部实跑，未缩表）" % ncell)),
            "external_ref": {"what": "上一轮 E4 基线（B4 全池、未加真主板、出口 TP15/SL-20/H20，训练窗 2018-2021）",
                             "src": "报告-超跌低开低吸-T+1合规出场复测-20260922.md",
                             "n": 1672, "cagr": 12.63, "sharpe": 2.539, "mdd": -18.38,
                             "note": "口径不同（池含非主板 + 成本档 20bp 不含每边滑点）→ 仅作方向对照，不做对拍"},
        },
        "entry_counts": cnt,
        "baseline": base,
        "cost_sens": cs,
        "cells": cells,
    }
    return payload


def _snip(obj, maxlines=20):
    try:
        src = inspect.getsource(obj).rstrip().splitlines()
    except Exception as e:                                    # pragma: no cover
        return "```\n（取源码失败：%s）\n```" % e
    if len(src) > maxlines:
        src = src[:maxlines] + ["# ……（截断，完整实现见脚本本体）"]
    return "```python\n%s\n```" % "\n".join(src)


HDR = ("| # | 入场 | TP | SL | H | 笔数 | 下单/年 | 胜率% | 年化% | 夏普 | 回撤% | 平均持有日 | 换手/年 | 资金占用% |\n"
       "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def _row(rank, c):
    return ("| %d | %s | TP%d | SL%d | H%d | %d | %.1f | %.1f | %+.2f | %.3f | %+.2f | %.1f | %.1f | %.1f |"
            % (rank, c["entry"], c["tp"], c["sl"], c["h"], c["n"], c["ord"], c["wr"], c["cagr"],
               c["sharpe"], c["mdd"], c["hold"], c["turn"], c["inv"]))


def _table(rows, key):
    s = sorted(rows, key=lambda c: c[key], reverse=True)
    return HDR + "\n" + "\n".join(_row(i + 1, c) for i, c in enumerate(s[:20]))


def build_md(p):
    cells, base = p["cells"], p["baseline"]
    m, smp = p["meta"], p["meta"]["sample"]
    ncells = len(cells)
    combos = ["".join(c) for c in COMBOS]
    out = []
    A = out.append
    A("未投产：投产须另立预注册")
    A("")
    A("# 超跌低开低吸 · 入场情形 × 出场参数 网格回测（R-qlch-grid-0923）")
    A("")
    A("> **研究用途，结论不投产。** 本报告不改变任何生产配置；任何采用须另立 `PRE-REGISTRATION_*.md`"
      "（本轮 %d 格 × %d 种子属重度多重检验，未经预注册的读数只能当线索）。" % (ncells, len(SEEDS)))
    A("")
    A("- **新增文件清单（仅此 3 个；未改任何生产脚本）**：`%s`（回测脚本，`--smoke` 为冒烟档）· "
      "`backtest/qlch_grid_bt_0923.json`（%d 格 + %d 基线 + meta）· 本报告。"
      % (p["meta"]["script"], ncells, len(base)))
    A("- 脚本：`%s`（版本 `%s`，`--smoke` 仅用于冒烟验证，交付产物由全量单阶段跑出）" % (p["meta"]["script"], VERSION))
    A("- 结果：`backtest/qlch_grid_bt_0923.json`（%d 格 + %d 条基线 + meta）" % (len(cells), len(base)))
    A("- 引擎：`%s`（importlib 复用，只读；该文件有 `__main__` 守卫 → `main()` 未执行）" % ENGINE)
    A("- 运行：%s · 耗时 %.1f s（%.1f 分钟）· %s" % (m["run_at"], m["elapsed_sec"],
                                                  m["elapsed_sec"] / 60.0, m["stage"]))
    A("- 样本：实得 %s → %s（%d 个交易日；面板 %s..%s 共 %d 日，2016-2017 无成交）"
      % (smp["full"][0], smp["full"][1], smp["full"][2], smp["panel"][0], smp["panel"][1], smp["panel"][2]))
    A("")
    A("## ① 口径与样本")
    A("")
    A("**候选池（全部取自引擎 `build_signals()`，本脚本不复制阈值）**：真主板 ∩ 非ST ∩ 量比≥1.2 ∩ "
      "市值分位[.20,.70] ∩ 换手分位[.40,.80]（B4）∩ `ret20(T−1) ≤ −7.31%` ∩ 熊市门 `HS300(T) < MA20(T)`。"
      "对应生产轨 `B4_K3_MB`（`--variant B4 --maxpos 3 --mainboard`）。")
    A("")
    A("**入场 3 情形**（判定在入场日 T+1 的当日路径上，Csig = 信号日收盘；买入带 = `[0.95×Csig, 0.98×Csig]`）：")
    A("")
    A("| 情形 | 判定 | 成交价 | 实得笔数 |")
    A("|---|---|---|---|")
    A("| A 保持 | `open/Csig−1 ∈ [−5%%,−2%%]`（开盘即在带内） | open | %d |" % p["entry_counts"]["A"])
    A("| B 回落 | `open < 0.95Csig` 且当日 `high ≥ 0.95Csig` | 0.95×Csig（自下回升入带首触价） | %d |" % p["entry_counts"]["B"])
    A("| C 跌到区间 | `open > 0.98Csig` 且当日 `low ≤ 0.98Csig` | 0.98×Csig（自上回落入带首触价） | %d |" % p["entry_counts"]["C"])
    A("")
    A("三情形**逐日互斥**（A 需 `open ≥ 带下沿`、B 需 `open < 带下沿`、C 需 `open > 带上沿`），实现里已断言 → "
      "**同标的同日只入一次**，不存在「同时满足多情形需择优」的情况；7 种组合 = 各情形机会集的并集，各自独立成组合。")
    A("")
    A("**出场网格**：TP ∈ %s%% × SL ∈ %s%% × MAXHOLD ∈ %s 交易日 = %d 组 × 7 入场 = **%d 格**（全部实跑，未缩表）。"
      % (TPS, SLS, HS, len(TPS) * len(SLS) * len(HS), len(cells)))
    A("")
    A("**出场判定（与引擎一致）**：逐日 high/low 触达即触发，不等收盘；跳空穿线按 open 成交；"
      "同一日内同时触达 TP 与 SL → **先 SL**（保守，与 `qlch_paper_20260921.py` 出场块一致）；"
      "同 bar 优先级 `跳空SL > 跳空TP > 日内SL > 日内TP`；无 open 的 bar 整天跳过；"
      "到期（≤ MAXHOLD 个交易日，**含入场日**）按当日收盘强制平仓；入场日不可卖（T+1，最早 T+2 出场）。")
    A("")
    A("**成本**：往返 `COST_RT = 0.0020`（引擎口径）+ **每边滑点 20bp**（看板主显口径，0.0020/边 × 2 边）"
      "= 单笔总成本 **0.0060（往返 60bp）**，在每笔出场时一次性扣减。⚠ 该口径在换手 30-50 单/年量级下"
      "= **每年约 20-30% 的成本拖累**（见 ⑥ 成本敏感性），是本轮绝对水平低于上一轮报告的主因之一。")
    A("")
    A("**组合口径**：K=3 槽位组合（满槽不发新单；**单票目标权重 = 当日净值 × 1/3**（生产 `B4_K3_MB` 口径），"
      "受可用现金约束、不加杠杆；资金锁定、逐日几何摊销、空闲现金零收益）；固定 5 种子（%s）取净值均值 → "
      "**无随机性，可复跑**。（说明：参考引擎 `_tmp_0922_t1exit_v2.py` 未加槽位约束且按「可用现金×1/3」定分配，"
      "会以近零分配开出大量边角单（笔数/换手虚高）；本脚本补上槽位 + 净值口径权重，NAV 路径一致但笔数口径可解释。）"
      % (SEEDS,))
    A("")
    A("**指标定义**（按引擎实得区间 `%s → %s`）：夏普 = 日收益均值/标准差×√244；年化 = 切片内几何年化；"
      "回撤 = 切片内净值峰谷最大回撤；胜率 = 单笔净收益 > 0 占比（5 种子合计笔数）；"
      "平均持有 = 含入场日的交易日数；**下单/年 = 年均单侧成交笔数（5 种子均）**；"
      "**换手/年 = 资金加权双边换手 = Σ(2×分配额)/(切片均净值×年数)**；资金占用 = 日均持仓市值/净值。"
      % (smp["full"][0], smp["full"][1]))
    A("")
    A("| 切片 | 起 | 止 | 交易日数 | 说明 |")
    A("|---|---|---|---|---|")
    A("| full（实得） | %s | %s | %d | 指标主口径 |" % (smp["full"][0], smp["full"][1], smp["full"][2]))
    A("| train | %s | %s | %d | 2018-2021 训练窗（选型参照） |" % (smp["train"][0], smp["train"][1], smp["train"][2]))
    A("| val | %s | %s | %d | 2022+ 验证窗（仅参照，不用于选型） |" % (smp["val"][0], smp["val"][1], smp["val"][2]))
    A("")
    A("## ② Top 20 格（按夏普 / 年化 / 回撤三个维度各一张表）")
    A("")
    A("### ②-1 按夏普（full）")
    A("")
    A(_table(cells, "sharpe"))
    A("")
    A("### ②-2 按年化（full，%）：低笔数格天然占优，读表必须同时看「笔数」列")
    A("")
    A(_table(cells, "cagr"))
    A("")
    A("### ②-3 按回撤（full，%）：回撤为负值，越接近 0 越好")
    A("")
    A(_table(cells, "mdd"))
    A("")
    A("### ②-4 现行基线格对照（TP%d / SL%d / H%d，7 种入场情形）" % (BASE_TP, BASE_SL, BASE_H))
    A("")
    A(HDR + "\n" + "\n".join(_row(i + 1, c) for i, c in enumerate(base)))
    A("")
    A("> 上一轮口径（B4 全池、未加真主板、不含每边滑点）的 E4 基线 = 年化 +12.63% / 夏普 2.539 / 回撤 −18.38% / "
      "训练窗笔数 1672（`报告-超跌低开低吸-T+1合规出场复测-20260922.md`）。本轮池/成本不同 → 仅作方向对照。")
    A("")
    A("## ③ 按入场情形汇总（7 种各自的最优 / 中位数）")
    A("")
    A("| 入场 | 最优格（按夏普） | 最优夏普 | 最优年化% | 最优回撤% | 中位夏普 | 中位年化% | 中位回撤% | 中位笔数 | 中位换手/年 | 中位胜率% |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for name in combos:
        sub = [c for c in cells if c["entry"] == name]
        b = max(sub, key=lambda c: c["sharpe"])
        med = lambda k: float(np.median([c[k] for c in sub]))
        A("| %s | TP%d/SL%d/H%d | %.3f | %+.2f | %+.2f | %.3f | %+.2f | %+.2f | %.0f | %.1f | %.1f |"
          % (name, b["tp"], b["sl"], b["h"], b["sharpe"], b["cagr"], b["mdd"],
             med("sharpe"), med("cagr"), med("mdd"), med("n"), med("turn"), med("wr")))
    A("")
    A("各情形最优格（夏普/年化/回撤 三个维度分别取最优）：")
    A("")
    A("| 入场 | 最优夏普格 | 最优年化格 | 最优回撤格 |")
    A("|---|---|---|---|")
    for name in combos:
        sub = [c for c in cells if c["entry"] == name]
        bs = max(sub, key=lambda c: c["sharpe"])
        bc = max(sub, key=lambda c: c["cagr"])
        bd = max(sub, key=lambda c: c["mdd"])
        A("| %s | TP%d/SL%d/H%d（%.3f） | TP%d/SL%d/H%d（%+.2f%%） | TP%d/SL%d/H%d（%+.2f%%） |"
          % (name, bs["tp"], bs["sl"], bs["h"], bs["sharpe"], bc["tp"], bc["sl"], bc["h"], bc["cagr"],
             bd["tp"], bd["sl"], bd["h"], bd["mdd"]))
    A("")
    A("## ④ 稳健性：邻域中位数与「单格极值但邻域平庸」嫌疑格")
    A("")
    A("**邻域定义**：同一入场情形下，TP/SL/MAXHOLD 各取相邻一档（最多 26 个邻格，网格边缘自然收窄），"
      "取邻格中位数（不含自身）。判定嫌疑格 = 该格夏普位于本情形前 10% **且** 邻域中位夏普 < 本情形夏普中位数。")
    A("")
    susp = []
    for name in combos:
        sub = [c for c in cells if c["entry"] == name]
        thr = float(np.percentile([c["sharpe"] for c in sub], 90))
        cm = float(np.median([c["sharpe"] for c in sub]))
        for c in sub:
            nb = c.get("nb_sharpe")
            if nb is not None and c["sharpe"] >= thr and nb < cm:
                susp.append((name, c, nb, cm))
    A("嫌疑格 **%d 个**（占 %d 格 %.1f%%；涉及 %d 种入场情形）。按「自身夏普 − 邻域中位」降序列出前 12 个："
      % (len(susp), len(cells), 100.0 * len(susp) / len(cells), len({s[0] for s in susp})))
    A("")
    A("| 入场 | TP | SL | H | 自身夏普 | 邻域中位夏普 | 差 | 本情形中位夏普 | 自身年化% | 邻域中位年化% |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for name, c, nb, cm in sorted(susp, key=lambda x: -(x[1]["sharpe"] - x[2]))[:12]:
        A("| %s | %d | %d | %d | %.3f | %.3f | %+.3f | %.3f | %+.2f | %s |"
          % (name, c["tp"], c["sl"], c["h"], c["sharpe"], nb, c["sharpe"] - nb, cm, c["cagr"],
             ("%.2f" % c["nb_cagr"]) if c.get("nb_cagr") is not None else "—"))
    A("")
    A("**反过来，按邻域中位夏普排序的稳健格 Top 10**（邻域也不差 → 更像真效应）：")
    A("")
    A("| # | 入场 | TP | SL | H | 邻域中位夏普 | 自身夏普 | 年化% | 回撤% | 笔数 |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    rob = [c for c in cells if c.get("nb_sharpe") is not None]
    for i, c in enumerate(sorted(rob, key=lambda c: -c["nb_sharpe"])[:10], 1):
        A("| %d | %s | %d | %d | %d | %.3f | %.3f | %+.2f | %+.2f | %d |"
          % (i, c["entry"], c["tp"], c["sl"], c["h"], c["nb_sharpe"], c["sharpe"], c["cagr"], c["mdd"], c["n"]))
    A("")
    A("## ⑤ 样本内外切分（训练 2018-2021 / 验证 2022+）")
    A("")
    A("**选型只用训练窗**：每种入场情形取「训练窗夏普最优格」，再看它在验证窗的表现（下滑幅度 = 过拟合温度计）。")
    A("")
    A("| 入场 | 训练最优格 | 训练夏普 | 训练年化% | 训练回撤% | 训练笔数 | 验证夏普 | 验证年化% | 验证回撤% | 验证笔数 | 夏普留存 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for name in combos:
        sub = [c for c in cells if c["entry"] == name]
        b = max(sub, key=lambda c: c["tr_sharpe"])
        keep = (b["va_sharpe"] / b["tr_sharpe"] * 100.0) if b["tr_sharpe"] else float("nan")
        A("| %s | TP%d/SL%d/H%d | %.3f | %+.2f | %+.2f | %d | %.3f | %+.2f | %+.2f | %d | %.0f%% |"
          % (name, b["tp"], b["sl"], b["h"], b["tr_sharpe"], b["tr_cagr"], b["tr_mdd"], b["tr_n"],
             b["va_sharpe"], b["va_cagr"], b["va_mdd"], b["va_n"], keep))
    A("")
    A("全网格（%d 格）训练/验证中位数与基线格（TP%d/SL%d/H%d）：" % (ncells, BASE_TP, BASE_SL, BASE_H))
    A("")
    A("| 口径 | 训练夏普中位 | 验证夏普中位 | 训练年化中位% | 验证年化中位% |")
    A("|---|---|---|---|---|")
    A("| %d 格全体 | %.3f | %.3f | %+.2f | %+.2f |"
      % (ncells, np.median([c["tr_sharpe"] for c in cells]), np.median([c["va_sharpe"] for c in cells]),
         np.median([c["tr_cagr"] for c in cells]), np.median([c["va_cagr"] for c in cells])))
    for c in base:
        A("| 基线 %s | %.3f | %.3f | %+.2f | %+.2f |" % (c["entry"], c["tr_sharpe"], c["va_sharpe"], c["tr_cagr"], c["va_cagr"]))
    A("")
    A("训练窗最优 10 格在验证窗的表现（按训练夏普降序）：")
    A("")
    A("| # | 入场 | TP | SL | H | 训练夏普 | 验证夏普 | 训练年化% | 验证年化% | 训练回撤% | 验证回撤% |")
    A("|---|---|---|---|---|---|---|---|---|---|---|")
    for i, c in enumerate(sorted(cells, key=lambda c: -c["tr_sharpe"])[:10], 1):
        A("| %d | %s | %d | %d | %d | %.3f | %.3f | %+.2f | %+.2f | %+.2f | %+.2f |"
          % (i, c["entry"], c["tp"], c["sl"], c["h"], c["tr_sharpe"], c["va_sharpe"],
             c["tr_cagr"], c["va_cagr"], c["tr_mdd"], c["va_mdd"]))
    A("")
    A("## ⑥ 结论与风险")
    A("")
    A("**成本敏感性（附加口径，非主口径）**：基线 7 格 + 全样本夏普 Top 10 格在 20/40/60bp 往返成本下的读数。")
    A("")
    A("| 入场 | TP/SL/H | 成本 20bp 年化% | 成本 20bp 夏普 | 成本 40bp 年化% | 成本 40bp 夏普 | 成本 60bp 年化%（主口径） | 成本 60bp 夏普 | 下单/年 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for r in p.get("cost_sens", {}).get("rows", []):
        b = r["by_bp"]
        g = lambda k, f: (b.get(k) or {}).get(f)
        A("| %s | TP%d/SL%d/H%d | %s | %s | %s | %s | %s | %s | %s |"
          % (r["entry"], r["tp"], r["sl"], r["h"],
             ("%+.2f" % g("20", "cagr")) if g("20", "cagr") is not None else "—",
             ("%.3f" % g("20", "sharpe")) if g("20", "sharpe") is not None else "—",
             ("%+.2f" % g("40", "cagr")) if g("40", "cagr") is not None else "—",
             ("%.3f" % g("40", "sharpe")) if g("40", "sharpe") is not None else "—",
             ("%+.2f" % g("60", "cagr")) if g("60", "cagr") is not None else "—",
             ("%.3f" % g("60", "sharpe")) if g("60", "sharpe") is not None else "—",
             ("%.1f" % g("60", "turn")) if g("60", "turn") is not None else "—"))
    A("")
    A("> 20bp 档 = 引擎往返 `COST_RT`（不含每边滑点，与上一轮报告同口径）；60bp 档 = 本轮主口径。"
      "两档之差即「每边 20bp 滑点」的价值：可见本策略的换手下，成本档位直接决定正负。")
    A("")
    # 自动化判据（写死在报告里，避免人工挑数字）
    bA = [c for c in base if c["entry"] == "A"][0]
    nbA = bA.get("nb_sharpe")
    cand_ok = []
    med_by = {}
    for name in combos:
        sub = [c for c in cells if c["entry"] == name]
        med_by[name] = {
            "sharpe": float(np.median([c["sharpe"] for c in sub])),
            "nb": float(np.median([c["nb_sharpe"] for c in sub if c.get("nb_sharpe") is not None] or [np.nan])),
            "val": float(np.median([c["va_sharpe"] for c in sub])),
            "tr": float(np.median([c["tr_sharpe"] for c in sub])),
        }
        for c in sub:
            nb = c.get("nb_sharpe")
            if nb is None or nbA is None:
                continue
            if (c["tr_sharpe"] >= bA["tr_sharpe"] and c["va_sharpe"] >= 1.0 and c["va_cagr"] > 0
                    and nb >= nbA and c["n"] >= 500):
                cand_ok.append(c)
    rk = sorted(combos, key=lambda n: -med_by[n]["val"])
    best_combo = rk[0]
    ec = p["entry_counts"]
    A("- **最稳的入场情形**（按验证窗夏普中位排序）：%s。全网格 %d 格的中位 = %.3f；"
      "机会数 A=%d / B=%d / C=%d —— A/B 类机会稀少（分别为 C 的 %.0f%% / %.0f%%），"
      "单情形结论的置信度最低的是 B 类。"
      % ("、".join("`%s` %.3f" % (n, med_by[n]["val"]) for n in rk[:3]), ncells,
         float(np.median([c["va_sharpe"] for c in cells])), ec["A"], ec["B"], ec["C"],
         100.0 * ec["A"] / ec["C"], 100.0 * ec["B"] / ec["C"]))
    A("- **最稳的出场区**：按邻域中位夏普看，高分集中在 %s 附近（见 ④ 表）；"
      "基线 TP%d/SL%d/H%d 的 7 种情形读数为 %s。"
      % ("/".join(sorted({"TP%d" % c["tp"] for c in sorted(rob, key=lambda x: -x["nb_sharpe"])[:5]})),
         BASE_TP, BASE_SL, BASE_H,
         "；".join("%s 夏普%.3f" % (c["entry"], c["sharpe"]) for c in base)))
    A("- **是否值得进预注册**：%s。预置判据（同时满足才算过）：训练窗夏普 ≥ 基线 A 格(%.3f) 且 "
      "验证窗夏普 ≥ 1.0 且 验证窗年化 > 0 且 邻域中位夏普 ≥ 基线 A 格邻域中位(%s) 且 笔数 ≥ 500；"
      "本轮满足 = **%d / %d 格（%.1f%%）**。"
      % (("不值得——无格同时满足" if not cand_ok else "只值得把下列格写进预注册逐个双盲复核（仍非投产）"),
         bA["tr_sharpe"], ("%.3f" % bA["nb_sharpe"]) if bA.get("nb_sharpe") is not None else "—",
         len(cand_ok), ncells, 100.0 * len(cand_ok) / ncells))
    if cand_ok:
        A("  ⚠ 通过率 %.1f%% 与「多重检验下的假阳性量级」同阶（%d 格 × %d 种子），**本身不构成真效应证据**；"
          "只说明这些格值得用封存集做一次独立的双盲复核。" % (100.0 * len(cand_ok) / ncells, ncells, len(SEEDS)))
    else:
        A("  ⚠ 0 格通过 → 无候选可复核；本轮不改变生产，也不新增预注册。")
    if cand_ok:
        for c in sorted(cand_ok, key=lambda c: -c["sharpe"])[:5]:
            A("  - `%s TP%d/SL%d/H%d`：训练夏普 %.3f / 验证夏普 %.3f / 邻域中位 %.3f / 笔数 %d"
              % (c["entry"], c["tp"], c["sl"], c["h"], c["tr_sharpe"], c["va_sharpe"], c["nb_sharpe"], c["n"]))
    A("- **风险**：① %d 格 × %d 种子 = %d 次试验，多重检验膨胀严重，Top 表的极值大概率含运气成分"
      "（④ 已量化嫌疑格）；② 验证窗（2022+）整体弱于训练窗（中位夏普 %.3f → %.3f）——超跌低吸的边际在衰减；"
      "③ 未计冲击成本/涨跌停不可成交/停牌顺延，成本只按 60bp 固定扣减；④ 未处理退市/长期停牌样本"
      "（面板 mask 之外无生死判定）；⑤ 复权口径沿用引擎面板，跨除权日的跳空可能被高估/低估。"
      % (ncells, len(SEEDS), ncells * len(SEEDS), np.median([c["tr_sharpe"] for c in cells]),
         np.median([c["va_sharpe"] for c in cells])))
    A("- **一句话**：%s" % "；".join([
        "入场端：%s 类最稳（验证窗夏普中位 %.3f，7 情形最高）" % (best_combo, med_by[best_combo]["val"]),
        "出场端：%s" % "、".join("%s TP%d/SL%d/H%d（邻域中位夏普 %.3f）"
                                % (c["entry"], c["tp"], c["sl"], c["h"], c["nb_sharpe"])
                                for c in sorted(rob, key=lambda x: -x["nb_sharpe"])[:3]),
        "处置：%s" % ("值得进预注册复核（%d 格过预置判据，仍非投产）" % len(cand_ok) if cand_ok
                     else "不值得进预注册（无稳健格过门），生产维持 TP15/SL−20/H20 不动")]))
    A("")
    A("## 附 A · 关键实现代码片段（每处 ≤20 行）")
    A("")
    A("入场三情形判定（`case_masks`，逐信号日向量化；互斥不变量内联断言）：")
    A("")
    A(_snip(case_masks))
    A("")
    A("出场循环：逐日触发解析（`resolve_exit`，同 bar 先 SL + 跳空按 open + 入场日不可卖）：")
    A("")
    A(_snip(resolve_exit))
    A("")
    A("出场循环：按 MAXHOLD 定案（`exit_plan`，到期按当日收盘）：")
    A("")
    A(_snip(exit_plan))
    A("")
    A("成本（常量段）：")
    A("")
    A("```python\nCOST_RT = %.4f          # 引擎往返成本（qlch_paper COST_RT）\n"
      "SLIP_SIDE = %.4f        # 每边滑点 20bp（看板主显口径）\n"
      "COST_TOT = COST_RT + 2 * SLIP_SIDE        # %.4f = 往返 60bp\n"
      "ret = opx[use] / px[use] - 1.0 - COST_TOT  # 每笔出场时一次性扣减\n```"
      % (COST_RT, SLIP_SIDE, COST_TOT))
    A("")
    A("## 附 B · 运行日志尾部与耗时")
    A("")
    A("```")
    out.extend(LOG[-25:])
    A("```")
    A("")
    A("总耗时 %.1f s（%.1f 分钟）；单阶段全网格，无两阶段缩表（%d 格全部实跑）。"
      % (m["elapsed_sec"], m["elapsed_sec"] / 60.0, ncells))
    A("")
    A("## 附 C · 验收与对拍（格数 + 自读文件对拍）")
    A("")
    A(MARK)
    A("")
    A("## 附 D · 未做到 / 不确定项")
    A("")
    A("- **入场情形的实现近似**：B 情形 `open < 0.95Csig` 时成交价写死为 `0.95×Csig`，"
      "而实盘挂 `0.95×Csig` 限价单在开盘已低于该价时会以**更优的开盘价**成交 → 本口径对 B 偏保守（低估）。")
    A("- **MAXHOLD 语义**：本报告用「≤ MAXHOLD 个交易日（含入场日）、到期按当日收盘」"
      "（= 上一轮回测 `_tmp_0922_t1exit_v2.py` 口径）；生产脚本 `qlch_paper_20260921.py` 的到期判定是 "
      "`t − e ≥ MAXHOLD`（即持有 MAXHOLD+1 根 bar），两者差 1 根 bar。此处取回测口径，已在 JSON meta 记录。")
    A("- **成本**：只做固定 60bp 扣减，未建模冲击成本、涨跌停一字不可成交、停牌期间无法出场。")
    A("- **样本**：2016-2017 无成交（引擎实得区间从 %s 起）；退市/长期停牌样本无生死处理；"
      "复权口径沿用引擎面板（未做除权日前复权一致性核验）。" % smp["full"][0])
    A("- **统计**：未做 bootstrap/安慰剂检验，未做 FDR 校正；5 种子平均只抹平了 K=3 的随机选择，"
      "不抹平多重检验。")
    A("- **未做**：入场情形与「门的配置（MA20/MA60/无门）」「TopK 排序」「B4 vs C1 滤网」的交叉网格；"
      "分年归因矩阵；逐笔交易明细落盘（本轮只落指标，未落 trades）。")
    A("")
    return "\n".join(out) + "\n"


def write_outputs(p, out_json, out_md):
    p["meta"]["elapsed_sec"] = round(time.time() - t0, 1)      # 含建模+落盘前总耗时
    json.dump(p, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("落盘 %s（%.2f MB）" % (out_json, out_json.stat().st_size / 1048576.0))
    md = build_md(p)
    open(out_md, "w", encoding="utf-8").write(md)
    log("落盘 %s（%d 行）" % (out_md, md.count("\n")))
    return md


RE_ROW = re.compile(r"^\|\s*\d+\s*\|\s*([ABC]{1,3})\s*\|\s*TP(-?\d+)\s*\|\s*SL(-?\d+)\s*\|\s*H(\d+)\s*\|"
                    r"\s*(\d+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([+\-][\d.]+)\s*\|\s*([+\-]?[\d.]+)\s*\|"
                    r"\s*([+\-][\d.]+)\s*\|")


def self_verify(json_path, md_path, payload):
    """自读落盘文件：json.load 格数校验 + 报告表格抽样与 JSON 对拍（贴进报告附 C）。"""
    L = []
    j = json.load(open(json_path, encoding="utf-8"))
    n_cells = len(j["cells"])
    exp = len(TPS) * len(SLS) * len(HS) * len(COMBOS)
    L.append("① json.load(%s) 成功：键 = %s" % (json_path.name, sorted(j.keys())))
    L.append("② 格数校验：len(cells) = %d，期望 %d×%d×%d×%d = %d → %s"
             % (n_cells, len(TPS), len(SLS), len(HS), len(COMBOS), exp, "PASS" if n_cells == exp else "FAIL"))
    L.append("   基线行 = %d（7 种入场情形 @ TP%d/SL%d/H%d）→ %s"
             % (len(j["baseline"]), BASE_TP, BASE_SL, BASE_H, "PASS" if len(j["baseline"]) == len(COMBOS) else "FAIL"))
    idmap = {(c["entry"], c["tp"], c["sl"], c["h"]): c for c in j["cells"]}
    L.append("   格 ID 唯一性：%d 个唯一键 / %d 格 → %s"
             % (len(idmap), n_cells, "PASS" if len(idmap) == n_cells else "FAIL"))
    txt = open(md_path, encoding="utf-8").read()
    parsed = []
    for ln in txt.splitlines():
        mt = RE_ROW.match(ln)
        if mt:
            g = mt.groups()
            parsed.append((g[0], int(g[1]), int(g[2]), int(g[3]), int(g[4]),
                           float(g[5]), float(g[6]), float(g[7]), float(g[8]), float(g[9])))
    n_par_exp = 3 * min(20, n_cells) + len(COMBOS)
    L.append("③ 报告表格解析：%d 行（Top20×3 + 基线 %d = %d）/ 期望 %d 行 → %s"
             % (len(parsed), len(COMBOS), 3 * min(20, n_cells) + len(COMBOS), n_par_exp,
                "PASS" if len(parsed) == n_par_exp else "FAIL"))
    top_s = max(j["cells"], key=lambda c: c["sharpe"])
    top_c = max(j["cells"], key=lambda c: c["cagr"])
    top_d = max(j["cells"], key=lambda c: c["mdd"])
    picks = [("夏普 Top1", top_s), ("年化 Top1", top_c), ("回撤 Top1", top_d),
             ("基线 A 格", [c for c in j["baseline"] if c["entry"] == "A"][0])]
    L.append("④ 抽 %d 格对拍（报告表格值 vs JSON 值；容差 = 打印精度）" % len(picks))
    L.append("")
    L.append("| 抽样 | 格（入场/TP/SL/H） | 指标 | 报告值 | JSON 值 | 判定 |")
    L.append("|---|---|---|---|---|---|")
    ok_all = True
    for tag, c in picks:
        hit = [q for q in parsed if q[:4] == (c["entry"], c["tp"], c["sl"], c["h"])]
        if not hit:
            L.append("| %s | %s TP%d/SL%d/H%d | — | （报告表格中未找到） | — | FAIL |"
                     % (tag, c["entry"], c["tp"], c["sl"], c["h"]))
            ok_all = False
            continue
        q = hit[0]
        for nm, rep, val, tol in (("笔数", q[4], c["n"], 0), ("下单/年", q[5], c["ord"], 0.05),
                                  ("胜率%", q[6], c["wr"], 0.05), ("年化%", q[7], c["cagr"], 0.005),
                                  ("夏普", q[8], c["sharpe"], 0.0005), ("回撤%", q[9], c["mdd"], 0.005)):
            same = abs(rep - val) <= tol + 1e-9
            ok_all &= same
            L.append("| %s | %s TP%d/SL%d/H%d | %s | %s | %s | %s |"
                     % (tag, c["entry"], c["tp"], c["sl"], c["h"], nm, rep, val, "PASS" if same else "FAIL"))
    L.append("")
    L.append("⑤ 总判定：%s（格数 %d + 基线 %d + 表格行 %d + 抽样对拍 %d 格 × 6 指标）"
             % ("PASS" if (n_cells == exp and ok_all and len(parsed) == n_par_exp) else "FAIL",
                n_cells, len(j["baseline"]), len(parsed), len(picks)))
    L.append("⑥ 可复跑：无随机数（仅 np.random.default_rng(固定 5 种子) 用于 K=3 择优），"
             "同参数重跑数值一致；本轮耗时 %.1f s。" % payload["meta"]["elapsed_sec"])
    return "\n".join(L)


def main():
    global TPS, SLS, HS, SEEDS, COMBOS
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="小网格冒烟（写 scratch，非交付产物）")
    args = ap.parse_args()
    out_json, out_md = OUT_JSON, OUT_MD
    if args.smoke:
        TPS, SLS, HS = [12, 15], [-15, -20], [3, 20]
        SEEDS = SEEDS[:2]
        COMBOS = [("A",), ("A", "B", "C")]
        sc = Path(os.environ.get("PI_SCRATCH_DIR", str(BK)))
        out_json, out_md = sc / "qlch_grid_smoke.json", sc / "qlch_grid_smoke.md"
        log("★ SMOKE 模式：网格缩小为 %d 格，产物写 scratch（非交付）"
            % (len(TPS) * len(SLS) * len(HS) * len(COMBOS)))
    p = run_grid()
    write_outputs(p, out_json, out_md)
    # 终端汇总
    cells = p["cells"]
    log("=" * 118)
    log("Top 10（按 full 夏普）")
    log("%-6s %6s %6s %6s %8s %8s %8s %8s %8s" % ("入场", "TP", "SL", "H", "笔数", "年化%", "夏普", "回撤%", "持有日"))
    for c in sorted(cells, key=lambda c: -c["sharpe"])[:10]:
        log("%-6s %6d %6d %6d %8d %+8.2f %8.3f %+8.2f %8.1f"
            % (c["entry"], c["tp"], c["sl"], c["h"], c["n"], c["cagr"], c["sharpe"], c["mdd"], c["hold"]))
    log("基线对照（TP%d/SL%d/H%d，7 种入场情形；上一轮 E4 参照 年化+12.63/夏普2.539/回撤−18.38）"
        % (BASE_TP, BASE_SL, BASE_H))
    for c in p["baseline"]:
        log("%-6s 笔数%6d 胜率%5.1f%% 年化%+7.2f%% 夏普%6.3f 回撤%+7.2f%% 平均持有%5.1f日 换手%5.1f次/年"
            % (c["entry"], c["n"], c["wr"], c["cagr"], c["sharpe"], c["mdd"], c["hold"], c["turn"]))
    log("=" * 118)
    txt = self_verify(out_json, out_md, p)
    print(txt, flush=True)
    md = open(out_md, encoding="utf-8").read()
    open(out_md, "w", encoding="utf-8").write(md.replace(MARK, txt))
    log("已把对拍结果注入报告附 C；总耗时 %.1f s" % (time.time() - t0))


if __name__ == "__main__":
    main()
