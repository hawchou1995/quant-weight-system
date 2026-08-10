# -*- coding: utf-8 -*-
"""Parse tdx kline tool-result dump files into per-fund CSV."""
import json, os, re, csv

from config import DATA_DIR as OUT
FUNDS = {
    "008254": "华宝致远混合C",
    "018036": "长城新能源车股C",
    "002891": "华夏移动互联CNY",
    "024239": "华夏全球QDII C",
    "014002": "浦银智能科技C",
    "020900": "天弘通信设备C",
}

def extract_json(text):
    """Find the JSON block starting at 详细K线数据:"""
    m = re.search(r"详细K线数据:\s*\n(\{.*)", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        # try to find first { to last }
        raw = m.group(1)
        s, e = raw.find("{"), raw.rfind("}")
        try:
            return json.loads(raw[s:e+1])
        except Exception:
            return None

def dump_fund(fname, code, name):
    with open(fname, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    data = extract_json(text)
    if not data or not data.get("Rows"):
        print(f"FAIL {code} {name}: no rows")
        return
    rows = data["Rows"]
    out_path = os.path.join(OUT, f"{code}.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "open", "high", "low", "close", "volume", "amount"])
        for r in rows:
            # rows are newest-first? check: assume as returned (tdx newest first typically)
            w.writerow([
                str(r.get("Data", "")),
                str(r.get("Open", "")),
                str(r.get("High", "")),
                str(r.get("Low", "")),
                str(r.get("Close", "")),
                str(r.get("Volume", "")),
                str(r.get("Amount", "")),
            ])
    # sort ascending by date
    with open(out_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        f.write(lines[0])
        for line in sorted(lines[1:]):
            f.write(line)
    print(f"OK {code} {name}: {len(rows)} bars")

if __name__ == "__main__":
    import sys
    fname = sys.argv[1]
    code = None
    if len(sys.argv) > 2:
        code = sys.argv[2]
    else:
        m = re.search(r"(008254|018036|002891|024239|014002|020900)", fname)
        if m:
            code = m.group(1)
    if not code:
        print("NEED code arg")
        sys.exit(1)
    dump_fund(fname, code, FUNDS.get(code, code))
