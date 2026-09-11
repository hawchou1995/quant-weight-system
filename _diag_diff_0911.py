# -*- coding: utf-8 -*-
"""对比 bak_0911 与当前缓存（回滚后）在 2026-08-17 的因子差异"""
import os, sys, json
from pathlib import Path
import pandas as pd
import numpy as np

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import v8_selector as V

names = json.load(open(BASE / "data_full_names.json", encoding="utf-8"))
A = pd.read_pickle(BASE / "v8_factor_cache.pkl.bak_0911")     # 事故前
B = pd.read_pickle(BASE / "v8_factor_cache.pkl")              # 回滚后
d = pd.Timestamp("2026-08-17")

codes = ["sz002990", "sz002979", "sz002585", "sh600186", "sh601101", "sh603259",
         "sz002458", "sh600664", "sh603065", "sz002841", "sh600707", "sz002303"]
cols = ["close", "volume", "amount", "mom_12_1", "ma200_pos", "aroon_osc", "amt20"]
for c in codes:
    a = A.get(c); b = B.get(c)
    print("====", c, names.get(c, "?"))
    if a is None or b is None:
        print("   missing", a is None, b is None); continue
    ha = d in a.index; hb = d in b.index
    if not (ha and hb):
        print("   08-17 缺失", ha, hb); continue
    ra, rb = a.loc[d], b.loc[d]
    for col in cols:
        if col in a.columns and col in b.columns:
            va, vb = ra[col], rb[col]
            mark = "" if (pd.isna(va) and pd.isna(vb)) or (not pd.isna(va) and not pd.isna(vb) and abs(float(va) - float(vb)) < 1e-6) else "   <<< DIFF"
            print(f"   {col:10} bak={va!r:>22} new={vb!r:>22}{mark}")
    print(f"   score  bak={V.score_row_v2(ra):.2f} new={V.score_row_v2(rb):.2f}")

# 数据索引范围对比
print("\n--- date index 范围 ---")
for c in ["sz002990", "sz002303"]:
    a = A.get(c); b = B.get(c)
    if a is not None and b is not None:
        print(c, "bak", a.index[0].date(), a.index[-1].date(), len(a),
              "| new", b.index[0].date(), b.index[-1].date(), len(b))
