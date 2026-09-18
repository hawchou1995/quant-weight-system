# -*- coding: utf-8 -*-
"""东财批量通道接主链（用户 2026-09-18 批准）。

形态：新增包装脚本 `backtest/em_bulk_all.py`（依次跑 A股 → ETF/LOF → 单只端点兜底），
在 daily_refresh 的「数据更新」步之后挂**一个** [软] 步骤。

为什么这样接线：
  · 三个子通道都只补「本地末行 < 交易日」的标的 → **幂等**；正常日 update_daily 已补齐时
    待补 0，成本 = 3 次批量拉取（A股 ~11s + ETF ~3s）+ 0 次写盘。
  · 今天那种「三源同时滞后」时，它是唯一能在十几秒内补齐全市场的通道（实测 A股 4191 只补齐）。
  · 全部走 [软]：失败不阻断主链（数据是上游，不该把看板链拖死）。
"""
import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
BASE = Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
OK = True

# ---- ① 包装脚本 ----
WRAP = BASE / "backtest" / "em_bulk_all.py"
if WRAP.exists():
    print("[skip] em_bulk_all.py 已存在")
else:
    WRAP.write_text('''# -*- coding: utf-8 -*-
"""东财批量补齐总入口（R-em-bulk-0918 · 用户 2026-09-18 批准接主链）。

依次跑三个子通道（全部幂等，只补「本地末行 < 交易日」的标的）：
    ① A股           em_bulk_snapshot.py            fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048
    ② ETF/LOF/基金  em_bulk_snapshot.py --etf      fs=b:MK0021..MK0026
    ③ 残余兜底      em_leftover_fill.py            单只端点（clist 未收录的 sz159* 等）

设计：任一步失败**不阻断**后续步，最后汇总；退出码 = 0（数据是上游，失败由主链按 [软] 处理）。
用法：python backtest/em_bulk_all.py [--dry]
"""
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PY = sys.executable
DRY = ["--dry"] if "--dry" in sys.argv else []
STEPS = [
    ("A股", [str(HERE / "em_bulk_snapshot.py")] + DRY),
    ("ETF/LOF/基金", [str(HERE / "em_bulk_snapshot.py"), "--etf"] + DRY),
    ("残余兜底(单只端点)", [str(HERE / "em_leftover_fill.py")] + DRY),
]

t0 = time.time()
fails = []
for name, args in STEPS:
    print(f"\\n---------- {name} ----------", flush=True)
    r = subprocess.run([PY] + args, cwd=str(HERE.parent), capture_output=True, text=True)
    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    for ln in tail[-6:]:
        print("  " + ln, flush=True)
    if r.returncode != 0:
        fails.append(f"{name}(rc={r.returncode})")
print(f"\\n[em-bulk-all] 完成 {len(STEPS) - len(fails)}/{len(STEPS)}  失败：{fails or '无'}"
      f"  耗时 {time.time() - t0:.0f}s")
sys.exit(0)
''', encoding="utf-8")
    ast.parse(WRAP.read_text(encoding="utf-8"))
    print("[ok] 新建 backtest/em_bulk_all.py（AST 过）")

# ---- ② 挂进 daily_refresh ----
DR = BASE / "daily_refresh.py"
t = DR.read_text(encoding="utf-8")
old = '    ("全量池守卫 fullpool_guard[软]", ["backtest/fullpool_guard.py"], "--skip-fullguard" in sys.argv),\n'
new = (
    '    ("全量池守卫 fullpool_guard[软]", ["backtest/fullpool_guard.py"], "--skip-fullguard" in sys.argv),\n'
    '    # 东财全市场批量补齐（R-em-bulk-0918 · 用户 2026-09-18 批准）：A股(5560只/11s) → ETF/LOF(1751只/3s)\n'
    '    # → 单只端点兜底。全部幂等（只补「本地末行 < 交易日」），正常日待补 0；三源同时滞后时是唯一\n'
    '    # 能十几秒补齐全市场的通道。实测：A股 4191 只、ETF 704 只、残余 26 只一次补全。\n'
    '    # [软]=失败不阻断主链；--skip-embulk 跳过。\n'
    '    ("东财批量补齐 em_bulk[软]", ["backtest/em_bulk_all.py"], "--skip-embulk" in sys.argv),\n'
)
if new in t:
    print("[skip] daily_refresh 已挂载")
else:
    if t.count(old) != 1:
        print(f"[FAIL] daily_refresh 锚点命中 {t.count(old)} 次")
        OK = False
    else:
        t = t.replace(old, new, 1)
        ast.parse(t)
        DR.write_text(t, encoding="utf-8")
        print("[ok] daily_refresh 已挂 em_bulk 步骤（数据更新之后、守卫之后）")

print()
print("总结论：" + ("✅ 落地" if OK else "❌ FAIL"))
sys.exit(0 if OK else 1)
