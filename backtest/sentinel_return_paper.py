# -*- coding: utf-8 -*-
"""热榜哨兵独立收益纸面账本（R-jiandi-top30-0924/v1）。

只读取 sentinel_daily.py 已生成的当日池、index_000300.csv 与 data_full 行情；
只写 backtest/sentinel_return_paper.json。绝不读写 sentinel_state.json、否决位、
预注册状态或其它策略账本，也不发送真实订单。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
POOL_PATH = BASE / "sentinel_pool.js"
INDEX_PATH = BASE / "index_000300.csv"
DATA_DIR = BASE / "data_full"
STATE_PATH = BASE / "backtest" / "sentinel_return_paper.json"
SCHEMA = "sentinel_return_paper/v1"
RULE_VERSION = "R-jiandi-top30-0924/v1"
SEED_NAV = 100_000.0
K = 5
THETA = 30
HOLD_DAYS = 5
SEED = 20260921
COSTS = {"0.20%": 0.002, "1.15%": 0.0115}
RSI_THRESHOLDS = {0: 55.0, 1: 65.0, 2: 65.0}


def _date(value: Any) -> str:
    return str(value or "")[:10]


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def new_state(seed_date: str, started_at: str | None = None) -> dict:
    return {
        "schema": SCHEMA,
        "strategy": "热榜哨兵收益模拟",
        "rule_version": RULE_VERSION,
        "seed_date": seed_date,
        "started_at": started_at or time.strftime("%Y-%m-%d %H:%M:%S"),
        "initial_nav": SEED_NAV,
        "universe": "沪深主板（sh60/sz00/sz002）· len(df)>=400 · 排除 sh5/sz1/bj",
        "entry_rule": "K>=2 且当日全市场共振家数 θ>=30；T 收盘确认，T+1 开盘成交",
        "selection_rule": "最多 K=5 槽等权；按冻结 seed=20260921 的日种子随机取样",
        "exit_rule": "RSI(14) 域 55/65/65（熊/强牛/弱牛），信号次日开盘卖；最多持有 5 日",
        "cost_rule": "预注册两档往返成本：0.20% 与 1.15%，在平仓时按入场名义金额扣除",
        "trading_enabled": False,
        "veto_state_source": "backtest/sentinel_state.json（只读职责；本账本不读写）",
        "portfolios": {label: _new_portfolio(label, rate, seed_date) for label, rate in COSTS.items()},
        "pending_entries": None,
        "signals": [],
        "last_processed_date": None,
        "as_of": seed_date,
        "status": "FLAT_NO_TRIGGER",
        "status_note": "未触发/空仓；种子 NAV 100000.00，累计净收益 0.00%。",
    }


def _new_portfolio(label: str, cost_rate: float, seed_date: str) -> dict:
    return {
        "cost_label": label,
        "round_trip_cost_rate": cost_rate,
        "cash": SEED_NAV,
        "positions": {},
        "nav": SEED_NAV,
        "cum_net_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "n_fills": 0,
        "n_completed_trades": 0,
        "fills": [],
        "closed_trades": [],
        "nav_history": [{"date": seed_date, "nav": SEED_NAV, "cash": SEED_NAV,
                          "market_value": 0.0, "cum_net_return_pct": 0.0, "n_positions": 0}],
    }


def read_js_object(path: Path, varname: str) -> dict:
    text = path.read_text(encoding="utf-8-sig")
    marker = "window.%s" % varname
    start = text.find(marker)
    if start < 0:
        raise ValueError("%s missing from %s" % (marker, path))
    start = text.find("{", start)
    if start < 0:
        raise ValueError("JSON object missing after %s" % marker)
    # JSON strings may contain braces; scan while honoring JSON quoting and escapes.
    depth, quoted, escaped = 0, False, False
    for pos in range(start, len(text)):
        ch = text[pos]
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
            continue
        if ch == '"':
            quoted = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:pos + 1])
    raise ValueError("unterminated JSON object in %s" % path)


def load_index(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = []
        for row in csv.DictReader(stream):
            day, close = _date(row.get("date") or row.get("日期")), _number(row.get("close") or row.get("收盘"))
            if day and close and close > 0:
                rows.append({"date": day, "close": close})
    rows.sort(key=lambda row: row["date"])
    if not rows:
        raise ValueError("index calendar is empty")
    return rows


def load_bars(data_dir: Path, codes: set[str]) -> dict[str, list[dict]]:
    out = {}
    for code in sorted(codes):
        path = data_dir / (code + ".csv")
        rows = []
        if path.is_file():
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    day = _date(row.get("date"))
                    op, close = _number(row.get("open")), _number(row.get("close"))
                    if day:
                        rows.append({"date": day, "open": op, "close": close})
        out[code] = sorted(rows, key=lambda row: row["date"])
    return out


def _bar_map(bars: dict[str, list[dict]], asof: str) -> dict[str, dict]:
    out = {}
    for code, rows in bars.items():
        matches = [row for row in rows if row["date"] == asof]
        if matches:
            out[code] = matches[-1]
    return out


def _prev_close(pos: dict) -> float | None:
    return _number(pos.get("last_close"))


def _regime_map(index_rows: list[dict]) -> dict[str, int]:
    """与 sentinel_daily.build_regime 一致：当日信号使用前一交易日分域。"""
    states = []
    closes = [row["close"] for row in index_rows]
    for i, row in enumerate(index_rows):
        ma20 = sum(closes[max(0, i - 19):i + 1]) / len(closes[max(0, i - 19):i + 1])
        ma60 = sum(closes[max(0, i - 59):i + 1]) / len(closes[max(0, i - 59):i + 1])
        is_bear = row["close"] < ma60
        is_bull = (not is_bear) and row["close"] > ma20
        states.append(0 if is_bear else (1 if is_bull else 2))
    return {row["date"]: (states[i - 1] if i else 0) for i, row in enumerate(index_rows)}


def _rsi14(rows: list[dict], asof: str) -> float | None:
    closes = [_number(row.get("close")) for row in rows if row["date"] <= asof]
    closes = [value for value in closes if value is not None and value > 0]
    if len(closes) < 2:
        return None
    delta = [closes[i] - closes[i - 1] for i in range(1, len(closes))][-14:]
    gains = [max(value, 0.0) for value in delta]
    losses = [max(-value, 0.0) for value in delta]
    avg_gain = sum(gains) / len(delta)
    avg_loss = sum(losses) / len(delta)
    if avg_loss == 0:
        return None
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _next_day(index_rows: list[dict], after: str) -> str | None:
    return next((row["date"] for row in index_rows if row["date"] > after), None)


def _selected_candidates(candidates: list[dict], free_slots: int, signal_date: str) -> list[dict]:
    if free_slots <= 0 or not candidates:
        return []
    valid = [row for row in candidates if int(row.get("cnt") or 0) >= 2 and row.get("code")]
    # Stable seed keyed by date: reproducible randomized choice without mutable global RNG state.
    ranked = sorted(valid, key=lambda row: hashlib.sha256(
        (str(SEED) + ":" + signal_date + ":" + str(row["code"])).encode("utf-8")).hexdigest())
    return ranked[:min(K, free_slots, len(ranked))]


def _nav_row(port: dict, day: str) -> dict:
    market_value = sum(max(0.0, float(pos.get("units") or 0.0)) *
                       max(0.0, float(pos.get("last_close") or 0.0))
                       for pos in port["positions"].values())
    cash = max(0.0, float(port.get("cash") or 0.0))
    nav = cash + market_value
    port["nav"] = round(nav, 6)
    port["cum_net_return_pct"] = round((nav / SEED_NAV - 1.0) * 100.0, 6)
    history = port.setdefault("nav_history", [])
    row = {"date": day, "nav": port["nav"], "cash": round(cash, 6),
           "market_value": round(market_value, 6),
           "cum_net_return_pct": port["cum_net_return_pct"],
           "n_positions": len(port["positions"])}
    if history and history[-1].get("date") == day:
        history[-1] = row
    else:
        history.append(row)
    peak, worst = SEED_NAV, 0.0
    for item in history:
        value = float(item.get("nav") or SEED_NAV)
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value / peak - 1.0) * 100.0)
    port["max_drawdown_pct"] = round(worst, 6)
    return row


def _fill_and_mark(port: dict, day: str, index_rows: list[dict], bars: dict[str, list[dict]],
                   pending: dict | None, seed_date: str) -> list[dict]:
    today = _bar_map(bars, day)
    # T+1 exits execute at the specified next session open; missing open stays pending.
    for code, pos in list(port["positions"].items()):
        exit_day = pos.get("exit_date")
        bar = today.get(code)
        if exit_day and exit_day <= day and bar and bar.get("open") and bar["open"] > 0:
            prev = _prev_close(pos)
            open_px = float(bar["open"])
            units = float(pos.get("units") or 0.0)
            gross = units * open_px
            fee = float(pos.get("entry_value") or 0.0) * float(port["round_trip_cost_rate"])
            port["cash"] += gross - fee
            trade = {
                "code": code, "name": pos.get("name") or code,
                "signal_date": pos.get("signal_date"), "entry_date": pos.get("entry_date"),
                "entry_price": pos.get("entry_price"), "exit_date": day,
                "exit_price": open_px, "units": round(units, 8),
                "gross_pnl": round(gross - float(pos.get("entry_value") or 0.0), 4),
                "fee": round(fee, 4),
                "net_pnl": round(gross - float(pos.get("entry_value") or 0.0) - fee, 4),
                "return_net_pct": round((open_px / float(pos.get("entry_price") or open_px) - 1.0
                                          - float(port["round_trip_cost_rate"])) * 100.0, 4),
                "exit_reason": pos.get("exit_reason") or "RSI_OR_MAX_5D",
            }
            port["closed_trades"].append(trade)
            port["fills"].append({"date": day, "side": "sell", "code": code, "name": trade["name"],
                                  "price": open_px, "units": round(units, 8), "fee": round(fee, 4),
                                  "signal_date": pos.get("signal_date")})
            port["positions"].pop(code, None)
        elif exit_day and exit_day <= day:
            pos["exit_status"] = "WAITING_FOR_NEXT_VALID_OPEN"

    # Candidate signal from previous close can only fill on the immediately following index session.
    if pending and pending.get("signal_date"):
        signal_date = _date(pending["signal_date"])
        t1 = _next_day(index_rows, signal_date)
        if t1 == day and pending.get("fill_date") in (None, t1):
            min_free = min(max(0, K - len(port["positions"]))
                           for port in (port,))
            picks = _selected_candidates(pending.get("candidates") or [], min_free, signal_date)
            unfilled = []
            for item in picks:
                code = str(item["code"])
                bar = today.get(code)
                if not bar or not bar.get("open") or bar["open"] <= 0:
                    unfilled.append(item)
                    continue
                if code in port["positions"]:
                    continue
                equity_open = float(port["cash"]) + sum(
                    float(pos.get("units") or 0.0) * float(pos.get("last_close") or 0.0)
                    for pos in port["positions"].values())
                budget = equity_open / K
                price = float(bar["open"])
                qty = min(budget / price, float(port["cash"]) / price)
                if qty <= 0:
                    unfilled.append(item)
                    continue
                amount = qty * price
                port["cash"] -= amount
                port["positions"][code] = {
                    "code": code, "name": item.get("name") or code,
                    "signal_date": signal_date, "entry_date": day,
                    "entry_price": price, "entry_value": amount, "units": qty,
                    "last_close": price, "bars_held": 1,
                    "exit_date": None, "exit_reason": None,
                }
                port["fills"].append({"date": day, "side": "buy", "code": code,
                                      "name": item.get("name") or code, "price": price,
                                      "units": round(qty, 8), "fee": 0.0,
                                      "signal_date": signal_date})
            if unfilled:
                pending["unfilled_candidates"] = unfilled
                pending["status"] = "MISSING_T1_OPEN_OR_PRICE"
        elif t1 and t1 < day:
            # Do not move a frozen T+1 order to T+2 after a missed/invalid T+1 open.
            pending["status"] = "MISSED_T1_OPEN_OR_DATA"

    # Mark at today's close, retaining last real close only for a missing/halted bar.
    for code, pos in port["positions"].items():
        bar = today.get(code)
        if bar and bar.get("close") and bar["close"] > 0:
            pos["last_close"] = float(bar["close"])
            pos["last_bar_date"] = day
            if pos.get("entry_date") != day:
                pos["bars_held"] = int(pos.get("bars_held") or 0) + 1
    return list(port["positions"].values())


def step(state: dict | None, pool: dict, index_rows: list[dict], bars: dict[str, list[dict]],
         market_asof: str, started_at: str | None = None) -> dict:
    """Pure daily transition, with injectable fixtures for isolation tests."""
    day = _date(market_asof)
    if not day:
        raise ValueError("market_asof missing")
    index_rows = sorted([{"date": _date(r.get("date")), "close": _number(r.get("close"))}
                         for r in index_rows if _date(r.get("date")) and _number(r.get("close"))],
                        key=lambda row: row["date"])
    if not index_rows:
        raise ValueError("index rows are empty")
    if state is None:
        state = new_state(day, started_at)
    if state.get("schema") != SCHEMA or state.get("rule_version") != RULE_VERSION:
        raise ValueError("unexpected sentinel return paper schema/rule version; refuse overwrite")
    if _date(state.get("last_processed_date")) == day:
        return state
    if day < _date(state.get("seed_date")):
        raise ValueError("market_asof precedes paper account seed date")

    # Previous close may have created an exit signal before T+1 exists in today's index file.
    # On the next refresh, restore that frozen next-session order before processing the open.
    for portfolio in state["portfolios"].values():
        for pos in portfolio["positions"].values():
            exit_signal_date = _date(pos.get("exit_signal_date"))
            if exit_signal_date and not pos.get("exit_date") and exit_signal_date < day:
                scheduled = _next_day(index_rows, exit_signal_date)
                if scheduled and scheduled <= day:
                    pos["exit_date"] = scheduled
    asof_pool = _date(pool.get("as_of"))
    pool_fresh = asof_pool == day
    triggered = bool(pool_fresh and pool.get("triggered")
                     and int(pool.get("threshold") or 0) == THETA
                     and int(pool.get("as_of_resonance") or 0) >= THETA)
    # Execute yesterday's queued entries/exits, then mark each isolated cost portfolio.
    pending = state.get("pending_entries")
    for portfolio in state["portfolios"].values():
        _fill_and_mark(portfolio, day, index_rows, bars, pending, state["seed_date"])
        row = _nav_row(portfolio, day)
        portfolio["n_fills"] = len(portfolio["fills"])
        portfolio["n_completed_trades"] = len(portfolio["closed_trades"])
        portfolio["current_positions"] = [dict(pos) for pos in portfolio["positions"].values()]

    # Evaluate T-close exits only after today's close has been marked; sale is next session open.
    regimes = _regime_map(index_rows)
    regime = regimes.get(day, 0)
    threshold = RSI_THRESHOLDS.get(regime, 55.0)
    next_session = _next_day(index_rows, day)
    for portfolio in state["portfolios"].values():
        for code, pos in portfolio["positions"].items():
            if pos.get("exit_date"):
                continue
            rsi = _rsi14(bars.get(code, []), day)
            reason = "RSI_%s" % int(threshold) if rsi is not None and rsi >= threshold else None
            if not reason and int(pos.get("bars_held") or 0) >= HOLD_DAYS:
                reason = "MAX_5D"
            if reason:
                pos["exit_date"] = next_session
                pos["exit_signal_date"] = day
                pos["exit_reason"] = reason
                if next_session is None:
                    pos["exit_status"] = "WAITING_NEXT_INDEX_SESSION"

    if pending and pending.get("signal_date") and _next_day(index_rows, _date(pending["signal_date"])) == day:
        state["pending_entries"] = pending if pending.get("status") == "MISSING_T1_OPEN_OR_PRICE" else None
    elif pending and pending.get("status") in ("MISSED_T1_OPEN_OR_DATA", "MISSING_T1_OPEN_OR_PRICE"):
        state["pending_entries"] = pending

    if triggered:
        rows = [row for row in (pool.get("pool") or []) if int(row.get("cnt") or 0) >= 2
                and row.get("code")]
        state["pending_entries"] = {"signal_date": day, "candidates": rows,
                                    "status": "WAITING_T1_OPEN"}
        state.setdefault("signals", []).append({
            "signal_date": day, "resonance": int(pool.get("as_of_resonance") or 0),
            "candidate_count": len(rows), "status": "QUEUED_FOR_T1_OPEN"})
        state["signals"] = state["signals"][-500:]

    state["last_processed_date"] = day
    state["as_of"] = day
    has_positions = any(p["positions"] for p in state["portfolios"].values())
    pending_status = (state.get("pending_entries") or {}).get("status")
    if pending_status:
        state["status"] = pending_status
        state["status_note"] = "触发信号已记录；只在信号次一交易日开盘成交，T+1 开盘缺失则保留待核，不顺延伪成交。"
    elif has_positions:
        state["status"] = "ACTIVE"
        state["status_note"] = "纸面持仓按收盘价标记；RSI 域阈值或持有满 5 日后，下一交易日开盘退出。"
    else:
        state["status"] = "FLAT_NO_TRIGGER"
        state["status_note"] = "未触发/空仓；种子 NAV 100000.00，累计净收益 0.00%。"
    return state


def _all_codes(pool: dict, state: dict | None) -> set[str]:
    codes = {str(row.get("code")) for row in (pool.get("pool") or []) if row.get("code")}
    if state:
        for portfolio in state.get("portfolios", {}).values():
            codes.update((portfolio.get("positions") or {}).keys())
        for row in (state.get("pending_entries") or {}).get("candidates", []):
            if row.get("code"):
                codes.add(str(row["code"]))
    return codes


def atomic_save(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run(pool_path: Path = POOL_PATH, index_path: Path = INDEX_PATH, data_dir: Path = DATA_DIR,
        state_path: Path = STATE_PATH, dry_run: bool = False) -> dict:
    pool = read_js_object(pool_path, "SENTINEL_POOL")
    index_rows = load_index(index_path)
    market_asof = index_rows[-1]["date"]
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None
    if state and (state.get("schema") != SCHEMA or state.get("rule_version") != RULE_VERSION):
        raise ValueError("existing sentinel return paper state has unexpected schema; refuse overwrite")
    codes = _all_codes(pool, state)
    bars = load_bars(data_dir, codes)
    state = step(state, pool, index_rows, bars, market_asof)
    print("热榜哨兵收益纸面账本：as_of=%s pool_as_of=%s triggered=%s status=%s" %
          (market_asof, _date(pool.get("as_of")) or "—", bool(pool.get("triggered")), state["status"]))
    for label, portfolio in state["portfolios"].items():
        print("  cost=%s NAV=%.2f net=%+.2f%% MDD=%.2f%% fills=%d closed=%d positions=%d cash=%.2f" %
              (label, portfolio["nav"], portfolio["cum_net_return_pct"], portfolio["max_drawdown_pct"],
               portfolio["n_fills"], portfolio["n_completed_trades"],
               len(portfolio["positions"]), portfolio["cash"]))
    print("  note:", state["status_note"])
    if not dry_run:
        atomic_save(state_path, state)
        print("  wrote independent state:", state_path)
    else:
        print("  dry-run: no file written")
    return state


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="热榜哨兵独立收益模拟盘；与只读否决状态隔离")
    parser.add_argument("--pool", type=Path, default=POOL_PATH)
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--state", type=Path, default=STATE_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    run(args.pool, args.index, args.data_dir, args.state, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
