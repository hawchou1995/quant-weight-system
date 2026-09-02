# -*- coding: utf-8 -*-
"""2026-09-02 补数失败清单重试（westock CLI 逐批重试 3 次 → 合并 data_full）
失败清单来自 _backfill_westock_0902.py 输出 data_full_fail_list.csv
"""
import json, re, subprocess, sys, time
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
WS = Path(r"C:/Users/Admin/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/westock-data/scripts/index.js")
ROW = re.compile(r"\| ([a-z]{2}\w+) \| (\d{4}-\d{2}-\d{2}) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d.eE+]+) \| ([\d.eE+]+) \|")


def call_westock(syms, limit=8):
    cmd = ["node", str(WS), "kline", ",".join(syms), "--period", "day",
           "--limit", str(limit), "--fq", "qfq"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
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
        out.setdefault(sym, []).append([d, float(o), float(last), float(h), float(l), float(v), float(amt)])
    return out


def main():
    t0 = time.time()
    fails = [ln.strip().split(",")[0] for ln in
             (BASE / "data_full_fail_list.csv").read_text(encoding="utf-8").splitlines()[1:]
             if ln.strip().split(",")[0]]
    print(f"失败清单 {len(fails)} 只，重试中...", flush=True)
    got = {}
    still = []
    for i in range(0, len(fails), 50):
        grp = fails[i:i + 50]
        ok = False
        for attempt in range(3):
            try:
                txt = call_westock(grp)
                parsed = parse(txt)
                got.update(parsed)
                miss = [s for s in grp if s not in parsed]
                still += miss
                ok = True
                break
            except Exception as e:
                if attempt == 2:
                    still += grp
                    print(f"  [批 {i//50}] 失败: {repr(e)[:60]}", flush=True)
        if not ok and i // 50 % 10 == 0:
            print(f"  [{i+len(grp)}/{len(fails)}] 已恢复 {len(got)}", flush=True)
        if i % 500 == 0:
            print(f"  [{i}/{len(fails)}] 已恢复 {len(got)} 耗时 {time.time()-t0:.0f}s", flush=True)
    dump_f = BASE / "westock_dump_2026-09-02_retry.json"
    json.dump(got, open(dump_f, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"重试成功 {len(got)} 只，仍失败 {len(still)} 只 → {dump_f.name}", flush=True)
    if still:
        pd.DataFrame([(s, "", "westock", "miss") for s in still],
                     columns=["sym", "name", "src", "err"]).to_csv(BASE / "data_full_fail_list2.csv", index=False)
        print(f"仍失败清单: {still[:30]}... (共 {len(still)})", flush=True)
    # 合并
    r = subprocess.run([sys.executable, str(BASE / "fetch_close_westock.py"),
                        "--dump", str(dump_f)], capture_output=True, text=True)
    print(r.stdout[-2500:])
    if r.stderr:
        print("STDERR:", r.stderr[-1000:])


if __name__ == "__main__":
    main()
