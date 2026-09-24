# -*- coding: utf-8 -*-
"""_verify_track_sep_0924.py —— 短线板块新增 2 子标签的「内容归属 + 物理隔离」校验器

对应契约判据：
  D｜`#bt-short` 参数化后每个子标签只渲染自己的回测数据；子导航恰好新增 2 项（四字名）
  F｜新增子标签的选股池 / 跟踪池 / 模拟盘状态文件 / 回测产物**无交叉读写**

设计原则（与 _verify_track_sep_0923.py 同口径）：判据全部落在**构建产物与真实文件**上，
不看源码注释；并且带**负对照**——把外策略内容注入后校验器必须报错，否则「全绿」无意义。

用法：python _verify_track_sep_0924.py        （rc 0 = 全绿；rc 1 = 有失败项）
"""
from __future__ import annotations

import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent
HTML = BASE / "dual_system.html"

NEW_SUBS = [("st-zuoce", "左侧捡漏"), ("st-sentinel", "热榜哨兵")]
OLD_SUBS = [("st-qlch", "超跌低开低吸"), ("st-kh", "超卖伏击"), ("st-etf", "ETF轮动"),
            ("st-stk", "股票池"), ("st-fund", "基金池")]

OWNED = {
    "st-zuoce": {
        "js": ["zuoce_jianlou_pool.js", "zuoce_jianlou_track.js"],
        "json": ["backtest/zuoce_jianlou_paper_state.json", "backtest/zuoce_jianlou_backtest.json"],
        "key": "zuoce_jianlou",
        "bt_json": "backtest/zuoce_jianlou_backtest.json",
        "var": ["window.ZUOCE_POOL", "window.ZUOCE_TRACK"],
        "producer": "backtest/zuoce_jianlou_daily.py",
    },
    "st-sentinel": {
        "js": ["sentinel_pool.js", "sentinel_track.js"],
        "json": ["backtest/sentinel_state.json", "backtest/sentinel_backtest.json"],
        "key": "sentinel",
        "bt_json": "backtest/sentinel_backtest.json",
        "var": ["window.SENTINEL_POOL", "window.SENTINEL_TRACK"],
        "producer": "backtest/sentinel_daily.py",
    },
}

LEGACY_SHARED = ["short_pool.js", "short_pool.json", "qlch_paper_state",
                 "a5_paper_state.json", "khunter_paper_state.json",
                 "satellite_paper.json", "satellite_pool.json"]

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


def slice_view(html, sub):
    i = html.find('id="sv-%s"' % sub)
    if i < 0:
        return ""
    j = html.find('<div class="subview"', i + 10)
    k = html.find('<div class="view"', i + 10)
    ends = [x for x in (j, k) if x > 0]
    return html[i:min(ends)] if ends else html[i:]


def slice_bt_sub(html, sub):
    """从一个 data-bt-sub 块的起点切到**下一个块或子视图/视图边界**。

    2026-09-24 修：原实现末块（st-sentinel）找不到下一个 data-bt-sub → 一路吃到
    #view-a5 的 bt-a5-all，造成「块内含非自有卡」的假阳性。故补 view/subview 边界。
    """
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


IO_TOKENS = ("read_text(", "write_text(", "open(", "json.load", "json.dump",
             "Path(", "= BASE /", "shutil.copy", "csv.")


# 每个子标签**自有**的回测卡 id 许可集（构建产物实测）。
# 判据不是「块内卡名必须等于某个字符串」，而是「块内不得出现**其他子标签**的卡」——
# 这才是契约点⑤「严禁共用」的可判定形式。
ALLOWED_CARDS = {
    "st-qlch": ["bt-st-qlch", "bt-qlch"],
    "st-kh": ["bt-short-stock-main-c", "bt-short-stock-hybrid"],
    "st-etf": ["bt-st-etf", "bt-etf"],
    "st-stk": ["bt-short-stock-all", "bt-short-stock-main",
               "bt-short-stock-gem", "bt-short-stock-star"],
    "st-fund": ["bt-short-fund"],
    "st-zuoce": ["bt-st-zuoce", "bt-zuoce"],
    "st-sentinel": ["bt-st-sentinel", "bt-sentinel"],
}


def foreign_cards(sub, ids):
    """块内出现「属于其他子标签」的卡 id → 返回那些 id。"""
    mine = set(ALLOWED_CARDS.get(sub, []))
    others = set()
    for k, v in ALLOWED_CARDS.items():
        if k != sub:
            others |= set(v)
    return [x for x in ids if x not in mine and x in others]


def cross_reads(src, forbid):
    """只把**真实读写行**算作跨界：散文/注释/字段说明里提到文件名不算（那是声明独立性）。

    判据：某行含禁止 token，且该行含任一 I/O 记号 → 判为真实跨界。
    """
    out = []
    for ln in src.splitlines():
        st = ln.strip()
        if st.startswith("#"):
            continue                      # 纯注释行跳过
        for t in forbid:
            if t in ln and any(k in ln for k in IO_TOKENS):
                out.append("%s (line: %s)" % (t, st[:90]))
    return out


def _selftest_cross_reads():
    """7 的负对照：合成一段真实读取他策略文件的源码 -> 必须被检出。"""
    lines = [
        'POOL_JS = BASE / "sentinel_pool.js"',
        'd = json.loads(POOL_JS.read_text(encoding="utf-8"))',
        '# 注释里提到 sentinel_track.js 不算跨界',
    ]
    fake = chr(10).join(lines)
    got = cross_reads(fake, ["sentinel_pool.js", "sentinel_track.js"])
    okd = (any("sentinel_pool.js" in g for g in got)
           and not any("sentinel_track" in g for g in got))
    print("   -> 负对照 3（静态跨读检测）：%s" % ("已检出" if okd else "漏检"))
    return okd




def check_d_nav_and_blocks(html):
    """判据 D：子导航 + bt-sub 分流 + 每块只含自有卡 + 无同文块"""
    del fails[:]
    del oks[:]

    print("\n① 子导航项（恰好 +2 / 四字名）")
    subs = nav_items(html)
    if len(subs) == 7:
        ok("短线子导航项数 = 7（原 5 + 新 2）")
    else:
        bad("短线子导航项数 = %d（应为 7）：%s" % (len(subs), subs))
    for k, t in OLD_SUBS:
        (ok if (k, t) in subs else bad)("原项 %s -> %s" % (k, t))
    for k, t in NEW_SUBS:
        (ok if (k, t) in subs else bad)("新增项 %s -> %s" % (k, t))
        if len(t) != 4:
            bad("「%s」不是四字名（len=%d）" % (t, len(t)))

    print("\n② data-bt-sub 与子导航 1:1")
    bt_keys, p = [], 0
    while True:
        a = html.find('data-bt-sub="', p)
        if a < 0:
            break
        b = html.find('"', a + 13)
        bt_keys.append(html[a + 13:b])
        p = b
    want = sorted(k for k, _ in OLD_SUBS + NEW_SUBS)
    if sorted(bt_keys) == want:
        ok("data-bt-sub 块 = %d 且键集合一致" % len(bt_keys))
    else:
        bad("data-bt-sub 键不一致 -> %s（期望 %s）" % (bt_keys, want))

    print("\n③ 每个 bt-sub 块只渲染**自己**的回测卡")
    for k, _t in NEW_SUBS + OLD_SUBS:
        seg = slice_bt_sub(html, k)
        if not seg:
            bad("找不到 data-bt-sub=%s 的块" % k)
            continue
        ids, p2 = [], 0
        while True:
            a = seg.find('class="bt-card" id="', p2)
            if a < 0:
                break
            b = seg.find('"', a + 20)
            ids.append(seg[a + 20:b])
            p2 = b
        if not ids:
            bad("%s 块内没有回测卡" % k)
            continue
        foreign = foreign_cards(k, ids)
        if foreign:
            bad("%s 块含**其他子标签**的卡 %s" % (k, foreign))
        else:
            ok("%s 块自有卡 %s（卡数 %d / 无跨策略卡）" % (k, ids, len(ids)))

    print("\n④ 任意两个 bt-sub 块内容不得完全相同（共用即同文）")
    seen, dup = {}, []
    for k, _t in OLD_SUBS + NEW_SUBS:
        h = hash(norm(slice_bt_sub(html, k)))
        if h in seen:
            dup.append((seen[h], k))
        seen[h] = k
    if dup:
        bad("发现同文回测块：%s" % dup)
    else:
        ok("7 个 bt-sub 块内容两两不同")


def check_d_views(html):
    """判据 D 续：两个新子视图只引用自己的产物"""
    print("\n⑤ 新子视图只引用**自己**的产物（不跨界）")
    for sub, meta in OWNED.items():
        seg = slice_view(html, sub)
        if not seg:
            bad("找不到子视图 #sv-%s" % sub)
            continue
        (ok if 'id="own-%s"' % meta["key"] in seg else bad)(
            "#sv-%s 含自有资产卡 #own-%s" % (sub, meta["key"]))
        for n in meta["js"] + [x for x in meta["json"] if x != meta["bt_json"]]:
            (ok if n in seg else bad)("#sv-%s 引用自有产物 %s" % (sub, n))
        # 回测卡的**内容**必须来自自有 json 那份：用 period 指纹验证（文件名不显示在卡上）
        _bj = json.loads((BASE / meta["bt_json"]).read_text(encoding="utf-8"))
        _fp = (_bj.get("period") or "")[:20]
        if _fp and _fp in seg:
            ok("#sv-%s 回测卡内容指纹 = %s 的 period「%s…」" % (sub, meta["bt_json"], _fp))
        else:
            bad("#sv-%s 回测卡未渲染 %s 的 period 指纹 %r" % (sub, meta["bt_json"], _fp))
        for s2, m in OWNED.items():
            if s2 == sub:
                continue
            leak = [n for n in (m["js"] + m["json"]) if n in seg]
            if leak:
                bad("#sv-%s 混入**其他策略**产物 %s" % (sub, leak))
            else:
                ok("#sv-%s 无跨策略产物引用（对侧 %s）" % (sub, m["key"]))


def check_f_files():
    """判据 F：产物文件物理隔离"""
    print("\n⑥ 物理隔离 · 产物文件在盘且互不重叠")
    allp = []
    for sub, meta in OWNED.items():
        for n in meta["js"] + meta["json"]:
            p = BASE / n
            if p.exists():
                ok("%s 在盘（%d B）" % (n, p.stat().st_size))
                allp.append(n)
            else:
                bad("%s 不在盘" % n)
    (ok if len(set(allp)) == len(allp) else bad)("全部产物路径唯一（无同名共用）")

    print("\n⑦ 产出脚本静态禁读面（跨策略文件引用 = 0）")
    for sub, meta in OWNED.items():
        src = (BASE / meta["producer"]).read_text(encoding="utf-8", errors="replace")
        other = [m for s2, m in OWNED.items() if s2 != sub][0]
        forbid = list(other["js"] + other["json"]) + other["var"] + LEGACY_SHARED
        h = cross_reads(src, forbid)
        if h:
            bad("%s 真实读取了他策略/共享文件 %s" % (meta["producer"], h))
        else:
            ok("%s 禁读面干净（%d 个 token；仅计真实 I/O 行）" % (meta["producer"], len(forbid)))

    print("\n⑧ 产物载荷自证身份（strategy_key / as_of）")
    for sub, meta in OWNED.items():
        for n in meta["js"]:
            t = (BASE / n).read_text(encoding="utf-8", errors="replace")
            head = t[t.find("window."):]
            var = head[:head.find("=")].strip()
            (ok if var in meta["var"] else bad)("%s 导出 %s" % (n, var))
            if '"strategy_key":"%s"' % meta["key"] in t or '"strategy_key": "%s"' % meta["key"] in t:
                ok("%s strategy_key = %s" % (n, meta["key"]))
            else:
                bad("%s 缺 strategy_key=%s" % (n, meta["key"]))
            if '"as_of":"2026-09-24"' in t or '"as_of": "2026-09-24"' in t:
                ok("%s as_of = 2026-09-24" % n)
            else:
                bad("%s as_of 不是 2026-09-24" % n)
        for n in meta["json"]:
            d = json.loads((BASE / n).read_text(encoding="utf-8"))
            (ok if d.get("strategy_key") == meta["key"] else bad)(
                "%s strategy_key = %r" % (n, d.get("strategy_key")))

    print("\n⑨ 模拟盘门禁一致性（未过门不得开仓）")
    ps = json.loads((BASE / "backtest/zuoce_jianlou_paper_state.json").read_text(encoding="utf-8"))
    if ps.get("trading_enabled") is False and ps.get("positions") == [] and ps.get("nav") is None:
        ok("左侧捡漏 模拟盘恒关：trading_enabled=false / positions=[] / nav=null（gate=%s）" % ps.get("gate"))
    else:
        bad("左侧捡漏 模拟盘状态异常：%r / %r / %r"
            % (ps.get("trading_enabled"), ps.get("positions"), ps.get("nav")))
    ref = json.loads((BASE / "backtest/zuoce_jianlou_backtest.json").read_text(encoding="utf-8"))
    if ref.get("gate_pass") is False and str(ref.get("holdout_gate", {}).get("total")) == "不通过":
        ok("左侧捡漏 回测卡门禁：gate_pass=false / verdict=%s" % ref["holdout_gate"]["total"])
    else:
        bad("左侧捡漏 回测卡门禁与审计结论不符：%r / %r"
            % (ref.get("gate_pass"), ref.get("holdout_gate", {}).get("total")))
    st = json.loads((BASE / "backtest/sentinel_state.json").read_text(encoding="utf-8"))
    (ok if st.get("trading_enabled") is False else bad)(
        "热榜哨兵 影子账本 trading_enabled=false（status=%s）" % st.get("status"))


def run_all(html):
    check_d_nav_and_blocks(html)
    check_d_views(html)
    check_f_files()
    return len(oks), len(fails), list(fails)


print("=" * 78)
print("短线板块新增 2 子标签 · 内容归属 + 物理隔离校验（_verify_track_sep_0924.py）")
print("=" * 78)
if not HTML.exists():
    print("缺 %s（先跑 build_dual_system.py）" % HTML)
    sys.exit(1)
HTML_TXT = HTML.read_text(encoding="utf-8", errors="replace")

print("\n【正例】真实构建产物")
n_ok, n_fail, real_fails = run_all(HTML_TXT)

print("\n" + "=" * 78)
print("【负对照 1】把 sentinel_pool.js 注入 #sv-st-zuoce → 必须报「混入」")
print("=" * 78)
INJ = HTML_TXT.replace('id="own-zuoce_jianlou"',
                       'id="own-zuoce_jianlou" data-leak="sentinel_pool.js"', 1)
run_all(INJ)
neg1 = any("混入" in f for f in fails)
print("   -> 负对照 1：%s" % ("已检出" if neg1 else "漏检（校验器无鉴别力）"))

print("\n" + "=" * 78)
print("【负对照 2】把 st-sentinel 的 bt 块换成 st-zuoce 的 → 必须报「同文/非自有卡」")
print("=" * 78)
seg_z = slice_bt_sub(HTML_TXT, "st-zuoce")
i2 = HTML_TXT.find('data-bt-sub="st-sentinel"')
j2 = HTML_TXT.find('<div class="subview"', i2)   # 末块：切到子视图边界
assert j2 > i2 > 0, '负对照 2 注入失败：找不到边界（测试本身失效，必须先修）'
swapped = HTML_TXT[:i2] + seg_z + HTML_TXT[j2:]
assert swapped != HTML_TXT, '负对照 2 未改动输入（测试本身失效）'
run_all(swapped)
neg2 = (len(fails) > 0)   # 本质判据：篡改后的输入必须被校验器判为不合格
print("      注入后失败项 %d 条，示例：%s" % (len(fails), (fails[:3] or "无")))
print("   -> 负对照 2：%s" % ("已检出" if neg2 else "漏检（校验器无鉴别力）"))

print("")
print("=" * 78)
print("【负对照 3】合成「真实读取他策略文件」的源码 → 静态判据 ⑦ 必须检出")
print("=" * 78)
neg3 = _selftest_cross_reads()

print("\n" + "=" * 78)
print("结果：正例 %d 项通过 / %d 项失败；负对照 1 %s；负对照 2 %s；负对照 3 %s"
      % (n_ok, n_fail, "已检出" if neg1 else "漏检", "已检出" if neg2 else "漏检",
         "已检出" if neg3 else "漏检"))
if real_fails:
    print("失败项：")
    for f in real_fails:
        print("   - %s" % f)
print("=" * 78)
rc = 0 if (n_fail == 0 and neg1 and neg2 and neg3) else 1
print("VERIFY_RC=%d" % rc)
sys.exit(rc)
