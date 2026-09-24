# -*- coding: utf-8 -*-
"""本机：把云端 data-delta 工件合并进本机 K 线（data_full/ + index_000300.csv）。

流程：取工件（gh run download 或 --src 指定目录）→ 解析 delta_bars.csv →
      **先做多源校验**（抽样代码的 delta 收盘 vs 腾讯 K 线，可加新浪）→ 通过才写盘 →
      逐票 append 本地缺失的交易日（幂等）→ 写 _cloud_local/delta_applied.json 日志。

用法：
  python backtest/apply_data_delta.py --latest                 # 取最近一次 close_refresh 的工件（dry-run 由 --dry-run 控制）
  python backtest/apply_data_delta.py --run-id 35999999999
  python backtest/apply_data_delta.py --src _cloud_local/delta --dry-run
  python backtest/apply_data_delta.py --rollback 2026-09-24    # 撤掉某个日期追加的行（只动末行匹配的票）
退出码：0 成功/无操作 · 3 校验失败（未写盘）· 4 环境异常
"""
import argparse, csv, io, json, os, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
GH = r"C:\Users\Admin\.workbuddy\binaries\gh\gh.exe"
REPO_SLUG = "hawchou1995/quant-weight-system"
JOURNAL = REPO / "_cloud_local" / "delta_applied.json"


def gh(args, timeout=300):
    r = subprocess.run([GH] + args, capture_output=True, timeout=timeout)
    return r.returncode, (r.stdout or b"").decode("utf-8", "replace"), (r.stderr or b"").decode("utf-8", "replace")


def fetch_delta(run_id, dest):
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)   # gh run download 不会覆盖已存在文件 → 先清空
    dest.mkdir(parents=True, exist_ok=True)
    if run_id in (None, "latest"):
        rc, out, err = gh(["run", "list", "-R", REPO_SLUG, "--workflow", "close_refresh.yml",
                           "--limit", "12", "--json", "databaseId,status,conclusion,createdAt,event"])
        if rc != 0:
            print("[ERR] gh run list 失败：%s" % err.strip()[:200]); return None
        runs = json.loads(out)
        picked = None
        for r in runs:                     # 取最近一次 chain 运行（schedule 或 dispatch）
            if r.get("status") == "completed" and r.get("event") in ("schedule", "workflow_dispatch"):
                picked = r["databaseId"]; break
        if picked is None:
            print("[ERR] 找不到可用的 close_refresh 运行"); return None
    else:
        picked = run_id
    print("[delta] 下载 artifact（run %s）…" % picked)
    rc, out, err = gh(["run", "download", str(picked), "-R", REPO_SLUG, "-n", "data-delta", "-D", str(dest)])
    if rc != 0:
        low = (err or "").lower()
        if ("no valid artifacts" in low) or ("no artifacts" in low) or ("not found" in low):
            print("[skip] 该轮没有 data-delta 工件（正常：工件步骤可能刚加 / 当日非 chain）")
            return None
        print("[ERR] 工件下载命令失败：%s" % err.strip()[:220])
        return "ERR"
    return dest


def _prefix(code):
    """真实交易所前缀：优先看本机 data_full 文件名，其次按代码段推断（6/5/9=沪，4/8=北，其余=深）"""
    for pre in ("sh", "sz", "bj"):
        if (REPO / "data_full" / (pre + code + ".csv")).exists():
            return pre
    return "sh" if code[0] in "569" else ("bj" if code[0] in "48" else "sz")


def tx_close(code, day):
    import urllib.request
    sym = _prefix(code) + code
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,60," % sym
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
        node = (j.get("data") or {}).get(sym) or {}
        for b in (node.get("day") or node.get("qfqday") or []):
            if b and b[0] == day:
                return float(b[2])
    except Exception:
        return None
    return None


def load_delta(src):
    src = Path(src)
    bp = src / "delta_bars.csv"
    if not bp.exists():
        cands = list(src.rglob("delta_bars.csv"))
        if not cands:
            return None, None, None
        bp = cands[0]
    rows = {}
    with bp.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.setdefault(r["date"], {})[r["code"]] = r
    meta = {}
    for mp in list(src.rglob("delta_meta.json")):
        try:
            meta = json.loads(mp.read_text(encoding="utf-8")); break
        except Exception:
            pass
    itail = []
    for ip in list(src.rglob("index_000300_tail.csv")):
        itail = ip.read_text(encoding="utf-8").strip().splitlines()
        break
    return rows, meta, itail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="latest")
    ap.add_argument("--latest", action="store_true", help="取最近一次 close_refresh 运行的工件（等价 --run-id latest，默认行为）")
    ap.add_argument("--src", default=None, help="直接用已有 delta 目录（跳过下载）")
    ap.add_argument("--data-dir", default=str(REPO / "data_full"))
    ap.add_argument("--index", default=str(REPO / "index_000300.csv"))
    ap.add_argument("--sample", type=int, default=12)
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", default=None, help="撤掉该日期追加的行")
    a = ap.parse_args()
    if a.latest:
        a.run_id = "latest"

    dd = Path(a.data_dir); ip = Path(a.index)

    if a.rollback:
        n = 0
        for p in dd.glob("*.csv"):
            lines = p.read_text(encoding="utf-8").rstrip("\n").splitlines()
            if len(lines) >= 2 and lines[-1].split(",")[0] == a.rollback:
                p.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8"); n += 1
        if ip.exists():
            lines = ip.read_text(encoding="utf-8").rstrip("\n").splitlines()
            while len(lines) >= 2 and lines[-1].split(",")[0] == a.rollback:
                lines = lines[:-1]
            ip.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("[rollback] 已从 %d 个 data_full 文件移除 %s 行" % (n, a.rollback))
        return 0

    src = Path(a.src) if a.src else fetch_delta(a.run_id, REPO / "_cloud_local" / "delta")
    if src == "ERR":
        return 4
    if src is None:
        return 4 if a.src else 0
    rows, meta, itail = load_delta(src)
    if not rows:
        print("[ERR] 未找到 delta_bars.csv（src=%s）" % src); return 4
    dates = sorted(rows.keys())
    print("[delta] 日期=%s 行数=%d 元信息=%s" % (dates, sum(len(v) for v in rows.values()),
                                                 {k: meta.get(k) for k in ("codes", "rows", "index_last") if k in meta}))

    # ---- 多源校验：最新日期抽样比对腾讯 K 线 ----
    newest = dates[-1]
    if not a.no_validate:
        codes = sorted(rows[newest].keys())
        step = max(1, len(codes) // max(1, a.sample))
        picked, ok, bad = [], 0, []
        for i in range(0, len(codes), step):
            c = codes[i]; picked.append(c)
            if len(picked) >= a.sample:
                break
        print("  多源校验（腾讯 K 线 %s）：" % newest)
        for c in picked:
            dv = float(rows[newest][c]["close"]); tv = tx_close(c, newest)
            hit = tv is not None and abs(dv - tv) / tv <= 0.005
            ok += 1 if hit else 0
            if not hit:
                bad.append((c, dv, tv))
            print("    %-8s delta=%-9s 腾讯=%-9s %s" % (c, dv, tv, "OK" if hit else "不一致"))
        print("  一致率 %d/%d" % (ok, len(picked)))
        if bad:
            print("!! 多源校验未通过 → **不写盘**：%s" % bad)
            return 3

    # ---- 写盘（append 缺失交易日）----
    added_codes, added_rows, skipped_missing = 0, 0, 0
    for d in dates:
        for code, r in rows[d].items():
            p = None
            for pre in ("sh", "sz", "bj"):
                q = dd / (pre + code + ".csv")
                if q.exists():
                    p = q; break
            if p is None:
                skipped_missing += 1; continue
            lines = p.read_text(encoding="utf-8").rstrip("\n").splitlines()
            last = lines[-1].split(",")[0] if len(lines) >= 2 else ""
            if last >= d:
                continue
            line = ",".join([r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"], r["amount"]]).rstrip(",")
            if not a.dry_run:
                with p.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            added_codes += 1; added_rows += 1
    idx_added = 0
    if itail and ip.exists():
        have = {l.split(",")[0] for l in ip.read_text(encoding="utf-8").strip().splitlines()[1:]}
        add = [l for l in itail[1:] if l.split(",")[0] not in have]
        if add:
            if not a.dry_run:
                with ip.open("a", encoding="utf-8") as fh:
                    fh.write("\n".join(add) + "\n")
            idx_added = len(add)
    print("[%s] data_full：%d 只票 / %d 行；index：%d 行；本地缺文件的代码跳过 %d 行" % (
        "dry-run" if a.dry_run else "已写入", added_codes, added_rows, idx_added, skipped_missing))

    if not a.dry_run:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "run": str(a.run_id), "src": str(src),
               "dates": dates, "codes_added": added_codes, "rows_added": added_rows,
               "index_rows_added": idx_added, "skipped_missing_codes": skipped_missing}
        hist = []
        if JOURNAL.exists():
            try:
                hist = json.loads(JOURNAL.read_text(encoding="utf-8")).get("history", [])
            except Exception:
                hist = []
        hist.append(rec)
        JOURNAL.write_text(json.dumps({"history": hist[-60:]}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("[journal] %s" % JOURNAL)
    return 0


if __name__ == "__main__":
    sys.exit(main())