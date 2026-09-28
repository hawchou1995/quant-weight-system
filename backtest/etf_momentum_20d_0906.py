# -*- coding: utf-8 -*-
"""
2026-09-06 公众号《ETF动量轮动策略》量化回测
==========================================
文章策略（mp.weixin.qq.com/s/8Ur-AShMc5cxGU6444-yow）：
1. 候选 ETF 池；2. 每只算过去 20 日收益率排序；3. 绝对动量保护：排名第一 20 日涨幅<0 → 全部空仓(货基/现金)；4. 最强>0 → 买入前 2，其余清仓；5. 每月底重复。

口径：
- 月调仓（月末最后交易日 或 月初首交易日 对比），T 收盘确认 → T+1 开盘成交
- 20 日动量 = close_T / close_{T-20} - 1（T 收盘生成，下一交易日执行，不使用 T+1 数据）
- 空仓期收益 = 货币基金年化 2%（日 0.02/252）
- 成本：主口径 0.1% 单边（ETF 免印花税）；敏感性 0.2%
- 前 2 等权（敏感性 60/40）
- 池：core=既有 6 只（300/500/50/创业板/黄金/国债）；ext=core+行业 8 只（半导体/证券/军工/酒/医药/银行/医疗/光伏）
- lookback 敏感性：10/20/40/60 日
- 判定（用户拍板 9/6）：胜率≥40% + 中位>0 + 均值>0 + 超额>0（vs 沪深300）；分年度 ≥7/9 正
- 对比锚点：沪深300（4.57%/年）+ 9/3 既有最佳（top1 12m 19.3%/0.915；双动量 9m 12.1%/0.734）
"""
import pandas as pd
import numpy as np
import os, json, itertools

# 2026-09-28（R-etf-chain-0928 · 用户批准「ETF 全族接入云端链」）：
#   BASE 由硬编码 Windows 路径改为**从文件位置解析**（本文件位于 backtest/ → 仓库根 = 上一级），
#   并保留旧路径兜底 → 本机解析恒等、云端（Linux runner）可移植。
_HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(_HERE)
_LEGACY = r"D:\Documents\Workbuddy\股票基金\quant-weight-system"
if not os.path.isdir(os.path.join(BASE, "data_full")) and os.path.isdir(os.path.join(_LEGACY, "data_full")):
    BASE = _LEGACY
DATA = os.path.join(BASE, "data_full")
OUT = os.path.join(BASE, "backtest", "etf_rotation_out")
os.makedirs(OUT, exist_ok=True)
IDX_CSV = os.path.join(BASE, "index_000300.csv")

CORE = {
    "sh510300": "沪深300ETF", "sh510500": "中证500ETF", "sh510050": "上证50ETF",
    "sz159915": "创业板ETF", "sh518880": "黄金ETF", "sh511260": "国债ETF",
}
IND = {
    "sh512480": "半导体ETF", "sh512880": "证券ETF", "sh512660": "军工ETF",
    "sh512690": "酒ETF", "sh512010": "医药ETF", "sh512800": "银行ETF",
    "sh512170": "医疗ETF", "sh515790": "光伏ETF",
}
CASH_ANN = 0.02  # 空仓期货基年化


def load_etf(code):
    f = os.path.join(DATA, code + ".csv")
    if not os.path.exists(f):
        return None
    df = pd.read_csv(f, usecols=["date", "open", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    return df


def run(pool, lookback, month_end, w1, cost):
    """回测一轮：返回 (nav_series, trades_log)"""
    prices = {c: load_etf(c) for c in pool}
    prices = {c: d for c, d in prices.items() if d is not None and len(d) > lookback + 5}
    if len(prices) < 2:
        return None, None
    # 统一日历（所有标的共同交易日，用于确定调仓日）
    all_idx = None
    for c, d in prices.items():
        all_idx = d.index if all_idx is None else all_idx.intersection(d.index)
    all_idx = all_idx.sort_values()
    # 标的的完整数据仍用各自序列（上市后即可被选：用标的自己的日历算动量）
    # 调仓日：每月末最后交易日 / 月初首交易日（基于共同日历）
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

    # 先生成“收盘确认 -> 下一交易日开盘执行”的事件表。
    # 旧实现虽然记录了 exec_dt，但净值循环实际在 sig_dt 就切换仓位，
    # 会把信号日开盘至收盘的收益错误归给新仓位。
    positions = {}  # code -> 目标权重（执行前的当前仓位）
    exec_events = {}  # exec_dt -> (old_weights, new_weights, sig_dt)
    trades = []
    for sig_dt in rebal_days:
        # 计算信号日收盘可观测的历史动量；执行发生在下一交易日开盘。
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
        # 绝对动量保护：第一名<0 → 空仓
        if top1 < 0:
            new_pos = {}
        else:
            top2 = [ranked[0][0], ranked[1][0]]
            new_pos = {c: (w1 if i == 0 else 1 - w1) for i, c in enumerate(top2)}
        # T+1 开盘成交
        sig_i = nav_dates.get_loc(sig_dt)
        if sig_i + 1 >= len(nav_dates):
            break
        exec_dt = nav_dates[sig_i + 1]
        old_pos = positions.copy()
        chg = set(old_pos) | set(new_pos)
        turnover = sum(abs(new_pos.get(c, 0.0) - old_pos.get(c, 0.0)) for c in chg)
        exec_events[exec_dt] = (old_pos, new_pos.copy(), sig_dt)
        # 仅将真实发生权重变化的执行日记为 trade；信号不变不产生费用。
        if turnover > 1e-12:
            trades.append({"signal": sig_dt, "exec": exec_dt,
                           "from": old_pos, "to": new_pos.copy(),
                           "turnover": turnover})
        positions = new_pos

    # 逐日净值
    current_weights = {}
    for i, dt in enumerate(nav_dates):
        if i == 0:
            nav.iloc[i] = 1.0
            continue

        prev_dt = nav_dates[i - 1]
        event = exec_events.get(dt)
        day_ret = 0.0

        if event is not None:
            # 执行日分两段：旧仓位承担前收至开盘的隔夜跳空，新仓位承担开盘至收盘。
            # 这样不会把隔夜收益错误归给已经在收盘后才决定的新仓位。
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
            # cost 为单边费率；turnover 同时计入卖出和买入两条腿。
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
    return nav, trades


def stats(nav, trades, pool_name, lb, month_end, w1, cost, bench):
    if nav is None or len(nav) < 60:
        return None
    rets = nav.pct_change().dropna()
    total = nav.iloc[-1] / nav.iloc[0] - 1
    years = len(nav) / 252
    annual = (1 + total) ** (1 / years) - 1
    dd = (nav / nav.cummax() - 1).min()
    sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
    # 月频收益 → 胜率/中位/均值
    mret = nav.resample("ME").last().pct_change().dropna()
    wr = (mret > 0).mean() * 100
    med = mret.median() * 100
    mean = mret.mean() * 100
    # 超额 vs 沪深300（同区间）
    b = bench.reindex(nav.index).ffill()
    ex_ann = annual - ((b.iloc[-1] / b.iloc[0]) ** (1 / years) - 1)
    # 分年度
    yr = {}
    for y, g in nav.resample("YE"):
        if len(g) < 20 or y.year == nav.index[0].year and len(g) < 40:
            continue
        yr[y.year] = (g.iloc[-1] / g.iloc[0] - 1) * 100
    cash_ratio = (nav.diff() == 0).sum() / len(nav)  # 近似（货基日收益极低≠0，用持仓零时不适用）
    n_trades = len(trades)
    return {
        "pool": pool_name, "lookback": lb, "month_end": month_end, "w1": w1, "cost": cost,
        "n_months": len(mret), "n_trades": n_trades,
        "total": round(total, 4), "annual": round(annual * 100, 2), "max_dd": round(dd * 100, 2),
        "sharpe": round(sharpe, 3), "wr": round(wr, 2), "med": round(med, 3), "mean": round(mean, 3),
        "excess_ann": round(ex_ann * 100, 2), "yearly": yr,
    }


def main():
    bench = pd.read_csv(IDX_CSV)
    bench["date"] = pd.to_datetime(bench["date"])
    bench = bench.sort_values("date").set_index("date")["close"]
    bench = bench / bench.iloc[0] * 100

    results = []
    configs = []
    # 主口径：core、20日、月末、等权、0.1%
    main_cfg = dict(pool=CORE, pool_name="core", lb=20, month_end=True, w1=0.5, cost=0.001)
    configs.append(main_cfg)
    # 敏感性
    for lb in (10, 40, 60):
        configs.append(dict(pool=CORE, pool_name="core", lb=lb, month_end=True, w1=0.5, cost=0.001))
    for me in (False,):
        configs.append(dict(pool=CORE, pool_name="core", lb=20, month_end=me, w1=0.5, cost=0.001))
    for w1 in (0.6,):
        configs.append(dict(pool=CORE, pool_name="core", lb=20, month_end=True, w1=w1, cost=0.001))
    for cost in (0.002,):
        configs.append(dict(pool=CORE, pool_name="core", lb=20, month_end=True, w1=0.5, cost=cost))
    # 扩展池
    EXT = {**CORE, **IND}
    for lb in (10, 20, 40, 60):
        configs.append(dict(pool=EXT, pool_name="ext", lb=lb, month_end=True, w1=0.5, cost=0.001))

    for cfg in configs:
        nav, trades = run(cfg["pool"], cfg["lb"], cfg["month_end"], cfg["w1"], cfg["cost"])
        s = stats(nav, trades, cfg["pool_name"], cfg["lb"], cfg["month_end"], cfg["w1"], cfg["cost"], bench)
        if s:
            results.append(s)
        print(f"{cfg['pool_name']} lb={cfg['lb']} 月末={cfg['month_end']} w1={cfg['w1']} cost={cfg['cost']} -> {'OK' if s else 'EMPTY'}", flush=True)

    out = pd.DataFrame(results)
    out.to_csv(os.path.join(OUT, "etf_momentum_20d_0906.csv"), index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(out[["pool", "lookback", "month_end", "w1", "cost", "n_months", "n_trades", "total", "annual",
               "max_dd", "sharpe", "wr", "med", "mean", "excess_ann"]].to_string(index=False))
    for r in results:
        print(f"\n=== pool={r['pool']} lb={r['lookback']} 月末={r['month_end']} w1={r['w1']} cost={r['cost']} 分年度 ===")
        print("  " + " ".join(f"{y}:{v:+.1f}" for y, v in sorted(r["yearly"].items())))
    # 主口径 NAV 落盘
    nav, _ = run(CORE, 20, True, 0.5, 0.001)
    if nav is not None:
        nav.to_csv(os.path.join(OUT, "etf_momentum_20d_nav_0906.csv"))
    print("完成")


if __name__ == "__main__":
    main()
