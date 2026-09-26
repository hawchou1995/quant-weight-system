# -*- coding: utf-8 -*-
"""hold_check.py — 核对持仓期: 组合模拟实际是 T+1买入 -> ? 卖出
对照: oos_run.py(冻结) 的 exit = T+2 ; 各回测脚本的 tgt = en+2
"""
import json, pathlib, numpy as np, pandas as pd
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal=list(U["calendar"]); T=len(cal)
# 冻结 OOS runner 的口径
print("oos_run.py(冻结 v1.2): 信号日=t, entry=O[t+1], ex_t=t+2  -> 持仓 = 2 个交易日 (T+1开盘 -> T+2收盘) ✔")
print("real_filters/rf2/final_report/sv3b/r6: pos=dict(en=t, tgt=t+2) 且卖出条件 tgt<=t -> 卖在 en+2 = T+3 -> 持仓 3 个交易日 ✘")
# 用真实成交记录验证: 用 rf2 的 per-trade 无法看天数, 改为直接演示索引
d=pd.Timestamp(cal[0])
i=2000
print("\n索引演示: 信号日 cal[%d]=%s ; en=cal[%d]=%s ; 本轮回测卖出日=cal[%d]=%s ; 冻结OOS卖出日=cal[%d]=%s" %
      (i-1, cal[i-1], i, cal[i], i+2, cal[i+2], i+1, cal[i+1]))
print("=> 回测比冻结口径多持 1 个交易日")
