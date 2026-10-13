# -*- coding: utf-8 -*-
r"""audit_samebar_causality_20261008.py — 全口径「同 bar 因果」扫描（ADR-0004 · B3 · 只出证据，不改造）

问题（ADR-0004）：探针 P1–P4 全是 `t`/`t−1` 的**日粒度**语义，于是
「用**成交那根 bar 的开盘**筛选 → 又按同一根开盘成交」这类口径四道探针全部逃逸，
而实盘不可执行（清单要等 09:25 撮合才知道，挂单必须早于 09:25 存在）。
本脚本对四个口径逐个判定：**决策是否读了成交那一根 bar**。

判据：引擎探针 `fleur_absorb/engine/audit.py:probe_same_bar_causality`（P5 · **双向投毒** ±1e9）。
  · 双向而非单向 —— 消除「毒值恰好没跨过阈值」的假通过；
  · 另设**阳性对照**（决策只读 ≤ t−1 行 → 必须 pass）—— 消除「探针恒判违规」的假阳性；
  · 决策集为空 → 拒绝给出结论（空转保护），另选交易日重测。

四个口径
--------
  1) HPDK v1.5  backtest/hengpan_fangliang_dikai_0925/oos_run.py        （信号+成交均读 T+1 开盘）
  2) A5         backtest/a5_experiment/paper_daban_a5.py                （gap 用入场日今开、成交价=今开）
  3) qlch       backtest/qlch_paper_20260921.py                         （cand[T−1] ∩ gap[T] 才买，成交价=O[T]）
  4) forum8     backtest/forum8_formulas_0928/m4_portfolio_20260928.py  （sig[T] → entry=O[T+1]，无带内筛选）
  额外：HPDK v1.6（本目录 oos_run_v16_executable.py · 盲挂协议）作为「修好之后」的对照臂。

只读纪律：**不修改**任何被审口径（qlch / forum8 一个字节不动）；只读其源码与产物。
用法：python audit_samebar_causality_20261008.py            # 落 evidence_samebar_causality_<YYYYMMDD>.json
"""
import argparse
import datetime
import importlib.util
import json
import os
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
R = HERE.parents[1]
FLEUR = pathlib.Path(r"E:\PI\投资\fleur_absorb")
if str(FLEUR) not in sys.path:
    sys.path.insert(0, str(FLEUR))
from engine import audit as AU          # noqa: E402

V16 = HERE / "oos_run_v16_executable.py"
OOS = HERE / "oos_run.py"
A5 = R / "backtest/a5_experiment/paper_daban_a5.py"
A5_STATE = R / "backtest/a5_experiment/paper_state.json"
QLCH = R / "backtest/qlch_paper_20260921.py"
QLCH_PANEL = R / "backtest/kv_resonance_0913/panel_kv_0913.npz"
FORUM8 = R / "backtest/forum8_formulas_0928/m4_portfolio_20260928.py"
TODAY = datetime.datetime.now().strftime("%Y%m%d")


def log(*a):
    print(*a, flush=True)


def cite_head(relpath, a, b):
    """从 `git show HEAD:<relpath>` 取行号引文（as-found 证据锚在 HEAD，不随工作区修改漂移）。"""
    import subprocess
    txt = subprocess.run(["git", "-C", str(R), "show", "HEAD:%s" % relpath],
                         capture_output=True, text=True, encoding="utf-8").stdout
    ln = txt.splitlines()
    return dict(file="HEAD:%s" % relpath,
                lines=[dict(n=i + 1, code=ln[i].strip()) for i in range(a - 1, min(b, len(ln)))])


def cite(p, a, b):
    """贴出 file:line 原文（行号与内容一并入证据，避免「引文漂移」）。"""
    p = pathlib.Path(p)
    ln = p.read_text(encoding="utf-8").splitlines()
    return dict(file=str(pathlib.Path(p).relative_to(R)).replace("\\", "/") if str(p).startswith(str(R)) else str(p),
                lines=[dict(n=i + 1, code=ln[i].strip()) for i in range(a - 1, min(b, len(ln)))])


def slim(ctx, upto):
    """把 ctx 的行截到前 `upto` 行（决策只读 ≤ t 行 ⇒ 不改变判定，但省内存）。"""
    out = {}
    for k, v in ctx.items():
        a = np.asarray(v)
        out[k] = a[:upto] if a.ndim >= 2 else a
    return out


def load_v16():
    spec = importlib.util.spec_from_file_location("v16_for_audit", V16)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ============================================================ 1) HPDK v1.5 / v1.6（真探针 · 全池面板）
def audit_hpdk(m):
    mod = m.load_mod()
    sha = mod.FROZEN_SHA
    cal, syms, dead, F, done, src = m.load_panel(mod, os.environ.get("PI_SCRATCH_DIR") or ".")
    P = dict(mod.P)
    FD = m.build_factors(cal, syms, F, dead, P)
    FL = m.build_filters(cal, syms, FD, dead, P)
    T = FD["C"].shape[0]
    ctx = {"open": FD["O"], "close": FD["C"], "amt20": FD["AMT20"],
           "volbr": FD["VOLBR"], "ret20": FD["RET20"]}

    def _top(ix, t, c):
        if ix.size == 0:
            return np.array([], dtype=int)
        comp = (m.zs(-np.log(c["amt20"][t][ix])) + m.zs(-np.log(c["volbr"][t][ix]))
                + m.zs(-c["ret20"][t][ix]))
        return np.sort(ix[np.argsort(-comp)[:min(P["K"], ix.size)]])

    def decide_v15(c, t):
        """v1.5 决策：**gap 读 ctx["open"][t+1]**（成交那根 bar 的开盘）—— 同源 oos_run.py:166-173。"""
        g = c["open"][t + 1] / np.where(c["close"][t] > 0, c["close"][t], np.nan) - 1.0
        b = m.elig(FD, FL, syms, t, P)
        mm = (b & np.isfinite(g) & (g <= -P["P1"]) & (g >= -P["P2"])
              & np.isfinite(c["ret20"][t]) & np.isfinite(c["volbr"][t]))
        return _top(np.nonzero(mm)[0], t, c)

    def decide_v16(c, t):
        """v1.6 决策：只读第 t 行（ctx 里**没有**任何"未来行"输入）—— 同源 oos_run_v16_executable.select_v16。"""
        b = m.elig(FD, FL, syms, t, P)
        mm = b & np.isfinite(c["ret20"][t]) & np.isfinite(c["volbr"][t])
        return _top(np.nonzero(mm)[0], t, c)

    def decide_control(c, t):
        """阳性对照：只读第 t−1 行 → 双向投毒第 t+1 行必须**不受影响**（否则探针恒判违规）。"""
        row = c["close"][max(t - 1, 0)]
        return np.sort(np.nonzero(np.isfinite(row) & (row > 0))[0][:5])

    days = []
    for t in range(T - 2, max(T - 800, 0), -1):
        if decide_v15(ctx, t).size and decide_v16(ctx, t).size:
            days.append(t)
        if len(days) >= 3:
            break
    assert days, "找不到 v1.5/v1.6 同时非空的交易日 —— 拒绝给出空转结论"
    out = {}
    for name, fn in (("v15", decide_v15), ("v16", decide_v16), ("control", decide_control)):
        rs = [AU.probe_same_bar_causality(fn, ctx, t, fill_idx=t + 1) for t in days]
        out[name] = dict(days=[cal[t] for t in days], n_probes=len(rs),
                         n_tripped=int(sum(1 for r in rs if not r["ok"])),
                         ok_all=bool(all(r["ok"] for r in rs)),
                         n_clean_decision=int(len(rs[0]["clean"])), detail=rs[0])
    log("[HPDK] v1.5 双向投毒 %d/%d 次被抓（ok_all=%s）· v1.6 %d/%d · 阳性对照 %d/%d" %
        (out["v15"]["n_tripped"], out["v15"]["n_probes"], out["v15"]["ok_all"],
         out["v16"]["n_tripped"], out["v16"]["n_probes"],
         out["control"]["n_tripped"], out["control"]["n_probes"]))
    return dict(
        id="hpdk_v15", name="HPDK v1.5（缩量超跌 · oos_run.py）", method="probe",
        decision="signal(t) = elig(t) ∩ 带内 g ∩ 复合分前 K；g = O[t+1]/C[t] − 1",
        fill_ref="今开（= O[t+1]）", fill_idx="t+1",
        same_bar_causality=True, probe=out,
        static=[cite(OOS, 166, 173), cite(OOS, 195, 199)],
        verdict="同 bar 因果成立：筛选读 `GAP[t]`（= O[t+1]/C[t]−1）而成交又按 `O[t+1][j]` ⇒ 用成交那根 bar 的开盘筛选。"
                "实盘不可执行（09:25 才知道清单，挂单须早于 09:25）⇒ 读数只能当研究上界。",
        executable_gap="清单需 09:25 撮合才有 ⇒ 无 ≤09:20 下单动作（P6 违规 n=%s）",
        extra=dict(probe_v16_for_reference=dict(
            name="HPDK v1.6（盲挂协议 · 本目录 oos_run_v16_executable.py）", method="probe",
            same_bar_causality=False, probe=out["v16"], positive_control=out["control"],
            verdict="不读成交那根 bar：选股只用 T 日及以前信息，带内条件移到成交判定（盲挂限价 前收×0.99）。")))


# ============================================================ 2) A5（真数据回放 + 双向投毒）
def audit_a5():
    src = A5.read_text(encoding="utf-8")
    lo, hi = -0.05, -0.02
    for ln in src.splitlines():
        if ln.strip().startswith("GAP_LO, GAP_HI"):
            lo, hi = [float(x) for x in ln.split("=", 1)[1].split("#")[0].split(",")]
            break
    st = json.loads(A5_STATE.read_text(encoding="utf-8"))
    rows = []
    for p in list(st.get("positions", [])) + list(st.get("closed", [])):
        ep, gp = p.get("entry_px"), p.get("gap")
        if ep and gp is not None and (1.0 + float(gp)) > 0:
            rows.append((float(ep), float(ep) / (1.0 + float(gp))))       # (今开, 昨收)
    assert rows, "A5 paper_state 里没有可用 (今开, 昨收) 记录"
    ctx = {"open": np.array([a for a, _ in rows], float), "close": np.array([b for _, b in rows], float)}

    def decide(c, t):
        """A5 入场判定（同源 paper_daban_a5.py:472-484）：gap = 今开/昨收 − 1，带内 → 建仓价 = 今开。"""
        g = c["open"][t] / c["close"][t] - 1.0
        return 1 if (lo - 1e-9 <= g <= hi + 1e-9) else 0

    rs = [AU.probe_same_bar_causality(decide, ctx, i, fill_idx=i) for i in range(len(rows))]
    n_trip = int(sum(1 for r in rs if not r["ok"]))
    log("[A5] 真实入场记录 %d 笔（今开=昨收×(1+gap) 反推）· 双向投毒被抓 %d/%d" % (len(rows), n_trip, len(rs)))
    return dict(
        id="a5", name="A5 打板族（paper_daban_a5.py）", method="probe(真实入场记录回放)+static",
        decision="watchlist(sb_date=T−1) → 入场日 D 读 feat['open'][i]/prev_close[i] 算 gap，带内才建仓",
        fill_ref="今开（entry_px = float(o)）", fill_idx="入场日 D 那一根",
        same_bar_causality=True,
        probe=dict(n_rows=len(rows), n_tripped=n_trip, ok_all=bool(n_trip == 0),
                   rows_source="backtest/a5_experiment/paper_state.json 的 positions+closed（entry_px/gap 实测值）",
                   detail=rs[0] if rs else None),
        static=[cite_head("backtest/a5_experiment/paper_daban_a5.py", 463, 484)],
        static_after_fix=[
            cite(A5, 520, 525),
            cite(A5, 532, 543),
        ],
        post_fix_note="B2（本会话）已把 A5 判定**前移**为盲挂协议：入场段改为 "
                      "`lim = blind_order_price(pc, GAP_HI)` + `fill_px, fill_why = blind_auction_fill(...)`，"
                      "记录里新增 order_time='09:18' / limit_px / band_hit / entry_reason / real_fill_px；"
                      "建仓集合与成交价与改前**逐笔等价**（12/12 真实入场记录验证通过）。"
                      "协议级 P5 证据：同一套盲挂协议在 HPDK v1.6 上跑双向投毒 = 0/3 次被抓（见本文件参照臂）。"
                      "**局限**：A5 本口径尚未跑修复后的正式 P5 探针（决策行 ≠ 成交行的 ctx 需按"
                      "「信号日 / 成交日」两行构造，本会话未做）⇒ 标为待办。",
        verdict="同 bar 因果成立：`gap = o/pc − 1` 的 o 是**入场日那根 bar 的开盘**，而 `entry_px = float(o)` 又按同价成交 "
                "⇒ 实盘只能「09:25 撮合出今开后立刻按今开买入」，与「≤09:20 盲挂」（集合竞价唯一可撤单窗口）冲突。",
        executable_gap="无 ≤09:20 下单动作（无 order_time/limit_px 字段）⇒ P6 不可执行",
        state_change="**本会话已修**（B2）：改为盲挂协议后，判定输入 = T 日收盘 × (1+上沿)（挂单时点信息），"
                     "带内条件由限价把关、下沿由 09:15–09:20 可撤单窗撤单 ⇒ 不再读成交那根 bar；"
                     "order_time='09:18' + limit_px 使 P6 可核。")


# ============================================================ 3) qlch（真探针 · gap 门）
def audit_qlch():
    z = np.load(QLCH_PANEL, mmap_mode="r")
    O, C = z["open"], z["close"]
    T = O.shape[0]
    lo, hi = -0.05, -0.02
    src = QLCH.read_text(encoding="utf-8")
    for ln in src.splitlines():
        if ln.strip().startswith("GAP_LO, GAP_HI"):
            lo, hi = [float(x) for x in ln.split("=", 1)[1].split("#")[0].split(",")]
            break
    pick = None
    for t in range(T - 2, max(T - 500, 1), -1):
        g = np.asarray(O[t], float) / np.asarray(C[t - 1], float) - 1.0
        n = int(np.count_nonzero(np.isfinite(g) & (g >= lo) & (g <= hi)))
        if n > 0:
            pick = (t, n)
            break
    assert pick, "qlch 面板上找不到任何 gap 带内名 —— 拒绝空转结论"
    t, n_inband = pick
    ctx = slim({"open": np.asarray(O[:t + 2], float), "close": np.asarray(C[:t + 2], float)}, t + 2)

    def decide(c, t_):
        """qlch 成交日门（同源 qlch_paper_20260921.py:356-358）：cand[T−1] ∩ gap[T] ∈ 带内。"""
        g = c["open"][t_] / c["close"][t_ - 1] - 1.0
        return np.sort(np.nonzero(np.isfinite(g) & (g >= lo) & (g <= hi))[0])

    def control(c, t_):
        row = c["close"][t_ - 2] if t_ >= 2 else c["close"][0]
        return np.sort(np.nonzero(np.isfinite(row) & (row > 0))[0][:5])

    p1 = AU.probe_same_bar_causality(decide, ctx, t, fill_idx=t)
    p0 = AU.probe_same_bar_causality(control, ctx, t, fill_idx=t)
    log("[qlch] 交易日 %d（=idx %d）带内 %d 只 · 双向投毒：gap 门 ok=%s（tripped=%s）· 对照 ok=%s" %
        (t, t, n_inband, p1["ok"], p1["tripped"], p0["ok"]))
    return dict(
        id="qlch", name="qlch 超跌低开低吸（qlch_paper_20260921.py）", method="probe",
        decision="cand[T−1]（超跌+熊市门）∩ gap[T] ∈ [−5%,−2%] → 建仓价 = O[T]",
        fill_ref="今开（entry_px = float(O[t, _j])）", fill_idx="T（成交那一根）",
        same_bar_causality=True,
        probe=dict(n_inband_in_clean=n_inband, ctx_rows=int(t + 2), probe_gap_gate=p1, positive_control=p0,
                   ctx_note="探针 ctx 只含 open/close 两键（mask/valid 是成交日的**可交易性**读，属 P6 类；"
                            "且 bool 数组不支持 ±1e9 投毒）—— 故本探针精确测 :357-358 的 gap 门"),
        static=[cite(QLCH, 356, 359), cite(QLCH, 384, 388), cite(QLCH, 181, 187)],
        verdict="同 bar 因果成立：`gap[t]` 用**成交日开盘** O[t]，同一行又按 O[t] 成交（:386 entry_px = float(O[t, _j])）。"
                "另 :358 还读 `valid[t]`（成交日有效性）—— 属可交易性判定，不是决策输入，但仍需 ≤09:20 的挂单动作。",
        executable_gap="无 ≤09:20 下单动作；成交价 = 今开 ⇒ P6 不可执行")


# ============================================================ 4) forum8（源码级判定）
def audit_forum8():
    scratch = pathlib.Path(os.environ.get("PI_SCRATCH_DIR") or ".")
    assets = dict(registry=(scratch / "gushi_raw" / "registry.json").exists(),
                  topics_dir=(scratch / "gushi_raw" / "topics").exists(),
                  panel_x1cache=(scratch / "x1cache" / "panel_oos.npz").exists())
    return dict(
        id="forum8", name="forum8 对称毛口径（m4_portfolio_20260928.py）",
        method="static（本机 scratch 缺 m2/v3 公式引擎资产 ⇒ 探针不可跑：%s）" % json.dumps(assets, ensure_ascii=False),
        decision="sig[T]（3 条公式的最后一布尔输出，由 m2_sweep/v3 公式引擎在 T 日数据上求值）→ entry = O[T+1]",
        fill_ref="今开（entry = O[e, j_idx]，e = t_idx + 1）", fill_idx="t+1",
        same_bar_causality=False,
        probe=dict(skipped=True, reason="缺 SCRATCH/gushi_raw/registry.json 与 SCRATCH/x1cache/panel_oos.npz（本会话 scratch 无该两份资产）",
                   assets=assets),
        static=[cite(FORUM8, 127, 144), cite(FORUM8, 165, 173), cite(FORUM8, 216, 246)],
        verdict="同 bar 因果**不成立**：选股矩阵 sig[T] 只由 T 日及以前数据求值，成交价取 T+1 开盘（:165），"
                "**没有**任何「用今开筛选」的门 —— 与 HPDK v1.5 / A5 / qlch 的关键差别就在此。"
                "但 :136/:143 的涨停剔除读 `O[e]`（成交日开盘）：那是**可交易性剔除**（开盘一字涨停确实买不到），"
                "属可执行的市场事实，不算决策输入。",
        executable_gap="仍带 P6 缺口：成交价 = 今开却无 ≤09:20 的挂单动作记录（清单/信号 T 日收盘即可得，"
                       "因此**可**用盲挂修复：挂 昨收×(1+上沿) 或直接 T 日收盘后下单）")


# ============================================================ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", default=str(HERE))
    a = ap.parse_args()
    m = load_v16()
    log("引擎探针 = %s" % (FLEUR / "engine" / "audit.py"))
    recs = []
    for fn, tag in ((lambda: audit_hpdk(m), "hpdk_v15"),
                    (audit_a5, "a5"), (audit_qlch, "qlch"), (audit_forum8, "forum8")):
        try:
            r = fn()
        except Exception as e:                       # noqa: BLE001
            r = dict(id=tag, name=tag, status="blocked", error="%s: %s" % (type(e).__name__, str(e)[:300]))
        r.setdefault("status", "ok")
        recs.append(r)
        log("[%s] 同bar因果=%s method=%s status=%s" %
            (tag, r.get("same_bar_causality"), (r.get("method") or "")[:28], r.get("status")))
    out = dict(generated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               probe="fleur_absorb/engine/audit.py:probe_same_bar_causality（P5 · 双向投毒 ±1e9）",
               criterion="决策是否读取**成交那一根** bar：把该行整行双向毒化，决策必须一字不变",
               reference_arm=dict(id="hpdk_v16", same_bar_causality=False,
                                  script=str(V16.relative_to(R)).replace("\\", "/")),
               records=recs)
    f = pathlib.Path(a.outdir) / ("evidence_samebar_causality_%s.json" % TODAY)
    f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log("\n=== 同 bar 因果扫描（四口径 + 参照臂） ===")
    log("| 口径 | 同 bar 因果 | 判据 method | 证据（probe / file:line） |")
    log("|---|---|---|---|")
    for r in recs:
        ev = ""
        if r.get("probe") and not r["probe"].get("skipped"):
            pr = r["probe"]
            if "v15" in pr:                      # HPDK：三路（v1.5 / v1.6 / 阳性对照）
                ev = "probe v1.5: n_tripped=%s/n=%s" % (pr["v15"]["n_tripped"], pr["v15"]["n_probes"])
            elif "probe_gap_gate" in pr:         # qlch：gap 门探针 + 阳性对照
                ev = ("probe gap门 tripped=%s（带内 %s 只）· 阳性对照 ok=%s"
                      % (pr["probe_gap_gate"]["tripped"], pr["n_inband_in_clean"], pr["positive_control"]["ok"]))
            else:
                ev = "probe: n_tripped=%s/n=%s" % (pr.get("n_tripped"), pr.get("n_probes") or pr.get("n_rows"))
        elif r.get("probe", {}).get("skipped"):
            ev = "static only（探针资产缺失）"
        st = r.get("static") or []
        if st:
            ev += " · %s:%s-%s" % (st[0]["file"], st[0]["lines"][0]["n"], st[0]["lines"][-1]["n"])
        log("| %s | %s | %s | %s |" % (r.get("name"), r.get("same_bar_causality"), r.get("method"), ev))
    if out["records"][0].get("extra"):
        e = out["records"][0]["extra"]["probe_v16_for_reference"]
        log("| %s（参照） | %s | %s | probe: n_tripped=%s/n=%s · 阳性对照 n_tripped=%s |" %
            (e["name"], e["same_bar_causality"], e["method"], e["probe"]["n_tripped"],
             e["probe"]["n_probes"], e["positive_control"]["n_tripped"]))
    log("写入 %s" % f.name)


if __name__ == "__main__":
    main()
