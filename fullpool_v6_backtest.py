# -*- coding: utf-8 -*-
"""
全量池基线回测（v6 引擎 × data_full 7420 只 · 2016-01-04 起）
=============================================================
复用 weight_system_backtest.py 的引擎函数（v6 对称打分已内置），仅覆盖：
- DATA_DIR → data_full/（7420 只全量：沪深 A 股 + 北交所 + ETF + 退市股）
- BACKTEST_START = 2016-01-04，BACKTEST_END = 2026-08-14
- 标的池 = data_full 全部 CSV（排除场外基金，全量池无基金）
- is_fund 判定：sh5/sz1 开头（ETF）→ 免印花税
- open<=0 价格保护：视为停牌行（跳过信号/执行，净值用 close 或前值）
- 输出精简：每标的结果只存 summary（不存全量 equity），组合等权净值全量保存
"""
import os, sys, json, glob, csv, time
from pathlib import Path
from datetime import datetime
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))

import weight_system_backtest as W

# ---- 覆盖配置 ----
W.DATA_DIR = str(BASE / "data_full")
W.BACKTEST_START = "2016-01-04"
W.BACKTEST_END = "2026-08-14"

PREFIX = "fullpool_v6"
OUT_JSON = BASE / f"{PREFIX}_results.json"
OUT_EQUITY = BASE / f"{PREFIX}_equity.csv"
OUT_TRADES = BASE / f"{PREFIX}_trades.csv"
OUT_SUMMARY = BASE / f"{PREFIX}_summary.json"

# ETF 判断（sh5x / sz1x 开头）
def is_etf_code(code: str) -> bool:
    return code.startswith(("sh5", "sz1"))

def load_data_protected(code: str) -> pd.DataFrame:
    """读数据 + open<=0 保护（标记停牌行，close 保留用于净值）"""
    df = W.load_data(code)
    # open<=0 的行：open 置 NaN 触发引擎停牌分支（等权净值仍用 close）
    df.loc[df["open"] <= 0, "open"] = float("nan")
    return df

def main():
    codes = sorted(Path(W.DATA_DIR).glob("*.csv"))
    total = len(codes)
    print(f"全量池 {total} 只 · 窗口 {W.BACKTEST_START} ~ {W.BACKTEST_END} · {W.POSITION_MODEL}")

    all_trades = []
    results = {}
    combined_equity = {}  # date -> [归一化净值]
    t_start = time.time()

    for i, f in enumerate(codes, 1):
        code = f.stem
        is_fund = is_etf_code(code)
        try:
            df = load_data_protected(code)
            if len(df) < 250:  # 数据不足 1 年：跳过（新股/退市尾段）
                continue
            eq_w, tr_w = W.run_backtest(df, None, is_fund=is_fund, strategy="weight")
            eq_b, tr_b = W.run_backtest(df, None, is_fund=is_fund, strategy="bh")
            if not eq_w:
                continue
            sum_w = W.compute_summary(eq_w, tr_w)
            sum_b = W.compute_summary(eq_b, tr_b)

            # 归一化净值（从 100 起，等权组合用）
            base = eq_w[0]["value"]
            norm = [{"date": p["date"], "value": round(100 * p["value"] / base, 4)} for p in eq_w]
            for t in tr_w:
                t["symbol"] = code
                t["symbol_name"] = code
                t["display_symbol"] = code
            all_trades.extend(tr_w)

            results[code] = {"type": "ETF" if is_fund else "股票",
                             "weight": sum_w, "buyhold": sum_b}
            for p in norm:
                combined_equity.setdefault(p["date"], []).append(p["value"])
        except Exception as e:
            results[code] = {"error": str(e)[:100]}

        if i % 500 == 0 or i == total:
            el = time.time() - t_start
            print(f"[{i}/{total}] {el/60:.1f} 分钟 · 组合日数 {len(combined_equity)} · 交易 {len(all_trades)} 笔")

    # ---- 组合等权净值 ----
    combo = []
    for date in sorted(combined_equity.keys()):
        vals = combined_equity[date]
        combo.append({"date": date, "value": round(sum(vals) / len(vals), 4)})
    combo_summary = W.compute_summary(combo, all_trades)

    # ---- 输出 ----
    out = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "window": {"start": W.BACKTEST_START, "end": W.BACKTEST_END},
        "weights": W.WEIGHTS,
        "universe_size": len(results),
        "skipped_short": total - len(results),
        "results": results,
        "combined_summary": combo_summary,
        "combined_equity": combo,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False)

    with open(OUT_EQUITY, "w", encoding="utf-8") as fp:
        fp.write("date,value\n")
        for p in combo:
            fp.write(f"{p['date']},{p['value']}\n")

    with open(OUT_TRADES, "w", newline="", encoding="utf-8") as fp:
        wtr = csv.writer(fp)
        wtr.writerow(["entry_date", "exit_date", "side", "size", "entry_price", "exit_price",
                      "pnl", "pnl_pct", "holding_bars", "symbol", "symbol_name", "display_symbol"])
        for t in all_trades:
            wtr.writerow([t.get(k, "") for k in
                          ["entry_date", "exit_date", "side", "size", "entry_price", "exit_price",
                           "pnl", "pnl_pct", "holding_bars", "symbol", "symbol_name", "display_symbol"]])

    with open(OUT_SUMMARY, "w", encoding="utf-8") as fp:
        json.dump({
            "meta": {
                "strategy_name": "综合指标权重系统 v6（全量池等权组合）",
                "symbol": f"{len(results)} 只全量池等权组合",
                "start": W.BACKTEST_START, "end": W.BACKTEST_END,
                "initial_cash": 100.0, "window_start_value": 100.0,
                "final_value": combo[-1]["value"] if combo else None,
                "market": "china_a", "generated_at": out["generated_at"],
            },
            "summary": combo_summary,
        }, fp, ensure_ascii=False, indent=2)

    el = time.time() - t_start
    print("=" * 80)
    print(f"完成 {len(results)} 只 · 耗时 {el/60:.1f} 分钟")
    print(f"组合(等权): 总收益 {combo_summary.get('total_return_pct')}% | 年化 {combo_summary.get('annual_return_pct')}% "
          f"| 最大回撤 {combo_summary.get('max_drawdown_pct')}% | 夏普 {combo_summary.get('sharpe')} "
          f"| 胜率 {combo_summary.get('win_rate_pct')}% | 交易 {combo_summary.get('total_trades')} 笔")
    print(f"输出: {OUT_JSON.name} / {OUT_EQUITY.name} / {OUT_TRADES.name} / {OUT_SUMMARY.name}")

if __name__ == "__main__":
    main()
