# -*- coding: utf-8 -*-
"""短线「基金轮动」独立纸面账本；与 FB3-H20 fund_paper.json 物理隔离。

候选完全取自 build_short_pool.py 已落盘的 tiers["基金"]：2000 基金池、牛市
S30 Top10 / 熊市 S45 Top3、同基份额去重并优先 C 类均由上游生产链执行。
本模块只做等权目标差额轮动、严格 T+1 净值成交和净值记账，不重算候选。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
POOL_PATH = BASE / "short_pool.json"
NAV_DIR = BASE / "fund_nav_cache"
INDEX_PATH = BASE / "index_000300.csv"
STATE_PATH = BASE / "backtest" / "fund_rotation_paper.json"
STRATEGY = "基金轮动"
SCHEMA = "fund_rotation_paper/v1"
INITIAL_CASH = 100_000.0
FEE_PER_SIDE = 0.0005  # 5bp/边，短线基金生产回测口径
EPS = 1e-8
SELECTION_RULE = {
    "universe": "2000 基金池",
    "bull": "短线分数 >= 30，Top10",
    "bear": "短线分数 >= 45，Top3",
    "share_dedup": "同基份额去重，优先 C 类；由 build_short_pool.py 生产",
    "candidate_source": "short_pool.json:tiers.基金（不在本账本重排）",
}


def _date(value: Any) -> str:
    return str(value or "")[:10]


def _num(value: Any) -> float | None:
    try:
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def selected_codes(pool: dict) -> list[str]:
    """取生产基金候选原顺序；不做二次评分、筛选或份额处理。"""
    out: list[str] = []
    for raw in (pool.get("tiers") or {}).get("基金") or []:
        code = str(raw).strip()
        if len(code) == 6 and code.isdigit() and code not in out:
            out.append(code)
    return out


def load_nav_series(nav_dir: Path, codes: set[str]) -> dict[str, list[tuple[str, float]]]:
    """仅读取指定基金净值；不跨缺失净值日向前填充成交。"""
    out: dict[str, list[tuple[str, float]]] = {}
    for code in sorted(codes):
        path = nav_dir / (code + ".csv")
        rows: list[tuple[str, float]] = []
        if path.is_file():
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    day = _date(row.get("净值日期") or row.get("date"))
                    nav = _num(row.get("单位净值") or row.get("unit_nav") or row.get("nav"))
                    if day and nav is not None and nav > 0:
                        rows.append((day, nav))
        out[code] = sorted({day: value for day, value in rows}.items())
    return out


def latest_nav(series: list[tuple[str, float]], asof: str) -> tuple[str, float] | None:
    eligible = [(day, value) for day, value in series if day <= asof]
    return eligible[-1] if eligible else None


def next_nav(series: list[tuple[str, float]], after: str, through: str) -> tuple[str, float] | None:
    return next(((day, value) for day, value in series if after < day <= through), None)


def new_state(seed_date: str, started_at: str | None = None) -> dict:
    return {
        "schema": SCHEMA,
        "strategy": STRATEGY,
        "rule_version": "short-fund-production-pool/v1",
        "selection_rule": dict(SELECTION_RULE),
        "target_weighting": "当前候选集合目标等权；目标变化时仅按单位差额轮动",
        "fill_rule": "信号净值日之后首个可得基金净值日成交；缺值保留待成交，不用信号日净值成交",
        "fee_per_side": FEE_PER_SIDE,
        "initial_cash": INITIAL_CASH,
        "started_at": started_at or time.strftime("%Y-%m-%d %H:%M:%S"),
        "seed_date": seed_date,
        "cash": INITIAL_CASH,
        "positions": {},
        "pending_orders": {},
        "target_codes": None,
        "names": {},
        "unpriced_codes": [],
        "last_market_asof": None,
        "last_signal": None,
        "status": "WAITING_FOR_SIGNAL",
        "status_note": "以 100000.00 种子 NAV 建账；当前空仓，累计收益 0.00%，等待新鲜生产候选。",
        "nav": INITIAL_CASH,
        "market_value": 0.0,
        "cum_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "fills": [],
        "events": [],
        "nav_history": [{
            "date": seed_date, "nav": INITIAL_CASH, "cash": INITIAL_CASH,
            "market_value": 0.0, "cum_return_pct": 0.0, "positions": 0,
            "latest_fund_nav_date": None,
        }],
    }


def _event(state: dict, day: str, text: str) -> None:
    state.setdefault("events", []).append({"date": day, "event": text})
    state["events"] = state["events"][-100:]


def _mark(state: dict, navs: dict[str, list[tuple[str, float]]], asof: str) -> dict:
    market_value = 0.0
    used_dates = []
    for code, pos in list((state.get("positions") or {}).items()):
        item = latest_nav(navs.get(code, []), asof)
        if item:
            pos["last_nav_date"], pos["last_nav"] = item
        nav = _num(pos.get("last_nav"))
        units = max(0.0, _num(pos.get("units")) or 0.0)
        if nav is not None:
            market_value += units * nav
            used_dates.append(pos.get("last_nav_date") or "")
    cash = max(0.0, _num(state.get("cash")) or 0.0)
    total = cash + market_value
    state["market_value"] = round(market_value, 4)
    state["nav"] = round(total, 4)
    initial = float(state.get("initial_cash") or INITIAL_CASH)
    state["cum_return_pct"] = round((total / initial - 1.0) * 100.0, 4)
    row = {
        "date": asof, "nav": round(total, 4), "cash": round(cash, 4),
        "market_value": round(market_value, 4), "cum_return_pct": state["cum_return_pct"],
        "positions": len(state.get("positions") or {}),
        "latest_fund_nav_date": max(used_dates) if used_dates else None,
    }
    history = state.setdefault("nav_history", [])
    if history and history[-1].get("date") == asof:
        history[-1] = row
    else:
        history.append(row)
    state["nav_history"] = history[-1000:]
    peak, worst = INITIAL_CASH, 0.0
    for sample in state["nav_history"]:
        value = _num(sample.get("nav")) or INITIAL_CASH
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value / peak - 1.0) * 100.0)
    state["max_drawdown_pct"] = round(worst, 4)
    return row


def _signal_nav(code: str, signal_date: str, navs: dict[str, list[tuple[str, float]]],
                pool: dict) -> tuple[str, float] | None:
    item = latest_nav(navs.get(code, []), signal_date)
    if item:
        return item
    record = ((pool.get("details") or {}).get(code)
              or (pool.get("details") or {}).get(code[-6:]) or {})
    value = _num(record.get("px"))
    detail_date = _date(record.get("date") or record.get("as_of") or pool.get("fund_as_of"))
    if value and detail_date and detail_date <= signal_date:
        return detail_date, value
    return None


def _plan_target(state: dict, pool: dict, navs: dict[str, list[tuple[str, float]]], market_asof: str) -> None:
    codes = selected_codes(pool)
    pool_asof = _date(pool.get("as_of"))
    fund_asof = _date(pool.get("fund_as_of"))
    signal_date = fund_asof or pool_asof
    details = pool.get("details") or {}
    state["names"] = {code: str((details.get(code) or details.get(code[-6:]) or {}).get("name") or code)
                       for code in codes}
    if not signal_date:
        state["status"] = "SIGNAL_DATE_MISSING"
        state["status_note"] = "short_pool 缺 as_of/fund_as_of；不生成订单。"
        return

    equity = max(0.0, _num(state.get("cash")) or 0.0)
    current_units = {}
    reference_navs = {}
    for code, pos in (state.get("positions") or {}).items():
        units = max(0.0, _num(pos.get("units")) or 0.0)
        current_units[code] = units
        mark = latest_nav(navs.get(code, []), signal_date)
        ref = mark[1] if mark else _num(pos.get("last_nav"))
        if ref and ref > 0:
            reference_navs[code] = ref
            equity += units * ref
    target_value = equity / len(codes) if codes else 0.0
    eligible_after = max(signal_date, _date(state.get("seed_date")))
    orders = {}
    unpriced = []
    for code in sorted(set(current_units) | set(codes)):
        current = current_units.get(code, 0.0)
        if code in codes:
            mark = _signal_nav(code, signal_date, navs, pool)
            if not mark:
                unpriced.append(code)
                continue
            ref_nav = mark[1]
            reference_navs[code] = ref_nav
            target_units = target_value / ref_nav
        else:
            ref_nav = (reference_navs.get(code)
                       or _num((state.get("positions") or {}).get(code, {}).get("last_nav")))
            target_units = 0.0
        delta = target_units - current
        if abs(delta) <= EPS:
            continue
        orders[code] = {
            "code": code,
            "name": state["names"].get(code) or code,
            "side": "buy" if delta > 0 else "sell",
            "target_units": round(target_units, 10),
            "signal_fund_asof": signal_date,
            "signal_pool_asof": pool_asof,
            "signal_nav": ref_nav,
            "eligible_after": eligible_after,
        }
    state["pending_orders"] = orders
    state["unpriced_codes"] = unpriced
    state["target_codes"] = codes
    state["last_signal"] = {
        "pool_asof": pool_asof,
        "fund_asof": fund_asof or None,
        "market_regime": "bull" if (pool.get("market_gate") or {}).get("open") else "bear",
        "target_count": len(codes),
        "target_codes": codes,
    }
    _event(state, pool_asof or market_asof,
           "目标集合变化：%d 只，按差额等权轮动；%d 只缺信号日净值" % (len(codes), len(unpriced)))


def _fill_orders(state: dict, navs: dict[str, list[tuple[str, float]]], market_asof: str) -> None:
    orders = state.get("pending_orders") or {}
    fills = state.setdefault("fills", [])
    cash = max(0.0, _num(state.get("cash")) or 0.0)
    fee = float(state.get("fee_per_side") or FEE_PER_SIDE)
    for side in ("sell", "buy"):
        for code in sorted(list(orders)):
            order = orders.get(code)
            if not order or order.get("side") != side:
                continue
            after = _date(order.get("eligible_after") or order.get("signal_fund_asof"))
            fill = next_nav(navs.get(code, []), after, market_asof)
            if not fill:
                order["status"] = "WAITING_FOR_NEXT_NAV"
                continue
            fill_date, nav = fill
            pos = (state.get("positions") or {}).get(code)
            current_units = max(0.0, _num((pos or {}).get("units")) or 0.0)
            target_units = max(0.0, _num(order.get("target_units")) or 0.0)
            delta = target_units - current_units
            if side == "sell":
                qty = min(current_units, max(0.0, -delta))
                if qty <= EPS or not pos:
                    orders.pop(code, None)
                    continue
                gross = qty * nav
                charge = gross * fee
                proceeds = gross - charge
                basis = max(0.0, _num(pos.get("cost_basis")) or 0.0)
                basis_piece = basis * qty / current_units if current_units else 0.0
                pos["units"] = max(0.0, current_units - qty)
                pos["cost_basis"] = max(0.0, basis - basis_piece)
                cash += proceeds
                fills.append({"date": fill_date, "code": code, "name": pos.get("name", code),
                              "side": "sell", "units": round(qty, 8), "nav": nav,
                              "gross": round(gross, 2), "fee": round(charge, 2),
                              "realized_pnl": round(proceeds - basis_piece, 2),
                              "signal_fund_asof": order.get("signal_fund_asof")})
                if pos["units"] <= EPS:
                    state["positions"].pop(code, None)
                current_after = max(0.0, _num((state.get("positions") or {}).get(code, {}).get("units")) or 0.0)
                if abs(target_units - current_after) <= EPS:
                    orders.pop(code, None)
                else:
                    order["eligible_after"] = fill_date
                    order["status"] = "PARTIAL_SELL_WAITING_NEXT_NAV"
            else:
                qty_need = max(0.0, delta)
                if qty_need <= EPS:
                    orders.pop(code, None)
                    continue
                affordable = cash / (nav * (1.0 + fee)) if nav > 0 else 0.0
                qty = min(qty_need, affordable)
                if qty <= EPS:
                    order["status"] = "WAITING_FOR_CASH_OR_NEXT_NAV"
                    continue
                gross = qty * nav
                charge = gross * fee
                cost = gross + charge
                cash -= cost
                positions = state.setdefault("positions", {})
                old = positions.get(code)
                old_units = max(0.0, _num((old or {}).get("units")) or 0.0)
                old_basis = max(0.0, _num((old or {}).get("cost_basis")) or 0.0)
                name = order.get("name") or state.get("names", {}).get(code) or code
                positions[code] = {
                    "code": code, "name": name, "units": old_units + qty,
                    "cost_basis": old_basis + cost,
                    "entry_date": (old or {}).get("entry_date") or fill_date,
                    "entry_nav": (old or {}).get("entry_nav") or nav,
                    "last_nav": nav, "last_nav_date": fill_date,
                }
                fills.append({"date": fill_date, "code": code, "name": name,
                              "side": "buy", "units": round(qty, 8), "nav": nav,
                              "gross": round(gross, 2), "fee": round(charge, 2),
                              "signal_fund_asof": order.get("signal_fund_asof")})
                current_after = old_units + qty
                if abs(target_units - current_after) <= EPS:
                    orders.pop(code, None)
                else:
                    order["eligible_after"] = fill_date
                    order["status"] = "PARTIAL_BUY_WAITING_NEXT_NAV"
    state["cash"] = round(max(0.0, cash), 6)
    state["pending_orders"] = orders
    state["fills"] = fills[-2000:]


def step(state: dict | None, pool: dict, navs: dict[str, list[tuple[str, float]]],
         market_asof: str, started_at: str | None = None) -> dict:
    """Pure one-day state transition. Inject fixtures for tests; no disk access or writes."""
    market_asof = _date(market_asof)
    if not market_asof:
        raise ValueError("market_asof missing")
    if state is None:
        state = new_state(market_asof, started_at)
    if state.get("schema") != SCHEMA:
        raise ValueError("unexpected fund rotation state schema; refuse overwrite")
    pool_asof = _date(pool.get("as_of"))
    fresh = bool(pool_asof and pool_asof == market_asof)
    # Allow one same-day retry only when a previously stale source is now fresh.
    if (_date(state.get("last_market_asof")) == market_asof
            and not (state.get("status") == "SIGNAL_SOURCE_STALE" and fresh)):
        return state  # 同日重跑绝不重复记账
    codes = selected_codes(pool) if fresh else []
    same_target = state.get("target_codes") is not None and sorted(codes) == sorted(state.get("target_codes") or [])
    unpriced_ready = bool(state.get("unpriced_codes")) and any(
        _signal_nav(c, _date(pool.get("fund_as_of")) or pool_asof, navs, pool)
        for c in state.get("unpriced_codes", [])
    ) if fresh else False
    if fresh and (not same_target or unpriced_ready):
        _plan_target(state, pool, navs, market_asof)
    elif not fresh:
        state["status"] = "SIGNAL_SOURCE_STALE"
        state["status_note"] = (
            "short_pool.as_of=%s 与指数最新交易日=%s 不一致；忽略过期候选，不补做历史交易。"
            % (pool_asof or "缺失", market_asof))
        if pool_asof != state.get("last_stale_asof"):
            _event(state, market_asof, state["status_note"])
            state["last_stale_asof"] = pool_asof

    # 已由新鲜信号生成的待成交单可以继续等后续净值；陈旧池不产生新单。
    _fill_orders(state, navs, market_asof)
    row = _mark(state, navs, market_asof)
    if not fresh:
        state["status"] = "SIGNAL_SOURCE_STALE"
        state["status_note"] = "基金候选日期滞后；仅标记既有仓位/执行既有待成交单，不生成新交易。"
    elif state.get("pending_orders"):
        state["status"] = "WAITING_FOR_NEXT_NAV"
        state["status_note"] = "候选目标已记录；等 fund_as_of 之后首个可得净值成交，不用信号日净值补成交。"
    elif state.get("positions"):
        state["status"] = "ACTIVE"
        state["status_note"] = "持仓按最新可得净值标记；候选集合变化时按差额等权轮动。"
    else:
        state["status"] = "FLAT_NO_CANDIDATE"
        state["status_note"] = "当前空仓；种子 NAV 有效、累计收益显示 0.00%；无候选不伪造交易。"
    state["last_market_asof"] = market_asof
    state["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state["n_fills"] = len(state.get("fills") or [])
    state["n_positions"] = len(state.get("positions") or {})
    state["n_completed_trades"] = sum(1 for fill in state.get("fills", []) if fill.get("side") == "sell")
    state["latest_nav_date"] = row.get("latest_fund_nav_date") or market_asof
    return state


def read_index_asof(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("index calendar is empty")
    return _date(rows[-1].get("date") or rows[-1].get("日期"))


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


def load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema") != SCHEMA:
        raise ValueError("existing independent paper state has unexpected schema; refuse overwrite")
    return state


def run(pool_path: Path = POOL_PATH, nav_dir: Path = NAV_DIR, index_path: Path = INDEX_PATH,
        state_path: Path = STATE_PATH, dry_run: bool = False) -> dict:
    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    market_asof = read_index_asof(index_path)
    state = load_state(state_path)
    codes = set(selected_codes(pool))
    if state:
        codes.update((state.get("positions") or {}).keys())
        codes.update((state.get("pending_orders") or {}).keys())
    navs = load_nav_series(nav_dir, codes)
    state = step(state, pool, navs, market_asof)
    print("基金轮动纸面账本：pool_as_of=%s fund_as_of=%s market_asof=%s status=%s" %
          (_date(pool.get("as_of")) or "—", _date(pool.get("fund_as_of")) or "—",
           market_asof, state["status"]))
    print("  NAV=%.2f return=%+.2f%% cash=%.2f positions=%d fills=%d pending=%d" %
          (state["nav"], state["cum_return_pct"], state["cash"], state["n_positions"],
           state["n_fills"], len(state.get("pending_orders") or {})))
    print("  note:", state["status_note"])
    if not dry_run:
        atomic_save(state_path, state)
        print("  wrote independent state:", state_path)
    else:
        print("  dry-run: no file written")
    return state


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="基金轮动独立纸面账本（不复用 FB3 fund_paper.json）")
    ap.add_argument("--pool", type=Path, default=POOL_PATH)
    ap.add_argument("--nav-dir", type=Path, default=NAV_DIR)
    ap.add_argument("--index", type=Path, default=INDEX_PATH)
    ap.add_argument("--state", type=Path, default=STATE_PATH)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    run(args.pool, args.nav_dir, args.index, args.state, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
