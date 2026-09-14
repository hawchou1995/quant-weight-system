# -*- coding: utf-8 -*-
"""基金净值缓存每日刷新（fund_nav_cache → 东财 pingzhongdata）
=================================================================
背景（2026-09-14 发现）：基金信号池 92% 的净值停在 2026-08-20 —— 刷新逻辑只存在于
`refresh_daily.py --fund`，而每日收盘链（daily_refresh.py）从未调用它 →
占 60% 仓位的 FB3 基金主仓长期用 3 周前的净值选基。本脚本把该步骤独立化并接入链。

口径（沿用 _fund_nav_0911_full.py，逻辑未改，仅参数化）：
  范围 = fund_top_pool.json top N（默认 3000）+ enhanced_data.js/short_pool.js 中在缓存的基金
  增量 = 仅刷新「缓存尾部日期 < TARGET」的基金
  目标 = --target 指定；缺省取 index_000300.csv 最新交易日
  写盘 = 整文件覆盖（东财返回最近 400 条），幂等
  数据源 = https://fund.eastmoney.com/pingzhongdata/{code}.js 的 Data_netWorthTrend
  ⚠ 东财 x = 北京时间(GMT+8) 00:00 戳 → 必须 localtime 转日期（gmtime 会错位 -1 天）

用法：
    python fund_nav_update.py                  # 刷到 index_000300 最新交易日
    python fund_nav_update.py --target 2026-09-11
    python fund_nav_update.py --workers 12 --pool 3000
"""
import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
CACHE = BASE / "fund_nav_cache"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "Referer": "https://fund.eastmoney.com/"}


def tail_date(f):
    try:
        with open(f, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 1024))
            tail = fh.read().decode("utf-8", errors="ignore")
        lines = [ln for ln in tail.strip().splitlines() if ln.strip()]
        return lines[-1].split(",")[0].strip() if lines else None
    except Exception:
        return None


def fetch_one(code):
    url = f"https://fund.eastmoney.com/pingzhongdata/{code}.js"
    for _ in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=15)
            m = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", r.text, re.S)
            if not m:
                return code, None, "no-trend"
            arr = json.loads(m.group(1))
            if not arr:
                return code, None, "empty"
            rows, seen = [], set()
            for it in arr[-400:]:
                if isinstance(it, dict):
                    ts, nav, chg = it.get("x", 0), it.get("y"), it.get("equityReturn", "")
                else:
                    ts = it[0] if len(it) > 0 else 0
                    nav = it[1] if len(it) > 1 else ""
                    chg = it[2] if len(it) > 2 else ""
                d = time.strftime("%Y-%m-%d", time.localtime(ts / 1000.0))
                if d in seen:
                    continue
                seen.add(d)
                rows.append(f"{d},{nav},{chg}")
            return code, rows, None
        except Exception:
            time.sleep(1.0)
    return code, None, "err"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=None, help="刷新到该日期（默认 index_000300.csv 最新交易日）")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--pool", type=int, default=3000, help="fund_top_pool.json 取前 N 只")
    a = ap.parse_args()

    if a.target:
        target = a.target
    else:
        csv = BASE / "index_000300.csv"
        target = [l.split(",")[0] for l in csv.read_text(encoding="utf-8").strip().splitlines()[1:]][-1] if csv.exists() else "2026-09-11"

    codes = set()
    fp = BASE / "fund_top_pool.json"
    if fp.exists():
        for x in json.load(open(fp, encoding="utf-8"))["top"][:a.pool]:
            codes.add(x["code"])
    # ⚠ 关键：基金信号的池 = short_engine.load_fund_pool(3000) 取「缓存目录按名排序的前 N 个文件」，
    #   因此刷新范围必须与之对齐，否则信号仍在用旧净值（2026-09-14 实测：只刷跟踪池 126 只不够）。
    codes.update(f.stem for f in sorted(CACHE.glob("*.csv"))[:a.pool])
    for js in ("enhanced_data.js", "short_pool.js"):
        p = BASE / js
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        codes.update(re.findall(r'"(\d{6})"\s*:\s*\{', txt))
        codes.update(re.findall(r'"code"\s*:\s*"(\d{6})"', txt))
    codes = {c for c in codes if (CACHE / f"{c}.csv").exists()}

    need = [c for c in sorted(codes) if (tail_date(CACHE / f"{c}.csv") or "") < target]
    print(f"[fund-nav] 目标 {target} | 范围 {len(codes)} 只 | 需更新 {len(need)} 只", flush=True)
    if not need:
        print("[fund-nav] 全部已是最新，无需更新")
        return
    t0, ok, fail = time.time(), 0, []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(fetch_one, c): c for c in need}
        for i, fut in enumerate(as_completed(futs)):
            code, rows, err = fut.result()
            if rows:
                CACHE.joinpath(f"{code}.csv").write_text(
                    "净值日期,单位净值,日增长率\n" + "\n".join(rows) + "\n", encoding="utf-8")
                ok += 1
            else:
                fail.append((code, err))
            if (i + 1) % 200 == 0:
                print(f"  [{i+1}/{len(need)}] 成功 {ok} 失败 {len(fail)} 耗时 {time.time()-t0:.0f}s", flush=True)
    print(f"[fund-nav] 完成：成功 {ok} 失败 {len(fail)} 耗时 {time.time()-t0:.0f}s")
    if fail:
        print("  失败示例:", fail[:8])


if __name__ == "__main__":
    main()
