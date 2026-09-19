# -*- coding: utf-8 -*-
"""valve_trackB 第3步: 四个尾盘阀的事件级对比（未来20交易日收益，口径与引擎一致）。

口径:
  信号日 T 收盘出清单 -> T+1 开盘买 -> 持有 20 交易日 -> T+21 开盘卖
  r = O[di+21]/O[di+1] - 1 - 0.0115   (1.15% 往返成本)
显著性:
  factor_infer.cluster_t / naive_t / daily_mean: 按天(di)聚类
  另加"按天配对"检验: 同日 通过组均值 - 被剔组均值, 对天序列做 t
"""
import os, sys, json
import numpy as np, pandas as pd

BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
BT = os.path.join(BASE, "backtest")
sys.path.insert(0, BT)
from factor_infer import cluster_t, naive_t, daily_mean  # noqa: E402

COST = 0.0115
HOLD = 20
VALVES = ["V1_强", "V2_不弱", "V3_反向", "V4_排带"]
DESC = {"V1_强": "14:30涨幅≥9.5% 且 14:45未封板",
        "V2_不弱": "14:45 ≥ 14:30×0.998（尾盘不走弱）",
        "V3_反向": "14:45 ≤ 14:30×0.998（尾盘回落才买）",
        "V4_排带": "14:30涨幅不落在[1%,3%)"}

D = pd.read_csv(os.path.join(BT, "valve_trackB_lists_valved.csv"), dtype={"code": str})
L = pd.read_csv(os.path.join(BT, "valve_trackB_lists.csv"), dtype={"code": str})

# ---- 未来 20 交易日收益（从面板 open 取，口径与引擎 fwdH 一致）----
import pickle
with open(os.path.join(BASE, "backtest", "oss_0913", "oss_panel_0913.pkl"), "rb") as fh:
    P = pickle.load(fh)
O = P["open"].astype(np.float64); ND, NC = O.shape
code2j = {str(c): j for j, c in enumerate(P["codes"])}
d2i = {str(d): i for i, d in enumerate(P["cal"])}
rows = []
for rec in D.itertuples():
    di = d2i.get(str(rec.date)); j = code2j.get(str(rec.code))
    r = np.nan
    if di is not None and j is not None and di + 1 + HOLD < ND:
        if np.isfinite(O[di + 1][j]) and np.isfinite(O[di + 1 + HOLD][j]) and O[di + 1][j] > 0:
            r = O[di + 1 + HOLD][j] / O[di + 1][j] - 1 - COST
    rows.append((di, j, r))
D["di"] = [x[0] for x in rows]; D["j"] = [x[1] for x in rows]; D["fwd20"] = [x[2] for x in rows]
n_pending = int((~np.isfinite(D["fwd20"])).sum())
D.to_csv(os.path.join(BT, "valve_trackB_lists_valved.csv"), index=False)

G = ND  # 聚类组数
def stat(r, day):
    r = np.asarray(r, float); day = np.asarray(day, int)
    m = np.isfinite(r)
    r, day = r[m], day[m]
    if r.size < 2:
        return dict(n=int(r.size), mean=np.nan, med=np.nan, win=np.nan, t_cluster=np.nan,
                    t_naive=np.nan, n_eff=np.nan, n_days=0, day_mean=np.nan, day_med=np.nan,
                    day_win=np.nan)
    nv = naive_t(r); cl = cluster_t(r, day, G); dm = daily_mean(r, day, G)
    infl = abs(nv["t"] / cl["t"]) if np.isfinite(cl["t"]) and cl["t"] != 0 else np.nan
    return dict(n=int(r.size), mean=float(r.mean() * 100), med=float(np.median(r) * 100),
                win=float((r > 0).mean() * 100), t_cluster=float(cl["t"]), t_naive=float(nv["t"]),
                n_eff=float(r.size / infl ** 2) if np.isfinite(infl) and infl > 0 else np.nan,
                n_days=int(dm.size), day_mean=float(dm.mean() * 100),
                day_med=float(np.median(dm) * 100), day_win=float((dm > 0).mean() * 100))

def paired_t_day(df_pass, df_rej):
    """按天配对: 每天 (通过组均值 - 被剔组均值), 对天序列做单样本 t。"""
    a = df_pass.groupby("di")["fwd20"].agg(["mean", "size"])
    b = df_rej.groupby("di")["fwd20"].agg(["mean", "size"])
    j = a.join(b, lsuffix="_p", rsuffix="_r", how="inner").dropna()
    d = j["mean_p"] - j["mean_r"]
    if len(d) < 2:
        return dict(k=len(d), diff_pct=np.nan, t=np.nan)
    se = d.std(ddof=1) / np.sqrt(len(d))
    return dict(k=int(len(d)), diff_pct=float(d.mean() * 100),
                t=float(d.mean() / se) if se > 0 else np.nan)

# ---- 基准组 ----
base = D[np.isfinite(D["fwd20"])]
st_all = stat(base["fwd20"], base["di"])
print("=" * 78)
print(f"清单 {len(D)} 条 / {L['date'].nunique()} 个调仓日 / {D['date'].min()} → {D['date'].max()}")
print(f"有分时 {int(D['has_minute'].sum())} 条, 缺分时 {int((D['has_minute'] == 0).sum())} 条"
      f"({(D['has_minute'] == 0).mean()*100:.1f}%)")
print(f"有未来20日收益 {int(np.isfinite(D['fwd20']).sum())} 条, 未到期/无价 {n_pending} 条")
print(f"不设阀全组: n={st_all['n']} 笔均 {st_all['mean']:+.3f}% 中位 {st_all['med']:+.3f}% "
      f"胜率 {st_all['win']:.1f}% t_cluster {st_all['t_cluster']:+.2f} t_naive {st_all['t_naive']:+.2f}")
print("=" * 78)

table = []
detail = {}
for v in VALVES:
    ok = D["has_minute"] == 1
    p = D[ok & (D[v] == 1) & np.isfinite(D["fwd20"])]
    r = D[ok & (D[v] == 0) & np.isfinite(D["fwd20"])]
    sp, sr = stat(p["fwd20"], p["di"]), stat(r["fwd20"], r["di"])
    pt = paired_t_day(p, r)
    tbl = dict(valve=v, desc=DESC[v],
               pass_n=sp["n"], pass_mean=sp["mean"], pass_med=sp["med"], pass_win=sp["win"],
               rej_n=sr["n"], rej_mean=sr["mean"], rej_med=sr["med"], rej_win=sr["win"],
               diff_pp=(sp["mean"] - sr["mean"]) if (np.isfinite(sp["mean"]) and np.isfinite(sr["mean"])) else np.nan,
               diff_vs_all_pp=(sp["mean"] - st_all["mean"]) if np.isfinite(sp["mean"]) else np.nan,
               t_cluster_pass=sp["t_cluster"], t_naive_pass=sp["t_naive"], n_eff_pass=sp["n_eff"],
               paired_diff_pp=pt["diff_pct"], paired_t=pt["t"], paired_k=pt["k"],
               rej_capital_share=(sr["n"] / (sp["n"] + sr["n"]) * 100) if (sp["n"] + sr["n"]) else np.nan,
               n_nodata=int((D["has_minute"] == 0).sum()))
    table.append(tbl); detail[v] = dict(pass_=sp, rej_=sr, paired=pt)

T = pd.DataFrame(table)
print(T[["valve", "pass_n", "pass_mean", "rej_n", "rej_mean", "diff_pp", "t_cluster_pass",
         "paired_t", "rej_capital_share", "n_nodata"]].to_string(index=False,
         float_format=lambda x: f"{x:+.3f}"))
print()
print("明细（含中位/胜率/日均口径）:")
for k in VALVES:
    d = detail[k]; p = d["pass_"]; r = d["rej_"]
    _t = T[T["valve"] == k].iloc[0]
    print(f"  {k:<10} 通过 n={p['n']:>4} 笔均{p['mean']:+.3f}% 中位{p['med']:+.3f}% 胜率{p['win']:.1f}% "
          f"t_clust{p['t_cluster']:+.2f} | 被剔 n={r['n']:>4} 笔均{r['mean']:+.3f}% 中位{r['med']:+.3f}% 胜率{r['win']:.1f}% "
          f"| 按天配对 {d['paired']['diff_pct']:+.3f}pp t={d['paired']['t']:+.2f}(k={d['paired']['k']}天)")
    print(f"             ▸ 口径背离: 按笔等权差值 {_t['diff_pp']:+.3f}pp vs 按天配对差值 {d['paired']['diff_pct']:+.3f}pp")
    print(f"             通过组按天口径: 日均{p['day_mean']:+.3f}% 日中位{p['day_med']:+.3f}% 上涨天占比{p['day_win']:.1f}% "
          f"n_eff={p['n_eff']:.0f} | 全组按天: 日均{st_all['day_mean']:+.3f}% 上涨天占比{st_all['day_win']:.1f}%")

# ---- V1 可达性诊断（阈值是否根本没样本）----
gk = D.loc[D["has_minute"] == 1, "g1430"]
print("\nV1 可达性 (清单内 14:30 涨幅 g1430 分布, n=%d):" % gk.notna().sum())
print("  分位: " + " ".join(f"p{q}={gk.quantile(q/100)*100:.2f}%" for q in (50, 90, 99)) +
      f" max={gk.max()*100:.2f}%")
for th in (0.03, 0.05, 0.07, 0.095):
    print(f"  g1430 >= {th*100:.1f}% 的条数: {int((gk >= th).sum())}")
lim_sealed = int(((D["has_minute"] == 1) & (D["p1445"] >= D["prev_close"] * (1 + D["limit"]) - 1e-3)).sum())
print(f"  14:45 已封板(>=涨停价)条数: {lim_sealed}")

out = dict(lists=dict(n=int(len(D)), n_dates=int(L["date"].nunique()), first=str(D["date"].min()),
                      last=str(D["date"].max()), n_nodata_minute=int((D["has_minute"] == 0).sum()),
                      n_pending_fwd=int(n_pending)),
           baseline=st_all, table=table, detail=detail,
           note="清单为该调仓日的目标 topN；被剔组=清单内被阀剔除的标的；资金占比按等份金额=条数占比")
json.dump(out, open(os.path.join(BT, "valve_trackB_summary.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1, default=float)
print("\nsaved valve_trackB_summary.json")
