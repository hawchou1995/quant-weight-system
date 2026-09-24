# -*- coding: utf-8 -*-
"""_verify_track_sep_0924.py —— 短线板块「下架回归 + 内容归属」校验器

覆盖本轮两次下架决策：
  R0-a｜「左侧捡漏」(bt520 纯左侧簿) 复测门未过 → 完全清除（ADR-0010 D14）
  R0-b｜「热榜哨兵」(jiandi top30) 不满足投产要求 → 完全清除（ADR-0010 D16）
  D  ｜`#bt-short` 参数化后每个子标签只渲染自己的回测数据（不得共用／不得跨标签）
  K  ｜**刻意保留**的研究证据仍在盘（删掉它们＝删除证据，是比残留更严重的错误）

判据全部落在**构建产物与真实文件**上，不看源码注释；并带 4 个**负对照**
（两个下架策略各自回注 / bt 块篡改 / 合成跨界读取源码），否则「全绿」没有鉴别力。

用法：python _verify_track_sep_0924.py     （rc 0 = 全绿；rc 1 = 有失败项）
"""
from __future__ import annotations

import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent
HTML = BASE / "dual_system.html"

# R0：构建产物内必须为 0 的下架 token
GONE_TOKENS = ["st-zuoce", "zuoce_jianlou", "ZUOCE_POOL", "ZUOCE_TRACK", "左侧捡漏",
               "st-sentinel", "sentinel_pool.js", "sentinel_track.js",
               "SENTINEL_POOL", "SENTINEL_TRACK", "热榜哨兵"]
# R0：文件系统层面必须已移除
GONE_FILES = ["zuoce_jianlou_pool.js", "zuoce_jianlou_track.js",
              "backtest/zuoce_jianlou_paper_state.json", "backtest/zuoce_jianlou_backtest.json",
              "backtest/zuoce_jianlou_daily.py", "backtest/build_zuoce_backtest_ref.py",
              "sentinel_pool.js", "sentinel_track.js",
              "backtest/sentinel_state.json", "backtest/sentinel_daily.py",
              "backtest/sentinel_0924"]
# R0：配置层「接线标识符」必须为 0（中文名可能合法出现在「已下架」注释里，故不查）
GONE_WIRING = ["st-zuoce", "zuoce_jianlou", "ZUOCE_", "build_zuoce_backtest_ref",
               "st-sentinel", "sentinel_pool.js", "sentinel_track.js",
               "sentinel_daily.py", "backtest/sentinel_state.json",
               "SENTINEL_POOL", "SENTINEL_TRACK"]
GONE_CONFIGS = ["daily_refresh.py", ".github/cloud/cloud_refresh.py",
                "_deploy_fundline_0911.py", "build_dual_system.py"]
# K：刻意保留的证据（必须仍在盘）
KEPT_FILES = ["backtest/bt520_holdout_0924.json",
              "backtest/sentinel_backtest.json",
              "backtest/PRE-REGISTRATION_20260924_jiandi_top30_sentinel.md",
              "backtest/jiandi_top_grid_0924_out/top1_nav_daily_0924.csv"]

ORIG_SUBS = [("st-qlch", "超跌低开低吸"), ("st-kh", "超卖伏击"), ("st-etf", "ETF轮动"),
             ("st-stk", "股票池"), ("st-fund", "基金池")]
ALLOWED_CARDS = {
    "st-qlch": ["bt-st-qlch", "bt-qlch"],
    "st-kh": ["bt-short-stock-main-c", "bt-short-stock-hybrid"],
    "st-etf": ["bt-st-etf", "bt-etf"],
    "st-stk": ["bt-short-stock-all", "bt-short-stock-main"],
    "st-fund": ["bt-short-fund"],
}
fails, oks = [], []


def ok(m):
    oks.append(m); print("   [ok] %s" % m)


def bad(m):
    fails.append(m); print("   [!!] %s" % m)


def norm(s):
    return " ".join(s.split())


IO_TOKENS = ("read_text(", "write_text(", "open(", "json.load", "json.dump",
             "Path(", "= BASE /", "shutil.copy", "csv.")


def cross_reads(src, forbid):
    """只把**真实读写行**算作跨界；散文/注释里提到文件名不算（那是声明，不是读取）。"""
    out = []
    for ln in src.splitlines():
        st = ln.strip()
        if st.startswith("#"):
            continue
        for t in forbid:
            if t in ln and any(k in ln for k in IO_TOKENS):
                out.append("%s (line: %s)" % (t, st[:90]))
    return out


def slice_bt_sub(html, sub):
    i = html.find('data-bt-sub="%s"' % sub)
    if i < 0:
        return ""
    cands = []
    for tok in ('data-bt-sub="', '<div class="subview"', '<div class="view"', '</div>' * 3):
        j = html.find(tok, i + 10)
        if j > 0:
            cands.append(j)
    return html[i:min(cands)] if cands else html[i:]


def nav_items(html):
    nav_i = html.find('data-view="short"')
    nav_seg = html[nav_i:html.find("</div>", nav_i)]
    subs, p = [], 0
    while True:
        a = nav_seg.find('data-sub="', p)
        if a < 0:
            break
        b = nav_seg.find('"', a + 10)
        c = nav_seg.find(">", b)
        d = nav_seg.find("<", c)
        subs.append((nav_seg[a + 10:b], nav_seg[c + 1:d].strip()))
        p = d
    return subs


def bt_keys(html):
    ks, p = [], 0
    while True:
        a = html.find('data-bt-sub="', p)
        if a < 0:
            break
        b = html.find('"', a + 13)
        ks.append(html[a + 13:b])
        p = b
    return ks


def cards_in(html, sub):
    seg = slice_bt_sub(html, sub)
    ids, p = [], 0
    while True:
        a = seg.find('class="bt-card" id="', p)
        if a < 0:
            break
        b = seg.find('"', a + 20)
        ids.append(seg[a + 20:b])
        p = b
    return ids


def foreign_cards(sub, ids):
    mine = set(ALLOWED_CARDS.get(sub, []))
    others = set()
    for k, v in ALLOWED_CARDS.items():
        if k != sub:
            others |= set(v)
    return [x for x in ids if x not in mine and x in others]


def check_r0(html):
    print("\n① R0 · 两次下架是否彻底（产物 / 文件 / 配置三面）")
    for t in GONE_TOKENS:
        n = html.count(t)
        (ok if n == 0 else bad)("构建产物内 %-18s 出现 %d 次（须为 0）" % (t, n))
    for f in GONE_FILES:
        p = BASE / f
        (ok if not p.exists() else bad)("已移除 %-46s %s" % (f, "✓" if not p.exists() else "仍存在 !!"))
    for c in GONE_CONFIGS:
        p = BASE / c
        if not p.exists():
            bad("配置 %s 不在盘" % c); continue
        t = p.read_text(encoding="utf-8", errors="replace")
        hits = [x for x in GONE_WIRING if x in t]
        (ok if not hits else bad)("%-34s 接线残留 %s" % (c, hits if hits else "无"))


def check_kept():
    print("\n② K · 刻意保留的研究证据仍在盘（删证据比残留更严重）")
    for f in KEPT_FILES:
        p = BASE / f
        (ok if p.exists() else bad)("保留 %-62s %s" % (f, "✓" if p.exists() else "缺失 !!"))


def check_d(html):
    print("\n③ 子导航回到原 5 项（不得有新增子标签残留）")
    subs = nav_items(html)
    (ok if subs == ORIG_SUBS else bad)("短线子导航 = %s" % (subs,))

    print("\n④ data-bt-sub 与子导航 1:1")
    ks = bt_keys(html)
    want = sorted(k for k, _ in ORIG_SUBS)
    (ok if sorted(ks) == want else bad)("data-bt-sub 块 = %d → %s" % (len(ks), ks))

    print("\n⑤ 每个 bt-sub 块只渲染自己那一块（不得跨标签）")
    for k, _t in ORIG_SUBS:
        ids = cards_in(html, k)
        if not ids:
            bad("%s 块内没有回测卡" % k); continue
        fc = foreign_cards(k, ids)
        (ok if not fc else bad)("%s 块自有卡 %s%s" % (k, ids, "" if not fc else "；含其他标签卡 %s" % fc))

    print("\n⑥ 任意两个 bt-sub 块不得同文（共用即同文）")
    seen, dup = {}, []
    for k, _t in ORIG_SUBS:
        h = hash(norm(slice_bt_sub(html, k)))
        if h in seen:
            dup.append((seen[h], k))
        seen[h] = k
    (ok if not dup else bad)("5 个 bt-sub 块内容两两不同" if not dup else "发现同文块 %s" % dup)


def _selftest_cross_reads():
    """负对照 3：合成一段真实读取已下架策略产物的源码 → cross_reads 必须检出。"""
    lines = [
        'POOL_JS = BASE / "sentinel_pool.js"',
        'd = json.loads(POOL_JS.read_text(encoding="utf-8"))',
        '# 注释里提到 zuoce_jianlou_pool.js 不算跨界',
    ]
    fake = chr(10).join(lines)
    got = cross_reads(fake, ["sentinel_pool.js", "zuoce_jianlou_pool.js"])
    okd = (any("sentinel_pool.js" in g for g in got)
           and not any("zuoce_jianlou_pool.js" in g for g in got))
    print("   -> 负对照 3（静态跨界读取检测）：%s" % ("已检出" if okd else "漏检"))
    return okd


def run_all(html):
    check_r0(html)
    check_kept()
    check_d(html)
    return len(oks), len(fails), list(fails)


print("=" * 78)
print("短线板块 · 下架回归 + 内容归属校验（_verify_track_sep_0924.py）")
print("=" * 78)
if not HTML.exists():
    print("缺 %s（先跑 build_dual_system.py）" % HTML)
    sys.exit(1)
HTML_TXT = HTML.read_text(encoding="utf-8", errors="replace")

print("\n【正例】真实构建产物")
n_ok, n_fail, real_fails = run_all(HTML_TXT)

print("\n" + "=" * 78)
print("【负对照 1】把已下架的 st-zuoce 回注子导航 -> R0 必须检出")
print("=" * 78)
N1 = HTML_TXT.replace('<button class="subtab" data-sub="st-fund"',
                      '<button class="subtab" data-sub="st-zuoce">左侧捡漏</button>'
                      '<button class="subtab" data-sub="st-fund"', 1)
assert N1 != HTML_TXT, "负对照 1 未改动输入"
run_all(N1)
neg1 = any(("st-zuoce" in f) or ("左侧捡漏" in f) for f in fails)
print("   -> 负对照 1：%s（失败项 %d）" % ("已检出" if neg1 else "漏检", len(fails)))

print("\n" + "=" * 78)
print("【负对照 2】把已下架的 st-sentinel 回注子导航 -> R0 必须检出")
print("=" * 78)
N2 = HTML_TXT.replace('<button class="subtab" data-sub="st-fund"',
                      '<button class="subtab" data-sub="st-sentinel">热榜哨兵</button>'
                      '<button class="subtab" data-sub="st-fund"', 1)
assert N2 != HTML_TXT, "负对照 2 未改动输入"
run_all(N2)
neg2 = any(("st-sentinel" in f) or ("热榜哨兵" in f) for f in fails)
print("   -> 负对照 2：%s（失败项 %d）" % ("已检出" if neg2 else "漏检", len(fails)))

print("\n" + "=" * 78)
print("【负对照 3】合成「真实读取已下架产物」的源码 -> 静态检测必须检出")
print("=" * 78)
neg3 = _selftest_cross_reads()

print("\n" + "=" * 78)
print("【负对照 4】把 st-kh 的 bt 块换成 st-qlch 的 -> 归属判据必须检出")
print("=" * 78)
seg_q = slice_bt_sub(HTML_TXT, "st-qlch")
i4 = HTML_TXT.find('data-bt-sub="st-kh"')
j4 = HTML_TXT.find('data-bt-sub="', i4 + 10)
assert j4 > i4 > 0, "负对照 4 定位失败"
N4 = HTML_TXT[:i4] + seg_q + HTML_TXT[j4:]
assert N4 != HTML_TXT, "负对照 4 未改动输入"
run_all(N4)
neg4 = len(fails) > 0
print("   -> 负对照 4：%s（失败项 %d）" % ("已检出" if neg4 else "漏检", len(fails)))

print("\n" + "=" * 78)
print("结果：正例 %d 项通过 / %d 项失败；负对照 1 %s / 2 %s / 3 %s / 4 %s"
      % (n_ok, n_fail, "已检出" if neg1 else "漏检", "已检出" if neg2 else "漏检",
         "已检出" if neg3 else "漏检", "已检出" if neg4 else "漏检"))
if real_fails:
    print("失败项：")
    for f in real_fails:
        print("   - %s" % f)
print("=" * 78)
rc = 0 if (n_fail == 0 and neg1 and neg2 and neg3 and neg4) else 1
print("VERIFY_RC=%d" % rc)
sys.exit(rc)
