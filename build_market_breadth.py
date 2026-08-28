# -*- coding: utf-8 -*-
"""
市场情绪晴雨表数据采样器（照抄 kunkundi/niuone tencent_market_breadth.py 口径）
================================================================================
数据源：https://qt.gtimg.cn/q=代码,代码,...（腾讯证券沪深A股实时行情，批量接口）
统计口径（与 niuone 一致）：
  red/green/flat  = 按涨跌幅正负统计红绿平盘家数
  limit_up        = price >= upper_limit 封板家数
  broken_limit    = high >= upper_limit 但未封板（触板回落=炸板）
  limit_down      = price <= lower_limit
  turnover_yi     = Σ(成交额万)/10000 → 亿元
代码空间：sz 000001-003999 + sz 300001-301999 + sh 600000-605999 + sh 688000-689999
          （过滤 (?:60|68|00|30)[0-9]{4}，不含北交所/ST 不剔——niuone 口径）

用法：
  python build_market_breadth.py [--output market_breadth.js] [--append] [--ts HH:MM]
      单次采样：--append 追加到 timeline，无则覆盖
  python build_market_breadth.py --daemon
      守护模式：交易时段（9:30-11:30 / 13:00-15:00）每 30s 采样一次，非交易时段休眠
输出：window.MARKET_BREADTH = {date, meta, latest, timeline, turnover_comparison}
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import Request, urlopen

CN_TZ = dt.timezone(dt.timedelta(hours=8))
SOURCE_NAME = "腾讯证券沪深A股实时行情"
SOURCE_URL = "https://gu.qq.com/"
UNIVERSE_LABEL = "沪深A股（含ST，不含B股、北交所及无有效现价证券）"
DEFAULT_MIN_ROWS = 4_000
DEFAULT_DEADLINE_SECONDS = 25
DEFAULT_WORKERS = 10
DEFAULT_CHUNK_SIZE = 200
BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUTPUT = BASE_DIR / "market_breadth.js"

_QUOTE_URL = "https://qt.gtimg.cn/q="


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(os.environ.get(name, str(default)) or str(default))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def symbols() -> list[str]:
    """Return the bounded Shanghai/Shenzhen code space used by Tencent quotes."""
    return (
        [f"sz{i:06d}" for i in range(1, 4_000)]
        + [f"sz{i:06d}" for i in range(300_001, 302_000)]
        + [f"sh{i:06d}" for i in range(600_000, 606_000)]
        + [f"sh{i:06d}" for i in range(688_000, 690_000)]
    )


def _finite_float(value):
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if (number == number) and abs(number) < 1e15 else None  # 非 NaN


def _download_chunk(symbols_chunk: list[str], timeout: float) -> str:
    request = Request(
        _QUOTE_URL + ",".join(symbols_chunk),
        headers={
            "User-Agent": "Mozilla/5.0 NiuOne/1.0",
            "Referer": "https://stock.qq.com/",
            "Connection": "close",
        },
    )
    with urlopen(request, timeout=max(1.0, timeout)) as response:
        body = response.read().decode("gbk", errors="replace")
    return body


def _quote_timestamp(value) -> int:
    """Tencent quote timestamp like 20260828161402 -> epoch seconds (CN)."""
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{14}", text):
        return 0
    try:
        naive = dt.datetime.strptime(text, "%Y%m%d%H%M%S")
    except ValueError:
        return 0
    return int(naive.replace(tzinfo=CN_TZ).timestamp())


def parse_quote_body(body: str) -> list[dict]:
    """Parse fields needed for breadth, limit-board, and turnover statistics."""
    rows: list[dict] = []
    for raw in str(body or "").split(";"):
        match = re.search(r'="(.*)"', raw, re.S)
        if not match:
            continue
        fields = match.group(1).split("~")
        if len(fields) < 49:
            continue
        code = str(fields[2] or "").strip()
        if not re.fullmatch(r"(?:60|68|00|30)\d{4}", code):
            continue
        price = _finite_float(fields[3])
        prev_close = _finite_float(fields[4])
        high = _finite_float(fields[33])
        low = _finite_float(fields[34])
        upper_limit = _finite_float(fields[47])
        lower_limit = _finite_float(fields[48])
        if price is None or prev_close is None or price <= 0 or prev_close <= 0:
            continue
        pct = _finite_float(fields[32])
        if pct is None:
            pct = (price / prev_close - 1) * 100
        turnover_amount_wan = _finite_float(fields[37])
        if turnover_amount_wan is not None and turnover_amount_wan < 0:
            turnover_amount_wan = None
        rows.append({
            "symbol": ("sh" if code.startswith("6") else "sz") + code,
            "code": code,
            "name": str(fields[1] or "").strip(),
            "price": price,
            "prev_close": prev_close,
            "pct": pct,
            "high": high,
            "low": low,
            "upper_limit": upper_limit,
            "lower_limit": lower_limit,
            "quote_ts": _quote_timestamp(fields[30]),
            "turnover_amount_wan": turnover_amount_wan,
        })
    return rows


def summarize_market_breadth(rows: list[dict]) -> dict:
    """Calculate breadth counts and market turnover from one quote snapshot."""
    deduplicated = {str(row.get("code") or ""): row for row in rows if str(row.get("code") or "")}
    quotes = list(deduplicated.values())
    red = green = flat = limit_up = limit_down = broken_limit = 0
    limit_price_count = 0
    turnover_amount_count = 0
    turnover_amount_wan = 0.0
    latest_quote_ts = 0
    for row in quotes:
        pct = _finite_float(row.get("pct"))
        if pct is not None and pct > 0:
            red += 1
        elif pct is not None and pct < 0:
            green += 1
        else:
            flat += 1

        price = _finite_float(row.get("price"))
        high = _finite_float(row.get("high"))
        upper_limit = _finite_float(row.get("upper_limit"))
        lower_limit = _finite_float(row.get("lower_limit"))
        if (price is not None and high is not None and upper_limit is not None
                and lower_limit is not None and upper_limit > 0 and lower_limit > 0):
            limit_price_count += 1
            if price >= upper_limit:
                limit_up += 1
            elif high >= upper_limit:
                broken_limit += 1
            if price <= lower_limit:
                limit_down += 1
        latest_quote_ts = max(latest_quote_ts, int(row.get("quote_ts") or 0))
        amount = _finite_float(row.get("turnover_amount_wan"))
        if amount is not None and amount >= 0:
            turnover_amount_count += 1
            turnover_amount_wan += amount

    generated = (dt.datetime.fromtimestamp(latest_quote_ts, tz=CN_TZ)
                 if latest_quote_ts > 0 else dt.datetime.now(CN_TZ))
    actual_turnover_yi = round(turnover_amount_wan / 10_000, 2)
    return {
        "schema_version": 1,
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "universe": UNIVERSE_LABEL,
        "generated_at": generated.strftime("%Y-%m-%d %H:%M:%S"),
        "quote_count": len(quotes),
        "limit_price_count": limit_price_count,
        "turnover_amount_count": turnover_amount_count,
        "actual_turnover_yi": actual_turnover_yi,
        "red": red,
        "green": green,
        "flat": flat,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "broken_limit": broken_limit,
    }


def fetch_breadth_snapshot(min_rows: int = DEFAULT_MIN_ROWS,
                           deadline_seconds: int = DEFAULT_DEADLINE_SECONDS,
                           workers: int = DEFAULT_WORKERS,
                           chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict:
    """Fetch full-market snapshot and return breadth summary."""
    all_symbols = symbols()
    chunks = [all_symbols[i:i + chunk_size] for i in range(0, len(all_symbols), chunk_size)]
    rows: list[dict] = []
    deadline = time.monotonic() + max(1, deadline_seconds)
    attempts = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_download_chunk, c, max(2.0, deadline - time.monotonic())): c for c in chunks}
        for fut in as_completed(futures):
            attempts += 1
            try:
                body = fut.result()
                rows.extend(parse_quote_body(body))
            except Exception:
                pass  # 单块失败跳过，保留其余块
            if len(rows) >= min_rows:
                # 数据够了就取消剩余任务
                for f in futures:
                    f.cancel()
                break
    summary = summarize_market_breadth(rows)
    summary["attempted_chunks"] = attempts
    return summary


def is_trading_session(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now(CN_TZ)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return (9 * 60 + 30 <= minutes <= 11 * 60 + 30) or (13 * 60 <= minutes <= 15 * 60)


def timeline_entry(summary: dict, now: dt.datetime) -> dict:
    return {
        "t": now.strftime("%H:%M"),
        "red": summary.get("red", 0),
        "green": summary.get("green", 0),
        "flat": summary.get("flat", 0),
        "limit_up": summary.get("limit_up", 0),
        "limit_down": summary.get("limit_down", 0),
        "broken_limit": summary.get("broken_limit", 0),
        "turnover_yi": summary.get("actual_turnover_yi", 0),
        "quote_count": summary.get("quote_count", 0),
    }


def load_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    match = re.search(r"window\.MARKET_BREADTH\s*=\s*(\{.*?\});?\s*$", text, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def write_js(path: Path, payload: dict) -> None:
    path.write_text(f"window.MARKET_BREADTH = {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))};",
                    encoding="utf-8")


def run_once(output: Path, append: bool, ts_label: str | None = None, quiet: bool = False) -> dict:
    now = dt.datetime.now(CN_TZ)
    summary = fetch_breadth_snapshot()
    entry = timeline_entry(summary, now)
    if ts_label:
        entry["t"] = ts_label
    payload = load_existing(output) if append else {}
    payload.update({
        "date": now.strftime("%Y-%m-%d"),
        "meta": {
            "as_of": now.strftime("%Y-%m-%d"),
            "ts": ts_label or now.strftime("%H:%M"),
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "source": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "universe": UNIVERSE_LABEL,
            "mode": "intraday" if is_trading_session(now) else "close",
        },
        "latest": {
            "red": summary.get("red", 0),
            "green": summary.get("green", 0),
            "flat": summary.get("flat", 0),
            "limit_up": summary.get("limit_up", 0),
            "limit_down": summary.get("limit_down", 0),
            "broken_limit": summary.get("broken_limit", 0),
            "turnover_yi": summary.get("actual_turnover_yi", 0),
            "quote_count": summary.get("quote_count", 0),
            "generated_at": summary.get("generated_at", ""),
        },
    })
    timeline = payload.get("timeline", [])
    timeline = [e for e in timeline if e.get("t") != entry["t"]]
    timeline.append(entry)
    timeline.sort(key=lambda e: e.get("t", ""))
    # 同日只保留当日曲线
    payload["timeline"] = [e for e in timeline]
    payload["meta"]["points"] = len(payload["timeline"])
    write_js(output, payload)
    if not quiet:
        print(json.dumps(entry, ensure_ascii=False))
    return summary


def run_daemon(output: Path) -> None:
    print(f"[daemon] 市场情绪采样守护启动 · 输出 {output} · 交易时段每 30s 采样", flush=True)
    while True:
        try:
            if is_trading_session():
                summary = run_once(output, append=True, quiet=True)
                print(f"[{dt.datetime.now(CN_TZ).strftime('%H:%M:%S')}] 采样 ok "
                      f"红{summary.get('red')}/绿{summary.get('green')}/涨跌停"
                      f"{summary.get('limit_up')}/{summary.get('limit_down')} "
                      f"量能{summary.get('actual_turnover_yi')}亿 · {summary.get('quote_count')}只", flush=True)
            else:
                print(f"[{dt.datetime.now(CN_TZ).strftime('%H:%M:%S')}] 非交易时段，休眠 60s", flush=True)
                time.sleep(60)
                continue
        except KeyboardInterrupt:
            print("[daemon] 停止", flush=True)
            break
        except Exception as exc:
            print(f"[daemon] 采样异常 {type(exc).__name__}: {exc}，30s 后重试", flush=True)
        time.sleep(30)


def main() -> None:
    args = sys.argv[1:]
    output = DEFAULT_OUTPUT
    append = "--append" in args
    daemon = "--daemon" in args
    ts_label = None
    for i, arg in enumerate(args):
        if arg == "--output" and i + 1 < len(args):
            output = Path(args[i + 1])
        if arg == "--ts" and i + 1 < len(args):
            ts_label = args[i + 1]
    if daemon:
        run_daemon(output)
    else:
        run_once(output, append=append, ts_label=ts_label)


if __name__ == "__main__":
    main()
