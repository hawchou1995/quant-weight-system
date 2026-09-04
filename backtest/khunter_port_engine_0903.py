# -*- coding: utf-8 -*-
"""
KHunter 组合化回测引擎（2026-09-03 20:30）—— 「行情开关 + 账户熔断 + 环境化买点」三设施验证
=================================================================================
背景：现有 khunter_fusion_s1b_bear.py 是逐股独立事件（无组合 NAV），无法做组合级熔断。
本引擎把 KHunter 主信号流改造成「组合持仓流」：
  - 信号日(T-1 确认) → T 开盘建仓（等权份，每笔仓位 = 1/max_hold）
  - 卖出信号（RSI > ob, T-1 确认 → T 开盘清仓）
  - 逐日 mark-to-market 构建组合 NAV → 可叠加组合级回撤熔断
  - 可叠加行情开关（ma20/ma60/三态）与环境化买点（牛熊 RSI 阈值不同）

设计（对齐 9/2 生产口径）：
  - 主信号 = KHunter 15 信号任一命中 + 信号日 RSI < osl（生产 osl=35）
  - 卖出 = RSI > ob 独立触发（生产 ob=75）
  - 成本 1.15% 往返（0.575%×2）
  - 仓位：每笔 = 1/max_hold（最多同时在仓 max_hold 笔等权）
  - 熔断：组合 NAV 从峰值回撤 ≥ dd 触发 → 次日全部清仓 + 停止开仓；恢复 = NAV ≥ 峰值×0.97（v8 口径）或 新高

验证门：四闸(n≥30 wr≥40% mean>0 med>0) + 前后半双过(2021 split) + 分年度覆盖
"""
import os, sys, time, json, pickle
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import khunter_all_strategies_backtest as K
import khunter_timing_backtest as T

T0 = time.time()
def log(msg):
    print(f"[{time.time()-T0:7.1f}s] {msg}", flush=True)

OUT_DIR = T.OUT_DIR
COST_BUY, COST_SELL = T.COST_BUY, T.COST_SELL
BACKTEST_START = K.BACKTEST_START
SPLIT = pd.Timestamp("2021-01-01")

# ---- 常量（与生产/fusion_s1b_bear 一致）----
MAX_HOLD = 10          # 最多同时在仓 10 笔（等权）
MIN_HOLD_DAYS = 1      # 最快 1 天后可卖
RUN_CAP = None         # 调试用：限制扫描股票数（None = 全量）

def board_of(code):
    if code.startswith(("sh688", "sh689")): return "star"
    if code.startswith("sz30"): return "gem"
    if code.startswith(("sh60", "sz00", "sz002")): return "main"
    return None

def load_market_state():
    """hs300 状态（严格 T-1）：is_bear(MA60)/bull_ma20/bull_ma40/mom20(动量)/regime 三态"""
    idx = pd.read_csv(r"D:\Documents\Workbuddy\股票基金\quant-weight-system\index_000300.csv")
    idx['date'] = pd.to_datetime(idx['date'])
    idx = idx.sort_values('date').reset_index(drop=True)
    for maw in (20, 40, 60):
        idx[f'ma{maw}'] = idx['close'].rolling(maw, min_periods=1).mean()
    idx['mom20'] = idx['close'].pct_change(20)
    idx['is_bear'] = idx['close'] < idx['ma60']
    idx['bull_ma20'] = idx['close'] > idx['ma20']
    idx['bull_ma40'] = idx['close'] > idx['ma40']
    # 严格 T-1 状态
    state_prev = {}
    prev = None
    for dt in sorted(idx['date']):
        state_prev[dt] = prev if prev is not None else {'is_bear': True, 'bull_ma20': False, 'bull_ma40': False, 'mom20': 0.0}
        row = idx.loc[idx['date'] == dt]
        prev = {'is_bear': bool(row['is_bear'].iloc[0]),
                'bull_ma20': bool(row['bull_ma20'].iloc[0]),
                'bull_ma40': bool(row['bull_ma40'].iloc[0]),
                'mom20': float(row['mom20'].iloc[0]) if not pd.isna(row['mom20'].iloc[0]) else 0.0}
    return idx, state_prev

def build_sig_cache(cache, board_only=None, cache_file=None, st_skip=True):
    """预计算每只股票的 sig_any（15 信号任一命中）+ rsi1（RSI 前一日）—— 主信号候选
    返回 {code: (dates[np.ndarray], sig_any[np.ndarray bool], rsi1[np.ndarray], opens, closes)}
    cache_file: 持久化路径（避免多次 130s 重建）
    st_skip: 剔除 ST/退市股（与生产 build_short_pool.py 第520行一致：名称含 ST/退/首字母S 或 close≤1.5）"""
    if cache_file and os.path.exists(cache_file):
        log(f"加载信号缓存 {cache_file} ...")
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    # 名称表（ST 过滤用，与生产目录一致）
    try:
        import json as _json
        _names = _json.load(open(r"D:\Documents\Workbuddy\股票基金\quant-weight-system\data_full_names.json"))
    except Exception:
        _names = {}
    out = {}
    n_stock = 0
    for code, df in cache.items():
        if df is None or len(df) < 70:
            continue
        if board_only and board_of(code) != board_only:
            continue
        if st_skip:
            _nm = _names.get(code, code)
            if "ST" in _nm or _nm.startswith("S") or "退" in _nm:
                continue
            _px = df['close'].iloc[-1] if len(df) else 0
            if _px is not None and _px <= 1.5:
                continue
        d = df[['open', 'high', 'low', 'close', 'volume']].copy()
        d.index.name = None
        d['date'] = d.index
        d = d.sort_values('date').reset_index(drop=True)
        try:
            r = T.prep(d)
        except Exception:
            continue
        sig_any = np.zeros(len(d), dtype=bool)
        for name, fn in K.SIGNALS.items():
            try:
                sv = fn(r)
            except Exception:
                continue
            if not sv.any():
                continue
            sig_any |= sv.values
        cand = np.zeros(len(d), dtype=bool)
        cand[1:] = sig_any[:-1]
        cand &= d['date'].values >= BACKTEST_START
        rsi1 = r['rsi'].shift(1).fillna(99).values
        out[code] = {'dates': d['date'].values, 'open': d['open'].values,
                     'close': d['close'].values, 'cand': cand, 'rsi1': rsi1}
        n_stock += 1
        if RUN_CAP and n_stock >= RUN_CAP:
            break
    log(f"信号缓存构建完成: {n_stock} 只（ST 过滤 {'开' if st_skip else '关'}）")
    if cache_file:
        with open(cache_file, 'wb') as f:
            pickle.dump(out, f)
        log(f"已保存信号缓存 {cache_file}")
    return out

def run_khunter_port(sigs, state_prev, ob, osl, gate='none', dd=None, env='uniform',
                     mom_thr=0.02, env_delta=5, max_hold=MAX_HOLD, board_only=None,
                     stop_loss=None, hold_max=None, low_price=None,
                     ob_bull=None, osl_bull=None, low_bull=None, util_track=False):
    """util_track: True 时 nav_series 每项追加 'invested'/'npos'（当日已投入市值/持仓数）供资金利用率统计"""
    """组合化 KHunter 主信号回测（单配置）：
    gate: 'none'/'ma20'/'ma40'/'ma60'/'bear60'/'tristate'/'hybrid'
          （hybrid=牛熊分域：牛市需 MA20 上方才开仓，熊市全开——对齐 9/1 铁律「牛熊权重向量完全独立」）
    dd: None / 0.10 / 0.15 / 0.20（组合回撤熔断）
    env: 'uniform'（牛熊统一阈值）/ 'split'（牛熊分域买点：熊市 osl+env_delta 放宽）
    mom_thr: 三态动量阈值（强牛>mom_thr）
    stop_loss: None / 0.08（逐笔止损：当日收盘价相对 entry_px 回撤 ≥ stop_loss → 次日开盘卖出）
    hold_max: None / N（持有上限：超过 N 个交易日 → 次日开盘卖出）
    low_price: None / 3.0（低价过滤：确认日收盘 ≥ low_price，与生产 KHUNTER_LOW_PRICE 同口径）
    ob_bull/osl_bull/low_bull: 牛市分域覆盖（None=用统一值）；熊市用 ob/osl/low_price
    """
    ob_bull = ob_bull if ob_bull is not None else ob
    osl_bull = osl_bull if osl_bull is not None else osl
    low_bull = low_bull if low_bull is not None else low_price
    all_dates = sorted({pd.Timestamp(dt) for s in sigs.values() for dt in s['dates']})
    all_dates = [d for d in all_dates if BACKTEST_START <= d]
    # 状态对齐
    st = {}
    for d in all_dates:
        st[d] = state_prev.get(d, {'is_bear': True, 'bull_ma20': False, 'bull_ma40': False, 'mom20': 0.0})

    # 事件流构建：date -> [(code, rsi1, close)] 按最宽松阈值收集，执行期按 regime 精筛
    buys = {}   # date -> [(code, rsi1, close)]
    sells = {}  # date -> [(code, rsi1)]
    osl_loose = max(osl, osl_bull) + env_delta   # 收集宽松上限（执行期精筛）
    ob_loose = min(ob, ob_bull)                  # 收集宽松下限（执行期精筛）
    for code, s in sigs.items():
        for i in range(len(s['dates'])):
            dt = pd.Timestamp(s['dates'][i])
            if dt < BACKTEST_START:
                continue
            if s['cand'][i] and s['rsi1'][i] < osl_loose:
                buys.setdefault(dt, []).append((code, s['rsi1'][i], s['close'][i]))
            if s['rsi1'][i] > ob_loose:
                sells.setdefault(dt, []).append((code, s['rsi1'][i]))

    # 组合模拟（真实资金记账：现金驱动 + 分数股持仓）
    # 关键：仓位是「当前 NAV 的 1/max_hold」，现金扣减 = size*(1+COST_BUY)，现金永不超支（无杠杆）
    holdings = {}    # code -> {'shares': 分数股数, 'entry_px': 含费买入价, 'entry_dt': dt}
    cash = 1.0       # 现金
    last_nav = 1.0   # 上一交易日 NAV（用于下注定仓）
    peak = 1.0
    circuit = False
    circuit_dt = None
    nav_series = []
    trade_log = []
    for di, d in enumerate(all_dates):
        st_d = st[d]
        # ---- 熔断清仓（触发后次日开盘强制平仓）----
        if circuit and len(holdings):
            for code, h in list(holdings.items()):
                s = sigs[code]
                i = np.where(s['dates'] == d)[0]
                if len(i) > 0 and i[0] > 0:
                    px = s['open'][i[0]] if s['open'][i[0]] > 0 else s['close'][i[0]]
                    if px > 0:
                        ret = px * (1 - COST_SELL) / h['entry_px'] - 1
                        cash += h['shares'] * px * (1 - COST_SELL)
                        trade_log.append({'code': code, 'entry': str(h['entry_dt'].date()), 'exit': str(d.date()),
                                          'ret': ret})
                        del holdings[code]
        # ---- 执行卖出（开盘）----
        # ① 止损触发（收盘检查昨日 → 开盘执行）
        if stop_loss is not None:
            for code, h in list(holdings.items()):
                if h.get('stop_flg'):
                    s = sigs[code]
                    i = np.where(s['dates'] == d)[0]
                    if len(i) > 0:
                        px = s['open'][i[0]] if s['open'][i[0]] > 0 else s['close'][i[0]]
                        if px > 0:
                            hh = holdings.pop(code)
                            ret = px * (1 - COST_SELL) / hh['entry_px'] - 1
                            cash += hh['shares'] * px * (1 - COST_SELL)
                            trade_log.append({'code': code, 'entry': str(hh['entry_dt'].date()), 'exit': str(d.date()),
                                              'ret': ret, 'reason': f'stop{int(stop_loss*100)}'})
        # ② 持有上限到期（次日开盘卖出）
        if hold_max is not None:
            for code, h in list(holdings.items()):
                if h.get('hold_over'):
                    s = sigs[code]
                    i = np.where(s['dates'] == d)[0]
                    if len(i) > 0:
                        px = s['open'][i[0]] if s['open'][i[0]] > 0 else s['close'][i[0]]
                        if px > 0:
                            hh = holdings.pop(code)
                            ret = px * (1 - COST_SELL) / hh['entry_px'] - 1
                            cash += hh['shares'] * px * (1 - COST_SELL)
                            trade_log.append({'code': code, 'entry': str(hh['entry_dt'].date()), 'exit': str(d.date()),
                                              'ret': ret, 'reason': f'hold{hold_max}'})
        # ③ 主卖出信号（RSI > ob，T-1 确认 → T 开盘卖出；牛熊分域用各自 ob）
        if sells.get(d):
            ob_eff = ob_bull if not st_d['is_bear'] else ob
            for code, rsi1 in sells[d]:
                if code not in holdings:
                    continue
                if rsi1 <= ob_eff:
                    continue
                s = sigs[code]
                i = np.where(s['dates'] == d)[0]
                if len(i) == 0:
                    continue
                px = s['open'][i[0]]
                if px > 0:
                    h = holdings.pop(code)
                    ret = px * (1 - COST_SELL) / h['entry_px'] - 1
                    cash += h['shares'] * px * (1 - COST_SELL)
                    trade_log.append({'code': code, 'entry': str(h['entry_dt'].date()), 'exit': str(d.date()),
                                      'ret': ret})
        # ---- 执行买入（开盘）----
        if buys.get(d) and not circuit and len(holdings) < max_hold:
            # 行情开关
            g_ok = True
            size_scale = 1.0
            if gate == 'ma20': g_ok = st_d['bull_ma20']
            elif gate == 'ma40': g_ok = st_d['bull_ma40']
            elif gate == 'ma60': g_ok = not st_d['is_bear']
            elif gate == 'bear60': g_ok = st_d['is_bear']   # 生产 B1：熊市（hs300<MA60）才开仓
            elif gate == 'hybrid':
                # 牛熊分域：牛市需 MA20 上方才开仓；熊市全开（MA60 下方 == 熊）
                g_ok = (not st_d['is_bear'] and st_d['bull_ma20']) or st_d['is_bear']
            elif gate == 'tristate':
                # 三态：强牛(mom20>thr 且 >MA20)=满仓；弱牛(>MA20 但动量不足)=减半仓；熊市=不开
                if st_d['bull_ma20']:
                    if st_d['mom20'] > mom_thr:
                        size_scale = 1.0
                    else:
                        size_scale = 0.5
                else:
                    g_ok = False
            if g_ok:
                size_target = last_nav / max_hold * size_scale   # 每笔 = 当前 NAV 的 1/max_hold（现金约束内）
                for code, rsi1, close in buys[d]:
                    if code in holdings:
                        continue
                    # 牛熊分域买点：牛市 osl_bull（+低价 low_bull），熊市 osl 或 env=split 放宽 osl+delta（+低价 low_price）
                    is_bear = st_d['is_bear']
                    if is_bear:
                        lim = osl if rsi1 < osl else (osl + env_delta if env == 'split' else None)
                        lp = low_price
                    else:
                        lim = osl_bull if rsi1 < osl_bull else None
                        lp = low_bull
                    if lim is None:
                        continue
                    if lp is not None and close < lp:
                        continue
                    s = sigs[code]
                    i = np.where(s['dates'] == d)[0]
                    if len(i) == 0:
                        continue
                    px = s['open'][i[0]]
                    if px > 0:
                        cost = size_target * (1 + COST_BUY)
                        if cash >= cost:
                            shares = size_target / px
                            holdings[code] = {'shares': shares, 'entry_px': px * (1 + COST_BUY), 'entry_dt': d,
                                              'entry_i': i[0]}
                            cash -= cost
                    if len(holdings) >= max_hold:
                        break
        # ---- 逐日 mark-to-market ----
        nav = cash
        invested = 0.0
        for code, h in holdings.items():
            s = sigs[code]
            i = np.where(s['dates'] == d)[0]
            if len(i) > 0:
                px = s['close'][i[0]]
                if px > 0:
                    invested += h['shares'] * px
                    nav += h['shares'] * px
                    # 收盘检查：止损触发（相对 entry_px 回撤 ≥ stop_loss）
                    if stop_loss is not None:
                        drawdown = px / h['entry_px'] - 1
                        if drawdown <= -stop_loss:
                            h['stop_flg'] = True
                    # 收盘检查：持有上限到期（距 entry_i ≥ hold_max 个交易日）
                    if hold_max is not None and (i[0] - h['entry_i']) >= hold_max:
                        h['hold_over'] = True
        last_nav = nav
        if util_track:
            nav_series.append({'date': d, 'nav': nav, 'invested': invested, 'npos': len(holdings)})
        else:
            nav_series.append({'date': d, 'nav': nav})
        # ---- 熔断检查（收盘）----
        if dd is not None:
            if nav > peak:
                peak = nav
            if not circuit and (nav / peak - 1) < -dd:
                circuit = True
                circuit_dt = d
                log(f"    [熔断] {d.date()} dd={dd} nav={nav:.3f} peak={peak:.3f}")
            # 恢复：空仓后市场转多（MA20 上方）→ 重新开仓
            if circuit and st_d['bull_ma20']:
                circuit = False
                peak = nav
                log(f"    [恢复] {d.date()} 市场转多，重新开仓")
    # 期末平仓
    for code, h in holdings.items():
        s = sigs[code]
        i = len(s['dates']) - 1
        px = s['close'][i]
        ret = px * (1 - COST_SELL) / h['entry_px'] - 1
        trade_log.append({'code': code, 'entry': str(h['entry_dt'].date()), 'exit': str(s['dates'][i]),
                          'ret': ret})
    return nav_series, trade_log

def nav_stats(nav_series, trade_log):
    """组合级统计：总收益/年化/最大回撤/夏普（基于 NAV）+ 四闸字段（基于逐笔）"""
    nav = pd.DataFrame(nav_series).set_index('date')
    fr = np.array([t['ret'] for t in trade_log])
    if len(fr) == 0 or len(nav) == 0:
        return None
    total = nav['nav'].iloc[-1] / nav['nav'].iloc[0] - 1
    days = (nav.index[-1] - nav.index[0]).days
    ann = (1 + total) ** (365.25 / max(days, 1)) - 1
    rets = nav['nav'].pct_change().dropna()
    sharp = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
    peak = nav['nav'].cummax()
    maxdd = (nav['nav'] / peak - 1).min()
    wr = (fr > 0).mean() * 100
    med = np.median(fr) * 100
    mean = fr.mean() * 100
    return {'n': len(fr), 'wr': round(wr, 2), 'med': round(med, 3), 'mean': round(mean, 3),
            'total': round(total * 100, 2), 'ann': round(ann * 100, 2), 'sharpe': round(sharp, 3),
            'maxdd': round(maxdd * 100, 2)}

def full_gate(nav_series, trade_log, split=SPLIT):
    """四闸 + 前后半双过（按入场日期 split，不是按交易数切片）"""
    st = nav_stats(nav_series, trade_log)
    if st is None:
        return None, None, None, None
    h1 = [t for t in trade_log if pd.Timestamp(t['entry']) < split]
    h2 = [t for t in trade_log if pd.Timestamp(t['entry']) >= split]
    s1 = nav_stats(nav_series, h1) if len(h1) >= 8 else None
    s2 = nav_stats(nav_series, h2) if len(h2) >= 8 else None
    ok = (st['n'] >= 30 and st['wr'] >= 40 and st['mean'] > 0 and st['med'] > 0)
    ok_half = (s1 and s2 and s1['med'] > 0 and s2['med'] > 0) if (s1 and s2) else False
    return st, s1, s2, {'pass': ok, 'pass_half': ok_half}

if __name__ == "__main__":
    log("加载缓存 ...")
    cache = pd.read_pickle(K.CACHE)
    log(f"缓存 {len(cache)} 只")
    idx, state_prev = load_market_state()
    # 主板限定（用户只能买主板）
    sigs = build_sig_cache(cache, board_only='main')
    log(f"主板信号缓存 {len(sigs)} 只")
    # 基线复现：ob75/osl35/gate=none/dd=None
    nav_series, trade_log = run_khunter_port(sigs, state_prev, 75, 35, gate='none', dd=None, env='uniform')
    st, s1, s2, gates = full_gate(nav_series, trade_log)
    print(f"基线 ob75/osl35/none: {st}")
    if st:
        nav = pd.DataFrame(nav_series).set_index('date')['nav']
        print(f"  NAV 检查: 最后={nav.iloc[-1]:.3f} min={nav.min():.3f} max={nav.max():.3f} (min 必须 > 0)")
    else:
        print("  基线交易为空")
    print(f"  前半: {s1 if s1 else None}")
    print(f"  后半: {s2 if s2 else None}")
    print(f"  四闸: {gates}")
