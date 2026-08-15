# -*- coding: utf-8 -*-
"""短线信号每日刷新（收盘后跑一次）
============================================
流程：
1. 股票/ETF K线增量更新（新浪，已有文件秒跳，约 1-2 分钟增量）
2. 基金净值更新（可选 --fund；东财全量 19359 只很慢，默认跳过）
3. 全市场短线信号 Top 池重算（build_short_pool.py：股票反转10剔ST + ETF动量10 + 基金动量10）
4. 监控看板重建（build_dual_system.py）
5. 历史快照归档 + 月度报告（build_snapshots.py / build_monitor_reports.py）
用法：python refresh_daily.py [--fund] [--skip-fetch]
"""
import sys, os, time, subprocess
from pathlib import Path

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run(cmd, **kw):
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        print(f"⚠️ 步骤失败: {' '.join(cmd[:2])} (exit {r.returncode})", flush=True)
    return r


def main():
    t0 = time.time()
    args = sys.argv[1:]
    skip_fetch = "--skip-fetch" in args
    do_fund = "--fund" in args

    print("== 1/5 股票/ETF 行情增量更新 ==", flush=True)
    if not skip_fetch:
        run([PY, str(BASE / "fetch_full_universe.py")])
    else:
        print("  跳过（--skip-fetch）", flush=True)

    if do_fund:
        print("== 2/5 基金净值更新（全量，较慢）==", flush=True)
        # 仅更新基金池相关（fund_top_pool 前 3000 只对应短线池；全量可手动跑 v8_fund_system.py）
        import json
        try:
            pool = json.load(open(BASE / "fund_top_pool.json", encoding="utf-8"))
            codes = [x["code"] for x in pool["top"][:3000]]
        except Exception:
            codes = []
        if codes:
            import v8_fund_system as FS
            for i, c in enumerate(codes):
                FS.fetch_nav(c)
                if i % 500 == 0:
                    print(f"  基金 {i}/{len(codes)} ({time.time()-t0:.0f}s)", flush=True)
        print(f"  基金更新完成 ({time.time()-t0:.0f}s)", flush=True)
    else:
        print("  跳过（基金净值未更新，短线基金池仍用旧数据；需更新加 --fund）", flush=True)

    print("== 3/5 全市场短线信号 Top 池重算 ==", flush=True)
    run([PY, str(BASE / "build_short_pool.py")])

    print("== 4/5 监控看板重建 ==", flush=True)
    run([PY, str(BASE / "build_dual_system.py")])

    print("== 5/5 快照归档 + 月度报告 ==", flush=True)
    run([PY, str(BASE / "build_snapshots.py")])
    run([PY, str(BASE / "build_monitor_reports.py")])

    print(f"\n✅ 刷新完成，总耗时 {(time.time()-t0)/60:.1f} 分钟", flush=True)
    print("下一步：浏览器打开 dual_system.html →「⚡ 全量池短线」查看最新信号", flush=True)


if __name__ == "__main__":
    main()
