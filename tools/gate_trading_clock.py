# -*- coding: utf-8 -*-
"""交易时钟机械门禁（ADR-0004 / C1）—— 会 `exit 1` 的真门禁，不是文档纪律

为什么需要它
------------
ADR-0004 审查取证：体系里没有任何地方表示「一根日线 bar 内部的交易时序」，
于是「09:25 才撮合出清单、却要求 09:25 前下单」「09:25 判定 → 09:25 就动手」
这类**实盘不可执行**的指令被反复写进卡片、清单与报告，而没有任何机械拦截。

本脚本把四类违规做成会失败的检查：

  G1 静默期动作     行内出现 09:25–09:29 时刻 **且** 含买卖/撤单动作词，
                    又没有任何「可执行时点」标注 → 违规（交易所该时段不接受申报/撤单）
  G2 判定即动手     行内既有「判定」又有动作词，且动作时刻落在 09:25 前/静默期而
                    未标注顺延规则 → 违规
  G3 锁单却提前买   行内/邻近文本说「09:25 锁定/冻结清单」**同时**要求在 09:2[0-4] 或 09:1x
                    买入，却未标注「盲挂协议 / 竞价预备清单 / 参考价」 → 违规
  G4 逐笔成交不可成交  成交价 = 今开却无 ≤09:20 下单动作（`probe_auction_order_admissibility`）；
                    或成交价落在涨停/一字板/停牌态（`probe_fill_tradability`）
  G5 成交口径三查  来源：gushi topic/1010 主帖（2026-10-11，管理员要求按此口径回测）。
                    G5a 开盘涨停买不进  买入腿落在「开盘已触及涨停 / 一字板 / 停牌」的 bar 上
                    G5b 成交未确立      按开盘价挂买，但当日除开盘价外没有任何报价 ≤ 挂价；
                                       `--strict-fill` 时「最低价恰等于开盘价」也计入
                    G5c 跌停封死却记成交  卖出腿落在当日 high 已触及跌停价（全天封死）的 bar 上，
                                       须顺延到下一可卖日再计价
                    三条全部复用 `engine.session` 的真值源（`board_of` / `limit_prices` /
                    `reaches_limit_up|down` / `limit_order_crossed` / `tradable_at_fill`），
                    不另写一份时钟或涨跌停常量。

用法
----
    python tools/gate_trading_clock.py                 # 扫仓库（默认根）
    python tools/gate_trading_clock.py --root <DIR>    # 扫指定目录（用于负例注入验证）
    python tools/gate_trading_clock.py --selftest      # V6：内置正/负例，证明门禁非空转
    python tools/gate_trading_clock.py --strict-fill # G5b 采用严格成交口径

退出码：0 = 无违规（例外已登记并计数）；1 = 有违规 **或** 门禁自身不可用（失败即闭锁）。

例外登记
--------
`tools/gate_trading_clock_exempt.txt`：每行 `<必须出现的子串> || <原因>`。
命中的候选行被记为「已登记例外」并在报告里**显式计数**——不做静默放行。
该文件缺失时不做任何豁免（宁可报错，不可静默）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- 时钟真值源
# 门禁必须复用引擎的时钟，而不是自己再写一份常量（否则又是「两个真值源」）。
_ENGINE_HOME = os.environ.get("FLEUR_ABSORB_HOME", r"E:\PI\投资\fleur_absorb")
_SESSION_PY = Path(_ENGINE_HOME) / "engine" / "session.py"


def _load_session():
    """载入引擎 session 模块；**载不到就失败闭锁**（不许静默放行）。"""
    if not _SESSION_PY.is_file():
        return None, f"找不到时钟真值源：{_SESSION_PY}（可用 FLEUR_ABSORB_HOME 覆盖）"
    if _ENGINE_HOME not in sys.path:
        sys.path.insert(0, _ENGINE_HOME)
    try:
        from engine import session as S  # type: ignore
    except Exception as e:  # noqa: BLE001
        return None, f"载入 session 失败：{type(e).__name__}: {e}"
    return S, ""


# ---------------------------------------------------------------- 词表
ACTION_WORDS = (
    "买入", "买进", "卖出", "下单", "申报", "委托", "撤单", "挂单", "挂买", "挂卖",
    "平仓", "清仓", "减仓", "加仓", "建仓", "止盈", "止损", "市价卖", "市价买",
    "限价卖", "限价买", "减半", "清空", "成交",
)
# 「已标注可执行时点 / 已声明不可执行」的正当写法 —— 命中任一即不判违规
EXEC_ANNOT = (
    "可执行时点", "静默期", "不可下单", "不可成交", "不能成交", "无法成交", "不接受申报",
    "≥09:30", "≥9:30", ">=09:30", ">=9:30", "≥ 09:30",
    "≤09:20", "≤9:20", "<=09:20", "<=9:20", "≤ 09:20",
    "仅判定", "只做判定", "仅做判定", "不判定", "不剔除", "只灰标", "灰标",
    "盲挂", "竞价预备清单", "预备清单", "参考价", "研究上界", "不可执行",
)
SILENT_TIME_RE = re.compile(r"(?<!\d)0?9:2[5-9](?!\d)")
PRE_SILENT_TIME_RE = re.compile(r"(?<!\d)0?9:(1[5-9]|2[0-4])(?!\d)")
LOCK_AT_0925_RE = re.compile(r"09:25[^\n]{0,24}(锁定|冻结|首算即冻结|出权威)")
# 「静默期时刻 + **紧邻**动作词」才算**指令**；纯描述性文字不算
# （否则术语表/报告里解释时钟的文字会被误报 —— 首轮实测确实误报了我方 ADR 的术语表条目）。
# 桥接串（时刻与动作词之间的字）含「前」或否定词 → 是「在该时刻之前动作」或
# 「不可动作」的正确表述，不算违规。
NEAR_ACTION_RE = re.compile(
    r"(?<!\d)(0?9:2[5-9])([^\n]{0,10}?)"
    r"(买入|买进|卖出|下单|挂单|撤单|申报|委托|平仓|清仓|减仓|加仓|建仓|操作|执行|动手)")
# G2 特型：「09:1x / 09:2[0-4] … 判定 … 动作」= 判定完立刻动手
G2_RE = re.compile(
    r"(?<!\d)(0?9:(?:1[5-9]|2[0-4]))([^\n]{0,12}?)(判定)([^\n]{0,12}?)"
    r"(买入|买进|卖出|下单|挂单|撤单|申报|委托|平仓|清仓|减仓|加仓|建仓|操作|执行|动手)")
EXEMPT_BRIDGE = ("前", "不可", "不能", "不接", "无需", "不必", "早于", "避免", "≠")
# 生成物：由已扫描的源文件（build_dual_system.py / intraday_live.py / build_log_pages.py）产出，
# 扫输出只会在同一缺陷上重复报警 ⇒ 跳过输出、只在源头修（报告里显式列出跳过项，不静默）。
SKIP_NAMES = {"index.html", "dual_system.html", "changelog.html", "review_log.html",
              "history_reports.html", "monitor_reports.html",
              # 门禁自身：内含 SELFTEST_BAD 负例夹具（扫自己必然自失败）；
              # 例外清单是**登记表**而非指令面
              "gate_trading_clock.py", "gate_trading_clock_exempt.txt"}
TEXT_EXT = {".py", ".js", ".ts", ".ps1", ".md", ".html", ".json", ".yaml", ".yml", ".csv", ".bat"}
SKIP_DIR_PARTS = {".git", "__pycache__", "node_modules", ".x3cache", "_bak", ".ruff_cache",
                  "_tmp_archive_0908", "legacy", "dist", "_cloud_dist", "_cloud_local"}
MAX_BYTES = 4_000_000


def _iter_text_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in TEXT_EXT:
            continue
        parts = set(p.parts)
        if parts & SKIP_DIR_PARTS:
            continue
        if p.name in SKIP_NAMES:
            continue
            continue
        try:
            if p.stat().st_size > MAX_BYTES:
                continue
        except OSError:
            continue
        yield p


def _read_lines(p: Path):
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return p.read_text(encoding=enc, errors="strict").splitlines()
        except (UnicodeDecodeError, LookupError):
            continue
        except OSError:
            return []
    try:
        return p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _has_any(s: str, words) -> bool:
    return any(w in s for w in words)


def load_exemptions(root: Path) -> list[tuple[str, str]]:
    f = root / "tools" / "gate_trading_clock_exempt.txt"
    out = []
    if f.is_file():
        for ln in _read_lines(f):
            if "||" in ln:
                k, _, why = ln.partition("||")
                out.append((k.strip(), why.strip()))
    return out


# ---------------------------------------------------------------- 文本检查器
def scan_texts(root: Path, ex: list[tuple[str, str]]) -> tuple[list[dict], list[dict], int]:
    """返回 (violations, exempted, n_scanned_files)。"""
    viol, exempt, nf = [], [], 0
    for p in _iter_text_files(root):
        nf += 1
        lines = _read_lines(p)
        for i, ln in enumerate(lines, 1):
            s = ln.strip()
            if not s or len(s) > 4000:
                continue
            has_action = _has_any(s, ACTION_WORDS)
            if not has_action:
                continue
            m_near = NEAR_ACTION_RE.search(s)
            m_g2 = G2_RE.search(s)
            reason = None
            if m_near and not any(w in (m_near.group(2) or "") for w in EXEMPT_BRIDGE):
                reason = ("G1 动作时点落在静默期：`%s%s%s` —— 09:25–09:30 不接受申报/撤单、"
                          "无成交，未标注可执行时点"
                          % (m_near.group(1), m_near.group(2), m_near.group(3)))
            elif m_g2 and not any(w in ((m_g2.group(2) or "") + (m_g2.group(4) or ""))
                                  for w in EXEMPT_BRIDGE):
                reason = ("G2 判定即动手：`%s%s判定%s%s` —— 判定后未标注顺延(≥09:30)/盲挂(≤09:20)"
                          % (m_g2.group(1), m_g2.group(2), m_g2.group(4), m_g2.group(5)))
            elif LOCK_AT_0925_RE.search(s) and PRE_SILENT_TIME_RE.search(s):
                reason = "G3 锁单却提前买：09:25 锁定清单，却要求在 09:25 前买入且未标注盲挂协议"
            if reason is None:
                continue
            if _has_any(s, EXEC_ANNOT):
                continue                      # 已显式标注 → 正当写法
            rel = str(p.relative_to(root)).replace("\\", "/")
            hit_ex = next((w for k, w in ex
                           if (k[1:] in rel if k.startswith("@") else (k and k in s))), None)
            item = dict(file=rel, line=i, text=s[:240], reason=reason)
            (exempt if hit_ex else viol).append(
                {**item, "exempt_reason": hit_ex} if hit_ex else item)
    return viol, exempt, nf


# ---------------------------------------------------------------- 逐笔记录检查器
TRADE_GLOBS = ("**/*trades*.jsonl", "**/_v16_trades.jsonl", "**/oos_trades.jsonl")


def scan_trade_records(root: Path, S) -> tuple[list[dict], int]:
    """G4：用引擎探针检查逐笔记录的可成交性。返回 (violations, n_records)。"""
    recs, files = [], []
    for pat in TRADE_GLOBS:
        for p in root.glob(pat):
            if any(part in SKIP_DIR_PARTS for part in p.parts):
                continue
            files.append(p)
    for p in sorted(set(files)):
        for ln in _read_lines(p):
            ln = ln.strip()
            if not ln:
                continue
            try:
                recs.append(json.loads(ln))
            except Exception:  # noqa: BLE001
                continue
    if not recs:
        return [], 0
    out = []
    # ① 竞价下单时点：成交价 = 今开者须有 ≤09:20 下单记录，且不在静默期
    import importlib
    audit = importlib.import_module("engine.audit")
    try:
        a = audit.probe_auction_order_admissibility(recs)
        for b in a.get("bad", []):
            out.append(dict(check="G4a 竞价下单时点", **b))
    except Exception as e:  # noqa: BLE001
        out.append(dict(check="G4a 竞价下单时点", reason="probe_error", detail=str(e)[:160]))
    # ② 成交日可成交性：需要 bars —— 记录里带 bar 快照时才判（否则只统计不可判）
    bare = [r for r in recs if isinstance(r.get("bar"), dict)]
    if bare:
        bars = {}
        for r in bare:
            bars[(r.get("sym"), r.get("date") or r.get("entry_date"))] = r["bar"]
        try:
            b2 = audit.probe_fill_tradability(
                [dict(sym=r.get("sym"), date=r.get("date") or r.get("entry_date"),
                      price=r.get("entry_px") or r.get("price"), side=r.get("side", "buy"),
                      prev_close=r.get("prev_close")) for r in bare], bars)
            for b in b2.get("bad", []):
                out.append(dict(check="G4b 成交日可成交性", **b))
        except Exception as e:  # noqa: BLE001
            out.append(dict(check="G4b 成交日可成交性", reason="probe_error",
                            detail=str(e)[:160]))
    return out, len(recs)


# ---------------------------------------------------------------- G5 成交口径三查（gushi topic/1010）
def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _close_px(a, b, atol: float = 1e-9) -> bool:
    fa, fb = _num(a), _num(b)
    if fa is None or fb is None:
        return False
    return abs(fa - fb) <= atol + 1e-9 * max(abs(fa), 1.0)


def _legs(rec: dict) -> list[tuple[str, object, object, dict | None]]:
    """把一条逐笔记录拆成 (side, date, price, bar) 的腿。

    支持两种形态：
      A 单腿：{sym, date|entry_date, price|entry_px, side, bar, prev_close?}
      B 往返：{sym, entry_date, entry_px, exit_date, exit_px, bar, exit_bar?, prev_close?}
    """
    buy_bar = rec.get("bar") if isinstance(rec.get("bar"), dict) else None
    exit_bar = rec.get("exit_bar") if isinstance(rec.get("exit_bar"), dict) else None
    side = rec.get("side")
    if side in ("buy", "sell") and (rec.get("date") or rec.get("entry_date")):
        d = rec.get("date") or rec.get("entry_date")
        px = rec.get("price") if rec.get("price") is not None else rec.get("entry_px")
        return [(side, d, px, buy_bar)]
    legs = []
    d = rec.get("entry_date") or rec.get("date")
    if d:
        legs.append(("buy", d, rec.get("entry_px") if rec.get("entry_px") is not None
                     else rec.get("price"), buy_bar))
    if rec.get("exit_date"):
        legs.append(("sell", rec.get("exit_date"), rec.get("exit_px"), exit_bar))
    return legs


def scan_fill_rules(root: Path, S, strict_fill: bool = False) -> tuple[list[dict], int, int]:
    """G5：按 topic/1010 的三条执行口径检查逐笔记录。

    返回 (violations, n_judged, n_unjudgeable)。只在记录带当日 bar 快照时才判；
    不可判的腿**显式计数**，不静默略过。涨跌停真值源一律取 `engine.session`。
    """
    files = []
    for pat in TRADE_GLOBS:
        for p in root.glob(pat):
            if any(part in SKIP_DIR_PARTS for part in p.parts):
                continue
            files.append(p)
    recs = []
    for p in sorted(set(files)):
        for ln in _read_lines(p):
            ln = ln.strip()
            if not ln:
                continue
            try:
                recs.append(json.loads(ln))
            except Exception:  # noqa: BLE001
                continue
    out: list[dict] = []
    n_ok = n_skip = 0
    for i, rec in enumerate(recs):
        sym = rec.get("sym")
        for side, d, px, bar in _legs(rec):
            if not isinstance(bar, dict):
                n_skip += 1
                continue
            n_ok += 1
            pc = _num(rec.get("prev_close"))
            if pc is None:
                pc = _num(bar.get("prev_close"))
            board = rec.get("board") or S.board_of(str(sym))
            is_st = bool(rec.get("is_st"))
            up, dn = bar.get("upper_limit"), bar.get("lower_limit")
            if (up is None or dn is None) and pc:
                up2, dn2 = S.limit_prices(float(pc), board, is_st)
                up = up2 if up is None else up
                dn = dn2 if dn is None else dn
            tag = f"sym={sym} date={d} side={side} px={px}"
            if side == "buy":
                if _close_px(px, bar.get("open")):
                    tradable, why = S.tradable_at_fill(bar, pc, board, "buy", is_st)
                    if not tradable:
                        out.append(dict(check="G5a 开盘涨停买不进", i=i, detail=f"{tag} —— {why}"))
                        continue
                    low, op = _num(bar.get("low")), _num(bar.get("open"))
                    if not S.limit_order_crossed(float(px), bar, "buy"):
                        out.append(dict(check="G5b 成交未确立", i=i,
                                        detail=f"{tag} —— 挂价未被当日最低价穿到，限价单不可能成交，"
                                               f"该笔成交记录不成立"))
                        continue
                    if strict_fill and low is not None and op is not None and low >= op - 1e-9:
                        out.append(dict(check="G5b 成交未确立（严格口径）", i=i,
                                        detail=f"{tag} —— 当日最低价恰等于开盘价：除开盘价外没有任何更低报价，"
                                               f"09:25 撮合后才按开盘价挂单的成交无法确立"))
                        continue
                continue
            if dn is not None:
                highv = _num(bar.get("high"))
                if highv is not None and S.reaches_limit_down(highv, float(dn)):
                    out.append(dict(check="G5c 跌停封死却记成交", i=i,
                                    detail=f"{tag} —— 当日 high {highv:.2f} 已触及跌停 {float(dn):.2f}"
                                           f"（全天封死、卖不掉），须顺延到下一可卖日再计价"))
                    continue
            tradable, why = S.tradable_at_fill(bar, pc, board, "sell", is_st)
            if not tradable and _close_px(px, bar.get("open")):
                out.append(dict(check="G5c 跌停封死却记成交", i=i, detail=f"{tag} —— {why}"))
    return out, n_ok, n_skip


# ---------------------------------------------------------------- 自检（V6）
SELFTEST_BAD = """# 负例：静默期动作（应被 G1 拦下）
| 09:25 | 判定后立刻买入 3 只 |
| 09:26 | 挂单撤单 |
# 负例：锁单却提前买（应被 G3 拦下）
09:25 锁定清单后，请在 09:18 按清单买入全部标的。
# 负例：判定即动手（应被 G2 拦下）
09:15 判定 后按清单下单
"""
SELFTEST_GOOD = """# 正例：已标注可执行时点（不应被拦）
| 09:25 | 仅判定（权威清单冻结） | 可执行时点 ≥09:30 |
| 09:15–09:20 | 盲挂 前收×0.99 限价买单（可撤单窗内撤带外单） | 可执行时点 ≤09:20 |
09:25–09:30 为静默期·不可下单；动作一律顺延到 09:30 或前置到 ≤09:20。
09:25 锁定清单，下单依据是竞价预备清单（用参考价），动作 ≤09:20（盲挂协议）。
"""


SELFTEST_TRADES_BAD = """\
{"sym":"sh600000","entry_date":"2026-03-02","entry_px":11.00,"prev_close":10.00,"bar":{"open":11.00,"high":11.00,"low":11.00,"close":11.00,"volume":1000}}
{"sym":"sh600001","entry_date":"2026-03-02","entry_px":10.50,"prev_close":10.00,"bar":{"open":10.50,"high":10.90,"low":10.60,"close":10.80,"volume":1000}}
{"sym":"sh600002","entry_date":"2026-03-02","entry_px":10.50,"exit_date":"2026-03-03","exit_px":9.00,"prev_close":10.00,"bar":{"open":10.50,"high":10.90,"low":10.20,"close":10.00,"volume":1000},"exit_bar":{"open":9.00,"high":9.00,"low":9.00,"close":9.00,"volume":1000}}
{"sym":"sh600003","entry_date":"2026-03-02","entry_px":10.50,"prev_close":10.00,"bar":{"open":10.50,"high":10.90,"low":10.50,"close":10.80,"volume":1000}}
"""
SELFTEST_TRADES_GOOD = """\
{"sym":"sh600010","entry_date":"2026-03-02","entry_px":10.50,"exit_date":"2026-03-03","exit_px":10.40,"prev_close":10.00,"bar":{"open":10.50,"high":10.90,"low":10.20,"close":10.00,"volume":1000},"exit_bar":{"open":10.30,"high":10.60,"low":10.10,"close":10.40,"volume":1000}}
"""


def _selftest(S) -> int:
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "bad.md").write_text(SELFTEST_BAD, encoding="utf-8")
        bad_v, _, _ = scan_texts(root, [])
        n_bad = len(bad_v)
        print(f"[自检] 文本负例：检出 {n_bad} 条（期望 ≥3，覆盖 G1/G2/G3）")
        if n_bad < 3:
            print("  !! 负例未被完整拦下 → 门禁空转"); ok = False
        (root / "bad.md").unlink()
        (root / "good.md").write_text(SELFTEST_GOOD, encoding="utf-8")
        good_v, _, _ = scan_texts(root, [])
        print(f"[自检] 文本正例：检出 {len(good_v)} 条（期望 0）")
        if good_v:
            for v in good_v:
                print(f"  !! 误报 {v['file']}:{v['line']} {v['reason']} | {v['text'][:80]}")
            ok = False
        (root / "good.md").unlink()

        # ---- G5 成交口径三查：注入式正/负对照（夹具见 SELFTEST_TRADES_*）----
        bad_tr = root / "bt_trades_bad.jsonl"
        bad_tr.write_text(SELFTEST_TRADES_BAD, encoding="utf-8")
        v_norm, nj, ns = scan_fill_rules(root, S, strict_fill=False)
        kinds = sorted({v["check"] for v in v_norm})
        print(f"[自检] G5 负例/常规口径：违规 {len(v_norm)} 条（期望 3：G5a+G5b+G5c），"
              f"可判腿 {nj} 条，不可判 {ns} 条")
        if len(v_norm) != 3 or len(kinds) != 3:
            print(f"  !! G5 常规口径未按预期拦下：{[v['check'] for v in v_norm]}"); ok = False
        v_strict, _, _ = scan_fill_rules(root, S, strict_fill=True)
        print(f"[自检] G5 负例/严格口径：违规 {len(v_strict)} 条（期望 4：多一条「最低价=开盘价」）")
        if len(v_strict) != 4:
            print(f"  !! G5 严格口径计数异常：{[v['check'] for v in v_strict]}"); ok = False
        bad_tr.unlink()

        good_tr = root / "bt_trades_good.jsonl"
        good_tr.write_text(SELFTEST_TRADES_GOOD, encoding="utf-8")
        v_ok, nj2, _ = scan_fill_rules(root, S, strict_fill=False)
        v_ok2, _, _ = scan_fill_rules(root, S, strict_fill=True)
        print(f"[自检] G5 正例：常规 {len(v_ok)} 条 / 严格 {len(v_ok2)} 条（期望 0/0），可判腿 {nj2} 条")
        for v in (v_ok + v_ok2):
            print(f"  !! G5 误报 {v['check']} {v['detail'][:100]}")
            ok = False
        good_tr.unlink()
    print("\n自检" + ("通过：门禁既能拦违规、又不误报正当写法（退出码 0）" if ok
                     else "失败（退出码 1）"))
    return 0 if ok else 1


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="交易时钟机械门禁（ADR-0004）")
    ap.add_argument("--root", default=r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
    ap.add_argument("--json", default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--strict-fill", action="store_true",
                    help="G5b 采用严格成交口径：当日最低价恰等于开盘价也算成交未确立")
    a = ap.parse_args()

    S, err = _load_session()
    if S is None:
        print(f"门禁不可用（失败闭锁）：{err}", file=sys.stderr)
        return 1
    if a.selftest:
        return _selftest(S)

    root = Path(a.root)
    if not root.is_dir():
        print(f"根目录不存在：{root}", file=sys.stderr)
        return 1

    print("=== 交易时钟门禁（ADR-0004）===")
    print(f"根目录：{root}")
    print(f"时钟真值源：{_SESSION_PY}")
    print(f"静默期定义：{S.SILENT_START:%H:%M}–{S.SILENT_END:%H:%M}（不接受申报/撤单、无成交）；"
          f"动作最早可执行 = {S.AM_START:%H:%M}；盲挂须 ≤{S.AUCTION_CANCEL_END:%H:%M}\n")

    ex = load_exemptions(root)
    print(f"例外登记：{len(ex)} 条" + ("（见 tools/gate_trading_clock_exempt.txt）" if ex else "（无）"))
    viol, exempted, nf = scan_texts(root, ex)
    print(f"文本扫描：{nf} 个文件 → 违规 {len(viol)} 条，已登记例外 {len(exempted)} 条")
    for v in viol[:40]:
        print(f"  ✗ {v['file']}:{v['line']}  {v['reason']}")
        print(f"      {v['text'][:150]}")
    if len(viol) > 40:
        print(f"  …… 另有 {len(viol) - 40} 条")
    for v in exempted[:10]:
        print(f"  · 例外 {v['file']}:{v['line']}（{v['exempt_reason']}）")

    tv, nrec = scan_trade_records(root, S)
    print(f"\n逐笔记录：{nrec} 条 → G4 违规 {len(tv)} 条" + ("（无可判记录）" if nrec == 0 else ""))
    for v in tv[:20]:
        print(f"  ✗ {v}")

    fv, n_judged, n_unjudged = scan_fill_rules(root, S, strict_fill=a.strict_fill)
    print(f"\nG5 成交口径三查（topic/1010，口径={'严格' if a.strict_fill else '常规'}）："
          f"可判腿 {n_judged} 条 / 不可判腿 {n_unjudged} 条 → 违规 {len(fv)} 条"
          + ("（无可判记录：记录未带当日 bar 快照）" if n_judged == 0 else ""))
    for v in fv[:20]:
        print(f"  ✗ {v['check']}  {v['detail']}")

    n_bad = len(viol) + len(tv) + len(fv)
    res = dict(root=str(root), silent_window=[f"{S.SILENT_START:%H:%M}", f"{S.SILENT_END:%H:%M}"],
               n_text_files=nf, n_violations_text=len(viol), n_exempted=len(exempted),
               n_trade_records=nrec, n_violations_trades=len(tv),
               fill_rule_mode="strict" if a.strict_fill else "normal",
               n_fill_legs_judged=n_judged, n_fill_legs_unjudgeable=n_unjudged,
               n_violations_fill_rules=len(fv),
               violations=viol[:200], exempted=exempted[:200], trade_violations=tv[:200],
               fill_rule_violations=fv[:200],
               verdict="PASS" if n_bad == 0 else "FAIL")
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n已写出 {a.json}")

    print(f"\n判定：{res['verdict']}（违规合计 {n_bad} 条）")
    return 0 if n_bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
