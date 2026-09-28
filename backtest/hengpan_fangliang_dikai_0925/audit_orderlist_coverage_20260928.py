# -*- coding: utf-8 -*-
"""audit_orderlist_coverage_20260928.py — 挂单清单覆盖度：冻结买入的票，在「盘前 provisional 榜单」里排第几？

背景（watch_next.py 三种模式）：
  · 盘前（T+1 开盘未知）→ 按**全部合格股**打分 → 「盘前候选 top-30」provisional；挂单清单默认取 `--orders 20`
  · 买日数据入库后     → 用真实 GAP → 「精确前 10」（在**带内子集**内重算复合分，与冻结脚本一致）
所以：你盘前实际挂单的那批名字（provisional 前 N）与冻结策略真正会买的票（带内前 10）**不是同一批**。
本脚本量化：冻结的每一笔买入，其**盘前 provisional 名次**分布 → 挂单清单要覆盖到第几名才不漏票。

只读：直接流式读取上一脚本落盘的逐笔（scratch 缓存），不重跑回测、不改任何文件。
用法: python audit_orderlist_coverage_20260928.py [--cache DIR] [--out FILE]
"""
import argparse
import json
import os
import pathlib
import time

import numpy as np


def stream(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                out.append((r["signal_date"], r["sym"], r.get("gap_pct")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.environ.get("PI_SCRATCH_DIR") or ".")
    ap.add_argument("--out",
                    default=r"D:\Documents\Workbuddy\股票基金\quant-weight-system\backtest"
                            r"\hengpan_fangliang_dikai_0925\evidence_orderlist_coverage_20260928.json")
    a = ap.parse_args()
    cache = pathlib.Path(a.cache)
    t0 = time.time()
    W = cache / "_c_audit99_wide_trades.jsonl"
    F = cache / "_c_audit99_frozen_trades.jsonl"
    for p in (W, F):
        if not p.exists():
            raise SystemExit("缺少 %s —— 先跑 audit_orderflow_099_20260928.py" % p)

    print("[read] 资格池逐笔 …")
    wide = stream(W)
    print("[read] 冻结逐笔 …  (%d / %d 条, %.0fs)" % (len(wide), 0, time.time() - t0))
    frozen = stream(F)
    print("[read] done: wide=%d frozen=%d (%.0fs)" % (len(wide), len(frozen), time.time() - t0))

    # provisional 名次 = 该日 wide 列表中的出现次序（oos_run 按复合分降序 append）
    rank = {}
    for i, (d, s, _g) in enumerate(wide):
        rank.setdefault(d, []).append(s)
    pos = {}
    for d, lst in rank.items():
        for k, s in enumerate(lst):
            pos[(d, s)] = k

    ranks, gaps, miss = [], [], 0
    for d, s, g in frozen:
        k = pos.get((d, s))
        if k is None:
            miss += 1
            continue
        ranks.append(k)
        gaps.append(g)
    ranks = np.array(ranks, int)
    print("[rank] 冻结买入 %d 笔（其中 %d 笔在资格池中找不到，跳过）" % (len(ranks), miss))

    def share(n):
        return round(100.0 * float((ranks < n).mean()), 2)

    payload = dict(
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        purpose="量化「盘前 provisional 挂单清单」与「冻结策略实际买入」的覆盖差",
        n_frozen=int(len(ranks)), n_not_found=int(miss), n_wide=int(len(wide)),
        provisional_rank=dict(
            min=int(ranks.min()), p10=int(np.percentile(ranks, 10)), median=int(np.median(ranks)),
            p90=int(np.percentile(ranks, 90)), p99=int(np.percentile(ranks, 99)), max=int(ranks.max()),
            mean=round(float(ranks.mean()), 1)),
        coverage_pct=dict(top10=share(10), top20=share(20), top30=share(30), top50=share(50),
                          top100=share(100), top200=share(200), top500=share(500), top1000=share(1000)),
        note="coverage_pct[topN] = 冻结买入中，盘前 provisional 名次 < N 的占比（= 挂单清单取前 N 名能覆盖到的比例）",
        runtime_sec=round(time.time() - t0, 1))
    pathlib.Path(a.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n=== 冻结买入的「盘前 provisional 名次」分布 ===")
    print("  min=%d p10=%d 中位=%d p90=%d p99=%d max=%d 均值=%.1f"
          % (ranks.min(), np.percentile(ranks, 10), np.median(ranks), np.percentile(ranks, 90),
             np.percentile(ranks, 99), ranks.max(), ranks.mean()))
    print("\n=== 挂单清单取前 N 名能覆盖多少冻结买入 ===")
    for n in (10, 20, 30, 50, 100, 200, 500, 1000):
        print("  top%-5d → %6.2f%%" % (n, share(n)))
    print("\n[wrote] %s (%.0fs)" % (a.out, time.time() - t0))


if __name__ == "__main__":
    main()
