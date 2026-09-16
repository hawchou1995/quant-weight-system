# -*- coding: utf-8 -*-
"""低相关策略挖掘 · 阶段3：时间结构轴（隔夜/日内/周期/波动结构/量价背离） —— 2026-09-16
================================================================================
背景：阶段1（同日股票面板内 2 因子全枚举 190 组）证明「同一面板换价量因子拿不到低相关」
      （与轨B 日相关最小 0.557，过闸 0 组）。阶段2 走跨资产（ETF/债/金）另有结论。
      本阶段第三次换轴：**时间结构**——隔夜 vs 日内分解、日内结构、周期效应、
      波动结构、量价背离。这些信息轴与「月度调仓的价量+估值」不同，最有希望低相关。
      全部由 OHLC 直接构造（零新增抓数）。

口径（与生产冻结引擎完全一致，勿改）：
  · 轨B 基准 = 生产冻结脚本 oss_super_combo_0913.py 前缀（composite/run_engine）off0 净值日收益
    （自检：off0 年化必须 = 22.87%，否则 ABORT）
  · 腿 = 同一 run_engine（Top20 / 20 日调仓 / T 收盘信号 → T+1 开盘执行 / ELIG3 域
    = 成交额20均≥300万 + 非ST + 上市≥150日 + 价>2元，且共用 sc1000 MA20 择时闸 + 高波半区半仓）
    → 腿与轨B **只差 alpha 信号**，执行/成本/域完全同源
  · 相位扫描 5 相位 offsets 0/4/8/12/16 → 报**相位中位夏普**（ADR-0006）
  · 双成本档：20bp（主，run_engine 默认 SLIP）/ 50bp（稳健，SLIP_STRESS）
  · 相关性 = 与 rB 的日收益皮尔逊相关，取日期交集（腿与轨B 同起 2021-08-17，索引天然对齐）
  · 组合层 = 轨B 换出 10/15/20pp 给候选腿（日频收益线性混合，资本分割近似）；
    安慰剂 = ①同点换现金（数学上 ΔSharpe≡0，仅作口径校验）②同点换**随机 Top20 腿**（200 个种子）

预注册闸门（**跑之前写死，禁止事后修改**）：
  G1 硬闸   corr vs 轨B ≤ 0.30
  G2 腿下限 相位中位夏普 ≥ 0.50 且 50bp 档夏普 ≥ 0.30
  G3 采纳线 组合层（卫星层：B 内部替换）夏普提升 ≥ +0.02 且 年化降幅 ≤ 1.0pp 且 Calmar 不降
  G4 稳健性 样本分半（前/后半段）符号一致（腿夏普两半均>0 且 ΔSharpe 两半均 ≥0）且 相位 min ≥ 0
  * 变体方向（hi/lo）显式枚举，不用 IC 自动定向（避免隐藏拟合）；38 变体多重检验已在 meta 申报

宇宙口径（2026-09-16 追加指令）：
  · **收紧到 A 股主板**：ELIG 选股域追加代码前缀过滤 sh60* / sz00*，排除 sz30*(创业板) /
    sh68*(科创板) / bj92*(北交所)。过滤同时作用于**腿与轨B**（run_engine 读全局 ELIG3），
    保证「腿 vs 轨B」同宇宙可比。
  · meta 申报 universe 与实际日均可选只数（median/mean）+ 前缀普查（census）。

产物：backtest/lowcorr_stage3_timestructure_0916.json
      （旧冒烟残留自动备份为 ..._partial_ballbackup.json；
        --universe all 控制组另存 ..._alluniverse_control.json）
用法：python backtest/lowcorr_stage3_timestructure_0916.py [--smoke] [--placebo N]
      [--universe mainboard|all] [--out PATH] [--diff-control PATH]
"""
import argparse
import json
import shutil
import sys
import time
import warnings
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OSS = BASE / "backtest" / "oss_0913"
RES = BASE / "backtest" / "lowcorr_stage3_timestructure_0916.json"
RES_BAK = BASE / "backtest" / "lowcorr_stage3_timestructure_0916_partial_ballbackup.json"
UNIVERSE_LABEL = {"mainboard": "mainboard(sh60|sz00)", "all": "all(frozen panel, no prefix filter)"}

import numpy as np                      # noqa: E402
import pandas as pd                     # noqa: E402

warnings.filterwarnings("ignore")

PHASES = [0, 4, 8, 12, 16]
REBAL, TOPN = 20, 20
SLIP_MAIN, SLIP_STRESS = 0.0020, 0.0050
ANN_ENGINE = 244.0                      # run_engine / 组合层年化因子（与冻结引擎一致）
GATES = dict(corr_B_max=0.30, phmed_sharpe_min=0.50, slip50_sharpe_min=0.30,
             blend_sharpe_gain=0.02, blend_ann_drop_pp=1.0)
# 附加腿（预注册）：若过 corr 硬闸的变体 ≥2 且来自 ≥2 个不同族 → 取各族最优等权 z 复合
COMPOSITE_RULE = "跨族等权 z 复合，每族只取 1 个（按相位中位夏普最高）"

t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:6.1f}s]", *a, flush=True)


# ============================================================ 0) 冻结引擎前缀 + 轨B 基准
def mainboard_mask(codes):
    """sh60*/sz00* 主板掩码。返回 (mask, census)。
    主板定义（A 股）：沪市 sh60x（600/601/603/605）、深市 sz00x（000/001/002/003）。
    排除：sz30x（创业板 300/301）、sh68x（科创板 688/689）、bj9x/4x/8x（北交所）。"""
    norm = [str(c).strip().lower()
            .replace("sh", "").replace("sz", "").replace("bj", "") for c in codes]
    is_mb = np.array([s.startswith("60") or s.startswith("00") for s in norm], dtype=bool)
    def pref3(s):
        return s[:3]
    from collections import Counter
    cnt_all = Counter(pref3(s) for s in norm)
    cnt_exc = Counter(pref3(s) for s, m in zip(norm, is_mb) if not m)
    census = {"n_codes": len(norm), "n_mainboard": int(is_mb.sum()),
              "n_excluded": int((~is_mb).sum()),
              "prefix3_census_all": dict(sorted(cnt_all.items())),
              "prefix3_census_excluded": dict(sorted(cnt_exc.items())),
              "mainboard_rule": "sh60*(600/601/603/605) | sz00*(000/001/002/003)",
              "excluded_rule": "sz30*(300/301 创业板) / sh68*(688/689 科创板) / bj92*(北交所)"}
    return is_mb, census


def load_engine(universe="mainboard"):
    """执行冻结前缀 → 全宇宙口径自检（22.87%）→ 按 universe 收紧 ELIG3 → 返回同宇宙轨B"""
    src = (OSS / "oss_super_combo_0913.py").read_text(encoding="utf-8")
    G = {}
    exec(src.split("comp = composite()")[0], G)          # noqa: S102 生产冻结前缀（口径已验证）

    # ---- 口径自检（**全宇宙** off0，官方 22.87%）----
    r_all = G["run_engine"](G["composite"](), TOPN, offset=0)
    ann_all = float(r_all["ann"]) * 100
    log(f"[轨B·全宇宙自检] off0 年化 {ann_all:.2f}%（官方 22.87%）| 夏普(√244) {r_all['sharpe']:.3f} | "
        f"回撤 {r_all['mdd']*100:.1f}% | 净值 {r_all['equity'].index[0].date()}→"
        f"{r_all['equity'].index[-1].date()}（{len(r_all['equity'])}d）")
    if abs(ann_all - 22.87) > 0.5:
        log(f"[ABORT] 轨B 复现年化 {ann_all:.2f}% ≠ 官方 22.87% → 口径未对齐，拒绝出结论")
        sys.exit(2)

    # ---- universe 收紧（腿与轨B 同时生效，保证同宇宙可比）----
    mb, census = mainboard_mask(G["codes"])
    elig_all = G["ELIG3"].copy()
    elig_mb = elig_all & mb[None, :]
    n_elig_all = elig_all.sum(axis=1)
    n_elig_mb = elig_mb.sum(axis=1)
    census["eligible_in_panel"] = int(mb.sum())
    census["excluded_had_data"] = int(elig_all[:, ~mb].any()) if (~mb).any() else 0
    log(f"[universe] 面板 {census['n_codes']} 只 | 主板 {census['n_mainboard']} | 排除 "
        f"{census['n_excluded']} {census['prefix3_census_excluded'] or ''}")

    if universe == "mainboard":
        G["ELIG3"] = elig_mb
        # volpct 依赖 ELIG3 域（高波半区半仓用）→ 必须按新域重算，否则域内生变
        ret1 = pd.DataFrame(G["close_ff"]).pct_change()
        v20f = (-ret1.rolling(20, min_periods=15).std()).to_numpy()
        G["volpct"] = pd.DataFrame(np.where(G["ELIG3"], v20f, np.nan)) \
            .rank(axis=1, pct=True).to_numpy()
        log("[universe] ELIG3 已收紧至主板，volpct 已按新域重算")
    else:
        log("[universe] 未过滤（控制组 = 冻结面板原域）")

    aud = {
        "universe": UNIVERSE_LABEL[universe], "mode": universe,
        "filter_applied_to": "腿(alpha) 与 轨B(composite) 同时生效（run_engine 读全局 ELIG3）",
        "elig_daily_median_pre_filter": int(np.median(n_elig_all)),
        "elig_daily_mean_pre_filter": round(float(n_elig_all.mean()), 1),
        "elig_daily_median": int(np.median(n_elig_mb)),
        "elig_daily_mean": round(float(n_elig_mb.mean()), 1),
        "elig_daily_min": int(n_elig_mb.min()), "elig_daily_max": int(n_elig_mb.max()),
        "elig_days_below_topn": int((n_elig_mb < TOPN).sum()),
        "prefix_filter_bitwise_noop": bool(np.array_equal(elig_all, elig_mb)),
        "prefix_filter_is_noop_note":
            "若 bitwise_noop=True → 冻结面板本身已无 sz30*/sh68*/bj92* 标的，前缀过滤在数学上是恒等变换，"
            "「含非主板 vs 仅主板」两版结果应逐位相同（see --universe all 控制组）",
        **census,
    }
    # 至少保留 TOPN 只有效可选日（否则 run_engine 不动仓，腿退化为空转）
    if aud["elig_days_below_topn"] > 0:
        log(f"[warn] 主板域下 {aud['elig_days_below_topn']} 天可选 < TopN={TOPN}")

    r_mb = G["run_engine"](G["composite"](), TOPN, offset=0)
    annB = float(r_mb["ann"]) * 100
    log(f"[轨B·当前宇宙={universe}] off0 年化 {annB:.2f}% | 夏普 {r_mb['sharpe']:.3f} | "
        f"回撤 {r_mb['mdd']*100:.1f}% | 日均可选 {aud['elig_daily_mean']}（中位 "
        f"{aud['elig_daily_median']}）只")
    rB = r_mb["equity"].pct_change().dropna()
    return G, rB, r_mb, annB, aud


# ============================================================ 1) 时间结构因子构造
def build_factors(G):
    """全部由 OHLC/vol/amount 直接构造；返回 {族: [(name, 矩阵, 说明)]}"""
    O, H, L, C = (G["O"].astype(np.float64), G["H"].astype(np.float64),
                  G["L"].astype(np.float64), G["C"].astype(np.float64))
    V, AMT = G["V"].astype(np.float64), G["AMT"].astype(np.float64)
    close_ff, Cprev = G["close_ff"], G["Cprev"]
    ND, NC = C.shape
    cal = pd.DatetimeIndex([pd.Timestamp(str(d)[:10]) for d in G["cal"]])

    traded = np.isfinite(O) & np.isfinite(C) & (O > 0) & (C > 0)
    tprev = np.vstack([np.zeros((1, NC), bool), traded[:-1]])
    with np.errstate(all="ignore"):
        gap = np.where(traded & tprev & (Cprev > 0), O / np.where(Cprev > 0, Cprev, np.nan) - 1, np.nan)
        intra = np.where(traded, C / np.where(O > 0, O, np.nan) - 1, np.nan)
        dret = np.where(traded & (Cprev > 0), C / np.where(Cprev > 0, Cprev, np.nan) - 1, np.nan)
    gap = np.clip(gap, -0.5, 0.5); intra = np.clip(intra, -0.5, 0.5); dret = np.clip(dret, -0.5, 0.5)
    # 隔夜/日内分解用域：前一日必须有交易（否则「隔夜」跨多日停牌 → 污染）
    onf = traded & tprev & (Cprev > 0)
    log(f"[因子] 隔夜样本占有率 {np.nanmean(onf):.3f} | 日内 {np.nanmean(traded):.3f}")

    def rmean(a, w, mp):
        return pd.DataFrame(a).rolling(w, min_periods=mp).mean().to_numpy()

    def rstd(a, w, mp):
        return pd.DataFrame(a).rolling(w, min_periods=mp).std(ddof=0).to_numpy()

    def rcorr(x, y, w, mp):
        mx, my = rmean(x, w, mp), rmean(y, w, mp)
        cxy = rmean(x * y, w, mp) - mx * my
        vx = np.maximum(rmean(x * x, w, mp) - mx * mx, 0.0)
        vy = np.maximum(rmean(y * y, w, mp) - my * my, 0.0)
        return cxy / (np.sqrt(vx * vy) + 1e-12)

    def cond_mean(x, mask1d, w, min_occ):
        """条件均值：只在 mask 命中的交易日上对 20 日窗求均值（逐股同 mask）"""
        mm = mask1d[:, None] & np.isfinite(x)
        num = pd.DataFrame(np.where(mm, x, 0.0)).rolling(w, min_periods=w).sum().to_numpy()
        den = pd.DataFrame(mm.astype(np.float64)).rolling(w, min_periods=w).sum().to_numpy()
        return np.where(den >= min_occ, num / np.maximum(den, 1.0), np.nan)

    F = {}

    # ---------- 族1 隔夜 vs 日内分解 ----------
    on20, id20 = rmean(gap, 20, 15), rmean(intra, 20, 15)
    F["F1"] = [
        ("on20", on20, "20日隔夜收益均值（累积等价）"),
        ("id20", id20, "20日日内收益均值（累积等价）"),
        ("onid_spread20", on20 - id20, "20日 隔夜−日内 均值差"),
        ("onid_spread60", rmean(gap, 60, 40) - rmean(intra, 60, 40), "60日 隔夜−日内 均值差"),
    ]

    # ---------- 族2 日内结构 ----------
    hl = H - L
    clv = np.where(hl > 0, (C - L) / np.where(hl > 0, hl, np.nan), 0.5)
    clv = np.where(traded, clv, np.nan)
    F["F2"] = [
        ("clv20", rmean(clv, 20, 15), "20日 收盘位置(close-low)/(high-low) 均值＝尾盘强度代理"),
        ("gapcont20", rcorr(gap, intra, 20, 15), "20日 corr(隔夜gap, 日内收益)＝跳空延续(+)/反转(−)"),
        ("gapabs20", rmean(np.abs(gap), 20, 15), "20日 平均|gap|＝跳空幅度"),
    ]

    # ---------- 族3 周期效应（逐股条件均值） ----------
    dow = np.asarray(cal.weekday)
    mon, fri = (dow == 0), (dow == 4)
    ym = cal.year * 100 + cal.month
    s = pd.Series(np.arange(ND))
    idx_in = s.groupby(ym).cumcount().to_numpy(); tot = s.groupby(ym).transform("count").to_numpy()
    mstart, mend = (idx_in < 3), ((tot - 1 - idx_in) < 3)
    dg = np.diff(cal.values).astype("timedelta64[D]").astype(int)
    gapdays = np.concatenate([[3], dg])
    postlb = gapdays >= 4                       # 长假后首个交易日
    prelb = np.zeros(ND, bool); prelb[:-1] = postlb[1:]   # 长假前最后交易日
    log(f"[因子] 周期 mask：周一 {mon.sum()} 周五 {fri.sum()} 月初 {mstart.sum()} 月末 {mend.sum()} "
        f"长假前 {prelb.sum()} 长假后 {postlb.sum()}（gap≥4 日历日）")
    m60, m120 = 60, 120
    F["F3"] = [
        ("mon60", cond_mean(dret, mon, m60, 8), "个股 60日内 周一 平均收益"),
        ("fri60", cond_mean(dret, fri, m60, 8), "个股 60日内 周五 平均收益"),
        ("mend60", cond_mean(dret, mend, m60, 6), "个股 60日内 月末3日 平均收益"),
        ("mstart60", cond_mean(dret, mstart, m60, 6), "个股 60日内 月初3日 平均收益"),
        ("prehol120", cond_mean(dret, prelb, m120, 2), "个股 120日内 长假前最后交易日 平均收益"),
        ("posthol120", cond_mean(dret, postlb, m120, 2), "个股 120日内 长假后首个交易日 平均收益"),
    ]

    # ---------- 族4 波动结构 ----------
    onv, idv = rstd(gap, 20, 15), rstd(intra, 20, 15)
    amp = np.where((Cprev > 0) & traded, (H - L) / np.where(Cprev > 0, Cprev, np.nan), np.nan)
    ampm = rmean(amp, 20, 15)
    F["F4"] = [
        ("on_id_vol20", onv / (idv + 1e-8), "20日 隔夜波动 / 日内波动"),
        ("on_id_vol60", rstd(gap, 60, 40) / (rstd(intra, 60, 40) + 1e-8), "60日 隔夜波动 / 日内波动"),
        ("ampcv20", rstd(amp, 20, 15) / (ampm + 1e-8), "20日 振幅变异系数＝振幅稳定性(越低越稳)"),
    ]

    # ---------- 族5 量价背离 ----------
    cmax = pd.DataFrame(np.where(traded, C, np.nan)).rolling(20, min_periods=15).max().to_numpy()
    vmax = pd.DataFrame(np.where(traded, V, np.nan)).rolling(20, min_periods=15).max().to_numpy()
    ratio = np.where((V > 0) & (C > 0) & np.isfinite(AMT) & traded, AMT / (V * C), np.nan)
    lr = np.log(np.where(ratio > 0, ratio, np.nan))
    F["F5"] = [
        ("pvdiv20", C / (cmax + 1e-12) - V / (vmax + 1e-12), "价格20日新高 − 量20日新高（背离）"),
        ("vwapdrift20", lr - pd.DataFrame(lr).shift(20).to_numpy(),
         "20日 (amount/volume)/close 漂移＝收盘相对 VWAP 的漂移"),
        ("vwappos20", lr - rmean(lr, 60, 40), "当前 (amount/volume)/close 相对 60 日基线偏离"),
    ]

    out = {}
    for fam, lst in F.items():
        for nm, m, desc in lst:
            out[nm] = (np.asarray(m, dtype=np.float32), desc)
    log(f"[因子] 共 {len(out)} 个基因子（{len(F)} 族）")
    return out, dict(prelb_count=int(prelb.sum()), postlb_count=int(postlb.sum()))


# ============================================================ 2) 单腿评估
def zcomp(mat, ELIG3):
    """域内横截面 z（±3 clip）——与冻结 composite() 同口径"""
    a = np.where(ELIG3, mat.astype(np.float64), np.nan)
    mu = np.nanmean(a, axis=1, keepdims=True); sd = np.nanstd(a, axis=1, keepdims=True)
    return np.clip((a - mu) / (sd + 1e-12), -3, 3)


def eval_leg(G, ELIG3, comp, name, smoke=False):
    per, shs = {}, []
    offs = PHASES[:2] if smoke else PHASES
    for off in offs:
        m = G["run_engine"](comp, TOPN, offset=off)
        per[off] = m; shs.append(float(m["sharpe"]))
    o0 = per[0]
    m50 = G["run_engine"](comp, TOPN, offset=0, slip=SLIP_STRESS)
    rets = o0["equity"].pct_change().dropna()
    return dict(leg=name, phmed_sharpe=float(np.median(shs)), sharpe_min=float(np.min(shs)),
                sharpe_max=float(np.max(shs)),
                phase_sharpes={str(k): round(v["sharpe"], 4) for k, v in per.items()},
                slip50_sharpe=float(m50["sharpe"]), off0_ann_pct=float(o0["ann"]) * 100,
                off0_sharpe=float(o0["sharpe"]), off0_mdd_pct=float(o0["mdd"]) * 100,
                n_trades=int(o0["n_trades"]), win=float(o0["win"]),
                by_year_pct={int(y): round(float(g.iloc[-1] / g.iloc[0] - 1) * 100, 1)
                             for y, g in o0["equity"].groupby(o0["equity"].index.year)},
                rets=rets)


def perf(r, ann=ANN_ENGINE):
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


# ============================================================ 3) 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--placebo", type=int, default=200)
    ap.add_argument("--universe", choices=["mainboard", "all"], default="mainboard",
                    help="mainboard=追加 sh60*/sz00* 前缀过滤（默认）；all=冻结面板原域（控制组）")
    ap.add_argument("--out", type=str, default=None, help="产物路径（默认 RES）")
    ap.add_argument("--diff-control", type=str, default=None,
                    help="另一 universe 的产物 JSON 路径 → 把逐腿数值差注入 meta.universe_audit")
    a = ap.parse_args()
    OUT = Path(a.out) if a.out else RES
    if OUT.resolve() == RES.resolve() and RES.exists() and not RES_BAK.exists():
        shutil.copy2(RES, RES_BAK)                       # 旧（中断的冒烟残留）备份，便于对照
        log(f"[备份] 旧产物 → {RES_BAK.name}")

    G, rB, rBfull, annB, uni_aud = load_engine(a.universe)
    ELIG3 = G["ELIG3"]
    cal = G["cal"]
    gate_open = np.isfinite(G["ma20sc"]) & (G["sc1000"] > G["ma20sc"])       # 生产择时闸状态

    FAM, hol = build_factors(G)
    families = {"F1": "隔夜/日内分解", "F2": "日内结构", "F3": "周期效应",
                "F4": "波动结构", "F5": "量价背离"}
    FAM_MEMBERS = {"F1": ["on20", "id20", "onid_spread20", "onid_spread60"],
                   "F2": ["clv20", "gapcont20", "gapabs20"],
                   "F3": ["mon60", "fri60", "mend60", "mstart60", "prehol120", "posthol120"],
                   "F4": ["on_id_vol20", "on_id_vol60", "ampcv20"],
                   "F5": ["pvdiv20", "vwapdrift20", "vwappos20"]}
    fam_of = {nm: fk for fk, lst in FAM_MEMBERS.items() for nm in lst}
    FAM_LEN = {fk: 2 * len(lst) for fk, lst in FAM_MEMBERS.items()}      # ×2 = hi/lo 双向
    assert set(fam_of) == set(FAM), set(fam_of) ^ set(FAM)

    variants = []
    for nm, (mat, desc) in FAM.items():
        variants.append((f"{nm}_hi", mat, f"[{fam_of[nm]}] {desc}（高值做多）"))
        variants.append((f"{nm}_lo", -mat, f"[{fam_of[nm]}] {desc}（低值做多）"))
    variants.sort(key=lambda x: x[0])
    if a.smoke:
        keep = {"on20_hi", "on20_lo", "clv20_hi", "mon60_hi"}
        variants = [v for v in variants if v[0] in keep]
    log(f"[枚举] {len(variants)} 个变体 × ({len(PHASES)} 相位 + 50bp) = "
        f"{len(variants)*(len(PHASES)+1)} 次 run_engine")
    if a.smoke:
        log("[smoke] 仅跑各族代表变体 × 前 2 相位 —— 结果**不完整**，不得据此下结论")

    META = {
        "date": "2026-09-16", "stage": 3, "axis": "时间结构（隔夜/日内/周期/波动结构/量价背离）",
        "window": [str(pd.Timestamp(str(cal[0])[:10]).date()), str(pd.Timestamp(str(cal[-1])[:10]).date())],
        "rebal_days": REBAL, "topn": TOPN, "phases": PHASES,
        "slip_main_bps": SLIP_MAIN * 1e4, "slip_stress_bps": SLIP_STRESS * 1e4,
        "cost_model": "冻结引擎 run_engine（slip/边 + 佣金2.5bp(最低5元) + 卖出印花5bp）",
        "sharpe_annualization": ANN_ENGINE, "gates": GATES,
        "universe": UNIVERSE_LABEL[a.universe],
        "universe_audit": uni_aud,
        "trackB": {"off0_ann_pct": round(annB, 2), "official_full_universe": 22.87,
                   "note": "冻结脚本 oss_super_combo_0913.py 前缀 + run_engine(composite(),20,offset=0)，"
                           "在**当前 universe 域**内重算；全宇宙口径自检见 universe_audit"},
        "n_variants": len(variants), "families": families, "composite_rule": COMPOSITE_RULE,
        "holiday_mask": hol, "smoke": bool(a.smoke),
    }
    META["data_gaps"] = [
        "无分钟/tick 数据 → 尾盘强度用 CLV 代理、日内分布用 amount/volume(VWAP) 代理，非真实分时",
        "冻结面板 oss_panel_0913.pkl 前缀普查见 universe_audit.prefix3_census_all："
        "本身已只含 000/001/002/003/600/601/603/605 系（主板），无 sz30*/sh68*/bj92* → "
        "主板前缀过滤为恒等变换（bitwise noop），「含非主板 vs 仅主板」对照由 --universe all 给出",
        "长假只能由交易日历 gap≥4 日历日推断 → 单日假期（如某些调休）漏检，prehol/posthol 覆盖不全",
    ]
    META["approx"] = [
        "amount/volume = **原始未复权** VWAP，而 OHLC 为前复权 → 量价类因子(F5)用「比率对自身基线归一」处理，"
        "除权日仍有跳变噪声（F5 结论须打折看）",
        "周期效应为逐股条件均值，样本极少（周一≈12/60日、长假前≈2/120日）→ 噪声主导，属探索性",
        "腿与轨B 共用 sc1000 MA20 择时闸 + 高波半区半仓 → 现金段同相位；已给闸开/闸关分组相关做对照",
        "组合层为日频收益线性混合（资本分割近似），非逐笔资金重放",
        "变体方向 hi/lo 显式枚举 + %d 变体 = 多重检验，未过闸结论按『分布下界』解读而非单点最优"
        % len(variants),
        "腿从 WARMUP=150 起评（2021-08-17），与轨B 同窗口；相位中位夏普为 5 相位的稳健中心而非最优相位",
    ]

    def dump(status, done_fams, tail=None):
        """增量落盘（每完成一个族调用一次）——会话中断也不丢已跑结果"""
        payload = {"meta": {**META, "status": status, "families_done": done_fams},
                   "n_legs": len(rows), "legs": [{k: v for k, v in r.items() if k != "rets"} for r in rows]}
        if tail:
            payload.update(tail)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    rows = []
    done_fams = []
    ordered = [v for fk in sorted(FAM_MEMBERS) for v in variants
               if fam_of[v[0].rsplit("_", 1)[0]] == fk]
    assert len(ordered) == len(variants), "族分组后变体数不符"
    for i, (nm, mat, desc) in enumerate(ordered, 1):
        comp = zcomp(mat, ELIG3)
        r = eval_leg(G, ELIG3, comp, nm, smoke=a.smoke)
        rets = r.pop("rets")
        idx = rets.index.intersection(rB.index)
        rr, rb = rets.reindex(idx), rB.reindex(idx)
        r["corr_B"] = round(float(np.corrcoef(rr, rb)[0, 1]), 3)
        r["align_n"] = int(len(idx))
        r["align_start"], r["align_end"] = str(idx[0].date()), str(idx[-1].date())
        # 闸门开/关分组相关（检查低相关是否靠择时错位偷来的）
        gd = pd.Series(gate_open, index=pd.DatetimeIndex([pd.Timestamp(str(d)[:10]) for d in cal])).reindex(idx)
        for tag, sel in (("on", gd.to_numpy()), ("off", ~gd.to_numpy())):
            if sel.sum() >= 60:
                r[f"corr_B_gate{tag}"] = round(float(np.corrcoef(rr[sel], rb[sel])[0, 1]), 3)
        r["desc"] = desc; r["family"] = fam_of[nm.rsplit("_", 1)[0]]; r["base_factor"] = nm.rsplit("_", 1)[0]
        r["pass_G1"] = bool(r["corr_B"] <= GATES["corr_B_max"])
        r["pass_G2"] = bool(r["phmed_sharpe"] >= GATES["phmed_sharpe_min"]
                            and r["slip50_sharpe"] >= GATES["slip50_sharpe_min"])
        r["pass_G4a"] = bool(r["sharpe_min"] >= 0)
        r["pass_G1G2G4a"] = bool(r["pass_G1"] and r["pass_G2"] and r["pass_G4a"])
        rows.append(r)
        log(f"  [{i}/{len(ordered)}] {nm:16s} phmed {r['phmed_sharpe']:+.3f} | 50bp {r['slip50_sharpe']:+.3f} | "
            f"mdd {r['off0_mdd_pct']:6.1f}% | corrB {r['corr_B']:+.3f} "
            f"(闸开 {r.get('corr_B_gateon')} / 闸关 {r.get('corr_B_gateoff')}) | "
            f"{'PASS' if r['pass_G1G2G4a'] else ' -  '}")
        # 每完成一个族即落盘
        fk = r["family"]
        if fk not in done_fams and all(x["family"] == fk for x in rows[-FAM_LEN[fk]:]):
            done_fams.append(fk)
            dump(f"partial: family {fk} done ({len(rows)}/{len(ordered)} legs)",
                 list(done_fams))
            log(f"  [落盘] 族 {fk} 完成 → {OUT.name}（{len(rows)}/{len(ordered)} 腿）")

    rows.sort(key=lambda r: r["corr_B"])
    log(f"\n[corr 分布] min {rows[0]['corr_B']:+.3f} ({rows[0]['leg']}) | "
        f"p10 {np.percentile([r['corr_B'] for r in rows], 10):+.3f} | "
        f"中位 {np.median([r['corr_B'] for r in rows]):+.3f} | max {rows[-1]['corr_B']:+.3f}")

    cand = [r for r in rows if r["pass_G1G2G4a"]]
    log(f"[闸门] 过 G1(相关)+G2(腿)+G4a(相位min) 的变体 {len(cand)} 个: {[r['leg'] for r in cand]}")

    # ---------------- 附加腿：跨族等权 z 复合（预注册规则） ----------------
    comp_legs = {}
    if len(cand) >= 2:
        bestf = {}
        for r in sorted(cand, key=lambda x: -x["phmed_sharpe"]):
            bestf.setdefault(r["family"], r["leg"])
        if len(bestf) >= 2:
            keys = list(bestf.values())[:3]
            log(f"[复合] 跨族复合 {keys}（{COMPOSITE_RULE}）")
            zs = []
            for k in keys:
                bf, dirn = k.rsplit("_", 1)
                m = FAM[bf][0].astype(np.float64) * (1.0 if dirn == "hi" else -1.0)
                zs.append(zcomp(m, ELIG3))
            comp = np.nanmean(np.stack(zs), axis=0)
            comp_legs["composite_crossfamily"] = (comp, f"[COMP] 跨族等权 z 复合 {keys}")
            r = eval_leg(G, ELIG3, comp, "composite_crossfamily", smoke=a.smoke)
            rets = r.pop("rets")
            idx = rets.index.intersection(rB.index)
            rr, rb = rets.reindex(idx), rB.reindex(idx)
            r["corr_B"] = round(float(np.corrcoef(rr, rb)[0, 1]), 3)
            r["align_n"] = int(len(idx)); r["align_start"] = str(idx[0].date()); r["align_end"] = str(idx[-1].date())
            r["desc"] = comp_legs["composite_crossfamily"][1]; r["family"] = "COMP"
            r["base_factor"] = "composite"; r["composite_members"] = keys
            r["pass_G1"] = bool(r["corr_B"] <= GATES["corr_B_max"])
            r["pass_G2"] = bool(r["phmed_sharpe"] >= GATES["phmed_sharpe_min"]
                                and r["slip50_sharpe"] >= GATES["slip50_sharpe_min"])
            r["pass_G4a"] = bool(r["sharpe_min"] >= 0)
            r["pass_G1G2G4a"] = bool(r["pass_G1"] and r["pass_G2"] and r["pass_G4a"])
            log(f"  [COMP] phmed {r['phmed_sharpe']:+.3f} | 50bp {r['slip50_sharpe']:+.3f} | "
                f"corrB {r['corr_B']:+.3f} | {'PASS' if r['pass_G1G2G4a'] else ' -  '}")
            rows.append(r); comp_legs["composite_crossfamily"] = (comp, r["desc"])

    # ---------------- 组合层（卫星层：轨B 内部替换） ----------------
    blend_report, halves, placebo = {}, {}, {}
    base_all = perf(rB)
    log(f"[组合层] 基准 100% 轨B：年化 {base_all['ann_pct']}% 夏普 {base_all['sharpe']} "
        f"回撤 {base_all['mdd_pct']}% Calmar {base_all['calmar']}（{rB.index[0].date()}~{rB.index[-1].date()}）")

    finalists = [r for r in rows if r["pass_G1"]]               # 至少过 corr 硬闸
    finalists.sort(key=lambda r: -r["phmed_sharpe"])
    focus = finalists[:12] if len(finalists) > 12 else finalists
    if not focus:                                                # 无过闸者也给 corr 最小的 3 条做参考
        focus = sorted(rows, key=lambda r: r["corr_B"])[:3]
    LEGMAP = {nm: mat for nm, mat, _ in variants}
    LEGMAP["composite_crossfamily"] = comp_legs.get("composite_crossfamily", (None, None))[0]

    for r in focus:
        nm = r["leg"]
        comp = LEGMAP[nm]
        m0 = G["run_engine"](comp, TOPN, offset=0)
        rets = m0["equity"].pct_change().dropna()
        idx = rets.index.intersection(rB.index)
        rl, rb = rets.reindex(idx), rB.reindex(idx)
        bw = perf(rb)
        entry = {"leg": nm, "family": r["family"], "desc": r["desc"], "corr_B": r["corr_B"],
                 "base_100B": bw, "leg_on_window": perf(rl), "variants": {}}
        for w in (0.10, 0.15, 0.20):
            v = perf((1 - w) * rb + w * rl)
            v["d_sharpe"] = round(v["sharpe"] - bw["sharpe"], 3)
            v["d_ann_pp"] = round(v["ann_pct"] - bw["ann_pct"], 2)
            v["d_calmar"] = round((v["calmar"] or 0) - (bw["calmar"] or 0), 2)
            v["gate_G3"] = bool(v["d_sharpe"] >= GATES["blend_sharpe_gain"]
                                and v["d_ann_pp"] >= -GATES["blend_ann_drop_pp"]
                                and (v["calmar"] or 0) >= (bw["calmar"] or 0))
            entry["variants"][f"w{int(w*100)}"] = v
        # 安慰剂①：同点换现金（数学上 ΔSharpe ≡ 0，仅口径校验）
        pl_cash = {f"w{int(w*100)}": {**perf((1 - w) * rb),
                                      "d_sharpe": round(perf((1 - w) * rb)["sharpe"] - bw["sharpe"], 3)}
                   for w in (0.10, 0.15, 0.20)}
        entry["placebo_cash"] = pl_cash
        blend_report[nm] = entry
        log(f"  [{nm}] 同窗基准 S{bw['sharpe']} | " + " | ".join(
            f"w{int(w*100)}: S{v['sharpe']}({v['d_sharpe']:+.3f}) 年化{v['ann_pct']}%({v['d_ann_pp']:+.2f}pp) "
            f"Calmar{v['calmar']}({v['d_calmar']:+.2f}){'✓' if v['gate_G3'] else '✗'}"
            for w, v in ((10, entry['variants']['w10']), (15, entry['variants']['w15']),
                         (20, entry['variants']['w20']))))

        # 分半稳健性
        if len(idx) >= 260:
            mid = idx[len(idx) // 2]
            h = {}
            for tag, sl in (("h1", idx[idx < mid]), ("h2", idx[idx >= mid])):
                rl_s, rb_s = rets.reindex(sl), rB.reindex(sl)
                b_s, v_s = perf(rb_s), perf(0.85 * rb_s + 0.15 * rl_s)
                h[tag] = {"leg_sharpe": perf(rl_s)["sharpe"], "base_sharpe": b_s["sharpe"],
                          "w15_sharpe": v_s["sharpe"], "d_sharpe": round(v_s["sharpe"] - b_s["sharpe"], 3),
                          "corr_B": round(float(np.corrcoef(rl_s, rb_s)[0, 1]), 3),
                          "window": [str(sl[0].date()), str(sl[-1].date())]}
            h["sign_consistent"] = bool(h["h1"]["d_sharpe"] >= 0 and h["h2"]["d_sharpe"] >= 0
                                        and h["h1"]["leg_sharpe"] > 0 and h["h2"]["leg_sharpe"] > 0)
            h["verdict"] = ("符号一致(两半 ΔS≥0 且腿夏普>0)" if h["sign_consistent"] else "符号不一致")
            halves[nm] = h
            log(f"    [分半 {nm}] h1 ΔS {h['h1']['d_sharpe']:+.3f} (腿S {h['h1']['leg_sharpe']:.2f}, "
                f"corr {h['h1']['corr_B']:.3f}) | h2 ΔS {h['h2']['d_sharpe']:+.3f} "
                f"(腿S {h['h2']['leg_sharpe']:.2f}, corr {h['h2']['corr_B']:.3f}) → {h['verdict']}")

    # ---------------- 安慰剂②：同点换随机 Top20 腿（N 种子） ----------------
    if a.placebo > 0:
        rng = np.random.default_rng(20260916)
        base_w_sharpe = perf(rB)["sharpe"]
        ds = []
        t_pl = time.time()
        for i in range(a.placebo):
            cr = np.where(ELIG3, rng.standard_normal(ELIG3.shape), np.nan)
            mm = G["run_engine"](cr, TOPN, offset=0)
            rr = mm["equity"].pct_change().dropna()
            ii = rr.index.intersection(rB.index)
            v = perf(0.85 * rB.reindex(ii) + 0.15 * rr.reindex(ii))
            ds.append(round(v["sharpe"] - perf(rB.reindex(ii))["sharpe"], 4))
        ds = np.array(ds)
        placebo = {"n": a.placebo, "w": 0.15, "secs": round(time.time() - t_pl, 1),
                   "rand_d_sharpe_mean": round(float(ds.mean()), 4),
                   "rand_d_sharpe_median": round(float(np.median(ds)), 4),
                   "rand_d_sharpe_p90": round(float(np.percentile(ds, 90)), 4),
                   "rand_d_sharpe_p95": round(float(np.percentile(ds, 95)), 4),
                   "rand_d_sharpe_max": round(float(ds.max()), 4),
                   "rand_d_sharpe_min": round(float(ds.min()), 4),
                   "rand_frac_d_ge_0.02": round(float((ds >= 0.02).mean()), 4),
                   "note": "随机 Top20 腿（ELIG3 域内均匀随机的 alpha 信号）经同一 run_engine 跑出"}
        for nm, e in blend_report.items():
            dv = e["variants"]["w15"]["d_sharpe"]
            placebo.setdefault("candidate_percentile", {})[nm] = {
                "d_sharpe": dv, "pct_of_random": round(float((ds < dv).mean() * 100), 1)}
        log(f"[安慰剂②] 随机腿 n={a.placebo} ΔS 中位 {placebo['rand_d_sharpe_median']:+.4f} "
            f"p95 {placebo['rand_d_sharpe_p95']:+.4f} | ≥+0.02 占比 {placebo['rand_frac_d_ge_0.02']:.1%} "
            f"| 候选超越分位 " + " ".join(f"{k}:{v['pct_of_random']}%" for k, v in
                                          placebo.get("candidate_percentile", {}).items()))

    # ---------------- 落盘 ----------------
    for r in rows:
        r.pop("rets", None)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    # 控制组对照（含非主板 vs 仅主板）：逐腿数值差
    if a.diff_control:
        cp = Path(a.diff_control)
        if cp.exists():
            ctl = json.loads(cp.read_text(encoding="utf-8"))
            ctl_legs = {l["leg"]: l for l in ctl.get("legs", [])}
            keys = [k for k in ("phmed_sharpe", "sharpe_min", "slip50_sharpe", "corr_B",
                                "off0_ann_pct", "off0_sharpe", "off0_mdd_pct", "n_trades")]
            deltas = {}
            for r in rows:
                c = ctl_legs.get(r["leg"])
                if not c:
                    continue
                deltas[r["leg"]] = {k: round(float(r[k]) - float(c[k]), 8) for k in keys
                                    if isinstance(r.get(k), (int, float)) and isinstance(c.get(k), (int, float))}
            flat = [v for d in deltas.values() for v in d.values()]
            uni_aud["control_all_universe"] = {
                "control_json": cp.name,
                "control_universe": ctl.get("meta", {}).get("universe"),
                "control_trackB_off0_ann_pct": ctl.get("meta", {}).get("trackB", {}).get("off0_ann_pct"),
                "n_legs_compared": len(deltas),
                "max_abs_delta": round(float(max(abs(x) for x in flat)), 8) if flat else None,
                "deltas_by_leg": deltas,
                "verdict": ("逐位相同：前缀过滤为恒等变换 → 「含非主板 vs 仅主板」无差异（面板本已全主板）"
                            if flat and max(abs(x) for x in flat) < 1e-9
                            else "存在数值差异，见 deltas_by_leg"),
            }
            log(f"[对照] 控制组 {cp.name}：{uni_aud['control_all_universe']['verdict']}")
        else:
            log(f"[对照] 控制组 {cp} 不存在，跳过")
            uni_aud["control_all_universe"] = {"error": f"control json not found: {cp}"}

    out = {"meta": {**META, "status": "complete" if not a.smoke else "smoke",
                    "families_done": sorted(FAM_MEMBERS)},
           "n_legs": len(rows), "legs": rows, "corr_distribution": {
               "min": rows[0]["corr_B"], "min_leg": rows[0]["leg"],
               "p10": round(float(np.percentile([r["corr_B"] for r in rows], 10)), 3),
               "median": round(float(np.median([r["corr_B"] for r in rows])), 3),
               "max": rows[-1]["corr_B"], "max_leg": rows[-1]["leg"],
               "all": sorted([(r["leg"], r["corr_B"]) for r in rows], key=lambda x: x[1])},
           "pass_corr_gate": [r["leg"] for r in rows if r["pass_G1"]],
           "pass_all_leg_gates": [r["leg"] for r in rows if r["pass_G1G2G4a"]],
           "blends": blend_report, "halves": halves, "placebo_random": placebo,
           "base_100B": base_all}

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[done] {OUT.name} 已落盘（{len(rows)} 腿 × {len(PHASES)} 相位）")

    # ---------------- 屏幕表 ----------------
    print("\n变体 | 族 | 相位中位夏普 | 相位min | 50bp | 回撤 | corr vs 轨B | 过闸(G1G2G4)")
    for r in sorted(rows, key=lambda x: x["corr_B"]):
        print(f"{r['leg']:18s} | {r['family']:4s} | {r['phmed_sharpe']:+7.3f} | {r['sharpe_min']:+7.3f} | "
              f"{r['slip50_sharpe']:+7.3f} | {r['off0_mdd_pct']:6.1f}% | {r['corr_B']:+.3f} | "
              f"{'PASS' if r['pass_G1G2G4a'] else '  - '}")
    if cand:
        print(f"\n过三闸 {len(cand)} 个：{[r['leg'] for r in cand]}")
    else:
        print(f"\n无过闸者。corr 下界 = {rows[0]['corr_B']:+.3f}（{rows[0]['leg']}：{rows[0]['desc']}）")


if __name__ == "__main__":
    main()
