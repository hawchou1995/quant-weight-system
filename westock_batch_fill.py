# -*- coding: utf-8 -*-
"""westock 全市场批量补数（加速版，2026-08-20 沉淀）
====================================================================
背景：新浪/腾讯源单只串行补数 7421 只需 1-2 小时。westock MCP/CLI 支持批量 K 线，
50 只/批约 1s → 全市场 ~5 分钟可补齐最新交易日收盘。

用法：
  python westock_batch_fill.py [--lag data_lag_list.csv] [--limit N-rows-per-sym] [--batch 50]
     1) 读滞后清单（update_daily 生成的 data_lag_list.csv，第 1 列 sym）
     2) 分批调用 westock CLI kline（--period day --limit <每只行数> --fq qfq）
     3) 解析 markdown → dump JSON（sh/sz 行序 [date,open,close,high,low,volume,amount]）
     4) 自动调 fetch_close_westock.py --dump 合并进 data_full
  直接调用 fetch_close_westock.py 亦可（已含 merge 逻辑）。

westock kline 输出行（markdown 表）：
  | symbol | date | open | last | high | low | volume | amount | exchange |
  last = 收盘价；行序最新在前 → 需反转为升序并重排 [date,open,high,low,close,volume,amount]
"""
import json, os, re, subprocess, sys, time
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
WS = Path(r"C:/Users/XAUTHUB/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/westock-data/scripts/index.js")
LAG_DEFAULT = BASE / "data_lag_list.csv"
DUMP = BASE / "westock_dump_batch.json"

HDR = r"\| symbol \| date \| open \| last \| high \| low \| volume \| amount \| exchange \|"
ROW = re.compile(r"\| ([a-z]{2}\w+) \| (\d{4}-\d{2}-\d{2}) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d.eE+]+) \| ([\d.eE+]+) \|")


def call_westock(syms: list, limit: int) -> str:
    cmd = ["node", str(WS), "kline", ",".join(syms), "--period", "day",
           "--limit", str(limit), "--fq", "qfq"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.stdout


def parse(text: str):
    """解析 markdown 表 → {sym: [[date,open,high,low,close,volume,amount], ...]} 升序
    直接用 ROW 正则逐行匹配（不再依赖 HDR 表头 gate——表头只用于确认进入数据区）。"""
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
        cur = out.setdefault(sym, [])
        # 行序最新在前 → append 后统一反转成升序
        cur.append((d, float(o), float(h), float(l), float(last), float(v), float(amt)))
    for sym, rows in out.items():
        rows.sort(key=lambda x: x[0])  # 升序
        out[sym] = [list(r) for r in rows]
    return out


def main():
    t0 = time.time()
    lag_f = Path(sys.argv[sys.argv.index("--lag") + 1]) if "--lag" in sys.argv else LAG_DEFAULT
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 8
    batch = int(sys.argv[sys.argv.index("--batch") + 1]) if "--batch" in sys.argv else 50
    lag = pd.read_csv(lag_f, dtype=str)["sym"].tolist()
    print(f"滞后清单 {len(lag)} 只 | 每只取 {limit} 行 | 每批 {batch} 只", flush=True)

    all_rows = {}
    fails = []
    for i in range(0, len(lag), batch):
        grp = lag[i:i + batch]
        for attempt in range(3):
            try:
                txt = call_westock(grp, limit)
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
            BASE / "data_full_fail_list.csv", index=False if False else False)
    if sys.argv and "--merge" in sys.argv:
        r = subprocess.run([sys.executable, str(BASE / "fetch_close_westock.py"),
                            "--dump", str(DUMP)], capture_output=True, text=True)
        print(r.stdout)
        print(r.stderr[-1500:] if r.stderr else "")


if __name__ == "__main__":
    main()
