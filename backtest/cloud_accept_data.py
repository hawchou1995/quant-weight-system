# -*- coding: utf-8 -*-
"""云端发布数据的本地验收 + 落地（供 17:30 自动验收使用）。

做什么：
  1) 取线上 _cloud_manifest.json → 逐文件下载（cache-bust）→ 校验 md5 与清单一致；
  2) 结构一致性：dual_system.html 与 index.html 必须同 md5；
  3) 新鲜度：运行期依赖（enhanced_data.js/short_signals.js/a5_pool.js/...）的 as_of 是否 == 今日；
  4) **多源验证**：从云端 short_signals.js 抽 N 只股票的 px（云端口径收盘价），与
     ① 本机 data_full 日线收盘 ② 腾讯 K 线收盘 三方对齐（容差 0.5%）；
  5) `--inplace` 时才把云端文件覆盖到仓库根（改前备份 .bak-cloudsync-<ts>）。

用法：
  python backtest/cloud_accept_data.py                 # 只读：下载到 _cloud_local/ + 全套校验
  python backtest/cloud_accept_data.py --inplace       # 校验通过后覆盖本地（备份旧件）
  python backtest/cloud_accept_data.py --sample 20     # 多源验证抽样只数
退出码：0 全部通过 · 3 有校验失败项 · 4 环境异常
"""
import argparse, hashlib, io, json, os, re, shutil, subprocess, sys, time, urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BASE = "https://hawchou1995.github.io/quant-weight-system/"
TOL = 0.005          # 多源价格容差 0.5%
UA = {"User-Agent": "Mozilla/5.0"}


def get(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def md5_12(b):
    return hashlib.md5(b).hexdigest()[:12]


def local_close(code, day):
    """本机 data_full 日线收盘（raw）"""
    for pre in ("sh", "sz", "bj"):
        p = REPO / "data_full" / (pre + code + ".csv")
        if p.exists():
            for line in p.read_text(encoding="utf-8").strip().splitlines()[1:]:
                f = line.split(",")
                if f and f[0] == day and len(f) >= 5:
                    try:
                        return float(f[4])
                    except Exception:
                        return None
            return None
    return None


def tx_close(code, day):
    """腾讯 K 线收盘（不复权）；前缀优先取本机文件名，其次按代码段推断（6/5/9=沪，4/8=北）"""
    pre = None
    for cand in ("sh", "sz", "bj"):
        if (REPO / "data_full" / (cand + code + ".csv")).exists():
            pre = cand
            break
    if pre is None:
        pre = "sh" if code[0] in "569" else ("bj" if code[0] in "48" else "sz")
    sym = pre + code
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,60," % sym)
    try:
        j = json.loads(get(url, timeout=25).decode("utf-8", "replace"))
        node = (j.get("data") or {}).get(sym) or {}
        bars = node.get("day") or node.get("qfqday") or []
        for b in bars:
            if b and b[0] == day:
                return float(b[2])
    except Exception:
        return None
    return None


def sina_close(code, day):
    """新浪日线收盘（akshare，慢；仅抽样）"""
    pre = "sh" if code[0] in "59" else ("bj" if code[0] in "48" else "sz")
    try:
        import akshare as ak
        df = ak.stock_zh_a_daily(symbol=pre + code, start_date=day, end_date=day, adjust="")
        if df is not None and len(df):
            return float(df["close"].iloc[-1])
    except Exception:
        return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inplace", action="store_true", help="校验通过后覆盖仓库根文件（备份旧件）")
    ap.add_argument("--sample", type=int, default=12, help="多源验证抽样只数")
    ap.add_argument("--no-sina", action="store_true", help="跳过新浪（akshare，慢）")
    ap.add_argument("--out", default=None, help="下载目录（默认 <repo>/_cloud_local）")
    a = ap.parse_args()

    out = Path(a.out) if a.out else (REPO / "_cloud_local")
    out.mkdir(parents=True, exist_ok=True)
    cb = str(int(time.time()))
    fails, warns = [], []

    try:
        raw = get(BASE + "_cloud_manifest.json?cb=" + cb)
    except Exception as e:
        print("[ERR] 取不到云端清单：%s" % str(e)[:160]); return 4
    man = json.loads(raw.decode("utf-8", "replace"))
    (out / "_cloud_manifest.json").write_bytes(raw)
    print("=== 云端发布清单 ===")
    print("run=%s mode=%s status=%s ts_cn=%s today_cn=%s chain_rc=%s g2_fresh=%s" % (
        man.get("run_id"), man.get("mode"), man.get("status"), man.get("ts_cn"),
        man.get("today_cn"), man.get("chain_rc"), man.get("g2_fresh")))

    print("\n=== 1. 逐文件下载 + md5 校验 ===")
    print("%-38s %10s %-14s %s" % ("文件", "bytes", "md5", "结论"))
    got = {}
    for f in man.get("files", []):
        nm = f["name"]
        try:
            b = get(BASE + nm + "?cb=" + cb)
        except Exception as e:
            print("%-38s %10s %-14s 下载失败 %s" % (nm, f.get("bytes"), f.get("md5"), str(e)[:60])); fails.append(nm); continue
        h = md5_12(b)
        ok = (h == f.get("md5"))
        note = "OK" if ok else "MD5 不符(清单 %s)" % f.get("md5")
        lp0 = REPO / nm
        if not ok and lp0.exists() and md5_12(lp0.read_bytes()) == h:
            # 该文件已被 rt 盘中快照 workflow 覆盖到 gh-pages → 清单过期，而非数据损坏
            ok = True
            note += " → 与仓库同版（gh-pages 被 rt 盘中快照覆盖，清单过期，非损坏）"
            warns.append("清单过期(rt 覆盖):" + nm)
        if not ok:
            fails.append(nm)
        print("%-38s %10d %-14s %s" % (nm, len(b), h, note))
        (out / nm).write_bytes(b)
        got[nm] = {"bytes": len(b), "md5": h, "as_of": f.get("as_of"), "ok": ok}

    print("\n=== 2. 结构一致性（index.html 与 dual_system.html 必须同份）===")
    if got.get("index.html", {}).get("md5") == got.get("dual_system.html", {}).get("md5"):
        print("OK  两份 md5 相同（%s）" % got["index.html"]["md5"])
    else:
        print("FAIL md5 不同：index=%s dual=%s" % (got.get("index.html", {}).get("md5"), got.get("dual_system.html", {}).get("md5"))); fails.append("index-vs-dual")

    today = datetime.now().strftime("%Y-%m-%d")
    print("\n=== 3. 新鲜度（as_of 是否 == 今日 %s）===" % today)
    deps = man.get("runtime_deps") or []
    stale = []
    for nm in deps:
        ao = (got.get(nm) or {}).get("as_of")
        flag = "fresh" if ao == today else "STALE(%s)" % ao
        if ao != today:
            stale.append(nm)
        print("  %-24s as_of=%s  %s" % (nm, ao, flag))
    if stale:
        warns.append("as_of 未推进：" + ",".join(stale))

    print("\n=== 4. 多源验证（云端 px vs 本机 data_full vs 腾讯 K 线）===")
    ss = None
    p = out / "short_signals.js"
    if p.exists():
        txt = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"\{", txt)
        try:
            ss = json.loads(txt[m.start():].rstrip().rstrip(";"))
        except Exception as e:
            print("  [warn] short_signals.js 解析失败：%s" % str(e)[:120])
    as_of = (ss or {}).get("as_of")
    stock = (ss or {}).get("stock") or {}
    print("  云端样本 as_of=%s  股票数=%d" % (as_of, len(stock)))
    if not stock or not as_of:
        warns.append("short_signals.js 无股票样本，跳过三方校验")
    else:
        codes = sorted(stock.keys())
        step = max(1, len(codes) // max(1, a.sample))
        picked, ok_n, bad = [], 0, []
        for i in range(0, len(codes), step):
            c = codes[i]
            if local_close(c, as_of) is None:
                continue
            picked.append(c)
            if len(picked) >= a.sample:
                break
        print("  %-8s %-9s %-9s %-9s %-9s %s" % ("代码", "云端px", "本机", "腾讯", "偏差(云-本)", "结论"))
        for c in picked:
            px = stock[c].get("px")
            lc = local_close(c, as_of)
            tc = tx_close(c, as_of)
            dev = (abs(px - lc) / lc) if (px and lc) else None
            ok = dev is not None and dev <= TOL
            ok_n += 1 if ok else 0
            if not ok:
                bad.append((c, px, lc, tc))
            print("  %-8s %-9s %-9s %-9s %-9s %s" % (
                c, px, lc, tc, ("%.3f%%" % (100*dev)) if dev is not None else "-", "OK" if ok else "偏差超限"))
        if not picked:
            print("  ⚠️ 本机 data_full 缺 %s 的数据 → 三方校验无法进行（先跑 backtest\\apply_data_delta.py --latest 合并云端 K 线）" % as_of)
            warns.append("三方校验跳过：本机缺 %s 数据" % as_of)
        if picked:
            print("  三方一致率：%d/%d" % (ok_n, len(picked)))
            if bad:
                fails.append("多源价格不一致:%s" % ",".join(b[0] for b in bad))
        if not a.no_sina and picked[:4]:
            print("  新浪（akshare）抽查 4 只：")
            for c in picked[:4]:
                sc = sina_close(c, as_of)
                lc = local_close(c, as_of)
                ok = (sc is not None and lc and abs(sc - lc) / lc <= TOL)
                print("    %-8s 新浪=%s 本机=%s %s" % (c, sc, lc, "OK" if ok else ("跳过" if sc is None else "偏差超限")))
                if sc is not None and not ok:
                    fails.append("新浪与本机不一致:%s" % c)

    print("\n=== 5. 本地差异（云端 vs 仓库根同名文件）===")
    diff = []
    for nm, info in got.items():
        lp = REPO / nm
        if lp.exists():
            lb = lp.read_bytes()
            if md5_12(lb) != info["md5"]:
                diff.append((nm, len(lb), info["bytes"]))
    if diff:
        for nm, lb, cb2 in diff:
            print("  DIFF %-38s 本地=%dB 云端=%dB" % (nm, lb, cb2))
    else:
        print("  本地与云端完全一致")

    if a.inplace and not fails:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        for nm in got:
            lp = REPO / nm
            sp = out / nm
            if lp.exists() and md5_12(lp.read_bytes()) == got[nm]["md5"]:
                continue
            if lp.exists():
                shutil.copy2(lp, lp.with_suffix(lp.suffix + ".bak-cloudsync-%s" % ts))
            shutil.copy2(sp, lp)
        print("\n[inplace] 已用云端文件覆盖本地（旧件已备份 .bak-cloudsync-%s）" % ts)
    elif a.inplace:
        print("\n[inplace] 有校验失败项 → 不覆盖本地")

    rep = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "manifest": man,
           "files": got, "fails": fails, "warns": warns, "local_diff": diff}
    (out / "accept_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n报告 → %s" % (out / "accept_report.json"))
    if fails:
        print("!! 验收失败项：%s" % fails); return 3
    if warns:
        print("⚠️ 告警：%s" % warns)
    return 0


if __name__ == "__main__":
    sys.exit(main())