# -*- coding: utf-8 -*-
"""2026-09-11 amount 数据事故修复
=========================================================
事故：update_daily.py fetch_tx_qfq()（腾讯源）把 amount 写成 0
      （row[6] 是 dict/缺失 → amt=0.0），今日 pools_only 命中 410 只池/跟踪标的，
      导致这些标的 2024-01-17 起 amount 整段归零 → v8_factor_cache 重建后 amt20=0
      → v9_rank_board 的 amt20<5e6 过滤把它们全部剔除 → 选池被静默改写（美盈森 002303 消失）。

修复：
  1) 受影响 CSV 全量备份 → _backup_amt_0911/
  2) amount 精确回滚：从事故前缓存 v8_factor_cache.pkl.bak_0911（≤2026-09-10）取真值
  3) 缓存未覆盖的尾部日期（09-11）用 westock kline amount 补
  4) 仍为 0 的 2024+ 行 → short_engine.fix_amount_units（vol×close×mult 自锚定）
"""
import os, sys, json, shutil, subprocess, re, time
from pathlib import Path
import pandas as pd

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import short_engine as SH

OUT = BASE / "data_full"
BAK = BASE / "_backup_amt_0911"
BAK.mkdir(exist_ok=True)
CACHE = BASE / "v8_factor_cache.pkl.bak_0911"
AFF = json.load(open(BASE / "_affected_amt_0911.json", encoding="utf-8"))
CODES = [c for c in AFF if c != "_index"]
print(f"受影响 {len(CODES)} 只", flush=True)

# ---------- 1) 备份 ----------
n_bak = 0
for c in CODES:
    src = OUT / f"{c}.csv"
    dst = BAK / f"{c}.csv"
    if src.exists() and not dst.exists():
        shutil.copy2(src, dst)
        n_bak += 1
print(f"备份 {n_bak} 个新文件 → {BAK}", flush=True)

# ---------- 2) 载入事故前缓存 ----------
t0 = time.time()
C = pd.read_pickle(CACHE)
print(f"载入事故前缓存 {len(C)} 只 ({time.time()-t0:.0f}s)", flush=True)

# ---------- 3) westock 取 09-11 amount ----------
WS = Path(r"C:/Users/Admin/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/westock-data/scripts/index.js")
ROW = re.compile(r"\| ([a-z]{2}\w+) \| (\d{4}-\d{2}-\d{2}) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d\.]+) \| ([\d.eE+]+) \| ([\d.eE+]+) \|")

def ws_fetch(syms):
    out = {}
    cmd = ["node", str(WS), "kline", ",".join(syms), "--period", "day", "--limit", "8", "--fq", "qfq"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    hdr = False
    for ln in (r.stdout or "").splitlines():
        s = ln.strip()
        if "| symbol |" in s or ("| date |" in s and "amount" in s):
            hdr = True; continue
        if not hdr or s.startswith("|---") or not s.startswith("|"):
            continue
        m = ROW.match(s)
        if m:
            sym, d, o, last, h, l, v, amt = m.groups()
            out.setdefault(sym, {})[d] = float(amt)
    return out

ws_amt = {}
B = 50
for i in range(0, len(CODES), B):
    grp = CODES[i:i+B]
    for attempt in range(3):
        try:
            ws_amt.update(ws_fetch(grp)); break
        except Exception as e:
            if attempt == 2:
                print("  westock 批失败", i, repr(e)[:60], flush=True)
print(f"westock 覆盖 {len(ws_amt)} 只", flush=True)

# ---------- 4) 精确回滚 + 兜底 ----------
stat = {"restored": 0, "ws_tail": 0, "fallback": 0, "mismatch": 0, "files": 0}
for c in CODES:
    f = OUT / f"{c}.csv"
    if not f.exists():
        continue
    df = pd.read_csv(f, dtype={"date": str})
    if "amount" not in df.columns or len(df) == 0:
        continue
    cd = C.get(c)
    amt_col = df["amount"].astype("float64").copy()
    if cd is not None and "amount" in cd.columns:
        cmap = cd["amount"].astype("float64").to_dict()
        cmap = {str(k)[:10]: v for k, v in cmap.items()}
        for idx, d in df["date"].items():
            dv = cmap.get(str(d)[:10])
            if dv is not None and dv > 0:
                cur = amt_col.get(idx, 0.0)
                if cur and cur > 0 and abs(cur - dv) / dv > 0.02:
                    stat["mismatch"] += 1
                amt_col.at[idx] = dv
                stat["restored"] += 1
        # 尾部（缓存未覆盖日期）用 westock
        wm = ws_amt.get(c, {})
        for idx, d in df["date"].items():
            if str(d)[:10] > "2026-09-10" and wm.get(str(d)[:10]):
                amt_col.at[idx] = wm[str(d)[:10]]
                stat["ws_tail"] += 1
    df["amount"] = amt_col
    # 兜底：2024+ 仍为 0 且 volume>0
    df = SH.fix_amount_units(df)
    df.to_csv(f, index=False)
    stat["files"] += 1

print("修复统计:", json.dumps(stat, ensure_ascii=False), flush=True)
print("完成 ✅", flush=True)
