# -*- coding: utf-8 -*-
"""云端：把「最近 N 个交易日的全市场日线」+「策略状态」压成一个小 delta 工件，供本机同步。

为什么：data_full/ 在 cloud runner 的 actions/cache 里，本机拿不到；而本机链已停用
（本机 data_full/index_000300.csv 不再自动更新）。本脚本在云端链跑完后产出
_cloud_delta/{delta_bars.csv, index_000300_tail.csv, delta_meta.json,
             state_meta.json, a5/paper_state.json, a5/reports/*.md,
             qlch/qlch_paper_state*.json, qlch/qlch_candidates.json}，
由 workflow 用 actions/upload-artifact 上传（约 0.2~1MB/日 + 状态 ~70KB），
本机用 apply_data_delta.py 合并（K 线 append + 策略状态回灌，两者都「先校验后写盘」）。

为什么带策略状态（2026-09-24 用户要求）：A5（打板族）与 qlch（超跌低开低吸六臂）在云端跑的是
仓库内副本，状态随 actions/cache 滚动，本机拿不到 → 本机实验目录/A5 与 backtest/qlch_* 会永久
停在旧日期。状态文件很小（A5 ~35KB、qlch 六臂 ~10KB、候选 ~19KB），随 delta 回传最省。
state_meta.json 是本机「只前进不回退」判据的载体：逐文件记录 kind/date/bytes/src。

用法（云端）：python -X utf8 backtest/build_data_delta.py --out _cloud_delta
纯标准库，无第三方依赖。
"""
import argparse, gzip, json, os, re, shutil, sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# 策略状态的「日期键」优先级：同一键在同一类文件里单调可比即可（本机据此判「只前进不回退」）
DATE_KEYS = ("last_scan", "last_run", "updated", "as_of", "date")


def obj_date(obj):
    """取状态 JSON 的日期/时间戳字符串（显式键优先，否则回落到 equity/trades 里最大日期）。"""
    if isinstance(obj, dict):
        for k in DATE_KEYS:
            v = obj.get(k)
            if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}", v):
                return v
        days = []
        for k in ("equity", "trades", "events"):
            v = obj.get(k)
            if isinstance(v, list):
                for e in v:
                    if isinstance(e, dict):
                        d = e.get("date") or e.get("day") or e.get("sb_date")
                        if isinstance(d, str) and re.match(r"^\d{4}-\d{2}-\d{2}", d):
                            days.append(d)
        if days:
            return max(days)
    return None


def pack_one(out, rel, src, kind, rows):
    """拷贝单个状态文件进工件（失败只记错误，绝不阻断 delta 产出）。"""
    src = Path(src)
    if not src.exists():
        return
    dest = out / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    date_error = None
    try:
        date = obj_date(json.loads(src.read_text(encoding="utf-8")))
    except Exception as e:
        date, date_error = None, str(e)[:120]
    rows.append({"rel": rel.replace("\\", "/"), "kind": kind, "date": date,
                 "src": str(src).replace("\\", "/"), "bytes": dest.stat().st_size,
                 "src_mtime": datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                 "parse_error": date_error})


def pack_state(out, a):
    """把 A5（打板族）+ qlch（超跌低开低吸）策略状态打进工件，供本机回灌。"""
    rows = []
    info = {"files": rows}
    if getattr(a, "no_state", False):
        info["skipped"] = "--no-state"
        return info

    # A5 实验盘：状态 + 最近 N 份日报告（报告很小，回本机归档）
    a5d = Path(a.a5_dir)
    pack_one(out, "a5/paper_state.json", a5d / "paper_state.json", "a5-state", rows)
    rps = sorted((a5d / "reports").glob("*.md"))
    keep = rps[-int(a.a5_reports):] if int(getattr(a, "a5_reports", 0) or 0) > 0 else []
    for p in keep:
        pack_one(out, "a5/reports/" + p.name, p, "a5-report", rows)

    # qlch 六臂状态 + 今日候选（看板「超跌低开低吸」数据源）
    bd = Path(a.backtest_dir)
    for p in sorted(bd.glob("qlch_paper_state*.json")):
        pack_one(out, "qlch/" + p.name, p, "qlch-state", rows)
    pack_one(out, "qlch/qlch_candidates.json", bd / "qlch_candidates.json", "qlch-candidates", rows)

    info["kinds"] = sorted({r["kind"] for r in rows})
    info["max_date"] = max([r["date"] for r in rows if r["date"]], default=None)
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_cloud_delta", help="输出目录")
    ap.add_argument("--days", type=int, default=3, help="每只票最多带最近 N 根（默认 3）")
    ap.add_argument("--index-rows", type=int, default=30, help="index_000300.csv 尾部行数")
    ap.add_argument("--data-dir", default=str(REPO / "data_full"))
    ap.add_argument("--index", default=str(REPO / "index_000300.csv"))
    ap.add_argument("--gzip", action="store_true", help="额外产出 delta_bars.csv.gz")
    ap.add_argument("--a5-dir", default=str(REPO / "backtest" / "a5_experiment"),
                    help="A5 实验盘目录（paper_state.json + reports/）")
    ap.add_argument("--backtest-dir", default=str(REPO / "backtest"), help="qlch 状态所在目录")
    ap.add_argument("--a5-reports", type=int, default=3, help="随状态回传的最近 N 份 A5 日报告（0=不带）")
    ap.add_argument("--no-state", action="store_true", help="不打包策略状态（只产 K 线 delta）")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    dd = Path(a.data_dir)
    if not dd.is_dir():
        print("[warn] data_full 不存在：%s → 产出空 delta（rc=0）" % dd)
        st = pack_state(out, a)   # data_full 缺失也照常回传状态（状态不依赖 K 线）
        (out / "state_meta.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "delta_meta.json").write_text(json.dumps(
            {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "error": "data_full missing",
             "codes": 0, "rows": 0, "dates": [], "state": st}, ensure_ascii=False), encoding="utf-8")
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

    # 4) 策略状态（A5 打板族 + qlch 超跌低开低吸）→ 本机回灌用
    st = pack_state(out, a)
    (out / "state_meta.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")

    meta = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "dates": sorted(keep), "codes": len(codes_kept), "rows": len(rows),
            "delta_bytes": bp.stat().st_size,
            "index_rows": max(0, len(idx_tail) - 1),
            "index_last": idx_tail[-1].split(",")[0] if idx_tail else None,
            "state": st}
    (out / "delta_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[delta] dates=%s codes=%d rows=%d bytes=%d → %s" % (
        meta["dates"], meta["codes"], meta["rows"], meta["delta_bytes"], out))
    print("[state] 打包 %d 个状态文件（%s）max_date=%s → %s" % (
        len(st["files"]), ",".join(st.get("kinds") or []) or "-", st.get("max_date"), out / "state_meta.json"))
    for r in st["files"]:
        print("    · %-34s %-14s %s" % (r["rel"], r["kind"], r["date"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
