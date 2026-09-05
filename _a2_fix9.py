# -*- coding: utf-8 -*-
"""A2 定向修复：对 9 只已知 qfq 基准漂移股，用 run_rebase_check 完全相同的代码路径
（F.fetch_sina_daily 规范化源 + F.save_csv 全量覆盖）重拉 qfq 覆盖，消除基准漂移。
单独对 9 只定向执行（而非 400 候选全扫），避免突发请求触发新浪限流导致整批 verify 静默失败。
"""
import sys, time
sys.path.insert(0, r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
import fetch_full_universe as F
import update_daily as U

DRIFT = ['sh600351','sh600817','sh603259','sh688036',
         'sz002997','sz300012','sz300017','sz300406','sz300896']

fixed = 0
for sym in DRIFT:
    try:
        if U.verify_rebase_drift(sym, F.fetch_sina_daily):
            full = F.fetch_sina_daily(sym)   # 全量 qfq（2016 起，新浪口径）
            if full is not None and len(full) > 0:
                F.save_csv(sym, full, "")
                fixed += 1
                print(f"  [修复] {sym} 基准漂移 → 已全量重拉 qfq 覆盖 ({len(full)} 行)", flush=True)
            else:
                print(f"  [跳过] {sym} 新浪返回空", flush=True)
        else:
            print(f"  [无漂移] {sym} verify=False（已对齐或抓取失败）", flush=True)
    except Exception as e:
        print(f"  [异常] {sym}: {str(e)[:60]}", flush=True)
    time.sleep(3)   # 节奏：避免突发请求触发新浪限流
print(f"A2_FIXED_COUNT: {fixed}")
