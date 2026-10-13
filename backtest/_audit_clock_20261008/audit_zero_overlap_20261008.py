# -*- coding: utf-8 -*-
"""交易集合「共有=0」归因 · 可复跑回归门（2026-10-08）

背景
----
上一轮发现：`fourarms_A_x3_legacy_trades.csv`（生产状态机，404 笔）
与引擎侧交易集合的**归一化键交集 = 0**，但**代码交集 283**、日期交集 47。
根因是**移植 off-by-one**：引擎成交日比生产口径晚 1 个交易日。

本脚本把那次只读验证**固化成可复跑判据**，并作为修正后的回归门。

输入（**全部来自已落盘产物**，故满足「可从产物重算」的复现性要求）
--------------------------------------------------------------------
  fourarms_<arm>_legacy_trades.csv                              L1 生产状态机 @cache
  fourarms_<arm>_engine_cache<suffix>_trades.csv                L2 引擎 @cache
  index_000300.csv                                              交易日历（位移扫描按它索引）

`suffix` 用于区分两档对齐产物：
  ""（默认）        → 修正后同 bar 对齐，期望 **PASS**
  "_LEGACYALIGN"    → 修正前 off-by-one 写法，应复现 **FAIL（共有=0 / 位移−1 更高）**

判据
----
  G1 对齐 : 位移 0 的归一化键交集 ≥ 0.95 × min(n_legacy, n_engine)
  G2 反向 : 位移 −1 / +1 的交集 **不得**高于位移 0
  G5 出场 : 已对齐键的 exit 交易日距离众数 = 0
  H1/H2/H3: 上述三条的逐条裁定记录

用法
----
  python audit_zero_overlap_20261008.py                                   # 审计修正后产物
  python audit_zero_overlap_20261008.py --suffix _LEGACYALIGN \
         --out evidence_zero_overlap_prefix_20261008.json --label prefix  # 复现修正前基线

退出码：0 = 全门 PASS / 1 = 有门未过
"""
from __future__ import annotations

import argparse
import json
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
IDX = os.path.join(REPO, "index_000300.csv")
OUT = os.path.join(HERE, "evidence_zero_overlap_20261008.json")
ARMS = ["A_x3", "C_x3", "B_x3"]
SHIFTS = (-3, -2, -1, 0, 1, 2, 3)


def load_calendar():
    idx = pd.read_csv(IDX)
    idx["date"] = pd.to_datetime(idx["date"])
    idx = idx.sort_values("date").reset_index(drop=True)
    cal = [d for d in idx["date"] if d >= pd.Timestamp("2016-06-01")]
    return cal, {d: i for i, d in enumerate(cal)}


def read_trades(path, cal):
    """读逐笔 CSV。兼容两种 `entry_date` 语义：

    ① 已是日期（修正后 `dump_trades` 写出）→ 直接解析；
    ② 是**引擎时间索引**（旧产物，如 int64 19..2472）→ 用交易日历还原成日期。
    这样修正前的旧产物也能被审计（复现「共有=0」基线要用它）。
    """
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path, encoding="utf-8-sig")
    if df.empty:
        return None
    ed = pd.to_datetime(df["entry_date"], errors="coerce")
    if ed.isna().all() and "entry_idx" in df.columns:
        df["entry_date"] = [cal[int(i)].normalize() for i in df["entry_idx"]]
    else:
        df["entry_date"] = ed.dt.normalize()
    if "exit_date" in df.columns:
        xd = pd.to_datetime(df["exit_date"], errors="coerce")
        if xd.isna().all() and "exit_idx" in df.columns:
            df["exit_date"] = [cal[int(i)].normalize() for i in df["exit_idx"]]
        else:
            df["exit_date"] = xd.dt.normalize()
    return df


def keyset(df):
    return {(str(r.sym), r.entry_date) for r in df.itertuples(index=False)}


def dist_mode(pairs):
    """距离分布 → 众数 / 计数 / 全直方图。"""
    if not pairs:
        return dict(mode=None, n=0, hist={})
    hist = {}
    for d in pairs:
        hist[d] = hist.get(d, 0) + 1
    mode = max(sorted(hist), key=lambda k: hist[k])
    return dict(mode=int(mode), n=len(pairs),
                hist={str(k): v for k, v in sorted(hist.items())})


def _dist_between(d1, d2, di):
    """同代码配对 → 交易日距离列表。"""
    out = []
    for sym in set(d1) & set(d2):
        for a in d1[sym]:
            for b in d2[sym]:
                ia, ib = di.get(a), di.get(b)
                if ia is not None and ib is not None:
                    out.append(ib - ia)
    return out


def audit_arm(arm, cal, di, src_dir, suffix):
    f_leg = "fourarms_%s_legacy_trades.csv" % arm
    f_eng = "fourarms_%s_engine_cache%s_trades.csv" % (arm, suffix)
    r = dict(arm=arm, align_suffix=suffix,
             artifacts=dict(legacy=f_leg, engine=f_eng))
    l1 = read_trades(os.path.join(src_dir, f_leg), cal)
    l2 = read_trades(os.path.join(src_dir, f_eng), cal)
    if l1 is None or l2 is None:
        r["status"] = "SKIP"
        r["why"] = "缺产物（%s）" % ("L1" if l1 is None else "L2")
        return r
    r["n_legacy"] = int(len(l1))
    r["n_engine"] = int(len(l2))
    k1, k2 = keyset(l1), keyset(l2)
    r["n_keys_legacy"] = len(k1)
    r["n_keys_engine"] = len(k2)
    r["code_intersection"] = len({s for s, _ in k1} & {s for s, _ in k2})
    r["date_intersection"] = len({d for _, d in k1} & {d for _, d in k2})

    # ---- 位移扫描（按交易日历索引平移引擎侧入场日）----
    scan = {}
    for sh in SHIFTS:
        moved = set()
        for sym, d in k2:
            i = di.get(d)
            if i is None:
                continue
            j = i + sh
            if 0 <= j < len(cal):
                moved.add((sym, cal[j]))
        scan[sh] = len(k1 & moved)
    r["shift_scan"] = {str(k): v for k, v in scan.items()}
    r["n_common_shift0"] = scan[0]

    # ---- 入场距离分布（同代码配对）----
    e1, e2 = {}, {}
    for sym, dt in k1:
        e1.setdefault(sym, []).append(dt)
    for sym, dt in k2:
        e2.setdefault(sym, []).append(dt)
    r["entry_distance"] = dist_mode(_dist_between(e1, e2, di))

    # ---- 出场距离分布：只比对位移 0 已对齐的键 ----
    common = k1 & k2
    if "exit_date" in l1.columns and "exit_date" in l2.columns:
        x1 = {(str(x.sym), x.entry_date): x.exit_date for x in l1.itertuples(index=False)
              if (str(x.sym), x.entry_date) in common}
        x2 = {(str(x.sym), x.entry_date): x.exit_date for x in l2.itertuples(index=False)
              if (str(x.sym), x.entry_date) in common}
        pairs = []
        for kk in set(x1) & set(x2):
            ia, ib = di.get(x1[kk]), di.get(x2[kk])
            if ia is not None and ib is not None:
                pairs.append(ib - ia)
        r["exit_distance"] = dist_mode(pairs)
    else:
        r["exit_distance"] = dict(mode=None, n=0, hist={}, why="缺 exit_date 列")

    # ---- 判据 ----
    thr = 0.95 * min(len(k1), len(k2))
    g1 = scan[0] >= thr
    g2 = scan[0] >= max(scan[-1], scan[1])
    g5 = (r["exit_distance"]["mode"] == 0) and (r["exit_distance"]["n"] > 0)
    r["gates"] = dict(
        G1=dict(pass_=bool(g1), rule="位移0 交集 ≥ 0.95×min(n)",
                value=scan[0], threshold=round(thr, 2)),
        G2=dict(pass_=bool(g2), rule="位移±1 不得高于位移0",
                value=dict(m1=scan[-1], s0=scan[0], p1=scan[1])),
        G5=dict(pass_=bool(g5), rule="已对齐键的 exit 交易日距离众数=0",
                value=r["exit_distance"]["mode"]))
    r["H1"] = "支持「已对齐」" if g1 else "不支持 —— 仍有系统性偏移"
    r["H2"] = "支持「不再是 off-by-one」" if g2 else "不支持 —— 位移±1 更优，仍是 off-by-one"
    r["H3"] = ("支持「同日入场」" if r["entry_distance"]["mode"] == 0
               else "不支持 —— 入场日距离众数=%s" % r["entry_distance"]["mode"])
    r["status"] = "PASS" if (g1 and g2 and g5) else "FAIL"
    return r


def main():
    ap = argparse.ArgumentParser(description="交易集合归因 · 回归门（G1/G2/G5）")
    ap.add_argument("--dir", default=HERE, help="逐笔产物目录")
    ap.add_argument("--suffix", default="", help="engine 文件名后缀（如 _LEGACYALIGN）")
    ap.add_argument("--out", default=None, help="证据 JSON 输出路径")
    ap.add_argument("--label", default="", help="本次审计标签（写入证据 JSON）")
    a = ap.parse_args()

    cal, di = load_calendar()
    out_path = a.out or OUT
    ev = dict(_what="交易集合「共有=0」归因 · 回归门（G1/G2/G5）",
              label=a.label or (a.suffix.strip("_") or "fixed"),
              generated_at=pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
              src_dir=a.dir, align_suffix=a.suffix,
              calendar=dict(source="index_000300.csv", n_days=len(cal),
                            first=cal[0].date().isoformat(), last=cal[-1].date().isoformat()),
              shifts=list(SHIFTS), arms={})
    rc = 0
    for arm in ARMS:
        r = audit_arm(arm, cal, di, a.dir, a.suffix)
        ev["arms"][arm] = r
        if r.get("status") == "SKIP":
            print("%-6s SKIP  %s" % (arm, r.get("why")))
            continue
        print("%-6s %-4s n(L1)=%-4s n(L2)=%-4s | 共有@0=%-4s @-1=%-4s @+1=%-4s | "
              "入场距离众数=%-3s 出场距离众数=%-3s | G1=%s G2=%s G5=%s"
              % (arm, r["status"], r["n_legacy"], r["n_engine"], r["n_common_shift0"],
                 r["shift_scan"]["-1"], r["shift_scan"]["1"],
                 r["entry_distance"]["mode"], r["exit_distance"]["mode"],
                 r["gates"]["G1"]["pass_"], r["gates"]["G2"]["pass_"], r["gates"]["G5"]["pass_"]))
        if r["status"] != "PASS":
            rc = 1
    ev["verdict"] = "PASS" if rc == 0 else "FAIL"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(ev, fh, ensure_ascii=False, indent=1)
    print("\nverdict = %s  →  %s" % (ev["verdict"], os.path.basename(out_path)))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
