# -*- coding: utf-8 -*-
"""补 c2-js/js-foot：导航底部三个链接的标签包进 <span class="lbl">。"""
import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
P = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system/ui_components.py")
t = P.read_text(encoding="utf-8")

old = (
    "    '<a href=\"javascript:void(0)\" data-anchor=\"review\"><span class=\"ic\">\U0001F4CB</span>复盘日志</a>'+\n"
    "    '<a href=\"javascript:void(0)\" data-anchor=\"changelog\"><span class=\"ic\">\U0001F4DD</span>更新日志</a>'+\n"
    "    '<a href=\"https://qingju.me/\" target=\"_blank\" rel=\"noopener\"><span class=\"ic\">\U0001F4AC</span>\u9752\u6a58\u793e\u533a</a></div>';"
)
new = (
    "    '<a href=\"javascript:void(0)\" data-anchor=\"review\"><span class=\"ic\">\U0001F4CB</span><span class=\"lbl\">\u590d\u76d8\u65e5\u5fd7</span></a>'+\n"
    "    '<a href=\"javascript:void(0)\" data-anchor=\"changelog\"><span class=\"ic\">\U0001F4DD</span><span class=\"lbl\">\u66f4\u65b0\u65e5\u5fd7</span></a>'+\n"
    "    '<a href=\"https://qingju.me/\" target=\"_blank\" rel=\"noopener\"><span class=\"ic\">\U0001F4AC</span><span class=\"lbl\">\u9752\u6a58\u793e\u533a</span></a></div>';"
)

if new in t:
    print("[skip] js-foot 已打过")
else:
    c = t.count(old)
    if c != 1:
        print(f"[FAIL] 锚点命中 {c} 次（期望 1）")
        sys.exit(1)
    t = t.replace(old, new, 1)
    ast.parse(t)
    P.write_text(t, encoding="utf-8")
    print("[ok] js-foot 已打 + AST 过")
