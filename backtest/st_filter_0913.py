# -*- coding: utf-8 -*-
"""ST/*ST/PT/退市 过滤对照回测（双卫星）
数据：data_fundamental/name_hist.csv（每日简称 2021-01-04 起，8 线程全市场）
口径：信号日简称含 ST/PT/退 → 候选剔除（与"当前名"不同，用的是历史时点名，PIT 安全）
载体A：冷门低波 lab_combo 引擎（TR 口径，基线 ≈+127.4%）
载体B：A4D r6b 引擎（ELIG_A4 & ~ST）
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

t0 = time.time()
NH = pd.read_csv(Path(__file__).resolve().parents[1] / "data_fundamental" / "name_hist.csv", dtype={"code": str})
NH["TRADE_DATE"] = pd.to_datetime(NH["TRADE_DATE"])
NH["st"] = NH["SECURITY_NAME_ABBR"].astype(str).str.contains("ST|PT|退")
NH = NH.sort_values(["code", "TRADE_DATE"])
NAME_BY = {c: g.set_index("TRADE_DATE")["st"] for c, g in NH.groupby("code")}
print(f"[name_hist] {len(NH):,} 行 / {NH['code'].nunique()} 票 ({time.time()-t0:.0f}s)", flush=True)


def st_matrix(days, codes):
    """days: DatetimeIndex/可转; codes: 6 位代码列表 → (len(days), len(codes)) bool"""
    days = pd.DatetimeIndex(days)
    M = np.zeros((len(days), len(codes)), dtype=bool)
    for j, c in enumerate(codes):
        s = NAME_BY.get(c)
        if s is None:
            continue
        M[:, j] = s.reindex(days, method="ffill").fillna(False).to_numpy()
    return M


# ================= 载体 A：冷门低波 =================
g = {"__name__": "__audit__", "__file__": "D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest/lab_combo_0913.py"}
exec(compile(open("lab_combo_0913.py", encoding="utf-8").read(), "lab_combo_0913.py", "exec"), g)
O, C, FIRST, codes, cix = g["O"], g["C"], g["FIRST"], g["codes"], g["cix"]
ND, NS, FACTORS, ALL_DAYS = g["ND"], g["NS"], g["FACTORS"], g["ALL_DAYS"]
STa = st_matrix(ALL_DAYS, codes)
print(f"[A] ST 矩阵 {STa.shape} | ST 行占比 {STa.mean():.2%} ({time.time()-t0:.0f}s)", flush=True)


def runA(st_filter, rebal=60, topk=10, slip=0.002, offset=0):
    fac_dict = {f: (1 if False else 0) for f in FACTORS}
    fac_dict["ln_amt20"] = g["best_dir"]["ln_amt20"] if False else -1
    fac_dict["atr20"] = -1
    active = ["ln_amt20", "atr20"]
    Z = {}
    for f in active:
        a = FACTORS[f] * (-1)
        m, s = np.nanmean(a, axis=0), np.nanstd(a, axis=0)
        Z[f] = (a - m) / np.where(s > 0, s, 1)
    comp = np.zeros((ND, NS))
    for f in active:
        comp += np.nan_to_num(Z[f], nan=0)
    comp = np.where(np.isfinite(C), comp, np.nan)
    cash, eq, hold, n_tr, blocked = 1e6, [], {}, 0, 0
    for di in range(ND):
        for code in [c for c, h in hold.items() if h.get("sell_flag")]:
            j = cix[code]
            if np.isnan(O[di, j]) or O[di, j] <= 0:
                continue
            px_o = O[di, j] * (1 - slip)
            h = hold.pop(code); sh = h["sh"]
            cash += sh * px_o - max(sh * px_o * 0.00025, 5) - sh * px_o * 0.001
            n_tr += 1
        if di % rebal == offset and di > 120:
            sc = comp[di]
            ok = np.where(np.isfinite(sc))[0]
            if st_filter:
                order = ok[np.argsort(-sc[ok])]
                picks_pool = [j for j in order if np.isfinite(O[di, j]) and O[di, j] >= 2 and di - FIRST[j] >= 180]
                top_before = picks_pool[:topk]
                blocked += int(STa[di, top_before].sum())
                ok = ok[~STa[di, ok]]
            ok = [j for j in ok[np.argsort(-sc[ok])][:topk]
                  if np.isfinite(O[di, j]) and O[di, j] >= 2 and di - FIRST[j] >= 180]
            tgt = {codes[j] for j in ok}
            for code, h in hold.items():
                if code not in tgt and not h.get("sell_flag"):
                    h["sell_flag"] = True
            pv = cash + sum(h["sh"] * (C[di, cix[c]] if np.isfinite(C[di, cix[c]]) else h["ep"]) for c, h in hold.items())
            for j in ok:
                code = codes[j]
                if code in hold:
                    continue
                px_o = O[di, j]; pc = C[di - 1, j]
                if not np.isfinite(px_o) or not np.isfinite(pc) or px_o >= pc * 1.097:
                    continue
                nl = int((min(pv / topk, cash) - 5) / (px_o * 100 * 1.00025))
                if nl < 1:
                    continue
                sh = nl * 100
                cost = sh * px_o * (1 + slip) + max(sh * px_o * 0.00025, 5)
                if cost > cash:
                    continue
                cash -= cost
                hold[code] = {"sh": sh, "ep": px_o, "sell_flag": False}
        pv = cash + sum(h["sh"] * (C[di, cix[c]] if np.isfinite(C[di, cix[c]]) else h["ep"]) for c, h in hold.items())
        eq.append(pv)
    eq = np.array(eq)
    r = np.diff(eq) / eq[:-1]
    tot = eq[-1] / 1e6 - 1
    return {"total": round(tot * 100, 1), "ann": round(((1 + tot) ** (252 / len(eq)) - 1) * 100, 2),
            "mdd": round((eq / np.maximum.accumulate(eq) - 1).min() * 100, 1),
            "sharpe": round(float(np.mean(r) / np.std(r) * np.sqrt(252)), 3), "n_trades": n_tr, "st_blocked": blocked}


out = {}
print("\n===== 载体A 冷门低波：不过滤 vs ST过滤 =====", flush=True)
for tag, f in (("A0_不过滤", False), ("A1_过滤ST", True)):
    r = runA(f)
    out[tag] = r
    print(f"  {tag}: {r['total']}% | 年化 {r['ann']}% | 回撤 {r['mdd']}% | 夏普 {r['sharpe']} | {r['n_trades']}笔 | ST剔除 {r['st_blocked']} 只次", flush=True)
# 相位对照（3 相位）
ph = {"base": [], "st": []}
for off in (10, 30, 50):
    ph["base"].append(runA(False, offset=off)["total"])
    ph["st"].append(runA(True, offset=off)["total"])
out["_phase_A"] = ph
print(f"  [相位] base {ph['base']} | st {ph['st']}", flush=True)

# ================= 载体 B：A4D r6b =================
gb = {"__file__": "D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest/factorlab_0913/factor_blend_r6b_0913.py"}
exec(compile(open("factorlab_0913/factor_blend_r6b_0913.py", encoding="utf-8").read().split("if __name__")[0], "r6b", "exec"), gb)
cal, bcodes, ELIG, COMP, run_engine = gb["cal"], gb["codes"], gb["ELIG_A4"], gb["COMP_A4"], gb["run_engine"]
STb = st_matrix(pd.to_datetime(cal), bcodes)
print(f"\n[B] ST 矩阵 {STb.shape} | 行占比 {STb.mean():.2%} ({time.time()-t0:.0f}s)", flush=True)
ELIG_ST = ELIG & ~STb

print("===== 载体B A4D：不过滤 vs ST过滤 =====", flush=True)
for tag, elig in (("B0_不过滤", ELIG), ("B1_过滤ST", ELIG_ST)):
    m = run_engine(COMP, elig, 20, 0)
    out[tag] = {k: (round(v, 4) if isinstance(v, (int, float)) else v) for k, v in m.items() if k in ("total", "ann", "sharpe", "mdd", "n_trades", "win")}
    print(f"  {tag}: 总 {m['total']*100:.1f}% | 年化 {m['ann']*100:.2f}% | 夏普 {m['sharpe']:.3f} | 回撤 {m['mdd']*100:.1f}%", flush=True)
phb = {"base": [], "st": []}
for off in (5, 10, 15):
    phb["base"].append(run_engine(COMP, ELIG, 20, off)["sharpe"])
    phb["st"].append(run_engine(COMP, ELIG_ST, 20, off)["sharpe"])
out["_phase_B"] = phb
print(f"  [相位夏普] base {phb['base']} | st {phb['st']}", flush=True)

json.dump(out, open("st_filter_0913.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print(f"\n总耗时 {time.time()-t0:.0f}s | st_filter_0913.json", flush=True)
