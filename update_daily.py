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
- 第三源预留（2026-09-05 借鉴 Rockyzsu 多源容错）：tushare pro（pro.daily + adj='qfq'）可在
  新浪/腾讯双源失效时作补充源；需自备 token（环境变量 TUSHARE_TOKEN），接入时在 fetchers
  字典注册 fetch_ts_pro_daily 即可，当前无 token 故仅占位不启用

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
                F._backoff(attempt)
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
            F._backoff(attempt)
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
    """当前需保持新鲜的代码集 = 看板池（v9 全量池，2026-08-21 起固定池已去除）+ 两跟踪池（含掉榜标的，backfill 曾漏掉它们）。
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


# ════════ 复权基准漂移检测（2026-09-05 借鉴 Rockyzsu/stock 前复权纪律）════════
# 问题：滞后文件全量重拉 qfq 后基准一致；但「当天除权」的股票尾日=最新 → 判定 fresh →
#   不重拉 → 本地历史停在除权前基准，新增行情行是真实价 → 除权日出现假缺口
#   （假 -X% 会污染 RSI/突破信号 → 误触发超卖买入）。此处收盘管道每日兜底检测。
REBASE_JUMP_PCT = 5.0     # 近 32 日存在 |单日跳变| ≥ 此值 → 候选（疑似除权假缺口）
REBASE_VOL_MAX = 4.0      # 且跳变日成交量 ≤ 前5日均量×此值（真涨跌停通常放量，除权正常量）
REBASE_DRIFT_PCT = 0.3    # 重拉 qfq 对比重叠区 |Δ| > 此值 → 确认基准漂移
                          # 2026-09-05 对齐 A1 证据阈值：0.5 会漏掉 sh603259(-0.329%)
                          # 与 sz300012(-0.367%)。统一新浪源验证（新浪 vs 自身）噪声≈0，
                          # 无假阳性风险，可放心收紧到 0.3。
REBASE_MAX_CAND = 400     # 每日候选上限（防异常行情日扫崩）


def _tail_rows(f, n=40):
    """快速读 CSV 尾部 n 行（date,close,volume 足够）"""
    try:
        with open(f, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 4096))
            tail = fh.read().decode("utf-8", errors="ignore")
        lines = [ln for ln in tail.strip().splitlines() if ln.strip()]
        rows = []
        for ln in lines[-n:]:
            p = ln.split(",")
            if len(p) >= 6:
                try:
                    rows.append((p[0], float(p[4]), float(p[5])))
                except ValueError:
                    pass
        return rows
    except Exception:
        return []


def scan_rebase_candidates(target_date):
    """fresh 文件（尾日=最新）中近 32 日有 ≥REBASE_JUMP_PCT% 单日跳变且未放量者 → 候选"""
    cands = []
    for f in sorted(OUT_DIR.glob("*.csv")):
        if f.stat().st_size < 100:
            continue
        rows = _tail_rows(f, 40)
        if len(rows) < 15:
            continue
        closes = [c for _, c, _ in rows]
        vols = [v for _, _, v in rows]
        for i in range(5, len(rows)):
            chg = closes[i] / closes[i - 1] - 1
            if abs(chg) * 100 < REBASE_JUMP_PCT:
                continue
            v5 = sum(vols[max(0, i - 5):i]) / max(1, i - max(0, i - 5))
            if vols[i] > v5 * REBASE_VOL_MAX:
                continue  # 放量跳变=真实行情，跳过
            cands.append(f.stem)
            break
        if len(cands) >= REBASE_MAX_CAND:
            break
    return cands


def verify_rebase_drift(sym, fetcher):
    """重拉 qfq 近 45 日 vs 本地重叠区：最大 |Δ闭|>REBASE_DRIFT_PCT% → 漂移 True"""
    f = OUT_DIR / f"{sym}.csv"
    if not f.exists():
        return False
    try:
        loc = pd.read_csv(f, dtype={"date": str})
    except Exception:
        return False
    if len(loc) < 30:
        return False
    try:
        new = fetcher(sym)
    except Exception:
        return False
    if new is None or len(new) < 10:
        return False
    m = loc.merge(new, on="date", suffixes=("_loc", "_new"))
    if m.empty:
        return False
    drift = (m["close_new"] / m["close_loc"] - 1).abs().max()
    return bool(drift * 100 > REBASE_DRIFT_PCT)


def run_rebase_check(target_date, source):
    """收盘管道兜底：候选剪枝（无网络）→ 重拉验证（有网络）→ 全量 qfq 重拉覆盖。

    ⚠ 规范化源固定为「新浪」(F.fetch_sina_daily)，参数 source 仅保留调用兼容、一律忽略。
    2026-09-05 三源对照实测：新浪 vs 腾讯 qfq 存在最高 0.72% 系统性口径差
    （如 sh600351 实测 53 行不一致）。若用活动 source（可能为 tx）做验证/覆盖，
    会把基准在 sina/tx 之间来回振荡，漂移永远修不干净。
    腾讯仅作增量更新降级源（增量 append 今日行不受 qfq 基准影响，安全），
    绝不用于复权重拉覆盖。
    """
    cands = scan_rebase_candidates(target_date)
    if not cands:
        print(f"  复权基准检测：近 30 日无 ≥{REBASE_JUMP_PCT}% 未放量跳变候选，通过", flush=True)
        return 0
    print(f"  复权基准检测：候选 {len(cands)} 只（≥{REBASE_JUMP_PCT}% 跳变未放量）→ 重拉验证", flush=True)
    # 规范化源固定新浪（见函数注释）；活动 source 参数忽略，腾讯绝不用于复权重拉
    fetcher = F.fetch_sina_daily
    # 新浪可用性探针：不可用时跳过本轮（verify_rebase_drift 虽容错返回 False，
    # 但需显式告知，避免静默漏检漂移）
    if probe_date(fetcher) is None:
        print("  复权基准检测：新浪源不可用，本次跳过（漂移将在下次收盘管道重试）", flush=True)
        return 0
    fixed = 0
    for i, sym in enumerate(cands, 1):
        try:
            if verify_rebase_drift(sym, fetcher):
                full = fetcher(sym)  # 全量 qfq（2016 起），覆盖保存 → 基准统一（新浪口径）
                if full is not None and len(full) > 0:
                    F.save_csv(sym, full, "")
                    fixed += 1
                    print(f"    [修复] {sym} 基准漂移 → 已全量重拉 qfq 覆盖 ({len(full)} 行)", flush=True)
        except Exception as e:
            print(f"    [跳过] {sym} 验证异常: {str(e)[:50]}", flush=True)
        # 2026-09-05 实测：0.35s 间隔连发 400 请求触发新浪限流（整批 verify 静默失败→0 修复）
        # 调至 1.2s 躲限流；全量 400 候选扫描约 8-10 分钟，可接受
        time.sleep(1.2)
    print(f"  复权基准检测完成：候选 {len(cands)} / 确认漂移修复 {fixed} 只", flush=True)
    return fixed


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
        # 无滞后也要跑复权基准漂移检测（fresh 文件除权日假缺口兜底）
        run_rebase_check(target_date, source)
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
    # 滞后更新完成后：复权基准漂移检测兜底（fresh 文件除权假缺口）
    run_rebase_check(target_date, source)
    if fails:
        print(f"失败清单: {FAIL_FILE}（前几个: {[x[0] for x in fails[:5]]}）", flush=True)
        print("  失败标的若在跟踪池（track_v9 / 短线 track）→ 用 westock 降级补数后重跑 build_dual_system.py", flush=True)


if __name__ == "__main__":
    main()
