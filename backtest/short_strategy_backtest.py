# -*- coding: utf-8 -*-
"""短线策略历史回测：反转 vs 动量 vs 双通道，全市场，月度调仓
==============================================================
方法：每个调仓日（每月首个可用交易日），用截至该日的数据对全池打短评分，
按权限（主板/创业板/科创板）各取 TopN（等权持有到下月调仓），计算组合净值/胜率/回撤。
回测期：2024-08 ~ 2026-08（约2年）。
策略：
  A. 反转（当前生产 reversal=True）
  B. 动量（reversal=False）
  C. 双通道（反转Top5 + 动量Top5 合并，同权限）
  D. 基准：全池等权（沪深全A代表）
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
import short_engine as S

t0 = time.time()
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

print("加载全池...", flush=True)
pool = S.load_stock_pool()
print(f"池 {len(pool)} 只 ({time.time()-t0:.0f}s)", flush=True)

# 统一日期网格（取所有标的中出现频率最高的交易日序列）
all_dates = sorted(set().union(*[set(ddf.index.unique()) for ddf in pool.values()])) if pool else []
# 只用 2024-06 之后的
all_dates = [d for d in all_dates if d >= pd.Timestamp("2024-06-01")]
print(f"回测日期网格 {len(all_dates)} 个交易日 ({all_dates[0].date()} ~ {all_dates[-1].date()})", flush=True)

# 预计算每个标的的 close 序列（dict code->Series），加速
closes = {c: ddf["close"] for c, ddf in pool.items()}
print("close 预计算完成", flush=True)

def board_of(code):
    if code.startswith(("sh688", "sh689")): return "star"
    if code.startswith("sz30"): return "gem"
    if code.startswith(("sh60", "sz00", "sz002")): return "main"
    return None

def score_at(code, dt):
    """在 dt 及之前用最近数据算短评分（避免未来函数）"""
    df = pool[code]
    hist = df.loc[:dt]
    if len(hist) < 30:
        return None, None
    r = hist.iloc[-1]
    sr = S.short_score(r, reversal=True)
    sm = S.short_score(r, reversal=False)
    return sr, sm

# 调仓日：每月第一个交易日
rebal_dates = []
prev_ym = None
for d in all_dates:
    ym = (d.year, d.month)
    if ym != prev_ym:
        rebal_dates.append(d)
        prev_ym = ym
print(f"调仓日 {len(rebal_dates)} 个", flush=True)

# 各策略持仓（code -> 权重）
def calc_rankings(dt):
    rk = {"rev": {"main": [], "gem": [], "star": []},
          "mom": {"main": [], "gem": [], "star": []}}
    for code in pool:
        if board_of(code) is None:
            continue
        sr, sm = score_at(code, dt)
        bd = board_of(code)
        if sr is not None: rk["rev"][bd].append((code, sr))
        if sm is not None: rk["mom"][bd].append((code, sm))
    return rk

# 记录每月持仓
holdings = {}   # date -> {strategy: [codes]}
for dt in rebal_dates:
    rk = calc_rankings(dt)
    h = {}
    TOP = 6
    for kind in ("rev", "mom"):
        picks = []
        for bd in ("main", "gem", "star"):
            lst = sorted(rk[kind][bd], key=lambda x: -x[1])[:TOP]
            picks += [c for c, _ in lst]
        h[kind] = picks
    # 双通道
    h["dual"] = list(dict.fromkeys(h["rev"] + h["mom"]))
    holdings[dt] = h
    print(f"  {dt.date()} rev={len(h['rev'])} mom={len(h['mom'])} dual={len(h['dual'])} ({time.time()-t0:.0f}s)", flush=True)

# 计算净值：月度调仓，等权持有时看月度收益（用月末首次月内涨幅近似→直接用下一调仓日前收益）
# 简化：每月第一个交易日后持有，收益 = 组合在下月调仓日前一个月内各标的的累计收益均值
def monthly_ret(picks, start_dt, end_dt):
    """从 start_dt（含）到 end_dt（不含）各标的等权收益"""
    if not picks:
        return 0.0
    rets = []
    for c in picks:
        s = closes[c]
        try:
            a = s.loc[:start_dt].iloc[-1]
        except Exception:
            continue  # 数据不够
        # 找 end_dt 之前最后可用价
        sub = s.loc[:end_dt]
        if len(sub) < 2:
            continue
        b = sub.iloc[-1]
        if a <= 0 or pd.isna(a):
            continue
        rets.append(b / a - 1)
    return float(np.mean(rets)) if rets else 0.0

# 全A等权基准（月末收益均值）
def market_ret(start_dt, end_dt):
    rs = []
    for c, s in closes.items():
        sub = s.loc[start_dt:end_dt]
        if len(sub) >= 2:
            a, b = sub.iloc[0], sub.iloc[-1]
            if a > 0: rs.append(b / a - 1)
    return float(np.mean(rs)) if rs else 0.0

# 累积净值
navs = {"rev": [1.0], "mom": [1.0], "dual": [1.0], "mkt": [1.0]}
for i, dt in enumerate(rebal_dates[:-1]):
    nd = rebal_dates[i + 1]
    r = {k: monthly_ret(holdings[dt][k], dt, nd) for k in ("rev", "mom", "dual")}
    r["mkt"] = market_ret(dt, nd)
    for k in navs:
        navs[k].append(navs[k][-1] * (1 + r[k]))
    print(f"  {dt.date()}->{nd.date()}: rev {r['rev']*100:+.1f}% mom {r['mom']*100:+.1f}% dual {r['dual']*100:+.1f}% mkt {r['mkt']*100:+.1f}%", flush=True)

def perf(nav):
    nav = np.array(nav)
    tot = nav[-1] / nav[0] - 1
    peak = np.maximum.accumulate(nav)
    mdd = float(((nav / peak) - 1).min())
    # 年化
    years = len(nav) / 12.0
    ann = (nav[-1] / nav[0]) ** (1 / years) - 1 if years > 0 else 0
    # 月胜率
    mrets = np.diff(nav) / nav[:-1]
    win = float((mrets > 0).mean())
    return {"总收益": round(tot * 100, 1), "年化": round(ann * 100, 1),
            "最大回撤": round(mdd * 100, 1), "月胜率": round(win * 100, 1),
            "期末净值": round(float(nav[-1]), 3)}

result = {"period": f"{rebal_dates[0].date()} ~ {rebal_dates[-1].date()}",
          "top_per_board": TOP}
for k in ("rev", "mom", "dual", "mkt"):
    result[k] = perf(navs[k])

print("\n===== 回测结果（月度调仓，每权限Top6） =====", flush=True)
print(json.dumps(result, ensure_ascii=False, indent=2))
json.dump(result, open(os.path.join(BASE, "backtest", "short_strategy_backtest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("已存 backtest/short_strategy_backtest.json")
