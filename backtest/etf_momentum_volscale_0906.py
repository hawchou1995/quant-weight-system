# -*- coding: utf-8 -*-
"""
2026-09-06 组合层波动率缩放实验（核心动量不变）
============================================
基线：core 6 只 / 20日动量 / 绝对动量保护 / 前2等权 / 月末调仓 / T收盘确认→T+1开盘 / 成本0.1%
缩放层（method-策略回撤诊断与风险预算实验设计.md 第二层）：
  - 信号日 T 收盘：计算目标组合（前2等权）过去 vol_win 日实现波动率（年化 ×√252）
  - 总仓位 = clamp(目标波动率/实现波动率, 25%, 100%)，剩余现金（货基 2%）
  - T+1 开盘执行，真实换手扣成本（scale 变化本身产生换手）
  - 目标波动率 12%/15%/18% × 波动率窗口 20/60 × 成本 0.1%/0.2%

验收门（6 项）：
  1. 最大回撤绝对改善 ≥5pp（最好相对改善 ≥25%）
  2. 年化 ≥8%
  3. 夏普 ≥0.70
  4. 分年度 ≥7/10 正年
  5. 成本 0.2% 后仍不失效
  6. 2021+ 独立验证段同样改善
"""
import pandas as pd
import numpy as np
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from etf_momentum_20d_0906 import run, stats, load_etf, CORE, CASH_ANN, IDX_CSV

# 2026-09-28（R-etf-chain-0928）：BASE 从文件位置解析 + 旧路径兜底（云端可移植；本机恒等）
_HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(_HERE)
_LEGACY = r"D:\Documents\Workbuddy\股票基金\quant-weight-system"
if not os.path.isdir(os.path.join(BASE, "data_full")) and os.path.isdir(os.path.join(_LEGACY, "data_full")):
    BASE = _LEGACY
OUT = os.path.join(BASE, "backtest", "etf_rotation_out")
os.makedirs(OUT, exist_ok=True)


def run_volscale(pool, lookback, month_end, w1, cost, target_vol, vol_win):
    """基线 run() + 组合层波动率缩放。返回 (nav, trades, scales)"""
    prices = {c: load_etf(c) for c in pool}
    prices = {c: d for c, d in prices.items() if d is not None and len(d) > lookback + 5}
    if len(prices) < 2:
        return None, None, None
    all_idx = None
    for c, d in prices.items():
        all_idx = d.index if all_idx is None else all_idx.intersection(d.index)
    all_idx = all_idx.sort_values()
    month = all_idx.to_period("M")
    groups = {}
    for dt, m in zip(all_idx, month):
        groups.setdefault(m, []).append(dt)
    rebal_days = []
    for m, days in groups.items():
        rebal_days.append(days[-1] if month_end else days[0])
    rebal_days = pd.DatetimeIndex(sorted(set(rebal_days)))

    nav_dates = all_idx
    nav = pd.Series(1.0, index=nav_dates)
    cash_daily = (1 + CASH_ANN) ** (1 / 252) - 1
    cash_halfday = (1 + CASH_ANN) ** (1 / (2 * 252)) - 1

    positions = {}
    exec_events = {}
    trades = []
    scales = []  # (sig_dt, scale)
    for sig_dt in rebal_days:
        moms = {}
        for c, d in prices.items():
            if sig_dt not in d.index:
                continue
            pos = d.index.get_loc(sig_dt)
            if pos < lookback:
                continue
            moms[c] = d["close"].iloc[pos] / d["close"].iloc[pos - lookback] - 1
        if len(moms) < 2:
            continue
        ranked = sorted(moms.items(), key=lambda x: -x[1])
        top1 = ranked[0][1]
        if top1 < 0:
            new_pos = {}
            scale = 0.0
        else:
            top2 = [ranked[0][0], ranked[1][0]]
            # 目标组合（前2等权）实现波动率：过去 vol_win 日，年化 ×√252
            rets = None
            for c in top2:
                d = prices[c]
                pos = d.index.get_loc(sig_dt)
                lo = max(0, pos - vol_win)
                closes = d["close"].iloc[lo:pos + 1]
                r = closes.pct_change().dropna() * 0.5
                rets = r if rets is None else rets + r  # 自动按索引对齐
            if rets is not None and len(rets.dropna()) >= 5:
                rv = rets.std(ddof=1) * np.sqrt(252)
                scale = min(1.0, max(0.25, target_vol / rv)) if rv > 0 else 1.0
            else:
                scale = 1.0
            new_pos = {c: scale * (w1 if i == 0 else 1 - w1) for i, c in enumerate(top2)}
        scales.append((sig_dt, scale))
        sig_i = nav_dates.get_loc(sig_dt)
        if sig_i + 1 >= len(nav_dates):
            break
        exec_dt = nav_dates[sig_i + 1]
        old_pos = positions.copy()
        chg = set(old_pos) | set(new_pos)
        turnover = sum(abs(new_pos.get(c, 0.0) - old_pos.get(c, 0.0)) for c in chg)
        exec_events[exec_dt] = (old_pos, new_pos.copy(), sig_dt)
        if turnover > 1e-12:
            trades.append({"signal": sig_dt, "exec": exec_dt,
                           "from": old_pos, "to": new_pos.copy(),
                           "turnover": turnover})
        positions = new_pos

    # 逐日净值（与基线同构：执行日两段式，旧仓承担隔夜、新仓承担开盘→收盘）
    current_weights = {}
    for i, dt in enumerate(nav_dates):
        if i == 0:
            nav.iloc[i] = 1.0
            continue
        prev_dt = nav_dates[i - 1]
        event = exec_events.get(dt)
        day_ret = 0.0
        if event is not None:
            old_weights, new_weights, _sig_dt = event
            old_total = sum(old_weights.values())
            new_total = sum(new_weights.values())
            old_cash = max(0.0, 1.0 - old_total)
            new_cash = max(0.0, 1.0 - new_total)
            day_ret += old_cash * cash_halfday
            for c, w in old_weights.items():
                d = prices.get(c)
                if d is None or prev_dt not in d.index or dt not in d.index:
                    continue
                day_ret += w * (d.loc[dt, "open"] / d.loc[prev_dt, "close"] - 1)
            day_ret += new_cash * cash_halfday
            for c, w in new_weights.items():
                d = prices.get(c)
                if d is None or dt not in d.index:
                    continue
                day_ret += w * (d.loc[dt, "close"] / d.loc[dt, "open"] - 1)
            turnover = sum(abs(new_weights.get(c, 0.0) - old_weights.get(c, 0.0))
                           for c in set(old_weights) | set(new_weights))
            day_ret -= cost * turnover
            current_weights = new_weights
        elif len(current_weights) == 0:
            day_ret = cash_daily
        else:
            total_w = 0.0
            for c, w in current_weights.items():
                d = prices.get(c)
                if d is None or prev_dt not in d.index or dt not in d.index:
                    continue
                day_ret += w * (d.loc[dt, "close"] / d.loc[prev_dt, "close"] - 1)
                total_w += w
            if total_w < 1.0:
                day_ret += (1.0 - total_w) * cash_daily
        prev_val = nav.iloc[nav.index.get_loc(dt) - 1] if nav.index.get_loc(dt) > 0 else 1.0
        nav.iloc[nav.index.get_loc(dt)] = prev_val * (1 + day_ret)
    return nav, trades, scales


def seg_stats(nav, start="2021-01-01"):
    """独立验证段（2021+）统计"""
    s = nav[nav.index >= start]
    if len(s) < 60:
        return None
    rets = s.pct_change().dropna()
    total = s.iloc[-1] / s.iloc[0] - 1
    years = len(s) / 252
    annual = (1 + total) ** (1 / years) - 1
    dd = (s / s.cummax() - 1).min()
    sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
    mret = s.resample("ME").last().pct_change().dropna()
    wr = (mret > 0).mean() * 100
    return {"annual": annual * 100, "max_dd": dd * 100, "sharpe": sharpe, "wr": wr}


def main():
    bench = pd.read_csv(IDX_CSV)
    bench["date"] = pd.to_datetime(bench["date"])
    bench = bench.sort_values("date").set_index("date")["close"]
    bench = bench / bench.iloc[0] * 100

    # 基线复现校验
    nav0, trades0 = run(CORE, 20, True, 0.5, 0.001)
    s0 = stats(nav0, trades0, "core", 20, True, 0.5, 0.001, bench)
    print("=== 基线复现校验（应吻合 total 1.3544 / annual 10.35 / dd -28.78 / sharpe 0.605 / wr 56.88 / n_trades 87）===")
    print(f"  total={s0['total']} annual={s0['annual']} max_dd={s0['max_dd']} sharpe={s0['sharpe']} "
          f"wr={s0['wr']} med={s0['med']} mean={s0['mean']} excess={s0['excess_ann']} n_trades={s0['n_trades']}")
    seg0 = seg_stats(nav0)
    print(f"  2021+ 段: annual={seg0['annual']:.2f} max_dd={seg0['max_dd']:.2f} sharpe={seg0['sharpe']:.3f} wr={seg0['wr']:.1f}")

    rows = []
    for tv in (0.12, 0.15, 0.18):
        for vw in (20, 60):
            for cost in (0.001, 0.002):
                nav, trades, scales = run_volscale(CORE, 20, True, 0.5, cost, tv, vw)
                if nav is None:
                    continue
                s = stats(nav, trades, f"core_vs{tv:.2f}_w{vw}", 20, True, 0.5, cost, bench)
                seg = seg_stats(nav)
                avg_scale = float(np.mean([sc for _, sc in scales])) if scales else 1.0
                pos_years = sum(1 for v in s["yearly"].values() if v > 0)
                dd_imp = s["max_dd"] - s0["max_dd"]  # 正=改善（回撤变浅）
                rel_imp = dd_imp / abs(s0["max_dd"]) * 100
                rows.append({
                    "target_vol": tv, "vol_win": vw, "cost": cost,
                    "n_trades": s["n_trades"], "avg_scale": round(avg_scale, 3),
                    "total": s["total"], "annual": s["annual"], "max_dd": s["max_dd"],
                    "sharpe": s["sharpe"], "wr": s["wr"], "med": s["med"], "mean": s["mean"],
                    "excess_ann": s["excess_ann"], "pos_years": pos_years,
                    "dd_imp_pp": round(dd_imp, 2), "dd_imp_rel_pct": round(rel_imp, 1),
                    "seg_annual": seg["annual"] if seg else None,
                    "seg_max_dd": seg["max_dd"] if seg else None,
                    "seg_sharpe": seg["sharpe"] if seg else None,
                    "seg_wr": seg["wr"] if seg else None,
                })
                print(f"  vs={tv:.2f} w={vw} cost={cost} -> total={s['total']:.4f} annual={s['annual']:.2f} "
                      f"dd={s['max_dd']:.2f} sharpe={s['sharpe']:.3f} wr={s['wr']:.1f} pos_years={pos_years} "
                      f"dd_imp={dd_imp:+.2f}pp({rel_imp:+.1f}%) avg_scale={avg_scale:.3f}", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(OUT, "etf_momentum_volscale_0906.csv"), index=False)

    # 验收门评估（对 0.1% 成本主配置）
    print("\n=== 验收门评估（成本 0.1%，vs 基线 dd=-28.78 / annual=10.35 / sharpe=0.605 / 6/10 正年）===")
    print("门1: 回撤绝对改善≥5pp | 门1b: 相对改善≥25% | 门2: 年化≥8% | 门3: 夏普≥0.70 | 门4: 正年≥7/10 | 门6: 2021+段同样改善")
    for tv in (0.12, 0.15, 0.18):
        for vw in (20, 60):
            r = out[(out.target_vol == tv) & (out.vol_win == vw) & (out.cost == 0.001)].iloc[0]
            g1 = r["dd_imp_pp"] >= 5.0
            g1b = r["dd_imp_rel_pct"] >= 25.0
            g2 = r["annual"] >= 8.0
            g3 = r["sharpe"] >= 0.70
            g4 = r["pos_years"] >= 7
            g6 = (r["seg_max_dd"] is not None and seg0 is not None
                  and r["seg_max_dd"] > seg0["max_dd"] and r["seg_annual"] >= seg0["annual"] * 0.9)
            print(f"  vs={tv:.2f} w={vw}: 门1={'PASS' if g1 else 'FAIL'}({r['dd_imp_pp']:+.1f}pp) "
                  f"门1b={'PASS' if g1b else 'FAIL'}({r['dd_imp_rel_pct']:+.1f}%) "
                  f"门2={'PASS' if g2 else 'FAIL'}({r['annual']:.2f}%) "
                  f"门3={'PASS' if g3 else 'FAIL'}({r['sharpe']:.3f}) "
                  f"门4={'PASS' if g4 else 'FAIL'}({r['pos_years']}/10) "
                  f"门6={'PASS' if g6 else 'FAIL'}(seg_dd={r['seg_max_dd']:.1f} vs {seg0['max_dd']:.1f}, seg_ann={r['seg_annual']:.1f} vs {seg0['annual']:.1f})")

    # 成本 0.2% 敏感性（门5）
    print("\n=== 门5: 成本 0.2% 后是否仍不失效（对比同配置 0.1%）===")
    for tv in (0.12, 0.15, 0.18):
        for vw in (20, 60):
            r1 = out[(out.target_vol == tv) & (out.vol_win == vw) & (out.cost == 0.001)].iloc[0]
            r2 = out[(out.target_vol == tv) & (out.vol_win == vw) & (out.cost == 0.002)].iloc[0]
            print(f"  vs={tv:.2f} w={vw}: 0.1%->annual={r1['annual']:.2f} dd={r1['max_dd']:.2f} sharpe={r1['sharpe']:.3f} | "
                  f"0.2%->annual={r2['annual']:.2f} dd={r2['max_dd']:.2f} sharpe={r2['sharpe']:.3f} "
                  f"| 年化损失={r1['annual'] - r2['annual']:.2f}pp")

    # 最佳配置分年度
    print("\n=== 分年度（基线 vs 各目标波动率 w=20 主配置）===")
    print("  基线: " + " ".join(f"{y}:{v:+.1f}" for y, v in sorted(s0["yearly"].items())))
    for tv in (0.12, 0.15, 0.18):
        nav, trades, _ = run_volscale(CORE, 20, True, 0.5, 0.001, tv, 20)
        s = stats(nav, trades, f"vs{tv}", 20, True, 0.5, 0.001, bench)
        print(f"  vs={tv:.2f}: " + " ".join(f"{y}:{v:+.1f}" for y, v in sorted(s["yearly"].items())))

    print("\n完成 -> etf_momentum_volscale_0906.csv")


if __name__ == "__main__":
    main()
