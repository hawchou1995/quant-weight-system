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
    ("KHunter 模拟盘A khunter_paper", ["khunter_paper_20260903.py"], False),
    ("KHunter 模拟盘C khunter_paper_c", ["khunter_paper_20260903.py", "--state", "khunter_paper_state_c", "--rsi-sell", "50"], False),
    ("A5 打板模拟盘 a5_paper", ["backtest/a5_paper_0914.py"], False),
    ("双卫星模拟盘 satellite_paper", ["backtest/satellite_paper_0914.py"], False),
    ("pct40 出场影子轨 exit_shadow", ["backtest/exit_shadow_0915.py"], False),
    ("KHunter 模拟盘快照 khunter_snapshot", ["khunter_paper_snapshot.py"], False),
    # A5 打板实验盘（看板「打板族」视图的数据源）——必须在 build_dual_system 之前跑；[软]=失败不阻断主链
    # 2026-09-14 补：此前该流水线未接入每日链 → 看板 A5 卡停在 as_of 09-10（持仓只显示 1 只），
    # 用户据此提问「A5 命中这么多，模拟盘为什么只有一只」。顺序=扫描→数据桥→复盘。
    ("A5 打板实验盘扫描 paper_daban_a5[软]", [str(BASE.parent / "打板系统A5实验_20260827" / "paper_daban_a5.py")], "--skip-a5" in sys.argv),
    ("A5 看板数据 build_a5_pool[软]", ["build_a5_pool.py"], "--skip-a5" in sys.argv),
    ("A5 复盘日志 build_a5_review[软]", ["build_a5_review.py"], "--skip-a5" in sys.argv),
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
        if name.endswith("[软]"):   # 软步骤：失败只告警，不阻断（如 A5 实验盘、影子轨）
            print(f"⚠️ {name} 失败（exit {r.returncode}）—— 非致命，继续后续步骤", flush=True)
            continue
        fails.append(name)
        print(f"❌ {name} 失败（exit {r.returncode}）—— 中止后续步骤", flush=True)
        break

# ---- main 源码同步（看板产物，失败不阻断）----
if not fails:
    git = subprocess.run(["git", "add", "dual_system.html", "index.html", "short_pool.json",
                          "short_pool.js", "enhanced_data.js", "short_signals.js", "a5_pool.js",
                          "changelog.md", "changelog.html", "review_log.html",
                          "short_v3_fund_summary.json", "short_v3_fund_slip20_summary.json",
                          "backtest/satellite_pool.json",
                          "khunter_paper_state.json", "khunter_paper_state_c.json",
                          "backtest/a5_paper_state.json", "backtest/satellite_paper.json",
                          "backtest/satellite_paper_init.json", "backtest/turn_shadow_state.json",
                          "backtest/exit_shadow_state.json"],
                         cwd=str(BASE), capture_output=True)
    if git.returncode == 0:
        c = subprocess.run(["git", "commit", "-m", f"chore(daily): {date.today()} 收盘刷新（池/信号/看板/复盘日志）"],
                           cwd=str(BASE), capture_output=True)
        if c.returncode == 0:
            p = subprocess.run(["git", "push", "origin", "main"], cwd=str(BASE), capture_output=True)
            print(f"[git] main 同步 {'✓' if p.returncode == 0 else '✗ ' + p.stderr.decode(errors='replace')[:100]}", flush=True)

# ---- 双卫星模拟盘记账（非致命：按「信号日次一交易日开盘价+20bp」口径自动建仓/日更净值，无需用户回填成交）----
if not fails:
    print(f"\n========== 双卫星模拟盘记账 satellite_paper ==========", flush=True)
    r = subprocess.run([PY, "backtest/satellite_paper_0914.py"],
                       cwd=str(BASE), capture_output=True, text=True, timeout=600)
    for ln in ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-8:]:
        print(ln, flush=True)

# ---- gushi 策略股池采集（非致命：CDP 离线/未登录/依赖缺失都不阻断主链）----
def _gushi_py():
    for p in (PY, r"D:/Tools/venvs/pandadata/Scripts/python.exe"):
        try:
            if subprocess.run([p, "-c", "import websockets"], capture_output=True).returncode == 0:
                return p
        except FileNotFoundError:
            continue
    return None


if not fails:
    gp = _gushi_py()
    if gp:
        print(f"\n========== gushi 策略股池采集 collect_gushi ==========", flush=True)
        r = subprocess.run([gp, "backtest/gushi_daily_collect.py", "--days", "10"],
                           cwd=str(BASE), capture_output=True, text=True, timeout=900)
        for ln in ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-12:]:
            print(ln, flush=True)
    else:
        print("[skip] gushi 采集：无可用解释器（websockets 缺失）", flush=True)

print(f"\n{'❌ 失败: ' + ', '.join(fails) if fails else '✅ 全链完成'} · 总耗时 {time.time()-t0:.0f}s", flush=True)
sys.exit(1 if fails else 0)
