# -*- coding: utf-8 -*-
"""08-21 全量补数重试：akshare 腾讯历史接口（stock_zh_a_hist_tx）增量补齐滞后股票
背景：full_refresh_tx_concurrent.py 24 并发把 web.ifzq.gtimg.cn 打 WAF 限流（501），
      akshare 封装的 hist_tx 走不同域名未受限，实测 sh600008/sh600010/sz000001 均返回 08-21。
用法: python retry_hist_tx_0821.py [--workers 6]
"""
import sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

BASE = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
sys.path.insert(0, str(BASE))
import update_daily as U
import fetch_full_universe as F

TARGET = "2026-08-24"
workers = 6
if "--workers" in sys.argv:
    workers = int(sys.argv[sys.argv.index("--workers") + 1])

# 1. 扫描滞后（排除 bj 北交所 + sh5/sz1 ETF——选股本就排除）
lag = U.scan_lag(TARGET)
stocks = [s for s, _, _, _ in lag if not s.startswith(("bj", "sh5", "sz1"))]
print(f"[hist_tx] 待补真实股票 {len(stocks)} 只（目标 {TARGET}），并发 {workers}", flush=True)
if not stocks:
    print("全部到位"); sys.exit(0)

import akshare as ak

t0 = time.time()
ok = 0
fail = []
done = 0
total = len(stocks)


def job(sym):
    """从本地尾部日期增量拉取 hist_tx，重排列序后 merge_save"""
    try:
        f = BASE / "data_full" / f"{sym}.csv"
        start = "20160101"
        if f.exists():
            old = pd.read_csv(f, dtype={"date": str})
            if len(old):
                start = old["date"].iloc[-1].replace("-", "")
        df = ak.stock_zh_a_hist_tx(symbol=sym, start_date=start, end_date="20260824", adjust="qfq")
        if df is None or len(df) == 0:
            return (sym, False, "empty")
        df = df.rename(columns={"close": "close"})
        # hist_tx 列序 [date, open, close, high, low, volume, turnover, amount] → HEADERS [date, open, high, low, close, volume, amount]
        df = df[["date", "open", "high", "low", "close", "volume", "amount"]]
        df = df[F.HEADERS].drop_duplicates(subset="date").sort_values("date")
        if str(df["date"].iloc[-1]) != TARGET:
            return (sym, False, f"last={df['date'].iloc[-1]}")
        U.merge_save(sym, df, "")
        return (sym, True, None)
    except Exception as e:
        return (sym, False, str(e)[:60])


with ThreadPoolExecutor(max_workers=workers) as ex:
    fut2sym = {ex.submit(job, sym): sym for sym in stocks}
    for fut in as_completed(fut2sym):
        sym, success, err = fut.result()
        done += 1
        if success:
            ok += 1
        else:
            fail.append((sym, err))
        if done % 300 == 0 or done == total:
            el = time.time() - t0
            print(f"  [{done}/{total}] ok={ok} fail={len(fail)} elapsed={el/60:.1f}min rate={done/el:.1f}/s", flush=True)

print(f"✅ hist_tx 重试完成：成功 {ok}/{total} 失败 {len(fail)} 耗时 {(time.time()-t0)/60:.1f}分", flush=True)
if fail:
    print(f"失败前10: {fail[:10]}", flush=True)
    Path(BASE / "data_full_fail_hist_tx.csv").write_text("\n".join([f"{a},{b}" for a, b in fail]), encoding="utf-8")
