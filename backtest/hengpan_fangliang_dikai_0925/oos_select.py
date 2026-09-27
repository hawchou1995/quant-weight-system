# -*- coding: utf-8 -*-
"""oos_select.py — 复合打分的「额外收益」在样本外是否还在（2026-09-27）

用 6.3M 条全资格池宽口径重放（_p_all_trades.jsonl）流式筛出「真实低开 −3%~−1%」的池，
再从面板取 AMT20/VOLBR/RET20 三个键，比较：
  · 池均值（不选股）
  · 随机 10 只
  · 复合分前 10（现口径）
  · 单键前 10（amt_lo / volbr_lo / ret20_lo）
分别在 train 2018-2021 与 val 2022-2026 上，看**额外收益是否在 val 保留**。
"""
import json, os, pathlib
import numpy as np, pandas as pd
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
C = pathlib.Path(os.environ["PI_SCRATCH_DIR"]) / "x1cache"
z = np.load(C / "panel_oos.npz", allow_pickle=True)
cal = [str(x) for x in z["cal"]]; syms = [str(x) for x in z["syms"]]
O, Cl, V, A = z["O"], z["C"], z["V"], z["A"]
lut = {d: i for i, d in enumerate(cal)}; jof = {s: j for j, s in enumerate(syms)}
VALID = (Cl > 0) & np.isfinite(Cl) & (O > 0)
Av = np.where(VALID, A, np.nan); Vv = np.where(VALID, V, np.nan)
AMT20 = pd.DataFrame(Av).rolling(20, min_periods=10).mean().to_numpy()
VMA = pd.DataFrame(Vv).rolling(20, min_periods=10).mean().to_numpy()
VMAp = np.full_like(VMA, np.nan); VMAp[1:] = VMA[:-1]
VOLBR = V / np.where(VMAp > 0, VMAp, np.nan)
Cv = np.where(VALID, Cl, np.nan)
RET20 = np.full(Cl.shape, np.nan); RET20[20:] = Cv[20:] / Cv[:-20] - 1.0

f = C / "_p_all_trades.jsonl"
print("流式扫描 %s（%.1f GB）…" % (f.name, f.stat().st_size / 1e9), flush=True)
pool = []
n = 0
with f.open(encoding="utf-8") as fh:
    for line in fh:
        n += 1
        if '"gap_pct"' not in line: continue
        try: r = json.loads(line)
        except Exception: continue
        g = r.get("gap_pct")
        if g is None or not (-3.0 <= g <= -1.0): continue
        if r["entry_date"] < "2018-01-01": continue
        pool.append((r["signal_date"], r["sym"], r["ret_pct"]))
print("  扫描 %d 行 → 带内样本 %d 笔" % (n, len(pool)), flush=True)

def zs(x):
    x = np.asarray(x, float); mu = np.nanmean(x); sd = np.nanstd(x)
    return (x - mu) / sd if np.isfinite(sd) and sd > 0 else np.zeros_like(x)

byday = {}
for d, s, r in pool:
    byday.setdefault(d, []).append((s, r))
print("  覆盖信号日 %d 天" % len(byday), flush=True)

def keys(d, ss):
    i = lut[d]
    a = np.array([AMT20[i, jof[s]] for s in ss]); v = np.array([VOLBR[i, jof[s]] for s in ss])
    rr = np.array([RET20[i, jof[s]] for s in ss])
    return a, v, rr

rng = np.random.default_rng(20260927)
RES = {}
for win, lo, hi in (("train 2018-2021", "2018-01-01", "2021-12-31"), ("val 2022-2026", "2022-01-01", "2099-01-01")):
    acc = {"池均值": [], "随机10": [], "复合分前10": [], "amt_lo前10": [], "volbr_lo前10": [], "ret20_lo前10": []}
    nd = 0
    for d, rows in byday.items():
        if not (lo <= d <= hi): continue
        ss = [s for s, _ in rows]
        if len(ss) < 10: continue
        rr = np.array([r for _, r in rows], float)
        a, v, rt = keys(d, ss)
        if not (np.isfinite(a).all() and np.isfinite(v).all() and np.isfinite(rt).all()): continue
        nd += 1
        comp = zs(-np.log(a)) + zs(-np.log(v)) + zs(-rt)
        acc["池均值"].append(rr.mean())
        order = rng.permutation(len(ss))[:10]
        acc["随机10"].append(rr[order].mean())
        acc["复合分前10"].append(rr[np.argsort(-comp)[:10]].mean())
        for lab, key in (("amt_lo前10", -np.log(a)), ("volbr_lo前10", -np.log(v)), ("ret20_lo前10", -rt)):
            acc[lab].append(rr[np.argsort(-key)[:10]].mean())
    print("\n=== %s（%d 天 / 每日 ≥10 只）===" % (win, nd))
    RES[win] = {}
    print("  %-14s 日均净收益   年化(近似, 50%%占用×243日)" % "口径")
    for k, v in acc.items():
        m = float(np.mean(v)); RES[win][k] = round(m, 4)
        print("  %-14s %+8.4f%%     %+8.1f%%" % (k, m, ((1 + m * 0.5 / 100) ** 243 - 1) * 100))
    if "池均值" in acc and acc["池均值"]:
        print("  → 选股额外收益：复合分 %+0.4f pp ｜ amt_lo %+0.4f pp" %
              (np.mean(acc["复合分前10"]) - np.mean(acc["随机10"]),
               np.mean(acc["amt_lo前10"]) - np.mean(acc["随机10"])))
json.dump(RES, open(os.path.join(os.environ["PI_SCRATCH_DIR"], "oos_select.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\n[out] oos_select.json")
