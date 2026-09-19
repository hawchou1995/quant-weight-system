# -*- coding: utf-8 -*-
"""valve_trackB 第2步: 取清单标的的尾盘分时状态 + 算四个阀标记 (分步落盘, 断点可续)。

用法:
  python valve_trackB_2_fetch.py fetch     # 分时抓取 -> valve_trackB_minute.csv
  python valve_trackB_2_fetch.py valved    # 合并阀标记 -> valve_trackB_lists_valved.csv
纪律: 只新增 backtest/valve_trackB_*; 失败如实计入。
"""
import os, sys, time
import numpy as np, pandas as pd

BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
BT = os.path.join(BASE, "backtest")
sys.path.insert(0, BT)
from t293_minute_0919 import pv  # noqa: E402

LISTS = os.path.join(BT, "valve_trackB_lists.csv")
MINCSV = os.path.join(BT, "valve_trackB_minute.csv")
VALVED = os.path.join(BT, "valve_trackB_lists_valved.csv")
COLS = ["date", "code", "rank", "g1430", "pull", "p1430", "p1445", "prev_close", "limit", "note"]


def limit_of(code):
    return 0.20 if str(code)[:2] in ("30", "68") else 0.10


def fetch():
    L = pd.read_csv(LISTS, dtype={"code": str})
    done = set()
    if os.path.exists(MINCSV):
        old = pd.read_csv(MINCSV, dtype={"code": str})
        done = set(zip(old["code"], old["date"]))
        print(f"续跑: 已有 {len(done)} 条", flush=True)
    rows = []
    t0 = time.time(); nfail = 0; n = 0
    for rec in L.itertuples():
        code, date = str(rec.code), str(rec.date)
        if (code, date) in done:
            continue
        n += 1
        di = int(date.replace("-", ""))
        r = None
        try:
            r = pv(code, di)
        except Exception as e:
            note = f"exc:{type(e).__name__}"
        else:
            note = "" if r else "none"
        if r is None:
            nfail += 1
            rows.append(dict(date=date, code=code, rank=int(rec.rank), g1430=np.nan, pull=np.nan,
                             p1430=np.nan, p1445=np.nan, prev_close=np.nan, limit=limit_of(code),
                             note=note or "none"))
        else:
            pc = r.get("prev_close", np.nan)
            g = (r["p1430"] / pc - 1) if (np.isfinite(pc) and pc > 0) else np.nan
            pl = (r["p1445"] / r["p1430"] - 1) if r["p1430"] > 0 else np.nan
            rows.append(dict(date=date, code=code, rank=int(rec.rank), g1430=g, pull=pl,
                             p1430=r["p1430"], p1445=r["p1445"], prev_close=pc,
                             limit=limit_of(code), note=note))
        if n % 25 == 0:
            pd.DataFrame(rows, columns=COLS).to_csv(MINCSV, mode="a", header=not os.path.exists(MINCSV), index=False)
            rows = []
            el = time.time() - t0
            print(f"  {n} 条 / {el:.0f}s ({el/max(n,1):.2f}s/条) 失败 {nfail} 剩余约 {(len(L)-len(done)-n)*el/max(n,1)/60:.1f}min", flush=True)
    if rows:
        pd.DataFrame(rows, columns=COLS).to_csv(MINCSV, mode="a", header=not os.path.exists(MINCSV), index=False)
    out = pd.read_csv(MINCSV, dtype={"code": str})
    print(f"fetch 完成: {len(out)} 行, 失败(无分时) {int((out['note'] != '').sum())} 条", flush=True)


def valved():
    L = pd.read_csv(LISTS, dtype={"code": str})
    M = pd.read_csv(MINCSV, dtype={"code": str})
    D = L.merge(M[["date", "code", "g1430", "pull", "p1430", "p1445", "prev_close", "note"]],
                on=["date", "code"], how="left")
    lim = D["code"].str[:2].isin(["30", "68"]).map({True: 0.20, False: 0.10})
    D["limit"] = lim
    ok = np.isfinite(D["g1430"]) & np.isfinite(D["pull"])
    D["has_minute"] = ok.astype(int)
    cap = D["prev_close"] * (1 + D["limit"])
    D["V1_强"] = (ok & (D["g1430"] >= 0.095) & (D["p1445"] < cap - 1e-3)).astype(int)
    D["V2_不弱"] = (ok & (D["p1445"] >= D["p1430"] * 0.998)).astype(int)
    D["V3_反向"] = (ok & (D["p1445"] <= D["p1430"] * 0.998)).astype(int)
    D["V4_排带"] = (ok & ~((D["g1430"] >= 0.01) & (D["g1430"] < 0.03))).astype(int)
    for c in ("V1_强", "V2_不弱", "V3_反向", "V4_排带"):
        D.loc[~ok, c] = -1     # -1 = 无分时数据, 不可判定
    D.to_csv(VALVED, index=False)
    print("saved", VALVED, D.shape)
    print("分时缺失:", int((~ok).sum()), "/", len(D), f"({(~ok).mean()*100:.1f}%)")
    print(D[["V1_强", "V2_不弱", "V3_反向", "V4_排带"]].apply(lambda s: (s == 1).sum(), axis=0).to_dict())


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    (fetch if m == "fetch" else valved)()
