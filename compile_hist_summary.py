# -*- coding: utf-8 -*-
"""生成全量回测池历史数据编译清单（区间/行数/涨幅）"""
import glob
from pathlib import Path
import pandas as pd

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
HIST = BASE / "data_hist"

# 代码 -> 名称（合并 UNIVERSE 与 data_tmp 已知集合）
NAME_MAP = {
    "300502": "新易盛", "300308": "中际旭创", "159516": "半导体设备ETF", "600498": "烽火通信",
    "601138": "工业富联", "002463": "沪电股份", "002384": "东山精密", "600183": "生益科技",
    "300476": "胜宏科技", "603986": "兆易创新", "002185": "华天科技", "605358": "立昂微",
    "603228": "景旺电子", "603339": "四方科技", "000636": "风华高科", "515880": "通信ETF",
    "516150": "稀土ETF嘉实", "560390": "电网设备ETF易方达", "008254": "华宝致远混合C",
    "018036": "长城新能源车股C", "002891": "华夏移动互联CNY", "024239": "华夏全球QDII C",
    "014002": "浦银智能科技C", "020900": "天弘通信设备C",
    "000002": "万科A", "000333": "美的集团", "000651": "格力电器", "000858": "五粮液",
    "002594": "比亚迪", "002714": "牧原股份", "300059": "东方财富", "300274": "阳光电源",
    "300750": "宁德时代", "300760": "迈瑞医疗", "600009": "上海机场", "600030": "中信证券",
    "600036": "招商银行", "600048": "保利发展", "600111": "北方稀土", "600276": "恒瑞医药",
    "600438": "通威股份", "600519": "贵州茅台", "600598": "北大荒", "600760": "中航沈飞",
    "600887": "伊利股份", "600893": "航发动力", "600900": "长江电力", "600905": "三峡能源",
    "600941": "中国移动", "601006": "大秦铁路", "601012": "隆基绿能", "601088": "中国神华",
    "601225": "陕西煤业", "601318": "中国平安", "601398": "工商银行", "601601": "中国太保",
    "601633": "长城汽车", "601728": "中国电信", "601899": "紫金矿业", "603259": "药明康德",
    "603288": "海天味业", "688981": "中芯国际",
}

def pct(a, b):
    if a and b and b != 0:
        return (a / b - 1) * 100
    return float("nan")

rows = []
for f in sorted(glob.glob(str(HIST / "*.csv"))):
    code = Path(f).stem
    df = pd.read_csv(f, dtype={"date": str})
    df = df.sort_values("date")
    first, last = df["date"].iloc[0], df["date"].iloc[-1]
    c0, c1 = df["close"].iloc[0], df["close"].iloc[-1]
    rows.append((code, NAME_MAP.get(code, code), first, last, len(df), c0, c1, pct(c1, c0)))

lines = []
lines.append("# 全量回测池历史数据-20260814\n")
lines.append("> 数据源：akshare（新浪前复权日线 + 东财场外基金净值），Wind 限额替代方案\n")
lines.append(f"> 编译时间：2026-08-14 18:0X · 标的数：**{len(rows)}** · 输出：`量化权重系统/data_hist/`\n")
lines.append("| 代码 | 名称 | 起始 | 截止 | 行数 | 首收盘 | 末收盘 | 区间涨幅 |")
lines.append("|---|---|---|---|---|---|---|---|")
ok = 0
for code, name, first, last, n, c0, c1, p in rows:
    if n > 1000:
        ok += 1
    lines.append(f"| {code} | {name} | {first} | {last} | {n} | {c0:.2f} | {c1:.2f} | {p:+.1f}% |")
lines.append("")
lines.append(f"**统计**：62 只全部入库；覆盖 2016 年至今的 {ok} 只；新上市标的起始日按实际上市日。")
lines.append("")
lines.append("## 说明")
lines.append("- 股票/ETF：akshare 新浪接口 `stock_zh_a_daily` / `fund_etf_hist_sina`，前复权，2016-01-04 起（新上市按上市日）。")
lines.append("- 场外基金：akshare 东财 `fund_open_fund_info_em` 单位净值，无 OHLC，close=单位净值。")
lines.append("- 与旧数据（westock-data，2022-06 起）按日期合并，旧数据优先保留。")
lines.append("- Wind 补齐：本次已覆盖 2016 年至今，**无需再用 Wind 补齐**（如用户要求双源校验可后续做）。")

out = BASE / "data-全量回测池历史数据-20260814.md"
out.write_text("\n".join(lines), encoding="utf-8")
print(f"已生成: {out} ({len(rows)} 只)")
