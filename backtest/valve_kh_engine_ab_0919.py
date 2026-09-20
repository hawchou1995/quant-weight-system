# -*- coding: utf-8 -*-
"""KHunter V2 咬合率 + 引擎内 A/B（接生产动态出场）。

A/B 口径（与生产对齐，逐条注明）：
- 事件集：生产四道门 252 笔（15 策略 ∧ 分域 RSI 门 ∧ 熊市低价 ≥3 ∧ amt20≥3e7 ∧ 剔ST退 ∧ 主板）
- 入场：信号日 T 收盘 → **T+1 开盘买**（整手、20bp 滑点、佣金 2.5bp 最低 5 元）
- 出场（生产动态）：**分域 RSI**——熊 >59 / 牛 >75 / 弱牛 >80；**hold25**（距入场 ≥25 交易日在次日开盘卖）
  （⚠ 生产弱牛域用 hold15，本模拟统一 hold25，如实申报）
- 仓位：N=5 槽 · 2 万/仓 · 10 万起点 · 满仓跳过 · 资金不足跳过（不补位、现金滞留）
- 阀 V2：信号日 T 的 14:45 相对 14:30 回落 >0.2% 者 **次日不买**（不满仓）
- 咬合率（本项目定义：效应强度 × 动作重叠率）= 被剔比例 × (被剔笔均 与 保留笔均 之差)
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import khunter_all_strategies_backtest as K  # noqa: E402

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest"
DATA_FULL = BASE / "data_full"
CASH0, PER, N_SLOTS, HOLD_MAX = 100000.0, 20000.0, 5, 25
COMM, TAX, SLIP, MIN_COMM = 0.00025, 0.0005, 0.0020, 5.0
SELL_RSI = {"bear": 59, "bull": 75, "weak": 80}
t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:7.1f}s]", *a, flush=True)


def load_ctx(codes):
    """code → (dates, open, close, rsi, regime) 只建一次"""
    idx = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
    idx["ma250"] = idx["close"].rolling(250, min_periods=200).mean()
    idx["mom20"] = idx["close"] / idx["close"].shift(20) - 1
    REG = {}
    for x in idx.itertuples():
        bear = x.close < x.ma250 if pd.notna(x.ma250) else False
        REG[x.date] = "bear" if bear else ("bull" if (pd.notna(x.mom20) and x.mom20 > 0.02) else "weak")
    cache = pd.read_pickle(K.CACHE)
    ctx = {}
    for code in codes:
        key = "sh" + code if code[0] in "659" else "sz" + code
        df = cache.get(key)
        if df is None or len(df) < 300:
            continue
        d = df[["open", "high", "low", "close", "volume"]].copy()
        d.index.name = None
        d["date"] = d.index
        d = d.sort_values("date").reset_index(drop=True)
        r = K.calc_indicators(d)
        ctx[code] = (d["date"].dt.strftime("%Y-%m-%d").tolist(),
                     d["open"].to_numpy(), d["close"].to_numpy(),
                     np.nan_to_num(r["rsi"].to_numpy()), REG)
    return ctx, REG


def sim(ev, ctx, REG, use_valve, tag):
    cal = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})["date"].tolist()
    byday = {}
    for x in ev:
        byday.setdefault(x["date"], []).append(x)
    pos, cash, navs, dates = [], CASH0, [], []
    n_entry = n_exit = n_slot = n_cash = 0
    invested = []
    for di in range(1, len(cal)):
        d, prev = cal[di], cal[di - 1]
        keep = []
        for p in pos:
            p["held"] += 1
            dd, op, cl, rsi, _ = ctx[p["code"]]
            j = p["pos"] + p["held"]
            if j >= len(dd):
                continue
            regime = p["regime"]
            try:
                j0 = dd.index(prev)
            except ValueError:
                keep.append(p)
                continue
            cur_rsi = rsi[j0]
            if cur_rsi > SELL_RSI[regime] or p["held"] >= HOLD_MAX:
                sell = op[j] * (1 - SLIP)
                amt = p["sh"] * sell
                cash += amt - max(amt * COMM, MIN_COMM) - amt * TAX
                n_exit += 1
            else:
                keep.append(p)
        pos = keep
        for x in byday.get(prev, []):
            if use_valve and not x["pass_v2"]:
                continue
            dd, op, cl, rsi, _ = ctx[x["code"]]
            try:
                j = dd.index(prev) + 1
            except ValueError:
                continue
            if j >= len(dd):
                continue
            buy = op[j] * (1 + SLIP)
            if buy <= 0 or len(pos) >= N_SLOTS:
                if len(pos) >= N_SLOTS:
                    n_slot += 1
                continue
            lots = int(np.floor(min(PER, cash) / (buy * 100)))
            if lots < 1:
                n_cash += 1
                continue
            amt = lots * 100 * buy
            fee = max(amt * COMM, MIN_COMM)
            if amt + fee > cash:
                lots -= 1
                if lots < 1:
                    n_cash += 1
                    continue
                amt = lots * 100 * buy
                fee = max(amt * COMM, MIN_COMM)
            cash -= (amt + fee)
            pos.append({"code": x["code"], "sh": lots * 100, "held": 0, "pos": dd.index(prev),
                        "regime": x["regime"]})
            n_entry += 1
        mv = sum(p["sh"] * (cl[dd_index(ctx, p, prev)] if False else 0.0) for p in pos)
        # mark：用上一交易日收盘近似（前复权同口径，误差 < 1 日漂移）
        m = 0.0
        for p in pos:
            dd, op, cl, rsi, _ = ctx[p["code"]]
            try:
                j = dd.index(prev)
            except ValueError:
                continue
            jj = min(j, len(cl) - 1)
            m += p["sh"] * cl[jj]
        navs.append(cash + m)
        dates.append(d)
        invested.append(m / (cash + m) if (cash + m) > 0 else 0.0)
    nav = pd.Series(navs, index=pd.to_datetime(dates))
    nav = nav[nav.index >= pd.Timestamp("2021-01-04")]
    ret = nav.pct_change().dropna()
    yrs = len(nav) / 244.0
    ann = (nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1
    sh = ret.mean() / ret.std() * np.sqrt(244) if ret.std() > 0 else np.nan
    mdd = float((nav / nav.cummax() - 1).min())
    inv = float(np.mean(invested))
    print(f"  {tag:<12} 期末 {nav.iloc[-1]/CASH0:>5.3f}  年化 {ann*100:>6.2f}%  夏普 {sh:>5.2f}  "
          f"回撤 {mdd*100:>6.2f}%  入场 {n_entry:>4}  出场 {n_exit:>4}  满仓跳过 {n_slot:>3}  钱不够 {n_cash:>3}  "
          f"日均投入 {inv*100:>4.1f}%")
    return {"ann_pct": float(ann * 100), "sharpe": float(sh), "mdd_pct": float(mdd * 100),
            "final": float(nav.iloc[-1] / CASH0), "n_entry": n_entry, "n_exit": n_exit,
            "skipped_slots": n_slot, "skipped_cash": n_cash, "mean_invested": inv}


def dd_index(ctx, p, prev):
    return 0


if __name__ == "__main__":
    ev = pd.read_csv(OUT / "valve_kh_rows.csv", dtype={"code": str, "date": str})
    ev = ev[np.isfinite(ev["fwd20"].to_numpy())].copy()
    ev["pass_v2"] = ev["pull"].to_numpy() >= -0.002
    ev["regime"] = ev["regime"].fillna("bear")
    codes = sorted(set(ev["code"]))
    log(f"事件 {len(ev)} 笔 / {ev['date'].nunique()} 天；加载 {len(codes)} 只标的数据…")
    ctx, REG = load_ctx(codes)
    log(f"数据上下文 {len(ctx)} 只")
    records = ev.to_dict("records")
    print("\n=== KHunter 引擎内 A/B（生产动态出场：分域 RSI 59/75/80 + hold25 · N=5 · 2万/仓 · 20bp）===")
    res = {}
    res["B0 无阀"] = sim(records, ctx, REG, False, "B0 无阀")
    res["V2 不弱门"] = sim(records, ctx, REG, True, "V2 不弱门")
    # 咬合率
    r = ev["fwd20"].to_numpy()
    kept = np.isfinite(r) & ev["pass_v2"].to_numpy()
    drop = np.isfinite(r) & (~ev["pass_v2"].to_numpy())
    drop_ratio = drop.mean()
    diff = float(r[kept].mean() - r[drop].mean())
    bite = drop_ratio * diff * 100
    print(f"\n=== 咬合率（本项目定义：效应强度 × 动作重叠率）===")
    print(f"  动作重叠率（被剔比例）= {drop_ratio*100:.1f}%（{drop.sum()}/{len(ev)}）")
    print(f"  效应强度（保留−被剔笔均）= {diff*100:+.3f}pp")
    print(f"  **咬合度 = {bite:+.3f} pp/笔**，占全池均值（{r[kept|drop].mean()*100:.3f}%）的 "
          f"{bite/(r[kept|drop].mean()*100)*100:.1f}% → 门槛 2% ⇒ {'PASS' if bite/(r[kept|drop].mean()*100)*100 >= 2 else 'FAIL'}")
    b, v = res["B0 无阀"], res["V2 不弱门"]
    print(f"\n  A/B 差值：年化 {v['ann_pct']-b['ann_pct']:+.2f}pp ｜ 夏普 {v['sharpe']-b['sharpe']:+.3f} ｜ "
          f"回撤 {v['mdd_pct']-b['mdd_pct']:+.2f}pp ｜ 入场 {v['n_entry']-b['n_entry']:+d} 笔")
    out = {"bite_pp_per_trade": float(bite), "bite_ratio_pct": float(bite / (r[kept | drop].mean() * 100) * 100),
           "drop_ratio_pct": float(drop_ratio * 100), "effect_pp": diff * 100, "arms": res,
           "note": "生产动态出场；⚠ 弱牛域 hold 统一 25（生产为 15，需申报）；mark 用上一交易日收盘近似"}
    (OUT / "valve_kh_engine_ab.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log("落盘 valve_kh_engine_ab.json")
