# -*- coding: utf-8 -*-
"""
v9 中/长线每日全量更新管道（2026-09-08 用户拍板：中/长线选股改为每日更新）
============================================================================
流程（Q3B 每日全量：选池 + 完整回测 + 渲染）：
1. 增量拉取全量池最新行情（fetch_full_universe.py，已有文件秒跳）
2. 删除因子缓存强制重建（含新股）
3. 完整回测：v8_selector（股票）+ v8_etf_run（ETF）
4. 全量池选股 + 跟踪池维护（build_enhanced_data.py：
   v9_rank_board 各板块 Top10 → maintain_track_v9 跟踪池
   —— 2026-09-08 新规则：新上榜次日进池；掉榜5日/score<50 清仓信号 → 21交易日剔除）
5. 渲染监控看板（build_dual_system.py → dual_system.html = index.html）
用法：python v9_daily_update.py [--skip-fetch]
"""
import sys, os, time, subprocess
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run(cmd, **kw):
    print(f">>> {' '.join(str(c) for c in cmd)}", flush=True)
    r = subprocess.run(cmd, cwd=str(BASE), **kw)
    if r.returncode != 0:
        print(f"⚠️ 步骤失败: {cmd[1] if len(cmd) > 1 else cmd[0]} (exit {r.returncode})", flush=True)
    return r


def main():
    skip_fetch = "--skip-fetch" in sys.argv
    t0 = time.time()

    # 1. 数据更新（增量；⚠ 2026-09-08 修复：原用 fetch_full_universe.py「存在即跳过」=全量建库非增量，
    #    导致存量文件永不更新、as_of 停留在旧日。改用 tickflow_update.py（批量 100 只/批 ≈ 8-10 秒，
    #    源思路来自 KHunter utils/stock_data_fetcher._fetch_stock_batch_tickflow）；
    #    TickFlow 不可用时回退 update_daily.py（新浪/腾讯逐只，慢））
    if not skip_fetch:
        print("== 1/5 数据更新（TickFlow 批量增量）==", flush=True)
        r = run([PY, str(BASE / "tickflow_update.py"), "--workers", "10"])
        if r.returncode != 0:
            print("⚠️ TickFlow 更新失败 → 回退 update_daily.py", flush=True)
            run([PY, str(BASE / "update_daily.py")])
    else:
        print("== 1/5 数据更新（跳过 --skip-fetch）==", flush=True)

    # 2. 因子缓存重建（含新股）
    cache = BASE / "v8_factor_cache.pkl"
    if cache.exists():
        cache.unlink()
        print("== 2/5 因子缓存已清除，重建中 ==", flush=True)
    else:
        print("== 2/5 因子缓存重建 ==", flush=True)

    # 3. 完整回测（股票 + ETF）
    print("== 3/5 股票回测 ==", flush=True)
    run([PY, str(BASE / "v8_selector.py"), "--top_n", "25", "--timing", "1", "--out", "v8"])
    print("== 3/5 ETF 回测 ==", flush=True)
    run([PY, str(BASE / "v8_etf_run.py")])

    # 4. 全量池选股 + 跟踪池维护（build_enhanced_data.py 模块级执行）
    print("== 4/5 全量池选股 + 跟踪池维护（v9_rank_board → maintain_track_v9）==", flush=True)
    run([PY, str(BASE / "build_enhanced_data.py")])

    # 5. 渲染监控看板
    print("== 5/5 看板渲染（dual_system.html）==", flush=True)
    run([PY, str(BASE / "build_dual_system.py")])

    print(f"\n✅ v9 每日全量更新完成，总耗时 {(time.time()-t0)/60:.1f} 分钟", flush=True)
    print("下一步：浏览器打开 dual_system.html →「🅰️ 全量池中/长线」查看最新选池与跟踪池", flush=True)


if __name__ == "__main__":
    main()
