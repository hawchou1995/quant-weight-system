# -*- coding: utf-8 -*-
"""v1.3 正式对比：死区 + 反转才动 开关效果（对比 v1.2 基线）"""
import sys, json
sys.path.insert(0, ".")
import pandas as pd
import weight_system_backtest as wsb
from weight_system_backtest import load_data, compute_summary

MODES = {
    "v12基线(开关全关)": dict(USE_DEADBAND=False, USE_REVERSAL_ONLY=False),
    "死区55-65":         dict(USE_DEADBAND=True,  USE_REVERSAL_ONLY=False),
    "反转才动":           dict(USE_DEADBAND=False, USE_REVERSAL_ONLY=True),
    "死区+反转才动":      dict(USE_DEADBAND=True,  USE_REVERSAL_ONLY=True),
}

def run_pool(mode_cfg):
    wsb.USE_DEADBAND = mode_cfg["USE_DEADBAND"]
    wsb.USE_REVERSAL_ONLY = mode_cfg["USE_REVERSAL_ONLY"]
    combos = {}
    per_symbol = {}
    for code, name, typ, mkt, news in wsb.UNIVERSE:
        df = load_data(code)
        eq, tr = wsb.run_backtest(df, news, is_fund=(typ == "基金"), strategy="weight")
        if not eq:
            continue
        base = eq[0]["value"]
        for p in eq:
            combos.setdefault(p["date"], []).append(100 * p["value"] / base)
        w_ret = eq[-1]["value"] / eq[0]["value"] * 100 - 100
        wins = sum(1 for t in tr if t["pnl"] > 0)
        per_symbol[code] = {
            "name": name, "ret": w_ret, "trades": len(tr),
            "win": wins, "win_rate": round(wins / len(tr) * 100, 1) if tr else 0,
        }
    combo = [{"date": dt, "value": round(sum(v) / len(v), 4)} for dt, v in sorted(combos.items())]
    s = compute_summary(combo, [])
    return s, per_symbol

def main():
    out = {}
    print("=" * 78)
    print("v1.3 正式对比（19 标的等权组合，2025-01 ~ 2026-08）")
    print("=" * 78)
    header = f"{'模式':<14}{'总收益':>10}{'年化':>9}{'回撤':>9}{'夏普':>7}{'交易数':>7}"
    print(header)
    rows = []
    for name, cfg in MODES.items():
        s, per = run_pool(cfg)
        trades = sum(v["trades"] for v in per.values())
        print(f"{name:<14}{s['total_return_pct']:>+9.1f}%{s['annual_return_pct']:>+8.1f}%{s['max_drawdown_pct']:>8.1f}%{s['sharpe']:>7.2f}{trades:>7}")
        rows.append({"mode": name, "total": s["total_return_pct"], "annual": s["annual_return_pct"],
                     "dd": s["max_drawdown_pct"], "sharpe": s["sharpe"], "trades": trades})
        out[name] = {"summary": {k: s[k] for k in ["total_return_pct", "annual_return_pct", "max_drawdown_pct", "sharpe"]},
                     "per_symbol": per}
    print("=" * 78)
    # 逐标的对比：基线 vs 死区+反转
    print("\n逐标的对比（基线 → 死区+反转才动，收益% / 交易数 / 胜率%）：")
    base_per = out["v12基线(开关全关)"]["per_symbol"]
    new_per = out["死区+反转才动"]["per_symbol"]
    print(f"{'标的':<10}{'基线收益':>10}{'新收益':>10}{'基线交易':>9}{'新交易':>9}{'基线胜率':>9}{'新胜率':>9}")
    for code in base_per:
        b, n = base_per[code], new_per[code]
        delta = n["ret"] - b["ret"]
        flag = " ▲" if delta > 1 else (" ▼" if delta < -1 else " =")
        print(f"{b['name']:<10}{b['ret']:>+9.1f}%{n['ret']:>+9.1f}%{b['trades']:>9}{n['trades']:>9}{b['win_rate']:>8.1f}%{n['win_rate']:>8.1f}%{flag}")
    with open("v13_compare.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n已保存: v13_compare.json")

if __name__ == "__main__":
    main()
