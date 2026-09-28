# -*- coding: utf-8 -*-
"""m4_portfolio_20260928.py — forum8「对称毛口径过门」3 条选股公式的**组合级可化复核（M4）**

背景（不重复证明，只补缺环）：
  · M2/v3 已做**事件级**读数（①档口径：最后一布尔输出、T+1 开盘入场、T+2 收盘出场、往返 20bp）。
    这 3 条（543 探底放量突破 / 774 最强黄金坑 / 807 均线粘合起爆）在 v3 里都只过 **gross_buy（无成本）** 门，
    net（含成本）与 all 门均未过 ⇒ 事件级边际 < 成本。
  · 本脚本补上**组合化**这一环：把同样的信号矩阵喂给项目主仓冻结的组合记账，看扣成本后
    「年化 / 回撤 / 夏普 / 胜率 / 成交笔数 / 资金占用 / 换手 / 容量」这 8 个读数是否可投产。

口径冻结来源（**只导入，不修改**）：
  · 信号矩阵引擎 = m2_sweep_20260928.py（extract_blocks / clean_code / normalize /
    evaluate_formula / bool_probe / make_eval）——与 v3 的差异仅在 N4 显示层归一化；
    已断言：对这 3 帖 m2.normalize == v3.normalize（code_sha1 与 v3 证据逐位一致）。
  · 同尺子锚定 = m2_sweep_v3_20260928.py 的 event_study（三口径 all/net/gross_buy），
    逐字段复现 evidence_forum8_sweep_v3_20260928.json 的 3 行；不一致则**立即停止**。
  · 组合记账 = hengpan_fangliang_dikai_0925/x2_sens.py 的 sim_portfolio()，照抄，资金时序
    order="entry_first"（同一交易日内 09:25 先入场、15:00 后出场）；单边成本 COST_SIDE=0.000346。
    规则：每日按**信号排序**取前 K 只（本脚本 K = KSLOT）；单票分配 = min(前一日净值 / KSLOT, 可用现金)；
    最多同时持有 KSLOT 只；同一标的持仓期内不重复买入；逐日收盘盯市；出场 T+2 收盘（缺失顺延≤5 日，
    取不到记最坏 −100%，实现为在原定 T+2 收盘日以 exit_px=0 结算；顺延窗口越出面板末端的**样本截断**笔
    单独剔除并计数 —— 与事件级引擎丢弃 n_drop_no_exit 同源）。

排序口径（这 3 条公式没有复合分）：
  (a) 随机：固定种子 20260928，20 次独立抽样取**中位数**（另报 p10/p90 说明离散度）；
  (b) 确定性代理：**ADV20（20 日均成交额）降序**。理由：容量口径本身就是 ADV20×1%×KSLOT，
      按 ADV 降序可避免把收益归因于「排到无法成交的极小票」；且 ADV 是信号日即可得的单一公开量，
      不引入未来信息。反向的 ADV 升序会把项目主仓已验证的「低成交额」因子偷渡进排序，
      不再是中性代理；振幅类排序同理会隐含一个波动率因子。

用法: python m4_portfolio_20260928.py [--reps 20] [--out FILE] [--topics 543,774,807]
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import pathlib
import sys
import time

import numpy as np

R = pathlib.Path(__file__).resolve().parents[2]
OUT = R / "backtest/forum8_formulas_0928"
SCRATCH = pathlib.Path(os.environ.get("PI_SCRATCH_DIR") or ".")
PANEL = SCRATCH / "x1cache" / "panel_oos.npz"
REGISTRY = SCRATCH / "gushi_raw" / "registry.json"
BODIES = SCRATCH / "gushi_raw" / "topics"
M2 = OUT / "m2_sweep_20260928.py"
V3 = OUT / "m2_sweep_v3_20260928.py"
X2 = R / "backtest/hengpan_fangliang_dikai_0925/x2_sens.py"
EV_ANCHOR = OUT / "evidence_forum8_sweep_v3_20260928.json"

IDS = ("543", "774", "807")
COST_SIDE = 0.000346
ANN = 244.0
KSLOT_GRID = (4, 10, 20)
RAND_REPS = 20
RAND_SEED = 20260928
ADV_WIN = 20
ADV_CAP = 0.01
PROXY_NAME = "adv20_desc"


def log(*a):
    print(*a, flush=True)


def sha256_file(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ 信号矩阵（引擎照抄）
def build_code(m2, md):
    blocks = [m2.clean_code(b) for b in m2.extract_blocks(md)]
    blocks = [b for b in blocks if len(b) >= 10]
    if not blocks:
        return None, 0, ""
    code = m2.normalize(max(blocks, key=len))
    return code, len(blocks), hashlib.sha1(code.encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------------------ 同尺子锚定（逐字段复现）
def diff_obj(mine, theirs, path=""):
    out = []
    for k in sorted(theirs):
        if k not in mine:
            out.append("%s.%s: 复现缺失（证据=%r）" % (path, k, theirs[k]))
        else:
            out += diff_val(mine[k], theirs[k], "%s.%s" % (path, k))
    for k in sorted(mine):
        if k not in theirs:
            out.append("%s.%s: 证据无此字段（复现=%r）" % (path, k, mine[k]))
    return out


def diff_val(a, b, path):
    if isinstance(b, dict):
        return diff_obj(a if isinstance(a, dict) else {}, b, path)
    if isinstance(a, bool) or isinstance(b, bool):
        return [] if a == b else ["%s: 复现=%r 证据=%r" % (path, a, b)]
    if isinstance(b, float) or isinstance(a, float):
        if a is None or b is None:
            return [] if a == b else ["%s: 复现=%r 证据=%r" % (path, a, b)]
        return [] if float(a) == float(b) else ["%s: 复现=%.12g 证据=%.12g" % (path, float(a), float(b))]
    return [] if a == b else ["%s: 复现=%r 证据=%r" % (path, a, b)]


# ------------------------------------------------------------------ 候选逐笔（含最坏 −100%）
def build_trades(sig, panel, cal, syms, mult, cost_side):
    O, C, A = panel["O"], panel["C"], panel["A"]
    Tn, N = C.shape
    pc = np.full((Tn, N), np.nan, dtype=np.float32)
    pc[1:] = C[:-1]
    with np.errstate(all="ignore"):
        ZT = np.round(pc * mult[None, :], 2)
    t_idx, j_idx = np.where(sig)
    n_sig = int(t_idx.size)
    blank = dict(n_signal=n_sig, n_rej_limit_up=0, n_drop_no_exit=0, n_drop_truncation=0,
                 n_tradeable=0, n_wiped=0, recs=[])
    if n_sig == 0:
        return blank
    e = t_idx + 1
    inw = e < Tn
    e_c = np.clip(e, 0, Tn - 1)
    zt_hit = inw & np.isfinite(O[e_c, j_idx]) & (O[e_c, j_idx] >= ZT[e_c, j_idx] - 1e-4)
    n_rej = int(zt_hit.sum())
    c_bad = ~(np.isfinite(C[t_idx, j_idx]) & (C[t_idx, j_idx] > 0))
    o_bad = ~(np.isfinite(O[e_c, j_idx]) & (O[e_c, j_idx] > 0))
    n_not_inw = int((~inw).sum())
    n_c_bad = int((c_bad & inw).sum())
    n_o_bad = int((o_bad & inw).sum())
    ok = inw & (~c_bad) & (~o_bad) & (~zt_hit)
    t_idx, j_idx, e = t_idx[ok], j_idx[ok], e[ok]
    if t_idx.size == 0:
        return dict(blank, n_rej_limit_up=n_rej)
    x = e + 1
    ext = np.zeros(x.shape, bool)
    for k in range(0, 6):
        d = e + 1 + k
        need = (~ext) & (d <= Tn - 1)
        d_c = np.clip(d, 0, Tn - 1)
        good = need & np.isfinite(C[d_c, j_idx]) & (C[d_c, j_idx] > 0)
        x = np.where(good, d, x)
        ext |= good
    n_drop = int((~ext).sum())
    # 样本截断剔除：只有**完整落在面板内**的顺延窗口（e+1..e+5 全部 <= Tn-1）才允许判「取不到 → 最坏 −100%」。
    # 出场日越界是样本末端截断、不是缺价；按 −100% 记会把账户在末日一次性清零（实测 774/KSLOT=4 被打到 −100%），
    # 事件级引擎对这批也是直接丢弃（计入 n_drop_no_exit）——两口径在这一点上同源。
    full_win = (e + 6) <= (Tn - 1)
    n_trunc = int((~full_win).sum())
    if not full_win.all():
        t_idx, j_idx, e, x, ext = (t_idx[full_win], j_idx[full_win], e[full_win],
                                   x[full_win], ext[full_win])
    entry = O[e, j_idx].astype(np.float64)
    x_ex = np.clip(x, 0, Tn - 1)
    # 顺延窗口内取不到收盘 → 记最坏 −100%：仍在**原定 T+2 收盘日**结算，成交价 = 0
    # （不在面板末日结算——那会把 2 日的损失变成「占着一个仓位好几年再全损」，人为摧毁容量）
    exitp = np.where(ext, C[x_ex, j_idx].astype(np.float64), 0.0)
    good = np.isfinite(entry) & (entry > 0)
    t_idx, j_idx, e, x, entry, exitp, ext = (t_idx[good], j_idx[good], e[good], x[good],
                                             entry[good], exitp[good], ext[good])
    ret = (exitp * (1.0 - cost_side) / (entry * (1.0 + cost_side)) - 1.0) * 100.0
    xc = np.minimum(x, Tn - 1)          # 仅用于取日历：x==Tn 者即窗口内无有效出场（已按最坏计）
    recs = []
    for i in range(t_idx.size):
        j = int(j_idx[i])
        recs.append(dict(sym=syms[j], j=j, t=int(t_idx[i]), e_t=int(e[i]),
                         signal_date=cal[int(t_idx[i])], entry_date=cal[int(e[i])],
                         entry_open=float(entry[i]), exit_date=cal[int(xc[i])],
                         exit_px=float(exitp[i]), wiped=bool(not ext[i]),
                         ret_pct=float(ret[i])))
    return dict(n_signal=n_sig, n_rej_limit_up=n_rej, n_not_inw=n_not_inw,
                n_signal_day_invalid=n_c_bad, n_entry_open_invalid=n_o_bad,
                n_drop_no_exit=n_drop, n_drop_truncation=n_trunc, n_tradeable=len(recs),
                n_wiped=int((~ext).sum()), recs=recs)


def adv20_grid(A):
    """20 日均成交额（含当日，窗口内只数 A>0 的有效日）→ (T,N)"""
    Tn, N = A.shape
    M = np.isfinite(A) & (A > 0)
    csA = np.cumsum(np.where(M, A.astype(np.float64), 0.0), axis=0)
    csM = np.cumsum(M.astype(np.float64), axis=0)
    zA = np.zeros((1, N))
    pA = np.concatenate([zA, csA], axis=0)
    pM = np.concatenate([zA, csM], axis=0)
    hi = np.arange(Tn) + 1
    lo = np.maximum(np.arange(Tn) - ADV_WIN + 1, 0)
    sA = pA[hi] - pA[lo]
    sM = pM[hi] - pM[lo]
    with np.errstate(all="ignore"):
        out = np.where(sM > 0, sA / np.where(sM > 0, sM, 1.0), np.nan)
    return out


# ------------------------------------------------------------------ 排序
def order_recs(recs, key):
    """entry 日升序；同一 entry 日内按 key **降序**（与 x2_sens 的 recs 顺序约定一致）"""
    e = np.fromiter((r["e_t"] for r in recs), float, count=len(recs))
    o = np.lexsort((-np.asarray(key, float), e))
    return [recs[i] for i in o]


# ------------------------------------------------------------------ 组合记账（照抄 x2_sens.sim_portfolio）
def sim_portfolio(recs, cal, syms, F, K, KSLOT, cost_side, start=None, order="entry_first"):
    T = len(cal)
    jof = {s: j for j, s in enumerate(syms)}
    C = F["C"]
    by_entry = {}
    for r in recs:
        by_entry.setdefault(r["entry_date"], []).append(r)
    nav = np.full(T, np.nan)
    depl = np.full(T, np.nan)
    cash, pos, n_in = 1.0, [], 0
    executed = []

    def do_entry(t, d):                              # 入场（09:25，只能用开盘前已有现金）
        nonlocal cash, n_in
        if not (start is None or d >= start):
            return
        for r in by_entry.get(d, [])[:K]:
            if len(pos) >= KSLOT:
                break
            if any(q["sym"] == r["sym"] for q in pos):
                continue
            navprev = nav[t - 1] if (t > 0 and np.isfinite(nav[t - 1])) else 1.0
            alloc = min(navprev / KSLOT, cash)
            if alloc <= 1e-12:
                break
            px = r["entry_open"]
            if not (np.isfinite(px) and px > 0):
                continue
            cash -= alloc
            pos.append(dict(sym=r["sym"], shares=alloc / (px * (1.0 + cost_side)),
                            entry_px=px, exit_date=r["exit_date"], exit_px=r["exit_px"]))
            n_in += 1
            executed.append(r)

    def do_exit(d):                                  # 出场（15:00 收盘价结算）
        nonlocal cash
        for p in list(pos):
            if p["exit_date"] == d:
                cash += p["shares"] * p["exit_px"] * (1.0 - cost_side)
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
            c = C[t, j] if j is not None else np.nan
            if not (np.isfinite(c) and c > 0):
                c = p["entry_px"]
            mv += p["shares"] * c
        nav[t] = cash + mv
        depl[t] = (mv / nav[t]) if nav[t] > 0 else np.nan
    idx_all = [i for i in range(T) if start is None or cal[i] >= start]
    if not idx_all:
        return None
    i0 = idx_all[0]
    nav[i0] = 1.0
    v = nav[idx_all]
    if v.size < 30 or not np.all(np.isfinite(v)):
        return None
    nd = len(v) - 1
    ann = (v[-1] / v[0]) ** (ANN / nd) - 1
    pk = np.maximum.accumulate(v)
    mdd = float((v / pk - 1).min())
    dr = v[1:] / v[:-1] - 1
    sd = dr.std(ddof=1)
    r_in = [r for r in recs if (start is None or r["entry_date"] >= start)]
    rets = np.array([r["ret_pct"] for r in r_in], float)
    years = nd / ANN
    caps = np.array([r["adv"] * ADV_CAP for r in executed if np.isfinite(r["adv"])], float)
    dd = depl[idx_all]
    exe = [r for r in executed if (start is None or r["entry_date"] >= start)]
    return dict(
        ann=round(ann * 100, 2), mdd=round(mdd * 100, 2),
        sharpe=None if sd == 0 else round(float(dr.mean() / sd * math.sqrt(ANN)), 2),
        win_rate=round(float(100 * (rets > 0).mean()), 2) if rets.size else None,
        mean_per_trade=round(float(rets.mean()), 4) if rets.size else None,
        med_per_trade=round(float(np.median(rets)), 4) if rets.size else None,
        n_candidates=int(rets.size), n_entries=int(len(exe)),
        deploy_pct=round(float(np.nanmean(dd)) * 100, 2),
        deploy_p95_pct=round(float(np.nanpercentile(dd, 95)) * 100, 2),
        turnover_per_year=round(float(len(exe)) / years, 1) if years > 0 else None,
        cap_single_p10=None if caps.size == 0 else round(float(np.percentile(caps, 10)), 0),
        cap_single_med=None if caps.size == 0 else round(float(np.median(caps)), 0),
        cap_single_mean=None if caps.size == 0 else round(float(caps.mean()), 0),
        cap_acct_p10=None if caps.size == 0 else round(float(np.percentile(caps, 10)) * KSLOT, 0),
        cap_acct_med=None if caps.size == 0 else round(float(np.median(caps)) * KSLOT, 0),
        n_wipeout=int(sum(1 for r in exe if r["wiped"])),
        years=round(years, 3), window=[cal[i0], cal[idx_all[-1]]])


def med_of(rows, key):
    vals = [r[key] for r in rows if r is not None and r.get(key) is not None]
    return round(float(np.median(vals)), 4) if vals else None


def agg_random(sims):
    """20 次随机排序 → 逐指标取中位；另报年化 p10/p90"""
    sims = [s for s in sims if s]
    if not sims:
        return None
    out = {}
    for k in ("ann", "mdd", "sharpe", "win_rate", "n_entries", "deploy_pct",
              "turnover_per_year", "mean_per_trade", "med_per_trade", "n_candidates", "n_wipeout",
              "cap_single_p10", "cap_single_med", "cap_acct_p10", "cap_acct_med"):
        v = med_of(sims, k)
        out[k] = None if v is None else (int(round(v)) if k in ("n_entries", "n_candidates", "n_wipeout") else round(v, 4))
    anns = [s["ann"] for s in sims]
    out["ann_p10"] = round(float(np.percentile(anns, 10)), 2)
    out["ann_p90"] = round(float(np.percentile(anns, 90)), 2)
    out["reps"] = len(sims)
    return out


# ------------------------------------------------------------------ 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=RAND_REPS)
    ap.add_argument("--placebo", type=int, default=5)
    ap.add_argument("--topics", default=",".join(IDS))
    ap.add_argument("--out", default=str(OUT / "evidence_forum8_portfolio_m4_20260928.json"))
    a = ap.parse_args()
    t0 = time.time()
    ids = [x.strip() for x in a.topics.split(",") if x.strip()]

    m2 = load_mod("m2_frozen", M2)
    v3 = load_mod("v3_frozen", V3)
    v3._init(str(PANEL))
    panel = v3._PANEL
    z = np.load(str(PANEL), allow_pickle=True)
    cal = [str(c) for c in z["cal"]]
    syms = [str(s) for s in z["syms"]]
    F = dict(panel)
    mult = np.array([m2.mult_of(s) for s in syms])
    adv = adv20_grid(panel["A"])
    reg = {str(e["id"]): e for e in json.loads(REGISTRY.read_text(encoding="utf-8"))}
    anchor_ev = json.loads(EV_ANCHOR.read_text(encoding="utf-8"))
    anchor_rows = {r["id"]: r for r in anchor_ev["rows"]}
    log("[panel] T=%d N=%d %s..%s" % (panel["C"].shape[0], panel["C"].shape[1], cal[0], cal[-1]))

    payload = dict(
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        task="forum8 对称毛口径过门 3 条公式的组合级可化复核（M4）",
        engine=dict(m2=str(M2), m2_sha256=sha256_file(M2), v3=str(V3), v3_sha256=sha256_file(V3),
                    x2_sim_source=str(X2), x2_sha256=sha256_file(X2),
                    anchor_evidence=str(EV_ANCHOR), anchor_sha256=sha256_file(EV_ANCHOR)),
        panel=dict(path=str(PANEL), T=int(panel["C"].shape[0]), N=int(panel["C"].shape[1]),
                   cal0=cal[0], cal1=cal[-1],
                   universe_note="面板全池（含创业板/科创板/退市，未做主板限定）——与 v3 事件级同池，保证同尺子"),
        capacity=dict(adv_win=ADV_WIN, adv_cap=ADV_CAP,
                      note=("单票上限 = 信号日 20 日均成交额 × 1%（ADV20 只数窗口内 A>0 的有效日，含当日）；"
                            "账户上限 = 单票上限 × KSLOT；p10/中位按**实际成交笔**的标的分布统计，"
                            "单位为元（面板 A = 成交额）")),
        cost=dict(cost_side=COST_SIDE, round_trip_pct=round(2 * COST_SIDE * 100, 4), ann_factor=ANN,
                  cost_source="x2_sens.py BASE_P['COST_SIDE']"),
        sim_rule=("x2_sens.sim_portfolio 照抄：每日按信号排序取前 K（此处 K=KSLOT）；"
                  "单票分配=min(前一日净值/KSLOT, 可用现金)；最多并发 KSLOT；同一标的持仓期内不重复买入；"
                  "逐日收盘盯市；出场 T+2 收盘（缺失顺延≤5 日，取不到记最坏 −100%）；"
                  "资金时序 order='entry_first'（09:25 先入场→15:00 后出场）；无成本臂 cost_side=0"),
        ordering=dict(
            a_random=dict(mode="random", seed=RAND_SEED, reps=a.reps, stat="20 次取中位数（另报年化 p10/p90）"),
            b_proxy=dict(mode=PROXY_NAME, name="20 日均成交额（ADV20）降序",
                         why=("容量口径本身就是 ADV20×1%×KSLOT，按 ADV 降序可避免把收益归因于「排到无法成交的极小票」；"
                              "ADV 是信号日即可得的单一公开确定量，不引入未来信息。反向的 ADV 升序会把项目主仓已验证的"
                              "「低成交额」因子偷渡进排序，振幅类排序同理隐含波动率因子，均不再是中性代理。"))),
        anchor=dict(), portfolio_rows=[], conclusion=dict())

    # ---- 1) 同尺子锚定：逐字段复现 v3 证据 ----
    keep = {}
    for tid in ids:
        md = (BODIES / ("t%s.md" % tid)).read_text(encoding="utf-8")
        code, nb, sha = build_code(m2, md)
        code_v3, nb_v3, sha_v3 = build_code(v3, md)
        meta = reg[tid]
        rec = dict(id=tid, title=meta.get("title", ""), group=meta.get("group", ""),
                   reply_cnt=meta.get("reply_cnt"), url="https://gushi.in/topic/%s" % tid)
        rec["n_blocks"] = nb
        rec["code_len"] = len(code)
        rec["code_sha1"] = sha
        r = m2.evaluate_formula(code, panel)
        if r["kind"] != "①":
            raise SystemExit("[STOP] %s 不是 ①档：%s %s" % (tid, r["kind"], r.get("reason")))
        ev = v3.event_study(r["sig"], panel)
        rec.update(tier="①", verdict=("过门→进M3" if ev.get("gate") else "否证（未过门）"),
                   signal_name=r.get("signal_name"), n_outputs=r.get("n_outputs"),
                   bool_outputs=r.get("bool_outputs"), eval_err_cols=r.get("eval_err_cols"), event=ev)
        diffs = diff_obj(rec, anchor_rows[tid])
        payload["anchor"][tid] = dict(
            match=(len(diffs) == 0), n_diffs=len(diffs), diffs=diffs[:40],
            normalize_identical_m2_vs_v3=bool(code == code_v3),
            code_sha1_m2=sha, code_sha1_v3=sha_v3,
            code_sha1_evidence=anchor_rows[tid].get("code_sha1"),
            exc_gross_buy_pct=ev.get("exc_gross_buy_pct"),
            exc_at_project_cost_pct=(None if ev.get("exc_gross_buy_pct") is None else
                                     round(ev["exc_gross_buy_pct"] - 2 * COST_SIDE * 100, 4)),
            day_at_project_cost_pct=(None if ev.get("day_gross_buy_pct") is None else
                                     round(ev["day_gross_buy_pct"] - 2 * COST_SIDE * 100, 4)),
            cost_note=("v3 尺子 = 往返 20bp；项目主仓冻结 COST_SIDE=0.000346 ⇒ 往返 6.92bp。"
                       "exc/day_at_project_cost = v3 的 gross_buy 读数 − 6.92pp（成本对逐笔超额是常数平移）"),
            reproduced=rec, evidence_row=anchor_rows[tid])
        log("[anchor] %s %s  match=%s diffs=%d" % (tid, meta.get("title", ""), len(diffs) == 0, len(diffs)))
        for d in diffs[:10]:
            log("    ! %s" % d)
        if diffs:
            pathlib.Path(a.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            raise SystemExit("[STOP] 同尺子锚定不一致 → 已写出 %s，后续组合级不再执行" % a.out)
        keep[tid] = dict(code=code, sig=r["sig"], ev=ev, title=meta.get("title", ""))

    # ---- 2) 组合级：候选逐笔 ----
    for tid in ids:
        k = keep[tid]
        tr = build_trades(k["sig"], panel, cal, syms, mult, COST_SIDE)
        recs = tr["recs"]
        av = adv[[r["t"] for r in recs], [r["j"] for r in recs]] if recs else np.array([])
        for i, r in enumerate(recs):
            r["adv"] = float(av[i])
        k["recs"] = recs
        k["trades_stat"] = {kk: tr[kk] for kk in
                            ("n_signal", "n_rej_limit_up", "n_not_inw", "n_signal_day_invalid",
                             "n_entry_open_invalid", "n_drop_no_exit", "n_drop_truncation",
                             "n_tradeable", "n_wiped")}
        k["trades_stat"]["anchor_n_buy_leg"] = k["ev"]["bench_buy"]["n"]
        k["trades_stat"]["n_gap_vs_anchor"] = tr["n_tradeable"] - int(k["ev"]["bench_buy"]["n"])
        # 集合级交叉校验：v3 事件级 n（buy 腿）== 我的 after_ok − 无有效出场集
        k["trades_stat"]["identity_event_buy_n"] = (
            tr["n_signal"] - tr["n_not_inw"] - tr["n_rej_limit_up"] - tr["n_entry_open_invalid"]
            - tr["n_drop_no_exit"])
        k["trades_stat"]["identity_ok"] = bool(
            k["trades_stat"]["identity_event_buy_n"] == int(k["ev"]["bench_buy"]["n"]))
        k["trades_stat"]["note"] = ("n_signal = 信号矩阵真值数；n_rej_limit_up = T+1 开盘涨停剔除；"
                                    "n_drop_no_exit = 顺延≤5 日仍无有效收盘（事件级直接丢弃集）；"
                                    "n_drop_truncation = 顺延窗口越出面板末端的样本截断（同样剔除）；"
                                    "n_wiped = 面板内确证缺价 → 记最坏 −100% 并在原定 T+2 收盘日结算。"
                   "identity_event_buy_n = n_signal−n_not_inw−n_rej_limit_up−n_entry_open_invalid"
                   "−n_drop_no_exit，必须逐位等于 v3 事件的 bench_buy.n（⇒ 我的候选集与冻结事件引擎"
                   "的入样集完全相同，benchmark NaN 剔除数为 0）")
        log("[trades] %s n_sig=%d rej_zt=%d no_exit=%d trunc=%d tradeable=%d wiped=%d (v3 buy n=%d)"
            % (tid, tr["n_signal"], tr["n_rej_limit_up"], tr["n_drop_no_exit"], tr["n_drop_truncation"],
               tr["n_tradeable"], tr["n_wiped"], k["ev"]["bench_buy"]["n"]))
        proxy_key = np.array([r["adv"] for r in recs], float)

        for KSLOT in KSLOT_GRID:
            for arm, cs in (("net", COST_SIDE), ("zero_cost", 0.0)):
                recs_p = order_recs(recs, proxy_key)
                mp = sim_portfolio(recs_p, cal, syms, F, KSLOT, KSLOT, cs)
                rng_sims = []
                for rep in range(a.reps):
                    rng = np.random.default_rng(RAND_SEED + rep)
                    key = rng.random(len(recs))
                    recs_r = order_recs(recs, key)
                    rng_sims.append(sim_portfolio(recs_r, cal, syms, F, KSLOT, KSLOT, cs))
                mr = agg_random(rng_sims)
                row = dict(topic=tid, title=k["title"], KSLOT=KSLOT, arm=arm, cost_side=cs,
                           proxy=(dict(mp) if mp else None), random_median=mr)
                if arm == "net":
                    k.setdefault("rows_net", {})[KSLOT] = row
                else:
                    k.setdefault("rows_zero", {})[KSLOT] = row
                log("  [%s KSLOT=%d %s] proxy ann=%s mdd=%s sh=%s wr=%s n=%s dep=%s to=%s | rand med ann=%s p10=%s p90=%s"
                    % (tid, KSLOT, arm,
                       (mp or {}).get("ann"), (mp or {}).get("mdd"), (mp or {}).get("sharpe"),
                       (mp or {}).get("win_rate"), (mp or {}).get("n_entries"), (mp or {}).get("deploy_pct"),
                       (mp or {}).get("turnover_per_year"),
                       (mr or {}).get("ann"), (mr or {}).get("ann_p10"), (mr or {}).get("ann_p90")))

        # ---- 组合级器械检验：同轮廓随机选股（同记账 / 同成本 / 同排序口径）----
        # 绝对年化里含大盘 beta，必须用「同规则的随机选股组合」做基准，否则无法判断增量。
        cnt = np.bincount(np.where(k["sig"])[0], minlength=len(cal))
        days = [(int(d), int(cnt[d])) for d in np.nonzero(cnt)[0]]
        Cv = panel["C"]
        vix = [np.nonzero(np.isfinite(Cv[d]) & (Cv[d] > 0))[0] for d in range(Cv.shape[0])]
        k["placebo"] = {}
        for KSLOT in KSLOT_GRID:
            sims_p = []
            for si in range(a.placebo):
                rng = np.random.default_rng(RAND_SEED + 7 * si)
                sigp = np.zeros(k["sig"].shape, bool)
                for d, c in days:
                    pool = vix[d]
                    m = int(min(c, pool.size))
                    if m <= 0:
                        continue
                    sigp[d, rng.choice(pool, size=m, replace=False)] = True
                trp = build_trades(sigp, panel, cal, syms, mult, COST_SIDE)
                rp = trp["recs"]
                if not rp:
                    continue
                avp = adv[[r["t"] for r in rp], [r["j"] for r in rp]]
                for i2, r in enumerate(rp):
                    r["adv"] = float(avp[i2])
                rp = order_recs(rp, [r["adv"] for r in rp])
                sims_p.append(sim_portfolio(rp, cal, syms, F, KSLOT, KSLOT, COST_SIDE))
            k["placebo"][KSLOT] = agg_random(sims_p)
            pm = k["placebo"][KSLOT] or {}
            log("  [placebo %s KSLOT=%d] seeds=%d ann=%s (p10 %s / p90 %s) mdd=%s dep=%s n_ent=%s "
                "mean/trade=%s n_wipeout=%s"
                % (tid, KSLOT, len(sims_p), pm.get("ann"), pm.get("ann_p10"), pm.get("ann_p90"),
                   pm.get("mdd"), pm.get("deploy_pct"), pm.get("n_entries"),
                   pm.get("mean_per_trade"), pm.get("n_wipeout")))

        for KSLOT in KSLOT_GRID:
            n = k["rows_net"][KSLOT]
            zrow = k["rows_zero"][KSLOT]
            pm = k["placebo"].get(KSLOT) or {}
            incr = None
            if n["proxy"] is not None and pm.get("ann") is not None:
                incr = round(n["proxy"]["ann"] - pm["ann"], 2)
            incr_r = None
            if n["random_median"] is not None and pm.get("ann") is not None:
                incr_r = round(n["random_median"]["ann"] - pm["ann"], 2)
            payload["portfolio_rows"].append(dict(
                topic=tid, title=k["title"], KSLOT=KSLOT, K=KSLOT,
                trades=k["trades_stat"],
                placebo_median=pm,
                combo_increment_vs_placebo_ann_pp=dict(proxy=incr, random=incr_r),
                net=dict(proxy=n["proxy"], random=n["random_median"]),
                zero_cost=dict(proxy=zrow["proxy"], random=zrow["random_median"]),
                cost_drag_ann_pp=dict(
                    proxy=(None if not (n["proxy"] and zrow["proxy"]) else
                           round(zrow["proxy"]["ann"] - n["proxy"]["ann"], 2)),
                    random=(None if not (n["random_median"] and zrow["random_median"]) else
                            round(zrow["random_median"]["ann"] - n["random_median"]["ann"], 2)))))

    # ---- 3) 结论（判据：净口径年化 > 0 且容量下占用可行）----
    crit = []
    for row in payload["portfolio_rows"]:
        for mode in ("proxy", "random"):
            m = (row["net"] or {}).get(mode)
            if not m:
                continue
            caps_ok = None
            if m.get("cap_acct_med"):
                caps_ok = bool(m["cap_acct_med"] >= 1e6)
            crit.append(dict(topic=row["topic"], KSLOT=row["KSLOT"], mode=mode,
                             net_ann=m.get("ann"), net_ann_positive=bool((m.get("ann") or 0) > 0),
                             deploy_pct=m.get("deploy_pct"), mdd=m.get("mdd"), sharpe=m.get("sharpe"),
                             n_entries=m.get("n_entries"),
                             cap_acct_med=m.get("cap_acct_med"), cap_acct_ge_1e6=caps_ok))
    anns = [c["net_ann"] for c in crit if c["net_ann"] is not None]
    incrs = [r["combo_increment_vs_placebo_ann_pp"]["proxy"] for r in payload["portfolio_rows"]
             if r.get("combo_increment_vs_placebo_ann_pp", {}).get("proxy") is not None]
    incrs_r = [r["combo_increment_vs_placebo_ann_pp"]["random"] for r in payload["portfolio_rows"]
               if r.get("combo_increment_vs_placebo_ann_pp", {}).get("random") is not None]
    payload["conclusion"] = dict(
        criterion="净口径年化 > 0 且 容量上限（ADV20×1%×KSLOT 中位）下的资金占用可行",
        placebo_increment=dict(
            note=("组合级增量 = 该公式组合净年化 − 同记账/同成本/同排序口径下的"
                  "「同轮廓随机选股」组合净年化（中位）；这是判断绝对年化里有多少是选股 alpha 的关键读数"),
            proxy_median_pp=None if not incrs else round(float(np.median(incrs)), 2),
            random_median_pp=None if not incrs_r else round(float(np.median(incrs_r)), 2),
            n_positive_proxy=int(sum(1 for x in incrs if x > 0)), n_proxy=len(incrs)),
        per_config=crit,
        n_configs=len(crit),
        n_net_ann_positive=sum(1 for c in crit if c["net_ann_positive"]),
        min_net_ann=None if not anns else round(min(anns), 2),
        max_net_ann=None if not anns else round(max(anns), 2),
        investable=bool(all(c["net_ann_positive"] for c in crit)) if crit else False,
        note=("任意一条 (topic, KSLOT, 排序口径) 净年化 ≤ 0 即判不可投产；"
              "此外需披露：事件级已证边际 < 成本（v3: net/all 门未过，仅 gross_buy 过门）。"))
    payload["anchor"] = {t: dict(v) for t, v in payload["anchor"].items()}
    payload["runtime_sec"] = round(time.time() - t0, 1)
    pathlib.Path(a.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    log("[done] %s  %.0fs" % (a.out, time.time() - t0))
    log("  结论：净年化>0 的配置 %d/%d  investable=%s" %
        (payload["conclusion"]["n_net_ann_positive"], payload["conclusion"]["n_configs"],
         payload["conclusion"]["investable"]))


if __name__ == "__main__":
    main()
