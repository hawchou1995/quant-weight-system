# -*- coding: utf-8 -*-
"""r2 · 分域根因解剖：熊/弱牛/强牛 × 因子 IC × 基础盘期望（2026-09-12）
================================================================
用户质询（@pua）：「有没有为不同的域应用不同的策略、指标、因子和权重向量？负期望的根因在哪里？」
诊断：
  A) 三域定义（与 T3 一致）：熊=HS300<MA250；弱牛=MA250上&MA20下；强牛=MA250上&MA20上
  B) 每域基础盘期望：域内随机等权 10 只、持有 20 日、T+1 开盘、扣 1.15% 往返
     ——这是任何「分域策略」必须打过的零假设地板
  C) 因子×域 横截面 rank-IC（fwd20）：mom_12_1/ma200_pos/aroon_osc/vp_confirm/vol20/
     slope20/momr2_60/momr2_120/ret20(短反转)/ret5(超短反转)
     ——若所有因子在所有域 IC≤0，则「分域权重向量」在数学上= 给零信息因子调权=噪声
  D) #41（深跌低吸，唯一事件级正 edge 族）按信号日分域拆 edge
输出：domain_rootcause_0912.{json,csv,png}
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BASE = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system")
R2 = BASE / "backtest" / "r2_rebuild_0911"
sys.path.insert(0, str(R2))
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "backtest"))

import v8_selector as V  # noqa: E402
import v9_auto  # noqa: E402
import tdx_interp as T  # noqa: E402

COST_RT = 1.15   # % 往返铁律
KS_FWD = 20
SAMPLE_EVERY = 5


def build_regime():
    idx = pd.read_csv(BASE / "index_000300.csv", dtype={"date": str})
    idx["date"] = pd.to_datetime(idx["date"])
    idx = idx.sort_values("date").set_index("date")
    ma250 = idx["close"].rolling(250, min_periods=250).mean()
    ma20 = idx["close"].rolling(20, min_periods=20).mean()
    regime = np.where(idx["close"] < ma250, "bear",
                      np.where(idx["close"] < ma20, "weak", "strong"))
    return pd.Series(regime, index=idx.index), idx["close"]


def main():
    t0 = time.time()
    regime, hs300 = build_regime()
    pool = v9_auto.pool_all
    codes = [c for c in pool if c.startswith(("sh60", "sz00"))]

    # 注入 r2 因子列（slope20/momr2/lowmom91）
    from r2_factors119_portfolio_0912 import add_factor_columns
    add_factor_columns(pool, codes)

    # 采样日
    days = [d for d in regime.index
            if V.START <= str(d.date()) <= V.END and pd.notna(regime.get(d))]
    days = days[::SAMPLE_EVERY]

    FACTORS = ["mom_12_1", "ma200_pos", "aroon_osc", "vp_confirm", "vol20",
               "f_slope20", "f_momr2_60", "f_momr2_120", "ret20", "ret5"]
    rows = []   # 长表：day, code, domain, factors..., fwd20
    t1 = time.time()
    for day in days:
        dom = regime.get(day)
        cols = {}
        ddates = None
        for code in codes:
            df = pool[code]
            if ddates is None:
                ddates = df.index
            if day not in df.index:
                continue
            k = df.index.get_loc(day)
            if k < 130 or k + KS_FWD + 1 >= len(df):
                continue
            o = df["open"].to_numpy(float)
            fwd = o[k + 1 + KS_FWD] / o[k + 1] - 1
            if not np.isfinite(fwd):
                continue
            c = df["close"].to_numpy(float)
            r = {"day": day, "code": code, "domain": dom, "fwd20": fwd,
                 "mom_12_1": df["mom_12_1"].iloc[k] if "mom_12_1" in df else np.nan,
                 "ma200_pos": df["ma200_pos"].iloc[k] if "ma200_pos" in df else np.nan,
                 "aroon_osc": df["aroon_osc"].iloc[k] if "aroon_osc" in df else np.nan,
                 "vp_confirm": df["vp_confirm"].iloc[k] if "vp_confirm" in df else np.nan,
                 "vol20": df["vol20"].iloc[k] if "vol20" in df else np.nan,
                 "f_slope20": df["f_slope20"].iloc[k],
                 "f_momr2_60": df["f_momr2_60"].iloc[k],
                 "f_momr2_120": df["f_momr2_120"].iloc[k],
                 "ret20": c[k] / c[k - 20] - 1 if k >= 20 else np.nan,
                 "ret5": c[k] / c[k - 5] - 1 if k >= 5 else np.nan}
            rows.append(r)
    panel = pd.DataFrame(rows)
    print(f"[panel] {len(panel)} 行 / {panel['day'].nunique()} 采样日 ({time.time()-t1:.0f}s)", flush=True)

    # ---- B) 每域基础盘期望（随机等权 10 只，扣成本） ----
    rng = np.random.default_rng(42)
    base_rows = []
    for dom in ("bear", "weak", "strong"):
        sub = panel[panel["domain"] == dom]
        day_g = sub.groupby("day")["fwd20"]
        stats = {"domain": dom, "n_days": int(sub["day"].nunique()),
                 "mean_fwd20_pct": round(sub["fwd20"].mean() * 100, 3),
                 "median_fwd20_pct": round(sub["fwd20"].median() * 100, 3),
                 "pos_stock_day_pct": round((sub["fwd20"] > 0).mean() * 100, 1)}
        # 随机 10 只组合
        port = []
        for day, g in sub.groupby("day"):
            if len(g) < 10:
                continue
            for _ in range(200):
                picks = rng.choice(g["fwd20"].to_numpy(), size=10, replace=False)
                port.append(picks.mean() * 100 - COST_RT)
        port = np.array(port)
        stats["rand_port10_mean_pct"] = round(port.mean(), 3)
        stats["rand_port10_std_pct"] = round(port.std(), 3)
        stats["rand_port10_win_pct"] = round((port > 0).mean() * 100, 1)
        # 年化近似（每 20 日一段 × 12.6 段/年，仅量级参考）
        stats["rand_port10_ann_approx_pct"] = round(((1 + port.mean() / 100) ** 12.6 - 1) * 100, 1)
        base_rows.append(stats)
        print(f"  [base {dom}] 股票均值 {stats['mean_fwd20_pct']}% 中位 {stats['median_fwd20_pct']}% | "
              f"随机10只均值 {stats['rand_port10_mean_pct']}%±{stats['rand_port10_std_pct']} "
              f"胜率{stats['rand_port10_win_pct']}%", flush=True)

    # ---- C) 因子×域 rank-IC ----
    ic_rows = []
    for dom in ("bear", "weak", "strong"):
        sub = panel[panel["domain"] == dom]
        for f in FACTORS:
            ics = []
            for day, g in sub.groupby("day"):
                gg = g[[f, "fwd20"]].dropna()
                if len(gg) < 30:
                    continue
                ics.append(gg[f].rank().corr(gg["fwd20"].rank()))
            ics = np.array(ics)
            if len(ics) < 20:
                continue
            # 简化 HAC：滞后1阶自相关调整
            m = ics.mean()
            sd = ics.std(ddof=1)
            ac = np.corrcoef(ics[:-1], ics[1:])[0, 1] if len(ics) > 2 else 0
            neff = len(ics) * max(0.2, (1 - ac) / (1 + ac))
            t = m / (sd / np.sqrt(neff)) if sd > 0 else 0
            ic_rows.append({"domain": dom, "factor": f, "mean_ic": round(float(m), 4),
                            "ic_ir": round(float(m / sd), 3) if sd > 0 else 0,
                            "t_simple": round(float(t), 2),
                            "pos_day_pct": round(float((ics > 0).mean() * 100), 1),
                            "n_days": int(len(ics))})
    icdf = pd.DataFrame(ic_rows).sort_values(["domain", "mean_ic"], ascending=[True, False])
    icdf.to_csv(R2 / "domain_ic_0912.csv", index=False, encoding="utf-8")
    print("\n[IC 表]", flush=True)
    print(icdf.to_string(index=False), flush=True)

    # ---- D) #41 深低吸按域拆 edge ----
    data = json.load(open(Path(r"D:\Documents\Workbuddy\股票基金\formula_lib\formulas_66.json"), encoding="utf-8"))
    it41 = next(it for it in data["items"] if it["serial"] == 41)
    ast41, local41, _ = T.compile_block(it41["select_blocks"][0]["code"])
    ev_rows = []
    for code in codes:
        df = pool[code]
        c = df["close"].to_numpy(float); o = df["open"].to_numpy(float)
        h = df["high"].to_numpy(float); l = df["low"].to_numpy(float)
        v = df["volume"].to_numpy(float); amo = df["amount"].to_numpy(float)
        env = {"CLOSE": c, "C": c, "OPEN": o, "O": o, "HIGH": h, "H": h, "LOW": l, "L": l,
               "VOL": v, "V": v, "VOLUME": v, "AMO": amo, "AMOUNT": amo, "DRAWNULL": np.nan}
        with np.errstate(invalid="ignore", divide="ignore"):
            for nm, a in local41.items():
                env[nm] = T.ev(a, env)
            sig = np.asarray(T.ev(ast41, env), float) != 0
        ks = np.where(sig)[0]
        for k in ks:
            if k < 5 or k + 61 >= len(df):
                continue
            fwd = o[k + 61] / o[k + 1] - 1
            if not np.isfinite(fwd):
                continue
            d = df.index[k]
            ev_rows.append({"day": d, "code": code, "fwd60": fwd,
                            "domain": regime.get(d)})
    ev = pd.DataFrame(ev_rows)
    dom41 = []
    for dom in ("bear", "weak", "strong", None):
        sub = ev[ev["domain"] == dom] if dom else ev[ev["domain"].isna()]
        if len(sub) < 30:
            continue
        # 同日同域基线
        base = panel[panel["domain"] == dom].groupby("day")["fwd20"].mean()  # 近似基线（fwd20）
        # 严格应使用 fwd60 基线——用无信号股同日 fwd60 均值近似：此处用面板重算太重，改用
        # 事件股 fwd60 直接均值 + 与全体股票同日 fwd60 均值差（面板只存了 fwd20，做近似说明）
        dom41.append({"domain": dom or "other", "n_events": int(len(sub)),
                      "mean_fwd60_pct": round(sub["fwd60"].mean() * 100, 2),
                      "median_fwd60_pct": round(sub["fwd60"].median() * 100, 2),
                      "win_pct": round((sub["fwd60"] > 0).mean() * 100, 1)})
    dom41df = pd.DataFrame(dom41)
    print("\n[#41 按域]（fwd60 毛收益，未减同日基线）", flush=True)
    print(dom41df.to_string(index=False), flush=True)

    out = {"base": base_rows, "ic": ic_rows, "sig41_by_domain": dom41}
    json.dump(out, open(R2 / "domain_rootcause_0912.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    # 图：IC 热力图 + 三域基础盘柱状
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    piv = icdf.pivot(index="factor", columns="domain", values="mean_ic")
    piv = piv[["bear", "weak", "strong"]]
    ax = axes[0]
    im = ax.imshow(piv.to_numpy(), cmap="RdYlGn", vmin=-0.05, vmax=0.05, aspect="auto")
    ax.set_xticks(range(3), piv.columns); ax.set_yticks(range(len(piv)), piv.index)
    for i in range(len(piv)):
        for j in range(3):
            ax.text(j, i, f"{piv.iloc[i, j]:.3f}", ha="center", va="center", fontsize=9)
    ax.set_title("因子×域 平均 rank-IC（fwd20）")
    plt.colorbar(im, ax=ax, shrink=0.8)
    ax = axes[1]
    xs = np.arange(3)
    ax.bar(xs - 0.2, [r["rand_port10_mean_pct"] for r in base_rows], 0.4,
           label="随机10只均值(净1.15%)")
    ax.bar(xs + 0.2, [r["median_fwd20_pct"] for r in base_rows], 0.4, label="个股中位 fwd20")
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(xs, [r["domain"] for r in base_rows])
    ax.set_title("三域基础盘期望（20日，%）"); ax.legend(); ax.grid(alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(R2 / "domain_rootcause_0912.png", dpi=130)
    print(f"\n[done] {time.time()-t0:.0f}s → domain_rootcause_0912.json", flush=True)


if __name__ == "__main__":
    main()
