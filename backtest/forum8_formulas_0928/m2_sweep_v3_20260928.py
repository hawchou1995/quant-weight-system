# -*- coding: utf-8 -*-
"""m2_sweep_v3_20260928.py — v3 = v2 + N4（显示层归一化扩展：删含字符串字面量的语句 / 全局剥离 COLOR 记号）
原说明：m2_sweep_v2_20260928.py — v2：双基准（all=预注册 / buy=剔除开盘涨停的可成交票）+ 安慰剂器械检验
v1（m2_sweep_20260928.py）的预注册读数保持不变，v2 只修**测量仪器的可比性**，两者读数并报。
原说明：m2_sweep_20260928.py — gushi.in/forum/8 全量策略事件级粗筛（M2）

判据已冻结：backtest/PRE-REGISTRATION_20260928_forum8_formula_sweep.md
  · 分类四分（①真回测 ②画线只登记 ③跳过 ④无法编译）
  · 面板 = panel_oos.npz（O/H/L/C/V/A；含 253 只退市）
  · 入场 T+1 开盘（开盘涨停剔除）· 出场 T+2 收盘（无效顺延≤5日）· 往返成本 20bp
  · 粗筛门：n ≥ 100 且 **按信号日聚类 95% CI 下界 > 0**

**语法归一化（只动显示层，不动数学）**——预注册 §3 的实现细则：
  N1 去掉显示属性（逗号或空格分隔的 COLOR*/NODRAW/LINETHICK*/STICK*/DOTLINE 等）
  N2 `RGB(a,b,c)` → `0`
  N3 删掉**整条纯画线语句**（DRAWBAND/DRAWKLINE/POLYLINE/PARTLINE/DRAWLINE/DRAWRECT/VERTLINE…）
  以上三项都不改变任何数学表达式；未知**数学**函数（如 MEMA）一律不代改 → 归 ④。

用法:
  python m2_sweep_20260928.py --bodies DIR --registry FILE --out FILE [--jobs 6] [--single]
                              [--ids 543,530] [--limit N] [--probe]
"""
import argparse
import hashlib
import json
import multiprocessing as mp
import os
import pathlib
import re
import sys
import time

import numpy as np
from scipy import stats

R = pathlib.Path(__file__).resolve().parents[2]
SCRATCH = pathlib.Path(os.environ.get("PI_SCRATCH_DIR") or ".")
PANEL = SCRATCH / "x1cache" / "panel_oos.npz"
sys.path.insert(0, str(R / "backtest/r2_rebuild_0911"))
import tdx_interp as T  # noqa: E402

COST = 0.0020
MIN_N = 100
ALPHA = 0.05
TITLE_SKIP = ("第1课", "第2课", "第三课", "第3课", "第4课", "第5课", "第四课", "第五课",
              "入门", "基础", "教学", "分时", "教程", "扫盲")
OUT_NAME = re.compile(r"^([A-Za-z_\u4e00-\u9fff][A-Za-z_0-9\u4e00-\u9fff]*)\s*:(?!=)\s*(.+)$")
ATTR_RE = re.compile(r"(?:\s*,\s*|\s+)(?:COLOR[A-Z0-9]*|NODRAW|LINETHICK\d*|VOLSTICK|"
                     r"STICK\d*|DOTLINE|CIRCLEDOT|CROSSDOT|POINTDOT|LINEDOT|LINEDASH)\s*$")
RGB_RE = re.compile(r"RGB\s*\([^)]*\)", re.I)
DRAWONLY = ("DRAWBAND", "DRAWKLINE", "POLYLINE", "PARTLINE", "DRAWLINE", "DRAWRECT",
            "VERTLINE", "HORLINE", "DRAWZIG", "BAND")

_PANEL = None
_CODES = None
_MULT = None


def log(*a):
    print(*a, flush=True)


def mult_of(code):
    c = code.lower()
    return 1.20 if (c.startswith("sz30") or c.startswith("sh688")) else 1.10


# ------------------------------------------------------------------ 正文 → 代码块
def load_bodies(dirp, registry):
    reg = {str(e["id"]): e for e in registry}
    out = {}
    for tid in reg:
        p = dirp / ("t%s.md" % tid)
        if p.exists():
            out[tid] = p.read_text(encoding="utf-8")
    return reg, out


def extract_blocks(md):
    blocks = []
    for m in re.finditer(r"```[a-zA-Z]*\r?\n(.*?)```", md, re.S):
        b = m.group(1)
        if ":" in b:
            blocks.append(b)
    if not blocks:
        cur = []
        for ln in md.splitlines():
            s = ln.strip()
            is_code = (":=" in s) or bool(re.match(r"^[\u4e00-\u9fffA-Za-z_][\w\u4e00-\u9fff]*\s*:", s))
            if is_code:
                cur.append(s)
            else:
                if len(cur) >= 3:
                    blocks.append("\n".join(cur))
                cur = []
        if len(cur) >= 3:
            blocks.append("\n".join(cur))
    return blocks


def clean_code(code):
    code = code.replace("复制", "").replace("\u3000", " ")
    keep = []
    for ln in code.splitlines():
        s = ln.rstrip()
        if not s.strip() or s.strip().startswith(("#", "//", ">")):
            continue
        keep.append(s)
    return "\n".join(keep)


def normalize(code):
    """语法归一化：只剥离显示层。"""
    code = RGB_RE.sub("0", code)
    stmts = [s.strip() for s in code.replace("\r", "").split(";")]
    out = []
    for s in stmts:
        if not s:
            continue
        if any(s.upper().startswith(f) for f in DRAWONLY):      # N3 纯画线语句整条删除
            continue
        if ("'" in s) or ('"' in s):                          # N4a 字符串字面量（TDX 仅显示用）
            continue
        s = re.sub(r"COLOR[A-Z0-9]+", "", s).strip()          # N4b 全局 COLOR 记号
        if not s:
            continue
        prev = None
        while prev != s:
            prev = s
            s = ATTR_RE.sub("", s)                              # N1 显示属性（逗号或空格）
        s = s.strip().rstrip(",").strip()
        if s:
            out.append(s)
    return ";\n".join(out) + ";"


def all_output_prefixes(code):
    stmts = [s.strip() for s in code.replace("\r", "").split(";") if s.strip()]
    res = []
    for i, s in enumerate(stmts):
        m = OUT_NAME.match(s)
        if m:
            res.append((m.group(1), ";".join(stmts[:i + 1]) + ";"))
    return res


# ------------------------------------------------------------------ 求值
def make_eval(ast, local):
    def f(o, h, l, c, v, amo):
        env = {"CLOSE": c, "C": c, "OPEN": o, "O": o, "HIGH": h, "H": h, "LOW": l, "L": l,
               "VOL": v, "V": v, "VOLUME": v, "AMO": amo, "AMOUNT": amo, "DRAWNULL": np.nan}
        with np.errstate(all="ignore"):
            for nm, a in local.items():
                env[nm] = T.ev(a, env)
            return np.asarray(T.ev(ast, env), float)
    return f


def bool_probe(x):
    """→ (是否布尔型, 探针真值数, 说明)"""
    f = x[np.isfinite(x)]
    if f.size < 50:
        return False, 0, "finite<50"
    u = np.unique(np.round(f, 8))
    if not set(u.tolist()).issubset({0.0, 1.0}):
        return False, 0, "numeric(%d distinct)" % u.size
    return True, int((f != 0).sum()), "ok"


def evaluate_formula(code, panel, probe_cols=40):
    O, H, L, C, V, A = panel["O"], panel["H"], panel["L"], panel["C"], panel["V"], panel["A"]
    Tn, N = C.shape
    valid = np.isfinite(C) & (C > 0)
    vcnt = valid.sum(axis=0)
    cols = np.nonzero(vcnt >= 60)[0]
    probe = cols[:: max(1, len(cols) // probe_cols)][:probe_cols]

    cand = []
    for name, prefix in all_output_prefixes(code):
        try:
            ast, local, flags = T.compile_block(prefix)
        except NotImplementedError as e:
            return dict(kind="④", reason=str(e)[:170], signal_name=name)
        except Exception as e:
            return dict(kind="④", reason="compile: %s" % str(e)[:150], signal_name=name)
        f = make_eval(ast, local)
        nb = nt = 0
        for j in probe:
            try:
                x = f(O[:, j], H[:, j], L[:, j], C[:, j], V[:, j], A[:, j])
            except Exception as e:
                return dict(kind="④", reason="eval: %s" % str(e)[:150], signal_name=name)
            b, hits, _ = bool_probe(x)
            nb += 1 if b else 0
            nt += hits
        cand.append(dict(name=name, f=f, bool_share=nb / max(1, len(probe)), probe_true=nt,
                         flags=flags))
    if not cand:
        return dict(kind="③", reason="无输出行")
    bools = [c for c in cand if c["bool_share"] >= 0.9 and c["probe_true"] >= 3]
    if not bools:
        zero = [c for c in cand if c["bool_share"] >= 0.9]
        return dict(kind="②",
                    reason="输出无有效布尔条件（恒零或纯数值）" if zero else "输出为数值序列（画线类）",
                    outputs=[c["name"] for c in cand])
    pick = bools[-1]
    sig = np.zeros((Tn, N), bool)
    n_err = 0
    for j in cols:
        try:
            x = pick["f"](O[:, j], H[:, j], L[:, j], C[:, j], V[:, j], A[:, j])
            sig[:, j] = np.nan_to_num(x, nan=0.0) != 0
        except Exception:
            n_err += 1
    return dict(kind="①", sig=sig, signal_name=pick["name"], n_outputs=len(cand),
                bool_outputs=len(bools), probe_true=int(pick["probe_true"]),
                eval_err_cols=n_err, eval_cols=int(len(cols)))


# ------------------------------------------------------------------ 事件研究
def event_study(sig, panel):
    O, H, L, C = panel["O"], panel["H"], panel["L"], panel["C"]
    Tn, N = C.shape
    mult = _MULT if _MULT is not None else np.full(N, 1.10)
    pc = np.full_like(C, np.nan)
    pc[1:] = C[:-1]
    with np.errstate(all="ignore"):
        ZT = np.round(pc * mult[None, :], 2)
    t_idx, j_idx = np.where(sig)
    if t_idx.size == 0:
        return dict(n=0)
    e = t_idx + 1
    inw = e < Tn
    e_c = np.clip(e, 0, Tn - 1)
    zt_hit = inw & np.isfinite(O[e_c, j_idx]) & (O[e_c, j_idx] >= ZT[e_c, j_idx] - 1e-4)
    n_rej_zt = int(zt_hit.sum())
    ok = inw & np.isfinite(C[t_idx, j_idx]) & (C[t_idx, j_idx] > 0)
    ok &= np.isfinite(O[e_c, j_idx]) & (O[e_c, j_idx] > 0) & (~zt_hit)
    t_idx, j_idx, e = t_idx[ok], j_idx[ok], e[ok]
    if t_idx.size == 0:
        return dict(n=0, n_rej_limit_up=n_rej_zt)
    x = e + 1
    ext = np.zeros(x.shape, bool)
    for k in range(0, 6):
        d = e + 1 + k
        need = (~ext) & (d <= Tn - 1)
        d_c = np.clip(d, 0, Tn - 1)
        good = need & np.isfinite(C[d_c, j_idx]) & (C[d_c, j_idx] > 0)
        x = np.where(good, d, x)
        ext |= good
    n_drop_exit = int((~ext).sum())
    t_idx, j_idx, e, x = t_idx[ext], j_idx[ext], e[ext], x[ext]
    if t_idx.size == 0:
        return dict(n=0, n_rej_limit_up=n_rej_zt, n_drop_no_exit=n_drop_exit)
    entry = O[e, j_idx].astype(np.float64)
    exitp = C[x, j_idx].astype(np.float64)
    with np.errstate(all="ignore"):
        net = exitp / entry - 1.0 - COST
    good = np.isfinite(net) & np.isfinite(entry) & (entry > 0)
    t_idx, j_idx, e, x, net = t_idx[good], j_idx[good], e[good], x[good], net[good]
    pairs, inv = np.unique(np.stack([e, x], axis=1), axis=0, return_inverse=True)
    bm_all = np.empty(len(pairs))
    bm_buy = np.empty(len(pairs))
    for pi, (ee, xx) in enumerate(pairs):
        b = O[ee]
        c = C[xx]
        with np.errstate(all="ignore"):
            rr = c / b - 1.0
        m = np.isfinite(b) & (b > 0) & np.isfinite(c) & (c > 0)   # 面板缺失存 0 → 必须两腿都>0
        zt = np.isfinite(O[ee]) & np.isfinite(ZT[ee]) & (O[ee] >= ZT[ee] - 1e-4)
        m_buy = m & (~zt)
        bm_all[pi] = np.nanmean(rr[m]) if m.any() else np.nan
        bm_buy[pi] = np.nanmean(rr[m_buy]) if m_buy.any() else np.nan
    idx0 = np.argmax(np.isfinite(C), axis=0)
    out = {}
    for tag, bmv, retv in (("all", bm_all, net), ("buy", bm_buy, net),
                            ("gross_buy", bm_buy, net + COST)):
        exc = retv - bmv[inv]
        okk = np.isfinite(exc)
        tt, jj, ee_, xx_, nn_, ex_ = (t_idx[okk], j_idx[okk], e[okk], x[okk], net[okk], exc[okk])
        n = int(len(nn_))
        if n == 0:
            out[tag] = dict(n=0, n_days=0, gate=False)
            continue
        cnt = np.bincount(tt, minlength=Tn)
        s = np.bincount(tt, weights=ex_, minlength=Tn)
        dm = np.divide(s, cnt, out=np.zeros(Tn), where=cnt > 0)
        dm_act = dm[cnt > 0]
        nd = int(dm_act.size)
        if nd >= 2:
            sd = float(dm_act.std(ddof=1))
            se = sd / np.sqrt(nd)
            tstat = float(dm_act.mean() / se) if se > 0 else float("nan")
            tcrit = float(stats.t.ppf(1 - ALPHA / 2, nd - 1))
            ci_lo = float(dm_act.mean() - tcrit * se)
            ci_hi = float(dm_act.mean() + tcrit * se)
        else:
            sd = se = tstat = tcrit = ci_lo = ci_hi = float("nan")
        hold = xx_ - ee_ + 1
        occ = np.zeros(Tn + 1)
        np.add.at(occ, ee_, 1.0)
        np.add.at(occ, np.clip(xx_ + 1, 0, Tn), -1.0)
        conc = np.cumsum(occ)[:Tn]
        out[tag] = dict(
            n=n, n_days=nd, n_rej_limit_up=n_rej_zt, n_drop_no_exit=n_drop_exit,
            net_mean_pct=round(float(nn_.mean()) * 100, 4),
            net_med_pct=round(float(np.median(nn_)) * 100, 4),
            wr=round(float((nn_ > 0).mean()), 4),
            exc_mean_pct=round(float(ex_.mean()) * 100, 4),
            exc_med_pct=round(float(np.median(ex_)) * 100, 4),
            day_mean_pct=round(float(dm_act.mean()) * 100, 4) if nd else None,
            day_med_pct=round(float(np.median(dm_act)) * 100, 4) if nd else None,
            day_pos_share=round(float((dm_act > 0).mean()), 4) if nd else None,
            days_active=nd,
            median_per_day=float(np.median(cnt[cnt > 0])) if nd else None,
            sd_day_pct=round(sd * 100, 4) if np.isfinite(sd) else None,
            t_stat=tstat if np.isfinite(tstat) else None,
            t_crit=tcrit if np.isfinite(tcrit) else None,
            ci95_lo_pct=round(ci_lo * 100, 4) if np.isfinite(ci_lo) else None,
            ci95_hi_pct=round(ci_hi * 100, 4) if np.isfinite(ci_hi) else None,
            avg_hold_days=float(hold.mean()), avg_concurrent=float(conc.mean()),
            max_concurrent=int(conc.max()), uniq_symbols=int(len(np.unique(jj))),
            age_med_days=float(np.median(ee_ - idx0[jj])),
            age_lt120_share=round(float((ee_ - idx0[jj] < 120).mean()), 4),
            bm_ref_mean_pct=round(float(np.nanmean(bmv[inv][okk])) * 100, 4),
            gross_mean_pct=round(float(nn_.mean() + COST) * 100, 4),
            gate=bool(n >= MIN_N and np.isfinite(ci_lo) and ci_lo > 0))
    st = dict(out["all"])
    st.update(bench_buy=out["buy"],
              exc_mean_buy_pct=out["buy"]["exc_mean_pct"],
              day_mean_buy_pct=out["buy"].get("day_mean_pct"),
              ci95_lo_buy_pct=out["buy"].get("ci95_lo_pct"),
              ci95_hi_buy_pct=out["buy"].get("ci95_hi_pct"),
              t_stat_buy=out["buy"].get("t_stat"), t_crit_buy=out["buy"].get("t_crit"),
              gate_buy=bool(out["buy"].get("gate")),
              bm_ref_mean_pct=out["all"].get("bm_ref_mean_pct"),
              bm_ref_mean_buy_pct=out["buy"].get("bm_ref_mean_pct"),
              gross_mean_pct=out["all"].get("gross_mean_pct"),
              exc_gross_buy_pct=out["gross_buy"]["exc_mean_pct"],
              day_gross_buy_pct=out["gross_buy"].get("day_mean_pct"),
              ci95_lo_gross_buy_pct=out["gross_buy"].get("ci95_lo_pct"),
              ci95_hi_gross_buy_pct=out["gross_buy"].get("ci95_hi_pct"),
              t_stat_gross_buy=out["gross_buy"].get("t_stat"),
              gate_gross_buy=bool(out["gross_buy"].get("gate")),
              bench_gross_buy=out["gross_buy"],
              bench_bias_pp=round(float(np.nanmean(bm_all - bm_buy)) * 100, 4))
    return st



# ------------------------------------------------------------------ 工作进程
def _init(panel_path):
    global _PANEL, _MULT
    z = np.load(panel_path, allow_pickle=True)
    _PANEL = {k: z[k] for k in ("O", "H", "L", "C", "V", "A")}
    syms = [str(s) for s in z["syms"]]
    _MULT = np.array([mult_of(s) for s in syms])


def _work(item):
    tid, code = item
    try:
        r = evaluate_formula(code, _PANEL)
    except NotImplementedError as e:
        return tid, dict(kind="④", reason=str(e)[:170])
    except Exception as e:
        return tid, dict(kind="④", reason="%s: %s" % (type(e).__name__, str(e)[:150]))
    if r["kind"] == "①":
        ev = event_study(r["sig"], _PANEL)
        return tid, dict(kind="①", signal_name=r.get("signal_name"), n_outputs=r.get("n_outputs"),
                         bool_outputs=r.get("bool_outputs"), probe_true=r.get("probe_true"),
                         eval_err_cols=r.get("eval_err_cols"), event=ev)
    return tid, r



def build_valid_idx(panel):
    C = panel["C"]
    valid = np.isfinite(C) & (C > 0)
    return [np.nonzero(valid[d])[0] for d in range(C.shape[0])]


def placebo_profile(cnt, rng, vix, Tn, N):
    sig = np.zeros((Tn, N), bool)
    for d in np.nonzero(cnt)[0]:
        pool = vix[d]
        k = int(min(cnt[d], pool.size))
        if k <= 0:
            continue
        sig[d, rng.choice(pool, size=k, replace=False)] = True
    return sig


def run_placebo(panel, vix, profile, seeds):
    """器械检验：同轮廓随机信号在两种基准下的超额收益。"""
    Tn, N = panel["C"].shape
    rng = np.random.default_rng(20260928)
    rows = []
    for sd in range(seeds):
        sig = placebo_profile(profile, rng, vix, Tn, N)
        ev = event_study(sig, panel)
        rows.append(dict(seed=sd, n=ev.get("n"), exc_all=ev.get("exc_mean_pct"),
                         exc_buy=ev.get("exc_mean_buy_pct"),
                         ci_lo_all=ev.get("ci95_lo_pct"), ci_lo_buy=ev.get("ci95_lo_buy_pct"),
                         bm_all=ev.get("bm_ref_mean_pct"), bm_buy=ev.get("bm_ref_mean_buy_pct"), gross=ev.get("gross_mean_pct"),
                         exc_gross=ev.get("exc_gross_buy_pct"),
                         ci_lo_gross=ev.get("ci95_lo_gross_buy_pct"),
                         gate_gross=bool(ev.get("gate_gross_buy")),
                         gate_all=bool(ev.get("gate")), gate_buy=bool(ev.get("gate_buy"))))
    ex_a = np.array([r["exc_all"] for r in rows if r["exc_all"] is not None], float)
    ex_b = np.array([r["exc_buy"] for r in rows if r["exc_buy"] is not None], float)
    ex_g = np.array([r["exc_gross"] for r in rows if r["exc_gross"] is not None], float)
    return dict(n_seeds=len(rows),
                exc_all_mean_pct=float(ex_a.mean()) if ex_a.size else None,
                exc_gross_mean_pct=float(ex_g.mean()) if ex_g.size else None,
                exc_gross_sd_pct=float(ex_g.std(ddof=1)) if ex_g.size > 1 else None,
                gate_gross_hits=int(sum(1 for r in rows if r["gate_gross"])),
                exc_all_sd_pct=float(ex_a.std(ddof=1)) if ex_a.size > 1 else None,
                exc_buy_mean_pct=float(ex_b.mean()) if ex_b.size else None,
                exc_buy_sd_pct=float(ex_b.std(ddof=1)) if ex_b.size > 1 else None,
                bias_pp=float(ex_b.mean() - ex_a.mean()) if (ex_a.size and ex_b.size) else None,
                gate_all_hits=int(sum(1 for r in rows if r["gate_all"])),
                gate_buy_hits=int(sum(1 for r in rows if r["gate_buy"])),
                rows=rows)


# ------------------------------------------------------------------ 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bodies", required=True)
    ap.add_argument("--registry", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ids")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--single", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--placebo", type=int, default=0)
    a = ap.parse_args()

    t0 = time.time()
    dirp = pathlib.Path(a.bodies)
    registry = json.loads(pathlib.Path(a.registry).read_text(encoding="utf-8"))
    reg, bodies = load_bodies(dirp, registry)
    log("[load] registry=%d bodies_found=%d" % (len(reg), len(bodies)))
    _z0 = np.load(PANEL, allow_pickle=True)
    PT, PN = int(_z0["C"].shape[0]), int(_z0["C"].shape[1])
    cal0 = list(_z0["cal"])
    log("[panel] T=%d N=%d %s .. %s" % (PT, PN, cal0[0], cal0[-1]))

    # ---- 预分类（不依赖面板）----
    todo, rows = [], []
    ids = [x.strip() for x in a.ids.split(",")] if a.ids else sorted(bodies, key=lambda x: -int(x))
    if a.limit:
        ids = ids[:a.limit]
    for tid in ids:
        meta = reg.get(tid, {})
        title = meta.get("title", "")
        md = bodies.get(tid, "")
        rec = dict(id=tid, title=title, group=meta.get("group", ""),
                   reply_cnt=meta.get("reply_cnt"), url="https://gushi.in/topic/%s" % tid)
        if not md:
            rec.update(tier="③", verdict="不可用", reason="正文未抓到"); rows.append(rec); continue
        blocks = [clean_code(b) for b in extract_blocks(md)]
        blocks = [b for b in blocks if len(b) >= 10]
        rec["n_blocks"] = len(blocks)
        if not blocks:
            rec.update(tier="③", verdict="不可用", reason="无代码块"); rows.append(rec); continue
        hit = next((k for k in TITLE_SKIP if k in title), None)
        if hit:
            rec.update(tier="③", verdict="不可用", reason="标题含「%s」" % hit); rows.append(rec); continue
        code = normalize(max(blocks, key=len))
        rec["code_len"] = len(code)
        rec["code_sha1"] = hashlib.sha1(code.encode("utf-8")).hexdigest()[:12]
        todo.append((rec, code))

    log("[plan] 待编译 %d 帖；预分类已排除 %d 帖" % (len(todo), len(rows)))

    # ---- 编译 + 事件研究 ----
    res = {}
    if a.single:
        _init(str(PANEL))
        for k, (rec, code) in enumerate(todo):
            tid, r = _work((rec["id"], code))
            res[tid] = r
            log("  [%d/%d] %s %s" % (k + 1, len(todo), rec["id"], r["kind"]))
            if a.probe and k >= 4:
                break
    else:
        with mp.Pool(a.jobs, initializer=_init, initargs=(str(PANEL),)) as pool:
            it = pool.imap_unordered(_work, [(rec["id"], code) for rec, code in todo], chunksize=1)
            for k, (tid, r) in enumerate(it):
                res[tid] = r
                log("  [%d/%d] %s -> %s" % (k + 1, len(todo), tid, r["kind"]))
                if a.probe and k >= 4:
                    pool.terminate(); break

    # ---- 归并 ----
    for rec, code in todo:
        r = res.get(rec["id"])
        if r is None:
            rec.update(tier="④", verdict="不可用", reason="未求值（探针提前结束）"); rows.append(rec); continue
        if r["kind"] == "④":
            rec.update(tier="④", verdict="不可用", reason=r.get("reason", ""))
        elif r["kind"] == "③":
            rec.update(tier="③", verdict="不可用", reason=r.get("reason", ""))
        elif r["kind"] == "②":
            rec.update(tier="②", verdict="不可用", reason=r.get("reason", ""),
                       outputs=r.get("outputs"))
        else:
            ev = r.get("event", {})
            rec.update(tier="①", verdict=("过门→进M3" if ev.get("gate") else "否证（未过门）"),
                       signal_name=r.get("signal_name"), n_outputs=r.get("n_outputs"),
                       bool_outputs=r.get("bool_outputs"), eval_err_cols=r.get("eval_err_cols"),
                       event=ev)
        rows.append(rec)

    placebo_out = None
    if a.placebo > 0:
        log("[placebo] 器械检验：%d 种子 × 2 轮廓（同轮廓随机信号）" % a.placebo)
        if _PANEL is None:
            _init(str(PANEL))
        vix = build_valid_idx(_PANEL)
        Tn, N = _PANEL["C"].shape
        prof_dense = np.zeros(Tn, dtype=int)
        for d in range(Tn):
            if len(vix[d]):
                prof_dense[d] = 30
        prof_sparse = np.zeros(Tn, dtype=int)
        act = [d for d in range(Tn) if len(vix[d])]
        pick = np.random.default_rng(7).choice(act, size=min(500, len(act)), replace=False)
        for d in pick:
            prof_sparse[d] = 5
        placebo_out = dict(dense30=run_placebo(_PANEL, vix, prof_dense, a.placebo),
                           sparse5x500=run_placebo(_PANEL, vix, prof_sparse, a.placebo))
        for tag, r in placebo_out.items():
            log("  [placebo %s] exc_all=%s | exc_buy(含成本)=%s | exc_gross(无成本)=%s (sd %s) | 过门 all=%d net=%d gross=%d / %d"
                % (tag, r["exc_all_mean_pct"], r["exc_buy_mean_pct"], r["exc_gross_mean_pct"],
                   r["exc_gross_sd_pct"], r["gate_all_hits"], r["gate_buy_hits"],
                   r["gate_gross_hits"], r["n_seeds"]))
    rows.sort(key=lambda x: -int(x["id"]))

    from collections import Counter
    tiers = Counter(r["tier"] for r in rows)
    passed = [r for r in rows if r.get("verdict", "").startswith("过门")]
    payload = dict(generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                   prereg="backtest/PRE-REGISTRATION_20260928_forum8_formula_sweep.md",
                   panel=dict(path=str(PANEL), T=PT, N=PN),
                   cost=COST, min_n=MIN_N, alpha=ALPHA,
                   n_topics=len(rows), tier_counts=dict(tiers),
                   n_pass=len(passed), pass_ids=[r["id"] for r in passed],
                   n_pass_buy=sum(1 for r in rows if (r.get("event") or {}).get("gate_buy")),
                   placebo=placebo_out,
                   rows=rows, runtime_sec=round(time.time() - t0, 1))
    pathlib.Path(a.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    log("[done] %s tiers=%s 过门=%d  %.0fs" % (a.out, dict(tiers), len(passed), time.time() - t0))
    for r in passed:
        e = r["event"]
        log("  ★ %s %s n=%d exc=%+.4f%% day=%+.4f%% CIlo=%+.4f%%" % (
            r["id"], r["title"][:34], e["n"], e["exc_mean_pct"], e["day_mean_pct"], e["ci95_lo_pct"]))


if __name__ == "__main__":
    main()
