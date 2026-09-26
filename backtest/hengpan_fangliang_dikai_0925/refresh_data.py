# -*- coding: utf-8 -*-
"""refresh_data.py — 数据维护(批准项3): 退市名录 / 退市日线 / 季度BPS, 可复跑·幂等·断点续抓
用法:
  python refresh_data.py --all              # 全部 (推荐, 建议每月或每季跑一次)
  python refresh_data.py --roster           # 只刷退市名录
  python refresh_data.py --bars             # 只补新增退市标的的日线
  python refresh_data.py --bps 2400         # 只补 BPS, 内部预算 2400 秒(超时自动断点, 可重复跑)
"""
import json, sys, time, pathlib, pandas as pd
R = pathlib.Path(__file__).resolve().parents[2]
UNI = R/"backtest/wechat_hotspot_leader_0925/universe.json"
DEADDIR = R/"backtest/_delisted_universe"; DEADDIR.mkdir(parents=True, exist_ok=True)
FUNDDIR = R/"backtest/_fundamentals"; FUNDDIR.mkdir(parents=True, exist_ok=True)
def log(*a): print(*a, flush=True)
def fetch_roster():
    import akshare as ak
    frames = []
    for tag, fn, kw in (("SH", ak.stock_info_sh_delist, {}),
                        ("SZ", ak.stock_info_sz_delist, {"symbol":"终止上市公司"})):
        for i in range(8):
            try:
                df = fn(**kw)
                if df is not None and len(df):
                    c = [x for x in ("公司代码","证券代码") if x in df.columns][0]
                    nm = [x for x in ("公司简称","证券简称") if x in df.columns][0]
                    ld = [x for x in ("上市日期",) if x in df.columns][0]
                    ed = [x for x in ("暂停上市日期","终止上市日期") if x in df.columns][0]
                    frames.append(df.rename(columns={c:"code",nm:"name",ld:"list_date",ed:"end_date"})[["code","name","list_date","end_date"]].assign(mkt=tag.lower()))
                    log("  [%s] OK shape=%s" % (tag, df.shape)); break
            except Exception as e:
                log("  [%s] try %d FAIL %s" % (tag, i+1, type(e).__name__))
            time.sleep(4)
    if not frames: log("!! 名录抓取失败(两个市场都失败)"); return None
    d = pd.concat(frames, ignore_index=True)
    d["code"] = d["code"].astype(str).str.zfill(6)
    d["end_date"] = pd.to_datetime(d["end_date"], errors="coerce"); d = d[d["end_date"].notna()]
    d = d.drop_duplicates(subset=["mkt","code"]); d["list_date"] = pd.to_datetime(d["list_date"], errors="coerce")
    keep = d[(d["end_date"]>="2014-06-01") & (d["code"].str.match(r"^(60|00|30|68)"))].copy()
    keep["sym"] = keep["mkt"]+keep["code"]
    keep["end_date_s"] = keep["end_date"].dt.strftime("%Y-%m-%d"); keep["list_date_s"] = keep["list_date"].dt.strftime("%Y-%m-%d")
    keep[["sym","code","name","mkt","list_date_s","end_date_s"]].to_csv(DEADDIR/"delisted_roster.csv", index=False, encoding="utf-8-sig")
    log("  名录落盘: %d 只 -> %s" % (len(keep), DEADDIR/"delisted_roster.csv"))
    return keep
def fetch_bars(roster=None):
    import akshare as ak
    if roster is None:
        f = DEADDIR/"delisted_roster.csv"
        if not f.exists(): log("!! 无名录, 先跑 --roster"); return
        roster = pd.read_csv(f)
    have = set()
    if (DEADDIR/"delisted_bars.csv.gz").exists():
        have = set(pd.read_csv(DEADDIR/"delisted_bars.csv.gz", usecols=["sym"])["sym"].unique())
    todo = [s for s in roster["sym"].tolist() if s not in have]
    log("  退市日线: 已有 %d 只, 待补 %d 只" % (len(have), len(todo)))
    rows = []; fail = []
    for i, sym in enumerate(todo):
        got = None
        for kw in (dict(symbol=sym, start_date="20140101", end_date="20301231", adjust="qfq"), dict(symbol=sym, adjust="qfq")):
            try:
                df = ak.stock_zh_a_hist_tx(**kw)
                if df is not None and len(df): got = df; break
            except Exception: pass
        if got is None: fail.append(sym); continue
        d = got.copy(); d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d"); d["sym"] = sym
        rows.append(d[[c for c in ("sym","date","open","high","low","close","volume","amount") if c in d.columns]])
        if (i+1) % 50 == 0:
            _save_bars(rows); rows = []
            log("    %d/%d" % (i+1, len(todo)))
    _save_bars(rows)
    log("  退市日线补齐: 新增 %d 只, 失败 %d 只 %s" % (len(todo)-len(fail), len(fail), fail[:8]))
def _save_bars(rows):
    if not rows: return
    old = pd.read_csv(DEADDIR/"delisted_bars.csv.gz") if (DEADDIR/"delisted_bars.csv.gz").exists() else pd.DataFrame(columns=["sym","date","open","high","low","close","volume","amount"])
    out = pd.concat([old]+[pd.DataFrame(r) for r in rows], ignore_index=True).drop_duplicates(subset=["sym","date"]).sort_values(["sym","date"])
    out.to_csv(DEADDIR/"delisted_bars.csv.gz", index=False, compression="gzip")
def fetch_bps(budget=2400.0):
    import akshare as ak
    U = json.loads(UNI.read_text(encoding="utf-8"))
    live = [u["sym"] for u in U["universe"]]
    dead = []
    if (DEADDIR/"delisted_bars.csv.gz").exists():
        dead = sorted(pd.read_csv(DEADDIR/"delisted_bars.csv.gz", usecols=["sym"])["sym"].unique().tolist())
    alls = live + dead
    OUT = FUNDDIR/"bps_quarterly.csv.gz"; DONE = FUNDDIR/"bps_done.json"
    done = json.loads(DONE.read_text(encoding="utf-8")) if DONE.exists() else {"ok":[], "fail":[]}
    todo = [s for s in alls if s not in set(done["ok"]) and s not in set(done["fail"])]
    log("  BPS: 总 %d, 已完成 %d, 待抓 %d (本轮预算 %.0fs)" % (len(alls), len(done["ok"]), len(todo), budget))
    t0 = time.time(); rows = []; nok = nf = 0
    for i, s_ in enumerate(todo):
        if time.time()-t0 > budget: log("  达到预算, 本轮 %d 只, 可再次运行续抓" % i); break
        code = s_.replace("sh","").replace("sz",""); got = False
        try:
            df = ak.stock_financial_analysis_indicator(symbol=code, start_year="2014")
            if df is not None and len(df):
                col = [c for c in df.columns if c.startswith("每股净资产")]
                if col:
                    sub = df[["日期", col[0]]].copy(); sub["日期"] = sub["日期"].astype(str).str.slice(0,10)
                    sub["bps"] = pd.to_numeric(sub[col[0]], errors="coerce"); sub = sub[sub["bps"].notna()]
                    for r in sub.itertuples(index=False): rows.append((s_, r.日期, float(r.bps)))
                    got = True
        except Exception: pass
        (done["ok"] if got else done["fail"]).append(s_)
        nok += int(got); nf += int(not got)
        if (i+1) % 150 == 0:
            _save_bps(rows); rows = []
            json.dump(done, DONE.open("w",encoding="utf-8"), ensure_ascii=False)
            log("    %d/%d %.0fs ok=%d fail=%d" % (i+1, len(todo), time.time()-t0, nok, nf))
    _save_bps(rows); json.dump(done, DONE.open("w",encoding="utf-8"), ensure_ascii=False)
    log("  BPS 本轮: ok=%d fail=%d ; 累计完成 %d/%d" % (nok, nf, len(done["ok"])+len(done["fail"]), len(alls)))
def _save_bps(rows):
    if not rows: return
    old = pd.read_csv(FUNDDIR/"bps_quarterly.csv.gz") if (FUNDDIR/"bps_quarterly.csv.gz").exists() else pd.DataFrame(columns=["sym","report_date","bps"])
    out = pd.concat([old, pd.DataFrame(rows, columns=["sym","report_date","bps"])], ignore_index=True).drop_duplicates(subset=["sym","report_date"])
    out.to_csv(FUNDDIR/"bps_quarterly.csv.gz", index=False, compression="gzip")
if __name__ == "__main__":
    a = sys.argv[1:]
    bud = float(a[a.index("--bps")+1]) if ("--bps" in a and len(a) > a.index("--bps")+1 and a[a.index("--bps")+1].replace(".","").isdigit()) else 2400.0
    log("=== refresh_data 开始 ===")
    ros = None
    if not a or "--all" in a or "--roster" in a: ros = fetch_roster()
    if not a or "--all" in a or "--bars" in a: fetch_bars(ros)
    if not a or "--all" in a or "--bps" in a: fetch_bps(bud)
    log("=== 完成 (可重复运行, 幂等) ===")
