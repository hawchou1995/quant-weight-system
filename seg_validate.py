# -*- coding: utf-8 -*-
"""分段稳定性验证（过拟合防线，v5.11.11 起每次参数优化必跑）
============================================
两段复测：2016-2021 / 2022-2026（monkey-patch START/END，注意 S 与 V 都要 patch）
用法：python seg_validate.py
输出：控制台表格（收益/回撤/夏普/胜率/笔数），两段均正且夏普>1 为通过
"""
import sys, time
from pathlib import Path

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
sys.path.insert(0, str(BASE))
import short_engine as S
import v9_auto as A
import v8_lite as L
import v8_selector as V

SEGS = [("2016-2021", "2016-01-04", "2021-12-31"), ("2022-2026", "2022-01-01", "2026-08-14")]


def seg_run(label, fn, *args, **kw):
    """fn 需在内部使用模块级 START/END（S.START / A 用 V.START）"""
    out = []
    for name, st, en in SEGS:
        S.START, S.END = st, en        # short_engine（导入时复制值）
        V.START, V.END = st, en        # v8_selector / v9_auto 动态读取
        eq, tr = fn(*args, **kw)
        s = V.summary(eq, tr)
        out.append((name, s))
        print(f"  [{label}] {name}: 收益 {s['total_return_pct']:>7.1f}% | 回撤 {s['max_drawdown_pct']:>6.2f}% | "
              f"夏普 {s['sharpe']:.3f} | 胜率 {s['win_rate_pct']:.1f}% | {s['total_trades']} 笔", flush=True)
    ok = all(s["sharpe"] > 1.0 and s["total_return_pct"] > 0 for _, s in out)
    print(f"  → {'✅ 分段通过' if ok else '❌ 分段不通过（过拟合风险）'}\n", flush=True)
    return ok


if __name__ == "__main__":
    t0 = time.time()
    all_ok = True
    sp = S.load_stock_pool()
    print("=== 短线股票 T10/H10/S55 反转+MA5 slip20 ===", flush=True)
    all_ok &= seg_run("短线", S.run_short, sp, top_n=10, hold_days=10, score_min=55,
                      reversal=True, ma5_exit=True, slippage_bps=20)
    print("=== v9 全量池 T3/MA150 slip20 ===", flush=True)
    all_ok &= seg_run("v9", A.run_auto, top_n=3, mom_min=0.25, score_min=65, stop_loss=0.055,
                      dynamic=True, rsi_max=85, ma_window=150, slippage_bps=20)
    lite_pool = L.build_pool(verbose=False)
    print("=== v8 固定池 T4/H42/MA200 slip20 ===", flush=True)
    all_ok &= seg_run("v8", L.run_lite, lite_pool, top_n=4, hold_days=42, use_timing=True,
                      stop_loss=0.10, slippage_bps=20)
    print(f"\n{'✅ 全部策略分段验证通过' if all_ok else '❌ 存在不通过项'}（{time.time()-t0:.0f}s）")
