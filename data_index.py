# -*- coding: utf-8 -*-
"""data_full 索引层（manifest）—— 借鉴 Sequoia-X `sequoia_x/data/engine.py` 的工程写法
================================================================================
吸收来源：Sequoia-X/sequoia_x/data/engine.py (⭐7001)
  - `_CREATE_TABLE_SQL` L14-27  : `UNIQUE(symbol,date)` + `idx_symbol_date` 索引
  - `_get_last_date`    L72-78  : `SELECT MAX(date) WHERE symbol=?`   → 单只断点查询
  - `sync_today_bulk`   L105-108: `SELECT symbol, MAX(date) GROUP BY symbol` → 全量断点表
  - `backfill`          L192-194: 已入库即 skip，可断点续传
  - `sync_today_bulk`   L150-151: 按 date 先 DELETE 再 append（幂等覆盖）

本项目的差异与取舍（**不照搬**）：
  - 存储仍是 `data_full/<sym>.csv` 逐文件（**不改 SQLite**）——因为全仓库下游
    (v9_auto / khunter / build_dual_system …) 全部按 CSV 路径读取，改存储＝全链路重写，风险远大于收益。
  - 复权口径**保持前复权(qfq) 不动**——Sequoia-X 用后复权(adjustflag="1")，两者数值不可混，
    切换会让全部历史回测数值作废（见 MEMORY「前复权手写铁律」）。
  - 因此**只吸收"断点表 + 索引"这一工程思想**：把"每次跑都扫 1900+ 个 CSV 尾部"降级为
    "读一个 manifest"。SQL 的 `MAX(date) GROUP BY symbol` ≡ 本模块的 `build_index()/load_index()`。

manifest 形态：`data_full/_index.csv`  (sym, last_date, rows, mtime, size)
  - 由 build_index() 全量重建（扫全部 CSV 尾部）
  - 由 update_entry() 增量维护（更新完某只票即回写一行，无需重扫）
  - get_lag() 优先读 manifest；manifest 缺失/过期(>STALE_DAYS) → 自动 fallback 全量扫描

用法（库调用）：
    from data_index import load_index, get_lag, update_entry, build_index
    idx = load_index()                     # None 表示需重建
    lag = get_lag(target_date, idx)        # [(sym, "", "", tail)]  —— 与旧 scan_lag 返回同构
    update_entry(sym, last_date, rows)     # 更新完成一只即回写
"""
import os
import csv
import time
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = BASE / "data_full"
INDEX_FILE = OUT_DIR / "_index.csv"
FIELDS = ["sym", "last_date", "rows", "mtime", "size"]
STALE_DAYS = 3.0          # manifest 超过此天数未更新 → 判定过期，回退全量扫描
MIN_FILES = 100           # 文件数少于此时视为建库未完成，manifest 不可信


def tail_date(f):
    """快速读 csv 尾部日期（不加载全文件）—— 与 update_daily.tail_date 同实现"""
    try:
        with open(f, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 2048))
            tail = fh.read().decode("utf-8", errors="ignore")
        lines = [ln for ln in tail.strip().splitlines() if ln.strip()]
        return lines[-1].split(",")[0].strip() if lines else None
    except Exception:
        return None


def tail_rows(f):
    """尾部行数粗估（不精确，仅用于 manifest 的 rows 字段参考值）"""
    try:
        with open(f, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            return max(1, size // 70)      # 每行约 70 字节
    except Exception:
        return 0


def count_csv_files():
    n = 0
    for f in OUT_DIR.glob("*.csv"):
        if f.name.startswith("_"):
            continue
        if f.stat().st_size >= 100:
            n += 1
    return n


def build_index(verbose=True):
    """全量重建 manifest（≡ Sequoia-X `SELECT symbol, MAX(date) GROUP BY symbol`）
    返回 {sym: (last_date, rows, mtime, size)}"""
    t0 = time.time()
    idx = {}
    files = [f for f in sorted(OUT_DIR.glob("*.csv"))
             if not f.name.startswith("_") and f.stat().st_size >= 100]
    for f in files:
        td = tail_date(f)
        if td is None:
            continue
        st = f.stat()
        idx[f.stem] = (td, tail_rows(f), st.st_mtime, st.st_size)
    if verbose:
        print(f"  [index] 全量重建完成：{len(idx)} 只，耗时 {time.time()-t0:.1f}s", flush=True)
    save_index(idx)
    return idx


def save_index(idx):
    tmp = INDEX_FILE.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for sym, (td, rows, mtime, size) in idx.items():
            w.writerow([sym, td, rows, f"{mtime:.0f}", size])
    os.replace(tmp, INDEX_FILE)


def load_index(allow_stale=False):
    """读 manifest；缺失/过期/文件数明显不符 → 返回 None（调用方回退全量扫描）"""
    if not INDEX_FILE.exists():
        return None
    try:
        idx = {}
        with open(INDEX_FILE, "r", newline="", encoding="utf-8") as fh:
            r = csv.DictReader(fh)
            for row in r:
                if row.get("sym"):
                    idx[row["sym"]] = (row.get("last_date") or "",
                                       int(float(row.get("rows") or 0)),
                                       float(row.get("mtime") or 0),
                                       int(float(row.get("size") or 0)))
        if len(idx) < MIN_FILES:
            return None
        age_days = (time.time() - INDEX_FILE.stat().st_mtime) / 86400.0
        if not allow_stale and age_days > STALE_DAYS:
            return None
        n_disk = count_csv_files()
        # 磁盘文件数与 manifest 严重不符（新增/删除超过 10%）→ 不可信
        if n_disk > 0 and abs(n_disk - len(idx)) / max(n_disk, 1) > 0.10:
            return None
        return idx
    except Exception:
        return None


def get_lag(target_date, idx=None, verbose=True):
    """滞后清单。idx 为 None 时先尝试 load_index，失败则全量扫描。
    返回 [(sym, "", "", tail)] —— 与 update_daily.scan_lag 返回同构，可直接替换。"""
    used_index = False
    if idx is None:
        idx = load_index()
    if idx is not None:
        used_index = True
        lag = [(sym, "", "", td) for sym, (td, _r, _m, _s) in idx.items() if td and td < target_date]
    else:
        lag, ok_cnt = [], 0
        for f in sorted(OUT_DIR.glob("*.csv")):
            if f.name.startswith("_") or f.stat().st_size < 100:
                continue
            td = tail_date(f)
            if td is None:
                continue
            if td < target_date:
                lag.append((f.stem, "", "", td))
            else:
                ok_cnt += 1
        if verbose:
            print(f"  [index] 无可用 manifest → 全量扫描（最新 {ok_cnt} / 滞后 {len(lag)}）", flush=True)
        return lag
    if verbose:
        miss = len(idx)
        print(f"  [index] manifest 命中（{miss} 只已登记，滞后 {len(lag)} 只）", flush=True)
    return lag


def update_entry(sym, last_date, rows=0):
    """增量回写一行（更新完一只票即调用；O(1)，不重扫）
    ⚠ 若 manifest 不存在则静默跳过（等 build_index 全量重建）"""
    if not INDEX_FILE.exists():
        return False
    try:
        f = OUT_DIR / f"{sym}.csv"
        st = f.stat() if f.exists() else None
        with open(INDEX_FILE, "r", newline="", encoding="utf-8") as fh:
            rows_all = list(csv.DictReader(fh))
        hit = False
        for row in rows_all:
            if row.get("sym") == sym:
                row["last_date"] = last_date or ""
                row["rows"] = str(rows or row.get("rows") or 0)
                if st:
                    row["mtime"] = f"{st.st_mtime:.0f}"
                    row["size"] = str(st.st_size)
                hit = True
                break
        if not hit:
            rows_all.append({"sym": sym, "last_date": last_date or "",
                             "rows": str(rows or 0),
                             "mtime": f"{st.st_mtime:.0f}" if st else "0",
                             "size": str(st.st_size) if st else "0"})
        _incremental_flush = INDEX_FILE.with_suffix(".csv.tmp")
        with open(_incremental_flush, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            for row in rows_all:
                w.writerow({k: row.get(k, "") for k in FIELDS})
        os.replace(_incremental_flush, INDEX_FILE)
        return True
    except Exception:
        return False


def update_entries(pairs):
    """批量回写（更新完成后一次性写，避免 1900 次文件读写）
    pairs: [(sym, last_date, rows), ...]"""
    if not INDEX_FILE.exists() or not pairs:
        return False
    try:
        m = {s: (d, r) for s, d, r in pairs}
        with open(INDEX_FILE, "r", newline="", encoding="utf-8") as fh:
            rows_all = list(csv.DictReader(fh))
        for row in rows_all:
            s = row.get("sym")
            if s in m:
                d, r = m.pop(s)
                row["last_date"] = d or ""
                row["rows"] = str(r or row.get("rows") or 0)
                f = OUT_DIR / f"{s}.csv"
                if f.exists():
                    st = f.stat()
                    row["mtime"] = f"{st.st_mtime:.0f}"
                    row["size"] = str(st.st_size)
        for s, (d, r) in m.items():
            f = OUT_DIR / f"{s}.csv"
            st = f.stat() if f.exists() else None
            rows_all.append({"sym": s, "last_date": d or "", "rows": str(r or 0),
                             "mtime": f"{st.st_mtime:.0f}" if st else "0",
                             "size": str(st.st_size) if st else "0"})
        tmp = INDEX_FILE.with_suffix(".csv.tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            for row in rows_all:
                w.writerow({k: row.get(k, "") for k in FIELDS})
        os.replace(tmp, INDEX_FILE)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    import sys
    if "--build" in sys.argv:
        build_index()
    else:
        i = load_index()
        print("manifest:", "OK" if i else "None（需重建）", f"({len(i) if i else 0} 只)")
        print("CSV 文件数:", count_csv_files())
