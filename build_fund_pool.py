# -*- coding: utf-8 -*-
"""全市场基金池打分（选池分=基金动量分；A/C 份额去重，2026-08-18 追加）
原四因子 score_row 对基金退化同分（全 76.4 并列）→ Top 排序实际无序。
改为 short_engine 基金动量分（动量30+通道25+波动20，无量价）。
A/C 去重：同一基金（简称去 A/B/C/E 份额后缀）只保留高分份额，避免 Top10 全是同一基金的 A/C。"""
import os, json, time
import pandas as pd, numpy as np
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.insert(0, str(BASE))
import short_engine as SH

CACHE = BASE / "fund_nav_cache"
OUT = BASE / "fund_top_pool.json"

# 基金简称（本地 fund_list.csv，股票/混合型基金全域，含 A/C 份额全称）
FNAMES = {}
try:
    _fl = pd.read_csv(BASE / "fund_list.csv", dtype=str)
    FNAMES = dict(zip(_fl["基金代码"], _fl["基金简称"]))
except Exception:
    pass


def base_name(nm):
    """去份额后缀 → 同基金基准名（如 '中金瑞安混合发起A'→'中金瑞安混合发起'）"""
    if not nm:
        return nm
    nm = str(nm).strip()
    if nm.endswith("(后端)"):
        nm = nm[:-4]
    while len(nm) > 1 and nm[-1] in "ABCE" and nm[-2] != "(":
        nm = nm[:-1]
    return nm


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
        nm = FNAMES.get(code, code)
        cand.append({"code": code, "score": round(sc, 1), "name": nm, "base": base_name(nm),
                     "px": round(float(r["close"]), 4),
                     "mom20": round(float(r["mom20"]) * 100, 1),
                     "dnc": round(float(r["dnc"]), 3),
                     "vol20": round(float(r["vol20"]), 3)})
        n_ok += 1
    except Exception:
        continue
    if n_ok % 3000 == 0 and n_ok:
        print(f"  {n_ok} 只 ({time.time()-t0:.0f}s)", flush=True)

# A/C 份额去重：同基础名只保留最高分份额
best = {}
for x in cand:
    b = x["base"]
    if b not in best or x["score"] > best[b]["score"]:
        best[b] = x
cand2 = sorted(best.values(), key=lambda x: -x["score"])
top = cand2[:50]
OUT.write_text(json.dumps({"as_of": str(pd.Timestamp.now().date()), "total": n_ok,
                           "unique": len(cand2), "top": top}, ensure_ascii=False), encoding="utf-8")
print(f"完成: {n_ok} 只 → 去重后 {len(cand2)} 只独立基金，Top50 已存 {OUT.name} ({time.time()-t0:.0f}s)")
print("Top10:", [(x['code'], x['score'], x['name']) for x in top[:10]])
