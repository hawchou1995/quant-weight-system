# -*- coding: utf-8 -*-
"""oss_0913 批9: turn 因子全池复验 — 第一步补 baostock turn 数据（extra 216 只）
已有 baostock_val 覆盖 400 只；本脚本补 data_full 主板中 val_em 缺失票的 turn
输出: data_fundamental/baostock_val/turn_extra_0913.csv
"""
import numpy as np, pandas as pd, time
from pathlib import Path

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "oss_0913"
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

# 目标: data_full 主板 且 不在 val_em 的票
import pickle
with open(OUT / "oss_panel_0913.pkl", "rb") as fh:
    P = pickle.load(fh)
codes_vem = set(P["codes"])
extra = []
for f in sorted((BASE / "data_full").glob("*.csv")):
    s = f.stem
    if s.startswith(("sh600", "sh601", "sh603", "sh605", "sz000", "sz001", "sz002", "sz003")):
        c = s[2:]
        if c not in codes_vem:
            extra.append(c)
log("extra:", len(extra))

# 已有 baostock 覆盖
have = set()
for f in ["val_all_0.csv", "val_all_1.csv"]:
    p = BASE / "data_fundamental" / "baostock_val" / f
    if p.exists():
        d = pd.read_csv(p, usecols=["code"])
        have.update(c.split(".")[1] if "." in c else c for c in d["code"].unique())
todo = [c for c in extra if c not in have]
log("already covered:", len(extra) - len(todo), "| to fetch:", len(todo))
assert len(todo) > 0

import baostock as bs
lg = bs.login()
assert lg.error_code == "0", lg.error_msg
log("baostock login ok")
rows = []
for k, c in enumerate(todo):
    pre = "sh." if c[0] == "6" else "sz."
    rs = bs.query_history_k_data_plus(pre + c, "date,turn,close", start_date="2021-01-01",
                                      end_date="2026-09-11", frequency="d", adjustflag="3")
    while rs.error_code == "0" and rs.next():
        r = rs.get_row_data()
        rows.append({"code": c, "date": r[0], "turn": r[1], "close": r[2]})
    if (k + 1) % 50 == 0:
        log(f"fetched {k+1}/{len(todo)}")
    time.sleep(0.1)
bs.logout()
df = pd.DataFrame(rows)
df.to_csv(BASE / "data_fundamental" / "baostock_val" / "turn_extra_0913.csv", index=False)
log("saved turn_extra_0913.csv rows:", len(df), "codes:", df["code"].nunique())
assert df["code"].nunique() >= len(todo) * 0.9
log("TURN DATA FETCH DONE")
