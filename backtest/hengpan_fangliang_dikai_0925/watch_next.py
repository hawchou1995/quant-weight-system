# -*- coding: utf-8 -*-
"""watch_next.py — 用「最后可用交易日 T 的收盘」为 T+1 开盘生成候选表 / 精确选股
【注意】本脚本不产生 OOS 记录；OOS 记录只由冻结的 oos_run.py 产生。
规则与 oos_run.py 完全一致（同参数、同公式），含与样本内面板的对拍自检。
用法:
  python watch_next.py                                # T = 日历最后一日, 输出盘前候选表
  python watch_next.py 2026-09-23                     # 指定 T; 若 T+1 数据已入库则直接给精确前 10
  python watch_next.py 2026-09-24 --opens opens.csv   # 手工喂 T+1 开盘价 -> 精确前 10 (09-28 早上用)
      opens.csv 两列: sym,open      (例: sh600076,2.05)
"""
import json, pathlib, sys, numpy as np, pandas as pd
R = pathlib.Path(__file__).resolve().parents[2]
UNI = R/"backtest/wechat_hotspot_leader_0925/universe.json"
DEAD = R/"backtest/_delisted_universe/delisted_bars.csv.gz"
P = dict(P1=0.01, P2=0.03, K=10, KSLOT=20, MINAMT=2e7, MINPX=2.0, LISTED=250, COST_SIDE=0.000346)
U = json.loads(UNI.read_text(encoding="utf-8"))
cal = list(U["calendar"]); live=[u["sym"] for u in U["universe"]]
dead = sorted(pd.read_csv(DEAD)["sym"].unique().tolist()) if DEAD.exists() else []
syms = live+dead; T=len(cal); N=len(syms); lut={d:i for i,d in enumerate(cal)}
print("日历 %s..%s (%d 日) ; 池 %d (现存 %d + 退市 %d)" % (cal[0],cal[-1],T,N,len(live),len(dead)))
F={k:np.zeros((T,N),dtype=np.float32) for k in ("O","C","V","A")}
dm={}
if DEAD.exists():
    b=pd.read_csv(DEAD); b=b[b["sym"].isin(set(syms))]; dm={s:g for s,g in b.groupby("sym")}
for j,s_ in enumerate(syms):
    if s_ in dm:
        df=dm[s_].copy(); df["date"]=df["date"].astype(str)
    else:
        p=R/"data_full"/(s_+".csv")
        if not p.exists(): continue
        try: df=pd.read_csv(p)
        except Exception: continue
        df["date"]=df["date"].astype(str).str.slice(0,10)
    ri=np.array([lut.get(d,-1) for d in df["date"]],dtype=np.int64); k=ri>=0; ri=ri[k]
    for nm,col in (("O","open"),("C","close"),("V","volume"),("A","amount")):
        if col in df.columns: F[nm][ri,j]=pd.to_numeric(df[col],errors="coerce").to_numpy(dtype=np.float64)[k]
O,C,V,A=F["O"],F["C"],F["V"],F["A"]
VALID=(C>0)&np.isfinite(C)&(O>0)
Cv=np.where(VALID,C,np.nan); Vv=np.where(VALID,V,np.nan); Av=np.where(VALID,A,np.nan)
AMT20=pd.DataFrame(Av).rolling(20,min_periods=10).mean().to_numpy(dtype=np.float32)
VMA20=pd.DataFrame(Vv).rolling(20,min_periods=10).mean().to_numpy(dtype=np.float32)
VMA20_prev=np.full_like(VMA20,np.nan); VMA20_prev[1:]=VMA20[:-1]
VOLBR=V/np.where(VMA20_prev>0,VMA20_prev,np.nan)
RET20=np.full((T,N),np.nan,dtype=np.float32); RET20[20:]=Cv[20:]/Cv[:-20]-1.0
NV=np.cumsum(VALID,axis=0).astype(np.int32)
GAP=np.full((T,N),np.nan,dtype=np.float32); GAP[:-1]=O[1:]/np.where(C[:-1]>0,C[:-1],np.nan)-1.0
def zs(x):
    x=np.asarray(x,float); mu=np.nanmean(x); sd=np.nanstd(x)
    return (x-mu)/sd if np.isfinite(sd) and sd>0 else np.zeros_like(x)
try:
    SS=pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
    if (SS/"wl_AMT20.npy").exists():
        m_amt=np.asarray(np.load(SS/"wl_AMT20.npy",mmap_mode="r")); m_vb=np.asarray(np.load(SS/"wl2_VOLBR.npy",mmap_mode="r"))
        m_rt=np.asarray(np.load(SS/"wl_RET20.npy",mmap_mode="r")); t0=T-1
        def md(a,b):
            a=a[:len(live)]; ok=np.isfinite(a)&np.isfinite(b)
            return float(np.max(np.abs(a[ok]-b[ok])/np.maximum(np.abs(b[ok]),1e-9))) if ok.any() else 0.0
        d1=md(AMT20[t0],m_amt[t0]); d2=md(VOLBR[t0],m_vb[t0]); d3=md(RET20[t0],m_rt[t0])
        print("\n[自检] 与样本内面板对拍 T=%s: AMT20 %.2e | VOLBR %.2e | RET20 %.2e  ->  %s" %
              (cal[t0],d1,d2,d3,"一致 ✅" if max(d1,d2,d3)<1e-4 else "不一致 ❌"))
except Exception as e: print("\n[自检] 跳过:",str(e)[:70])
args=[a for a in sys.argv[1:] if not a.startswith("--")]
OPEN_CSV=None
if "--opens" in sys.argv:
    OPEN_CSV=sys.argv[sys.argv.index("--opens")+1]
Td=args[0] if args else cal[-1]
assert Td in lut, "T=%s 不在交易日历内" % Td
t=lut[Td]; next_td=cal[t+1] if t+1<T else "(尚未发生)"
print("\n信号日 T = %s  ->  买入日 T+1 = %s" % (Td,next_td))
elig=VALID[t]&(NV[t]>=P["LISTED"])&(C[t]>=P["MINPX"])&np.isfinite(AMT20[t])&(AMT20[t]>=P["MINAMT"])
ix_all=np.nonzero(elig)[0]
comp_all=zs(-np.log(AMT20[t][ix_all]))+zs(-np.log(VOLBR[t][ix_all]))+zs(-RET20[t][ix_all])
df=pd.DataFrame(dict(sym=[syms[j] for j in ix_all],close=np.round(C[t][ix_all],3),
    amt20_wan=np.round(AMT20[t][ix_all]/1e4,1),volbr=np.round(VOLBR[t][ix_all],3),
    ret20_pct=np.round(RET20[t][ix_all]*100,2),comp_prov=np.round(comp_all,4)))
df=df.sort_values("comp_prov",ascending=False).reset_index(drop=True); df["rank_prov"]=df.index+1
print("合格股票 %d 只（跳空未定，含低开与高开）" % len(df))
g=GAP[t].astype(np.float64).copy(); src=None
if OPEN_CSV:
    od=pd.read_csv(OPEN_CSV); sylut={s:j for j,s in enumerate(syms)}
    g=np.full(N,np.nan)
    nset=0
    for r_ in od.itertuples(index=False):
        j=sylut.get(str(r_.sym))
        if j is None: continue
        if np.isfinite(C[t][j]) and C[t][j]>0 and np.isfinite(r_.open) and r_.open>0:
            g[j]=float(r_.open)/C[t][j]-1.0; nset+=1
    src="用户提供开盘价 (%d/%d 只匹配)" % (nset,len(od))
elif t+1<T:
    src="T+1(%s) 数据已入库" % next_td
if src:
    m=elig&np.isfinite(g)&(g<=-P["P1"])&(g>=-P["P2"])&np.isfinite(RET20[t])&np.isfinite(VOLBR[t])
    ix=np.nonzero(m)[0]
    if ix.size:
        comp=zs(-np.log(AMT20[t][ix]))+zs(-np.log(VOLBR[t][ix]))+zs(-RET20[t][ix])
        o=np.argsort(-comp)[:P["K"]]
        exact=pd.DataFrame(dict(sym=[syms[j] for j in ix[o]],gap_pct=np.round(g[ix[o]]*100,3),
            prev_close=np.round(C[t][ix[o]],3),open_used=np.round(g[ix[o]]*C[t][ix[o]]+C[t][ix[o]],3),comp=np.round(comp[o],4)))
        print("\n【精确前 10】来源: %s ; 低开池 %d 只" % (src,ix.size))
        print(exact.to_string(index=False))
        out2=R/"backtest/hengpan_fangliang_dikai_0925"/("exact_picks_%s.csv" % Td)
        exact.to_csv(out2,index=False,encoding="utf-8-sig"); print("已写出:",out2.name)
    else:
        print("\n【精确前 10】来源: %s -> 当日无合格低开(空仓)" % src)
else:
    print("\n【盘前候选 top-30】provisional（跳空未定，按全部合格股打分；盘中按实际低开池重算）")
    print(df.head(30).to_string(index=False))
out=R/"backtest/hengpan_fangliang_dikai_0925"/("watchlist_%s.csv"%Td)
df.to_csv(out,index=False,encoding="utf-8-sig")
print("\n全量候选已写出: %s (%d 行)" % (out.name,len(df)))
