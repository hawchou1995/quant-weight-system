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

# ---- 交易日闸门（R-gate-0917 重构：数据步后置 + HS300 行自动维护）----
# 旧逻辑以「index_000300.csv 末行==今天」判交易日，但该文件仓库无写手（长期靠人工"补 HS300 指数行"，
# 见 09-16 提交说明）→ 15:30 自动链时末行必为昨天 → 恒输出 [skip] 非交易日 → 实际全靠傍晚人工
# --force 追跑（09-16 卡死进程的命令行带 --force 即证）。
# 新逻辑：① 周末直接跳过；② 工作日先跑数据步，再由链内步骤 ensure_index_row 判定——
#   今日 HS300 行情可取得 = 交易日 → 自动写入/刷新 index_000300.csv（消除人工补行 + 修正
#   review_daily 等步骤的 as-of 依赖）；不可取得（节假日/数据源未就绪）= 非交易日 →
#   该步 exit 3 → 主链打印 skip 并干净退出（数据步已完成，无副作用）。
if not FORCE and date.today().weekday() >= 5:
    _wd = "一二三四五六日"[date.today().weekday()]
    print(f"[skip] 周末（{date.today().strftime('%Y-%m-%d')} 周{_wd}）——收盘刷新无需执行", flush=True)
    sys.exit(0)

STEPS = [
    ("数据更新 update_daily", ["update_daily.py"], "--skip-data" in sys.argv),
    # 全量池守卫（R-fullpool-0917，2026-09-17 建）：降级源只补池内子集（如 440/7539）→ 全市场口径
    # 数据（涨停全景/A5 扫描）失真。本步查 data_full 新鲜度，陈旧 >100 只自动触发全量补数（约 1-2h）。
    # [软]=失败不阻断主链；--skip-fullguard 跳过。
    ("全量池守卫 fullpool_guard[软]", ["backtest/fullpool_guard.py"], "--skip-fullguard" in sys.argv),
    # 估值日更（2026-09-17 建，R-valfreeze-0917）：根因=旧管道只写 4 列快照、从不扩展 val_em 主表
    # → 主表冻结 → factorlab/oss 面板冻结 → 生产轨B 目标清单冻结（asof 谎报）。[软]=失败不阻断。
    ("估值日更 fetch_val_em_daily[软]", ["fetch_val_em_daily.py"], "--skip-val" in sys.argv),
    # HS300 指数行维护 + 交易日闸门（R-gate-0917）：exit 3 = 今日行情不可得（非交易日/未就绪）→ 主链跳过后续
    ("HS300 索引行 ensure_index_row", ["backtest/ensure_index_row.py"], False),
    # 基金净值刷新：必须在 build_short_pool 之前——否则基金信号用旧净值排序
    # 2026-09-14 补：此前刷新逻辑只在 refresh_daily.py --fund，收盘链从不调用 → 92% 的基金净值停在 08-20，
    # 占 60% 仓位的 FB3 基金主仓长期用 3 周前净值选基（且新旧净值混算）。[软]=失败不阻断主链。
    ("基金净值刷新 fund_nav_update[软]", ["fund_nav_update.py"], "--skip-fundnav" in sys.argv),
    ("短池+门控+FB3基金池 build_short_pool", ["build_short_pool.py"], False),
    ("复盘日志+跟踪池 review_daily", ["review_daily.py"], False),
    ("复盘日志页 build_log_pages", ["build_log_pages.py"], False),
    ("市值快照 fetch_val_daily", ["backtest/fetch_val_daily.py"], False),
    # 面板刷新 + 影子轨（2026-09-17 建）：必须在 build_satellite_pool 之前——轨B 与影子轨
    # 共用同一面板；重建器自带「已最新则跳过」守卫。[软]=失败不阻断（影子轨数据会停更一天）。
    ("面板刷新 rebuild_panels[软]", ["backtest/rebuild_panels.py"], "--skip-panel" in sys.argv),
    # 影子轨 shadow_ret20（用户 2026-09-17 拍板 ③纸面跟踪）：BASE / λ0.2 / λ0.3 三臂日度记录，
    # 生产 composite 不动。产出 backtest/shadow_ret20/{ledger.csv,daily_metrics.jsonl}。
    ("影子轨 shadow_ret20[软]", ["backtest/shadow_ret20.py"], "--skip-shadow" in sys.argv),
    ("双卫星池 build_satellite_pool", ["backtest/build_satellite_pool.py"], False),
    ("三轨信号 signal_satellite", ["backtest/signal_satellite_0913.py"], False),
    ("KHunter 模拟盘A khunter_paper", ["khunter_paper_20260903.py"], False),
    ("KHunter 模拟盘C khunter_paper_c", ["khunter_paper_20260903.py", "--state", "khunter_paper_state_c", "--rsi-sell", "50"], False),
    ("A5 打板模拟盘 a5_paper", ["backtest/a5_paper_0914.py"], False),
    # 黄金卫星叠加模拟盘（R-gold-sat-0917 · 2026-09-17 用户拍板投产）：轨B 内划出 10%（6800）
    # 买入 sh518880 买入持有（B&H），并把黄金腿镜像成轨B 的一个 position。**必须在 satellite_paper 之前**
    # ——satellite_paper 的 mark 循环会逐只 load_px(code) 取价 → 黄金市值自动进轨B 净值（总敞口保持 CAP_B）。
    # [软]=失败不阻断主链；--skip-gold 跳过。
    ("黄金卫星模拟盘 gold_sat_paper[软]", ["backtest/gold_sat_paper.py"], "--skip-gold" in sys.argv),
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
    # kxmm 市场情绪（恐贪指数+热力图）数据抓取——看板「市场情绪」视图数据源；[软]=失败不阻断，
    # 失败时保留上一份 kxmm_data.js（页面继续显示旧数据+日期）。R-kxmm-0917
    ("kxmm 市场情绪数据 fetch_kxmm[软]", ["backtest/fetch_kxmm.py"], "--skip-kxmm" in sys.argv),
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
    if r.returncode == 3 and name.startswith("HS300 索引行"):
        if FORCE:
            print("⚠️ 今日 HS300 行情不可得（非交易日/数据源未就绪）—— --force 继续执行", flush=True)
            continue
        print("[skip] 非交易日：今日 HS300 行情不可得（数据源无今日行情）—— 数据步已完成，跳过后续步骤",
              flush=True)
        sys.exit(0)
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
                          "backtest/gold_sat_paper.json", "backtest/gold_sat_paper.py",
                          "backtest/shadow_ret20.py", "backtest/engine_anchor.json",
                          "backtest/shadow_ret20/ledger.csv", "backtest/shadow_ret20/state.json",
                          "backtest/shadow_ret20/daily_metrics.jsonl",
                          "backtest/pct40_exits_state.json", "backtest/exit_control_state.json",
                          "backtest/pct40_exit_apply.py", "backtest/exit_control_0915.py",
                          "backtest/fetch_val_daily.py", "backtest/signal_satellite_0913.py",
                          "backtest/build_satellite_pool.py", "backtest/fetch_kxmm.py",
                          "backtest/ensure_index_row.py", "index_000300.csv",
                          "kxmm_card.py", "kxmm_data.js", "echarts.min.js", "daily_refresh.py"],
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
