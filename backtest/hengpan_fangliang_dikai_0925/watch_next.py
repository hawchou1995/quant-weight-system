# -*- coding: utf-8 -*-
"""watch_next.py — 用「最后可用交易日 T 的收盘」为 T+1 开盘生成候选表 / 精确选股
【注意】本脚本不产生 OOS 记录；OOS 记录只由冻结的 oos_run.py 产生。
规则与 oos_run.py 完全一致（同参数、同公式），含与样本内面板的对拍自检。
用法:
  python watch_next.py                                  # T = 日历最后一日, 输出盘前候选表
  python watch_next.py 2026-09-23                       # 指定 T; T+1 数据已入库则直接给精确前 10
  python watch_next.py 2026-09-24 --opens opens.csv     # 喂 T+1 开盘价 -> 精确前 10
        opens.csv 两列: sym,open        (例: sh600076,2.05)
  python watch_next.py 2026-09-24 --syms qual.csv       # 【最省事】喂「低开 1~3%」代码清单 -> 精确前 10
        qual.csv 一列: sym              (行情软件筛「开盘跌幅 1%~3%」导出代码; 跳空只做筛选、不参与排序)
"""
import json, pathlib, sys, numpy as np, pandas as pd
R = pathlib.Path(__file__).resolve().parents[2]
UNI = R/"backtest/wechat_hotspot_leader_0925/universe.json"
DEAD = R/"backtest/_delisted_universe/delisted_bars.csv.gz"
P = dict(P1=0.01, P2=0.03, K=10, KSLOT=20, MINAMT=2e7, MINPX=3.0, LISTED=250, COST_SIDE=0.000346)
U = json.loads(UNI.read_text(encoding="utf-8"))
cal = list(U["calendar"]); live = [u["sym"] for u in U["universe"]]
dead = sorted(pd.read_csv(DEAD)["sym"].unique().tolist()) if DEAD.exists() else []
syms = live + dead; T = len(cal); N = len(syms); lut = {d:i for i,d in enumerate(cal)}
sylut = {s:j for j,s in enumerate(syms)}
print("日历 %s..%s (%d 日) ; 池 %d (现存 %d + 退市 %d)" % (cal[0], cal[-1], T, N, len(live), len(dead)))
F = {k: np.zeros((T,N), dtype=np.float32) for k in ("O","C","V","A")}
dm = {}
if DEAD.exists():
    b = pd.read_csv(DEAD); b = b[b["sym"].isin(set(syms))]; dm = {s:g for s,g in b.groupby("sym")}
for j, s_ in enumerate(syms):
    if s_ in dm:
        df = dm[s_].copy(); df["date"] = df["date"].astype(str)
    else:
        p = R/"data_full"/(s_+".csv")
        if not p.exists(): continue
        try: df = pd.read_csv(p)
        except Exception: continue
        df["date"] = df["date"].astype(str).str.slice(0,10)
    ri = np.array([lut.get(d,-1) for d in df["date"]], dtype=np.int64); k = ri >= 0; ri = ri[k]
    for nm, col in (("O","open"),("C","close"),("V","volume"),("A","amount")):
        if col in df.columns:
            F[nm][ri,j] = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=np.float64)[k]
O,C,V,A = F["O"], F["C"], F["V"], F["A"]
VALID = (C>0)&np.isfinite(C)&(O>0)
Cv = np.where(VALID,C,np.nan); Vv = np.where(VALID,V,np.nan); Av = np.where(VALID,A,np.nan)
AMT20 = pd.DataFrame(Av).rolling(20,min_periods=10).mean().to_numpy(dtype=np.float32)
VMA20 = pd.DataFrame(Vv).rolling(20,min_periods=10).mean().to_numpy(dtype=np.float32)
VMA20_prev = np.full_like(VMA20, np.nan); VMA20_prev[1:] = VMA20[:-1]
VOLBR = V/np.where(VMA20_prev>0, VMA20_prev, np.nan)
RET20 = np.full((T,N),np.nan,dtype=np.float32); RET20[20:] = Cv[20:]/Cv[:-20] - 1.0
NV = np.cumsum(VALID,axis=0).astype(np.int32)
GAP = np.full((T,N),np.nan,dtype=np.float32); GAP[:-1] = O[1:]/np.where(C[:-1]>0, C[:-1], np.nan) - 1.0

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
    x = np.asarray(x,float); mu = np.nanmean(x); sd = np.nanstd(x)
    return (x-mu)/sd if np.isfinite(sd) and sd>0 else np.zeros_like(x)
try:
    SS = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
    if (SS/"wl_AMT20.npy").exists():
        m_amt = np.asarray(np.load(SS/"wl_AMT20.npy",mmap_mode="r"))
        m_vb  = np.asarray(np.load(SS/"wl2_VOLBR.npy",mmap_mode="r"))
        m_rt  = np.asarray(np.load(SS/"wl_RET20.npy",mmap_mode="r")); t0 = T-1
        def md(a,b):
            a=a[:len(live)]; ok=np.isfinite(a)&np.isfinite(b)
            return float(np.max(np.abs(a[ok]-b[ok])/np.maximum(np.abs(b[ok]),1e-9))) if ok.any() else 0.0
        d1=md(AMT20[t0],m_amt[t0]); d2=md(VOLBR[t0],m_vb[t0]); d3=md(RET20[t0],m_rt[t0])
        print("[自检] 与样本内面板对拍 T=%s: AMT20 %.2e | VOLBR %.2e | RET20 %.2e -> %s" %
              (cal[t0],d1,d2,d3,"一致 ✅" if max(d1,d2,d3)<1e-4 else "不一致 ❌"))
except Exception as e:
    print("[自检] 跳过:", str(e)[:70])
args = [a for a in sys.argv[1:] if not a.startswith("--")]
OPEN_CSV = sys.argv[sys.argv.index("--opens")+1] if "--opens" in sys.argv else None
SYM_CSV  = sys.argv[sys.argv.index("--syms")+1]  if "--syms"  in sys.argv else None
Td = args[0] if args else cal[-1]
assert Td in lut, "T=%s 不在交易日历内" % Td
t = lut[Td]; next_td = cal[t+1] if t+1 < T else "(尚未发生)"
print("信号日 T = %s  ->  买入日 T+1 = %s" % (Td, next_td))
elig = VALID[t]&(NV[t]>=P["LISTED"])&(C[t]>=P["MINPX"])&np.isfinite(AMT20[t])&(AMT20[t]>=P["MINAMT"])&FILT(t)
ix_all = np.nonzero(elig)[0]
comp_all = zs(-np.log(AMT20[t][ix_all]))+zs(-np.log(VOLBR[t][ix_all]))+zs(-RET20[t][ix_all])
df = pd.DataFrame(dict(sym=[syms[j] for j in ix_all], close=np.round(C[t][ix_all],3),
    amt20_wan=np.round(AMT20[t][ix_all]/1e4,1), volbr=np.round(VOLBR[t][ix_all],3),
    ret20_pct=np.round(RET20[t][ix_all]*100,2), comp_prov=np.round(comp_all,4)))
df = df.sort_values("comp_prov", ascending=False).reset_index(drop=True); df["rank_prov"] = df.index+1
print("合格股票 %d 只（跳空未定，含低开与高开）" % len(df))
mask = None; src = None
if SYM_CSV:
    sl = set(pd.read_csv(SYM_CSV)["sym"].astype(str).str.strip())
    g = np.full(N, np.nan); hit = 0
    for s_ in sl:
        j = sylut.get(s_)
        if j is not None: g[j] = -0.02; hit += 1
    src = "用户提供「低开1~3pct」代码清单 (%d/%d 匹配)" % (hit, len(sl))
    mask = elig & np.isfinite(g)
elif OPEN_CSV:
    od = pd.read_csv(OPEN_CSV); g = np.full(N, np.nan); nset = 0
    for r_ in od.itertuples(index=False):
        j = sylut.get(str(r_.sym))
        if j is None: continue
        if np.isfinite(C[t][j]) and C[t][j] > 0 and np.isfinite(r_.open) and r_.open > 0:
            g[j] = float(r_.open)/C[t][j] - 1.0; nset += 1
    src = "用户提供开盘价 (%d/%d 匹配)" % (nset, len(od))
    mask = elig & np.isfinite(g) & (g<=-P["P1"]) & (g>=-P["P2"])
elif t+1 < T:
    g = GAP[t].astype(np.float64)
    src = "T+1(%s) 数据已入库" % next_td
    mask = elig & np.isfinite(g) & (g<=-P["P1"]) & (g>=-P["P2"])
if mask is not None:
    m = mask & np.isfinite(RET20[t]) & np.isfinite(VOLBR[t])
    ix = np.nonzero(m)[0]
    if ix.size:
        comp = zs(-np.log(AMT20[t][ix]))+zs(-np.log(VOLBR[t][ix]))+zs(-RET20[t][ix])
        o = np.argsort(-comp)[:P["K"]]
        gapv = g[ix[o]]
        out_cols = dict(sym=[syms[j] for j in ix[o]], prev_close=np.round(C[t][ix[o]],3), comp=np.round(comp[o],4))
        if np.any(np.isfinite(gapv)):
            out_cols = dict(sym=[syms[j] for j in ix[o]], gap_pct=np.round(gapv*100,3),
                            prev_close=np.round(C[t][ix[o]],3), comp=np.round(comp[o],4))
        exact = pd.DataFrame(out_cols)
        print("\n【精确前 10】来源: %s ; 低开池 %d 只" % (src, ix.size))
        print(exact.to_string(index=False))
        o2 = R/"backtest/hengpan_fangliang_dikai_0925"/("exact_picks_%s.csv" % Td)
        exact.to_csv(o2, index=False, encoding="utf-8-sig"); print("已写出:", o2.name)
    else:
        print("\n【精确前 10】来源: %s -> 当日无合格低开（空仓）" % src)
else:
    print("\n【盘前候选 top-30】provisional（跳空未定, 按全部合格股打分; 盘中按实际低开池重算）")
    print(df.head(30).to_string(index=False))
o3 = R/"backtest/hengpan_fangliang_dikai_0925"/("watchlist_%s.csv" % Td)
df.to_csv(o3, index=False, encoding="utf-8-sig")
print("\n全量候选已写出: %s (%d 行)" % (o3.name, len(df)))

# ===== 挂单清单 (09:15 前盲挂限价单用; 批准项2) =====
def _argval(flag, default=None):
    return sys.argv[sys.argv.index(flag)+1] if flag in sys.argv else default
N_ORD = int(_argval("--orders", 20)); CAP = float(_argval("--capital", 0)); KS = int(_argval("--kslot", 4))
top = df.head(N_ORD).copy()
top["limit_099"] = (top["close"]*0.99).round(2)
if CAP > 0:
    per = CAP/KS
    top["shares"] = (((per/top["limit_099"])//100)*100).astype(int)
    top["amount_yuan"] = (top["shares"]*top["limit_099"]).round(0)
    top["pct_of_cap"] = (100*top["amount_yuan"]/CAP).round(1)
top["adv_limit_yuan"] = (top["amt20_wan"]*1e4*0.01).round(0)   # 单票上限 = ADV 的 1% (集合竞价深度约束)
if CAP > 0:
    top["over_adv"] = (top["amount_yuan"] > top["adv_limit_yuan"]).map({True:"⚠超限", False:""})
cols = ["rank_prov","sym","close","limit_099"] + (["shares","amount_yuan","adv_limit_yuan","over_adv"] if CAP>0 else []) + ["volbr","ret20_pct","amt20_wan","comp_prov"]
if CAP > 0:
    _cap_max = KS * float(top["amt20_wan"].median()) * 1e4 * 0.01
    print("\n【容量校验】选中标的 ADV 中位 %.0f 万 -> 单票上限(ADV 1%%) %.1f 万 -> KSLOT=%d 时账户上限 ≈ %.0f 万元" %
          (top["amt20_wan"].median(), top["amt20_wan"].median()*1e4*0.01/1e4, KS, _cap_max/1e4))
    print("           当前设置 每只 %.1f 万; 超限标的 %d/%d 只 -> %s" %
          (CAP/KS/1e4, int((top["amount_yuan"]>top["adv_limit_yuan"]).sum()), len(top),
           "⚠ 建议下调总资金或提高 KSLOT" if (top["amount_yuan"]>top["adv_limit_yuan"]).any() else "✅ 全部在限内"))
print("\n" + "="*104)
print("挂单清单 | 信号日 T=%s -> 买入日 T+1 | 限价 = 前收x0.99 (=低开1%%的价位, 覆盖-1%%~-3%%低开)" % Td)
print("仓位: 资金 %.1f 万 / KSLOT=%d -> 每只 %.1f 万 ; 历史实际成交 1.7~2.8 只/日" % (CAP/1e4, KS, CAP/KS/1e4) if CAP>0 else "未给 --capital, 只出代码与限价")
print("="*104)
print(top[cols].to_string(index=False))
o4 = R/"backtest/hengpan_fangliang_dikai_0925"/("orderlist_%s.csv" % Td)
top[cols].to_csv(o4, index=False, encoding="utf-8-sig")
print("\n已写出挂单清单: %s (%d 行)" % (o4.name, len(top)))
print("\n【当日流程】")
print("  前一晚/09:15 前 : 按上表挂 前收x0.99 的限价买单")
print("  09:15-09:20    : 【可撤单窗口】按虚拟开盘价, 撤掉「跌幅>3%%」的标的 (历史占选中 16.2%%, 该组毛均为负)")
print("  09:25          : 集合竞价撮合, 开盘在 -1%%~-3%% 的自动以开盘价成交")
print("  T+2 09:15 前   : 对持仓挂 买入价x1.02 的限价卖单 (止盈, 限价卖出成交可靠)")
print("  T+2 14:55      : 未成交的市价卖出 (未达标尾盘离场)")
print("  T+1 当日不可卖 (T+1 制度)")

