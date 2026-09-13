# -*- coding: utf-8 -*-
"""每日收盘后一键刷新（三轨体系）：数据 → 池 → 信号 → 看板 → 部署
用法：python daily_refresh.py [--skip-deploy] [--skip-data]
步骤：
 1. update_daily.py          拉最新日 K/基金净值（数据层）
 2. build_short_pool.py      短池+FB3 基金池+市况门控（short_pool.json / enhanced_data.js）
 3. build_satellite_pool.py  双卫星目标持仓（satellite_pool.json）
 4. signal_satellite_0913.py 三轨信号输出（轨A/轨B/轨C 明细）
 5. build_dual_system.py     看板重建（dual_system.html）
 6. _deploy_fundline_0911.py gh-pages 部署 + 线上校验
"""
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
PY = sys.executable
STEPS = [
    ("数据更新 update_daily", ["update_daily.py"], "--skip-data" in sys.argv),
    ("短池+门控 build_short_pool", ["build_short_pool.py"], False),
    ("双卫星池 build_satellite_pool", ["backtest/build_satellite_pool.py"], False),
    ("三轨信号 signal_satellite", ["backtest/signal_satellite_0913.py"], False),
    ("看板重建 build_dual_system", ["build_dual_system.py"], False),
    ("部署 gh-pages", ["_deploy_fundline_0911.py"], "--skip-deploy" in sys.argv),
]
t0 = time.time()
fails = []
for name, args, skip in STEPS:
    if skip:
        print(f"[skip] {name}", flush=True)
        continue
    print(f"\n========== {name} ==========", flush=True)
    r = subprocess.run([PY] + args, cwd=str(BASE))
    if r.returncode != 0:
        fails.append(name)
        print(f"❌ {name} 失败（exit {r.returncode}）—— 中止后续步骤", flush=True)
        break
print(f"\n{'❌ 失败: ' + ', '.join(fails) if fails else '✅ 全链完成'} · 总耗时 {time.time()-t0:.0f}s", flush=True)
sys.exit(1 if fails else 0)
