# -*- coding: utf-8 -*-
"""定向补齐 77 只活跃滞后至 08-20（westock CLI 批量，2026-08-21 沉淀）
====================================================================
背景：TX 4 并发 77/77 全灭（限流未恢复）；TDX MCP 逐只太慢。
方案：westock CLI kline 批量（50 只/批 ~1s）→ 解析 markdown → 过滤 date<=2026-08-20
（排除今日 08-21 盘中不完整行）→ 合并进 data_full（keep=last 覆盖当日根）。

用法：
  python fill_active_77_westock.py [--lag data_lag_active.csv] [--limit 8] [--batch 50]
"""
import json, re, subprocess, sys, time
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
WS = Path(r"C:/Users/Admin/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/westock-data/scripts/index.js")
LAG_DEFAULT = BASE / "data_lag_active.csv"
DUMP = BASE / "westock_dump_active77.json"
MAX_DATE = "2026-08-20"  # 目标最新交易日（排除今日盘中不完整行）

ROW = re.compile(r"\| ([a-z]{2}\w+) \| (\d{4}-\d{2}-\d{2}) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d.eE+]+) \| ([\d.eE+]+) \|")


def call_westock(syms: list, limit: int) -> str:
    cmd = ["node", str(WS), "kline", ",".join(syms), "--period", "day",
           "--limit", str(limit), "--fq", "qfq"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.stdout


def parse(text: str):
    """解析 markdown 表 → {sym: [[date,open,high,low,close,volume,amount], ...]} 升序
    只保留 date <= MAX_DATE 的行（排除今日盘中不完整行）。"""
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
        if d > MAX_DATE:
            continue  # 排除 08-21 盘中不完整行
        cur = out.setdefault(sym, [])
        cur.append((d, float(o), float(h), float(l), float(last), float(v), float(amt)))
    for sym, rows in out.items():
        rows.sort(key=lambda x: x[0])
        out[sym] = [list(r) for r in rows]
    return out


def merge_sym(sym, rows):
    """与本地合并去重（keep=last 覆盖当日根）"""
    COLS = ["date", "open", "high", "low", "close", "volume", "amount"]
    df = pd.DataFrame(rows, columns=COLS)
    df["date"] = df["date"].astype(str)
    f = BASE / "data_full" / f"{sym}.csv"
    if not f.exists():
        print(f"  ⚠ {sym} 本地无文件，跳过", flush=True)
        return False
    old = pd.read_csv(f, dtype={"date": str})
    merged = pd.concat([old, df]).drop_duplicates(subset="date", keep="last")
    merged = merged.sort_values("date").reset_index(drop=True)
    merged.to_csv(f, index=False)
    return True


def main():
    t0 = time.time()
    lag_f = Path(sys.argv[sys.argv.index("--lag") + 1]) if "--lag" in sys.argv else LAG_DEFAULT
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 8
    batch = int(sys.argv[sys.argv.index("--batch") + 1]) if "--batch" in sys.argv else 50
    lag = [ln.strip().split(",")[0] for ln in open(lag_f, encoding="utf-8").read().splitlines() if ln.strip()]
    print(f"待补 {len(lag)} 只 | 每只取 {limit} 行 | 每批 {batch} 只 | 目标日期 <= {MAX_DATE}", flush=True)

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
        if (i // batch) % 10 == 0 or i + batch >= len(lag):
            print(f"  [{i+len(grp)}/{len(lag)}] 已覆盖 {len(all_rows)} 只，耗时 {time.time()-t0:.0f}s", flush=True)

    dump = {k: v for k, v in all_rows.items() if v}
    json.dump(dump, open(DUMP, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"dump 写入 {DUMP}: {len(dump)} 只 | 失败 {len(fails)} 只（{fails[:8]}…）", flush=True)

    # 合并进 data_full
    ok = 0
    for sym, rows in dump.items():
        if merge_sym(sym, rows):
            ok += 1
    print(f"✅ 合并完成：成功 {ok} / dump {len(dump)}，总耗时 {(time.time()-t0)/60:.1f} 分钟", flush=True)
    if fails:
        Path(BASE / "data_full_fail_77_ws.csv").write_text("\n".join(fails), encoding="utf-8")
        print("失败清单:", fails[:20], flush=True)


if __name__ == "__main__":
    main()
