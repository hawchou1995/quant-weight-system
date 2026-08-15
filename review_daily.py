# -*- coding: utf-8 -*-
"""每日复盘引擎（v1）
============================================
输入：--as-of 信号日（默认最新 short_pool 信号日）、--calc 计算日（默认最新交易日）
流程：
1. calc_signals(as_of) 重算信号池（不覆盖生产文件）
2. 对每只信号标的：T+1 开盘买入价 → 计算日收盘价 → 收益；计算日 MA5 状态
3. 判定：🟢吃到（收益>0）/ 🔴被套（收益<0）/ ⚪持平；汇总胜率/平均收益/最大亏
4. 缺陷检测（grill）：胜率 vs 回测基准（股票/ETF/基金 ~54%）、单池<40%、MA5破位>50%、单标的<-5%
5. 输出 review/<calc>_sig<as_of>.md + review/review_index.json（GitHub release 风格）
用法：python review_daily.py [--as-of 2026-08-13] [--calc 2026-08-14]
"""
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(r"C:/Users/XAUTHUB/WorkBuddy/投资/量化权重系统")
sys.path.insert(0, str(BASE))
import short_engine as S
import build_short_pool as B

REVIEW_DIR = BASE / "review"
REVIEW_DIR.mkdir(exist_ok=True)

# 回测基准胜率（v3 最优参数实测）
BENCH_WIN = {"股票": 53.7, "ETF": 54.3, "基金": 54.1}


def t_plus_1(ddf, as_of):
    """信号日后第一个交易日"""
    idx = ddf.index[ddf.index > as_of]
    return idx[0] if len(idx) else None


def load_pool(board):
    if board == "基金":
        return S.load_fund_pool(3000)
    return S.load_etf_pool() if board == "ETF" else S.load_stock_pool()


def review(as_of=None, calc=None):
    t0 = time.time()
    # 1. 信号（默认最新信号日）
    if as_of is None:
        cur = json.load(open(BASE / "short_pool.json", encoding="utf-8"))
        as_of = cur["as_of"]
    out, _sigs = B.calc_signals(as_of)
    as_of = out["as_of"]
    print(f"信号 {as_of}: 股票{len(out['tiers'].get('股票',[]))} + "
          f"ETF{len(out['tiers'].get('ETF',[]))} + 基金{len(out['tiers'].get('基金',[]))} ({time.time()-t0:.0f}s)", flush=True)

    # 2. 每标的行情（pool 复用一次）
    pools = {b: load_pool(b) for b in ("股票", "ETF", "基金")}
    calc_day = pd.Timestamp(calc) if calc else None
    rows = []          # 明细
    for grp, codes in out["tiers"].items():
        for c in codes:
            d = out["details"][c]
            ddf = pools[grp].get(("sh" if c.startswith(("6", "5")) else "sz") + c)
            if ddf is None:
                ddf = pools[grp].get(c)   # 基金池 key 为裸代码
            if ddf is None:
                continue
            t1 = t_plus_1(ddf, pd.Timestamp(as_of))
            if t1 is None:
                continue
            # T+1 开盘买入价（基金=当日净值）
            buy_px = float(ddf.loc[t1, "close" if grp == "基金" else "open"])
            # 计算日（默认最新交易日）收盘
            if calc_day is not None:
                avail = ddf.index[ddf.index <= calc_day]
            else:
                avail = ddf.index
            cur_px = float(ddf.loc[avail[-1], "close"]) if len(avail) else None
            if not cur_px or cur_px <= 0 or buy_px <= 0:
                continue
            pct = (cur_px / buy_px - 1) * 100
            # 计算日 MA5
            ma5 = ddf.loc[avail[-1], "ma5"] if "ma5" in ddf.columns and len(avail) else np.nan
            ma5_above = bool(not pd.isna(ma5) and cur_px > ma5)
            rows.append({
                "grp": grp, "code": c, "name": d["name"], "score": d["short_score"],
                "buy_px": round(buy_px, 4), "cur_px": round(cur_px, 4),
                "pct": round(pct, 2), "ma5_above": ma5_above,
                "status": ("🟢吃到" if pct > 0 else ("🔴被套" if pct < 0 else "⚪持平")),
                "calc_date": str(avail[-1].date()),
            })
    calc_date = rows[0]["calc_date"] if rows else (str(calc_day.date()) if calc_day else as_of)
    print(f"明细 {len(rows)} 条, 计算日 {calc_date} ({time.time()-t0:.0f}s)", flush=True)

    # 3. 汇总 + 缺陷检测
    md_lines = [f"# 📋 复盘日志 v1.0.0",
                f"## 🗓 {time.strftime('%Y-%m-%d')} ｜ 信号日 {as_of} → 计算日 {calc_date}（T+1 持仓）", ""]
    md_lines.append("### 📊 总览")
    md_lines.append("| 池 | 数量 | 🟢吃到 | 🔴被套 | ⚪持平 | 胜率 | 平均收益 | 最大亏 |")
    md_lines.append("|---|---|---|---|---|---|---|---|")
    defects = []
    pool_notes = []   # 数据窗口说明（基金 T+1 确认 / ETF 数据滞后）
    sig_t = pd.Timestamp(as_of)
    for grp in ("股票", "ETF", "基金"):
        rs = [r for r in rows if r["grp"] == grp]
        if not rs:
            if grp == "ETF":
                pool_notes.append("⚠️ ETF 行情数据滞后（T+1 未入库），本次跳过，数据更新后自动补复盘")
            continue
        wins = sum(1 for r in rs if r["pct"] > 0)
        wr = wins / len(rs) * 100
        avg = sum(r["pct"] for r in rs) / len(rs)
        mx = min(r["pct"] for r in rs)
        bench = BENCH_WIN[grp]
        # 数据窗口判定：基金 T+1 确认净值，T+2 才有收益；ETF 看 T+1 是否入库
        enough = True
        if grp == "基金" and all(abs(r["pct"]) < 0.001 for r in rs):
            enough = False
            pool_notes.append("⚠️ 基金按 T+1 净值确认，收益待 T+2 净值（本次为确认日，无收益属正常）")
        md_lines.append(f"| {grp} | {len(rs)} | {wins} | {len(rs)-wins-sum(1 for r in rs if r['pct']==0)} | "
                        f"{sum(1 for r in rs if r['pct']==0)} | {wr:.0f}% | {avg:+.2f}% | {mx:+.2f}% |")
        # 缺陷检测（数据不足的池跳过）
        if not enough:
            continue
        if wr < 45 and avg < 0:
            defects.append(f"⚠️ **{grp}池信号失效预警**：胜率 {wr:.0f}%（<45%）且平均收益 {avg:+.2f}%，偏离回测基准 {bench}%")
        elif wr < bench - 15:
            defects.append(f"⚠️ **{grp}池胜率偏低**：{wr:.0f}% vs 回测基准 {bench}%（偏离 >15pct）")
        if all(r["pct"] < 0 for r in rs):
            defects.append(f"🔴 **{grp}池全败**：{len(rs)} 只全部被套，板块性信号缺陷")
    # 整体
    wins = sum(1 for r in rows if r["pct"] > 0)
    wr_all = wins / len(rows) * 100 if rows else 0
    avg_all = sum(r["pct"] for r in rows) / len(rows) if rows else 0
    ma5_down = sum(1 for r in rows if not r["ma5_above"])
    md_lines.append(f"| **合计** | {len(rows)} | {wins} | {len(rows)-wins} | 0 | {wr_all:.0f}% | {avg_all:+.2f}% | — |")
    md_lines.append("")
    if ma5_down / len(rows) > 0.5 if rows else False:
        defects.append(f"⚠️ **MA5 破位率 {ma5_down}/{len(rows)}（{ma5_down/len(rows)*100:.0f}% > 50%）**：趋势恶化，次日应批量减仓")
    deep = [r for r in rows if r["pct"] < -5]
    if deep:
        names = "、".join(f"{r['name']}({r['pct']:.1f}%)" for r in deep[:5])
        defects.append(f"🔴 **深套标的**（<-5%）：{names}")
    md_lines.append("### 🔍 缺陷检测（grill）")
    if pool_notes:
        md_lines.extend([f"- {x}" for x in pool_notes])
        md_lines.append("")
    if defects:
        md_lines.extend([f"- {x}" for x in defects])
        md_lines.append("")
        md_lines.append("> ⚠️ 发现缺陷 → 需启动量化系统更新，记录于更新日志（changelog）")
    elif not pool_notes:
        md_lines.append("- ✅ 各池胜率/收益符合系统设计（对比回测基准），未发现设计缺陷")
        md_lines.append("- ✅ MA5 生命线运行正常，无批量破位")

    # 4. 明细
    md_lines.append("")
    md_lines.append("### 📑 明细")
    for grp in ("股票", "ETF", "基金"):
        rs = [r for r in rows if r["grp"] == grp]
        if not rs:
            continue
        md_lines.append(f"#### {grp}（信号 {as_of}）")
        md_lines.append("| 代码 | 名称 | 信号分 | 买入价 | 现价 | 收益 | MA5 | 判定 |")
        md_lines.append("|---|---|---|---|---|---|---|---|")
        for r in sorted(rs, key=lambda x: -x["pct"]):
            md_lines.append(f"| {r['code']} | {r['name']} | {r['score']:.0f} | {r['buy_px']} | {r['cur_px']} | "
                            f"**{r['pct']:+.2f}%** | {'✅' if r['ma5_above'] else '⚠️下方'} | {r['status']} |")
        md_lines.append("")
    md_lines.append("---")
    md_lines.append("> ⚠️ 复盘内容由 AI 基于公开数据自动生成，仅供系统自检，不构成投资建议。")

    # 5. 输出
    fname = f"{calc_date}_sig{as_of}.md"
    (REVIEW_DIR / fname).write_text("\n".join(md_lines), encoding="utf-8")
    # 索引
    idx_f = REVIEW_DIR / "review_index.json"
    idx = json.load(open(idx_f, encoding="utf-8")) if idx_f.exists() else {"reviews": []}
    idx["reviews"].insert(0, {"file": fname, "date": calc_date, "sig": as_of,
                              "n": len(rows), "win_rate": round(wr_all, 1), "avg": round(avg_all, 2),
                              "defects": len(defects)})
    json.dump(idx, open(idx_f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✅ 复盘已生成 review/{fname}（{len(rows)} 条，胜率 {wr_all:.0f}%，缺陷 {len(defects)} 项，耗时 {time.time()-t0:.0f}s）")
    return fname


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=None, help="信号日 YYYY-MM-DD（默认最新）")
    ap.add_argument("--calc", default=None, help="计算日 YYYY-MM-DD（默认最新交易日）")
    args = ap.parse_args()
    review(as_of=args.as_of, calc=args.calc)
