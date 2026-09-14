# -*- coding: utf-8 -*-
"""轴④⑤ 分钟数据抓取（R-daban-opt-0915）：A5 事件（2024-06 起）的 首板日/T/T+1/T+2 分钟线
缓存：D:/Tools/cache/tdx_min/min_{code}_{yyyymmdd}.parquet
输出：backtest/oss_0913/daban_minute_fetch_log.json（成功/失败清单）
用法：python daban_minute_fetch_0915.py [--limit N]
"""
import os, sys, json, time, argparse
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
sys.path.insert(0, "D:/Tools/ashare-replay-src")
import strategy_absorb_ev3_a5_absorb as A5

CACHE = Path("D:/Tools/cache/tdx_min")
CACHE.mkdir(parents=True, exist_ok=True)
HERE = Path(__file__).resolve().parent

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, default=0)
args = ap.parse_args()

E = pd.read_csv(HERE / "daban_events_0915.csv")
E = E[E.buy >= "2024-05-01"].copy()      # pytdx 深度边界（含一点余量，抓不到自然记 fail）
if args.limit:
    E = E.head(args.limit)
print(f"事件 {len(E)} 笔（{E.buy.min()} ~ {E.buy.max()}）", flush=True)

# 载入 pkl 找每笔事件的前一交易日（首板日）
d = pd.read_pickle(A5.PKL)

tasks = []          # (code, date_int)
for _, r in E.iterrows():
    code = str(r['code'])
    df = d.get(code)
    if df is None:
        continue
    idx = df.index
    try:
        pos = idx.get_loc(pd.Timestamp(r['buy']))
    except KeyError:
        pos = int(np.searchsorted(idx.values, np.datetime64(r['buy'])))
        if pos >= len(idx) or idx[pos].strftime('%Y-%m-%d') != r['buy']:
            continue
    for off in (-1, 0, 1, 2):
        p = pos + off
        if 0 <= p < len(idx):
            tasks.append((code, int(idx[p].strftime('%Y%m%d'))))
tasks = sorted(set(tasks))
print(f"待抓股票日 {len(tasks)} 个（去重后）", flush=True)

# pytdx 连接
import importlib.util as _iu
spec = _iu.spec_from_file_location("pytdx_data_0914", r"D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest/pytdx_data_0914.py")
p14 = _iu.module_from_spec(spec); spec.loader.exec_module(p14)
api = p14._api()
print(f"TDX 已连接 {p14._conn['ip']}", flush=True)


def fetch_min(code, date_int):
    cf = CACHE / f"min_{code}_{date_int}.parquet"
    if cf.exists():
        return "cache"
    raw = code[2:] if code[:2] in ("sh", "sz") else code      # pkl 键带 sh/sz 前缀，pytdx 需纯 6 位
    market = 1 if raw.startswith("6") else 0
    for attempt in range(2):
        try:
            data = api.get_history_minute_time_data(market, raw, date_int)
            if not data:
                return "empty"
            dfm = pd.DataFrame(data)
            dfm["code"] = code; dfm["date"] = date_int
            dfm.to_parquet(cf, compression="gzip", index=False)
            return "ok"
        except Exception as ex:
            time.sleep(0.5)
            if attempt == 1:
                return f"err:{type(ex).__name__}"
    return "err"


t0 = time.time()
stats = {"ok": 0, "cache": 0, "empty": 0, "err": 0}
fails = []
for i, (code, dt) in enumerate(tasks):
    r = fetch_min(code, dt)
    if r.startswith("err"):
        stats["err"] += 1; fails.append((code, dt, r))
    else:
        stats[r] = stats.get(r, 0) + 1
    if (i + 1) % 100 == 0:
        el = time.time() - t0
        print(f"  {i+1}/{len(tasks)} | {stats} | {el:.0f}s（{el/(i+1):.2f}s/个）", flush=True)

json.dump({"stats": stats, "fails": fails[:200], "tasks": len(tasks),
           "cache_dir": str(CACHE)},
          open(HERE / "daban_minute_fetch_log.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"完成 {stats} | 失败样例 {fails[:5]}", flush=True)
