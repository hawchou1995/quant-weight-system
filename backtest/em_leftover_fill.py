# -*- coding: utf-8 -*-
"""补 clist 未覆盖的残余陈旧标的（单只报价端点）。

背景：29 只残留陈旧 ETF/基金中，27 只 `sz159*` 在**所有** clist 分类里都找不到
（实测 MK0021-26 / MK0401-05 并集覆盖仅 2/29）；但单只端点
`push2delay.eastmoney.com/api/qt/stock/get?secid=<mkt>.<code>` 有它们的数据。
本脚本用单只端点补，**先与 clist 交叉验证口径**（同一只票两个端点必须一致）再写盘。
"""
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(__file__).resolve().parent.parent  # 2026-09-24 云端可移植（原写死 D:/…，本机解析恒等）
DATA = BASE / "data_full"
CAL = BASE / "index_000300.csv"
H = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
     "Accept": "application/json, text/javascript, */*",
     "Referer": "https://quote.eastmoney.com/"
     }
HOSTS_GET = ["push2delay.eastmoney.com", "push2.eastmoney.com", "82.push2.eastmoney.com"]
CLIST = "https://push2delay.eastmoney.com/api/qt/clist/get"
GET = "https://{host}/api/qt/stock/get"
F_GET = "f43,f44,f45,f46,f47,f48,f58,f60"      # 现价/高/低/开/量/额/名/昨收


_GOOD = {"host": None}


def get_one(secid):
    """单只报价（f47=量「手」、f48=额「元」）。
    2026-09-23 改：三台主机轮换、每台 1 次（原来死钉 push2delay 且同主机重试 3 次，
    端点一被限流就白敲 3 次）；主机可达即记住复用。返回 data 或 None。"""
    hosts = [_GOOD["host"]] if _GOOD["host"] else HOSTS_GET
    P = {"secid": secid, "ut": "fa5fd1943c7b386f172d6893dbfba10b", "invt": "2",
         "fltt": "2", "fields": F_GET, "_": str(int(time.time() * 1000))}
    for h in hosts:
        try:
            d = json.loads(urllib.request.urlopen(
                urllib.request.Request(GET.format(host=h) + "?" + urllib.parse.urlencode(P),
                                       headers=H),
                timeout=12).read().decode("utf-8", "ignore"))
            _GOOD["host"] = h          # 主机可达（该标的有无数据另说）
            return d.get("data")
        except Exception:
            continue
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


# ---- ① 干活闸 + 端点探活 + 口径共识（2026-09-23 重写）----
# 旧版把口径校验硬编码在单只 sz158000 上：端点一被限流（返回空）就误报「口径不一致」
# 并 sys.exit(2) 整步退出，日志还误导人去核对口径。现改为：
#   ① 先扫「残余陈旧 ETF/基金」：没有 → 一个请求都不发，直接成功退出
#   ② 多样本（≤8 只本地已新鲜的 ETF/基金）中位比 → 因子 fac（100 / 10000，±5% 收口）
#   ③ 首样本无响应 = 端点不可用 → rc=3（与「口径问题 rc=2」分开报）
ETF_SH = ("510", "511", "512", "513", "515", "516", "517", "518", "520", "521", "522", "523",
          "526", "560", "561", "562", "563", "588", "589", "501", "502", "506", "508")


def is_etf(s):
    cc = s[2:]
    return (s.startswith("sh") and cc[:3] in ETF_SH) \
        or (s.startswith("sz") and cc[:2] in ("15", "16", "18"))


trade_day = open(CAL, encoding="utf-8").read().strip().splitlines()[-1].split(",")[0][:10]
dry = "--dry" in sys.argv

# ---- ② 找残余陈旧 ETF/基金（没有 → 零请求直接成功退出）----
stale = []
for f in sorted(DATA.glob("*.csv")):
    s = f.stem
    if not is_etf(s):
        continue
    r = last_row(f)
    if r and r[0] < trade_day:
        stale.append((s, r[0]))
print(f"[stale] {len(stale)} 只待补（末行 < {trade_day}）")
if not stale:
    print("[skip] 无残余陈旧 → 一个请求都不发；本步完成")
    sys.exit(0)

# ---- ①′ 口径共识：≤8 只本地已新鲜的 ETF/基金，比「本地量 / 端点量」中位比 ----
print("=== 口径共识（本地已新鲜 ETF/基金 vs 单只端点，多样本中位比）===")
cand = []
for f in sorted(DATA.glob("*.csv")):
    s = f.stem
    if not is_etf(s):
        continue
    r = last_row(f)
    if r and r[0] >= trade_day and r[5] > 0:
        cand.append((s, r))
    if len(cand) >= 8:
        break
ratios, nodata, noresp = [], 0, 0
for i, (s, lr) in enumerate(cand):
    mk = "1" if s.startswith("sh") else "0"
    d = get_one(f"{mk}.{s[2:]}")
    if not d:
        if i == 0:
            print("!! 首样本无响应 → 单只端点当前不可用（限流/被拦）；本步不做；rc=3")
            sys.exit(3)
        noresp += 1
        continue
    v = d.get("f47")
    if not isinstance(v, (int, float)) or v <= 0:
        nodata += 1
        continue
    ratios.append(lr[5] / float(v))
    print(f"   {s}: 本地量 {lr[5]:.0f} / 端点量 {v:.0f} = {lr[5] / float(v):.2f}")
if not ratios:
    print(f"!! 端点无有效样本（无响应 {noresp} / 无成交 {nodata}）"
          f"→ 单只端点当前不可用；本步不做；rc=3")
    sys.exit(3)
med = statistics.median(ratios)
fac = 100.0 if abs(med - 100.0) <= 5 else (10000.0 if abs(med - 10000.0) <= 500 else None)
ins = sum(1 for x in ratios if abs(x - fac) <= fac * 0.05) if fac else 0
print(f"   中位比 {med:.2f}（n={len(ratios)}）→ 因子 fac={fac}；±5% 内 {ins}/{len(ratios)}")
if fac is None or ins < max(2, int(len(ratios) * 0.6)):
    print("!! 口径未达成共识 → 放弃写盘（先人工核对）；rc=2")
    sys.exit(2)

# ---- ③ 单只端点补（量「手」× fac → 股；再用均价夹逼校验）----
wrote, skipped = 0, []
for s, lastd in stale:
    mk = "1" if s.startswith("sh") else "0"
    d = get_one(f"{mk}.{s[2:]}")
    if not d:
        skipped.append((s, "端点无返回")); continue
    o, h, l, cl, v, a = (d.get("f46"), d.get("f44"), d.get("f45"),
                         d.get("f43"), d.get("f47"), d.get("f48"))
    if not all(isinstance(x, (int, float)) and x > 0 for x in (o, h, l, cl)):
        skipped.append((s, "今日无成交（停牌/未开盘）")); continue
    if not isinstance(v, (int, float)) or v <= 0:
        skipped.append((s, "端点量缺失")); continue
    vv = v * fac                                   # 手 → 股（与 clist/ulist 通道同口径）
    aa = a if isinstance(a, (int, float)) else 0.0
    if aa > 0 and not (l * 0.97 <= aa / vv <= h * 1.03):
        skipped.append((s, f"均价离群 {aa / vv:.4f} 不在 [{l},{h}]")); continue
    row = f"{trade_day},{o},{h},{l},{cl},{vv},{aa}"
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
