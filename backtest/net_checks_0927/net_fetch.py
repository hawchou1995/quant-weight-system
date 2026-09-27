# -*- coding: utf-8 -*-
"""Rate-limited, retrying akshare fetchers for the two ALLOWED sources:
   - Sina    : ak.stock_zh_a_daily(symbol, adjust)      (full history, sliced client-side)
   - Tencent : ak.stock_zh_a_hist_tx(symbol, start_date, end_date, adjust)
Eastern (EM) endpoints are deliberately NOT used.

Every successful / failed response is cached on disk so a run can be resumed.
"""
import hashlib
import json
import os
import time

import akshare as ak
import pandas as pd
import requests as _requests
import threading as _threading

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

MIN_INTERVAL = 0.5      # seconds between consecutive top-level akshare calls (>= 0.4 required)
MAX_RETRY = 2           # retries AFTER the first attempt  (task says "retry <= 2 times")
MAX_ATTEMPT_TOTAL = 3   # a cached failure is re-attempted until it has had this many attempts
TX_TIMEOUT = 20.0
CALL_TIMEOUT = 90.0   # watchdog: abandon a hung akshare call

# --- global request timeout shim: akshare calls requests.get() without a timeout,
# --- which can block forever on a stalled socket.
_REQ_TIMEOUT = 20.0
_orig_get = _requests.get


def _get_timed(url, **kw):
    kw.setdefault("timeout", _REQ_TIMEOUT)
    return _orig_get(url, **kw)


_requests.get = _get_timed
_orig_sess_request = _requests.Session.request


def _sess_request_timed(self, method, url, **kw):
    kw.setdefault("timeout", _REQ_TIMEOUT)
    return _orig_sess_request(self, method, url, **kw)


_requests.Session.request = _sess_request_timed


def _run_guarded(fn):
    box = {}

    def worker():
        try:
            box["r"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["e"] = exc

    th = _threading.Thread(target=worker, daemon=True)
    th.start()
    th.join(CALL_TIMEOUT)
    if th.is_alive():
        raise TimeoutError("akshare call exceeded watchdog %.0fs" % CALL_TIMEOUT)
    if "e" in box:
        raise box["e"]
    return box["r"]

STATE = {"calls": 0, "retries": 0, "hard_fail": 0, "cache_hits": 0, "last": 0.0}


def stats():
    return dict(STATE)


def _throttle():
    dt = time.time() - STATE["last"]
    if dt < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - dt)
    STATE["last"] = time.time()


def _paths(key):
    h = hashlib.md5(key.encode("utf-8")).hexdigest()[:12]
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in key)[:90]
    stem = os.path.join(CACHE_DIR, safe + "__" + h)
    return stem + ".csv", stem + ".err.json"


def _read_cache(key):
    csv_p, err_p = _paths(key)
    if os.path.exists(csv_p):
        try:
            df = pd.read_csv(csv_p, dtype={"date": str})
            STATE["cache_hits"] += 1
            return df, None, True
        except Exception:
            os.remove(csv_p)
    if os.path.exists(err_p):
        try:
            with open(err_p, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            obj = {"attempts": 0, "err": "unreadable error cache"}
        if int(obj.get("attempts", 0)) >= MAX_ATTEMPT_TOTAL:
            STATE["cache_hits"] += 1
            return None, obj.get("err", ""), True
        return None, None, False
    return None, None, False


def _write_err(key, err, attempts):
    _csv_p, err_p = _paths(key)
    tmp = err_p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"attempts": attempts, "err": err}, f, ensure_ascii=False)
    os.replace(tmp, err_p)


def _write_csv(key, df):
    csv_p, _err_p = _paths(key)
    tmp = csv_p + ".tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, csv_p)


KEEP = ["date", "open", "high", "low", "close", "volume", "amount"]


def _normalize(df):
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df[df["date"].notna()]
    keep = [c for c in KEEP if c in df.columns]
    df = df[keep]
    for c in keep:
        if c != "date":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    return df


def fetch(key, fn):
    """Returns (dataframe_or_None, error_or_None). Cached on disk."""
    df, err, cached = _read_cache(key)
    if cached:
        return df, err
    n_err = 0
    last_err = ""
    for attempt in range(MAX_RETRY + 1):
        _throttle()
        STATE["calls"] += 1
        if attempt > 0:
            STATE["retries"] += 1
        try:
            out = _run_guarded(fn)
            if out is None:
                raise RuntimeError("None returned")
            out = pd.DataFrame(out)
            if len(out) == 0:
                raise RuntimeError("empty dataframe")
            df = _normalize(out)
            if len(df) == 0:
                raise RuntimeError("empty after normalize")
            _write_csv(key, df)
            return df, None
        except Exception as exc:  # noqa: BLE001
            last_err = "%s: %s" % (type(exc).__name__, str(exc)[:400])
            n_err += 1
            if attempt < MAX_RETRY:
                time.sleep(0.8 * (attempt + 1))
    STATE["hard_fail"] += 1
    _write_err(key, last_err, MAX_ATTEMPT_TOTAL)
    return None, last_err


def sina(sym, adjust, start="19900101", end="21000118"):
    key = "sina|%s|%s|%s|%s" % (sym, adjust, start, end)
    return fetch(key, lambda: ak.stock_zh_a_daily(symbol=sym, start_date=start,
                                                  end_date=end, adjust=adjust))


def tx(sym, adjust, start_date, end_date):
    key = "tx|%s|%s|%s|%s" % (sym, adjust, start_date, end_date)
    return fetch(key, lambda: ak.stock_zh_a_hist_tx(symbol=sym, start_date=start_date,
                                                    end_date=end_date, adjust=adjust,
                                                    timeout=TX_TIMEOUT))
