# -*- coding: utf-8 -*-
"""2026-08-31 westock 全市场补数（新浪/腾讯qfq/akshare hist_tx 全滞后时使用）
====================================================================
- 扫描 data_full 尾部日期 < 2026-08-31 的文件 → 滞后清单
- 分批调用 westock CLI kline（50 只/批，每只 8 行）→ 解析 markdown
- dump 行序 = [date, open, last, high, low, volume, amount]（westock 原生序，last=收盘价）
  ⚠ 与 fetch_close_westock.py WESTOCK_COLS 一致（08-21 修复后口径），勿用旧 [date,open,high,low,close] 序
- 自动调 fetch_close_westock.py --dump 合并进 data_full
"""
import json, os, re, subprocess, sys, time
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
OUT = BASE / "data_full"
WS = Path(r"C:/Users/Admin/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/westock-data/scripts/index.js")
TARGET = "2026-08-31"
DUMP = BASE / f"westock_dump_{TARGET}.json"

ROW = re.compile(r"\| ([a-z]{2}\w+) \| (\d{4}-\d{2}-\d{2}) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d.eE+]+) \| ([\d.eE+]+) \|")


def tail_date(f):
    try:
        with open(f, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 2048))
            tail = fh.read().decode("utf-8", errors="ignore")
        lines = [ln for ln in tail.strip().splitlines() if ln.strip()]
        return lines[-1].split(",")[0].strip() if lines else None
    except Exception:
        return None


def scan_lag():
    lag = []
    for f in sorted(OUT.glob("*.csv")):
        if f.stat().st_size < 100:
            continue
        td = tail_date(f)
        if td is None:
            continue
        if td < TARGET:
            lag.append(f.stem)
    return lag


def call_westock(syms, limit=8):
    cmd = ["node", str(WS), "kline", ",".join(syms), "--period", "day",
           "--limit", str(limit), "--fq", "qfq"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.stdout


def parse(text):
    out = {}
    got_header = False
    for ln in text.splitlines():
        s = ln.strip()
        if "| symbol |" in s and "| date |" in s:
            got_header = True
            continue
        if not got_header:
            continue
        if s.startswith("|---"):
            continue
        if not s.startswith("|"):
            continue
        m = ROW.match(s)
        if not m:
            continue
        sym, d, o, last, h, l, v, amt = m.groups()
        # ⚠ 行序 = [date, open, last, high, low, volume, amount]（westock 原生序，last=收盘价）
        out.setdefault(sym, []).append([d, float(o), float(last), float(h), float(l), float(v), float(amt)])
    return out


def main():
    t0 = time.time()
    lag = scan_lag()
    print(f"滞后清单 {len(lag)} 只（尾部 < {TARGET}）", flush=True)
    batch = 50
    all_rows = {}
    fails = []
    for i in range(0, len(lag), batch):
        grp = lag[i:i + batch]
        for attempt in range(3):
            try:
                txt = call_westock(grp)
                parsed = parse(txt)
                all_rows.update(parsed)
                miss = [s for s in grp if s not in parsed]
                if miss:
                    fails += miss
                break
            except Exception as e:
                if attempt == 2:
                    fails += grp
                    print(f"  [批 {i//batch}] 失败: {repr(e)[:80]}", flush=True)
        if (i // batch) % 20 == 0 or i + batch >= len(lag):
            print(f"  [{i+len(grp)}/{len(lag)}] 已覆盖 {len(all_rows)} 只，耗时 {time.time()-t0:.0f}s", flush=True)
    dump = {k: v for k, v in all_rows.items() if v}
    json.dump(dump, open(DUMP, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"dump 写入 {DUMP}: {len(dump)} 只 | 失败 {len(fails)} 只（{fails[:8]}…） 耗时 {time.time()-t0:.0f}s", flush=True)
    if fails:
        pd.DataFrame([(s, "", "westock", "miss") for s in fails], columns=["sym", "name", "src", "err"]).to_csv(
            BASE / "data_full_fail_list.csv", index=False)
    # 合并进 data_full
    r = subprocess.run([sys.executable, str(BASE / "fetch_close_westock.py"),
                        "--dump", str(DUMP)], capture_output=True, text=True)
    print(r.stdout[-3000:])
    if r.stderr:
        print("STDERR:", r.stderr[-1500:])


if __name__ == "__main__":
    main()
