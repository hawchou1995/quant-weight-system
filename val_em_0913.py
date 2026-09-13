# -*- coding: utf-8 -*-
"""估值拉取 v2（东财数据中心 RPT_VALUEANALYSIS_DET）：主板全池 2021-01-01 起日频估值+市值。
字段：date/close/pe_ttm/pb_mrq/total_mv/float_mv。4 线程 + 断点续传。
用法：python val_em_0913.py"""
import concurrent.futures as cf
import json
import threading
import time
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).resolve().parent
OUT = BASE / "data_fundamental" / "val_em"
OUT.mkdir(parents=True, exist_ok=True)
URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HDR = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
TL = threading.local()

codes = []
for f in sorted((BASE / "data_full").glob("*.csv")):
    c = f.stem
    if c.startswith(("sh60", "sz000", "sz001", "sz002", "sz003")):
        codes.append(c[2:])
codes = sorted(set(codes))
done = set()
DONE_F = OUT / "done.json"
if DONE_F.exists():
    done = set(json.load(open(DONE_F, encoding="utf-8")))
todo = [c for c in codes if c not in done]
print(f"[val_em] {len(todo)}/{len(codes)} 票待拉（窗口 2021-01-01 起）", flush=True)
lock = threading.Lock()


def fetch_one(code):
    s = getattr(TL, "s", None)
    if s is None:
        s = requests.Session(); s.headers.update(HDR); TL.s = s
    rows, page = [], 1
    while True:
        p = {"reportName": "RPT_VALUEANALYSIS_DET", "columns": "ALL",
             "filter": f'(SECURITY_CODE="{code}")', "sortColumns": "TRADE_DATE",
             "sortTypes": "-1", "pageSize": "500", "pageNumber": str(page),
             "source": "WEB", "client": "WEB"}
        try:
            j = s.get(URL, params=p, timeout=15).json()
        except Exception:
            time.sleep(2)
            continue
        d = (j.get("result") or {}).get("data") or []
        if not d:
            break
        rows.extend(d)
        if len(d) < 500 or page >= 12:
            break
        page += 1
        time.sleep(0.12)
    if not rows:
        return code, []
    df = pd.DataFrame(rows)
    df = df[df["TRADE_DATE"] >= "2021-01-01"]
    out = pd.DataFrame({
        "code": code,
        "date": pd.to_datetime(df["TRADE_DATE"]).dt.strftime("%Y-%m-%d"),
        "close": pd.to_numeric(df["CLOSE_PRICE"], errors="coerce"),
        "pe_ttm": pd.to_numeric(df["PE_TTM"], errors="coerce"),
        "pb_mrq": pd.to_numeric(df["PB_MRQ"], errors="coerce"),
        "total_mv": pd.to_numeric(df["TOTAL_MARKET_CAP"], errors="coerce"),
        "float_mv": pd.to_numeric(df["NOTLIMITED_MARKETCAP_A"], errors="coerce"),
    }).drop_duplicates("date").sort_values("date")
    return code, out.to_dict("records")


if __name__ == "__main__":
    t0 = time.time()
    n_ok = 0
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(fetch_one, c): c for c in todo}
        for fu in cf.as_completed(futs):
            code, recs = fu.result()
            with lock:
                if recs:
                    pd.DataFrame(recs).to_csv(OUT / "val_em_all.csv", mode="a",
                                              header=not (OUT / "val_em_all.csv").exists(), index=False)
                done.add(code)
                if len(done) % 50 == 0:
                    json.dump(sorted(done), open(DONE_F, "w", encoding="utf-8"))
                n_ok += 1
                if n_ok % 100 == 0:
                    print(f"  {n_ok}/{len(todo)} ({time.time()-t0:.0f}s)", flush=True)
    json.dump(sorted(done), open(DONE_F, "w", encoding="utf-8"))
    print(f"DONE {len(done)}/{len(codes)} ({time.time()-t0:.0f}s)", flush=True)
