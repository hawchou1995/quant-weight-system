# -*- coding: utf-8 -*-
"""TickFlow 批量增量更新器（2026-09-08 投产）
=================================================
来源：KHunter 开源项目 `utils/stock_data_fetcher.py::_fetch_stock_batch_tickflow` 的现成思路
（一次 HTTP 请求批量拿 100 只，替代 akshare 逐只 py_mini_racer JS 解码）。

性能实测（2026-09-08）：
  - TickFlow: 100 只/批 × 0.83s，10 批并发 → 1000 只 1.13s → 7419 只约 8-10 秒
  - akshare 串行: ~1.79s/只 → 7419 只约 3.7 小时（8 线程并行仍 ~1 只/s = 88 分钟）
  - 本脚本替代 update_daily.py 的拉取步骤（快 400+ 倍）

口径验证（对 akshare qfq 逐日比对 sh600000 2016-2026 共 2578 天）：
  open/high/low/close max 相对误差 0.13%（复权基准微差），amount 完全一致
  ⚠ volume 单位 = 手，需 ×100 转股，与本地 CSV 口径对齐

用法：
  python tickflow_update.py                    # 全量增量（扫描滞后文件）
  python tickflow_update.py --all              # 全库全量重建
  python tickflow_update.py --limit 500        # 只更新前 500 只滞后
  python tickflow_update.py --workers 10       # 并发批数（默认 10）
"""
import sys
import os
import csv
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = BASE / "data_full"
TF_API = "https://free-api.tickflow.org/v1/klines/batch"
BATCH_SIZE = 100          # API 硬上限 100
HIST_DAYS = 10000         # 足够覆盖全部上市历史
HEADERS = {"User-Agent": "Mozilla/5.0"}

session = requests.Session()
session.headers.update(HEADERS)


def to_tf_symbol(sym: str) -> str:
    """sh600000 -> 600000.SH"""
    code = sym[2:]
    if sym.startswith("sh"):
        return code + ".SH"
    if sym.startswith("sz"):
        return code + ".SZ"
    if sym.startswith("bj"):
        return code + ".BJ"
    return code


def last_date_of(path: Path):
    """读本地 CSV 末行日期（无文件返回 None）"""
    try:
        with open(path, encoding="utf-8") as f:
            last = None
            for line in f:
                line = line.strip()
                if line and not line.startswith("date"):
                    last = line.split(",")[0]
        return last
    except Exception:
        return None


def scan_lag(symbols=None):
    """扫描滞后文件：返回 [(sym, last_date), ...]（末行 < 全库最新日期）"""
    files = sorted(DATA_DIR.glob("*.csv"))
    if symbols:
        want = set(symbols)
        files = [f for f in files if f.stem in want]
    latest = None
    meta = []
    for f in files:
        d = last_date_of(f)
        if d:
            meta.append((f.stem, d))
            if latest is None or d > latest:
                latest = d
    lag = [(s, d) for s, d in meta if d < latest] if latest else []
    return lag, latest


def fetch_batch(batch):
    """拉一批（<=100 只），返回 {sym: rows} 或抛异常"""
    syms = [to_tf_symbol(s) for s in batch]
    params = {
        "symbols": ",".join(syms),
        "period": "1d",
        "count": HIST_DAYS,
        "adjust": "forward",
    }
    r = session.get(TF_API, params=params, timeout=max(30, 15 + len(batch) * 0.3))
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
    data = r.json().get("data", {})
    out = {}
    for sym in batch:
        ts = to_tf_symbol(sym)
        d = data.get(ts)
        if not d or not d.get("timestamp"):
            out[sym] = []
            continue
        rows = []
        for i, t in enumerate(d["timestamp"]):
            dt = datetime.fromtimestamp(t / 1000).strftime("%Y-%m-%d")
            if dt < "2016-01-01":
                continue
            vol = d["volume"][i]
            rows.append((
                dt,
                d["open"][i], d["high"][i], d["low"][i], d["close"][i],
                int(vol) * 100 if vol else 0,      # ⚠ 手 → 股
                d["amount"][i] if d.get("amount") else 0,
            ))
        out[sym] = rows
    return out


def merge_and_save(sym: str, rows):
    """合并本地 + 新数据，原子写。返回最终行数。"""
    f = DATA_DIR / f"{sym}.csv"
    seen = {}
    if f.exists():
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\r\n")
                if not line or line.startswith("date"):
                    continue
                p = line.split(",")
                if len(p) >= 6:
                    seen[p[0]] = ",".join(p[:7])
    for row in rows:
        seen[row[0]] = f"{row[0]},{row[1]},{row[2]},{row[3]},{row[4]},{row[5]},{row[6]}"
    sorted_dates = sorted(seen)
    out = ["date,open,high,low,close,volume,amount"]
    out.extend(seen[d] for d in sorted_dates)
    tmp = f.with_suffix(".csv.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    os.replace(tmp, f)
    return len(sorted_dates)


def load_skip_list(skip_file: Path, ttl_days: int):
    """读取跳过清单 sym,date 两列；返回 {sym} 中未过期部分。

    ⚠ 2026-09-08 加 TTL：停牌股复牌/ETF 恢复交易后必须能重新拉取，
    否则会被永久跳过。超过 ttl_days（默认 30 天）的条目自动失效重试。
    ⚠ 旧格式（仅 sym 无日期）视为「今日新登记」并原地迁移，避免被当永不过期。
    """
    if not skip_file.exists():
        return set()
    today = date.today()
    live = set()
    need_migrate = False
    for line in skip_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        sym = parts[0].strip()
        if not sym:
            continue
        d = parts[1].strip() if len(parts) > 1 else ""
        if not d:
            need_migrate = True          # 旧格式：补日期戳
            live.add(sym)
            continue
        try:
            age = (today - datetime.strptime(d, "%Y-%m-%d").date()).days
            if age > ttl_days:
                continue          # 过期 → 不再跳过（自动重试）
        except Exception:
            need_migrate = True
        live.add(sym)
    if need_migrate and live:
        # 原地迁移为 sym,date 格式（今日为基准，TTL 从此日算起）
        save_skip_list(skip_file, live, set())
        print(f"  ↻ 跳过清单已迁移为带日期格式（{len(live)} 只）", flush=True)
    return live


def save_skip_list(skip_file: Path, syms, keep: set):
    """写回跳过清单（保留未过期旧条目 + 新增），格式 sym,YYYY-MM-DD"""
    today = date.today().strftime("%Y-%m-%d")
    all_syms = set(keep) | set(syms)
    if not all_syms:
        return 0
    skip_file.write_text("\n".join(f"{s},{today}" for s in sorted(all_syms)) + "\n", encoding="utf-8")
    return len(all_syms)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="全库全量（不扫描滞后）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 只")
    ap.add_argument("--workers", type=int, default=10, help="并发批数")
    ap.add_argument("--symbols", default="", help="逗号分隔的指定代码")
    ap.add_argument("--no-skip", action="store_true", help="不跳过已知无源清单")
    ap.add_argument("--skip-ttl", type=int, default=30, help="跳过清单有效期天数（默认 30）")
    args = ap.parse_args()

    t0 = time.time()
    syms = [s.strip() for s in args.symbols.split(",") if s.strip()] or None

    if args.all:
        targets = [(f.stem, last_date_of(f)) for f in sorted(DATA_DIR.glob("*.csv"))]
        latest = max((d for _, d in targets if d), default="")
        print(f"全量模式: {len(targets)} 只（最新日期 {latest}）", flush=True)
    else:
        lag, latest = scan_lag(syms)
        targets = lag
        print(f"滞后扫描: {len(targets)} 只待更新（全库最新 {latest}）", flush=True)

    # 跳过已知无源（退市/长期停牌/源不提供）——2026-09-08：每次重试白耗 15s
    # TTL 30 天：过期自动重试，防停牌复牌被永久跳过
    skip_file = BASE / "data_full_skip_list.csv"
    known = set()
    if not args.no_skip and not args.all:
        known = load_skip_list(skip_file, args.skip_ttl)
        _before = len(targets)
        targets = [x for x in targets if x[0] not in known]
        print(f"跳过已知无源 {_before - len(targets)} 只（TTL {args.skip_ttl} 天，--no-skip 可强制重试）", flush=True)

    if args.limit:
        targets = targets[: args.limit]
    if not targets:
        print("✅ 无滞后，无需更新", flush=True)
        return

    batches = [targets[i:i + BATCH_SIZE] for i in range(0, len(targets), BATCH_SIZE)]
    print(f"分 {len(batches)} 批 × ≤{BATCH_SIZE} 只，{args.workers} 并发", flush=True)

    ok = fail = 0
    fails = []          # 无数据（退市/停牌/源不提供）
    stale = []          # 有数据但源本身仍滞后（末行 < 全库最新）——同样应跳过，否则每次重试
    done = 0
    latest_global = latest if not args.all else ""

    def work(batch):
        syms_b = [s for s, _ in batch]
        return syms_b, fetch_batch(syms_b)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, b): b for b in batches}
        for fut in as_completed(futs):
            batch = futs[fut]
            try:
                syms_b, res = fut.result()
                for sym in syms_b:
                    rows = res.get(sym) or []
                    if rows:
                        merge_and_save(sym, rows)
                        # ⚠ 2026-09-08：源本身滞后（返回数据但末行仍 < 全库最新）→ 归入 stale
                        if latest_global and (last_date_of(DATA_DIR / f"{sym}.csv") or "") < latest_global:
                            stale.append(sym)
                        else:
                            ok += 1
                    else:
                        fail += 1
                        fails.append(sym)
            except Exception as e:
                for sym, _ in batch:
                    fail += 1
                    fails.append(sym)
                print(f"  ⚠ 批失败: {str(e)[:100]}", flush=True)
            done += 1
            if done % 10 == 0 or done == len(batches):
                print(f"  [{done}/{len(batches)} 批] 已更新 {ok} / 源滞后 {len(stale)} / 无数据 {fail} 耗时 {time.time()-t0:.0f}s", flush=True)

    el = time.time() - t0
    print(f"\n✅ TickFlow 更新完成: 已更新 {ok} / 源滞后 {len(stale)} / 无数据 {fail} / 总 {len(targets)}，耗时 {el:.1f}s", flush=True)
    if fails:
        fp = BASE / "data_full_fail_list_tickflow.csv"
        fp.write_text("\n".join(fails) + "\n", encoding="utf-8")
        print(f"无数据清单: {fp.name}（{len(fails)} 只，多为退市/停牌）", flush=True)
    # 累计到跳过清单：无数据 + 源滞后（下次不再重试；TTL 到期或 --no-skip 可强制）
    skip_add = fails + stale
    if skip_add:
        try:
            n = save_skip_list(skip_file, skip_add, known)
            print(f"跳过清单: {skip_file.name}（累计 {n} 只，含无数据 {len(fails)} + 源滞后 {len(stale)}，TTL {args.skip_ttl} 天）", flush=True)
        except Exception as e:
            print(f"⚠ 跳过清单写入失败: {e}", flush=True)


if __name__ == "__main__":
    main()
