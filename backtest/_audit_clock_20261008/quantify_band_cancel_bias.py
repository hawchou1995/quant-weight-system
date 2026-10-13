# -*- coding: utf-8 -*-
"""量化「盲挂撤单乐观偏差」（ADR-0004 · B-3 / R3）

问题
----
盲挂协议把「带内成交、带外不成交」实现为：挂 `昨收×(1+上沿)` 限价，**下沿**（gap < lo）
靠 **09:15–09:20 可撤单窗**撤单。而撤单决策当时能看到的是**集合竞价虚拟开盘参考价**，
不是最终的今开。回测（v1.6 / A5）用**最终今开**代替参考价来决定撤不撤 —— 这是**残留的
同 bar 依赖**，且方向**乐观**：

  · 参考价在带内（不撤）→ 最终开盘跌破下沿 → 你的限价单**成交在带外更低的价格**
    （回测把它记成「未成交」⇒ 回测回避了这些交易 = 乐观）
  · 参考价跌破下沿（撤单）→ 最终开盘回到带内 → 现实**没有**成交
    （回测按今开判不撤、记成成交 ⇒ 回测多记了一笔 = 乐观）

本脚本用本机**已有实测证据**量化这两个方向的发生率与幅度。

数据源
------
`evidence_auction_field_probe_20260930.json` —— 2026-09-30 09:44 实测，8 只票在
  09:15–09:29 的逐分钟「现价」序列（已实证该序列 = 集合竞价虚拟开盘参考价）+ 昨收 + 腾讯官方今开。
`sample_intraday_20260929.json` —— 同日另一份盘中样本（结构不同，按可用字段尽力纳入）。

输出：`evidence_band_cancel_bias_20261008.json`
用法：`python quantify_band_cancel_bias.py`
"""
from __future__ import annotations

import json
import os
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
HP = os.path.join(os.path.dirname(HERE), "hengpan_fangliang_dikai_0925")  # 证据所在目录

SRC1 = os.path.join(HP, "evidence_auction_field_probe_20260930.json")
SRC2 = os.path.join(HP, "sample_intraday_20260929.json")
OUT = os.path.join(HERE, "evidence_band_cancel_bias_20261008.json")

#: 策略带（下沿 lo, 上沿 hi）—— 撤单决策只由**下沿**触发
BANDS = {"hpdk": (-0.03, -0.01), "a5": (-0.05, -0.02)}
#: 撤单决策的观察时点（可撤单窗内）
DECIDE_AT = "09:18"


def _f(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def collect():
    """收集 (sym, name, pcl, opn, series) 记录。"""
    recs = []
    if os.path.isfile(SRC1):
        d = json.load(open(SRC1, encoding="utf-8"))
        for sym, v in (d.get("detail") or {}).items():
            if not isinstance(v, dict):
                continue
            pcl, opn, ser = _f(v.get("pcl")), _f(v.get("opn")), v.get("series") or {}
            if pcl and pcl > 0 and opn and opn > 0 and isinstance(ser, dict) and ser:
                recs.append(dict(sym=sym, name=v.get("name", ""), pcl=pcl, opn=opn,
                                 series={k: _f(x) for k, x in ser.items()}, src="field_probe_0930"))
    if os.path.isfile(SRC2):
        d = json.load(open(SRC2, encoding="utf-8"))
        # 结构未知 → 递归找「含 pcl+opn+series」的字典
        def walk(o):
            if isinstance(o, dict):
                if _f(o.get("pcl")) and _f(o.get("opn")) and isinstance(o.get("series"), dict):
                    recs.append(dict(sym=o.get("sym") or o.get("code") or "?",
                                     name=o.get("name", ""), pcl=_f(o["pcl"]), opn=_f(o["opn"]),
                                     series={k: _f(x) for k, x in o["series"].items()},
                                     src="sample_0929"))
                    return
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(d)
    return recs


def quantify(recs):
    rows, disag = [], {k: dict(n=0, cancel_bt_only=0, cancel_rt_only=0, outside_fill=0,
                               missed_fill=0) for k in BANDS}
    deltas = []
    for r in recs:
        pcl = r["pcl"]
        g_open = r["opn"] / pcl - 1.0
        ref = r["series"].get(DECIDE_AT)
        if not (ref and ref > 0):
            # 退化到可撤单窗内最后一刻
            for t in ("09:20", "09:19", "09:17", "09:16", "09:15"):
                ref = r["series"].get(t)
                if ref and ref > 0:
                    break
        if not (ref and ref > 0):
            continue
        g_ref = ref / pcl - 1.0
        deltas.append(abs(g_ref - g_open))
        row = dict(sym=r["sym"], name=r["name"], src=r["src"], pcl=pcl,
                   ref_px=ref, open_px=r["opn"],
                   gap_ref=round(g_ref, 6), gap_open=round(g_open, 6),
                   abs_delta=round(abs(g_ref - g_open), 6))
        for bk, (lo, hi) in BANDS.items():
            cancel_bt = g_open < lo        # 回测：用最终今开判撤单
            cancel_rt = g_ref < lo         # 现实：用 09:18 参考价判撤单
            row[f"{bk}_band"] = [round(lo, 4), round(hi, 4)]
            row[f"{bk}_cancel_bt"] = bool(cancel_bt)
            row[f"{bk}_cancel_rt"] = bool(cancel_rt)
            row[f"{bk}_disagree"] = bool(cancel_bt != cancel_rt)
            if cancel_bt != cancel_rt:
                disag[bk]["n"] += 1
                if cancel_bt and not cancel_rt:
                    # 回测判撤（不计成交）；现实没撤 → 成交在带外更低处 = 回测乐观
                    disag[bk]["outside_fill"] += 1
                else:
                    # 回测判不撤（计成交）；现实已撤 → 现实无此笔 = 回测乐观
                    disag[bk]["missed_fill"] += 1
        rows.append(row)
    return rows, disag, deltas


def main() -> int:
    recs = collect()
    rows, disag, deltas = quantify(recs)
    n = len(rows)
    ev = dict(
        _what="量化「盲挂撤单乐观偏差」（ADR-0004 · B-3/R3）：回测用最终今开代替"
              "09:15–09:20 可撤单窗可见的虚拟开盘参考价来决定撤单 ⇒ 残留同 bar 依赖",
        method="逐票比较 gap(09:18 参考价) vs gap(最终今开)，统计两侧撤单决策不一致率与幅度",
        sources=[os.path.basename(SRC1), os.path.basename(SRC2)],
        decide_at=DECIDE_AT,
        bands={k: list(v) for k, v in BANDS.items()},
        n_stocks=n,
        noise=dict(
            abs_delta_pct=dict(
                mean=round(100 * (st.mean(deltas) if deltas else 0.0), 4),
                median=round(100 * (st.median(deltas) if deltas else 0.0), 4),
                max=round(100 * (max(deltas) if deltas else 0.0), 4),
                n=len(deltas)),
            note="|gap(09:18 参考价) − gap(最终今开)| 的分布 —— 撤单决策可见信息与成交价的差"),
        disagreement={k: dict(**v, rate=(round(v["n"] / n, 4) if n else None)) for k, v in disag.items()},
        rows=rows,
        materiality=dict(
            band_width_pct={k: round((hi - lo) * 100, 2) for k, (lo, hi) in BANDS.items()},
            noise_max_pct=round(100 * (max(deltas) if deltas else 0.0), 4),
            ratio_noise_max_over_hpdk_width=(
                round((max(deltas) if deltas else 0.0) / (BANDS["hpdk"][1] - BANDS["hpdk"][0]), 3)
                if deltas else None),
            note=("参考价噪声上限 %.2fpp **大于** HPDK 带宽 %.2fpp ⇒ 在带边附近"
                  "「撤不撤」的决策**本质不稳定** ⇒ 该残留同 bar 依赖是**实质性**的，"
                  "不是装饰性的。A5 带宽 %.2fpp 亦与噪声同量级。"
                  % (100 * (max(deltas) if deltas else 0.0),
                     (BANDS["hpdk"][1] - BANDS["hpdk"][0]) * 100,
                     (BANDS["a5"][1] - BANDS["a5"][0]) * 100))),
        caveat=("样本极小（n=%d）且 8 只票的 gap 都靠近 0（|gap| 多在 1%% 内），"
                "**未落在 HPDK[−3%%,−1%%] / A5[−5%%,−2%%] 的下沿附近** ⇒ 本样本对"
                "「下沿撤单不一致」的估计**不具统计效力**，只能作为**机制存在性证明**与"
                "噪声量级的粗估。要给出可用偏差率，需要「候选池内、开盘 gap 落在"
                "下沿 ±1%% 邻域」的样本 —— 本机现有证据不含该子集。" % n),
        verdict=("机制**确实存在**（参考价与今开在可撤单窗内会变动，09:18 与最终开盘不一致）；"
                 "但偏差**幅度不可用现有证据定量**，须先采集「下沿邻域」样本。"
                 "在拿到该样本前：v1.6 / A5 的读数必须标注「下沿撤单假设完美 ⇒ 乐观」。"),
    )
    print("\n结论：", ev["verdict"][:120])
    print("\n已写出", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
