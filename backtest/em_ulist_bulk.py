# -*- coding: utf-8 -*-
"""东财 ulist 批量补齐器（次选通道 · R-em-ulist-0923 v3）。

定位：**clist 是首选**（backtest/em_bulk_snapshot.py，56 页秒级拿全市场）；
本脚本只在 clist 不可用时兜底（clist/get 端点被拦时 ulist.np/get 仍 200）。

2026-09-23 实测（代理出口 103.151.173.91）：
  · clist/get：push2delay/push2 握手超时、82.push2 RemoteDisconnected、经代理 502 nginx → 端点级拦截
  · ulist.np/get：n=1/10/50/100/200/500 全 200（500 只 2.76s），n=1000 → HTTP 414（URL 过长）
  · 连打十几批后被限流（RemoteDisconnected）→ 省请求 + 批间冷却 + 失败批冷却重试
  · 口径：clist 对 sh688 是 ×10000、其余 ×100；ulist 实测 sh688 也是 ×100 —— 端点相关，按实测走

设计（都是为「省请求 + 不错写」服务）：
  · **只取缺口**：只对「本地末行 < 目标交易日」的标的发请求；已新鲜的只抽样校验
    （沪深缺口为 0 时全脚本只发 1 个请求）。
  · **自校验因子**（不依赖本地样本）：东财自家数据自洽 —— 成交量(股) ≈ 成交额(f6)/均价，
    均价取 (f15+f16+2×f2)/4 ⇒ K = (f6/均价)/f5。中位 K 落 100±5% → ×100；落 10000±5% → ×10000。
    对**所有取到的行**都成立（含缺口标的），所以「本地无新鲜样本」的分组（如北交所）也能校验。
  · **本地样本交叉验证**：组内「本地volume / 东财f5」中位比必须与自校验因子一致，冲突则整组跳过。
  · **分组前缀精确划分**（修 v2 的 sh60 误归基金组）：sh688/sh60/sh5xx/…、sz30/sz00/sz1xx/…
  · 与 clist 版同语义：只补不改、停牌/无值跳过、写盘复用「读-加行-写」。

用法：
    python backtest/em_ulist_bulk.py --dry            # 只校验+报缺口，不写盘
    python backtest/em_ulist_bulk.py                  # 补齐缺口
    python backtest/em_ulist_bulk.py --limit 200      # 只补前 N 只
    python backtest/em_ulist_bulk.py --bj             # 缺口含北交所（默认不含）
"""
import json
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
DATA = BASE / "data_full"
CAL = BASE / "index_000300.csv"

HOSTS = ["push2delay.eastmoney.com", "push2.eastmoney.com", "82.push2.eastmoney.com"]
UT = "bd1d9ddb04089700cf9c27f6f7426281"
FIELDS = "f2,f3,f5,f6,f12,f13,f14,f15,f16,f17,f18"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/javascript, */*",
    "Referer": "https://quote.eastmoney.com/",
}
BATCH = 480            # 实测 500 可行 / 1000 → 414；批次越少越不容易触发限流
SAMPLE_PER_GROUP = 20  # 每组抽样校验只数（只对「已新鲜」标的取样，仍只占 1 个请求）
BATCH_SLEEP = 1.2      # 批间冷却秒（v1 连打十几批即被限流）
COOLDOWN = 30          # 失败批冷却重试间隔秒
TOL_SNAP = 0.05        # 档位容差 ±5%
SELF_OUTLIER = 0.08    # 自校验离群阈值（均价用 (H+L+2C)/4 近似 VWAP，放宽到 ±8%）
LOCAL_OUTLIER = 0.05   # 本地样本离群阈值（本地volume 是精确值）
MAX_OUTLIER_FRAC = 0.25


def grp(sym):
    """按交易所前缀精确分组（v2 的 sym[2] in "5679" 会把 sh60 误归基金组）"""
    if sym.startswith("sh688") or sym.startswith("sh689"):
        return "sh688 科创板"
    if sym.startswith("sh60"):
        return "sh60 沪主板"
    if sym.startswith("sh5"):
        return "sh5xx 沪基金"
    if sym.startswith("sh"):
        return "sh 其他(7/9/11x债等)"
    if sym.startswith("sz30"):
        return "sz30 创业板"
    if sym.startswith("sz00"):
        return "sz00 深主板"
    if sym.startswith("sz1"):
        return "sz1xx 深基金债"
    if sym.startswith("sz"):
        return "sz 其他(2/3/8 等)"
    return "bj 北交所"


def secid(sym):
    return ("1." if sym.startswith("sh") else "0.") + sym[2:]


def last_row(p):
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
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def k_self(r):
    """东财自家数据自洽：K = 估算股数 / f5(手)，估算股数 = f6(元) / 均价"""
    f2, f5, f6 = num(r.get("f2")), num(r.get("f5")), num(r.get("f6"))
    f15, f16 = num(r.get("f15")), num(r.get("f16"))
    if not f2 or f2 <= 0 or not f5 or f5 <= 0 or not f6 or f6 <= 0:
        return None
    hi = f15 if (f15 and f15 > 0) else f2
    lo = f16 if (f16 and f16 > 0) else f2
    avgp = (hi + lo + 2 * f2) / 4.0
    if avgp <= 0:
        return None
    return (f6 / avgp) / f5


def fetch(syms, host_idx=0, retries=4, timeout=25):
    """一批 ≤BATCH 只；返回 {sym: row}；失败抛异常"""
    secs = ",".join(secid(s) for s in syms)
    last = None
    for i in range(1, retries + 1):
        host = HOSTS[(host_idx + i - 1) % len(HOSTS)]
        u = (f"https://{host}/api/qt/ulist.np/get?fltt=2&invt=2&secids={secs}"
             f"&fields={FIELDS}&ut={UT}&_={int(time.time() * 1000)}")
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=HEADERS), timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8", "ignore"))
            out = {}
            for row in (d.get("data") or {}).get("diff") or []:
                c = str(row.get("f12") or "")
                if len(c) == 6 and c.isdigit():
                    m = "sh" if str(row.get("f13")) == "1" else ("bj" if c[0] in ("4", "8", "9") else "sz")
                    out[m + c] = row
            return out
        except Exception as e:
            last = e
            time.sleep(1.2 * i)
    raise RuntimeError(f"{type(last).__name__} {last}")


def main():
    dry = "--dry" in sys.argv
    with_bj = "--bj" in sys.argv
    limit = 0
    if "--limit" in sys.argv and len(sys.argv) > sys.argv.index("--limit") + 1:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    trade_day = open(CAL, encoding="utf-8").read().strip().splitlines()[-1].split(",")[0][:10]
    syms = []
    for f in sorted(os.listdir(DATA)):
        if not f.endswith(".csv"):
            continue
        s = f[:-4]
        if len(s) == 8 and s[2:].isdigit() and (s[:2] in ("sh", "sz") or (with_bj and s[:2] == "bj")):
            syms.append(s)

    gap, fresh = [], {}
    for s in syms:
        lr = last_row(DATA / f"{s}.csv")
        if lr and lr[0] >= trade_day:
            fresh.setdefault(grp(s), []).append(s)
        else:
            gap.append(s)
    print(f"[cal] 目标交易日 {trade_day} | 池 {len(syms)} 只 | 缺当日 {len(gap)} 只"
          f"（{'含' if with_bj else '不含'}北交所）", flush=True)

    # ---- ⓪ 缺口/端点闸（2026-09-23 加）----
    #  缺口 0 → 一个请求都不发（链里每天先由 clist/ulist 写满，此处通常直接秒过）
    #  有缺口但端点被限流 → ≤3 次探测即退（rc=3），不再走「每批 4 重试 × N 批 + 30s 冷却」
    if not gap:
        print("[skip] 缺口 0 只 → 一个请求都不发；本步完成", flush=True)
        return 0
    try:
        fetch(syms[:2], retries=3, timeout=6)
    except Exception as e:
        print(f"!! ulist 端点探活失败（{type(e).__name__}: {str(e)[:80]}）"
              f"→ 端点当前不可用（限流/被拦）；本步不做；rc=3", flush=True)
        return 3

    # ---- ① 因子校验：分组抽样（1 个请求）+ 自校验/本地样本双判据 ----
    sample = []
    for g, lst in sorted(fresh.items()):
        step = max(1, len(lst) // SAMPLE_PER_GROUP)
        sample.extend(lst[::step][:SAMPLE_PER_GROUP])
    ks_by, ls_by, notes = {}, {}, []
    nreq = 0
    for i in range(0, len(sample), BATCH):
        chunk = sample[i:i + BATCH]
        try:
            data = fetch(chunk, host_idx=nreq)
            nreq += 1
        except Exception as e:
            print(f"  !! 校验批失败：{str(e)[:100]}", flush=True)
            continue
        for s, r in data.items():
            kk = k_self(r)
            if kk:
                ks_by.setdefault(grp(s), []).append(kk)
            lr = last_row(DATA / f"{s}.csv")
            f5 = num(r.get("f5"))
            if lr and lr[0] == trade_day and lr[5] > 0 and f5 and f5 > 0:
                ls_by.setdefault(grp(s), []).append(lr[5] / f5)
        time.sleep(0.3)

    factors, reasons = {}, {}
    for g in sorted(set(fresh) | set(ks_by)):
        ks, ls = ks_by.get(g, []), ls_by.get(g, [])
        note, fac = [], None
        if len(ks) >= 5:
            med = statistics.median(ks)
            if abs(med / 100.0 - 1) <= TOL_SNAP:
                fac = 100.0
            elif abs(med / 10000.0 - 1) <= TOL_SNAP:
                fac = 10000.0
            else:
                note.append(f"自校验中位 {med:.1f} 非 100/10000 档")
            if fac:
                off = sum(1 for x in ks if abs(x / fac - 1) > SELF_OUTLIER)
                note.append(f"自校验 中位{med:.1f} n={len(ks)} 离群{off}")
                if off / len(ks) > MAX_OUTLIER_FRAC:
                    note.append(f"离群> {MAX_OUTLIER_FRAC:.0%} → 弃")
                    fac = None
        else:
            note.append(f"自校验样本 {len(ks)}<5")
        if fac and len(ls) >= 5:
            ml = statistics.median(ls)
            if abs(ml / fac - 1) <= TOL_SNAP:
                note.append(f"本地样本中位比 {ml:.1f} ✓")
            else:
                note.append(f"本地样本中位比 {ml:.1f} ✗ 与自校验冲突 → 弃")
                fac = None
        factors[g] = fac
        if fac:
            notes.append((g, " ".join(note) or "-"))
        else:
            reasons[g] = " ".join(note)
    for g, nt in notes:
        print(f"[factor] {g:20s} ×{factors[g]:.0f}  （{nt}）", flush=True)
    for g in sorted(reasons):
        print(f"[factor] {g:20s} 未校验 → 整组跳过（{reasons[g]}）", flush=True)
    ok = {g: f for g, f in factors.items() if f}
    if not ok:
        print("!! 没有任何分组通过校验 → 放弃写盘", flush=True)
        return 2

    # ---- ② 只取缺口（按分组因子换算） ----
    todo = [s for s in gap if factors.get(grp(s))]
    skipped = {}
    for g in sorted({grp(s) for s in gap}):
        if not factors.get(g):
            skipped[g] = sum(1 for s in gap if grp(s) == g)
    fetch_list = todo[:limit] if limit else todo
    rows, failed = {}, []
    chunks = [fetch_list[j:j + BATCH] for j in range(0, len(fetch_list), BATCH)]
    for idx, chunk in enumerate(chunks, 1):
        try:
            rows.update(fetch(chunk, host_idx=nreq))
            nreq += 1
            print(f"  [gap] 批 {idx}/{len(chunks)} 取到 {len(chunk)} 只", flush=True)
        except Exception as e:
            print(f"  !! 缺口批 {idx}/{len(chunks)} 失败（{len(chunk)} 只）：{str(e)[:90]}", flush=True)
            failed.append(chunk)
        time.sleep(BATCH_SLEEP)
    if failed and not dry:
        print(f"[cool] {len(failed)} 个失败批，冷却 {COOLDOWN}s 后重试一次", flush=True)
        time.sleep(COOLDOWN)
        for chunk in failed:
            try:
                got = fetch(chunk, host_idx=nreq)
                rows.update(got)
                nreq += 1
                print(f"  [re] 冷却重试取到 {len(got)}/{len(chunk)} 只", flush=True)
            except Exception as e:
                print(f"  !! 冷却重试仍失败（{len(chunk)} 只）：{str(e)[:90]}", flush=True)
            time.sleep(BATCH_SLEEP)

    tgt = []
    for s in fetch_list:
        r = rows.get(s)
        if not r:
            continue
        p = DATA / f"{s}.csv"
        lr = last_row(p)
        if lr and lr[0] >= trade_day:
            continue
        fac = factors[grp(s)]
        e_o, e_h, e_l, e_c = num(r.get("f17")), num(r.get("f15")), num(r.get("f16")), num(r.get("f2"))
        e_v = num(r.get("f5"))
        e_a = num(r.get("f6"))
        e_v = None if e_v is None else e_v * fac
        if None in (e_o, e_h, e_l, e_c) or e_c <= 0 or e_o <= 0:
            continue                      # 停牌/无值
        tgt.append((s, p, e_o, e_h, e_l, e_c, e_v or 0.0, e_a or 0.0))

    print(f"[plan] 缺口 {len(gap)} 只 → 取到 {len(rows)} 只 → 待补 {len(tgt)} 只"
          + (f"（--limit {limit}）" if limit else ""), flush=True)
    for g, n in sorted(skipped.items()):
        print(f"   - 跳过 {g}：{n} 只（该组未通过口径校验）", flush=True)

    if dry:
        print(f"[dry] 未写盘（共发 {nreq} 个请求）。样例：", flush=True)
        for s, p, o, h, l, c, v, a in tgt[:5]:
            print(f"   {s}: {trade_day},{o},{h},{l},{c},{v},{a}", flush=True)
        return 0

    wrote = 0
    for s, p, o, h, l, c, v, a in tgt:
        try:
            p.write_text(p.read_text(encoding="utf-8").rstrip("\n")
                         + f"\n{trade_day},{o},{h},{l},{c},{v},{a}\n", encoding="utf-8")
            wrote += 1
        except Exception as e:
            print(f"   !! {s} 写失败 {type(e).__name__}: {e}", flush=True)
    print(f"[done] 补齐 {wrote}/{len(tgt)} 只 → {trade_day}（共发 {nreq} 个请求）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
