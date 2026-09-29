# -*- coding: utf-8 -*-
"""hpdk_candidates.py — 生成「横盘低开·两日」看板所需的当日候选数据（日链 [软] 步）。

口径纪律（本项目已有 9 次口径翻车记录）：
  信号逻辑 **100% 复用冻结脚本 oos_run.py** —— import 该模块，把 STATE_F/TRADES_F/REPORT_F
  重定向到临时目录，只改**运行期**的 P 字典，调用其 main() 重放；**脚本文件字节零修改，SHA256 不变**。
  两次重放（同一代码路径，不存在第二套实现）：
    ① 冻结参数                 → 实际候选集（每日按复合分降序前 10），用于 **A11 对拍**；
    ② P1=-1.0 / P2=+10.0       → 「资格池」= 当日通过 elig 的全部标的（低开带放宽到不约束）。
       资格池用来看板盘前展示 + 给浏览器端盘中 z 标准化提供全体候选。
  特征值（AMT20 / VOLBR / RET20）从**同一面板**按 oos_run 内的公式复算（逐行同式），
  并由 ① 的 top-10 对拍反向验证：若复算口径漂移，对拍必然失败 → 脚本非零退出。

产出（供看板只读）：
  · backtest/hpdk_candidates.json —— 当日信号日的资格池 + 参数 + 明日买点区间 + 建议股数
  · backtest/hpdk_oos_view.json   —— 冻结 OOS 台账的只读投影（进度 / 四闸 / 已完成笔数）

用法:
  python hpdk_candidates.py [--cache DIR] [--capital 1000000] [--kslot 4] [--check-days 25]
                            [--outdir DIR]
"""
import os, sys, json, math, argparse, pathlib, importlib.util, time, tempfile
import numpy as np
import pandas as pd

R = pathlib.Path(__file__).resolve().parents[2]
OUT = R / "backtest/hengpan_fangliang_dikai_0925"
PUB = R / "backtest"          # 看板读取路径（build_dual_system/hpdk_card.py 与日链白名单都用这一处）
OOS = OUT / "oos_run.py"
CAP_DEFAULT, KSLOT_DEFAULT = 1_000_000.0, 4          # 用户 2026-09-27 拍定：100 万 / KSLOT=4
ADV_FRAC = 0.01                                      # 单票上限 = 该股 ADV × 1%
WIDE_P1, WIDE_P2 = -1.0, 10.0                        # 放宽低开带 → 取出整天资格池


def log(*a):
    print(*a, flush=True)


def load_mod():
    spec = importlib.util.spec_from_file_location("oos_run_cand", OOS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get_panel(mod, cache):
    cal, live, dead = mod.load_universe()
    syms = live + dead
    key = "%s_%d_%d" % (cal[-1], len(cal), len(syms))
    f = cache / ("hpdk_panel_%s.npz" % abs(hash(key)))
    if f.exists():
        z = np.load(f, allow_pickle=True)
        if list(z["cal"]) == cal and list(z["syms"]) == syms:
            log("[panel] 缓存命中 %s" % f.name)
            return cal, syms, {k: z[k] for k in ("O", "H", "L", "C", "V", "A")}
    t0 = time.time()
    F, done = mod.build(cal, syms)
    log("[panel] 重建 T=%d N=%d done=%d（%.1fs）"
        % (F["C"].shape[0], F["C"].shape[1], done, time.time() - t0))
    np.savez_compressed(f, cal=np.array(cal, dtype=object), syms=np.array(syms, dtype=object),
                        **{k: v.astype(np.float32) for k, v in F.items()})
    return cal, syms, F


def replay(mod, cache, tag, overrides, F, done, start="2016-01-01"):
    mod.P["SHADOW_START"] = start
    mod.P.update(overrides)
    mod.STATE_F = cache / ("_c_%s_state.json" % tag)
    mod.TRADES_F = cache / ("_c_%s_trades.jsonl" % tag)
    mod.REPORT_F = cache / ("_c_%s_report.json" % tag)
    for p in (mod.STATE_F, mod.TRADES_F, mod.REPORT_F):
        if p.exists():
            p.unlink()
    mod.build = lambda _c, _s: (F, done)
    mod.main()
    return [json.loads(x) for x in mod.TRADES_F.read_text(encoding="utf-8").splitlines() if x.strip()]


def features(F, P):
    """与 oos_run.py 内逐行同式的特征复算（仅供展示与浏览器端 z 标准化；不参与信号判定）。"""
    O, C, V, A = F["O"], F["C"], F["V"], F["A"]
    VALID = (C > 0) & np.isfinite(C) & (O > 0)
    Av = np.where(VALID, A, np.nan)
    Vv = np.where(VALID, V, np.nan)
    AMT20 = pd.DataFrame(Av).rolling(20, min_periods=10).mean().to_numpy(dtype=np.float64)
    VMA20 = pd.DataFrame(Vv).rolling(20, min_periods=10).mean().to_numpy(dtype=np.float64)
    VMA20p = np.full_like(VMA20, np.nan); VMA20p[1:] = VMA20[:-1]
    VOLBR = V / np.where(VMA20p > 0, VMA20p, np.nan)
    Cv = np.where(VALID, C, np.nan)
    RET20 = np.full(C.shape, np.nan); RET20[20:] = Cv[20:] / Cv[:-20] - 1.0
    GAP = np.full(C.shape, np.nan); GAP[:-1] = O[1:] / np.where(C[:-1] > 0, C[:-1], np.nan) - 1.0
    return dict(AMT20=AMT20, VOLBR=VOLBR, RET20=RET20, GAP=GAP, VALID=VALID)


def zs(x):
    x = np.asarray(x, float); mu = np.nanmean(x); sd = np.nanstd(x)
    return (x - mu) / sd if np.isfinite(sd) and sd > 0 else np.zeros_like(x)

def next_trade_days(after, n=2):
    """返回 after 之后的 n 个交易日。优先级：
      ① **仓库内置日历** trade_cal_sina.csv（由 gen_trade_cal.py 从 akshare 生成，含未来日期）
         —— 离线可用；云端不依赖联网即可跨过中秋/国庆等休市窗口；
      ② akshare 权威日历（内置文件过期时兜底）；
      ③ 「跳周末」近似（并把 fallback 标记写进产物供看板披露）。
    2026-09-27 加固原因：原实现只靠 ②，云端一旦取不到就会把 2026-09-24 的次一交易日算成
    09-25（实为中秋休市），买日/了结日全错。"""
    _f = R / "trade_cal_sina.csv"
    if _f.exists():
        try:
            _ds = [ln.split(",")[0].strip() for ln in
                   _f.read_text(encoding="utf-8-sig").splitlines()[1:] if ln.strip()]
            _ds = [d for d in _ds if len(d) >= 10]
            _nxt = [d for d in _ds if d > after][:n]
            if len(_nxt) == n:
                return _nxt, False
            log("[warn] 内置日历不含 %s 之后 %d 个交易日（文件过期？跑 gen_trade_cal.py 刷新）" % (after, n))
        except Exception as e:
            log("[warn] 内置交易日历读失败：%r" % (e,))
    try:
        import akshare as ak
        t = ak.tool_trade_date_hist_sina()
        ds = sorted(str(x) for x in t["trade_date"].astype(str).tolist())
        nxt = [d for d in ds if d > after][:n]
        if len(nxt) == n:
            return nxt, False
    except Exception as e:
        log("[warn] 权威交易日历取失败：%r" % (e,))
    import datetime as _dt
    out, d = [], _dt.date.fromisoformat(after)
    while len(out) < n:
        d += _dt.timedelta(days=1)
        if d.weekday() < 5:
            out.append(d.isoformat())
    return out, True



def board_of(sym):
    p, n = sym[:2], sym[2:]
    if p == "sh" and n[:3] in ("600", "601", "603", "605"): return "主板"
    if p == "sz" and n[:3] in ("000", "001", "002", "003"): return "主板"
    if p == "sz" and n[:3] in ("300", "301", "302"): return "创业板"
    if p == "sh" and n[:3] == "688": return "科创板"
    return "其他"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.environ.get("PI_SCRATCH_DIR")
                                         or os.path.join(tempfile.gettempdir(), "hpdk_cache"))
    ap.add_argument("--capital", type=float, default=CAP_DEFAULT)
    ap.add_argument("--kslot", type=int, default=KSLOT_DEFAULT)
    ap.add_argument("--check-days", type=int, default=25)
    ap.add_argument("--outdir", default=None)
    a = ap.parse_args()
    cache = pathlib.Path(a.cache); cache.mkdir(parents=True, exist_ok=True)
    outdir = pathlib.Path(a.outdir) if a.outdir else PUB
    outdir.mkdir(parents=True, exist_ok=True)

    mod = load_mod()
    sha0 = mod.FROZEN_SHA
    cal, syms, F = get_panel(mod, cache)
    assert mod.FROZEN_SHA == sha0, "冻结脚本 SHA 被改动！"
    T, N = F["C"].shape
    jof = {s: j for j, s in enumerate(syms)}
    names = json.loads((R / "data_full_names.json").read_text(encoding="utf-8"))
    ind = {u["sym"]: u.get("ind", "") for u in
           json.loads((R / "backtest/wechat_hotspot_leader_0925/universe.json")
                      .read_text(encoding="utf-8"))["universe"]}

    # ---------- ① 冻结参数重放（对拍基准） ----------
    log("[replay] 冻结参数…")
    # 面板尾部追加 2 个占位交易日：冻结脚本的「待了结」保护会吞掉末尾两个信号日，
    # 而看板要的正是「最新信号日」的资格池。占位行价格置 1.0，**只影响占位日自身**：
    # 所有滚动/累计量（AMT20 / VMA20_prev / NV / STP）都是尾部窗口，不会污染任何真实交易日。
    # 占位日不参与任何统计；A11 对拍仍只比对真实交易日。
    cal2 = list(cal) + ["2099-01-01", "2099-01-02"]
    F2 = {k: np.concatenate([v, np.ones((2, v.shape[1]), dtype=v.dtype)], axis=0)
          for k, v in F.items()}
    _lu = mod.load_universe
    mod.load_universe = lambda: (cal2, syms[:len(syms)], [])      # live 全给；dead 已含在 syms 里
    _orig_build = mod.build
    frozen = replay(mod, cache, "frozen", {}, F2, N, start="2016-01-01")
    wide = replay(mod, cache, "wide", {"P1": WIDE_P1, "P2": WIDE_P2, "K": 10 ** 9},
                  F2, N, start="2016-01-01")
    mod.load_universe = _lu
    T2 = F2["C"].shape[0]
    FZ = dict(P1=0.01, P2=0.03, K=10, KSLOT=20, MINAMT=2e7, MINPX=3.0, LISTED=250, TP=0.02,
              COST_SIDE=0.000346)
    ft = features(F2, FZ)

    # ---------- A11 对拍：我的复算是否能逐位重建冻结重放的 top-10 ----------
    by_day_f = {}
    for r in frozen:
        by_day_f.setdefault(r["signal_date"], []).append(r["sym"])
    by_day_w = {}
    for r in wide:
        by_day_w.setdefault(r["signal_date"], []).append(r["sym"])
    days = sorted(by_day_f)[-a.check_days:]
    n_ok = n_cmp = 0
    mism = []
    for d in days:
        i = cal.index(d)
        g = ft["GAP"][i]
        cand = [s for s in by_day_w.get(d, []) if np.isfinite(g[jof[s]]) and -0.03 <= g[jof[s]] <= -0.01]
        if not cand:
            continue
        n_cmp += 1
        amt = np.array([ft["AMT20"][i, jof[s]] for s in cand])
        vbr = np.array([ft["VOLBR"][i, jof[s]] for s in cand])
        r20 = np.array([ft["RET20"][i, jof[s]] for s in cand])
        comp = zs(-np.log(amt)) + zs(-np.log(vbr)) + zs(-r20)
        mine = [cand[q] for q in np.argsort(-comp)[:10]]
        theirs = by_day_f[d][:10]
        if mine == theirs:
            n_ok += 1
        else:
            mism.append(dict(day=d, mine=mine, theirs=theirs))
    log("[A11 对拍] 逐位相等 %d / %d 天" % (n_ok, n_cmp))
    if mism or n_ok < n_cmp or n_cmp < 20:
        print(json.dumps(dict(n_ok=n_ok, n_cmp=n_cmp, mism=mism[:3]), ensure_ascii=False, indent=1))
        log("!! A11 对拍失败 → 口径漂移，拒绝产出候选。")
        sys.exit(2)

    # ---------- 当日候选（供看板） ----------
    T_last = cal[-1]
    i = T - 1
    pool = sorted(by_day_w.get(T_last, []))
    rows = []
    for s in pool:
        j = jof[s]
        row = dict(sym=s, code=s[2:], name=names.get(s, ""), ind=ind.get(s, ""),
                   board=board_of(s), close=round(float(F["C"][i, j]), 3),
                   amt20=round(float(ft["AMT20"][i, j]), 1) if np.isfinite(ft["AMT20"][i, j]) else None,
                   volbr=round(float(ft["VOLBR"][i, j]), 4) if np.isfinite(ft["VOLBR"][i, j]) else None,
                   ret20=round(float(ft["RET20"][i, j]), 6) if np.isfinite(ft["RET20"][i, j]) else None)
        c = row["close"]
        row["buy_lo"] = round(c * (1 - 0.03), 3)      # gap = −3% → 买入价下界
        row["buy_hi"] = round(c * (1 - 0.01), 3)      # gap = −1% → 买入价上界
        row["tp_lo"] = round(row["buy_lo"] * 1.02, 3)  # 止盈 = 买入价×1.02
        row["tp_hi"] = round(row["buy_hi"] * 1.02, 3)
        cap = (row["amt20"] or 0.0) * ADV_FRAC
        rows.append(row)
    # KSLOT 口径下的分配（操作档）：取前 KSLOT 只在最坏价格（buy_lo）下算股数
    rows.sort(key=lambda r: (r["amt20"] if r["amt20"] is not None else 1e30))
    alloc = min(a.capital / max(1, a.kslot), a.capital)
    for k, r in enumerate(rows):
        px = r["buy_lo"] or 0.0
        cap = (r["amt20"] or 0.0) * ADV_FRAC
        a_use = min(alloc, cap) if cap > 0 else 0.0
        r["cap_single"] = round(cap, 0)
        r["order_size"] = int(math.floor(a_use / px / 100.0) * 100) if px > 0 else 0
        r["cap_ok"] = bool(cap >= alloc)              # 是否触及 ADV×1% 容量上限
    # 交易日历：下一交易日 = 买日，再下一日 = 了结日
    nxt, fb = next_trade_days(T_last, 2)
    buy_date, exit_date = (nxt + [None, None])[:2]

    out = dict(as_of=T_last, buy_date=buy_date, exit_date=exit_date, calendar_fallback=fb,
               frozen_sha256=sha0, params=FZ,
               gap_band=[-0.03, -0.01], gap_band_pct="−3% ~ −1%",
               capacity=dict(capital=a.capital, kslot=a.kslot, adv_frac=ADV_FRAC,
                             account_cap_note="单票上限 = 该股 ADV×1%；KSLOT=4 ⇒ 账户上限 ≈101 万"),
               a11_check=dict(days_compared=n_cmp, days_bitwise_equal=n_ok),
               n=len(rows), rows=rows)
    (outdir / "hpdk_candidates.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
    log("[out] hpdk_candidates.json  as_of=%s buy=%s exit=%s n=%d（前 10 示例：%s）"
        % (T_last, buy_date, exit_date, len(rows),
           "、".join("%s %s" % (r["code"], r["name"]) for r in rows[:10])))

    # ---------- 今日命中（收盘链全池复算 · R-hpdk-hits-0928）----------
    # 为什么要有这一步：原设计的「命中」只活在**浏览器端**（09:25 用真实今开判定），且
    #   ① 只在渲染的 RENDER_N=600 行内做 F 排名 → **系统性少报**（2026-09-28 实测：全池真命中
    #      147 只，前端只显示 3 只，F 第 2 名落在第 601 行之后被截掉）；
    #   ② 记录只存 localStorage 且**按 HPDK.as_of 作废** → 信号日一推进，当天命中即消失；
    #   ③ 零落盘（ADR-0009）→ 服务端无档可查。
    # 但**收盘后**「上一信号日池 × 当日今开带」是**静态可复算**的（ADR-0009 反对的是盘中实时
    # 判定需常驻进程，不适用于收盘复算）⇒ 本步复算并落盘，供看板常驻显示与历史回看。
    # 口径与 A11 对拍、前端 judge 逐条一致：命中 = 上一信号日 wide 池 ∩ gap∈[-3%,-1%]
    # ∩ B 闸（可交易，剔停牌/一字）∩ F 闸（量比与 20 日涨幅可算），按 F 降序取前 K 只标注。
    hits = dict(date=T_last, signal_date=None, n_pool=0, n_hits=0, k=FZ["K"],
                gap_band=[-0.03, -0.01], frozen_sha256=sha0,
                rule=("命中 = 上一信号日 wide 池 ∩ 当日开盘跳空 gap∈[-3%,-1%] ∩ 可交易"
                      "（非停牌/一字）∩ 量比与 20 日涨幅可算；F 复合分在命中子集内横截面 z 标准化，"
                      "降序取前 K 只标注为当日买入候选"),
                rows=[], top=[])
    if len(cal) >= 2:
        S = cal[-2]                       # 上一交易日 = 本买日的信号日
        iS = cal.index(S)
        pool_s = sorted(by_day_w.get(S, []))
        gS = ft["GAP"][iS]
        cand = []
        for s in pool_s:
            j = jof[s]
            gg = gS[j]
            oD, cD, cS = F2["O"][iS + 1, j], F2["C"][iS + 1, j], F2["C"][iS, j]
            a20, vbr, r20 = ft["AMT20"][iS, j], ft["VOLBR"][iS, j], ft["RET20"][iS, j]
            if not (np.isfinite(gg) and -0.03 <= gg <= -0.01):
                continue
            if not (np.isfinite(oD) and oD > 0 and np.isfinite(cS) and cS > 0):
                continue
            if abs(oD - cD) < 1e-9 and abs(oD - cS) < 1e-9:       # B 闸：停牌/一字
                continue
            if not (np.isfinite(a20) and a20 > 0 and np.isfinite(vbr) and vbr > 0
                    and np.isfinite(r20)):                         # F 闸
                continue
            cand.append((s, float(gg), float(a20), float(vbr), float(r20)))
        if cand:
            _amt = np.array([c[2] for c in cand])
            _vbr = np.array([c[3] for c in cand])
            _r20 = np.array([c[4] for c in cand])
            _comp = zs(-np.log(_amt)) + zs(-np.log(_vbr)) + zs(-_r20)
            order = np.argsort(-_comp)
            # 2026-09-28（R-hpdk-ind-0928）：命中清单加**行业 + 同行业序** ——
            # 用户 09-28 实际操作口径是「同行业只买 1 只」（人工去重），但冻结判据里没有行业约束
            # （改判据属预注册变更，须走勘误）。行业集中度实测：146 只命中里有色金属 34 只（23%），
            # F 前 10 里占 5 席 ⇒ 去重信息必须可见，故只做**显示层**（不改选股、不改排名）。
            _rows, _indseq = [], {}
            for r, q in enumerate(order):
                sym = cand[q][0]
                gi = ind.get(sym, "") or "—"
                _indseq[gi] = _indseq.get(gi, 0) + 1
                _rows.append(dict(rank=int(r + 1), code=sym[2:], sym=sym,
                                  name=names.get(sym, ""), ind=gi, ind_seq=_indseq[gi],
                                  gap_pct=round(cand[q][1] * 100, 3),
                                  F=round(float(_comp[q]), 4), volbr=round(cand[q][3], 3),
                                  ret20_pct=round(cand[q][4] * 100, 2)))
            hits["rows"] = _rows
            hits["top"] = _rows[:FZ["K"]]
            hits["ind_counts"] = dict(sorted(_indseq.items(), key=lambda kv: -kv[1]))
            # 「同行业只取 1 只」口径下的前 K（显示层参考，不改策略）
            _ded, _seen = [], set()
            for x in _rows:
                if x["ind"] in _seen:
                    continue
                _seen.add(x["ind"])
                _ded.append(x)
                if len(_ded) >= FZ["K"]:
                    break
            hits["top_dedup_ind"] = [x["code"] for x in _ded]
        hits["signal_date"] = S
        hits["n_pool"] = len(pool_s)
        hits["n_hits"] = len(hits["rows"])
    (outdir / "hpdk_hits.json").write_text(json.dumps(hits, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    log("[out] hpdk_hits.json  买日=%s 信号日=%s 资格池=%d 命中=%d（F 前 3：%s）"
        % (hits["date"], hits["signal_date"], hits["n_pool"], hits["n_hits"],
           "、".join("%s %s" % (x["code"], x["name"]) for x in hits["top"][:3])))
    # ---------- 命中历史留档（R-hpdk-hits-0928）----------
    # 2026-09-28 的教训：命中记录当时只在浏览器 localStorage、且按 as_of 作废 ⇒ **事后无从回看**
    # （用户傍晚再看只剩 3 只候选，无法证明早上是 4 只）。此档一行一日、体积可忽略。
    # 2026-09-29 code review 修正：原为「该日已存在则跳过」⇒ 同一买日被重算（数据修订/补跑）时
    #   档案会停在**首算**版本（陈旧）。改为**就地覆盖该日**（其余日期原样保留、顺序不变）。
    _hist = outdir / "hpdk_hits_history.jsonl"
    _rec = dict(date=hits["date"], signal_date=hits["signal_date"], n_pool=hits["n_pool"],
                n_hits=hits["n_hits"], k=hits["k"],
                top=[x["code"] for x in hits["top"]],
                rows=[dict(code=x["code"], name=x["name"], ind=x.get("ind", ""),
                           gap_pct=x["gap_pct"], F=x["F"]) for x in hits["rows"]])
    _old = []
    if _hist.exists():
        _old = [json.loads(l) for l in _hist.read_text(encoding="utf-8").splitlines() if l.strip()]
    _idx = next((i for i, r in enumerate(_old) if r.get("date") == hits["date"]), None)
    if _idx is None:
        _old.append(_rec)
        _verb = "追加"
    else:
        _same = json.dumps(_old[_idx], ensure_ascii=False, sort_keys=True) == \
                json.dumps(_rec, ensure_ascii=False, sort_keys=True)
        _old[_idx] = _rec
        _verb = "无变化" if _same else "就地覆盖（该买日被重算）"
    _hist.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in _old) + "\n",
                     encoding="utf-8")
    log("[out] hpdk_hits_history.jsonl %s %s（累计 %d 天）" % (_verb, hits["date"], len(_old)))
    # ---------- OOS 台账只读投影 ----------
    st = json.loads((OUT / "oos_state.json").read_text(encoding="utf-8")) if (OUT / "oos_state.json").exists() else {}
    rp = json.loads((OUT / "oos_report.json").read_text(encoding="utf-8")) if (OUT / "oos_report.json").exists() else {}
    tr = []
    if (OUT / "oos_trades.jsonl").exists():
        tr = [json.loads(x) for x in (OUT / "oos_trades.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    view = dict(script_sha256=st.get("frozen_script_sha256") or sha0,
                shadow_start=st.get("shadow_start"), last_scan_date=st.get("last_scan_date"),
                n_settled=st.get("n_settled"), n_pending=st.get("n_pending"),
                acceptance=rp.get("acceptance"), acceptance_close_only=rp.get("acceptance_close_only"),
                gates=rp.get("gates"), exec_dev_pct=rp.get("exec_dev_pct"),
                tp_hit_pct=rp.get("tp_hit_pct"), verdict=rp.get("verdict"),
                exit_rule=rp.get("exit_rule"),
                last=[dict(signal_date=x["signal_date"], sym=x["sym"], code=x["sym"][2:],
                           name=names.get(x["sym"], ""), gap_pct=x.get("gap_pct"),
                           entry_date=x.get("entry_date"), entry_open=x.get("entry_open"),
                           exit_date=x.get("exit_date"), exit_px=x.get("exit_px"),
                           tp_hit=x.get("tp_hit"), ret_pct=x.get("ret_pct"),
                           ret_pct_close=x.get("ret_pct_close"),
                           real_fill_px=x.get("real_fill_px"), order_size=x.get("order_size"))
                      for x in tr[-40:]])
    (outdir / "hpdk_oos_view.json").write_text(json.dumps(view, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    log("[out] hpdk_oos_view.json  settled=%s pending=%s verdict=%s"
        % (view["n_settled"], view["n_pending"], view["verdict"]))
    log("hpdk_candidates.py DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
