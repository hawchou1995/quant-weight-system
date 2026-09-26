# -*- coding: utf-8 -*-
"""r7: survivorship check — do any names stop trading mid-sample, and what did the strategy earn on them?"""
import json, pathlib, numpy as np
S = pathlib.Path(r"C:/Users/Admin/.pi-desktop/scratch/d40abb6e-dc12-4d27-8ed2-f290de0a6c5c")
R = pathlib.Path(r"D:/Documents/Workbuddy/股票基金/quant-weight-system")
U = json.loads((R/"backtest/wechat_hotspot_leader_0925/universe.json").read_text(encoding="utf-8"))
cal = np.array(U["calendar"], dtype=object); T, N = len(cal), len(U["universe"])
sym=[u["sym"] for u in U["universe"]]
VALID = np.load(S/"wl_VALID.npy").astype(bool)
O = np.asarray(np.load(S/"wl_OPEN.npy", mmap_mode="r")); C = np.asarray(np.load(S/"wl_CLOSE.npy", mmap_mode="r"))
AMT20 = np.asarray(np.load(S/"wl_AMT20.npy", mmap_mode="r")); NV = np.asarray(np.load(S/"wl_NV.npy", mmap_mode="r"))
RET20 = np.asarray(np.load(S/"wl_RET20.npy", mmap_mode="r")); VOLBR = np.asarray(np.load(S/"wl2_VOLBR.npy", mmap_mode="r"))
GAPO = np.asarray(np.load(S/"wl2_GAPNEXT.npy", mmap_mode="r"))
def sh(a,k):
    b=np.full(a.shape,np.nan,dtype=np.float32); b[:-k]=a[k:]; return b
O1=sh(O,1); C2=sh(C,2)
FULL=C2/O1-1.0
FULL[~(np.isfinite(C2)&(C2>0)&np.isfinite(O1)&(O1>0))]=np.nan
lastv = np.array([np.max(np.nonzero(VALID[:,j])[0]) if VALID[:,j].any() else -1 for j in range(N)])
print("=== 存活检查 ===")
for q in (0,1,5,10,25,50,90,100): print("   个股最后有效日索引 p%-3d = %d (%s)" % (q, np.percentile(lastv,q), cal[int(np.percentile(lastv,q))] if np.percentile(lastv,q)>=0 else "-"))
early = lastv < (T-40)
print("  最后有效日早于样本末 40 日以上的股票: %d 只 (%.2f%%)" % (early.sum(), 100*early.mean()))
print("  其中最后有效日 < 2024-01-01 的: %d 只" % int((lastv < 2230).sum()))
print("  样例:", [(sym[j], str(cal[lastv[j]])) for j in np.argsort(lastv)[:12]])
okb=np.zeros((T,N),bool)
for t in range(60,T-4):
    okb[t]=(VALID[t]&(NV[t]>=250)&(C[t]>=2.0)&np.isfinite(AMT20[t])&(AMT20[t]>=2e7))
POOL={}
for t in range(60,T-3):
    g=GAPO[t]
    m=okb[t]&np.isfinite(g)&(g<=-0.01)&(g>=-0.03)&np.isfinite(FULL[t])
    idx=np.nonzero(m)[0]
    if idx.size: POOL[t]=idx
def zs(x):
    x=np.asarray(x,float); mu=np.nanmean(x); sd=np.nanstd(x)
    return (x-mu)/sd if np.isfinite(sd) and sd>0 else np.zeros_like(x)
SIG={}
for t,idx in POOL.items():
    s=zs(-np.log(np.where(AMT20[t][idx]>0,AMT20[t][idx],np.nan)))+zs(-np.log(np.where(VOLBR[t][idx]>0,VOLBR[t][idx],np.nan)))+zs(-RET20[t][idx])
    SIG[t]= idx if len(idx)<=10 else idx[np.argsort(-np.where(np.isfinite(s),s,-1e30))][:10]
print("\n=== 选中标的按「是否活到样本末」拆分 ===")
a_live=[]; a_dead=[]
for t,idx in SIG.items():
    v=FULL[t][idx]
    live=~early[idx]
    x=v[(np.isfinite(v))&live]; y=v[(np.isfinite(v))&(~live)]
    if x.size: a_live.append(x)
    if y.size: a_dead.append(y)
al=np.concatenate(a_live)*100 if a_live else np.array([0.0]); ad=np.concatenate(a_dead)*100 if a_dead else np.array([0.0])
print("  活到样本末: n=%6d 毛均 %+8.4f%% 毛中 %+8.4f%% 毛胜 %6.2f%%" % (al.size, al.mean(), np.median(al), 100*(al>0).mean()))
print("  提前终止  : n=%6d 毛均 %+8.4f%% 毛中 %+8.4f%% 毛胜 %6.2f%%" % (ad.size, ad.mean(), np.median(ad), 100*(ad>0).mean()))
print("\n=== 全池对照: 提前终止标的占比 ===")
all_dead=0; all_n=0
for t,idx in POOL.items():
    for j in idx:
        if np.isfinite(FULL[t][j]):
            all_n+=1; all_dead+=int(early[j])
print("  池内信号来自「提前终止」标的的比例: %.3f%% (%d/%d)" % (100*all_dead/max(1,all_n), all_dead, all_n))
print("\n注: data_full 仅含现存标的, 真正已退市/摘牌的标的不在池内 -> 生存者偏差无法在本数据集内完全修正")
json.dump(dict(early_names=int(early.sum()), early_pct=round(100*float(early.mean()),2),
    picks_live=dict(n=int(al.size), mean=round(float(al.mean()),4), med=round(float(np.median(al)),4), wr=round(float(100*(al>0).mean()),2)),
    picks_dead=dict(n=int(ad.size), mean=round(float(ad.mean()),4), med=round(float(np.median(ad)),4), wr=round(float(100*(ad>0).mean()),2)),
    pool_dead_share_pct=round(100*all_dead/max(1,all_n),3)),
    open(S/"r7_survivorship.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("saved r7_survivorship.json")
