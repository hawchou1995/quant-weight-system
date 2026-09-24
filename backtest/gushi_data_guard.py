# -*- coding: utf-8 -*-
"""gushi 采集数据体检 + picks_daily.jsonl 去重（默认只读；--dedupe 才写）。

背景（2026-09-24 发现）：09-21 / 09-22 两天的 12 个共振因子全空（策略正常），
  原因是站点 /api.php?action=resonance-* **只支持最新交易日**（旧日期 409）——
  即「共振数据错过当天即永久缺失、不可回补」。缺了没人发现，所以需要体检。
判据：
  GAP_ALL   nf==0                     该日整体缺失（窗口内可回补）
  GAP_RESON nf>0 且 nr==0             该日共振永久缺失（站点限制）
  OK        nf>0 且 nr>0
用法：
  python backtest/gushi_data_guard.py --days 5                # 只读体检（写 health.json）
  python backtest/gushi_data_guard.py --days 5 --dedupe       # 顺带对 jsonl 去重（保留最后一次出现）
  python backtest/gushi_data_guard.py --health <path> --jsonl <path> --days 5
退出码：0 无空洞 · 3 有空洞 · 4 环境异常
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gushi_daily_collect as G  # noqa: E402

CSV = HERE.parent / "index_000300.csv"


def trading_days(n):
    if not CSV.exists():
        return []
    ds = [l.split(",")[0] for l in CSV.read_text(encoding="utf-8").strip().splitlines()[1:]]
    ds = ds[-n:]
    today = datetime.now().strftime("%Y-%m-%d")
    if datetime.now().weekday() < 5 and today not in ds:
        ds.append(today)   # 本机链已停用 → 本机日历常不含今日；与采集器 missing_days 同规则补上
    return ds


def key_of(r):
    return (r.get("date"), r.get("kind"), r.get("strategy"), r.get("fid"), r.get("stock_code"))


def dedupe_jsonl(path):
    """保留每个键的最后一次出现；返回 (原行数, 去重后行数, 丢弃数, 保底备份路径)。"""
    if not path.exists():
        return (0, 0, 0, None)
    raw = path.read_text(encoding="utf-8").splitlines()
    seen, bad = {}, 0
    for ln in raw:
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:
            bad += 1
            continue
        seen[key_of(r)] = r          # 后出现的覆盖先出现的（新数据优先）
    out = raw and len(seen) < (len(raw) - bad)
    kept = list(seen.values())
    if out:
        bak = path.with_suffix(path.suffix + ".bak-guard-%s" % datetime.now().strftime("%Y%m%d%H%M%S"))
        shutil.copy2(path, bak)
        with path.open("w", encoding="utf-8") as fh:
            for r in kept:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        return (len(raw), len(kept), len(raw) - bad - len(kept), str(bak))
    return (len(raw), len(raw), 0, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5, help="体检最近 N 个交易日")
    ap.add_argument("--data-dir", default=str(G.OUT), help="gushi_data 目录")
    ap.add_argument("--jsonl", default=None, help="picks_daily.jsonl（默认 <data-dir>/picks_daily.jsonl）")
    ap.add_argument("--health", default=None, help="health.json 输出路径（默认 <data-dir>/health.json）")
    ap.add_argument("--dedupe", action="store_true", help="对 jsonl 去重（写操作，先备份）")
    a = ap.parse_args()

    ddir = Path(a.data_dir)
    daily = ddir / "daily"
    jsonl = Path(a.jsonl) if a.jsonl else (ddir / "picks_daily.jsonl")
    health = Path(a.health) if a.health else (ddir / "health.json")
    if not ddir.exists():
        print("[ERR] 数据目录不存在：%s" % ddir)
        return 4

    jl_rows = {}
    if jsonl.exists():
        for ln in jsonl.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
                jl_rows[r.get("date")] = jl_rows.get(r.get("date"), 0) + 1
            except Exception:
                pass

    rows, gaps = [], []
    for d in trading_days(a.days):
        p = daily / ("%s.json" % d)
        nf = nr = 0
        size = p.stat().st_size if p.exists() else 0
        if p.exists():
            try:
                nf, nr = G.counts(json.loads(p.read_text(encoding="utf-8")))
            except Exception as e:
                print("[warn] %s 解析失败：%s" % (p.name, e))
        st = "OK" if (nf > 0 and nr > 0) else ("GAP_ALL" if nf == 0 else "GAP_RESON")
        if st != "OK":
            gaps.append({"date": d, "status": st, "nf": nf, "nr": nr})
        rows.append({"date": d, "exists": p.exists(), "nf": nf, "nr": nr, "bytes": size,
                     "jsonl_rows": jl_rows.get(d, 0), "status": st})

    print("=== gushi 采集体检（最近 %d 个交易日）===" % a.days)
    print("%-12s %-9s %6s %6s %9s %9s" % ("日期", "状态", "策略", "共振", "文件B", "jsonl行"))
    for r in rows:
        print("%-12s %-9s %6d %6d %9d %9d" % (r["date"], r["status"], r["nf"], r["nr"], r["bytes"], r["jsonl_rows"]))

    ded = None
    if a.dedupe:
        before, after, dropped, bak = dedupe_jsonl(jsonl)
        ded = {"lines_before": before, "lines_after": after, "dropped": dropped, "backup": bak}
        print("=== jsonl 去重：%d → %d 行（丢弃重复 %d）%s" % (before, after, dropped, ("备份 " + bak) if bak else ""))

    rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "days": a.days, "rows": rows,
           "gaps": gaps, "jsonl": str(jsonl), "dedupe": ded,
           "note": "GAP_RESON=该日共振永久缺失（站点共振接口仅支持最新交易日）；GAP_ALL=可回补"}
    try:
        health.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        print("health → %s" % health)
    except Exception as e:
        print("[warn] health 写入失败：%s" % e)

    if gaps:
        print("!! 发现 %d 个空洞：%s" % (len(gaps), ", ".join("%s(%s)" % (g["date"], g["status"]) for g in gaps)))
        return 3
    print("✅ 最近 %d 个交易日无空洞" % a.days)
    return 0


if __name__ == "__main__":
    sys.exit(main())