# -*- coding: utf-8 -*-
"""Shared constants / helpers for the two-source cross-check."""
import json
import os
import random
import re

import akshare as ak
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "out")
os.makedirs(OUT_DIR, exist_ok=True)

DATA_FULL = r"D:\Documents\Workbuddy\股票基金\quant-weight-system\data_full"

SEED = 20260926
N_SAMPLE = int(os.environ.get("NETCHECKS_N", "120"))

SYM_RE = re.compile(r"^(sh|sz|bj)\d{6}$")


def list_symbols():
    files = [f for f in os.listdir(DATA_FULL) if f.endswith(".csv")]
    syms = sorted(f[:-4] for f in files if SYM_RE.match(f[:-4]))
    others = sorted(f[:-4] for f in files if not SYM_RE.match(f[:-4]))
    return syms, others


def sample_symbols(syms, n=N_SAMPLE, seed=SEED):
    rng = random.Random(seed)
    return sorted(rng.sample(syms, min(n, len(syms))))


_cal = None


def calendar():
    global _cal
    if _cal is None:
        df = ak.tool_trade_date_hist_sina()
        d = pd.to_datetime(df["trade_date"], errors="coerce").dropna()
        _cal = pd.DatetimeIndex(sorted(d.unique()))
    return _cal


def window(n_days=250):
    """Last n_days trade dates of the official SSE calendar that are <= today."""
    cal = calendar()
    today = pd.Timestamp.today().normalize()
    past = cal[cal <= today]
    end = past[-1]
    start = past[-n_days]
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), past[-n_days:]


def write_json(name, obj):
    p = os.path.join(OUT_DIR, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
    return p


def classify(sym):
    code = sym[2:]
    if sym.startswith("sh"):
        if code[:3] in ("600", "601", "603", "605", "688"):
            return "sh_stock"
        if code[:3] == "900":
            return "b_share"
        return "sh_fund_or_other"
    if sym.startswith("sz"):
        if code[:3] in ("000", "001", "002", "003", "300", "301", "302"):
            return "sz_stock"
        if code[:3] == "200":
            return "b_share"
        return "sz_fund_or_other"
    return "bj_stock"
