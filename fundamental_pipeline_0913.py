# -*- coding: utf-8 -*-
"""基本面数据管道 v1（ADR-0007 后股票端破局方向，章程：提案-基本面数据源立项_20260912.md）
baostock 季频四表（profit/growth/cashflow/balance，自带 pubDate=PIT 公告日）× 主板全池（data_full 含退市 3469 只）。
落盘：data_fundamental/baostock/<table>.csv 长表 + done_<table>.txt 断点续传。
用法：python fundamental_pipeline_0913.py --shard 0 --nshard 4 [--years 2015,2026]
"""
import argparse
import time
from pathlib import Path

import baostock as bs
import pandas as pd

BASE = Path(__file__).resolve().parent
OUT = BASE / "data_fundamental" / "baostock"
OUT.mkdir(parents=True, exist_ok=True)

TABLES = {
    "profit": "code,pubDate,statDate,roeAvg,npMargin,gpMargin,netProfit,epsTTM,MBRevenue",
    "growth": "code,pubDate,statDate,YOYEquity,YOYAsset,YOYNI,YOYEPSBasic,YOYPNI",
    "cashflow": "code,pubDate,statDate,CAToAsset,NCAToAsset,TangibleAToAsset,CAToNCA,OperCashInToCurrentLiability,debtToAssets",
    "balance": "code,pubDate,statDate,currentRatio,quickRatio,cashRatio,YOYLiability,liabilityToAsset",
}

# 主板全池（含退市）
codes = []
for f in sorted((BASE / "data_full").glob("*.csv")):
    c = f.stem
    if c.startswith(("sh60", "sz000", "sz001", "sz002", "sz003")):
        codes.append("sh." + c[2:] if c.startswith("sh") else "sz." + c[2:])
codes = sorted(set(codes))

ap = argparse.ArgumentParser()
ap.add_argument("--shard", type=int, default=0)
ap.add_argument("--nshard", type=int, default=4)
ap.add_argument("--years", default="2015,2026")
args = ap.parse_args()
Y0, Y1 = (int(x) for x in args.years.split(","))
my_codes = codes[args.shard::args.nshard]
print(f"[shard {args.shard}/{args.nshard}] {len(my_codes)}/{len(codes)} 只 · {Y0}-{Y1}", flush=True)

bs.login()
for table, fields in TABLES.items():
    done_f = OUT / f"done_{table}_{args.shard}.txt"
    done = set(done_f.read_text(encoding="utf-8").split()) if done_f.exists() else set()
    out_f = OUT / f"{table}_{args.shard}.csv"
    t0 = time.time()
    n_ok = 0
    for i, code in enumerate(my_codes):
        if code in done:
            continue
        frames = []
        for y in range(Y0, Y1 + 1):
            for q in (1, 2, 3, 4):
                try:
                    rs = getattr(bs, f"query_{table}_data")(code=code, year=y, quarter=q)
                except AttributeError:
                    rs = bs.query_cash_flow_data(code=code, year=y, quarter=q) if table == "cashflow" \
                        else bs.query_balance_data(code=code, year=y, quarter=q)
                rows = []
                while rs.error_code == "0" and rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    frames.append(pd.DataFrame(rows, columns=rs.fields))
                time.sleep(0.12)  # 限速礼貌间隔
        if frames:
            df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["code", "pubDate", "statDate"])
            df.to_csv(out_f, mode="a", header=not out_f.exists(), index=False)
            n_ok += 1
        done.add(code)
        done_f.write_text("\n".join(sorted(done)), encoding="utf-8")
        if (i + 1) % 25 == 0:
            print(f"  [{table}] {i+1}/{len(my_codes)} 完成 ({time.time()-t0:.0f}s)", flush=True)
    print(f"[shard {args.shard}] {table} done: {len(done)}/{len(my_codes)} ({time.time()-t0:.0f}s)", flush=True)
bs.logout()
print("ALL DONE", flush=True)
