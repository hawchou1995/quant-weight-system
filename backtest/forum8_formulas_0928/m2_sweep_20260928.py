# -*- coding: utf-8 -*-
"""m2_sweep_20260928.py — gushi.in/forum/8 全量策略事件级粗筛（M2）

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
    bmv = np.empty(len(pairs))
    for pi, (ee, xx) in enumerate(pairs):
        b = O[ee]
        c = C[xx]
        with np.errstate(all="ignore"):
            rr = c / b - 1.0
        m = np.isfinite(rr) & np.isfinite(b) & (b > 0)
        bmv[pi] = np.nanmean(rr[m]) if m.any() else np.nan
    exc = net - bmv[inv]
    okk = np.isfinite(exc)
    t_idx, j_idx, e, x, net, exc = (t_idx[okk], j_idx[okk], e[okk], x[okk], net[okk], exc[okk])
    n = int(len(net))
    if n == 0:
        return dict(n=0, n_rej_limit_up=n_rej_zt, n_drop_no_exit=n_drop_exit)
    cnt = np.bincount(t_idx, minlength=Tn)
    s = np.bincount(t_idx, weights=exc, minlength=Tn)
    dm = np.divide(s, cnt, out=np.zeros(Tn), where=cnt > 0)
    dm_act = dm[cnt > 0]
    n_days = int(dm_act.size)
    if n_days >= 2:
        sd = float(dm_act.std(ddof=1))
        se = sd / np.sqrt(n_days)
        tstat = float(dm_act.mean() / se) if se > 0 else float("nan")
        tcrit = float(stats.t.ppf(1 - ALPHA / 2, n_days - 1))
        ci_lo, ci_hi = float(dm_act.mean() - tcrit * se), float(dm_act.mean() + tcrit * se)
    else:
        sd = se = tstat = tcrit = ci_lo = ci_hi = float("nan")
    hold = x - e + 1
    occ = np.zeros(Tn + 1)
    np.add.at(occ, e, 1.0)
    np.add.at(occ, np.clip(x + 1, 0, Tn), -1.0)
    conc = np.cumsum(occ)[:Tn]
    idx0 = np.argmax(np.isfinite(C), axis=0)
    gate = bool(n >= MIN_N and np.isfinite(ci_lo) and ci_lo > 0)
    return dict(n=n, n_days=n_days, n_rej_limit_up=n_rej_zt, n_drop_no_exit=n_drop_exit,
                net_mean_pct=round(float(net.mean()) * 100, 4),
                net_med_pct=round(float(np.median(net)) * 100, 4),
                wr=round(float((net > 0).mean()), 4),
                exc_mean_pct=round(float(exc.mean()) * 100, 4),
                exc_med_pct=round(float(np.median(exc)) * 100, 4),
                day_mean_pct=round(float(dm_act.mean()) * 100, 4),
                day_med_pct=round(float(np.median(dm_act)) * 100, 4),
                day_pos_share=round(float((dm_act > 0).mean()), 4),
                days_active=n_days, median_per_day=float(np.median(cnt[cnt > 0])),
                sd_day_pct=round(sd * 100, 4) if np.isfinite(sd) else None,
                t_stat=tstat if np.isfinite(tstat) else None, t_crit=tcrit if np.isfinite(tcrit) else None,
                ci95_lo_pct=round(ci_lo * 100, 4) if np.isfinite(ci_lo) else None,
                ci95_hi_pct=round(ci_hi * 100, 4) if np.isfinite(ci_hi) else None,
                avg_hold_days=float(hold.mean()), avg_concurrent=float(conc.mean()),
                max_concurrent=int(conc.max()), uniq_symbols=int(len(np.unique(j_idx))),
                age_med_days=float(np.median(e - idx0[j_idx])),
                age_lt120_share=round(float((e - idx0[j_idx] < 120).mean()), 4),
                gate=gate)


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
                   rows=rows, runtime_sec=round(time.time() - t0, 1))
    pathlib.Path(a.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    log("[done] %s tiers=%s 过门=%d  %.0fs" % (a.out, dict(tiers), len(passed), time.time() - t0))
    for r in passed:
        e = r["event"]
        log("  ★ %s %s n=%d exc=%+.4f%% day=%+.4f%% CIlo=%+.4f%%" % (
            r["id"], r["title"][:34], e["n"], e["exc_mean_pct"], e["day_mean_pct"], e["ci95_lo_pct"]))


if __name__ == "__main__":
    main()
