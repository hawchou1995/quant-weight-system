# -*- coding: utf-8 -*-
"""用「事故前缓存 bak_0911」直接复算 v9 main 选池，判断 rt 快照池来自哪份数据"""
import os, sys, json
from pathlib import Path
import pandas as pd
import numpy as np

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import v8_selector as V

names = json.load(open(BASE / "data_full_names.json", encoding="utf-8"))
C = pd.read_pickle(BASE / "v8_factor_cache.pkl.bak_0911")
print("bak_0911 缓存", len(C), "只", flush=True)

sel = V.pool_rebalance_state()
last_day = pd.Timestamp(sel["select_day"])
print("select_day", last_day)


def rank(pool, board="main", top_n=10, mom_min=0.25, score_min=65):
    cand = []
    for code, ddf in pool.items():
        if not code.startswith(("sh60", "sz00", "sz002")):
            continue
        _nm = names.get(code, "")
        if "ST" in str(_nm).upper() or "退" in str(_nm) or str(_nm).lstrip().upper().startswith("S"):
            continue
        if last_day not in ddf.index:
            continue
        r = ddf.loc[last_day]
        if pd.isna(r['close']) or r['close'] <= 0 or pd.isna(r['mom_12_1']):
            continue
        if r['close'] < 2.0:
            continue
        if pd.isna(r['amt20']) or r['amt20'] < 5e6:
            continue
        if r['mom_12_1'] < mom_min:
            continue
        if pd.isna(r['ma200_pos']) or r['ma200_pos'] <= 0:
            continue
        sc = V.score_row_v2(r)
        if sc < score_min:
            continue
        cand.append((code, sc))
    cand.sort(key=lambda kv: -kv[1])
    return [c for c, _ in cand[:top_n]], cand


m, c = rank(C)
print("\nbak_0911 复算 main:", m)
print("候选数", len(c))
print("\n前 25 名候选:")
for code, sc in c[:25]:
    print(f"  {code} {names.get(code,'?'):10} {sc:.2f}")
