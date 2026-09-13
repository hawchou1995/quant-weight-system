# -*- coding: utf-8 -*-
"""fwd 语义复核（2026-09-13）：冷门低波 ln_amt20+atr20 在「固定持有窗口」语义下是否仍正。
fwd 口径（对齐 factorcombo）：每 60 交易日一段，T+1 开盘等权买入，T+1+60 开盘全部卖出换下一段，
段内零操作；每段独立（资金等权重置）。对照：调仓制（复利连续）+ 单因子双向。
输出：fwd_check_0913.json + 控制台裁决表。"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
START = pd.Timestamp("2021-01-04")
t0 = time.time()

codes, mat = [], {}
for f in sorted((BASE / "data_full").glob("*.csv")):
    c = f.stem
    if not (c.startswith("sh60") or c.startswith("sz00")):
        continue
    d = pd.read_csv(f, usecols=["date", "open", "high", "low", "close", "volume", "amount"], dtype={"date": str})
    d["date"] = pd.to_datetime(d["date"])
    d = d[d["date"] >= START].sort_values("date")
    if len(d) < 120:
        continue
    codes.append(c[2:])
    mat[c[2:]] = d.set_index("date")
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


def roll_mean(x, n):
    return pd.DataFrame(x).rolling(n, min_periods=n).mean().to_numpy()


PC = np.full((ND, NS), np.nan); PC[1:] = C[:-1]
TR = np.nanmax(np.stack([H - L, np.abs(H - PC), np.abs(L - PC)]), axis=0)
FAC = {
    "ln_amt20": np.log(np.maximum(roll_mean(A, 20), 1e3)),
    "atr20": roll_mean(TR, 20) / C,
}
print(f"[factors] ({time.time()-t0:.0f}s)", flush=True)

SLIP = 0.002
FEE_B = 0.00025
TAX_S = 0.001


def zsc_row(a):
    mu = np.nanmean(a); sd = np.nanstd(a)
    return (a - mu) / sd if sd > 0 else np.zeros_like(a)


def run_fwd(spec, h=60, topn=10, offset=0):
    """fwd 固定持有：每 h 交易日一段，T+1 开盘买、T+1+h 开盘卖、段内零操作、每段资金等权重置复利。"""
    cash, eq = 1e6, []
    seg_start = 120 + offset
    while seg_start + 1 + h < ND:
        # 信号日 seg_start 收盘 → seg_start+1 开盘买 → seg_start+1+h 开盘卖
        sc = np.zeros(NS)
        for fname, dv in spec:
            a = FAC[fname] * dv
            sc += np.nan_to_num(zsc_row(a[seg_start]), nan=0)
        ok = np.where(np.isfinite(sc) & np.isfinite(O[seg_start + 1]))[0]
        ok = [j for j in ok[np.argsort(-sc[ok])][:topn]
              if O[seg_start + 1, j] >= 2 and seg_start + 1 - FIRST[j] >= 180]
        if ok:
            w = 1.0 / len(ok)
            seg_val = 0.0
            for j in ok:
                px_in = O[seg_start + 1, j] * (1 + SLIP)
                px_out = O[seg_start + 1 + h, j] * (1 - SLIP)
                if not np.isfinite(px_in) or not np.isfinite(px_out) or px_out <= 0:
                    px_out = px_in  # 停牌保本近似
                seg_val += w * (px_out / px_in)
            fee_drag = w * (max(1e6 * w * FEE_B, 5) / (1e6 * w) + TAX_S / len(ok)) if False else 0.0
            cash *= (seg_val * (1 - 2 * 0.00025 * 0.2))  # 粗略双边佣金+印税拖累（保守 8bps/段）
        eq.append(cash)
        seg_start += h
    eq = np.array(eq)
    # 段收益转日收益近似（夏普按段频×sqrt(252/h)）
    r = np.diff(eq) / eq[:-1]
    tot = eq[-1] / 1e6 - 1
    years = h * len(r) / 252.0
    ann = (1 + tot) ** (1 / max(years, 1e-9)) - 1
    sharpe = float(np.mean(r) / np.std(r) * np.sqrt(252 / h)) if np.std(r) > 0 else 0
    return {"total": tot * 100, "ann": ann * 100, "sharpe": sharpe, "n_seg": len(r)}


def run_rot(spec, h=60, topn=10, offset=0):
    """调仓制（lab_combo 同口径简化版）：di%h==0 调仓，段内持有，复利。"""
    comp = np.zeros((ND, NS))
    for fname, dv in spec:
        a = FAC[fname] * dv
        mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
        comp += np.nan_to_num((a - mu) / np.where(sd > 0, sd, 1), nan=0)
    comp = np.where(np.isfinite(C), comp, np.nan)
    cash, eq, hold = 1e6, [], {}
    for di in range(ND):
        for code in list(hold.keys()):
            j = cix[code]
            if np.isnan(O[di, j]) or O[di, j] <= 0:
                continue
            px_o = O[di, j] * (1 - SLIP)
            sh = hold.pop(code)["sh"]
            cash += sh * px_o - max(sh * px_o * FEE_B, 5) - sh * px_o * TAX_S
        if di % h == offset and di > 120:
            sc = comp[di]
            ok = np.where(np.isfinite(sc))[0]
            ok = [j for j in ok[np.argsort(-sc[ok])][:topn]
                  if np.isfinite(O[di, j]) and O[di, j] >= 2 and di - FIRST[j] >= 180]
            tgt = {codes[j] for j in ok}
            for code in list(hold.keys()):
                if code not in tgt:
                    j = cix[code]
                    if np.isnan(O[di, j]) or O[di, j] <= 0:
                        continue
                    px_o = O[di, j] * (1 - SLIP)
                    sh = hold.pop(code)
                    cash += sh * px_o - max(sh * px_o * FEE_B, 5) - sh * px_o * TAX_S
            pv = cash + sum(h["sh"] * C[di, cix[c]] for c, h in hold.items() if np.isfinite(C[di, cix[c]]))
            for j in ok:
                code = codes[j]
                if code in hold:
                    continue
                px_o = O[di, j]; pc = C[di - 1, j]
                if not np.isfinite(px_o) or not np.isfinite(pc) or px_o >= pc * 1.097:
                    continue
                nl = int((min(pv / topn, cash) - 5) / (px_o * 100 * (1 + FEE_B)))
                if nl < 1:
                    continue
                sh = nl * 100
                cost = sh * px_o * (1 + SLIP) + max(sh * px_o * FEE_B, 5)
                if cost > cash:
                    continue
                cash -= cost
                hold[code] = {"sh": sh}
        pv = cash + sum(h["sh"] * C[di, cix[c]] for c, h in hold.items() if np.isfinite(C[di, cix[c]]))
        eq.append(pv)
    eq = np.array(eq)
    r = np.diff(eq) / eq[:-1]
    tot = eq[-1] / 1e6 - 1
    return {"total": tot * 100, "ann": ((1 + tot) ** (252 / max(1, len(eq))) - 1) * 100,
            "mdd": ((eq / np.maximum.accumulate(eq) - 1).min()) * 100,
            "sharpe": float(np.mean(r) / np.std(r) * np.sqrt(252)) if np.std(r) > 0 else 0}


if __name__ == "__main__":
    out = {}
    SPECS = [
        ("combo_双低 ln-+atr-", [("ln_amt20", -1), ("atr20", -1)]),
        ("atr20_低波(-1)", [("atr20", -1)]),
        ("atr20_高波(+1)", [("atr20", 1)]),
        ("ln_amt20_低额(-1)", [("ln_amt20", -1)]),
        ("ln_amt20_高额(+1)", [("ln_amt20", 1)]),
    ]
    print(f"{'臂':<22}{'fwd60 总收益':>12}{'fwd 年化':>10}{'fwd 夏普':>9}{'调仓制收益':>11}{'调仓制夏普':>10}", flush=True)
    for name, spec in SPECS:
        f = run_fwd(spec)
        r = run_rot(spec)
        out[name] = {"fwd": f, "rot": r}
        print(f"{name:<22}{f['total']:>11.1f}%{f['ann']:>9.1f}%{f['sharpe']:>9.3f}{r['total']:>10.1f}%{r['sharpe']:>10.3f}", flush=True)
    json.dump(out, open(BASE / "backtest" / "fwd_check_0913.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=str)
    print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
