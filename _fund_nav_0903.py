# -*- coding: utf-8 -*-
"""2026-09-03 基金净值并发补更（东财 pingzhongdata 直连，绕 py_mini_racer）
- 只更新 fund_top_pool top 3000 中尾部日期 < 2026-09-02 的基金
- 并发 8，直接 requests + 正则解析 Data_netWorthTrend
- 输出与 akshare fund_open_fund_info_em 同构：净值日期,单位净值,日增长率
"""
import json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests

BASE = Path(__file__).resolve().parent
CACHE = BASE / "fund_nav_cache"
TARGET = "2026-09-02"  # 基金净值 T+1 公布，今日可拉到的最新=09-02
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://fund.eastmoney.com/"}

def tail_date(f):
    try:
        with open(f, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 1024))
            tail = fh.read().decode("utf-8", errors="ignore")
        lines = [ln for ln in tail.strip().splitlines() if ln.strip()]
        return lines[-1].split(",")[0].strip() if lines else None
    except Exception:
        return None

def fetch_one(code):
    url = f"https://fund.eastmoney.com/pingzhongdata/{code}.js"
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=20, headers=UA)
            if r.status_code != 200:
                time.sleep(1.0)
                continue
            m = re.search(r"var Data_netWorthTrend\s*=\s*(\[.*?\]);", r.text, re.S)
            if not m:
                return code, None, "no-data"
            arr = json.loads(m.group(1))
            rows = []
            for it in arr:
                x = it.get("x")
                y = it.get("y")
                er = it.get("equityReturn")
                if x is None or y is None:
                    continue
                d = time.strftime("%Y-%m-%d", time.localtime(x / 1000))
                rows.append(f"{d},{y},{er if er is not None else ''}")
            if not rows:
                return code, None, "empty"
            # 去重保序
            seen = set()
            out = []
            for ln in rows:
                d = ln.split(",")[0]
                if d in seen:
                    continue
                seen.add(d)
                out.append(ln)
            return code, out, None
        except Exception as e:
            time.sleep(1.0)
    return code, None, "err"

def main():
    pool = json.load(open(BASE / "fund_top_pool.json", encoding="utf-8"))
    codes = [x["code"] for x in pool["top"][:3000]]
    need = []
    for c in codes:
        f = CACHE / f"{c}.csv"
        if not f.exists():
            need.append(c)
            continue
        td = tail_date(f)
        if td is None or td < TARGET:
            need.append(c)
    print(f"需更新 {len(need)}/{len(codes)} 只（尾部 < {TARGET}）", flush=True)
    t0 = time.time()
    ok, fail = 0, []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_one, c): c for c in need}
        for i, fut in enumerate(as_completed(futs)):
            code, rows, err = fut.result()
            if rows:
                CACHE.joinpath(f"{code}.csv").write_text(
                    "净值日期,单位净值,日增长率\n" + "\n".join(rows) + "\n", encoding="utf-8")
                ok += 1
            else:
                fail.append((code, err))
            if (i + 1) % 200 == 0:
                print(f"  [{i+1}/{len(need)}] 成功 {ok} 失败 {len(fail)} 耗时 {time.time()-t0:.0f}s", flush=True)
    print(f"完成: 成功 {ok} 失败 {len(fail)} 耗时 {time.time()-t0:.0f}s", flush=True)
    if fail:
        print("失败样例:", fail[:10], flush=True)

if __name__ == "__main__":
    main()
