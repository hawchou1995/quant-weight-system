# -*- coding: utf-8 -*-
"""
akshare 批量下载历史日线（2016-01-01 至今，前复权）
====================================================
数据源：新浪 stock_zh_a_daily（已验证可用，~0.4s/只）
输出：data_hist/{code}.csv，列格式与原 data/ 一致（date,open,high,low,close,volume,amount）
策略：先全量拉 2016 至今，覆盖原文件日期缺失段；已有数据与新股数据按日期合并去重。
"""
import os, sys, time, glob
from pathlib import Path
import akshare as ak
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = BASE / "data"
DATA_TMP = BASE / "data_tmp"
OUT_DIR = BASE / "data_hist"
OUT_DIR.mkdir(exist_ok=True)

# 场外基金（净值型，akshare 需专用接口，本次跳过，另行处理）
FUND_CODES = {"008254", "018036", "002891", "024239", "014002", "020900"}

def collect_codes():
    """收集 data/ + data_tmp/ 所有标的代码"""
    codes = set()
    for d in (DATA_DIR, DATA_TMP):
        for f in glob.glob(str(d / "*.csv")):
            codes.add(Path(f).stem)
    return sorted(codes)

def to_sina_symbol(code: str) -> str:
    """转换为新浪 symbol：sh600498 / sz300308 / sh515880"""
    if code.startswith(("6", "5", "9")):
        return f"sh{code}"
    if code.startswith(("0", "1", "2", "3")):
        return f"sz{code}"
    raise ValueError(f"无法识别市场: {code}")

def fetch_one(code: str, retries: int = 3) -> pd.DataFrame | None:
    symbol = to_sina_symbol(code)
    for attempt in range(1, retries + 1):
        try:
            df = ak.stock_zh_a_daily(
                symbol=symbol, start_date="20160101", end_date="20260814", adjust="qfq"
            )
            if df is None or df.empty:
                print(f"  [{code}] 空数据 (尝试 {attempt}/{retries})")
                time.sleep(1.5)
                continue
            # 统一列名：date, open, high, low, close, volume, amount
            df = df.rename(columns={"date": "date", "amount": "amount"})
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df[["date", "open", "high", "low", "close", "volume", "amount"]]
            df = df.drop_duplicates(subset="date").sort_values("date")
            return df
        except Exception as e:
            msg = str(e)[:80]
            print(f"  [{code}] 失败: {msg} (尝试 {attempt}/{retries})")
            time.sleep(2.0)
    return None

def merge_and_save(code: str, df_new: pd.DataFrame) -> None:
    """新数据与旧文件按日期合并（旧文件优先保留，避免覆盖），写入 data_hist/"""
    out_path = OUT_DIR / f"{code}.csv"
    old_path = None
    for d in (DATA_DIR, DATA_TMP):
        p = d / f"{code}.csv"
        if p.exists():
            old_path = p
            break
    if old_path:
        try:
            df_old = pd.read_csv(old_path, dtype={"date": str})
            df_old["date"] = pd.to_datetime(df_old["date"]).dt.strftime("%Y-%m-%d")
            merged = pd.concat([df_old, df_new]).drop_duplicates(subset="date", keep="first")
            merged = merged.sort_values("date")
        except Exception as e:
            print(f"  [{code}] 合并失败，使用纯新数据: {e}")
            merged = df_new
    else:
        merged = df_new
    merged.to_csv(out_path, index=False)
    return merged

def main():
    codes = collect_codes()
    fund_cnt = len(set(codes) & FUND_CODES)
    print(f"共 {len(codes)} 只标的（含场外基金 {fund_cnt} 只，将跳过）")
    summary = []
    ok = fail = 0
    for i, code in enumerate(codes, 1):
        if code in FUND_CODES:
            print(f"[{i}/{len(codes)}] {code} 场外基金跳过（akshare 净值接口另行处理）")
            summary.append((code, "基金跳过"))
            continue
        print(f"[{i}/{len(codes)}] {code} 拉取中...")
        df = fetch_one(code)
        if df is None:
            summary.append((code, "FAIL"))
            fail += 1
            continue
        merged = merge_and_save(code, df)
        first, last = merged["date"].iloc[0], merged["date"].iloc[-1]
        n = len(merged)
        print(f"  -> {first} ~ {last} 共 {n} 行")
        summary.append((code, f"{first}~{last} {n}行"))
        ok += 1
        time.sleep(0.4)  # 限流保护

    print("\n===== 汇总 =====")
    print(f"成功 {ok} / 失败 {fail} / 跳过 {len(codes) - ok - fail}")
    for code, s in summary:
        print(f"  {code}: {s}")

if __name__ == "__main__":
    main()
