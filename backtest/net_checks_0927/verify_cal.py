import json, pathlib, datetime as dt
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = list(U["calendar"]); live=[u["sym"] for u in U["universe"]]
print("universe.json calendar:", cal[0], "..", cal[-1], " n =", len(cal))
bad = [d for d in cal if dt.date.fromisoformat(d).weekday() >= 5]
print("日历里的周末日 =", bad)
print("含 2021-06-27 ?", "2021-06-27" in cal)
L = {d:i for i,d in enumerate(cal)}
print("2021-06-25 idx =", L.get("2021-06-25"), " 2021-06-28 idx =", L.get("2021-06-28"))
# 权威日历对照
try:
    import akshare as ak
    t = ak.tool_trade_date_hist_sina(); ds=set(str(x) for x in t["trade_date"].astype(str))
    print("权威日历 2021-06-25/28 是否交易日:", "2021-06-25" in ds, "2021-06-28" in ds, "; 2021-06-27 是否交易日:", "2021-06-27" in ds)
    miss = [d for d in cal if d not in ds]
    extra = [d for d in ds if cal[0] <= d <= cal[-1] and d not in set(cal)]
    print("日历中非交易日 =", len(miss), miss[:10])
    print("区间内权威交易日但日历缺 =", len(extra), extra[:10])
except Exception as e:
    print("akshare 失败:", repr(e))
# 这 7 个文件是否在策略池内
sus = ["sz300028","sz300090","sz300104","sz300156","sz300216","sz300372","sz300431"]
inj = set(live)
print("伪造填充的 7 只在 universe.json 池内 =", [s for s in sus if s in inj])
