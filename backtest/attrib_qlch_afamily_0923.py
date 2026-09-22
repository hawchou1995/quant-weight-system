# -*- coding: utf-8 -*-
"""归档：qlch A 族失效归因与三因素敏感性（R-attrib-afamily-0923）。

来源：2026-09-23 会话 scratch 的 s2_core.py（一字未改），仅追加本说明头。
只读复用 backtest/qlch_paper_20260921.py 与 backtest/qlch_grid_bt_0923.py，不写仓库数据。
原始输出：backtest/attrib_qlch_afamily_0923.out.txt
复现：python backtest/attrib_qlch_afamily_0923.py（约 45s；产物写系统临时目录）
"""
# -*- coding: utf8 -*-
"""s2_core.py — 只读分析：A 类入场（gap∈[-5%,-2%]）在 2022 年后失去优势的归因。

复用（只读、不写仓库）：
  backtest/qlch_paper_20260921.py   —— load_all() / build_signals()
  backtest/qlch_grid_bt_0923.py     —— entry_cases / case_path / resolve_exit /
                                       exit_plan / simulate / metrics_all
  backtest/index_000300.csv         —— 熊市门 & 市况分桶
所有产物只写 scratch。

口径（与 grid 一致）：TP15 / SL-20 / H20 · K=3 槽位 · 5 固定种子 ·
                     单笔成本 = cost_bp（主口径 60bp = 往返20 + 每边滑点20×2）
"""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

T0 = time.time()
SCRATCH = Path(r"C:\Users\Admin\.pi-desktop\scratch\819deaca-ff8f-4e41-a272-5b5cb031c25d")
BK = Path(r"D:\Documents\Workbuddy\股票基金\quant-weight-system\backtest")
BASE = BK.parent
IDX = BASE / "index_000300.csv"
if str(BK) not in sys.path:
    sys.path.insert(0, str(BK))

SEEDS = [20260921, 20260922, 20260923, 20260924, 20260925]
K = 3
TPS, SLS, HS = 15, -20, 20          # 基线格
KMAX = 39
COST_BASE = 60                      # bp，主口径
TRAIN_HI, VAL_LO = "2021-12-31", "2022-01-01"


def log(*a):
    print("[%7.1fs]" % (time.time() - T0), *a, flush=True)


# ------------------------------------------------------------------ 引擎/网格接入
def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_engine(variant, mainboard, gate, tag):
    """环境变量必须在 exec_module 之前设置（引擎为模块级常量）。"""
    os.environ["QLCH_VARIANT"] = variant
    os.environ["QLCH_MAINBOARD"] = mainboard
    os.environ["QLCH_GATE"] = gate
    m = load_mod("qlch_eng_" + tag, BK / "qlch_paper_20260921.py")
    return m


GRID = load_mod("qgrid", BK / "qlch_grid_bt_0923.py")
log("网格脚本已载入（module 级，main() 未执行）")

CFGS = {
    "MB_GATE":    ("B4", "1", "20"),   # 生产配置：真主板 + 熊市门
    "FULL_GATE":  ("B4", "0", "20"),   # B4 全池 + 熊市门（对齐 ZCode 池）
    "MB_NOGATE":  ("B4", "1", "0"),    # 真主板 + 无门
    "FULL_NOGATE": ("B4", "0", "0"),   # B4 全池 + 无门
}

# ---- P 只读一次（load_all 与配置无关；val_em 三个大 CSV）----
ENG0 = load_engine(*CFGS["MB_GATE"], "MB_GATE")
P = ENG0.load_all()
log("面板载入：close %s，%s .. %s" % (str(P["close"].shape), P["cal"][0], P["cal"][-1]))
T, N = P["close"].shape
cal = P["cal"]

STATE = {}
for tag, (v, mb, g) in CFGS.items():
    eng = load_engine(v, mb, g, tag)
    S = eng.build_signals(P)
    ents = GRID.entry_cases(S)
    cnt_all = {k: int(ents[k]["e"].size) for k in "ABC"}
    a = ents["A"]
    o = np.argsort(a["e"], kind="stable")
    e, j, px = a["e"][o], a["j"][o], a["px"][o]
    i_first_all = int(min(ents[k]["e"].min() for k in "ABC"))
    STATE[tag] = dict(S=S, e=e, j=j, px=px, cnt=cnt_all,
                      cand_days=int(np.isfinite(S["cand"].sum()) and S["cand"].sum()),
                      A_first=int(e.min()), A_last=int(e.max()),
                      first_all=i_first_all,
                      dstr=(cal[int(e.min())], cal[int(e.max())]))
    log("%-11s cand 信号日 %6d | 情形 A=%5d B=%4d C=%6d | A 首笔 %s 末笔 %s | i_first(A∪B∪C)=%s"
        % (tag, int(S["cand"].sum()), cnt_all["A"], cnt_all["B"], cnt_all["C"],
           cal[int(e.min())], cal[int(e.max())], cal[i_first_all]))

# 索引窗口边界
i_train = max(i for i, d in enumerate(cal) if d <= TRAIN_HI)
i_val = min(i for i, d in enumerate(cal) if d >= VAL_LO)
log("i_train=%d(%s) i_val=%d(%s) T-1=%d(%s)" % (i_train, cal[i_train], i_val, cal[i_val], T - 1, cal[-1]))


# ------------------------------------------------------------------ 单元回测
def prep_exit(tag):
    """出场计划与成本无关 → 每配置只算一次。"""
    st = STATE[tag]
    e, j, px = st["e"], st["j"], st["px"]
    S = st["S"]
    Oa, Ha, La, Ca = GRID.case_path(e, j, S["open"], S["high"], S["low"], S["close"], T, KMAX)
    kf, ex_px, ex_rs, hit = GRID.resolve_exit(px, Oa, Ha, La, Ca, TPS / 100.0, SLS / 100.0)
    use, x, opx, hold, rsn = GRID.exit_plan(e, px, kf, ex_px, ex_rs, hit, Ca, HS, T)
    st.update(use=use, x=x, opx=opx, hold=hold, rsn=rsn)
    return st


def run_cell(tag, cost_bp, K_=K):
    st = STATE[tag]
    if "use" not in st:
        prep_exit(tag)
    use, x, opx, hold = st["use"], st["x"], st["opx"], st["hold"]
    e, px = st["e"][use], st["px"][use]
    ret = opx[use] / px - 1.0 - cost_bp / 10000.0
    nav, inv, te, tx, tr, th, tv = GRID.simulate(e, x[use], ret, hold[use], T, SEEDS, K_)
    return dict(nav=nav, inv=inv, te=te, tx=tx, tr=tr, th=th, tv=tv,
                e=e, px=px, opx=opx[use], hold=hold[use], rsn=st["rsn"][use])


for tag in CFGS:
    prep_exit(tag)
log("四配置出场计划已生成")

# 全样本/训练/验证（口径与 grid 完全一致：i_first 取 A∪B∪C 首笔）
SLICES = {}
for tag in CFGS:
    i0 = STATE[tag]["first_all"]
    SLICES[tag] = {"full": (i0, T - 1), "train": (i0, i_train), "val": (i_val, T - 1)}


def metrics(cell, slices):
    return GRID.metrics_all(cell["nav"], cell["inv"], cell["te"], cell["tr"], cell["th"],
                            cell["tv"], slices, len(SEEDS))


# ------------------------------------------------------------------ 1) 分年度绩效
def year_slices(tag):
    i0 = STATE[tag]["first_all"]
    out, prev = {}, i0
    for y in range(int(cal[i0][:4]), int(cal[-1][:4]) + 1):
        idx = [i for i, d in enumerate(cal) if d[:4] == str(y) and i > prev]
        if not idx:
            continue
        i1 = max(idx)
        out[str(y)] = (prev, i1)
        prev = i1
    return out


Y = year_slices("MB_GATE")
BASELINE = {bp: run_cell("MB_GATE", bp) for bp in (0, 20, 60)}
BASE60 = BASELINE[60]
m_year = metrics(BASE60, Y)
m_win = metrics(BASE60, SLICES["MB_GATE"])

print("\n" + "=" * 118)
print("【1】A 基线（TP15/SL-20/H20 · 真主板+B4 · 熊市门 MA20 · K=3 · 5 种子 · 单笔成本 60bp）逐自然年")
print("=" * 118)
print("%-6s %-11s %-11s %6s %7s %7s %9s %8s %8s %8s %7s" %
      ("年", "起点", "终点", "笔数", "胜率%", "均笔%", "年化%", "夏普", "回撤%", "持有日", "占用%"))
for k, v in m_year.items():
    i0, i1 = Y[k]
    print("%-6s %-11s %-11s %6d %7.2f %+7.3f %+9.2f %8.3f %+8.2f %8.2f %7.1f" %
          (k, cal[i0], cal[i1], v["n"], v["wr"], v["ret"], v["cagr"], v["sharpe"],
           v["mdd"], v["hold"], v["inv"]))
print("%-6s %-11s %-11s %6d %7.2f %+7.3f %+9.2f %8.3f %+8.2f %8.2f %7.1f" %
      ("FULL", cal[STATE["MB_GATE"]["first_all"]], cal[-1], m_win["full"]["n"],
       m_win["full"]["wr"], m_win["full"]["ret"], m_win["full"]["cagr"],
       m_win["full"]["sharpe"], m_win["full"]["mdd"], m_win["full"]["hold"], m_win["full"]["inv"]))
print("%-6s %-11s %-11s %6d %7.2f %+7.3f %+9.2f %8.3f %+8.2f %8.2f %7.1f" %
      ("TRAIN", cal[STATE["MB_GATE"]["first_all"]], cal[i_train], m_win["train"]["n"],
       m_win["train"]["wr"], m_win["train"]["ret"], m_win["train"]["cagr"],
       m_win["train"]["sharpe"], m_win["train"]["mdd"], m_win["train"]["hold"], m_win["train"]["inv"]))
print("%-6s %-11s %-11s %6d %7.2f %+7.3f %+9.2f %8.3f %+8.2f %8.2f %7.1f" %
      ("VAL", cal[i_val], cal[-1], m_win["val"]["n"], m_win["val"]["wr"], m_win["val"]["ret"],
       m_win["val"]["cagr"], m_win["val"]["sharpe"], m_win["val"]["mdd"],
       m_win["val"]["hold"], m_win["val"]["inv"]))

# ---- 自证：与已发布的 grid JSON 基线行对拍（口径一致性硬证据）----
_J = json.load(open(BK / "qlch_grid_bt_0923.json", encoding="utf-8"))
_ref = [c for c in _J["baseline"] if c["entry"] == "A"][0]
print("\n[自证] 本机复算 vs backtest/qlch_grid_bt_0923.json baseline[A]（full 窗）")
for _k in ("n", "wr", "cagr", "sharpe", "mdd", "hold", "ord", "turn", "inv"):
    print("   %-7s 复算 %11.4f | JSON %11.4f | Δ %+.6f" % (_k, m_win["full"][_k], _ref[_k], m_win["full"][_k] - _ref[_k]))
for _k in ("tr_n", "tr_cagr", "tr_sharpe", "tr_mdd", "va_n", "va_cagr", "va_sharpe", "va_mdd"):
    _w = "train" if _k.startswith("tr") else "val"
    _k2 = _k[3:]
    print("   %-7s 复算 %11.4f | JSON %11.4f | Δ %+.6f" % (_k, m_win[_w][_k2], _ref[_k], m_win[_w][_k2] - _ref[_k]))
print("   [机会数] 全池+门 A 情形 %d（ZCode 报告 3895）；真主板+门 A 情形 %d"
      % (STATE["FULL_GATE"]["cnt"]["A"], STATE["MB_GATE"]["cnt"]["A"]))

# A 首笔起点口径（去掉前导死区）——检验「窗口起点」对年化的稀释
SL_AONLY = {"full_Astart": (STATE["MB_GATE"]["A_first"], T - 1)}
m_aonly = metrics(BASE60, SL_AONLY)
print("\n[窗口起点敏感性] grid 口径 full 起点=%s（A∪B∪C 首笔）；A 首笔=%s；起点差 %d 日" %
      (cal[STATE["MB_GATE"]["first_all"]], cal[STATE["MB_GATE"]["A_first"]],
       STATE["MB_GATE"]["A_first"] - STATE["MB_GATE"]["first_all"]))
print("   full(i_first)  年化 %+7.2f%% 夏普 %6.3f" % (m_win["full"]["cagr"], m_win["full"]["sharpe"]))
print("   full(A_first)  年化 %+7.2f%% 夏普 %6.3f" %
      (m_aonly["full_Astart"]["cagr"], m_aonly["full_Astart"]["sharpe"]))

# ---- 窗口口径对照：ZCode 卡用「绝对净值水平」算年化，本机用「窗口内归一」----
SLICES["MB_GATE"]["zcode_full"] = (0, T - 1)      # 2016-01-04 起点（ZCode 卡的 ks[0]）
_mzf = metrics(BASE60, {"zcode_full": SLICES["MB_GATE"]["zcode_full"]})["zcode_full"]
print("\n[窗口口径对照] A 基线 nav：2016-01-04=%.4f  首笔日(%s)=%.4f  2021-12-31=%.4f  2026-09-22=%.4f"
      % (BASE60["nav"][0], cal[STATE["MB_GATE"]["A_first"]],
         BASE60["nav"][STATE["MB_GATE"]["A_first"]], BASE60["nav"][i_train], BASE60["nav"][-1]))
print("   (a) ZCode 卡公式 v[-1]^(1/yrs)-1，窗口起点 2016-01-04 → 年化 %+.2f%% 夏普 %.3f"
      % (_mzf["cagr"], _mzf["sharpe"]))
print("   (b) 本机公式（窗口内归一）同一窗口 → 年化 %+.2f%%"
      % (100 * ((BASE60["nav"][-1] / BASE60["nav"][0]) ** (244.0 / (T - 1)) - 1.0)))
print("   (c) 验证窗 2022-01-04→末 窗口内真实年化 %+.2f%%（本机公式）"
      % m_win["val"]["cagr"])

# 成本档对比（全样本/训练/验证）
print("\n[成本档] A 基线在三窗下的 年化/夏普（0 / 20 / 60 bp 单笔）")
print("%-6s | %-22s | %-22s | %-22s" % ("cost", "full", "train", "val"))
for bp in (0, 20, 60):
    mm = metrics(BASELINE[bp], SLICES["MB_GATE"])
    print("%-6s | %+7.2f%% / %6.3f     | %+7.2f%% / %6.3f     | %+7.2f%% / %6.3f" %
          ("%dbp" % bp, mm["full"]["cagr"], mm["full"]["sharpe"],
           mm["train"]["cagr"], mm["train"]["sharpe"], mm["val"]["cagr"], mm["val"]["sharpe"]))

# ------------------------------------------------------------------ 2) 市况归因
idx = pd.read_csv(IDX, parse_dates=["date"])
idx["d"] = idx["date"].dt.strftime("%Y-%m-%d")
ic = idx.close.astype(np.float64).values
ima20 = pd.Series(ic).rolling(20).mean().values
i2t = {d: k for k, d in enumerate(idx["d"])}
bull = np.full(T, np.nan)
mkt_ret = np.full(T, np.nan)       # HS300 当日收益
mkt_r20 = np.full(T, np.nan)       # HS300 近 20 日收益
for t, d in enumerate(cal):
    k = i2t.get(d)
    if k is None:
        continue
    if np.isfinite(ima20[k]):
        bull[t] = 1.0 if ic[k] > ima20[k] else 0.0
    if k > 0 and ic[k - 1] > 0:
        mkt_ret[t] = ic[k] / ic[k - 1] - 1.0
        mkt_r20[t] = ic[k] / ic[k - 20] - 1.0
log("市况序列完成（HS300 覆盖 %d/%d 日）" % (int(np.isfinite(bull).sum()), T))


def regime_report(tag, cost_bp, bucket_kind, edges, labels, label):
    cell = BASELINE[cost_bp] if (tag == "MB_GATE" and cost_bp in BASELINE) else run_cell(tag, cost_bp)
    nav = cell["nav"]
    rr = np.full(T, np.nan)
    rr[1:] = np.diff(nav) / nav[:-1]
    i0 = STATE[tag]["first_all"]
    if bucket_kind == "bull":
        key = bull
    elif bucket_kind == "mkt_ret":
        key = mkt_ret
    else:
        key = mkt_r20
    # 桶标签
    lab = np.full(T, "", dtype=object)
    if bucket_kind == "bull":
        lab[np.where(key == 1.0)[0]] = labels[0]
        lab[np.where(key == 0.0)[0]] = labels[1]
    else:
        for i in range(len(edges) - 1):
            m = (key > edges[i]) & (key <= edges[i + 1])
            lab[np.where(m)[0]] = labels[i]
    rows = []
    ent_day, ent_ret = cell["te"], cell["tr"]     # simulate 的 te/tr 同序对齐（入场日/净收益）
    print("\n" + "-" * 118)
    print("【2】%s — %s（配置 %s / 成本 %dbp / 窗口 %s..%s）" %
          (label, bucket_kind, tag, cost_bp, cal[i0], cal[-1]))
    print("%-14s %6s %8s %8s %9s %8s | %6s %8s %8s" %
          ("桶", "天数", "日收益均%", "日胜率%", "桶内累计%", "等效年化%", "笔数", "均笔%", "笔胜率%"))
    for L in labels:
        m = (lab == L) & np.isfinite(rr)
        m[:STATE[tag]["A_first"] + 1] = False
        if m.sum() == 0:
            print("%-14s %6d %8s %8s %9s %8s | %6d %8s %8s" % (L, 0, "-", "-", "-", "-", 0, "-", "-"))
            rows.append(dict(bucket=L, days=0))
            continue
        r = rr[m]
        prod = float(np.prod(1.0 + r) - 1.0) * 100
        yrs = m.sum() / 244.0
        ann = ((1.0 + prod / 100.0) ** (1.0 / yrs) - 1.0) * 100 if yrs > 0 else 0.0
        sel = m[ent_day]
        n_ = int(sel.sum())
        ptr = ent_ret[sel]
        print("%-14s %6d %+8.4f %8.2f %+9.2f %+8.2f | %6d %+8.3f %8.2f" %
              (L, int(m.sum()), 100 * r.mean(), 100 * (r > 0).mean(), prod, ann,
               n_, 100 * ptr.mean() if n_ else 0.0, 100 * (ptr > 0).mean() if n_ else 0.0))
        rows.append(dict(bucket=L, days=int(m.sum()), dmean=float(100 * r.mean()),
                         dwin=float(100 * (r > 0).mean()), cum=prod, ann=ann,
                         n=n_, pt=float(100 * ptr.mean()) if n_ else None,
                         ptw=float(100 * (ptr > 0).mean()) if n_ else None))
    return rows


REG = {}
REG["MB_GATE_60_bull"] = regime_report("MB_GATE", 60, "bull", None, ["HS300>MA20（牛）", "HS300<MA20（熊）"], "A 基线（门开）")
REG["MB_GATE_60_r20"] = regime_report("MB_GATE", 60, "mkt_r20",
                                      [-1.0, -0.05, 0.0, 0.05, 1.0],
                                      ["市场20日≤-5%", "-5%~0", "0~+5%", ">+5%"], "A 基线（门开）")
REG["MB_GATE_60_ret"] = regime_report("MB_GATE", 60, "mkt_ret",
                                      [-1.0, -0.02, 0.0, 0.02, 1.0],
                                      ["当日≤-2%", "-2%~0", "0~+2%", ">+2%"], "A 基线（门开）")
REG["MB_NOGATE_60_bull"] = regime_report("MB_NOGATE", 60, "bull", None, ["HS300>MA20（牛）", "HS300<MA20（熊）"], "门关（同池）")
REG["MB_NOGATE_60_r20"] = regime_report("MB_NOGATE", 60, "mkt_r20",
                                        [-1.0, -0.05, 0.0, 0.05, 1.0],
                                        ["市场20日≤-5%", "-5%~0", "0~+5%", ">+5%"], "门关（同池）")

# ------------------------------------------------------------------ 3) 三因素敏感性 2×3×2
print("\n" + "=" * 118)
print("【3】三因素敏感性：池（真主板 / B4全池）× 成本（0/20/60bp）× 熊市门（开/关）—— 其余完全相同")
print("=" * 118)
SENS = {}
CELLS = {}
print("%-11s %-6s %-7s | %19s | %19s | %19s" %
      ("池", "成本", "熊市门", "全样本 年化/夏普/回撤", "训练 年化/夏普/回撤", "验证 年化/夏普/回撤"))
for pool_tag, pool_name in (("MB", "真主板"), ("FULL", "B4全池")):
    for bp in (0, 20, 60):
        for gt, gname in (("GATE", "开"), ("NOGATE", "关")):
            tag = "%s_%s" % (pool_tag, gt)
            cell = run_cell(tag, bp)
            mm = metrics(cell, SLICES[tag])
            key = "%s|%dbp|%s" % (pool_name, bp, gname)
            SENS[key] = {w: dict(cagr=mm[w]["cagr"], sharpe=mm[w]["sharpe"], mdd=mm[w]["mdd"],
                                 n=mm[w]["n"], wr=mm[w]["wr"], inv=mm[w]["inv"])
                         for w in ("full", "train", "val")}
            if bp == 60:
                CELLS[tag] = cell
            print("%-11s %-6s %-7s | %+7.2f%% %6.3f %+7.2f | %+7.2f%% %6.3f %+7.2f | %+7.2f%% %6.3f %+7.2f" %
                  (pool_name, "%dbp" % bp, gname,
                   mm["full"]["cagr"], mm["full"]["sharpe"], mm["full"]["mdd"],
                   mm["train"]["cagr"], mm["train"]["sharpe"], mm["train"]["mdd"],
                   mm["val"]["cagr"], mm["val"]["sharpe"], mm["val"]["mdd"]))

# 逐因素摆动（保持其余两项为生产档：真主板 / 60bp / 门开）
print("\n[逐因素摆动] 生产档 = 真主板 · 60bp · 门开（基线）。每行只切换一项：")
BASE_REF = SENS["真主板|60bp|开"]
print("%-34s | %-24s | %-24s | %-24s" % ("切换", "full 年化/夏普", "train 年化/夏普", "val 年化/夏普"))
for label, key in (("基线（真主板/60bp/门开）", "真主板|60bp|开"),
                   ("① 池 → B4全池", "B4全池|60bp|开"),
                   ("② 成本 60→20bp", "真主板|20bp|开"),
                   ("② 成本 60→0bp", "真主板|0bp|开"),
                   ("③ 门 → 关", "真主板|60bp|关")):
    r = SENS[key]
    d = {w: (r[w]["cagr"] - BASE_REF[w]["cagr"], r[w]["sharpe"] - BASE_REF[w]["sharpe"])
         for w in ("full", "train", "val")}
    print("%-34s | %+7.2f%%(%+6.2f) %6.3f(%+5.2f) | %+7.2f%%(%+6.2f) %6.3f(%+5.2f) | %+7.2f%%(%+6.2f) %6.3f(%+5.2f)" %
          (label, r["full"]["cagr"], d["full"][0], r["full"]["sharpe"], d["full"][1],
           r["train"]["cagr"], d["train"][0], r["train"]["sharpe"], d["train"][1],
           r["val"]["cagr"], d["val"][0], r["val"]["sharpe"], d["val"][1]))

# 单因素跨越符号的幅度（验证窗）
print("\n[验证窗符号影响幅度] 只切一项 vs 基线(val 年化 %+.2f%% / 夏普 %.3f)：" %
      (BASE_REF["val"]["cagr"], BASE_REF["val"]["sharpe"]))
for label, key in (("池 → B4全池", "B4全池|60bp|开"), ("成本 60→20bp", "真主板|20bp|开"),
                   ("成本 60→0bp", "真主板|0bp|开"), ("门 → 关", "真主板|60bp|关"),
                   ("池+成本（全池/20bp）", "B4全池|20bp|开"), ("池+成本+门（全池/20bp/关）", "B4全池|20bp|关")):
    r = SENS[key]
    print("   %-26s val 年化 %+7.2f%% (Δ%+7.2f%%)  夏普 %6.3f (Δ%+6.3f)  回撤 %+7.2f%%" %
          (label, r["val"]["cagr"], r["val"]["cagr"] - BASE_REF["val"]["cagr"],
           r["val"]["sharpe"], r["val"]["sharpe"] - BASE_REF["val"]["sharpe"], r["val"]["mdd"]))

# ------------------------------------------------------------------ 4) ZCode 口径复算
def zcode_portfolio(st, cost_bp, seeds=SEEDS, K_=K):
    """逐行复刻 _tmp_0922_t1exit_v2.py 的 run()：
       槽位不封顶（每日最多开 K 单，不管已持多少）；base=cash 快照；w=1/max(len,K)。
       返回 (nav均值, trades[入场日,出场日,净收益])。"""
    st = STATE[st]
    use = st["use"]
    e, opx, hold, px = st["e"][use], st["opx"][use], st["hold"][use], st["px"][use]
    ret = opx / px - 1.0 - cost_bp / 10000.0
    xcore = np.minimum(np.maximum(e + hold - 1, e + 1), T - 1)
    by_day = {}
    for i in range(e.size):
        by_day.setdefault(int(e[i]), []).append(i)
    navs, alltr = [], []
    for sd in seeds:
        rng = np.random.default_rng(sd)
        cash, pos, nav, tr = 1.0, [], np.full(T, np.nan), []
        for t in range(T):
            still = []
            for p in pos:
                if p[0] == t:
                    cash += p[1] * (1.0 + p[2])
                    tr.append((p[3], p[0], p[2]))
                else:
                    still.append(p)
            pos = still
            lst = by_day.get(t)
            if lst and cash > 1e-12:
                sel = lst if len(lst) <= K_ else [lst[i] for i in sorted(rng.choice(len(lst), size=K_, replace=False))]
                w = 1.0 / max(len(sel), K_)
                base = cash
                for ii in sel:
                    alloc = base * w
                    cash -= alloc
                    pos.append((int(xcore[ii]), alloc, float(ret[ii]), t))
            mv = 0.0
            for x_, alloc, r_, e_ in pos:
                hold_ = max(x_ - e_ + 1, 1)
                elap = min(t - e_ + 1, hold_)
                mv += alloc * ((1.0 + r_) ** (elap / hold_))
            nav[t] = cash + mv
        navs.append(nav)
        alltr.extend(tr)
    return np.mean(navs, axis=0), np.array(alltr, dtype=np.float64)


def zcode_stats(nav, tr, lo, hi):
    """逐行复刻 _tmp_0922_t1exit_v2.stats()（相同的窗口/年化/夏普/回撤定义）。"""
    ks = [k for k, d in enumerate(cal) if lo <= d <= hi]
    v = nav[ks[0]:ks[-1] + 1]
    rr = np.diff(v) / v[:-1]
    yrs = max(len(v) / 244.0, 1e-9)
    cagr = (v[-1] ** (1 / yrs) - 1) * 100
    sh = np.mean(rr) / np.std(rr) * np.sqrt(244) if np.std(rr) > 0 else float("nan")
    dd = 100 * float((v / np.maximum.accumulate(v) - 1.0).min())
    m = (tr[:, 0] >= ks[0]) & (tr[:, 0] <= ks[-1]) if tr.size else np.zeros(0, bool)
    tt = tr[m] if tr.size else tr
    rets = tt[:, 2] if tt.size else np.zeros(0)
    daym = {}
    for a, b, c in tt:
        daym.setdefault(int(a), []).append(c)
    dayavg = np.array([np.mean(z) for z in daym.values()]) if daym else np.zeros(0)
    yr = {}
    for kk in range(1, len(v)):
        yr.setdefault(str(cal[ks[0] + kk])[:4], []).append(v[kk] / v[kk - 1] - 1.0)
    yret = {y: float(100 * (np.prod([1 + z for z in a]) - 1.0)) for y, a in yr.items()}
    return dict(n=int(rets.size), nd=int(len(dayavg)),
                pt=100 * float(rets.mean()) if rets.size else 0.0,
                ptw=100 * float((rets > 0).mean()) if rets.size else 0.0,
                dt=100 * float(dayavg.mean()) if dayavg.size else 0.0,
                dtw=100 * float((dayavg > 0).mean()) if dayavg.size else 0.0,
                cagr=float(cagr), sh=float(sh), dd=float(dd),
                cagr_win=float((v[-1] / v[0]) ** (1 / yrs) - 1) * 100,
                lvl0=float(v[0]), lvl1=float(v[-1]),
                years=float(yrs), span=(cal[ks[0]], cal[ks[-1]]), yr=yret)


print("\n" + "=" * 118)
print("【4】ZCode 口径复算（对齐 _tmp_0922_t1exit_v2.py / qlch_bt_t1exit_0922.json 的 E4）")
print("=" * 118)
print("ZCode 目标值 TR20|E4: n=1672 cagr=+12.63 sh=2.539 mdd=-18.38 按笔胜率56.5 按天胜率63.1 (窗口 2016-01-04..2021-12-31)")
print("ZCode 目标值 VA20|E4: n=1955 cagr=+22.10 sh=0.684 mdd=-33.62 按笔胜率59.6 按天胜率56.8 (窗口 2022-01-04..2026-09-22)")
print("ZCode 目标值 VA50|E4: n=1955 cagr=+16.13 sh=0.327 mdd=-35.73")
ZREP = {}
Z_WINDOWS = [("ZCode-TR(2016-01-04..2021-12-31)", "0000", "2021-12-31"),
             ("本机-train(A首笔..2021-12-31)", None, "2021-12-31"),
             ("ZCode-VA(2022-01-01..末)", "2022-01-01", "9999")]
for tag, poolname in (("FULL_GATE", "B4全池"), ("MB_GATE", "真主板")):
    for mech, mechname in (("zcode", "ZCode机制(槽位不封顶)"), ("grid", "本机机制(K=3槽位)")):
        for bp in (20, 50):
            if mech == "zcode":
                nav, tr = zcode_portfolio(tag, bp)
                trr = np.array([[a, b, c] for a, b, c in tr], dtype=np.float64)
            else:
                cell = run_cell(tag, bp)
                nav = cell["nav"]
                trr = np.stack([cell["te"].astype(np.float64), cell["tx"].astype(np.float64),
                                cell["tr"]]).T
            for wname, lo, hi in Z_WINDOWS:
                if lo is None:
                    lo = cal[STATE[tag]["A_first"]]
                r = zcode_stats(nav, trr, lo, hi)
                ZREP["%s|%s|%dbp|%s" % (poolname, mechname, bp, wname)] = r
                print("  %-7s %-22s %3dbp %-32s n=%5d nd=%4d 卡年化=%+7.2f%% 窗口年化=%+7.2f%% sh=%6.3f mdd=%+7.2f%% 按笔%5.1f%% 按天%5.1f%% 净值 %.3f→%.3f (%s..%s, %.2fy)" %
                      (poolname, mechname, bp, wname, r["n"], r["nd"], r["cagr"], r["cagr_win"],
                       r["sh"], r["dd"], r["ptw"], r["dtw"], r["lvl0"], r["lvl1"],
                       r["span"][0], r["span"][1], r["years"]))
                print("         分年 %s" % {y: round(v, 2) for y, v in sorted(r["yr"].items())})
    print()

# ------------------------------------------------------------------ 落盘
OUT = dict(
    meta=dict(script="s2_core.py（scratch）", run_at=time.strftime("%Y-%m-%d %H:%M:%S"),
              engine="backtest/qlch_paper_20260921.py + backtest/qlch_grid_bt_0923.py",
              panel=[cal[0], cal[-1], T, N], K=K, seeds=SEEDS, tp=TPS, sl=SLS, h=HS,
              cost_base_bp=COST_BASE, note="只读分析，未写任何仓库文件"),
    cfg_counts={t: dict(cnt=STATE[t]["cnt"], A_first=cal[STATE[t]["A_first"]],
                        A_last=cal[STATE[t]["A_last"]],
                        first_all=cal[STATE[t]["first_all"]],
                        cand_signal_days=int(STATE[t]["S"]["cand"].sum())) for t in CFGS},
    yearly=m_year, windows=m_win, a_start_only=m_aonly,
    cost_ladder={str(bp): metrics(BASELINE[bp], SLICES["MB_GATE"]) for bp in (0, 20, 60)},
    regime=REG, sens=SENS, zcode=ZREP,
)
json.dump(OUT, open(SCRATCH / "s2_core.out.json", "w", encoding="utf-8"),
                            ensure_ascii=False, indent=1, default=float)
log("已落盘 %s" % (SCRATCH / "s2_core.out.json"))
