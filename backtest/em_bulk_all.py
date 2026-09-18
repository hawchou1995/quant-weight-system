# -*- coding: utf-8 -*-
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
    print(f"\n---------- {name} ----------", flush=True)
    r = subprocess.run([PY] + args, cwd=str(HERE.parent), capture_output=True, text=True)
    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    for ln in tail[-6:]:
        print("  " + ln, flush=True)
    if r.returncode != 0:
        fails.append(f"{name}(rc={r.returncode})")
print(f"\n[em-bulk-all] 完成 {len(STEPS) - len(fails)}/{len(STEPS)}  失败：{fails or '无'}"
      f"  耗时 {time.time() - t0:.0f}s")
sys.exit(0)
