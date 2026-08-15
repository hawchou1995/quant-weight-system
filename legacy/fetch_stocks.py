# -*- coding: utf-8 -*-
"""Fetch daily kline for 13 stocks/ETFs via westock-data CLI, save as CSV."""
import subprocess, os, csv, re, sys

from config import WSTOCK_CLI as WS, DATA_DIR as OUT

# code -> (name, westock_code, type)
WATCHLIST = [
    ("300502", "新易盛", "sz300502", "股票"),
    ("300308", "中际旭创", "sz300308", "股票"),
    ("159516", "半导体设备ETF", "sz159516", "ETF"),
    ("600498", "烽火通信", "sh600498", "股票"),
    ("601138", "工业富联", "sh601138", "股票"),
    ("002463", "沪电股份", "sz002463", "股票"),
    ("002384", "东山精密", "sz002384", "股票"),
    ("600183", "生益科技", "sh600183", "股票"),
    ("300476", "胜宏科技", "sz300476", "股票"),
    ("603986", "兆易创新", "sh603986", "股票"),
    ("515880", "通信ETF", "sh515880", "ETF"),
    ("516150", "稀土ETF嘉实", "sh516150", "ETF"),
    ("560390", "电网设备ETF易方达", "sh560390", "ETF"),
]

def parse_markdown_table(text):
    """Parse westock-data markdown table output into list of dicts."""
    lines = [l for l in text.strip().splitlines() if l.strip()]
    if not lines or "|" not in lines[0]:
        return []
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:  # skip header + separator
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells)))
    return rows

def main():
    os.makedirs(OUT, exist_ok=True)
    for code, name, wcode, typ in WATCHLIST:
        out_path = os.path.join(OUT, f"{code}.csv")
        if os.path.exists(out_path) and os.path.getsize(out_path) > 100:
            print(f"SKIP {code} {name} (exists)")
            continue
        cmd = ["node", WS, "kline", wcode, "--period", "day", "--limit", "1000", "--fq", "qfq"]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        rows = parse_markdown_table(r.stdout)
        if not rows:
            print(f"FAIL {code} {name}: empty output, stderr={r.stderr[:200]}")
            continue
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["date", "open", "high", "low", "close", "volume", "amount"])
            for row in rows:
                # westock kline: date open last high low volume amount exchange
                date = row.get("date", "")
                open_ = row.get("open", "")
                high = row.get("high", "")
                low = row.get("low", "")
                close = row.get("last", row.get("close", ""))
                volume = row.get("volume", "")
                amount = row.get("amount", "")
                w.writerow([date, open_, high, low, close, volume, amount])
        print(f"OK {code} {name}: {len(rows)} bars -> {out_path}")

if __name__ == "__main__":
    main()
