# -*- coding: utf-8 -*-
"""跟踪池按策略独立（R-track-sep-0923）—— 静态断言（只读 dual_system.html + 各策略源文件）

断言：
  A）5 张卡各存在且唯一，页面级共享卡已删除；4 张构建期卡在各自子视图内
  B）每张卡的代码集合 ⊆ **该策略自有数据源**的代码集合（白名单）
  C）跨策略 0 混入：每张卡 ∩（其它策略**独占**代码） = ∅
  D）反例（负对照）：把外策略代码塞进某张卡 → 检查器必须报错（证明判据有牙）
  E）st-stk（JS 渲染）代码只来自 SHORT_POOL.track / track_pending_short
  F）st-fund 无自有账本 → 渲染「暂无跟踪数据」+ 缺字段清单（不编造数据）

用法: python _verify_track_sep_0923.py
"""
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
HTML = (BASE / "dual_system.html").read_text(encoding="utf-8")
FAILS = []

# 6 臂账本文件名与 build_dual_system.QLCH_TRACKS 同源（构建脚本是脚本性质、不可 import）
QLCH_STATES = ["qlch_paper_state_b4_k3.json", "qlch_paper_state_b4_k3_mb.json",
               "qlch_paper_state.json", "qlch_paper_state_b4_k3_gate60.json",
               "qlch_paper_state_b4_k3_combo.json", "qlch_paper_state_b4.json"]
KH_STATES = ["khunter_paper_state.json", "khunter_paper_state_c.json"]
ETF_STATES = ["etf_paper_state.json"]
STATE_DIRS = ("", "dist", "backtest")


def load_state(name):
    for d in STATE_DIRS:
        p = (BASE / d / name) if d else (BASE / name)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None


def codes_of_state(d):
    """状态文件里的代码集合（positions / pending_* / trades / to 字典）。"""
    out = set()
    if not isinstance(d, dict):
        return out
    for key in ("positions", "trades", "pending_buys", "pending_sells", "hold_over_codes"):
        for it in (d.get(key) or []):
            if isinstance(it, dict) and it.get("code"):
                out.add(str(it["code"]))
            elif isinstance(it, str):
                out.add(it)
    _pend = d.get("pending")
    if isinstance(_pend, dict):
        out |= set(_pend)

    def _scan_trades():
        for t in (d.get("trades") or []):
            if isinstance(t, dict) and isinstance(t.get("to"), dict):
                out.update(t["to"].keys())
    _scan_trades()
    for key in ("positions", "trades"):
        for it in (d.get(key) or []):
            if isinstance(it, dict) and isinstance(it.get("to"), dict):
                out.update(it["to"].keys())
    return out


def whitelists():
    """各策略自有数据源的代码集合（白名单）+ 数据源文件说明。"""
    wl, src = {}, {}

    q = set()
    for f in QLCH_STATES:
        d = load_state(f)
        if d:
            q |= codes_of_state(d)
    wl["st-qlch"] = q
    src["st-qlch"] = "backtest/qlch_paper_state*.json ×6（positions + trades）"

    k = set()
    for f in KH_STATES:
        d = load_state(f)
        if d:
            k |= codes_of_state(d)
    wl["st-kh"] = k
    src["st-kh"] = "khunter_paper_state.json + khunter_paper_state_c.json（positions/pending/trades）"

    e = set()
    for f in ETF_STATES:
        d = load_state(f)
        if d:
            e |= codes_of_state(d)
    wl["st-etf"] = e
    src["st-etf"] = "etf_paper_state.json（positions/pending/trades.to）"

    sp = json.loads((BASE / "short_pool.json").read_text(encoding="utf-8"))
    wl["st-stk"] = set(sp.get("track") or {}) | set(sp.get("track_pending_short") or {})
    src["st-stk"] = "short_pool.json（track + track_pending_short；JS 渲染）"

    wl["st-fund"] = set()
    src["st-fund"] = "（无独立 paper/持仓状态：backtest/fund_paper.json 属中线 FB3 基金主仓，非本策略）"
    return {k: {c for c in v if c} for k, v in wl.items()}, src


KEYS = ["st-stk", "st-qlch", "st-kh", "st-etf", "st-fund"]


def card_slices(html):
    """按出现顺序切出 5 张卡的 HTML 片段。"""
    idx = {}
    for k in KEYS:
        m = re.search(r'id="watch-card-%s"' % re.escape(k), html)
def card_slices(html):
    """按出现顺序切出 5 张卡的 HTML 片段（右界 = 下一个 card/subview/view/注释，避免串到邻卡）。"""
    bounds = ['<div class="card', '<div class="subview', '<div class="view"', '<!--']
    idx = {}
    for k in KEYS:
        m = re.search(r'id="watch-card-%s"' % re.escape(k), html)
        idx[k] = m.start() if m else -1
    order = sorted([k for k in KEYS if idx[k] >= 0], key=lambda k: idx[k])
    out = {}
    for k in order:
        s = idx[k]
        ends = [html.find(b, s + 10) for b in bounds]
        ends = [e for e in ends if e > s]
        out[k] = html[s:(min(ends) if ends else len(html))]
    return out
def card_codes(frag):
    """卡内代码集合：优先 data-code，其次 6 位裸码文本。"""
    out = {m.group(1) for m in re.finditer(r'data-code="([^"]+)"', frag)}
    if not out:
        out = {m.group(1) for m in re.finditer(r">(\d{6})<", frag)}
    return {c for c in out if c}


def check(html, wl):
    """核心判据：返回失败列表（也能被负对照调用）。"""
    fails = []
    sl = card_slices(html)
    all_wl = set().union(*wl.values()) if wl else set()
    for k in KEYS:
        if k not in sl:
            fails.append("卡 %s 不存在" % k)
            continue
        codes = card_codes(sl[k])
        own = {c for c in codes if c in wl[k]}
        bad_sub = codes - wl[k]
        if bad_sub:
            fails.append("卡 %s 含非自有代码 %s（白名单外）" % (k, sorted(bad_sub)[:5]))
        foreign = all_wl - wl[k]
        hit = {c for c in codes if c in foreign}
        if hit:
            fails.append("卡 %s 混入外策略代码 %s" % (k, sorted(hit)[:5]))
        print("     %-8s 卡内 %2d 码 ｜ 自有白名单 %3d 码 ｜ ⊆ 自有 %s ｜ 跨策略混入 %d"
              % (k, len(codes), len(wl[k]), "✓" if not bad_sub else "✗", len(hit)))
    return fails


def main():
    """跑全部静态断言（可被别的验收脚本 import 而不触发执行）。"""
    global FAILS
    FAILS = []
    wl, SRC = whitelists()
    print("① 各策略自有数据源（白名单规模）")
    for k in KEYS:
        print("   %-8s %3d 码 ｜ %s" % (k, len(wl[k]), SRC[k]))

        print("   %-8s %3d 码 ｜ %s" % (k, len(wl[k]), SRC[k]))

    print("\n② 卡存在性 / 页面级共享卡已删除")
    sl = card_slices(HTML)
    for k in KEYS:
        ok = k in sl and HTML.count('id="watch-card-%s"' % k) == 1
        print("   [%s] #watch-card-%s 存在且唯一" % ("ok" if ok else "FAIL", k))
        if not ok:
            FAILS.append("卡 %s 缺失/重复" % k)
    _shared = re.search(r'id="watch-card"', HTML)
    if _shared:
        FAILS.append("页面级共享卡 #watch-card 仍存在")
    print("   [%s] 页面级共享卡 #watch-card 已删除" % ("FAIL" if _shared else "ok"))

    print("\n③ 每卡代码集合 ⊆ 自有白名单 + 跨策略 0 混入")
    f1 = check(HTML, wl)
    FAILS += f1
    print("   [%s] 静态判据（真实产物）" % ("ok" if not f1 else "FAIL"))


    print("\n⑦ 每张卡都挂在自己的子视图内（spec：5 个子视图内部各挂一张）")
    for k in KEYS:
        s0 = HTML.find('id="sv-%s"' % k)
        s1 = HTML.find('id="sv-', s0 + 5)
        s1 = s1 if s1 > 0 else HTML.find('<div class="view"', s0)
        c0 = HTML.find('id="watch-card-%s"' % k)
        ok = s0 >= 0 and s0 < c0 < s1
        print("   [%s] #watch-card-%s ∈ #sv-%s" % ("ok" if ok else "FAIL", k, k))
        if not ok:
            FAILS.append("卡 %s 不在其子视图 sv-%s 内" % (k, k))
    print("\n④ 反例（负对照）：把外策略代码 sh518880 塞进 st-qlch 卡 → 检查器必须报错")
    _f = sl["st-qlch"]
    _f2 = re.sub(r'data-code="[^"]+"', 'data-code="sh518880"', _f, count=1)
    mut = HTML.replace(_f, _f2, 1)
    print('   （注入后 st-qlch 卡首行 → data-code="sh518880"；st-etf 白名单含 sh518880，st-qlch 白名单不含）')
    f2 = check(mut, wl)
    _ok = any("st-qlch" in x for x in f2)
    print("   [%s] 负对照被检出：%s" % ("ok" if _ok else "FAIL", [x for x in f2 if "st-qlch" in x][:1]))
    if not _ok:
        FAILS.append("负对照未检出（判据无牙）")

    print("\n⑤ st-stk（JS 渲染）数据源检查：只读 SHORT_POOL.track / track_pending_short")
    js = HTML[HTML.index("function renderWatchFor(k)"):HTML.index("function renderKhHits()")]
    for pat, ok in (("window.SHORT_POOL&&window.SHORT_POOL.track", True),
                    ("track_pending_short", True),
                    ("window.QLCH", False), ("window.ENH", False), ("KH_SNAP", False)):
        hit = pat in js
        print("   [%s] %s %s" % ("ok" if hit == ok else "FAIL", "含" if ok else "不含", pat))
        if hit != ok:
            FAILS.append("st-stk JS 数据源异常：%s" % pat)

    print("\n⑥ st-fund 无自有账本 → 空态 + 缺字段清单（不编造）")
    frag = sl.get("st-fund", "")
    ok = ("暂无跟踪数据" in frag) and ("缺字段清单" in frag) and ("entry_px" in frag)
    print("   [%s] 渲染「暂无跟踪数据」+ 缺字段清单" % ("ok" if ok else "FAIL"))
    if not ok:
        FAILS.append("st-fund 空态/缺字段清单缺失")

    print("\n===== 结果：%d 项失败 =====" % len(FAILS))
    for f in FAILS:
        print("  FAIL", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
