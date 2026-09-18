# -*- coding: utf-8 -*-
"""补 clist 未覆盖的残余陈旧标的（单只报价端点）。

背景：29 只残留陈旧 ETF/基金中，27 只 `sz159*` 在**所有** clist 分类里都找不到
（实测 MK0021-26 / MK0401-05 并集覆盖仅 2/29）；但单只端点
`push2delay.eastmoney.com/api/qt/stock/get?secid=<mkt>.<code>` 有它们的数据。
本脚本用单只端点补，**先与 clist 交叉验证口径**（同一只票两个端点必须一致）再写盘。
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
DATA = BASE / "data_full"
CAL = BASE / "index_000300.csv"
H = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
     "Accept": "application/json, text/javascript, */*",
     "Referer": "https://quote.eastmoney.com/"
     }
CLIST = "https://push2delay.eastmoney.com/api/qt/clist/get"
GET = "https://push2delay.eastmoney.com/api/qt/stock/get"
F_GET = "f43,f44,f45,f46,f47,f48,f58,f60"      # 现价/高/低/开/量/额/名/昨收


def get_one(secid):
    P = {"secid": secid, "ut": "fa5fd1943c7b386f172d6893dbfba10b", "invt": "2",
         "fltt": "2", "fields": F_GET, "_": str(int(time.time() * 1000))}
    for i in range(3):
        try:
            d = json.loads(urllib.request.urlopen(
                urllib.request.Request(GET + "?" + urllib.parse.urlencode(P), headers=H),
                timeout=12).read().decode("utf-8", "ignore"))
            return d.get("data")
        except Exception:
            time.sleep(1.0)
    return None


def clist_one(fs, code):
    P = {"pn": "1", "pz": "100", "po": "1", "np": "1", "ut": "bd1d9ddb04089700cf9c27f6f7426281",
         "fltt": "2", "invt": "2", "fid": "f12", "fs": fs, "fields": "f12,f2,f5,f15,f16,f17",
         "_": str(int(time.time() * 1000))}
    for i in range(3):
        try:
            d = json.loads(urllib.request.urlopen(
                urllib.request.Request(CLIST + "?" + urllib.parse.urlencode(P), headers=H),
                timeout=15).read().decode("utf-8", "ignore"))
            for r in ((d.get("data") or {}).get("diff") or []):
                if str(r.get("f12")) == code:
                    return r
        except Exception:
            time.sleep(1.0)
    return None


def last_row(p):
    try:
        with open(p, "rb") as fh:
            fh.seek(0, 2)
            sz = fh.tell()
            fh.seek(max(0, sz - 400))
            L = [x for x in fh.read().decode("utf-8", "ignore").strip().splitlines() if x.strip()]
        q = L[-1].split(",")
        return (q[0][:10], float(q[1]), float(q[2]), float(q[3]), float(q[4]), float(q[5]), float(q[6]))
    except Exception:
        return None


# ---- ① 口径交叉验证：拿「刚由 clist 补好的」sz158000 当基准（本地行即 clist 写的）----
print("=== 口径交叉验证（clist 已写入的本地行 vs 单只端点）===")
lr = last_row(DATA / "sz158000.csv")
g = get_one("0.158000")
print(f"  本地(clist源): {lr}")
if g:
    print(f"  单只端点     : 开={g.get('f46')} 高={g.get('f44')} 低={g.get('f45')} "
          f"现价={g.get('f43')} 量={g.get('f47')} 额={g.get('f48')} 名={g.get('f58')!r}")
    same = (lr and abs(lr[1] - float(g.get("f46") or -1)) < 0.02
            and abs(lr[4] - float(g.get("f43") or -1)) < 0.02
            and float(g.get("f47") or 0) > 0
            and abs(lr[5] - float(g.get("f47")) * 100.0) <= max(1.0, float(g["f47"]) * 100.0 * 0.01))
    print("  （量需 ×100：单只端点 f47 同为「手」，本地存「股」——实测 38041 vs 本地 3,804,100）")
else:
    same = False
print(f"  两端口径一致 = {same}")
if not same:
    print("!! 口径不一致 → 放弃（先人工核对）")
    sys.exit(2)

trade_day = open(CAL, encoding="utf-8").read().strip().splitlines()[-1].split(",")[0][:10]
dry = "--dry" in sys.argv

# ---- ② 找残余陈旧 ETF/基金 ----
stale = []
for f in sorted(DATA.glob("*.csv")):
    s = f.stem
    cc = s[2:]
    isetf = (s.startswith("sh") and cc[:3] in ("510", "511", "512", "513", "515", "516", "517", "518",
                                               "520", "521", "522", "523", "526", "560", "561", "562",
                                               "563", "588", "589", "501", "502", "506", "508")) \
        or (s.startswith("sz") and cc[:2] in ("15", "16", "18"))
    if not isetf:
        continue
    r = last_row(f)
    if r and r[0] < trade_day:
        stale.append((s, r[0]))
print(f"\n[stale] {len(stale)} 只待补（末行 < {trade_day}）")

# ---- ③ 单只端点补 ----
wrote, skipped = 0, []
for s, lastd in stale:
    mk = "1" if s.startswith("sh") else "0"
    d = get_one(f"{mk}.{s[2:]}")
    if not d:
        skipped.append((s, "端点无返回")); continue
    o, h, l, cl, v, a = d.get("f46"), d.get("f44"), d.get("f45"), d.get("f43"), d.get("f47"), d.get("f48")
    if not all(isinstance(x, (int, float)) and x > 0 for x in (o, h, l, cl)):
        skipped.append((s, "今日无成交（停牌/未开盘）")); continue
    v = v * 100.0 if isinstance(v, (int, float)) else 0.0      # 手 → 股（与 clist 通道同口径）
    row = (f"{trade_day},{o},{h},{l},{cl},{v},"
           f"{a if isinstance(a, (int, float)) else 0}")
    if dry:
        print(f"  [dry] {s} ← {row}")
    else:
        p = DATA / f"{s}.csv"
        p.write_text(p.read_text(encoding="utf-8").rstrip("\n") + "\n" + row + "\n", encoding="utf-8")
    wrote += 1
    print(f"  [{'dry' if dry else 'ok'}] {s} 末行 {lastd} → {trade_day}  {d.get('f58')}")

print(f"\n[none] 补齐 {wrote}/{len(stale)}")
for s, why in skipped:
    print(f"   跳过 {s}：{why}")
