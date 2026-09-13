# -*- coding: utf-8 -*-
"""MACD 多周期规则回测（用户命题：「月线拐头向上或站上零轴，周线金叉上重仓」）
预注册口径（T 收盘信号 → T+1 执行；bar 完成即次交易日生效）：
  月线多头 m_bull = DIF 较上月抬升 OR DIF>0（月线 MACD 12/26/9）
  周线金叉 w_gc = DIF 上穿 DEA，取近 4 周内出现
载体 A：沪深300 指数择时（空仓避险）——V1 月线多头持有 / V2 半仓+金叉加满 / V3 双条件全仓
载体 B：冷门低波 Top10/60d 主板组合加 MACD 过滤（要求个股月线多头 / 双条件）vs 基线
窗口：2021-01-04 起（指数另报 2015 起）；成本 20bps 滑点 + 真实费率。"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
START = pd.Timestamp("2021-01-04")
t0 = time.time()


def macd_series(close):
    ef = close.ewm(span=12, adjust=False).mean()
    es = close.ewm(span=26, adjust=False).mean()
    dif = ef - es
    dea = dif.ewm(span=9, adjust=False).mean()
    return dif, dea


def mtf_signals(close_daily):
    """月线多头 / 周线金叉(近4周)，对齐日频（bar 完成后次一交易日生效，PIT-safe）"""
    w = close_daily.resample("W-FRI").last().dropna()
    m = close_daily.resample("ME").last().dropna()
    if len(w) < 30 or len(m) < 14:
        idx = close_daily.index
        return pd.Series(False, index=idx), pd.Series(False, index=idx)
    wd, we = macd_series(w)
    md, me = macd_series(m)
    w_gc = ((wd > we) & (wd.shift(1) <= we.shift(1))).rolling(4, min_periods=1).max().astype(bool)
    m_bull = (md > md.shift(1)) | (md > 0)
    w_eff = w_gc.copy()
    w_eff.index = w_eff.index + pd.Timedelta(days=3)
    m_eff = m_bull.copy()
    m_eff.index = m_eff.index + pd.Timedelta(days=1)
    w_d = w_eff.reindex(close_daily.index, method="ffill").fillna(False).astype(bool)
    m_d = m_eff.reindex(close_daily.index, method="ffill").fillna(False).astype(bool)
    return m_d, w_d


def metrics(eq, name, days_per_year=252):
    eq = np.asarray(eq, dtype=float)
    r = np.diff(eq) / eq[:-1]
    tot = eq[-1] / eq[0] - 1
    ann = (1 + tot) ** (days_per_year / max(1, len(eq))) - 1
    mdd = (eq / np.maximum.accumulate(eq) - 1).min()
    sh = float(np.mean(r) / np.std(r) * np.sqrt(days_per_year)) if np.std(r) > 0 else 0
    return {"total": round(tot * 100, 1), "ann": round(ann * 100, 2), "mdd": round(mdd * 100, 1), "sharpe": round(sh, 3)}


# ================= 载体 A：指数择时 =================
idx_raw = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str}).drop_duplicates("date")
idx_raw["date"] = pd.to_datetime(idx_raw["date"])
idx_all = idx_raw.set_index("date")["close"].sort_index()
m_all, w_all = mtf_signals(idx_all)

for tag, start in (("2021起", START), ("2015起", pd.Timestamp("2015-09-01"))):
    c = idx_all.loc[start:]
    m_d, w_d = m_all.loc[start:], w_all.loc[start:]
    ret = c.pct_change().fillna(0).to_numpy()
    res = {}
    res["V0_买入持有"] = metrics(np.cumprod(1 + ret) * 1e6, "bh")
    pos1 = m_d.to_numpy().astype(float)
    res["V1_月线多头"] = metrics(np.cumprod(1 + pos1 * ret) * 1e6, "v1")
    pos2 = 0.5 * m_d.to_numpy().astype(float) + 0.5 * (m_d.to_numpy() & w_d.to_numpy()).astype(float)
    res["V2_半仓+金叉加满"] = metrics(np.cumprod(1 + pos2 * ret) * 1e6, "v2")
    pos3 = (m_d.to_numpy() & w_d.to_numpy()).astype(float)
    res["V3_双条件全仓"] = metrics(np.cumprod(1 + pos3 * ret) * 1e6, "v3")
    res["_仓位占比"] = {"V1": round(float(pos1.mean()), 2), "V2": round(float(pos2.mean()), 2), "V3": round(float(pos3.mean()), 2)}
    print(f"\n===== 载体A 指数择时（HS300 · {tag} ）=====", flush=True)
    for k, v in res.items():
        if k.startswith("_"):
            print(f"  平均仓位 {v}", flush=True)
        else:
            print(f"  {k:<18} 总收益 {v['total']:>8.1f}% | 年化 {v['ann']:>6.2f}% | 回撤 {v['mdd']:>6.1f}% | 夏普 {v['sharpe']:.3f}", flush=True)
    json_A = res

# ================= 载体 B：冷门低波 + MACD 过滤 =================
print(f"\n[加载主板 2015+ 数据...] ({time.time()-t0:.0f}s)", flush=True)
codes, mat = [], {}
for f in sorted((BASE / "data_full").glob("*.csv")):
    stem = f.stem
    if not (stem.startswith("sh60") or stem.startswith("sz00")):
        continue
    d = pd.read_csv(f, usecols=["date", "open", "close", "high", "amount"], dtype={"date": str})
    d["date"] = pd.to_datetime(d["date"])
    d = d[d["date"] >= pd.Timestamp("2015-06-01")].sort_values("date")
    if len(d) < 500:
        continue
    code = stem[2:]
    codes.append(code)
    mat[code] = d.set_index("date")
codes = sorted(codes)
print(f"[load] {len(codes)} 票 ({time.time()-t0:.0f}s)", flush=True)

ALL_DAYS = sorted({d for c in codes for d in mat[c].index if d >= START})
day_ix = {d: i for i, d in enumerate(ALL_DAYS)}
ND, NS = len(ALL_DAYS), len(codes)
cix = {c: i for i, c in enumerate(codes)}
O = np.full((ND, NS), np.nan); C = np.full((ND, NS), np.nan)
H = np.full((ND, NS), np.nan); A = np.full((ND, NS), np.nan)
MB = np.zeros((ND, NS), dtype=bool)   # 月线多头
WG = np.zeros((ND, NS), dtype=bool)   # 周线金叉近4周
FIRST = np.full(NS, -1, dtype=int)
for code in codes:
    m = mat[code]; j = cix[code]
    md, wd = mtf_signals(m["close"])
    md_w = md.reindex(ALL_DAYS, method="ffill").fillna(False).to_numpy()
    wd_w = wd.reindex(ALL_DAYS, method="ffill").fillna(False).to_numpy()
    MB[:, j] = md_w; WG[:, j] = wd_w
    ii = np.array([day_ix[d] for d in m.index if d >= START], dtype=int)
    sub = m.loc[m.index >= START]
    O[ii, j] = sub["open"].to_numpy(); C[ii, j] = sub["close"].to_numpy()
    H[ii, j] = sub["high"].to_numpy(); A[ii, j] = sub["amount"].to_numpy()
    FIRST[j] = ii.min() if len(ii) else -1
amt20 = pd.DataFrame(A).rolling(20, min_periods=15).mean().to_numpy()
PC = np.full((ND, NS), np.nan); PC[1:] = C[:-1]
TR = np.nanmax(np.stack([H - np.full((ND, NS), np.nan), np.abs(H - PC), np.abs(np.full((ND, NS), np.nan) - PC)]), axis=0) if False else None
atr20 = pd.DataFrame(np.abs(C - PC)).rolling(20, min_periods=15).mean().to_numpy() / C  # 简化波幅（|ΔC|，与TR近似）
ln_amt = np.log(np.maximum(amt20, 1e3))
print(f"[matrix] {ND}×{NS} ({time.time()-t0:.0f}s)", flush=True)


def run(mode, topk=10, rebal=60, slip=0.002, offset=0):
    """mode: base | mbull | both"""
    comp = np.nan_to_num(((-ln_amt) - np.nanmean(-ln_amt, axis=0)) / np.where(np.nanstd(-ln_amt, axis=0) > 0, np.nanstd(-ln_amt, axis=0), 1), nan=0) \
         + np.nan_to_num(((-atr20) - np.nanmean(-atr20, axis=0)) / np.where(np.nanstd(-atr20, axis=0) > 0, np.nanstd(-atr20, axis=0), 1), nan=0)
    comp = np.where(np.isfinite(C), comp, np.nan)
    cash, eq, hold, n_tr = 1e6, [], {}, 0
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
    m = metrics(eq, mode)
    m["n_trades"] = n_tr
    return m


print("\n===== 载体B 冷门低波 Top10/60d + MACD 过滤（2021起 · 20bps）=====", flush=True)
outB = {}
for mode, name in (("base", "B0 基线（无MACD）"), ("mbull", "B1 仅月线多头"), ("both", "B2 月线多头+周线金叉")):
    r = run(mode)
    outB[name] = r
    print(f"  {name:<22} 总收益 {r['total']:>8.1f}% | 年化 {r['ann']:>6.2f}% | 回撤 {r['mdd']:>6.1f}% | 夏普 {r['sharpe']:.3f} | {r['n_trades']}笔", flush=True)

json.dump({"A_指数择时": {k: v for k, v in json_A.items()}, "B_冷门低波过滤": outB},
          open(BASE / "backtest" / "macd_mtf_0913.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print(f"\n总耗时 {time.time()-t0:.0f}s", flush=True)
