# -*- coding: utf8 -*-
"""R-qlch-t1exit-0922 · T+1 合规出口重测（★198 复发修正）

预注册：PRE-REGISTRATION_20260922_qlch_t1exit.md（n_trials=4）
冻结：超跌 ret20(T-1)<=-7.31% / gap[-5%,-2%] / B4 分位滤网 / K=3 / MA20 门 / 量比>=1.2 / 非ST / 20bp
唯一改动 = 出场规则。

触发判定（陷阱库 179-186）：
  · 止损止盈用 low/high 非 close（日内触及即触发）
  · 同 bar 止损优先
  · 跳空按 open（开盘价直接穿过目标价 → 按开盘价成交）
  · 末仓显式：上限 20 日到期当日按收盘价平仓
  · T+1 规则：入场日 e 当日**不可卖**，最早出场 e+1
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
import factor_gate as FG

BASE = Path(".").resolve()
PANEL = FG.PANEL
VAL = BASE.parent / "data_fundamental" / "val_em"
TRAIN_END = "2021-12-31"
SEEDS = [20260921, 20260922, 20260923, 20260924, 20260925]
K = 3
t0 = time.time()


def log(*a):
    print("[%6.1fs]" % (time.time() - t0), *a, flush=True)


z = np.load(PANEL, allow_pickle=True)
C = z["close"].astype(np.float64); O = z["open"].astype(np.float64)
H = z["high"].astype(np.float64); L = z["low"].astype(np.float64)
A = z["amount"].astype(np.float64); M = z["mask"].astype(bool)
cal = [str(x) for x in z["cal"]]; codes = [str(x) for x in z["codes"]]
T, N = C.shape
c2j = {c: j for j, c in enumerate(codes)}; d2i = {d: i for i, d in enumerate(cal)}
import json as _json
names = {str(k): str(v) for k, v in _json.load(
    open(BASE.parent / "data_full_names.json", encoding="utf-8")).items()}
is_st = np.zeros((T, N), dtype=bool)
for j, c in enumerate(codes):
    if "ST" in (names.get(c, "") or "").upper():
        is_st[:, j] = True
vm = pd.concat([pd.read_csv(VAL / f, usecols=["code", "date", "float_mv"], dtype={"code": str})
                for f in ("val_em_pre2021.csv", "val_em_all.csv", "val_em_ext.csv")], ignore_index=True)
vm["code"] = vm["code"].str.zfill(6)
vm = vm.drop_duplicates(subset=["code", "date"], keep="last")
vm["j"] = [c2j.get(("sh" + c) if c.startswith("6") else ("sz" + c), -1) for c in vm["code"]]
vm["i"] = [d2i.get(str(d), -1) for d in vm["date"]]
vm = vm[(vm.j >= 0) & (vm.i >= 0)]
FM = np.full((T, N), np.nan); FM[vm.i.values, vm.j.values] = vm.float_mv.values
amt5 = FG.roll_trailing(A, 5, "mean")
vr = np.where(np.isfinite(amt5) & (amt5 > 0), A / np.where(amt5 > 0, amt5, 1.0), np.nan)
turn = np.where(np.isfinite(FM) & (FM > 0) & (C > 0), A / np.where(FM > 0, FM, 1.0), np.nan)
mcap = FM / 1e8
valid = M & np.isfinite(C) & (C > 0) & np.isfinite(O) & (O > 0) & np.isfinite(A) & (A > 0)
ret20 = np.full((T, N), np.nan); ret20[20:] = C[20:] / C[:-20] - 1.0
r20m = np.full_like(ret20, np.nan); r20m[1:] = ret20[:-1]
PM = pd.DataFrame(np.where(valid, mcap, np.nan)).rank(axis=1, pct=True).values
PT = pd.DataFrame(np.where(valid, turn, np.nan)).rank(axis=1, pct=True).values
gap = np.full((T, N), np.nan); gap[1:] = O[1:] / C[:-1] - 1.0
gap[1:] = np.where(np.isfinite(O[1:]) & (O[1:] > 0) & np.isfinite(C[:-1]) & (C[:-1] > 0), gap[1:], np.nan)
idx = pd.read_csv(BASE.parent / "index_000300.csv", parse_dates=["date"])
ic = idx.close.astype(np.float64).values
ma20 = pd.Series(ic).rolling(20).mean().values
i2t = {d.strftime("%Y-%m-%d"): k for k, d in enumerate(idx.date)}
bear = np.zeros(T, dtype=bool)
for t, d in enumerate(cal):
    k = i2t.get(d)
    if k is not None and np.isfinite(ma20[k]):
        bear[t] = bool(ic[k] < ma20[k])

F = ((~is_st) & np.isfinite(vr) & (vr >= 1.2) & valid
     & np.isfinite(PM) & (PM >= 0.20) & (PM <= 0.70)
     & np.isfinite(PT) & (PT >= 0.40) & (PT <= 0.80))
OV = np.isfinite(r20m) & (r20m <= -0.0731)
CAND = F & OV & bear[:, None]

ENTRIES = []          # (e=入场日, j, entry_px)
for t in range(T - 1):
    js = np.where(CAND[t] & np.isfinite(gap[t + 1]) & (gap[t + 1] >= -0.05)
                  & (gap[t + 1] <= -0.02) & valid[t + 1])[0]
    for j in js:
        e = t + 1
        if np.isfinite(O[e, j]) and O[e, j] > 0:
            ENTRIES.append((e, int(j), float(O[e, j])))
log("入场机会 %d 笔（gap 过滤后）" % len(ENTRIES))


def exit_ret(e, j, px, rule, cost=0.002):
    """返回 (净收益, 持有天数, 出场原因)。已扣往返成本。"""
    if rule == "E0":            # 同日收盘（非法，仅作对照）
        if e >= T or not np.isfinite(C[e, j]):
            return None
        return (C[e, j] / px - 1.0 - cost, 1, "同日收盘(非法)")
    if rule == "E1":            # T+2 开盘卖（= e+1 开盘）
        d = e + 1
        if d >= T or not np.isfinite(O[d, j]) or O[d, j] <= 0:
            return None
        return (O[d, j] / px - 1.0 - cost, 2, "T+2开盘")
    if rule == "E2":            # T+2 收盘卖
        d = e + 1
        if d >= T or not np.isfinite(C[d, j]) or C[d, j] <= 0:
            return None
        return (C[d, j] / px - 1.0 - cost, 2, "T+2收盘")
    # E3 / E4：止盈止损，入场日 e 不可卖，最早 e+1，上限 20 日
    # 2026-09-23 增补：E5 = 生产新口径（止 25% / 损 30% / 上限 40 交易日）；上限参数化
    _P = {"E3": (0.08, -0.10, 20), "E5": (0.25, -0.30, 40)}
    tp_pct, sl_pct, _H = _P.get(rule, (0.15, -0.20, 20))
    tp = px * (1 + tp_pct); sl = px * (1 + sl_pct)
    for d in range(e + 1, min(e + _H, T)):
        if not (np.isfinite(O[d, j]) and O[d, j] > 0):
            continue
        o_, h_, l_, c_ = O[d, j], H[d, j], L[d, j], C[d, j]
        # 跳空穿止损 → 按开盘价
        if o_ <= sl:
            return (o_ / px - 1.0 - cost, d - e + 1, "止损跳空")
        # 跳空穿止盈 → 按开盘价
        if o_ >= tp:
            return (o_ / px - 1.0 - cost, d - e + 1, "止盈跳空")
        # 同 bar：止损优先
        if np.isfinite(l_) and l_ <= sl:
            return (sl / px - 1.0 - cost, d - e + 1, "止损触发")
        if np.isfinite(h_) and h_ >= tp:
            return (tp / px - 1.0 - cost, d - e + 1, "止盈触发")
    # 末仓显式：e+19 收盘平仓
    d = min(e + _H - 1, T - 1)
    if not np.isfinite(C[d, j]):
        return None
    return (C[d, j] / px - 1.0 - cost, d - e + 1, "到期平仓")


def run(rule, seed, cost=0.002):
    """仓位跟踪引擎（修复：多日持仓收益不可在入场日一次性计入复利）

    修复点：原实现 `cash *= (1 + sum(w*full_trade_ret))` 把 20 日收益当 1 日收益计入，
    导致 E3/E4 年化出现 +603% 这类「好到不可能是真的」数字（★198 同族执行层伪影）。
    现改为：资金在持有期内锁定，逐日几何摊销计入净值，出场日才释放现金。
    """
    rng = np.random.default_rng(seed)
    by_day = {}
    for e, j, px in ENTRIES:
        by_day.setdefault(e, []).append((j, px))
    # 预算每笔的 (出场日 x, 净收益 ret)
    TR = {}
    for e, j, px in ENTRIES:
        r = exit_ret(e, j, px, rule, cost)
        if r is None:
            continue
        ret, days, _why = r
        # 同日出口（E0）在引擎里必须至少锁定到次日：free-check 在 entry 之前，
        # 否则 x==e 的仓位永不被释放（E0 曾因此 0 笔）
        x = min(max(e + days - 1, e + 1), T - 1)
        TR.setdefault(e, []).append((j, px, float(ret), int(x), _why))
    cash = 1.0
    pos = []                 # (x, alloc, ret, e)
    nav = np.full(T, np.nan)
    tr = []
    for t in range(T):
        still = []
        for p in pos:
            if p[0] == t:
                cash += p[1] * (1.0 + p[2])
                tr.append((p[3], p[0], p[2], p[4]))   # 入场日/出场日/净收益/原因
            else:
                still.append(p)
        pos = still
        if t in TR and cash > 1e-12:
            lst = TR[t]
            sel = lst if len(lst) <= K else [lst[i] for i in sorted(rng.choice(len(lst), size=K, replace=False))]
            w = 1.0 / max(len(sel), K)
            base = cash   # ★ 快照：原按递减后的 cash 连乘，3x1/3 只投 70.4%，
                          #   现金永滞 29.6% → 净值被稀释
            for j, px, ret, x, why in sel:
                alloc = base * w
                cash -= alloc
                pos.append((x, alloc, ret, t, why))
        mv = 0.0
        for x, alloc, ret, e, _w in pos:
            hold = max(x - e + 1, 1)
            elap = min(t - e + 1, hold)
            mv += alloc * ((1.0 + ret) ** (elap / hold))
        nav[t] = cash + mv
    return nav, tr



# ============================== 报告 ==============================
ARMS = [("E0", "E0 同日(非法)"), ("E1", "E1 次日开盘"), ("E2", "E2 次日收盘"),
        ("E3", "E3 止8%损10%"), ("E4", "E4 止15%损20%"), ("E5", "E5 止25%损30%/40日")]
W = 118
REPORT = {}


def stats(rule, cost, lo="0000", hi=None):
    hi = hi or TRAIN_END
    tr = []; navs = []
    for sd in SEEDS:
        nav, t = run(rule, sd, cost=cost)
        navs.append(nav); tr.extend(t)
    tr = [x for x in tr if lo <= cal[x[0]] <= hi]
    rets  = np.array([x[2] for x in tr])
    holds = np.array([x[1] - x[0] + 1 for x in tr])
    daym = {}
    for x in tr:
        daym.setdefault(x[0], []).append(x[2])
    dayavg = np.array([np.mean(v) for v in daym.values()])
    reasons = {}
    for x in tr:
        reasons[x[3]] = reasons.get(x[3], 0) + 1
    nav = np.mean(navs, axis=0)
    ks = [k for k, d in enumerate(cal) if lo <= d <= hi]
    v = nav[ks[0]:ks[-1] + 1]
    assert np.isfinite(v).all(), "净值含 NaN，切片与日历错位"
    rr = np.diff(v) / v[:-1]; yrs = max(len(v) / 244.0, 1e-9)
    cagr = (v[-1] ** (1 / yrs) - 1) * 100
    sh = np.mean(rr) / np.std(rr) * np.sqrt(244) if np.std(rr) > 0 else float("nan")
    dd = 100 * float((v / np.maximum.accumulate(v) - 1.0).min())
    yr = {}
    for kk in range(1, len(v)):
        yr.setdefault(str(cal[ks[0] + kk])[:4], []).append(v[kk] / v[kk - 1] - 1.0)
    yret = {y: 100 * (np.prod([1 + z for z in a]) - 1.0) for y, a in yr.items()}
    kon = {}
    for y in sorted(yret):
        rows = [x for x in tr if str(cal[x[0]])[:4] == y]
        if not rows:
            continue
        dm_ = {}
        for x in rows:
            dm_.setdefault(x[0], []).append(x[2])
        kon[y] = (100 * np.mean([x[2] for x in rows]),
                  100 * np.mean([np.mean(z) for z in dm_.values()]))
    return dict(n=len(rets), nd=len(dayavg), holds=holds, reasons=reasons,
                pt=100 * rets.mean(), ptm=100 * np.median(rets), ptw=100 * (rets > 0).mean(),
                dt=100 * dayavg.mean(), dtm=100 * np.median(dayavg), dtw=100 * (dayavg > 0).mean(),
                cagr=cagr, sh=sh, dd=dd, yr=yret, kon=kon)


HDR = ("%-15s %6s %5s | %8s %8s %6s | %8s %8s %6s | %8s %7s %7s"
       % ("出口", "笔数", "天数", "按笔均", "按笔中位", "胜率", "按天均", "按天中位", "胜率", "年化", "夏普", "回撤"))


def show(tag, cost, lo, hi, title):
    global REPORT
    print()
    print(title)
    print(HDR)
    print("-" * W)
    for rule, lab in ARMS:
        d = stats(rule, cost, lo, hi)
        REPORT["%s|%s" % (tag, rule)] = d
        print("%-15s %6d %5d | %+8.3f %+8.3f %5.1f | %+8.3f %+8.3f %5.1f | %+8.2f %7.3f %+7.2f"
              % (lab, d["n"], d["nd"], d["pt"], d["ptm"], d["ptw"],
                 d["dt"], d["dtm"], d["dtw"], d["cagr"], d["sh"], d["dd"]))


print("=" * W)
print("T+1 合规出口复测 v2 — 训练窗（2018-2021，选型依据）")
print("=" * W)
show("TR20", 0.002, "0000", None, "【0.2% 成本档】")
show("TR50", 0.005, "0000", None, "【0.5% 成本档】")

print()
print("=" * W)
print("主判据逐条裁决（预注册 §四；20bp 为主档，第 4 条为 50bp 档）")
print("=" * W)
print("%-15s | %-11s %-11s %-11s %-11s %-11s | %s"
      % ("出口", "①按天均>0", "②按天中位>0", "③胜率>52%", "④50bp均>0", "⑤年化>8%", "裁决"))
print("-" * W)
for rule, lab in ARMS:
    a = REPORT["TR20|" + rule]; b = REPORT["TR50|" + rule]
    c = [a["dt"] > 0, a["dtm"] > 0, a["dtw"] > 52, b["dt"] > 0, a["cagr"] > 8]
    ok = all(c)
    print("%-15s | %-11s %-11s %-11s %-11s %-11s | %s"
          % (lab, *["%s %+.3f" % ("✓" if x else "✗", 0) if False else ("✓" if x else "✗") for x in c],
             "全过" if ok else "未过 %d 项" % (5 - sum(c))))
print("-" * W)
print("  注：②按「按入场日分组求均值后取中位」（引擎产出口径）；①③⑤均为 0.2% 档。")
print("  E0 为非法对照，不参与裁决。")

print()
print("=" * W)
print("验证窗（2022-01-01 起）— 预注册 §六：仅参照，不用于选型")
print("=" * W)
show("VA20", 0.002, "2022-01-01", "9999", "【0.2% 成本档】")
show("VA50", 0.005, "2022-01-01", "9999", "【0.5% 成本档】")

print()
print("E0（非法）与合法臂的差距 = 回测虚增幅度（0.2% 档，训练窗）")
e0 = REPORT["TR20|E0"]
for rule, lab in ARMS[1:]:
    d = REPORT["TR20|" + rule]
    print("   %-15s 按天差 %+7.3f pp   相对 %+6.1f%%"
          % (lab, d["dt"] - e0["dt"], 100 * (d["dt"] / e0["dt"] - 1)))

print()
print("逐年双口径符号一致（0.2% 档，训练窗；✗ = 两口径符号相反）")
for rule, lab in ARMS[1:]:
    d = REPORT["TR20|" + rule]
    cells = []
    bad = 0
    for y, (p_, q_) in sorted(d["kon"].items()):
        same = (p_ > 0) == (q_ > 0)
        bad += 0 if same else 1
        cells.append("%s %+6.2f/%+6.2f%s" % (y, p_, q_, "" if same else "✗"))
    print("  %-15s %s   → 一致 %d/%d" % (lab, "  ".join(cells), len(cells) - bad, len(cells)))

print()
print("持有期分布（0.2% 档，训练窗）")
for rule, lab in ARMS[3:]:
    h = REPORT["TR20|" + rule]["holds"]
    print("  %-15s 中位 %.0f 日 均值 %.1f 日 | 1日 %.0f%% / 2-5日 %.0f%% / 6-10日 %.0f%% / 11-19日 %.0f%% / 满20日 %.0f%%"
          % (lab, np.median(h), h.mean(),
             100 * (h == 1).mean(), 100 * ((h >= 2) & (h <= 5)).mean(),
             100 * ((h >= 6) & (h <= 10)).mean(), 100 * ((h >= 11) & (h <= 19)).mean(),
             100 * (h >= 20).mean()))
    print("  %-15s 出场原因 %s" % ("", REPORT["TR20|" + rule]["reasons"]))

import json as _json
_clean = {k: {kk: (vv.tolist() if isinstance(vv, np.ndarray) else vv) for kk, vv in v.items()}
          for k, v in REPORT.items()}
_json.dump(_clean, open("_tmp_0922_t1exit_v2.json", "w", encoding="utf-8"),
           ensure_ascii=False, indent=1, default=float)
print()
print("  已落盘 _tmp_0922_t1exit_v2.json（%d 格）" % len(_clean))
