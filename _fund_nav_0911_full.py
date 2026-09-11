# -*- coding: utf-8 -*-
"""2026-09-11 基金净值联合补更（东财 pingzhongdata 直连）
- 范围 = fund_top_pool top ∪ 跟踪池基金（track_v9/short track 中存在于 fund_nav_cache 的代码）∪ v9 fund tiers
- TARGET = 2026-09-10（今日可拉到的最新净值日）
- 并发 8 + 正则解析 Data_netWorthTrend，绕 py_mini_racer
"""
import json, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests

BASE = Path(__file__).resolve().parent
CACHE = BASE / "fund_nav_cache"
TARGET = "2026-09-10"
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
            r = requests.get(url, headers=UA, timeout=15)
            m = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", r.text, re.S)
            if not m:
                return code, None, "no-trend"
            arr = json.loads(m.group(1))
            if not arr:
                return code, None, "empty"
            rows, seen = [], set()
            for it in arr[-400:]:
                # 2026-09-11 接口结构：数组 → dict {"x": ms时间戳, "y": 单位净值, "equityReturn": 日增长率}
                if isinstance(it, dict):
                    ts = it.get("x", 0)
                    nav = it.get("y")
                    chg = it.get("equityReturn", "")
                else:
                    ts = it[0] if len(it) > 0 else 0
                    nav = it[1] if len(it) > 1 else ""
                    chg = it[2] if len(it) > 2 else ""
                # 东财 x = 北京时间(GMT+8) 00:00 戳 → 必须 localtime 转日期（gmtime 会错位 -1 天，2026-09-11 实测）
                d = time.strftime("%Y-%m-%d", time.localtime(ts / 1000.0))
                if d in seen:
                    continue
                seen.add(d)
                rows.append(f"{d},{nav},{chg}")
            return code, rows, None
        except Exception as e:
            time.sleep(1.0)
    return code, None, "err"

def main():
    codes = set()
    # 1) fund_top_pool top
    pool = json.load(open(BASE / "fund_top_pool.json", encoding="utf-8"))
    for x in pool["top"][:3000]:
        codes.add(x["code"])
    # 2) 跟踪池基金（track_v9 + short track）——存在于 fund_nav_cache 即视为基金
    for js in ["enhanced_data.js", "short_pool.js"]:
        p = BASE / js
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        # 提取 code 字段："600228": {...} 或 {"code": "..."} 两种形态
        for m in re.finditer(r'"(\d{6})"\s*:\s*\{', txt):
            codes.add(m.group(1))
        for m in re.finditer(r'"code"\s*:\s*"(\d{6})"', txt):
            codes.add(m.group(1))
    # 只保留 fund_nav_cache 中存在文件的 = 基金
    codes = {c for c in codes if (CACHE / f"{c}.csv").exists()}
    need = []
    for c in sorted(codes):
        f = CACHE / f"{c}.csv"
        td = tail_date(f)
        if td is None or td < TARGET:
            need.append(c)
    print(f"范围 {len(codes)} 只，需更新 {len(need)} 只（尾部 < {TARGET}）", flush=True)
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
            if (i + 1) % 100 == 0:
                print(f"  [{i+1}/{len(need)}] 成功 {ok} 失败 {len(fail)} 耗时 {time.time()-t0:.0f}s", flush=True)
    print(f"完成: 成功 {ok} 失败 {len(fail)} 耗时 {time.time()-t0:.0f}s", flush=True)
    if fail:
        print("失败示例:", fail[:10], flush=True)

if __name__ == "__main__":
    main()
