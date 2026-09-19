# -*- coding: utf-8 -*-
"""诊断: 动态复算 sign / picked / weights，与冻结 JSON 对比。"""
import numpy as np, pandas as pd, pickle, json, os
BASE = r"D:/Documents/Workbuddy/股票基金/quant-weight-system"
OSS = os.path.join(BASE,"backtest","oss_0913"); FL = os.path.join(BASE,"backtest","factorlab_0913")
CFG = json.load(open(os.path.join(OSS,"super_combo_0913.json"),encoding="utf-8"))
with open(os.path.join(OSS,"oss_panel_0913.pkl"),"rb") as fh: P=pickle.load(fh)
with open(os.path.join(FL,"panel_0913.pkl"),"rb") as fh: FP=pickle.load(fh)
cal=P["cal"]; codes=P["codes"]; st=P["st_mask"]; ND,NC=P["close"].shape
E=P["ext"]; FD=FP["factors"]
O=P["open"].astype(np.float64);H=P["high"].astype(np.float64);L=P["low"].astype(np.float64)
C=P["close"].astype(np.float64);V=P["vol"].astype(np.float64);AMT=P["amt"].astype(np.float64)
ATR=E["atr14"].astype(np.float64);J=E["kdj_j"].astype(np.float64)
ZW=E["z_white"].astype(np.float64);ZY=E["z_yellow"].astype(np.float64)
close_ff=pd.DataFrame(C).ffill().to_numpy()
amt20=pd.DataFrame(AMT).rolling(20,min_periods=15).mean().to_numpy()
hist_n=np.cumsum(np.isfinite(O),axis=0)
lo20=pd.DataFrame(L).rolling(20,min_periods=15).min().to_numpy()
hi20=pd.DataFrame(H).rolling(20,min_periods=15).max().to_numpy()
hi120=pd.DataFrame(H).rolling(120,min_periods=80).max().to_numpy()
sig20=pd.DataFrame(close_ff).rolling(20,min_periods=20).std(ddof=0).to_numpy()
Cprev=np.vstack([np.full((1,NC),np.nan),close_ff[:-1]])
with np.errstate(all="ignore"):
    TR=np.maximum.reduce([H-L,np.abs(H-Cprev),np.abs(L-Cprev)])
tr20=pd.DataFrame(TR).rolling(20,min_periods=20).mean().to_numpy()
v5=pd.DataFrame(V).rolling(5,min_periods=5).mean().to_numpy()
v20=pd.DataFrame(V).rolling(20,min_periods=20).mean().to_numpy()
up90=pd.DataFrame(H).rolling(90,min_periods=60).max().shift(1).to_numpy()
with np.errstate(all="ignore"):
    AF={"neg_j":-J,"shrink":-(v5/v20),
        "low_lift":(lo20/pd.DataFrame(L).rolling(60,min_periods=40).min().to_numpy()-1)*100,
        "neg_dbbi":-np.abs(E["dist_bbi"].astype(np.float64)),
        "neg_dyel":-np.abs(E["dist_yellow"].astype(np.float64)),
        "wy_ratio":(ZW/ZY-1)*100,"neg_sspace":-((close_ff/lo20-1)*100),
        "pspace":(hi20/close_ff-1)*100,"dd120":(close_ff/hi120-1)*100,
        "slope_bbi":(E["bbi"].astype(np.float64)/pd.DataFrame(E["bbi"].astype(np.float64)).shift(3).to_numpy()-1)*100,
        "sqz_ratio":-(sig20/tr20),"neg_atrp":-(ATR/close_ff)*100,
        "brk90":(close_ff/up90-1)*100,"neg_vr":-(v5/v20)}
ALL=dict(AF)
for k in ["amount20","size_rev","amp20","ret60","bp","size_ep"]: ALL[k]=FD[k].astype(np.float64)
ELIG3=(np.isfinite(O)&np.isfinite(C)&(amt20>=3e6)&(~st[None,:])&(hist_n>=150)&(C>2.0))
fwdH=np.full((ND,NC),np.nan); fwdH[:ND-1-20]=O[21:]/O[1:ND-20]-1
def rank_ic(mat):
    a=np.where(ELIG3&np.isfinite(mat),mat,np.nan)
    r=pd.DataFrame(a).rank(axis=1).to_numpy()
    zy=pd.DataFrame(np.where(ELIG3&np.isfinite(fwdH),fwdH,np.nan)).rank(axis=1).to_numpy()
    zf=r-np.nanmean(r,axis=1,keepdims=True); zz=zy-np.nanmean(zy,axis=1,keepdims=True)
    zf=zf/(np.nanstd(zf,axis=1,keepdims=True)+1e-12); zz=zz/(np.nanstd(zz,axis=1,keepdims=True)+1e-12)
    both=np.isfinite(zf)&np.isfinite(zz); n=both.sum(axis=1)
    ic=np.where(n>50,np.nansum(np.where(both,zf*zz,0),axis=1)/np.maximum(n,1),np.nan)
    v=ic[np.isfinite(ic)]; return float(v.mean()),float(v.mean()/(v.std()+1e-12))
EV={k:rank_ic(m) for k,m in ALL.items()}
sign={k:(1.0 if EV[k][0]>=0 else -1.0) for k in ALL}
J_sign=CFG["meta"]["sign"]
print("--- sign 对比 (动态 vs 冻结JSON) ---")
diff=[k for k in J_sign if sign[k]!=J_sign[k]]
print("候选数",len(ALL),"sign 不一致:",diff if diff else "无")
for k in J_sign: print(f"  {k:<12} dyn={sign[k]:+.0f} json={J_sign[k]:+.0f}  ic={EV[k][0]:+.4f} icir={EV[k][1]:+.3f}")
sample=np.arange(150,ND,3); Zs={}
for k,mat in ALL.items():
    a=(mat*sign[k])[sample]; a=np.where(np.isfinite(a)&ELIG3[sample],a,np.nan)
    mu=np.nanmean(a,axis=1,keepdims=True); sd=np.nanstd(a,axis=1,keepdims=True)
    Zs[k]=np.clip((a-mu)/(sd+1e-12),-8,8)
order=sorted(ALL,key=lambda k:-abs(EV[k][0])); picked=[]; dropped={}
for k in order:
    ok=True
    for p in picked:
        m=np.isfinite(Zs[k])&np.isfinite(Zs[p])
        r=np.corrcoef(Zs[k][m],Zs[p][m])[0,1] if m.sum()>500 else 0.0
        if abs(r)>0.6: dropped[k]=f"{r:+.2f}~{p}"; ok=False; break
    if ok: picked.append(k)
print("--- picked 对比 ---")
print("动态 picked(%d):"%len(picked),picked)
print("JSON  picked(%d):"%len(CFG['meta']['picked']),CFG['meta']['picked'])
print("集合一致:", set(picked)==set(CFG['meta']['picked']))
Wd={}; 
for k in picked: Wd[k]=max(abs(EV[k][1]),0.01)
sW=sum(Wd.values()); Wd={k:v/sW for k,v in Wd.items()}
print("--- weights 对比 ---")
for k in CFG['meta']['weights']:
    print(f"  {k:<12} dyn={Wd.get(k,float('nan')):.6f} json={CFG['meta']['weights'][k]:.6f} delta={Wd.get(k,float('nan'))-CFG['meta']['weights'][k]:+.2e}")
