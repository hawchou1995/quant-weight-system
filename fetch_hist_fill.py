# -*- coding: utf-8 -*-
"""补齐 4 只 ETF（新浪 fund_etf_hist_sina）+ 6 只场外基金（东财净值接口）"""
import os, time
from pathlib import Path
import akshare as ak
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = BASE / "data_hist"
OUT_DIR.mkdir(exist_ok=True)

ETF_SINA = {  # code -> sina symbol
    "515880": "sh515880",
    "159516": "sz159516",
    "516150": "sh516150",
    "560390": "sh560390",
}
FUNDS = ["008254", "018036", "002891", "024239", "014002", "020900"]


def merge_save(code, df_new, old_dirs):
    out_path = OUT_DIR / f"{code}.csv"
    old_path = None
    for d in old_dirs:
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
            print(f"  [{code}] 合并失败用纯新数据: {e}")
            merged = df_new
    else:
        merged = df_new
    merged.to_csv(out_path, index=False)
    return merged


def main():
    data_dir, data_tmp = BASE / "data", BASE / "data_tmp"
    old_dirs = [data_dir, data_tmp]

    # ---- ETF ----
    for code, sym in ETF_SINA.items():
        for attempt in range(1, 4):
            try:
                df = ak.fund_etf_hist_sina(symbol=sym)
                if df is None or df.empty:
                    print(f"[{code}] 空数据 尝试{attempt}/3")
                    time.sleep(2)
                    continue
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                df = df[["date", "open", "high", "low", "close", "volume", "amount"]]
                df = df.drop_duplicates(subset="date").sort_values("date")
                merged = merge_save(code, df, old_dirs)
                print(f"[{code}] ETF OK: {merged['date'].iloc[0]} ~ {merged['date'].iloc[-1]} {len(merged)} 行")
                break
            except Exception as e:
                print(f"[{code}] 失败: {str(e)[:80]} 尝试{attempt}/3")
                time.sleep(2)
        else:
            print(f"[{code}] ETF FAIL")
        time.sleep(1)

    # ---- 场外基金净值 ----
    for code in FUNDS:
        for attempt in range(1, 4):
            try:
                df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
                if df is None or df.empty:
                    print(f"[{code}] 空数据 尝试{attempt}/3")
                    time.sleep(2)
                    continue
                df["date"] = pd.to_datetime(df["净值日期"]).dt.strftime("%Y-%m-%d")
                # 基金净值无 OHLC，close=单位净值，volume/amount 置空
                out = pd.DataFrame({
                    "date": df["date"],
                    "open": df["单位净值"],
                    "high": df["单位净值"],
                    "low": df["单位净值"],
                    "close": df["单位净值"],
                    "volume": 0,
                    "amount": 0,
                })
                out = out.drop_duplicates(subset="date").sort_values("date")
                merged = merge_save(code, out, old_dirs)
                print(f"[{code}] 基金 OK: {merged['date'].iloc[0]} ~ {merged['date'].iloc[-1]} {len(merged)} 行")
                break
            except Exception as e:
                print(f"[{code}] 失败: {str(e)[:80]} 尝试{attempt}/3")
                time.sleep(2)
        else:
            print(f"[{code}] 基金 FAIL")
        time.sleep(1)


if __name__ == "__main__":
    main()
