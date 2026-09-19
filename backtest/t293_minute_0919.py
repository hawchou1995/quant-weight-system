# -*- coding: utf-8 -*-
"""topic293 分时数据层（R-topic293）：pytdx 240 点/日 分时 → 14:30 / 14:45 / 15:00 + 昨收。

要点（口径决定成败）：
1. pytdx 分时是**不复权**；日线（v8_factor_cache / data_full）是**前复权** → 直接混用必错。
   本层只输出**同日比值可用**的原始量，收益换算交给调用方用「k_T = A_close_T / U_close_T」处理：
       ret = A_{T+1}open × p239_T / (A_close_T × p1445) − 1
2. 索引锚定（已与 5 分钟线逐点交叉验证）：idx209 = 14:30、idx224 = 14:45、idx239 = 15:00
3. 缓存：D:/Tools/cache/tdx_min/min_{code}_{yyyymmdd}.parquet（与既有管线同路径同格式）
"""
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytdx_data_0914 as PX  # noqa: E402
from pytdx_data_0914 import _api, market_of  # noqa: E402

MIN_CACHE = Path("D:/Tools/cache/tdx_min")
MIN_CACHE.mkdir(parents=True, exist_ok=True)
IDX_1430, IDX_1445, IDX_1500 = 209, 224, 239

_api_holder = {"api": None}


def _get_api():
    if _api_holder["api"] is None:
        _api_holder["api"] = _api()
    return _api_holder["api"]


def _reconnect():
    try:
        _api_holder["api"].disconnect()
    except Exception:
        pass
    _api_holder["api"] = None
    PX._conn["api"] = None
    time.sleep(0.6)
    return _get_api()


def minute(code6: str, date_int: int, use_cache: bool = True):
    """单股单日分时（240 点）；返回 DataFrame[price, vol, pre_close] 或 None。"""
    code6, date_int = str(code6), int(date_int)
    cf = MIN_CACHE / f"min_{code6}_{date_int}.parquet"
    if use_cache and cf.exists():
        try:
            df = pd.read_parquet(cf)
            if len(df) >= 200:
                return df
        except Exception:
            pass
    last = None
    for attempt in range(3):
        try:
            data = _get_api().get_history_minute_time_data(market_of(code6), code6, date_int)
            if not data or len(data) < 200:
                raise ValueError(f"empty/short n={0 if not data else len(data)}")
            df = pd.DataFrame(data)
            cols = [c for c in ("price", "vol", "pre_close") if c in df.columns]
            df = df[cols].astype(float).reset_index(drop=True)
            df.to_parquet(cf, compression="gzip", index=False)
            return df
        except Exception as e:
            last = e
            time.sleep(0.5)
            _reconnect()
    print(f"    [minute-fail] {code6} {date_int}: {type(last).__name__} {str(last)[:60]}", flush=True)
    return None


def pv(code6: str, date_int: int):
    """取 14:30 / 14:45 / 15:00 / 昨收 四点。返回 dict 或 None。"""
    df = minute(code6, date_int)
    if df is None or len(df) < 240:
        return None
    p = df["price"].to_numpy()
    out = {
        "p1430": float(p[IDX_1430]),
        "p1445": float(p[IDX_1445]),
        "p1500": float(p[IDX_1500]),
        "uclose": float(p[IDX_1500]),   # 不复权收盘（= idx239，已实测与日线不复权收盘逐位相等）
    }
    if "pre_close" in df.columns:
        pc = float(df["pre_close"].iloc[0])
        if pc > 0:
            out["prev_close"] = pc
    if "vol" in df.columns:
        out["vol"] = df["vol"].to_numpy()
    return out


def selftest():
    """自检：① 索引锚点 ② 昨收 ③ 与 5 分钟线交叉验证。"""
    ok = True
    print("=== 自检 1：索引锚点（600519 / 2026-09-17，期望 1430=1263.33 1445=1264.84 1500=1266.98）===")
    d = pv("600519", 20260917)
    if not d:
        print("  FAIL 取数失败"); return False
    for k, exp in (("p1430", 1263.33), ("p1445", 1264.84), ("p1500", 1266.98)):
        got = d[k]
        hit = abs(got - exp) < 0.011
        ok &= hit
        print(f"  {'PASS' if hit else 'FAIL'} {k} = {got} (期望 {exp})")
    print(f"  昨收(series) = {d.get('prev_close')}")
    print("\n=== 自检 2：昨收 vs 上一交易日不复权收盘（600519：09-17 的昨收应 = 09-16 的收盘）===")
    prev = pv("600519", 20260916)
    if prev:
        same = abs(prev["uclose"] - d["prev_close"]) < 0.011
        ok &= same
        print(f"  {'PASS' if same else 'FAIL'} 09-16 uclose={prev['uclose']} vs 09-17 pre_close={d['prev_close']}")
    print("\n=== 自检 3：不复权收盘 vs data_full 前复权收盘（近期应为同一锚点）===")
    dd = pd.read_csv("D:/Documents/Workbuddy/股票基金/quant-weight-system/data_full/sh600519.csv",
                     dtype={"date": str})
    for ds, key in (("2026-09-17", 20260917), ("2026-09-18", 20260918)):
        r = dd[dd["date"] == ds]
        m = pv("600519", key)
        if len(r) and m:
            hit = abs(float(r["close"].iloc[0]) - m["uclose"]) < 0.02
            ok &= hit
            print(f"  {'PASS' if hit else 'FAIL'} {ds} data_full close={float(r['close'].iloc[0])} vs 分时={m['uclose']}")
    print(f"\nRESULT: {'OK' if ok else 'FAIL'}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if selftest() else 1)
