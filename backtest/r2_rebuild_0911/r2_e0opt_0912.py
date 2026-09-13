# -*- coding: utf-8 -*-
"""E0 优化矩阵：权重向量穷举 × 黄金分割融合 × 轮动节奏。
载体 = 高流动性 Top10 月度轮动（r2_naci_exit_0912 A 载体 E0），口径不变：
T+1 开盘成交、SLIP 20bps、COMM 0.025%、TAX 0.05%、起点 2021-01-04、主板全池(含退市)。
预注册 19 臂；出场侧止盈/组合清仓闸门已证伪方向不进矩阵（见报告）。
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[2]
DATA = BASE / "data_full"
R2 = BASE / "backtest" / "r2_rebuild_0911"
START = pd.Timestamp("2021-01-04")
COMM, TAX, SLIP = 0.00025, 0.0005, 0.0020
CASH0 = 1_000_000.0
LIMIT_UP_GUARD = 1.097
MA_PERIODS = (10, 15, 20, 22, 25, 30, 35, 40, 45, 50, 60)
LLV_PERIODS = (10, 13, 15, 20, 25, 30, 40, 60)
EMA_PERIODS = (144, 169, 576, 676)

t0 = time.time()
idx = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
idx["date"] = pd.to_datetime(idx["date"])
idx = idx.set_index("date").sort_index()
ALL_DAYS = [d for d in idx.index if START <= d]
ND = len(ALL_DAYS)
ALL_D64 = np.array(ALL_DAYS, dtype="datetime64[ns]")
HS300_TOTAL = (idx.loc[ALL_DAYS, "close"].iloc[-1] / idx.loc[ALL_DAYS, "close"].iloc[0] - 1) * 100

codes, stock = [], {}
for f in sorted(DATA.glob("*.csv")):
    code = f.stem
    if not (code.startswith("sh60") or code.startswith("sz00")):
        continue
    try:
        df = pd.read_csv(f, usecols=["date", "open", "close", "high", "low", "amount"], dtype={"date": str})
    except Exception:
        continue
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < 420:
        continue
    c = df["close"].to_numpy(float)
    o = df["open"].to_numpy(float)
    amo = df["amount"].to_numpy(float)
    cs = pd.Series(c)
    ma_map = {p: cs.rolling(p, min_periods=p).mean().to_numpy() for p in MA_PERIODS}
    llv_map = {p: cs.rolling(p, min_periods=p).min().shift(1).to_numpy() for p in LLV_PERIODS}  # 前N日最低（含当日则c<LLV恒假）
    ema_map = {p: cs.ewm(span=p, adjust=False, min_periods=p).mean().to_numpy() for p in EMA_PERIODS}
    amt20 = pd.Series(amo).rolling(20, min_periods=20).mean().to_numpy()
    hh20 = cs.rolling(20, min_periods=20).max().to_numpy()
    ll20 = cs.rolling(20, min_periods=20).min().to_numpy()
    hh60 = cs.rolling(60, min_periods=60).max().to_numpy()
    ll60 = cs.rolling(60, min_periods=60).min().to_numpy()
    ret1 = np.full(len(c), np.nan); ret1[1:] = c[1:] / c[:-1] - 1
    atr20 = pd.Series(ret1).rolling(20, min_periods=20).std().to_numpy() * np.sqrt(20)  # 20日已实现波动
    mom20 = np.full(len(c), np.nan); mom20[20:] = c[20:] / c[:-20] - 1
    d64 = df["date"].to_numpy(dtype="datetime64[ns]")
    gpos = np.searchsorted(ALL_D64, d64)
    gvalid = (gpos < ND) & (ALL_D64[np.minimum(gpos, ND - 1)] == d64)
    gpos = np.where(gvalid, gpos, 0)
    rowof = np.full(ND, -1, np.int32)
    rows = np.where(gvalid)[0]
    rowof[gpos[rows]] = rows
    stock[code] = dict(o=o, c=c, ma=ma_map, rowof=rowof, amt20=np.where(np.isfinite(amt20), amt20, 0),
                       hh20=hh20, ll20=ll20, hh60=hh60, ll60=ll60, atr20=atr20, mom20=mom20,
                       llv=llv_map, ema=ema_map)
    codes.append(code)
print(f"[load] {len(codes)} 只 ({time.time()-t0:.0f}s)", flush=True)

LIQ_RANK = sorted(codes, key=lambda cc: -np.nanmax(stock[cc]["amt20"]))


_RW_OVERRIDE = None


def rank_weights(n, shape):
    """名次权重向量，长度 n，和为 1。_RW_OVERRIDE 供安慰剂注入随机权重。"""
    if _RW_OVERRIDE is not None:
        w = np.asarray(_RW_OVERRIDE, float)
        assert len(w) == n
        return w / w.sum()
    if shape == "eq":
        w = np.ones(n)
    elif shape == "lin":      # 线性递减
        w = np.arange(n, 0, -1, dtype=float)
    elif shape == "sq":       # 平方递减
        w = np.arange(n, 0, -1, dtype=float) ** 2
    elif shape == "geo08":    # 几何 0.8 衰减
        w = 0.8 ** np.arange(n)
    elif shape == "top2":     # 前两名集中 40%/30%
        w = np.full(n, (1 - 0.7) / max(1, n - 2))
        w[0], w[1] = 0.4, 0.3
    else:
        raise ValueError(shape)
    return w / w.sum()


def run(name, npos=5, shape="eq", wfactor=None, rebal=20, fib_entry=None, fib_p=20, fib_stop=False, offset=0,
        ma_p=20, stop_pct=0.08, maxhold=60, pool_n=10, amt_th=5e6,
        exit_mode="ma", llv_p=20, ma_shift=0.0, ema_filter=None, comm_min=0.0, liq_mode="hist"):
    """wfactor: None | 'vol'(1/atr20) | 'mom'(1+mom20) | 'amt'(amt20) —— 在选定候选内按因子加权。
    fib_entry: None | 'filter50'(c≤0.5回撤位才买) | 'sort382'(按距0.382位接近度排序)
    fib_stop: True 时 −8% 硬止损 → 收盘跌破 0.382 回撤位止损。
    """
    w_slot = rank_weights(npos, shape)
    cash = CASH0
    holdings, pending_sell, pending_buy, last_close = {}, {}, [], {}
    trades_ep, trades, reason_cnt = {}, [], {}
    eq = []
    for di in range(ND):
        d64 = ALL_D64[di]
        for code in list(pending_sell.keys()):
            if code not in holdings:
                pending_sell.pop(code, None); continue
            s = stock[code]
            k = s["rowof"][di]
            if k < 0:
                continue
            px = s["o"][k] * (1 - SLIP)
            sh = holdings.pop(code)["sh"]
            fee_s = max(sh * px * COMM, comm_min)
            cash += sh * px - fee_s - sh * px * TAX
            trades.append((px / trades_ep.pop(code) - 1) * 100)
            r = pending_sell.pop(code)
            reason_cnt[r] = reason_cnt.get(r, 0) + 1
        rk = 0
        for code, frac in pending_buy:
            if len(holdings) >= npos or code in holdings or code in pending_sell:
                continue
            s = stock[code]
            k = s["rowof"][di]
            if k <= 0:
                continue
            px_prev = s["c"][k - 1]
            px_raw = s["o"][k]
            if not np.isfinite(px_prev) or px_raw >= px_prev * LIMIT_UP_GUARD:
                rk += 1
                continue
            px = px_raw * (1 + SLIP)
            pv = cash + sum(h["sh"] * last_close.get(cc, h["ep"]) for cc, h in holdings.items())
            budget = min(pv * frac, cash)
            nl = int((budget - comm_min) / (px * 100 * (1 + COMM)))
            if nl < 1:
                rk += 1
                continue
            sh = nl * 100
            cost = sh * px + max(sh * px * COMM, comm_min)
            if cost > cash:
                rk += 1
                continue
            cash -= cost
            holdings[code] = {"sh": sh, "ep": px, "di": di}
            trades_ep[code] = px
            last_close[code] = px
            rk += 1
        pending_buy = []
        # 收盘检查
        for code, h in list(holdings.items()):
            s = stock[code]
            k = s["rowof"][di]
            if k < 0:
                continue
            c = s["c"][k]
            last_close[code] = c
            reason = ""
            if fib_stop:
                hh = (s["hh20"][k] if fib_p == 20 else s["hh60"][k])
                ll = (s["ll20"][k] if fib_p == 20 else s["ll60"][k])
                sup = ll + 0.382 * (hh - ll) if np.isfinite(hh) and np.isfinite(ll) else np.nan
                if np.isfinite(sup) and c < sup:
                    reason = "fib0.382支撑止损"
            elif stop_pct is not None and c <= h["ep"] * (1 - stop_pct):
                reason = f"硬止损-{stop_pct*100:.0f}%"
            if exit_mode == "llv":
                stopline = s["llv"][llv_p][k]
                if not reason and np.isfinite(stopline) and c < stopline:
                    reason = f"LLV{llv_p}破位"
            else:
                stopline = s["ma"][ma_p][k] * (1 + ma_shift) if np.isfinite(s["ma"][ma_p][k]) else np.nan
                if not reason and np.isfinite(stopline) and c < stopline:
                    reason = f"MA{ma_p}破位" if ma_shift == 0 else f"MA{ma_p}x{1+ma_shift:.2f}破位"
            if not reason and maxhold is not None and di - h["di"] >= maxhold:
                reason = f"满{maxhold}日"
            if reason and code not in pending_sell:
                pending_sell[code] = reason
        # 买入信号。W 臂：流动性名次序取满 npos 个合格候选（=原 E0 行为）。
        # F/wfactor 臂：先取「可交易流动性 Top10 池」（顶10个合格候选），池内过滤/排序/加权。
        # liq_mode="daily"：实盘无前视口径——先宽扫 200 名，再按当日 amt20 降序重排名。
        if len(holdings) < npos and di % rebal == offset:
            pool_cap = pool_n if (fib_entry or wfactor) else max(pool_n, npos)
            scan_cap = 200 if liq_mode == "daily" else pool_cap
            pool = []
            for cc in LIQ_RANK:
                if cc in holdings or cc in pending_sell:
                    continue
                s = stock[cc]
                k = s["rowof"][di]
                if k < 1 or s["amt20"][k] < amt_th or not np.isfinite(s["c"][k]) or s["c"][k] < 2:
                    continue
                if ema_filter is not None:
                    ef = s["ema"][ema_filter][k]
                    if not np.isfinite(ef) or s["c"][k] <= ef:
                        continue
                    if ema_filter == 144 and s["c"][k] <= s["ema"][169][k]:
                        continue   # 维加斯中层多头排列：c>EMA144 且 c>EMA169
                pool.append(cc)
                if len(pool) >= scan_cap:
                    break
            if liq_mode == "daily":
                pool.sort(key=lambda cc: -stock[cc]["amt20"][stock[cc]["rowof"][di]])
                pool = pool[:pool_cap]

            def fib_levels(cc):
                s = stock[cc]; k = s["rowof"][di]
                hh = (s["hh20"][k] if fib_p == 20 else s["hh60"][k])
                ll = (s["ll20"][k] if fib_p == 20 else s["ll60"][k])
                return hh, ll

            cands = pool
            if fib_entry == "filter50":
                keep = []
                for cc in pool:
                    hh, ll = fib_levels(cc)
                    if np.isfinite(hh) and np.isfinite(ll) and hh > ll:
                        c_k = stock[cc]["c"][stock[cc]["rowof"][di]]
                        if c_k <= ll + 0.5 * (hh - ll):   # 回撤过半=低吸区
                            keep.append(cc)
                cands = keep
            elif fib_entry == "sort382":
                def dist382(cc):
                    s = stock[cc]; k = s["rowof"][di]
                    hh, ll = fib_levels(cc)
                    if not (np.isfinite(hh) and np.isfinite(ll)) or hh <= ll:
                        return 9e9
                    sup = ll + 0.382 * (hh - ll)
                    return abs(s["c"][k] - sup) / sup
                cands = sorted(pool, key=dist382)
            elif wfactor is not None:
                keyf = {"vol": lambda cc: -stock[cc]["atr20"][stock[cc]["rowof"][di]],
                        "mom": lambda cc: -stock[cc]["mom20"][stock[cc]["rowof"][di]],
                        "amt": lambda cc: -stock[cc]["amt20"][stock[cc]["rowof"][di]]}[wfactor]
                cands = sorted(pool, key=keyf)

            picks = cands[:npos - len(holdings)]
            if wfactor is not None and picks:
                vals = []
                for cc in picks:
                    s = stock[cc]; k = s["rowof"][di]
                    v = (s["atr20"][k] if wfactor == "vol" else
                         s["mom20"][k] if wfactor == "mom" else s["amt20"][k])
                    v = (1.0 / v) if wfactor == "vol" else ((1.0 + v) if wfactor == "mom" else v)
                    vals.append(max(float(v), 1e-9) if np.isfinite(v) and v > 0 else 1e-9)
                tot = sum(vals)
                fracs = [v / tot for v in vals] if tot > 0 else [1 / len(picks)] * len(picks)
            else:
                fracs = [w_slot[min(i, npos - 1)] for i in range(len(picks))]
            pending_buy = list(zip(picks, fracs))
        pv = cash
        for code, h in holdings.items():
            pv += h["sh"] * last_close.get(code, h["ep"])
        eq.append(pv)
    eq = np.array(eq)
    r = np.diff(eq) / eq[:-1]
    total = eq[-1] / eq[0] - 1
    ann = (1 + total) ** (252 / max(1, len(eq))) - 1
    dd = (eq / np.maximum.accumulate(eq) - 1).min()
    sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0
    wins = [t for t in trades if t > 0]; losses = [t for t in trades if t <= 0]
    return {"arm": name, "total_pct": round(total * 100, 2), "ann_pct": round(ann * 100, 2),
            "mdd_pct": round(dd * 100, 1), "sharpe": round(sharpe, 3), "n_trades": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "payoff": round(float(np.mean(wins) / abs(np.mean(losses))), 2) if wins and losses else None,
            "reasons": reason_cnt, "eq": eq.tolist()}


ARMS = [
    # W 族：权重/仓位结构
    ("W1复刻E0",      dict(npos=5, shape="eq")),
    ("W3等权",        dict(npos=3, shape="eq")),
    ("W7等权",        dict(npos=7, shape="eq")),
    ("W10等权",       dict(npos=10, shape="eq")),
    ("W5线性",        dict(npos=5, shape="lin")),
    ("W5平方",        dict(npos=5, shape="sq")),
    ("W5几何08",      dict(npos=5, shape="geo08")),
    ("W5top2集中",    dict(npos=5, shape="top2")),
    ("W5波动率倒数",  dict(npos=5, shape="eq", wfactor="vol")),
    ("W5动量加权",    dict(npos=5, shape="eq", wfactor="mom")),
    ("W5流动性加权",  dict(npos=5, shape="eq", wfactor="amt")),
    # F 族：黄金分割融合（微信区间黄金分割口径：近P日高低点 0.382/0.5 位）
    ("F1低吸过滤0.5", dict(npos=5, shape="eq", fib_entry="filter50")),
    ("F2距离排序382", dict(npos=5, shape="eq", fib_entry="sort382")),
    ("F2P60排序382",  dict(npos=5, shape="eq", fib_entry="sort382", fib_p=60)),
    ("F3支撑止损382", dict(npos=5, shape="eq", fib_stop=True)),
    ("F2F3组合",      dict(npos=5, shape="eq", fib_entry="sort382", fib_stop=True)),
    # P 族：轮动节奏
    ("P10节奏",       dict(npos=5, shape="eq", rebal=10)),
    ("P40节奏",       dict(npos=5, shape="eq", rebal=40)),
]

if __name__ == "__main__":
    out = {}
    for name, kw in ARMS:
        r = run(name, **kw)
        r.pop("eq", None)
        out[name] = r
        print(f"[{name}] {r['total_pct']}% | 年化 {r['ann_pct']}% | 回撤 {r['mdd_pct']}% | "
              f"夏普 {r['sharpe']} | {r['n_trades']}笔 胜率{r['win_rate']}% 盈亏比{r['payoff']} | {r['reasons']}", flush=True)
        json.dump(out, open(R2 / "e0opt_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    out["_benchmark_HS300_pct"] = round(HS300_TOTAL, 2)
    json.dump(out, open(R2 / "e0opt_0912.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[基准 HS300] {HS300_TOTAL:.1f}% | 总耗时 {time.time()-t0:.0f}s", flush=True)
