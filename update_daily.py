# -*- coding: utf-8 -*-
"""日线增量更新（真正的一键增量：扫描滞后文件 → 拉最新 → 合并去重）
====================================================================
替代 fetch_full_universe.py 的"存在即跳过"（那只是全量建库，不会更新已有文件）。
流程：
1. 扫描 data_full 全部 csv 尾部日期，找出 < 最新交易日 的滞后文件
2. 对滞后文件重新拉取（默认自动选源）→ 与本地合并去重 → 覆盖保存
3. 输出滞后清单/失败清单

⚠ 多源自动降级（2026-08-19 修复，8/17、8/19 两次新浪滞后 3 个交易日致收盘管道卡死）：
   - 探样 sh600000：新浪返回日期 < 预期最新交易日（工作日 15:00 后=今日，其余=上一交易日）→ 自动切换腾讯 qfq 降级源
   - 腾讯 qfq 也失效 → 报错并给出 westock MCP 降级指引，不再盲目拉取卡死
   - 覆盖范围 = 扫描全部滞后文件（含中长线 track_v9 / 短线 track 掉榜标的——它们都在 data_full 里，
     之前只补池内 45 只导致跟踪池标的涨跌停留在旧日）

用法：python update_daily.py [--limit N] [--only etf|stock] [--source auto|sina|tx] [--pools-only|--all] [--force]
   --pools-only  仅更新「池内+跟踪池（含掉榜）」（降级源激活时自动启用）
   --all         全量更新所有滞后文件（降级源下约 1-2 小时，慎用）
   --force       即使源滞后也强制继续（节假日等场景）
"""
import os
import sys, time, json
from pathlib import Path
import pandas as pd
import requests

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import fetch_full_universe as F

OUT_DIR = BASE / "data_full"
FAIL_FILE = BASE / "data_full_fail_list.csv"
LAG_FILE = BASE / "data_lag_list.csv"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


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


def fetch_tx_qfq(sym, retries=3):
    """腾讯 fqkline 前复权（qfqday），纯 HTTP 降级源（与 sina 同口径=前复权，可无缝合并）。
    sym 形如 sh600498 / sz002185；行序 [date, open, close, high, low, volume(, amount?)]"""
    for attempt in range(1, retries + 1):
        try:
            url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                   f"?param={sym},day,2016-01-01,2030-12-31,2000,qfq")
            r = requests.get(url, timeout=20, headers=UA, proxies={"https": None, "http": None})
            j = r.json()
            data = j.get("data", {}).get(sym, {})
            if not isinstance(data, dict):
                continue
            kl = data.get("qfqday") or data.get("day") or []
            if not kl:
                time.sleep(1.0)
                continue
            out = []
            for row in kl:
                # row: [date, open, close, high, low, volume, (可选 dict/额)]
                d = row[0]
                if d < "2016-01-01":
                    continue
                vol = float(row[5]) if len(row) > 5 and not isinstance(row[5], dict) else 0
                amt = float(row[6]) if len(row) > 6 and isinstance(row[6], (int, float)) else 0.0
                out.append({"date": d, "open": float(row[1]), "high": float(row[3]),
                            "low": float(row[4]), "close": float(row[2]),
                            "volume": vol, "amount": amt})
            df = pd.DataFrame(out, columns=F.HEADERS)
            if len(df) > 0:
                return df
        except Exception:
            time.sleep(1.5)
    return None


def probe_date(fetcher, sym="sh600000"):
    """探样返回最新交易日（YYYY-MM-DD），失败返回 None"""
    try:
        df = fetcher(sym)
        if df is not None and len(df) > 0:
            return str(df["date"].iloc[-1])
    except Exception:
        pass
    return None


def expected_trade_date(now=None):
    """预期最新交易日（工作日启发式，无节假日历）：15:00 后=今日，否则=上一交易日（跳过周末）。
    节假日会误判为滞后 → 自动切腾讯源（腾讯同样返回最近交易日，切换无害），腾讯也滞后才报错。"""
    now = now or pd.Timestamp.now()
    d = now.normalize()
    if now.hour < 15:
        d -= pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d


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


def load_pool_codes():
    """当前需保持新鲜的代码集 = 看板池（v9+固定池）+ 两跟踪池（含掉榜标的，backfill 曾漏掉它们）。
    返回 {sym 形如 sh600498} 集合"""
    codes = set()
    try:
        js = (BASE / "enhanced_data.js").read_text(encoding="utf-8")
        E = json.loads(js[len("window.ENH = "):-1])
        codes.update(E.get("details", {}).keys())
        codes.update(E.get("track_v9", {}).keys())
        codes.update(E.get("track_pending_v9", {}).keys())
    except Exception:
        pass
    try:
        sp = json.load(open(BASE / "short_pool.json", encoding="utf-8"))
        codes.update(sp.get("details", {}).keys())
        codes.update(sp.get("track", {}).keys())
        codes.update(sp.get("track_pending_short", {}).keys())
    except Exception:
        pass
    syms = set()
    for c in codes:
        c6 = c[-6:]
        syms.add(("sh" if c6[0] in ("5", "6") else "sz") + c6)
    return syms


def main():
    t0 = time.time()
    args = sys.argv[1:]
    limit = 0
    only = None
    source = "auto"
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    if "--only" in args:
        only = args[args.index("--only") + 1]
    if "--source" in args:
        source = args[args.index("--source") + 1]
    force = "--force" in args

    # 1. 探样 + 多源自动降级（2026-08-19 修复：新浪滞后未检测 → 20 分钟无输出卡死）
    fetchers = {"sina": F.fetch_sina_daily, "tx": fetch_tx_qfq}
    if source == "auto":
        sina_d = probe_date(fetchers["sina"])
        exp = expected_trade_date()
        if sina_d is None or (pd.Timestamp(sina_d) < exp):
            reason = "失败" if sina_d is None else f"滞后（返回 {sina_d}，预期 ≥{str(exp.date())}）"
            print(f"⚠️ 新浪源探样{reason} → 自动切换腾讯 qfq 降级源", flush=True)
            source = "tx"
        else:
            source = "sina"
    src_fetch = fetchers[source]
    target_date = probe_date(src_fetch)
    if target_date is None:
        print(f"❌ {source} 源无法获取最新交易日（探样失败）", flush=True)
        print("   降级指引：westock MCP data_kline 拉池内+跟踪池代码 → 写 westock_dump_<date>.json →", flush=True)
        print("   python fetch_close_westock.py --dump westock_dump_<date>.json 合并进 data_full；确认后再重跑本脚本", flush=True)
        print("   （确认源已恢复可加 --force 继续，或 --source sina/tx 指定源）", flush=True)
        return
    exp = expected_trade_date()
    if not force and pd.Timestamp(target_date) < exp:
        print(f"❌ {source} 源也滞后（返回 {target_date}，预期 ≥{str(exp.date())}）——不盲目拉取，避免以旧数据覆盖/卡死", flush=True)
        print("   降级指引：westock MCP data_kline 拉池内+跟踪池代码 → 写 westock_dump_<date>.json →", flush=True)
        print("   python fetch_close_westock.py --dump westock_dump_<date>.json 合并进 data_full；确认后再重跑本脚本", flush=True)
        print("   （若今日为节假日属正常，可加 --force 继续）", flush=True)
        return
    print(f"数据源: {source} | 最新交易日: {target_date}", flush=True)

    # 2. 扫描滞后
    lag = scan_lag(target_date)
    # ⚠ 2026-08-19 修复：新浪源连续多日滞后时全市场滞后来高达数千只——
    #    降级源激活（tx）时默认只补「池内 + 跟踪池（含掉榜）」代码，避免 2 小时全量重拉；
    #    需全量重建请显式 --all
    pools_only = "--pools-only" in args or ("--all" not in args and source == "tx")
    if pools_only:
        _psyms = load_pool_codes()
        _before = len(lag)
        lag = [x for x in lag if x[0] in _psyms]
        print(f"  降级源模式：仅补池内+跟踪池 {len(lag)}/{_before} 只（--all 可全量，约 1-2 小时）", flush=True)
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
    print(f"滞后清单已存 {LAG_FILE}（含跟踪池掉榜标的——只要在 data_full 就会一并补齐）", flush=True)
    pd.DataFrame(lag, columns=["sym", "name", "src", "tail"]).to_csv(LAG_FILE, index=False)

    # 3. 逐个更新
    fails, ok = [], 0
    for i, (sym, _n, _s, _t) in enumerate(lag, 1):
        try:
            if source == "sina" and sym.startswith(("sh5", "sz1", "sz15", "sz16")):
                df = F.fetch_sina_etf(sym)
            else:
                df = src_fetch(sym)
        except Exception as e:
            fails.append((sym, "", source, str(e)[:60]))
            continue
        if df is not None and len(df) > 0:
            merge_save(sym, df, "")
            ok += 1
            if ok % 50 == 0 or i == len(lag):
                print(f"  [{i}/{len(lag)}] 已更新 {ok} 只（{sym} → {df['date'].iloc[-1]}）耗时 {time.time()-t0:.0f}s", flush=True)
        else:
            fails.append((sym, "", source, "empty"))
        time.sleep(0.35)
    pd.DataFrame(fails, columns=["sym", "name", "src", "err"]).to_csv(FAIL_FILE, index=False)
    print(f"✅ 增量更新完成（源 {source}）：成功 {ok} / 滞后 {len(lag)} / 失败 {len(fails)}，总耗时 {(time.time()-t0)/60:.1f} 分钟", flush=True)
    if fails:
        print(f"失败清单: {FAIL_FILE}（前几个: {[x[0] for x in fails[:5]]}）", flush=True)
        print("  失败标的若在跟踪池（track_v9 / 短线 track）→ 用 westock 降级补数后重跑 build_dual_system.py", flush=True)


if __name__ == "__main__":
    main()
