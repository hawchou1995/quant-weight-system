# -*- coding: utf-8 -*-
"""估值日更/补数（2026-09-17 建）——东财 RPT_VALUEANALYSIS_DET 逐票增量

背景（根因记录）：旧管道 fetch_val_daily 只抓 4 列快照（close/float_mv/total_mv），
**从不扩展 val_em_all（pe_ttm/pb_mrq 主表）** → 估值主表冻结于 09-11 → 面板构建器
（factorlab/oss）与生产轨 B（oss_super_prod）随之冻结 → satellite_pool 的 asof 声称 09-16
但轨 B 行价是 09-11 值（001256: 21.08=09-11 收盘，实测逐位一致）。

本脚本：对全主板池逐票拉 RPT_VALUEANALYSIS_DET（page1/500 倒序），
      把 TRADE_DATE > 现有 val_em_all 最大日期 的行追加进 val_em_all.csv。
特性：4 线程 / 断点续传（per-run done） / 幂等（重复跑按当前 max date 截断）
用法：python fetch_val_em_daily.py    # 挂在日链数据步之后
"""
import concurrent.futures as cf
import json
import threading
import time
from pathlib import Path

import pandas as pd
import requests

BASE = Path(__file__).resolve().parent
OUT = BASE / "data_fundamental" / "val_em"
ALL = OUT / "val_em_all.csv"
URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
HDR = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
TL = threading.local()
COLS = ["code", "date", "close", "pe_ttm", "pb_mrq", "total_mv", "float_mv"]
t0 = time.time()
def log(*a): print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)

# 逐票最大日期（resume 安全：断点续传时未处理票仍按各自 cutoff 精确补齐）
_dd = pd.read_csv(ALL, usecols=["code", "date"], dtype={"code": str, "date": str})
_per_max = _dd.groupby("code")["date"].max().to_dict()
_max = _dd["date"].max(); del _dd
import gc as _gc; _gc.collect()
log(f"[val_em_all] 全局最大日期 = {_max} | 逐票 cutoff 已建（{len(_per_max)} 票）")
codes = []
for f in sorted((BASE / "data_full").glob("*.csv")):
    c = f.stem
    if c.startswith(("sh60", "sz000", "sz001", "sz002", "sz003")):
        codes.append(c[2:])
codes = sorted(set(codes))
# 只延伸 val_em 已有票（绝不改变宇宙——退市/特殊码若被追加会污染面板 NC 与生产轨B）
_known = set(_per_max.keys())
_excl = [c for c in codes if c not in _known]
codes = [c for c in codes if c in _known]
if _excl:
    log(f"[宇宙守护] 排除 {len(_excl)} 个 val_em 外代码（样例 {_excl[:6]}）")
DONE_F = OUT / "val_daily_done.json"
done = set()
if DONE_F.exists():
    try:
        done = set(json.load(open(DONE_F, encoding="utf-8")))
    except Exception:
        done = set()
todo = [c for c in codes if c not in done]
log(f"[目标] 池 {len(codes)} 票 | 待拉 {len(todo)} | 增量方式=逐票 page1/500 倒序过滤 > {_max}")


def fetch_one(code):
    s = getattr(TL, "s", None)
    if s is None:
        s = requests.Session(); s.headers.update(HDR); TL.s = s
    p = {"reportName": "RPT_VALUEANALYSIS_DET", "columns": "ALL",
         "filter": f'(SECURITY_CODE="{code}")', "sortColumns": "TRADE_DATE", "sortTypes": "-1",
         "pageSize": "500", "pageNumber": "1", "source": "WEB", "client": "WEB"}
    for att in range(4):
        try:
            j = s.get(URL, params=p, timeout=15).json()
            d = (j.get("result") or {}).get("data") or []
            break
        except Exception:
            time.sleep(1.0 * (att + 1))
    else:
        return code, None
    rows = []
    for r in d:
        ds = str(r.get("TRADE_DATE", ""))[:10]
        if ds <= _per_max.get(code, "2021-01-01"):
            break  # 倒序，遇到该票已知旧日期即停
        rows.append({
            "code": code, "date": ds,
            "close": r.get("CLOSE_PRICE"),
            "pe_ttm": r.get("PE_TTM"),
            "pb_mrq": r.get("PB_MRQ"),
            "total_mv": r.get("TOTAL_MARKET_CAP"),
            "float_mv": r.get("NOTLIMITED_MARKETCAP_A"),
        })
    return code, rows


buf, ok, fail, nnew = [], 0, [], 0
with cf.ThreadPoolExecutor(max_workers=4) as ex:
    futs = {ex.submit(fetch_one, c): c for c in todo}
    for k, fu in enumerate(cf.as_completed(futs), 1):
        c, rows = fu.result()
        if rows is None:
            fail.append(c)
        else:
            ok += 1
            nnew += len(rows)
            buf.extend(rows)
            done.add(c)
        if len(buf) >= 200000 or (buf and k == len(todo)):
            pd.DataFrame(buf, columns=COLS).to_csv(ALL, mode="a", header=False, index=False, encoding="utf-8-sig")
            buf = []
            json.dump(sorted(done), open(DONE_F, "w", encoding="utf-8"))
            log(f"  [落盘] ok={ok}/{k} 新增行 {nnew:,} 失败 {len(fail)}")
if buf:
    pd.DataFrame(buf, columns=COLS).to_csv(ALL, mode="a", header=False, index=False, encoding="utf-8-sig")
json.dump(sorted(done), open(DONE_F, "w", encoding="utf-8"))
log(f"[完成] 成功 {ok} | 失败 {len(fail)} {fail[:6]} | 新增行 {nnew:,}")
# 验证
v = pd.read_csv(ALL, usecols=["date"], dtype={"date": str})
mx = v["date"].max()
cnt = v[v["date"] == mx].shape[0]
log(f"[验证] val_em_all 现值最大日期 = {mx}（{cnt} 票） | 行数 {len(v):,}")
# 清掉 per-run done（下次跑重新全量检查）
DONE_F.unlink(missing_ok=True)
