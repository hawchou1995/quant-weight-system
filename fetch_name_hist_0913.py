# -*- coding: utf-8 -*-
"""每日简称历史拉取（RPT_VALUEANALYSIS_DET 的 SECURITY_NAME_ABBR 列，2021-01-04 起）
用途：ST/*ST/PT/退市 风险过滤（历史时点，非当前名）。落盘 data_fundamental/name_hist.csv
8 线程 + 断点续传。"""
import concurrent.futures as cf
import threading
import time
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).resolve().parent
OUT = BASE / "data_fundamental" / "name_hist.csv"
DONE_F = BASE / "data_fundamental" / "name_hist_done.txt"
URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HDR = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
TL = threading.local()
LOCK = threading.Lock()

codes = []
for f in sorted((BASE / "data_full").glob("*.csv")):
    c = f.stem
    if c.startswith(("sh60", "sz000", "sz001", "sz002", "sz003")):
        codes.append(c[2:])
codes = sorted(set(codes))
done = set(DONE_F.read_text(encoding="utf-8").split()) if DONE_F.exists() else set()
todo = [c for c in codes if c not in done]
print(f"[name_hist] {len(todo)}/{len(codes)} 待拉", flush=True)


def fetch(code):
    s = getattr(TL, "s", None)
    if s is None:
        s = requests.Session(); s.headers.update(HDR); TL.s = s
    rows, page = [], 1
    while True:
        p = {"reportName": "RPT_VALUEANALYSIS_DET", "columns": "SECURITY_CODE,TRADE_DATE,SECURITY_NAME_ABBR",
             "filter": f'(SECURITY_CODE="{code}")', "sortColumns": "TRADE_DATE", "sortTypes": "-1",
             "pageSize": "1000", "pageNumber": str(page), "source": "WEB", "client": "WEB"}
        try:
            j = s.get(URL, params=p, timeout=15).json()
        except Exception:
            time.sleep(1.5)
            continue
        d = (j.get("result") or {}).get("data") or []
        if not d:
            break
        rows.extend(d)
        if len(d) < 1000 or page >= 5:
            break
        page += 1
    if not rows:
        return code, []
    df = pd.DataFrame(rows)
    df = df[df["TRADE_DATE"] >= "2021-01-04"]
    return code, df[["TRADE_DATE", "SECURITY_NAME_ABBR"]].to_dict("records")


if __name__ == "__main__":
    t0 = time.time()
    n = 0
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for fu in cf.as_completed({ex.submit(fetch, c): c for c in todo}):
            code, recs = fu.result()
            with LOCK:
                if recs:
                    out = pd.DataFrame(recs).assign(code=code)[["code", "TRADE_DATE", "SECURITY_NAME_ABBR"]]
                    out.to_csv(OUT, mode="a", header=not OUT.exists(), index=False)
                done.add(code)
                n += 1
                if n % 200 == 0:
                    DONE_F.write_text("\n".join(sorted(done)), encoding="utf-8")
                    print(f"  {n}/{len(todo)} ({time.time()-t0:.0f}s)", flush=True)
    DONE_F.write_text("\n".join(sorted(done)), encoding="utf-8")
    print(f"DONE {len(done)}/{len(codes)} ({time.time()-t0:.0f}s)", flush=True)
