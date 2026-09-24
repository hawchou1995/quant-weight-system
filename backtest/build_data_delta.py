# -*- coding: utf-8 -*-
"""云端：把「最近 N 个交易日的全市场日线」压成一个小 delta 工件，供本机同步 K 线用。

为什么：data_full/ 在 cloud runner 的 actions/cache 里，本机拿不到；而本机链已停用
（本机 data_full/index_000300.csv 不再自动更新）。本脚本在云端链跑完后产出
_cloud_delta/{delta_bars.csv,index_000300_tail.csv,delta_meta.json}，
由 workflow 用 actions/upload-artifact 上传（约 0.2~1MB/日），本机用 apply_data_delta.py 合并。

用法（云端）：python -X utf8 backtest/build_data_delta.py --out _cloud_delta
纯标准库，无第三方依赖。
"""
import argparse, gzip, json, os, re, sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_cloud_delta", help="输出目录")
    ap.add_argument("--days", type=int, default=3, help="每只票最多带最近 N 根（默认 3）")
    ap.add_argument("--index-rows", type=int, default=30, help="index_000300.csv 尾部行数")
    ap.add_argument("--data-dir", default=str(REPO / "data_full"))
    ap.add_argument("--index", default=str(REPO / "index_000300.csv"))
    ap.add_argument("--gzip", action="store_true", help="额外产出 delta_bars.csv.gz")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    dd = Path(a.data_dir)
    if not dd.is_dir():
        print("[warn] data_full 不存在：%s → 产出空 delta（rc=0）" % dd)
        (out / "delta_meta.json").write_text(json.dumps(
            {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "error": "data_full missing",
             "codes": 0, "rows": 0, "dates": []}, ensure_ascii=False), encoding="utf-8")
        return 0

    # 1) 收集每只票的尾部 N 根（只认 (sh|sz|bj)\d{6}.csv；data_full 里还有 index 类非行情文件）
    per_code = {}
    pat = re.compile(r"^(sh|sz|bj)(\d{6})\.csv$")
    dpat = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for p in sorted(dd.glob("*.csv")):
        m = pat.match(p.name)
        if not m:
            continue
        code = m.group(2)
        try:
            lines = p.read_text(encoding="utf-8").strip().splitlines()
        except Exception:
            continue
        if len(lines) < 2:
            continue
        tail = [l for l in lines[-a.days:] if l and not l.startswith("date") and dpat.match(l.split(",")[0])]
        if tail:
            per_code[code] = tail

    # 2) 只保留「全市场最近 N 个不同交易日」的行（避免带上停牌股的陈行）
    alldates = sorted({l.split(",")[0] for tail in per_code.values() for l in tail})
    keep = set(alldates[-a.days:]) if alldates else set()

    rows, codes_kept = [], set()
    for code, tail in per_code.items():
        for l in tail:
            f = l.split(",")
            if len(f) >= 5 and f[0] in keep:
                rows.append((code, f[0], f[1], f[2], f[3], f[4],
                             f[5] if len(f) > 5 else "", f[6] if len(f) > 6 else ""))
                codes_kept.add(code)
    rows.sort(key=lambda r: (r[0], r[1]))

    # 3) 写盘
    bp = out / "delta_bars.csv"
    with bp.open("w", encoding="utf-8", newline="") as fh:
        fh.write("code,date,open,high,low,close,volume,amount\n")
        for r in rows:
            fh.write(",".join(str(x) for x in r) + "\n")
    if a.gzip:
        with bp.open("rb") as fi, gzip.open(str(bp) + ".gz", "wb") as fo:
            fo.write(fi.read())

    idx_src = Path(a.index)
    idx_tail = []
    if idx_src.exists():
        lines = idx_src.read_text(encoding="utf-8").strip().splitlines()
        idx_tail = lines[:1] + lines[-a.index_rows:]
        (out / "index_000300_tail.csv").write_text("\n".join(idx_tail) + "\n", encoding="utf-8")

    meta = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "dates": sorted(keep), "codes": len(codes_kept), "rows": len(rows),
            "delta_bytes": bp.stat().st_size,
            "index_rows": max(0, len(idx_tail) - 1),
            "index_last": idx_tail[-1].split(",")[0] if idx_tail else None}
    (out / "delta_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[delta] dates=%s codes=%d rows=%d bytes=%d → %s" % (
        meta["dates"], meta["codes"], meta["rows"], meta["delta_bytes"], out))
    return 0


if __name__ == "__main__":
    sys.exit(main())