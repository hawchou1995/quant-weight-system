# -*- coding: utf-8 -*-
"""FB3-H20 基金线投产部署（2026-09-11 晚）
================================================================
把「基金线 FB3-H20 升级」产物同步到 dist 并发布 gh-pages：
- dual_system.html / index.html（曲线+summary 构建期嵌入，含新 FB3-H20 卡）
- short_v3_fund_slip20_summary.json / short_v3_fund_summary.json（dist 运行期口径）
- changelog.md / changelog.html / review_log.html（v5.13.1 条目）
随后 push gh-pages + 回读校验 + HTTP 端到端（检查 FB3-H20 上线）。
"""
import hashlib, shutil, subprocess, sys, time
from pathlib import Path

REPO = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
DIST = Path(r"D:/Documents/Workbuddy/股票基金/dist")
URL = "https://hawchou1995.github.io/quant-weight-system/"

SYNC = [
    "short_v3_fund_slip20_summary.json",
    "short_v3_fund_summary.json",
    "changelog.md",
    "changelog.html",
    "review_log.html",
]
DUAL = ["dual_system.html", "index.html"]


def md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sh(args, **kw):
    r = subprocess.run(args, cwd=str(REPO), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", **kw)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def line(t="-", n=78):
    print(t * n)


line("=")
print("STEP 0  前置校验")
line()
for n in DUAL + SYNC:
    p = REPO / n
    assert p.exists(), f"缺 {n}"
summ = (REPO / "short_v3_fund_slip20_summary.json").read_text(encoding="utf-8")
assert "FB3-H20" in summ, "repo 基金 summary 未含 FB3-H20（先跑 finalize_short_v3.py --asset fund）"
html = (REPO / "dual_system.html").read_text(encoding="utf-8", errors="replace")
assert "FB3-H20" in html, "repo dual_system.html 未含 FB3-H20（先跑 build_dual_system.py）"
assert "v5.13.1" in (REPO / "changelog.md").read_text(encoding="utf-8"), "changelog 缺 v5.13.1"
print(f"  repo/dual_system.html md5 {md5(REPO/'dual_system.html')[:12]}  (含 FB3-H20 ✅)")
print(f"  repo/short_v3_fund_slip20_summary.json 含 FB3-H20 ✅")

line("=")
print("STEP 1  同步产物 → dist")
line()
copied = []
for rel in SYNC:
    s = REPO / rel
    d = DIST / rel
    if d.exists() and md5(s) == md5(d):
        print(f"  未变  {rel}")
        continue
    d.parent.mkdir(parents=True, exist_ok=True)
    old = md5(d)[:12] if d.exists() else "无"
    shutil.copy2(s, d)
    assert md5(s) == md5(d), f"复制校验失败 {rel}"
    copied.append(rel)
    print(f"  同步  {rel:44s} {old} -> {md5(d)[:12]}")
shutil.copy2(REPO / "dual_system.html", DIST / "dual_system.html")
shutil.copy2(REPO / "dual_system.html", DIST / "index.html")
print(f"  同步  dual_system.html + index.html -> {md5(DIST/'dual_system.html')[:12]}")
assert md5(DIST / "dual_system.html") == md5(DIST / "index.html"), "双同步失败"
shutil.copy2(REPO / "dual_system.html", REPO / "index.html")
assert md5(REPO / "dual_system.html") == md5(REPO / "index.html"), "repo 双同步失败"

line("=")
print("STEP 2  发布 gh-pages")
line()
gitdir = sh(["git", "rev-parse", "--absolute-git-dir"])[1]
print(f"  GITDIR {gitdir}")
import tempfile, os
idx = tempfile.mktemp(prefix="ghpages-idx.", dir=gitdir)
env = dict(os.environ, GIT_INDEX_FILE=idx)
try:
    rc, out, err = sh(["git", "--git-dir", gitdir, "--work-tree", str(DIST), "add", "-A", "-f"], env=env)
    assert rc == 0, err
    rc, out, err = sh(["git", "fetch", "origin", "gh-pages"])
    print(f"  fetch rc={rc}")
    rc, tree, err = sh(["git", "--git-dir", gitdir, "--work-tree", str(DIST), "write-tree"], env=env)
    assert rc == 0, err
    print(f"  TREE {tree}")
    rc, old, _ = sh(["git", "rev-parse", "--verify", "FETCH_HEAD"])
    parent = old if rc == 0 and old else None
    print(f"  parent {parent}")
    msg = "deploy(fundline): FB3-H20 " + time.strftime("%Y-%m-%d %H:%M")
    args = ["git", "--git-dir", gitdir, "commit-tree", tree] + (["-p", parent] if parent else [])
    r = subprocess.run(args, input=msg, capture_output=True, text=True, encoding="utf-8", env=env)
    assert r.returncode == 0, r.stderr
    commit = r.stdout.strip()
    print(f"  COMMIT {commit}")
finally:
    try:
        os.remove(idx)
    except OSError:
        pass

env2 = dict(os.environ)
env2.pop("GIT_INDEX_FILE", None)
rc, out, err = sh(["git", "push", "origin", f"{commit}:refs/heads/gh-pages"], env=env2)
print(f"  push rc={rc}")
print("  ", (out or err)[-300:])
assert rc == 0, "push 失败"
print(f"\nOK 已发布 {URL}（GitHub Pages 约 1 分钟生效）")

line("=")
print("STEP 3  回读线上校验")
line()
time.sleep(6)
rc, out, _ = sh(["git", "fetch", "origin", "gh-pages"])
rc, head, _ = sh(["git", "rev-parse", "FETCH_HEAD"])
print(f"  线上 HEAD {head}  (期望 {commit})")
assert head == commit, "线上 HEAD 与推送提交不一致"
ok = True
checks = [("dual_system.html", md5(REPO / "dual_system.html")),
          ("index.html", md5(REPO / "index.html")),
          ("short_v3_fund_slip20_summary.json", md5(REPO / "short_v3_fund_slip20_summary.json")),
          ("changelog.html", md5(REPO / "changelog.html")),
          ("review_log.html", md5(REPO / "review_log.html"))]
for rel, expect in checks:
    r = subprocess.run(["git", "show", f"FETCH_HEAD:{rel}"], cwd=str(REPO), capture_output=True)
    if r.returncode != 0:
        print(f"  ❌ 线上缺 {rel}"); ok = False; continue
    # ⚠ autocrlf：本地含 CRLF 的文件 git 存储为 LF；比对前归一化（等价 tr -d '\r'）
    got = hashlib.md5(r.stdout.replace(b"\r\n", b"\n")).hexdigest()
    exp_norm = hashlib.md5((REPO / rel).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    flag = "✅" if got == exp_norm else "❌"
    if got != exp_norm:
        ok = False
    print(f"  {flag} {rel:36s} 线上 {got[:12]} 本地 {exp_norm[:12]}")

r = subprocess.run(["git", "show", "FETCH_HEAD:dual_system.html"], cwd=str(REPO), capture_output=True)
live_html = r.stdout.decode("utf-8", "replace")
print(f"  线上 dual_system.html 含 'FB3-H20' = {'FB3-H20' in live_html} / 含 '牛动量重Top10' = {'牛动量重Top10' in live_html}")
if "FB3-H20" not in live_html:
    ok = False
    print("  ❌ 线上仍无 FB3-H20")

line("=")
print("STEP 4  HTTP 端到端（GitHub Pages 实际响应）")
line()
import urllib.request
for path, must in [("short_v3_fund_slip20_summary.json", "FB3-H20")]:
    try:
        req = urllib.request.Request(f"{URL}{path}", headers={"User-Agent": "Mozilla/5.0"})
        body = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
        hit = must in body
        print(f"  {'✅' if hit else '⏳'} {path}  len={len(body)}  contains '{must}'={hit}")
        if not hit:
            print("     （Pages CDN 可能有延迟，稍后重试即可）")
    except Exception as e:
        print(f"  ⚠ {path} HTTP 读取失败: {e}")

print()
print("RESULT:", "ALL PASS ✅" if ok else "需复核 ⚠")
