# -*- coding: utf-8 -*-
"""诊断：用当前 data_full 复算 v9 选池（select_day=2026-08-17），对比两个 enhanced_data.js 版本"""
import os, sys, json
from pathlib import Path
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import v8_selector as V
import v9_auto as A

print("V.END =", getattr(V, "END", None))
print("A.END =", getattr(A, "END", None))

sel = V.pool_rebalance_state()
print("pool_rebalance_state:", sel)

last_day = pd.Timestamp(sel["select_day"])
print("last_day =", last_day, "| in idx?", )

# 复刻 v9_rank_board
names = json.load(open(BASE / "data_full_names.json", encoding="utf-8"))
ENTRY_MIN_STOCK = 65

def _is_board(code, board):
    if board == "main":
        return code.startswith(("sh60", "sz00", "sz002"))
    if board == "gem":
        return code.startswith("sz30")
    if board == "star":
        return code.startswith(("sh688", "sh689"))
    return False

def v9_rank_board(board, top_n=10, exclude=(), mom_min=0.25, score_min=ENTRY_MIN_STOCK):
    excl = {c[-6:] for c in exclude}
    cand = []
    n_nodata = 0
    for code, ddf in A.pool_all.items():
        if code[-6:] in excl:
            continue
        if not _is_board(code, board):
            continue
        _nm = names.get(code, "")
        if "ST" in str(_nm).upper() or "退" in str(_nm) or str(_nm).lstrip().upper().startswith("S"):
            continue
        if last_day not in ddf.index:
            n_nodata += 1
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
    return [c for c, _ in cand[:top_n]], cand, n_nodata

main, cand, nodata = v9_rank_board("main", 10)
print("\n== main 池 (top10) ==")
for c in main:
    print("  ", c, names.get(c, "?"))
print("main 候选总数:", len(cand), "| 无 08-17 数据跳过:", nodata)

# 002303 是否在候选中？
hits = [(c, s) for c, s in cand if c[-6:] == "002303"]
print("\n002303 在 main 候选中:", hits)

# 检查 002303 在 08-17 的原始因子
for code in ["sz002303", "sh600228", "sz002440"]:
    if code in A.pool_all:
        ddf = A.pool_all[code]
        if last_day in ddf.index:
            r = ddf.loc[last_day]
            print(f"\n{code} @08-17 close={r['close']} mom12_1={r['mom_12_1']} amt20={r['amt20']} ma200_pos={r['ma200_pos']} score={V.score_row_v2(r):.2f}")
        else:
            print(f"\n{code} 无 08-17 行；索引范围 {ddf.index[0]} ~ {ddf.index[-1]}")
    else:
        print(f"\n{code} 不在 pool_all")
