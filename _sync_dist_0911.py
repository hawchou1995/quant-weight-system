# -*- coding: utf-8 -*-
"""把本轮重建的看板产物同步到部署源 D:/Documents/Workbuddy/股票基金/dist"""
import os, shutil, datetime, hashlib
from pathlib import Path

SRC = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
DST = Path(r"D:/Documents/Workbuddy/股票基金/dist")

CORE = ["enhanced_data.js", "dual_system.html", "index.html", "short_pool.js", "short_signals.js",
        "a5_pool.js", "market_breadth.js", "market_weather.js", "stock_industry.json",
        "jiandi_panic.json", "changelog.html", "changelog.md", "advice_v8lite.html",
        "data_full_names.json", "etf_dashboard_snapshot.json"]

def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

copied, same, miss = [], [], []
for name in CORE:
    s = SRC / name
    d = DST / name
    if not s.exists():
        miss.append(name); continue
    if d.exists() and md5(s) == md5(d):
        same.append(name); continue
    shutil.copy2(s, d)
    copied.append((name, s.stat().st_size, md5(d)[:12]))

# review/*.md 同步
rs, rd = SRC / "review", DST / "review"
if rs.exists():
    rd.mkdir(exist_ok=True)
    for f in rs.glob("*.md"):
        t = rd / f.name
        if (not t.exists()) or md5(f) != md5(t):
            shutil.copy2(f, t); copied.append((f"review/{f.name}", f.stat().st_size, md5(t)[:12]))

print("同步完成")
print("  更新:", len(copied))
for n, sz, h in copied:
    print(f"    {n}  {sz}  {h}")
print("  未变:", len(same), same[:6])
print("  缺失:", miss)
print()
for n in ["index.html", "dual_system.html", "enhanced_data.js"]:
    p = DST / n
    print(f"  dist/{n}  mtime={datetime.datetime.fromtimestamp(p.stat().st_mtime):%m-%d %H:%M}  md5={md5(p)[:12]}")
