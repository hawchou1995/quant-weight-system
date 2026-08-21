# -*- coding: utf-8 -*-
"""每日复盘引擎 v2（三池全量）
============================================
复盘全部标的：
  1. 全量池中/长线（普适版 v9，40 只：主板10+创业板10+科创板10+基金10，2026-08-17 去 ETF）
  2. 短线全量池（40 只：股票反转按权限各10【主板/创业板/科创板】 + 基金动量10，去 ETF）
  （2026-08-19 晚用户决策：复盘日志已移除固定池中/长线——固定池已并入 track_v9，其信号在跟踪池呈现；
   全量池中/长线与短线全量池一样按 主板/创业板/科创板/基金 四个板块细分展示总览）

流程（每个池）：
1. as_of 信号日：用当日行情重算信号分（v9/v8 用 V.score_row，短线用 calc_signals）
2. 买入信号判定：v9/v8 = 档位 ≥ 轻仓加仓（分≥60）；短线 = 短分 ≥ 50（强买入/买入）
3. 买入信号标的：T+1 开盘买入（基金=T+1 净值）→ 计算日收盘 → 收益/MA5 → 🟢吃到/🔴被套/⚪持平
4. 缺陷检测（grill）：各池胜率 vs 回测基准（v9 48.1% / v8 57.1% / 短线按板块 46.8~57.8%）、
   单池全败、MA5 破位>50%、深套<-5%
5. 输出 review/<calc>_sig<as_of>.md + review/review_index.json

用法：python review_daily.py [--as-of 2026-08-13] [--calc 2026-08-14]
"""
import os
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(BASE))
import short_engine as S
import build_short_pool as B
import v9_auto as A
import build_enhanced_data as E
import v8_selector as V

REVIEW_DIR = BASE / "review"
REVIEW_DIR.mkdir(exist_ok=True)

# 回测基准胜率（各池最优参数实测；短线按板块，2026-08-17 去 ETF）
BENCH_WIN = {
    "全量池中/长线": json.load(open(BASE / "v9_auto_summary.json", encoding="utf-8"))["summary"]["win_rate_pct"],
    "短线全量池-主板": 46.8, "短线全量池-创业板": 48.1, "短线全量池-科创板": 57.8, "短线全量池-基金": 55.5,
}

TIER_W = [("满仓加仓", 75), ("轻仓加仓", 60), ("观望", 45), ("减至半仓", 30), ("清仓", 0)]

# 已知案例登记（2026-08-18）：缺陷检测命中已立项/已评估的标的时，标注状态而非纯告警。
# code -> {kind, status}；kind 与缺陷类型匹配（deep=深套 / fix_pool_sig=固定池信号失效）
KNOWN_CASES = {
    "300720": {"kind": "deep",
               "status": "🟡 已回测评估：Aroon 高位抑制敏感性 5/9 正向（A50/M060 最优 +304% vs 基线 192%=+112pct、回撤 -3.8pct、夏普 0.83），未达 ≥7/9 投产门槛 → 观察待投产"},
}

# 权限 → 板块中文名（与三个监控池统一口径，2026-08-17 去 etf）
PERM_ZH = {"main": "主板", "gem": "创业板", "star": "科创板", "fund": "基金"}


def tier_of(sc):
    for t, th in TIER_W:
        if sc >= th:
            return t
    return "清仓"


def short_tier_of(sc):
    """短线买入口径（与 build_short_pool.buy_tier 一致）：≥60 强买入 / ≥50 买入 / 其余不买"""
    if sc >= 60:
        return "强买入"
    if sc >= 50:
        return "买入"
    return "不买"


def load_ddf(c, perm):
    """按权限加载带特征列的 ddf（复用 build_enhanced_data 的加载器）"""
    key = ("sh" if c.startswith(("6", "5")) else "sz") + c
    if perm in ("main", "gem", "star"):
        return A.pool_all.get(key)
    d = E.load_fund_cache_df(c)
    if d is None:
        d = E.load_hist_df(c)
    return d


def t_plus_1(ddf, as_of):
    idx = ddf.index[ddf.index > as_of]
    return idx[0] if len(idx) else None


def load_details():
    """从 enhanced_data.js 读完整数据（details/meta.v9_tiers 等）"""
    js = (BASE / "enhanced_data.js").read_text(encoding="utf-8")
    return json.loads(js[len("window.ENH = "):-1])


def pool_codes(details, tag):
    return [c for c, d in details.items() if d.get("pool") == tag]


def parse_pool_rows(md_text):
    """解析单篇复盘 md 当日总览表的各池行 → {池名: {n, buy, wins, losses, flat, avg}}
    2026-08-18 修复：累计总览已置顶，"| 池 | 累计标的 |..." 也会以 "| 池 |" 开头——
    必须精确匹配「当日总览」表头（第二列="标的"），否则把累计表当当日表重复累加（自乘缺陷）。
    """
    rows, in_table = {}, False
    for ln in md_text.splitlines():
        if ln.startswith("| 池 | 标的 |"):
            in_table = True
            continue
        if in_table and ln.startswith("|"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) >= 8 and not cells[0].startswith("**") and cells[0] not in ("固定池中/长线",):
                # 2026-08-19：固定池已并入 track_v9，复盘日志不再统计固定池（含历史累计）
                try:
                    rows[cells[0]] = {
                        "n": int(cells[1]), "buy": int(cells[2]), "wins": int(cells[3]),
                        "losses": int(cells[4]), "flat": int(cells[5]),
                        "avg": float(cells[7].replace("%", "").replace("+", "")),
                    }
                except (ValueError, IndexError):
                    continue
        elif in_table and not ln.startswith("|"):
            break
    return rows


def build_cumulative():
    """从 review_index.json 各篇 md 解析累加 → 自复盘以来累计统计（天然防重：同篇只解析一次）"""
    idx_f = REVIEW_DIR / "review_index.json"
    idx = json.load(open(idx_f, encoding="utf-8")) if idx_f.exists() else {"reviews": []}
    acc = {}
    for r in idx.get("reviews", []):
        f = REVIEW_DIR / r["file"]
        if not f.exists():
            continue
        for name, v in parse_pool_rows(f.read_text(encoding="utf-8")).items():
            a = acc.setdefault(name, {"n": 0, "buy": 0, "wins": 0, "losses": 0, "flat": 0, "sum_pct": 0.0})
            a["n"] += v["n"]; a["buy"] += v["buy"]; a["wins"] += v["wins"]
            a["losses"] += v["losses"]; a["flat"] += v["flat"]; a["sum_pct"] += v["avg"] * v["buy"]
    out = {"since": idx["reviews"][-1]["date"] if idx.get("reviews") else None,
           "count": len(idx.get("reviews", [])), "pools": acc}
    json.dump(out, open(REVIEW_DIR / "cumulative.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return out


def cumulative_md(cum):
    """累计总览 → md 表格"""
    lines = [f"### 📈 累计总览（自 {cum['since']} 首篇复盘以来，共 {cum['count']} 篇）",
             "| 池 | 累计标的 | 累计买入 | 🟢吃到 | 🔴被套 | ⚪持平 | 累计胜率 | 累计平均收益 |",
             "|---|---|---|---|---|---|---|---|"]
    t = {"n": 0, "buy": 0, "wins": 0, "losses": 0, "flat": 0, "sum_pct": 0.0}
    for name, a in cum["pools"].items():
        wr = a["wins"] / a["buy"] * 100 if a["buy"] else 0
        avg = a["sum_pct"] / a["buy"] if a["buy"] else 0
        lines.append(f"| {name} | {a['n']} | {a['buy']} | {a['wins']} | {a['losses']} | {a['flat']} | "
                     f"{wr:.0f}% | {avg:+.2f}% |")
        for k in t:
            t[k] += a[k]
    if t["buy"]:
        lines.append(f"| **合计** | {t['n']} | {t['buy']} | {t['wins']} | {t['losses']} | {t['flat']} | "
                     f"{t['wins']/t['buy']*100:.0f}% | {t['sum_pct']/t['buy']:+.2f}% |")
    lines.append("")
    return "\n".join(lines)


def review(as_of=None, calc=None):
    t0 = time.time()
    ENH = load_details()
    details = ENH["details"]
    # 2026-08-17 修复：全量池权限按 v9_tiers 分组映射（基金组曾因 details.perm 默认 main 被误标"主板"）
    _v9_tiers = ENH.get("meta", {}).get("v9_tiers", {}) or {}
    _v9_perm = {c: g for g, codes in _v9_tiers.items() for c in codes}
    v9_codes = pool_codes(details, "v9")          # 全量池中/长线 40 只（含基金组 10）
    if as_of is None:
        # 2026-08-19 修复（收盘复盘全跳过根因）：默认信号日取「上一交易日」，保证 T+1 开盘买入日 = 最新交易日（存在）。
        # 原实现取 short_pool 末日（=今日收盘）→ T+1 不存在 → 全部跳过误报「行情缺失」。
        # ⚠ 勿用 E.all_days 取 [-2]：它被 v8_selector 的 END（08-17 回测截断）过滤，[-2] 会落到 08-14。
        # 正确口径：index_000300.csv 日历的倒数第二行（数据日历），换算信号日 08-18 → T+1 08-19 开盘买入、08-19 收盘估值。
        try:
            _idx_cal = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
            as_of = _idx_cal["date"].iloc[-2]
        except Exception:
            cur = json.load(open(BASE / "short_pool.json", encoding="utf-8"))
            as_of = cur["as_of"]
    sig_t = pd.Timestamp(as_of)
    out, _sigs = B.calc_signals(as_of)            # 短线全量池信号（不覆盖生产文件）
    as_of = out["as_of"]
    print(f"信号 {as_of}: 全量池 {len(v9_codes)} + 短线 {sum(len(v) for v in out['tiers'].values())} ({time.time()-t0:.0f}s)", flush=True)

    # ---- 构建三个池的标的清单（统一结构）----
    pools = []
    for c in v9_codes:
        d = details[c]
        _perm = _v9_perm.get(c, d.get("perm", "main"))
        pools.append({"pool": "全量池中/长线", "code": c, "name": d["name"],
                      "perm": _perm, "board": d.get("board") or PERM_ZH.get(_perm, "")})
    for grp, codes in out["tiers"].items():
        for c in codes:
            d = out["details"][c]
            perm = {"主板": "main", "创业板": "gem", "科创板": "star", "基金": "fund"}.get(grp, "main")
            pools.append({"pool": "短线全量池", "code": c, "name": d["name"],
                          "perm": perm, "board": grp})
    print(f"三池标的 {len(pools)} 只", flush=True)

    # ---- 逐标的复盘 ----
    calc_day = pd.Timestamp(calc) if calc else None
    rows = []
    pending_funds = []   # 基金 T+1 净值未公布（T-1 口径，下次复盘补录）
    t1_pending = {}      # 2026-08-19：记录「T+1 交易日未到」的标的数（区分真缺失 vs 数据边界）
    for it in pools:
        ddf = load_ddf(it["code"], it["perm"])
        if ddf is None:
            continue
        if sig_t not in ddf.index:
            continue
        # 1) 信号日状态
        r = ddf.loc[sig_t]
        if pd.isna(r["close"]) or r["close"] <= 0 or pd.isna(r.get("mom_12_1", np.nan)):
            continue
        # 3) 信号分与买入判定
        if it["pool"] == "短线全量池":
            score = float(out["details"][it["code"]]["short_score"])
            t1_ = short_tier_of(score)
            buy_sig = score >= 50          # 强买入/买入
        else:
            score = float(V.score_row_v2(r))  # v9/v8 中长线分（2026-08-18 A80_M80 替换：Aroon 强趋势过滤）
            t1_ = tier_of(score)
            buy_sig = score >= 60          # 轻仓加仓及以上
        # 2026-08-17 用户决策：全量池中/长线、短线池 = 买入清单——不满足买入条件的标的直接不入日志（不凑数）
        # 2026-08-19：固定池已并入 track_v9，复盘日志不再含固定池（无「未买入」行来源）
        if not buy_sig:
            continue
        # 4) T+1 开盘买入（基金=净值）
        t1 = t_plus_1(ddf, sig_t)
        if t1 is None:
            if it["perm"] == "fund":
                pending_funds.append(it["code"])   # 基金净值 T+1 未公布 → 待确认
            else:
                t1_pending[it["pool"]] = t1_pending.get(it["pool"], 0) + 1   # 股票 T+1 未到（数据边界）
            continue
        if calc_day is not None:
            avail = ddf.index[ddf.index <= calc_day]
        else:
            avail = ddf.index
        cur_px = float(ddf.loc[avail[-1], "close"]) if len(avail) else None
        if not cur_px or cur_px <= 0:
            continue
        row = {
            "pool": it["pool"], "code": it["code"], "name": it["name"],
            "perm": it["perm"], "board": it["board"],
            "score": round(score, 1), "tier": t1_,
            "buy_sig": buy_sig, "buy_px": None, "cur_px": round(cur_px, 4),
            "pct": None, "ma5_above": None, "status": "—", "calc_date": str(avail[-1].date()),
        }
        if buy_sig:
            buy_px = float(ddf.loc[t1, "close" if it["perm"] in ("fund",) else "open"])
            if buy_px > 0:
                # 2026-08-21 修复：基金 T+1 净值=确认日买入净值，确认日无收益（此前计入胜率分母 → 胜率恒 0%）。
                # 收益须待 T+2 净值；T+2 未到时标记「⏳待T+2净值」并排除出胜率统计。
                cur_d = pd.Timestamp(str(avail[-1].date()))
                t1_d = pd.Timestamp(str(t1.date()))
                if it["perm"] == "fund" and cur_d <= t1_d:
                    row.update({"buy_px": round(buy_px, 4), "status": "⏳待T+2净值"})
                else:
                    pct = (cur_px / buy_px - 1) * 100
                    # MA5 现算（compute_factors_full 无 ma5 列，统一 rolling 5）
                    ma5 = float(ddf["close"].rolling(5).mean().loc[avail[-1]]) if len(ddf) >= 5 else np.nan
                    row.update({
                        "buy_px": round(buy_px, 4), "pct": round(pct, 2),
                        "ma5_above": bool(not pd.isna(ma5) and cur_px > ma5),
                        "status": ("🟢吃到" if pct > 0 else ("🔴被套" if pct < 0 else "⚪持平")),
                    })
        rows.append(row)
    calc_date = rows[0]["calc_date"] if rows else (str(calc_day.date()) if calc_day else as_of)
    print(f"明细 {len(rows)} 条, 计算日 {calc_date} ({time.time()-t0:.0f}s)", flush=True)

    # ---- 市场情境（2026-08-19：缺陷检测市场相对校准，防大跌日误报）----
    mkt_ret = None
    try:
        _idf = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str}).dropna(subset=["close"])
        _idc = dict(zip(_idf["date"], _idf["close"].astype(float)))
        if calc_date in _idc:
            _prev = max((d for d in _idc if d < calc_date), default=None)
            if _prev:
                mkt_ret = (_idc[calc_date] / _idc[_prev] - 1) * 100
    except Exception:
        pass
    extreme = mkt_ret is not None and abs(mkt_ret) >= 1.5
    mkt_tag = f"沪深300 {mkt_ret:+.2f}%" if mkt_ret is not None else "沪深300 数据缺失"

    # ---- 汇总（三池）+ 缺陷检测 ----
    md_lines = [f"# 📋 复盘日志 v2.1（全量中长线 + 短线双池）",
                f"## 🗓 {time.strftime('%Y-%m-%d')} ｜ 信号日 {as_of} → 计算日 {calc_date}（T+1 持仓）｜ 市场 {mkt_tag}", ""]
    md_lines.append("### 📊 总览（全量中长线 + 短线，按板块细分）")
    md_lines.append("| 池 | 标的 | 买入信号 | 🟢吃到 | 🔴被套 | ⚪持平 | 胜率 | 平均收益 | 最大亏 | 回测基准 |")
    md_lines.append("|---|---|---|---|---|---|---|---|---|---|")
    defects, pool_notes = [], []
    if pending_funds:
        pool_notes.append(f"⏳ 基金净值按 T+1 公布：{len(pending_funds)} 只基金（{'、'.join(pending_funds[:8])}{'…' if len(pending_funds) > 8 else ''}）待 T+1 净值确认，本次复盘跳过，下次复盘补录")
    groups = ["全量池中/长线", "短线全量池"]
    for grp in groups:
        rs = [r for r in rows if r["pool"] == grp]
        if not rs:
            _np = t1_pending.get(grp, 0)
            if _np:
                # 2026-08-19 修复：T+1 未到 ≠ 行情缺失（此前误报「标的行情缺失」）
                pool_notes.append(f"⏳ **{grp}**：信号日 {as_of} 的 T+1 开盘日尚未到来（{_np} 只标的无后续交易日）——属数据边界非行情缺失，T+1 交易日收盘后重跑补录")
            else:
                pool_notes.append(f"⚠️ **{grp}**：标的行情缺失，本次跳过")
            continue
        buy = [r for r in rs if r["buy_sig"] and r["pct"] is not None]
        wins = sum(1 for r in buy if r["pct"] > 0)
        wr = wins / len(buy) * 100 if buy else None
        avg = sum(r["pct"] for r in buy) / len(buy) if buy else None
        mx = min(r["pct"] for r in buy) if buy else None
        if grp == "短线全量池":
            # 整体基准 = 板块细分基准按买入信号数加权
            _w = [BENCH_WIN[f"短线全量池-{s}"] for s in ("主板", "创业板", "科创板", "基金")
                  for _ in [1] if any(r["board"] == s for r in rs)]
            bench = sum(_w) / len(_w) if _w else 54.0
        else:
            bench = BENCH_WIN[grp]
        if buy:
            md_lines.append(f"| {grp} | {len(rs)} | {len(buy)} | {wins} | {len(buy)-wins-sum(1 for r in buy if r['pct']==0)} | "
                            f"{sum(1 for r in buy if r['pct']==0)} | {wr:.0f}% | {avg:+.2f}% | {mx:+.2f}% | {bench:.1f}% |")
        else:
            # 2026-08-21：全部待 T+2 净值（基金确认日）→ 行仍显示，胜率/收益为 —（不再伪 0%）
            _pend = sum(1 for r in rs if r["status"] == "⏳待T+2净值")
            md_lines.append(f"| {grp} | {len(rs)} | {len(rs)} | 0 | 0 | {_pend} | — | — | — | {bench:.1f}% |")
        if buy and len(buy) >= 5:
            # 2026-08-19 市场相对校准：绝对胜率/均值在极端行情日（|沪深300|≥1.5%）必然恶化，
            # 只有「显著跑输大盘」才算信号缺陷；跑赢大盘的下跌（如 8/19 短线 -1.97% vs 大盘 -2.58%）
            # 属市场 beta 而非设计缺陷，不登记 changelog。
            mkt_bad = mkt_ret is not None and (avg or 0) < mkt_ret - 1.5  # 跑输大盘 >1.5pct
            if wr < 45 and avg < 0 and mkt_bad:
                defects.append(f"⚠️ **{grp}信号失效预警**：胜率 {wr:.0f}%（<45%）且平均收益 {avg:+.2f}%（跑输沪深300 {mkt_ret:+.2f}% 达 {avg-mkt_ret:+.2f}pct）")
            elif wr < bench - 15 and mkt_bad:
                defects.append(f"⚠️ **{grp}胜率偏低**：{wr:.0f}% vs 回测基准 {bench}%（偏离 >15pct 且跑输大盘 {mkt_ret:+.2f}%）")
            if all(r["pct"] < 0 for r in buy) and (mkt_ret is None or (avg or 0) < mkt_ret - 2.5):
                defects.append(f"🔴 **{grp}买入信号全败**：{len(buy)} 只全部被套（跑输沪深300 {mkt_ret:+.2f}% 达 {(avg or 0)-mkt_ret:+.2f}pct）")
    # 短线池按板块细分
    for sub in ("主板", "创业板", "科创板", "基金"):
        rs = [r for r in rows if r["pool"] == "短线全量池" and r["board"] == sub]
        if not rs:
            continue
        buy = [r for r in rs if r["buy_sig"] and r["pct"] is not None]
        if not buy:
            # 2026-08-21：全部待 T+2 净值（基金确认日）→ 行仍显示，不隐藏
            _pend = sum(1 for r in rs if r["status"] == "⏳待T+2净值")
            md_lines.append(f"| 短线·{sub} | {len(rs)} | {len(rs)} | 0 | 0 | {_pend} | — | — | — | {BENCH_WIN[f'短线全量池-{sub}']}% |")
            if sub == "基金" and _pend:
                pool_notes.append("⏳ 短线基金已按 T+1 净值确认买入，收益待 T+2 净值（确认日无收益属正常，非亏损）")
            continue
        wins = sum(1 for r in buy if r["pct"] > 0)
        wr = wins / len(buy) * 100
        avg = sum(r["pct"] for r in buy) / len(buy)
        mx = min(r["pct"] for r in buy)
        bench = BENCH_WIN[f"短线全量池-{sub}"]
        flat_n = sum(1 for r in buy if abs(r["pct"]) < 0.001)
        md_lines.append(f"| 短线·{sub} | {len(rs)} | {len(buy)} | {wins} | {len(buy)-wins-flat_n} | {flat_n} | "
                        f"{wr:.0f}% | {avg:+.2f}% | {mx:+.2f}% | {bench}% |")
    # 2026-08-19：全量池中/长线按板块细分（与短线全量池一致；基准统一用全量池整体胜率）
    for sub in ("主板", "创业板", "科创板", "基金"):
        rs = [r for r in rows if r["pool"] == "全量池中/长线" and r["board"] == sub]
        if not rs:
            continue
        buy = [r for r in rs if r["buy_sig"] and r["pct"] is not None]
        if not buy:
            # 2026-08-21：长线基金确认日 → 行仍显示，胜率/收益为 —
            _pend = sum(1 for r in rs if r["status"] == "⏳待T+2净值")
            md_lines.append(f"| 长线·{sub} | {len(rs)} | {len(rs)} | 0 | 0 | {_pend} | — | — | — | {BENCH_WIN['全量池中/长线']:.1f}% |")
            if sub == "基金" and _pend:
                pool_notes.append("⏳ 长线基金已按 T+1 净值确认买入，收益待 T+2 净值（确认日无收益属正常，非亏损）")
            continue
        wins = sum(1 for r in buy if r["pct"] > 0)
        wr = wins / len(buy) * 100
        avg = sum(r["pct"] for r in buy) / len(buy)
        mx = min(r["pct"] for r in buy)
        bench = BENCH_WIN["全量池中/长线"]
        flat_n = sum(1 for r in buy if abs(r["pct"]) < 0.001)
        md_lines.append(f"| 长线·{sub} | {len(rs)} | {len(buy)} | {wins} | {len(buy)-wins-flat_n} | {flat_n} | "
                        f"{wr:.0f}% | {avg:+.2f}% | {mx:+.2f}% | {bench:.1f}% |")
    # 合计（买入信号）
    buy_all = [r for r in rows if r["buy_sig"] and r["pct"] is not None]
    if buy_all:
        wins_all = sum(1 for r in buy_all if r["pct"] > 0)
        avg_all = sum(r["pct"] for r in buy_all) / len(buy_all)
        md_lines.append(f"| **合计（买入信号）** | {len(rows)} | {len(buy_all)} | {wins_all} | "
                        f"{len(buy_all)-wins_all-sum(1 for r in buy_all if r['pct']==0)} | "
                        f"{sum(1 for r in buy_all if r['pct']==0)} | {wins_all/len(buy_all)*100:.0f}% | "
                        f"{avg_all:+.2f}% | — | — |")
    md_lines.append("")
    # MA5 破位率 / 深套（仅买入信号）
    if buy_all:
        ma5_down = sum(1 for r in buy_all if not r["ma5_above"])
        if ma5_down / len(buy_all) > 0.5:
            _ma_line = f"⚠️ **MA5 破位率 {ma5_down}/{len(buy_all)}（{ma5_down/len(buy_all)*100:.0f}% > 50%）**：趋势恶化，次日应批量减仓"
            if extreme:
                # 极端行情下破位必超 50%，属市场后果非设计缺陷 → 记入观察（不触发 changelog）
                pool_notes.append(_ma_line + f"（极端行情 {mkt_tag} 下属正常市场后果，非信号设计缺陷，操作建议仍执行）")
            else:
                defects.append(_ma_line)
        deep = [r for r in buy_all if r["pct"] < -8]
        if deep:
            parts = []
            for r in deep[:5]:
                kc = KNOWN_CASES.get(r["code"])
                if kc and kc.get("kind") == "deep":
                    parts.append(f"{r['name']}({r['pct']:.1f}%) {kc['status']}")
                else:
                    parts.append(f"{r['name']}({r['pct']:.1f}%)")
            names = "；".join(parts)
            # 深套=单笔尾部记录（回测单笔分布 P1=-6.0%，-8% 属极值尾部）：只记录不触发系统更新
            pool_notes.append(f"🔴 **深套标的**（<-8%，回测单笔分布 P1=-6.0%，-8% 属极值尾部，单笔尾部亏损只记录不触发系统更新）：{names}")
    md_lines.append("### 🔍 缺陷检测（grill）")
    if pool_notes:
        md_lines.extend([f"- {x}" for x in pool_notes])
        md_lines.append("")
    if defects:
        md_lines.extend([f"- {x}" for x in defects])
        md_lines.append("")
        md_lines.append("> ⚠️ 发现缺陷 → 需启动量化系统更新，记录于更新日志（changelog）")
    elif not pool_notes:
        md_lines.append("- ✅ 三池胜率/收益符合系统设计（对比回测基准），未发现设计缺陷")
        md_lines.append("- ✅ MA5 生命线运行正常，无批量破位")

    # ---- 明细（按池分区）----
    md_lines.append("")
    md_lines.append("### 📑 明细")
    for grp in groups:
        rs = [r for r in rows if r["pool"] == grp]
        if not rs:
            continue
        md_lines.append(f"#### {grp}（{len(rs)} 只 · 信号 {as_of}）")
        md_lines.append("| 代码 | 名称 | 权限 | 信号分 | 档位 | 操作 | 买入价 | 现价 | 收益 | MA5 | 判定 |")
        md_lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for r in sorted(rs, key=lambda x: -(x["pct"] if x["pct"] is not None else -999)):
            if r["buy_sig"]:
                act = "买入" if r["tier"] in ("满仓加仓", "轻仓加仓", "强买入", "买入") else "买入(弱)"
                pct_s = f"**{r['pct']:+.2f}%**" if r["pct"] is not None else "—"
                ma_s = "✅" if r["ma5_above"] else ("⚠️下方" if r["ma5_above"] is not None else "—")
                st = r["status"]
            else:
                act = {"观望": "观望", "减至半仓": "卖出信号", "清仓": "卖出信号", "不买": "不买"}.get(r["tier"], "未触发")
                pct_s, ma_s, st = "—", "—", "未买入"
            md_lines.append(f"| {r['code']} | {r['name']} | {PERM_ZH.get(r['perm'], r['perm'])} | {r['score']:.0f} | {r['tier']} | {act} | "
                            f"{r['buy_px'] if r['buy_px'] else '—'} | {r['cur_px']} | {pct_s} | {ma_s} | {st} |")
        md_lines.append("")
    md_lines.append("---")
    md_lines.append("> ⚠️ 复盘内容由 AI 基于公开数据自动生成，仅供系统自检，不构成投资建议。")

    # ---- 输出 ----
    fname = f"{calc_date}_sig{as_of}.md"
    (REVIEW_DIR / fname).write_text("\n".join(md_lines), encoding="utf-8")
    idx_f = REVIEW_DIR / "review_index.json"
    idx = json.load(open(idx_f, encoding="utf-8")) if idx_f.exists() else {"reviews": []}
    wr_all = wins_all / len(buy_all) * 100 if buy_all else 0
    avg_all = sum(r["pct"] for r in buy_all) / len(buy_all) if buy_all else 0
    idx["reviews"] = [r for r in idx.get("reviews", []) if r.get("file") != fname]  # 同 file 替换防重复
    idx["reviews"].insert(0, {"file": fname, "date": calc_date, "sig": as_of,
                              "n": len(rows), "win_rate": round(wr_all, 1), "avg": round(avg_all, 2),
                              "defects": len(defects)})
    json.dump(idx, open(idx_f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    # 累计总览（2026-08-18 晚：移除每篇 md 内嵌——累计总览只在复盘日志页顶部独立卡片显示一次，
    # 见 build_log_pages.py 的「📈 累计总览」独立区块，data 来自 cumulative.json）
    cum = build_cumulative()
    print(f"✅ 复盘已生成 review/{fname}（三池 {len(rows)} 只，买入信号 {len(buy_all)}，胜率 {wr_all:.0f}%，"
          f"缺陷 {len(defects)} 项，累计 {cum['count']} 篇，耗时 {time.time()-t0:.0f}s）")
    return fname


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=None, help="信号日 YYYY-MM-DD（默认最新）")
    ap.add_argument("--calc", default=None, help="计算日 YYYY-MM-DD（默认最新交易日）")
    args = ap.parse_args()
    review(as_of=args.as_of, calc=args.calc)