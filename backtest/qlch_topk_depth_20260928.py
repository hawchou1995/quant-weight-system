# -*- coding: utf-8 -*-
"""qlch_topk_depth_20260928.py — qlch「按超跌深度取 TopK」预注册回测（R-qlch-topkdepth-0928）

预注册： backtest/PRE-REGISTRATION_20260928_qlch_topk_depth.md（**本脚本跑数前已落盘**）

纪律
----
· 复用生产引擎（importlib 加载 `qlch_paper_20260921.py`，其有 `__main__` 守卫 → main() 不执行）取信号与冻结阈值，**不复制阈值**；
· 复用既有工装 `qlch_grid_bt_0923.py` 的入场情形/出场解析/指标函数（该文件亦有 `__main__` 守卫）；
· 唯一的自写部分是「K 槽位组合 + 逐日几何摊销」的 `simulate_rule`——它是 `qlch_grid_bt_0923.simulate` 的**逐行副本 + 排序钩子**，
  `rule="random"` 时必须与原型逐位一致（脚本内自校验，失败即退出，不出裁决）。

臂（冻结，见预注册 §四）
----
  B0 random（生产现状，5 种子均值对照）
  B1 depth（**主臂**：ret20(T−1) 越负越前取最深前 room 个）
  B2/B3 depth 且 K=1/2（鲁棒性臂，不参与过门裁决）

用法:
  python qlch_topk_depth_20260928.py --validate                 # 只跑同尺子锚定
  python qlch_topk_depth_20260928.py --out evidence.json         # 全量
"""
import argparse, importlib.util, json, os, sys, time
import numpy as np
from pathlib import Path

BK = Path(__file__).resolve().parent
sys.path.insert(0, str(BK))
import qlch_grid_bt_0923 as G          # noqa: E402  复用其函数（有 __main__ 守卫）

COST_RT, SLIP_SIDE = 0.0020, 0.0020
COST_TOT = COST_RT + 2 * SLIP_SIDE      # 0.0060 = 往返 60bp（看板主显压力档）
COST50 = 0.0050
SEEDS = list(G.SEEDS)
K0 = 3
ANN = G.ANN
TRAIN_HI, VAL_LO = G.TRAIN_HI, G.VAL_LO
ENGINE_FILE = "qlch_paper_20260921.py"
PREREG = "PRE-REGISTRATION_20260928_qlch_topk_depth.md"

LOG = []
def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True); LOG.append(s)


def load_engine(mainboard: bool):
    """等价于 G.load_engine，但池口径可配（生产主轨 = 全池；grid 原版硬编码真主板）。"""
    os.environ["QLCH_VARIANT"] = "B4"
    os.environ["QLCH_MAINBOARD"] = "1" if mainboard else "0"
    os.environ["QLCH_GATE"] = "20"
    os.environ["QLCH_SELECT"] = "random"
    spec = importlib.util.spec_from_file_location("qlch_paper_engine", str(BK / ENGINE_FILE))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def simulate_rule(e, x, ret, hold, keys, T, seeds, K=3, rule="random"):
    """`G.simulate` 的逐行副本 + 排序钩子。

    与原型唯一差异：候选多于空位时的取法
      · rule="random" → 原型行为（rng.choice）——用于自校验逐位一致
      · rule="depth"  → 按 keys 升序（ret20 越负越前 = 超跌最深优先）取前 room 个
    """
    n = e.size
    by_day = {}
    for i in range(n):
        by_day.setdefault(int(e[i]), []).append(i)
    navs, invs = [], []
    te, tx, tr, th, tv = [], [], [], [], []
    t_lo, t_hi = int(e.min()), int(x.max())
    for sd in seeds:
        rng = np.random.default_rng(sd)
        cash, pos = 1.0, []
        nav, inv = np.ones(T), np.zeros(T)
        for t in range(t_lo, t_hi + 1):
            if pos:
                still = []
                for q in pos:
                    if q[0] == t:
                        cash += q[1] * (1.0 + q[2])
                        te.append(q[4]); tx.append(t); tr.append(q[2]); th.append(q[3]); tv.append(2.0 * q[1])
                    else:
                        still.append(q)
                pos = still
            mv_now = 0.0
            for q in pos:
                mv_now += q[1] * (1.0 + q[2]) ** (min(t - q[4] + 1, q[3]) / q[3])
            lst, room = by_day.get(t), K - len(pos)
            if lst and room > 0 and cash > 1e-12:
                if len(lst) <= room:
                    sel = lst
                elif rule == "random":
                    sel = [lst[i] for i in sorted(rng.choice(len(lst), size=room, replace=False))]
                elif rule == "depth":
                    # lst 的元素本身即「已用子集」内的下标 → depth 直接按 keys 升序取前 room 个元素
                    sel = sorted(lst, key=lambda ii: keys[ii])[:room]
                else:
                    raise ValueError("unknown rule %r" % rule)
                for ii in sel:
                    alloc = min(cash, (cash + mv_now) / K)
                    if alloc <= 1e-12:
                        break
                    cash -= alloc
                    pos.append((int(x[ii]), alloc, float(ret[ii]), int(hold[ii]), t))
            mv = 0.0
            for q in pos:
                elap = min(t - q[4] + 1, q[3])
                mv += q[1] * (1.0 + q[2]) ** (elap / q[3])
            tot = cash + mv
            nav[t], inv[t] = tot, (mv / tot if tot > 0 else 0.0)
        nav[t_hi + 1:] = cash
        navs.append(nav); invs.append(inv)
    return (np.mean(navs, axis=0), np.mean(invs, axis=0),
            np.array(te, np.int64), np.array(tx, np.int64),
            np.array(tr, np.float64), np.array(th, np.int64), np.array(tv, np.float64))


def build(mainboard, cost_total, tp_pct, sl_pct, H, case="A"):
    """取信号 → 入场情形 → 出场计划 → 组合输入。返回 dict（含 keys = 排序用的 ret20 深度）。"""
    eng = load_engine(mainboard)
    P = eng.load_all()
    S = eng.build_signals(P)
    ents = G.entry_cases(S)
    T = S["close"].shape[0]
    e = np.concatenate([ents[k]["e"] for k in case])
    j = np.concatenate([ents[k]["j"] for k in case])
    px = np.concatenate([ents[k]["px"] for k in case])
    o = np.argsort(e, kind="stable")
    e, j, px = e[o], j[o], px[o]
    kmax = max(H - 1, 1)
    Oa, Ha, La, Ca = G.case_path(e, j, S["open"], S["high"], S["low"], S["close"], T, kmax)
    kf, ex_px, ex_rs, hit = G.resolve_exit(px, Oa, Ha, La, Ca, tp_pct, sl_pct)
    use, x, opx, hold, rs = G.exit_plan(e, px, kf, ex_px, ex_rs, hit, Ca, H, T)
    ret = opx[use] / px[use] - 1.0 - cost_total
    keys = np.asarray(S["r20"][e[use] - 1, j[use]], dtype=np.float64)   # ret20(T-1)，入场日开盘前已知
    all_e = np.concatenate([ents[k]["e"] for k in "ABC"])
    i_first = int(all_e.min())
    cal = S["cal"]
    i_train = max([i for i, d in enumerate(cal) if d <= TRAIN_HI] or [0])
    i_val = min([i for i, d in enumerate(cal) if d >= VAL_LO] or [T - 1])
    slices = {"full": (i_first, T - 1), "train": (i_first, i_train), "val": (i_val, T - 1)}
    return dict(S=S, T=T, e=e[use], x=x[use], ret=ret, hold=hold[use], keys=keys,
                cal=cal, slices=slices, eng=eng, n_raw=int(e.size), n_used=int(use.sum()),
                i_first=i_first, i_train=i_train, i_val=i_val,
                ret20_min=float(np.nanmin(keys)), ret20_max=float(np.nanmax(keys)))


def yearly(nav, cal, i_first, i_last):
    out = {}
    for i in range(i_first, i_last + 1):
        y = cal[i][:4]
        out.setdefault(y, [i, i])
        out[y][1] = i
    res = {}
    for y, (a, b) in out.items():
        if b <= a:
            res[y] = None
            continue
        v = nav[a:b + 1]
        res[y] = round(100.0 * (float(v[-1] / v[0]) - 1.0), 4)
    return res


def run_arm(D, rule, K, cost_total, seeds=SEEDS):
    nav, inv, te, tx, tr, th, tv = simulate_rule(
        D["e"], D["x"], D["ret"], D["hold"], D["keys"], D["T"], seeds, K=K, rule=rule)
    met = G.metrics_all(nav, inv, te, tr, th, tv, D["slices"], len(seeds))
    tr_win = D["slices"]["train"]
    yy = yearly(nav, D["cal"], tr_win[0], tr_win[1])
    yrs = [v for v in yy.values() if v is not None]
    yneg = sum(1 for v in yrs if v < 0)
    # 按天等权（每笔净收益 / 持有天数）；用于 50bp 硬门
    m = (te >= tr_win[0]) & (te <= tr_win[1])
    perday = float(np.mean(tr[m] / np.maximum(th[m], 1))) * 100.0 if m.any() else None
    return dict(rule=rule, K=K, cost_bp=round(cost_total * 1e4, 2),
                full=met["full"], train=met["train"], val=met["val"],
                yearly_train=yy, n_neg_years_train=yneg, n_years_train=len(yrs),
                train_perday_net_pct=(round(perday, 4) if perday is not None else None),
                nav_last=float(nav[-1])), nav, tr, th, te


def _grid_base_current(cost_total=COST_TOT):
    """用**既有工装自身的函数**（不改一行）在当前面板复算 grid BASE 格（entry=A/tp15/sl-20/h20/真主板/60bp）。"""
    D = build(True, cost_total, 15 / 100.0, -20 / 100.0, 20, case="A")
    nav, inv, te, tx, tr, th, tv = G.simulate(D["e"], D["x"], D["ret"], D["hold"], D["T"], SEEDS, K=K0)
    met = G.metrics_all(nav, inv, te, tr, th, tv, D["slices"], len(SEEDS))
    return D, nav, met


def anchor_check(cost_total=COST_TOT):
    """同尺子锚定（预注册 §六之二）：
       锚-1 自写 simulate_rule(random) 与工装原型 G.simulate 在相同输入下净值逐位一致（≤1e-12）；
       锚-2 用 G 自身函数在当前面板复算 grid BASE 格，与我的 run_arm(random) 对照。
    """
    D = build(True, cost_total, 15 / 100.0, -20 / 100.0, 20, case="A")
    # 锚-1：逐位等价
    nav_g, inv_g, te_g, tx_g, tr_g, th_g, tv_g = G.simulate(
        D["e"], D["x"], D["ret"], D["hold"], D["T"], SEEDS, K=K0)
    nav_m, inv_m, te_m, tx_m, tr_m, th_m, tv_m = simulate_rule(
        D["e"], D["x"], D["ret"], D["hold"], D["keys"], D["T"], SEEDS, K=K0, rule="random")
    d_nav = float(np.max(np.abs(nav_m - nav_g)))
    d_inv = float(np.max(np.abs(inv_m - inv_g)))
    a1 = dict(max_abs_nav_diff=d_nav, max_abs_inv_diff=d_inv,
              pass_=bool(d_nav <= 1e-12 and d_inv <= 1e-12))
    # 锚-2：同面板复算对照
    met_g = G.metrics_all(nav_g, inv_g, te_g, tr_g, th_g, tv_g, D["slices"], len(SEEDS))
    out_m, _, _, _, _ = run_arm(D, "random", K0, cost_total)
    exp = dict(n=met_g["full"]["n"], cagr=met_g["full"]["cagr"], sharpe=met_g["full"]["sharpe"],
               mdd=met_g["full"]["mdd"], tr_sharpe=met_g["train"]["sharpe"], tr_n=met_g["train"]["n"])
    got = dict(n=out_m["full"]["n"], cagr=out_m["full"]["cagr"], sharpe=out_m["full"]["sharpe"],
               mdd=out_m["full"]["mdd"], tr_sharpe=out_m["train"]["sharpe"], tr_n=out_m["train"]["n"])
    a2 = dict(expect=exp, got=got, pass_=dict(
        n_pass=bool(got["n"] == exp["n"]),
        cagr_pass=bool(abs(got["cagr"] - exp["cagr"]) <= 0.05),
        sharpe_pass=bool(abs(got["sharpe"] - exp["sharpe"]) <= 0.01),
        mdd_pass=bool(abs(got["mdd"] - exp["mdd"]) <= 0.05),
        tr_sharpe_pass=bool(abs(got["tr_sharpe"] - exp["tr_sharpe"]) <= 0.02)),
        all_pass=bool(got["n"] == exp["n"] and got["tr_n"] == exp["tr_n"]
                      and abs(got["cagr"] - exp["cagr"]) <= 0.05
                      and abs(got["sharpe"] - exp["sharpe"]) <= 0.01
                      and abs(got["mdd"] - exp["mdd"]) <= 0.05
                      and abs(got["tr_sharpe"] - exp["tr_sharpe"]) <= 0.02))
    hist = dict(note="历史锚点（面板末 2026-09-21，已延展，仅作旁证）",
                n=1127, cagr=4.2178, sharpe=0.6695, mdd=-29.5468,
                current_panel_n=exp["n"], panel_extension_extra_trades=exp["n"] - 1127)
    return dict(anchor1_bitwise=a1, anchor2_samepanel=a2, historical_grid_base=hist,
                all_pass=bool(a1["pass_"] and a2["all_pass"])), out_m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    res = dict(meta=dict(script=Path(__file__).name, version="qlch-topkdepth-0928/v1",
                         run_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                         prereg=PREREG,
                         prereg_mtime=time.strftime("%Y-%m-%d %H:%M:%S",
                                                    time.localtime((BK / PREREG).stat().st_mtime)),
                         engine=ENGINE_FILE, K=K0, seeds=SEEDS,
                         costs=dict(prod_bp=20.0, main_display_bp=round(COST_TOT * 1e4, 2),
                                    hardgate_bp=50.0),
                         criteria=dict(sharpe_gain_min=0.05, mdd_not_worse=True,
                                       perday_gt=0.0, yearly_neg_frac_max=1 / 3.0)),
                anchor=None, arms=[], checks=[])

    log("=== 同尺子锚定（预注册 §六之二）===")
    anc, _ = anchor_check()
    res["anchor"] = anc
    log("  锚-1 逐位等价：自写 simulate_rule(random) vs 工装 G.simulate → max|Δnav|=%.3e max|Δinv|=%.3e ⇒ %s"
        % (anc["anchor1_bitwise"]["max_abs_nav_diff"], anc["anchor1_bitwise"]["max_abs_inv_diff"],
           anc["anchor1_bitwise"]["pass_"]))
    log("  锚-2 同面板复算：期望 %s" % json.dumps(anc["anchor2_samepanel"]["expect"], ensure_ascii=False))
    log("                  实得 %s" % json.dumps(anc["anchor2_samepanel"]["got"], ensure_ascii=False))
    log("                  判据 %s ⇒ %s" % (json.dumps(anc["anchor2_samepanel"]["pass_"], ensure_ascii=False),
                                             anc["anchor2_samepanel"]["all_pass"]))
    log("  旁证：历史锚点(g) %s" % json.dumps(anc["historical_grid_base"], ensure_ascii=False))
    res["checks"].append(dict(name="anchor1_bitwise", passed=anc["anchor1_bitwise"]["pass_"]))
    res["checks"].append(dict(name="anchor2_samepanel", passed=anc["anchor2_samepanel"]["all_pass"]))
    if not anc["all_pass"]:
        log("!! 锚定未通过 → 按预注册 §六：停止，不出裁决。")
        if a.out:
            Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        return 3
    if a.validate:
        log("--validate 指定 → 仅锚定，结束。")
        return 0

    log("")
    log("=== 主口径（现行生产：B4 + K3 + MA20 + 全池 / 现行出场 E2 = 固定持 2 日）===")
    for tag, mb in (("prod_allpool", False), ("prod_mainboard", True)):
        for cost, lab in ((COST_RT, "20bp（生产引擎档）"), (COST_TOT, "60bp（看板主显压力档）"),
                          (COST50, "50bp（上游硬门档）")):
            D = build(mb, cost, 9.99, -0.99, 2, case="A")
            base = None
            for rule, K, arm_lab in (("random", K0, "B0"), ("depth", K0, "B1"),
                                     ("depth", 1, "B2"), ("depth", 2, "B3")):
                out, nav, tr, th, te = run_arm(D, rule, K, cost)
                rec = dict(pool=tag, pool_mainboard=bool(mb), cost_label=lab, arm=arm_lab,
                           n_cand=int(D["n_raw"]), n_used=int(D["n_used"]),
                           ret20_key_range=[D["ret20_min"], D["ret20_max"]], **out)
                if rule == "random" and K == K0:
                    base = rec
                res["arms"].append(rec)
                log("  %-14s %-8s %-18s %s K=%d | 训练窗 年化%+7.2f%% 夏普%6.3f 回撤%+7.2f%% 笔数%5d | 全窗 年化%+7.2f%% 夏普%6.3f 回撤%+7.2f%% inv%5.1f%%"
                    % (tag, lab[:6], lab if lab else "", arm_lab, K,
                       rec["train"]["cagr"], rec["train"]["sharpe"], rec["train"]["mdd"], rec["train"]["n"],
                       rec["full"]["cagr"], rec["full"]["sharpe"], rec["full"]["mdd"], rec["full"]["inv"]))
            if base is not None:
                b1 = [r for r in res["arms"] if r["pool"] == tag and r["cost_label"] == lab
                      and r["arm"] == "B1"][-1]
                d_sh = round(b1["train"]["sharpe"] - base["train"]["sharpe"], 4)
                d_mdd = round(b1["train"]["mdd"] - base["train"]["mdd"], 4)
                res["checks"].append(dict(
                    name="B1_vs_B0@%s/%s" % (tag, lab),
                    sharpe_gain=d_sh, mdd_delta=d_mdd,
                    sharpe_pass=bool(d_sh >= 0.05), mdd_pass=bool(d_mdd >= -1e-9),
                    n_neg_years_train=b1["n_neg_years_train"], n_years_train=b1["n_years_train"],
                    yearly_pass=bool(b1["n_neg_years_train"] <= b1["n_years_train"] / 3.0),
                    perday_net_pct=b1["train_perday_net_pct"]))
                log("     B1 vs B0：夏普 %+.4f（判据≥+0.05 → %s）| 回撤 %+.4fpp（不劣化 → %s）| 训练窗负年 %d/%d"
                    % (d_sh, d_sh >= 0.05, d_mdd, d_mdd >= -1e-9, b1["n_neg_years_train"], b1["n_years_train"]))

    res["elapsed_sec"] = round(time.time() - t0, 1)
    log("")
    log("总耗时 %.1f s" % res["elapsed_sec"])
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        log("[out] %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
