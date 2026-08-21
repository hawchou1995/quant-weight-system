# -*- coding: utf-8 -*-
"""定向补齐 77 只活跃滞后（tail>=08-17 且非bj）至 08-20
TX 4 并发 + 0.4s 节流；失败清单落盘，供 TDX MCP 兜底。
"""
import sys, time
sys.path.insert(0, r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import update_daily as U

BASE = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
syms = [ln.strip() for ln in open(BASE / "data_lag_active.csv", encoding="utf-8").read().splitlines() if ln.strip()]
print(f"[fill77] 待补 {len(syms)} 只 sample {syms[:6]}", flush=True)

t0 = time.time(); ok = 0; fails = []; done = 0

def job(sym):
    for _ in range(3):
        try:
            df = U.fetch_tx_qfq(sym)
            if df is not None and len(df) > 0:
                last = str(df["date"].iloc[-1])
                if last >= "2026-08-20":
                    U.merge_save(sym, df, "")
                    return (True, last)
                return (False, f"tx-last={last}")
            time.sleep(0.7)
        except Exception:
            time.sleep(0.9)
    return (False, "tx-fail")

with ThreadPoolExecutor(max_workers=4) as ex:
    futs = {ex.submit(job, s): s for s in syms}
    for fut in as_completed(futs):
        sym = futs[fut]
        done += 1
        success, tag = fut.result()
        if success:
            ok += 1
        else:
            fails.append(f"{sym},{tag}")
        if done % 20 == 0 or done == len(syms):
            print(f"  [{done}/{len(syms)}] ok={ok} fail={len(fails)} elapsed={(time.time()-t0)/60:.1f}min", flush=True)
        time.sleep(0.4)

print(f"✅ fill77 完成 ok={ok}/{len(syms)} 失败{len(fails)} 耗时{(time.time()-t0)/60:.1f}分", flush=True)
if fails:
    Path(BASE / "data_full_fail_77.csv").write_text("\n".join(fails), encoding="utf-8")
    print("失败:", fails[:20], flush=True)
