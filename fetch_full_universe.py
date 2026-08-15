# -*- coding: utf-8 -*-
"""
全量回测池历史数据抓取（2016-01 至今 · 在市/退市股票 + ETF）
================================================================
数据源方案（2026-08-14 实测）：
- 在市 A 股（沪深北 5542 只）：新浪 stock_zh_a_daily，前复权，0.4s/只
- ETF（1629 只）：新浪 fund_etf_hist_sina（新浪 ETF 无复权参数，返回原始价）
- 退市股票（沪 159 + 深 208 = 367 只）：腾讯 web.ifzq.gtimg.cn 原始 API，**不复权**
  （腾讯前复权对退市股仅保留 500 根截断；不复权完整 2015 起）
输出：data_full/{code}.csv（date,open,high,low,close,volume,amount）
特性：断点续跑（文件存在且非空即跳过）、失败重试 3 次、限流保护、失败清单落盘
"""
import os, sys, time, json, glob
from pathlib import Path
import requests
import akshare as ak
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = BASE / "data_full"
OUT_DIR.mkdir(exist_ok=True)
FAIL_FILE = BASE / "data_full_fail_list.csv"
START_DATE = "20160101"
END_DATE = "20260814"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

HEADERS = ["date", "open", "high", "low", "close", "volume", "amount"]


# ---------------- 列表获取 ----------------
def get_listed_stocks():
    """在市 A 股列表（新浪快照，沪深北全量）"""
    df = ak.stock_zh_a_spot()
    rows = []
    for _, r in df.iterrows():
        code = str(r["代码"])  # 如 sh600519 / sz000001 / bj920000
        name = str(r["名称"])
        rows.append((code, name))
    return rows


def get_etf_list():
    """ETF 列表（新浪分类，1629 只）"""
    df = ak.fund_etf_category_sina(symbol="ETF基金")
    rows = []
    for _, r in df.iterrows():
        code = str(r["代码"])  # 如 sz159998 / sh515880
        name = str(r["名称"])
        rows.append((code, name))
    return rows


def get_delist():
    """退市股票列表：东财沪市 159 + 深市 208"""
    rows = []
    try:
        sh = ak.stock_info_sh_delist()  # 公司代码/公司简称/上市日期/暂停上市日期
        for _, r in sh.iterrows():
            code = str(r["公司代码"])
            if code.startswith(("6", "9")):
                rows.append((f"sh{code}", str(r["公司简称"])))
    except Exception as e:
        print(f"[警告] 沪市退市列表失败: {e}")
    try:
        sz = ak.stock_info_sz_delist()  # 证券代码/证券简称/上市日期/终止上市日期
        for _, r in sz.iterrows():
            code = str(r["证券代码"])
            if code.startswith(("0", "3")):
                rows.append((f"sz{code}", str(r["证券简称"])))
    except Exception as e:
        print(f"[警告] 深市退市列表失败: {e}")
    # 去重
    seen = set()
    uniq = []
    for c, n in rows:
        if c not in seen:
            seen.add(c)
            uniq.append((c, n))
    return uniq


# ---------------- 抓取函数 ----------------
def fetch_sina_daily(sym: str, retries: int = 3):
    """新浪 A 股日线（前复权），sym 形如 sh600519 / bj920000"""
    for attempt in range(1, retries + 1):
        try:
            df = ak.stock_zh_a_daily(symbol=sym, start_date=START_DATE,
                                     end_date=END_DATE, adjust="qfq")
            if df is None or df.empty:
                time.sleep(1.5)
                continue
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df[HEADERS].drop_duplicates(subset="date").sort_values("date")
            return df
        except Exception as e:
            time.sleep(2.0)
    return None


def fetch_sina_etf(sym: str, retries: int = 3):
    """新浪 ETF 日线（原始价）"""
    for attempt in range(1, retries + 1):
        try:
            df = ak.fund_etf_hist_sina(symbol=sym)
            if df is None or df.empty:
                time.sleep(1.5)
                continue
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df[HEADERS].drop_duplicates(subset="date").sort_values("date")
            # 只保留 2016 之后
            df = df[df["date"] >= "2016-01-01"]
            return df
        except Exception as e:
            time.sleep(2.0)
    return None


def fetch_tx_delist(sym: str, retries: int = 3):
    """腾讯日线（不复权），退市股专用；sym 形如 sz300104"""
    for attempt in range(1, retries + 1):
        try:
            url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                   f"?param={sym},day,2015-01-01,{END_DATE[:4]}-{END_DATE[4:6]}-{END_DATE[6:]},2000,")
            r = requests.get(url, timeout=25, headers=UA)
            j = r.json()
            data = j.get("data", {}).get(sym, {})
            if isinstance(data, dict):
                kl = data.get("day") or []
            else:
                kl = []
            if not kl:
                time.sleep(1.5)
                continue
            out = []
            for row in kl:
                # row: [date, open, close, high, low, volume, (可选 dict: 除权除息信息)]
                d = row[0]
                if d < "2016-01-01":
                    continue
                out.append({
                    "date": d, "open": float(row[1]), "high": float(row[3]),
                    "low": float(row[4]), "close": float(row[2]),
                    "volume": float(row[5]) if len(row) > 5 and not isinstance(row[5], dict) else 0,
                    "amount": 0,  # 腾讯 day 接口不含成交额
                })
            df = pd.DataFrame(out, columns=HEADERS)
            return df if len(df) > 0 else None
        except Exception as e:
            time.sleep(2.0)
    return None


def save_csv(sym, df, name):
    out = OUT_DIR / f"{sym}.csv"
    df.to_csv(out, index=False)
    return len(df)


# ---------------- 主流程 ----------------
def main():
    # 1. 收集全部目标
    all_targets = []  # (sym, name, source)
    print("== 获取在市股票列表 ==")
    try:
        stocks = get_listed_stocks()
        all_targets += [(c, n, "sina") for c, n in stocks]
        print(f"  在市股票 {len(stocks)} 只")
    except Exception as e:
        print(f"  [错误] 在市列表失败: {e}")
    time.sleep(1)

    print("== 获取 ETF 列表 ==")
    try:
        etfs = get_etf_list()
        all_targets += [(c, n, "etf") for c, n in etfs]
        print(f"  ETF {len(etfs)} 只")
    except Exception as e:
        print(f"  [错误] ETF 列表失败: {e}")
    time.sleep(1)

    print("== 获取退市列表 ==")
    try:
        dels = get_delist()
        all_targets += [(c, n, "tx") for c, n in dels]
        print(f"  退市 {len(dels)} 只")
    except Exception as e:
        print(f"  [错误] 退市列表失败: {e}")

    # 去重（同代码保留优先在市/ETF）
    seen = set()
    targets = []
    for c, n, src in all_targets:
        if c not in seen:
            seen.add(c)
            targets.append((c, n, src))
    total = len(targets)
    print(f"\n== 总目标 {total} 只（去重后）==")

    # 2. 断点续跑：加载已有
    done = {f.stem for f in OUT_DIR.glob("*.csv") if f.stat().st_size > 100}
    print(f"已存在 {len(done)} 只，将跳过")

    # 3. 循环抓取
    fails = []
    ok = skip = 0
    t_start = time.time()
    for i, (sym, name, src) in enumerate(targets, 1):
        if sym in done:
            skip += 1
            continue
        if i % 200 == 0:
            elapsed = time.time() - t_start
            print(f"  [{i}/{total}] 已用 {elapsed/60:.1f} 分钟，成功 {ok}，失败 {len(fails)}")
        if src == "sina":
            df = fetch_sina_daily(sym)
            sleep = 0.35
        elif src == "etf":
            df = fetch_sina_etf(sym)
            sleep = 0.35
        else:
            df = fetch_tx_delist(sym)
            sleep = 0.5
        if df is not None and len(df) > 0:
            save_csv(sym, df, name)
            ok += 1
            # 进度日志（每 50 只打印一次）
            if ok % 50 == 0:
                print(f"    ...已成功 {ok} 只（{sym} {name} {df['date'].iloc[0]}~{df['date'].iloc[-1]} {len(df)}行）")
        else:
            fails.append((sym, name, src))
        time.sleep(sleep)

    # 4. 失败清单
    with open(FAIL_FILE, "w", encoding="utf-8", newline="") as f:
        pd.DataFrame(fails, columns=["sym", "name", "source"]).to_csv(f, index=False)

    elapsed = time.time() - t_start
    print("\n===== 全量抓取完成 =====")
    print(f"总目标 {total} / 本次成功 {ok} / 跳过(已存在) {skip} / 失败 {len(fails)}")
    print(f"耗时 {elapsed/60:.1f} 分钟")
    print(f"失败清单: {FAIL_FILE}")
    if fails:
        print("失败样例:", fails[:10])


if __name__ == "__main__":
    main()
