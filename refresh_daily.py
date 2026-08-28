# -*- coding: utf-8 -*-
"""短线信号每日刷新（收盘后跑一次）
============================================
流程：
1. 股票/ETF K线增量更新（新浪，已有文件秒跳，约 1-2 分钟增量）
2. 基金净值更新（可选 --fund；东财全量 19359 只很慢，默认跳过）
3. 全市场短线信号 Top 池重算（build_short_pool.py：股票反转10剔ST + ETF动量10 + 基金动量10）
4. A5 打板实验扫描 + 数据桥 + 复盘（paper_daban_a5.py 每日推进 → build_a5_pool.py → a5_pool.js；build_a5_review.py → review/review_a5.md + a5_review.json；2026-08-28 接入，扫描器 2026-08-28 补入管道）
5. 监控看板重建（build_dual_system.py，内联 A5 视图 + 复盘区块）
6. 历史快照归档 + 月度报告（build_snapshots.py / build_monitor_reports.py）
7. 当日复盘（review_daily.py 三池信号复盘 + build_log_pages.py）
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

    print("== 1/7 股票/ETF 行情增量更新（扫描滞后文件 → 拉最新合并）==", flush=True)
    if not skip_fetch:
        run([PY, str(BASE / "update_daily.py")])
    else:
        print("  跳过（--skip-fetch）", flush=True)

    if do_fund:
        print("== 2/7 基金净值更新（全量，较慢）==", flush=True)
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
                FS.fetch_nav(c, force=True)   # ⚠ force=True：不带 force 会命中缓存永不更新（2026-08-19 修复，基金净值曾停更 3 个交易日）
                if i % 500 == 0:
                    print(f"  基金 {i}/{len(codes)} ({time.time()-t0:.0f}s)", flush=True)
        print(f"  基金更新完成 ({time.time()-t0:.0f}s)", flush=True)
    else:
        print("  跳过（基金净值未更新，短线基金池仍用旧数据；需更新加 --fund）", flush=True)

    print("== 3/7 全市场短线信号 Top 池重算 ==", flush=True)
    # 2026-08-27 修复：显式传 --as-of 最新交易日（index_000300.csv 最后一行）。
    # 停牌股（无当日数据）走 calc_signals as_of 分支 `as_of not in ddf.index → continue` 自动跳过，
    # 避免 002274 华昌化工式「停牌股用旧数据评分入池」；与 calc_signals 内新鲜度校验双保险。
    _asof = None
    try:
        with open(BASE / "index_000300.csv", encoding="utf-8") as _f:
            _lines = [l for l in _f if l.strip()]
        _asof = _lines[-1].split(",")[0].strip()
    except Exception:
        _asof = None
    if _asof:
        run([PY, str(BASE / "build_short_pool.py"), "--as-of", _asof])
    else:
        run([PY, str(BASE / "build_short_pool.py")])

    print("== 4/7 A5 打板实验扫描 + 数据桥 + 复盘（paper_daban_a5 → build_a5_pool → a5_pool.js → build_a5_review）==", flush=True)
    # 2026-08-28 接入：A5_tp8t2 模拟盘第三系统。
    # ① paper_daban_a5.py：每日推进扫描（入场确认/出场结算/新观察清单），幂等（last_scan==最新交易日跳过）。
    #    ⚠ 2026-08-28 修复：此前管道只跑 build 不跑扫描，导致 last_scan 停在 08-27、打板池显示旧收盘。
    # ② build_a5_pool.py 读打板目录 paper_state.json → a5_pool.js（window.A5_POOL）；
    # ③ build_a5_review.py 读 a5_pool.js → review/review_a5.md + review/a5_review.json（独立逐笔口径）。
    # ⚠ 顺序必须在 build_dual_system.py 之前：看板 build 时内联 A5 数据与复盘区块。
    # 幂等：paper_state.json 无更新时也重跑，确保 as_of/验证统计与当日对齐。
    run([PY, r"D:/Documents/Workbuddy/股票基金/打板系统A5实验_20260827/paper_daban_a5.py"])
    run([PY, str(BASE / "build_a5_pool.py")])
    run([PY, str(BASE / "build_a5_review.py")])

    print("== 5/7 监控看板重建 ==", flush=True)
    run([PY, str(BASE / "build_dual_system.py")])

    print("== 6/7 快照归档 + 月度报告 ==", flush=True)
    run([PY, str(BASE / "build_snapshots.py")])
    run([PY, str(BASE / "build_monitor_reports.py")])

    print("== 7/7 当日复盘（信号 → T+1 结果，缺陷检测）==", flush=True)
    run([PY, str(BASE / "review_daily.py")])
    run([PY, str(BASE / "build_log_pages.py")])

    print(f"\n✅ 刷新完成，总耗时 {(time.time()-t0)/60:.1f} 分钟", flush=True)
    print("下一步：浏览器打开 dual_system.html →「⚡ 全量池短线」查看最新信号；「🎯 打板实验」查看 A5 模拟盘；「📋 复盘日志」查看当日复盘", flush=True)


if __name__ == "__main__":
    main()
