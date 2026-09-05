# -*- coding: utf-8 -*-
"""一次性实证：确认腾讯行情体 fields[9]=买一价、fields[10]=买一量(手)。"""
import sys, re
sys.path.insert(0, ".")
import build_market_breadth as M
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_chunk(cs):
    req = Request(M._QUOTE_URL + ",".join(cs),
                  headers={"User-Agent": "Mozilla/5.0", "Referer": "https://stock.qq.com/", "Connection": "close"})
    return urlopen(req, timeout=20).read().decode("gbk", "replace")

def fetch_one(sym):
    req = Request("https://qt.gtimg.cn/q=" + sym,
                  headers={"User-Agent": "Mozilla/5.0", "Referer": "https://stock.qq.com/"})
    return urlopen(req, timeout=10).read().decode("gbk", "replace")

# 1) sh600000 基准
body = fetch_one("sh600000")
fields = body.split('"')[1].split("~") if '"' in body else []
print("=== sh600000 ===")
print("len(fields)=", len(fields))
for i in [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]:
    if i < len(fields):
        print(f"  [{i}] = {fields[i]!r}")

# 2) 分块拉取，直到找到 >=3 只涨停股（避免全市场下载）
all_syms = M.symbols()
chunks = [all_syms[i:i+200] for i in range(0, len(all_syms), 200)]
rows = []
zt = []
for ci in range(0, len(chunks), 10):  # 每轮并发 10 块
    batch = chunks[ci:ci+10]
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = [pool.submit(fetch_chunk, c) for c in batch]
        for f in as_completed(futs):
            try:
                rows.extend(M.parse_quote_body(f.result()))
            except Exception:
                pass
    for r in rows:
        ul = r.get("upper_limit")
        if ul and ul > 0 and r.get("price") and r.get("price") >= ul:
            if r["code"] not in [x["code"] for x in zt]:
                zt.append(r)
    if len(zt) >= 3:
        break

print("\n=== 涨停股 sample (%d found) ===" % len(zt))
for r in zt[:3]:
    b = fetch_one(r["symbol"])
    f = b.split('"')[1].split("~")
    bid1_price = f[9] if len(f) > 10 else None
    bid1_vol = f[10] if len(f) > 11 else None
    ok_price = abs(float(bid1_price) - r["upper_limit"]) < 1e-6 if bid1_price else False
    ok_vol = int(bid1_vol) > 0 if bid1_vol else False
    print(f"  {r['code']} {r['name']}: price={r['price']} upper={r['upper_limit']} [9]={bid1_price!r} [10]={bid1_vol!r} -> 买一≈涨停价?{ok_price} 买一量>0?{ok_vol}")

print("\n=== CONFIRM fields[9]=买一价, fields[10]=买一量(手) ===")
