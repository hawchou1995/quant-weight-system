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
    FUND_NAV_WORKERS=12 FUND_NAV_BUDGET_S=1800 python fund_nav_update.py   # 云端：12 并发 + 30min 硬预算（超预算即收工，未刷完下轮续）
"""
import argparse
import json
import os
import re
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
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
            # ⚠ 2026-09-14 事故：初版沿用旧脚本的 arr[-400:]（只取最近 400 条）→ 覆盖写把
            #   3042 只基金的净值历史截断到 1.6 年，基金回测从 733%/夏普1.316 掉到 59%/0.517。
            #   东财 Data_netWorthTrend 本身返回全历史（实测 000001 = 6005 条），必须全量写。
            for it in arr:
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


REF_CODES = ("000001", "110022", "519066")   # 参考基金：老牌产品，净值发布最早最全


def published_tail():
    """参考基金已发布到的最后一个净值日期（= 东财当前发布进度）。
    取多只参考的**最大值**（降低单只停更导致的误判）；全部拿不到 → None（预检自动放弃）"""
    tails = []
    for code in REF_CODES:
        _, rows, _err = fetch_one(code)
        if rows:
            tails.append(max(r.split(",", 1)[0] for r in rows))
    return max(tails) if tails else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=None, help="刷新到该日期（默认 index_000300.csv 最新交易日）")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("FUND_NAV_WORKERS", "8")),
                    help="并发线程数（默认读环境变量 FUND_NAV_WORKERS，缺省 8）")
    ap.add_argument("--pool", type=int, default=3000, help="fund_top_pool.json 取前 N 只")
    ap.add_argument("--no-precheck", action="store_true",
                    help="跳过「参考基金发布进度」预检（默认开启：目标日未发布时压缩有效目标）")
    a = ap.parse_args()

    if a.target:
        target = a.target
    else:
        csv = BASE / "index_000300.csv"
        target = [l.split(",")[0] for l in csv.read_text(encoding="utf-8").strip().splitlines()[1:]][-1] if csv.exists() else "2026-09-11"

    # 发布进度预检（2026-09-24 加）：目标日净值可能**尚未发布**（盘中 / 刚收盘跑），此时全部基金
    # 尾部日期都 < 目标 → 3000+ 只全进队列、每只重下全历史再覆盖写（云端实测 run 35943548423：
    # 02:36:57 起 ≥29min 未跑完，是链超时的最大单点）。判据 = 参考基金已发布尾部（= 东财实际
    # 发布进度）→ 有效目标 = min(目标, 尾部)。拿不到参考（网络/无数据）→ 不 clamp，保持原语义
    # （宁可多跑，不漏补）；--no-precheck 可整体禁用。
    if not a.no_precheck:
        pub = published_tail()
        if pub and pub < target:
            print(f"[fund-nav] 预检：参考基金净值已发布至 {pub} < 目标 {target}"
                  f"（目标日未发布）→ 有效目标压到 {pub}", flush=True)
            target = pub

    codes = set()
    fp = BASE / "fund_top_pool.json"
    if fp.exists():
        for x in json.load(open(fp, encoding="utf-8"))["top"][:a.pool]:
            codes.add(x["code"])
    # ⚠ 关键：基金信号的池 = short_engine.load_fund_pool(2000)（2026-09-16 起与回测同池）
    #   取「缓存目录按名排序的前 N 个文件」；本脚本默认刷 3000 作超集（多刷无害，防未来扩池）
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
    # 时间预算（2026-09-24 加）：云端 FUND_NAV_BUDGET_S>0 → 本步硬上限。云端实测（run
    # 35943548423）该步 02:36:57 起 ≥29.2min 连一条进度行都没有（<200/3038 只）：pingzhongdata
    # 全历史 JS 在 US runner 上极慢，无限等待会把整条链拖死（链 5400s 超时）。
    # 语义：超预算 → 停止提交、停止等待；已完成者每只都是独立整文件覆盖（幂等、无半成品），
    #      未跑的下次续；顺序按尾部日期升序（最陈旧优先）→ 多轮公平轮转。本机默认 0 = 不限。
    try:
        budget = float(os.environ.get("FUND_NAV_BUDGET_S", "0") or 0)
    except ValueError:
        budget = 0.0
    need.sort(key=lambda c: (tail_date(CACHE / f"{c}.csv") or "", c))
    t0, ok, fail, i = time.time(), 0, [], 0
    ex = ThreadPoolExecutor(max_workers=a.workers)
    inflight, src = set(), iter(need)
    deadline = (time.time() + budget) if budget > 0 else None
    try:
        while True:
            while len(inflight) < a.workers and (deadline is None or time.time() < deadline):
                try:
                    inflight.add(ex.submit(fetch_one, next(src)))
                except StopIteration:
                    break
            if not inflight:
                break
            left = None if deadline is None else max(0.0, deadline - time.time())
            done, _ = wait(list(inflight), timeout=left, return_when=FIRST_COMPLETED)
            if not done:
                break
            for fut in done:
                inflight.discard(fut)
                code, rows, err = fut.result()
                i += 1
                if rows:
                    CACHE.joinpath(f"{code}.csv").write_text(
                        "净值日期,单位净值,日增长率\n" + "\n".join(rows) + "\n", encoding="utf-8")
                    ok += 1
                else:
                    fail.append((code, err))
                if i % 200 == 0:
                    print(f"  [{i}/{len(need)}] 成功 {ok} 失败 {len(fail)} 耗时 {time.time()-t0:.0f}s", flush=True)
        skipped = sum(1 for _ in src) + len(inflight)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    tail = f" | 预算 {budget:.0f}s 用尽，本轮跳过 {skipped} 只（下轮最陈旧优先续补）" if skipped else ""
    print(f"[fund-nav] 完成：成功 {ok} 失败 {len(fail)} 耗时 {time.time()-t0:.0f}s{tail}")
    if fail:
        print("  失败示例:", fail[:8])


if __name__ == "__main__":
    main()
