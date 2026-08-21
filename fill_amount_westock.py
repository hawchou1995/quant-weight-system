# -*- coding: utf-8 -*-
"""补齐 data_full 缺失的 amount 列（westock CLI 批量，2026-08-21 沉淀）
====================================================================
背景：腾讯源不含成交额 → data_full 自 2023-12 起 amount=0 → amt20 过滤杀光
v9_rank_board 候选（6989/7160 只近20日 amount=0，榜单空池）。
方案：westock CLI kline（含 amount）批量拉近 30 个交易日 → 只填 amount 列
（不动 OHLC，避免 qfq 复权口径差异）→ 过滤 date<=2026-08-20（排除今日盘中）。

用法：
  python fill_amount_westock.py [--limit 30] [--batch 50] [--max-date 2026-08-20]
"""
import json, re, subprocess, sys, time
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
WS = Path(r"C:/Users/Admin/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/westock-data/scripts/index.js")
MAX_DATE = "2026-08-20"

ROW = re.compile(r"\| ([a-z]{2}\w+) \| (\d{4}-\d{2}-\d{2}) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d.eE+]+) \| ([\d.eE+]+) \|")


def call_westock(syms: list, limit: int) -> str:
    cmd = ["node", str(WS), "kline", ",".join(syms), "--period", "day",
           "--limit", str(limit), "--fq", "qfq"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return r.stdout


def parse(text: str):
    """解析 markdown → {sym: {date: amount}}，只保留 date<=MAX_DATE"""
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
            continue
        out.setdefault(sym, {})[d] = float(amt)
    return out


def fill_amount(sym, amt_map):
    """只填 amount 列（本地 amount=0/NaN 的行），不动 OHLC"""
    f = BASE / "data_full" / f"{sym}.csv"
    if not f.exists():
        return False
    d = pd.read_csv(f, dtype={"date": str})
    mask = d["date"].isin(amt_map) & (d["amount"].fillna(0) == 0)
    if mask.any():
        d.loc[mask, "amount"] = d.loc[mask, "date"].map(amt_map)
        d.to_csv(f, index=False)
        return int(mask.sum())
    return 0


def main():
    t0 = time.time()
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 30
    batch = int(sys.argv[sys.argv.index("--batch") + 1]) if "--batch" in sys.argv else 50
    # 全部非 bj 标的
    syms = sorted([p.stem for p in (BASE / "data_full").glob("*.csv") if not p.stem.startswith("bj")])
    print(f"待补 amount {len(syms)} 只 | 每只取 {limit} 行 | 每批 {batch} 只 | 目标 <= {MAX_DATE}", flush=True)

    all_amt = {}
    fails = []
    for i in range(0, len(syms), batch):
        grp = syms[i:i + batch]
        for attempt in range(3):
            try:
                txt = call_westock(grp, limit)
                parsed = parse(txt)
                all_amt.update(parsed)
                miss = [s for s in grp if s not in parsed]
                if miss:
                    fails += miss
                break
            except Exception as e:
                if attempt == 2:
                    fails += grp
                    print(f"  [批 {i//batch}] 失败: {repr(e)[:80]}", flush=True)
        if (i // batch) % 20 == 0 or i + batch >= len(syms):
            print(f"  [{i+len(grp)}/{len(syms)}] 已覆盖 {len(all_amt)} 只，耗时 {time.time()-t0:.0f}s", flush=True)

    # 合并进 data_full（只填 amount）
    filled = 0
    filled_rows = 0
    for sym, amt_map in all_amt.items():
        n = fill_amount(sym, amt_map)
        if n is not False:
            filled += 1
            filled_rows += n
    print(f"✅ amount 补齐完成：覆盖 {filled}/{len(all_amt)} 只，填充 {filled_rows} 行，总耗时 {(time.time()-t0)/60:.1f} 分钟", flush=True)
    if fails:
        Path(BASE / "amount_fill_fail.csv").write_text("\n".join(fails), encoding="utf-8")
        print("失败:", fails[:20], flush=True)


if __name__ == "__main__":
    main()
