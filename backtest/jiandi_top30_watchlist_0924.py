# -*- coding: utf-8 -*-
"""
《见底信号》共振 · 触发日信号排序清单 v2（笔数与金额由使用者决定）
规则：主板；某日同时出现六个分项中 >=2 个 = 共振；当日全市场共振家数 >=30 = 触发日。
清单排序：共振分项数 多→少；同分项数按成交额/代码。
买入 = 信号次一交易日开盘；出场 = 相对强弱指标(14) 域55/65/65 或满 5 个交易日（次日开盘卖）。
用法：
  python jiandi_top30_watchlist_0924.py                # 最新状态（自动定位最近触发日）
  python jiandi_top30_watchlist_0924.py --date 2026-08-04
  python jiandi_top30_watchlist_0924.py --last 8 --top 60 --min-cnt 2
输出：控制台 + jiandi_top_grid_0924_out/jiandi_signals_ranked_0924.csv（utf-8-sig）
"""
import os, sys, time, json, argparse
from collections import defaultdict
import numpy as np, pandas as pd

T0=time.time()
def log(m): print(f"[{time.time()-T0:5.1f}s] {m}", flush=True)
BASE = r'D:\Documents\Workbuddy\股票基金\quant-weight-system'
BK = os.path.join(BASE,'backtest'); OUT = os.path.join(BK,'jiandi_top_grid_0924_out')
sys.path.insert(0, BK)
W_LO, W_HI = pd.Timestamp('2016-06-01'), pd.Timestamp('2026-09-23')
BS = W_LO; THETA=30; HOLD=5
SUBS = [('rushi','入市'),('jihui','机会'),('jiandi','见底'),('kuaixian','穿20'),('laiLin','穿25'),('deng','穿30')]
THR_A3 = {0:55,1:65,2:65}
import jiandi_signal_0906 as JG

ap = argparse.ArgumentParser()
ap.add_argument('--date', default=None)
ap.add_argument('--last', type=int, default=8)
ap.add_argument('--min-cnt', type=int, default=2)
ap.add_argument('--top', type=int, default=60)
a = ap.parse_args()

def vlen(s): return sum(2 if ord(ch)>0x2e80 else 1 for ch in str(s))
def pad(s, w):
    s=str(s); n=w-vlen(s)
    return s+(' '*n if n>0 else ' ')
def famt(v):
    if v is None: return "—"
    if v >= 1e8: return f"{v/1e8:.1f}亿"
    if v >= 1e4: return f"{v/1e4:.0f}万"
    return f"{v:.0f}"

idx = pd.read_csv(os.path.join(BASE,'index_000300.csv'))
idx['date']=pd.to_datetime(idx['date']); idx=idx.sort_values('date').reset_index(drop=True)
for maw in (20,60): idx[f'ma{maw}']=idx['close'].rolling(maw,min_periods=1).mean()
CAL=[d for d in idx['date'] if W_LO<=d<=W_HI]
cal_pos={d:i for i,d in enumerate(CAL)}
last_cal = CAL[-1]

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
NAMES = json.load(open(os.path.join(BASE,'data_full_names.json'), encoding='utf-8'))

amt_key=None; res_daily=defaultdict(int); n_bad_excl=defaultdict(int)
CAND=defaultdict(list)
for code,df in cache.items():
    if len(df)<70: continue
    sm=JG.jiandi_signals(code,df)
    sig=[np.asarray(sm[k],bool) for k,_ in SUBS]
    cnt=np.sum(sig,axis=0)
    if not (cnt>=2).any(): continue
    o=df['open'].to_numpy(); c=df['close'].to_numpy()
    if amt_key is None:
        amt_key = 'amount' if any(str(x).lower()=='amount' for x in df.columns) else 'NONE'
        log(f"量列={amt_key}（缓存列共 {len(df.columns)} 个）")
    amtv=None; volv=None
    for cc in df.columns:
        if str(cc).lower()=='amount': amtv=df[cc].to_numpy()
        if str(cc).lower()=='volume': volv=df[cc].to_numpy()
    bad=(~np.isfinite(o))|(~np.isfinite(c))|(o<=0)|(c<=0)
    dates=df.index; n=len(df)
    rsi=rsiN(df['close'],14)
    for i in np.where(cnt>=2)[0]:
        sd=dates[i]
        if sd<BS or sd not in cal_pos: continue
        if bad[i]:
            n_bad_excl[sd]+=1; continue
        res_daily[sd]+=1
        CAND[sd].append(dict(code=code,i=i,cnt=int(cnt[i]),
                             subs=[lab for (k,lab),fl in zip(SUBS,sig) if fl[i]],
                             close=float(c[i]),
                             amt=(float(amtv[i]) if amtv is not None and np.isfinite(amtv[i]) else None),
                             vol=(float(volv[i]) if volv is not None and np.isfinite(volv[i]) else None),
                             o=o,c=c,dates=dates,rsi=rsi,bad=bad,n=n))
log(f"已剔除 0 价污染候选 {sum(n_bad_excl.values())} 个")

def replay(c):
    o=c['o']; cc=c['c']; dts=c['dates']; rsi=c['rsi']; bad=c['bad']; i=c['i']; n=c['n']
    B=i+1
    if B>=n or bad[B]: return None
    sell=min(B+HOLD,n-1)
    for d in range(B,min(B+HOLD,n)):
        st=reg_fn(dts[d]); thr=THR_A3.get(st if st is not None else 0,55)
        if np.isfinite(rsi[d]) and rsi[d]>=thr:
            sell=min(d+1,B+HOLD); break
    if sell<=B or sell>=n: return None
    w=slice(B,sell+1)
    if not (np.isfinite(o[w]).all() and np.isfinite(cc[w]).all() and (o[w]>0).all() and (cc[w]>0).all()): return None
    return dict(buy=dts[B],bpx=float(o[B]),sell=dts[sell],spx=float(o[sell]),ret=(float(o[sell])/float(o[B])-1)*100)

def ranked(sd, mincnt=2):
    cs=[c for c in CAND.get(sd,[]) if c['cnt']>=mincnt]
    cs.sort(key=lambda x:(-x['cnt'], -(x['amt'] or 0.0), x['code']))
    return cs

trig=sorted([d for d,v in res_daily.items() if v>=THETA])
if not trig: log("无触发日"); sys.exit()
if a.date:
    tgt=pd.Timestamp(a.date)
    if tgt not in set(trig): log(f"⚠ {tgt.date()} 非触发日（共振家数 {res_daily.get(tgt,0)}）——仍输出当日清单")
else:
    tgt=trig[-1]
log(f"触发日共 {len(trig)} 个（最近 = {tgt.date()}）")
s0=ranked(tgt)[0] if ranked(tgt) else None
if s0 and s0['amt'] and s0['vol']:
    r=s0['amt']/(s0['close']*s0['vol'])
    log(f"成交额单位校验：{s0['code']} amount={s0['amt']:.4g} vol={s0['vol']:.4g} close={s0['close']} → amount/(close*vol)={r:.4f}")

print("="*112)
print("《见底信号》共振 · 触发日信号清单（只列信号；买几只、各买多少钱 = 由你决定）")
print(f"数据截至 {last_cal.date()} ｜ 触发阈值：当日共振家数 ≥ {THETA} ｜ 宇宙：沪深主板")
print("排序：共振分项数 多→少（同分项数按成交额）｜ 买入=信号次一交易日开盘 ｜ 出场=相对强弱(14) 域55/65/65 或满5日·次日开盘卖")
print("="*112)
print("近 15 个交易日共振家数：" + "  ".join(f"{str(d)[5:10]}={res_daily.get(d,0)}" for d in CAL[-15:]))
print(f"最新交易日 {last_cal.date()} {'⚠ 是触发日' if last_cal in set(trig) else '非触发日'}｜最近触发日 = {tgt.date()}（共振 {res_daily.get(tgt,0)} 家 / 候选 {len(CAND.get(tgt,[]))} 只 / 距最新交易日 {cal_pos[last_cal]-cal_pos.get(tgt,cal_pos[last_cal])} 个交易日）")
print()
print(f"—— 最近 {a.last} 个触发日 · 回放摘要（毛收益，未扣费）——")
print(pad("触发日",12)+" "+pad("共振家数",10)+" "+pad("候选",6)+" "+pad("≥3分项",8)+" "+pad("前2只均值%",12)+" "+pad("全池均值%",10))
for d in trig[-a.last:]:
    cs=ranked(d)
    p2=[replay(c) for c in cs[:2]]; pall=[replay(c) for c in cs]
    v1=[r['ret'] for r in p2 if r]; v2=[r['ret'] for r in pall if r]
    print(pad(str(d.date()),12)+" "+pad(res_daily.get(d,0),10)+" "+pad(len(cs),6)+" "+pad(sum(1 for c in cs if c['cnt']>=3),8)
          +" "+pad(f"{np.mean(v1):+.2f}" if v1 else "—",12)+" "+pad(f"{np.mean(v2):+.2f}" if v2 else "—",10))
print()
cs_show=ranked(tgt, a.min_cnt)
dist={k:sum(1 for c in CAND.get(tgt,[]) if c['cnt']==k) for k in range(6,1,-1)}
print(f"—— {tgt.date()} 信号清单（分项数分布：6:{dist[6]}  5:{dist[5]}  4:{dist[4]}  3:{dist[3]}  2:{dist[2]}；显示前 {a.top} 条，全部 {len(cs_show)} 条入 CSV）——")
print(pad("序",4)+" "+pad("代码",9)+" "+pad("名称",11)+" "+pad("分项",4)+" "+pad("触发分项",30)+" "+pad("信号日收盘",10)+" "+pad("买入=次日开盘",17)+" "+pad("卖出日@价",17)+" "+pad("毛收益%",8)+" "+pad("成交额",9))
for k,c in enumerate(cs_show[:a.top],1):
    r=replay(c)
    buy_s=f"{r['buy'].date()}@{r['bpx']:.2f}" if r else "待次日开盘"
    sell_s=f"{r['sell'].date()}@{r['spx']:.2f}" if r else "—"
    ret_s=f"{r['ret']:+.2f}" if r else "—"
    nm=str(NAMES.get(c['code'],""))
    flag="·ST" if ("ST" in nm.upper() or "退" in nm) else ""
    print(pad(k,4)+" "+pad(c['code'],9)+" "+pad(nm[:5],11)+" "+pad(c['cnt'],4)+" "+pad("+".join(c['subs']),30)+" "+pad(f"{c['close']:.2f}",10)+" "+pad(buy_s,17)+" "+pad(sell_s,17)+" "+pad(ret_s,8)+" "+pad(famt(c['amt']),9)+flag)
print()
print("-"*112)
print("提示：① 清单只列信号，不替你决定笔数/金额（你的容量参考：2 笔）② 信号日=今天时，收盘后看此清单，明早开盘执行")
print("      ③ 出场两版（固定55 / 域55/65/65）长期差 <0.1pp，选一个固定用即可 ④ 数据尾部 0 价污染行已剔除")
csv_p = os.path.join(OUT,'jiandi_signals_ranked_0924.csv')
rows=[]
days = [tgt] if a.date else trig[-a.last:]
if tgt not in days: days = days+[tgt]
for d in days:
    for rk,c in enumerate(ranked(d),1):
        if c['cnt']<a.min_cnt: continue
        r=replay(c); nm=str(NAMES.get(c['code'],''))
        rows.append(dict(signal_date=str(d.date()),rank=rk,code=c['code'],name=nm,cnt=c['cnt'],
                         subs="+".join(c['subs']),close=round(c['close'],2),
                         buy_date=str(r['buy'].date()) if r else "",buy_open=round(r['bpx'],2) if r else "",
                         sell_date=str(r['sell'].date()) if r else "",sell_px=round(r['spx'],2) if r else "",
                         ret_gross_pct=round(r['ret'],2) if r else "",amount_raw=c['amt'] if c['amt'] is not None else ""))
pd.DataFrame(rows).to_csv(csv_p, index=False, encoding='utf-8-sig')
log(f"CSV 已写：{csv_p}（{len(rows)} 行，{len(days)} 个触发日）")
log("DONE")