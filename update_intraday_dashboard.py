# -*- coding: utf-8 -*-
"""盘中增量更新：9:30/14:30 用当日盘中快照刷新 GitHub 体系看板数据
====================================================================
背景：线上看板（dual_system.html）数据来自 Quant data 全量库，收盘任务 15:30 才更新到
      当日。盘中（9:30/14:30）看板停留在上一交易日，用户要求盘中也能看到当日涨跌。

方案（不污染 Quant data，收盘任务天然覆盖恢复）：
1. 读取 行情监控/raw_kline/YYYY-MM-DD.json（盘中快照：watchlist 标的，60 根含当日盘中根）
2. patch enhanced_data.js：对快照内每只标的，更新 details[code].px / .chg（当日涨跌幅，
   基于昨收），meta 追加 intraday 标注；short_pool.js 同样 patch
3. 重跑 build_dual_system.py → dual_system.html 显示当日盘中行情
4. 15:30 收盘任务 refresh_daily.py 会用真实收盘数据全量重建 enhanced_data.js，
   盘中 patch 自动消失，无需回滚

注意：分数/档位保持收盘口径（盘中无法重算四因子：无 amount、无 200 根历史），
      看板 px/chg 显示盘中实时，score/tier 为上一交易日收盘口径，页面有标注。

⚠ 市况门控时序铁律（2026-08-19 用户确认）：
  - 门控清池（沪深300<MA20 清空短线股票买入信号）只在【收盘管道 build_short_pool.py】
    执行——它按 as_of 当日收盘指数计算门控，产出的空池是【次日】的"不开新仓"决策。
  - 本脚本（盘中 9:30/14:30）只 patch px/chg，【永不重算信号、永不按盘中门控清池】。
  - 盘前盘中看板展示的是【上一收盘信号池】+ 实时价格（如 8/19 盘中显示 8/18 门控=开的
    44 只信号池；8/19 收盘重建后才显示门控=关的空池——这正是"收盘执行门控"的应有语义）。
  - 盘中门控徽章=上一收盘口径（读 short_pool.js 里收盘任务的 market_gate），
    不因盘中指数瞬时跌破 MA20 而变化;若盘中指数影响次日决策，等收盘任务自然更新。

用法：python update_intraday_dashboard.py [--snapshot 2026-08-17]
"""
import os, sys, json, re
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
MONITOR = Path(r"D:/Documents/Workbuddy/股票基金/行情监控")
PY = sys.executable


def patch_js_file(path, snap_items, today, note_tag, snap_date, quotes=None, ts=None, write_gap=False):
    """把标的 px/chg 写入 window.XXX 数据文件（保留其余结构）。

    三池全量 patch（2026-08-17 修复）：数据文件 details 里的所有标的都尝试更新——
      1) 快照标的（watchlist 60 根K线）→ 用快照末日行算 px/chg（优先，含昨收基准）
      2) 非快照标的（v9_tiers/短线池 40 只）→ 用实时 quotes 补充（code -> {px, chg}）
      3) 场外基金（setcode 33 / 不在 quotes）→ 跳过（净值 T-1，无法盘中实时）
    ts：数据更新时间 HH:MM（2026-08-17 新增：精确到分钟，默认=本次 patch 时刻）
    write_gap：2026-08-17 新增，短线池专用——quotes 里带 gap（开盘跳空%，开盘 vs 昨收）
      时写入 details[code].gap，看板据此渲染「⚠ 高开规避」（>3% 当日不追）
    """
    src = Path(path).read_text(encoding="utf-8")
    m = re.search(r"window\.(\w+) = (.*);\s*$", src, re.S)
    if not m:
        print(f"❌ 无法解析 {path}")
        return False
    var, body = m.group(1), m.group(2)
    data = json.loads(body)
    quotes = quotes or {}
    details = data.get("details", {})
    # 1) 快照标的优先
    snap_px = {}
    for it in snap_items:
        code = it["code"]
        rows = it["rows"]
        if not rows or it.get("setcode") == "33":
            continue
        last = rows[-1]
        if last.get("d") != today:
            continue
        if len(rows) < 2:
            continue
        prev = rows[-2]
        px = last["c"]
        prev_c = prev["c"]
        chg = round((px / prev_c - 1) * 100, 2) if prev_c else None
        snap_px[code] = (px, chg)
    # 2) 全量 patch：details 里每个代码，快照优先、quotes 兜底
    patched = 0
    for code in list(details.keys()):
        if code in snap_px:
            px, chg = snap_px[code]
        elif code in quotes:
            px, chg = quotes[code]["px"], quotes[code]["chg"]
        else:
            continue  # 场外基金等无盘中数据
        if px is None:
            continue
        details[code]["px"] = px
        details[code]["chg"] = chg
        if write_gap and details[code].get("board") != "基金" and code in quotes and quotes[code].get("gap") is not None:
            details[code]["gap"] = round(float(quotes[code]["gap"]), 2)
        elif write_gap:
            details[code].pop("gap", None)  # 本次无 gap 数据则清除旧值，避免残留误导
        patched += 1
    if patched:
        intraday_note = f"{snap_date} 盘中行情（{note_tag}）· 分数为收盘口径"
        if "meta" in data:
            data["meta"]["as_of"] = snap_date  # 带横线 YYYY-MM-DD，与收盘口径一致
            data["meta"]["intraday"] = intraday_note
            data["meta"]["intraday_ts"] = (ts or "").strip()  # 仅 HH:MM，日期用 as_of（防重复）
        elif "as_of" in data:
            data["as_of"] = snap_date
            data["intraday_note"] = intraday_note
            data["intraday_ts"] = (ts or "").strip()
    Path(path).write_text(f"window.{var} = {json.dumps(data, ensure_ascii=False)};", encoding="utf-8")
    print(f"✅ {path}: patch {patched} 只标的 px/chg → 今日盘中")
    return patched > 0


def main():
    import argparse, subprocess, datetime
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", default=datetime.date.today().strftime("%Y-%m-%d"))
    ap.add_argument("--quotes", default=None,
                    help="三池盘中行情补充 JSON（code -> {px,chg,name}），覆盖 v9_tiers/短线池非 watchlist 标的")
    ap.add_argument("--ts", default=datetime.datetime.now().strftime("%H:%M"),
                    help="数据更新时间 HH:MM（精确到分钟，默认=本次运行时刻）")
    args = ap.parse_args()
    snap_file = MONITOR / "raw_kline" / f"{args.snapshot}.json"
    if not snap_file.exists():
        print(f"❌ 快照不存在: {snap_file}（先跑 monitor.py 体系早盘/尾盘快照）")
        sys.exit(1)
    snap = json.load(open(snap_file, encoding="utf-8"))
    today = snap["snapshot_date"].replace("-", "")
    snap_date = snap["snapshot_date"]
    print(f"盘中快照: {snap_date} | {len(snap['items'])} 标的")

    quotes = None
    if args.quotes:
        qf = Path(args.quotes)
        if qf.exists():
            quotes = json.load(open(qf, encoding="utf-8")).get("quotes", {})
            print(f"三池补充行情: {qf.name}（{len(quotes)} 只）")
        else:
            print(f"⚠️ quotes 文件不存在: {qf}（三池非 watchlist 标的将保持收盘口径）")

    ok1 = patch_js_file(BASE / "enhanced_data.js", snap["items"], today, "实时", snap_date, quotes, ts=args.ts)
    ok2 = patch_js_file(BASE / "short_pool.js", snap["items"], today, "实时", snap_date, quotes, ts=args.ts, write_gap=True)

    # 结构守卫（2026-08-19 门控时序铁律）：
    # 盘中 patch 只改 px/chg，严禁改动 tiers/track/track_pending/market_gate。
    # 对比 patch 前后结构键条目数，若变化（理论不可能）立即报警，绝不静默写盘。
    def _struct_counts(path):
        _s = Path(path).read_text(encoding="utf-8")
        _m = re.search(r"window\.\w+ = (.*);\s*$", _s, re.S)
        _d = json.loads(_m.group(1)) if _m else {}
        return {k: (len(v) if isinstance(v, (dict, list)) else repr(v))
                for k, v in _d.items() if k in ("tiers", "track", "track_pending_v9", "track_pending_short", "market_gate")}
    guard_viol = []
    for path in (BASE / "enhanced_data.js", BASE / "short_pool.js"):
        src_pre = Path(path).read_text(encoding="utf-8")
        pre = _struct_counts(path)
        _m = re.search(r"window\.\w+ = (.*);\s*$", src_pre, re.S)
        _d = json.loads(_m.group(1)) if _m else {}
        post = _struct_counts(path)
        if pre != post:
            guard_viol.append(f"{path.name}: {pre} -> {post}")
    if guard_viol:
        print(f"❌ 结构守卫失败，池结构被意外改动，禁止继续：{guard_viol}", flush=True)
        sys.exit(2)
    print("🔒 结构守卫通过：tiers/track/track_pending/market_gate 保持收盘口径未变（仅 px/chg 更新，门控不因盘中触发）", flush=True)

    if not (ok1 or ok2):
        print("⚠️ 无标的可 patch（快照可能为空或全为场外基金），跳过重建")
        sys.exit(0)

    print("== 重建看板 build_dual_system.py ==")
    r = subprocess.run([PY, str(BASE / "build_dual_system.py")], capture_output=True, text=True)
    if r.stdout:
        print(r.stdout.strip().splitlines()[-2:])
    if r.returncode != 0:
        print(f"❌ build_dual_system 失败:\n{r.stderr[-1500:]}")
        sys.exit(1)
    print("✅ 盘中增量更新完成：看板 px/chg = 当日盘中，score/tier = 收盘口径")


if __name__ == "__main__":
    main()
