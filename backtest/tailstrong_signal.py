# -*- coding: utf-8 -*-
"""打板尾盘强势线 · 信号生成器（R-valve-0919d 投产准备 · 步骤 1/3）

策略（预注册口径，全窗口回测 n=9,802、+1.076%/笔、聚类 t +10.10）：
  1. **14:30 时点**：当日涨幅（相对前一交易日收盘）≥ 9.5%
  2. **14:45 时点**：价格未封板（可成交）→ 以 14:45 价买入
  3. **T+1 开盘**卖出
  4. 每日最多 K 只（K=10），等额 17 万/K；不满足则当日少买/不买

运行时刻：**每个交易日 14:45-15:00**（由自动化任务调度）。
数据通道：东财 push2delay clist（全市场快照，实测 800 码/请求、全市场 56 请求 ~1.1s）
          + pytdx 历史分时（精确取 14:30/14:45 两点价，实测深度到 2005+）
产出：`backtest/tailstrong_signal.json`（供 tailstrong_paper.py 在 T+1 记账）

纪律：
  · 只在 14:30-15:00 窗口内生成信号（窗口外拒绝，防用收盘/次日数据伪造信号）
  · 涨幅一律用 pytdx 的**不复权**昨收（与回测口径一致；已实测除权污染 0/10,731）
  · `--dry` 只打印不落盘
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t293_minute_0919 import minute, _reconnect  # noqa: E402

BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OUT = BASE / "backtest" / "tailstrong_signal.json"
HOST = "push2delay.eastmoney.com"
FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"      # 沪深主板/创业板/科创板（不做北交所）
FIELDS = "f3,f6,f12,f14,f20,f21"
K_SLOTS = 10
G_MIN = 0.095
t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)


def snapshot():
    """全市场实时快照 → DataFrame[code,name,pct,amount]"""
    rows, pn, total = [], 1, None
    while True:
        P = {"pn": str(pn), "pz": "800", "po": "1", "np": "1",
             "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": "2", "invt": "2",
             "fid": "f12", "fs": FS, "fields": FIELDS, "_": str(int(time.time() * 1000))}
        u = f"https://{HOST}/api/qt/clist/get?" + urllib.parse.urlencode(P)
        last = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(u, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://quote.eastmoney.com/"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    d = json.loads(r.read().decode("utf-8", "ignore"))
                break
            except Exception as e:
                last = e
                time.sleep(1.0)
                _reconnect()
        else:
            raise RuntimeError(f"快照第 {pn} 页失败：{type(last).__name__}")
        diff = (d.get("data") or {}).get("diff") or []
        total = (d.get("data") or {}).get("total") or total
        if not diff:
            break
        rows.extend(diff)
        if total and len(rows) >= total:
            break
        pn += 1
    df = pd.DataFrame(rows)
    for c in ("f3", "f6", "f20"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.rename(columns={"f12": "code", "f14": "name", "f3": "pct", "f6": "amount"})
    return df[["code", "name", "pct", "amount"]].dropna(subset=["pct"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只打印不落盘")
    ap.add_argument("--force", action="store_true", help="跳过时间窗校验（调试用，会标注）")
    a = ap.parse_args()

    now = datetime.now()
    hhmm = now.hour * 100 + now.minute
    if not a.force and not (1430 <= hhmm <= 1500):
        print(f"[拒绝] 当前 {now:%H:%M} 不在 14:30-15:00 信号窗口内 —— 本策略只在尾盘定信号，"
              f"窗口外运行会产生用收盘价伪造的信号。如确需调试请加 --force（会写入 forced=true）")
        return 2
    di = int(now.strftime("%Y%m%d"))
    log(f"信号窗口 {now:%Y-%m-%d %H:%M:%S}｜拉全市场快照…")
    snap = snapshot()
    log(f"快照 {len(snap)} 只")
    cand = snap[snap["pct"] >= G_MIN * 100].copy()
    log(f"涨幅 ≥9.5% 的候选 {len(cand)} 只（快照口径，含已封板）")

    out, fail = [], 0
    for i, x in enumerate(cand.itertuples(), 1):
        code = str(x.code).zfill(6)
        df = minute(code, di)
        if df is None or len(df) < 240:
            fail += 1
            continue
        p = df["price"].to_numpy()
        pc = float(df["pre_close"].iloc[0]) if "pre_close" in df.columns else 0.0
        if pc <= 0:
            fail += 1
            continue
        p1430, p1445 = float(p[209]), float(p[224])
        g = p1430 / pc - 1
        lim = 0.20 if code[:2] in ("30", "68") else 0.10
        sealed = p1445 >= pc * (1 + lim) - 1e-3
        if g < G_MIN or sealed:
            continue
        out.append({"code": code, "name": str(x.name), "p1430": p1430, "p1445": p1445,
                    "prev_close": pc, "g": round(g, 6), "amount": float(x.amount) if x.amount == x.amount else None})
        if i % 50 == 0:
            log(f"  分时核价 {i}/{len(cand)}（通过 {len(out)}）")
    out.sort(key=lambda r: -r["g"])
    log(f"分时核价完成：候选 {len(cand)} → 通过 {len(out)}（分时失败 {fail}）")

    sig = {"date": now.strftime("%Y-%m-%d"), "asof": now.strftime("%H:%M:%S"),
           "window": "14:45", "g_min": G_MIN, "k_slots": K_SLOTS,
           "capital": 170000.0, "per_trade": round(170000.0 / K_SLOTS, 2),
           "cost_tier": "100bp（保守）", "forced": bool(a.force),
           "n_candidates": int(len(cand)), "n_pass": int(len(out)),
           "minute_fail": int(fail), "candidates": out}
    if a.dry:
        print("\n=== DRY：不落盘 ===")
        print(json.dumps({k: v for k, v in sig.items() if k != "candidates"}, ensure_ascii=False, indent=1))
        for r in out[:15]:
            print(f"  {r['code']} {r['name'][:6]:<8} 14:30涨幅 {r['g']*100:6.2f}%  14:45价 {r['p1445']:>8.2f}  昨收 {r['prev_close']:>8.2f}")
        return 0
    OUT.write_text(json.dumps(sig, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"信号落盘 {OUT.name}（{len(out)} 只）")
    for r in out[:15]:
        print(f"  {r['code']} {r['name'][:6]:<8} 14:30涨幅 {r['g']*100:6.2f}%  14:45价 {r['p1445']:>8.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
