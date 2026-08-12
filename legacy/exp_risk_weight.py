# -*- coding: utf-8 -*-
"""风控权重敏感性实验：风控 10→15（从 osc 或 volume 挪 5%），
在 24 池（主池）与 37 池（试金石）上对比收益/回撤/夏普。
结论用于决定是否调整权重（素材文档纪律：37 只验证池为试金石）。"""
import sys, os, statistics, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import weight_system_backtest as wb

VARIANTS = {
    "基线(v1.0)": {"trend": 0.30, "momentum": 0.25, "volume": 0.15, "osc": 0.15, "risk": 0.10, "news": 0.05},
    "风控15/osc10": {"trend": 0.30, "momentum": 0.25, "volume": 0.15, "osc": 0.10, "risk": 0.15, "news": 0.05},
    "风控15/volume10": {"trend": 0.30, "momentum": 0.25, "volume": 0.10, "osc": 0.15, "risk": 0.15, "news": 0.05},
}

# 37 只验证池（从 validate_industry_v2）
sys.path.insert(0, ".")
from validate_industry_v2 import TMP_UNIVERSE, load_tmp

def run_pool(universe, loader, is_fund_map):
    """等权组合回测，返回 (组合summary, 每标的summary列表)"""
    eqs, trades = [], []
    per = []
    for u in universe:
        if len(u) == 5:
            code, name, typ, market, news = u
        else:
            code, name, ind = u
            typ, market, news = "股票", "", None
        df = loader(code)
        eq_w, tr_w = wb.run_backtest(df, news, is_fund=(typ == "基金"), strategy="weight")
        sm = wb.compute_summary(eq_w, tr_w)
        per.append({"code": code, "name": name, "ret": sm.get("total_return_pct", 0),
                    "dd": sm.get("max_drawdown_pct", 0), "trades": len(tr_w)})
        # 等权合成净值
        norm = {}
        for p in eq_w:
            norm[p["date"]] = p["value"] / wb.INITIAL_CASH
        eqs.append(norm)
        trades.extend(tr_w)
    dates = sorted(set(d for e in eqs for d in e))
    combo = []
    for d in dates:
        vals = [e[d] for e in eqs if d in e]
        if vals:
            combo.append({"date": d, "value": statistics.mean(vals) * wb.INITIAL_CASH})
    cs = wb.compute_summary(combo, trades)
    return cs, per

def main():
    print(f"{'配置':18s} | {'24池 收益/回撤/夏普/胜率':36s} | {'37池 平均收益/平均回撤':28s} | 37池正收益")
    print("-" * 120)
    out = {}
    for label, W in VARIANTS.items():
        wb.WEIGHTS = dict(W)
        cs24, per24 = run_pool(wb.UNIVERSE, wb.load_data, lambda t: t == "基金")
        cs37, per37 = run_pool(TMP_UNIVERSE, load_tmp, lambda t: False)
        wins37 = sum(1 for r in per37 if r["ret"] > 0)
        avg_ret37 = statistics.mean(r["ret"] for r in per37)
        avg_dd37 = statistics.mean(r["dd"] for r in per37)
        print(f"{label:18s} | {cs24.get('total_return_pct',0):+.1f}% / {cs24.get('max_drawdown_pct',0):.1f}% / {cs24.get('sharpe',0):.2f} / {cs24.get('win_rate_pct',0):.0f}% | {avg_ret37:+.1f}% / {avg_dd37:.1f}% | {wins37}/37")
        out[label] = {"pool24": cs24, "pool37": {"avg_ret": avg_ret37, "avg_dd": avg_dd37, "wins": wins37}}
    wb.WEIGHTS = dict(VARIANTS["基线(v1.0)"])  # 恢复
    json.dump(out, open("exp_risk_weight.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
    print("saved: exp_risk_weight.json")

if __name__ == "__main__":
    main()
