# -*- coding: utf-8 -*-
"""因子挖掘实验室 L2/L2b 可信族 · 主板独立复现（2021-01-04 起）
来源：用户提供的另一会话结论（可信冠军 L2::ln_amt20+intraday20+pvc20+ret20+vr5_20 @10/60d
声明 Sharpe 1.760/CAGR 46.78%/回撤 −14.88%；十闸 0/90 通过、G2 相位不达标）。
口径假设（无源码，按标准语义移植，声明于报告）：
  ln_amt20=ln(20日均成交额)｜atr20=20日均真实波幅｜amp20=20日均振幅((H-L)/PC)｜
  vol20=20日均成交量｜vol_ratio=量比(V/VMA5)｜vr5_20=VMA5/VMA20｜vr20_60=VMA20/VMA60｜
  intraday20=20日均日内收益(C/O-1)｜pvc20=20日量价相关(C,V)｜apvc20=20日额价相关(A,C)｜
  ret20/ret60=20/60日动量。
流程：单因子双向定标（22 臂）→ 组合合成（单因子最优方向）→ 12 组配置网格 → 相位扫描。
宇宙：data_full 主板全池（含退市），成本=佣金 2.5bp+印税 10bp+滑点 20bps（声明口径另测 0 滑点）。"""
import json
import time
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
START = pd.Timestamp("2021-01-04")
t0 = time.time()

# ---- 数据矩阵 ----
codes, px_rows = [], []
mat = {}
for f in sorted((BASE / "data_full").glob("*.csv")):
    c = f.stem
    if not (c.startswith("sh60") or c.startswith("sz00")):
        continue
    d = pd.read_csv(f, usecols=["date", "open", "high", "low", "close", "volume", "amount"], dtype={"date": str})
    d["date"] = pd.to_datetime(d["date"])
    d = d[d["date"] >= START].sort_values("date")
    if len(d) < 120:
        continue
    code = c[2:]
    codes.append(code)
    mat[code] = d.set_index("date")
codes = sorted(codes)
ALL_DAYS = sorted(set().union(*[set(m.index) for m in mat.values()]))
day_ix = {d: i for i, d in enumerate(ALL_DAYS)}
ND, NS = len(ALL_DAYS), len(codes)
cix = {c: i for i, c in enumerate(codes)}
O = np.full((ND, NS), np.nan); H = np.full((ND, NS), np.nan)
L = np.full((ND, NS), np.nan); C = np.full((ND, NS), np.nan)
V = np.full((ND, NS), np.nan); A = np.full((ND, NS), np.nan)
FIRST = np.full(NS, -1, dtype=int)
for code in codes:
    m = mat[code]; j = cix[code]
    ii = m.index.map(day_ix)
    O[ii, j] = m["open"].to_numpy(); H[ii, j] = m["high"].to_numpy()
    L[ii, j] = m["low"].to_numpy(); C[ii, j] = m["close"].to_numpy()
    V[ii, j] = m["volume"].to_numpy(); A[ii, j] = m["amount"].to_numpy()
    FIRST[j] = ii.min()
print(f"[load] {NS} 票 {ND} 日 ({time.time()-t0:.0f}s)", flush=True)

# ---- 因子计算（11 个）----
def roll_mean(x, n):
    return pd.DataFrame(x).rolling(n, min_periods=n).mean().to_numpy()

PC = np.full((ND, NS), np.nan); PC[1:] = C[:-1]
TR = np.nanmax(np.stack([H - L, np.abs(H - PC), np.abs(L - PC)]), axis=0)
ln_amt20 = np.log(np.maximum(roll_mean(A, 20), 1e3))
atr20 = roll_mean(TR, 20) / C
amp20 = roll_mean((H - L) / PC, 20)
vol20 = roll_mean(V, 20)
vma5 = roll_mean(V, 5); vma20 = roll_mean(V, 20); vma60 = roll_mean(V, 60)
vol_ratio = V / vma5
vr5_20 = vma5 / vma20
vr20_60 = vma20 / vma60
intraday20 = roll_mean(C / O - 1, 20)
def roll_corr(a, b, n):
    out = np.full_like(a, np.nan)
    da, db = pd.DataFrame(a), pd.DataFrame(b)
    out = da.rolling(n, min_periods=n).corr(db).to_numpy()
    return out
pvc20 = roll_corr(C, V, 20)
apvc20 = roll_corr(A, C, 20)
ret20 = np.full((ND, NS), np.nan); ret20[20:] = C[20:] / C[:-20] - 1
ret60 = np.full((ND, NS), np.nan); ret60[60:] = C[60:] / C[:-60] - 1

FACTORS = {"ln_amt20": ln_amt20, "atr20": atr20, "amp20": amp20, "vol20": vol20,
           "vol_ratio": vol_ratio, "vr5_20": vr5_20, "vr20_60": vr20_60,
           "intraday20": intraday20, "pvc20": pvc20, "apvc20": apvc20,
           "ret20": ret20, "ret60": ret60}
print(f"[factors] 12 个计算完成 ({time.time()-t0:.0f}s)", flush=True)


def run(fac_dict, rebal=60, topk=10, slip=0.002, offset=0):
    """fac_dict: {factor_name: direction(+1/-1/0)} 0=不参与；复合=Σ z(f)*dir"""
    cash, eq, hold, reasons = 1e6, [], {}, {}
    active = [f for f, dv in fac_dict.items() if dv != 0]
    Z = {}
    for f in active:
        a = fac_dict[f] * FACTORS[f]
        m, s = np.nanmean(a, axis=0), np.nanstd(a, axis=0)   # 截面 z（逐日）
        Z[f] = (a - m) / np.where(s > 0, s, 1)
    comp = np.zeros((ND, NS))
    for f in active:
        comp += np.nan_to_num(Z[f], nan=0)
    valid = np.isfinite(C)
    comp = np.where(valid, comp, np.nan)
    n_tr = 0
    for di in range(ND):
        for code in [c for c, h in hold.items() if h.get("sell_flag")]:
            j = cix[code]
            if np.isnan(O[di, j]) or O[di, j] <= 0:
                continue
            px_o = O[di, j] * (1 - slip)
            h = hold.pop(code)
            sh = h["sh"]
            cash += sh * px_o - max(sh * px_o * 0.00025, 5) - sh * px_o * 0.001
            n_tr += 1
        if di % rebal == offset and di > 120:
            sc = comp[di]
            ok = np.where(np.isfinite(sc))[0]
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
                px_o = O[di, j]
                pc = C[di - 1, j]
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
                hold[code] = {"sh": sh, "ep": px_o * (1 + slip), "sell_flag": False}
        pv = cash + sum(h["sh"] * (C[di, cix[c]] if np.isfinite(C[di, cix[c]]) else h["ep"]) for c, h in hold.items())
        eq.append(pv)
    eq = np.array(eq)
    r = np.diff(eq) / eq[:-1]
    tot = eq[-1] / 1e6 - 1
    return {"total": tot * 100, "ann": ((1 + tot) ** (252 / max(1, len(eq))) - 1) * 100,
            "mdd": ((eq / np.maximum.accumulate(eq) - 1).min()) * 100,
            "sharpe": float(np.nanmean(r) / np.nanstd(r) * np.sqrt(252)) if np.nanstd(r) > 0 else 0,
            "n_trades": n_tr}


if __name__ == "__main__":
    out = {"_meta": {"universe": "主板含退市", "start": "2021-01-04", "slip": 20, "n_factor_arms": 24}}
    # 1. 单因子双向定标（12×2=24 臂，10/60d 主配置）
    print("--- 单因子双向（10/60d）---", flush=True)
    best_dir = {}
    for fn in FACTORS:
        res = {}
        for dv in (1, -1):
            r = run({fn: dv})
            res[dv] = r["sharpe"]
            out[f"单因子_{fn}_{'+1' if dv > 0 else '-1'}"] = r
        best_dir[fn] = max(res, key=res.get)
        print(f"[{fn}] +1 夏普 {res[1]:.3f} | -1 夏普 {res[-1]:.3f} → 最优 {'+' if best_dir[fn] > 0 else '-'}", flush=True)
    # 2. 组合合成（单因子最优方向）
    COMBOS = {
        "冠军_L2_5f": ["ln_amt20", "intraday20", "pvc20", "ret20", "vr5_20"],
        "过闸最多_L2b_3f": ["ln_amt20", "atr20", "amp20"],
        "L2_6f_a": ["ln_amt20", "intraday20", "pvc20", "vr20_60", "ret20", "vr5_20"],
        "L2_6f_b": ["ln_amt20", "apvc20", "intraday20", "vr20_60", "ret20", "vr5_20"],
        "L2b_vol20": ["ln_amt20", "vol20", "ret20"],
        "稳健_ret60": ["ln_amt20", "ret60"],
        "稳健_atr20": ["ln_amt20", "atr20"],
        "稳健_amp20": ["ln_amt20", "amp20"],
    }
    print("--- 组合（10/60d 主配置）---", flush=True)
    for name, fl in COMBOS.items():
        fd = {f: best_dir[f] for f in FACTORS}
        for f in fl:
            fd[f] = best_dir[f]
        for f in FACTORS:
            if f not in fl:
                fd[f] = 0
        r = run(fd)
        out[f"组合_{name}"] = r
        print(f"[{name}] {r['total']:.1f}% | 年化 {r['ann']:.1f}% | 回撤 {r['mdd']:.1f}% | 夏普 {r['sharpe']:.3f} | {r['n_trades']}笔", flush=True)
    # 3. 冠军组合 12 组配置网格（TopN×调仓）+ 相位
    print("--- 冠军组合配置网格 ---", flush=True)
    fd = {f: (best_dir[f] if f in COMBOS["冠军_L2_5f"] else 0) for f in FACTORS}
    grid = {}
    for topk, reb in product((5, 10, 20), (5, 20, 60)):
        r = run(fd, rebal=reb, topk=topk)
        grid[f"{topk}/{reb}d"] = r["sharpe"]
        print(f"  冠军 {topk}/{reb}d: 夏普 {r['sharpe']:.3f} | {r['total']:.1f}%", flush=True)
    out["冠军_12组网格_夏普"] = grid
    gvals = np.array(list(grid.values()))
    out["冠军_网格中位"] = float(np.median(gvals))
    out["冠军_网格最小"] = float(gvals.min())
    ph = [run(fd, offset=o)["sharpe"] for o in (0, 15, 30, 45)]
    out["冠军_相位夏普"] = ph
    print(f"[冠军相位] off0 {ph[0]:.3f} | 中位 {np.median(ph):.3f} | 区间 [{min(ph):.2f},{max(ph):.2f}]", flush=True)
    json.dump(out, open(BASE / "backtest" / "lab_combo_0913.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=str)
    print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
