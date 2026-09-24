# -*- coding: utf-8 -*-
"""
分年度数据（个人口径 17 万，与 top1_personal_170k_0924.py 完全同引擎）：
- 逐年：触发日数 / 候选笔数 / 单笔毛均值 / 胜率（A2 固定55）
- 逐年收益：2槽×6万、2槽×8.5万、按35%比例 三种买入口径（200 种子 → 中位 [5%~95%]）
输出：jiandi_top_grid_0924_out/top1_personal_yearly_0924.json + .csv
"""
import os, sys, time, json
from collections import defaultdict
import numpy as np, pandas as pd

T0=time.time()
def log(m): print(f"[{time.time()-T0:5.1f}s] {m}", flush=True)
BASE = r'D:\Documents\Workbuddy\股票基金\quant-weight-system'
BK = os.path.join(BASE,'backtest'); OUT = os.path.join(BK,'jiandi_top_grid_0924_out')
sys.path.insert(0, BK)
BS=pd.Timestamp('2016-06-01'); W_LO,W_HI=pd.Timestamp('2016-06-01'),pd.Timestamp('2026-09-23')
CAPITAL=170000.0; COMM=0.000086; CMIN=5.0; STAMP=0.0005; TRF=0.00001
THETA=30; HOLD=5; NSEED=200
YRS=[2016,2017,2018,2019,2020,2021,2022,2023,2024,2025,2026]
import jiandi_signal_0906 as JG

idx = pd.read_csv(os.path.join(BASE,'index_000300.csv'))
idx['date']=pd.to_datetime(idx['date']); idx=idx.sort_values('date').reset_index(drop=True)
for maw in (20,60): idx[f'ma{maw}']=idx['close'].rolling(maw,min_periods=1).mean()
CAL=[d for d in idx['date'] if W_LO<=d<=W_HI]

def build_regime(bear_ma=60,bull_ma=20):
    is_bear = (idx['close'] < idx[f'ma{bear_ma}']).to_numpy()
    bull = (~is_bear) & (idx['close'] > idx[f'ma{bull_ma}']).to_numpy()
    state = np.where(is_bear, 0, np.where(bull, 1, 2))
    prev_map={}; prev=None
    for k,dt in enumerate(idx['date']):
        prev_map[dt]=prev if prev is not None else 0
        prev=int(state[k])
    return (lambda dt: prev_map.get(pd.Timestamp(dt)))
reg_fn = build_regime(60,20)
def rsiN(c,n):
    delta=c.diff(); gain=delta.clip(lower=0).rolling(n,min_periods=1).mean()
    loss=(-delta.clip(upper=0)).rolling(n,min_periods=1).mean()
    return (100-100/(1+gain/loss.replace(0,np.nan))).to_numpy()

log("加载缓存 + 信号 ...")
cache0 = pd.read_pickle(os.path.join(BASE,'v8_factor_cache.pkl'))
cache = {c: df.sort_index() for c,df in cache0.items() if df is not None and JG.board_of(c)=='main'}
SIG_KEYS=('rushi','jihui','jiandi','kuaixian','laiLin','deng')
DA={}; events=[]; res_daily=defaultdict(int)
for code,df in cache.items():
    if len(df)<70: continue
    sm=JG.jiandi_signals(code,df)
    sig6=np.stack([np.asarray(sm[k],bool) for k in SIG_KEYS],axis=1)
    cnt=sig6.sum(axis=1)
    if not (cnt>=2).any(): continue
    o=df['open'].to_numpy(); c=df['close'].to_numpy()
    bad=(~np.isfinite(o))|(~np.isfinite(c))|(o<=0)|(c<=0)
    dates=df.index; n=len(df)
    for i in np.where(cnt>=2)[0]:
        sd=dates[i]
        if sd<BS: continue
        res_daily[sd]+=1
        B=i+1
        if B>=n or bad[B]: continue
        sell=B+HOLD
        if sell>=n or bad[B:sell+1].any(): continue
        if code not in DA:
            DA[code]=dict(o=o,c=c,dates=dates,rsi=rsiN(df['close'],14),pos={d:k for k,d in enumerate(dates)})
        events.append((sd,code,B,sell,int(cnt[i])))
evsT=[e for e in events if res_daily[e[0]]>=THETA]
log(f"事件池 {len(events)} / θ>=30 {len(evsT)}")

def win_ok(code,B,sell):
    da=DA[code]; oo=da['o'][B:sell+1]; cc=da['c'][B:sell+1]
    return bool(np.isfinite(oo).all() and np.isfinite(cc).all() and (oo>0).all() and (cc>0).all())
def arm_rsi(evs,thr_map):
    out=[]
    for (sd,code,B,sell0,cn) in evs:
        da=DA[code]; rsi=da['rsi']; dts=da['dates']; n=len(dts)
        sell=min(B+HOLD,n-1)
        for d in range(B,min(B+HOLD,n)):
            st=reg_fn(dts[d]); thr=thr_map.get(st if st is not None else 0,55)
            if np.isfinite(rsi[d]) and rsi[d]>=thr:
                sell=min(d+1,B+HOLD); break
        if sell<=B or sell>=n: continue
        if not win_ok(code,B,sell): continue
        out.append((sd,code,B,sell,cn))
    return out
evsA2=arm_rsi(evsT,{0:55,1:55,2:55})

# 逐年事件统计（按信号日归年）
ev_y={y:dict(days=set(),n=0,sumr=0.0,wins=0) for y in YRS}
for (sd,code,B,sell,cn) in evsA2:
    g=DA[code]['o'][sell]/DA[code]['o'][B]-1
    r=ev_y[sd.year]; r['days'].add(sd); r['n']+=1; r['sumr']+=g; r['wins']+=int(g>0)

def fee_buy(a): return max(a*COMM,CMIN)+a*TRF
def fee_sell(a): return max(a*COMM,CMIN)+a*TRF+a*STAMP
be=defaultdict(list)
for (sd,code,B,sell,cn) in evsA2: be[DA[code]['dates'][B]].append((code,B,sell,cn))
for d in be: be[d]=sorted(be[d],key=lambda x:(-x[3],x[0]))

def run_sim(slots, notional, max_new, seed=0, frac=None):
    rng=np.random.default_rng(seed)
    cash=CAPITAL; positions=[]; equity=[]; tcount=defaultdict(int)
    for d in CAL:
        if not positions and d not in be:
            equity.append(cash); continue
        still=[]
        for p in positions:
            if DA[p['code']]['dates'][p['sell']]==d:
                px=float(DA[p['code']]['o'][p['sell']]); amt=p['shares']*px
                cash+=amt-fee_sell(amt)
            else: still.append(p)
        positions=still
        c=be.get(d)
        if c:
            free=slots-len(positions)
            if free>0:
                n_pick=min(len(c),free,max_new)
                if n_pick<len(c):
                    jj=sorted(rng.choice(len(c),n_pick,replace=False)); picks=[c[j] for j in jj]
                else: picks=c[:n_pick]
                for (code,B,sell,cn) in picks:
                    if len(positions)>=slots: break
                    px=float(DA[code]['o'][B])
                    cap_amt = notional if frac is None else frac*(equity[-1] if equity else CAPITAL)
                    budget=min(cap_amt, cash*0.995)
                    sh=int(budget//(px*100))*100
                    if sh<=0: continue
                    amt=sh*px; bf=fee_buy(amt)
                    if amt+bf>cash: continue
                    cash-=amt+bf
                    positions.append(dict(code=code,shares=sh,B=B,sell=sell,entry_px=px,buy_fee=bf))
                    tcount[d.year]+=1
        mv=0.0
        for p in positions:
            k=DA[p['code']]['pos'].get(d)
            if k is None: k=p['B']
            mv+=p['shares']*float(DA[p['code']]['c'][k])
        equity.append(cash+mv)
    eq=np.array(equity)
    s=pd.Series(eq,index=pd.DatetimeIndex(CAL))
    ye=s.resample('YE').last()
    yearly={}; base=CAPITAL
    for ts,v in ye.items():
        yearly[int(ts.year)]=(float(v)/base-1)*100; base=float(v)
    return yearly, dict(tcount), float(eq[-1])

CONFIGS=[('6万×2',2,60000,2,None), ('8.5万×2',2,85000,2,None), ('按35%比例',2,0,2,0.353)]
RES={}
for name,slots,notional,max_new,frac in CONFIGS:
    py={y:[] for y in YRS}; ty={y:[] for y in YRS}; ends=[]
    for s in range(NSEED):
        yearly,tc,end=run_sim(slots,notional,max_new,seed=s,frac=frac)
        for y in YRS:
            py[y].append(yearly.get(y,0.0)); ty[y].append(tc.get(y,0))
        ends.append(end)
    RES[name]=dict(
        per_year={y:dict(med=round(float(np.median(py[y])),2),p5=round(float(np.percentile(py[y],5)),2),p95=round(float(np.percentile(py[y],95)),2)) for y in YRS},
        trades_per_year={y:round(float(np.median(ty[y])),1) for y in YRS},
        end=dict(med=round(float(np.median(ends)),0),p5=round(float(np.percentile(ends,5)),0),p95=round(float(np.percentile(ends,95)),0)))
    log(f"  {name}: 期末中位 {RES[name]['end']['med']} [{RES[name]['end']['p5']}~{RES[name]['end']['p95']}]")

def vlen(s): return sum(2 if ord(ch)>0x2e80 else 1 for ch in str(s))
def pad(s,w):
    s=str(s); n=w-vlen(s)
    return s+(' '*n if n>0 else ' ')
print("="*118)
print("分年度数据 · 个人口径（17 万；A2 固定55；出场=相对强弱(14) 域55/65/65 或满5日；毛收益未扣费，年收益已扣真实费用）")
print("="*118)
print(pad("年份",7)+" "+pad("触发日",7)+" "+pad("候选",7)+" "+pad("单笔毛均值%",11)+" "+pad("胜率%",7)+" "+pad("笔数",6)+" "+pad("6万×2 年收益%(中位[p5~p95])",26)+" "+pad("8.5万×2 中位",12)+" "+pad("35%比例 中位",12))
tot_days=set(); 
for y in YRS:
    r=ev_y[y]; n=r['n']
    mm=f"{r['sumr']/n*100:+.2f}" if n else "—"
    wr=f"{r['wins']/n*100:.1f}" if n else "—"
    a=RES['6万×2']['per_year'][y]; b=RES['8.5万×2']['per_year'][y]; c3=RES['按35%比例']['per_year'][y]
    print(pad(y,7)+" "+pad(len(r['days']),7)+" "+pad(n,7)+" "+pad(mm,11)+" "+pad(wr,7)+" "+pad(RES['6万×2']['trades_per_year'][y],6)
          +" "+pad(f"{a['med']:+.2f} [{a['p5']:+.2f}~{a['p95']:+.2f}]",26)
          +" "+pad(f"{b['med']:+.2f}",12)+" "+pad(f"{c3['med']:+.2f}",12))
print("-"*118)
for name in RES:
    e=RES[name]['end']
    print(f"{name}: 期末资金中位 {e['med']:.0f} 元（区间 {e['p5']:.0f}~{e['p95']:.0f}）｜全期触发日合计 {sum(len(ev_y[y]['days']) for y in YRS)} 个、候选合计 {sum(ev_y[y]['n'] for y in YRS)} 笔")
print("-"*118)
rows=[]
for y in YRS:
    r=ev_y[y]
    rows.append(dict(year=y,trigger_days=len(r['days']),candidates=r['n'],
                     mean_gross_pct=round(r['sumr']/r['n']*100,2) if r['n'] else "",
                     win_pct=round(r['wins']/r['n']*100,1) if r['n'] else "",
                     trades_med=RES['6万×2']['trades_per_year'][y],
                     ret_6w_med=RES['6万×2']['per_year'][y]['med'],ret_6w_p5=RES['6万×2']['per_year'][y]['p5'],ret_6w_p95=RES['6万×2']['per_year'][y]['p95'],
                     ret_85w_med=RES['8.5万×2']['per_year'][y]['med'],
                     ret_35pct_med=RES['按35%比例']['per_year'][y]['med']))
pd.DataFrame(rows).to_csv(os.path.join(OUT,'top1_personal_yearly_0924.csv'), index=False, encoding='utf-8-sig')
with open(os.path.join(OUT,'top1_personal_yearly_0924.json'),'w',encoding='utf-8') as fh:
    json.dump(dict(generated_at=time.strftime('%Y-%m-%d %H:%M:%S'), capital=CAPITAL, arm='A2 固定55',
                   ev_yearly={y:dict(trigger_days=len(ev_y[y]['days']),n=ev_y[y]['n'],
                                     mean_gross_pct=(ev_y[y]['sumr']/ev_y[y]['n']*100 if ev_y[y]['n'] else None),
                                     win_pct=(ev_y[y]['wins']/ev_y[y]['n']*100 if ev_y[y]['n'] else None)) for y in YRS},
                   configs=RES), fh, ensure_ascii=False, indent=1, default=str)
log("SAVED top1_personal_yearly_0924.json / .csv")
log("DONE")