# -*- coding: utf-8 -*-
"""补丁 2e：WATCH_V9_CARD 替换为退役说明（独立文件避免引号嵌套）"""
import io
import re

SRC = r"D:\Documents\Workbuddy\股票基金\quant-weight-system\build_dual_system.py"
t = io.open(SRC, encoding="utf-8").read()

m2 = re.search(r"WATCH_V9_CARD = f'''<div class=\"card\" id=\"watch-v9-card\">.*?'''", t, re.S)
assert m2, "watch card missing"
new_card = (
    "WATCH_V9_CARD = ('<div class=\"card\" id=\"watch-v9-card\"><h2>📌 历史跟踪池（已退役）</h2>'\n"
    "                 '<div class=\"sub\" style=\"color:#ef4444\">⛔ v9 跟踪池展示已于 2026-09-13 移除（战法退役，十重证伪）。"
    "数据文件保留于 enhanced_data.js 供回溯。</div></div>')"
)
t = t[:m2.start()] + new_card + t[m2.end():]
io.open(SRC, "w", encoding="utf-8").write(t)
print("2e done")
