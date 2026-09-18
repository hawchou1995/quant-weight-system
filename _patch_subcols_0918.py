# -*- coding: utf-8 -*-
"""#5 第三次修正：卫星目标持仓表 —— 子项**每个指标一列**（用户明确要求）。

用户原话：「中长线选股池我让你把子项拆开，是每个指标都要拆开作为表头，单元格填分数，懂？」

前两次我做错的：把子项做成**一列**（`子项评分`，值形如 "65/62/47/75/72"）。
正确形态：**代码 名称 行业 收盘 一手约 计划金额 评分总分 | 各指标各一列 | 操作 …**

关键：两轨子项结构不同，**不能拆显示串**，必须在源头输出结构化字段
  轨A（冷门低波，3 项）：额 / 波 / 换（各 0-33.3）
  轨B（SUPER，13 因子 ICIR 贡献）：额 市反 振 动60 BP EP 牛绳 止损间 距BBI 缩量 J低 回撤 压力间 挤压
"""
import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
SP = BASE / "backtest" / "build_satellite_pool.py"
BD = BASE / "build_dual_system.py"
OK = True


def patch(path, pairs, tag):
    global OK
    p = path
    t = p.read_text(encoding="utf-8")
    for old, new, name in pairs:
        if new in t and old not in t:
            print(f"  [skip] {tag}/{name}（已打过）")
            continue
        c = t.count(old)
        if c != 1:
            print(f"  [FAIL] {tag}/{name}：命中 {c}")
            OK = False
            continue
        t = t.replace(old, new, 1)
        print(f"  [ok]   {tag}/{name}")
    try:
        ast.parse(t)
    except SyntaxError as e:
        print(f"  [FAIL] {tag} AST line {e.lineno}: {e.msg}")
        OK = False
        return
    p.write_text(t, encoding="utf-8")


print("=" * 74)
print("① 源头：输出结构化 parts_kv")
print("=" * 74)
patch(SP, [
    ('        "parts": f"额 {p_amt:.0f} · 波 {p_atr:.0f} · 换 {p_turn:.0f}（各 0-33.3）",',
     '        "parts": f"额 {p_amt:.0f} · 波 {p_atr:.0f} · 换 {p_turn:.0f}（各 0-33.3）",\n'
     '        # 结构化子项（R-subcols-0918）：供看板按「每个指标一列」渲染，勿拆显示串\n'
     '        "parts_kv": [["额", p_amt], ["波", p_atr], ["换", p_turn]],',
     "track_a"),
    ('        "parts": parts,\n',
     '        "parts": parts,\n'
     '        # 结构化子项（R-subcols-0918）：13 因子贡献，按 |贡献| 降序（与 parts 同序）\n'
     '        "parts_kv": [[_lbl.get(k, k), round(v, 2)] for k, v in contrib],\n',
     "track_b"),
], "①")

print()
print("=" * 74)
print("② 看板：子项按指标拆列")
print("=" * 74)
patch(BD, [
    # 表头：评分总分 之后插入动态子项列
    ('        head = ("<th>代码</th><th>名称</th><th>行业</th><th>收盘</th><th>一手约</th><th>计划金额</th>"\n'
     '                "<th>评分总分</th><th>子项评分</th><th>操作</th><th>涨跌幅</th><th>近1年</th>")',
     '        _subs = [k for k, _v in ((tr["rows"][0].get("parts_kv") or []) if tr.get("rows") else [])]\n'
     '        _sub_th = "".join(\n'
     '            f\'<th title="{tr.get("ranking", "")} 子项（{tr.get("name", "")}）" \'\n'
     '            f\'style="text-align:center;font-weight:500">{lbl}</th>\' for lbl in _subs)\n'
     '        head = ("<th>代码</th><th>名称</th><th>行业</th><th>收盘</th><th>一手约</th><th>计划金额</th>"\n'
     '                "<th>评分总分</th>" + _sub_th +\n'
     '                "<th>操作</th><th>涨跌幅</th><th>近1年</th>")',
     "head"),
    # 单元格：每个子项一个 td
    ('                f\'<td title="{r.get("detail", "")}"><b>{r.get("score_txt", "—")}</b></td>\'\n'
     '                f\'<td><div style="font-size:10.5px;color:#94a3b8;line-height:1.35;'
     'white-space:normal;max-width:190px" title="{r.get("detail", "")}">{r.get("parts", "")}</div></td>\'',
     '                f\'<td title="{r.get("detail", "")}"><b>{r.get("score_txt", "—")}</b></td>\'\n'
     '                + "".join(\n'
     '                    f\'<td class="num" style="text-align:center;font-size:12px">{'
     '_kv.get(lbl, "—")}</td>\'\n'
     '                    for lbl in _subs)',
     "cells"),
    # _kv 需在 _row 之前定义
    ('        def _row(r):\n            cells = (',
     '        def _row(r):\n'
     '            _kv = {k: v for k, v in (r.get("parts_kv") or [])}\n'
     '            cells = (',
     "kv"),
], "②")

print()
print("总结论：" + ("✅ 落地" if OK else "❌ FAIL"))
sys.exit(0 if OK else 1)
