# -*- coding: utf-8 -*-
"""
构建 1000 只分层子样本（按类型分层 + 随机种子 42）
====================================================
分层：沪深A股(不含ETF/北交所) 70% + ETF 15% + 北交所 5% + 退市 10%
（退市股在数据池中约 250/7420=3.4%，为验证退市暴露提升至 10%）
输出：subsample_1000.txt（每行 code）
"""
import os
import glob, random
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
DATA = BASE / "data_full"
OUT = BASE / "subsample_1000.txt"

stocks, etfs, bj, delist = [], [], [], []
for f in glob.glob(str(DATA / "*.csv")):
    code = Path(f).stem
    if code.startswith("bj"):
        bj.append(code)
    elif code.startswith(("sh5", "sz1")):
        etfs.append(code)
    elif code.startswith(("sh9",)):
        delist.append(code)  # B股/退市
    elif code.startswith(("sh6", "sz0", "sz3")):
        # 退市股判定：用 names 映射里退市标记（简化：sh6/sz0/sz3 中与退市列表同码的）
        stocks.append(code)
    else:
        delist.append(code)

# 退市名单（东财退市列表，抓取脚本同源逻辑）
import json
names = json.loads((BASE / "data_full_names.json").read_text(encoding="utf-8"))
delist_set = set()
import akshare as ak
try:
    sh = ak.stock_info_sh_delist()
    for _, r in sh.iterrows():
        c = str(r["公司代码"])
        if c.startswith(("6", "9")):
            delist_set.add("sh" + c)
    sz = ak.stock_info_sz_delist()
    for _, r in sz.iterrows():
        c = str(r["证券代码"])
        if c.startswith(("0", "3")):
            delist_set.add("sz" + c)
except Exception as e:
    print("退市列表获取失败:", e)

# 重新分类：stocks 中属于退市名单的移入 delist
stocks2, delist2 = [], list(delist)
for c in stocks:
    if c in delist_set:
        delist2.append(c)
    else:
        stocks2.append(c)
stocks, delist = stocks2, delist2
print(f"分层池: 沪深A股 {len(stocks)} / ETF {len(etfs)} / 北交所 {len(bj)} / 退市 {len(delist)}")

random.seed(42)
N_STOCK = 700
N_ETF = 150
N_BJ = 50
N_DELIST = 100

s_stock = random.sample(stocks, min(N_STOCK, len(stocks)))
s_etf = random.sample(etfs, min(N_ETF, len(etfs)))
s_bj = random.sample(bj, min(N_BJ, len(bj)))
s_delist = random.sample(delist, min(N_DELIST, len(delist)))

sub = s_stock + s_etf + s_bj + s_delist
print(f"子样本: {len(sub)} 只 (股票 {len(s_stock)} + ETF {len(s_etf)} + 北交所 {len(s_bj)} + 退市 {len(s_delist)})")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(sorted(sub)))
print(f"已写: {OUT}")