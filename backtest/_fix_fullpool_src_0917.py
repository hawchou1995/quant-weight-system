# -*- coding: utf-8 -*-
"""R-fullpool-0917 收尾修复：① ETF 源滞后 ② 新鲜度口径把 ETF/退市当"陈旧"

现场（2026-09-17 19:20 全量补数 --all 收工后）：
  data_full 7540 只 → 新鲜 5546 / 陈旧 1993(26.4%) → fullpool_guard 判 ABORT，看板重建被拦。
  分型后真相：
    A股-沪市 2307 新鲜 / A股-深市 2896 新鲜 / A股-北交所 342 新鲜  = 5545 只**全新鲜**
    陈旧 = ETF 1626（沪896+深730）+ 其他37（sh526000 等新基金）+ 退市/长期停牌 A 股 330（sz000003 末行 2002-06-13）
           + 无法解析 1
  → ① 三个系统（轨A/轨B/轨C）吃的是 A 股，**已经全新鲜**；被"陈旧"字样误伤。
     ② ETF 假装陈旧是**真 bug**：ak.fund_etf_hist_sina 走 finance.sina.com.cn/realstock/company/
        {sym}/hisdata_klc2/klc_kl.js（JS 端点 + py_mini_racer 解码），实测该端点对 ETF 服务端滞后：
        sh510050/sh512100/sz159915 末行全停 09-16，而同日 sh600519（A股，同族端点）已到 09-17。
        同标的改走 money.finance.sina.com.cn/.../CN_MarketData.getKLineData?scale=240&datalen=3000
        → 三只末行全 09-17，volume 与 hq.sinajs 实时量逐位一致（sh510050 09-17=483343312）。

修复：
  P1 fetch_full_universe.fetch_sina_etf → 改用 money.finance.sina.com.cn getKLineData(datalen=3000)，
     旧 klc_kl.js 路径降级为 _fetch_sina_etf_klcjs 兜底（json 端点整体失败时才走）。
     该端点无 amount → 置 0：merge_save 已有「绝不拿 0 覆盖本地非 0」防线（L115-121），
     新增行由 _repair_amount(vol×close×mult 自锚定) 兜底 → 成交额不丢。
  P2 backtest/check_data_freshness.py → 加证券分型（A股/ETF/指数/其他）+ 退市&长期停牌识别
     （末行距交易日 > 30 自然日 = 已停止交易，不是"数据陈旧"），输出 stale_stock / stale_etf /
     stale_delisted / by_kind，门控字段改为 **stale_tradable**。
  P3 backtest/fullpool_guard.py → 门控改读 stale_tradable（旧字段缺失时回退 stale）。

不动：update_daily.py 的滞后扫描/降级源逻辑、merge_save、任何生产策略口径。
用法：python backtest/_fix_fullpool_src_0917.py
"""
import re
import sys
import py_compile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(__file__).resolve().parent.parent
OK = True


def rep(path, old, new, tag):
    global OK
    p = BASE / path
    t = p.read_text(encoding="utf-8")
    if new in t:
        print(f"  [skip] {tag}（已打过）")
        return
    if t.count(old) != 1:
        print(f"  [FAIL] {tag}：锚点命中 {t.count(old)} 次（期望 1）")
        OK = False
        return
    p.write_text(t.replace(old, new), encoding="utf-8")
    print(f"  [ok]   {tag}")


print("=" * 74)
print("P1 fetch_full_universe.fetch_sina_etf → money.finance.sina.com.cn getKLineData")
print("=" * 74)

OLD_ETF = '''def fetch_sina_etf(sym: str, retries: int = 3):
    """新浪 ETF 日线（原始价）"""
    for attempt in range(1, retries + 1):
        try:
            df = ak.fund_etf_hist_sina(symbol=sym)
            if df is None or df.empty:
                _backoff(attempt)
                continue
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df[HEADERS].drop_duplicates(subset="date").sort_values("date")
            # 只保留 2016 之后
            df = df[df["date"] >= "2016-01-01"]
            return df
        except Exception:
            _backoff(attempt)
    return None
'''

NEW_ETF = '''def fetch_sina_etf(sym: str, retries: int = 3):
    """新浪 ETF 日线（原始价）

    ⚠ 2026-09-17 根因修复（R-fullpool-0917，勿回退）：
      原实现走 `ak.fund_etf_hist_sina` → `finance.sina.com.cn/realstock/company/{sym}/
      hisdata_klc2/klc_kl.js`（JS 端点 + py_mini_racer 解码）。实测该端点对 **ETF 服务端滞后**：
      sh510050 / sh512100 / sz159915 末行全停在 09-16，而同一天同族的 A 股端点 sh600519 已到 09-17
      → 1626 只 ETF 集体"假陈旧"，全量补数跑完仍 26.4% 陈旧，链上守卫 ABORT 掉看板重建。
      改走与 A 股同族的 `money.finance.sina.com.cn/.../CN_MarketData.getKLineData`：
        scale=240（日线）、datalen=3000（覆盖 2016+ 全部交易日）。
      实测三只 ETF 末行 = 2026-09-17，且 volume 与 hq.sinajs 实时量逐位一致
      （sh510050 2026-09-17 volume=483343312 = 实时 483343312）→ 单位同为「股」，与本地历史一致。
      该端点不返回 amount → 置 0；merge_save 对 amount≤0 有「绝不拿 0 覆盖本地非 0」防线，
      新增行再由 _repair_amount（vol×close×mult 自锚定）兜底 → 成交额不丢，无需额外处理。
      旧 klc_kl.js 路径保留为 _fetch_sina_etf_klcjs 兜底（仅当 json 端点整体失败时降级）。
    """
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen=3000")
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=25,
                             headers={**UA, "Referer": "https://finance.sina.com.cn"})
            js = r.json()
            if not js:
                _backoff(attempt)
                continue
            df = pd.DataFrame(js)
            if df.empty or "day" not in df.columns:
                _backoff(attempt)
                continue
            df["date"] = pd.to_datetime(df["day"]).dt.strftime("%Y-%m-%d")
            for c in ("open", "high", "low", "close", "volume"):
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                else:
                    df[c] = 0.0
            df["amount"] = 0.0            # 端点无成交额；由 merge_save/_repair_amount 兜底
            df = df[HEADERS].drop_duplicates(subset="date").sort_values("date")
            df = df[df["date"] >= "2016-01-01"]      # 只保留 2016 之后
            if df.empty:
                _backoff(attempt)
                continue
            return df
        except Exception:
            _backoff(attempt)
    return _fetch_sina_etf_klcjs(sym, retries=1)


def _fetch_sina_etf_klcjs(sym: str, retries: int = 3):
    """新浪 ETF 日线 · 旧 klc_kl.js 路径（兜底，2026-09-17 降级；实测对 ETF 服务端滞后 1 日）"""
    for attempt in range(1, retries + 1):
        try:
            df = ak.fund_etf_hist_sina(symbol=sym)
            if df is None or df.empty:
                _backoff(attempt)
                continue
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            df = df[HEADERS].drop_duplicates(subset="date").sort_values("date")
            # 只保留 2016 之后
            df = df[df["date"] >= "2016-01-01"]
            return df
        except Exception:
            _backoff(attempt)
    return None
'''

rep("fetch_full_universe.py", OLD_ETF, NEW_ETF, "P1 ETF 源切 getKLineData + klc_kl.js 降级为兜底")


print()
print("=" * 74)
print("P2 backtest/check_data_freshness.py → 证券分型 + 退市识别 + stale_tradable 门控字段")
print("=" * 74)

OLD_FRESH = '''def main():
    idx = BASE / "index_000300.csv"
    rows = idx.read_text(encoding="utf-8").strip().splitlines()
    trade_day = rows[-1].split(",")[0][:10]

    total = fresh = stale = nodate = 0
    stale_list = []
    for f in sorted((BASE / "data_full").glob("*.csv")):
        total += 1
        d = last_date(f)
        if d is None:
            nodate += 1
        elif d >= trade_day:
            fresh += 1
        else:
            stale += 1
            if len(stale_list) < 20:
                stale_list.append([f.stem, d])
    out = {"ts": time.strftime("%Y-%m-%d %H:%M"), "trade_day": trade_day, "total": total,
           "fresh": fresh, "stale": stale, "nodate": nodate,
           "stale_pct": round(stale / max(1, total) * 100, 1), "stale_sample": stale_list}'''

NEW_FRESH = '''def kind(stem: str) -> str:
    """证券分型（2026-09-17 加，R-fullpool-0917）：三个系统只吃 A 股，ETF/基金不得混进门控分母"""
    m, c = stem[:2], stem[2:] if stem[:2] in ("sh", "sz", "bj") else stem
    if m == "bj":
        return "A股-北交所"
    if m == "sh" and c[:2] in ("60", "68"):
        return "A股-沪市"
    if m == "sz" and c[:2] in ("00", "30"):
        return "A股-深市"
    if m == "sh" and c[:3] in ("510", "511", "512", "513", "515", "516", "517", "518", "520", "521",
                              "522", "523", "560", "561", "562", "563", "588", "589", "501", "502",
                              "506", "508", "526"):
        return "ETF/基金-沪"
    if m == "sz" and c[:2] in ("15", "16", "18"):
        return "ETF/基金-深"
    if m == "sh" and c[:2] in ("00", "95", "99"):
        return "指数-沪"
    if m == "sz" and c[:3] in ("399", "398", "000"):
        return "指数/其他-深"
    return "其他"


def is_stock(k: str) -> bool:
    return k.startswith("A股")


def days_between(a: str, b: str) -> int:
    import datetime as _dt
    try:
        return (_dt.date.fromisoformat(b) - _dt.date.fromisoformat(a)).days
    except Exception:
        return 0


DELIST_GAP = 30          # 末行距交易日 > 30 自然日 = 已停止交易（退市/长停），不是"数据陈旧"


def main():
    idx = BASE / "index_000300.csv"
    rows = idx.read_text(encoding="utf-8").strip().splitlines()
    trade_day = rows[-1].split(",")[0][:10]

    total = fresh = stale = nodate = 0
    stale_list = []
    by_kind = {}          # kind -> {total, fresh, stale, delisted}
    for f in sorted((BASE / "data_full").glob("*.csv")):
        total += 1
        k = kind(f.stem)
        b = by_kind.setdefault(k, {"total": 0, "fresh": 0, "stale": 0, "delisted": 0})
        b["total"] += 1
        d = last_date(f)
        if d is None:
            nodate += 1
        elif d >= trade_day:
            fresh += 1
            b["fresh"] += 1
        else:
            stale += 1
            b["stale"] += 1
            # 已停止交易（退市整理/长期停牌）：末行距交易日 > 30 自然日 → 不计入门控
            if days_between(d, trade_day) > DELIST_GAP:
                b["delisted"] += 1
            if len(stale_list) < 20:
                stale_list.append([f.stem, d])

    # 门控口径：**可交易标的中真正陈旧的数量**（A股 + 现仍在交易的 ETF；剔除退市/长停）
    stale_tradable = sum(v["stale"] - v["delisted"] for v in by_kind.values())
    stale_stock = sum(v["stale"] - v["delisted"] for k, v in by_kind.items() if is_stock(k))
    stale_etf = sum(v["stale"] - v["delisted"] for k, v in by_kind.items()
                    if k.startswith("ETF"))
    stock_total = sum(v["total"] for k, v in by_kind.items() if is_stock(k))
    stock_fresh = sum(v["fresh"] for k, v in by_kind.items() if is_stock(k))
    out = {"ts": time.strftime("%Y-%m-%d %H:%M"), "trade_day": trade_day, "total": total,
           "fresh": fresh, "stale": stale, "nodate": nodate,
           "stale_pct": round(stale / max(1, total) * 100, 1),
           "stale_tradable": stale_tradable,          # ← 门控字段
           "stale_stock": stale_stock, "stale_etf": stale_etf,
           "stock_total": stock_total, "stock_fresh": stock_fresh,
           "stock_fresh_pct": round(stock_fresh / max(1, stock_total) * 100, 1),
           "by_kind": by_kind, "stale_sample": stale_list}'''

rep("backtest/check_data_freshness.py", OLD_FRESH, NEW_FRESH, "P2 分型 + 门控字段 stale_tradable")

OLD_PRINT = '''    print(f"[freshness] 交易日 {trade_day} | data_full {total} 只：新鲜 {fresh} / 陈旧 {stale}（{out['stale_pct']}%）/ 无法解析 {nodate} | {time.time()-t0:.1f}s")
    if stale_list:
        print("  陈旧样例:", ", ".join(f"{c}={d}" for c, d in stale_list[:8]))
    return out'''

NEW_PRINT = '''    print(f"[freshness] 交易日 {trade_day} | data_full {total} 只：新鲜 {fresh} / 陈旧 {stale}"
          f"（{out['stale_pct']}%）/ 无法解析 {nodate} | {time.time()-t0:.1f}s")
    print(f"[freshness] A股 {stock_fresh}/{stock_total}（{out['stock_fresh_pct']}%）"
          f" | 可交易标的中陈旧 {stale_tradable}（股 {stale_stock} / ETF {stale_etf}）← 门控值", flush=True)
    for k, v in sorted(by_kind.items(), key=lambda x: -x[1]["total"]):
        print(f"    {k:14s} 共 {v['total']:5d} | 新鲜 {v['fresh']:5d} | 陈旧 {v['stale']:5d}"
              f"（其中退市/长停 {v['delisted']}）")
    if stale_list:
        print("  陈旧样例:", ", ".join(f"{c}={d}" for c, d in stale_list[:8]))
    return out'''

rep("backtest/check_data_freshness.py", OLD_PRINT, NEW_PRINT, "P2 输出分型明细")


print()
print("=" * 74)
print("P3 backtest/fullpool_guard.py → 门控读 stale_tradable")
print("=" * 74)

OLD_G1 = '''    if f["stale"] <= STALE_GATE:
        print(f"[guard] 陈旧 {f['stale']} ≤ {STALE_GATE}：全量池新鲜，无需补数（{time.time()-t0:.0f}s）", flush=True)
        return
    if check_only:
        print(f"[guard] 陈旧 {f['stale']} > {STALE_GATE}：需全量补数（--check-only 模式未执行）", flush=True)
        return
    print(f"[guard] ⚠️ 陈旧 {f['stale']} > {STALE_GATE}（降级源只补了池内子集）→ 触发全量补数 update_daily.py --all（约 1-2h）", flush=True)'''
NEW_G1 = '''    n = _gate_n(f)
    if n <= STALE_GATE:
        print(f"[guard] 可交易陈旧 {n} ≤ {STALE_GATE}（A股 {f.get('stock_fresh','?')}/{f.get('stock_total','?')}）："
              f"全量池新鲜，无需补数（{time.time()-t0:.0f}s）", flush=True)
        return
    if check_only:
        print(f"[guard] 可交易陈旧 {n} > {STALE_GATE}：需全量补数（--check-only 模式未执行）", flush=True)
        return
    print(f"[guard] ⚠️ 可交易陈旧 {n} > {STALE_GATE}（降级源只补了池内子集）"
          f"→ 触发全量补数 update_daily.py --all（约 1-2h）", flush=True)'''
rep("backtest/fullpool_guard.py", OLD_G1, NEW_G1, "P3 门控 1/2（触发前）")

OLD_G2 = '''    f2 = freshness()
    if f2:
        ok = f2["stale"] <= STALE_GATE
        print(f"[guard] 补数后复查：新鲜 {f2['fresh']} / 陈旧 {f2['stale']} → {'✓ 全量池已对齐' if ok else '✗ 仍有陈旧（源侧限制，明日重试）'}（总 {time.time()-t0:.0f}s）", flush=True)'''
NEW_G2 = '''    f2 = freshness()
    if f2:
        n2 = _gate_n(f2)
        ok = n2 <= STALE_GATE
        print(f"[guard] 补数后复查：可交易陈旧 {n2} / A股 {f2.get('stock_fresh','?')}/{f2.get('stock_total','?')}"
              f" → {'✓ 全量池已对齐' if ok else '✗ 仍有陈旧（源侧限制，明日重试）'}（总 {time.time()-t0:.0f}s）", flush=True)'''
rep("backtest/fullpool_guard.py", OLD_G2, NEW_G2, "P3 门控 2/2（补数后复查）")

OLD_SRC = '''def freshness():'''
NEW_SRC = '''def _gate_n(f):
    """门控计数（2026-09-17 修）：可交易标的中真正陈旧的数量。
    旧口径把 1626 只 ETF（源滞后）+ 330 只退市股算成"陈旧"，分母失真是全量池守卫 ABORT 的真因。"""
    return int(f.get("stale_tradable", f.get("stale", 0)))


def freshness():'''
rep("backtest/fullpool_guard.py", OLD_SRC, NEW_SRC, "P3 加 _gate_n()")


print()
print("=" * 74)
print("编译校验")
print("=" * 74)
for rel in ("fetch_full_universe.py", "backtest/check_data_freshness.py", "backtest/fullpool_guard.py"):
    try:
        py_compile.compile(str(BASE / rel), doraise=True)
        print(f"  [ok] {rel}")
    except Exception as e:
        OK = False
        print(f"  [FAIL] {rel}: {type(e).__name__}: {e}")

print()
print("总结论：" + ("✅ 全部落地" if OK else "❌ 存在 FAIL"))
sys.exit(0 if OK else 1)
