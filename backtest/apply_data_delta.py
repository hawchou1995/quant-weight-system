# -*- coding: utf-8 -*-
"""本机：把云端 data-delta 工件合并进本机 K 线（data_full/ + index_000300.csv）+ 回灌策略状态。

流程：取工件（gh run download 或 --src 指定目录）→ 解析 delta_bars.csv →
      **先做多源校验**（抽样代码的 delta 收盘 vs 腾讯 K 线，可加新浪）→ 通过才写盘 →
      逐票 append 本地缺失的交易日（幂等）→ 回灌策略状态（A5 打板族 + qlch 超跌低开低吸）→
      写 _cloud_local/delta_applied.json 日志。

策略状态回灌（2026-09-24 起，用户要求）：A5 与 qlch 在云端跑仓库内副本、状态随 actions/cache
滚动，本机拿不到 → 本机 A5 实验目录与 backtest/qlch_* 会永久停在旧日期。故云端
build_data_delta.py 把状态打进同一工件（附 state_meta.json 逐文件清单）：
  a5/paper_state.json + a5/reports/*.md          → 本机 backtest/a5_experiment/ 与 A5 实验目录（--a5-ext）
  qlch/qlch_paper_state*.json + qlch_candidates.json → 本机 backtest/
覆盖规则：云端状态日期键（last_scan / last_run / updated）必须**严格新于**本机现值才写；
旧件先备份 <名字>.bak-a5sync-<ts>（qlch 为 .bak-statesync-<ts>）；相同或更旧一律 skip（只前进不回退）；
报告类文件已存在则不覆盖。校验不过（rc=3）时 K 线与状态都不写。

用法：
  python backtest/apply_data_delta.py --latest                 # 取最近一次 close_refresh 的工件
  python backtest/apply_data_delta.py --run-id 35999999999
  python backtest/apply_data_delta.py --src _cloud_local/delta --dry-run
  python backtest/apply_data_delta.py --rollback 2026-09-24    # 撤掉某个日期追加的行（只动末行匹配的票）
  python backtest/apply_data_delta.py --latest --no-state      # 只并 K 线，不回灌策略状态
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
# 本机 A5 实验目录（与仓库同级）：云端状态回灌的第二个落点
A5_EXT_DEFAULT = REPO.parent / "打板系统A5实验_20260827"


def gh(args, timeout=300):
    r = subprocess.run([GH] + args, capture_output=True, timeout=timeout)
    return r.returncode, (r.stdout or b"").decode("utf-8", "replace"), (r.stderr or b"").decode("utf-8", "replace")


def fetch_delta(run_id, dest):
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)   # gh run download 不会覆盖已存在文件 → 先清空
    dest.mkdir(parents=True, exist_ok=True)
    if run_id in (None, "latest"):
        # 2026-09-25 R-cloudsync-0925：workflow 文件已改名（close_refresh.yml → close_refresh_cloud.yml，
        # 用于强制 GitHub 重新注册 schedule）→ 主用新名、兼容旧名，避免按文件名过滤失效。
        runs = None
        for _wf in ("close_refresh_cloud.yml", "close_refresh.yml"):
            rc, out, err = gh(["run", "list", "-R", REPO_SLUG, "--workflow", _wf,
                               "--limit", "12", "--json", "databaseId,status,conclusion,createdAt,event"])
            if rc == 0:
                _runs = json.loads(out)
                if _runs:            # 新名在改名后首跑前为空 → 继续用旧名（历史运行仍按旧名可查）
                    if _wf != "close_refresh_cloud.yml":
                        print("[info] 新名 close_refresh_cloud.yml 尚无运行记录 → 取旧名历史运行")
                    runs = _runs
                    break
        if not runs:
            print("[ERR] gh run list 无可用运行（新名未首跑且旧名无历史）：%s" % err.strip()[:160]); return None
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


def _tx_kline_close(code, day):
    """腾讯 K 线接口（web.ifzq.gtimg.cn）——首选源"""
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


def tx_snapshot_close(code, day):
    """腾讯行情快照（qt.gtimg.cn）——K 线接口被网络层拦截/限流时的**同源兜底**。
    仅当快照时间戳（field30）日期 == 目标日才命中，避免误用其它交易日的价。"""
    import urllib.request
    sym = _prefix(code) + code
    url = "https://qt.gtimg.cn/q=%s" % sym
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = r.read().decode("gbk", "replace")
        if '="' not in txt:
            return None
        f = txt.split('="', 1)[1].rstrip('";\n').split("~")
        ts = f[30] if len(f) > 30 else ""
        if ts[:8] != str(day).replace("-", ""):
            return None
        return float(f[3])
    except Exception:
        return None


def tx_close(code, day):
    """腾讯收盘价：K 线优先、快照兜底（任一命中即可；仍受 0.5% 容差门禁约束，判据不放松）"""
    v = _tx_kline_close(code, day)
    if v is None:
        v = tx_snapshot_close(code, day)
    return v


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


# ===================== 策略状态回灌（云端 → 本机） =====================

def _state_date(path):
    """状态文件自身的日期键（与云端 build_data_delta.obj_date 同优先级）。"""
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    for k in ("last_scan", "last_run", "updated", "as_of", "date"):
        v = obj.get(k)
        if isinstance(v, str) and len(v) >= 10:
            return v
    days = []
    for k in ("equity", "trades", "events"):
        v = obj.get(k)
        if isinstance(v, list):
            for e in v:
                if isinstance(e, dict):
                    d = e.get("date") or e.get("day") or e.get("sb_date")
                    if isinstance(d, str) and len(d) >= 10:
                        days.append(d)
    return max(days) if days else None


def load_state_meta(src):
    """读工件的 state_meta.json（云端产出）；缺则回落到任意 paper_state.json（老工件兼容）。"""
    src = Path(src)
    for mp in sorted(src.rglob("state_meta.json")):
        try:
            d = json.loads(mp.read_text(encoding="utf-8"))
            if isinstance(d.get("files"), list):
                return d["files"], mp.parent
        except Exception:
            continue
    for sp in sorted(src.rglob("paper_state.json")):
        return [{"rel": str(sp.relative_to(src)).replace("\\", "/"), "kind": "a5-state",
                 "date": _state_date(sp)}], src
    return [], src


def dest_paths(kind, name, a5_ext):
    """状态文件在本机的落点：a5 = 仓库副本 + 本机实验目录；qlch = 仓库 backtest/。"""
    if kind == "a5-state":
        return [(REPO / "backtest" / "a5_experiment" / "paper_state.json", "a5sync"),
                (Path(a5_ext) / "paper_state.json", "a5sync")]
    if kind == "a5-report":
        return [(REPO / "backtest" / "a5_experiment" / "reports" / name, "a5sync"),
                (Path(a5_ext) / "reports" / name, "a5sync")]
    return [(REPO / "backtest" / name, "statesync")]


def sync_state_back(src, a, dry_run=False):
    """策略状态回灌：云端 → 本机（只前进不回退 + 旧件备份 + 幂等 + 报告不覆盖）。"""
    files, root_dir = load_state_meta(src)
    res = {"artifact": str(root_dir), "files": len(files), "written": [], "skipped": [],
           "reports": [], "status": "ok" if files else "no-state-in-artifact"}
    if a.no_state:
        res["status"] = "disabled(--no-state)"
        return res
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for f in files:
        rel, kind = f.get("rel"), f.get("kind")
        if not rel or not kind:
            continue
        sp = Path(root_dir) / rel
        if not sp.exists():
            res["skipped"].append("%s（工件内缺失）" % rel)
            continue
        name = Path(rel).name
        cloud_date = f.get("date") or _state_date(sp)
        for dest, tag in dest_paths(kind, name, a.a5_ext):
            if kind.endswith("report"):
                if dest.exists():
                    res["skipped"].append("%s（报告已存在）" % dest.name)
                    continue
                if not dry_run:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(sp, dest)
                res["reports"].append(str(dest))
                continue
            local_date = _state_date(dest) if dest.exists() else None
            if local_date and cloud_date and local_date >= cloud_date:
                res["skipped"].append("%s（本地 %s ≥ 云端 %s，不回退）" % (dest.name, local_date, cloud_date))
                continue
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    try:
                        shutil.copy2(dest, Path(str(dest) + ".bak-%s-%s" % (tag, ts)))
                    except Exception as e:
                        print("[warn] 备份失败 %s：%s" % (dest, e))
                shutil.copy2(sp, dest)
            res["written"].append("%s ← %s（云端 %s）" % (str(dest), rel, cloud_date))
    return res


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
    ap.add_argument("--no-state", action="store_true", help="不回灌策略状态（A5/qlch），只并 K 线")
    ap.add_argument("--a5-ext", default=str(A5_EXT_DEFAULT),
                    help="本机 A5 实验目录（默认仓库同级 打板系统A5实验_20260827）")
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
        print("  多源校验（腾讯 K线→快照兜底 %s）：" % newest)
        for c in picked:
            dv = float(rows[newest][c]["close"]); tv = tx_close(c, newest)
            hit = tv is not None and abs(dv - tv) / tv <= 0.005
            ok += 1 if hit else 0
            if not hit:
                bad.append((c, dv, tv))
            print("    %-8s delta=%-9s 腾讯=%-9s %s" % (c, dv, tv, "OK" if hit else "不一致"))
        print("  一致率 %d/%d" % (ok, len(picked)))
        if bad:
            print("!! 多源校验未通过 → **不写盘**（K 线与策略状态都不写）：%s" % bad)
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

    # ---- 策略状态回灌（云端 → 本机；只前进不回退 + 备份 + 幂等）----
    st = sync_state_back(src, a, dry_run=a.dry_run)
    print("[state] 工件内 %d 个状态文件：写入 %d / 跳过 %d / 报告归档 %d（%s）" % (
        st["files"], len(st["written"]), len(st["skipped"]), len(st["reports"]), st["status"]))
    for w in st["written"]:
        print("    + %s" % w)
    for s in st["skipped"]:
        print("    - %s" % s)

    if not a.dry_run:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "run": str(a.run_id), "src": str(src),
               "dates": dates, "codes_added": added_codes, "rows_added": added_rows,
               "index_rows_added": idx_added, "skipped_missing_codes": skipped_missing, "state": st}
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
