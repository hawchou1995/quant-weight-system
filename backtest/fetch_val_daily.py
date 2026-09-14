# -*- coding: utf-8 -*-
"""每日全市场市值快照（turn 因子 live 化前提）
数据源：akshare stock_zh_a_spot_em（东财全市场快照，一次调用覆盖 5000+ 只）
产出：data_fundamental/val_live/val_daily_snapshot.csv（date,code,close,float_mv,total_mv；按日追加去重）
用法：python backtest/fetch_val_daily.py   # 收盘后跑（挂在 build_satellite_pool 之前）
"""
import sys, time
from pathlib import Path
import pandas as pd

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "data_fundamental" / "val_live"
OUT.mkdir(parents=True, exist_ok=True)
SNAP = OUT / "val_daily_snapshot.csv"
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:5.1f}s]", *a, flush=True)

import akshare as ak
log("akshare importing done")
df = None
for _k in range(3):
    try:
        df = ak.stock_zh_a_spot_em()
        log(f"fast 快照 rows={len(df)} cols={list(df.columns)[:8]} (try {_k+1})")
        break
    except Exception as e:
        log(f"akshare spot ERR(try {_k+1}):", type(e).__name__, str(e)[:120])
        time.sleep(8 + 12 * _k)
if df is None:
    log("快照失败（3 次）——本次跳过快照；fmv_recent 保持既有（turn 用 20 日窗仍可算）")
    # 仍确保 fmv_recent 存在（缺则从 val_em 构建）
    RECENT = OUT / "fmv_recent.csv"
    if not RECENT.exists():
        import datetime as _dt
        import pandas as _pd
        sample = BASE / "data_full" / "sh600519.csv"
        last_date = _pd.read_csv(sample, dtype={"date": str})["date"].iloc[-1]
        _cut = (_dt.date.fromisoformat(last_date) - _dt.timedelta(days=130)).isoformat()
        vem = _pd.read_csv(BASE / "data_fundamental" / "val_em" / "val_em_all.csv",
                           usecols=["date", "code", "float_mv"], dtype={"code": str, "date": str})
        vem = vem[vem["date"] >= _cut][["date", "code", "float_mv"]].dropna()
        if SNAP.exists():   # 合并已有每日快照（覆盖 val_em 之后的日期）
            sn = _pd.read_csv(SNAP, usecols=["date", "code", "float_mv"], dtype={"code": str, "date": str}).dropna()
            sn = sn[sn["date"] > vem["date"].max()]
            vem = _pd.concat([vem, sn], ignore_index=True)
        vem.to_csv(RECENT, index=False)
        log(f"fmv_recent 从 val_em 构建 {len(vem)} 行（{vem['date'].min()} ~ {vem['date'].max()}）")
    sys.exit(0)

need = {"代码": "code", "最新价": "close", "流通市值": "float_mv", "总市值": "total_mv"}
missing = [k for k in need if k not in df.columns]
if missing:
    log("列缺失:", missing); sys.exit(1)
snap = pd.DataFrame({
    "code": df["代码"].astype(str).str.zfill(6),
    "close": pd.to_numeric(df["最新价"], errors="coerce"),
    "float_mv": pd.to_numeric(df["流通市值"], errors="coerce"),
    "total_mv": pd.to_numeric(df["总市值"], errors="coerce"),
})
# 日期：以本地日线最新交易日为准（快照盘后取，避免把盘中价混入）
sample = BASE / "data_full" / "sh600519.csv"
last_date = pd.read_csv(sample, dtype={"date": str})["date"].iloc[-1]
snap["date"] = last_date
snap = snap.dropna(subset=["float_mv"]).query("float_mv > 0")
if SNAP.exists():
    old = pd.read_csv(SNAP, dtype={"code": str, "date": str})
    old = old[old["date"] != last_date]
    snap = pd.concat([old, snap], ignore_index=True)
snap = snap.sort_values(["date", "code"])
SNAP.write_text(snap.to_csv(index=False), encoding="utf-8")
log(f"写入 {SNAP.name} | 本次 {last_date} {len(snap[snap['date']==last_date])} 只 | 累计 {len(snap)} 行 / {snap['date'].nunique()} 个日期")

# ---- 维护 fmv_recent.csv（近 120 日 float_mv：val_em 历史 + 每日快照），供 turn 因子 live 计算 ----
RECENT = OUT / "fmv_recent.csv"
import datetime as _dt
_cut = (_dt.date.fromisoformat(last_date) - _dt.timedelta(days=130)).isoformat()
if not RECENT.exists():
    log("重建 fmv_recent（读 val_em_all 尾部）...")
    vem = pd.read_csv(BASE / "data_fundamental" / "val_em" / "val_em_all.csv",
                      usecols=["date", "code", "float_mv"], dtype={"code": str, "date": str})
    vem = vem[vem["date"] >= _cut][["date", "code", "float_mv"]].dropna()
    vem.to_csv(RECENT, index=False)
    log(f"fmv_recent 初始 {len(vem)} 行（{vem['date'].min()} ~ {vem['date'].max()}）")
else:
    rc = pd.read_csv(RECENT, dtype={"code": str, "date": str})
    snap_today = snap[["date", "code", "float_mv"]]
    rc = rc[rc["date"] != last_date]
    rc = pd.concat([rc, snap_today], ignore_index=True)
    rc = rc[rc["date"] >= _cut].dropna()
    rc.to_csv(RECENT, index=False)
    log(f"fmv_recent 更新 {len(rc)} 行（{rc['date'].min()} ~ {rc['date'].max()}）")

print(snap[snap["date"] == last_date].head(3).to_string(index=False))
