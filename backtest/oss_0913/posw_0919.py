# -*- coding: utf-8 -*-
"""持仓层不等权（IC / 信号强度）· 轨B SUPER 载体（R-posw-0919）

预注册：同目录 `PRE-REGISTRATION_20260919_posw.md`（507 臂、四条门槛、禁测清单）

实现方式（照抄 `khunter_optim2_0910.py` 的源码注入范式）：
  1. 截断 `oss_super_combo_0913.py` 到 `comp = composite()` 之前，exec 出全部名字（不跑原回测）
  2. 两处注入：
     a. `topN = [...]; topS = set(topN)` → 追加 `if WFN is not None: WFN(di, topN, row)`
     b. `budget = eq_prev_known / N` → `budget = eq_prev_known * float(WG[j]) if WG is not None else ...`
  3. 自检：WFN=None/WG=None 时必须与原引擎逐字节一致（ann/sharpe/n_trades 全同）
"""
import inspect
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
BASE = HERE.parent.parent
sys.path.insert(encoding := "utf-8") if False else None
sys.stdout.reconfigure(encoding="utf-8")
t0 = time.time()


def log(*a):
    print(f"[{time.time()-t0:7.1f}s]", *a, flush=True)


# ---------------- 1) 载入引擎命名空间（截断到 comp = composite() 之前）----------------
SRC = (HERE / "oss_super_combo_0913.py").read_text(encoding="utf-8")
CUT = "comp = composite()"
assert SRC.count(CUT) == 1, "截断锚点失效"
NS = {}
exec(compile(SRC[:SRC.index(CUT)], "<super_head>", "exec"), NS)
comp = NS["composite"]()
NC, ND, F, WARMUP = NS["NC"], NS["ND"], NS["F"], NS["WARMUP"]
ELIG3, O, close_ff, cal = NS["ELIG3"], NS["O"], NS["close_ff"], NS["cal"]
CASH0, SLIP, SLIP_STRESS = NS["CASH0"], NS["SLIP"], NS["SLIP_STRESS"]
COMM, MIN_COMM, TAX = NS["COMM"], NS["MIN_COMM"], NS["TAX"]
sc1000, ma20sc, volpct = NS["sc1000"], NS["ma20sc"], NS["volpct"]
log(f"引擎命名空间就绪：{NC} 码 × {ND} 日｜WARMUP={WARMUP} F={F}")
log(f"composite: finite {np.isfinite(comp).sum()}/{comp.size}")

# ---------------- 2) 源码注入 ----------------
# 注意：不能用 inspect.getsource（exec 进来的代码没有源文件），直接从原文件文本按缩进截取函数体
def _extract_fn(src, name):
    lines = src.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith(f"def {name}("):
            start = i
            break
    assert start is not None, f"函数 {name} 未找到"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if ln.strip() and not ln[0].isspace():
            end = i
            break
    return "\n".join(lines[start:end])


_src = _extract_fn(SRC, "run_engine")
A_OLD = "                topN = [int(j) for j in ordj[:N_eff]]; topS = set(topS)"
A_OLD = "                topN = [int(j) for j in ordj[:N_eff]]; topS = set(topN)"
B_OLD = "                budget = eq_prev_known / N"
assert A_OLD in _src, "锚点 A 失效"
assert B_OLD in _src, "锚点 B 失效"
A_NEW = A_OLD + "\n                if WFN is not None: WFN(di, topN, row)"
B_NEW = "                budget = eq_prev_known * float(WG[j]) if WG is not None else eq_prev_known / N"
_src2 = _src.replace(A_OLD, A_NEW).replace(B_OLD, B_NEW).replace("def run_engine(", "def run_engine_w(")
_NS2 = dict(NS)
_NS2["WFN"] = None
_NS2["WG"] = None
exec(compile(_src2, "<engine_w>", "exec"), _NS2)
run_engine_w = _NS2["run_engine_w"]
log("引擎注入完成（run_engine_w）")


def stats_of(m):
    return dict(ann=float(m["ann"]), sharpe=float(m["sharpe"]), mdd=float(m["mdd"]),
                win=float(m["win"]) if m["win"] == m["win"] else None,
                n_trades=int(m["n_trades"]), total=float(m["total"]))


# ---------------- 3) 自检：注入引擎（不开权）必须复现原引擎 ----------------
log("自检：注入引擎 vs 原引擎（offset=0, N=20）…")
o_orig = stats_of(NS["run_engine"](comp, 20, offset=0))
o_inj = stats_of(run_engine_w(comp, 20, offset=0))
same = all(abs((o_orig[k] or 0) - (o_inj[k] or 0)) < 1e-9 for k in ("ann", "sharpe", "mdd", "total")) \
    and o_orig["n_trades"] == o_inj["n_trades"]
log(f"  原引擎 {o_orig}")
log(f"  注入后 {o_inj}")
log(f"  ⇒ 逐字节一致：{'PASS' if same else 'FAIL'}")
if not same:
    raise SystemExit("自检失败：注入改变了引擎行为，中止")

# ---------------- 4) 个股 IC / ICIR（PIT：右对齐滚动窗口，全向量化）----------------
log("计算个股滚动 IC / ICIR（60 日 IC 窗口 / 120 日 ICIR 窗口，全向量化）…")
# 个股未来 20 日收益（T+1 开盘 → T+21 开盘，与引擎成交口径一致）
fwd = np.full((ND, NC), np.nan)
for j in range(NC):
    o = O[:, j]
    idx = np.flatnonzero(np.isfinite(o))
    if len(idx) < 30:
        continue
    a = idx[:-21]
    b = idx[21:]
    fwd[a, j] = o[b] / o[idx[1:-20]] - 1

IC_W, ICIR_W = 60, 120
# ⚠ 2026-09-20 修：原来只在 offset=0 的调仓日算 IC → 其他 19 个相位上 IC 全 NaN、
#    权重回退等权，相位扫描对加权臂形同虚设（phmedΔ 全是 0.00）。改为**全日期**计算。
all_days = list(range(WARMUP + IC_W, ND))
IC = np.full((ND, NC), np.nan)
t_ic = time.time()
for di in all_days:
    lo = di - IC_W + 1
    S = comp[lo:di + 1, :]
    Fv = fwd[lo:di + 1, :]
    M = np.isfinite(S) & np.isfinite(Fv)
    n = M.sum(0).astype(float)
    S0 = np.where(M, S, 0.0)
    F0 = np.where(M, Fv, 0.0)
    sS, sF = S0.sum(0), F0.sum(0)
    sSS, sFF, sSF = (S0 * S0).sum(0), (F0 * F0).sum(0), (S0 * F0).sum(0)
    num = n * sSF - sS * sF
    den = np.sqrt(np.maximum(n * sSS - sS * sS, 0.0) * np.maximum(n * sFF - sF * sF, 0.0))
    IC[di, :] = np.where((den > 0) & (n >= 30), num / np.where(den > 0, den, 1.0), np.nan)
# ICIR：全日期滚动 120 日均值/标准差
_icdf = pd.DataFrame(IC)
_mu = _icdf.rolling(ICIR_W, min_periods=60).mean()
_sd = _icdf.rolling(ICIR_W, min_periods=60).std()
with np.errstate(invalid="ignore", divide="ignore"):
    ICIR = (_mu / _sd.replace(0.0, np.nan)).to_numpy()
log(f"IC/ICIR 完成（{time.time()-t_ic:.0f}s）｜IC 有效格 {np.isfinite(IC).sum()}｜ICIR 有效格 {np.isfinite(ICIR).sum()}")
np.save(HERE / "posw_ic.npy", IC)
np.save(HERE / "posw_icir.npy", ICIR)

# ---------------- 5) 权重函数工厂 ----------------
DIAG = []
N_FIXED = 20          # 引擎 run_engine 的 N 参数（闸门关闭时 N_eff=N//2，但等权基线恒按 eq/N 下单）


def mk_wfn(kind):
    def wfn(di, topN, row):
        arr = np.full(NC, 0.0)
        idx = np.array(topN, dtype=int)
        s = row[idx].astype(float)
        if kind == "A3":
            # 头部倾斜：前一半 3/4、后一半 1/4（组内按 A1 的 shifted 线性分摊）
            # ⚠ 2026-09-20 修：原来写在 `if kind.startswith("A")` 分支之后用 elif，
            #   导致 A3 被 A1 分支吞掉、两者结果逐位相同（假臂）
            half = max(1, len(idx) // 2)
            lo, hi = s.min(), s.max()
            base = s - lo + 0.25 * max(hi - lo, 1e-12)
            w = np.empty(len(idx))
            w[:half] = (base[:half] / base[:half].sum()) * 0.75
            w[half:] = (base[half:] / base[half:].sum()) * 0.25
        elif kind.startswith("A"):
            lo, hi = s.min(), s.max()
            rng = max(hi - lo, 1e-12)
            sh = s - lo + 0.25 * rng                     # 正移线性
            if kind == "A2":
                sh = sh ** 2
            w = sh / sh.sum()
        elif kind in ("C1", "C2", "C3"):
            src = IC if kind == "C1" else ICIR
            v = np.abs(src[di, idx]).astype(float)
            good = np.isfinite(v)
            if good.sum() < max(2, len(idx) // 2):      # 覆盖不足 → 回退等权
                w = np.ones(len(idx)) / len(idx)
            else:
                med = float(np.nanmedian(v[good]))
                v = np.where(np.isfinite(v), v, med)
                if kind == "C3":
                    v = np.minimum(v, 2 * med if med > 0 else v)
                lo, hi = v.min(), v.max()
                v = v - lo + 0.25 * max(hi - lo, 1e-12)
                w = v / v.sum()
        else:
            w = np.ones(len(idx)) / len(idx)
        # ⚠ 2026-09-20 修：权重必须归一到 N_eff/N（而不是 1），否则闸门关闭（N_eff=10）时
        #    权重臂会部署满仓、而等权基线只部署半仓 → 总敞口不同，比较被污染
        #    （旧版回退分支 ones(len)/len(idx) 在 N_eff=10 时给每只 eq/10 = 满仓，
        #     实测把 C 臂相位中位从 17.09% 虚抬到 21.80%，并让 C1/C2/C3 中位数完全相同）
        w = w / w.sum() * (len(idx) / float(N_FIXED))
        arr[idx] = w
        _NS2["WG"][:] = arr
        DIAG.append((di, idx.copy(), w.copy()))
    return wfn


# ---------------- 6) 跑臂 ----------------
ARMS = [("B0 等权(基线)", None), ("A1 信号强度·线性", "A1"), ("A2 信号强度·平方", "A2"),
        ("A3 头部倾斜3:1", "A3"), ("C1 个股IC·线性", "C1"), ("C2 个股ICIR", "C2"),
        ("C3 个股ICIR·截断", "C3")]
N = 20
res = {}
print(f"\n=== off0（N={N}）===")
print(f"  {'臂':<18}{'年化%':>8}{'夏普':>7}{'回撤%':>8}{'笔数':>6}{'Δ年化pp':>9}{'Δ夏普':>8}")
for name, kind in ARMS:
    _NS2["WG"] = np.full(NC, 1.0 / N)
    _NS2["WFN"] = mk_wfn(kind) if kind else None
    if kind is None:
        _NS2["WG"] = None
    m = stats_of(run_engine_w(comp, N, offset=0))
    res[name] = {"off0": m}
    b = res["B0 等权(基线)"]["off0"]
    d_ann = (m["ann"] - b["ann"]) * 100 if name != "B0 等权(基线)" else 0.0
    d_sh = (m["sharpe"] - b["sharpe"]) if name != "B0 等权(基线)" else 0.0
    print(f"  {name:<18}{m['ann']*100:>8.2f}{m['sharpe']:>7.2f}{m['mdd']*100:>8.1f}"
          f"{m['n_trades']:>6}{d_ann:>9.2f}{d_sh:>8.3f}")
    log(f"  {name} 完成")

# ---------------- 7) 相位扫描（20 相位，看 phmed）----------------
print(f"\n=== 相位扫描（20 相位）===")
print(f"  {'臂':<18}{'phmed年化%':>11}{'phmed夏普':>10}{'phmin夏普':>10}{'Δphmed年化pp':>13}")
for name, kind in ARMS:
    shs, anns = [], []
    for off in range(F):
        _NS2["WG"] = np.full(NC, 1.0 / N)
        _NS2["WFN"] = mk_wfn(kind) if kind else None
        if kind is None:
            _NS2["WG"] = None
        m = stats_of(run_engine_w(comp, N, offset=off))
        shs.append(m["sharpe"]); anns.append(m["ann"])
    res[name]["phmed"] = {"ann": float(np.median(anns)), "sharpe": float(np.median(shs)),
                          "phmin": float(np.min(shs))}
    b = res["B0 等权(基线)"]["phmed"]
    print(f"  {name:<18}{np.median(anns)*100:>11.2f}{np.median(shs):>10.3f}{np.min(shs):>10.3f}"
          f"{(np.median(anns)-b['ann'])*100:>13.2f}")
    log(f"  {name} 相位完成")

# ---------------- 8) 50bp 成本档 ----------------
print(f"\n=== 50bp 成本档（off0）===")
for name, kind in ARMS:
    _NS2["WG"] = np.full(NC, 1.0 / N)
    _NS2["WFN"] = mk_wfn(kind) if kind else None
    if kind is None:
        _NS2["WG"] = None
    m = stats_of(run_engine_w(comp, N, offset=0, slip=SLIP_STRESS))
    res[name]["slip50"] = m
    print(f"  {name:<18} 年化 {m['ann']*100:>7.2f}%  夏普 {m['sharpe']:>6.2f}  回撤 {m['mdd']*100:>6.1f}%")

# ---------------- 9) Dirichlet 随机权重对照 500 组 ----------------
log("Dirichlet 随机权重 500 组（同载体同成本 off0）…")
rng = np.random.default_rng(20260919)
rand_ann, rand_sh = [], []
reb_days = [di for di in range(WARMUP, ND) if (di - WARMUP) % F == 0 and di + 1 < ND]
for s_i in range(500):
    _NS2["WFN"] = None
    _NS2["WG"] = np.full(NC, 1.0 / N)
    seed_w = {}
    for di in reb_days:
        ok = np.flatnonzero(ELIG3[di] & np.isfinite(comp[di]))
        if len(ok) < N:
            continue
        gate = bool(np.isfinite(ma20sc[di]) and sc1000[di] > ma20sc[di])
        neff = N if gate else max(2, N // 2)
        cand = np.flatnonzero(ok)
        if not gate:
            sub = cand[np.isfinite(volpct[di][cand]) & (volpct[di][cand] <= 0.5)]
            if len(sub) >= neff:
                cand = sub
        topN = cand[np.argsort(-comp[di][cand])][:neff]
        w = rng.dirichlet(np.ones(len(topN)))
        for j, ww in zip(topN, w):
            seed_w[int(j)] = ww
    # 用固定的随机权重表跑一次（每个调仓日已写死）
    def wfn_fixed(di, topN, row):
        arr = np.zeros(NC)
        tot = sum(seed_w.get(int(j), 0.0) for j in topN)
        for j in topN:
            arr[int(j)] = seed_w.get(int(j), 0.0) / tot if tot > 0 else 1.0 / N_FIXED
        # 与实臂同口径：归一到 N_eff/N，保持总敞口与等权一致
        ssum = sum(arr[int(j)] for j in topN)
        for j in topN:
            arr[int(j)] = arr[int(j)] / ssum * (len(topN) / float(N_FIXED)) if ssum > 0 else 1.0 / N_FIXED
        _NS2["WG"][:] = arr
    _NS2["WFN"] = wfn_fixed
    m = stats_of(run_engine_w(comp, N, offset=0))
    rand_ann.append(m["ann"]); rand_sh.append(m["sharpe"])
    if (s_i + 1) % 100 == 0:
        log(f"  随机对照 {s_i+1}/500")
rand_ann = np.array(rand_ann); rand_sh = np.array(rand_sh)

# ---------------- 10) 汇总与门槛判定 ----------------
print("\n" + "=" * 100)
print("=== 门槛判定（预注册四条）===")
print(f"  {'臂':<18}{'Δ年化pp':>9}{'Δ夏普':>8}{'随机分位':>9}{'phmedΔ年化pp':>13}{'50bp年化%':>10}{'判定':>8}")
final = {"arms": res, "random": {"n": 500, "ann_med": float(np.median(rand_ann)),
                                 "ann_p80": float(np.quantile(rand_ann, 0.8)),
                                 "sh_med": float(np.median(rand_sh)),
                                 "sh_p80": float(np.quantile(rand_sh, 0.8))},
         "selfcheck_injected_engine_matches_original": bool(same)}
b0 = res["B0 等权(基线)"]["off0"]
b0ph = res["B0 等权(基线)"]["phmed"]
for name, kind in ARMS:
    if name == "B0 等权(基线)":
        continue
    m, ph = res[name]["off0"], res[name]["phmed"]
    d_ann = (m["ann"] - b0["ann"]) * 100
    d_sh = m["sharpe"] - b0["sharpe"]
    pct = float((rand_ann < m["ann"]).mean())
    d_ph = (ph["ann"] - b0ph["ann"]) * 100
    g1 = d_ann >= 2.0 and d_sh >= 0.05
    g2 = pct >= 0.8
    g3 = d_ph >= 0.0
    g4 = res[name]["slip50"]["ann"] > 0
    ok = g1 and g2 and g3 and g4
    print(f"  {name:<18}{d_ann:>9.2f}{d_sh:>8.3f}{pct:>9.2f}{d_ph:>13.2f}"
          f"{res[name]['slip50']['ann']*100:>10.2f}{'✅过' if ok else '❌':>8}")
    final["arms"][name]["gates"] = {"g1_delta": g1, "g2_random_pct": g2, "g3_phmed": g3,
                                    "g4_slip50": g4, "random_pctile": pct, "pass": bool(ok)}
print(f"\n  随机对照（500 组）年化：中位 {np.median(rand_ann)*100:.2f}%｜p80 {np.quantile(rand_ann,.8)*100:.2f}%｜"
      f"max {rand_ann.max()*100:.2f}%")
print(f"  等权基线 off0 年化 {b0['ann']*100:.2f}%（在随机分布分位 {(rand_ann<b0['ann']).mean():.2f}）")
(HERE / "posw_0919.json").write_text(json.dumps(final, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
log("落盘 posw_0919.json")
