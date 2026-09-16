# -*- coding: utf-8 -*-
"""轨A（冷门低波）去留的**组合层**证据（2026-09-16）
=================================================================
问题：轨A 单轨年化 11.79%/夏普 0.959/回撤 −16.47%（30 相位中位 0.827）——是"弱"还是"该退休"？
      单轨指标无法回答：轨A 的价值若在**低相关/低回撤**，就看组合层是否因它变好。

方法：三条生产净值曲线对齐后，按现行配比加权（日频再平衡近似），扫描 轨A 权重 w_A：
      主仓 FB3 固定 60%，卫星 40% 内 轨B = 40% − w_A（w_A=10% 即现行 60/10/30）。
      输出 CAGR / 年化波动 / 夏普 / 最大回撤 / Calmar，以及三轨相关矩阵。
数据：轨C = short_v3_fund_slip20_equity.csv；轨A = lnatr_v2_equity_0915.csv；
      轨B = oss_0913/super_champion_equity_0913.csv（各为自家生产口径，跨引擎近似，仅作同尺度对照）
产物：backtest/report_trackA_keep_or_retire_0916.json（+ 屏幕输出）
"""
import json
import pathlib

import numpy as np
import pandas as pd

BASE = pathlib.Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
OUT = BASE / "backtest" / "report_trackA_keep_or_retire_0916.json"

SRC = {
    "C_FB3": (BASE / "short_v3_fund_slip20_equity.csv", "date", "value"),
    "A_lnatr": (BASE / "backtest" / "lnatr_v2_equity_0915.csv", "date", "value"),
    "B_super": (BASE / "backtest" / "oss_0913" / "super_champion_equity_0913.csv", "Unnamed: 0", "0"),
}


def load():
    out = {}
    for k, (f, dc, vc) in SRC.items():
        d = pd.read_csv(f)
        s = pd.Series(pd.to_numeric(d[vc], errors="coerce").values, index=pd.to_datetime(d[dc]))
        out[k] = s[~s.index.isna()].sort_index()
    return out


def metrics(r):
    r = r.dropna()
    if len(r) < 30:
        return {}
    eq = (1 + r).cumprod()
    yrs = len(r) / 244.0
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    vol = r.std(ddof=0) * np.sqrt(244)
    sharpe = (r.mean() / (r.std(ddof=0) + 1e-12)) * np.sqrt(244)
    mdd = (eq / eq.cummax() - 1).min()
    return {"cagr_pct": round(cagr * 100, 2), "vol_pct": round(vol * 100, 2),
            "sharpe": round(sharpe, 3), "mdd_pct": round(mdd * 100, 2),
            "calmar": round(cagr / abs(mdd), 2) if mdd else None,
            "total_pct": round((eq.iloc[-1] - 1) * 100, 1), "days": len(r)}


def main():
    eq = load()
    df = pd.DataFrame({k: v for k, v in eq.items()}).dropna()
    print(f"对齐窗口：{df.index[0].date()} → {df.index[-1].date()}（{len(df)} 交易日）\n")
    ret = df.pct_change().dropna()

    print("=== 各轨单轨（同窗口）===")
    single = {}
    for k in ("C_FB3", "A_lnatr", "B_super"):
        m = metrics(ret[k])
        single[k] = m
        print(f"  {k:<8} 年化 {m['cagr_pct']:>5.2f}%  波动 {m['vol_pct']:>5.2f}%  夏普 {m['sharpe']:>5.3f}  回撤 {m['mdd_pct']:>6.2f}%  Calmar {m['calmar']}")

    print("\n=== 相关矩阵（日收益）===")
    cm = ret.corr().round(3)
    print(cm.to_string())
    corr = {f"{a}~{b}": float(cm.loc[a, b]) for a in cm.index for b in cm.columns if a < b}
    for k, v in corr.items():
        print(f"  {k}: {v}")

    print("\n=== 组合扫描（主仓 60% 固定；轨A 权重 w_A，轨B = 40% − w_A）===")
    rows = []
    for wa in [0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40]:
        w = {"C_FB3": 0.60, "A_lnatr": wa, "B_super": 0.40 - wa}
        pr = sum(ret[k] * ww for k, ww in w.items())
        m = metrics(pr)
        tag = "  ← 现行 60/10/30" if abs(wa - 0.10) < 1e-9 else ("  ← 无轨A（退休）" if wa == 0 else "")
        rows.append({"w_A": wa, **m})
        print(f"  w_A={wa:.0%}（C/A/B = {w['C_FB3']:.0%}/{w['A_lnatr']:.0%}/{w['B_super']:.0%}）"
              f"  年化 {m['cagr_pct']:>5.2f}%  夏普 {m['sharpe']:>5.3f}  回撤 {m['mdd_pct']:>6.2f}%  Calmar {m['calmar']}{tag}")

    OUT.write_text(json.dumps({"window": [str(df.index[0].date()), str(df.index[-1].date())],
                               "single": single, "corr": corr, "scan": rows},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[done] → {OUT.name}")


if __name__ == "__main__":
    main()
