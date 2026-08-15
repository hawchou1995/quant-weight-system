# -*- coding: utf-8 -*-
"""验证 akshare 能否获取 2016 年至今的日线数据（东财接口）"""
import sys, time
import akshare as ak

def test_one(code, name, market="sh"):
    """market: sh/sz；东财接口用代码前缀区分"""
    prefix = "1" if code.startswith(("5", "6", "9")) else "0"
    symbol = f"{prefix}.{code}"
    t0 = time.time()
    try:
        # 东财日线：支持前复权，start_date 最早可到 1990 年
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date="20160101",
            end_date="20260814",
            adjust="qfq",
        )
        dt = time.time() - t0
        if df is None or df.empty:
            print(f"[{code}] {name}: 空数据 ({dt:.1f}s)")
            return None
        first = df.iloc[0]["日期"]
        last = df.iloc[-1]["日期"]
        n = len(df)
        print(f"[{code}] {name}: {first} ~ {last} {n} 行 ({dt:.1f}s)")
        return df
    except Exception as e:
        dt = time.time() - t0
        print(f"[{code}] {name}: 失败 {type(e).__name__}: {str(e)[:100]} ({dt:.1f}s)")
        return None

if __name__ == "__main__":
    # 测试 3 只：沪市股票、深市股票、ETF
    codes = [
        ("600498", "烽火通信", "sh"),
        ("300308", "中际旭创", "sz"),
        ("515880", "通信ETF", "sh"),
    ]
    for c, n, m in codes:
        test_one(c, n, m)
        time.sleep(0.5)  # 防限流
