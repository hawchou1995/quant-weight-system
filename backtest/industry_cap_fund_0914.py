# -*- coding: utf-8 -*-
"""轨C（FB3-H20 基金主仓）行业集中度约束实验 —— 预注册口径
=================================================================
预注册（2026-09-14 grill 拍板）：
  Q1 三轨都测（本脚本=轨C）；Q2 只对 25 个行业类标签生效，宽类/风格类（均衡配置/指数/债券/货币/海外/港股…）
  豁免、未分类不合并计数；Q3 扫 N∈{1,2,3}，主判据=全相位中位夏普 + 50bp 档不劣化，辅助=分年度；
  Q4 池=2000（生产口径）；Q5 先去重后约束（本脚本沿用生产去重后的候选排序）；Q6 先出数据再拍板。
对照：N=0（无约束，即现行 FB3-H20 生产口径）
相位：hold=20 → offsets 0/4/8/12/16（5 相位，ADR-0006）
滑点：主档 5bp；稳健档 20/50bp
产物：backtest/industry_cap_fund_0914.json
用法：python backtest/industry_cap_fund_0914.py
"""
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import numpy as np
import short_engine as S
import industry_pool as IP
import v8_selector as V   # 与 finalize_short_v3.py 同源：summary(eq, tr)

STATE = BASE / "backtest" / "industry_cap_fund_0914.json"

# ---- 生产口径（finalize_short_v3.py 第 36-45 行，勿改）----
FUND_BULL = dict(top_n=10, hold_days=20, score_min=30, reversal=False, min_amt=0,
                 weights=(40, 0, 30, 30), mask=(1, 1, 1, 1))
FUND_BEAR = dict(top_n=3, hold_days=20, score_min=45, reversal=False, min_amt=0,
                 weights=(25, 0, 30, 45), mask=(1, 1, 1, 1))

# 只对这 25 个「行业类」标签生效；宽类/风格类豁免（Q2 拍板）
INDUSTRY_LABELS = {
    "医药生物", "电子", "通信", "计算机", "电力设备", "环保", "国防军工", "机械设备", "汽车",
    "基础化工", "有色金属", "煤炭", "石油石化", "食品饮料", "农林牧渔", "家用电器",
    "银行", "非银金融", "房地产", "建筑装饰", "公用事业", "传媒", "交通运输", "社会服务", "商贸零售",
}


def build_industry_of():
    from build_short_pool import fund_names
    fn = fund_names()
    cache = {}

    def ind_of(code):
        c6 = code[-6:]
        if c6 in cache:
            return cache[c6]
        lab = IP.fund_industry(fn.get(c6, ""))
        out = lab if lab in INDUSTRY_LABELS else None   # 宽类/风格/未分类 → None（不参与约束）
        cache[c6] = out
        return out
    return ind_of, fn


def main():
    t0 = time.time()
    pool = S.load_fund_pool(2000)
    ind_of, fn = build_industry_of()
    print(f"[setup] 池 {len(pool)} 只 | 行业映射就绪（{time.time()-t0:.0f}s）", flush=True)

    # 覆盖度自检：候选里有多少能拿到行业标签（只统计会被约束的那部分）
    sample = list(pool)[:400]
    labeled = sum(1 for c in sample if ind_of(c))
    print(f"[check] 抽样 400 只中 {labeled} 只（{labeled/4:.0f}%）拿到行业类标签（其余为宽类/风格，豁免）", flush=True)

    def run(N, slip, off):
        eq, tr = S.run_short_regime(pool, bull_cfg=dict(FUND_BULL), bear_cfg=dict(FUND_BEAR),
                                    allow_bear_buy=True, fund_mode=True, slippage_bps=slip,
                                    max_per_industry=N, industry_of=ind_of, offset=off)
        s = V.summary(eq, tr)
        return s

    out = {"prereg": {
        "track": "C · FB3-H20 基金主仓", "pool": 2000, "slip_main": 5, "phases": [0, 4, 8, 12, 16],
        "N_grid": [0, 1, 2, 3], "industry_whitelist_count": len(INDUSTRY_LABELS),
        "note": "N=0 为对照（现行生产口径）；先去重后约束；宽类/风格类豁免约束",
    }, "runs": {}}

    # 1) 主档 slip5 相位扫描
    for N in (0, 1, 2, 3):
        rows = []
        for off in (0, 4, 8, 12, 16):
            t1 = time.time()
            s = run(N, 5, off)
            rows.append({"offset": off, "total": s["total_return_pct"], "sharpe": s["sharpe"],
                         "mdd": s["max_drawdown_pct"], "trades": s["total_trades"],
                         "win": s.get("win_rate_pct"), "annual": s.get("annual_return_pct")})
            print(f"  N={N} off={off:<3} {s['total_return_pct']:>9.1f}%  夏普 {s['sharpe']:.3f}  "
                  f"回撤 {s['max_drawdown_pct']:.1f}%  笔数 {s['total_trades']}  ({time.time()-t1:.0f}s)", flush=True)
        sh = [r["sharpe"] for r in rows]
        tt = [r["total"] for r in rows]
        out["runs"][f"N{N}_slip5"] = {"phases": rows, "sharpe_med": float(np.median(sh)),
                                      "total_med": float(np.median(tt)), "sharpe_min": float(min(sh)),
                                      "sharpe_max": float(max(sh))}
        print(f"  → N={N} 相位中位：收益 {np.median(tt):.1f}% / 夏普 {np.median(sh):.3f} "
              f"[{min(sh):.3f}, {max(sh):.3f}]", flush=True)

    # 2) 稳健档 slip20 / slip50（offset=0）
    for N in (0, 1, 2, 3):
        for slip in (20, 50):
            s = run(N, slip, 0)
            out["runs"].setdefault(f"N{N}_slip{slip}", {})["off0"] = {
                "total": s["total_return_pct"], "sharpe": s["sharpe"], "mdd": s["max_drawdown_pct"]}
            print(f"  N={N} slip{slip}bps off0: 收益 {s['total_return_pct']:.1f}% 夏普 {s['sharpe']:.3f}", flush=True)

    STATE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[done] {time.time()-t0:.0f}s → {STATE.name}")

    # 3) 判定表
    print("\n===== 判定（主判据：相位中位夏普 ≥ 对照 且 slip50 不劣化）=====")
    base = out["runs"]["N0_slip5"]
    for N in (1, 2, 3):
        r = out["runs"][f"N{N}_slip5"]
        s50 = out["runs"][f"N{N}_slip50"]["off0"]["sharpe"]
        b50 = out["runs"]["N0_slip50"]["off0"]["sharpe"]
        verdict = "优于对照" if r["sharpe_med"] > base["sharpe_med"] else "不优于对照"
        print(f"  N={N}: 相位中位夏普 {r['sharpe_med']:.3f} vs 对照 {base['sharpe_med']:.3f} → {verdict}"
              f" | slip50 夏普 {s50:.3f} vs {b50:.3f}"
              f" | 相位最小 {r['sharpe_min']:.3f}")


if __name__ == "__main__":
    main()
