# -*- coding: utf-8 -*-
"""westock 收盘降级补数（多源自动降级的执行端，2026-08-19 沉淀为可复用脚本）
====================================================================
背景：新浪/腾讯源都失效（或 agent 判断需双源核验）时，用 westock MCP data_kline 补齐
data_full 的当日收盘，替代 8/19 一次性脚本 _backfill_0819_close.py。

用法（两步）：
1) agent 用 westock MCP data_kline 拉取代码清单的日K（多码批量超限会自动落盘
   tool-results/*.txt，re+json 解析；也可逐个拉）→ 整理为 dump JSON：
   {"sh600498": [["2026-08-19",39.5,37.35,39.97,37.01,850587,3274091599], ...],
    "sz002185": [...], ...}
   ⚠ westock 行序 = [date, open, last, high, low, volume, amount]，最新在前；last=收盘价！
2) python fetch_close_westock.py --dump westock_dump_2026-08-19.json [--codes 滞后清单.txt]

--codes（可选）：update_daily.py 输出的 data_lag_list.csv 第 1 列 sym 清单；脚本会先打印
「仍需 westock 补数的代码」，再执行合并（dump 里没有的代码会标 ❌）。
"""
import sys, json, time
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
OUT = BASE / "data_full"
COLS = ["date", "open", "high", "low", "close", "volume", "amount"]


def merge_sym(sym, rows):
    """westock 行 → DataFrame → 与本地合并去重（keep=last 覆盖当日根）"""
    df = pd.DataFrame(rows, columns=COLS)
    df["date"] = df["date"].astype(str)
    f = OUT / f"{sym}.csv"
    if not f.exists():
        print(f"  ⚠ {sym} 本地无文件，跳过（新标的请走 fetch_full_universe 全量建库）", flush=True)
        return False
    old = pd.read_csv(f, dtype={"date": str})
    merged = pd.concat([old, df]).drop_duplicates(subset="date", keep="last")
    merged = merged.sort_values("date").reset_index(drop=True)
    merged.to_csv(f, index=False)
    return True


def main():
    t0 = time.time()
    args = sys.argv[1:]
    if "--dump" not in args:
        print(__doc__)
        return
    dump_f = Path(args[args.index("--dump") + 1])
    dump = json.load(open(dump_f, encoding="utf-8"))
    want = set()
    if "--codes" in args:
        codes_f = Path(args[args.index("--codes") + 1])
        for ln in codes_f.read_text(encoding="utf-8").splitlines():
            s = ln.split(",")[0].strip()
            if s:
                want.add(s)
    print(f"dump {len(dump)} 只标的历史行，目标清单 {len(want)} 只（--codes）", flush=True)
    if want:
        missing = sorted(want - set(dump))
        if missing:
            print(f"❌ 以下 {len(missing)} 只代码 dump 里没有，仍需 westock 拉取：{missing[:10]}{'…' if len(missing) > 10 else ''}", flush=True)
        print(f"   dump 覆盖清单内 {len(want & set(dump))} 只", flush=True)
    ok = 0
    for sym, rows in dump.items():
        if not rows:
            continue
        if merge_sym(sym, rows):
            ok += 1
            if ok % 10 == 0 or ok == len(dump):
                print(f"  [{ok}/{len(dump)}] {sym} → {rows[0][0]} 收盘 {rows[0][2]} ({time.time()-t0:.0f}s)", flush=True)
    print(f"✅ westock 补数完成：成功 {ok} / dump {len(dump)}，总耗时 {(time.time()-t0)/60:.1f} 分钟", flush=True)
    print("下一步：python build_enhanced_data.py && python build_short_pool.py && python build_dual_system.py 重建看板", flush=True)


if __name__ == "__main__":
    main()
