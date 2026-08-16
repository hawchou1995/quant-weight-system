# -*- coding: utf-8 -*-
"""
全量回测池历史数据编译 → Obsidian 知识库
=========================================
读取 data_full/*.csv，生成编译清单 md（区间/行数/涨幅），输出到：
1. 量化权重系统/data-全量回测池历史数据-20260814-full.md
2. 复制到 Obsidian 02-投资研究-Investment/
"""
import os
import json, glob
from pathlib import Path
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
HIST = BASE / "data_full"
NAMES = json.loads((BASE / "data_full_names.json").read_text(encoding="utf-8"))
OUT_MD = BASE / "data-全量回测池历史数据-20260814-full.md"
OBSIDIAN_DIR = Path(r"D:/Documents/Obsidian/WorkBuddy/wiki/02-投资研究-Investment")

def classify(code: str) -> str:
    """按代码前缀分类：北交所/沪市/深市/ETF/退市"""
    c = code.lower()
    if c.startswith("bj"):
        return "北交所"
    if c.startswith("sh5") or c.startswith("sz1"):
        return "ETF"
    if c.startswith("sh6") or c.startswith("sh9"):
        return "沪市"
    if c.startswith("sz0") or c.startswith("sz3"):
        return "深市"
    return "其他"

rows = []
for f in sorted(glob.glob(str(HIST / "*.csv"))):
    code = Path(f).stem
    try:
        df = pd.read_csv(f, dtype={"date": str})
        df = df.sort_values("date")
        first, last = df["date"].iloc[0], df["date"].iloc[-1]
        n = len(df)
        c0, c1 = df["close"].iloc[0], df["close"].iloc[-1]
        pct = (c1 / c0 - 1) * 100 if c0 and c0 > 0 else float("nan")
        rows.append({
            "code": code, "name": NAMES.get(code, code), "cat": classify(code),
            "first": first, "last": last, "n": n, "c0": c0, "c1": c1, "pct": pct,
        })
    except Exception as e:
        print(f"[跳过] {code}: {e}")

rows.sort(key=lambda r: (r["cat"], r["code"]))

# 统计
total = len(rows)
cats = {}
for r in rows:
    cats[r["cat"]] = cats.get(r["cat"], 0) + 1
covered_2016 = sum(1 for r in rows if r["first"] <= "2016-01-04")

lines = []
lines.append("# 全量回测池历史数据-20260814（全量版）\n")
lines.append("> 数据源：akshare（新浪前复权日线 + 新浪 ETF + 腾讯退市股不复权），Wind 限额替代方案\n")
lines.append(f"> 编译时间：2026-08-14 19:00 · 标的数：**{total}** · 输出：`量化权重系统/data_full/`\n")
lines.append(f"**分类统计**：{' · '.join(f'{k} {v} 只' for k, v in sorted(cats.items()))}\n")
lines.append(f"**2016-01-04 起覆盖**：{covered_2016} 只（{covered_2016/total*100:.1f}%；其余为上市/挂牌晚于 2016）\n")
lines.append("| 分类 | 代码 | 名称 | 起始 | 截止 | 行数 | 首收盘 | 末收盘 | 区间涨幅 |")
lines.append("|---|---|---|---|---|---|---|---|---|")
for r in rows:
    lines.append(f"| {r['cat']} | {r['code']} | {r['name']} | {r['first']} | {r['last']} | {r['n']} | "
                 f"{r['c0']:.2f} | {r['c1']:.2f} | {r['pct']:+.1f}% |")
lines.append("")
lines.append("## 说明")
lines.append("- 在市 A 股（沪深北）：akshare 新浪接口 `stock_zh_a_daily`，前复权，2016-01-04 起（新上市按上市日）。")
lines.append("- ETF：akshare 新浪接口 `fund_etf_hist_sina`（新浪 ETF 无复权参数，返回原始价）。")
lines.append("- 退市股：腾讯行情接口（不复权），2016 起至退市日；停牌期无数据属正常。")
lines.append("- 退市股含知识库 v6 样本池 10 只（乐视/暴风/康美/中弘/雏鹰/长生/华泽/千山/金亚/ST锐电）。")
lines.append("- ⚠️ 康美药业 600518 腾讯接口返回至 2026-08-14（代码疑似被复用），退市前数据仍有效。")
lines.append("- 与旧数据（westock-data，2022-06 起）格式一致：date/open/high/low/close/volume/amount。")
lines.append("")
lines.append("> ⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。")

OUT_MD.write_text("\n".join(lines), encoding="utf-8")
print(f"已生成: {OUT_MD} ({total} 只)")
if OBSIDIAN_DIR.exists():
    target = OBSIDIAN_DIR / OUT_MD.name
    import shutil
    shutil.copy2(OUT_MD, target)
    print(f"已复制到 Obsidian: {target}")
else:
    print(f"[警告] Obsidian 目录不存在: {OBSIDIAN_DIR}")