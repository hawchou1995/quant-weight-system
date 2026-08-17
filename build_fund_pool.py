# -*- coding: utf-8 -*-
"""全市场基金池打分（选池分改用基金动量分，2026-08-17 修复）：
原四因子 score_row 对基金退化同分（动量/趋势撞顶、量价恒0、aroon 恒定）→ Top 排序实际近乎无序。
改为 short_engine 基金动量分（动量30+通道25+波动20，基金无量价→量价=0），有区分度。
保存 Top50 候选供普适池选 10 只。"""
import os, json, time
import pandas as pd, numpy as np
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, str(BASE))
import short_engine as SH

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
        fctx = SH.short_factors(d)
        r = fctx.iloc[-1]
        if pd.isna(r["close"]) or r["close"] <= 0 or pd.isna(r["mom20"]):
            continue
        sc = float(SH.short_score(r, reversal=False))
        cand.append({"code": code, "score": round(sc, 1),
                     "px": round(float(r["close"]), 4),
                     "mom20": round(float(r["mom20"]) * 100, 1),
                     "dnc": round(float(r["dnc"]), 3),
                     "vol20": round(float(r["vol20"]), 3)})
        n_ok += 1
    except Exception:
        continue
    if n_ok % 3000 == 0 and n_ok:
        print(f"  {n_ok} 只 ({time.time()-t0:.0f}s)", flush=True)

cand.sort(key=lambda x: -x["score"])
top = cand[:50]
OUT.write_text(json.dumps({"as_of": str(pd.Timestamp.now().date()), "total": n_ok, "top": top}, ensure_ascii=False), encoding="utf-8")
print(f"完成: {n_ok} 只基金打分（基金动量分口径），Top50 已存 {OUT.name} ({time.time()-t0:.0f}s)")
print("Top10:", [(x['code'], x['score']) for x in top[:10]])
