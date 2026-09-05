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
import statistics
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
        # 买一价/买一量（腾讯行情体标准索引：fields[9]=买一价, fields[10]=买一量(手)）
        # 实证确认见 _verify_bid_fields.py（sh600000 / 涨停股对照）。
        bid1_price = _finite_float(fields[9])
        bid1_vol = _finite_float(fields[10])
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
            "bid1_price": bid1_price,
            "bid1_vol": bid1_vol,
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
    # 情绪聚合（对 limit_up 行）：封单强度
    seal_wans = []
    seal_ratios = []
    total_seal_wan = 0.0
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
                # 封单强度：买一价 × 买一量(手) × 100(股/手) → 元 → /1e4 → 万元/只
                bp = _finite_float(row.get("bid1_price"))
                bv = _finite_float(row.get("bid1_vol"))
                ta = _finite_float(row.get("turnover_amount_wan"))
                if bp is not None and bv is not None and bv > 0:
                    seal_wan = bp * bv * 100 / 1e4
                    total_seal_wan += seal_wan
                    seal_wans.append(seal_wan)
                    if ta is not None:
                        seal_ratios.append(seal_wan / max(1, ta))
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
    # ---- 情绪聚合（涨停封单强度作为市场情绪特征）----
    total_seal_yi = round(total_seal_wan / 1e4, 2)
    median_seal_ratio = round(statistics.median(seal_ratios), 2) if seal_ratios else 0.0
    zt_ratio = round(limit_up / max(1, limit_price_count) * 100, 2)
    broken_rate = round(broken_limit / max(1, limit_up + broken_limit) * 100, 2)
    if zt_ratio >= 1.2:
        sentiment_zone = "亢奋"
    elif zt_ratio >= 0.7:
        sentiment_zone = "活跃"
    elif zt_ratio >= 0.35:
        sentiment_zone = "中性"
    elif zt_ratio >= 0.15:
        sentiment_zone = "低迷"
    else:
        sentiment_zone = "冰点"
    sentiment = {
        "zone": sentiment_zone,
        "zt_ratio": zt_ratio,
        "broken_rate": broken_rate,
        "total_seal_yi": total_seal_yi,
        "median_seal_ratio": median_seal_ratio,
        # 连板高度盘中不计算（收盘由 compute_lianban 填充），缺省 0
        "lianban_max": 0,
        "lianban_count": 0,
        "lianban_top": [],
    }
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
        "sentiment": sentiment,
    }


def _tail_rows_lianban(path: Path, n: int = 11) -> list[dict]:
    """快速读 data_full/*.csv 尾部 n 行（date,open,high,low,close,volume,amount）。

    参照 update_daily.py 的 _tail_rows：open 后 seek 末尾读几 KB，避免全文件加载。
    返回最后 n 个交易日的 dict 列表（含列名映射）；不足则有多少返多少。
    """
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 4096))
            tail = fh.read().decode("utf-8", errors="ignore")
    except Exception:
        return []
    lines = [ln for ln in tail.strip().splitlines() if ln.strip()]
    # 首行可能是表头（含 'date'）；若是则从第二行起作为数据
    if lines and lines[0].strip().lower().startswith("date"):
        lines = lines[1:]
    out = []
    for ln in lines[-n:]:
        p = ln.split(",")
        if len(p) < 7:
            continue
        try:
            out.append({
                "date": p[0].strip(),
                "open": float(p[1]), "high": float(p[2]),
                "low": float(p[3]), "close": float(p[4]),
                "volume": float(p[5]), "amount": float(p[6]),
            })
        except ValueError:
            continue
    return out


def _is_limit_up_day(code: str, row: dict, prev_close: float) -> bool:
    """单日是否涨停（连板判定用）：收盘价≈最高价 且 涨幅达阈值 且 有成交量。"""
    if prev_close <= 0 or row.get("volume", 0) <= 0:
        return False
    if not (row.get("close", 0) >= row.get("high", 0) * 0.9999):
        return False
    pct = row["close"] / prev_close - 1
    # sh60/sz00 → ≥9.8%；sz30/sh68 → ≥19.8%（创业板/科创板 20% 涨跌幅）
    if code.startswith("30") or code.startswith("68"):
        return pct >= 0.198
    return pct >= 0.098


def compute_lianban(today: str, top: int = 5) -> dict:
    """计算连板高度（收盘用）。

    读 data_full/*.csv 仅尾部 10 行：从尾行向前数连续涨停行数即连板数。
    只统计尾行日期 == today（以市场快照 quote_ts 的日期为准）的股票，否则该股连板记 0（防陈旧数据）。
    返回 {lianban_max, lianban_count, lianban_top:[{code,streak} 最多 top 条]}。
    """
    data_dir = BASE_DIR / "data_full"
    if not data_dir.exists():
        return {"lianban_max": 0, "lianban_count": 0, "lianban_top": []}
    results = []
    for path in data_dir.glob("*.csv"):
        stem = path.stem
        # 文件名形如 sh600000.csv / sz300001.csv（带 sh/sz 前缀），归一为 6 位代码
        m = re.match(r"^(?:sh|sz)?(\d{6})$", stem)
        if not m:
            continue
        code = m.group(1)
        if not re.fullmatch(r"(?:60|68|00|30)\d{4}", code):
            continue
        rows = _tail_rows_lianban(path, n=11)
        if not rows:
            continue
        # 尾行（最新交易日）日期必须与快照日期一致，否则视为陈旧数据，连板记 0
        if rows[-1].get("date") != today:
            continue
        # 评估 rows[1:]（每行用前一行的 close 作 prev_close），从尾行向前连续计涨停
        evaluable = rows[1:]
        streak = 0
        for i in range(len(evaluable) - 1, -1, -1):
            r = evaluable[i]
            prev = evaluable[i - 1]["close"] if i > 0 else rows[0]["close"]
            if _is_limit_up_day(code, r, prev):
                streak += 1
            else:
                break
        if streak >= 2:
            results.append((code, streak))
    results.sort(key=lambda x: (-x[1], x[0]))
    lianban_max = max((s for _, s in results), default=0)
    lianban_count = len(results)
    lianban_top = [{"code": c, "streak": s} for c, s in results[:top]]
    return {"lianban_max": lianban_max, "lianban_count": lianban_count, "lianban_top": lianban_top}


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
    sent = summary.get("sentiment") or {}
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
        # 情绪（盘中可得）
        "seal_yi": sent.get("total_seal_yi", 0),
        "zt_ratio": sent.get("zt_ratio", 0),
        "broken_rate": sent.get("broken_rate", 0),
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
    # 收盘/非交易时段：填充连板高度（盘中不计算，保持 0）
    if not is_trading_session(now):
        today = (summary.get("generated_at") or "")[:10] or now.strftime("%Y-%m-%d")
        try:
            lb = compute_lianban(today)
            sent = summary.setdefault("sentiment", {})
            sent["lianban_max"] = lb["lianban_max"]
            sent["lianban_count"] = lb["lianban_count"]
            sent["lianban_top"] = lb["lianban_top"]
        except Exception:
            pass
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
            "sentiment": summary.get("sentiment", {}),
        },
        "sentiment": summary.get("sentiment", {}),
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
