# -*- coding: utf-8 -*-
"""B1（月线多头过滤）双闸审计：相位扫描 + 匹配患病率随机过滤安慰剂
复用 macd_mtf_0913.py 的数据矩阵与引擎口径（exec 加载）。"""
import json
import time

import numpy as np

t0 = time.time()
g = {"__name__": "__audit__", "__file__": "D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest/macd_mtf_0913.py"}
exec(compile(open("macd_mtf_0913.py", encoding="utf-8").read(), "macd_mtf_0913.py", "exec"), g)
C, O, FIRST = g["C"], g["O"], g["FIRST"]
codes, cix, ND, NS = g["codes"], g["cix"], g["ND"], g["NS"]
MB, WG, ln_amt, atr20 = g["MB"], g["WG"], g["ln_amt"], g["atr20"]
print(f"[audit] 矩阵就绪 ({time.time()-t0:.0f}s)", flush=True)

comp = np.nan_to_num(((-ln_amt) - np.nanmean(-ln_amt, axis=0)) / np.where(np.nanstd(-ln_amt, axis=0) > 0, np.nanstd(-ln_amt, axis=0), 1), nan=0) \
     + np.nan_to_num(((-atr20) - np.nanmean(-atr20, axis=0)) / np.where(np.nanstd(-atr20, axis=0) > 0, np.nanstd(-atr20, axis=0), 1), nan=0)
comp = np.where(np.isfinite(C), comp, np.nan)


def metrics(eq):
    eq = np.asarray(eq, float)
    r = np.diff(eq) / eq[:-1]
    tot = eq[-1] / eq[0] - 1
    return {"total": round(tot * 100, 1), "ann": round(((1 + tot) ** (252 / len(eq)) - 1) * 100, 2),
            "mdd": round((eq / np.maximum.accumulate(eq) - 1).min() * 100, 1),
            "sharpe": round(float(np.mean(r) / np.std(r) * np.sqrt(252)), 3) if np.std(r) > 0 else 0}


def run2(mode, offset=0, slip=0.002, rebal=60, topk=10, rng=None):
    cash, eq, hold, n_tr, n_pos = 1e6, [], {}, 0, []
    for di in range(ND):
        for code in [c for c, h in hold.items() if h.get("sell_flag")]:
            j = cix[code]
            if np.isnan(O[di, j]) or O[di, j] <= 0:
                continue
            px_o = O[di, j] * (1 - slip)
            h = hold.pop(code); sh = h["sh"]
            cash += sh * px_o - max(sh * px_o * 0.00025, 5) - sh * px_o * 0.001
            n_tr += 1
        if di % rebal == offset and di > 250:
            sc = comp[di]
            ok = np.where(np.isfinite(sc))[0]
            if mode == "mbull":
                ok = ok[MB[di, ok]]
            elif mode == "both":
                ok = ok[MB[di, ok] & WG[di, ok]]
            elif mode == "rand":
                prob = float(MB[di, ok].mean()) if len(ok) else 0.0
                ok = ok[rng.random(len(ok)) < prob]
            ok = [j for j in ok[np.argsort(-sc[ok])][:topk]
                  if np.isfinite(O[di, j]) and O[di, j] >= 2 and di - FIRST[j] >= 180]
            n_pos.append(len(ok))
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
    m = metrics(eq)
    m["n_trades"] = n_tr
    m["avg_pos"] = round(float(np.mean(n_pos)), 1) if n_pos else 0
    return m


out = {}
# 预热日候选的月线多头患病率
di0 = 250
cand0 = np.where(np.isfinite(comp[di0]))[0]
out["_prevalence_2022ish"] = round(float(MB[di0, cand0].mean()), 3) if len(cand0) else None

# 1) 相位扫描
OFFS = (0, 10, 20, 30, 40, 50)
print("\n===== 相位扫描（rebal=60） =====", flush=True)
ph = {"base": [], "mbull": []}
for off in OFFS:
    b = run2("base", offset=off)
    m = run2("mbull", offset=off)
    ph["base"].append(b); ph["mbull"].append(m)
    print(f"  off{off:>2}: base {b['total']:>7.1f}%/{b['sharpe']:.2f} | mbull {m['total']:>7.1f}%/{m['sharpe']:.2f} (仓 {m['avg_pos']})", flush=True)
bm = np.median([x["total"] for x in ph["base"]]); mm = np.median([x["total"] for x in ph["mbull"]])
bs = np.median([x["sharpe"] for x in ph["base"]]); ms = np.median([x["sharpe"] for x in ph["mbull"]])
out["_phase"] = {"offsets": list(OFFS), "base": ph["base"], "mbull": ph["mbull"],
                 "base_med_total": round(bm, 1), "mbull_med_total": round(mm, 1),
                 "base_med_sharpe": round(bs, 3), "mbull_med_sharpe": round(ms, 3)}
print(f"  [相位汇总] base 中位 {bm:.1f}%/{bs:.2f} | mbull 中位 {mm:.1f}%/{ms:.2f}", flush=True)

# 2) 安慰剂：匹配患病率随机过滤 × 100
print("\n===== 安慰剂（匹配患病率随机过滤 × 100） =====", flush=True)
rng_master = np.random.default_rng(913)
plc = []
for it in range(100):
    r = run2("rand", offset=0, rng=np.random.default_rng(1000 + it))
    plc.append(r)
    if (it + 1) % 25 == 0:
        print(f"  {it+1}/100 ({time.time()-t0:.0f}s)", flush=True)
plc_s = np.array([x["sharpe"] for x in plc]); plc_t = np.array([x["total"] for x in plc])
target = ph["mbull"][0]
p_s = float((plc_s >= target["sharpe"]).mean()); p_t = float((plc_t >= target["total"]).mean())
out["_placebo"] = {"n": 100, "sharpe_med": round(float(np.median(plc_s)), 3), "sharpe_p95": round(float(np.quantile(plc_s, 0.95)), 3),
                   "total_med": round(float(np.median(plc_t)), 1), "total_p95": round(float(np.quantile(plc_t, 0.95)), 1),
                   "target_total": target["total"], "target_sharpe": target["sharpe"],
                   "p_sharpe": round(p_s, 3), "p_total": round(p_t, 3)}
print(f"  [安慰剂] 夏普中位 {np.median(plc_s):.3f} p95 {np.quantile(plc_s,0.95):.3f} | 收益中位 {np.median(plc_t):.1f}% p95 {np.quantile(plc_t,0.95):.1f}%", flush=True)
print(f"  [B1 目标] 夏普 {target['sharpe']} → p={p_s:.3f} | 收益 {target['total']}% → p={p_t:.3f}", flush=True)

json.dump(out, open("audit_macd_b1_0913.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print(f"\n总耗时 {time.time()-t0:.0f}s | 结果 audit_macd_b1_0913.json", flush=True)
