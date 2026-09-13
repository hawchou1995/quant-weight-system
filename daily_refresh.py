# -*- coding: utf-8 -*-
"""每日收盘后一键刷新（三轨体系·全量）：数据 → 池 → 复盘 → 信号 → 看板 → 部署 → 同步 main
用法：python daily_refresh.py [--skip-deploy] [--skip-data] [--force]
非交易日自动跳过（index_000300.csv 最后日期 != 今天 时，除非 --force）。
"""
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
PY = sys.executable
FORCE = "--force" in sys.argv

# ---- 交易日闸门 ----
if not FORCE:
    idx = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
    last_trade = idx["date"].iloc[-1]
    today = date.today().strftime("%Y-%m-%d")
    if last_trade != today:
        print(f"[skip] 非交易日（最新交易日 {last_trade} ≠ 今天 {today}）——收盘刷新无需执行", flush=True)
        sys.exit(0)
    print(f"[交易日确认] {today} = 最新交易日 ✓", flush=True)

STEPS = [
    ("数据更新 update_daily", ["update_daily.py"], "--skip-data" in sys.argv),
    ("短池+门控+FB3基金池 build_short_pool", ["build_short_pool.py"], False),
    ("复盘日志+跟踪池 review_daily", ["review_daily.py"], False),
    ("复盘日志页 build_log_pages", ["build_log_pages.py"], False),
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

# ---- main 源码同步（看板产物，失败不阻断）----
if not fails:
    git = subprocess.run(["git", "add", "dual_system.html", "index.html", "short_pool.json",
                          "short_pool.js", "enhanced_data.js", "short_signals.js", "a5_pool.js",
                          "changelog.md", "changelog.html", "review_log.html",
                          "short_v3_fund_summary.json", "short_v3_fund_slip20_summary.json",
                          "backtest/satellite_pool.json"],
                         cwd=str(BASE), capture_output=True)
    if git.returncode == 0:
        c = subprocess.run(["git", "commit", "-m", f"chore(daily): {date.today()} 收盘刷新（池/信号/看板/复盘日志）"],
                           cwd=str(BASE), capture_output=True)
        if c.returncode == 0:
            p = subprocess.run(["git", "push", "origin", "main"], cwd=str(BASE), capture_output=True)
            print(f"[git] main 同步 {'✓' if p.returncode == 0 else '✗ ' + p.stderr.decode(errors='replace')[:100]}", flush=True)

print(f"\n{'❌ 失败: ' + ', '.join(fails) if fails else '✅ 全链完成'} · 总耗时 {time.time()-t0:.0f}s", flush=True)
sys.exit(1 if fails else 0)
