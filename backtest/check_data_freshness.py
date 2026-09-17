# -*- coding: utf-8 -*-
"""data_full 全量新鲜度检查（2026-09-17 建，R-fullpool-0917）
口径：data_full/*.csv 末行日期 vs index_000300.csv 末日（最新交易日）。
输出：stdout 摘要 + backtest/_data_freshness.json；exit 0（信息性，不阻断）。
用法：python backtest/check_data_freshness.py
"""
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
t0 = time.time()


def last_date(p: Path):
    """快速读文件末行日期（只读尾部 512 字节）"""
    try:
        with open(p, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 512))
            tail = fh.read().decode("utf-8", errors="ignore").strip().splitlines()
        for ln in reversed(tail):
            s = ln.split(",")[0].strip()
            if len(s) >= 10 and s[4] == "-":
                return s[:10]
    except Exception:
        pass
    return None


def kind(stem: str) -> str:
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
           "by_kind": by_kind, "stale_sample": stale_list}
    (HERE / "_data_freshness.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[freshness] 交易日 {trade_day} | data_full {total} 只：新鲜 {fresh} / 陈旧 {stale}"
          f"（{out['stale_pct']}%）/ 无法解析 {nodate} | {time.time()-t0:.1f}s")
    print(f"[freshness] A股 {stock_fresh}/{stock_total}（{out['stock_fresh_pct']}%）"
          f" | 可交易标的中陈旧 {stale_tradable}（股 {stale_stock} / ETF {stale_etf}）← 门控值", flush=True)
    for k, v in sorted(by_kind.items(), key=lambda x: -x[1]["total"]):
        print(f"    {k:14s} 共 {v['total']:5d} | 新鲜 {v['fresh']:5d} | 陈旧 {v['stale']:5d}"
              f"（其中退市/长停 {v['delisted']}）")
    if stale_list:
        print("  陈旧样例:", ", ".join(f"{c}={d}" for c, d in stale_list[:8]))
    return out


if __name__ == "__main__":
    main()
