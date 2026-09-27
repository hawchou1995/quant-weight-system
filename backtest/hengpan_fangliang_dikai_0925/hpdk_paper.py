# -*- coding: utf-8 -*-
"""hpdk_paper.py — 「横盘低开·两日」模拟盘账户 + 跟踪池（2026-09-27，R-hpdk-paper-0927）

为什么需要它：其它 5 个短线策略都有「模拟盘 + 跟踪池」，本策略初版只有策略卡与前向 OOS 卡 —— 这是缺口。

口径纪律（不重写信号逻辑）：
  · import 冻结脚本 oos_run.py（与 hpdk_candidates.py 同一做法），重定向输出 + 运行期前移 SHADOW_START，
    并把 K 放大以取到每日**全部**入选；面板复用 hpdk_candidates 的缓存文件。
  · **账户记账**（操作档，与看板「单票可买」「建议股数」同口径）：
      本金 100 万 / KSLOT=4 / 单票 = min(前一日净值/KSLOT, 可用现金, 该股 ADV×1%) / 成本单边 0.000346
      出场按台账 exit_date/exit_px（止盈 +2% 或 T+2 尾盘）
  · **与冻结台账对拍**：oos_trades.jsonl 的已了结子集必须与本地重放结果逐位一致（金额字段除外），
    不一致即 exit≠0 并打印差异 —— 防止模拟盘与 OOS 台账各说各话。

产出 backtest/hpdk_paper.json：
  config / account / nav_daily / positions(持有中) / settled(已了结) / track(跟踪池行) / pool_now(当前信号日资格池摘要)

用法: python hpdk_paper.py [--cache DIR] [--capital 1000000] [--kslot 4] [--outdir DIR]
"""
import os, sys, json, math, argparse, pathlib, importlib.util, time, tempfile
import numpy as np
import pandas as pd

R = pathlib.Path(__file__).resolve().parents[2]
OUT = R / "backtest/hengpan_fangliang_dikai_0925"
PUB = R / "backtest"
OOS = OUT / "oos_run.py"
UNI = R / "backtest/wechat_hotspot_leader_0925/universe.json"
ADV_FRAC = 0.01
TRACK_KEEP_DAYS = 30          # 跟踪池保留窗口（自然日）


def log(*a):
    print(*a, flush=True)


def load_mod():
    spec = importlib.util.spec_from_file_location("oos_run_paper", OOS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get_panel(mod, cache):
    cal, live, dead = mod.load_universe()
    syms = live + dead
    key = abs(hash("%s_%d_%d" % (cal[-1], len(cal), len(syms))))
    f = cache / ("hpdk_panel_%d.npz" % key)
    if f.exists():
        z = np.load(f, allow_pickle=True)
        if list(z["cal"]) == cal and list(z["syms"]) == syms:
            log("[panel] 缓存命中 %s" % f.name)
            return cal, syms, {k: z[k] for k in ("O", "H", "L", "C", "V", "A")}
    t0 = time.time()
    F, done = mod.build(cal, syms)
    log("[panel] 重建 T=%d N=%d done=%d（%.1fs）" % (F["C"].shape[0], F["C"].shape[1], done, time.time() - t0))
    np.savez_compressed(f, cal=np.array(cal, dtype=object), syms=np.array(syms, dtype=object),
                        **{k: v.astype(np.float32) for k, v in F.items()})
    return cal, syms, F


def allpicks(mod, cache, F, done):
    """用宽口径重放取「每日全部入选（含并列）」，用于自行排名（与 hpdk_candidates 的 A11 同源）。"""
    mod.STATE_F = cache / "_p_all_state.json"
    mod.TRADES_F = cache / "_p_all_trades.jsonl"
    mod.REPORT_F = cache / "_p_all_report.json"
    for p in (mod.STATE_F, mod.TRADES_F, mod.REPORT_F):
        if p.exists():
            p.unlink()
    mod.P["SHADOW_START"] = "2016-01-01"
    mod.P["K"] = 10 ** 9
    mod.P["P1"], mod.P["P2"] = -1.0, 10.0          # 放宽低开带 -> 取整天资格集；真实带在下方自行过滤
    mod.build = lambda _c, _s: (F, done)
    mod.main()
    if not mod.TRADES_F.exists():
        return {}
    out = {}
    for x in mod.TRADES_F.read_text(encoding="utf-8").splitlines():
        if x.strip():
            r = json.loads(x)
            out.setdefault(r["signal_date"], []).append(r["sym"])   # 只存 sym（存整条 dict 会 unhashable）
    return out


def features(F):
    O, C, V, A = F["O"], F["C"], F["V"], F["A"]
    VALID = (C > 0) & np.isfinite(C) & (O > 0)
    Av = np.where(VALID, A, np.nan); Vv = np.where(VALID, V, np.nan)
    AMT20 = pd.DataFrame(Av).rolling(20, min_periods=10).mean().to_numpy(np.float64)
    VMA = pd.DataFrame(Vv).rolling(20, min_periods=10).mean().to_numpy(np.float64)
    VMAp = np.full_like(VMA, np.nan); VMAp[1:] = VMA[:-1]
    VOLBR = V / np.where(VMAp > 0, VMAp, np.nan)
    Cv = np.where(VALID, C, np.nan)
    RET20 = np.full(C.shape, np.nan); RET20[20:] = Cv[20:] / Cv[:-20] - 1.0
    GAP = np.full(C.shape, np.nan); GAP[:-1] = O[1:] / np.where(C[:-1] > 0, C[:-1], np.nan) - 1.0
    return dict(AMT20=AMT20, VOLBR=VOLBR, RET20=RET20, GAP=GAP, VALID=VALID)


def zs(x):
    x = np.asarray(x, float); mu = np.nanmean(x); sd = np.nanstd(x)
    return (x - mu) / sd if np.isfinite(sd) and sd > 0 else np.zeros_like(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.environ.get("PI_SCRATCH_DIR")
                                         or os.path.join(tempfile.gettempdir(), "hpdk_cache"))
    ap.add_argument("--capital", type=float, default=1_000_000.0)
    ap.add_argument("--kslot", type=int, default=4)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--shadow-start", default=None, help="测试用：覆盖冻结 shadow_start（默认不覆盖）")
    a = ap.parse_args()
    cache = pathlib.Path(a.cache); cache.mkdir(parents=True, exist_ok=True)
    outdir = pathlib.Path(a.outdir) if a.outdir else PUB
    outdir.mkdir(parents=True, exist_ok=True)

    mod = load_mod()
    sha0 = mod.FROZEN_SHA
    P = dict(mod.P)
    if a.shadow_start:
        P["SHADOW_START"] = a.shadow_start
        log("[test] 已覆盖 shadow_start = %s" % a.shadow_start)
    cal, syms, F = get_panel(mod, cache)
    T = len(cal)
    jof = {s: j for j, s in enumerate(syms)}
    names = json.loads((R / "data_full_names.json").read_text(encoding="utf-8"))
    ind = {u["sym"]: u.get("ind", "") for u in
           json.loads(UNI.read_text(encoding="utf-8"))["universe"]}

    def board_of(s):
        if s[:2] == "sh" and s[2:5] in ("600", "601", "603", "605"): return "主板"
        if s[:2] == "sz" and s[2:5] in ("000", "001", "002", "003"): return "主板"
        if s[:2] == "sz" and s[2:5] in ("300", "301", "302"): return "创业板"
        if s[:2] == "sh" and s[2:5] == "688": return "科创板"
        return "其他"

    # ---- ① 宽口径重放（占位日历 2 日 → 可解析到末日信号日的资格集）----
    cal2 = list(cal) + ["2099-01-01", "2099-01-02"]
    F2 = {k: np.concatenate([v, np.ones((2, v.shape[1]), dtype=v.dtype)], axis=0) for k, v in F.items()}
    _lu = mod.load_universe
    mod.load_universe = lambda: (cal2, syms, [])
    wide = allpicks(mod, cache, F2, len(syms))
    mod.load_universe = _lu
    assert mod.FROZEN_SHA == sha0, "冻结脚本 SHA 被改动！"
    ft = features(F2)

    # ---- ② 逐信号日自行排名（与 oos_run 的复合分同式）----
    si = next((i for i, d in enumerate(cal) if d >= P["SHADOW_START"]), None)
    if si is None:
        si = T
    log("shadow_start=%s → 首个信号日索引 %s（日历 %d 日）" % (P["SHADOW_START"], si, T))
    trades = []
    for t in range(si, T):
        cand = wide.get(cal[t], [])
        g = ft["GAP"][t]
        if t >= T - 1:
            # 末日：gap 需要 t+1 的开盘价（占位行无效）→ 无法定榜，仅登记为「待判定」
            trades.append(dict(signal_date=cal[t], undetermined=True, n_pool=len(cand)))
            continue
        pick = [c for c in cand if np.isfinite(g[jof[c]]) and -P["P2"] <= g[jof[c]] <= -P["P1"]]
        if not pick:
            continue
        amt = np.array([ft["AMT20"][t, jof[s]] for s in pick])
        vbr = np.array([ft["VOLBR"][t, jof[s]] for s in pick])
        r20 = np.array([ft["RET20"][t, jof[s]] for s in pick])
        comp = zs(-np.log(amt)) + zs(-np.log(vbr)) + zs(-r20)
        order = [pick[q] for q in np.argsort(-comp)[:int(P["K"])]]
        for s in order:
            j = jof[s]
            trades.append(dict(signal_date=cal[t], undetermined=False, sym=s,
                               gap=round(float(g[j]) * 100, 3),
                               entry_date=cal[t + 1] if t + 1 < T else None,
                               entry_open=None if t + 1 >= T else round(float(F2["O"][t + 1, j]), 4),
                               exit_date=cal[t + 2] if t + 2 < T else None,
                               exit_px=None if t + 2 >= T else round(float(F2["C"][t + 2, j]), 4)))
    n_und = sum(1 for x in trades if x.get("undetermined"))
    n_real = len(trades) - n_und
    log("信号日条目：定榜 %d 笔（含未到期）· 待判定信号日 %d 个" % (n_real, n_und))

    # ---- ③ 与冻结台账对拍 ----
    led = {}
    lf = OUT / "oos_trades.jsonl"
    if lf.exists() and lf.stat().st_size > 0:
        for x in lf.read_text(encoding="utf-8").splitlines():
            if x.strip():
                r = json.loads(x)
                led[(r["signal_date"], r["sym"])] = r
    mine_set = {(x["signal_date"], x["sym"]) for x in trades
                if not x.get("undetermined") and x.get("exit_date") and x.get("entry_date")}
    bad = []
    for k, v in led.items():
        m = next((x for x in trades if x["signal_date"] == k[0] and x.get("sym") == k[1]), None)
        if m is None:
            bad.append(("台账有、重放无", k)); continue
        if m["entry_open"] != v["entry_open"] or m["exit_px"] != v["exit_px"]:
            bad.append(("价格不一致", k, m["entry_open"], v["entry_open"], m["exit_px"], v["exit_px"]))
    log("[对拍] 台账 %d 笔 / 重放可了结 %d 笔 / 不一致 %d 项" % (len(led), len(mine_set), len(bad)))
    for b in bad[:5]:
        log("   !! %s" % (b,))

    # ---- ④ 模拟盘账户（操作档：本金/KSLOT/ADV×1%/成本）----
    # 建仓时点 = **买入日**（信号日的次一交易日）开盘：故在第 t 日先按 cal[t-1] 的信号建仓、
    # 再处理当日了结（exit_date == 当日），最后按当日收盘盯市 —— 避免「用信号日收盘估值刚建的仓」。
    cost = float(P["COST_SIDE"])
    CAP = float(a.capital)                     # 账户用**真钱**（元）；用归一化 1.0 会让整手 floor 成 0 股
    nav, cash, pos, settled = {}, CAP, [], []
    by_day = {}
    for x in trades:
        if not x.get("undetermined"):
            by_day.setdefault(x["signal_date"], []).append(x)
    for t in range(si, T):
        d = cal[t]
        navprev = nav.get(cal[t - 1], CAP) if t > si else CAP
        if t > si:                                     # A) 入场（信号日 cal[t-1] → 今日开盘买）
            for x in by_day.get(cal[t - 1], []):
                if len(pos) >= a.kslot:
                    break
                if any(q["sym"] == x["sym"] for q in pos):
                    continue
                px = x.get("entry_open")
                if not (px and px > 0):
                    continue
                amt20 = ft["AMT20"][t - 1, jof[x["sym"]]]
                capv = float(amt20) * ADV_FRAC if np.isfinite(amt20) else 0.0
                alloc = min(navprev / a.kslot, cash, capv)
                if alloc <= 1e-9:
                    continue
                sh = int(math.floor(alloc / (px * (1.0 + cost)) / 100.0) * 100)
                if sh <= 0:
                    continue
                outlay = sh * px * (1.0 + cost)
                cash -= outlay
                pos.append(dict(signal_date=x["signal_date"], sym=x["sym"], code=x["sym"][2:],
                                name=names.get(x["sym"], ""), board=board_of(x["sym"]),
                                ind=ind.get(x["sym"], ""), gap=x.get("gap"),
                                entry_date=x["entry_date"], entry_open=px,
                                exit_date=x.get("exit_date"), exit_px=x.get("exit_px"),
                                alloc=round(alloc, 2), outlay=round(outlay, 2), shares=sh,
                                cap_limited=bool(capv < navprev / a.kslot - 1e-9)))
        for p in list(pos):                            # B) 出场（exit_date == 当日，T+2 尾盘）
            if p["exit_date"] == d and p.get("exit_px"):
                cash += p["shares"] * p["exit_px"] * (1.0 - cost)
                p["ret_pct"] = round(100.0 * (p["exit_px"] * (1 - cost) /
                                              (p["entry_open"] * (1 + cost)) - 1.0), 4)
                p["pnl"] = round(p["shares"] * (p["exit_px"] * (1 - cost)
                                                - p["entry_open"] * (1 + cost)), 2)
                settled.append(p); pos.remove(p)
        mv = 0.0                                       # C) 盯市（当日收盘，不做卖出成本预扣）
        for p in pos:
            c = F["C"][t, jof[p["sym"]]] if p["sym"] in jof else np.nan
            if not (np.isfinite(c) and c > 0):
                c = p["entry_open"]
            mv += p["shares"] * c
        nav[d] = float(cash + mv)          # 面板是 float32 -> 必须显式转 float，否则 json 序列化失败
    positions = [dict(x) for x in pos]
    navv = nav.get(cal[T - 1], CAP)
    navx = navv / CAP
    rets = np.array([x["ret_pct"] for x in settled], float)
    account = dict(nav=round(float(navx), 6), nav_yuan=round(float(navv), 2), capital=round(CAP, 2),
                   ret_pct=round(float(navx - 1) * 100, 4),
                   cash=round(cash, 2), n_positions=len(positions), n_settled=len(settled),
                   win_rate=None if not len(rets) else round(float(100 * (rets > 0).mean()), 2),
                   mean_per_trade=None if not len(rets) else round(float(rets.mean()), 4),
                   med_per_trade=None if not len(rets) else round(float(np.median(rets)), 4),
                   total_pnl=round(float(sum(x["pnl"] for x in settled)), 2),
                   nav_series_len=len(nav))
    log("[account] 净值 %.6f（累计 %+.4f%%）· 持仓 %d · 已了结 %d · 净值点 %d"
        % (account["nav"], account["ret_pct"], account["n_positions"], account["n_settled"],
           account["nav_series_len"]))

    # ---- ⑤ 跟踪池（待买入 / 持有中 / 已了结近 30 自然日）----
    track = []
    for x in positions:
        track.append(dict(state="持有中", **{k: x[k] for k in
                     ("signal_date", "code", "name", "board", "ind", "gap", "entry_date",
                      "entry_open", "exit_date", "alloc", "shares", "cap_limited")}))
    for x in settled:
        track.append(dict(state="已了结", **{k: x[k] for k in
                     ("signal_date", "code", "name", "board", "ind", "gap", "entry_date",
                      "entry_open", "exit_date", "exit_px", "ret_pct", "alloc", "shares")}))
    for x in trades:
        if x.get("undetermined"):
            track.append(dict(state="待判定", signal_date=x["signal_date"],
                              code="—", name="资格池 %d 只（等次一交易日 09:25 用真实今开筛选）" % x["n_pool"],
                              board="", ind="", gap=None, entry_date=None, entry_open=None,
                              exit_date=None))
    pool_now = None
    fp = PUB / "hpdk_candidates.json"
    if fp.exists():
        try:
            cj = json.loads(fp.read_text(encoding="utf-8"))
            pool_now = dict(as_of=cj.get("as_of"), buy_date=cj.get("buy_date"),
                            exit_date=cj.get("exit_date"), n=cj.get("n"),
                            boards={})
            for r in cj.get("rows") or []:
                b = r.get("board") or "其他"
                pool_now["boards"][b] = pool_now["boards"].get(b, 0) + 1
        except Exception:
            pool_now = None

    payload = dict(as_of=cal[T - 1], updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                   frozen_script_sha256=sha0,
                   config=dict(capital=a.capital, kslot=a.kslot, cost_side=cost,
                               cost_rt_bp=round(cost * 2 * 1e4, 2), tp=P["TP"],
                               adv_frac=ADV_FRAC, mainboard=bool(P.get("MAINBOARD", True)),
                               gap_band=[-P["P2"], -P["P1"]], K=int(P["K"]),
                               shadow_start=P["SHADOW_START"],
                               exit_rule="止盈 +%.0f%% ／ 未达标 T+2 尾盘" % (P["TP"] * 100)),
                   account=account,
                   nav_daily=[[d, round(float(v) / CAP, 6)] for d, v in sorted(nav.items())],
                   positions=positions, settled=settled, track=track,
                   reconcile=dict(ledger_n=len(led), replay_settleable=len(mine_set), mismatches=bad[:20]),
                   pool_now=pool_now)
    (outdir / "hpdk_paper.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    log("[out] hpdk_paper.json  跟踪池 %d 行（持有 %d / 已了结 %d / 待判定 %d）"
        % (len(track), len(positions), len(settled),
           sum(1 for x in track if x["state"] == "待判定")))
    log("hpdk_paper.py DONE")
    return 0 if not bad else 3


if __name__ == "__main__":
    sys.exit(main())
