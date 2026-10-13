# -*- coding: utf-8 -*-
"""独立抽查：对「只有成交价、没有入场日 OHLC」的逐笔产物做**成交日可成交性**审计

做法：把 trades CSV 的 (symbol, entry_date/exit_date) 与 `data_full/<sym>.csv` join，
取该日 OHLCV 与前一交易日收盘，再用引擎判据判定：
  · 入场日：涨停开盘 / 一字涨停 / 停牌 → **买不进**
  · 出场日：跌停开盘 / 一字跌停 / 停牌 → **卖不出**

为什么必须单独做：这些族的 trades 只有 `entry_price`，**没有** prev_close/OHLC，
所以「入场日不可买」这件事在它们自己的产物里**无法自证**，只能靠外部 join。

用法：python audit_trades_tradability_spotcheck.py <trades.csv> [more.csv ...]
输出：evidence_trades_tradability_spotcheck.json
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DATA = r"D:\Documents\Quant data\data_full"
ENG = r"E:\PI\投资\fleur_absorb"
if ENG not in sys.path:
    sys.path.insert(0, ENG)

from engine import session as S  # noqa: E402

OUT = os.path.join(HERE, "evidence_trades_tradability_spotcheck.json")
_cache: dict[str, pd.DataFrame | None] = {}


def load_sym(sym: str):
    if sym in _cache:
        return _cache[sym]
    p = os.path.join(DATA, sym + ".csv")
    if not os.path.isfile(p):
        _cache[sym] = None
        return None
    try:
        df = pd.read_csv(p)
        df.columns = [str(c).strip().lower() for c in df.columns]
        df["date"] = df["date"].astype(str).str.slice(0, 10)
        _cache[sym] = df.sort_values("date").reset_index(drop=True)
    except Exception:  # noqa: BLE001
        _cache[sym] = None
    return _cache[sym]


def bar_at(df, date):
    """返回 (bar_dict | None, prev_close | None)。"""
    if df is None:
        return None, None
    hit = df.index[df["date"] == date]
    if len(hit) == 0:
        return None, None
    i = int(hit[0])
    r = df.iloc[i]
    bar = dict(open=r.get("open"), high=r.get("high"), low=r.get("low"),
               close=r.get("close"), volume=r.get("volume"))
    pc = float(df.iloc[i - 1]["close"]) if i >= 1 else None
    return bar, pc


def audit(path: str) -> dict:
    df = pd.read_csv(path, encoding="utf-8-sig")
    cols = {c.lower(): c for c in df.columns}
    sym_c = cols.get("symbol") or cols.get("sym") or cols.get("code")
    en_c = cols.get("entry_date") or cols.get("signal_date")
    ex_c = cols.get("exit_date")
    if not sym_c or not en_c:
        return dict(file=os.path.basename(path), status="unsupported",
                    reason="缺 symbol/entry_date 列：%s" % list(df.columns)[:12])
    n = len(df)
    miss_entry = n_unbuy = n_unbuy_one = n_unbuy_susp = 0
    n_exit = miss_exit = n_unsell = n_unsell_one = n_unsell_susp = 0
    ex_bad = []
    for r in df.itertuples(index=False):
        sym = str(getattr(r, sym_c))
        d = str(getattr(r, en_c))[:10]
        sub = load_sym(sym)
        bar, pc = bar_at(sub, d)
        if bar is None:
            miss_entry += 1
        else:
            ok, why = S.tradable_at_fill(bar, pc, S.board_of(sym), "buy")
            if not ok:
                n_unbuy += 1
                if "一字" in why:
                    n_unbuy_one += 1
                if "停牌" in why:
                    n_unbuy_susp += 1
                if len(ex_bad) < 8:
                    ex_bad.append(dict(sym=sym, date=d, side="entry", why=why))
        if ex_c:
            ed = getattr(r, ex_c)
            if isinstance(ed, str) and len(ed) >= 10:
                n_exit += 1
                ebar, epc = bar_at(sub, ed[:10])
                if ebar is None:
                    miss_exit += 1
                else:
                    ok2, why2 = S.tradable_at_fill(ebar, epc, S.board_of(sym), "sell")
                    if not ok2:
                        n_unsell += 1
                        if "一字" in why2:
                            n_unsell_one += 1
                        if "停牌" in why2:
                            n_unsell_susp += 1
    return dict(file=os.path.basename(path), status="ok", n_trades=n,
                entry=dict(bar_missing=miss_entry, not_buyable=n_unbuy,
                           one_word=n_unbuy_one, suspended=n_unbuy_susp,
                           pct=(round(100.0 * n_unbuy / max(1, n - miss_entry), 2))),
                exit=dict(n=n_exit, bar_missing=miss_exit, not_sellable=n_unsell,
                          one_word=n_unsell_one, suspended=n_unsell_susp,
                          pct=(round(100.0 * n_unsell / max(1, n_exit - miss_exit), 2))),
                examples=ex_bad)


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    res = [audit(os.path.join(REPO, a) if not os.path.isabs(a) else a) for a in args]
    ev = dict(_what="独立抽查：逐笔产物的成交日可成交性（join data_full）",
              data_dir=DATA, items=res)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(ev, fh, ensure_ascii=False, indent=1)
    for r in res:
        if r.get("status") != "ok":
            print("%-34s %s %s" % (r["file"][:34], r["status"], r.get("reason", "")))
            continue
        print("%-34s n=%-6d 入场不可买 %-5d (%.2f%%) [一字%d 停牌%d] | "
              "出场不可卖 %-5d (%.2f%%)"
              % (r["file"][:34], r["n_trades"], r["entry"]["not_buyable"], r["entry"]["pct"],
                 r["entry"]["one_word"], r["entry"]["suspended"],
                 r["exit"]["not_sellable"], r["exit"]["pct"]))
    print("\n已写出", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
