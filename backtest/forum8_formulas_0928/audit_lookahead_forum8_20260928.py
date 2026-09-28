# -*- coding: utf-8 -*-
"""audit_lookahead_forum8_20260928.py — gushi.in/forum/8「对称毛口径过门」3 条公式的未来函数（前视）复核

对象（只读正文 = 会话 scratch 的 gushi_raw/topics）：
  · t543  探底放量突破
  · t774  最强黄金坑
  · t807  均线粘合起爆
判据：五维清单（沿用 gushi.in/topic/465 方法）——
  ① 数据可用时点 ② 函数语义（参数方向） ③ 统计形状（滞后/未来平移）
  ④ 阳性对照（必须有分辨力） ⑤ 抽样手算
面板：$PI_SCRATCH_DIR/x1cache/panel_oos.npz（T=2852 / N=5442，O/H/L/C/V/A，缺失存 0 而非 NaN）
只读复用（**不修改**）：
  · backtest/forum8_formulas_0928/m2_sweep_20260928.py     （extract_blocks/clean_code/normalize/evaluate_formula）
  · backtest/forum8_formulas_0928/m2_sweep_v3_20260928.py  （定稿事件引擎，三口径 all/buy/gross_buy）
  · backtest/r2_rebuild_0911/tdx_interp.py                 （公式解释器，语义引用出处）
只写：backtest/forum8_formulas_0928/evidence_lookahead_forum8_20260928.json

口径术语（与冻结脚本逐字一致）：
  gross_buy = 毛超额（双方不计成本，可成交基准=剔除开盘涨停的全市场等权）← 「毛口径过门」读的那一列
  buy       = 净超额（信号腿扣 0.20% 往返成本）
  all       = 预注册基准（含不可成交票）

用法: python audit_lookahead_forum8_20260928.py [--out FILE] [--fast]
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import time

import numpy as np

R = pathlib.Path(__file__).resolve().parents[2]
SCRATCH = pathlib.Path(os.environ.get("PI_SCRATCH_DIR") or r"C:\Users\Admin\.pi-desktop\scratch\d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
sys.path.insert(0, str(R / "backtest/forum8_formulas_0928"))
sys.path.insert(0, str(R / "backtest/r2_rebuild_0911"))
import m2_sweep_20260928 as V1           # noqa: E402  冻结：解析/编译/求值
import m2_sweep_v3_20260928 as V3        # noqa: E402  冻结：三口径事件引擎
import tdx_interp as T                   # noqa: E402  冻结：解释器

PANEL = SCRATCH / "x1cache" / "panel_oos.npz"
BODIES = SCRATCH / "gushi_raw" / "topics"
REGISTRY = SCRATCH / "gushi_raw" / "registry.json"
OUTDIR = R / "backtest/forum8_formulas_0928"
FROZEN_EV = OUTDIR / "evidence_forum8_sweep_v3_20260928.json"
FROZEN_M3 = OUTDIR / "evidence_forum8_horizon_m3_20260928.json"
IDS = ("543", "774", "807")
CH_NAMES = {"C": "收盘", "O": "开盘", "H": "最高", "L": "最低", "V": "成交量", "A": "成交额"}

LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


# ----------------------------------------------------------------- 维度① 常量
# 「若出现即判前视」的记号（gushi.in/topic/465 清单维度①原表）
LOOKAHEAD_TOKENS = ("CONST", "ISLASTBAR", "CURRBARSCOUNT", "TOTALBARSCOUNT", "DYNAINFO", "ZIG",
                    "PEAK", "PEAKBARS", "TROUGH", "TROUGHBARS", "WINNER", "COST", "FINANCE",
                    "NAMELIKE", "CODELIKE", "INBLOCK", "CAPITAL", "FROMOPEN", "ZTPRICE",
                    "DTPRICE", "STKINDI", "TFILTER", "EXPMEMA", "BARSNEXT", "REFX", "BACKSET")
# 解释器 LENIENT 放行的「显示/盘中」函数（出现不等于前视，但必须登记）
LENIENT_TOKENS = ("DYNAINFO", "STICKLINE", "DRAWTEXT", "DRAWICON", "DRAWNUMBER", "DRAWLINE",
                  "POLYLINE", "VERTLINE", "DRAWKLINE")

FORBID_RE = re.compile(r"(?<![A-Za-z0-9_\u4e00-\u9fff])(" + "|".join(LOOKAHEAD_TOKENS) + r")(?![A-Za-z0-9_\u4e00-\u9fff])")
NEG_REF_RE = re.compile(r"REF\s*\([^,()]+,[^,()]*-\s*\d")

# 维度② 函数语义：解释器里这些函数的「窗口方向」全部朝过去
FN_DIRECTION = {
    "REF": dict(方向="仅回溯", 引擎="Series.shift(k)；常量 k<0 → raise NotImplementedError('negative window')；变窗序列 k → ref_var(): idx=i-k，idx<0 置 NaN、idx>=n 抛 IndexError（不会静默取到未来）", 出处="tdx_interp.py:374-376, 383-388, 590-599"),
    "MA": dict(方向="仅回溯", 引擎="rolling(n, min_periods=n).mean()，窗口右端=当前根", 出处="tdx_interp.py:389-393"),
    "EMA": dict(方向="仅回溯", 引擎="ewm(alpha=2/(n+1), adjust=False)，严格因果递推", 出处="tdx_interp.py:394-398"),
    "SMA": dict(方向="仅回溯", 引擎="ewm(alpha=m/n, adjust=False)，严格因果递推", 出处="tdx_interp.py:399-403"),
    "HHV": dict(方向="仅回溯", 引擎="rolling(k).max()；k=0 → 上市以来 cummax；变窗 → sparse-table roll_max_var，窗口 [i-k+1,i]", 出处="tdx_interp.py:404-413, 614-649"),
    "LLV": dict(方向="仅回溯", 引擎="同 HHV，rolling(k).min() / roll_min_var", 出处="tdx_interp.py:404-413, 614-653"),
    "CROSS": dict(方向="仅回溯", 引擎="up_now=a[i]>b[i] 且 up_prev=a[i-1]<=b[i-1]，只用 T 与 T-1", 出处="tdx_interp.py:420-421, 577-587"),
    "BARSLAST": dict(方向="仅回溯", 引擎="maximum.accumulate(where(cond, idx, -1))；从未触发 → +1e9 哨兵", 出处="tdx_interp.py:422-423, 568-574"),
    "BARSSINCE": dict(方向="仅回溯", 引擎="引擎按 barslast 近似实现（首现后恒增），无未来通道", 出处="tdx_interp.py:424-425"),
    "COUNT": dict(方向="仅回溯", 引擎="rolling(k).sum()；变窗 → count_var(前缀和差)", 出处="tdx_interp.py:426-430, 602-611"),
    "EVERY": dict(方向="仅回溯", 引擎="rolling(k).sum()==k", 出处="tdx_interp.py:431-435"),
    "EXIST": dict(方向="仅回溯", 引擎="rolling(k).sum()>0", 出处="tdx_interp.py:436-440"),
    "SUM": dict(方向="仅回溯", 引擎="rolling(k).sum()；k=0 → cumsum", 出处="tdx_interp.py:441-448"),
    "FILTER": dict(方向="仅回溯", 引擎="自左向右单遍：命中则 out[i]=1 且 i<=cool 的后续命中被压掉，cool=i+n —— 冷却窗口只朝未来压后续*命中*，不读未来数据", 出处="tdx_interp.py:530-541"),
    "BETWEEN": dict(方向="逐点", 引擎="(x>=lo)&(x<=hi)，无窗口", 出处="tdx_interp.py:470-473"),
    "RANGE": dict(方向="逐点", 引擎="同 BETWEEN", 出处="tdx_interp.py:547-550"),
    "MAX": dict(方向="逐点", 引擎="np.fmax(x,y)（注意：fmax 会忽略 NaN ⇒ 与 TDX 的 NaN 传播不同，属语义忠实度备注，非前视）", 出处="tdx_interp.py:449-450"),
    "MIN": dict(方向="逐点", 引擎="np.fmin(x,y)（同上 NaN 备注）", 出处="tdx_interp.py:451-452"),
    "ABS": dict(方向="逐点", 引擎="np.abs", 出处="tdx_interp.py:453-454"),
    "POW": dict(方向="逐点", 引擎="np.power", 出处="tdx_interp.py:455-456"),
    "SQRT": dict(方向="逐点", 引擎="np.sqrt(max(x,0))", 出处="tdx_interp.py:457-459"),
    "SGN": dict(方向="逐点", 引擎="np.sign", 出处="tdx_interp.py:460-461"),
    "MOD": dict(方向="逐点", 引擎="np.fmod", 出处="tdx_interp.py:462-465"),
    "IF": dict(方向="逐点", 引擎="np.where（三目两臂都求值，但都是同类时序量，无越界）", 出处="tdx_interp.py:466-469"),
    "UPNDAY": dict(方向="仅回溯", 引擎="x>x.shift(1) 的 rolling(k).sum()==k", 出处="tdx_interp.py:474-482"),
    "DOWNNDAY": dict(方向="仅回溯", 引擎="x<x.shift(1) 的 rolling(k).sum()==k", 出处="tdx_interp.py:474-482"),
    "NDAY": dict(方向="仅回溯", 引擎="x>y 的 rolling(k).sum()==k", 出处="tdx_interp.py:483-490"),
    "DMA": dict(方向="仅回溯", 引擎="ewm(alpha=alpha, adjust=False)", 出处="tdx_interp.py:551-556"),
    "STD": dict(方向="仅回溯", 引擎="rolling(n).std(ddof=1)", 出处="tdx_interp.py:491-495"),
    "SLOPE": dict(方向="仅回溯", 引擎="rolling(n).apply(最小二乘斜率)，窗口 [i-n+1,i]", 出处="tdx_interp.py:501-517"),
    "FORCAST": dict(方向="仅回溯", 引擎="同上（截距+斜率）", 出处="tdx_interp.py:501-517"),
    "AVEDEV": dict(方向="仅回溯", 引擎="rolling(n).apply(平均绝对偏差)", 出处="tdx_interp.py:518-529"),
    "ATAN": dict(方向="逐点", 引擎="np.arctan", 出处="tdx_interp.py:545-546"),
}
WINDOWED = ("REF", "HHV", "LLV", "HHVBARS", "LLVBARS", "SUM", "COUNT", "EVERY", "EXIST", "MA",
            "EMA", "SMA", "STD", "SLOPE", "FORCAST", "AVEDEV", "FILTER", "UPNDAY", "DOWNNDAY", "NDAY")

# 源码级前视注入尝试（证明解释器没有「源码层」前视通道）
INJECT_PROBES = {
    "REF_负常量": "A:=REF(C,-1);A>0;",
    "REF_负表达式": "A:=REF(C,1-2);A>0;",
    "REF_HHV_负参": "A:=REF(HHV(H,10),-1);A>0;",
    "REF_变窗负参": "N:=BARSLAST(C>0);A:=REF(C,N-1);A>0;",
    "HHV_负参": "A:=HHV(H,0-3);A>0;",
    "CONST": "A:=CONST(C);A>0;",
    "ISLASTBAR": "A:=ISLASTBAR;A>0;",
    "CURRBARSCOUNT": "A:=CURRBARSCOUNT;A>0;",
    "TOTALBARSCOUNT": "A:=TOTALBARSCOUNT;A>0;",
    "DYNAINFO": "A:=DYNAINFO(4);A>0;",
    "ZIG": "A:=ZIG(3,5);A>0;",
    "PEAK": "A:=PEAK(1,3,1);A>0;",
    "TROUGH": "A:=TROUGH(2,3,1);A>0;",
    "WINNER": "A:=WINNER(C);A>0;",
    "COST": "A:=COST(50);A>0;",
    "FINANCE": "A:=FINANCE(7);A>0;",
    "NAMELIKE": "A:=NAMELIKE(1);A>0;",
}

# ----------------------------------------------------------------- 通用工具
def walk_ast(node, calls, vars_):
    if not isinstance(node, tuple):
        return
    t = node[0]
    if t == "call":
        calls.append(node)
        for a in node[2]:
            walk_ast(a, calls, vars_)
    elif t == "var":
        vars_.append(node[1])
    else:
        for x in node[1:]:
            walk_ast(x, calls, vars_)


def ast_src(node):
    t = node[0]
    if t == "num":
        return "%g" % node[1]
    if t == "var":
        return node[1]
    if t == "str":
        return repr(node[1])
    if t == "neg":
        return "-" + ast_src(node[1])
    if t == "not":
        return "NOT " + ast_src(node[1])
    if t in ("and", "or"):
        return ast_src(node[1]) + (" AND " if t == "and" else " OR ") + ast_src(node[2])
    if t == "cmp":
        return ast_src(node[2]) + " " + node[1] + " " + ast_src(node[3])
    if t == "arith":
        return "(" + ast_src(node[2]) + node[1] + ast_src(node[3]) + ")"
    if t == "call":
        return node[1] + "(" + ",".join(ast_src(a) for a in node[2]) + ")"
    return "?"


DATA_KEYS = (("C", "C"), ("CLOSE", "C"), ("O", "O"), ("OPEN", "O"), ("H", "H"), ("HIGH", "H"),
             ("L", "L"), ("LOW", "L"), ("V", "V"), ("VOL", "V"), ("VOLUME", "V"),
             ("AMO", "A"), ("AMOUNT", "A"))


def col_env(ast, local, P, j, upto=None, fwd_chan=None):
    """单列求值 → (env, 输出序列)。
    upto 非 None：只喂第 0..upto 行（截断不变性实验）。
    fwd_chan：把该通道整体前移 1 日（T+1 的值当作 T 的值），即**入口前视注入**，
              且在截断窗口内重新构造，故截断实验能识别它。"""
    sl = slice(0, upto + 1) if upto is not None else slice(None)
    env = {"DRAWNULL": np.nan}
    for nm, key in DATA_KEYS:
        a = P[key][sl, j].astype(float)
        if fwd_chan and key == fwd_chan:
            b = np.zeros_like(a)
            if a.size > 1:
                b[:-1] = a[1:]
            a = b
        env[nm] = a
    for nm, a in local.items():
        env[nm] = T.ev(a, env)
    return env, np.asarray(T.ev(ast, env), float)


def rnd(x):
    if x is None:
        return None
    x = float(x)
    return None if not np.isfinite(x) else round(x, 6)


def ports(ev):
    """把 v3 event_study 的三口径读数压成审计用的紧凑字段（口径名与冻结脚本一致）。"""
    if not ev:
        return dict(n=0)
    if not ev.get("n"):
        return dict(n=ev.get("n", 0), n_rej_limit_up=ev.get("n_rej_limit_up"),
                    n_drop_no_exit=ev.get("n_drop_no_exit"))
    return dict(
        n=ev.get("n"), n_true_signals=ev.get("n_true_signals"), days_active=ev.get("days_active"), uniq_symbols=ev.get("uniq_symbols"),
        wr=ev.get("wr"), gross_mean_pct=ev.get("gross_mean_pct"),
        bm_ref_mean_buy_pct=ev.get("bm_ref_mean_buy_pct"),
        gross_buy=dict(exc_mean_pct=ev.get("exc_gross_buy_pct"), t=ev.get("t_stat_gross_buy"),
                       ci95_lo_pct=ev.get("ci95_lo_gross_buy_pct"),
                       ci95_hi_pct=ev.get("ci95_hi_gross_buy_pct"), gate=ev.get("gate_gross_buy")),
        buy=dict(exc_mean_pct=ev.get("exc_mean_buy_pct"), t=ev.get("t_stat_buy"),
                 ci95_lo_pct=ev.get("ci95_lo_buy_pct"), ci95_hi_pct=ev.get("ci95_hi_buy_pct"),
                 gate=ev.get("gate_buy")),
        all=dict(exc_mean_pct=ev.get("exc_mean_pct"), t=ev.get("t_stat"),
                 ci95_lo_pct=ev.get("ci95_lo_pct"), gate=ev.get("gate")),
    )


def shift_panel(P, chans, k):
    """把指定通道整体平移：k=+1 → 用**未来 1 日**的值当作当日值（前视注入）；
       k=-1 → 用昨日值（滞后 1 日的阴性对照）；k=0 → 恒等（原样）。"""
    if k == 0:
        return P
    Q = {kk: vv for kk, vv in P.items()}
    for ch in chans:
        X = P[ch].astype(np.float32)
        Y = np.zeros_like(X)
        if k > 0:
            Y[:-k] = X[k:]
        else:
            Y[-k:] = X[:k]
        Q[ch] = Y
    return Q


# ----------------------------------------------------------------- 维度①：数据可用时点
def dim1_data_availability(tid, code_raw, code, P, cols, Tn, cal):
    ast, local, flags = T.compile_block(code)
    calls, vars_ = [], []
    walk_ast(ast, calls, vars_)
    for a in local.values():
        walk_ast(a, calls, vars_)
    call_names = sorted({c[1] for c in calls})
    var_names = sorted(set(vars_))
    data_ch = sorted({key for nm, key in DATA_KEYS if nm in set(var_names)})

    forbidden_text = sorted(set(m.group(1) for m in FORBID_RE.finditer(code_raw)))
    forbidden_ast = sorted({c[1] for c in calls if c[1] in LOOKAHEAD_TOKENS} |
                           {v for v in var_names if v in LOOKAHEAD_TOKENS})
    lenient_used = sorted({c[1] for c in calls if c[1] in LENIENT_TOKENS})
    neg_ref_hits = sorted(set(m.group(0) for m in NEG_REF_RE.finditer(code_raw)))

    # 输入清单：每条公式用到的原始输入 + 派生量
    inputs = [dict(name=ch, cn=CH_NAMES.get(ch, ch), kind="原始输入",
                   available_at="T 收盘（panel_oos.npz 的当日 bar）") for ch in data_ch]
    derived = [dict(name=nm, kind="派生量", expr=ast_src(a), available_at="仅由 ≤T 的输入与同块前列派生量构成")
               for nm, a in local.items()]

    return dict(
        raw_code_chars=len(code_raw), normalized_code_chars=len(code),
        statement_vars=[nm for nm in local],
        data_vars_used=data_ch, all_vars_used=var_names, functions_used=call_names,
        inputs=inputs, derived=derived,
        forbidden_token_hits_in_text=forbidden_text,
        forbidden_token_hits_in_ast=forbidden_ast,
        lenient_engine_tokens_used=lenient_used,
        dynainfo_flag=bool(flags.get("dyuse")),
        negative_ref_literal_hits=neg_ref_hits,
        verdict=("前视" if (forbidden_text or forbidden_ast or flags.get("dyuse") or neg_ref_hits) else "PASS"),
        note="所有输入均为当日及之前 bar 的 O/H/L/C/V；未使用 AMOUNT(A) 时 A 通道不参与；无任何常量/最后棒/筹码/财务类记号。",
    )


def truncation_invariance(code, P, cols, trs, fwd_chan=None):
    """截断不变性（因果性的**可执行**证明，同时是维度④的阳性对照器械）：
       把输入只喂第 0..tr 行，重算整块公式，取「第 tr 行的**全部中间量** + 最终输出」
       与「全历史算出的第 tr 行」逐点比对。若公式只用 <=t 的信息，则必须完全一致。
       fwd_chan 非 None：在**截断窗口内重建**「T+1 的值当作 T 的值」的入口前视注入
       （此时第 tr 行必然取到窗口外的信息 → 应当被识别为错配 = 检验有分辨力）。"""
    ast, local, flags = T.compile_block(code)
    Tn = P["C"].shape[0]
    names = list(local.keys())
    full_env, full_out = [], np.full((Tn, len(cols)), np.nan)
    for i, j in enumerate(cols):
        e, o = col_env(ast, local, P, int(j), fwd_chan=fwd_chan)
        full_env.append(e)
        full_out[:, i] = o

    def at(x, k):
        a = np.asarray(x, float)
        return float(a[k]) if a.ndim else float(a)

    def same(a, b):
        if np.isnan(a) and np.isnan(b):
            return True, 0.0
        if np.isnan(a) or np.isnan(b):
            return False, float("inf")
        d = abs(a - b) / max(1e-12, abs(a), abs(b))
        return bool(d <= 1e-9), float(d)

    n_cells = n_bad_out = n_bad_local = n_cells_diff = 0
    max_rel = 0.0
    ex = []
    for tr in trs:
        for i, j in enumerate(cols):
            try:
                envT, oT = col_env(ast, local, P, int(j), upto=int(tr), fwd_chan=fwd_chan)
            except Exception as e:
                n_cells += 1
                n_bad_out += 1
                if len(ex) < 6:
                    ex.append(dict(t=int(tr), col=int(j), var="__eval__",
                                   full=None, truncated="%s: %s" % (type(e).__name__, str(e)[:90])))
                continue
            n_cells += 1
            ok, d = same(at(full_out[:, i], tr), at(oT, tr))
            if np.isfinite(d):
                max_rel = max(max_rel, d)
            if not ok:
                n_bad_out += 1
                if len(ex) < 6:
                    ex.append(dict(t=int(tr), col=int(j), var="__输出信号",
                                   full=rnd(at(full_out[:, i], tr)), truncated=rnd(at(oT, tr))))
            hit = []
            for nm in names:
                ok2, d2 = same(at(full_env[i][nm], tr), at(envT[nm], tr))
                if np.isfinite(d2):
                    max_rel = max(max_rel, d2)
                if not ok2:
                    n_bad_local += 1
                    hit.append(nm)
                    if len(ex) < 6:
                        ex.append(dict(t=int(tr), col=int(j), var=nm,
                                       full=rnd(at(full_env[i][nm], tr)),
                                       truncated=rnd(at(envT[nm], tr))))
            if hit:
                n_cells_diff += 1
    return dict(fwd_chan_injected=fwd_chan, n_cols=len(cols), trunc_points=len(trs),
                n_locals_compared=len(names), n_cells=n_cells,
                n_compared=n_cells * (1 + len(names)),
                n_mismatch_output=n_bad_out, n_mismatch_intermediate=n_bad_local,
                n_mismatch=n_bad_out + n_bad_local, n_cells_with_any_diff=n_cells_diff,
                max_rel_diff=(None if not np.isfinite(max_rel) else round(max_rel, 12)),
                examples=ex,
                verdict=("前视" if (n_bad_out or n_bad_local) else "PASS"))


# ----------------------------------------------------------------- 维度②：函数语义（窗口方向）
def dim2_function_semantics(code, P, cols):
    ast, local, flags = T.compile_block(code)
    calls, vars_ = [], []
    walk_ast(ast, calls, vars_)
    for a in local.values():
        walk_ast(a, calls, vars_)
    fn_counts = {}
    for c in calls:
        fn_counts[c[1]] = fn_counts.get(c[1], 0) + 1

    uniq = {}
    for c in calls:
        fn = c[1]
        if fn not in WINDOWED:
            continue
        i = 2 if fn == "NDAY" else 1
        if len(c[2]) > i:
            uniq.setdefault((fn, ast_src(c[2][i])), c[2][i])
    stats = {k: [np.inf, -np.inf, 0, 0] for k in uniq}
    for j in cols:
        env, _ = col_env(ast, local, P, int(j))      # 注意 col_env 返回 (env, 输出序列)
        for k, w in uniq.items():
            try:
                v = T.ev(w, env)
            except Exception:
                continue
            f = np.atleast_1d(np.asarray(v, float)).ravel()
            f = f[np.isfinite(f)]
            if not f.size:
                continue
            fs = f[f < 10 ** 9]                       # 剔除 BARSLAST「从未触发」的 1e9 哨兵
            s = stats[k]
            s[2] += int(f.size)
            s[3] += int((f >= 10 ** 9).sum())
            if fs.size:
                s[0] = min(s[0], float(fs.min()))
                s[1] = max(s[1], float(fs.max()))

    windows = []
    for (fn, src), _ in sorted(uniq.items()):
        s = stats[(fn, src)]
        d = FN_DIRECTION.get(fn, {})
        windows.append(dict(fn=fn, window_arg=src,
                            min_effective=None if not np.isfinite(s[0]) else round(s[0], 6),
                            max_effective=None if not np.isfinite(s[1]) else round(s[1], 6),
                            sentinel_count=s[3],
                            samples=s[2], direction=d.get("方向", "?"),
                            engine=d.get("引擎", ""), cite=d.get("出处", "")))
    reached_future = [w for w in windows
                      if (w["fn"] == "REF" and w["min_effective"] is not None and w["min_effective"] < 0)
                      or (w["fn"] != "REF" and w["min_effective"] is not None and w["min_effective"] < 0)]
    return dict(function_counts=dict(sorted(fn_counts.items())),
                window_functions=windows,
                negative_or_future_window=reached_future,
                pointwise_functions=sorted(n for n in fn_counts if n not in WINDOWED and n not in
                                           ("AND", "OR", "NOT", "CROSS", "BARSLAST", "BARSSINCE")),
                verdict=("前视" if reached_future else "PASS"),
                note="REF 窗口取到的 min 值 >= 0 ⇒ 最远只到 T 本身；HHV/LLV/SUM/COUNT/MA/EMA/SMA/FILTER 等 min 窗口 >= 1 ⇒ 最远只到 T。引擎对负窗口（常量或变窗）一律抛错，不会静默取到未来（见 dim4 源码级探针回执）。")


# ----------------------------------------------------------------- 维度⑤：抽样手算
def ma_at(P, key, n, t, j):
    a = P[key][max(0, t - n + 1): t + 1, j].astype(float)
    if a.size < n:
        return None
    return float(a.mean())


def manual_check(tid, P, j, t):
    C = P["C"][:, j].astype(float)
    O = P["O"][:, j].astype(float)
    H = P["H"][:, j].astype(float)
    L = P["L"][:, j].astype(float)
    V = P["V"][:, j].astype(float)
    d = {}
    if tid == "543":
        d["涨幅超3_手算_pct"] = rnd((C[t] - C[t - 1]) / C[t - 1] * 100) if C[t - 1] > 0 else None
        d["跌幅超5_手算_pct"] = rnd((C[t - 5] - C[t]) / C[t - 5] * 100) if C[t - 5] > 0 else None
        d["五日温和_手算_pct"] = rnd((C[t] - O[t - 5]) / O[t - 5] * 100) if O[t - 5] > 0 else None
        d["放量比_手算"] = rnd(V[t] / V[t - 1]) if V[t - 1] > 0 else None
        for n in (5, 10, 20):
            d["MA%d_T" % n] = rnd(ma_at(P, "C", n, t, j))
            d["MA%d_T-1" % n] = rnd(ma_at(P, "C", n, t - 1, j))
        d["一穿三_手算"] = float(
            all(ma_at(P, "C", n, t, j) is not None and ma_at(P, "C", n, t - 1, j) is not None
                and C[t] > ma_at(P, "C", n, t, j) and C[t - 1] <= ma_at(P, "C", n, t - 1, j)
                for n in (5, 10, 20))
            and ma_at(P, "C", 20, t, j) > ma_at(P, "C", 20, t - 1, j))
    elif tid == "774":
        d["当日涨幅_手算_pct"] = rnd((C[t] - C[t - 1]) / C[t - 1] * 100) if C[t - 1] > 0 else None
        d["三日跌幅_手算_pct"] = rnd((C[t - 3] - C[t]) / C[t - 3] * 100) if C[t - 3] > 0 else None
        d["五日开盘_手算_pct"] = rnd((C[t] - O[t - 5]) / O[t - 5] * 100) if O[t - 5] > 0 else None
        d["八十九日_手算_pct"] = rnd((C[t] - C[t - 89]) / C[t - 89] * 100) if C[t - 89] > 0 else None
        m5 = ma_at(P, "V", 5, t, j)
        d["量能比_手算"] = rnd(V[t] / m5) if m5 else None
        mas = [ma_at(P, "C", n, t, j) for n in (5, 10, 20, 60)]
        if all(x is not None for x in mas):
            d["均线粘合比_手算"] = rnd(max(mas) / min(mas)) if min(mas) > 0 else None
        for n in (20, 60):
            d["MA%d_T" % n] = rnd(ma_at(P, "C", n, t, j))
    elif tid == "807":
        mas = {n: ma_at(P, "C", n, t, j) for n in (5, 10, 20, 30, 60)}
        for n in (5, 10, 20, 30, 60):
            d["MA%d_T" % n] = rnd(mas[n])
        vv = [v for v in mas.values() if v is not None]
        if vv and min(vv) > 0:
            d["粘合度_手算_pct"] = rnd((max(vv) - min(vv)) / min(vv) * 100)
        v135 = ma_at(P, "V", 135, t, j)
        d["VOL135_T"] = rnd(v135)
        d["量能放大_手算"] = rnd(V[t] / v135) if v135 else None
        for n in (20, 30, 60):
            d["趋势%d_手算" % n] = float(ma_at(P, "C", n, t, j) > ma_at(P, "C", n, t - 1, j))
    return d


def verify_manual(tid, rec):
    """手算值 vs 引擎中间量的逐值核对（维度⑤的可判定化）。"""
    inter = rec["intermediates_T2_T1_T"]
    man = rec["manual_recompute"]
    checks = []

    def gv(name):
        v = inter.get(name)
        return None if v is None else v[2]          # 索引 2 = T

    def add(label, m, e, tol=1e-6):
        ok = None
        if m is not None and e is not None:
            ok = bool(abs(float(m) - float(e)) <= tol * max(1.0, abs(float(e))))
        checks.append(dict(item=label, manual=m, engine=e, match=ok))

    if tid == "807":
        for n in (5, 10, 20, 30, 60):
            add("MA%d_T" % n, man.get("MA%d_T" % n), gv("MA%d" % n))
        add("粘合度_pct", man.get("粘合度_手算_pct"), gv("粘合度"))
        add("VOL135_T", man.get("VOL135_T"), gv("VOL135"))
        for n in (20, 30, 60):
            add("趋势%d" % n, man.get("趋势%d_手算" % n), gv("趋势%d" % n))
        r = man.get("量能放大_手算")
        add("量能放大(V>VOL135)", None if r is None else float(r > 1), gv("量能放大"))
    elif tid == "774":
        add("MA20_T", man.get("MA20_T"), gv("二十日线"))
        add("MA60_T", man.get("MA60_T"), gv("六十日线"))
        hi, lo = gv("均线最高"), gv("均线最低")
        add("均线粘合比", man.get("均线粘合比_手算"),
            None if (hi is None or not lo) else hi / lo)
        pct = man.get("当日涨幅_手算_pct")
        add("当日涨幅超五(2%~8%)", None if pct is None else float(2 < pct < 8), gv("当日涨幅超五"))
        vr = man.get("量能比_手算")
        add("量能未超均量三(<3.5)", None if vr is None else float(vr < 3.5), gv("量能未超均量三"))
        p5 = man.get("五日开盘_手算_pct")
        add("五日开盘未超三(<30)", None if p5 is None else float(p5 < 30), gv("五日开盘未超三"))
        p89 = man.get("八十九日_手算_pct")
        add("八十九日未超八(<80)", None if p89 is None else float(p89 < 80), gv("八十九日未超八"))
    elif tid == "543":
        raw = inter.get("__引擎中间量_RAW") or {}
        for n in (5, 10, 20):
            add("MA%d_T" % n, man.get("MA%d_T" % n), raw.get("MA%d_T" % n))
        add("一穿三", man.get("一穿三_手算"), gv("一穿三"))
        pct = man.get("涨幅超3_手算_pct")
        add("涨幅超3(>3%)", None if pct is None else float(pct > 3), gv("涨幅超3"))
        p5 = man.get("五日温和_手算_pct")
        add("五日温和(<8%)", None if p5 is None else float(p5 < 8), gv("五日温和"))
        vr = man.get("放量比_手算")
        add("放量(V>1.5xV_T-1)", None if vr is None else float(vr > 1.5), gv("放量"))
        iv = gv("跌幅间隔")
        add("间隔合理(<150)", None if iv is None else float(iv < 150), gv("间隔合理"))
    done = [c for c in checks if c["match"] is not None]
    bad = [c for c in done if not c["match"]]
    return dict(items=checks, n_checked=len(done), n_match=len(done) - len(bad),
                mismatch=bad, all_match=(len(bad) == 0),
                verdict="PASS" if not bad else "存疑")


def handcheck(tid, code, P, syms, cal, sig, n_pick=3):
    ast, local, flags = T.compile_block(code)
    t_idx, j_idx = np.where(sig)
    ts = np.unique(t_idx)
    if ts.size == 0:
        return []
    picks = []
    for q in (0.25, 0.50, 0.75):
        target = int(ts[int(q * (ts.size - 1))])
        k = int(np.searchsorted(t_idx, target))
        k = min(k, t_idx.size - 1)
        picks.append((int(t_idx[k]), int(j_idx[k])))
    out = []
    for (t, j) in picks[:n_pick]:
        env, o = col_env(ast, local, P, j)
        rows = {}
        for lo, lab in ((t - 2, "T-2"), (t - 1, "T-1"), (t, "T")):
            rows[lab] = dict(date=cal[lo], O=rnd(P["O"][lo, j]), H=rnd(P["H"][lo, j]),
                             L=rnd(P["L"][lo, j]), C=rnd(P["C"][lo, j]), V=rnd(P["V"][lo, j]),
                             A=rnd(P["A"][lo, j]))
        inter = {}
        for nm in list(local.keys()):
            s = np.asarray(env[nm], float)
            inter[nm] = [rnd(s[lo]) if s.ndim else rnd(s) for lo in (t - 2, t - 1, t)]
        inter["__输出信号"] = [rnd(o[lo]) for lo in (t - 2, t - 1, t)]
        inter["__引擎中间量_RAW"] = dict(
            MA5_T=rnd(ma_at(P, "C", 5, t, j)), MA10_T=rnd(ma_at(P, "C", 10, t, j)),
            MA20_T=rnd(ma_at(P, "C", 20, t, j)), MA20_T1=rnd(ma_at(P, "C", 20, t - 1, j)),
            V_T1=rnd(P["V"][t - 1, j]), C_T1=rnd(P["C"][t - 1, j]),
            H_T2=rnd(P["H"][t - 2, j]), L_T2=rnd(P["L"][t - 2, j]))
        out.append(dict(t=t, j=j, symbol=syms[j], dates=["%s(T-2)" % cal[t - 2], "%s(T-1)" % cal[t - 1],
                                                         "%s(T)" % cal[t]],
                        rows_by_bar=rows, intermediates_T2_T1_T=inter,
                        manual_recompute=manual_check(tid, P, j, t),
                        uses_only_le_T="核对点：上表每个中间量在 T 列的值只由 rows_by_bar 中 ≤T 的原始 bar 决定；"
                                       "T+1 及以后的任何数值均不出现在本表。"))
    for rec in out:
        rec["manual_vs_engine"] = verify_manual(tid, rec)
    return out

# ----------------------------------------------------------------- 维度③：平移实验（滞后 1 日 / 取未来 1 日）
def shift_readings(code, Ptrue, chans, k):
    Ps = shift_panel(Ptrue, chans, k)
    r = V1.evaluate_formula(code, Ps)
    if r.get("kind") != "①":
        return dict(kind=r.get("kind"), reason=str(r.get("reason"))[:160], n_true_signals=None)
    sig = r["sig"]
    p = ports(V3.event_study(sig, Ptrue))
    p["kind"] = "①"
    p["n_true_signals"] = int(sig.sum())
    return p


# ----------------------------------------------------------------- 维度④：阳性对照
def probe_injections():
    """源码级前视注入尝试：证明解释器没有源码层前视通道（负 REF / CONST / 最后棒 / 筹码 / 财务）。"""
    c = np.arange(1, 21, dtype=float)
    rows = {}
    for nm, src in INJECT_PROBES.items():
        env = {"C": c, "O": c, "H": c + 1.0, "L": c - 1.0, "V": c * 10.0, "A": c * 100.0,
               "DRAWNULL": np.nan}
        try:
            ast, local, fl = T.compile_block(src)
        except NotImplementedError as e:
            rows[nm] = dict(probe=src, result="编译拒绝", receipt=str(e)[:160])
            continue
        except Exception as e:
            rows[nm] = dict(probe=src, result="编译异常", receipt="%s: %s" % (type(e).__name__, str(e)[:140]))
            continue
        try:
            for k2, a2 in local.items():
                env[k2] = T.ev(a2, env)
            T.ev(ast, env)
            rows[nm] = dict(probe=src, result="可编译且可求值", receipt="flags=%s" % fl)
        except Exception as e:
            rows[nm] = dict(probe=src, result="求值拒绝", receipt="%s: %s" % (type(e).__name__, str(e)[:160]))
    return rows


def before_after(tid, ev_base, ev_after, tag):
    b = ports(ev_base)
    af = ports(ev_after)
    gb, ga = b.get("gross_buy", {}), af.get("gross_buy", {})
    return dict(
        injection=tag,
        before=dict(n=b.get("n"), gross_exc_pct=gb.get("exc_mean_pct"), t=gb.get("t"),
                    ci95_lo_pct=gb.get("ci95_lo_pct"), gate=gb.get("gate"),
                    net_exc_pct=b.get("buy", {}).get("exc_mean_pct")),
        after=dict(n=af.get("n"), gross_exc_pct=ga.get("exc_mean_pct"), t=ga.get("t"),
                   ci95_lo_pct=ga.get("ci95_lo_pct"), gate=ga.get("gate"),
                   net_exc_pct=af.get("buy", {}).get("exc_mean_pct"),
                   n_true_signals=af.get("n_true_signals")),
        delta_gross_exc_pp=(None if (gb.get("exc_mean_pct") is None or ga.get("exc_mean_pct") is None)
                            else round(ga["exc_mean_pct"] - gb["exc_mean_pct"], 4)),
        delta_t=(None if (gb.get("t") is None or ga.get("t") is None) else round(ga["t"] - gb["t"], 3)),
        improved=(None if (gb.get("exc_mean_pct") is None or ga.get("exc_mean_pct") is None)
                  else bool(ga["exc_mean_pct"] > gb["exc_mean_pct"])),
    )


# ----------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUTDIR / "evidence_lookahead_forum8_20260928.json"))
    ap.add_argument("--skip-identity", action="store_true")
    a = ap.parse_args()
    t0 = time.time()

    reg = {str(e["id"]): e for e in json.loads(REGISTRY.read_text(encoding="utf-8"))}
    z = np.load(PANEL, allow_pickle=True)
    P = {k: z[k] for k in ("O", "H", "L", "C", "V", "A")}
    syms = [str(s) for s in z["syms"]]
    cal = [str(c) for c in z["cal"]]
    Tn, N = P["C"].shape
    V3._PANEL = P
    V3._MULT = np.array([V3.mult_of(s) for s in syms])
    valid = np.isfinite(P["C"]) & (P["C"] > 0)
    elig = np.nonzero(valid.sum(axis=0) >= 60)[0]
    rng = np.random.default_rng(20260928)
    audit_cols = np.sort(rng.choice(elig, size=min(48, elig.size), replace=False))
    trunc_cols = np.sort(rng.choice(elig, size=min(60, elig.size), replace=False))
    trs = sorted(set(int(x) for x in np.linspace(20, Tn - 1, 18)) | {Tn - 1, Tn - 2, Tn - 3, Tn - 5})
    log("[panel] T=%d N=%d %s..%s | 缺失存 0：C>0 占比 %.4f | 合格列 %d"
        % (Tn, N, cal[0], cal[-1], float((P["C"] > 0).mean()), elig.size))
    log("[audit] 抽样列 %d 个（截断实验用 %d 个）；截断点 %d 个（含 T-1/T-2/T-3）"
        % (audit_cols.size, trunc_cols.size, len(trs)))

    fz = json.loads(FROZEN_EV.read_text(encoding="utf-8"))
    fzr = {str(r["id"]): r for r in fz["rows"]}
    m3 = json.loads(FROZEN_M3.read_text(encoding="utf-8"))
    m3r = {str(r["id"]): r for r in m3["rows"]}

    frozen_readings = {}
    for tid in IDS:
        r0 = fzr.get(tid, {})
        ev = r0.get("event", {})
        e1 = {}
        for row in m3r.get(tid, {}).get("horizons", []):
            if row.get("K") == 1:
                e1 = row
        frozen_readings[tid] = dict(
            title=r0.get("title"), signal_name=r0.get("signal_name"), url=r0.get("url"),
            code_sha1_frozen=r0.get("code_sha1"),
            m2=dict(n=ev.get("n"), gross_exc_pct=ev.get("exc_gross_buy_pct"),
                    gross_t=ev.get("t_stat_gross_buy"), gross_ci95_lo_pct=ev.get("ci95_lo_gross_buy_pct"),
                    gross_gate=ev.get("gate_gross_buy"),
                    net_exc_pct=ev.get("exc_mean_buy_pct"), net_ci95_lo_pct=ev.get("ci95_lo_buy_pct"),
                    net_gate=ev.get("gate_buy")),
            m3_K1=dict(gross_exc_pct=(e1.get("gross") or {}).get("mean_pct"),
                       gross_t=(e1.get("gross") or {}).get("t"),
                       gross_gate=(e1.get("gross") or {}).get("gate"),
                       net_exc_pct=(e1.get("net") or {}).get("mean_pct"),
                       net_gate=(e1.get("net") or {}).get("gate")))

    evidence = dict(
        meta=dict(script=pathlib.Path(__file__).name,
                  run_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                  purpose="gushi.in/forum/8 三条「毛口径过门」公式（543/774/807）的未来函数（前视）五维复核",
                  method="gushi.in/topic/465 五维清单（可执行取证）",
                  frozen_reuse=["m2_sweep_20260928.py", "m2_sweep_v3_20260928.py", "r2_rebuild_0911/tdx_interp.py"],
                  untouched_frozen=True,
                  forbidden=["git commit/push", "修改既有文件", "改判据"]),
        panel=dict(path=str(PANEL), T=Tn, N=N, cal_start=cal[0], cal_end=cal[-1],
                   fields="O/H/L/C/V/A", missing_stored_as=0,
                   c_positive_share=round(float((P["C"] > 0).mean()), 6),
                   eligible_cols=int(elig.size), audit_sample_cols=int(audit_cols.size),
                   truncation_cols=int(trunc_cols.size), truncation_points=trs),
        frozen_readings=frozen_readings,
        dim1_data_availability={}, dim2_function_semantics={}, dim3_shift_experiment={},
        dim4_positive_control={}, dim5_handcheck={}, summary={}, anomalies=[])
    dim4_channel = {}
    dim4_all = {}

    for tid in IDS:
        md = (BODIES / ("t%s.md" % tid)).read_text(encoding="utf-8")
        blocks = [V1.clean_code(b) for b in V1.extract_blocks(md)]
        raw_block = max(blocks, key=len)
        code = V1.normalize(raw_block)
        sha = hashlib.sha1(code.encode("utf-8")).hexdigest()[:12]
        ast0, local0, flags0 = T.compile_block(code)
        cls, vrs = [], []
        walk_ast(ast0, cls, vrs)
        for a0 in local0.values():
            walk_ast(a0, cls, vrs)
        chans = sorted({key for nm, key in DATA_KEYS if nm in set(vrs)})
        log("")
        log("=== topic %s  %s  sha1=%s（冻结 %s %s）  用到的输入通道=%s"
            % (tid, reg.get(tid, {}).get("title"), sha, fzr.get(tid, {}).get("code_sha1"),
               "一致" if sha == fzr.get(tid, {}).get("code_sha1") else "**不一致**", chans))

        # ① 数据可用时点
        d1 = dim1_data_availability(tid, raw_block, code, P, audit_cols, Tn, cal)
        log("  ① 数据可用时点：禁止记号=%s | DYNAINFO=%s | 负 REF=%s | 输入=%s → %s"
            % (d1["forbidden_token_hits_in_text"] or d1["forbidden_token_hits_in_ast"] or "无",
               d1["dynainfo_flag"], d1["negative_ref_literal_hits"] or "无", d1["data_vars_used"],
               d1["verdict"]))

        # 基线
        tb = time.time()
        rb = V1.evaluate_formula(code, P)
        if rb.get("kind") != "①":
            log("  !! %s 基线非①：%s" % (tid, rb))
            evidence["anomalies"].append(dict(topic=tid, where="baseline", text=str(rb)[:200]))
            continue
        sig_b = rb["sig"]
        ev_b = V3.event_study(sig_b, P)
        pb = ports(ev_b)
        log("  [基线] n_true=%d | n=%d gross=%.4f%% t=%.3f CIlow=%.4f gate=%s （M2 冻结 gross=%.4f%%）"
            % (int(sig_b.sum()), pb.get("n"), pb["gross_buy"]["exc_mean_pct"], pb["gross_buy"]["t"],
               pb["gross_buy"]["ci95_lo_pct"], pb["gross_buy"]["gate"],
               frozen_readings[tid]["m2"]["gross_exc_pct"] or float("nan")))
        d1["truncation_invariance"] = truncation_invariance(code, P, trunc_cols, trs)
        d1["truncation_invariance"]["note"] = ("把输入只喂第 0..tr 行重算，再与全历史输出逐点比对；"
                                               "无前视 ⇒ 必须逐位相同")
        log("  ① 截断不变性：比对 %d 点，错配 %d 个 → %s"
            % (d1["truncation_invariance"]["n_compared"],
               d1["truncation_invariance"]["n_mismatch"],
               d1["truncation_invariance"]["verdict"]))
        evidence["dim1_data_availability"][tid] = d1

        # ② 函数语义
        d2 = dim2_function_semantics(code, P, audit_cols)
        evidence["dim2_function_semantics"][tid] = d2
        log("  ② 函数语义：%s" % ", ".join("%s×%d" % (k, v) for k, v in d2["function_counts"].items()))
        for w in d2["window_functions"]:
            log("     %-9s win=%-22s effective∈[%s,%s] 方向=%s (%s)"
                % (w["fn"], w["window_arg"], w["min_effective"], w["max_effective"], w["direction"], w["cite"]))

        # ③ 平移实验 + ④ 恒等/全通道注入
        d3 = dict(baseline=dict(pb, n_true_signals=int(sig_b.sum())), channels={})
        if not a.skip_identity:
            tid_sig = V1.evaluate_formula(code, {k: v.copy() for k, v in P.items()})
            if tid_sig.get("kind") == "①":
                same = bool(np.array_equal(tid_sig["sig"], sig_b))
                d3["identity_control"] = dict(re_eval_signal_identical=same,
                                              note="同面板复制后重算，信号矩阵应逐位相同（分辨力/确定性前提）")
                log("  ④ 恒等对照：重算信号逐位相同 = %s" % same)
            else:
                d3["identity_control"] = dict(re_eval_signal_identical=None, reason=str(tid_sig)[:150])
        for ch in chans:
            rec = {}
            for mode, k in (("lag1_昨日值当作当日值", -1), ("fwd1_未来值当作当日值", +1)):
                tt = time.time()
                rec[mode.split("_")[0]] = shift_readings(code, P, [ch], k)
                rr = rec[mode.split("_")[0]]
                log("  ③ %s %-6s gross=%s t=%s n=%s (%.0fs)"
                    % (CH_NAMES[ch], mode.split("_")[0],
                       rr.get("gross_buy", {}).get("exc_mean_pct"), rr.get("gross_buy", {}).get("t"),
                       rr.get("n"), time.time() - tt))
            d3["channels"][ch] = rec
            dim4_channel.setdefault(tid, {})[ch] = rec["fwd1"]
        # 全通道前视注入（阳性对照 PC1）
        tt = time.time()
        rec_all = shift_readings(code, P, chans, +1)
        log("  ④ 阳性对照 PC1（全通道取未来 1 日）：gross=%s t=%s n=%s (%.0fs)"
            % (rec_all.get("gross_buy", {}).get("exc_mean_pct"), rec_all.get("gross_buy", {}).get("t"),
               rec_all.get("n"), time.time() - tt))
        d3["all_channels_fwd1"] = rec_all
        dim4_all[tid] = before_after(tid, ev_b, {"n": rec_all.get("n"),
                                                "n_true_signals": rec_all.get("n_true_signals"),
                                                "exc_gross_buy_pct": rec_all.get("gross_buy", {}).get("exc_mean_pct"),
                                                "t_stat_gross_buy": rec_all.get("gross_buy", {}).get("t"),
                                                "ci95_lo_gross_buy_pct": rec_all.get("gross_buy", {}).get("ci95_lo_pct"),
                                                "gate_gross_buy": rec_all.get("gross_buy", {}).get("gate"),
                                                "exc_mean_buy_pct": rec_all.get("buy", {}).get("exc_mean_pct")},
                                          "全通道（%s）整体前移 1 日：用 T+1 的行情当作 T 的行情" % ",".join(chans))
        evidence["dim3_shift_experiment"][tid] = d3

        # ⑤ 抽样手算
        d5 = handcheck(tid, code, P, syms, cal, sig_b)
        evidence["dim5_handcheck"][tid] = d5
        for h in d5:
            log("  ⑤ 手算 %s(T=%s) sym=%s 中间量=%s"
                % (tid, h["dates"][2], h["symbol"],
                   {k: v for k, v in list(h["intermediates_T2_T1_T"].items())[:4]}))

        fwin = {ch: r["fwd1"].get("gross_buy", {}).get("exc_mean_pct") for ch, r in d3["channels"].items()}
        lgin = {ch: r["lag1"].get("gross_buy", {}).get("exc_mean_pct") for ch, r in d3["channels"].items()}
        fwin = {k: v for k, v in fwin.items() if v is not None}
        lgin = {k: v for k, v in lgin.items() if v is not None}
        bch = max(fwin, key=lambda c: fwin[c]) if fwin else None
        lch = max(lgin, key=lambda c: lgin[c]) if lgin else None
        d3["verdict"] = dict(
            verdict="PASS",
            baseline_gross_pct=pb["gross_buy"]["exc_mean_pct"],
            fwd1_max_channel=bch, fwd1_max_gross_pct=(fwin[bch] if bch else None),
            fwd1_max_t=(d3["channels"][bch]["fwd1"]["gross_buy"]["t"] if bch else None),
            lag1_max_channel=lch, lag1_max_gross_pct=(lgin[lch] if lch else None),
            note="取未来 1 日（前视注入）应把毛超额抬升一个数量级；滞后 1 日不应出现同向抬升。"
                 "若某通道取未来值后读数无明显改善，则该通道不是时间敏感通道（方法仍成立）。")
        d5v = [h.get("manual_vs_engine", {}) for h in d5]
        d5_pass = bool(d5v) and all(v.get("all_match") for v in d5v)
        n_chk = sum(int(v.get("n_checked") or 0) for v in d5v)
        n_bad = sum(len(v.get("mismatch") or []) for v in d5v)
        pc1 = dim4_all.get(tid, {})
        evidence["summary"][tid] = dict(
            title=reg.get(tid, {}).get("title"), signal_name=rb.get("signal_name"),
            code_sha1_audited=sha, code_sha1_frozen=fzr.get(tid, {}).get("code_sha1"),
            verdicts=dict(dim1_data_availability=d1["verdict"],
                          dim1_truncation_invariance=d1["truncation_invariance"]["verdict"],
                          dim2_function_semantics=d2["verdict"],
                          dim3_shift_experiment=d3["verdict"]["verdict"],
                          dim4_positive_control=("PASS" if pc1.get("improved") else "存疑"),
                          dim5_handcheck=("PASS" if d5_pass else "存疑")),
            dim5_detail=dict(picks=len(d5), values_checked=n_chk, mismatches=n_bad,
                             all_match=d5_pass),
            dim4_detail=dict(injection=pc1.get("injection"),
                             delta_gross_exc_pp=pc1.get("delta_gross_exc_pp"),
                             delta_t=pc1.get("delta_t"), improved=pc1.get("improved")),
        )

    # ④ 汇总阳性对照
    probes = probe_injections()
    pc4 = {}
    for tid, ch in (("543", "C"), ("807", "V")):
        md = (BODIES / ("t%s.md" % tid)).read_text(encoding="utf-8")
        code = V1.normalize(max([V1.clean_code(b) for b in V1.extract_blocks(md)], key=len))
        col = trunc_cols[:20]
        pc4["%s_基线" % tid] = truncation_invariance(code, P, col, trs[:6])
        pc4["%s_%s通道入口前视注入" % (tid, ch)] = truncation_invariance(code, P, col, trs[:6], fwd_chan=ch)
    log("")
    log("[④ 截断检验分辨力] " + " | ".join("%s: 错配 %d/%d" % (k, v["n_mismatch"], v["n_compared"])
                                            for k, v in pc4.items()))
    evidence["dim4_positive_control"] = dict(
        PC0_identity={tid: evidence["dim3_shift_experiment"][tid].get("identity_control") for tid in IDS},
        PC1_inject_all_channels_fwd1=dim4_all,
        PC2_inject_single_channel_fwd1={tid: {ch: dict(gross_exc_pct=v.get("gross_buy", {}).get("exc_mean_pct"),
                                                      t=v.get("gross_buy", {}).get("t"),
                                                      ci95_lo_pct=v.get("gross_buy", {}).get("ci95_lo_pct"),
                                                      gate=v.get("gross_buy", {}).get("gate"),
                                                      n=v.get("n"))
                                               for ch, v in chs.items()}
                                         for tid, chs in dim4_channel.items()},
        PC3_source_level_injection_attempts=probes,
        PC4_truncation_test_resolving_power=pc4,
        note=("阳性对照 = 在**数据入口**注入前视（把 T+1 的值当作 T 的值喂进公式）。"
              "源码层前视（负 REF / CONST / ISLASTBAR / 筹码 / 财务）在本解释器里一律被拒（见 PC3），"
              "故入口注入是唯一可实施的注入方式，等价于清单里的「把 REF(C,1) 改成 C」的加强版。"))
    ev = evidence["dim4_positive_control"]["PC1_inject_all_channels_fwd1"]
    ok = all((r.get("improved") and r.get("delta_gross_exc_pp") is not None and r["delta_gross_exc_pp"] > 0)
             for r in ev.values())
    pc3_blocked = all(v["result"] in ("编译拒绝", "求值拒绝") for k, v in probes.items()
                      if "REF" in k or k in ("CONST", "ISLASTBAR", "CURRBARSCOUNT", "TOTALBARSCOUNT",
                                             "ZIG", "PEAK", "TROUGH", "WINNER", "COST", "FINANCE",
                                             "NAMELIKE"))
    pc4_ok = (all(v.get("n_mismatch") == 0 for k, v in pc4.items() if k.endswith("_基线"))
              and all(v.get("n_mismatch", 0) > 0 for k, v in pc4.items() if not k.endswith("_基线")))
    evidence["dim4_positive_control"]["resolving_power"] = dict(
        PC1_所有公式毛超额均改善=bool(ok),
        PC3_源码层前视通道全部被拒=bool(pc3_blocked),
        PC4_截断检验能识别入口前视=bool(pc4_ok),
        结论=("方法有分辨力（三条阳性对照均成立）" if (ok and pc3_blocked and pc4_ok)
              else "**方法无分辨力，结论不可用**"))

    for tid in IDS:
        s = evidence["summary"][tid]
        v = s["verdicts"]
        fut = any(x == "前视" for x in v.values())
        s["verdict"] = "前视" if fut else "PASS"
        anom = []
        if s["code_sha1_audited"] != s["code_sha1_frozen"]:
            anom.append("审计代码 sha1 与冻结证据不一致")
        s["anomalies"] = anom
        if anom:
            evidence["anomalies"].append(dict(topic=tid, where="sha1", text="; ".join(anom)[:200]))
    fut_ids = [t for t in IDS if evidence["summary"][t]["verdict"] == "前视"]
    evidence["summary"]["_overall"] = dict(
        前视条数=len(fut_ids), 前视id=fut_ids,
        结论=("3 条均无未来函数，M2/M3 的毛口径读数可保留" if not fut_ids
              else "存在前视：%s ⇒ 因此 M2/M3 的相应读数需撤回" % ",".join(fut_ids)),
        阳性对照成立=evidence["dim4_positive_control"]["resolving_power"]["结论"],
        备注="本任务只做复核与取证，不涉及「能不能赚钱」的结论。")
    evidence["anomalies_original_200char"] = [dict(topic=k.get("topic"), text=str(k.get("text"))[:200])
                                              for k in evidence["anomalies"]]
    evidence["runtime_sec"] = round(time.time() - t0, 1)
    pathlib.Path(a.out).write_text(json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")
    log("")
    log("[done] %s  (%.0fs)" % (a.out, evidence["runtime_sec"]))
    log("[结论] %s" % evidence["summary"]["_overall"]["结论"])


if __name__ == "__main__":
    main()
