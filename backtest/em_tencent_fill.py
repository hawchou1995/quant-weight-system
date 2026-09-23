# -*- coding: utf-8 -*-
"""腾讯批量补齐（R-em-tx-0923）—— 东财 em_bulk 通道的**兜底**，独立可跑，未接链
================================================================================
背景（2026-09-22/23 实测）
--------------------------------------------------------------------------------
东财 push 系列端点对本机**连接层整片丢包**，24h 未恢复：
  push2delay → 502（clist/ulist/stock 三端点同）｜ push2 → 302｜ 82.push2 → 连接被丢
同刻腾讯 `qt.gtimg.cn` 全程 200。已判定**不是限流**（判据：3 分钟里零请求，push2his 自己从
200 变 000 = 时间驱动；且 schannel 与 OpenSSL 两个 TLS 栈被同样丢弃）。
后果：`em_bulk_all.py`（快通道，秒级）0/3 失败 → 只能走 `update_daily.py --all`（慢通道，1-2h）。

本脚本 = 用**已验证可用**的腾讯批量通道顶上快通道的位置。

数据契约（与 em_bulk_snapshot.py 逐位一致）
--------------------------------------------------------------------------------
- 追加行：`{trade_day},{open},{high},{low},{close},{volume},{amount}` + 换行
- 幂等：只补「本地末行日期 < 交易日」的标的；末行 == 交易日 一律跳过
- 腾讯 `q=` 字段：`[2]代码 [3]现价(收盘后=收盘) [5]今开 [33]最高 [34]最低 [6]成交量(手) [37]成交额(万元)`
  → volume ×100 = 股；amount ×10000 = 元（与 data_full 既有列口径一致）
- ⚠ **精度差（实测）**：腾讯成交额只给到**万元整数**（EM 到元）→ amount 列与 EM 口径
  存在 ~0.001% 级差异（实测 sh600000: 458,950,000 vs 458,952,162）；date/OHLC/volume 逐位一致。
- ⚠ **只写收盘后**：校验收到的行情时间戳日期 == 交易日 **且 时间 ≥ 15:00** ——
  否则会把盘中价当收盘价写进去（不可逆污染）。这是本脚本唯一的硬门。
- 批量：腾讯实测上限 **400 码/请求**（800 → 浏览器 TypeError / curl 可过但浏览器不行）
  → 全市场约 14 个请求

用法
--------------------------------------------------------------------------------
    python backtest/em_tencent_fill.py --dry              # 只看待补清单，不写盘
    python backtest/em_tencent_fill.py                    # 补全部（股票+ETF）
    python backtest/em_tencent_fill.py --only etf         # 只补 ETF/基金
    python backtest/em_tencent_fill.py --limit 5          # 只补前 5 只（冒烟）
  - ⚠ manifest：写盘后回写 `data_full/_index.csv`（data_index.update_entries，2026-09-23 接链前置）——
    否则 update_daily 下次仍按旧 manifest 末行判定「滞后」→ 退回 1.4s/只 慢补（快通道白跑）。
退出码：0 = 正常（含"无待补"）；1 = 参数/环境错
"""
import glob
import os
import re
import subprocess
import sys
import urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data_full")
CAL = os.path.join(BASE, "index_000300.csv")

sys.path.insert(0, BASE)          # data_index 在项目根（manifest 回写用）
try:
    import data_index as DI       # 写盘后回写 _index.csv；导入失败则退化为"下次全量扫描"（无害）
except Exception:
    DI = None
CHUNK = 400          # 腾讯 q= 批量上限（实测；800 会被拒）
HOST = "https://qt.gtimg.cn/q="
ETF_PRE = ("51", "56", "58", "15", "16")


def trade_day():
    with open(CAL, encoding="utf-8") as f:
        rows = [l.split(",")[0] for l in f.read().strip().splitlines()[1:] if l[:4].isdigit()]
    return rows[-1]


def is_etf(code6):
    return code6.startswith(ETF_PRE)


def last_date(path):
    """只读末行（大文件省时间）"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            sz = f.tell()
            f.seek(max(0, sz - 4000))
            tail = f.read().decode("utf-8", "ignore").strip().splitlines()
        for ln in reversed(tail):
            if ln[:4].isdigit():
                return ln.split(",")[0]
    except Exception:
        pass
    return ""


def fetch_tx(codes, timeout=15):
    """返回 {code6: (ts, open, high, low, close, vol_股, amt_元)}"""
    q = ",".join(("sh" if c[0] in "659" else "sz") + c for c in codes)
    u = HOST + urllib.parse.quote(q, safe=",")
    r = subprocess.run(["curl", "-s", "-m", str(timeout), "--noproxy", "*", u],
                       capture_output=True)
    out = {}
    txt = r.stdout.decode("gbk", "replace")
    for ln in txt.split("\n"):
        i = ln.find('="')
        if i < 0:
            continue
        f = ln[i + 2:].rstrip().rstrip('";').split("~")
        if len(f) < 46:
            continue
        try:
            code, ts = f[2], f[30]
            o, hi, lo, c = float(f[5]), float(f[33]), float(f[34]), float(f[3])
            vol = float(f[6]) * 100.0            # 手 → 股
            amt = float(f[37]) * 1e4             # 万元 → 元
        except Exception:
            continue
        out[code] = (ts, o, hi, lo, c, vol, amt)
    return out


def main():
    args = sys.argv[1:]
    dry = "--dry" in args
    only = None
    if "--only" in args:
        only = args[args.index("--only") + 1]
    limit = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    allow = None
    if "--syms-file" in args:
        _sfp = args[args.index("--syms-file") + 1]
        try:
            with open(_sfp, encoding="utf-8") as _f:
                allow = {ln.strip()[-6:] for ln in _f if ln.strip()}
        except Exception as _e:
            print(f"[err] 读 --syms-file 失败：{type(_e).__name__}: {_e}")
            return 1
        print(f"[filter] --syms-file 限定 {len(allow)} 只")


    day = trade_day()
    files = sorted(glob.glob(os.path.join(DATA, "*.csv")))
    tgt, stock_n, etf_n = [], 0, 0
    for p in files:
        stem = os.path.basename(p)[:-4]                 # sh600000
        # R-em-tx-0923 修：data_full 里除标的外还有 index*/其它文件 → 必须窄匹配，否则会把它们当标的
        if not re.match(r"^(sh|sz)\d{6}$", stem):
            continue
        if stem.startswith("bj"):
            continue                                     # 不做北交所
        c6 = stem[2:]
        etf = is_etf(c6)
        if only == "etf" and not etf:
            continue
        if only == "stock" and etf:
            continue
        if allow is not None and c6 not in allow:
            continue
        if last_date(p) >= day:
            continue
        tgt.append((c6, p))
        etf_n += 1 if etf else 0
        stock_n += 0 if etf else 1
    print(f"[scan] 交易日 {day} | 待补 {len(tgt)} 只（股票 {stock_n} / ETF {etf_n}）"
          f" | 数据目录 {len(files)} 个文件")
    if not tgt:
        print("[done] 无待补 —— 全量池已是最新")
        return 0
    if limit:
        tgt = tgt[:limit]
        print(f"[plan] --limit {limit} → 只处理前 {len(tgt)} 只")

    # ---- 先取行情（分批），并统一做"收盘后"校验 ----
    quotes = {}
    for i in range(0, len(tgt), CHUNK):
        batch = [c for c, _ in tgt[i:i + CHUNK]]
        quotes.update(fetch_tx(batch))
        print(f"   拉取 {min(i + CHUNK, len(tgt))}/{len(tgt)} …", flush=True)
    ymd = day.replace("-", "")
    good, warm = {}, 0
    for c6, _ in tgt:
        q = quotes.get(c6)
        if not q:
            continue
        ts = q[0]
        if not (ts[:8] == ymd and ts[8:12] >= "1500"):
            warm += 1
            continue
        o, hi, lo, c, vol, amt = q[1:]
        if not (c > 0 and hi >= max(o, c) and lo <= min(o, c) and lo > 0):
            continue
        good[c6] = (o, hi, lo, c, vol, amt)

    print(f"[quote] 取到 {len(quotes)} 只 / 通过收盘校验 {len(good)} 只"
          f"（未收盘或时间戳不符 {warm} 只）")
    if dry:
        print("[dry] 未写盘。样例：")
        for c6, _ in tgt[:5]:
            g = good.get(c6)
            print(f"   {c6}: {day},{g[0]},{g[1]},{g[2]},{g[3]},{g[4]:.0f},{g[5]:.0f}" if g else f"   {c6}: （无有效行情）")
        return 0

    wrote, miss = 0, 0
    for c6, p in tgt:
        g = good.get(c6)
        if not g:
            miss += 1
            continue
        o, hi, lo, c, vol, amt = g
        try:
            with open(p, encoding="utf-8") as f:
                body = f.read().rstrip("\n")
            with open(p, "w", encoding="utf-8") as f:
                f.write(body + f"\n{day},{o},{hi},{lo},{c},{vol:.0f},{amt:.0f}\n")
            wrote += 1
        except Exception as e:
            print(f"   !! {c6} 写失败 {type(e).__name__}: {e}")
    # 2026-09-23 接链前置（PI 复核）：写盘后必须回写 manifest —— data_index.load_index() 只校验
    #   manifest 全局过期(>3天)/文件数，**不校验单条 mtime/size**；不回写则 update_daily 下次
    #   仍按旧末行判定「滞后」→ 退回 1.4s/只 慢补，快通道白跑。rows 传 0 = 保留原值（update_entries 语义）。
    if DI is not None and wrote:
        try:
            DI.update_entries([(os.path.basename(p)[:-4], day, 0) for c6, p in tgt if c6 in good])
        except Exception as e:
            print(f"   !! manifest 回写失败（下次 scan_lag 退回全量扫描）：{type(e).__name__}: {e}")
    print(f"[done] 补齐 {wrote}/{len(tgt)} 只 → {day}（无有效行情 {miss} 只）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
