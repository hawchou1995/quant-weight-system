# -*- coding: utf-8 -*-
"""
全量池基线回测（v6 引擎 × data_full 全量 · 2016-01-04 起）
=============================================================
复用 weight_system_backtest.py 的引擎函数（v6 对称打分已内置），仅覆盖：
- DATA_DIR → data_full/（全量：沪深 A 股 + 北交所 + ETF + 退市股）
- BACKTEST_START = 2016-01-04，BACKTEST_END = 2026-08-14
- 标的池 = data_full 全部 CSV（排除场外基金，全量池无基金）
- is_fund 判定：sh5/sz1 开头（ETF）→ 免印花税
- open<=0 价格保护：视为停牌行（跳过信号/执行，净值用 close 或前值）
- 输出精简：每标的结果只存 summary（不存全量 equity），组合等权净值全量保存

v6fix1（2026-10-10）两处修复
-------------------------------------------------------------
A. 组合净值按 A 股交易日历取样（口径修复）
   缺陷：组合净值 = 「当日有数据标的的归一化净值均值」，既无交易日门槛、也无成分数门槛。
   data_full 中 7 只退市股（sz300028 / sz300090 / sz300104 / sz300156 / sz300216 /
   sz300372 / sz300431）各自被追加了一条「最后交易日行的逐字节副本」，日期却错标为
   2021-06-27（周日）。于是该周日成为全池唯一「只含这 7 只、且归一化净值≈1.6」的样本日
   ⇒ 等权均值 1.5992（前后交易日均为 108.x），把最大回撤从真值 −39.09% 伪造成 −98.64%，
   虚增 59.5pp。同一批文件尾巴上还各挂一条 `2026-09-23,0,0,0,<close>,0,0` 的全零行
   （open 已由 load_data_protected 置 NaN，仅留痕，不影响净值）。
   修复：组合净值只保留 trade_cal_sina.csv 内的交易日；被剔除日逐日登记进 diag。
B. 最大回撤符号（报道修复）
   缺陷：legacy/weight_system_backtest.py:719 `max_dd = abs(dd.min())` 抹掉负号，
   报出的 max_drawdown_pct 恒为正（冻结件 +39.30、复跑件 +98.64 同一个成因）。
   修复：本脚本按组合净值序列重算带符号回撤并覆盖该字段；legacy 原值留档为
   `max_drawdown_pct_legacy_abs`。**不改动 legacy 引擎**（该模块另有 13 个历史消费者，
   属未经批准的链上改动）。

读数纪律：五项（年化/回撤/夏普/笔数/胜率）全部来自本脚本本次真实运行；
回撤为带符号口径；口径与剔除明细见 `fullpool_v6_mdd_diag.json`。
"""
import os, sys, json, glob, csv, time, re
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
OUT_MDD_DIAG = BASE / f"{PREFIX}_mdd_diag.json"

# v6fix1-A：最小成分数门槛（仅作告警留痕，不做过滤；正式过滤走交易日历）
BREADTH_WARN = 100


def load_trade_cal(root: Path):
    """A 股交易日历（仓根 trade_cal_sina.csv，单列 trade_date）。
    缺失时返回 (None, None) —— 调用方须显式降级并把降级事实写进读数。"""
    p = root / "trade_cal_sina.csv"
    if not p.is_file():
        return None, None
    pat = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    days = set()
    with open(p, "r", encoding="utf-8", errors="ignore") as fp:
        for line in fp:
            d = line.strip().split(",")[0].strip().replace("/", "-")
            if pat.match(d):
                days.add(d)
    return (days if days else None), str(p)


CAL, CAL_PATH = load_trade_cal(BASE)


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
    if CAL:
        print(f"交易日历：已加载 {len(CAL)} 天 @ {CAL_PATH}（组合净值按此取样 · v6fix1-A）")
    else:
        print(f"交易日历：**缺失** @ {CAL_PATH} ⇒ 组合净值不按日历取样，该口径降级须在读数中声明")

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

    # ---- 组合等权净值（v6fix1-A：按 A 股交易日历取样）----
    dropped_dates = []
    combo = []
    breadth = []
    for date in sorted(combined_equity.keys()):
        vals = combined_equity[date]
        if CAL is not None and date not in CAL:
            dropped_dates.append({
                "date": date,
                "constituents": len(vals),
                "combo_value_if_kept": round(sum(vals) / len(vals), 4),
                "sample_codes_note": "非交易日（日历外）；成分数按当日有数据的标的计",
            })
            continue
        combo.append({"date": date, "value": round(sum(vals) / len(vals), 4)})
        breadth.append(len(vals))

    combo_summary = W.compute_summary(combo, all_trades)

    # ---- v6fix1-B：带符号最大回撤（覆盖 legacy 的 abs() 结果）----
    legacy_abs_mdd = combo_summary.get("max_drawdown_pct")
    _v = pd.to_numeric(pd.Series([p["value"] for p in combo]))
    _dd = (_v / _v.cummax() - 1) * 100
    fixed_mdd = round(float(_dd.min()), 2)
    # 自检 1：修复后必须 ≤ 0（等价净值序列的回撤不可能是正的）
    if fixed_mdd > 0.005:
        raise RuntimeError(f"v6fix1-B 自检失败：带符号回撤 {fixed_mdd} > 0，组合净值序列非正值形态")
    # 自检 2：与 legacy 的绝对值必须**逐位相等** ⇒ 证明本次只改了符号、没顺带改量级
    if legacy_abs_mdd is not None and round(abs(legacy_abs_mdd), 2) != round(abs(fixed_mdd), 2):
        raise RuntimeError(
            f"v6fix1-B 自检失败：legacy_abs={legacy_abs_mdd} vs fixed={fixed_mdd} "
            f"（绝对值不等 ⇒ abs() 之外还有别的分歧，不得直接覆盖）")
    combo_summary["max_drawdown_pct"] = fixed_mdd
    combo_summary["max_drawdown_pct_legacy_abs"] = legacy_abs_mdd

    # ---- 回撤诊断（口径 + 剔除明细 + 成分数 + 极值日）----
    n = len(combo)
    i_min = int(_dd.idxmin()) if n else 0
    i_max = int(_v.idxmax()) if n else 0
    lowest5 = sorted(range(n), key=lambda k: _v[k])[:5]
    mdd_diag = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "caliber": {
            "equity_sampling": "A 股交易日历（trade_cal_sina.csv）取样",
            "calendar_path": CAL_PATH,
            "calendar_days": (len(CAL) if CAL else None),
            "calendar_applied": bool(CAL),
            "combo_definition": "当日有数据标的的归一化净值（各自首根 = 100）等权均值",
            "drawdown_definition": "(组合净值 / 历史峰值 - 1)，带符号，取最负值",
            "sign_fix": "覆盖 legacy/weight_system_backtest.py:719 `max_dd = abs(dd.min())`",
            "scope_note": "legacy 引擎未改动（该模块另有 13 个历史消费者）",
        },
        "n_days": n,
        "n_dropped_non_trading_days": len(dropped_dates),
        "dropped_non_trading_days": dropped_dates,
        "mdd_pct": fixed_mdd,
        "mdd_legacy_abs_pct": legacy_abs_mdd,
        "mdd_date": combo[i_min]["date"] if n else None,
        "mdd_value": combo[i_min]["value"] if n else None,
        "mdd_constituents": breadth[i_min] if n else None,
        "peak_date": combo[i_max]["date"] if n else None,
        "peak_value": combo[i_max]["value"] if n else None,
        "breadth": {
            "min": min(breadth) if breadth else None,
            "max": max(breadth) if breadth else None,
            "median": (sorted(breadth)[len(breadth) // 2] if breadth else None),
            "first": breadth[0] if breadth else None,
            "last": breadth[-1] if breadth else None,
            "n_days_below_warn": (sum(1 for c in breadth if c < BREADTH_WARN) if breadth else None),
            "warn_threshold": BREADTH_WARN,
        },
        "lowest5_by_value": [{
            "date": combo[k]["date"], "value": combo[k]["value"],
            "dd_pct": round(float(_dd[k]), 4), "constituents": breadth[k],
        } for k in lowest5],
        "window": {"start": W.BACKTEST_START, "end": W.BACKTEST_END,
                   "first_equity_date": combo[0]["date"] if n else None,
                   "last_equity_date": combo[-1]["date"] if n else None},
    }
    with open(OUT_MDD_DIAG, "w", encoding="utf-8") as fp:
        json.dump(mdd_diag, fp, ensure_ascii=False, indent=2)

    # ---- 输出 ----
    out = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "window": {"start": W.BACKTEST_START, "end": W.BACKTEST_END},
        "weights": W.WEIGHTS,
        "universe_size": len(results),
        "skipped_short": total - len(results),
        "caliber": mdd_diag["caliber"],
        "dropped_non_trading_days": dropped_dates,
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
                "caliber": mdd_diag["caliber"],
                "n_days": n,
                "n_dropped_non_trading_days": len(dropped_dates),
                "harness_version": "v6fix1（交易日历取样 + 带符号回撤）",
            },
            "summary": combo_summary,
        }, fp, ensure_ascii=False, indent=2)

    el = time.time() - t_start
    print("=" * 80)
    print(f"完成 {len(results)} 只 · 耗时 {el/60:.1f} 分钟")
    print(f"组合(等权): 总收益 {combo_summary.get('total_return_pct')}% | 年化 {combo_summary.get('annual_return_pct')}% "
          f"| 最大回撤 {combo_summary.get('max_drawdown_pct')}%（带符号；legacy abs 原值 "
          f"{combo_summary.get('max_drawdown_pct_legacy_abs')}） | 夏普 {combo_summary.get('sharpe')} "
          f"| 胜率 {combo_summary.get('win_rate_pct')}% | 交易 {combo_summary.get('total_trades')} 笔")
    print(f"组合日数 {n}（按交易日历取样；剔除日历外 {len(dropped_dates)} 天）"
          f" · 回撤极值日 {mdd_diag['mdd_date']}（当日成分 {mdd_diag['mdd_constituents']} 只）")
    print(f"输出: {OUT_JSON.name} / {OUT_EQUITY.name} / {OUT_TRADES.name} / {OUT_SUMMARY.name} / {OUT_MDD_DIAG.name}")


if __name__ == "__main__":
    main()
