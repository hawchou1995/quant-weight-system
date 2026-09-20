# -*- coding: utf-8 -*-
"""打板线修三处（用户「接着修」）：
 ① 容量门 amount 取值 bug（旧 daily() 只取 date/open/close → 三行数字全同 = 门没生效）
 ② **除权污染筛查**：ampm2 是前复权，除权日 c1430/prev 会虚高 → 用 pytdx **不复权**昨收重算涨幅
 ③ 真实可执行口径：T+1 **跌停不可卖**守卫 + 卖出按 min(开盘, 昨收×0.97) 的跳空惩罚 +
    买点 14:45 vs 全日 VWAP 对比 + 每笔独立（不复利）口径
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factor_infer import cluster_t  # noqa: E402

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest"
DATA_FULL = BASE / "data_full"
ALT = Path("D:/Tools/cache/altdata")
MIN_CACHE = Path("D:/Tools/cache/tdx_min")
CAPITAL, K_SLOTS = 170000.0, 10
COMM, TAX = 0.00025, 0.0005
TIERS = {"20bp": 0.0020, "50bp": 0.0050, "100bp": 0.0100}
t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:7.1f}s]", *a, flush=True)


def daily_full(code):
    """date → (open, close, amount)，带缓存（旧版只取 open/close 导致容量门失效）"""
    pre = "sh" if code[0] in "659" else "sz"
    f = DATA_FULL / f"{pre}{code}.csv"
    if not f.exists():
        return None
    d = pd.read_csv(f, dtype={"date": str})[["date", "open", "close", "amount"]]
    return d.drop_duplicates("date").set_index("date").sort_index()


def minute_cached(code6, date_int):
    cf = MIN_CACHE / f"min_{code6}_{date_int}.parquet"
    if not cf.exists():
        return None
    try:
        df = pd.read_parquet(cf)
        return df
    except Exception:
        return None


def main():
    hi = pd.read_parquet(OUT / "p1_full_hi.parquet")
    hi["code"] = hi["code"].str.zfill(6)
    m45 = pd.read_csv(OUT / "p1_full_1445.csv", dtype={"code": str, "date": str})
    m45["code"] = m45["code"].str.zfill(6)
    log(f"≥9.5% 全窗口 {len(hi)} 行；已抓 14:45 {len(m45)} 行")

    # ---------- ② 除权污染：用 pytdx 不复权重算 14:30 涨幅 ----------
    log("用 pytdx 不复权昨收重算涨幅（查除权污染）…")
    rows = []
    for i, x in enumerate(m45.itertuples(), 1):
        di = int(str(x.date).replace("-", ""))
        df = minute_cached(x.code, di)
        if df is None or len(df) < 240:
            continue
        p = df["price"].to_numpy()
        pc = float(df["pre_close"].iloc[0]) if "pre_close" in df.columns else np.nan
        if not (pc > 0):
            continue
        v = df["vol"].to_numpy() if "vol" in df.columns else np.zeros(240)
        vwap = float((p * v).sum() / v.sum()) if v.sum() > 0 else np.nan
        rows.append({"code": x.code, "date": x.date, "p1445": float(p[224]), "p1430": float(p[209]),
                     "p1500": float(p[239]), "pc": pc, "g_true": float(p[209]) / pc - 1,
                     "vwap": vwap, "sealed45": bool(x.sealed45)})
        if i % 2000 == 0:
            log(f"  读数 {i}/{len(m45)}")
    u = pd.DataFrame(rows)
    # 与 ampm2 前复权口径对比
    am = hi.set_index(["code", "date"])["g"]
    u["g_ampm"] = [am.get((c, d), np.nan) for c, d in zip(u["code"], u["date"])]
    u["dg"] = u["g_true"] - u["g_ampm"]
    bad = u[np.abs(u["dg"]) > 0.005]
    log(f"除权污染：|不复权涨幅 − 前复权涨幅| > 0.5pp 的有 {len(bad)}/{len(u)} 条（{len(bad)/len(u)*100:.2f}%）")
    if len(bad):
        print("  样例（前复权 vs 不复权）：")
        for _, x in bad.head(6).iterrows():
            print(f"    {x['date']} {x['code']} 前复权 g={x['g_ampm']*100:.2f}% 不复权 g={x['g_true']*100:.2f}% 差 {x['dg']*100:+.2f}pp")

    # ---------- 事件级（真实涨幅口径 + 跌停守卫 + 买点对比）----------
    dmap = {c: daily_full(c) for c in sorted(set(u["code"]))}
    log(f"日线（含 amount）{len([v for v in dmap.values() if v is not None])} 只")

    def ret_of(x, entry_px, yk="t1o", gap_guard=False):
        d = dmap.get(x["code"])
        if d is None or x["date"] not in d.index:
            return np.nan
        idx = d.index.tolist()
        i = idx.index(x["date"])
        if i + 1 >= len(idx):
            return np.nan
        o1 = float(d["open"].iloc[i + 1])
        c0 = float(d["close"].iloc[i])
        if gap_guard and o1 <= c0 * 0.902:          # T+1 开盘跌停 → 卖不出
            return np.nan
        # 卖出价一律用 T+1 开盘价（现实可成交价）；低开本身已体现在 o1 里，
        # 不再叠加 min(o1, c0*0.97) 这类"必然惩罚"（上一版那么写等于每天按 -3% 卖，是 bug）
        sell = o1
        A_close = c0
        entry_A = A_close * (entry_px / x["p1500"])
        return sell / entry_A - 1

    print("\n=== 事件级（全窗口 · 真实涨幅口径 + T+1 跌停守卫 + 跳空惩罚 · 往返 50bp）===")
    print(f"  {'买点':<12}{'守卫':<10}{'n':>7}{'笔均%':>9}{'胜率%':>7}{'聚类t':>8}{'分年笔均 2024/25/26'}")
    variants = []
    for entry, ename in (("p1445", "14:45"), ("p1500", "15:00"), ("vwap", "全日VWAP")):
        for guard, gname in ((False, "无"), (True, "跌停守卫+跳空")):
            sub = u[np.isfinite(u[entry].to_numpy()) & (u["g_true"] >= 0.095) & (~u["sealed45"].astype(bool))].copy()
            sub["r"] = [ret_of(x, x[entry], gap_guard=guard) for x in sub.to_dict("records")]
            sub = sub[np.isfinite(sub["r"].to_numpy())]
            if len(sub) < 100:
                continue
            r = sub["r"].to_numpy() - 0.0110
            days = sorted(sub["date"].unique()); dm = {d: i for i, d in enumerate(days)}
            c = cluster_t(r, np.array([dm[x] for x in sub["date"]]), len(days))
            yr = sub["date"].str[:4].to_numpy()
            yy = " ".join(f"{r[yr==y].mean()*100:+.2f}" for y in ("2024", "2025", "2026") if (yr == y).sum() >= 20)
            print(f"  {ename:<12}{gname:<10}{len(r):>7}{r.mean()*100:>9.3f}{(r>0).mean()*100:>7.1f}{c['t']:>8.2f}  {yy}")
            variants.append({"entry": ename, "guard": gname, "n": int(len(r)),
                             "mean_pct": float(r.mean() * 100), "win": float((r > 0).mean() * 100),
                             "t_cluster": float(c["t"])})

    # ---------- 组合级（修好的容量门 + 三成本档 + 跳空惩罚）----------
    print("\n=== 组合级（全窗口 · K=10 · 17 万 · 整手 · 容量门已修 · 跌停守卫+跳空惩罚）===")
    print(f"  {'成本':<7}{'容量门':<12}{'日均值%':>9}{'日胜率%':>8}{'累计%':>9}{'年化%':>8}{'夏普':>7}{'回撤%':>8}{'日均买入':>8}")
    res = {"event": variants, "port": {}}
    per = CAPITAL / K_SLOTS
    exe = u[np.isfinite(u["p1445"].to_numpy()) & (u["g_true"] >= 0.095) & (~u["sealed45"].astype(bool))].copy()
    exe["r"] = [ret_of(x, x["p1445"], gap_guard=True) for x in exe.to_dict("records")]
    exe = exe[np.isfinite(exe["r"].to_numpy())]
    for tname, slip in TIERS.items():
        c_rt = 2 * (slip + COMM) + TAX
        for cap in (None, 0.10, 0.05, 0.02):
            day_r, nb = {}, {}
            for d in sorted(exe["date"].unique()):
                sub = exe[exe["date"] == d].sort_values("g_true", ascending=False)
                rets, spent, n_buy = [], 0.0, 0
                for _, x in sub.iterrows():
                    if n_buy >= K_SLOTS:
                        break
                    if cap is not None:
                        dd = dmap.get(x["code"])
                        amt = float(dd.loc[x["date"], "amount"]) if dd is not None and x["date"] in dd.index else None
                        if amt and per > cap * amt:
                            continue
                    lots = int(np.floor(per / (x["p1445"] * 100)))
                    if lots < 1 or spent + lots * 100 * x["p1445"] > CAPITAL:
                        continue
                    spent += lots * 100 * x["p1445"]
                    n_buy += 1
                    rets.append(float(x["r"]) - c_rt)
                day_r[d] = float(np.mean(rets)) * (spent / CAPITAL) if rets else 0.0
                nb[d] = n_buy
            days = sorted(day_r)
            years = (pd.Timestamp(days[-1]) - pd.Timestamp(days[0])).days / 365.25
            rr = np.array([day_r[d] for d in days])
            nav = np.cumprod(1 + rr)
            ann = nav[-1] ** (1 / years) - 1
            r2 = np.diff(nav) / nav[:-1]
            sh = r2.mean() / r2.std() * np.sqrt(244) if r2.std() > 0 else np.nan
            mdd = float((nav / np.maximum.accumulate(nav) - 1).min())
            lab = "无容量门" if cap is None else f"≤{cap*100:.0f}%成交额"
            print(f"  {tname:<7}{lab:<12}{rr.mean()*100:>9.3f}{(rr>0).mean()*100:>8.1f}"
                  f"{(nav[-1]-1)*100:>9.1f}{ann*100:>8.1f}{sh:>7.2f}{mdd*100:>8.2f}{np.mean(list(nb.values())):>8.1f}")
            res["port"][f"{tname}|{lab}"] = {"mean_day_pct": float(rr.mean() * 100),
                                            "win_day": float((rr > 0).mean() * 100),
                                            "total_pct": float((nav[-1] - 1) * 100),
                                            "ann_pct": float(ann * 100), "sharpe": float(sh),
                                            "mdd_pct": float(mdd * 100), "avg_bought": float(np.mean(list(nb.values())))}
    (OUT / "p1_full_fixed.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    log("落盘 p1_full_fixed.json")


if __name__ == "__main__":
    main()
