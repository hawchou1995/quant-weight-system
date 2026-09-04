# -*- coding: utf-8 -*-
"""盘中数据刷新：westock CLI 批量拉 watchlist 最新日K → raw_kline 快照（整体覆盖）"""
import subprocess, csv, os, json, time, sys

WSTOCK_CLI = r"C:/Users/Admin/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/westock-data/scripts/index.js"
BASE = r"D:/Documents/Workbuddy/股票基金/行情监控"
RAW_DIR = os.path.join(BASE, "raw_kline")

def to_wind_prefix(code):
    return "sh" + code if code.startswith(("6", "5")) else "sz" + code

def fetch_batch(codes):
    cmd = ["node", WSTOCK_CLI, "kline", ",".join(to_wind_prefix(c) for c in codes),
           "--period", "day", "--limit", "60"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=120)
    return r.stdout

def parse_batch(text):
    """批量单表 → {code: rows}。列序铁律：symbol|date|open|last|high|low|volume|amount|exchange，last=close"""
    data = {}
    for l in text.splitlines():
        if not l.strip().startswith("|"):
            continue
        cells = [c.strip() for c in l.strip("|").split("|")]
        if len(cells) < 9 or cells[0] == "symbol":
            continue
        sym, date = cells[0], cells[1]
        code = sym[2:]
        try:
            o, last, h, low, v = float(cells[2]), float(cells[3]), float(cells[4]), float(cells[5]), float(cells[6])
        except ValueError:
            continue
        data.setdefault(code, []).append([date, o, h, low, last, v])
    return data

def main():
    wl = json.load(open(os.path.join(BASE, "watchlist.json"), encoding="utf-8"))
    today = time.strftime("%Y-%m-%d")
    print(f"watchlist {len(wl)} 标的，拉取最新日K（{today}）")
    # 分批（每批 8 只）
    items = []
    ok, fail = 0, []
    for i in range(0, len(wl), 8):
        batch = wl[i:i+8]
        codes = [b["code"] for b in batch]
        text = fetch_batch(codes)
        parsed = parse_batch(text)
        for b in batch:
            code = b["code"]
            rows = parsed.get(code, [])
            if not rows:
                fail.append(code)
                print(f"  {code} {b['name']}: 无数据 ❌")
                continue
            rows.sort(key=lambda r: r[0])
            # → {"d":日期(带横线), "c":close, "v":volume, "h":high, "l":low}
            krows = []
            for r in rows:
                d = r[0]
                if len(d) == 8 and d.isdigit():
                    d = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                krows.append({"d": d, "c": r[4], "v": r[5], "h": r[1], "l": r[3]})
            items.append({"code": code, "name": b["name"], "setcode": str(b.get("setcode", "")), "rows": krows})
            last = krows[-1]
            print(f"  {code} {b['name']}: {len(krows)} 根, 末日 {last['d']} 收盘 {last['c']} v={last['v']}")
            ok += 1
    # 检查当日 K 线是否实时
    real = sum(1 for it in items if it["rows"] and it["rows"][-1]["d"] == today and it["rows"][-1]["v"] > 0)
    note = f"盘中数据刷新（{time.strftime('%H:%M')}，westock 批量）；当日K线真实成交 {real}/{len(items)} 只" if real else f"盘中数据刷新（{time.strftime('%H:%M')}，westock 批量）；注意当日K线无真实成交"
    snap = {"snapshot_date": today, "snapshot_note": note, "items": items}
    p = os.path.join(RAW_DIR, f"{today}.json")
    json.dump(snap, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n✅ {ok} 只写入 {p}")
    print(f"snapshot_note: {note}")
    if fail:
        print(f"❌ 失败 {len(fail)} 只: {fail}")
    return ok, fail

if __name__ == "__main__":
    sys.exit(0 if main()[0] > 0 else 1)
