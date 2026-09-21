# -*- coding: utf-8 -*-
"""小步碎阳 · 新止损口径（围绕五日线 + 不跌破十日均线）（XBSY-MA10-0921）
================================================================================
用户 2026-09-21 追加：把止损换成 —— **围绕五日均线，期间不跌破十日均线**

拆成两个组件，全部预注册、并列跑、不合并、不事后择优
--------------------------------------------------------------------------------
入场形态（「围绕五日均线」）：
  F0 = 无过滤（原 A_tdx，TDX 原文）
  F1 = 信号日 |收盘−MA5|/MA5 ≤ **3%**  且  收盘 > MA(C,10)
  F2 = 信号日 |收盘−MA5|/MA5 ≤ **1.5%** 且  收盘 > MA(C,10)

止损（「期间不跌破十日均线」）：
  Y1 = 收盘 < MA(C,10)（单日）→ 次日开盘卖
  Y2 = 收盘 < MA(C,10) **连续 2 日** → 次日开盘卖（防单日洗盘）
  Y3 = 爆量≥2×MA(V,20) + 次日阴（上一轮冠军 X8，作参照）
  Y4 = Y3 与 Y1 先到者
  Y7 = 固定 20 日（基准对照）

出场上限 cap=60（Y7 为 20）。成本：滑点 20bp/边 + 佣金 2.5bp（最低 5 元，每仓名义 8,500 元）。
两种资金口径都跑：**无限资金**（全吃信号·等权·无并发上限）与 **可执行 20 仓**（量比升序）。

判据同前：年化 / 夏普 / 最大回撤 / 胜率（按笔 + 按天）双给；样本量必须一并报（过滤后是否塌缩）。

用法：cd quant-weight-system && python backtest/xbsy_ma10_0921.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

import factor_gate as FG                                    # noqa: E402
import xbsy_0921 as X                                       # noqa: E402
import xbsy_port_0921 as PORT                               # noqa: E402

OUT_JSON = str(HERE / "xbsy_ma10_0921.json")

Y1 = dict(boom=None, lag=1, ma5=False, ma10=True, ma10_days=1, cap=60)
Y2 = dict(boom=None, lag=1, ma5=False, ma10=True, ma10_days=2, cap=60)
Y3 = dict(boom="q2", lag=1, ma5=False, ma10=False, cap=250)          # 上轮冠军 X8
Y4 = dict(boom="q2", lag=1, ma5=False, ma10=True, ma10_days=1, cap=60)
Y7 = dict(boom=None, lag=1, ma5=False, ma10=False, cap=20)

GRID = [
    ("F0无过滤 + Y1破MA10单日", "F0", Y1),
    ("F0无过滤 + Y2破MA10连续2日", "F0", Y2),
    ("F1围绕MA5≤3% + Y1破MA10", "F1", Y1),
    ("F2围绕MA5≤1.5% + Y1破MA10", "F2", Y1),
    ("F1围绕MA5≤3% + Y4爆量阴&破MA10", "F1", Y4),
    ("F1围绕MA5≤3% + Y3爆量阴(参照)", "F1", Y3),
    ("F0无过滤 + Y3爆量阴(参照)", "F0", Y3),
    ("F0无过滤 + Y7固定20日(对照)", "F0", Y7),
    ("F1围绕MA5≤3% + Y7固定20日(对照)", "F1", Y7),
]


def entry_variants(P, V, SIG):
    C = P["close"].astype(np.float64)
    ma5 = X.roll_mean(C, 5)
    ma10 = X.roll_mean(C, 10)
    with np.errstate(all="ignore"):
        dev = np.abs(C - ma5) / ma5
    base = SIG.copy()
    f1 = base & np.isfinite(dev) & (dev <= 0.03) & np.isfinite(ma10) & (C > ma10)
    f2 = base & np.isfinite(dev) & (dev <= 0.015) & np.isfinite(ma10) & (C > ma10)
    return {"F0": base, "F1": f1, "F2": f2}


def main():
    t0 = time.time()
    print("=" * 112)
    print("小步碎阳 · 新止损：围绕五日线 + 期间不跌破十日均线（XBSY-MA10-0921）")
    print("=" * 112)
    P = FG.load_panel(X.PANEL)
    D = np.load(X.PANEL, allow_pickle=True)
    codes, cal = D["codes"], D["cal"]
    T, N = P["close"].shape
    V = X.load_volume([str(c) for c in codes], [str(d) for d in cal])
    SIGA = X.build_arms(P, V)["A_tdx"]
    mav20 = X.roll_mean(V, 20)
    ratio = np.where(np.isfinite(mav20) & (mav20 > 0), V / mav20, np.nan)
    SIGS = entry_variants(P, V, SIGA)
    print(f"面板 {T} 日 × {N} 只 | {cal[0]} → {cal[-1]}")

    print("\n① 入场过滤后的样本（是否塌缩）")
    for k, S in SIGS.items():
        per = S.sum(axis=1)
        act = int((per > 0).sum())
        med = float(np.median(per[per > 0])) if act else 0.0
        print(f"  {k:<4} 信号 {int(S.sum()):>8,}  活跃日 {act:>5}  日中位 {med:>6.1f}  "
              f"样本闸 {'PASS' if int(S.sum()) >= 100 and act >= 30 else '不可判定'}")

    out = {"span": [str(cal[0]), str(cal[-1])], "runs": {}, "sample": {}}
    for k, S in SIGS.items():
        out["sample"][k] = {"n_sig": int(S.sum()),
                            "days_active": int((S.sum(axis=1) > 0).sum())}

    # 沪深300 对照
    import pandas as pd
    idx = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
    idx = idx[(idx["date"] >= str(cal[0])) & (idx["date"] <= str(cal[-1]))]
    hs = idx["close"].to_numpy(dtype=np.float64)
    bm = PORT.metrics(PORT.NAV0 * hs / hs[0], idx["date"].tolist(), [], "沪深300")

    print("\n" + "-" * 112)
    print("② 无限资金（全吃信号 · 等权 · 无并发上限）")
    print("-" * 112)
    hdr = (f"  {'配置':<36}{'信号数':>9}{'年化':>8}{'夏普':>8}{'最大回撤':>10}{'按笔胜率':>9}"
           f"{'按天胜率':>9}{'每笔均值':>10}{'平均并发':>10}{'末期净值':>10}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for tag, fk, yk in GRID:
        S = SIGS[fk]
        nav, _, meta = PORT.simulate_unlimited(P, V, S, yk)
        m = PORT.metrics(nav, cal, [], tag)
        m.update(meta)
        m["entry_filter"] = fk
        m["n_sig"] = int(S.sum())
        out["runs"][f"无限资金 · {tag}"] = m
        print(f"  {tag:<36}{int(S.sum()):>9,}{m['cagr']:>8.2%}{m['sharpe']:>8.3f}"
              f"{m['max_drawdown']:>10.2%}{meta['win_rate_per_trade']:>9.1%}"
              f"{m['win_rate_per_day']:>9.1%}{meta['mean_per_trade']:>10.4f}"
              f"{meta['avg_concurrency']:>10,.0f}{m['final_nav']:>10,.0f}")
    print(f"  {'沪深300 买入持有（对照）':<36}{'—':>9}{bm['cagr']:>8.2%}{bm['sharpe']:>8.3f}"
          f"{bm['max_drawdown']:>10.2%}{'—':>9}{bm['win_rate_per_day']:>9.1%}{'—':>10}"
          f"{'—':>10}{bm['final_nav']:>10,.0f}")

    print("\n" + "-" * 112)
    print("③ 可执行版本（并发上限 20 · 每仓 8,500 元 · 量比升序）")
    print("-" * 112)
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for tag, fk, yk in GRID:
        S = SIGS[fk]
        nav, trades = PORT.simulate(P, V, S, ratio, yk, "量比升序", 20)
        m = PORT.metrics(nav, cal, trades, tag)
        m["entry_filter"] = fk
        out["runs"][f"20仓 · {tag}"] = m
        print(f"  {tag:<36}{int(S.sum()):>9,}{m['cagr']:>8.2%}{m['sharpe']:>8.3f}"
              f"{m['max_drawdown']:>10.2%}{(m['win_rate_per_trade'] or 0):>9.1%}"
              f"{m['win_rate_per_day']:>9.1%}{(m['mean_per_trade'] or 0):>10.4f}"
              f"{20:>10,}{m['final_nav']:>10,.0f}")
    print(f"  {'沪深300 买入持有（对照）':<36}{'—':>9}{bm['cagr']:>8.2%}{bm['sharpe']:>8.3f}"
          f"{bm['max_drawdown']:>10.2%}{'—':>9}{bm['win_rate_per_day']:>9.1%}{'—':>10}"
          f"{'—':>10}{bm['final_nav']:>10,.0f}")

    out["elapsed_s"] = round(time.time() - t0, 1)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n结果已落盘 {OUT_JSON}（{out['elapsed_s']}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
