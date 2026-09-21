# -*- coding: utf-8 -*-
"""小步碎阳策略回测（XBSY-0921 · 2026-09-21 用户提出）
================================================================================
用户给的两份口径**语义不同**，故预注册成独立臂，差异作为结果呈现，不合并：

  A  = TDX 原文（权威）
       COUNT(C>O AND (C-REF(C,1))/REF(C,1)*100 < 3, 5) >= 4
       AND MA(C,5) > MA(C,10)
       AND MA(V,5) > MA(V,10)
       AND C > MA(C,20)

  B  = 用户 Python 代码**字面**复刻
       yang_count(5日阳线) >= 4
       AND max(近 4 日涨幅) < 3        ← ⚠ 缺陷：pct_chg 只在 tail(5) 内 shift
       AND MA(C,5) > MA(C,10)              → recent 首行涨幅=NaN，被 max() 跳过
       缺：C>MA(C,20)、量能条件         → 实际只查 4 天涨幅、且无年线/量能约束

  B' = 用户代码**修掉 shift 缺陷**（5 日涨幅全部参与判定），其余与 B 同

  A_vol_off = TDX 原文去掉量能条件（归因用：量能条件贡献多少）

预注册（**看任何收益数字之前**固定，避免 config-snooping）
--------------------------------------------------------------------------------
- 出场：T 日收盘出信号 → **T+1 开盘买入 → T+1+H 收盘卖出**（与 factor_infer 同口径）
- 相位扫描：H ∈ {1, 3, 5, 10, 20}（20 是基准，因 TDX 式形态策略多为波段）
- 成本档：往返 0bp / 20bp（基准假设）/ 50bp（压力档）
- 域门：复用 factor_gate 面板的 `mask`（引擎域门，上市初期/不可交易日已排除）
- 判据：① `factor_gate.audit_fn` 无前视（截断重算对拍）
        ② 样本闸：n≥100 且 活跃日≥30，否则记「不可判定」（陷阱 ★177）
        ③ **以 t_cluster 为准**，t_naive 只作参照；虚高倍数 ≥3 倍则事件级结论不可采信（★195）
        ④ 按笔等权 与 按天等权 **两个口径都给**（只给按笔即为选择性汇报，★197）
        ⑤ 全同/异常先跑随机对照（安慰剂：同日均笔数的随机信号 200 次抽样）

用法：
    cd quant-weight-system && python backtest/xbsy_0921.py            # 全流程
    python backtest/xbsy_0921.py --phase                              # 只跑相位扫描（跳过闸）
    python backtest/xbsy_0921.py --placebo                            # 只跑随机对照
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))

import factor_infer as FI          # noqa: E402  （聚类 t / 按天等权 / 分块自助）
import factor_gate as FG           # noqa: E402  （面板 / audit / 域门）

PANEL = str(HERE / "kv_resonance_0913" / "panel_kv_0913.npz")
PHASES = [1, 3, 5, 10, 20]
COST_TIERS = {"0bp": 0.0, "20bp": 0.0020, "50bp": 0.0050}
PLACEBO_B = 200
OUT_JSON = str(BASE / "backtest" / "xbsy_0921.json")
VOL_CACHE = str(HERE / "_xbsy_volume.npz")


# ---------------------------------------------------------------- trailing 窗口
def roll_sum(a, n):
    """尾随窗口 [i-n+1, i] 的和（NaN 记 0）。numpy 版，不依赖 scipy origin —— 陷阱 ★175。"""
    a = np.nan_to_num(np.asarray(a, dtype=np.float64), nan=0.0)
    c = np.cumsum(a, axis=0)
    out = np.full_like(c, np.nan)
    if n - 1 < c.shape[0]:
        out[n - 1:] = c[n - 1:]
        out[n:] -= c[:-n]
    return out


def roll_mean(a, n):
    """尾随窗口满窗均值；窗口内有 NaN 则返回 NaN（不足窗=不可用，不当 0 用）。"""
    a = np.asarray(a, dtype=np.float64)
    f = np.isfinite(a)
    s = roll_sum(np.where(f, a, 0.0), n)
    k = roll_sum(f.astype(np.float64), n)
    with np.errstate(all="ignore"):
        return np.where(k == n, s / n, np.nan)


def roll_max(a, n):
    """尾随窗口满窗最大值；窗口内有 NaN 则 NaN。O(T·N·n)，n≤5 可接受。"""
    a = np.asarray(a, dtype=np.float64)
    T = a.shape[0]
    out = np.full_like(a, np.nan)
    for n_ in range(n):
        seg = np.full_like(a, np.nan)
        if n_ == 0:
            seg = a.copy()
        else:
            seg[n_:] = a[:-n_]
        if n_ == 0:
            out = seg.copy()
        else:
            out = np.fmax(out, seg)
    # 满窗校验：窗口内必须全有效
    valid = roll_sum(np.isfinite(a).astype(np.float64), n) == n
    return np.where(valid, out, np.nan)


def load_volume(codes, cal):
    """按面板的 codes/cal 从 data_full 取真实成交量（手/股，仅用于同口径比较，不需单位换算）。"""
    if Path(VOL_CACHE).exists():
        D = np.load(VOL_CACHE, allow_pickle=True)
        if list(D["codes"]) == list(codes) and list(D["cal"]) == list(cal):
            print(f"  成交量矩阵：读缓存 {VOL_CACHE}")
            return D["vol"]
    cal_i = {d: i for i, d in enumerate(cal)}
    vol = np.full((len(cal), len(codes)), np.nan, dtype=np.float32)
    miss = 0
    t0 = time.time()
    for j, c in enumerate(codes):
        f = BASE / "data_full" / f"{c}.csv"
        if not f.exists():
            miss += 1
            continue
        try:
            df = pd.read_csv(f, dtype={"date": str}, usecols=["date", "volume"])
            ds = df["date"].to_numpy()
            vv = df["volume"].to_numpy(dtype=np.float64)
            idx = np.fromiter((cal_i.get(str(d)[:10], -1) for d in ds), dtype=np.int64, count=ds.size)
            ok = idx >= 0
            vol[idx[ok], j] = vv[ok]
        except Exception:
            miss += 1
    print(f"  成交量矩阵：{len(codes)} 只构建完成（缺 {miss} 只）/ {time.time()-t0:.0f}s")
    np.savez_compressed(VOL_CACHE, vol=vol, codes=np.array(codes, dtype=object),
                        cal=np.array(cal, dtype=object))
    return vol


# ---------------------------------------------------------------- 四臂信号
def build_arms(P, V):
    V = np.asarray(V)[: P["close"].shape[0]]      # audit_fn 从头截断面板 → 量能同步切片
    O = P["open"].astype(np.float64)
    C = P["close"].astype(np.float64)
    yang = C > O
    pct = np.full_like(C, np.nan)
    pct[1:] = C[1:] / C[:-1] - 1.0
    small = yang & (pct < 0.03)              # TDX：阳线 且 当日涨幅<3%

    cnt5 = roll_sum(small, 5)                # TDX：近 5 日满足「阳线∧涨<3%」的天数
    ma5c, ma10c, ma20c = roll_mean(C, 5), roll_mean(C, 10), roll_mean(C, 20)
    ma5v, ma10v = roll_mean(V, 5), roll_mean(V, 10)
    up_c = ma5c > ma10c
    up_v = ma5v > ma10v
    above20 = C > ma20c

    arms = {}
    arms["A_tdx"] = (cnt5 >= 4) & up_c & up_v & above20
    arms["A_vol_off"] = (cnt5 >= 4) & up_c & above20
    # 用户代码：yang_count(5)>=4 且 max(近4日涨幅)<3% 且 MA(C,5)>MA(C,10)
    arms["B_user_literal"] = (roll_sum(yang, 5) >= 4) & (roll_max(pct, 4) < 0.03) & up_c
    arms["B_fixed"] = (roll_sum(yang, 5) >= 4) & (roll_max(pct, 5) < 0.03) & up_c
    for k in arms:
        arms[k] = np.where(np.isfinite(C), arms[k], False).astype(bool)
    return arms


# ---------------------------------------------------------------- 评估
def evaluate(P, SIG, arm, hold, bm=None):
    """返回一臂一相位下的全部数字（按笔 / 按天 / 超额 三口径 + 聚类 t + 分块自助 p）。"""
    T = P["close"].shape[0]
    r, day, _ = FI.trade_returns(P, SIG, hold=hold)
    G = T
    rec = {"n": int(r.size), "days_active": int(np.unique(day).size) if r.size else 0}
    if r.size < 2:
        rec["verdict"] = "不可判定（样本不存在）"
        return rec, r
    nt = FI.naive_t(r)
    ct = FI.cluster_t(r, day, G)
    dm = FI.daily_mean(r, day, G)
    rec.update({
        "mean_per_trade": round(float(nt["mean"]), 6),
        "win_rate": round(float((r > 0).mean()), 4),
        "t_naive": round(float(nt["t"]), 2),
        "t_cluster": round(float(ct["t"]), 2),
        "n_days_cluster": int(ct["n_groups"]),
        "inflation_x": round(abs(float(nt["t"])) / max(abs(float(ct["t"])), 1e-9), 2),
        "mean_per_day": round(float(dm.mean()), 6) if dm.size else None,
        "n_day_obs": int(dm.size),
    })
    # 超额口径：逐笔扣掉「同一天全市场等权同期收益」（同 hold、同执行口径）—— 吸收共同因子
    if bm is not None:
        ex_raw = r - bm[day]
        fin = np.isfinite(ex_raw)
        ex, exd = ex_raw[fin], day[fin]
        rec["excess_market_mean"] = round(float(bm[day].mean()), 6)
        if ex.size >= 2:
            dmx = FI.daily_mean(ex, exd, G)
            rec.update({
                "excess_mean_per_trade": round(float(ex.mean()), 6),
                "excess_win": round(float((ex > 0).mean()), 4),
                "excess_t_naive": round(float(FI.naive_t(ex)["t"]), 2),
                "excess_t_cluster": round(float(FI.cluster_t(ex, exd, G)["t"]), 2),
                "excess_mean_per_day": round(float(dmx.mean()), 6) if dmx.size else None,
            })
    for tag, cost in COST_TIERS.items():
        rn = r - cost
        rec[f"mean_{tag}"] = round(float(rn.mean()), 6)
        rec[f"win_{tag}"] = round(float((rn > 0).mean()), 4)
        rec[f"t_cluster_{tag}"] = round(float(FI.cluster_t(rn, day, G)["t"]), 2)
        if bm is not None and "excess_mean_per_trade" in rec:
            rec[f"excess_mean_{tag}"] = round(float(rec["excess_mean_per_trade"] - cost), 6)
    # 分块自助（20 日块）在基准相位只跑一次，避免无谓开销
    if hold == 20:
        try:
            p = FI.boot_p(dm, side="pos", B=1000) if dm.size else None
            rec["boot_p_20bp"] = round(float(p), 4) if p is not None else None
        except Exception as e:
            rec["boot_p_20bp"] = f"ERR {e}"[:60]
    # 样本闸（★177）
    rec["sample_gate"] = "PASS" if (rec["n"] >= 100 and rec["days_active"] >= 30) else "不可判定"
    return rec, r


def main():
    only_phase = "--phase" in sys.argv
    only_placebo = "--placebo" in sys.argv
    t_start = time.time()

    print("=" * 96)
    print("小步碎阳（XBSY-0921）· 预注册四臂 × 五相位 × 三成本档")
    print("=" * 96)
    FG.PANEL = PANEL          # audit_fn 内部用 factor_gate.PANEL 相对常量 → 必须改成绝对路径
    P = FG.load_panel(PANEL)
    D = np.load(PANEL, allow_pickle=True)
    codes = D["codes"]
    cal = D["cal"]
    T, N = P["close"].shape
    mb = int(sum(1 for c in codes if str(c).startswith(("sh60", "sz00"))))
    print(f"面板 {T} 日 × {N} 只 | {cal[0]} → {cal[-1]} | 主板(60/00) {mb} 只（{mb/N:.1%}）")
    print(f"域门 mask 可交易率 {P['mask'].mean():.3f}")

    V = load_volume([str(c) for c in codes], [str(d) for d in cal])
    arms = build_arms(P, V)

    print("\n" + "-" * 96)
    print("① 信号结构 + 样本闸（任何收益数字之前）")
    print("-" * 96)
    struct = {}
    for name, S in arms.items():
        per_day = S.sum(axis=1)
        act = int((per_day > 0).sum())
        med = float(np.median(per_day[per_day > 0])) if act else 0.0
        uniq = int(S.any(axis=0).sum())
        gate = "PASS" if (int(S.sum()) >= 100 and act >= 30) else "不可判定"
        struct[name] = {"n_sig": int(S.sum()), "days_active": act, "uniq_symbols": uniq,
                        "median_per_day": round(med, 1), "sample_gate": gate}
        print(f"  {name:<16} n_sig={int(S.sum()):>8}  活跃日={act:>5}  标的={uniq:>5}  "
              f"日中位={med:>6.1f}  样本闸={gate}")

    out = {"panel": PANEL, "span": [str(cal[0]), str(cal[-1])], "n_stocks": N,
           "main_board": mb, "structure": struct, "phases": {}, "audit": {}, "placebo": None}

    if not only_placebo:
        print("\n" + "-" * 96)
        print("② 前视审计（截断重算对拍，FAIL 即停 —— 不看收益数字）")
        print("-" * 96)
        for name in ("A_tdx", "B_user_literal"):
            try:
                # audit_fn 内部 `load_panel(sub=sub)` 用的是**默认参数** PANEL（def 时已绑定，
                # 改 FG.PANEL 无效）→ 只能把 cwd 切到 backtest/ 让相对路径解析
                _cwd = os.getcwd()
                os.chdir(HERE)
                try:
                    au = FG.audit_fn(lambda P_: build_arms(P_, V)[name], sample=6, verbose=False)
                finally:
                    os.chdir(_cwd)
                out["audit"][name] = au
                print(f"  {name:<16} audit={au['verdict']}  mismatch={au['mismatch_rows']}  "
                      f"maxdiff={au['max_abs_diff']:.2e}")
            except Exception as e:
                out["audit"][name] = {"verdict": "ERROR", "err": str(e)[:160]}
                print(f"  {name:<16} audit=ERROR {str(e)[:120]}")

        print("\n" + "-" * 96)
        print("③ 收益（T+1 开盘买入 → T+1+H 收盘卖出）· 按笔 / 超额 / 聚类 t 三给")
        print("-" * 96)
        hdr = (f"  {'臂':<16}{'H':>3}{'笔数':>8}{'活跃日':>7}{'胜率':>7}{'按笔均值':>10}"
               f"{'超额均值':>10}{'按天均值':>10}{'超额按天':>10}{'t_cluster':>10}"
               f"{'超额t_cl':>10}{'虚高':>6}{'超额50bp':>10}")
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))
        for h in PHASES:                       # 按相位外层：全市场基准每相位只算一次
            BM = FI.market_bm(P, hold=h)
            for name, S in arms.items():
                out["phases"].setdefault(name, {})
                rec, _ = evaluate(P, S, name, h, bm=BM)
                out["phases"][name][str(h)] = rec
                if rec["n"] < 2:
                    print(f"  {name:<16}{h:>3}{rec['n']:>8}   不可判定（样本不存在）")
                    continue
                print(f"  {name:<16}{h:>3}{rec['n']:>8}{rec['days_active']:>7}"
                      f"{rec['win_rate']:>7.1%}{rec['mean_per_trade']:>10.4f}"
                      f"{rec.get('excess_mean_per_trade', float('nan')):>10.4f}"
                      f"{rec['mean_per_day']:>10.4f}"
                      f"{rec.get('excess_mean_per_day', float('nan')):>10.4f}"
                      f"{rec['t_cluster']:>10.2f}"
                      f"{rec.get('excess_t_cluster', float('nan')):>10.2f}"
                      f"{rec['inflation_x']:>6.1f}"
                      f"{rec.get('excess_mean_50bp', float('nan')):>10.4f}")

    if not only_phase:
        print("\n" + "-" * 96)
        print(f"④ 随机对照（安慰剂）：同日均笔数的随机信号 × {PLACEBO_B} 抽样，H=20")
        print("-" * 96)
        rng = np.random.default_rng(20260921)
        S = arms["A_tdx"]
        per_day = S.sum(axis=1)
        BM20 = FI.market_bm(P, hold=20)
        real, _ = evaluate(P, S, "A_tdx", 20, bm=BM20)
        plac, plac_ex = [], []
        M = P["mask"]
        Tt = P["close"].shape[0]
        for b in range(PLACEBO_B):
            R = np.zeros_like(S)
            for t in range(Tt):
                k = int(per_day[t])
                if k <= 0:
                    continue
                cand = np.nonzero(M[t])[0]
                if cand.size == 0:
                    continue
                pick = rng.choice(cand, size=min(k, cand.size), replace=False)
                R[t, pick] = True
            rr, rd, _ = FI.trade_returns(P, R, hold=20)
            if rr.size:
                plac.append(float(rr.mean()))
                exv = rr - BM20[rd]
                exv = exv[np.isfinite(exv)]
                if exv.size:
                    plac_ex.append(float(exv.mean()))
        plac = np.array(plac)
        plac_ex = np.array(plac_ex)
        real_m = real["mean_per_trade"]
        real_ex = real.get("excess_mean_per_trade", float("nan"))
        p_hi = float((plac >= real_m).mean()) if plac.size else float("nan")
        p_lo = float((plac <= real_m).mean()) if plac.size else float("nan")
        p_ex = float((plac_ex >= real_ex).mean()) if plac_ex.size else float("nan")
        out["placebo"] = {"n_draws": int(plac.size), "real_mean": real_m,
                          "placebo_mean": round(float(plac.mean()), 6) if plac.size else None,
                          "placebo_sd": round(float(plac.std(ddof=1)), 6) if plac.size > 1 else None,
                          "p_ge_real": round(p_hi, 4), "p_le_real": round(p_lo, 4),
                          "real_excess": real_ex,
                          "placebo_excess_mean": round(float(plac_ex.mean()), 6) if plac_ex.size else None,
                          "p_excess": round(p_ex, 4)}
        print(f"  真实 A_tdx H=20｜按笔均值 {real_m:+.4%}  超额均值 {real_ex:+.4%}")
        print(f"  安慰剂 {plac.size} 次｜按笔均值 {plac.mean():+.4%} (sd {plac.std(ddof=1):.4%})"
              f"｜超额均值 {plac_ex.mean():+.4%}")
        print(f"  P(安慰剂按笔 ≥ 真实) = {p_hi:.4f}｜P(安慰剂超额 ≥ 真实超额) = {p_ex:.4f}"
              f"   （下限 1/(B+1)={1/(plac.size+1):.4f}，触底时不可当真实 p 值排序）")
        print(f"  → 超额口径才是判据：信号超额 {real_ex:+.4%} vs 随机同笔数超额 {plac_ex.mean():+.4%}")

    out["elapsed_s"] = round(time.time() - t_start, 1)
    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n结果已落盘 {OUT_JSON}（{out['elapsed_s']}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
