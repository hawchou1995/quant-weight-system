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
P = dict(P1=0.01, P2=0.03, K=10, KSLOT=20, MINAMT=2e7, MINPX=3.0, LISTED=250,
         COST_SIDE=0.000346, SHADOW_START="2026-09-25", WORST_CASE_WIPEOUT=True)
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
    O, C, V, A = F["O"], F["C"], F["V"], F["A"]
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

    lut = {d: i for i, d in enumerate(cal)}
    # ===== 过滤件（2026-09-26 用户要求，预注册 E-6）: 剔ST/*ST + 股价>=3元 + 每股净资产>=3元 =====
    _NAMES = json.loads((R/"data_full_names.json").read_text(encoding="utf-8"))
    STNOW = np.array([(("ST" in (_NAMES.get(_s,"") or "").upper()) or ("退" in (_NAMES.get(_s,"") or "")))
                      for _s in syms], dtype=bool)
    _Cv = np.where(VALID, C, np.nan)
    _r1 = np.full((T, N), np.nan, dtype=np.float32); _r1[1:] = _Cv[1:]/_Cv[:-1] - 1.0
    _MX = pd.DataFrame(np.abs(_r1)).rolling(250, min_periods=60).max().to_numpy(dtype=np.float32)
    STP = np.isfinite(_MX) & (_MX <= 0.056)          # 期内 ST 代理: 250日最大绝对日收益<=5.6% (即 ±5% 限价制度)
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
        """返回可交易掩码: 非ST(期内代理+当前名) 且 股价>=3 且 每股净资产>=3(报告期+4个月后方可用)"""
        return (~STP[t]) & (~STNOW) & (C[t] >= 3.0) & np.isfinite(BPSA[t]) & (BPSA[t] >= 3.0)

    def zs(x):
        x = np.asarray(x, float); mu = np.nanmean(x); sd = np.nanstd(x)
        return (x-mu)/sd if np.isfinite(sd) and sd > 0 else np.zeros_like(x)
    def elig(t):
        return (VALID[t] & (NV[t] >= P["LISTED"]) & (C[t] >= P["MINPX"]) &
                np.isfinite(AMT20[t]) & (AMT20[t] >= P["MINAMT"]) & FILT(t))
    def signal(t):
        b = elig(t); g = GAP[t]
        m = b & np.isfinite(g) & (g <= -P["P1"]) & (g >= -P["P2"]) & np.isfinite(RET20[t]) & np.isfinite(VOLBR[t])
        ix = np.nonzero(m)[0]
        if ix.size == 0: return []
        comp = zs(-np.log(AMT20[t][ix])) + zs(-np.log(VOLBR[t][ix])) + zs(-RET20[t][ix])
        k = min(P["K"], ix.size)
        return [[int(ix[q]), float(comp[q])] for q in np.argsort(-comp)[:k]]
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
            ex = C[ex_t][j]; used = ex_t; flag = 0
            if not (np.isfinite(ex) and ex > 0):
                for k in range(ex_t+1, min(ex_t+6, T)):
                    if np.isfinite(C[k][j]) and C[k][j] > 0: ex, used, flag = C[k][j], k, 1; break
                else:
                    if P["WORST_CASE_WIPEOUT"]: ex, used, flag = 0.0, ex_t, 2
            ret = -100.0 if ex == 0 else (ex*(1-P["COST_SIDE"])/(entry*(1+P["COST_SIDE"])) - 1)*100
            settled.append(dict(signal_date=cal[t], sym=sym, gap_pct=round(float(g)*100,3),
                entry_date=cal[t+1], entry_open=round(float(entry),4), exit_date=cal[used],
                exit_px=round(float(ex),4), exit_flag=flag,
                ret_pct=round(float(ret),4), real_fill_px=None, real_ret_pct=None))
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
    gaps = {"n": (acc["n"] >= 300), "days": (len({x["signal_date"] for x in settled}) >= 120),
            "mean": bool(acc["mean_pct"] and acc["mean_pct"] > 0), "wr": bool(acc["wr_pct"] and acc["wr_pct"] >= 46),
            "med": bool(acc["med_pct"] and acc["med_pct"] > 0)}
    exec_dev = [ (x["real_fill_px"]/x["entry_open"]-1)*100 for x in settled if x.get("real_fill_px")]
    rep = dict(frozen_script_sha256=FROZEN_SHA, shadow_start=P["SHADOW_START"], last_data_date=last_cal,
               n_pending=n_pending, acceptance=acc, gates=gaps,
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
