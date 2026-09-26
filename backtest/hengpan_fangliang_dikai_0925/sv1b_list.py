# -*- coding: utf-8 -*-
"""sv1b: fetch delisted roster with retries + fallback, then save the 2014-06+ subset."""
import json, pathlib, time, pandas as pd, akshare as ak
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
def retry(fn, tries=8, wait=4.0, tag=""):
    for i in range(tries):
        try:
            df = fn()
            if df is not None and len(df): print("  [%s] OK on try %d shape=%s" % (tag, i+1, df.shape)); return df
            print("  [%s] try %d -> empty" % (tag, i+1))
        except Exception as e:
            print("  [%s] try %d -> %s" % (tag, i+1, type(e).__name__))
        time.sleep(wait)
    return None
print("--- 上交所终止上市 ---")
sh = retry(lambda: ak.stock_info_sh_delist(), tag="SH")
print("--- 深交所终止上市 ---")
sz = retry(lambda: ak.stock_info_sz_delist(symbol="终止上市公司"), tag="SZ")
print("--- 深交所暂停上市 ---")
szp = retry(lambda: ak.stock_info_sz_delist(symbol="暂停上市公司"), tries=3, tag="SZP")
frames=[]
if sh is not None:
    c=[x for x in ("公司代码","证券代码","code") if x in sh.columns][0]
    n=[x for x in ("公司简称","证券简称","name") if x in sh.columns][0]
    l=[x for x in ("上市日期","list_date") if x in sh.columns][0]
    e=[x for x in ("暂停上市日期","终止上市日期","end_date") if x in sh.columns][0]
    frames.append(sh.rename(columns={c:"code",n:"name",l:"list_date",e:"end_date"})[["code","name","list_date","end_date"]].assign(mkt="sh"))
if sz is not None:
    c=[x for x in ("证券代码","公司代码") if x in sz.columns][0]
    n=[x for x in ("证券简称","公司简称") if x in sz.columns][0]
    l=[x for x in ("上市日期",) if x in sz.columns][0]
    e=[x for x in ("终止上市日期","暂停上市日期") if x in sz.columns][0]
    frames.append(sz.rename(columns={c:"code",n:"name",l:"list_date",e:"end_date"})[["code","name","list_date","end_date"]].assign(mkt="sz"))
if szp is not None and len(szp):
    print("  SZP cols:", list(szp.columns))
if not frames:
    print("BOTH ROSTERS FAILED"); raise SystemExit(1)
d = pd.concat(frames, ignore_index=True)
d["code"]=d["code"].astype(str).str.zfill(6)
d["end_date"]=pd.to_datetime(d["end_date"], errors="coerce")
d = d[d["end_date"].notna()].drop_duplicates(subset=["mkt","code"])
d["list_date"]=pd.to_datetime(d["list_date"], errors="coerce")
print("\n合计 %d 条" % len(d))
for lo,hi in (("2014-06-01","2016-12-31"),("2017-01-01","2019-12-31"),("2020-01-01","2022-12-31"),("2023-01-01","2026-12-31")):
    m=(d["end_date"]>=lo)&(d["end_date"]<=hi)
    print("  终止 %s~%s : %3d 只" % (lo,hi,m.sum()))
keep = d[d["end_date"]>="2014-06-01"].copy()
keep = keep[keep["code"].str.match(r"^(60|00|30|68)")]
keep["sym"]=keep["mkt"]+keep["code"]
print("\n窗口内终止 且 主板/中小/创业/科创: %d 只" % len(keep))
print("  最近 10 只:", keep.sort_values("end_date")[["sym","name","end_date"]].tail(10).astype(str).to_dict("records"))
S.joinpath("sv_delisted_list.json").write_text(json.dumps(keep[["sym","code","name","mkt"]].assign(
    list_date=keep["list_date"].astype(str), end_date=keep["end_date"].astype(str)).to_dict("records"), ensure_ascii=False, indent=1), encoding="utf-8")
print("saved sv_delisted_list.json  (%d 只)" % len(keep))
