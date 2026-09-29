# -*- coding: utf-8 -*-
"""oos_run.py — 前向 OOS 运行器（自包含：只读 data_full + delisted_bars，不依赖任何临时目录）
规则已于 PRE-REGISTRATION_20260926_hengpan_dikai_oos.md 冻结；本脚本不得修改判据。
用法: python oos_run.py            (自动追赶到最新可用数据)
"""
import json, hashlib, pathlib, sys, datetime, numpy as np, pandas as pd
R = pathlib.Path(__file__).resolve().parents[2]
OUT = R/"backtest/hengpan_fangliang_dikai_0925"
UNI = R/"backtest/wechat_hotspot_leader_0925/universe.json"
DEAD = R/"backtest/_delisted_universe/delisted_bars.csv.gz"
STATE_F = OUT/"oos_state.json"; TRADES_F = OUT/"oos_trades.jsonl"; REPORT_F = OUT/"oos_report.json"
# ---- 冻结参数（不得修改）----
P = dict(P1=0.01, P2=0.03, K=10, KSLOT=20, MINAMT=2e7, MINPX=3.0, LISTED=250, TP=0.02,
          COST_SIDE=0.000346, SHADOW_START="2026-09-25", WORST_CASE_WIPEOUT=True,
          # ---- ST 筛子（2026-09-29 · 勘误 E-22 · 用户批准 A+C）----
          # STP_CNT=3        → A：代理需「250 日内 |日收益|≥4.8% 的天数 ≥3」；设 0 = 关掉 A
          # STNOW_LIVE_ONLY  → C：现名过滤只作用于在售票（退市票豁免）；设 False = 复原 v1.5 全量剔
          # STNOW_OFF=True   → 完全不使用现名过滤（E-19 行为）；保留供审计复现
          STP_CNT=3, STNOW_LIVE_ONLY=True,
          STNOW_OFF=False)
FROZEN_SHA = hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
def log(*a): print(*a, flush=True)
def load_universe():
    U = json.loads(UNI.read_text(encoding="utf-8"))
    cal = list(U["calendar"]); live = [u["sym"] for u in U["universe"]]
    dead = []
    if DEAD.exists():
        b = pd.read_csv(DEAD); dead = sorted(b["sym"].unique().tolist())
    return cal, live, dead
def build(cal, syms):
    T = len(cal); N = len(syms); lut = {d:i for i,d in enumerate(cal)}
    F = {k: np.zeros((T,N), dtype=np.float32) for k in ("O","H","L","C","V","A")}
    live_set = set(syms)
    dead_map = {}
    if DEAD.exists():
        b = pd.read_csv(DEAD)
        b = b[b["sym"].isin(live_set)]
        dead_map = {s: g for s, g in b.groupby("sym")}
    done = 0
    for j, s in enumerate(syms):
        if s in dead_map:
            df = dead_map[s].copy()
            df["date"] = df["date"].astype(str)
        else:
            p = R/"data_full"/(s+".csv")
            if not p.exists(): continue
            try: df = pd.read_csv(p)
            except Exception: continue
            df["date"] = df["date"].astype(str).str.slice(0,10)
        ri = np.array([lut.get(d,-1) for d in df["date"]], dtype=np.int64)
        keep = ri >= 0
        ri = ri[keep]
        for nm, col in (("O","open"),("H","high"),("L","low"),("C","close"),("V","volume"),("A","amount")):
            if col in df.columns:
                F[nm][ri, j] = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=np.float64)[keep]
        done += 1
    return F, done
def main():
    cal, live, dead = load_universe()
    syms = live + dead
    log("universe: live=%d dead=%d total=%d ; calendar %s..%s" % (len(live), len(dead), len(syms), cal[0], cal[-1]))
    F, done = build(cal, syms)
    T, N = F["C"].shape
    O, H, C, V, A = F["O"], F["H"], F["C"], F["V"], F["A"]
    VALID = (C > 0) & np.isfinite(C) & (O > 0)
    Cv = np.where(VALID, C, np.nan); Vv = np.where(VALID, V, np.nan); Av = np.where(VALID, A, np.nan)
    AMT20 = pd.DataFrame(Av).rolling(20, min_periods=10).mean().to_numpy(dtype=np.float32)
    VMA20 = pd.DataFrame(Vv).rolling(20, min_periods=10).mean().to_numpy(dtype=np.float32)
    VMA20_prev = np.full_like(VMA20, np.nan); VMA20_prev[1:] = VMA20[:-1]   # 只用 <=T-1 的均量（与预注册 / 样本内一致）
    VOLBR = V / np.where(VMA20_prev > 0, VMA20_prev, np.nan)
    RET20 = np.full((T,N), np.nan, dtype=np.float32); RET20[20:] = Cv[20:]/Cv[:-20] - 1.0
    NV = np.cumsum(VALID, axis=0).astype(np.int32)
    GAP = np.full((T,N), np.nan, dtype=np.float32); GAP[:-1] = O[1:]/np.where(C[:-1] > 0, C[:-1], np.nan) - 1.0
    GAP = GAP.astype(np.float32)

    # ---- 研究用因子：盈亏比 RR = 止盈距离 / ATR20%（2026-09-27, 见 E-13）----
    # ATR20% = mean(TR)/close，TR = max(H−L, |H−C_prev|, |L−C_prev|)；仅当 P["RR_MIN"]>0 时参与筛选
    _L = F["L"]        # main() 只解包了 O/H/C/V/A，low 要单独取（2026-09-27 自查修复）
    _Cp = np.full((T, N), np.nan, dtype=np.float32); _Cp[1:] = C[:-1]
    _tr = np.maximum(H - _L, np.maximum(np.abs(H - _Cp), np.abs(_L - _Cp)))
    _ATR20 = pd.DataFrame(np.where(VALID, _tr, np.nan)).rolling(20, min_periods=10).mean().to_numpy(np.float32)
    _ATRp = _ATR20 / np.where(C > 0, C, np.nan)
    RR = (P["TP"] / np.where(_ATRp > 0, _ATRp, np.nan)).astype(np.float32)

    lut = {d: i for i, d in enumerate(cal)}
    # ===== 过滤件（2026-09-26 用户要求，预注册 E-6）: 剔ST/*ST + 股价>=3元 + 每股净资产>=3元 =====
    _NAMES = json.loads((R/"data_full_names.json").read_text(encoding="utf-8"))
    STNOW = np.array([(("ST" in (_NAMES.get(_s,"") or "").upper()) or ("退" in (_NAMES.get(_s,"") or "")))
                      for _s in syms], dtype=bool)
    # 【勘误 E-22 · C】退市票掩码：现名过滤 C 只作用于在售票，退市票豁免（保 E-19 的幸存者修正）
    _Cv = np.where(VALID, C, np.nan)          # 有效收盘（供 _r1 / 过滤件使用）
    _DEAD = np.array([s_ in set(dead) for s_ in syms], dtype=bool)
    _r1 = np.full((T, N), np.nan, dtype=np.float32); _r1[1:] = _Cv[1:]/_Cv[:-1] - 1.0
    _MX = pd.DataFrame(np.abs(_r1)).rolling(250, min_periods=60).max().to_numpy(dtype=np.float32)
    # 【勘误 E-22 · A（2026-09-29 用户批准）】代理加第二条件：窗口内 |日收益| ≥4.8% 的天数 ≥ STP_CNT。
    # 依据（E-21 实测）：只看「最大绝对日收益 ≤5.6%」会把**安静的正常股**误判成 ST ——
    # 基准日 2026-09-28 判 ST 128 只、真 ST 仅 6 只（误杀率 2.46%）；加本条件后降到 0.26% 且召回不变
    # （点时代理、无前视）。真 ST 票在 250 日内几乎必然出现 ≥4.8% 的日波动。
    _CNT = pd.DataFrame((np.abs(_r1) >= 0.048).astype(np.float32)).rolling(250, min_periods=60).sum().to_numpy(dtype=np.float32)
    _NEED = int(P.get("STP_CNT", 3))
    STP = (np.isfinite(_MX) & (_MX <= 0.056) & (_CNT >= _NEED)) if _NEED > 0 else (np.isfinite(_MX) & (_MX <= 0.056))
    BPSA = np.full((T, N), np.nan, dtype=np.float32)
    _bp = pd.read_csv(R/"backtest/_fundamentals/bps_quarterly.csv.gz")
    _bp["report_date"] = pd.to_datetime(_bp["report_date"], errors="coerce")
    _bp = _bp[_bp["report_date"].notna()]
    _bp["usable_from"] = (_bp["report_date"] + pd.DateOffset(months=4)).dt.strftime("%Y-%m-%d")
    _c2i = {s_: i for i, s_ in enumerate(syms)}
    for _s, _g in _bp.groupby("sym"):
        _j = _c2i.get(_s)
        if _j is None: continue
        _g = _g.sort_values("usable_from")
        _idx = np.array([lut.get(d, -1) for d in _g["usable_from"]], dtype=np.int64)
        _v = _g["bps"].to_numpy(dtype=np.float32); _ok = _idx >= 0; _idx = _idx[_ok]; _v = _v[_ok]
        if not _idx.size: continue
        _pos = np.searchsorted(_idx, np.arange(T), side="right") - 1; _gd = _pos >= 0
        BPSA[_gd, _j] = _v[_pos[_gd]]
    def FILT(t):
        """返回可交易掩码: 非ST **仅用点时（point-in-time）期内代理 STP** 且 股价>=3 且 每股净资产>=3(报告期+4个月后方可用)

        【勘误 E-19，2026-09-28 用户批准】
        原实现额外叠加 STNOW（按**当前名称**含 ST/退 一次性剔除全历史），有两个问题：
          ① 形式上是跨期信息：用「今天的名字」回溯十年历史（未来函数的一种，方向保守）；
          ② 实测把 253 只退市股整体剔除 228 只（90.1%）→ 使幸存者偏差修正失效。
        现改为只保留点时 STP；STNOW 仍计算（保留供审计与展示），但**不再参与筛选**。
        复现 v1.5 旧读数：P["STNOW_OFF"] = False（x2_sens 的 v15_stnow 臂即此）。
        """
        m = (~STP[t]) & (C[t] >= 3.0) & np.isfinite(BPSA[t]) & (BPSA[t] >= 3.0)
        if not P.get("STNOW_OFF", True):
            m = m & (~STNOW)                       # v1.5 旧行为（全量剔现名）：仅审计复现用
        elif P.get("STNOW_LIVE_ONLY", True):
            # 【勘误 E-22 · C（2026-09-29 用户批准）】现名过滤只作用于**在售票**；退市票豁免。
            # 依据：E-19 实测「全量剔现名」把 253 只退市股剔掉 228 只（90.1%）⇒ 幸存者修正失效；
            # 而近期才戴帽的在售票（002743 / *ST网达）必须剔 —— 代理对它们召回仅 ~3%（E-21 实测）。
            # 代价：重新引入「用今天的名字回溯历史」的跨期信息（方向保守）。
            m = m & ((~STNOW) | _DEAD)
        return m

    # ---- 板块掩码（2026-09-27 用户要求「只买主板，其他板块去掉」）----
    # 真主板 = sh600/601/603/605 + sz000/001/002/003
    #   （剔创业板 sz300/301/302、科创板 sh688；北交所 bj* 本就已在池外）
    _MB = np.array([(s_[:2] == "sh" and s_[2:5] in ("600", "601", "603", "605")) or
                    (s_[:2] == "sz" and s_[2:5] in ("000", "001", "002", "003"))
                    for s_ in syms], dtype=bool)
    _MBUSE = _MB if P.get("MAINBOARD", True) else np.ones(N, dtype=bool)

    def zs(x):
        x = np.asarray(x, float); mu = np.nanmean(x); sd = np.nanstd(x)
        return (x-mu)/sd if np.isfinite(sd) and sd > 0 else np.zeros_like(x)
    def elig(t):
        m = (VALID[t] & (NV[t] >= P["LISTED"]) & (C[t] >= P["MINPX"]) &
             np.isfinite(AMT20[t]) & (AMT20[t] >= P["MINAMT"]) & FILT(t) & _MBUSE)
        # ---- 研究用门槛：**默认值下完全不生效**（保证与 v1.4 逐位等价）----
        if P.get("VOLBR_MIN", 0.0) > 0:
            m = m & np.isfinite(VOLBR[t]) & (VOLBR[t] >= P["VOLBR_MIN"])
        if P.get("VOLBR_MAX", 1e9) < 1e8:
            m = m & np.isfinite(VOLBR[t]) & (VOLBR[t] <= P["VOLBR_MAX"])
        if P.get("RR_MIN", 0.0) > 0:
            m = m & np.isfinite(RR[t]) & (RR[t] >= P["RR_MIN"])
        return m
    def signal(t):
        b = elig(t); g = GAP[t]
        m = b & np.isfinite(g) & (g <= -P["P1"]) & (g >= -P["P2"]) & np.isfinite(RET20[t]) & np.isfinite(VOLBR[t])
        ix = np.nonzero(m)[0]
        if ix.size == 0: return []
        comp = zs(-np.log(AMT20[t][ix])) + zs(-np.log(VOLBR[t][ix])) + zs(-RET20[t][ix])
        k = min(P["K"], ix.size)
        return [[int(ix[q]), float(comp[q])] for q in np.argsort(-comp)[:k]]
    def _ret_of(entry, x):
        return -100.0 if x == 0 else (x*(1-P["COST_SIDE"])/(entry*(1+P["COST_SIDE"])) - 1)*100
    st = json.loads(STATE_F.read_text(encoding="utf-8")) if STATE_F.exists() else {}
    st.setdefault("shadow_start", P["SHADOW_START"]); st.setdefault("last_scan_date", None)
    st["frozen_script_sha256"] = FROZEN_SHA; st["params"] = P
    st["names_loaded"] = int(done); st["last_data_date"] = cal[-1]
    # 已了结交易
    settled = []
    if TRADES_F.exists():
        for line in TRADES_F.read_text(encoding="utf-8").splitlines():
            if line.strip(): settled.append(json.loads(line))
    have = {(x["signal_date"], x["sym"]) for x in settled}
    last_cal = cal[-1]
    si = next((i for i,d in enumerate(cal) if d >= P["SHADOW_START"]), None)
    if si is None: log("!! shadow_start 之后暂无数据"); si = T
    n_new = 0; n_pending = 0
    for t in range(si, T):
        if t+1 >= T: break
        picks = signal(t)
        if not picks: continue
        for j, sc in picks:
            sym = syms[j]
            if (cal[t], sym) in have: continue
            g = GAP[t][j]; entry = O[t+1][j] if t+1 < T else np.nan
            if not (np.isfinite(entry) and entry > 0): continue
            ex_t = t+2
            if ex_t >= T:
                n_pending += 1; continue
            # --- 对照口径: 纯 T+2 尾盘 (v1.2 原规则) ---
            exC = C[ex_t][j]; usedC = ex_t; flagC = 0
            if not (np.isfinite(exC) and exC > 0):
                for k in range(ex_t+1, min(ex_t+6, T)):
                    if np.isfinite(C[k][j]) and C[k][j] > 0: exC, usedC, flagC = C[k][j], k, 1; break
                else:
                    if P["WORST_CASE_WIPEOUT"]: exC, usedC, flagC = 0.0, ex_t, 2
            # --- 主口径(v1.3): 止盈 +TP%, 不止损; 未达标 -> T+2 尾盘 ---
            tp_lv = entry * (1.0 + P["TP"]); o2 = O[ex_t][j]; h2 = H[ex_t][j]
            exT, usedT, flagT, tp_hit = exC, usedC, flagC, 0
            if np.isfinite(h2) and h2 > 0 and np.isfinite(o2):
                if o2 >= tp_lv: exT, usedT, flagT, tp_hit = o2, ex_t, 0, 1
                elif h2 >= tp_lv: exT, usedT, flagT, tp_hit = tp_lv, ex_t, 0, 1
            settled.append(dict(signal_date=cal[t], sym=sym, gap_pct=round(float(g)*100,3),
                entry_date=cal[t+1], entry_open=round(float(entry),4),
                exit_date=cal[usedT], exit_px=round(float(exT),4), exit_flag=flagT, tp_hit=int(tp_hit),
                ret_pct=round(float(_ret_of(entry, exT)),4),
                close_exit_date=cal[usedC], close_exit_px=round(float(exC),4),
                ret_pct_close=round(float(_ret_of(entry, exC)),4),
                real_fill_px=None, real_ret_pct=None, order_size=None, auction_volume=None))
            have.add((cal[t], sym)); n_new += 1
    if n_new:
        with TRADES_F.open("w", encoding="utf-8") as fh:
            for x in settled: fh.write(json.dumps(x, ensure_ascii=False)+"\n")
    st["n_settled"] = len(settled); st["n_pending"] = n_pending; st["last_scan_date"] = last_cal
    st["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reps = np.array([x["ret_pct"] for x in settled], float)
    acc = dict(n=int(reps.size), mean_pct=round(float(reps.mean()),4) if reps.size else None,
               med_pct=round(float(np.median(reps)),4) if reps.size else None,
               wr_pct=round(float(100*(reps>0).mean()),2) if reps.size else None)
    repsC = np.array([x.get("ret_pct_close", x["ret_pct"]) for x in settled], float)
    accC = dict(n=int(repsC.size), mean_pct=round(float(repsC.mean()),4) if repsC.size else None,
                med_pct=round(float(np.median(repsC)),4) if repsC.size else None,
                wr_pct=round(float(100*(repsC>0).mean()),2) if repsC.size else None)
    tpr = [x.get("tp_hit",0) for x in settled]
    gaps = {"n": (acc["n"] >= 300), "days": (len({x["signal_date"] for x in settled}) >= 120),
            "mean": bool(acc["mean_pct"] and acc["mean_pct"] > 0), "wr": bool(acc["wr_pct"] and acc["wr_pct"] >= 46),
            "med": bool(acc["med_pct"] and acc["med_pct"] > 0)}
    exec_dev = [ (x["real_fill_px"]/x["entry_open"]-1)*100 for x in settled if x.get("real_fill_px")]
    rep = dict(frozen_script_sha256=FROZEN_SHA, shadow_start=P["SHADOW_START"], last_data_date=last_cal,
               exit_rule="v1.3 主口径: 止盈 +%.2f%% / 不止损 / 未达标 T+2 尾盘; 对照口径: 纯 T+2 尾盘" % (P["TP"]*100),
               n_pending=n_pending, acceptance=acc, acceptance_close_only=accC,
               tp_hit_pct=round(100*sum(tpr)/max(1,len(tpr)),1), gates=gaps,
               exec_dev_pct=dict(n=len(exec_dev), mean=round(float(np.mean(exec_dev)),4) if exec_dev else None),
               verdict="尚未开始（无已完成样本）" if acc["n"]==0 else ("继续观察" if not all(gaps.values()) else "四闸+样本量达标，可评估"))
    REPORT_F.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    STATE_F.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    log("names_loaded=%d 新增了结 %d 笔, 待了结 %d 笔, 累计 %d 笔" % (done, n_new, n_pending, len(settled)))
    log("acceptance:", json.dumps(acc, ensure_ascii=False))
    log("gates:", json.dumps(gaps, ensure_ascii=False))
    log("verdict:", rep["verdict"])
    log("wrote", STATE_F.name, TRADES_F.name, REPORT_F.name)
if __name__ == "__main__":
    main()
