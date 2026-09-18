# -*- coding: utf-8 -*-
"""东财全市场批量快照补齐器（R-em-bulk-0918）。

为什么建：今天（2026-09-18）暴露了主链取数的结构性缺陷——
`update_daily.py --all` 走**逐只 K 线**（7539 次请求），今日被限流到 1.4s/只 ≈ 3 小时；
而 KHunter 本地版走**东财全市场批量快照** `push2.eastmoney.com/api/qt/clist/get`：
一次翻页（100 只/页 × 56 页）**3.27 秒**拿全 A 股当日 OHLCV。

本脚本：拉东财全市场当日快照 → **校验单位/口径** → 给本地 data_full 缺当日的标的**补一行**。
只补不改：已有当日行的一律跳过；单位校验不过就整体放弃（不写盘）。

字段口径（2026-09-18 实测对拍，sh600519 与本地 09-18 行逐位一致）：
    f12=代码 f14=名称 f13=市场(1沪/0深) f17=开 f15=高 f16=低 f2=收
    f5=成交量(手，与本地同口径)  f6=成交额(元)  f18=昨收  f3=涨跌幅%
用法：
    python backtest/em_bulk_snapshot.py --dry          # 只校验，不写盘
    python backtest/em_bulk_snapshot.py                # 校验通过后补齐
    python backtest/em_bulk_snapshot.py --limit 300    # 只补前 N 只（灰度）
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

# 主机选择（2026-09-18 实测矩阵）：push2*.eastmoney.com 主镜像在密集请求后集体 502/断连；
# push2delay.eastmoney.com（延时行情主机）http/https 均可用。收盘后「延时=最终收盘价」→ EOD 补齐无损。
HOSTS = ["push2delay.eastmoney.com", "push2.eastmoney.com", "82.push2.eastmoney.com"]
URL = "https://" + HOSTS[0] + "/api/qt/clist/get"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/javascript, */*",
    "Referer": "https://quote.eastmoney.com/",
}
FIELDS = "f2,f3,f5,f6,f12,f13,f14,f15,f16,f17,f18"
# 沪深主板/创业板/科创板 + 北交所
FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
HDR = ["date", "open", "high", "low", "close", "volume", "amount"]
MISMATCH_TOL = 0.02          # 单位/口径校验：允许 2% 不一致


def page(pn, pz=100, retries=4):
    params = {"pn": str(pn), "pz": str(pz), "po": "1", "np": "1",
              "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": "2", "invt": "2",
              "fid": "f12", "fs": FS, "fields": FIELDS, "_": int(time.time() * 1000)}
    last = None
    for i in range(1, retries + 1):
        host = HOSTS[(i - 1) % len(HOSTS)]          # 失败轮换主机
        u = "https://" + host + "/api/qt/clist/get?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=HEADERS), timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8", "ignore"))
        except Exception as e:
            last = e
            # 东财连打会间歇 4xx/5xx → 退避 + 轮换主机
            time.sleep(1.2 * i)
    raise RuntimeError(f"page {pn} 连续 {retries} 次失败: {type(last).__name__} {last}")


def pull_all():
    rows, pn, total = [], 1, None
    t0 = time.time()
    while True:
        d = page(pn)
        data = d.get("data") or {}
        total = data.get("total") or total
        diff = data.get("diff") or []
        if not diff:
            break
        rows.extend(diff)
        if total and len(rows) >= total:
            break
        pn += 1
        if pn > 120:
            break
        time.sleep(0.12)          # 页间节流：56 页共 ~7s，换来 0 失败
    return rows, total, time.time() - t0



def sym_of(r):
    """东财 f12/f13 → 本地文件名 sh600519 / sz000001 / bj920000"""
    c = str(r.get("f12") or "")
    if len(c) != 6 or not c.isdigit():
        return None
    if c[0] in ("4", "8", "9"):          # 北交所
        return "bj" + c
    return ("sh" if str(r.get("f13")) == "1" else "sz") + c


def vol_factor(sym: str) -> float:
    """东财 f5 → 本地 volume（股）的市场换算因子。

    ⚠ 2026-09-18 实测（1354 只可比样本，各市场桶内 100% 单一档位）：**科创板是特例**——
    东财对 sh688* 按「万股」报量，其余市场按「手」：
        sh688科创板 → ×10000 ；bj北交所 / sh60 / sz00 / sz30 / 其他 → ×100
    一律用 ×100 会把 87 只科创板的成交量写错 100 倍（dry-run 校验器拦下过）。
    """
    return 10000.0 if sym.startswith("sh688") else 100.0


def last_row(p: Path):
    """(date, open, high, low, close, volume, amount) 或 None"""
    try:
        with open(p, "rb") as fh:
            fh.seek(0, 2)
            sz = fh.tell()
            fh.seek(max(0, sz - 400))
            lines = [l for l in fh.read().decode("utf-8", "ignore").strip().splitlines() if l.strip()]
        parts = lines[-1].split(",")
        if len(parts) < 7:
            return None
        return (parts[0][:10], float(parts[1]), float(parts[2]), float(parts[3]),
                float(parts[4]), float(parts[5]), float(parts[6]))
    except Exception:
        return None


def num(v):
    return float(v) if isinstance(v, (int, float)) else None


def main():
    dry = "--dry" in sys.argv
    limit = 0
    if "--limit" in sys.argv and len(sys.argv) > sys.argv.index("--limit") + 1:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    trade_day = open(CAL, encoding="utf-8").read().strip().splitlines()[-1].split(",")[0][:10]
    print(f"[cal] 目标交易日 {trade_day}")

    rows, total, el = pull_all()
    print(f"[em] 拉取 {len(rows)}/{total} 只（{el:.2f}s）")

    m = {}
    for r in rows:
        s = sym_of(r)
        if s:
            m[s] = r
    print(f"[em] 可用标的 {len(m)} 只")

    # ---- ① 单位/口径校验：本地已是最新交易日的标的，逐位对比 ----
    ok_cmp = bad_cmp = 0
    bad_samples = []
    for s, r in m.items():
        p = DATA / f"{s}.csv"
        if not p.exists():
            continue
        lr = last_row(p)
        if not lr or lr[0] != trade_day:
            continue
        e_o, e_h, e_l, e_c = num(r.get("f17")), num(r.get("f15")), num(r.get("f16")), num(r.get("f2"))
        e_v, e_a = num(r.get("f5")), num(r.get("f6"))
        e_v = None if e_v is None else e_v * vol_factor(s)   # 东财 f5 → 股（科创板 ×10000，其余 ×100）
        if None in (e_o, e_h, e_l, e_c):
            continue
        good = (abs(lr[1] - e_o) < 0.02 and abs(lr[2] - e_h) < 0.02
                and abs(lr[3] - e_l) < 0.02 and abs(lr[4] - e_c) < 0.02
                and (e_v is None or abs(lr[5] - e_v) <= max(1.0, e_v * 0.01)))
        if good:
            ok_cmp += 1
        else:
            bad_cmp += 1
            if len(bad_samples) < 5:
                bad_samples.append((s, lr, (e_o, e_h, e_l, e_c, e_v)))
    tot_cmp = ok_cmp + bad_cmp
    if tot_cmp < 20:
        print(f"!! 可比样本仅 {tot_cmp} 只，不足以判口径 —— 放弃写盘（等主链先跑出一批当日行）")
        return 2
    rate = bad_cmp / tot_cmp
    print(f"[check] 可比 {tot_cmp} 只：一致 {ok_cmp} / 不一致 {bad_cmp}（{rate:.2%}，容忍 {MISMATCH_TOL:.0%}）")
    for s, lr, e in bad_samples:
        print(f"   × {s} 本地={lr} 东财={e}")
    if rate > MISMATCH_TOL:
        print("!! 不一致率超容忍 → 口径未对齐，**放弃写盘**")
        return 2

    # ---- ② 补齐 ----
    tgt = []
    for s, r in sorted(m.items()):
        p = DATA / f"{s}.csv"
        lr = last_row(p)
        if lr and lr[0] >= trade_day:
            continue                       # 已有当日及更新 → 跳过（只补不改）
        e_o, e_h, e_l, e_c = num(r.get("f17")), num(r.get("f15")), num(r.get("f16")), num(r.get("f2"))
        e_v, e_a = num(r.get("f5")), num(r.get("f6"))
        e_v = None if e_v is None else e_v * vol_factor(s)   # 东财 f5 → 股（科创板 ×10000，其余 ×100）
        if None in (e_o, e_h, e_l, e_c) or e_c <= 0 or e_o <= 0:
            continue                       # 停牌/无值
        if lr is None and not p.exists():
            continue                       # 本地无此文件 → 不新建（避免引入未审计标的）
        tgt.append((s, p, e_o, e_h, e_l, e_c, e_v or 0.0, e_a or 0.0))
    if limit:
        tgt = tgt[:limit]
    print(f"[plan] 待补 {len(tgt)} 只" + (f"（--limit {limit}）" if limit else ""))

    if dry:
        print("[dry] 未写盘。样例：")
        for s, p, o, h, l, c, v, a in tgt[:5]:
            print(f"   {s}: {trade_day},{o},{h},{l},{c},{v},{a}")
        return 0

    wrote = 0
    for s, p, o, h, l, c, v, a in tgt:
        try:
            p.write_text(p.read_text(encoding="utf-8").rstrip("\n")
                         + f"\n{trade_day},{o},{h},{l},{c},{v},{a}\n", encoding="utf-8")
            wrote += 1
        except Exception as e:
            print(f"   !! {s} 写失败 {type(e).__name__}: {e}")
    print(f"[done] 补齐 {wrote}/{len(tgt)} 只 → {trade_day}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
