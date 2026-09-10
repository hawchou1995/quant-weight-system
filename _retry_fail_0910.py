# -*- coding: utf-8 -*-
"""2026-09-10 失败清单重试（新浪 CN 接口，前复权口径与 data_full 一致）
- 读 _retry_need_0910.json（417 只）
- 新浪 CN_MarketDataService 拉日K（scale=240, datalen=8）
- 合并进 data_full（列序 date,open,high,low,close,volume,amount）
"""
import json, re, time
from pathlib import Path
import requests

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "data_full"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def fetch_one(sym):
    url = (f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20x=/CN_MarketDataService.getKLineData"
           f"?symbol={sym}&scale=240&ma=no&datalen=8")
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=15, headers=UA)
            if r.status_code != 200:
                time.sleep(0.5)
                continue
            m = re.search(r"\[.*\]", r.text)
            if not m:
                return sym, None, "no-data"
            arr = json.loads(m.group(0))
            if not arr:
                return sym, None, "empty"
            rows = []
            for it in arr:
                d = it.get("day")
                o = it.get("open"); h = it.get("high"); l = it.get("low")
                c = it.get("close"); v = it.get("volume")
                if not d or o is None or c is None:
                    continue
                rows.append(f"{d},{o},{h},{l},{c},{v},")
            if not rows:
                return sym, None, "empty2"
            return sym, rows, None
        except Exception as e:
            time.sleep(0.5)
    return sym, None, "err"

def main():
    need = json.load(open(BASE / "_retry_need_0910.json", encoding="utf-8"))
    print(f"重试 {len(need)} 只", flush=True)
    ok, fail = 0, []
    for i, sym in enumerate(need):
        s, rows, err = fetch_one(sym)
        if rows:
            f = OUT / f"{sym}.csv"
            if f.exists():
                old = f.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
                old_dates = {ln.split(",")[0] for ln in old if ln.strip()}
                new_rows = [ln for ln in rows if ln.split(",")[0] not in old_dates]
                merged = old + new_rows
            else:
                merged = rows
            f.write_text("\n".join(merged) + "\n", encoding="utf-8")
            ok += 1
        else:
            fail.append((sym, err))
        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(need)}] 成功 {ok} 失败 {len(fail)}", flush=True)
    print(f"完成: 成功 {ok} 失败 {len(fail)}", flush=True)
    if fail:
        print("失败样例:", fail[:15], flush=True)

if __name__ == "__main__":
    main()
