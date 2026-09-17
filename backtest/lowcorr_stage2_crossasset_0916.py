# -*- coding: utf-8 -*-
"""低相关策略挖掘 · 阶段2：跨资产腿（ETF/黄金/债券）—— 2026-09-16
=================================================================
背景：阶段1（同日）证明「同一股票面板内 2 因子全枚举 190 组」过闸 0 组、与轨B 日相关最小 0.557
      → 股票面板内拿不到低相关（共享市场 beta）。本阶段换维度：**跨资产**（ETF/债券/黄金）。

口径（与生产一致，勿改）：
  · 轨B 基准 = 生产冻结引擎 oss_super_combo_0913.py 前缀（composite/run_engine）off0 净值日收益
  · 腿：T 日收盘定目标 → T+1 开盘执行；成本 = slip 每边（主档 20bp / 稳健档 50bp）
    + 佣金 2.5bp（买/卖，最低 5 元）+ 卖出印花 5bp（与冻结引擎 COMM/TAX/MIN_COMM 同口径，保守）
  · 日历 = 冻结引擎面板 cal（2021-01-04 → 2026-09-11），与轨B 严格同轴
  · 相位扫描 5 相位 rebal=20 → offsets 0/4/8/12/16；报相位中位夏普（ADR-0006）
  · 指标：V.summary（夏普年化 √252）；组合层夏普 √244（与冻结引擎一致，JSON 中标注）
  · 数据：本地面板 data_full（ETF，腾讯 qfq 前复权重抓，etf_qfq_diff.json 记录 1454 只核对）
  · 缺数据如实申报：无国债期货/期权/商品期货本地数据 → 不测；黄金只能用 ETF 代理

候选腿（至少这些）：
  (a) ETF 20d 动量 Top-K（K=1/3/5，含/不含绝对动量保护）
  (b) ETF 20d 低波 Top-K（K=1/3/5）
  (c) 黄金 sh518880 单腿 + 20d 动量择时
  (d) 国债/债券 ETF 单腿（511010/511260/511090/511060/511030/511220/511380）
  (e) (c)+(d) 等权防御组合
  (f) 股/债/金 按动量轮动（1 只）
  (x) 扩展：纳指 513100 单腿/择时、债券内部动量轮动

判定：corr ≤0.30 硬闸；腿单独夏普 ≥0.5 可执行下限；组合层夏普 +≥0.02 采纳线
产物：backtest/lowcorr_stage2_crossasset_0916.json
用法：python backtest/lowcorr_stage2_crossasset_0916.py [--smoke]

修订（2026-09-16 当日冒烟发现）：
  ① 买卖「涨跌停开」守卫原用 last[]（卖出后即冻结的陈旧收盘价）→ 卖出后再买入被误判为涨停开，
     nasdaq 择时腿 2023-11 起永久空仓（假结果）。改为**数据前一日收盘**（与冻结引擎 px_prev 同口径）。
  ② 货币 ETF 宇宙排除补漏：名称关键词漏掉「快钱/财富宝/添益」等 → 加「价格长期钉在 100 且年化波动<2%」判据。
"""
import argparse
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
OSS = BASE / "backtest" / "oss_0913"
RES = BASE / "backtest" / "lowcorr_stage2_crossasset_0916.json"

import numpy as np                      # noqa: E402
import pandas as pd                     # noqa: E402
import short_engine as S                # noqa: E402  引擎复用（池加载）
import v8_selector as V                 # noqa: E402  指标复用（V.summary）

PHASES = [0, 4, 8, 12, 16]
REBAL = 20
SLIP_MAIN, SLIP_STRESS = 0.0020, 0.0050
CASH0 = 170_000.0
COMM, TAX, MIN_COMM, LOT = 0.00025, 0.0005, 5.0, 100
LIQ_AMT, MIN_PX = 3e6, 0.5
ANN_BLEND = 244.0       # 组合层年化因子（=冻结引擎口径）
GATES = {"corr_B_max": 0.30, "leg_phmed_min": 0.50, "blend_sharpe_gain": 0.02}

t0 = time.time()
def log(*a):
    print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)


# ============================================================ 1) 轨B 基准
def _anchor_value():
    """软锚（2026-09-17）：读 shadow_ret20 日链刷新的 engine_anchor.json；缺省回落历史锚 22.87"""
    try:
        return float(json.loads((OSS.parent / "engine_anchor.json").read_text(encoding="utf-8"))["base_off0_ann"])
    except Exception:
        return 22.87


def load_track_b():
    src = (OSS / "oss_super_combo_0913.py").read_text(encoding="utf-8")
    g = {}
    exec(src.split("comp = composite()")[0], g)          # 生产冻结引擎前缀
    comp = g["composite"]()
    r = g["run_engine"](comp, 20, offset=0)
    ann = float(r["ann"]) * 100
    eq = r["equity"]
    cal = pd.to_datetime([str(d)[:10] for d in g["cal"]])   # 面板全窗口（2021-01-04 起）
    _anchor = _anchor_value()          # 2026-09-17 软锚：数据 vintage 日更，22.87 为历史锚非硬门
    _d = abs(ann - _anchor)
    log(f"[轨B] off0 年化 {ann:.2f}%（锚 {_anchor}% | 漂移 {_d:.2f}pp）| 夏普(引擎√244) {r['sharpe']:.3f} | "
        f"回撤 {r['mdd']*100:.1f}% | 净值区间 {eq.index[0].date()}→{eq.index[-1].date()} | "
        f"面板日历 {cal[0].date()}→{cal[-1].date()}（{len(cal)}d，WARMUP=150）")
    if _d > 3.0:
        log(f"[ABORT] 轨B 复现年化 {ann:.2f}% 偏离锚 {_anchor}% 达 {_d:.2f}pp（>3pp）→ 口径/数据异常，拒绝出结论")
        sys.exit(2)
    elif _d > 1.0:
        log(f"[WARN] 轨B 锚漂移 {_d:.2f}pp（数据版本推进所致，正常范围）")
    return eq, cal


# ============================================================ 2) ETF 面板
def build_panel(cal):
    pool = S.load_etf_pool()
    names = json.loads((BASE / "data_full_names.json").read_text(encoding="utf-8"))
    close = pd.DataFrame({c: d["close"] for c, d in pool.items()}).sort_index()
    open_ = pd.DataFrame({c: d["open"] for c, d in pool.items()}).sort_index()
    amt = pd.DataFrame({c: d["amount"] for c, d in pool.items()}).sort_index()
    CF = close.ffill()
    ret = CF.pct_change()
    mom20 = CF / CF.shift(20) - 1
    vol20 = ret.rolling(20, min_periods=20).std(ddof=0) * np.sqrt(252.0)
    amt20 = amt.rolling(20, min_periods=15).mean()
    D = {k: v.reindex(cal) for k, v in dict(close=CF, open=open_, amt20=amt20,
                                            mom20=mom20, vol20=vol20).items()}
    cov = D["close"].notna().sum(axis=0)
    keep = cov[cov >= 200].index
    codes = list(keep)
    MONEY_KW = ["货币", "现金", "理财", "日日鑫", "天天金", "保证金", "逆回购", "日利", "快线", "活期"]
    px = D["close"][codes]
    volw = px.pct_change().std(ddof=0) * np.sqrt(252.0)
    pin = ((px >= 99) & (px <= 101)).sum() / px.notna().sum()          # 价格钉在 100 = 场内货币/理财基金
    by_name = np.array([any(k in (names.get(c) or "") for k in MONEY_KW) for c in codes])
    is_money = by_name | ((pin >= 0.9) & (volw < 0.02)).to_numpy()
    log(f"[面板] ETF {len(codes)} 只（窗口内 ≥200 天）| 货币/理财类 {int(is_money.sum())} 只"
        f"（名称命中 {int(by_name.sum())} + 价格钉100/低波补漏 {int(is_money.sum()-by_name.sum())}）→ 低波腿排除")
    return dict(codes=codes, CN=D["close"].to_numpy(), ON=D["open"].to_numpy(),
                MN=D["mom20"].to_numpy(), VN=D["vol20"].to_numpy(), AN=D["amt20"].to_numpy(),
                is_money=is_money, names={c: (names.get(c) or "") for c in codes}, n=len(cal))


# ============================================================ 3) 模拟器
def simulate(cal, P, targets, slip=SLIP_MAIN, cash0=CASH0):
    """targets: {di: [codes]}（T 日收盘目标，T+1 开盘执行）；等权、整手、收盘 mark-to-market"""
    n, col = len(cal), {c: i for i, c in enumerate(P["codes"])}
    CN, ON = P["CN"], P["ON"]
    cash, shares, cost, first_buy, eq = cash0, {}, {}, None, np.full(n, np.nan)
    trades, last, pending, entry_di = [], {}, None, {}
    for di in range(n):
        if pending is not None:                                  # 1) 昨收信号 → 今开执行
            tgt = set(pending)
            for c in list(shares):
                if c in tgt:
                    continue
                j = col[c]; o = ON[di, j]
                pc = CN[di - 1, j] if di > 0 else np.nan     # ⚠ 用数据前一日收盘（非 last[]，防卖后陈旧价永久卡买/卖）
                if not np.isfinite(o) or o <= 0:
                    continue                                      # 无开盘价 → 顺延
                if np.isfinite(pc) and o <= pc * 0.902:
                    continue                                      # 跌停开 → 卖不掉，顺延
                px = o * (1 - slip); amt = px * shares[c]
                fee = max(amt * COMM, MIN_COMM) + amt * TAX
                cash += amt - fee
                trades.append({"symbol": c, "entry_date": str(cal[entry_di.get(c, di)].date()),
                               "exit_date": str(cal[di].date()), "pnl": float(amt - fee - cost[c])})
                del shares[c]; cost.pop(c, None); entry_di.pop(c, None)
            need = [c for c in pending if c not in shares]
            if need:
                pv = cash + sum(shares[c] * last.get(c, 0.0) for c in shares)
                per = pv / len(pending)
                for c in need:
                    j = col[c]; o = ON[di, j]
                    pc = CN[di - 1, j] if di > 0 else np.nan     # ⚠ 同上：用数据前一日收盘（与冻结引擎 px_prev 同口径）
                    if not np.isfinite(o) or o <= 0:
                        continue
                    if np.isfinite(pc) and o >= pc * 1.098:
                        continue                                  # 涨停开 → 买不到，跳过
                    px = o * (1 + slip)
                    lots = int(min(per, cash) / (px * LOT * (1 + COMM)))
                    if lots < 1:
                        continue
                    amt = px * lots * LOT; fee = max(amt * COMM, MIN_COMM)
                    if amt + fee > cash:
                        continue
                    cash -= amt + fee
                    shares[c] = lots * LOT; cost[c] = amt + fee; entry_di[c] = di
                    if first_buy is None:
                        first_buy = di
            pending = None
        for c in shares:                                          # 2) mark-to-market
            v = CN[di, col[c]]
            if np.isfinite(v):
                last[c] = v
        eq[di] = cash + sum(shares[c] * last.get(c, 0.0) for c in shares)
        if di in targets and di + 1 < n:                          # 3) 收盘定目标
            pending = targets[di]
    s = pd.Series(eq, index=cal).ffill()
    return s, trades, first_buy


def mk_eqdf(s):
    return pd.DataFrame({"date": [str(d.date()) for d in s.index], "value": s.to_numpy()})


def eval_leg(cal, P, targets_for_offset, name, smoke=False):
    """5 相位 + slip50；日收益序列与 corr 在 rB 窗口对齐（阶段2 统一处理）"""
    per, rets, sh = {}, {}, []
    eq_off0 = None
    for off in PHASES:
        s, tr, fb = simulate(cal, P, targets_for_offset(off), slip=SLIP_MAIN)
        if fb is None:
            return None
        s2 = s.iloc[fb:]                                          # 从首次建仓日起评（避免前置现金段虚高夏普）
        st = V.summary(mk_eqdf(s2), tr)
        per[off] = st; sh.append(st["sharpe"])
        rets[off] = s2.pct_change().dropna()
        if off == 0:
            off0 = dict(st=st, rets=rets[0], trades=tr); eq_off0 = s2
    s50, tr50, fb50 = simulate(cal, P, targets_for_offset(0), slip=SLIP_STRESS)
    st50 = V.summary(mk_eqdf(s50.iloc[fb50:]), tr50) if fb50 is not None else {"sharpe": None}
    out = {"leg": name, "phmed_sharpe": float(np.median(sh)), "sharpe_min": float(min(sh)),
           "sharpe_max": float(max(sh)), "slip50_sharpe": st50.get("sharpe"),
           "off0_ann_pct": off0["st"]["annual_return_pct"], "off0_mdd_pct": off0["st"]["max_drawdown_pct"],
           "off0_total_pct": off0["st"]["total_return_pct"], "n_trades": off0["st"]["total_trades"],
           "phase_sharpes": {str(k): v["sharpe"] for k, v in per.items()},
           "by_year_pct": {int(y): round(float(g.iloc[-1] / g.iloc[0] - 1) * 100, 1)
                           for y, g in eq_off0.groupby(eq_off0.index.year)},
           "rets0": off0["rets"], "start": str(off0["rets"].index[0].date()),
           "end": str(off0["rets"].index[-1].date())}
    return out


# ============================================================ 4) 腿目标构建
def make_legs(cal, P):
    n, codes, is_money = P["n"], P["codes"], P["is_money"]
    col = {c: i for i, c in enumerate(codes)}
    CN, ON, MN, VN, AN = P["CN"], P["ON"], P["MN"], P["VN"], P["AN"]
    cov_ok = np.isfinite(CN).sum(axis=0) >= 200
    univ_nomoney = cov_ok & (~is_money)
    univ_all = cov_ok.copy()

    def elig(di, univ):
        return np.isfinite(MN[di]) & np.isfinite(CN[di]) & np.isfinite(ON[di]) & \
               (AN[di] >= LIQ_AMT) & (CN[di] > MIN_PX) & univ

    def rebal_days(off):
        return list(range(off, n - 1, REBAL))

    def topk(score, K, off, univ, asc=False, abs_score=False):
        out = {}
        for di in rebal_days(off):
            if di + 1 >= n:
                continue
            ok = elig(di, univ)
            sc = score[di]
            if abs_score:
                ok = ok & (sc > 0)
            idx = np.flatnonzero(ok)
            if idx.size == 0:
                out[di] = []
                continue
            o = idx[np.argsort(sc[idx])] if asc else idx[np.argsort(-sc[idx])]
            out[di] = [codes[j] for j in o[:K]]
        return out

    def fixed(codes_sel, off, timed=False):
        out = {}
        for di in rebal_days(off):
            if di + 1 >= n:
                continue
            if timed:
                sel = [c for c in codes_sel if c in col and np.isfinite(MN[di, col[c]]) and MN[di, col[c]] > 0]
            else:
                sel = list(codes_sel)
            out[di] = sel
        return out

    def pick1(codes_sel, off, abs_filter=False):
        out = {}
        for di in rebal_days(off):
            if di + 1 >= n:
                continue
            best, bm = None, -9e9
            for c in codes_sel:
                if c not in col:
                    continue
                m = MN[di, col[c]]
                if np.isfinite(m) and m > bm:
                    best, bm = c, m
            if best is None or (abs_filter and bm <= 0):
                out[di] = []
            else:
                out[di] = [best]
        return out

    LEGS = []
    def add(name, group, desc, fn, assets, univ_note=""):
        LEGS.append(dict(name=name, group=group, desc=desc, fn=fn, assets=assets, univ=univ_note))

    # (a) ETF 20d 动量 Top-K
    for K in (1, 3, 5):
        add(f"a_mom20_K{K}", "a", f"ETF 20d 动量 Top{K} 月度轮动", lambda off, K=K: topk(MN, K, off, univ_nomoney),
            ["ETF池(非货币)"], "1021只非货币ETF")
        add(f"a_mom20_K{K}_abs", "a", f"ETF 20d 动量 Top{K}（绝对动量保护：<0 留现金）",
            lambda off, K=K: topk(MN, K, off, univ_nomoney, abs_score=True), ["ETF池(非货币)"])
    add("a0_mom20_K3_allpool", "a", "ETF 20d 动量 Top3（含货币 ETF 的全池，敏感性）",
        lambda off: topk(MN, 3, off, univ_all), ["全ETF池"])

    # (b) ETF 20d 低波 Top-K
    for K in (1, 3, 5):
        add(f"b_lowvol_K{K}", "b", f"ETF 20d 波动率最低 Top{K} 月度轮动",
            lambda off, K=K: topk(VN, K, off, univ_nomoney, asc=True), ["ETF池(非货币)"])

    # (c) 黄金
    GOLD = "sh518880"
    add("c_gold_bh", "c", "黄金ETF(518880) 买入持有", lambda off: fixed([GOLD], off), [GOLD])
    add("c_gold_mom", "c", "黄金ETF 20d 动量择时（<0 留现金）", lambda off: fixed([GOLD], off, timed=True), [GOLD])

    # (d) 债券/国债单腿
    BONDS = [("sh511010", "国债ETF(5y)"), ("sh511260", "十年国债ETF"), ("sh511090", "30年国债ETF"),
             ("sh511060", "5年地方债ETF"), ("sh511030", "公司债ETF"), ("sh511220", "城投债ETF"),
             ("sh511380", "可转债ETF")]
    for c, nm in BONDS:
        if c in col:
            add(f"d_{c}_bh", "d", f"{nm} 买入持有", lambda off, c=c: fixed([c], off), [c])

    # (e) 黄金+国债 等权防御
    add("e_gold_bond_5050", "e", "黄金518880 + 国债511010 等权（月度再平衡）",
        lambda off: fixed([GOLD, "sh511010"], off), [GOLD, "sh511010"])
    add("e_gold_bond_5050_timed", "e", "黄金 + 国债 等权 + 各自 20d 动量择时",
        lambda off: fixed([GOLD, "sh511010"], off, timed=True), [GOLD, "sh511010"])
    add("e_gold_10y_5050", "e", "黄金 + 十年国债511260 等权（扩展）",
        lambda off: fixed([GOLD, "sh511260"], off), [GOLD, "sh511260"])

    # (f) 股/债/金 动量轮动（1 只）
    EQ = "sh512100"
    add("f_stock_gold_mom1", "f", "股(中证1000ETF) / 金 二选一 20d 动量", lambda off: pick1([EQ, GOLD], off), [EQ, GOLD])
    add("f_stock_gold_mom1_abs", "f", "股 / 金 二选一 + 绝对动量（All Money 留现金）",
        lambda off: pick1([EQ, GOLD], off, abs_filter=True), [EQ, GOLD])
    add("f_stock_bond_mom1", "f", "股(中证1000ETF) / 债(511010) 二选一 20d 动量", lambda off: pick1([EQ, "sh511010"], off), [EQ, "sh511010"])
    add("f_stock_bond_mom1_abs", "f", "股 / 债 二选一 + 绝对动量", lambda off: pick1([EQ, "sh511010"], off, abs_filter=True), [EQ, "sh511010"])
    add("f_triple_mom1_abs", "f", "股/金/债 三选一 20d 动量 + 绝对动量", lambda off: pick1([EQ, GOLD, "sh511010"], off, abs_filter=True),
        [EQ, GOLD, "sh511010"])

    # (x) 扩展
    add("x_nasdaq_bh", "x", "纳指ETF(513100) 买入持有", lambda off: fixed(["sh513100"], off), ["sh513100"])
    add("x_nasdaq_mom", "x", "纳指ETF 20d 动量择时", lambda off: fixed(["sh513100"], off, timed=True), ["sh513100"])
    BOND3 = [c for c, _ in BONDS if c in col and c not in ("sh511380", "sh511090")]
    add("x_bond_rot_mom1_abs", "x", "国债/地方债/公司债/城投 动量轮动 1 只 + 绝对动量",
        lambda off: pick1(BOND3, off, abs_filter=True), BOND3, "利率债/信用债 5 只")
    return LEGS, col


# ============================================================ 5) 组合层
def perf(r, ann=ANN_BLEND):
    eq = (1 + r).cumprod()
    years = (r.index[-1] - r.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / years) - 1
    sharpe = r.mean() / r.std() * np.sqrt(ann)
    mdd = (eq / eq.cummax() - 1).min()
    return dict(ann_pct=round(float(cagr) * 100, 2), sharpe=round(float(sharpe), 3),
                vol_pct=round(float(r.std()) * np.sqrt(ann) * 100, 2),
                mdd_pct=round(float(mdd) * 100, 2),
                calmar=round(float(cagr) / abs(float(mdd)), 2) if mdd < 0 else None,
                n_days=int(len(r)))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()

    eqB, cal = load_track_b()
    rB = eqB.pct_change().dropna()                             # 轨B 日收益（2021-08-17 起，见上）
    P = build_panel(cal)
    LEGS, col = make_legs(cal, P)
    if a.smoke:
        LEGS = [L for L in LEGS if L["name"] in ("c_gold_bh", "c_gold_mom", "d_sh511010_bh", "a_mom20_K3", "f_stock_gold_mom1_abs")]
        log(f"[smoke] 仅跑 {len(LEGS)} 条腿")

    # FB3（轨C）生产净值（组合层 60% 主仓）
    fb3 = pd.read_csv(BASE / "short_v3_fund_slip20_equity.csv", parse_dates=["date"]).set_index("date")["value"]
    rF = fb3.pct_change().dropna()
    log(f"[FB3] 净值 {fb3.index[0].date()}→{fb3.index[-1].date()}（生产脚本 finalize_short_v3.py 产物）")

    rows = []
    colmap = {c: i for i, c in enumerate(P["codes"])}

    def leg_exec_info(L):
        """整手可执行性：按最常持仓标的的最小交易单位（100 份）核验本金 17 万 × 权重 ÷ 持仓数"""
        from collections import Counter
        tg = L["fn"](0)
        if not tg:
            return None
        cnt, ks = Counter(), []
        for di, cs in tg.items():
            cnt.update(cs); ks.append(max(1, len(cs)))
        k_med = int(np.median(ks))
        hot = [c for c, n in cnt.most_common(10) if n >= 0.2 * max(1, len(tg))] or [c for c, _ in cnt.most_common(5)]
        lots = []
        for c in hot[:6]:
            if c in colmap:
                px = float(P["CN"][-1, colmap[c]])
                lots.append({"code": c, "name": P["names"].get(c, ""), "px": round(px, 3),
                             "min_lot_cost": round(px * LOT * (1 + COMM), 1)})
        mx = max([x["min_lot_cost"] for x in lots], default=None)
        out = {"median_names": k_med, "hot_assets": lots, "max_min_lot_cost": mx}
        for w in (0.10, 0.15, 0.20):
            out[f"exec_{int(w*100)}pct"] = bool(mx is not None and (CASH0 * w / max(1, k_med)) >= mx)
        return out

    for L in LEGS:
        r = eval_leg(cal, P, L["fn"], L["name"])
        if r is None:
            log(f"  [skip] {L['name']}（无建仓）"); continue
        rets = r.pop("rets0")
        # 与轨B 同窗口对齐（日收益）
        idx = rets.index.intersection(rB.index).intersection(rF.index)
        rr, rb, rf = rets.reindex(idx), rB.reindex(idx), rF.reindex(idx)
        r["corr_B"] = round(float(np.corrcoef(rr, rb)[0, 1]), 3)
        r["corr_FB3"] = round(float(np.corrcoef(rr, rf)[0, 1]), 3)
        r["align_n"] = int(len(idx)); r["align_start"] = str(idx[0].date()); r["align_end"] = str(idx[-1].date())
        r["desc"], r["group"], r["assets"] = L["desc"], L["group"], L["assets"]
        r["exec"] = leg_exec_info(L)
        rows.append(r)
        log(f"  {r['leg']:26s} phmed {r['phmed_sharpe']:.3f} | slip50 {r['slip50_sharpe']} | "
            f"mdd {r['off0_mdd_pct']:6.1f}% | corrB {r['corr_B']:.3f} | corrFB3 {r['corr_FB3']:.3f} | "
            f"{r['align_start']}~{r['align_end']}({r['align_n']}d)")

    # ---------------- 组合层 ----------------
    blends = {}
    cand = [r for r in rows if r["corr_B"] <= GATES["corr_B_max"] and r["phmed_sharpe"] >= GATES["leg_phmed_min"]]
    cand.sort(key=lambda r: -r["phmed_sharpe"])
    focus = {r["leg"] for r in rows if r["corr_B"] <= GATES["corr_B_max"]}          # 过 corr 硬闸的全部腿
    focus |= {r["leg"] for r in sorted(rows, key=lambda x: -x["phmed_sharpe"])[:3]}  # + phmed 前三（对照）
    log(f"[组合层] 过 corr 硬闸 {sum(1 for r in rows if r['corr_B'] <= GATES['corr_B_max'])} 条；"
        f"其中 phmed≥{GATES['leg_phmed_min']} 的 {len(cand)} 条 → 进组合检验 {len(focus)} 条")

    # focus 腿的日收益在 eval 时已丢弃 → 这里按需重算（只跑 off0/20bp，成本低）
    LEGMAP = {L["name"]: L for L in LEGS}
    idx_all = rB.index.intersection(rF.index)
    base_stats = perf(0.60 * rF.reindex(idx_all) + 0.40 * rB.reindex(idx_all))
    log(f"[组合层] 基准 60% FB3 + 40% 轨B：年化 {base_stats['ann_pct']}% 夏普 {base_stats['sharpe']} "
        f"回撤 {base_stats['mdd_pct']}% Calmar {base_stats['calmar']}（{idx_all[0].date()}~{idx_all[-1].date()}，{len(idx_all)}d）")
    for leg in sorted(focus):
        L = LEGMAP[leg]
        s, tr, fb = simulate(cal, P, L["fn"](0), slip=SLIP_MAIN)
        rets = s.iloc[fb:].pct_change().dropna()
        idx = rets.index.intersection(idx_all)
        rl = rets.reindex(idx)
        rb = rB.reindex(idx); rf = rF.reindex(idx)
        base_w = perf(0.60 * rf + 0.40 * rb)                       # ⚠ 同窗口基准（511090 等短历史腿必须同窗对照）
        entry = {"leg": leg, "blend_window": [str(idx[0].date()), str(idx[-1].date())],
                 "base_on_window": base_w, "variants": {}}
        for w in (0.10, 0.15, 0.20):
            v = perf(0.60 * rf + (0.40 - w) * rb + w * rl)
            v["vs_base_sharpe"] = round(v["sharpe"] - base_w["sharpe"], 3)
            v["vs_base_ann_pct"] = round(v["ann_pct"] - base_w["ann_pct"], 2)
            pl = perf(0.60 * rf + (0.40 - w) * rb)                 # 安慰剂：换现金（只降风险不加资产）
            pl["vs_base_sharpe"] = round(pl["sharpe"] - base_w["sharpe"], 3)
            v["placebo_cash"] = pl
            entry["variants"][f"w{int(w*100)}"] = v
        entry["leg_standalone_on_blend_window"] = perf(rl)
        entry["exec"] = next((x["exec"] for x in rows if x["leg"] == leg), None)
        blends[leg] = entry
        log(f"  [{leg}] 基准同窗 S{base_w['sharpe']} | " + " | ".join(
            f"w{int(w*100)}: S{v['sharpe']}({v['vs_base_sharpe']:+.3f}) 年化{v['ann_pct']}% 回撤{v['mdd_pct']}% "
            f"[安慰剂S{v['placebo_cash']['sharpe']}]"
            for w, v in ((0.10, entry['variants']['w10']), (0.15, entry['variants']['w15']), (0.20, entry['variants']['w20']))))

    # ---------------- 稳健性：分段 + 逐年相关 + 卫星层（100% 轨B 内部替换） ----------------
    robust, satellite = {}, {}
    for leg in sorted(blends):
        L = LEGMAP[leg]
        s, tr, fb = simulate(cal, P, L["fn"](0), slip=SLIP_MAIN)
        rets = s.iloc[fb:].pct_change().dropna()
        idx = rets.index.intersection(idx_all)
        rl, rb = rets.reindex(idx), rB.reindex(idx)
        if len(idx) < 260:
            continue
        mid = idx[len(idx) // 2]
        halves = {}
        for tag, sl in (("h1", idx[idx < mid]), ("h2", idx[idx >= mid])):
            rf_s, rb_s, rl_s = rF.reindex(sl), rB.reindex(sl), rets.reindex(sl)
            b_s = perf(0.60 * rf_s + 0.40 * rb_s)["sharpe"]
            v_s = perf(0.60 * rf_s + 0.25 * rb_s + 0.15 * rl_s)["sharpe"]      # w15 检验
            halves[tag] = {"base_sharpe": b_s, "blend_sharpe": v_s, "delta": round(v_s - b_s, 3)}
        ycorr = {}
        for y in sorted(set(idx.year)):
            m = idx[idx.year == y]
            if len(m) >= 60:
                ycorr[int(y)] = round(float(np.corrcoef(rl.reindex(m), rb.reindex(m))[0, 1]), 3)
        robust[leg] = {"halves_w15": halves, "yearly_corr_B": ycorr}
        # 卫星层：直接替换「100% 押轨B」的一部分（用户目标场景：卫星 = 100% 轨B）
        if max(v["vs_base_sharpe"] for v in blends[leg]["variants"].values()) >= GATES["blend_sharpe_gain"]:
            sat = {f"w{int(w*100)}": {
                **perf((1 - w) * rb + w * rl),
                "vs_100B_sharpe": round(perf((1 - w) * rb + w * rl)["sharpe"] - perf(rb)["sharpe"], 3)}
                for w in (0.10, 0.15, 0.20, 0.30)}
            sat_halves = {}
            for tag, sl in (("h1", idx[idx < mid]), ("h2", idx[idx >= mid])):
                rb_s, rl_s = rB.reindex(sl), rets.reindex(sl)
                b_s = perf(rb_s)["sharpe"]
                for w in (0.20, 0.30):
                    v_s = perf((1 - w) * rb_s + w * rl_s)["sharpe"]
                    sat_halves[f"{tag}_w{int(w*100)}"] = round(v_s - b_s, 3)
            satellite[leg] = {"variants": sat, "halves_delta": sat_halves,
                              "note": "对照 = 卫星 100% 轨B（同窗口）"}
    log("[稳健性] 分段/逐年相关完成" + (f" | 卫星层检验 {list(satellite)}" if satellite else ""))

    # ---------------- 黄金收益打折敏感性（结论是否依赖 2021-26 黄金大牛？） ----------------
    drift_sens = {}
    if "c_gold_bh" in LEGMAP:
        L = LEGMAP["c_gold_bh"]
        s, tr, fb = simulate(cal, P, L["fn"](0), slip=SLIP_MAIN)
        gr = s.iloc[fb:].pct_change().dropna()
        gidx = gr.index.intersection(idx_all)
        rb0, rf0, rg0 = rB.reindex(gidx), rF.reindex(gidx), gr.reindex(gidx)
        base_b = perf(0.60 * rf0 + 0.40 * rb0)["sharpe"]
        for cut in (0, 4, 8, 12, 16):
            gc = rg0 - cut / 100.0 / ANN_BLEND
            drift_sens[f"cut{cut}pct"] = {
                "gold_ann_pct": round(float((1 + gc).prod() ** (ANN_BLEND / len(gc)) - 1) * 100, 2),
                "gold_sharpe": perf(gc)["sharpe"],
                "satellite_b_plus_gold20_delta": round(perf(0.8 * rb0 + 0.2 * gc)["sharpe"] - perf(rb0)["sharpe"], 3),
                "book_w8_delta": round(perf(0.60 * rf0 + 0.32 * rb0 + 0.08 * gc)["sharpe"] - base_b, 3),
                "book_w15_delta": round(perf(0.60 * rf0 + 0.25 * rb0 + 0.15 * gc)["sharpe"] - base_b, 3)}
        log("[敏感性] 黄金收益打折（0/4/8/12/16%年）→ book_w15 ΔS " +
            " ".join(f"{k}:{v['book_w15_delta']:+.3f}" for k, v in drift_sens.items()))

    out = {"meta": {
        "date": "2026-09-16", "stage": 2, "window": [str(cal[0].date()), str(cal[-1].date())],
        "rebal_days": REBAL, "phases": PHASES, "slip_main_bps": SLIP_MAIN * 1e4, "slip_stress_bps": SLIP_STRESS * 1e4,
        "cost_model": f"slip/边 + 佣金{COMM*1e4}bp(最低{MIN_COMM}元) + 卖出印花{TAX*1e4}bp（=冻结引擎口径）",
        "leg_sharpe_annualization": 252, "blend_sharpe_annualization": ANN_BLEND,
        "gates": GATES, "cash0": CASH0,
        "trackB": {"off0_ann_pct": _anchor_value(), "official_hist": 22.87,
                   "note": "冻结引擎 oss_super_combo_0913.py off0（软锚 engine_anchor.json）；窗口 " +
                   f"{eqB.index[0].date()}→{eqB.index[-1].date()}（面板 WARMUP=150 起）"},
        "data_gaps": ["无国债期货/期权/商品期货本地数据 → 未测（如实申报）",
                      "黄金只有 ETF 代理（518880/159934/159937）；场外金/金矿股未测",
                      "ETF 价格 = 腾讯 qfq 前复权重抓（etf_qfq_diff.json：核对 1454 只，105 只除权跳变>0.1%）",
                      "ETF 无 T+0 vs T+1 差异：全部按 T 收盘信号→T+1 开盘执行",
                      "货币/理财类 ETF（场内货币基金，价格长期钉在 100/低波，32 只）从动量/低波腿宇宙中排除：其本质是现金，纳入会使低波腿退化为现金且被调仓成本磨损"],
        "approx": ["组合层为日频再平衡近似（实际月频调仓会有偏差，量级 ±0.02 夏普内）",
                   "腿指标用 V.summary(√252)，组合层用 √244（与冻结引擎一致）——细微口径差已在 JSON 标注",
                   "相关性为 off0 相位的日收益皮尔逊相关，与阶段1 口径一致",
                   "511090（30年国债）2023-06 才上市 → 其统计窗口更短（JSON align_start）",
                   "开盘涨跌停守卫：买入遇开盘 ≥ 前收×1.098 跳过 / 卖出遇开盘 ≤ 前收×0.902 顺延（与冻结引擎一致）；"
                   "对 20% 涨跌幅的双创类 ETF 偏保守（会少买/晚卖）",
                   "BH 腿（黄金/国债）只有 1 次买入，故 50bp 档与 20bp 档几乎相同（换手≈0），不构成成本稳健性证据"]},
        "trackB_window": [str(rB.index[0].date()), str(rB.index[-1].date())],
        "fb3_window": [str(fb3.index[0].date()), str(fb3.index[-1].date())],
        "blend_base": base_stats, "n_legs": len(rows), "legs": rows, "blends": blends,
        "robustness": robust, "satellite_blend": satellite, "gold_drift_sensitivity": drift_sens}

    RES.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[done] {RES.name} 已落盘 | 腿 {len(rows)} 条 | 组合检验 {len(blends)} 条")

    # ---- 表格输出 ----
    print("\n腿名 | 相位中位夏普 | 50bp夏普 | 最大回撤 | corr vs 轨B | 过闸 | 可执行(10/15/20%仓整手)")
    for r in sorted(rows, key=lambda x: -x["phmed_sharpe"]):
        passed = r["corr_B"] <= GATES["corr_B_max"] and r["phmed_sharpe"] >= GATES["leg_phmed_min"]
        e = r.get("exec") or {}
        eflag = "/".join("Y" if e.get(f"exec_{w}pct") else "N" for w in (10, 15, 20))
        print(f"{r['leg']:26s} | {r['phmed_sharpe']:+.3f} | {str(r['slip50_sharpe']):>6s} | "
              f"{r['off0_mdd_pct']:7.1f}% | {r['corr_B']:+.3f} | {'PASS' if passed else '  - '} | {eflag}")


if __name__ == "__main__":
    main()
