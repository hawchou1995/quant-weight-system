# -*- coding: utf-8 -*-
"""sv2: fetch delisted bars from Tencent (qfq) + cross-validate against data_full on live names."""
import json, pathlib, time, numpy as np, pandas as pd, akshare as ak
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
lst = json.loads((S/"sv_delisted_list.json").read_text(encoding="utf-8"))
print("待取 %d 只" % len(lst))
def fetch(sym):
    for kw in (dict(symbol=sym, start_date="20140101", end_date="20260930", adjust="qfq"),
               dict(symbol=sym, adjust="qfq"), dict(symbol=sym)):
        try:
            df = ak.stock_zh_a_hist_tx(**kw)
            if df is not None and len(df): return df, kw
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, str(e)[:60]); continue
    return None, last
rows=[]; fails=[]; t0=time.time()
for i, rec in enumerate(lst):
    sym = rec["sym"]
    df, info = fetch(sym)
    if df is None:
        fails.append((sym, rec["name"], info)); continue
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    d["sym"] = sym
    keepcols = [c for c in ("sym","date","open","high","low","close","volume","amount") if c in d.columns]
    rows.append(d[keepcols])
    if (i+1) % 40 == 0: print("  %d/%d  %.0fs  fails=%d" % (i+1, len(lst), time.time()-t0, len(fails)), flush=True)
print("取数完成 %.0fs ; 成功 %d, 失败 %d" % (time.time()-t0, len(rows), len(fails)))
for f in fails[:15]: print("   FAIL", f)
if rows:
    allb = pd.concat(rows, ignore_index=True)
    allb = allb.drop_duplicates(subset=["sym","date"]).sort_values(["sym","date"])
    print("总行数 %d ; 覆盖 %d 只 ; 日期范围 %s ~ %s" % (len(allb), allb["sym"].nunique(), allb["date"].min(), allb["date"].max()))
    for c in ("open","high","low","close","volume","amount"):
        allb[c] = pd.to_numeric(allb[c], errors="coerce")
    OUTD = R/"backtest/_delisted_universe"; OUTD.mkdir(parents=True, exist_ok=True)
    allb.to_csv(OUTD/"delisted_bars.csv.gz", index=False, compression="gzip")
    json.dump(dict(n_names=int(allb["sym"].nunique()), n_rows=int(len(allb)), fails=len(fails),
                   date_min=str(allb["date"].min()), date_max=str(allb["date"].max()),
                   failed_names=[f[0] for f in fails]), open(OUTD/"delisted_meta.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved %s" % (OUTD/"delisted_bars.csv.gz"))
    # ---- 双源交叉校验：现存股票 tx(qfq) vs data_full ----
    print("\n=== 双源交叉校验 (现存 20 只: 腾讯 qfq vs data_full) ===")
    import random
    random.seed(7)
    live = sorted(p.stem for p in (R/"data_full").glob("*.csv"))
    samp = random.sample(live, 20)
    diffs=[]; cov=[]
    for s_ in samp:
        try:
            tx = ak.stock_zh_a_hist_tx(symbol=s_, start_date="20240101", end_date="20260930", adjust="qfq")
        except Exception as e:
            continue
        if tx is None or not len(tx): continue
        tx = tx.copy(); tx["date"]=pd.to_datetime(tx["date"]).dt.strftime("%Y-%m-%d")
        try: loc = pd.read_csv(R/"data_full"/(s_+".csv"))
        except Exception: continue
        loc["date"]=loc["date"].astype(str).str.slice(0,10)
        m = tx.merge(loc[["date","open","close","high","low","volume","amount"]], on="date", suffixes=("_tx","_loc"))
        if len(m) < 50: continue
        for col in ("open","close"):
            a=pd.to_numeric(m[col+"_tx"], errors="coerce"); b=pd.to_numeric(m[col+"_loc"], errors="coerce")
            ra=a/a.shift(1)-1; rb=b/b.shift(1)-1
            dd=(ra-rb).abs().dropna()
            diffs.append((s_, col, len(m), float(dd.mean()), float(dd.quantile(0.99))))
        cov.append((s_, len(m)))
    df2 = pd.DataFrame(diffs, columns=["sym","col","n","mean_abs_ret_diff","p99_abs_ret_diff"])
    print(df2.groupby("col")[["n","mean_abs_ret_diff","p99_abs_ret_diff"]].mean().round(6).to_string())
    print("  配对样本数:", len(df2), " 股票数:", df2["sym"].nunique())
    print("  结论: 若 mean_abs_ret_diff 在 1e-4 量级 => 两源收益一致, 可混合使用")
