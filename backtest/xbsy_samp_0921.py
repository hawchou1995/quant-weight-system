# -*- coding: utf-8 -*-
"""小步碎阳 + 爆量阴线出场 · 组合层样本量补足（XBSY-SAMP-0921 · 用户 2026-09-21 批准）
================================================================================
要解决的问题
--------------------------------------------------------------------------------
上一轮结论是「组合层不可判定」：20 仓口径只有几百笔交易、单一窗口，撑不起任何结论。
本轮的命题：**把交易笔数抬到可判定的量级，看结论是否稳定。**

关键设计（为什么这样设计才干净）
--------------------------------------------------------------------------------
「样本量」在组合层是**资金约束**而不是数据约束（数据里有 23 万事件）。
直接放大槽位会同时改变**单仓名义** → 佣金最低 5 元的占比变化 → 成本口径变了，结论不可比。
故主口径 **A：固定每仓名义 8,500 元（= 17万/20），槽位与本金同比例放大** ——
只有笔数变、每笔成本率不变，才能把"样本量"这一个变量单独拎出来。

预注册（看数字之前固定）
--------------------------------------------------------------------------------
- 入场 = A_tdx（TDX 原文小步碎阳形态）；出场 = 爆量 ≥2×MA(V,20) + 次日阴线 → 次日开盘卖（cap 250）
  （即 XBSY-MA10-0921 里 20 仓 +4.54% 的同一配置，本轮不改口径，只改样本量）
- 宇宙 = 主板面板（kv_resonance_0913，4087 只，2016-01-04 → 2026-09-18）
- 成本 = 滑点 20bp/边 + 佣金 max(名义×2.5bp, **5 元最低**) —— 整手约束照实建模
- 口径 A（主）：每仓名义固定 8,500 元；槽位 N ∈ {20, 50, 100, 200}，对应本金 {17万, 42.5万, 85万, 170万}
- 口径 B（执行墙）：本金固定 17 万；只放大槽位 N ∈ {20, 50, 100, 200} → 每仓 8,500 → 850 元
- 排序键两档：**代码序**（无信息、无逆向选择，作主）＋ **量比升序**（上一轮的键，作对照）
  ⚠ 上一轮 XBSY-ABL-0921 已证「量比升序」是稳定负 alpha 选票规则（3/3 臂为负），故本轮**不以它为主**
- 判据：笔数是否达到可判定量级；年化/夏普/回撤/按笔胜率随样本量的走向；
  并按日 t = 夏普 × √年数，与沪深300（长窗 t=0.73）对比 —— **t 才是判据，年化不是**

用法：cd quant-weight-system && python backtest/xbsy_samp_0921.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

import xbsy_0921 as X                                       # noqa: E402
import xbsy_port_0921 as PORT                               # noqa: E402
import xbsy_res_0921 as RES                                 # noqa: E402
import xbsy_res2_0921 as RES2                               # noqa: E402
import xbsy_abl_0921 as ABL                                 # noqa: E402

OUT_JSON = str(HERE / "xbsy_samp_0921.json")
CFG = dict(boom="q2", lag=1, ma5=False, ma10=False, cap=250)
NOTIONAL = 8500.0
NS = [20, 50, 100, 200]
KEYS = [("代码序", "code", False), ("量比升序", "vr", False)]


def main():
    t0 = time.time()
    print("=" * 118)
    print("小步碎阳 + 爆量阴线 · 组合层样本量补足（XBSY-SAMP-0921）· 主板 2016-01-04 → 2026-09-18")
    print("=" * 118)
    idxall, cal, codes, P, V = RES2.build()
    T, N = P["close"].shape
    SIG = X.build_arms(P, V)["A_tdx"]
    vma = X.roll_mean(V, 20)
    with np.errstate(all="ignore"):
        vr = V / vma
    keymats = {"vr": vr, "code": None}

    ix = idxall[(idxall["date"] >= RES.PANEL_FROM) & (idxall["date"] <= "2026-09-18")].reset_index(drop=True)
    ic = ix["close"].to_numpy(float)
    s_i = cal.index(RES2.START) if RES2.START in cal else 0
    bm = PORT.metrics(PORT.NAV0 * ic[s_i:] / ic[s_i], [str(x) for x in ix["date"][s_i:]], [], "沪深300")
    bm["t_daily"] = round(bm["sharpe"] * np.sqrt(bm["years"]), 2)
    print(f"信号 A_tdx n={int(SIG.sum()):,} | 沪深300 长窗 年化 {bm['cagr']:+.2%} 夏普 {bm['sharpe']:.3f} "
          f"回撤 {bm['max_drawdown']:.2%} t {bm['t_daily']:.2f}")

    out = {"span": ["2016-01-04", "2026-09-18"], "cfg": CFG, "notional": NOTIONAL,
           "hs300": bm, "modeA": {}, "modeB": {}, "by_year": {}}

    hdr = (f"  {'口径':<10}{'键':<10}{'槽位':>5}{'本金':>11}{'每仓':>8}{'佣金bp/边':>10}"
           f"{'笔数':>7}{'年化':>9}{'夏普':>8}{'最大回撤':>10}{'按笔胜率':>9}{'t(按日)':>9}")
    print("\n" + "-" * 118)
    print("① 口径 A（固定每仓 8,500 元，槽位与本金同比例放大）—— 只有样本量这一个变量在变")
    print("-" * 118)
    print(hdr); print("  " + "-" * (len(hdr) - 2))
    for rname, rkey, desc in KEYS:
        for n_ in NS:
            nav0 = NOTIONAL * n_
            PORT.NAV0 = nav0
            nav, tr = ABL.sim_rank(P, V, SIG, keymats[rkey], desc, CFG, n_)
            m = PORT.metrics(nav, cal, tr, f"A|{rname}|{n_}")
            fee_bp = max(NOTIONAL * PORT.COMM, PORT.MIN_COMM) / NOTIONAL * 1e4
            td = round(m["sharpe"] * np.sqrt(m["years"]), 2)
            rec = {**m, "note_per_pos": NOTIONAL, "nav0": nav0, "fee_bp_side": round(fee_bp, 2), "t_daily": td}
            out["modeA"][f"{rname}|{n_}"] = rec
            print(f"  {'A':<10}{rname:<10}{n_:>5}{nav0:>11,.0f}{NOTIONAL:>8,.0f}{fee_bp:>10.1f}"
                  f"{len(tr):>7}{m['cagr']:>9.2%}{m['sharpe']:>8.3f}{m['max_drawdown']:>10.2%}"
                  f"{(m['win_rate_per_trade'] or 0):>9.1%}{td:>9.2f}")

    print("\n" + "-" * 118)
    print("② 口径 B（本金固定 17 万，只放大槽位）—— 每仓名义被摊薄，佣金最低 5 元开始咬人")
    print("-" * 118)
    print(hdr); print("  " + "-" * (len(hdr) - 2))
    for rname, rkey, desc in KEYS:
        for n_ in NS:
            PORT.NAV0 = 170000.0
            nav, tr = ABL.sim_rank(P, V, SIG, keymats[rkey], desc, CFG, n_)
            m = PORT.metrics(nav, cal, tr, f"B|{rname}|{n_}")
            per = 170000.0 / n_
            fee_bp = max(per * PORT.COMM, PORT.MIN_COMM) / per * 1e4
            td = round(m["sharpe"] * np.sqrt(m["years"]), 2)
            out["modeB"][f"{rname}|{n_}"] = {**m, "note_per_pos": round(per, 1),
                                             "fee_bp_side": round(fee_bp, 2), "t_daily": td}
            print(f"  {'B':<10}{rname:<10}{n_:>5}{170000:>11,.0f}{per:>8,.0f}{fee_bp:>10.1f}"
                  f"{len(tr):>7}{m['cagr']:>9.2%}{m['sharpe']:>8.3f}{m['max_drawdown']:>10.2%}"
                  f"{(m['win_rate_per_trade'] or 0):>9.1%}{td:>9.2f}")

    print("\n" + "-" * 118)
    print("③ 逐年拆解（口径 A · 代码序 · 槽位 100 / 本金 85 万 —— 笔数最大的可用口径）")
    print("-" * 118)
    PORT.NAV0 = NOTIONAL * 100
    nav, tr = ABL.sim_rank(P, V, SIG, None, False, CFG, 100)
    navs = pd.Series(nav, index=pd.to_datetime(cal))
    hs_s = pd.Series(PORT.NAV0 * ic / ic[0], index=pd.to_datetime(ix["date"])).reindex(navs.index).ffill()
    print(f"  {'年份':<8}{'策略':>10}{'年内回撤':>11}{'沪深300':>11}{'年内回撤':>11}")
    for y, g in navs.groupby(navs.index.year):
        r = g.iloc[-1] / g.iloc[0] - 1
        dd = float((g / g.cummax() - 1).min())
        gh = hs_s[hs_s.index.year == y]
        rh = gh.iloc[-1] / gh.iloc[0] - 1 if len(gh) else np.nan
        ddh = float((gh / gh.cummax() - 1).min()) if len(gh) else np.nan
        out["by_year"][str(y)] = {"strat": round(float(r), 4), "strat_mdd": round(dd, 4),
                                  "hs300": round(float(rh), 4)}
        print(f"  {y:<8}{r:>10.2%}{dd:>11.2%}{rh:>11.2%}{ddh:>11.2%}")

    out["elapsed_s"] = round(time.time() - t0, 1)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n结果已落盘 {OUT_JSON}（{out['elapsed_s']}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
