# -*- coding: utf-8 -*-
"""R-valve-0919 · KHunter 线：生产口径事件集 + 四个尾盘阀（事件级 + 简化组合级）。

生产四道门（与 build_short_pool.py 对齐，逐条在代码里注明）：
  15 策略任一命中 ∧ 分域 RSI(熊<35/牛<32/弱牛<32) ∧ 熊市低价≥3 ∧ amt20≥3e7 ∧ 剔 ST/退 ∧ 主板(sh60/sz00)
  （未实现：命中≥3 回避 —— 属排序层微调，如实申报）
事件收益：T+1 开盘买 → 持有 20 交易日收盘卖，往返成本 1.15%（= khunter_all_strategies_backtest 口径）

四个阀（观测 = 信号日 T 的 14:45，PIT 干净；进场仍 T+1 开盘）：
  V1 强势门  : 14:30 涨幅 ≥9.5% 且 14:45 未封板
  V2 不弱门  : 14:45 ≥ 14:30×0.998（原帖 F2 正向读法）
  V3 反向    : 14:45 ≤ 14:30×0.998（回落者才买）
  V4 排除带  : 14:30 涨幅 ∉ [1%,3%)
对照 B0 = 不设阀
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import khunter_all_strategies_backtest as K  # noqa: E402
from t293_minute_0919 import pv  # noqa: E402
from t293_l2_real_list_0919 import limit_pct  # noqa: E402
from factor_infer import cluster_t, naive_t, daily_mean  # noqa: E402

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest"
HOLD = 20
COST = 0.0115
t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:7.1f}s]", *a, flush=True)


def build_events():
    f = OUT / "valve_kh_events.csv"
    if f.exists():
        return pd.read_csv(f, dtype={"code": str, "date": str})
    idx = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
    idx["ma250"] = idx["close"].rolling(250, min_periods=200).mean()
    idx["ma20"] = idx["close"].rolling(20, min_periods=15).mean()
    idx["bear"] = idx["close"] < idx["ma250"]
    idx["mom20"] = idx["close"] / idx["close"].shift(20) - 1
    BE = idx.set_index("date")["bear"].to_dict()
    MOM = idx.set_index("date")["mom20"].to_dict()
    try:
        nh = pd.read_csv(BASE / "data_fundamental" / "name_hist.csv", dtype=str)
        log(f"name_hist 列 {list(nh.columns)[:6]} 行 {len(nh)}")
        key = "code" if "code" in nh.columns else nh.columns[0]
        nmcol = [c for c in nh.columns if c.lower() in ("name", "stock_name", "名称")] or [nh.columns[1]]
        nh["bad"] = nh[nmcol[0]].fillna("").str.contains("ST|退")
        BAD = set(nh.loc[nh["bad"], key].astype(str).str.replace(r"^(sh|sz|bj)", "", regex=True))
    except Exception as e:
        log("name_hist 不可用 → 用实时名表（申报：ST 判定非 PIT）", repr(e)[:60])
        nm = json.load(open(BASE / "data_full_names.json", encoding="utf-8"))
        BAD = {k.replace("sh", "").replace("sz", "").replace("bj", "") for k, v in nm.items()
               if ("ST" in v) or ("退" in v)}
    cache = pd.read_pickle(K.CACHE)
    rows = []
    n_stock = 0
    for code, df in cache.items():
        s = code if isinstance(code, str) else str(code)
        if not s.startswith(("sh60", "sz00")):     # 主板门
            continue
        d = df[["open", "high", "low", "close", "volume", "amount"]].copy()
        if "amt20" in df.columns:
            d["amt20"] = df["amt20"].values
        d.index.name = None
        d["date"] = d.index
        d = d.sort_values("date").reset_index(drop=True)
        if len(d) < 320:
            continue
        r = K.calc_indicators(d)
        sig = pd.Series(False, index=d.index)
        for _n, _fn in K.SIGNALS.items():
            try:
                sig |= _fn(r).fillna(False)
            except Exception:
                pass
        ds = d["date"].dt.strftime("%Y-%m-%d").values
        c6 = s[2:]
        for i in np.flatnonzero(sig.values):
            dt = ds[i]
            if dt < "2021-01-04" or i + HOLD + 2 >= len(d):
                continue
            if c6 in BAD:                                    # 剔 ST/退
                continue
            bear = BE.get(dt, False)
            mom = MOM.get(dt, np.nan)
            weak = (not bear) and not (pd.notna(mom) and mom > 0.02)
            osl = 35 if bear else 32                          # 分域 RSI 门
            low = 3.0 if bear else None                       # 熊市低价门
            if not (r["rsi"].values[i] < osl):
                continue
            if low is not None and d["close"].values[i] < low:
                continue
            a20 = float(d["amt20"].values[i]) if "amt20" in d.columns and np.isfinite(d["amt20"].values[i]) else np.nan
            if not np.isfinite(a20) or a20 < 3e7:             # 流动性门
                continue
            entry = float(d["open"].values[i + 1])
            exit_ = float(d["close"].values[i + HOLD])
            rows.append({"code": c6, "date": dt, "regime": "bear" if bear else ("weak" if weak else "bull"),
                         "rsi": float(r["rsi"].values[i]), "fwd20": exit_ / entry - 1 - COST if entry > 0 else np.nan})
        n_stock += 1
        if n_stock % 1000 == 0:
            log(f"  扫描 {n_stock} 票，事件 {len(rows)}")
    ev = pd.DataFrame(rows).sort_values(["date", "code"]).reset_index(drop=True)
    ev.to_csv(f, index=False, encoding="utf-8")
    log(f"生产口径事件集：{len(ev)} 笔 / {ev['date'].nunique()} 天 / {ev['code'].nunique()} 只 → {f.name}")
    return ev


def fetch_valve(ev):
    f = OUT / "valve_kh_rows.csv"
    if f.exists():
        return pd.read_csv(f, dtype={"code": str, "date": str})
    recs, fail = [], 0
    n = len(ev)
    for i, x in enumerate(ev.itertuples(), 1):
        m = pv(str(x.code).zfill(6), int(str(x.date).replace("-", "")))
        if not m or not m.get("prev_close"):
            fail += 1
            continue
        pc = m["prev_close"]
        g = m["p1430"] / pc - 1
        lim = limit_pct(str(x.code).zfill(6))
        recs.append({"code": str(x.code).zfill(6), "date": x.date, "regime": x.regime, "fwd20": x.fwd20,
                     "g": g, "pull": m["p1445"] / m["p1430"] - 1,
                     "sealed": bool(m["p1445"] >= pc * (1 + lim) - 1e-3)})
        if i % 100 == 0:
            log(f"  分时 {i}/{n}（失败 {fail}）ETA {(time.time()-t0)/i*(n-i):.0f}s")
    d = pd.DataFrame(recs)
    d.to_csv(f, index=False, encoding="utf-8")
    log(f"尾盘状态：成功 {len(d)}/{n}（失败 {fail}）")
    return d


def report(d, tag="KHunter"):
    days = sorted(d["date"].unique()); dm = {x: i for i, x in enumerate(days)}
    didx = np.array([dm[x] for x in d["date"]]); G = len(days)
    r = d["fwd20"].to_numpy()
    valves = {
        "B0 无阀": np.ones(len(d), bool),
        "V1 强势门": (d["g"].to_numpy() >= 0.095) & (~d["sealed"].to_numpy()),
        "V2 不弱门": d["pull"].to_numpy() >= -0.002,
        "V3 反向": d["pull"].to_numpy() <= -0.002,
        "V4 排除带": ~((d["g"].to_numpy() >= 0.01) & (d["g"].to_numpy() < 0.03)),
    }
    print(f"\n===== {tag} 尾盘阀（事件级 · T+1 开盘买 → 持 {HOLD} 日收盘卖 · 往返 {COST*100:.2f}%）=====")
    print(f"  {'阀':<12}{'通过n':>7}{'通过笔均%':>11}{'胜率%':>7}{'t_cluster':>10}"
          f"{'被剔n':>7}{'被剔笔均%':>11}{'差值pp':>9}{'按天差值pp':>11}{'按天t':>8}")
    out = {}
    for name, m in valves.items():
        ok = np.isfinite(r) & m
        no = np.isfinite(r) & (~m)
        if ok.sum() < 5:
            print(f"  {name:<12}{ok.sum():>7}  —— 样本不足(<5)，判**不可判定**")
            out[name] = {"n": int(ok.sum()), "verdict": "不可判定"}
            continue
        c = cluster_t(r[ok], didx[ok], G)
        diff = float(r[ok].mean() - r[no].mean()) * 100 if no.sum() >= 5 else np.nan
        # 按天配对：同一天 通过组均值 − 被剔组均值
        dm1 = daily_mean(r[ok], didx[ok], G) if ok.sum() else np.array([])
        pair = np.nan
        if no.sum() >= 5 and dm1.size:
            d2 = daily_mean(r[no], didx[no], G)
            common = set(np.unique(didx[ok])) & set(np.unique(didx[no]))
            if len(common) >= 5:
                a = np.array([r[ok][didx[ok] == j].mean() for j in common])
                b = np.array([r[no][didx[no] == j].mean() for j in common])
                pair = float((a - b).mean()) * 100
                tc = cluster_t(a - b, np.arange(len(common)), len(common))["t"]
            else:
                tc = np.nan
        else:
            tc = np.nan
        print(f"  {name:<12}{ok.sum():>7}{r[ok].mean()*100:>11.3f}{(r[ok]>0).mean()*100:>7.1f}{c['t']:>10.2f}"
              f"{no.sum():>7}{(r[no].mean()*100 if no.sum() else float('nan')):>11.3f}"
              f"{diff:>9.3f}{pair:>11.3f}{tc:>8.2f}")
        out[name] = {"n": int(ok.sum()), "kept_mean_pct": float(r[ok].mean() * 100),
                     "kept_win": float((r[ok] > 0).mean() * 100), "t_cluster": float(c["t"]),
                     "dropped_n": int(no.sum()),
                     "dropped_mean_pct": float(r[no].mean() * 100) if no.sum() else None,
                     "diff_pp": diff, "pair_day_diff_pp": pair}
    # 分年（B0 与 V1/V4）
    print(f"\n  --- 分年（笔均%）---")
    yr = d["date"].str[:4].to_numpy()
    for name, m in valves.items():
        if name == "B0 无阀":
            continue
        line = [f"  {name:<12}"]
        for y in ("2021", "2022", "2023", "2024", "2025", "2026"):
            mm = np.isfinite(r) & m & (yr == y)
            line.append(f"{y}:{(r[mm].mean()*100 if mm.sum()>=5 else float('nan')):>6.1f}(n{mm.sum():>3})")
        print("".join(line))
    (OUT / "valve_kh_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    ev = build_events()
    print("事件集分年:", ev.groupby(ev["date"].str[:4]).size().to_dict())
    print("分域:", ev.groupby("regime").size().to_dict())
    d = fetch_valve(ev)
    report(d)
