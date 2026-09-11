# -*- coding: utf-8 -*-
"""2026-09-11 amount/volume/复权 数据事故 —— 精确回滚到事故前状态
================================================================
事故文件 (410 只, mtime 09-11 15:33) 被 update_daily 腾讯降级源(pools_only)重写：
  ① amount 整段 → 0（腾讯 day 接口无成交额）
  ② volume ÷100（腾讯给「手」，本地历史是「股」）
  ③ 前复权基准漂移（换源 → close 序列小幅变化 → mom_12_1/ma200_pos 漂移）
本脚本：日期 ≤ 2026-09-10 的行，全部列 (open/high/low/close/volume/amount) 回滚为
       事故前缓存 v8_factor_cache.pkl.bak_0911 的原值（逐格精确）；
       2026-09-11 新行用 westock kline 重建（volume ×100 归一为「股」）。
"""
import os, sys, json, re, subprocess, shutil, time
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
OUT = BASE / "data_full"
BAK2 = BASE / "_backup_amt_0911"          # 事故后（本轮修复前）快照
CACHE = BASE / "v8_factor_cache.pkl.bak_0911"   # 事故前
CODES = [c for c in json.load(open(BASE / "_affected_amt_0911.json", encoding="utf-8")) if c != "_index"]
COLS = ["open", "high", "low", "close", "volume", "amount"]

print(f"回滚 {len(CODES)} 只", flush=True)
C = pd.read_pickle(CACHE)
print("事故前缓存加载完成", flush=True)

# ---- westock 拉 09-11 ----
WS = Path(r"C:/Users/Admin/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/westock-data/scripts/index.js")
ROW = re.compile(r"\| ([a-z]{2}\w+) \| (\d{4}-\d{2}-\d{2}) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d.eE+]+) \| ([\d.eE+]+) \|")

def ws_fetch(syms):
    out = {}
    r = subprocess.run(["node", str(WS), "kline", ",".join(syms), "--period", "day",
                        "--limit", "8", "--fq", "qfq"], capture_output=True, text=True, timeout=180)
    hdr = False
    for ln in (r.stdout or "").splitlines():
        s = ln.strip()
        if "| date |" in s and "amount" in s:
            hdr = True; continue
        if not hdr or s.startswith("|---") or not s.startswith("|"):
            continue
        m = ROW.match(s)
        if m:
            sym, d, o, last, h, l, v, amt = m.groups()
            # westock 行序 [date, open, last(=close), high, low, volume, amount]，volume=手
            out.setdefault(sym, {})[d] = {"open": float(o), "high": float(h), "low": float(l),
                                          "close": float(last), "volume": float(v) * 100, "amount": float(amt)}
    return out

ws = {}
for i in range(0, len(CODES), 50):
    grp = CODES[i:i + 50]
    for a in range(3):
        try:
            ws.update(ws_fetch(grp)); break
        except Exception:
            if a == 2: print("  ws 批失败", i, flush=True)
print(f"westock 覆盖 {len(ws)} 只", flush=True)

stat = {"rev_rows": 0, "new_row": 0, "no_cache": [], "files": 0, "basis_chk": []}
for c in CODES:
    f = OUT / f"{c}.csv"
    if not f.exists():
        continue
    cur = pd.read_csv(f, dtype={"date": str})
    cd = C.get(c)
    if cd is not None and "amount" in cd.columns:
        cmap = {}
        for k, row in cd.iterrows():
            cmap[str(k)[:10]] = {col: row[col] for col in COLS if col in cd.columns}
        for idx, d in cur["date"].items():
            ds = str(d)[:10]
            if ds <= "2026-09-10" and ds in cmap:
                for col in COLS:
                    if col in cmap[ds]:
                        cur.at[idx, col] = cmap[ds][col]
                stat["rev_rows"] += 1
    else:
        stat["no_cache"].append(c)
    # 09-11 行用 westock 重建
    wm = ws.get(c, {})
    for idx, d in cur["date"].items():
        if str(d)[:10] == "2026-09-11" and wm.get("2026-09-11"):
            for col in COLS:
                cur.at[idx, col] = wm["2026-09-11"][col]
            stat["new_row"] += 1
    cur.to_csv(f, index=False)
    stat["files"] += 1

print("回滚统计:", {k: (v if not isinstance(v, list) else f"{len(v)} {v[:5]}") for k, v in stat.items()}, flush=True)

# ---- 基准一致性抽查：事故前 09-10 close vs westock 09-10 close ----
print("\n-- 复权基准抽查（cache 09-10 close vs westock 09-10 close）--", flush=True)
for c in ["sz002303", "sh600707", "sz002990", "sh600186"]:
    cd = C.get(c)
    wv = ws.get(c, {}).get("2026-09-10", {}).get("close")
    if cd is not None:
        try:
            cv = cd.loc[pd.Timestamp("2026-09-10"), "close"]
            print(f"  {c}: cache={cv} westock={wv} diff={'-' if wv is None else round((float(wv)/float(cv)-1)*100,3)}%")
        except Exception:
            print(f"  {c}: cache 无 09-10")
print("\n完成 ✅", flush=True)
