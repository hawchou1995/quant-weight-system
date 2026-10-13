# -*- coding: utf-8 -*-
"""HPDK 买入清单「表头 ↔ 表体」列对齐门禁（ADR-0004 · R1）

为什么需要它
------------
2026-10-08 复核发现一个**真 bug**：`intraday_live.py` 的 `TOPTHEAD`（表头）18 列顺序是
`# | 标的 | 状态 | 可执行时点 | 板块 | …`，而数据行 `_h3` 实际发出的顺序是
`# | 标的 | **可执行时点** | **状态** | …` —— 第 3/4 列互换，表格渲染错位。

成因：新增「可执行时点」列时，表头插在「状态」**之后**、数据行却插在「状态」**之前**，
而当时的验证只覆盖了 JS 语法（`node --check`）与行为夹具，**没有任何检查比对表头与表体的列序**。

本门禁把「表头列序 == 表体列序」变成会 `exit 1` 的机械断言，避免同类漂移再次静默发生。

用法
----
    python tools/gate_hpdk_table_cols.py            # 检查真实源码
    python tools/gate_hpdk_table_cols.py --selftest  # 内置反例：故意交换两列 → 必须失败

退出码：0 = 对齐（或自检通过）；1 = 不对齐 / 无法解析（失败闭锁，不静默放行）。
"""
from __future__ import annotations

import argparse
import os
import re
import sys

DEFAULT_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "intraday_live.py")

#: 分类规则（按优先级）；label 必须与表头归一化后的词一致
CLASSIFY: list[tuple[str, str]] = [
    (r"_i3 \+ 1", "#"),
    (r"_x3\.name", "标的"),
    (r"买入候选", "状态"),
    (r"盲挂", "可执行时点"),
    (r"_m3\.board", "板块"),
    (r"_m3\.ind", "行业"),
    (r'data-key="px"', "现价"),
    (r'data-key="chg"', "涨跌幅"),
    (r'data-key="amt"', "成交额20"),
    (r'data-key="vr"', "量比"),
    (r'data-key="r20"', "20日涨幅"),
    (r'data-key="pcl"', "昨收价"),
    (r'data-key="buy"', "挂单价"),
    (r"今开成交", "成交价"),
    (r'data-key="tp"', "止盈价"),
    (r"尾盘", "卖出时点"),
    (r'data-key="qty"', "建议股数"),
    (r'data-key="cap"', "单票可买"),
]


def _strip_tags(s: str) -> str:
    s = re.sub(r"<span[^>]*>.*?</span>", " ", s, flags=re.S)   # 去掉 live-tag 徽标
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_header(src: str) -> list[str]:
    """抽 `var TOPTHEAD = …;` 里的列名（归一化后）。"""
    m = re.search(r"var TOPTHEAD\s*=(.*?);\r?\n", src, re.S)
    if not m:
        raise SystemExit("解析失败：找不到 var TOPTHEAD（失败闭锁）")
    ths = re.findall(r"<th(?:\s[^>]*)?>(.*?)</th>", m.group(1), re.S)
    labels = []
    for t in ths:
        txt = _strip_tags(t)
        # 归一化：截到第一个空白 / 括号前（表头「单票可买（上限）」「止盈价 +2%」「现价 实时」
        # 必须与表体分类标签同形）。注意 `<thead>` 会被 `<th[^>]*>` 误匹配 ——
        # 首版实测把第 1 列解析成 `'`，故必须用「th 后跟空白或直接 >」的形态。
        txt = re.split(r"[\s（(]", txt)[0] if txt else "?"
        labels.append(txt if txt else "?")
    return labels


def parse_row(src: str) -> tuple[list[str], list[str]]:
    """抽买入清单**数据行**的 td 序列，返回 (labels, 未识别片段)。

    数据行 = `_h3 += '<tr data-code='` 起、到其后第一个 `'</tr>';` 止。
    """
    i = src.find("_h3 += '<tr data-code=")
    if i < 0:
        raise SystemExit("解析失败：找不到买入清单数据行（失败闭锁）")
    j = src.find("'</tr>';", i)
    if j < 0:
        raise SystemExit("解析失败：找不到数据行结尾 '</tr>'（失败闭锁）")
    block = src[i:j]
    tds = re.findall(r"<td\b.*?</td>", block, re.S)
    labels, unknown = [], []
    for t in tds:
        hit = next((lab for pat, lab in CLASSIFY if re.search(pat, t)), None)
        if hit is None:
            unknown.append(_strip_tags(t)[:60])
            labels.append("?")
        else:
            labels.append(hit)
    return labels, unknown


def compare(header: list[str], row: list[str]) -> list[str]:
    """返回差异清单（空 = 对齐）。列数不等或逐列不等都算差异。"""
    diffs = []
    if len(header) != len(row):
        diffs.append("列数不等：表头 %d 列 vs 表体 %d 列" % (len(header), len(row)))
    for k in range(min(len(header), len(row))):
        if header[k] != row[k]:
            diffs.append("第 %d 列错位：表头「%s」≠ 表体「%s」" % (k + 1, header[k], row[k]))
    return diffs


def check(src: str, label: str) -> int:
    header = parse_header(src)
    row, unknown = parse_row(src)
    print("[%s] 表头 %d 列：%s" % (label, len(header), " | ".join(header)))
    print("[%s] 表体 %d 列：%s" % (label, len(row), " | ".join(row)))
    if unknown:
        print("[%s] !! 有 td 无法归类（分类规则需更新，不得静默通过）：%s" % (label, unknown))
        return 1
    diffs = compare(header, row)
    if diffs:
        print("[%s] 列序不对齐：" % label)
        for d in diffs:
            print("   ✗", d)
        return 1
    print("[%s] 列序对齐（逐列一致）" % label)
    return 0


def _selftest(src: str) -> int:
    """反例证明门禁非空转：把表体第 3、4 列互换后必须失败。"""
    ok = True
    i = src.find("_h3 += '<tr data-code=")
    j = src.find("'</tr>';", i)
    block = src[i:j]
    tds = re.findall(r"<td\b.*?</td>", block, re.S)
    if len(tds) < 4:
        print("[自检] 无法取出足够 td，跳过"); return 1
    swapped_tds = list(tds)
    swapped_tds[2], swapped_tds[3] = swapped_tds[3], swapped_tds[2]
    # 用同一套解析函数跑一份「被交换」的源码
    swapped_src = src[:i] + block.replace(tds[2], "\x00A\x00").replace(tds[3], tds[2]) \
        .replace("\x00A\x00", tds[3]) + src[j:]
    print("[自检] 预期：交换第 3/4 列后门禁必须失败")
    rc = check(swapped_src, "自检·反例")
    if rc == 0:
        print("[自检] !! 反例未被拦下 → 门禁空转"); ok = False
    else:
        print("[自检] 反例被拦下 ✓")
    print("\n自检" + ("通过（退出码 0）" if ok else "失败（退出码 1）"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="HPDK 买入清单表头/表体列对齐门禁")
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if not os.path.isfile(a.src):
        print("源文件不存在：%s（失败闭锁）" % a.src, file=sys.stderr)
        return 1
    src = open(a.src, "r", encoding="utf-8", errors="replace").read()
    if a.selftest:
        return _selftest(src)
    return check(src, "真实源码")


if __name__ == "__main__":
    raise SystemExit(main())
