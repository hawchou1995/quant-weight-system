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
    # 基金净值刷新：必须在 build_short_pool 之前——否则基金信号用旧净值排序
    # 2026-09-14 补：此前刷新逻辑只在 refresh_daily.py --fund，收盘链从不调用 → 92% 的基金净值停在 08-20，
    # 占 60% 仓位的 FB3 基金主仓长期用 3 周前净值选基（且新旧净值混算）。[软]=失败不阻断主链。
    ("基金净值刷新 fund_nav_update[软]", ["fund_nav_update.py"], "--skip-fundnav" in sys.argv),
    ("短池+门控+FB3基金池 build_short_pool", ["build_short_pool.py"], False),
    ("复盘日志+跟踪池 review_daily", ["review_daily.py"], False),
    ("复盘日志页 build_log_pages", ["build_log_pages.py"], False),
    ("市值快照 fetch_val_daily", ["backtest/fetch_val_daily.py"], False),
    ("双卫星池 build_satellite_pool", ["backtest/build_satellite_pool.py"], False),
    ("三轨信号 signal_satellite", ["backtest/signal_satellite_0913.py"], False),
    ("KHunter 模拟盘A khunter_paper", ["khunter_paper_20260903.py"], False),
    ("KHunter 模拟盘C khunter_paper_c", ["khunter_paper_20260903.py", "--state", "khunter_paper_state_c", "--rsi-sell", "50"], False),
    ("A5 打板模拟盘 a5_paper", ["backtest/a5_paper_0914.py"], False),
    ("双卫星模拟盘 satellite_paper", ["backtest/satellite_paper_0914.py"], False),
    # 基金主仓（轨C FB3-H20）模拟盘——补齐「三轨模拟盘」最后一块（2026-09-14 用户指出缺）
    ("基金主仓模拟盘 fund_paper[软]", ["backtest/fund_paper_0914.py"], False),
    ("pct40 出场执行 pct40_exit", ["backtest/pct40_exit_apply.py"], False),
    ("pct40 对照账本 exit_control", ["backtest/exit_control_0915.py"], False),
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
# ---- 数据步专用环境：显式禁代理 ----
# 2026-09-15 根因修复：本机代理（127.0.0.1:随机端口，VPN/Clash 类）会抖动；akshare 内部
# requests **不带 timeout**（stock_zh_a_short 等），代理一挂/半死 → 复权检测整段永久阻塞
# （0914 卡 52min / 0915 卡 76min 即此）。项目对腾讯/东财本就 `proxies=None` 直连，此处把
# 数据步的进程环境也隔离掉，源头消除依赖。（git push 等步骤仍用默认环境，避免影响 GitHub 访问）
import os as _os
NO_PROXY_ENV = {**_os.environ, "HTTP_PROXY": "", "HTTPS_PROXY": "", "http_proxy": "", "https_proxy": "",
                "NO_PROXY": "*", "no_proxy": "*"}

t0 = time.time()
fails = []
for name, args, skip in STEPS:
    if skip:
        print(f"[skip] {name}", flush=True)
        continue
    print(f"\n========== {name} ==========", flush=True)
    _env = NO_PROXY_ENV if name.startswith("数据更新") else None   # 数据步禁代理（防代理抖动阻塞）
    r = subprocess.run([PY] + args, cwd=str(BASE), env=_env)
    # 2026-09-16：原生崩溃（Windows 0xC0000005 访问违规 = 3221225477 或 -1073741819）
    # 在本机被观测到在内存吃紧时**间歇**发生（build_short_pool 单独重跑即成功）。
    # 处置：回收内存 → 等 5s → 原样重试一次；仍失败才走原失败路径。
    if r.returncode in (3221225477, -1073741819):
        print(f"⚠️ {name} 原生崩溃 exit {r.returncode} —— 回收内存后重试一次", flush=True)
        import gc as _gc
        _gc.collect()
        time.sleep(5)
        r = subprocess.run([PY] + args, cwd=str(BASE), env=_env)
        print(f"   重试 {'成功 ✓' if r.returncode == 0 else f'仍失败 exit {r.returncode}'}", flush=True)
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
                          "backtest/a5_paper_state.json", "backtest/satellite_paper.json", "backtest/satellite_paper_a.json", "backtest/satellite_paper_b.json", "backtest/satellite_cfg.py",
                          "backtest/satellite_paper_init.json", "backtest/turn_shadow_state.json",
                          "backtest/pct40_exits_state.json", "backtest/exit_control_state.json",
                          "backtest/pct40_exit_apply.py", "backtest/exit_control_0915.py",
                          "backtest/fetch_val_daily.py", "backtest/signal_satellite_0913.py",
                          "backtest/build_satellite_pool.py", "daily_refresh.py"],
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
        # --renew：非 VIP 时自动续费 1 天卡（30 论坛积分）后继续采集（用户 2026-09-16 授权；护栏见脚本注释）
        r = subprocess.run([gp, "backtest/gushi_daily_collect.py", "--days", "10", "--renew"],
                           cwd=str(BASE), capture_output=True, text=True, timeout=900)
        for ln in ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-12:]:
            print(ln, flush=True)
    else:
        print("[skip] gushi 采集：无可用解释器（websockets 缺失）", flush=True)

print(f"\n{'❌ 失败: ' + ', '.join(fails) if fails else '✅ 全链完成'} · 总耗时 {time.time()-t0:.0f}s", flush=True)
sys.exit(1 if fails else 0)
