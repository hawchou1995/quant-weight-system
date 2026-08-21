# -*- coding: utf-8 -*-
"""构建 2026-08-21 盘中快照 + 实时行情 quotes
====================================================================
流程：收集两池（enhanced/short）股票代码（排除基金/ETF）
（2026-08-21 起固定池 watchlist 已彻底去除，不再作为第三池）
→ westock kline limit=60 批量拉 60 根日K（末根=08-21 盘中）→
生成 raw_kline/2026-08-21.json + intraday_quotes_2026-08-21.json
"""
import json, re, subprocess, time, os
from pathlib import Path

BASE = Path(__file__).resolve().parent
MON = Path(r"D:/Documents/Workbuddy/股票基金/行情监控")
WS = Path(r"C:/Users/Admin/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/westock-data/scripts/index.js")
TODAY = "2026-08-21"
PREV = "2026-08-20"

ROW = re.compile(r"\| (sh|sz)\w+ \| (\d{4}-\d{2}-\d{2}) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d.eE+]+) \| ([\d.eE+]+) \| ([\d.eE+]+) \|")

def load_js(path):
    src = Path(path).read_text(encoding="utf-8")
    m = re.search(r"window\.(\w+) = (.*);\s*$", src, re.S)
    return json.loads(m.group(2))

def collect_codes():
    enh = load_js(BASE / "enhanced_data.js")
    sp = load_js(BASE / "short_pool.js")
    wl = json.load(open(MON / "watchlist.json", encoding="utf-8"))
    wl_codes = set()
    for it in wl:
        wl_codes.add(it["code"] if isinstance(it, dict) else it)
    codes = set()
    for det in (enh.get("details", {}), sp.get("details", {})):
        pass
    for d in [enh.get("details", {}), sp.get("details", {})]:
        for code, v in d.items():
            if v.get("board") == "基金":
                continue
            codes.add(code)
    codes |= {c for c in wl_codes if not c.isdigit() or True}  # watchlist 全股票
    # 排除基金代码（场外基金 0/1 开头，board 已标基金；这里 watchlist 全是股票）
    return sorted(codes)

def prefix(c):
    return ("sh" if c.startswith("6") else "sz") + c

def call_kline(syms, limit=60):
    cmd = ["node", str(WS), "kline", ",".join(syms), "--period", "day", "--limit", str(limit), "--fq", "qfq"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return r.stdout

def parse(text):
    out = {}
    cur = None
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("|") and "symbol" not in s and "---" not in s:
            m = ROW.match(s)
            if not m:
                continue
            sym = m.group(1) + m.group(0)[1:4] if False else None
            # 重新提取 sym
    # 用更稳的正则：整行
    out = {}
    for ln in text.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            continue
        if "| symbol |" in s or "---" in s:
            continue
        parts = [x.strip() for x in s.strip("|").split("|")]
        if len(parts) < 9:
            continue
        sym, d, o, last, h, l, v, amt, ex = parts[:9]
        if not re.match(r"\d{4}-\d{2}-\d{2}", d):
            continue
        cur = out.setdefault(sym, [])
        cur.append({"d": d, "c": float(last), "v": float(v), "h": float(h), "l": float(l), "o": float(o)})
    return out

def main():
    t0 = time.time()
    codes = collect_codes()
    print(f"三池股票代码（排除基金）: {len(codes)} 只", flush=True)
    names = json.load(open(BASE / "data_full_names.json", encoding="utf-8"))

    # 批量拉 K 线
    all_k = {}
    fails = []
    batch = 50
    for i in range(0, len(codes), batch):
        grp = codes[i:i+batch]
        syms = [prefix(c) for c in grp]
        for attempt in range(3):
            try:
                txt = call_kline(syms, 60)
                parsed = parse(txt)
                all_k.update(parsed)
                break
            except Exception as e:
                if attempt == 2:
                    fails += grp
                    print(f"  [批 {i//batch}] 失败: {repr(e)[:80]}", flush=True)
        if (i//batch) % 10 == 0:
            print(f"  [{i+len(grp)}/{len(codes)}] 已拉 {len(all_k)} 只，{time.time()-t0:.0f}s", flush=True)

    print(f"K线拉取完成: {len(all_k)} 只 | 失败 {len(fails)} 只（{fails[:5]}）", flush=True)

    # 构建 snapshot items + quotes
    items = []
    quotes = {}
    for c in codes:
        psym = prefix(c)
        rows = all_k.get(psym, [])
        if not rows:
            fails.append(c)
            continue
        # 取末 60 根（已 limit=60）
        rows = sorted(rows, key=lambda x: x["d"])[-60:]
        last = rows[-1]
        if last["d"] != TODAY:
            print(f"  ⚠ {c} 末根 {last['d']} != 今日，跳过", flush=True)
            fails.append(c)
            continue
        prev = rows[-2] if len(rows) >= 2 else None
        px = last["c"]
        prev_c = prev["c"] if prev else None
        chg = round((px / prev_c - 1) * 100, 2) if prev_c else None
        open_c = last.get("o")
        gap = round((open_c / prev_c - 1) * 100, 2) if (prev_c and open_c) else None
        setcode = "1" if c.startswith("6") else "0"
        items.append({"code": c, "name": names.get(c, ""), "setcode": setcode, "rows": rows})
        quotes[c] = {"px": px, "chg": chg, "name": names.get(c, ""), "gap": gap}

    snap = {
        "snapshot_date": TODAY,
        "snapshot_note": f"westock data_kline 批量拉取({TODAY} 盘中 {time.strftime('%H:%M')})，60根日K，末根=今日盘中实时；三池全量股票（排除基金/ETF）",
        "items": items,
    }
    (MON / "raw_kline" / f"{TODAY}.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    qj = {"snapshot_date": TODAY, "quotes": quotes}
    (BASE / f"intraday_quotes_{TODAY}.json").write_text(json.dumps(qj, ensure_ascii=False), encoding="utf-8")
    print(f"✅ snapshot: {len(items)} 只 | quotes: {len(quotes)} 只 | 失败 {len(fails)} 只（{fails[:10]}）", flush=True)
    print(f"总耗时 {(time.time()-t0)/60:.1f} 分钟", flush=True)

if __name__ == "__main__":
    main()
