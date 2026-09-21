# -*- coding: utf-8 -*-
"""D 臂扩窗复验（XBSY-RES2-0921 · 用户 2026-09-21 批准）
================================================================================
复验对象（XBSY-ABL-0921 唯一对排序键稳健的臂）
--------------------------------------------------------------------------------
D 臂 = 指数（沪深300）放量中阳线（涨幅≥1% 且 收>开 且 量比≥1.2）**标记** →
       其后 N 个交易日内出现「缩量大跌」（跌幅 ≤ −3% 且 量比 ≤ 0.8）→ **T+1 开盘买**
出场 = 爆量≥2×MA(V,20) + 次日阴线 → 次日开盘卖（cap 250 / 60）；对照 = 固定 20 日

待检验命题（预注册）
--------------------------------------------------------------------------------
**P1 键间稳健性**：在 1.9 年窗内 D 臂的键间标准差仅 2.03%~3.35%（B/C 臂为 15.68%~19.74%）。
   扩窗到 2016 起后，若 D 臂键间 sd **仍 ≤5pp**，则「收益来自入场条件而非选票运气」成立；
   若 sd 升到与 B/C 同量级（>10pp），则 1.9 年窗结论是样本偏差。
**P2 显著性**：长窗下按日收益的 t = 夏普 × √年数。夏普 0.4 / 10.7 年 → t≈1.3（不显著）；
   须报出 t 并与沪深300 同期对比，不以"年化高"下结论。
**P3 逐年**：单相位漂亮读数须过逐年拆解；报每年收益与胜率，看是否靠个别年份。
**P4 成本档**：20bp（基准）/ 50bp（压力），看是否"成本脆弱"。
**P5 样本闸**：扩窗后信号数/活跃日/笔数须重报，并以 n≥100 ∧ 活跃日≥30 闸门判定。

窗口：2016-01-04 → 2026-09-18（约 10.7 年）；面板自 2015-01-01 预热；剔 ST + 上市<60 交易日。
宇宙：主板 + 创业板 + 科创板 + 全部场内 ETF（剔北交所）。
资金口径：20 仓（每仓 = NAV0/20 = 8,500 元）× 5 排序键；另跑无限资金（全吃·等权·无上限）。

用法：cd quant-weight-system && python backtest/xbsy_res2_0921.py
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
import xbsy_exit_0921 as E                                  # noqa: E402
import xbsy_port_0921 as PORT                               # noqa: E402
import xbsy_res_0921 as RES                                 # noqa: E402
import xbsy_abl_0921 as ABL                                 # noqa: E402

OUT_JSON = str(HERE / "xbsy_res2_0921.json")
START = "2016-01-04"
MAX_POS = 20
RANKS = [("量比升序", "vr", False), ("量比降序", "vr", True),
         ("成交额升序", "amt", False), ("随机", "rand", False), ("代码序", "code", False)]


def build():
    RES.PANEL_FROM = "2015-01-01"
    idxall = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
    cal = [d for d in idxall["date"] if d >= RES.PANEL_FROM and d <= "2026-09-18"]
    codes = RES.universe()
    nm = RES.names_map()
    P, V, miss = RES.build_panel(codes, cal)
    st_cols = [j for j, c in enumerate(codes)
               if not c[2:].startswith(("51", "56", "58", "15", "16"))
               and nm.get(c[2:]) and "ST" in nm[c[2:]].upper()]
    if st_cols:
        P["mask"][:, st_cols] = False
    N = len(codes)
    etf_cols = [j for j, c in enumerate(codes) if c[2:].startswith(("51", "56", "58", "15", "16"))]
    print(f"面板 {len(cal)} 日 × {N} 只（{cal[0]} → {cal[-1]}）| 缺 {miss} | ST 剔 {len(st_cols)} | ETF {len(etf_cols)}")
    return idxall, cal, codes, P, V


def main():
    t0 = time.time()
    print("=" * 118)
    print("D 臂扩窗复验（XBSY-RES2-0921）· 2016-01-04 → 2026-09-18")
    print("=" * 118)
    idxall, cal, codes, P, V = build()
    T, N = P["close"].shape
    O = P["open"].astype(np.float64)
    C = P["close"].astype(np.float64)

    ix = idxall[(idxall["date"] >= RES.PANEL_FROM) & (idxall["date"] <= "2026-09-18")].reset_index(drop=True)
    assert list(ix["date"]) == list(cal)
    ic = ix["close"].to_numpy(float); io = ix["open"].to_numpy(float); iv = ix["volume"].to_numpy(float)
    ipct = np.full(T, np.nan); ipct[1:] = (ic[1:] / ic[:-1] - 1) * 100
    ivr = iv / pd.Series(iv).rolling(20).mean().to_numpy()
    i_boom = (ipct >= 1.0) & (ic > io) & (ivr >= 1.2)
    print(f"指数放量中阳线 全窗 {int(i_boom.sum())} 次")

    pct = np.full((T, N), np.nan, dtype=np.float32); pct[1:] = (C[1:] / C[:-1] - 1) * 100
    vma = X.roll_mean(V, 20)
    with np.errstate(all="ignore"):
        vr = V / vma
    yang = C > O
    A = np.repeat(i_boom[:, None], N, axis=1) & yang & (pct >= np.repeat(ipct[:, None], N, axis=1)) \
        & (vr >= 1.0) & np.isfinite(pct) & np.isfinite(vr)
    B = (pct <= -3.0) & (vr <= 0.8) & np.isfinite(vr)
    c1 = np.vstack([np.full((1, N), np.nan, dtype=np.float32), C[:-1].astype(np.float32)])
    c2 = np.vstack([np.full((2, N), np.nan, dtype=np.float32), C[:-2].astype(np.float32)])
    c3 = np.vstack([np.full((3, N), np.nan, dtype=np.float32), C[:-3].astype(np.float32)])
    v1 = np.vstack([np.full((1, N), np.nan, dtype=np.float32), V[:-1]])
    v2 = np.vstack([np.full((2, N), np.nan, dtype=np.float32), V[:-2]])
    Cm = (C.astype(np.float32) < c1) & (c1 < c2) & (c2 < c3) & (V < v1) & (v1 < v2) & np.isfinite(V)
    Aprev = np.vstack([np.zeros((1, N), dtype=bool), A.astype(bool)[:-1]])
    arms = {"D5": B.astype(bool) & (X.roll_sum(Aprev.astype(float), 5) > 0),
            "D10": B.astype(bool) & (X.roll_sum(Aprev.astype(float), 10) > 0),
            "D20": B.astype(bool) & (X.roll_sum(Aprev.astype(float), 20) > 0),
            "B缩量甲(对照)": B.astype(bool), "C越跌越缩(对照)": Cm.astype(bool)}
    s_i = cal.index(START)
    for k in arms:
        arms[k][:s_i] = False

    out = {"span": [START, "2026-09-18"], "panel": [cal[0], cal[-1]], "sample": {}, "runs": {}, "by_year": {}}
    print("\n① 样本闸（长窗）")
    for k, S in arms.items():
        per = S.sum(axis=1); act = int((per > 0).sum())
        gate = "PASS" if int(S.sum()) >= 100 and act >= 30 else "不可判定"
        out["sample"][k] = {"n_sig": int(S.sum()), "days_active": act, "gate": gate,
                            "uniq": int(S.any(axis=0).sum())}
        print(f"  {k:<16} 信号 {int(S.sum()):>8,}  活跃日 {act:>5}  标的 {int(S.any(axis=0).sum()):>5}  样本闸 {gate}")

    hs = ic[s_i:]; hsd = [str(x) for x in ix["date"][s_i:]]
    bm = PORT.metrics(PORT.NAV0 * hs / hs[0], hsd, [], "沪深300")
    bm["t_daily"] = round(bm["sharpe"] * np.sqrt(bm["years"]), 2)
    out["hs300"] = bm
    print(f"\n沪深300 同窗：年化 {bm['cagr']:+.2%}  夏普 {bm['sharpe']:.3f}  回撤 {bm['max_drawdown']:.2%}  "
          f"t(按日,={bm['sharpe']}×√{bm['years']:.1f}) {bm['t_daily']:.2f}")

    rand_mat = np.random.default_rng(20260921).random((T, N)).astype(np.float32)
    keymats = {"vr": vr, "amt": np.where(np.isfinite(C) & np.isfinite(V), C * V, np.nan),
               "rand": rand_mat, "code": None}

    print("\n" + "-" * 118)
    print("② P1 键间稳健性复验（20 仓 × 5 排序键 × cap250）—— 命题：D 臂 sd 应 ≤5pp")
    print("-" * 118)
    hdr = (f"  {'臂':<16}{'键':<10}{'年化':>9}{'夏普':>8}{'最大回撤':>10}{'按笔胜率':>9}"
           f"{'笔数':>7}{'填充率':>9}{'t(按日)':>9}{'末期净值':>11}")
    print(hdr); print("  " + "-" * (len(hdr) - 2))
    cells = {}
    for ak in ("D5", "D10", "D20", "B缩量甲(对照)", "C越跌越缩(对照)"):
        S = arms[ak]
        vals = []
        for rname, rkey, desc in RANKS:
            cfg = dict(boom="q2", lag=1, ma5=False, ma10=False, cap=250)
            nav, tr = ABL.sim_rank(P, V, S, keymats[rkey], desc, cfg, MAX_POS)
            m = PORT.metrics(nav, cal, tr, f"{ak}|{rname}")
            td = round(m["sharpe"] * np.sqrt(m["years"]), 2)
            fill = len(tr) / max(int(S.sum()), 1)
            out["runs"][f"{ak}|{rname}|cap250"] = {**m, "fill_rate": round(fill, 5), "t_daily": td}
            vals.append(m["cagr"])
            print(f"  {ak:<16}{rname:<10}{m['cagr']:>9.2%}{m['sharpe']:>8.3f}{m['max_drawdown']:>10.2%}"
                  f"{(m['win_rate_per_trade'] or 0):>9.1%}{len(tr):>7}{fill:>9.3%}{td:>9.2f}{m['final_nav']:>11,.0f}")
        v = np.array(vals)
        sd = float(v.std(ddof=1))
        cells[ak] = {"sd": round(sd, 4), "range": round(float(v.max() - v.min()), 4)}
        print(f"  → {ak:<14} 键间标准差 {sd:.2%}  极差 {v.max()-v.min():.2%}\n")

    print("-" * 118)
    print("③ P2/P4 D 臂无限资金（全吃·等权·无上限）· 聚类 t 用「夏普×√年数」诚实折算 · 成本双档")
    print("-" * 118)
    print(hdr.replace("填充率", "平均并发").replace("笔数", "笔数"))
    print("  " + "-" * (len(hdr) - 2))
    for ak in ("D5", "D10", "D20"):
        S = arms[ak]
        for slip, tag in ((PORT.SLIP, "20bp"), (0.0050, "50bp")):
            cfg = dict(boom="q2", lag=1, ma5=False, ma10=False, cap=250)
            nav, _, meta = PORT.simulate_unlimited(P, V, S, cfg, slip=slip)
            m = PORT.metrics(nav, cal, [], f"{ak}|{tag}")
            td = round(m["sharpe"] * np.sqrt(m["years"]), 2)
            out["runs"][f"无限资金|{ak}|{tag}"] = {**m, "avg_concurrency": meta["avg_concurrency"], "t_daily": td}
            print(f"  {ak:<16}{('无限·'+tag):<10}{m['cagr']:>9.2%}{m['sharpe']:>8.3f}{m['max_drawdown']:>10.2%}"
                  f"{(meta['win_rate_per_trade'] or 0):>9.1%}{meta['n_signal_events']:>7}"
                  f"{meta['avg_concurrency']:>9,.0f}{td:>9.2f}{m['final_nav']:>11,.0f}")

    print("\n" + "-" * 118)
    print("④ P3 逐年拆解（D10 · 20仓 · 量比降序 —— sd 最小档；含沪深300 对照）")
    print("-" * 118)
    cfg = dict(boom="q2", lag=1, ma5=False, ma10=False, cap=250)
    nav, tr = ABL.sim_rank(P, V, arms["D10"], keymats["vr"], True, cfg, MAX_POS)
    navs = pd.Series(nav, index=pd.to_datetime(cal))
    hs_s = pd.Series(PORT.NAV0 * hs / hs[0], index=pd.to_datetime(hsd))
    print(f"  {'年份':<8}{'D10 年收益':>12}{'D10 年内回撤':>13}{'沪深300 年收益':>15}{'年内回撤':>11}")
    for y, g in navs.groupby(navs.index.year):
        r = g.iloc[-1] / g.iloc[0] - 1
        dd = float((g / g.cummax() - 1).min())
        gh = hs_s[hs_s.index.year == y]
        rh = gh.iloc[-1] / gh.iloc[0] - 1 if len(gh) else np.nan
        ddh = float((gh / gh.cummax() - 1).min()) if len(gh) else np.nan
        out["by_year"][str(y)] = {"D10": round(float(r), 4), "D10_mdd": round(dd, 4),
                                 "hs300": round(float(rh), 4), "hs300_mdd": round(ddh, 4)}
        print(f"  {y:<8}{r:>12.2%}{dd:>13.2%}{rh:>15.2%}{ddh:>11.2%}")

    out["elapsed_s"] = round(time.time() - t0, 1)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n结果已落盘 {OUT_JSON}（{out['elapsed_s']}s）")
    print("键间标准差汇总:", {k: v["sd"] for k, v in cells.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
