import ast
import sys

sys.stdout.reconfigure(encoding="utf-8")
p = r"D:/Documents/Workbuddy/股票基金/quant-weight-system/daily_refresh.py"
src = open(p, encoding="utf-8").read()
ast.parse(src)
print("[ok] AST parse OK")
lines = src.splitlines()
print("[info] 链首试采行:", [i + 1 for i, l in enumerate(lines) if "链首·试采" in l])
print("[info] gushi 调用行:", [i + 1 for i, l in enumerate(lines) if "test/gushi_daily_collect.py" in l])
print("[info] STEPS 循环行:", [i + 1 for i, l in enumerate(lines) if l.startswith("for name, args, skip")])
print("[info] _gushi_py 定义行:", [i + 1 for i, l in enumerate(lines) if l.startswith("def _gushi_py")])
print("[info] t0 行:", [i + 1 for i, l in enumerate(lines) if l.startswith("t0 = time.time()")])
print("[info] fails=[] 行:", [i + 1 for i, l in enumerate(lines) if l.startswith("fails = []")])
print("[info] 步数:", src.count('\n    ("'))
