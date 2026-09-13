# -*- coding: utf-8 -*-
"""QuantZone Barra 风格因子 × 主板月度轮动（2021-01-04 起）
拉取：8 个 risk_fac_* 因子，按半年 11 批 × 全市场（配额 ~190MB/512MB）。
回测：主板过滤（60/00）→ 月末截面 Top10 等权 → 单因子双向（多重检验申报 n=8×2+复合）+ 经济先验方向复合分。
审计：因子值 T 日可得（Barra 日频因子）；对照 FB3-H20/护城河/HS300。"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from quantzone import QuantZone

BASE = Path(__file__).resolve().parent
OUT = BASE / "data_fundamental" / "quantzone"
OUT.mkdir(parents=True, exist_ok=True)
FACTORS = ["risk_fac_book_to_price", "risk_fac_earnings_yield", "risk_fac_profitability",
           "risk_fac_earnings_quality", "risk_fac_momentum", "risk_fac_residual_volatility",
           "risk_fac_size", "risk_fac_growth"]
START, END = "2021-01-01", "2026-09-12"

if __name__ == "__main__":
    k = json.load(open(r"D:\Documents\Obsidian\personal\quantzone-api-keys.json"))
    c = QuantZone(access_key=k["access_key"], sign_secret=k["sign_secret"], base_url=k["base_url"])
    t0 = time.time()
    for fac in FACTORS:
        out_f = OUT / f"{fac}.csv"
        if out_f.exists():
            print(f"[skip] {fac}", flush=True)
            continue
        frames = []
        edges = pd.date_range(START, END, freq="6MS")
        for i, s in enumerate(edges):
            e = (edges[i + 1] - pd.Timedelta(days=1)) if i + 1 < len(edges) else pd.Timestamp(END)
            try:
                d = c.get_factors(factor=fac, start_date=s.strftime("%Y-%m-%d"), end_date=e.strftime("%Y-%m-%d"))
                if len(d):
                    frames.append(d)
                print(f"  {fac} {s.date()}~{e.date()}: {len(d)} 行 q={c.get_quota()['available_bytes']//1048576}MB", flush=True)
            except Exception as ex:
                print(f"  ERR {fac} {s.date()}: {str(ex)[:60]}", flush=True)
                time.sleep(3)
        if frames:
            df = pd.concat(frames, ignore_index=True).drop_duplicates(["date", "ukey"])
            df.to_csv(out_f, index=False)
        print(f"[{fac}] done ({time.time()-t0:.0f}s)", flush=True)
    c.close()
    print("FETCH ALL DONE", flush=True)
