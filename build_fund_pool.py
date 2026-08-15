# -*- coding: utf-8 -*-
"""全市场基金池打分（一次性，缓存 fund_top_pool.json）：
从 fund_nav_cache 19359 只净值，四因子打分，保存 Top50 候选供普适池选 10 只。"""
import os, json, time
import pandas as pd, numpy as np
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
import sys
sys.path.insert(0, str(BASE))
import v8_selector as V

CACHE = BASE / "fund_nav_cache"
OUT = BASE / "fund_top_pool.json"

t0 = time.time()
cand = []
n_ok = 0
for f in sorted(os.listdir(CACHE)):
    if not f.endswith(".csv"):
        continue
    code = f[:-4]
    try:
        df = pd.read_csv(CACHE / f, dtype={"净值日期": str})
        s = pd.Series(pd.to_numeric(df["单位净值"], errors="coerce").values,
                      index=pd.to_datetime(df["净值日期"])).dropna()
        if len(s) < 400:
            continue
        d = pd.DataFrame({"open": s.values, "high": s.values, "low": s.values,
                          "close": s.values, "volume": 0.0, "amount": 0.0}, index=s.index)
        d = V.compute_factors_full(d)
        r = d.iloc[-1]
        if pd.isna(r["mom_12_1"]) or pd.isna(r["close"]) or r["close"] <= 0:
            continue
        sc = float(V.score_row(r))
        cand.append({"code": code, "score": round(sc, 1),
                     "px": round(float(r["close"]), 4),
                     "mom": round(float(r["mom_12_1"]) * 100, 1),
                     "ma200": round(float(r["ma200_pos"]) * 100, 1),
                     "aroon": round(float(r["aroon_osc"]), 1),
                     "rsi": None})
        n_ok += 1
    except Exception:
        continue
    if n_ok % 3000 == 0 and n_ok:
        print(f"  {n_ok} 只 ({time.time()-t0:.0f}s)", flush=True)

cand.sort(key=lambda x: -x["score"])
top = cand[:50]
OUT.write_text(json.dumps({"as_of": "2026-08-14", "total": n_ok, "top": top}, ensure_ascii=False), encoding="utf-8")
print(f"完成: {n_ok} 只基金打分，Top50 已存 {OUT.name} ({time.time()-t0:.0f}s)")
print("Top10:", [(x['code'], x['score']) for x in top[:10]])
