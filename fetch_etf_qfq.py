# -*- coding: utf-8 -*-
"""ETF 前复权数据重抓（腾讯 qfq 分段翻页，v5.11.12）
============================================
背景：新浪 ETF 接口无复权参数（原始价，除权跳变未处理=风险审查 P1）
方案：腾讯 fqkline qfq 每页 640 根，end 往前翻页重建全历史 → 覆盖 data_full 原文件
列：date,open,high,low,close,volume,amount（amount=volume*close 近似，兼容现有格式）
用法：python fetch_etf_qfq.py [--limit N]（后台跑全量约 25-40 分钟）
"""
import sys, time, json
from pathlib import Path
import requests
import pandas as pd

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
OUT = BASE / "data_full"
T0 = time.time()

def fetch_page(code, start, end, count=640, retries=3):
    for _ in range(retries):
        try:
            r = requests.get(
                f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,{start},{end},{count},qfq",
                timeout=12, proxies={"https": None, "http": None})
            d = r.json()
            data = d.get("data")
            if isinstance(data, dict):
                k = data.get(code, {})
                kl = k.get("qfqday") or k.get("day") or []
                return kl
        except Exception:
            time.sleep(1.0)
    return []


def fetch_full(code):
    """分段翻页重建全历史 qfq"""
    rows, end = [], "2026-08-15"
    guard = 0
    while guard < 12:          # 最多 12 页（>7680 根，覆盖 2015 起）
        guard += 1
        page = fetch_page(code, "2015-01-01", end)
        if not page:
            break
        rows = page + rows    # 新页更早，前插
        first = page[0][0]
        if first <= "2016-01-01" or len(page) < 640:
            break
        end = first           # 往前翻页
    # 去重
    seen, merged = set(), []
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0])
            merged.append(r)
    return merged


def save(code, rows):
    df = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume", "_x", "_y", "_z"] if len(rows[0]) > 6 else ["date", "open", "close", "high", "low", "volume"])
    # 腾讯行序: [date, open, close, high, low, volume(, ...)]
    cols = df.columns.tolist()
    if len(cols) >= 6:
        df = df.iloc[:, :6]
        df.columns = ["date", "open", "close", "high", "low", "volume"]
    for c in ["open", "close", "high", "low", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["amount"] = (df["volume"] * df["close"]).round(2)
    df = df[["date", "open", "high", "low", "close", "volume", "amount"]]
    df.to_csv(OUT / f"{code}.csv", index=False)


def main():
    args = sys.argv[1:]
    limit = 0
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    etfs = sorted(f.stem for f in OUT.glob("*.csv") if f.stem.startswith(("sh5", "sz1")))
    print(f"ETF 目标 {len(etfs)} 只", flush=True)
    if limit:
        etfs = etfs[:limit]
    fails, ok = [], 0
    for i, code in enumerate(etfs, 1):
        t1 = time.time()
        rows = fetch_full(code)
        if len(rows) > 50:
            save(code, rows)
            ok += 1
        else:
            fails.append(code)
        if i % 50 == 0 or i == len(etfs):
            print(f"  [{i}/{len(etfs)}] 成功 {ok} 失败 {len(fails)} | {code} {len(rows)} 行 "
                  f"({time.time()-T0:.0f}s)", flush=True)
    json.dump(fails, open(BASE / "etf_qfq_fail.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✅ ETF qfq 重抓完成：成功 {ok} / 总 {len(etfs)} / 失败 {len(fails)}（{(time.time()-T0)/60:.1f} 分钟）", flush=True)
    print(f"失败清单: etf_qfq_fail.json", flush=True)


if __name__ == "__main__":
    main()
