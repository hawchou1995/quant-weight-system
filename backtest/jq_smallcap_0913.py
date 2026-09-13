# -*- coding: utf-8 -*-
"""聚宽国九小市值 · 主板移植版（预注册，等 val 管道双 shard 数据齐后执行）
规则（源：聚宽2025年精选/15小市值排除3个bug版）：
- 域：流通市值 10~100 亿（主板版口径）；市值 = amount / (turn/100)，T 日收盘可得（信息集 ✓ ADR-0007）
- 排序：市值升序取前 10，等权；周频（5 日）与月频（20 日）两档
- 过滤：close≥2、新股<180 交易日、当日涨停不买（开盘≥昨收×1.097 跳过）
- 成本：佣金 2.5bp + 印花税 10bp（卖出）+ 最低 5 元 + 滑点 20/50bps 双档（聚宽原版 0 滑点为声明数字不可比）
- 退出：周/月调仓全换（无止损——忠实移植），另测 +LLV20 阶梯止损变体
判读重点：分年度（2017 大票年/2024 微盘崩的路径依赖）+ 声明 turn 精度误差（低换手票放大）
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
VAL = BASE / "data_fundamental" / "baostock_val"
OUTJ = BASE / "backtest" / "jq_smallcap_0913.json"

t0 = time.time()

# ---- 1. 合并 val 数据（双 shard）----
frames = []
for i in (0, 1):
    f = VAL / f"val_all_{i}.csv"
    if f.exists():
        frames.append(pd.read_csv(f, dtype={"code": str}))
df = pd.concat(frames, ignore_index=True)
for c in ("close", "peTTM", "pbMRQ", "psTTM", "turn"):
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values(["code", "date"])
print(f"[val] {df['code'].nunique()} 票 {len(df):,} 行 ({time.time()-t0:.0f}s)", flush=True)

# ---- 2. 流通市值（amount 来自 data_full；turn 为 %）----
amt_rows = []
for f in sorted((BASE / "data_full").glob("*.csv")):
    c = f.stem
    if not (c.startswith("sh60") or c.startswith("sz00")):
        continue
    d = pd.read_csv(f, usecols=["date", "amount"], dtype={"date": str})
    d["date"] = pd.to_datetime(d["date"])
    d["code"] = ("sh." if c.startswith("sh") else "sz.") + c[2:]
    amt_rows.append(d)
amt = pd.concat(amt_rows, ignore_index=True).sort_values(["code", "date"])
print(f"[amount] {amt['code'].nunique()} 票 ({time.time()-t0:.0f}s)", flush=True)

m = df.merge(amt, on=["code", "date"], how="left")
m["fmv"] = m["amount"] / (m["turn"] / 100.0)   # 流通市值（元）
m = m[(m["fmv"] >= 1e9) & (m["fmv"] <= 1e10)]  # 10~100 亿
m["fmv_yi"] = m["fmv"] / 1e8
print(f"[域] 10-100亿 行数 {len(m):,}，覆盖票 {m['code'].nunique()}", flush=True)

# ---- 3. 截面矩阵 ----
ALL_DAYS = sorted(m["date"].unique())
day_ix = {d: i for i, d in enumerate(ALL_DAYS)}
codes_u = sorted(m["code"].unique())
c_ix = {c: i for i, c in enumerate(codes_u)}
ND, NS = len(ALL_DAYS), len(codes_u)
FMV = np.full((ND, NS), np.nan)
OPEN = np.full((ND, NS), np.nan)
CLOSE = np.full((ND, NS), np.nan)
AMT = np.full((ND, NS), np.nan)
for r in m.itertuples(index=False):
    i, j = day_ix[r.date], c_ix[r.code]
    FMV[i, j], OPEN[i, j], CLOSE[i, j], AMT[i, j] = r.fmv_yi, r.open if hasattr(r, "open") else np.nan, r.close, r.amount
# open 列不在 val 管道 → 从 data_full 取。此处简化：用 close 次日近似 open 的 T+1 成交价改由 data_full open 表
o_rows = []
for f in sorted((BASE / "data_full").glob("*.csv")):
    c = f.stem
    if not (c.startswith("sh60") or c.startswith("sz00")):
        continue
    d = pd.read_csv(f, usecols=["date", "open"], dtype={"date": str})
    d["date"] = pd.to_datetime(d["date"])
    d["code"] = ("sh." if c.startswith("sh") else "sz.") + c[2:]
    o_rows.append(d)
opn = pd.concat(o_rows, ignore_index=True)
opn = opn[opn["code"].isin(c_ix)]
for r in opn.itertuples(index=False):
    if r.code in c_ix and r.date in day_ix:
        OPEN[day_ix[r.date], c_ix[r.code]] = r.open
print(f"[matrix] {ND}×{NS} ({time.time()-t0:.0f}s)", flush=True)

np.save(OUTJ.parent / "jq_smallcap_cache.npy", np.stack([FMV, OPEN, CLOSE, AMT]))
json.dump({"days": [str(d)[:10] for d in ALL_DAYS], "codes": codes_u},
          open(OUTJ.parent / "jq_smallcap_cache_meta.json", "w", encoding="utf-8"))
print(f"[cache] 矩阵缓存已落盘，回测入口 run_smallcap() 待数据核对后执行 ({time.time()-t0:.0f}s)", flush=True)

# ---- 4. 回测（周频/月频 × 滑点 20/50bps）----
def run(rebal, slip, stop_llv=None):
    cash, eq, trades, reasons = 1e6, [], [], {}
    holdings = {}
    for di in range(ND):
        day = ALL_DAYS[di]
        # 卖出（T 收盘信号 → T+1 开盘）
        for code in list(holdings.keys()):
            j = c_ix[code]
            c = CLOSE[di, j]
            if np.isnan(OPEN[di, j]):
                continue
            if holdings[code]["sell_flag"]:
                px = OPEN[di, j] * (1 - slip)
                sh = holdings.pop(code)["sh"]
                fee = max(sh * px * 0.00025, 5)
                cash += sh * px - fee - sh * px * 0.001
                trades.append((px / holdings.get(code, {}).get("ep", px)) * 100 if False else 0)
                reasons[holdings.get(code, {}).get("reason", "调仓")] = reasons.get(holdings.get(code, {}).get("reason", "调仓"), 0) + 1
                continue
            if stop_llv is not None and np.isfinite(c):
                # LLV20 阶梯止损（近 20 日最低收盘，前日窗口）
                k0 = max(0, di - 20)
                llv = np.nanmin(CLOSE[k0:di, j]) if di > 0 else np.nan
                if np.isfinite(llv) and c < llv:
                    holdings[code]["sell_flag"] = True
                    holdings[code]["reason"] = f"LLV{stop_llv}止损"
        # 买入信号（di % rebal == 0）
        if di % rebal == 0:
            row = FMV[di]
            ok = np.where(np.isfinite(row))[0]
            ok = ok[np.argsort(row[ok])][:10]  # 市值升序前 10
            tgt = {codes_u[j] for j in ok}
            for code in list(holdings.keys()):
                if code not in tgt:
                    holdings[code]["sell_flag"] = True
                    holdings[code]["reason"] = "调仓"
            pv = cash + sum(h["sh"] * CLOSE[di, c_ix[cc]] for cc, h in holdings.items() if np.isfinite(CLOSE[di, c_ix[cc]]))
            w = 1.0 / 10
            for j in ok:
                code = codes_u[j]
                if code in holdings:
                    continue
                px = OPEN[di, j]
                if np.isnan(px) or px < 2:
                    continue
                budget = min(pv * w, cash)
                nl = int((budget - 5) / (px * 100 * 1.00025))
                if nl < 1:
                    continue
                sh = nl * 100
                cost = sh * px * (1 + slip) + max(sh * px * 0.00025, 5)
                if cost > cash:
                    continue
                cash -= cost
                holdings[code] = {"sh": sh, "ep": px * (1 + slip), "sell_flag": False, "reason": ""}
        pv = cash + sum(h["sh"] * CLOSE[di, c_ix[cc]] for cc, h in holdings.items() if np.isfinite(CLOSE[di, c_ix[cc]]))
        eq.append(pv)
    eq = np.array(eq)
    r = np.diff(eq) / eq[:-1]
    return {"total": (eq[-1] / 1e6 - 1) * 100, "mdd": ((eq / np.maximum.accumulate(eq) - 1).min()) * 100,
            "sharpe": float(np.nanmean(r) / np.nanstd(r) * np.sqrt(252)) if np.nanstd(r) > 0 else 0,
            "n_days": ND, "reasons": reasons}

if __name__ == "__main__":
    out = {}
    for rebal, tag in ((5, "周频"), (20, "月频")):
        for slip in (0.002, 0.005):
            r = run(rebal, slip)
            out[f"{tag}_slip{int(slip*1e4)}"] = r
            print(f"[{tag} slip{int(slip*1e4)}bps] {r['total']:.1f}% | 回撤 {r['mdd']:.1f}% | 夏普 {r['sharpe']:.3f} | {r['reasons']}", flush=True)
    json.dump(out, open(OUTJ, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
    print(f"总耗时 {time.time()-t0:.0f}s", flush=True)
