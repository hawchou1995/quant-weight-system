# -*- coding: utf-8 -*-
"""refresh_name_latest.py — 从 data_fundamental/name_hist.csv（每日简称史）生成
「当日名称快照」data_fundamental/name_latest.json = {6位码: 最新可用简称}。

为什么需要它（2026-09-29 用户实测事故）：
  002743 当时已是 **ST富煌**（东财/腾讯实时名一致），但 `data_full_names.json` 停在 2026-08-17
  ⇒ frontier 的「现行名称剔 ST/退」用的是过期名 ⇒ ST 股进了买入清单（用户报「002743是ST股」）。
  name_hist.csv 是**按交易日**的简称史（RPT_VALUEANALYSIS_DET，2021-01-04 起），
  取每只票的**最后一条**即「最新可用名」，足以支撑 frontier 过滤（历史点时过滤另议，属冻结判据变更）。

用法：
  python refresh_name_latest.py            # 写 data_fundamental/name_latest.json
  python refresh_name_latest.py --check    # 只报告，不写盘（用于验证）

依赖：pandas（本机 venv 有）。文件较大（~165MB）⇒ 用 usecols 只读三列，按块扫。
"""
import argparse
import json
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parent
SRC = BASE / "data_fundamental" / "name_hist.csv"
OUT = BASE / "data_fundamental" / "name_latest.json"
FALLBACK = BASE / "data_full_names.json"


def is_st(name):
    n = str(name or "")
    return ("ST" in n.upper()) or ("退" in n)


def build():
    """返回 (latest_map, meta)。latest_map: {6位码: 名称}"""
    import pandas as pd

    if not SRC.exists():
        return None, {"error": "name_hist.csv 不存在（先跑 fetch_name_hist_0913.py）"}
    latest, last_date, n_rows = {}, "", 0
    for ch in pd.read_csv(SRC, dtype=str, usecols=["code", "TRADE_DATE", "SECURITY_NAME_ABBR"],
                          chunksize=500_000, encoding="utf-8", encoding_errors="ignore"):
        ch.columns = [c.strip() for c in ch.columns]
        for c, d, nm in zip(ch["code"], ch["TRADE_DATE"], ch["SECURITY_NAME_ABBR"]):
            c = str(c or "").strip()
            if len(c) != 6 or not c.isdigit():
                continue
            d = str(d or "")[:10]
            n_rows += 1
            if d >= latest.get("__d_" + c, ""):
                latest["__d_" + c] = d
                latest[c] = str(nm or "").strip()
            if d > last_date:
                last_date = d
    clean = {k: v for k, v in latest.items() if not k.startswith("__d_")}
    return clean, {"rows": n_rows, "codes": len(clean), "last_trade_date": last_date,
                   "source": str(SRC.relative_to(BASE))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只报告，不写盘")
    a = ap.parse_args()
    m, meta = build()
    if m is None:
        print("[name_latest] 失败：%s" % meta.get("error"))
        return 2
    st = sorted([c for c, n in m.items() if is_st(n)])
    main_board = [c for c in st if c[:2] in ("60", "00") or c[:3] in ("001", "002", "003")]
    meta.update({"st_total": len(st), "st_main_board": len(main_board),
                 "st_samples": ["%s=%s" % (c, m[c]) for c in main_board[:8]]})
    print("[name_latest] %s" % json.dumps(meta, ensure_ascii=False))
    print("   示例：002743=%s（应含 ST）" % m.get("002743"))
    if a.check:
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(m, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    # 与旧文件对比：报告「名称已变」的只数（透明度：这就是过期名会造成的漏剔规模）
    if FALLBACK.exists():
        old = json.loads(FALLBACK.read_text(encoding="utf-8"))
        diff = []
        for sym, nm in old.items():
            c = sym[2:] if sym[:2] in ("sh", "sz", "bj") else sym
            cur = m.get(c)
            if cur and cur != nm and (is_st(cur) or is_st(nm)):
                diff.append("%s %s→%s" % (c, nm, cur))
        print("   与 data_full_names.json 相比：**ST 状态翻转 %d 只**（旧文件漏剔/误剔的规模）" % len(diff))
        for x in diff[:10]:
            print("      " + x)
    print("[out] %s（%d 只）" % (OUT.relative_to(BASE), len(m)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
