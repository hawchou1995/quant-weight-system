# -*- coding: utf-8 -*-
"""修正 09-11 行 volume 单位（稳健版）：直接对比 本地09-10 volume vs westock09-10 volume
   local ≈ westock        → 本地=手  → 09-11 用 westock 原值
   local ≈ westock × 100  → 本地=股  → 09-11 用 westock × 100"""
import os, sys, json, re, subprocess
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
OUT = BASE / "data_full"
CODES = [c for c in json.load(open(BASE / "_affected_amt_0911.json", encoding="utf-8")) if c != "_index"]
WS = Path(r"C:/Users/Admin/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/westock-data/scripts/index.js")
ROW = re.compile(r"\| ([a-z]{2}\w+) \| (\d{4}-\d{2}-\d{2}) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d.eE+]+) \| ([\d.eE+]+) \|")


def ws_fetch(syms):
    out = {}
    r = subprocess.run(["node", str(WS), "kline", ",".join(syms), "--period", "day",
                        "--limit", "8", "--fq", "qfq"], capture_output=True, text=True, timeout=180)
    hdr = False
    for ln in (r.stdout or "").splitlines():
        s = ln.strip()
        if "| date |" in s and "amount" in s:
            hdr = True; continue
        if not hdr or s.startswith("|---") or not s.startswith("|"):
            continue
        m = ROW.match(s)
        if m:
            sym, d, o, last, h, l, v, amt = m.groups()
            out.setdefault(sym, {})[d] = float(v)      # 手
    return out


ws = {}
for i in range(0, len(CODES), 50):
    for a in range(3):
        try:
            ws.update(ws_fetch(CODES[i:i + 50])); break
        except Exception:
            if a == 2: print("ws 批失败", i, flush=True)

st = {"scale100": 0, "keep1": 0, "no_ws": 0, "skip": 0}
for c in CODES:
    f = OUT / f"{c}.csv"
    if not f.exists():
        continue
    df = pd.read_csv(f, dtype={"date": str})
    if len(df) < 2 or str(df.iloc[-1]["date"])[:10] != "2026-09-11":
        st["skip"] += 1; continue
    lv10 = float(df.iloc[-2]["volume"])
    wmap = ws.get(c, {})
    wv11, wv10 = wmap.get("2026-09-11"), wmap.get("2026-09-10")
    if wv11 is None:
        st["no_ws"] += 1; continue
    if wv10 and wv10 > 0 and lv10 > 0:
        mult = 100 if (lv10 / wv10) > 10 else 1
    else:
        mult = 1
    want = wv11 * mult
    cur = float(df.iloc[-1]["volume"])
    df.at[df.index[-1], "volume"] = want
    df.to_csv(f, index=False)
    st["scale100" if mult == 100 else "keep1"] += 1

print("volume 单位修正(v2):", st, flush=True)
