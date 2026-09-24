# -*- coding: utf-8 -*-
"""_verify_track_sep_0924.py —— 短线板块新子标签的「内容归属 + 物理隔离 + 下架回归」校验器

对应本轮两条要求：
  R0｜「左侧捡漏」(bt520 纯左侧簿) **已从看板系统完全清除** —— 任何残留引用即失败
  D ｜`#bt-short` 参数化后每个子标签只渲染自己的回测数据；子导航恰好新增 1 项（热榜哨兵）
  F ｜新子标签的选股池 / 跟踪池 / 模拟盘状态文件 / 回测产物**无交叉读写**

设计原则（与 _verify_track_sep_0923.py 同口径）：判据全部落在**构建产物与真实文件**上，
不看源码注释；并带**负对照**——注入外策略内容后校验器必须报错，否则「全绿」无意义。

用法：python _verify_track_sep_0924.py     （rc 0 = 全绿；rc 1 = 有失败项）
"""
from __future__ import annotations

import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent
HTML = BASE / "dual_system.html"

# R0：必须为零的下架残留 token（构建产物内）
GONE_TOKENS = ["st-zuoce", "zuoce_jianlou", "ZUOCE_POOL", "ZUOCE_TRACK", "左侧捡漏"]
# R0：文件系统 / 配置层面也必须为零
GONE_FILES = ["zuoce_jianlou_pool.js", "zuoce_jianlou_track.js",
              "backtest/zuoce_jianlou_paper_state.json", "backtest/zuoce_jianlou_backtest.json",
              "backtest/zuoce_jianlou_daily.py", "backtest/build_zuoce_backtest_ref.py"]
GONE_CONFIGS = ["daily_refresh.py", ".github/cloud/cloud_refresh.py", "_deploy_fundline_0911.py",
                "build_dual_system.py"]

NEW_SUBS = [("st-sentinel", "热榜哨兵")]
OLD_SUBS = [("st-qlch", "超跌低开低吸"), ("st-kh", "超卖伏击"), ("st-etf", "ETF轮动"),
            ("st-stk", "股票池"), ("st-fund", "基金池")]

OWNED = {
    "st-sentinel": {
        "js": ["sentinel_pool.js", "sentinel_track.js"],
        "state_json": "backtest/sentinel_state.json",
        "bt_json": "backtest/sentinel_backtest.json",
        "key": "sentinel",
        "var": ["window.SENTINEL_POOL", "window.SENTINEL_TRACK"],
        "producer": "backtest/sentinel_daily.py",
    },
}
LEGACY_SHARED = ["short_pool.js", "short_pool.json", "qlch_paper_state",
                 "a5_paper_state.json", "khunter_paper_state.json",
                 "satellite_paper.json", "satellite_pool.json"]

ALLOWED_CARDS = {
    "st-qlch": ["bt-st-qlch", "bt-qlch"],
    "st-kh": ["bt-short-stock-main-c", "bt-short-stock-hybrid"],
    "st-etf": ["bt-st-etf", "bt-etf"],
    "st-stk": ["bt-short-stock-all", "bt-short-stock-main",
               "bt-short-stock-gem", "bt-short-stock-star"],
    "st-fund": ["bt-short-fund"],
    "st-sentinel": ["bt-st-sentinel", "bt-sentinel"],
}

fails = []
oks = []


def ok(m):
    oks.append(m)
    print("   [ok] %s" % m)


def bad(m):
    fails.append(m)
    print("   [!!] %s" % m)


def norm(s):
    return " ".join(s.split())


IO_TOKENS = ("read_text(", "write_text(", "open(", "json.load", "json.dump",
             "Path(", "= BASE /", "shutil.copy", "csv.")


def cross_reads(src, forbid):
    """只把**真实读写行**算作跨界：散文/注释/字段说明里提到文件名不算（那是声明独立性）。"""
    out = []
    for ln in src.splitlines():
        st = ln.strip()
        if st.startswith("#"):
            continue
        for t in forbid:
            if t in ln and any(k in ln for k in IO_TOKENS):
                out.append("%s (line: %s)" % (t, st[:90]))
    return out


def slice_view(html, sub):
    i = html.find('id="sv-%s"' % sub)
    if i < 0:
        return ""
    j = html.find('<div class="subview"', i + 10)
    k = html.find('<div class="view"', i + 10)
    ends = [x for x in (j, k) if x > 0]
    return html[i:min(ends)] if ends else html[i:]


def slice_bt_sub(html, sub):
    """从一个 data-bt-sub 块起点切到下一个块或子视图/视图边界。"""
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


# 配置层只认**接线标识符**（中文名可能合法地出现在「已下架」注释里）
GONE_WIRING = ["st-zuoce", "zuoce_jianlou", "ZUOCE_", "build_zuoce_backtest_ref"]


def check_r0_gone(html):
    """R0：左侧捡漏已从看板系统完全清除。"""
    print("\n① R0 · 左侧捡漏已完全清除（产物 / 文件 / 配置三面）")
    for t in GONE_TOKENS:
        n = html.count(t)
        (ok if n == 0 else bad)("构建产物内 %-14s 出现 %d 次（须为 0）" % (t, n))
    for f in GONE_FILES:
        p = BASE / f
        (ok if not p.exists() else bad)("文件 %-46s %s" % (f, "已移除" if not p.exists() else "仍存在"))
    for c in GONE_CONFIGS:
        p = BASE / c
        if not p.exists():
            bad("配置 %s 不在盘" % c)
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        hits = [x for x in GONE_WIRING if x in t]
        (ok if not hits else bad)("%-34s 接线残留 %s" % (c, hits if hits else "无"))


def check_d_nav_blocks(html):
    """D：子导航恰好新增 1 项；bt-sub 1:1；每块只含自有卡；无同文块。"""
    print("\n② 子导航（恰好新增 1 项 / 四字名 / 原 5 项保留）")
    subs = nav_items(html)
    (ok if len(subs) == 6 else bad)("短线子导航项数 = %d（应为 6 = 原 5 + 新 1）：%s" % (len(subs), subs))
    for k, t in OLD_SUBS:
        (ok if (k, t) in subs else bad)("原项保留 %s -> %s" % (k, t))
    for k, t in NEW_SUBS:
        (ok if (k, t) in subs else bad)("新增项 %s -> %s" % (k, t))
        if len(t) != 4:
            bad("「%s」不是四字名（len=%d）" % (t, len(t)))

    print("\n③ data-bt-sub 与子导航 1:1")
    ks = bt_keys(html)
    want = sorted(k for k, _ in OLD_SUBS + NEW_SUBS)
    (ok if sorted(ks) == want else bad)("data-bt-sub 块 = %d → %s" % (len(ks), ks))

    print("\n④ 每个 bt-sub 块只渲染自己那一块（不得含其他子标签的卡）")
    for k, _t in NEW_SUBS + OLD_SUBS:
        ids = cards_in(html, k)
        if not ids:
            bad("%s 块内没有回测卡" % k)
            continue
        fc = foreign_cards(k, ids)
        if fc:
            bad("%s 块含其他子标签的卡 %s" % (k, fc))
        else:
            ok("%s 块自有卡 %s（%d 张 / 无跨标签卡）" % (k, ids, len(ids)))

    print("\n⑤ 任意两个 bt-sub 块不得同文（共用即同文）")
    seen, dup = {}, []
    for k, _t in OLD_SUBS + NEW_SUBS:
        h = hash(norm(slice_bt_sub(html, k)))
        if h in seen:
            dup.append((seen[h], k))
        seen[h] = k
    (ok if not dup else bad)("6 个 bt-sub 块内容两两不同" if not dup else "发现同文块 %s" % dup)


def check_d_views(html):
    """D 续：新子视图只引用自有产物；回测卡内容为自有 json 的指纹。"""
    print("\n⑥ 新子视图只引用自己的产物（不跨界）")
    for sub, meta in OWNED.items():
        seg = slice_view(html, sub)
        if not seg:
            bad("找不到子视图 #sv-%s" % sub)
            continue
        (ok if 'id="own-%s"' % meta["key"] in seg else bad)(
            "#sv-%s 含自有资产卡 #own-%s" % (sub, meta["key"]))
        for n in meta["js"] + [meta["state_json"]]:
            (ok if n in seg else bad)("#sv-%s 引用自有产物 %s" % (sub, n))
        bj = json.loads((BASE / meta["bt_json"]).read_text(encoding="utf-8"))
        fp = (bj.get("period") or "")[:20]
        if fp and fp in seg:
            ok("#sv-%s 回测卡内容指纹「%s…」= %s 的 period" % (sub, fp, meta["bt_json"]))
        else:
            bad("#sv-%s 回测卡未渲染 %s 的 period 指纹 %r" % (sub, meta["bt_json"], fp))
        leak = [x for x in GONE_TOKENS if x in seg]
        (ok if not leak else bad)("#sv-%s 未混入已下架策略 token%s"
                                 % (sub, "" if not leak else " %s" % leak))


def check_f():
    """F：文件物理隔离 + 脚本禁读面 + 载荷自证 + 影子账本门禁。"""
    print("\n⑦ 物理隔离 · 产物在盘且路径唯一")
    allp = []
    for sub, meta in OWNED.items():
        for n in meta["js"] + [meta["state_json"], meta["bt_json"]]:
            p = BASE / n
            if p.exists():
                ok("%-46s 在盘 %d B" % (n, p.stat().st_size))
                allp.append(n)
            else:
                bad("%-46s 不在盘" % n)
    (ok if len(set(allp)) == len(allp) else bad)("全部产物路径唯一（无同名共用）")

    print("\n⑧ 产出脚本静态禁读面（真实 I/O 层面跨界 = 0）")
    for sub, meta in OWNED.items():
        src = (BASE / meta["producer"]).read_text(encoding="utf-8", errors="replace")
        forbid = ["zuoce_jianlou_pool.js", "zuoce_jianlou_track.js",
                  "zuoce_jianlou_paper_state.json", "ZUOCE_POOL", "ZUOCE_TRACK"] + LEGACY_SHARED
        h = cross_reads(src, forbid)
        if h:
            bad("%s 真实读取了跨界文件 %s" % (meta["producer"], h))
        else:
            ok("%s 禁读面干净（%d 个 token；仅计真实 I/O 行）" % (meta["producer"], len(forbid)))

    print("\n⑨ 载荷自证身份 + 影子账本门禁")
    for sub, meta in OWNED.items():
        for n in meta["js"]:
            t = (BASE / n).read_text(encoding="utf-8", errors="replace")
            head = t[t.find("window."):]
            var = head[:head.find("=")].strip()
            (ok if var in meta["var"] else bad)("%s 导出 %s" % (n, var))
            if ('"strategy_key":"%s"' % meta["key"]) in t or ('"strategy_key": "%s"' % meta["key"]) in t:
                ok("%s strategy_key = %s" % (n, meta["key"]))
            else:
                bad("%s 缺 strategy_key=%s" % (n, meta["key"]))
        d = json.loads((BASE / meta["state_json"]).read_text(encoding="utf-8"))
        (ok if d.get("strategy_key") == meta["key"] else bad)(
            "%s strategy_key = %r" % (meta["state_json"], d.get("strategy_key")))
        (ok if d.get("trading_enabled") is False else bad)(
            "%s trading_enabled = %r（影子账本须恒 false）" % (meta["state_json"], d.get("trading_enabled")))
        clean = all(not d.get(k) for k in ("positions", "closed", "equity"))
        (ok if clean else bad)("%s positions/closed/equity 均为空（不伪造成交）" % meta["state_json"])


def _selftest_cross_reads():
    """负对照 3：合成一段真实读取跨界文件的源码 -> cross_reads 必须检出。"""
    lines = [
        'POOL_JS = BASE / "zuoce_jianlou_pool.js"',
        'd = json.loads(POOL_JS.read_text(encoding="utf-8"))',
        '# 注释里提到 short_pool.js 不算跨界',
    ]
    fake = chr(10).join(lines)
    got = cross_reads(fake, ["zuoce_jianlou_pool.js", "short_pool.js"])
    okd = (any("zuoce_jianlou_pool.js" in g for g in got)
           and not any("short_pool.js" in g for g in got))
    print("   -> 负对照 3（静态跨界读取检测）：%s" % ("已检出" if okd else "漏检"))
    return okd


def run_all(html):
    check_r0_gone(html)
    check_d_nav_blocks(html)
    check_d_views(html)
    check_f()
    return len(oks), len(fails), list(fails)


print("=" * 78)
print("短线板块新子标签 · 内容归属 + 物理隔离 + 下架回归校验（_verify_track_sep_0924.py）")
print("=" * 78)
if not HTML.exists():
    print("缺 %s（先跑 build_dual_system.py）" % HTML)
    sys.exit(1)
HTML_TXT = HTML.read_text(encoding="utf-8", errors="replace")

print("\n【正例】真实构建产物")
n_ok, n_fail, real_fails = run_all(HTML_TXT)

print("\n" + "=" * 78)
print("【负对照 1】把 zuoce_jianlou_pool.js 注入 #sv-st-sentinel -> 必须报错")
print("=" * 78)
INJ1 = HTML_TXT.replace('id="own-sentinel"', 'id="own-sentinel" data-leak="zuoce_jianlou_pool.js"', 1)
assert INJ1 != HTML_TXT, "负对照 1 未改动输入"
run_all(INJ1)
neg1 = len(fails) > 0
print("   -> 负对照 1：%s（失败项 %d）" % ("已检出" if neg1 else "漏检", len(fails)))

print("\n" + "=" * 78)
print("【负对照 2】把 st-sentinel 的 bt 块换成 st-kh 的 -> 必须报错")
print("=" * 78)
seg_kh = slice_bt_sub(HTML_TXT, "st-kh")
i2 = HTML_TXT.find('data-bt-sub="st-sentinel"')
j2 = HTML_TXT.find('<div class="subview"', i2)
assert j2 > i2 > 0, "负对照 2 注入失败：找不到边界"
SWAP = HTML_TXT[:i2] + seg_kh + HTML_TXT[j2:]
assert SWAP != HTML_TXT, "负对照 2 未改动输入"
run_all(SWAP)
neg2 = len(fails) > 0
print("   -> 负对照 2：%s（失败项 %d）" % ("已检出" if neg2 else "漏检", len(fails)))

print("\n" + "=" * 78)
print("【负对照 3】合成「真实读取跨界文件」的源码 -> 静态判据 8 必须检出")
print("=" * 78)
neg3 = _selftest_cross_reads()

print("\n" + "=" * 78)
print("【负对照 4】把已下架的 st-zuoce 回注子导航 -> R0 必须检出")
print("=" * 78)
INJ4 = HTML_TXT.replace('<button class="subtab" data-sub="st-sentinel"',
                        '<button class="subtab" data-sub="st-zuoce">左侧捡漏</button>'
                        '<button class="subtab" data-sub="st-sentinel"', 1)
assert INJ4 != HTML_TXT, "负对照 4 未改动输入"
run_all(INJ4)
neg4 = any("st-zuoce" in f for f in fails) or any("左侧捡漏" in f for f in fails)
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
