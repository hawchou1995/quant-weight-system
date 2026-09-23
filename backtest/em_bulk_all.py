# -*- coding: utf-8 -*-
"""东财批量补齐总入口（R-em-bulk-0918 · 用户 2026-09-18 批准接主链）。

依次跑四个子通道（全部幂等，只补「本地末行 < 交易日」的标的；clist 首选、ulist 次选）：
    ① A股           em_bulk_snapshot.py            clist 主力 fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048
    ② ETF/LOF/基金  em_bulk_snapshot.py --etf      clist 主力 fs=b:MK0021..MK0026
    ③ 缺口兜底      em_ulist_bulk.py               **clist 不可用时的次选**（ulist.np/get，缺口优先省请求）
    ④ 残余兜底      em_leftover_fill.py            单只端点（clist 未收录的 sz159* 等）
    ⑤ 腾讯兜底      em_tencent_fill.py             qt.gtimg.cn 批量（EM 三端点全挂时补齐全市场，~6s）

设计：任一步失败**不阻断**后续步，最后汇总；退出码 = 0（数据是上游，失败由主链按 [软] 处理）。
       2026-09-23 加「端点探活」：clist / 单只端点被限流时各步 ≤3 次探测即退（rc=3），
       秒级让位给 ③ulist 兜底，不再带重试去硬敲（省请求 = 缩短限流恢复时间）。
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
    ("①A股 clist(首选)", [str(HERE / "em_bulk_snapshot.py")] + DRY),
    ("②ETF/LOF clist(首选)", [str(HERE / "em_bulk_snapshot.py"), "--etf"] + DRY),
    ("③缺口兜底 ulist(次选)", [str(HERE / "em_ulist_bulk.py")] + DRY),
    ("④残余兜底(单只端点)", [str(HERE / "em_leftover_fill.py")] + DRY),
    # 2026-09-23 新增（用户要求"兜底还是要的"）：EM 三端点全挂时的**完整兜底** —— 腾讯 qt.gtimg.cn
    #   批量补齐全市场（实测 400 码/请求、全市场约 6s；幂等；含"时间戳==交易日且≥15:00"硬门）。
    #   ⚠ 精度差：腾讯成交额只到「万元」整数（EM 到元）→ amount 列 ~0.001% 级差异，已在脚本内注明。
    #   ⚠ 本步在 update_daily 之后（daily_refresh L32 → L46）：它是**完整性兜底**，不是提速替代。
    ("⑤腾讯批量兜底", [str(HERE / "em_tencent_fill.py")] + DRY),
]

t0 = time.time()
fails = []
for name, args in STEPS:
    print(f"\n---------- {name} ----------", flush=True)
    # 2026-09-22 修复：不传 encoding 时 Python 按 locale(GBK) 解码，而子脚本输出 UTF-8
    # → 读取线程 UnicodeDecodeError，子进程 stdout/stderr 全部丢弃（日志只剩 rc，看不到原因）。
    r = subprocess.run([PY] + args, cwd=str(HERE.parent), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    for ln in tail[-6:]:
        print("  " + ln, flush=True)
    if r.returncode != 0:
        fails.append(f"{name}(rc={r.returncode})")
print(f"\n[em-bulk-all] 完成 {len(STEPS) - len(fails)}/{len(STEPS)}  失败：{fails or '无'}"
      f"  耗时 {time.time() - t0:.0f}s")
if fails:
    print("  rc 含义：1=异常 / 2=口径未对齐（拒写）/ 3=端点不可用（限流被拦，交下游兜底）")
sys.exit(0)
