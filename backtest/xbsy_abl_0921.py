# -*- coding: utf-8 -*-
"""小步碎阳 · 共振/缩量臂的排序键与仓位回收消融（XBSY-ABL-0921）
================================================================================
为什么做这一步
--------------------------------------------------------------------------------
上一轮（XBSY-RES-0921）最可疑的一条：缩量大跌甲臂「无限资金 +19.82% / 夏普 0.896」
vs「20 仓 −25.16% / 夏普 −0.888」—— 相差 45pp，符号翻转。两个候选解释：

  假设 ① 容量：平均并发需求 7,775 仓，20 仓只填 0.26% → 容量解释一部分
  假设 ② **排序键逆向选择**：20 仓按「量比升序」选票 → 优先挑「缩量最极端」的 = 最没人要的票
  假设 ③ **仓位不回收**：cap=250（持有到爆量阴线才走）→ 20 个仓位被最早那批票**长期占满**，
           组合退化成「开局随机 20 只 + 长期不动」。实测上一轮 B 臂 20 仓 E1 只有 **152 笔**，
           而窗口内信号 **81,648 个** → **填充率 0.19%** ← 这个数量级才是主因嫌疑

预注册（看数字之前固定）
--------------------------------------------------------------------------------
因子 A（排序键，方向固定）：量比升序 / 量比降序 / 成交额(近似)升序 / 随机(种子 20260921) / 代码序
因子 B（仓位回收 = 出场上限 cap）：250（上一轮设定）/ 60 / 20
入场臂：B_缩量大跌甲 / C_越跌越缩乙 / D_共振后10日内缩量（上一轮样本闸 PASS 的三条）
资金口径：固定 **20 仓**（每仓 = NAV0/20 = 8,500 元）；成本同前（滑点 20bp/边 + 佣金 2.5bp/最低 5 元）
新增诊断列：**填充率**（成交笔数 ÷ 窗口内信号数）与 **持仓中位** —— 这是区分假设②③的关键量

判据：若「随机 / 代码序」显著优于「量比升序」→ 假设②成立（排序键选错）；
      若所有排序键都差且填充率 < 1% → 假设③成立（仓位不回收，形态未被真正测试）。
窗口 2024-10-16 → 2026-09-18。对照沪深300（上轮实测：年化 +9.06% / 夏普 0.602 / 回撤 −13.42%）。

用法：cd quant-weight-system && python backtest/xbsy_abl_0921.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

import xbsy_0921 as X                                       # noqa: E402
import xbsy_exit_0921 as E                                  # noqa: E402
import xbsy_port_0921 as PORT                               # noqa: E402
import xbsy_res_0921 as RES                                 # noqa: E402

OUT_JSON = str(HERE / "xbsy_abl_0921.json")
MAX_POS = 20
RANKS = [("量比升序", "vr", False), ("量比降序", "vr", True),
         ("成交额升序", "amt", False), ("随机", "rand", False), ("代码序", "code", False)]
CAPS = [250, 60, 20]


def sim_rank(P, V, SIG, keymat, desc, cfg, max_pos, seed=20260921):
    """PORT.simulate 的排序键泛化版：keymat 给排序值，desc 控制方向（NaN 排末尾）。"""
    O = P["open"].astype(np.float64)
    C = P["close"].astype(np.float64)
    M = P["mask"]
    T, N = C.shape
    NX = E.exit_day_matrix(O, C, V, cfg)

    cand = {}
    for t in range(T - 1):
        idx = np.nonzero(SIG[t] & M[t])[0]
        if idx.size:
            cand[t] = idx
    cash = PORT.NAV0
    pos = {}
    nav_hist = np.full(T, np.nan)
    trades = []
    rng = np.random.default_rng(seed)

    for t in range(T):
        for c in [x for x, p in pos.items() if p["sell_day"] == t and p["sell_at"] == "open"]:
            p = pos.pop(c)
            px = O[t, c] if np.isfinite(O[t, c]) and O[t, c] > 0 else C[t, c]
            if not (np.isfinite(px) and px > 0):
                continue
            sp = px * (1 - PORT.SLIP)
            amt = sp * p["shares"]
            cash += amt - max(amt * PORT.COMM, PORT.MIN_COMM)
            trades.append({"in": p["date"], "out": t, "ret":sp / p["px"] - 1 - 2 * PORT.COMM})
        idx = cand.get(t - 1)
        if idx is not None:
            free = max_pos - len(pos)
            if free > 0:
                av = np.array([i for i in idx if i not in pos
                               and np.isfinite(O[t, i]) and O[t, i] > 0])
                if av.size:
                    if keymat is None:
                        order = av
                    else:
                        k = keymat[t - 1, av]
                        k = np.where(np.isfinite(k), k, np.inf if not desc else -np.inf)
                        order = av[np.argsort(-k if desc else k, kind="stable")]
                    navp = nav_hist[t - 1] if np.isfinite(nav_hist[t - 1]) else PORT.NAV0
                    for i in order[:free]:
                        budget = min(cash, navp / max_pos)
                        px = O[t, i] * (1 + PORT.SLIP)
                        sh = int(budget // (px * 100)) * 100
                        if sh < 100:
                            continue
                        amt = sh * px
                        fee = max(amt * PORT.COMM, PORT.MIN_COMM)
                        if amt + fee > cash:
                            continue
                        cash -= amt + fee
                        sd = int(NX[t, i]); capd = min(t + cfg["cap"], T - 1)
                        pos[i] = dict(shares=sh, px=px, date=t,
                                      sell_day=sd if sd <= capd else capd,
                                      sell_at="open" if sd <= capd else "close")
        for c in [x for x, p in pos.items() if p["sell_day"] == t and p["sell_at"] == "close"]:
            p = pos.pop(c)
            px = C[t, c]
            if not (np.isfinite(px) and px > 0):
                continue
            sp = px * (1 - PORT.SLIP)
            amt = sp * p["shares"]
            cash += amt - max(amt * PORT.COMM, PORT.MIN_COMM)
            trades.append({"in": p["date"], "out": t, "ret":sp / p["px"] - 1 - 2 * PORT.COMM})
        mv = 0.0
        for c, p in pos.items():
            px = C[t, c]
            if np.isfinite(px):
                mv += p["shares"] * px
        nav_hist[t] = cash + mv
    return nav_hist, trades


def main():
    t0 = time.time()
    print("=" * 118)
    print("排序键 × 仓位回收 消融（XBSY-ABL-0921）· 20 仓 · 窗口 2024-10-16 → 2026-09-18")
    print("=" * 118)
    idxall = __import__("pandas").read_csv(BASE / "index_000300.csv", dtype={"date": str})
    cal = [d for d in idxall["date"] if d >= RES.PANEL_FROM]
    codes = RES.universe()
    nm = RES.names_map()
    P, V, miss = RES.build_panel(codes, cal)
    T, N = P["close"].shape
    st_cols = [j for j, c in enumerate(codes)
               if not c[2:].startswith(("51", "56", "58", "15", "16"))
               and nm.get(c[2:]) and "ST" in nm[c[2:]].upper()]
    if st_cols:
        P["mask"][:, st_cols] = False
    O = P["open"].astype(np.float64)
    C = P["close"].astype(np.float64)

    ipct = np.full(T, np.nan)
    ic = idxall[idxall["date"] >= RES.PANEL_FROM]["close"].to_numpy(float)
    io = idxall[idxall["date"] >= RES.PANEL_FROM]["open"].to_numpy(float)
    iv = idxall[idxall["date"] >= RES.PANEL_FROM]["volume"].to_numpy(float)
    ipct[1:] = (ic[1:] / ic[:-1] - 1) * 100
    ivr = iv / __import__("pandas").Series(iv).rolling(20).mean().to_numpy()
    i_boom = (ipct >= 1.0) & (ic > io) & (ivr >= 1.2)

    pct = np.full((T, N), np.nan); pct[1:] = (C[1:] / C[:-1] - 1) * 100
    vma = X.roll_mean(V, 20)
    with np.errstate(all="ignore"):
        vr = V / vma
    yang = C > O
    boom_day = np.repeat(i_boom[:, None], N, axis=1)
    A = (boom_day & yang & (pct >= np.repeat(ipct[:, None], N, axis=1)) & (vr >= 1.0)
         & np.isfinite(pct) & np.isfinite(vr))
    B = (pct <= -3.0) & (vr <= 0.8) & np.isfinite(vr)
    c1 = np.vstack([np.full((1, N), np.nan), C[:-1]]); c2 = np.vstack([np.full((2, N), np.nan), C[:-2]])
    c3 = np.vstack([np.full((3, N), np.nan), C[:-3]])
    v1 = np.vstack([np.full((1, N), np.nan), V[:-1]]); v2 = np.vstack([np.full((2, N), np.nan), V[:-2]])
    Cm = (C < c1) & (c1 < c2) & (c2 < c3) & (V < v1) & (v1 < v2) & np.isfinite(V)
    Aprev = np.vstack([np.zeros((1, N), dtype=bool), A.astype(bool)[:-1]])
    D10 = B.astype(bool) & (X.roll_sum(Aprev.astype(float), 10) > 0)

    arms = {"B_缩量大跌甲": B.astype(bool), "C_越跌越缩乙": Cm.astype(bool), "D_共振后10日": D10}
    s_i = cal.index(RES.START)
    for k in arms:
        arms[k][:s_i] = False

    print("\n① 窗口内信号数（样本闸全部 PASS，上轮已验）")
    for k, S in arms.items():
        per = S.sum(axis=1); act = int((per > 0).sum())
        print(f"  {k:<14} 信号 {int(S.sum()):>7,}  活跃日 {act:>4}  日中位 {np.median(per[per>0]):>6.1f}")

    rand_mat = np.random.default_rng(20260921).random((T, N))
    keymats = {"vr": vr,
               "amt": np.where(np.isfinite(C) & np.isfinite(V), C * V, np.nan),
               "rand": rand_mat, "code": None}

    out = {"span": [RES.START, "2026-09-18"], "hs300": {"cagr": 0.0906, "sharpe": 0.602, "mdd": -0.1342},
           "runs": {}}
    print("\n" + "-" * 118)
    print("② 20 仓 · 排序键 × 出场上限（填充率 = 成交笔数 ÷ 窗口内信号数）")
    print("-" * 118)
    hdr = (f"  {'入场臂':<14}{'排序键':<10}{'cap':>4}{'年化':>9}{'夏普':>8}{'最大回撤':>10}"
           f"{'按笔胜率':>9}{'笔数':>6}{'填充率':>9}{'持仓中位':>9}{'末期净值':>10}")
    print(hdr); print("  " + "-" * (len(hdr) - 2))
    for ak, S in arms.items():
        nsig = int(S.sum())
        for rname, rkey, desc in RANKS:
            for cap in CAPS:
                cfg = dict(boom="q2", lag=1, ma5=False, ma10=False, cap=cap)
                nav, tr = sim_rank(P, V, S, keymats[rkey], desc, cfg, MAX_POS)
                m = PORT.metrics(nav, cal, tr, f"{ak}|{rname}|{cap}")
                holds = np.array([t["out"] - t["in"] for t in tr]) if tr else np.array([])
                fill = (len(tr) / nsig) if nsig else 0.0
                rec = {**m, "fill_rate": round(fill, 5),
                       "hold_median": int(np.median(holds)) if holds.size else None}
                out["runs"][f"{ak}|{rname}|cap{cap}"] = rec
                print(f"  {ak:<14}{rname:<10}{cap:>4}{m['cagr']:>9.2%}{m['sharpe']:>8.3f}"
                      f"{m['max_drawdown']:>10.2%}{(m['win_rate_per_trade'] or 0):>9.1%}"
                      f"{len(tr):>6}{fill:>9.3%}"
                      f"{(rec['hold_median'] if rec['hold_median'] is not None else -1):>9}"
                      f"{m['final_nav']:>10,.0f}")
        print()

    out["elapsed_s"] = round(time.time() - t0, 1)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"结果已落盘 {OUT_JSON}（{out['elapsed_s']}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
