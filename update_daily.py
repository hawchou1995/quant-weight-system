# -*- coding: utf-8 -*-
"""日线增量更新（真正的一键增量：扫描滞后文件 → 拉最新 → 合并去重）
====================================================================
替代 fetch_full_universe.py 的"存在即跳过"（那只是全量建库，不会更新已有文件）。
流程：
1. 扫描 data_full 全部 csv 尾部日期，找出 < 最新交易日 的滞后文件
2. 对滞后文件重新拉取（新浪源，返回全量）→ 与本地合并去重 → 覆盖保存
3. 输出滞后清单/失败清单

用法：python update_daily.py [--limit N] [--only etf|stock]
"""
import sys, time, json
from pathlib import Path
import pandas as pd

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
sys.path.insert(0, str(BASE))
import fetch_full_universe as F

OUT_DIR = BASE / "data_full"
FAIL_FILE = BASE / "data_full_fail_list.csv"
LAG_FILE = BASE / "data_lag_list.csv"


def tail_date(f):
    """快速读 csv 尾部日期（不加载全文件）"""
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


def merge_save(sym, df, name):
    """本地 + 新数据合并去重保存（df 为源返回全量）"""
    f = OUT_DIR / f"{sym}.csv"
    df = df.copy()
    df["date"] = df["date"].astype(str)
    if f.exists():
        old = pd.read_csv(f, dtype={"date": str})
        merged = pd.concat([old, df]).drop_duplicates(subset="date", keep="last")
        merged = merged.sort_values("date").reset_index(drop=True)
        F.save_csv(sym, merged, name)
    else:
        F.save_csv(sym, df, name)


def scan_lag(target_date):
    """扫描全部文件，返回滞后文件清单 [(sym, name, src, tail)]"""
    lag, ok_cnt = [], 0
    for f in sorted(OUT_DIR.glob("*.csv")):
        if f.stat().st_size < 100:
            continue
        td = tail_date(f)
        if td is None:
            continue
        if td < target_date:
            lag.append((f.stem, "", "", td))
        else:
            ok_cnt += 1
    print(f"扫描完成：最新 {ok_cnt} 只已到位，滞后 {len(lag)} 只", flush=True)
    return lag


def main():
    t0 = time.time()
    args = sys.argv[1:]
    limit = 0
    only = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    if "--only" in args:
        only = args[args.index("--only") + 1]

    # 1. 最新交易日：取一个在股票文件的尾部（源已确认返回 08-14）
    probe = F.fetch_sina_daily("sh600000")
    target_date = str(probe["date"].iloc[-1]) if probe is not None else None
    if target_date is None:
        print("❌ 无法获取最新交易日（数据源失败）")
        return
    print(f"最新交易日: {target_date}", flush=True)

    # 2. 扫描滞后
    lag = scan_lag(target_date)
    if only == "etf":
        lag = [x for x in lag if x[0].startswith(("sh5", "sz1", "sz15", "sz16"))]
        print(f"  仅 ETF: {len(lag)} 只", flush=True)
    elif only == "stock":
        lag = [x for x in lag if not x[0].startswith(("sh5", "sz1", "sz15", "sz16"))]
        print(f"  仅股票: {len(lag)} 只", flush=True)
    if limit > 0:
        lag = lag[:limit]
        print(f"  限 {limit} 只", flush=True)
    if not lag:
        print("✅ 全部已是最新，无需更新")
        return
    print(f"滞后清单已存 {LAG_FILE}", flush=True)
    pd.DataFrame(lag, columns=["sym", "name", "src", "tail"]).to_csv(LAG_FILE, index=False)

    # 3. 逐个更新
    fails, ok = [], 0
    for i, (sym, _n, _s, _t) in enumerate(lag, 1):
        src = "etf" if sym.startswith(("sh5", "sz1", "sz15", "sz16")) else "sina"
        try:
            df = F.fetch_sina_etf(sym) if src == "etf" else F.fetch_sina_daily(sym)
        except Exception as e:
            fails.append((sym, "", src, str(e)[:60]))
            continue
        if df is not None and len(df) > 0:
            merge_save(sym, df, "")
            ok += 1
            if ok % 50 == 0 or i == len(lag):
                print(f"  [{i}/{len(lag)}] 已更新 {ok} 只（{sym} → {df['date'].iloc[-1]}）耗时 {time.time()-t0:.0f}s", flush=True)
        else:
            fails.append((sym, "", src, "empty"))
        time.sleep(0.35)
    pd.DataFrame(fails, columns=["sym", "name", "src", "err"]).to_csv(FAIL_FILE, index=False)
    print(f"✅ 增量更新完成：成功 {ok} / 滞后 {len(lag)} / 失败 {len(fails)}，总耗时 {(time.time()-t0)/60:.1f} 分钟", flush=True)
    if fails:
        print(f"失败清单: {FAIL_FILE}（前几个: {[x[0] for x in fails[:5]]}）", flush=True)


if __name__ == "__main__":
    main()
