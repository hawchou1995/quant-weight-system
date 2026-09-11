# -*- coding: utf-8 -*-
"""2026-09-11 修复版收尾：把仓库最新产物同步到部署源 dist，再发布到 gh-pages。

背景：今日 update_daily.py 走腾讯源写入 amount=0 → v8_factor_cache 重建后 amt20=0
     → v9_rank_board 的 amt20<5e6 过滤把 410 只全部剔除 → 中长线池被错误改写
     （美盈森 002303 消失）。数据已逐列回滚至 09-10 前状态并重建全链。
本脚本只做「同步 + 发布 + 校验」，不改任何业务数据。
"""
import hashlib, shutil, subprocess, sys, time
from pathlib import Path

REPO = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
DIST = Path(r"D:/Documents/Workbuddy/股票基金/dist")
URL = "https://hawchou1995.github.io/quant-weight-system/"

# ① 审核通过的同步清单（repo 内容均比 dist 新，且不与任何 dist 直写产物冲突）
SYNC = [
    "short_pool.json",
    "index_000300.csv",
    "etf_paper_state.json",
    "khunter_paper_state.json",
    "khunter_paper_state_c.json",
    "review/a5_review.json",
    "review/cumulative.json",
    "monitor/snapshots_index.js",
    "monitor/snapshots/20260901_dual.html",
    "v9split_all_a80_equity.csv",
    "v9split_gem_only_a80_equity.csv",
    "v9split_main_only_a80_equity.csv",
    "v9split_star_only_a80_equity.csv",
]
# ② 双同步：dist/index.html 必须与 dist/dual_system.html 完全一致
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
for n in DUAL:
    p = REPO / n
    assert p.exists(), f"缺 {n}"
print(f"  repo/dual_system.html md5 {md5(REPO/'dual_system.html')[:12]}")
print(f"  repo/index.html      md5 {md5(REPO/'index.html')[:12]}")
print(f"  dist/dual_system.html md5 {md5(DIST/'dual_system.html')[:12]}")

# 关键断言：修复后的中长线池必须含 002303
ed = (REPO / "enhanced_data.js").read_text(encoding="utf-8")
import json, re
m = re.search(r'"v9_tiers": \{.*?"main": \[[^\]]*\]', ed, re.S)
main_prev = re.search(r'"main": \[[^\]]*\]', m.group(0)).group(0) if m else None
assert main_prev and "002303" in main_prev, f"repo enhanced_data.js 中长线池缺 002303: {main_prev}"
print(f"  repo enhanced_data.js main = {main_prev}")
assert "美盈森" in ed, "repo enhanced_data.js 缺 美盈森 名称"
print(f"  repo enhanced_data.js 002303 出现 {ed.count('002303')} 次 / 美盈森 {ed.count('美盈森')} 次")

line("=")
print("STEP 1  同步产物 → dist")
line()
copied = []
for rel in SYNC:
    s = REPO / rel
    d = DIST / rel
    assert s.exists(), f"源缺 {rel}"
    if d.exists() and md5(s) == md5(d):
        print(f"  未变  {rel}")
        continue
    d.parent.mkdir(parents=True, exist_ok=True)
    old = md5(d)[:12] if d.exists() else "无"
    shutil.copy2(s, d)
    assert md5(s) == md5(d), f"复制校验失败 {rel}"
    copied.append(rel)
    print(f"  同步  {rel:44s} {old} -> {md5(d)[:12]}")

line("=")
print("STEP 2  双同步 index.html = dual_system.html")
line()
src = DIST / "dual_system.html"
dst = DIST / "index.html"
shutil.copy2(src, dst)
assert md5(src) == md5(dst), "双同步失败"
shutil.copy2(REPO / "dual_system.html", REPO / "index.html")
assert md5(REPO / "dual_system.html") == md5(REPO / "index.html"), "repo 双同步失败"
print(f"  dist dual/index md5 {md5(dst)[:12]}")
print(f"  repo dual/index md5 {md5(REPO/'index.html')[:12]}")

line("=")
print("STEP 3  发布 gh-pages")
line()
gitdir = sh(["git", "rev-parse", "--absolute-git-dir"])[1]
print(f"  GITDIR {gitdir}")
import tempfile, os
idx = tempfile.mktemp(prefix="ghpages-index.", dir=gitdir)
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
    msg = "deploy: " + time.strftime("%Y-%m-%d %H:%M")
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
print("STEP 4  回读线上校验")
line()
time.sleep(5)
rc, out, _ = sh(["git", "fetch", "origin", "gh-pages"])
rc, head, _ = sh(["git", "rev-parse", "FETCH_HEAD"])
print(f"  线上 HEAD {head}  (期望 {commit})")
assert head == commit, "线上 HEAD 与推送提交不一致"
ok = True
for rel, expect in [("enhanced_data.js", md5(REPO / "enhanced_data.js")),
                    ("dual_system.html", md5(REPO / "dual_system.html")),
                    ("index.html", md5(REPO / "index.html")),
                    ("short_pool.js", md5(REPO / "short_pool.js")),
                    ("short_pool.json", md5(REPO / "short_pool.json"))]:
    r = subprocess.run(["git", "show", f"FETCH_HEAD:{rel}"], cwd=str(REPO),
                       capture_output=True)
    if r.returncode != 0:
        print(f"  ❌ 线上缺 {rel}"); ok = False; continue
    got = hashlib.md5(r.stdout).hexdigest()
    flag = "✅" if got == expect else "❌"
    if got != expect:
        ok = False
    print(f"  {flag} {rel:20s} 线上 {got[:12]} 本地 {expect[:12]}")

r = subprocess.run(["git", "show", "FETCH_HEAD:enhanced_data.js"], cwd=str(REPO), capture_output=True)
live_ed = r.stdout.decode("utf-8", "replace")
mm = re.search(r'"v9_tiers": \{.*?"main": \[[^\]]*\]', live_ed, re.S)
live_main = re.search(r'"main": \[[^\]]*\]', mm.group(0)).group(0) if mm else None
print(f"  线上 v9 中长线池 = {live_main}")
print(f"  线上 002303 出现 {live_ed.count('002303')} 次 / 美盈森 {live_ed.count('美盈森')} 次")
if "002303" not in live_ed:
    ok = False
    print("  ❌ 线上仍无 002303")

line("=")
print("STEP 5  HTTP 端到端（GitHub Pages 实际响应）")
line()
import urllib.request
for path, must in [("enhanced_data.js", "002303"), ("short_pool.json", "2026-09-11")]:
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
