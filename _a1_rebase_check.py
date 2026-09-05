# -*- coding: utf-8 -*-
"""
A1: qfq 基准漂移实证核查（借鉴项 1 · 前复权纪律）
=====================================================
疑点：update_daily.py 只对「滞后文件」全量重拉 qfq（keep=last 重基准），
「当天除权」的股票尾日=最新交易日 → 判定 fresh → 不重拉 →
本地历史停留在除权前基准，新行情行是真实价 → 除权日出现假缺口。

核查方法：
1. 取看板池+短线池+两跟踪池代码（load_pool_codes 同源逻辑）
2. 对每只重拉新浪 qfq 近 45 日 → 与本地 data_full CSV 重叠区间逐个 close 对比
3. |Δ|>0.3% 的日期=基准漂移证据（若集中在某日且幅度≈除息比例 → 实锤）
4. 输出漂移清单 + 每只最大漂移日期/幅度

用法：python _a1_rebase_check.py
"""
import sys, time, json
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
OUT_DIR = BASE / "data_full"
import akshare as ak

DRIFT_TH = 0.3  # %


def load_pool_syms():
    codes = set()
    try:
        js = (BASE / "enhanced_data.js").read_text(encoding="utf-8")
        E = json.loads(js[len("window.ENH = "):-1])
        for k in ("details", "track_v9", "track_pending_v9"):
            codes.update(E.get(k, {}).keys())
    except Exception:
        pass
    try:
        sp = json.load(open(BASE / "short_pool.json", encoding="utf-8"))
        for k in ("details", "track", "track_pending_short"):
            codes.update(sp.get(k, {}).keys())
    except Exception:
        pass
    syms = set()
    for c in codes:
        c6 = c[-6:]
        syms.add(("sh" if c6[0] in ("5", "6") else "sz") + c6)
    return syms


def fetch_recent(sym):
    df = ak.stock_zh_a_daily(symbol=sym, start_date="20260720",
                             end_date="20260905", adjust="qfq")
    if df is None or df.empty:
        return None
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df[["date", "open", "high", "low", "close"]].drop_duplicates("date")


def main():
    syms = sorted(load_pool_syms())
    print(f"池+跟踪代码 {len(syms)} 只，开始核查...", flush=True)
    drift_total, checked, missing = 0, 0, 0
    rows = []
    for i, sym in enumerate(syms, 1):
        f = OUT_DIR / f"{sym}.csv"
        if not f.exists():
            missing += 1
            continue
        try:
            loc = pd.read_csv(f, dtype={"date": str})
        except Exception:
            missing += 1
            continue
        if len(loc) < 30:
            missing += 1
            continue
        for attempt in range(3):
            try:
                new = fetch_recent(sym)
                break
            except Exception:
                new = None
                time.sleep(1.5)
        if new is None:
            missing += 1
            continue
        m = loc.merge(new, on="date", suffixes=("_loc", "_new"))
        m["drift"] = (m["close_new"] / m["close_loc"] - 1) * 100
        big = m[m["drift"].abs() > DRIFT_TH]
        checked += 1
        if len(big) > 0:
            drift_total += 1
            w = big.loc[big["drift"].abs().idxmax()]
            rows.append({"sym": sym, "n_bad": len(big),
                         "max_date": w["date"], "max_drift_pct": round(w["drift"], 3)})
            print(f"  [漂移] {sym} 不一致 {len(big)} 天 | 最大 {w['date']} {w['drift']:+.3f}%", flush=True)
        if i % 50 == 0:
            print(f"  ...{i}/{len(syms)} 已查 {checked} 漂移 {drift_total}", flush=True)
        time.sleep(0.35)
    print(f"\n===== 结论 =====")
    print(f"核查 {checked} 只 / 漂移 {drift_total} 只 / 缺文件或失败 {missing} 只")
    df = pd.DataFrame(rows)
    if len(df):
        df.to_csv(BASE / "_a1_drift_report.csv", index=False, encoding="utf-8-sig")
        print("漂移清单 → _a1_drift_report.csv")
    return rows


if __name__ == "__main__":
    main()
