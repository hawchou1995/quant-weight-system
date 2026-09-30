# -*- coding: utf-8 -*-
"""hpdk_live_fullpool.py — 盘中止损复算器：全池口径的「今日买入清单」（权威名单）

## 为什么需要它（2026-09-30 实测事故）
卡片前端做全池判定时依赖浏览器报价覆盖。实测某轮覆盖只有 **29%**
（表头显示「全市场快照 0 只 · 东财」= 腾讯池内报价失败），后果：
  · 全池真实命中 **50** 只，前端只找到 **13** 只；
  · F 复合分是在**命中子集内**横截面 z 标准化 ⇒ 子集不全会**整体改变排名**；
  · 实测：前端前 4（招商港口/天保基建/华联控股/华斯股份）与全池前 4
    （民和股份/南都物业/一拖股份/浦东金桥）**一只都不重合**；
    前端那 10 只在全池口径下排 #9/#8/#16/#17/#22/#25/#21/#32/#23/#41（全中游）。
前端已加「覆盖 <50% 显著报警」，但报警只防误用、不给真名单 ⇒ 本脚本补上真名单。

## 口径（与冻结脚本 / 卡片三方一致）
  资格池   = `backtest/hpdk_candidates.json` 的 rows（信号日 T 收盘判定）
  命中     = gap = 今开/昨收 − 1 ∈ [gap_lo, gap_hi]（默认 [−3%, −1%]）
             ∩ 可交易（非停牌/一字）∩ 量比与 20 日涨幅可算
  复合分   = z(−ln 成交额20) + z(−ln 量比) + z(−20 日涨幅)，**在命中集内**横截面 z
  挂单价   = 交易所昨收 × 0.99（用行情 pcl，不用面板收盘 —— 自动处理除息 XD）
  昨收/今开取**交易所口径**（腾讯 f[4]/f[5]），因此除息日也正确。

## 用法
  python hpdk_live_fullpool.py                    # 打印前 10 + 命中总数
  python hpdk_live_fullpool.py --top 4            # 只看前 4（= K=4 执行档）
  python hpdk_live_fullpool.py --save             # 落盘 evidence_live_hits_<date>.json
  python hpdk_live_fullpool.py --min-cov 0.95     # 报价覆盖低于此值则判失败（默认 0.95）

退出码：0 正常 ｜ 2 报价覆盖不足（结果不可信）｜ 3 候选产物缺失/过期
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import sys
import time
import urllib.request

R = pathlib.Path(__file__).resolve().parents[2]
CAND = R / "backtest" / "hpdk_candidates.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TX_CHUNK = 400          # 浏览器实测 400 码 OK、800 码 URL 过长快速失败（intraday_live.py CFG.TX_CHUNK）


def log(*a):
    print(*a, flush=True)


def fetch(codes):
    u = "https://qt.gtimg.cn/q=" + ",".join(codes)
    t = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read().decode("gbk", "ignore")
    out = {}
    for line in t.split(";"):
        if "=" not in line or '"' not in line:
            continue
        try:
            f = line.split('"')[1].split("~")
            out[f[2]] = dict(name=f[1], px=float(f[3]), pcl=float(f[4]), opn=float(f[5]), ts=f[30])
        except Exception:
            continue
    return out


def zs(v):
    n = len(v)
    if n < 2:
        return [0.0] * n
    mu = sum(v) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in v) / n)
    return [0.0] * n if sd == 0 else [(x - mu) / sd for x in v]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--min-cov", type=float, default=0.95)
    ap.add_argument("--sleep", type=float, default=0.25)
    a = ap.parse_args()

    if not CAND.exists():
        log("[err] 缺 %s（先跑 hpdk_candidates.py）" % CAND)
        return 3
    cand = json.loads(CAND.read_text(encoding="utf-8"))
    rows = cand["rows"]
    lo, hi = cand.get("gap_band", [-0.03, -0.01])
    # 键 = 裸 6 位码（腾讯 f[2] 是裸码）；取数 = **带前缀 sym**（sh600327/sz002234）
    # —— 2026-09-30 同日两次踩坑：按 sym 建索引 ⇒ 全部 miss ⇒ 假报 0 命中；用裸码取数 ⇒ 整批返回空。
    meta = {r["code"]: r for r in rows}
    codes = sorted(r["sym"] for r in rows)
    today = dt.date.today().isoformat()
    stale = cand.get("buy_date") != today
    log("[in] 候选 as_of=%s buy=%s exit=%s n=%d%s"
        % (cand.get("as_of"), cand.get("buy_date"), cand.get("exit_date"), len(rows),
           "  ⚠ 买日 ≠ 今日（复算的是当日快照，仅供参考）" if stale else ""))

    ALL = {}
    t0 = time.time()
    for i in range(0, len(codes), TX_CHUNK):
        b = codes[i:i + TX_CHUNK]
        for k in range(3):
            try:
                ALL.update(fetch(b))
                break
            except Exception as e:
                log("  batch %d retry %d: %s" % (i // TX_CHUNK + 1, k + 1, type(e).__name__))
                time.sleep(1.2)
        time.sleep(a.sleep)
    cov = len(ALL) / max(1, len(codes))
    log("[quote] %d / %d = %.1f%%（%.1fs）" % (len(ALL), len(codes), cov * 100, time.time() - t0))
    if cov < a.min_cov:
        log("[FAIL] 报价覆盖 %.1f%% < %.1f%% ⇒ 结果不可信，不输出名单（避免误用）" % (cov * 100, a.min_cov * 100))
        return 2

    hits = []
    for c, d in ALL.items():
        m = meta.get(c)
        if not m or not (d["pcl"] > 0 and d["opn"] > 0):
            continue
        gap = d["opn"] / d["pcl"] - 1.0
        if not (lo <= gap <= hi):
            continue
        # B 闸：停牌/一字（现价=今开=昨收）
        if abs(d["px"] - d["pcl"]) < 1e-9 and abs(d["opn"] - d["pcl"]) < 1e-9:
            continue
        if not (m.get("volbr") and m["amt20"] > 0):
            continue
        if m.get("ret20") is None:
            continue
        hits.append(dict(code=c, name=d["name"], gap_pct=round(gap * 100, 3),
                         pcl=d["pcl"], opn=d["opn"], px=d["px"],
                         ordpx=round(d["pcl"] * 0.99, 3), lim_lo=round(d["pcl"] * 0.97, 3),
                         amt20=m["amt20"], volbr=m["volbr"], ret20=m["ret20"]))

    if not hits:
        log("\n[out] 带内命中 0 只 ⇒ 今日无买点（该结论基于 %.1f%% 覆盖，可信）" % (cov * 100))
        return 0

    z1 = zs([-math.log(h["amt20"]) for h in hits])
    z2 = zs([-math.log(h["volbr"]) if h["volbr"] > 0 else 0.0 for h in hits])
    z3 = zs([-h["ret20"] for h in hits])
    for i, h in enumerate(hits):
        h["F"] = z1[i] + z2[i] + z3[i]
    rank = sorted(hits, key=lambda x: -x["F"])

    log("\n[out] 带内命中 %d 只 · F 前 %d（全池口径 · 覆盖 %.1f%%）" % (len(hits), a.top, cov * 100))
    log("%-4s %-8s %-9s %8s %9s %9s %9s %8s" %
        ("#", "代码", "名称", "昨收", "挂单价", "撤单线", "今开", "F"))
    for i, h in enumerate(rank[:a.top], 1):
        log("%-4d %-8s %-9s %8.3f %9.3f %9.3f %9.3f %+8.3f"
            % (i, h["code"], h["name"], h["pcl"], h["ordpx"], h["lim_lo"], h["opn"], h["F"]))
    log("\n下单：挂单价**按分位向上取整**（宁可高一分，否则漏掉刚好在带内的票）；"
        "09:25 撮合后立刻撤掉未成交单。")

    if a.save:
        q = pathlib.Path(__file__).resolve().parent / ("evidence_live_hits_%s.json" % today.replace("-", ""))
        q.write_text(json.dumps(dict(
            _what="全池口径盘中止损复算（权威名单）", ts=time.strftime("%Y-%m-%d %H:%M:%S"),
            n_pool=len(rows), n_quote=len(ALL), cov_pct=round(cov * 100, 2), n_hits=len(hits),
            tool="backtest/hengpan_fangliang_dikai_0925/hpdk_live_fullpool.py",
            f_top=[h["code"] for h in rank[:a.top]], hits=hits), ensure_ascii=False, indent=1),
            encoding="utf-8", newline="")
        log("\n[saved] %s" % q)
    return 0


if __name__ == "__main__":
    sys.exit(main())
