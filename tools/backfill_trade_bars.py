# -*- coding: utf-8 -*-
"""给历史逐笔记录回填「当日 bar 快照」——让 gate_trading_clock 的 G4b/G5 真正可判。

背景
----
`gate_trading_clock.py` 的 G5 三条成交口径（来源 gushi topic/1010）必须知道成交日的
open/high/low 与前收；但本仓历史 `*trades*.jsonl` 只记 `entry_open`/`exit_px`，
不带 bar 快照 → 门禁只能报「不可判」。本工具**不改回测逻辑、不改任何收益数字**，
只按 (sym, date) 从本机只读日线补齐 bar 快照，并把结果写成新文件（原文件不动）。

同时做一次口径核对：记录里的 `entry_open` 与本机日线的开盘价是否一致（差值分布），
避免把复权口径差当成数据错误 —— 本机日线是**前复权**、记录里多是**原始价**，
所以「差 >1 分」是常态，属复权因子，不是数据错误。

用法
----
    python tools/backfill_trade_bars.py <输入 jsonl> <输出 jsonl> [--only-claimed]
    python tools/backfill_trade_bars.py --dir <目录> [--suffix _bar] [--only-claimed]
    # 批量模式默认跳过 .x3cache，且不碰已带后缀的输出文件

输出字段（在原记录上新增，不动原字段）：
    bar        : {open, high, low, close, volume, prev_close}
    exit_bar   : 同上（exit_date 那天）
    prev_close : 入场日的前收（顶层，仅在原记录缺该字段时补，兼容只读顶层的旧消费端）

`--only-claimed`：只保留**声称成交**的记录（`filled` 真值 或 `entry_px > 0`）。
用途是把可判集压到很小、便于入库（例：26,038 条日志 → 1,182 条），
剩下未成交的记录本来也不该被审「能不能成交」。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

DEFAULT_DATA_ROOT = Path(r"D:/Documents/Quant data/data_full")
_cache: dict[str, dict] = {}


def market_of(code: str) -> str:
    c = str(code).lower()
    if c.startswith(("sh", "sz", "bj")):
        return c[:2]
    if c.startswith(("60", "68", "69", "90")):
        return "sh"
    if c.startswith(("00", "30", "20")):
        return "sz"
    return "bj"


def bare_code(sym: str) -> str:
    s = str(sym).lower()
    return s[2:] if s.startswith(("sh", "sz", "bj")) else s


def load_series(sym: str, root: Path) -> dict:
    """本机只读日线：返回 {date: {open,high,low,close,volume}}（带缓存）。"""
    key = f"{root}|{sym}"
    if key in _cache:
        return _cache[key]
    fp = root / f"{market_of(sym)}{bare_code(sym)}.csv"
    rows: dict[str, dict] = {}
    if fp.is_file():
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                for r in csv.DictReader(f):
                    try:
                        rows[r["date"]] = {
                            "open": float(r["open"]), "high": float(r["high"]),
                            "low": float(r["low"]), "close": float(r["close"]),
                            "volume": float(r.get("volume") or 0.0),
                        }
                    except (KeyError, ValueError):
                        continue
        except OSError:
            rows = {}
    _cache[key] = rows
    return rows


def bar_with_prev(series: dict, date: str, dates: list[str] | None = None) -> dict | None:
    """取该日 bar，并附上「前一个交易日的收盘」作为 prev_close。"""
    if date not in series:
        return None
    if dates is None:
        dates = sorted(series)
    i = dates.index(date)
    prev = series[dates[i - 1]]["close"] if i > 0 else None
    b = dict(series[date])
    b["prev_close"] = prev
    return b


def claims_fill(rec: dict) -> bool:
    """记录是否**声称成交**（与门禁 G5 同判据）：`filled` 真值，或 `entry_px` 为正。"""
    if rec.get("filled") in (True, 1, "1", "true", "True"):
        return True
    try:
        return float(rec.get("entry_px")) > 0
    except (TypeError, ValueError):
        return False


def process(in_path: Path, out_path: Path, root: Path, only_claimed: bool = False) -> dict:
    """回填一个 jsonl。返回统计（含 kept / skipped_unclaimed）。"""
    n = n_in = n_out = n_mismatch = n_skip_unclaimed = 0
    max_diff = 0.0
    with open(in_path, "r", encoding="utf-8", errors="replace") as fi, \
            open(out_path, "w", encoding="utf-8") as fo:
        for line in fi:
            s = line.strip()
            if not s:
                continue
            n += 1
            try:
                rec = json.loads(s)
            except Exception:  # noqa: BLE001
                fo.write(line)
                continue
            if only_claimed and not claims_fill(rec):
                n_skip_unclaimed += 1
                continue
            sym = rec.get("sym")
            series = load_series(str(sym), root) if sym else {}
            dates = sorted(series) if series else []
            ed, xd = rec.get("entry_date"), rec.get("exit_date")
            be = bar_with_prev(series, ed, dates) if ed else None
            bx = bar_with_prev(series, xd, dates) if xd else None
            if be:
                rec["bar"] = be
                if rec.get("prev_close") is None:
                    rec["prev_close"] = be.get("prev_close")
                n_in += 1
                eo = rec.get("entry_open")
                if eo is not None:
                    try:
                        d = abs(float(eo) - float(be["open"]))
                    except (TypeError, ValueError):
                        d = 0.0
                    if d > 0.011:
                        n_mismatch += 1
                    max_diff = max(max_diff, d)
            if bx:
                rec["exit_bar"] = bx
                n_out += 1
            fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"file": in_path.name, "records": n, "kept": n - n_skip_unclaimed,
            "skipped_unclaimed": n_skip_unclaimed,
            "entry_bar_filled": n_in, "exit_bar_filled": n_out,
            "entry_open_mismatch_gt_1cent": n_mismatch, "max_open_diff": round(max_diff, 4),
            "out": out_path.name}


def main() -> int:
    ap = argparse.ArgumentParser(description="逐笔记录回填当日 bar（只读日线，不改收益）")
    ap.add_argument("src", help="输入 jsonl，或配合 --dir 使用目录")
    ap.add_argument("dst", nargs="?", help="输出 jsonl（单文件模式）")
    ap.add_argument("--dir", action="store_true", help="把 src 当目录，批量处理 *trades*.jsonl")
    ap.add_argument("--suffix", default="_bar", help="批量模式输出后缀（默认 _bar）")
    ap.add_argument("--only-claimed", action="store_true",
                    help="只保留声称成交的记录（filled 真值 或 entry_px>0），便于入库")
    ap.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    ap.add_argument("--json", default=None, help="统计落盘路径")
    a = ap.parse_args()
    root = Path(a.data_root)
    if not root.is_dir():
        print(f"日线目录不存在：{root}", file=sys.stderr)
        return 1
    print(f"日线真值源：{root}")
    stats = []
    if a.dir:
        src = Path(a.src)
        files = sorted(p for p in src.rglob("*trades*.jsonl")
                       if ".x3cache" not in p.parts and a.suffix not in p.stem)
        print(f"批量模式：{len(files)} 个文件")
        for p in files:
            out = p.with_name(p.stem + a.suffix + ".jsonl")
            st = process(p, out, root, only_claimed=a.only_claimed)
            stats.append(st)
            print(f"  {st}")
    else:
        if not a.dst:
            print("单文件模式需要 <输出 jsonl>", file=sys.stderr)
            return 1
        st = process(Path(a.src), Path(a.dst), root, only_claimed=a.only_claimed)
        stats.append(st)
        print(f"  {st}")
    if a.json:
        Path(a.json).write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已写出 {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
