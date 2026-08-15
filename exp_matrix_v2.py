# -*- coding: utf-8 -*-
"""
补跑实验（v2）：B 组权重扫描（修复后）+ D2 buyhold 全仓对照 + D5 连板否决
==========================================================================
修复：compute_total_score_w 支持 weights_override（原版硬编码全局 WEIGHTS）
D2v2：真正跑 bh 策略（fix_buyhold=True 全仓）与 weight 对照
D5：高位连板否决（IMA 黄金公式「4板+胜率0%」→ 连板≥4 清仓）——候选注入
"""
import sys, json, time
from pathlib import Path
sys.path.insert(0, r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
from exp_engine import run_pool, run_backtest, BASE
import weight_system_backtest as W
import pandas as pd

DATA = str(BASE / "data_full")
subs = (BASE / "subsample_1000.txt").read_text(encoding="utf-8").splitlines()
OUT = BASE / "exp_matrix_v2_results.json"

def run(label, **kw):
    t0 = time.time()
    cs, res, combo = run_pool(subs, DATA, label, **kw)
    dt = time.time() - t0
    row = {
        "label": label, "seconds": round(dt, 0),
        "total_return_pct": cs.get("total_return_pct"),
        "annual_return_pct": cs.get("annual_return_pct"),
        "max_drawdown_pct": cs.get("max_drawdown_pct"),
        "sharpe": cs.get("sharpe"),
        "win_rate_pct": cs.get("win_rate_pct"),
        "total_trades": cs.get("total_trades"),
    }
    print(f"[{label}] {dt:.0f}s | 收益 {row['total_return_pct']}% | 回撤 {row['max_drawdown_pct']}% "
          f"| 夏普 {row['sharpe']} | 胜率 {row['win_rate_pct']}% | 交易 {row['total_trades']}")
    return row

results = {}
base_w = {"trend": 0.30, "momentum": 0.25, "volume": 0.15, "osc": 0.15, "risk": 0.10, "news": 0.05}

def bump(key, delta):
    w = dict(base_w)
    w[key] += delta
    others = sum(v for k, v in w.items() if k != key)
    scale = (1 - w[key]) / others
    for k in w:
        if k != key:
            w[k] = round(w[k] * scale, 4)
    return w

# 基线（对照，确保与 v1 一致）
results["V2_基线"] = run("V2_基线")

# ===== B 组：权重扫描（修复后）=====
for key in ["trend", "momentum", "volume", "osc", "risk"]:
    results[f"B1_{key}+0.05"] = run(f"B1_{key}+0.05", weights_override=bump(key, 0.05))
for key in ["trend", "momentum", "volume", "osc", "risk"]:
    results[f"B2_{key}-0.05"] = run(f"B2_{key}-0.05", weights_override=bump(key, -0.05))
# 极端：news 从 0.05 → 0（研报权重归零，验证依赖度）
w_no_news = dict(base_w); w_no_news["news"] = 0.0
others = sum(v for k, v in w_no_news.items() if k != "news")
for k in w_no_news:
    if k != "news":
        w_no_news[k] = round(w_no_news[k] / others, 4)
results["B3_news归零"] = run("B3_news归零", weights_override=w_no_news)

# ===== D2v2：buyhold 全仓对照（独立跑 bh 组合）=====
t0 = time.time()
from collections import defaultdict
bh_equity = defaultdict(list)
for code in subs:
    f = f"{DATA}/{code}.csv"
    if not Path(f).exists():
        continue
    try:
        df = pd.read_csv(f)
        df["date"] = pd.to_datetime(df["date"])
        df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
        if len(df) < 250:
            continue
        is_fund = code.startswith(("sh5", "sz1"))
        eq_b, tr_b = run_backtest(df, None, is_fund=is_fund, strategy="bh",
                                  fix_buyhold=True, limit_rule=True)
        if not eq_b:
            continue
        base = eq_b[0]["value"]
        for p in eq_b:
            bh_equity[p["date"]].append(round(100 * p["value"] / base, 4))
    except Exception:
        pass
combo_bh = [{"date": dt, "value": round(sum(v) / len(v), 4)} for dt, v in sorted(bh_equity.items())]
cs_bh = W.compute_summary(combo_bh, [])
results["D2v2_buyhold全仓对照"] = {
    "label": "D2v2_buyhold全仓对照", "seconds": round(time.time() - t0, 0),
    "total_return_pct": cs_bh.get("total_return_pct"),
    "annual_return_pct": cs_bh.get("annual_return_pct"),
    "max_drawdown_pct": cs_bh.get("max_drawdown_pct"),
    "sharpe": cs_bh.get("sharpe"),
    "win_rate_pct": None, "total_trades": None,
}
print(f"[D2v2_buyhold全仓对照] {time.time()-t0:.0f}s | 收益 {cs_bh.get('total_return_pct')}% "
      f"| 回撤 {cs_bh.get('max_drawdown_pct')}% | 夏普 {cs_bh.get('sharpe')}")

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n已保存: {OUT}")
print("\n===== 汇总（按夏普排序）=====")
for k, v in sorted(results.items(), key=lambda kv: -(kv[1].get("sharpe") or 0)):
    print(f"{k:<22} 收益 {v.get('total_return_pct')}% | 回撤 {v.get('max_drawdown_pct')}% | 夏普 {v.get('sharpe')} | 胜率 {v.get('win_rate_pct')}% | 交易 {v.get('total_trades')}")
