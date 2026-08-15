# -*- coding: utf-8 -*-
"""
v8 月度看板更新脚本（供自动化任务调用）
==========================================
流程：
1. 增量拉取全量池最新行情（新浪，只拉最近 30 日缺口）
2. 重建因子缓存 v8_factor_cache.pkl
3. 重跑股票/ETF 回测三件套
4. 重渲染 index.html 三 tab 看板
用法：python v8_daily_update.py [--skip-fetch]
"""
import sys, os, time, json, csv, subprocess
from pathlib import Path
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
FETCH_SCRIPT = BASE / "fetch_full_universe.py"  # 断点续跑，已有文件跳过


def run(cmd, **kw):
    print(f">>> {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, cwd=str(BASE), **kw)


def main():
    skip_fetch = "--skip-fetch" in sys.argv
    t0 = time.time()

    # 1. 数据更新（akshare 新浪，增量；约 40-60 分钟全量，已有文件秒跳）
    if not skip_fetch:
        print("== 1/4 数据更新 ==", flush=True)
        r = run([sys.executable, str(FETCH_SCRIPT)])
        if r.returncode != 0:
            print("数据更新失败，继续用旧数据", flush=True)

    # 2. 删除因子缓存强制重建（含新股）
    cache = BASE / "v8_factor_cache.pkl"
    if cache.exists():
        cache.unlink()
        print("== 2/4 因子缓存已清除，重建中 ==", flush=True)
    else:
        print("== 2/4 因子缓存重建 ==", flush=True)

    # 3. 重跑股票 + ETF 回测
    print("== 3/4 股票回测 ==", flush=True)
    run([sys.executable, str(BASE / "v8_selector.py"), "--top_n", "25", "--timing", "1", "--out", "v8"])
    print("== 3/4 ETF 回测 ==", flush=True)
    run([sys.executable, str(BASE / "v8_etf_run.py")])

    # 4. 重渲染看板
    print("== 4/4 看板渲染 ==", flush=True)
    run([sys.executable, str(BASE / "v8_triple_dashboard.py")])

    print(f"\n完成，总耗时 {(time.time()-t0)/60:.1f} 分钟", flush=True)


if __name__ == "__main__":
    main()
