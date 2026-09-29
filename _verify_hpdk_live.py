# -*- coding: utf-8 -*-
"""_verify_hpdk_live.py — 「缩量超跌」（原名「横盘低开·两日」）子标签的静态校验器（对齐 _verify_qlch_live.py 范式）。

覆盖契约里的四条机械判据：
  A8  看板渲染：子标签容器 / 子导航项 / 操作必需列齐全 / data-code + data-search / th[data-key]
                / 搜索框 + 板块筛选 / 计数 span
  A9  盘中实时：新表是 table.tbl（主盘中层靠 `querySelectorAll('table.tbl')` 自动认行取码）
                / 盘中钩子存在且被主盘中层调用 / **零落盘**（无 fetch、无 XHR、不写任何 json）
  A12 隔离证明：本模块只读该策略自有产物；**其它策略的数据产物相对 git HEAD 零改动**
  A11 口径漂移防护：候选生成器与冻结 oos_run.py 的逐位对拍记录写进候选产物

用法: python _verify_hpdk_live.py [--html dual_system.html] [--repo .]
失败即非零退出。
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

FAIL = []


def chk(ok, name, detail=""):
    print("  %s %-58s %s" % ("OK " if ok else "FAIL", name, detail))
    if not ok:
        FAIL.append(name)


def read(p):
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default="dual_system.html")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args()
    R = pathlib.Path(a.repo).resolve()
    html_p = R / a.html
    html = read(html_p)
    src_build = read(R / "build_dual_system.py")
    src_card = read(R / "hpdk_card.py")
    src_live = read(R / "intraday_live.py")
    cand = {}
    fp = R / "backtest/hpdk_candidates.json"
    if fp.exists():
        try:
            cand = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            cand = {}

    print("=" * 100)
    print("A8 看板渲染")
    chk('id="sv-st-hpdk"' in html, "5.1 子视图容器 id=sv-st-hpdk")
    chk(">缩量超跌<" in html, "5.2 子导航项文案「缩量超跌」")
    chk('data-bt-sub="st-hpdk"' in html, "5.3 回测参考子块 data-bt-sub=st-hpdk")
    chk('id="tbl-hpdk-cand"' in html, "5.4 明日买点表 tbl-hpdk-cand")
    heads = re.findall(r'<th[^>]*>([^<]*)</th>', html)
    need = ["标的", "状态", "板块", "行业", "现价", "涨跌幅", "买入价", "止盈价", "卖出时点", "建议股数", "单票可买"]
    for nm in need:
        chk(any(nm in h for h in heads), "5.5 表头含「%s」" % nm)
    t_idx = html.find('id="tbl-hpdk-cand"')
    seg = html[t_idx:t_idx + 400000] if t_idx >= 0 else ""
    chk('id="sv-st-hpdk"' in html, "5.1 子视图容器 id=sv-st-hpdk")
    chk('data-code=' in seg, "5.6 行属性 data-code（盘中层认行）")
    chk('data-search=' in seg, "5.7 行属性 data-search（搜索用）")
    chk('data-tier=' in seg, "5.8 行属性 data-tier（板块筛选）")
    chk('id="tbl-hpdk-cand-q"' in html, "5.9 搜索框 tbl-hpdk-cand-q")
    chk('id="tbl-hpdk-cand-tier"' in html, "5.10 筛选控件 tbl-hpdk-cand-tier")
    chk('id="tbl-hpdk-cand-count"' in html, "5.11 计数 span tbl-hpdk-cand-count")
    chk('class="tbl" id="tbl-hpdk-cand"' in html or 'id="tbl-hpdk-cand" style' in html,
        "5.12 表带 class=tbl（板内通用排序/搜索/筛选自动接管）")
    chk('id="hpdk-oos-card"' in html, "5.13 前向 OOS 进度卡")
    chk('id="hpdk-card"' in html, "5.14 策略主卡")
    chk('id="hpdk-paper-card"' in html, "5.14b 模拟盘卡")
    chk('id="hpdk-track-card"' in html, "5.14c 跟踪池卡")
    chk('id="tbl-hpdk-track"' in html and 'id="tbl-hpdk-track-q"' in html
        and 'id="tbl-hpdk-track-tier"' in html, "5.14d 跟踪池表 + 搜索 + 状态筛选")
    _pk = R / "backtest/hpdk_paper.json"
    chk(_pk.exists(), "5.14e 模拟盘产物在盘")
    if _pk.exists():
        import json as _j
        _d = _j.loads(_pk.read_text(encoding="utf-8"))
        chk(bool(_d.get("config")) and "account" in _d and "track" in _d,
            "5.14f 产物含 config/account/track")
        chk((_d.get("reconcile") or {}).get("mismatches") == [],
            "5.14g 模拟盘与冻结台账零不一致",
            str(len((_d.get("reconcile") or {}).get("mismatches") or [])))
    chk("window.HPDK = " in html and 'window.HPDK = null' not in html,
        "5.15 内嵌 window.HPDK payload")
    chk('"gap_lo"' in html and '"buy_date"' in html, "5.16 payload 含 gap_lo / buy_date")

    print("-" * 100)
    print("A9 盘中实时 + 零落盘")
    chk("HPDK_JS" in src_live, "6.1 intraday_live.py 定义 HPDK_JS")
    chk(re.search(r"HPDK_ON_QUOTES\s*=", src_live) is not None, "6.2 导出 HPDK_ON_QUOTES 钩子")
    m = re.search(r'<script>\{HPDK_JS\}</script>', src_build)
    chk(m is not None, "6.3 build_dual_system.py 注入 {HPDK_JS}")
    hjs = ""
    if "HPDK_JS" in src_live:
        i = src_live.find("HPDK_JS = ")
        if i >= 0:
            j = src_live.find('"""', src_live.find('"""', i) + 3)
            hjs = src_live[i:j if j > i else i + 60000]
    chk(len(hjs) > 1000, "6.4 HPDK_JS 块已取到", "len=%d" % len(hjs))
    for bad in ("oos_trades", "oos_state", "hpdk_candidates.json", "hpdk_oos_view.json"):
        chk(bad not in hjs, "6.6 零落盘：HPDK_JS 不碰 %s" % bad)
    chk('.json"' not in hjs and ".json'" not in hjs, "6.6 零落盘：HPDK_JS 不引用任何 .json 文件")
    chk(".removeChild(" in hjs or "remove()" in hjs,
        "6.7 剔除是「移除行」而非仅置灰（含 DOM 移除调用）")

    print("-" * 100)
    print("A12 隔离证明")
    # 本策略自有产物（唯一真值源；2026-09-28 命中区块 / 09-29 历史档+批次跟踪 三次扩展都在这里改）
    OWN_FILES = ["hpdk_candidates.json", "hpdk_oos_view.json", "hpdk_paper.json",
                 "hpdk_bt_ref.json", "hpdk_hits.json", "hpdk_hits_history.jsonl",
                 "hpdk_cohorts.json"]
    own = {"backtest/" + f for f in OWN_FILES}
    reads = set(re.findall(r'"[^"]*backtest"\s*/\s*"([^"]+)"', src_card)) | \
            set(re.findall(r'[^/]*"backtest"\s*/\s*"([A-Za-z0-9_\-]+\.(?:jsonl|json|js|csv))"', src_card)) | \
            set(re.findall(r'backtest/([A-Za-z0-9_\-]+\.(?:jsonl|json|js|csv))', src_card))
    cross = sorted(reads - set(OWN_FILES))
    chk(not cross, "7.1 hpdk_card.py 只读本策略自有产物",
        "越界=%s" % cross if cross else "own=%s" % OWN_FILES)
    OTHER = ["backtest/qlch_candidates.json", "backtest/qlch_paper_state.json",
             "backtest/qlch_paper_state_b4_k3.json", "backtest/qlch_paper_state_b4_k3_mb.json",
             "backtest/qlch_bt_t1exit_0922.json", "backtest/qlch_bt_ref.json",
             "backtest/sentinel_backtest.json", "backtest/etf_bt_ref.json",
             "short_pool.json", "short_signals.js", "enhanced_data.js", "a5_pool.js",
             "market_breadth.js", "market_weather.js", "kxmm_data.js"]
    try:
        out = subprocess.run(["git", "diff", "--name-only", "HEAD", "--"] + OTHER,
                             cwd=str(R), capture_output=True, text=True, timeout=120)
        dirty = [x for x in (out.stdout or "").splitlines() if x.strip()]
        chk(not dirty, "7.2 其它策略数据产物相对 git HEAD 零改动",
            "被改动=%s" % dirty if dirty else "共 %d 个受保护文件" % len(OTHER))
    except Exception as e:
        chk(False, "7.2 其它策略数据产物相对 git HEAD 零改动", "git 执行失败 %r" % (e,))
    # 7.3 实盘登记区块（R-hpdk-real-0929）：存在性 + 隔离（零落盘/不出本机）+ 口径
    chk(('id="tbl-hpdk-real"' in html) and ("window.HPDK_REAL" in html) and ("hpdk-real-add" in html),
        "7.3 实盘登记区块已渲染（表单 + 表 + HPDK_REAL）")
    chk(("quant_hpdk_real_v1" in html) and ("localStorage" in html),
        "7.3b 实盘数据仅 localStorage（零落盘 / 不上传）")
    _realjs = html[html.find('var LS="quant_hpdk_real_v1"'):][:6000] if ('var LS="quant_hpdk_real_v1"' in html) else ""
    chk(("fetch(" not in _realjs) and ("XMLHttpRequest" not in _realjs),
        "7.3c 实盘区块 JS 无 fetch/XHR（数据不出本机）")
    chk("CAL[i+1]" in html, "7.3d 了结日 = 买日 + 1 交易日（冻结口径）")
    chk("index_000300.csv" in src_card,
        "7.3e 唯一跨件读取 = index_000300.csv（共享交易日历，全站同源）")

    print("-" * 100)
    print("A11 口径漂移防护（对拍记录）")
    a11 = (cand.get("a11_check") or {})
    chk(a11.get("days_compared", 0) >= 20, "8.1 对拍覆盖 ≥20 个交易日",
        "days=%s" % a11.get("days_compared"))
    chk(a11.get("days_bitwise_equal") == a11.get("days_compared") and a11.get("days_compared"),
        "8.2 对拍逐位全等", "%s/%s" % (a11.get("days_bitwise_equal"), a11.get("days_compared")))
    chk(bool(cand.get("frozen_sha256")), "8.3 候选产物带冻结脚本 SHA",
        (cand.get("frozen_sha256") or "")[:16])
    src_oos = read(R / "backtest/hengpan_fangliang_dikai_0925/oos_run.py")
    chk("SHADOW_START" in src_oos and "MINPX=3.0" in src_oos, "8.4 冻结脚本常量在位")

    print("=" * 100)
    if FAIL:
        print("HAS FAILURES  共 %d 项失败：" % len(FAIL))
        for x in FAIL:
            print("   - " + x)
        sys.exit(1)
    print("ALL PASS  全部静态断言通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
