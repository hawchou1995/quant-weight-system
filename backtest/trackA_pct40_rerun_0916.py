# -*- coding: utf-8 -*-
"""轨A pct40 组合层重跑（2026-09-16）
=================================================================
目的：回答"轨A 该不该退休" —— 上一次组合扫描用的是**未启用 pct40** 的轨A 曲线（夏普 0.959）。
      本脚本用出场实验同一 harness（exit_lab_trackA_0915.py）导出**同源**的两条曲线：
        (a) BASE（无 pct40）  (b) pct40（跌出前 40% → T+1 开盘出，留现金至下轮）
      再用三条生产曲线（轨C FB3、轨B SUPER）做组合扫描：w_A ∈ {0, 5, 10, 15, 20, 30, 40}%。
关键设计：BASE 与 pct40 出自**同一 harness**，两者之差=pct40 净效应；与生产曲线(lnatr_v2)的差=harness 差。
产物：backtest/trackA_lab_base_0916.csv、trackA_lab_pct40_0916.csv、report_trackA_pct40_blend_0916.json
"""
import json
import pathlib

import numpy as np
import pandas as pd

BASE = pathlib.Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
LAB = BASE / "backtest" / "oss_0913" / "exit_lab_trackA_0915.py"
OUT = BASE / "backtest"

# ---- 载入 lab harness（截断到结果段之前；给 run_exit 加一条"顺带返回净值曲线"）----
src = LAB.read_text(encoding="utf-8").split('res = {"track_a": {}, "track_b": {}}')[0]
assert "def run_exit" in src, "run_exit 未找到"
old_ret = "return dict(ann=float(ann)"
assert old_ret in src, "return 锚点未命中"
src = src.replace(old_ret, "return dict(eq_idx=[str(d.date()) for d in eq.index], eq_val=[float(x) for x in eq.values], ann=float(ann)", 1)
g = {"__name__": "lab_wrap"}
exec(src, g)
run_exit = g["run_exit"]

print("=== 轨A harness 载入完成，导出曲线 ===")
curves = {}
for tag, mode in (("base", None), ("pct40", "pct40")):
    m = run_exit("turn", 20, 30, 0, exit_mode=mode)
    s = pd.Series(m["eq_val"], index=pd.to_datetime(m["eq_idx"]))
    curves[tag] = s
    csv = OUT / f"trackA_lab_{tag}_0916.csv"
    pd.DataFrame({"date": s.index.strftime("%Y-%m-%d"), "value": s.values}).to_csv(csv, index=False)
    print(f"  {tag:6s}: {len(s)} 日 | ann {m['ann']*100:+.2f}% 夏普 {m['sharpe']:.3f} 回撤 {m['mdd']*100:.2f}% "
          f"换手 {m['n_trades']} 退出触发 {m['n_exit']} → {csv.name}")

# ---- 组合扫描 ----
C = pd.read_csv(BASE / "short_v3_fund_slip20_equity.csv")
C = pd.Series(pd.to_numeric(C["value"]).values, index=pd.to_datetime(C["date"]))
Bd = pd.read_csv(BASE / "backtest" / "oss_0913" / "super_champion_equity_0913.csv")
Bv = pd.Series(pd.to_numeric(Bd["0"]).values, index=pd.to_datetime(Bd["Unnamed: 0"]))
Aprod = pd.read_csv(BASE / "backtest" / "lnatr_v2_equity_0915.csv")
Aprod = pd.Series(pd.to_numeric(Aprod["value"]).values, index=pd.to_datetime(Aprod["date"]))


def metrics(r):
    r = r.dropna()
    eq = (1 + r).cumprod()
    yrs = len(r) / 244.0
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    sh = (r.mean() / (r.std(ddof=0) + 1e-12)) * np.sqrt(244)
    mdd = (eq / eq.cummax() - 1).min()
    return {"cagr_pct": round(cagr * 100, 2), "sharpe": round(sh, 3), "mdd_pct": round(mdd * 100, 2),
            "calmar": round(cagr / abs(mdd), 2) if mdd else None, "days": len(r)}


report = {}
for label, A in (("A_prod_v2(无pct40)", Aprod), ("A_lab_base(无pct40)", curves["base"]),
                 ("A_lab_pct40(启用pct40)", curves["pct40"])):
    df = pd.DataFrame({"C": C, "A": A, "B": Bv}).dropna()
    ret = df.pct_change().dropna()
    sA = metrics(ret["A"])
    print(f"\n=== 轨A 单轨（{label}，窗口 {df.index[0].date()}→{df.index[-1].date()}）"
          f" 年化 {sA['cagr_pct']}% 夏普 {sA['sharpe']} 回撤 {sA['mdd_pct']}% ===")
    rows = []
    for wa in [0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40]:
        w = {"C": 0.60, "A": wa, "B": 0.40 - wa}
        pr = sum(ret[k] * ww for k, ww in w.items())
        m = metrics(pr)
        rows.append({"w_A": wa, **m})
        tag = "  ← 现行 60/10/30" if abs(wa - 0.10) < 1e-9 else ("  ← 无轨A（退休）" if wa == 0 else "")
        print(f"  w_A={wa:>4.0%}（C/A/B={w['C']:.0%}/{w['A']:.0%}/{w['B']:.0%}） 年化 {m['cagr_pct']:>5.2f}%  "
              f"夏普 {m['sharpe']:>5.3f}  回撤 {m['mdd_pct']:>6.2f}%  Calmar {m['calmar']}{tag}")
    report[label] = {"single": sA, "scan": rows}

(OUT / "report_trackA_pct40_blend_0916.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
print("\n[done] → report_trackA_pct40_blend_0916.json")
