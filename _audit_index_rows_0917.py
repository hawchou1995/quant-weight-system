# -*- coding: utf-8 -*-
"""一次性：index_000300.csv 坏行审计与修复（R-gate-0917 附带；主源=新浪 json_v2 历史 K 线）

背景：接管 index_000300.csv 维护（ensure_index_row）后做全表对拍，发现 volume 口径混用
      （股/手/成交额）与个别 OHLC 错误。本脚本以新浪 3000 根日线为准，逐行比对修复。
用例：python _audit_index_rows_0917.py [--dry(默认) | --fix]
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
CSV = BASE / "index_000300.csv"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
SINA = ("https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
        "?symbol=sh000300&scale=240&ma=no&datalen=1500")


def get(u, tries=5):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(u, headers=UA)
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=25) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:                            # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def main():
    fix = "--fix" in sys.argv
    data = json.loads(get(SINA))
    ref = {d["day"]: d for d in data}
    print(f"新浪返回 {len(ref)} 根：{min(ref)} → {max(ref)}")

    raw = CSV.read_bytes()
    nl = b"\r\n" if b"\r\n" in raw else b"\n"      # 从字节判行尾（read_text 会吞 CRLF）
    lines = raw.decode("utf-8").splitlines()
    bad, notfound = [], []
    for i, ln in enumerate(lines[1:], 1):
        f = ln.split(",")
        dt = f[0]
        if dt not in ref:
            notfound.append(dt)
            continue
        r = ref[dt]
        new, why = list(f), []
        for idx, key, name in ((1, "open", "open"), (2, "high", "high"), (3, "low", "low"), (4, "close", "close")):
            if abs(float(f[idx]) - float(r[key])) > 0.006:
                new[idx] = r[key]; why.append(f"{name} {f[idx]}->{r[key]}")
        if int(float(f[5])) != int(float(r["volume"])):
            ratio = round(float(f[5]) / float(r["volume"]), 3) if float(r["volume"]) else 0
            new[5] = str(int(float(r["volume"]))); why.append(f"vol {f[5]}->{new[5]} (旧比值 {ratio})")
        if why:
            bad.append((i, dt, why))
            lines[i] = ",".join(new)
    print(f"库内不在新浪返回内的行: {len(notfound)} {notfound[:5]}")
    print(f"待修 {len(bad)} 行：")
    for i, dt, why in bad:
        print(f"  L{i} {dt}: " + " | ".join(why))
    if not fix:
        print("[dry] 未写（--fix 才落盘）")
        return
    CSV.write_bytes(nl.join(ln.encode("utf-8") for ln in lines) + nl)
    print(f"已写回 {CSV}")


if __name__ == "__main__":
    main()
