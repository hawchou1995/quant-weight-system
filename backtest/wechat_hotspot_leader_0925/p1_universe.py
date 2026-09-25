# -*- coding: utf-8 -*-
"""Step1: calendar + universe for the WeChat-article factor backtest."""
import json, pathlib, csv, io
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = R / "backtest/wechat_hotspot_leader_0925"
OUT.mkdir(parents=True, exist_ok=True)
cal = []
with (R / "index_000300.csv").open(encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        cal.append(r["date"])
cal = sorted(set(cal))
print("calendar %s -> %s  n=%d" % (cal[0], cal[-1], len(cal)))

ind = json.loads((R / "stock_industry.json").read_text(encoding="utf-8"))
imap = ind["map"]
print("industry map n=%d  n_ind=%d" % (len(imap), len(set(imap.values()))))
SKIP_IND = {"其他", "指数宽基"}
# ETF/指数代码前缀（5/1 开头）与北交所 bj 一律剔除
files = sorted((R / "data_full").glob("*.csv"))
uni = []
skipped = dict(etf=0, bj=0, noind=0, short=0, other=0, ok=0)
for p in files:
    sym = p.stem
    if sym.startswith("_"):
        continue
    if sym.startswith("bj"):
        skipped["bj"] += 1; continue
    code = sym[2:]
    if sym[2:3] in ("5", "1") or sym.startswith("sh5") or sym.startswith("sz1"):
        skipped["etf"] += 1; continue
    if not (sym.startswith("sh6") or sym.startswith("sz0") or sym.startswith("sz3")):
        skipped["other"] += 1; continue
    gi = imap.get(code)
    if gi is None or gi in SKIP_IND:
        skipped["noind"] += 1; continue
    uni.append((sym, code, gi))
    skipped["ok"] += 1
print("universe=%d  skipped=%s" % (len(uni), skipped))
from collections import Counter
c = Counter(g for _, _, g in uni)
print("industries in universe: %d" % len(c))
print("  top10:", c.most_common(10))
print("  bottom5:", c.most_common()[-5:])
(OUT / "universe.json").write_text(json.dumps(
    dict(calendar=cal, universe=[dict(sym=s, code=c0, ind=g) for s, c0, g in uni],
         note="excluded: bj / ETF-index(5*,1*) / industry in {其他,指数宽基} / non sh6|sz0|sz3"), ensure_ascii=False), encoding="utf-8")
print("saved universe.json")
