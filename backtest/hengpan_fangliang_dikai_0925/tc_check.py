# -*- coding: utf-8 -*-
"""tc_check.py — 数据新鲜度 / 交易日历核对（凡判断"数据是否完整/落后几天"必须先跑这个）
用法: python tc_check.py
纪律来源: PRE-REGISTRATION_20260926_hengpan_dikai_oos.md 勘误 E-3
"""
import json, pathlib, datetime, pandas as pd, akshare as ak
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = list(U["calendar"]); WD = ["周一","周二","周三","周四","周五","周六","周日"]
def wd(d): return WD[datetime.date.fromisoformat(d).weekday()]
tk = ak.tool_trade_date_hist_sina()
col = tk.columns[0]; tk[col] = pd.to_datetime(tk[col])
tset = set(tk[col].dt.strftime("%Y-%m-%d"))
last_local = cal[-1]
today = datetime.date.today().isoformat()
behind   = sorted(d for d in tset if last_local < d <= today)   # 已过去但本地缺失
upcoming = sorted(d for d in tset if d > today)                 # 尚未发生
print("权威交易日历: %s ~ %s (%d 个交易日)" % (tk[col].min().date(), tk[col].max().date(), len(tk)))
print("本地日历最后交易日: %s (%s)" % (last_local, wd(last_local)))
print("今天(系统日期):     %s (%s)  是交易日? %s" % (today, wd(today), "是" if today in tset else "否"))
print(">>> 本地数据落后:   %d 个交易日 %s" % (len(behind), "✅ 数据完整" if not behind else "⚠️ 需更新"))
if behind:
    print("    缺失的交易日: %s" % ", ".join("%s(%s)" % (d, wd(d)) for d in behind))
print(">>> 下一个交易日:   %s" % (upcoming[0]+"(%s)"%wd(upcoming[0]) if upcoming else "无(日历年历已用尽)"))
print("\n近期交易日历（本地末日 ~ +10）:")
for d in [last_local] + upcoming[:10]:
    print("   %s %s" % (d, wd(d)))
print("\n注: 本地 calendar 由 data_full 的日期并集生成, 只含交易日; 「落后 N 个交易日」= 本地末日到今日之间缺失的交易日数,")
print("    不可用自然日相减推断(节假日会造成假落后)。")
